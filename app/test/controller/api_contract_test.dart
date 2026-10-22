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
// mqtt_acl checks run against MqttAcl.field (mqtt_broker.dart).

import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_mqtt.dart';
import 'package:atalaia_app/controller/prop_link.dart' show propLinkProof;
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/controller/mqtt_broker.dart';
import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
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
};

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

  for (final c in cases(vectors, 'cases')) {
    test(c['name'] as String, () async {
      var now = 0;
      final dir = Directory.systemTemp.createTempSync('atalaia-contract-');
      final config = ControllerConfig(
        persistGameKey: (c['persist_game_key'] as bool?) ?? true,
      );
      final radio = RecordingModem();
      final joinKey = _unhex((c['join_key'] as String?) ?? '');
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
        )..joinKey = joinKey;
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
      final saved = <String, Object?>{};
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
        final secret = token == 'bad' ? 'not-a-token' : tokens[token];
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
          if (token == 'bad') {
            request.headers.set('Authorization', 'Bearer not-a-token');
          } else if (token != 'none') {
            request.headers.set('Authorization', 'Bearer ${tokens[token]}');
          }
          if (req.containsKey('body')) {
            request.headers.contentType = ContentType.json;
            request.write(jsonEncode(req['body']));
          }
          final response = await request.close();
          final text = await utf8.decodeStream(response);
          final where = 'step $i: $method $path';
          expect(response.statusCode, step['status'], reason: '$where: $text');
          final body = jsonDecode(text);
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
