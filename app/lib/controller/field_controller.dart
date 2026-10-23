// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The radio side of a game on the Android field controller (ADR-P3-12,
/// decision PE24): the Dart counterpart of the simulator's FieldController
/// (simulator/atalaia_sim/field_controller.py), which the Pi controller runs.
///
/// It keeps what the controller decides about a game, whatever carries the
/// packets: the game state and clock, TIME beacons, commands, the nodes heard
/// (HELLO, STATE), their events with replays dropped, ACKs, scores merged by
/// maximum per node, the controller's own events (GM adjustments, field.lua)
/// and node health (node.online, node.offline, battery.low). Packets reach it
/// decrypted ([onPacket]); what it sends goes to a [FieldTransport] (the I/O
/// pod's radio and the Wi-Fi props, slice S4 of PE24).
///
/// Not here yet (PE24 slice S7): the CLAIM election and TIME from another
/// controller. This controller is always in charge, term 1 unless told.
library;

import 'dart:convert';
import 'dart:typed_data';

import '../core/node_types.dart';
import '../radio/rf_codec.dart';

/// TIME key 2.
const gameWaiting = 0;
const gameRunning = 1;
const gamePaused = 2;
const gameEnded = 3;

/// CMD opcodes (ADR-P2-3, RFC 0001); 9 (update) is the GM's alone and not
/// sent by this controller.
const cmdOpcodes = {
  'start': 0,
  'pause': 1,
  'resume': 2,
  'end': 3,
  'set_owner': 4,
  'message': 5,
  'reset': 6,
  'reboot': 7,
  'mode': 8,
};

/// CMD update's opcode (firmware updates, slice S7c).
const cmdUpdate = 9;

const broadcastNode = 0xffff;

/// A box's C decoder turns CMD params into JSON in a 128-byte buffer.
const cmdParamsMax = 127;

/// Flood copies of a packet are dropped for this long (ADR-P2-6).
const packetDedupeMs = 60000;

/// TIME every 30 s (spec section 11; 10 s with automatic failover).
const beaconIntervalMs = 30000;

/// Node health (decisions FU1-1 to FU1-3).
const healthEvents = ['node.online', 'node.offline', 'battery.low'];
const linkGapMs = 60000;
const batteryGraceMs = 30000;
const batteryHysteresis = 5;
const tierNames = {0: 'full', 1: 'reduced', 2: 'proxy'};

class FieldControllerException implements Exception {
  FieldControllerException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// What carries the controller's packets: [send] gives the packet's seq, or
/// null when nothing could send it (no radio, the pod unplugged).
abstract interface class FieldTransport {
  /// "up", "down" or "none" (no radio at all), as the Pi's radio_state.
  String get state;

  int? send(
    int type,
    Uint8List payload, {
    required int prio,
    required bool ack,
    required int hopLimit,
  });
}

/// No radio: nothing is sent (the API answers 503 for node commands).
class NoRadio implements FieldTransport {
  const NoRadio();
  @override
  String get state => 'none';
  @override
  int? send(
    int type,
    Uint8List payload, {
    required int prio,
    required bool ack,
    required int hopLimit,
  }) => null;
}

/// A node the controller knows about.
class FieldNode {
  FieldNode(this.nodeId, this.name, this.role);

  final int nodeId;
  String name;
  String role;
  int lastSeenMs = 0;
  int lastSeq = 0;
  int epoch = 0;
  int ownerTeam = 0;
  int phase = 0;
  int gameTimeMs = 0;
  int? batteryPct;
  int? rssi;
  int? snr;
  RfHello? hello;

  /// Health: heard in this run, the game time of the last packet, the link
  /// as the last node.online/node.offline said it (null: neither yet) and
  /// when that was logged, and whether battery.low is logged for this
  /// crossing.
  bool heard = false;
  int lastSeenGameMs = 0;
  String? link;
  int? linkChangedMs;
  bool batteryLow = false;
  int? batteryLowSince;

  String? ownerName(List<String> teams) =>
      ownerTeam >= 1 && ownerTeam <= teams.length ? teams[ownerTeam - 1] : null;
}

/// Which seqs arrived from each (node, epoch), as ACK payloads.
class AckTracker {
  final _contig = <(int, int), int>{};
  final _above = <(int, int), Set<int>>{};

