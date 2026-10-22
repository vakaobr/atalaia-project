// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Android props on the phone controller's Wi-Fi (slice S4 of PE24,
/// protocol/prop-link.md): the server side of `WS /api/v1/prop`, as the Pi
/// controller's prop_link.py. A prop that joined a game holds the game's
/// id, key and its node id; it proves it holds the key with an HMAC-SHA256
/// over a fresh challenge, then takes part as a box does over the radio:
///
///     prop -> controller   hello, state, event (the payloads' fields as JSON), ping
///     controller -> prop   welcome, time (TIME beacons), cmd (CMD), ack, error, pong, replaced
///
/// Each message is encoded with the radio's codecs (rf_codec.dart, the
/// core's event codec) and handed to the engine as a packet from that node,
/// so the node list, the score merge and the log's duplicate check are the
/// radio's. The controller's TIME beacons and commands reach the linked
/// props as well as the radio (the engine's [ControllerEngine.wifiForward]).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import '../core/node_types.dart';
import '../radio/rf_codec.dart';
import 'controller_engine.dart';
import 'field_controller.dart';
import 'prop_link.dart' show propLinkProof;

const propNonceSize = 32;
const propAuthTimeout = Duration(seconds: 10);

String _b64(List<int> b) => base64Url.encode(b).replaceAll('=', '');

List<int>? _unb64(Object? text) {
  if (text is! String || text.length > 64) return null;
  try {
    return base64Url.decode(text.padRight((text.length + 3) ~/ 4 * 4, '='));
  } on FormatException {
    return null;
  }
}

bool _sameBytes(List<int> a, List<int> b) {
  if (a.length != b.length) return false;
  var diff = 0;
  for (var i = 0; i < a.length; i++) {
    diff |= a[i] ^ b[i];
  }
  return diff == 0;
}

class _Link {
  _Link(this.nodeId, this.gameId, this.socket);
  final int nodeId;
  final int gameId;
  final WebSocket socket;
  var closed = false;

  void put(Map<String, Object?> msg) {
    if (!closed) socket.add(jsonEncode(msg));
  }

  Future<void> close(int code) async {
    if (closed) return;
    closed = true;
    await socket.close(code);
  }
}

class PropLinks {
  PropLinks(this.engine, {Random? random})
    : _random = random ?? Random.secure() {
    engine.wifiForward = forward;
  }

  final ControllerEngine engine;
  final Random _random;
  final _links = <int, _Link>{};
  final _seq = <int, int>{};

  /// The node ids linked now.
  List<int> get linked => _links.keys.toList()..sort();

  static final _opcodeNames = {
    for (final e in cmdOpcodes.entries) e.value: e.key,
  };

  // --- controller -> props -----------------------------------------------

  /// A packet the controller sends: TIME and CMD go to the linked props
  /// too. True when one of them got it.
  bool forward(int type, Uint8List payload) {
    if (_links.isEmpty) return false;
    if (type == RfType.time) {
      final RfTime t;
      try {
        t = RfTime.decode(payload);
      } on RfException {
        return false;
      }
      final msg = {
        'type': 'time',
        'game_time_ms': t.gameTimeMs,
        'game_state': t.gameState,
        'duration_ms': t.durationMs,
        'wall_s': t.wallS,
        'term': t.term,
        if (t.txTimeUs != null) 'tx_time_us': t.txTimeUs,
        'state': t.stateName,
      };
      for (final l in _links.values) {
        l.put(msg);
      }
      return true;
    }
    if (type == RfType.cmd) {
      final RfCmd c;
      try {
        c = RfCmd.decode(payload);
      } on RfException {
        return false;
      }
      var sent = false;
      for (final l in _links.values) {
        if (c.dest == null || c.dest == l.nodeId) {
          l.put({
            'type': 'cmd',
            'cmd': _opcodeNames[c.cmd] ?? '${c.cmd}',
            'opcode': c.cmd,
            'params': c.params ?? const <String, Object?>{},
            'dest': c.dest,
          });
          sent = true;
        }
      }
      return sent;
    }
    return false;
  }

