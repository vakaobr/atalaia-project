// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The API's shared contract cases (protocol/vectors/controller_api.json)
// against the Android field controller (decision PE24): the engine on the
// real core, served over HTTP on the loopback address, as the Pi controller
// runs them in controller/tests/test_api_contract.py. Each case gets a
// fresh controller, a radio that is up (a RecordingModem: tx steps read what went to it, slice S4) and a clock that only moves on an
// advance_ms step, which also runs one tick; its store is a
// FileControllerStore in a temporary directory, and a restart step closes
// the controller and opens a new one on it (slice S3). Stream steps connect real
// WebSocket clients to WS /api/v1/stream on the loopback address; mqtt
// steps read what the MQTT bridge (controller_mqtt.dart) published; the
// mqtt_acl checks run against MqttAcl.field (mqtt_broker.dart). Field
// check-in and player positions (slice S5) are set up on every controller
// as the Pi runner sets them up: the portugal limit template, HTTPS off,
// the wall clock at the vectors' wall_start moving with the clock, the
// field's day in UTC; request and ws_connect steps may give a player token
// ('bearer'), and ws_closed reads a connection to its end. The field plan and
// the radio channel (slice S7a, the vectors' field_and_radio block) add
// requests with a raw body ('raw': an uploaded image), answers that are not
// JSON ('content_type', 'body_base64') and the noise scan's steps ('noise',
// 'hold_measure', 'scan_wait') on the recording modem; every controller has
// its field plan's files in the case's folder, so a restart keeps them.
// Slice S7c: field cards and firmware updates are set up on every
// controller, the boxes over the radio and pairing with the case's join
// key, as the Pi runner does; field_rx, pair_rx, field_tx, field_ack,
// pair_box and pair_box_done steps play the boxes' side of the field and
// pair frames, and requests may send raw bytes signed with a key (a box's
// firmware report). Slice S7b: the vectors' fixtures' values are saved in
// every case; a case's mode_keys, mode_revoked and box_keys set up signed
// mode packages and the modes sent to boxes (scenarios and branding are on
// every controller); raw bodies may name their 'content_type' and answers'
// 'headers' are matched. Slice S7 (the vectors' s7 block): a case's
// failover_mode, rx steps of another controller's TIME and CLAIM, and
// join_encode, which seals a join payload with the case's join key (a
// standby's join, as the leading controller makes it).

import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_adoption.dart';
import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_boxes.dart';
import 'package:atalaia_app/controller/controller_branding.dart';
import 'package:atalaia_app/controller/controller_mode_fetch.dart';
import 'package:atalaia_app/controller/controller_scenarios.dart';
import 'package:atalaia_app/controller/controller_signed_modes.dart';
import 'package:atalaia_app/controller/controller_checkin.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_field.dart';
import 'package:atalaia_app/controller/controller_firmware.dart';
import 'package:atalaia_app/controller/controller_pairing.dart';
import 'package:atalaia_app/controller/controller_positions.dart';
import 'package:atalaia_app/controller/controller_mqtt.dart';
import 'package:atalaia_app/controller/prop_link.dart' show propLinkProof;
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/controller/mqtt_broker.dart';
import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/protocol/field_frame.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/protocol/pair_frame.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:atalaia_app/security/cpace.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/event_schema.dart';
import '../support/recording_modem.dart';
import '../support/vectors.dart';

final _var = RegExp(r'\$\{(\w+)\}');

Object? substitute(Object? value, Map<String, Object?> saved) {
  if (value is String) {
    final whole = _var.matchAsPrefix(value);
    if (whole != null && whole.end == value.length) return saved[whole[1]];
    return value.replaceAllMapped(_var, (m) => '${saved[m[1]]}');
  }
  if (value is List) return [for (final v in value) substitute(v, saved)];
  if (value is Map) {
    return {
      for (final e in value.entries) '${e.key}': substitute(e.value, saved),
    };
  }
  return value;
}