  void record(int node, int epoch, int seq) {
    final key = (node, epoch);
    var contig = _contig[key] ?? -1;
    if (seq <= contig) return;
    final above = _above.putIfAbsent(key, () => <int>{})..add(seq);
    while (above.remove(contig + 1)) {
      contig += 1;
    }
    _contig[key] = contig;
  }

  /// Highest contiguous seq from 0, or -1.
  int contiguous(int node, int epoch) => _contig[(node, epoch)] ?? -1;

  RfAck ack(int node, int epoch) {
    final contig = contiguous(node, epoch);
    final bits = Uint8List(32);
    for (final seq in _above[(node, epoch)] ?? const <int>{}) {
      final n = seq - contig - 1;
      if (n >= 0 && n < 256) bits[n ~/ 8] |= 1 << (n % 8);
    }
    var used = 32;
    while (used > 0 && bits[used - 1] == 0) {
      used--;
    }
    return RfAck(
      node: node,
      seq: contig & 0xffff,
      bitmap: used == 0 ? null : Uint8List.sublistView(bits, 0, used),
    );
  }
}

/// Decodes a box's EVENT payload (the core's codec through dart:ffi).
typedef EventDecoder = EmittedEvent Function(Uint8List payload);

class FieldController {
  FieldController({
    required this.transport,
    required this.gameId,
    required List<String> teams,
    this.nodeId = 0,
    this.maxHops = 2,
    this.term = 1,
    this.decodeEvent,
    int Function()? wallSeconds,
  }) : teams = List.unmodifiable(teams),
       _wall =
           wallSeconds ??
           (() => DateTime.now().millisecondsSinceEpoch ~/ 1000) {
    for (final t in teams) {
      _scores[t] = {};
    }
  }

  final FieldTransport transport;
  final int gameId;
  final List<String> teams;
  final int nodeId;
  final int maxHops;
  int term;
  final EventDecoder? decodeEvent;
  final int Function() _wall;

  int gameState = gameWaiting;
  int gameTimeMs = 0;
  int durationMs = 0;
  int lastBeaconMs = 0;
  int _now = 0;
  int? _lastTick;
  int _eventSeq = 0;

  /// The seq of the health events this controller logs about boxes.
  int healthSeq = 0;
  int nodeOfflineMs = 0;
  int linkGapMsSetting = linkGapMs;
  int batteryLowPct = 0;

  final nodes = <int, FieldNode>{};

  /// Packets and events the controller did not log as events (errors).
  final List<Map<String, Object?>> problems = [];

  /// team -> node key ("node-4", "field-1") -> highest value reported.
  final _scores = <String, Map<String, int>>{};
  final _adjust = <String, int>{};
  final acks = AckTracker();
  final _packetsSeen = <(int, int, int), int>{};
  final _eventsSeen = <(int, int, int, String)>{};
  int _lastPrune = 0;

  void Function(Map<String, Object?> record)? onEvent;
  void Function(FieldNode node, String kind)? onNode;
  void Function(Map<String, int> totals)? onScores;

  /// Always true until the election is ported (PE24 slice S7).
  bool get isController => true;

  FieldNode registerNode(int id, String name, String role) {
    final node = nodes[id];
    if (node == null) return nodes[id] = FieldNode(id, name, role);
    node
      ..name = name
      ..role = role;
    return node;
  }

  FieldNode _node(int id) =>
      nodes[id] ?? registerNode(id, 'node-$id', 'unknown');

  String? teamName(int teamId) =>
      teamId >= 1 && teamId <= teams.length ? teams[teamId - 1] : null;

  void _advanceTime(int nowMs) {
    final last = _lastTick;
    if (gameState == gameRunning && last != null && nowMs > last) {
      gameTimeMs += nowMs - last;
    }
    _lastTick = nowMs;
    if (nowMs > _now) _now = nowMs;
  }

  /// Puts back the game clock after a restart (PE24 slice S3).
  void restoreClock(int state, int timeMs, int nowMs) {
    gameState = state;
    gameTimeMs = timeMs;
    _lastTick = nowMs;
  }

  // --- the game -------------------------------------------------------------