  Map<String, Object?>? _timeNow() {
    final g = engine.liveGame;
    if (g == null || engine.keyLost) return null;
    final status = engine.status();
    final game = engine.getGame(g['id']! as int);
    final state = switch (g['state']) {
      'running' => 1,
      'paused' => 2,
      'ended' => 3,
      _ => 0,
    };
    return {
      'type': 'time',
      'game_time_ms': game['game_time_ms'],
      'game_state': state,
      'state': rfGameStates[state],
      'duration_ms': g['duration_ms'],
      'term': status['term'],
    };
  }

  // --- props -> controller -----------------------------------------------

  void _deliver(_Link link, int type, Uint8List payload, int prio) {
    final g = engine.liveGame;
    if (g == null || g['id'] != link.gameId || engine.keyLost) {
      throw const FormatException('the game is no longer live here');
    }
    final seq = (_seq[link.nodeId] ?? 0) % 0x10000;
    _seq[link.nodeId] = seq + 1;
    engine.onPacket(
      RfHeader(
        // Version 1, the priority, no ACK requested, the encrypted bit.
        versionFlags: 1 << 5 | (prio & 3) << 3 | 1 << 1,
        gameId: link.gameId,
        source: link.nodeId,
        seq: seq,
        hopLimit: 0,
        type: type,
      ),
      payload,
    );
  }

  static int _need(Map<String, Object?> m, String key) {
    final v = m[key];
    if (v is! int) throw FormatException('$key: an integer');
    return v;
  }

  /// One message from a prop; the answer to send back, if any. Throws
  /// [FormatException] to refuse it (answered with an error).
  Map<String, Object?>? _handle(_Link link, Object? msg) {
    if (msg is! Map<String, Object?>) {
      throw const FormatException('a message is a JSON object');
    }
    switch (msg['type']) {
      case 'ping':
        return {'type': 'pong'};
      case 'hello':
        final caps = msg['capabilities'];
        final RfHello h;
        try {
          h = RfHello(
            nodeName: '${msg['node_name'] ?? ''}',
            platform: (msg['platform'] as int?) ?? 3, // android
            fwVersion: '${msg['fw_version'] ?? ''}',
            coreVersion: '${msg['core_version'] ?? ''}',
            tier: (msg['tier'] as int?) ?? 0,
            capabilities: caps is List ? caps.cast<int>() : const [],
            transports: (msg['transports'] as int?) ?? RfTransport.wifi,
            batteryPct: msg['battery_pct'] as int?,
            epoch: 0,
          );
        } on TypeError {
          throw const FormatException('hello: fields of the wrong type');
        }
        _deliver(link, RfType.hello, _encoded(h.encode), RfPrio.normal);
        return null;
      case 'state':
        final counters = <int, int>{};
        final c = msg['counters'];
        if (c is Map) {
          c.forEach((k, v) {
            final team = int.tryParse('$k');
            if (team != null && v is int) counters[team] = v;
          });
        }
        final st = RfState(
          ownerTeam: _need(msg, 'owner_team'),
          phase: _need(msg, 'phase'),
          gameTimeMs: _need(msg, 'game_time_ms'),
          counters: counters,
          batteryPct: msg['battery_pct'] as int?,
          flags: msg['flags'] as int?,
          epoch: 0,
        );
        _deliver(link, RfType.state, _encoded(st.encode), RfPrio.telemetry);
        return null;
      case 'event':
        final ev = msg['event'];
        if (ev is! Map<String, Object?>) {
          throw const FormatException('event: an object');
        }
        final core = engine.core;
        if (core == null) {
          throw const FormatException('the core library is not loaded');
        }
        final type = ev['type'];
        if (type is! String) throw const FormatException('event: type');
        final prioName = ev['prio'];
        final prio = prioName == null
            ? (core.eventDefaultPrio(type) ?? RfPrio.normal)
            : prioNames.indexOf('$prioName');
        if (prio < 0) throw FormatException('unknown priority $prioName');
        final data = ev['data'];
        if (data != null && data is! Map<String, Object?>) {
          throw const FormatException('event: data is an object');
        }
        final problems = core.eventSchemaProblems(
          type,
          (data as Map<String, Object?>?) ?? const {},
        );
        if (problems.isNotEmpty) throw FormatException(problems.join('; '));
        final encoded = core.encodeEvent(
          node: link.nodeId,
          seq: _need(ev, 'seq'),
          tMs: _need(ev, 't'),
          type: type,
          team: (ev['team'] as int?) ?? 0,
          squad: (ev['squad'] as int?) ?? 0,
          prio: prio,
          dataJson: data != null && data.isNotEmpty ? jsonEncode(data) : null,
        );
        final bytes = encoded.bytes;
        if (bytes == null) {
          throw FormatException(encoded.error ?? 'the event was refused');
        }
        _deliver(link, RfType.event, bytes, prio);
        return {'type': 'ack', 'seq': ev['seq'], 'event_type': type};
    }
    throw FormatException('unknown message type ${jsonEncode(msg['type'])}');
  }