/// Why [actual] does not match [pattern] (the rules in the vectors'
/// description), or null.
String? mismatch(Object? pattern, Object? actual, [String where = r'$']) {
  if (pattern is Map &&
      pattern.length == 1 &&
      pattern.containsKey(r'$contains')) {
    if (actual is! List) return '$where: a list was expected, got $actual';
    final items = pattern[r'$contains']! as List;
    for (var i = 0; i < items.length; i++) {
      if (actual.every((a) => mismatch(items[i], a) != null)) {
        return '$where: no element matches \$contains[$i] ${items[i]}';
      }
    }
    return null;
  }
  if (pattern is Map) {
    if (actual is! Map) return '$where: an object was expected, got $actual';
    for (final e in pattern.entries) {
      final k = e.key;
      if (e.value == r'$absent') {
        if (actual.containsKey(k)) {
          return '$where.$k: should be absent, is ${actual[k]}';
        }
        continue;
      }
      if (!actual.containsKey(k)) return '$where.$k: missing';
      if (e.value == r'$any') continue;
      final why = mismatch(e.value, actual[k], '$where.$k');
      if (why != null) return why;
    }
    return null;
  }
  if (pattern is List) {
    if (actual is! List || actual.length != pattern.length) {
      return '$where: ${pattern.length} elements were expected, got $actual';
    }
    for (var i = 0; i < pattern.length; i++) {
      final why = mismatch(pattern[i], actual[i], '$where[$i]');
      if (why != null) return why;
    }
    return null;
  }
  if (pattern == r'$any') return null;
  if (pattern is num && actual is num) {
    return pattern == actual
        ? null
        : '$where: $pattern was expected, got $actual';
  }
  if (pattern.runtimeType != actual.runtimeType || pattern != actual) {
    return '$where: $pattern was expected, got $actual';
  }
  return null;
}

Uint8List _unhex(String s) => Uint8List.fromList([
  for (var i = 0; i + 1 < s.length; i += 2)
    int.parse(s.substring(i, i + 2), radix: 16),
]);

String _hex(List<int> b) =>
    [for (final x in b) x.toRadixString(16).padLeft(2, '0')].join();

/// A join payload by protocol/join.md's names, bytes in hex (as the Python
/// runner shows the simulator's decoder's answer).
Map<String, Object?> joinJson(JoinPayload j) => {
  'game_id': j.gameId,
  'game_key': _hex(j.gameKey),
  'node_id': j.nodeId,
  'controller_id': j.controllerId,
  'channel_hz': j.channelHz,
  'max_hops': j.maxHops,
  'teams': j.teams,
  'mode_id': j.modeId,
  'role': j.role,
  'game_seed': j.gameSeed,
  'params': j.params,
  'kind': j.kind.name,
  'ca_sha256': j.caSha256 == null ? null : _hex(j.caSha256!),
  'urls': j.urls,
  'lang': j.lang,
  'fetch_modes': j.fetchModes,
  'forget_modes': j.forgetModes,
  'region': j.region,
};

/// A decoded frame's fields as the cases see them: bytes in hex.
Map<String, Object?> plainMessage(Map<String, Object?> m) => {
  for (final e in m.entries)
    e.key: e.value is List<int> ? _hex(e.value! as List<int>) : e.value,
};

/// A frame the controller sent, decoded with the case's join key.
Map<String, Object?> fieldJson(Uint8List frame, Uint8List joinKey) {
  if (isPairFrame(frame)) {
    return {'type': 'pair', ...plainMessage(decodePairFrame(frame))};
  }
  return {
    'type': 'field',
    ...plainMessage(decodeFieldFrame(fieldKey(joinKey), frame)),
  };
}

Object? dig(Object? value, String path) {
  for (final part in path.split('.')) {
    value = value is List ? value[int.parse(part)] : (value! as Map)[part];
  }
  return value;
}

/// A stream connection of a case: its messages as they come, then its end.
class _Stream {
  _Stream(this.socket) {
    socket.listen(
      (d) {
        _messages.add(jsonDecode(d as String));
        _wake();
      },
      onDone: () {
        done = true;
        _wake();
      },
      onError: (Object _) {
        done = true;
        _wake();
      },
    );
  }

  final WebSocket socket;
  final _messages = Queue<Object?>();
  var done = false;
  Completer<void>? _waiter;

  void _wake() {
    final w = _waiter;
    _waiter = null;
    w?.complete();
  }

  /// The next message, or null once the controller has closed it.
  Future<Map<String, Object?>?> next() async {
    while (_messages.isEmpty) {
      if (done) return null;
      final w = _waiter = Completer<void>();
      await w.future.timeout(const Duration(seconds: 15));
    }
    return (_messages.removeFirst()! as Map).cast<String, Object?>();
  }
}