  void startGame({int durationMs = 0, required int nowMs}) {
    gameState = gameRunning;
    this.durationMs = durationMs;
    gameTimeMs = 0;
    _lastTick = nowMs;
    if (nowMs > _now) _now = nowMs;
    lastBeaconMs = nowMs;
    _sendCmd(cmdOpcodes['start']!);
    sendTimeBeacon(nowMs);
  }

  void pauseGame({required int nowMs, String? reason}) {
    _advanceTime(nowMs);
    gameState = gamePaused;
    _sendCmd(cmdOpcodes['pause']!, reason == null ? null : {'reason': reason});
    sendTimeBeacon(nowMs);
  }

  void resumeGame({required int nowMs}) {
    _advanceTime(nowMs);
    gameState = gameRunning;
    _sendCmd(cmdOpcodes['resume']!);
    sendTimeBeacon(nowMs);
  }

  void endGame({required int nowMs, String? reason}) {
    _advanceTime(nowMs);
    gameState = gameEnded;
    _sendCmd(cmdOpcodes['end']!, reason == null ? null : {'reason': reason});
    sendTimeBeacon(nowMs);
  }

  // --- sending --------------------------------------------------------------

  int? _send(int type, Uint8List payload, int prio, {bool ack = false}) =>
      transport.send(type, payload, prio: prio, ack: ack, hopLimit: maxHops);

  int? sendTimeBeacon(int nowMs) {
    lastBeaconMs = nowMs;
    return _send(
      RfType.time,
      RfTime(
        gameTimeMs: gameTimeMs & 0xffffffff,
        gameState: gameState,
        durationMs: durationMs & 0xffffffff,
        wallS: _wall() & 0xffffffff,
        term: term & 0xffffffff,
      ).encode(),
      RfPrio.critical,
    );
  }

  /// A command by name to [dest] (null: every node); its packet's seq, or
  /// null when nothing sent it. Throws [FieldControllerException] for an
  /// unknown command or parameters that do not fit a CMD.
  int? sendCmd(String cmd, Map<String, Object?>? params, {int? dest}) {
    final opcode = cmdOpcodes[cmd];
    if (opcode == null) {
      throw FieldControllerException('unknown command $cmd');
    }
    return _sendCmd(opcode, params, dest);
  }

  int? _sendCmd(int cmd, [Map<String, Object?>? params, int? dest]) {
    if (params != null && params.isNotEmpty) {
      final size = utf8.encode(jsonEncode(params)).length;
      if (size > cmdParamsMax) {
        throw FieldControllerException(
          'command parameters are $size bytes; at most $cmdParamsMax fit in a CMD',
        );
      }
    }
    return _send(
      RfType.cmd,
      RfCmd(
        cmd: cmd,
        params: params == null || params.isEmpty ? null : params,
        dest: dest == null || dest == broadcastNode ? null : dest,
      ).encode(),
      RfPrio.critical,
    );
  }

  /// CMD update (opcode 9, RFC 0001 Amendment 6) to [dest]: the GM's alone
  /// (controller_firmware.dart), never a mode's field.lua, so not in
  /// [cmdOpcodes].
  int? sendUpdateCmd(Map<String, Object?> params, {required int dest}) =>
      _sendCmd(cmdUpdate, params, dest);

  // --- receiving ------------------------------------------------------------

  /// One decrypted packet; [epoch], [rssi] and [snr] as the radio gave them.
  void onPacket(
    RfHeader header,
    Uint8List payload, {
    int epoch = 0,
    int? rssi,
    int? snr,
  }) {
    final key = (header.source, epoch, header.seq);
    if (_packetsSeen.containsKey(key)) return; // a flood copy
    _packetsSeen[key] = _now;
    if (header.type == RfType.time || header.type == RfType.claim) {
      // Another controller (PE24 slice S7): noted, not followed.
      problems.add({
        't_ms': _now,
        'type': header.type == RfType.time ? 'time' : 'claim',
        'source': header.source,
      });
      return;
    }
    acks.record(header.source, epoch, header.seq);
    final node = _node(header.source)
      ..lastSeenMs = _now
      ..lastSeenGameMs = gameTimeMs
      ..heard = true
      ..lastSeq = header.seq
      ..epoch = epoch;
    if (rssi != null) node.rssi = rssi;
    if (snr != null) node.snr = snr;
    switch (header.type) {
      case RfType.state:
        _onState(node, payload);
      case RfType.hello:
        _onHello(node, payload);
      case RfType.event:
        _onEvent(node, header, payload, epoch);
    }
    if (header.ackRequested) {
      _send(RfType.ack, acks.ack(header.source, epoch).encode(), RfPrio.normal);
    }
    _checkHealth(node, _now);
  }