  static Uint8List _encoded(Uint8List Function() encode) {
    try {
      return encode();
    } on RfException catch (e) {
      throw FormatException(e.message);
    }
  }

  // --- the WebSocket -----------------------------------------------------

  /// WS /api/v1/prop: challenge, proof, then the link (close codes: 4401
  /// refused, 4409 replaced).
  Future<void> serve(WebSocket socket) async {
    final nonce = [
      for (var i = 0; i < propNonceSize; i++) _random.nextInt(256),
    ];
    socket.add(
      jsonEncode({'type': 'challenge', 'nonce': _b64(nonce), 'version': 1}),
    );
    final incoming = StreamIterator(socket);
    Object? auth;
    try {
      if (await incoming.moveNext().timeout(propAuthTimeout)) {
        auth = jsonDecode('${incoming.current}');
      }
    } on Object {
      auth = null;
    }
    final link = _authenticate(auth, nonce, socket);
    if (link == null) {
      socket.add(jsonEncode({'type': 'refused', 'reason': 'auth'}));
      await socket.close(4401);
      await incoming.cancel();
      return;
    }
    final old = _links[link.nodeId];
    _links[link.nodeId] = link;
    if (old != null) {
      old.put({'type': 'replaced'});
      await old.close(4409);
    }
    link.put({
      'type': 'welcome',
      'game_id': link.gameId,
      'node_id': link.nodeId,
      'controller_id': engine.nodeId,
      'time': _timeNow(),
    });
    try {
      while (await incoming.moveNext()) {
        Object? msg;
        Map<String, Object?>? answer;
        try {
          msg = jsonDecode('${incoming.current}');
          answer = _handle(link, msg);
        } on FormatException catch (e) {
          final ev = msg is Map ? msg['event'] : null;
          answer = {
            'type': 'error',
            'message': e.message.length > 200
                ? e.message.substring(0, 200)
                : e.message,
            'seq': ev is Map ? ev['seq'] : null,
          };
        } on ControllerError catch (e) {
          answer = {'type': 'error', 'message': e.message, 'seq': null};
        }
        if (answer != null) link.put(answer);
      }
    } on Object {
      // A socket that fails ends the link, as one that closes.
    } finally {
      link.closed = true;
      if (identical(_links[link.nodeId], link)) _links.remove(link.nodeId);
    }
  }

  _Link? _authenticate(Object? auth, List<int> nonce, WebSocket socket) {
    if (auth is! Map || auth['type'] != 'auth') return null;
    final gameId = auth['game_id'];
    final nodeId = auth['node_id'];
    if (gameId is! int || nodeId is! int || nodeId < 1 || nodeId > 0xfffe) {
      return null;
    }
    final g = engine.liveGame;
    if (g == null || g['id'] != gameId || engine.keyLost) return null;
    final assignments = (g['assignments'] as Map?) ?? const {};
    if (nodeId == engine.nodeId || !assignments.containsKey('$nodeId')) {
      return null;
    }
    final got = _unb64(auth['proof']);
    if (got == null ||
        !_sameBytes(
          got,
          propLinkProof(engine.gameKey, nonce, gameId, nodeId),
        )) {
      return null;
    }
    return _Link(nodeId, gameId, socket);
  }

  /// The Android props linked now.
  int get count => _links.length;

  /// Ends every link (the controller stops).
  Future<void> close() async {
    for (final l in _links.values.toList()) {
      await l.close(1001);
    }
    _links.clear();
    engine.wifiForward = null;
  }
}