void main() {
  final vectors = loadVectors('controller_api.json');
  final tokens = (vectors['tokens'] as Map).cast<String, String>();
  final schema = EventSchema.load();
  final wallStart = vectors['wall_start'] as int;
  final limits = File(
    'lib/chrono/limit_templates/portugal.yaml',
  ).readAsStringSync();
  late AtalaiaCore core;

  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  Uint8List rxPayload(Map<String, Object?> rx) {
    switch (rx['type']) {
      case 'HELLO':
        final h = (rx['hello']! as Map).cast<String, Object?>();
        return RfHello(
          nodeName: h['node_name']! as String,
          platform: h['platform']! as int,
          fwVersion: h['fw_version']! as String,
          coreVersion: h['core_version']! as String,
          tier: h['tier']! as int,
          capabilities: (h['capabilities']! as List).cast<int>(),
          transports: h['transports']! as int,
          batteryPct: h['battery_pct'] as int?,
          epoch: h['epoch']! as int,
          deviceId: h['device_id'] == null
              ? null
              : _unhex(h['device_id']! as String),
        ).encode();
      case 'STATE':
        final s = (rx['state']! as Map).cast<String, Object?>();
        return RfState(
          ownerTeam: s['owner_team']! as int,
          phase: s['phase']! as int,
          gameTimeMs: s['game_time_ms']! as int,
          counters: {
            for (final e in (s['counters']! as Map).entries)
              int.parse('${e.key}'): e.value as int,
          },
          epoch: s['epoch']! as int,
        ).encode();
      case 'TIME':
        // Slice S7: another controller's beacon.
        final t = (rx['time']! as Map).cast<String, Object?>();
        return RfTime(
          gameTimeMs: t['game_time_ms']! as int,
          gameState: t['game_state']! as int,
          durationMs: t['duration_ms']! as int,
          wallS: t['wall_s']! as int,
          term: t['term']! as int,
        ).encode();
      case 'CLAIM':
        final c = (rx['claim']! as Map).cast<String, Object?>();
        return RfClaim(
          term: c['term']! as int,
          priority: c['priority']! as int,
          nodeId: c['node_id']! as int,
          lastAckSeq: (c['last_ack_seq'] as Map?)?.map(
            (k, v) => MapEntry(int.parse('$k'), v as int),
          ),
        ).encode();
      case 'EVENT':
        final ev = (rx['event']! as Map).cast<String, Object?>();
        final type = ev['type']! as String;
        final encoded = core.encodeEvent(
          node: ev['node']! as int,
          seq: ev['seq']! as int,
          tMs: ev['t']! as int,
          type: type,
          team: (ev['team'] as int?) ?? 0,
          squad: (ev['squad'] as int?) ?? 0,
          prio: ev.containsKey('prio')
              ? prioNames.indexOf(ev['prio']! as String)
              : schema.defaultPrio(type),
          dataJson: ev.containsKey('data') ? jsonEncode(ev['data']) : null,
        );
        return encoded.bytes!;
    }
    throw ArgumentError('unknown rx type ${rx['type']}');
  }

  // The cases, then slice S7a's block (the field plan and the radio channel).
  for (final c in [
    ...cases(vectors, 'cases'),
    ...cases(
      (vectors['field_and_radio'] as Map).cast<String, dynamic>(),
      'cases',
    ),
    ...cases((vectors['s7'] as Map).cast<String, dynamic>(), 'cases'),
  ]) {
    test(c['name'] as String, () async {
      var now = 0;
      final dir = Directory.systemTemp.createTempSync('atalaia-contract-');
      final config = ControllerConfig(
        persistGameKey: (c['persist_game_key'] as bool?) ?? true,
        failoverMode: (c['failover_mode'] as String?) ?? 'manual',
      );
      final radio = RecordingModem();
      final joinKey = _unhex((c['join_key'] as String?) ?? '');
      final firmwareKeys = ((c['firmware_keys'] as List?) ?? const [])
          .cast<String>();
      // Slice S7c: the boxes' side of the field and pair frames.
      var fieldSeen = 0;
      Uint8List? lastField;
      final senders = <String, FieldNonceSource>{};
      PairKeys? pairKeys;
      final published = <Map<String, Object?>>[];
      late ControllerEngine engine;
      late ControllerApi api;
      late HttpServer server;
      var sockets = <String, _Stream>{};
      var props = <String, _Stream>{};
      // Streams of the controllers before a restart, closed with the case.
      final leftBehind = <_Stream>[];

      // A controller on the case's store (a new one after a restart step),
      // with its API, stream and MQTT bridge, as the Pi runner boots one.
      Future<void> boot() async {
        engine = ControllerEngine(
          config: config,
          store: FileControllerStore(dir),
          core: core,
          modem: radio,
          clockMs: () => now,
          wallSeconds: () => wallStart + now / 1000,
        )..joinKey = joinKey;
        ControllerCheckin(
          engine,
          CheckinConfig(
            limitsYaml: limits,
            noticePt: 'Aviso: {operator}, {retention_days} dias.',
            noticeEn: 'Notice: {operator}, {retention_days} days.',
            utcDay: true,
          ),
        );
        ControllerPositions(engine);
        ControllerField(engine, dir: Directory('${dir.path}/field'));
        // Slice S7c, as the Pi runner sets them up.
        ControllerAdoption(engine);
        ControllerFirmware(engine, '${dir.path}/firmware', keys: firmwareKeys);
        if (joinKey.length == 32) {
          ControllerBoxes(engine);
          ControllerPairing(engine);
        }
        // Slice S7b, as the host sets them up.
        ControllerScenarios(engine);
        ControllerBranding(engine);
        engine.signedModes = ControllerSignedModes(
          engine.modes,
          ModesConfig(
            keys: [...?(c['mode_keys'] as List?)?.cast<String>()],
            revoked: [...?(c['mode_revoked'] as List?)?.cast<String>()],
          ),
          wallSeconds: () => wallStart + now / 1000,
        );
        ControllerModeFetch(engine, [
          ...?(c['box_keys'] as List?)?.cast<String>(),
        ], clock: () => wallStart + now / 1000);
        if (c['https'] == true) {
          engine
            ..caSha256 = Uint8List.fromList(List.generate(32, (i) => i))
            ..linkUrls = ['https://192.0.2.10:8443'];
        }
        api = ControllerApi(
          engine,
          gmToken: tokens['gm']!,
          readToken: tokens['read']!,
        );
        if (c['stream_max_queue'] != null) {
          api.hub.maxQueue = c['stream_max_queue'] as int;
        }
        ControllerMqtt(
          engine,
          (topic, payload, {qos = 0, retain = false}) => published.add({
            'topic': topic,
            'qos': qos,
            'retain': retain,
            'payload': jsonDecode(payload as String),
          }),
        );
        server = await api.serve();
        sockets = {};
        props = {};
      }

      Future<void> shutDown() async {
        await api.props.close();
        await api.hub.close();
        await server.close(force: true);
        engine.close();
      }

      await boot();
      final client = HttpClient();
      final saved = <String, Object?>{
        ...?((vectors['fixtures'] as Map?)?['values'] as Map?)
            ?.cast<String, Object?>(),
      };
      var sentinel = 0;

      void check(Object? pattern, Object? actual, String where) {
        final why = mismatch(substitute(pattern, saved), actual);
        expect(why, isNull, reason: '$where: $why');
      }

      // Every message the connection got since its last look: a marker goes
      // through the stream after them (to every connection; the markers of
      // other looks are dropped).
      Future<List<Map<String, Object?>>> untilSentinel(_Stream ws) async {
        final mark = ++sentinel;
        api.hub.publish({'type': 'pong', 'sentinel': mark});
        final got = <Map<String, Object?>>[];
        while (true) {
          final m = await ws.next();
          if (m == null) fail('the stream closed (${ws.socket.closeCode})');
          if (m['type'] == 'pong' && m.containsKey('sentinel')) {
            if (m['sentinel'] == mark) return got;
            continue;
          }
          got.add(m);
        }
      }

      Future<void> wsConnect(Map<String, dynamic> step) async {
        final token = (step['token'] as String?) ?? 'none';
        final secret = step.containsKey('bearer')
            ? substitute(step['bearer'], saved)! as String
            : (token == 'bad' ? 'not-a-token' : tokens[token]);
        var url = 'ws://127.0.0.1:${server.port}/api/v1/stream';
        final headers = <String, Object>{};
        if (secret != null && step['via'] == 'header') {
          headers['Authorization'] = 'Bearer $secret';
        } else if (secret != null) {
          url += '?token=${Uri.encodeQueryComponent(secret)}';
        }
        final ws = _Stream(await WebSocket.connect(url, headers: headers));
        final name = step['ws_connect'] as String;
        if (step.containsKey('close')) {
          expect(await ws.next(), isNull, reason: 'stream $name');
          expect(ws.socket.closeCode, step['close'], reason: 'stream $name');
          return;
        }
        sockets[name] = ws;
        check(step['hello'], await ws.next(), 'stream $name: hello');
      }

      // An Android prop's link (protocol/prop-link.md): the challenge, the
      // proof with the key given (hex), then the welcome, or the refusal and
      // the close code.
      Future<void> propConnect(Map<String, dynamic> step, int i) async {
        final name = step['prop_connect'] as String;
        final ws = _Stream(
          await WebSocket.connect('ws://127.0.0.1:${server.port}/api/v1/prop'),
        );
        final challenge = await ws.next();
        check(
          {'type': 'challenge', 'version': 1, 'nonce': r'$any'},
          challenge,
          'step $i: the challenge',
        );
        final nonce = base64Url.decode(
          base64Url.normalize(challenge!['nonce']! as String),
        );
        final key = _unhex(substitute(step['key'], saved)! as String);
        final gid = substitute(step['game_id'] ?? r'${gid}', saved)! as int;
        final node = step['node_id'] as int;
        ws.socket.add(
          jsonEncode({
            'type': 'auth',
            'game_id': gid,
            'node_id': node,
            'proof': base64Url
                .encode(propLinkProof(key, nonce, gid, node))
                .replaceAll('=', ''),
          }),
        );
        if (step.containsKey('close')) {
          final got = <Map<String, Object?>>[];
          for (var m = await ws.next(); m != null; m = await ws.next()) {
            got.add(m);
          }
          check(step['messages'], got, 'step $i: prop $name');
          expect(ws.socket.closeCode, step['close'], reason: 'step $i');
          return;
        }
        props[name] = ws;
        check(step['welcome'], await ws.next(), 'step $i: prop $name: welcome');
      }

      try {
        final steps = (c['steps'] as List).cast<Map<String, dynamic>>();
        for (var i = 0; i < steps.length; i++) {
          final step = steps[i];
          if (step.containsKey('restart')) {
            // The phone's controller stops and a new one opens the same
            // store, as after the app was killed or the phone restarted.
            leftBehind
              ..addAll(sockets.values)
              ..addAll(props.values);
            await shutDown();
            await boot();
            continue;
          }
          if (step.containsKey('advance_ms')) {
            now += step['advance_ms'] as int;
            engine.tick();
            continue;
          }
          if (step.containsKey('ws_connect')) {
            await wsConnect(step);
            continue;
          }
          if (step.containsKey('ws')) {
            final name = step['ws'] as String;
            final got = await untilSentinel(sockets[name]!);
            check(step['messages'], got, 'step $i: stream $name');
            continue;
          }
          if (step.containsKey('ws_closed')) {
            // Every message until the controller closes the connection.
            final name = step['ws_closed'] as String;
            final ws = sockets.remove(name)!;
            final got = <Map<String, Object?>>[];
            for (var m = await ws.next(); m != null; m = await ws.next()) {
              // The markers of earlier looks at other connections.
              if (m['type'] == 'pong' && m.containsKey('sentinel')) continue;
              got.add(m);
            }
            check(step['messages'], got, 'step $i: stream $name');
            expect(ws.socket.closeCode, step['close'], reason: 'step $i');
            continue;
          }
          if (step.containsKey('ws_send')) {
            final name = step['ws_send'] as String;
            final ws = sockets[name]!..socket.add(jsonEncode(step['json']));
            check(step['reply'], await ws.next(), 'step $i: stream $name');
            continue;
          }
          if (step.containsKey('ws_flood')) {
            // More messages than the client takes, all handed to the clients
            // before any of them is sent.
            for (var n = 0; n < (step['count'] as int); n++) {
              api.hub.publish({'type': 'system', 'kind': 'test', 'i': n});
            }
            final ws = sockets.remove(step['ws_flood'] as String)!;
            while (await ws.next() != null) {}
            expect(ws.socket.closeCode, step['close'], reason: 'step $i');
            continue;
          }
          if (step.containsKey('noise')) {
            // Slice S7a: what the radio measures on each channel.
            (step['noise'] as Map).forEach((hz, v) {
              final l = (v as List).cast<int>();
              radio.noise[int.parse('$hz')] = (l[0], l[1]);
            });
            continue;
          }
          if (step.containsKey('hold_measure')) {
            radio.held = Completer<void>();
            continue;
          }
          if (step.containsKey('scan_wait')) {
            radio.held?.complete();
            radio.held = null;
            final scan = engine.channel?.scan;
            if (scan != null) {
              await scan.done.timeout(const Duration(seconds: 10));
            }
            continue;
          }
          if (step.containsKey('mqtt')) {
            final got = List.of(published);
            published.clear();
            check(step['mqtt'], got, 'step $i: MQTT');
            continue;
          }
          if (step.containsKey('rx')) {
            final rx = (step['rx'] as Map).cast<String, Object?>();
            final type = switch (rx['type']) {
              'HELLO' => RfType.hello,
              'STATE' => RfType.state,
              'TIME' => RfType.time,
              'CLAIM' => RfType.claim,
              _ => RfType.event,
            };
            radio.rx(
              RfHeader.v1(
                gameId: engine.liveGame!['id']! as int,
                source: rx['source']! as int,
                seq: rx['seq']! as int,
                hopLimit: 2,
                type: type,
                ack: rx['ack'] == true,
              ),
              rxPayload(rx),
              epoch: (rx['epoch'] as int?) ?? 0,
            );
            continue;
          }
          if (step.containsKey('prop_connect')) {
            await propConnect(step, i);
            continue;
          }
          if (step.containsKey('prop_send')) {
            props[step['prop_send'] as String]!.socket.add(
              jsonEncode(substitute(step['json'], saved)),
            );
            continue;
          }
          if (step.containsKey('prop')) {
            // Every message since the last look: a ping goes after them, its
            // pong ends the list.
            final name = step['prop'] as String;
            final ws = props[name]!..socket.add(jsonEncode({'type': 'ping'}));
            final got = <Map<String, Object?>>[];
            while (true) {
              final m = await ws.next();
              if (m == null) fail('step $i: prop $name closed');
              if (m.length == 1 && m['type'] == 'pong') break;
              got.add(m);
            }
            check(step['messages'], got, 'step $i: prop $name');
            continue;
          }
          if (step.containsKey('prop_closed')) {
            final name = step['prop_closed'] as String;
            final ws = props.remove(name)!;
            final got = <Map<String, Object?>>[];
            for (var m = await ws.next(); m != null; m = await ws.next()) {
              got.add(m);
            }
            check(step['messages'], got, 'step $i: prop $name');
            expect(ws.socket.closeCode, step['close'], reason: 'step $i');
            continue;
          }
          if (step.containsKey('join_encode')) {
            // Slice S7: a join payload sealed with the case's join key, as
            // another controller makes one; its text is saved.
            final f = (substitute(step['join_encode'], saved)! as Map)
                .cast<String, Object?>();
            final join = JoinPayload(
              gameId: f['game_id']! as int,
              gameKey: _unhex(f['game_key']! as String),
              nodeId: f['node_id']! as int,
              controllerId: f['controller_id']! as int,
              channelHz: f['channel_hz']! as int,
              maxHops: f['max_hops']! as int,
              teams: (f['teams']! as List).cast<String>(),
              modeId: f['mode_id']! as String,
              role: f['role']! as String,
              gameSeed: f['game_seed']! as int,
              params: (f['params'] as Map?)?.cast<String, Object?>(),
              kind: JoinKind.values.byName(f['kind']! as String),
              lang: f['lang'] as String?,
              region: (f['region'] as String?) ?? 'eu868',
            );
            saved[step['save'] as String] = joinToText(
              encodeJoin(join, joinKey),
            );
            continue;
          }
          if (step.containsKey('join_decode')) {
            // A join payload's text, opened with the case's field join key.
            final text = substitute(step['join_decode'], saved)! as String;
            final j = joinJson(decodeJoin(joinFromText(text), joinKey));
            check(step['json'], j, 'step $i: the join payload');
            for (final e
                in ((step['save'] as Map?) ?? const {})
                    .cast<String, String>()
                    .entries) {
              saved[e.key] = dig(j, e.value);
            }
            continue;
          }
          if (step.containsKey('tx')) {
            var got = List.of(radio.log);
            radio.log.clear();
            final kinds = (step['kinds'] as List?)?.cast<String>();
            if (kinds != null) {
              got = [
                for (final e in got)
                  if (kinds.contains(e['kind'])) e,
              ];
            }
            check(step['tx'], got, 'step $i: the radio');
            continue;
          }
          if (step.containsKey('field_rx')) {
            final spec = (substitute(step['field_rx'], saved)! as Map)
                .cast<String, Object?>();
            final Uint8List frame;
            if (spec['replay'] == true) {
              frame = lastField!;
            } else {
              final msg = {
                for (final e in spec.entries)
                  e.key:
                      const [
                        'device_id',
                        'token',
                        'key_tag',
                        'chunk',
                      ].contains(e.key)
                      ? _unhex(e.value! as String)
                      : e.value,
              };
              final sender = (msg['device_id'] as Uint8List?) ?? Uint8List(8);
              final nonces = senders.putIfAbsent(
                _hex(sender),
                () => FieldNonceSource(joinKey, sender),
              );
              frame = encodeFieldFrame(fieldKey(joinKey), msg, nonces.next());
            }
            lastField = frame;
            radio.onFieldRx?.call(frame, -61, 7);
            continue;
          }
          if (step.containsKey('pair_rx')) {
            final spec = (substitute(step['pair_rx'], saved)! as Map)
                .cast<String, Object?>();
            final msg = {
              for (final e in spec.entries)
                e.key:
                    const [
                      'pair_id',
                      'sid',
                      'point',
                      'tag',
                      'fingerprint',
                    ].contains(e.key)
                    ? _unhex(e.value! as String)
                    : e.value,
            };
            radio.onFieldRx?.call(encodePairFrame(msg), -62, 6);
            continue;
          }
          if (step.containsKey('field_ack')) {
            final a = (step['field_ack'] as Map).cast<String, Object?>();
            radio.onFieldAck?.call(a['id']! as int, a['status']! as String);
            continue;
          }
          if (step.containsKey('field_tx')) {
            var got = [
              for (final f in radio.fields.skip(fieldSeen))
                fieldJson(f, joinKey),
            ];
            fieldSeen = radio.fields.length;
            final kinds = (step['kinds'] as List?)?.cast<String>();
            if (kinds != null) {
              got = [
                for (final g in got)
                  if (kinds.contains(g['kind'])) g,
              ];
            }
            check(step['field_tx'], got, 'step $i: the field frames');
            for (final e
                in ((step['save'] as Map?) ?? const {})
                    .cast<String, String>()
                    .entries) {
              saved[e.key] = dig(got, e.value);
            }
            continue;
          }
          if (step.containsKey('pair_box') ||
              step.containsKey('pair_box_done')) {
            Map<String, Object?> last(String kind) {
              for (final f in radio.fields.reversed) {
                if (!isPairFrame(f)) continue;
                final m = decodePairFrame(f);
                if (m['kind'] == kind) return m;
              }
              fail('step $i: the controller sent no ${kind.toUpperCase()}');
            }

            if (step.containsKey('pair_box')) {
              // An unadopted box answers the last START with its own code.
              final spec = (step['pair_box'] as Map).cast<String, Object?>();
              final start = last('start');
              final pid = start['pair_id']! as Uint8List;
              final sid = start['sid']! as Uint8List;
              final ya = start['point']! as Uint8List;
              final ybSecret = _unhex((spec['yb'] as String?) ?? '6b' * 32);
              final yb = x25519(
                ybSecret,
                pairGenerator(spec['code']! as String, pid, sid),
              );
              final k = x25519Verified(ybSecret, ya);
              final keys = PairKeys(pairIsk(sid, k, ya, yb), sid);
              pairKeys = keys;
              radio.onFieldRx?.call(
                encodePairFrame({
                  'kind': 'reply',
                  'pair_id': pid,
                  'sid': sid,
                  'point': yb,
                  'tag': keys.tagReply,
                }),
                -62,
                6,
              );
            } else {
              // The box checks KEY, opens the key and answers DONE.
              final spec = (step['pair_box_done'] as Map)
                  .cast<String, Object?>();
              final keys = pairKeys!;
              final key = last('key');
              expect(
                _hex(key['tag']! as Uint8List),
                _hex(keys.tagKey),
                reason: "step $i: KEY's confirmation",
              );
              final (join, name) = openPairKey(
                keys,
                key['nonce']! as Uint8List,
                key['pair_id']! as Uint8List,
                key['sid']! as Uint8List,
                key['sealed']! as Uint8List,
              );
              check(
                spec['opened'] ?? const <String, Object?>{},
                {'join_key': _hex(join), 'field_name': name},
                'step $i: the sealed key',
              );
              final result = (spec['result'] as String?) ?? 'adopted';
              final fp = spec['fingerprint'] != null
                  ? _unhex(spec['fingerprint']! as String)
                  : fieldFingerprintBytes(join);
              radio.onFieldRx?.call(
                encodePairFrame({
                  'kind': 'done',
                  'pair_id': key['pair_id'],
                  'sid': key['sid'],
                  'result': result,
                  'fingerprint': fp,
                  'tag': keys.tagDone(result, fp),
                }),
                -62,
                6,
              );
            }
            continue;
          }
          if (step.containsKey('radio_state')) {
            radio.setState(step['radio_state'] as String);
            continue;
          }
          if (step.containsKey('tx_ack')) {
            final a = (step['tx_ack'] as Map).cast<String, Object?>();
            radio.onTxAck?.call(a['seq']! as int, a['status']! as String);
            continue;
          }
          final req = (substitute(step['request'], saved)! as Map)
              .cast<String, Object?>();
          final method = req['method']! as String;
          final path = req['path']! as String;
          final request = await client.openUrl(
            method,
            Uri.parse('http://127.0.0.1:${server.port}$path'),
          );
          final token = (req['token'] as String?) ?? 'none';
          if (req.containsKey('bearer')) {
            request.headers.set('Authorization', 'Bearer ${req['bearer']}');
          } else if (token == 'bad') {
            request.headers.set('Authorization', 'Bearer not-a-token');
          } else if (token != 'none') {
            request.headers.set('Authorization', 'Bearer ${tokens[token]}');
          }
          if (req.containsKey('body')) {
            request.headers.contentType = ContentType.json;
            request.write(jsonEncode(req['body']));
          }
          if (req.containsKey('raw')) {
            // Slice S7a: a raw body, zero bytes added up to 'size' if given.
            final raw = (req['raw']! as Map).cast<String, Object?>();
            final data = base64.decode((raw['base64'] as String?) ?? '');
            final size = (raw['size'] as int?) ?? 0;
            request.headers.set('Content-Type', raw['content_type']! as String);
            request.contentLength = data.length > size ? data.length : size;
            request.add(data);
            if (size > data.length) request.add(Uint8List(size - data.length));
          }
          // Slices S7c and S7b: raw bytes (hex or text) with their type,
          // signed with 'mac_key'.
          final rawBody = req.containsKey('body_hex')
              ? _unhex(req['body_hex']! as String)
              : req.containsKey('body_text')
              ? Uint8List.fromList(utf8.encode(req['body_text']! as String))
              : null;
          if (rawBody != null) {
            request.headers.set(
              'Content-Type',
              (req['content_type'] as String?) ?? 'application/octet-stream',
            );
            if (req.containsKey('mac_key')) {
              request.headers.set(
                'X-Atalaia-Mac',
                Hmac(
                  sha256,
                  _unhex(req['mac_key']! as String),
                ).convert(rawBody).toString(),
              );
            }
          }
          for (final e
              in ((req['headers'] as Map?) ?? const {})
                  .cast<String, String>()
                  .entries) {
            request.headers.set(e.key, e.value);
          }
          if (rawBody != null) request.add(rawBody);
          final response = await request.close();
          final bytes = await response.fold<BytesBuilder>(
            BytesBuilder(),
            (b, chunk) => b..add(chunk),
          );
          final data = bytes.takeBytes();
          final text = utf8.decode(data, allowMalformed: true);
          final where = 'step $i: $method $path';
          expect(
            response.statusCode,
            step['status'],
            reason:
                '$where: ${text.length > 500 ? text.substring(0, 500) : text}',
          );
          if (step.containsKey('headers')) {
            // Slice S7b: the answer's headers, by lower-case name.
            final got = <String, Object?>{};
            response.headers.forEach((k, v) => got[k] = v.join(','));
            check(
              {
                for (final e in (step['headers'] as Map).entries)
                  '${e.key}'.toLowerCase(): e.value,
              },
              got,
              '$where: headers',
            );
          }
          final ctype = response.headers.contentType?.mimeType ?? '';
          if (step.containsKey('content_type')) {
            expect(ctype, step['content_type'], reason: where);
          }
          if (step.containsKey('body_base64')) {
            expect(
              data,
              base64.decode(step['body_base64'] as String),
              reason: where,
            );
          }
          if (step.containsKey('text')) {
            expect(text, substitute(step['text'], saved), reason: where);
            continue;
          }
          if (step.containsKey('bytes_sha256')) {
            expect(
              sha256.convert(data).toString(),
              substitute(step['bytes_sha256'], saved),
              reason: where,
            );
            continue;
          }
          final body = ctype == 'application/json' ? jsonDecode(text) : null;
          if (step.containsKey('json')) check(step['json'], body, where);
          for (final e
              in ((step['save'] as Map?) ?? const {})
                  .cast<String, String>()
                  .entries) {
            saved[e.key] = dig(body, e.value);
          }
        }
      } finally {
        for (final ws in [...leftBehind, ...sockets.values, ...props.values]) {
          await ws.socket.close();
        }
        client.close(force: true);
        await shutDown();
        dir.deleteSync(recursive: true);
      }
    });
  }

  test('the prop link proof (protocol/vectors/prop_link.json)', () {
    final v = loadVectors('prop_link.json');
    for (final c in cases(v, 'valid')) {
      expect(
        _hex(
          propLinkProof(
            _unhex(c['game_key'] as String),
            _unhex(c['nonce'] as String),
            c['game_id'] as int,
            c['node_id'] as int,
          ),
        ),
        c['proof'],
        reason: c['name'] as String,
      );
    }
  });

  test('the MQTT ACL (as controller/deploy/atalaia.acl on the Pi)', () {
    final acl = (vectors['mqtt_acl'] as Map).cast<String, Object?>();
    expect(MqttAcl.field.rules.keys.toSet(), {
      ...(acl['users']! as List).cast<String>(),
      'controller',
    });
    for (final check in (acl['checks']! as List).cast<Map<String, dynamic>>()) {
      final user = check['user'] as String;
      final topic = check['topic'] as String;
      expect(
        MqttAcl.field.mayRead(user, topic),
        check['read'],
        reason: '$user reads $topic',
      );
      expect(
        MqttAcl.field.mayWrite(user, topic),
        check['write'],
        reason: '$user writes $topic',
      );
    }
  });

  test('the matching rules (as the Python runner checks them)', () {
    expect(mismatch({'a': 1}, {'a': 1, 'b': 2}), isNull);
    expect(mismatch({'a': 1}, {'a': 2}), isNotNull);
    expect(mismatch({'a': r'$absent'}, {'b': 1}), isNull);
    expect(mismatch({'a': r'$absent'}, {'a': null}), isNotNull);
    expect(mismatch({'a': r'$any'}, {'a': null}), isNull);
    expect(mismatch({'a': r'$any'}, <String, Object?>{}), isNotNull);
    expect(mismatch([1], [1, 2]), isNotNull);
    expect(
      mismatch(
        {
          r'$contains': [
            {'t': 2},
          ],
        },
        [
          {'t': 1},
          {'t': 2},
        ],
      ),
      isNull,
    );
    expect(
      mismatch(
        {
          r'$contains': [
            {'t': 3},
          ],
        },
        [
          {'t': 1},
        ],
      ),
      isNotNull,
    );
    expect(mismatch(1, true), isNotNull);
    expect(mismatch(null, 0), isNotNull);
    expect(substitute({'p': '/g/\${gid}/x', 'id': '\${gid}'}, {'gid': 7}), {
      'p': '/g/7/x',
      'id': 7,
    });
  });
}