  void _onState(FieldNode node, Uint8List payload) {
    final RfState state;
    try {
      state = RfState.decode(payload);
    } on Object {
      return;
    }
    node
      ..ownerTeam = state.ownerTeam
      ..phase = state.phase
      ..gameTimeMs = state.gameTimeMs;
    if (state.batteryPct != null) node.batteryPct = state.batteryPct;
    if (state.rssi != null) node.rssi = state.rssi;
    mergeCounters('node-${node.nodeId}', {
      for (final e in state.counters.entries)
        teamName(e.key) ?? '${e.key}': e.value,
    });
    onNode?.call(node, 'state');
  }

  void _onHello(FieldNode node, Uint8List payload) {
    final RfHello hello;
    try {
      hello = RfHello.decode(payload);
    } on Object {
      return;
    }
    node
      ..hello = hello
      ..name = hello.nodeName;
    if (hello.batteryPct != null) node.batteryPct = hello.batteryPct;
    onNode?.call(node, 'hello');
  }

  void _onEvent(FieldNode node, RfHeader header, Uint8List payload, int epoch) {
    final EmittedEvent ev;
    try {
      final decode = decodeEvent;
      if (decode == null) throw FieldControllerException('no event codec');
      ev = decode(payload);
    } on Object catch (e) {
      problems.add({
        't_ms': _now,
        'type': 'event',
        'source': node.nodeId,
        'seq': header.seq,
        'error': '$e',
      });
      return;
    }
    // A box's event seq restarts at 1 after a reboot: the event's identity
    // is (node, seq, game time, type), and replays match it exactly.
    if (!_eventsSeen.add((node.nodeId, ev.seq, ev.tMs, ev.type))) return;
    final record = <String, Object?>{
      'node': node.nodeId,
      'seq': ev.seq,
      't': ev.tMs,
      'type': ev.type,
      'team': teamName(ev.team),
      'team_id': ev.team,
      'squad': ev.squad,
      'prio': ev.prioName,
      'data': ev.data,
      'epoch': epoch,
      'pkt_seq': header.seq,
      'received_ms': _now,
    };
    if (ev.type == 'battery.low') {
      node
        ..batteryLow = true
        ..batteryLowSince = null;
    }
    onEvent?.call(record);
  }

  // --- tick -----------------------------------------------------------------

  /// Moves to [nowMs]: the game clock, due TIME beacons, node health.
  void tick(int nowMs) {
    _advanceTime(nowMs);
    if ((gameState == gameRunning || gameState == gamePaused) &&
        nowMs - lastBeaconMs >= beaconIntervalMs) {
      sendTimeBeacon(nowMs);
    }
    for (final node in nodes.values.toList()) {
      _checkHealth(node, nowMs);
    }
    if (nowMs - _lastPrune >= 10000) {
      _lastPrune = nowMs;
      _packetsSeen.removeWhere((_, t) => t < nowMs - packetDedupeMs);
    }
  }

  // --- scores ---------------------------------------------------------------

  /// Merges counters by maximum, per source: a node ("node-ID") or a run of
  /// the field script ("field-N"), whose points never travel in STATE.
  void mergeCounters(String nodeKey, Map<String, int> counters) {
    var changed = false;
    counters.forEach((team, value) {
      final perNode = _scores.putIfAbsent(team, () => {});
      if (value > (perNode[nodeKey] ?? 0)) {
        perNode[nodeKey] = value;
        changed = true;
      }
    });
    if (changed) onScores?.call(totalScores);
  }

  /// [team]'s points from one source ("node-4").
  int counter(String team, String nodeKey) => _scores[team]?[nodeKey] ?? 0;

  /// An event the controller itself originates (GM actions, field scripts).
  Map<String, Object?> controllerEvent(
    String type, [
    Map<String, Object?> data = const {},
    String? team,
    String prio = 'normal',
  ]) {
    _eventSeq = (_eventSeq % 0xffff) + 1;
    final teamId = team == null ? 0 : teams.indexOf(team) + 1;
    final record = <String, Object?>{
      'node': nodeId,
      'seq': _eventSeq,
      't': gameTimeMs,
      'type': type,
      'team': teamId > 0 ? team : null,
      'team_id': teamId,
      'squad': 0,
      'prio': prio,
      'data': Map<String, Object?>.of(data),
      'epoch': null,
      'pkt_seq': null,
      'received_ms': _now,
    };
    onEvent?.call(record);
    return record;
  }

  /// Puts back the seq of the controller's own events (after a restart).
  void restoreEventSeq(int seq) => _eventSeq = seq;

  /// An event the controller logs about a box: its node is the box's id.
  Map<String, Object?> nodeEvent(
    int id,
    String type, [
    Map<String, Object?> data = const {},
  ]) {
    healthSeq = (healthSeq % 0xffff) + 1;
    final record = <String, Object?>{
      'node': id,
      'seq': healthSeq,
      't': gameTimeMs,
      'type': type,
      'team': null,
      'team_id': 0,
      'squad': 0,
      'prio': 'telemetry',
      'data': Map<String, Object?>.of(data),
      'epoch': null,
      'pkt_seq': null,
      'received_ms': _now,
      'origin': 'controller',
    };
    onEvent?.call(record);
    return record;
  }

  void _checkHealth(FieldNode node, int nowMs) {
    if (gameState == gameEnded) return;
    final since = node.heard
        ? node.lastSeenMs
        : node.link == 'online'
        ? node.linkChangedMs
        : null;
    if (nodeOfflineMs > 0 && since != null) {
      final want = nowMs - since < nodeOfflineMs ? 'online' : 'offline';
      final changed = node.linkChangedMs;
      if (want != node.link &&
          (changed == null || nowMs - changed >= linkGapMsSetting)) {
        final data = <String, Object?>{};
        if (want == 'online') {
          final hello = node.hello;
          if (hello != null) {
            data['fw'] = hello.fwVersion;
            final tier = tierNames[hello.tier];
            if (tier != null) data['tier'] = tier;
          }
        } else {
          data['last_seen'] = node.lastSeenGameMs;
        }
        node
          ..link = want
          ..linkChangedMs = nowMs;
        nodeEvent(node.nodeId, 'node.$want', data);
        onNode?.call(node, want);
      }
    }
    final pct = node.batteryPct;
    if (batteryLowPct > 0 && pct != null && pct >= 0 && pct <= 100) {
      if (pct >= batteryLowPct + batteryHysteresis) {
        node
          ..batteryLow = false
          ..batteryLowSince = null;
      } else if (pct >= batteryLowPct || node.batteryLow) {
        node.batteryLowSince = null;
      } else if (node.batteryLowSince == null) {
        node.batteryLowSince = nowMs;
      } else if (nowMs - node.batteryLowSince! >= batteryGraceMs) {
        node
          ..batteryLow = true
          ..batteryLowSince = null;
        nodeEvent(node.nodeId, 'battery.low', {'percent': pct});
      }
    }
  }

  /// A GM's adjustment, logged as score.delta from the controller.
  Map<String, Object?> adjustScore(
    String team,
    int amount,
    String reason, {
    int? nowMs,
  }) {
    if (nowMs != null) _advanceTime(nowMs);
    _adjust[team] = (_adjust[team] ?? 0) + amount;
    final record = controllerEvent('score.delta', {
      'team': team,
      'amount': amount,
      'reason': reason,
    }, team);
    onScores?.call(totalScores);
    return record;
  }

  void restoreAdjustments(Map<String, int> adjustments) {
    _adjust
      ..clear()
      ..addAll(adjustments);
  }

  /// Per team: the highest value each source reported, summed, plus the
  /// GM's adjustments.
  Map<String, int> get totalScores {
    final out = <String, int>{};
    _scores.forEach((team, perNode) {
      out[team] = perNode.values.fold(0, (a, b) => a + b);
    });
    _adjust.forEach((team, amount) => out[team] = (out[team] ?? 0) + amount);
    return out;
  }
}
