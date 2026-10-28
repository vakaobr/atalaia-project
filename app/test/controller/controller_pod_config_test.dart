// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The I/O pod's settings over the radio on the phone controller (protocol/
// pod-config.md, decision PODC): the shared vectors (protocol/vectors/
// pod_config.json, which the pod's C and the Pi controller check too), then
// the service and its API over the real engine with a recording radio: the
// push as CMD pod (opcode 10) to the phone's node id, the pod's answer as
// node.setup_applied, the resends, the end of the tries and what is refused.
// The Pi's twin is controller/tests/test_pod_config.py.
import 'dart:convert';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_pod_config.dart';
import 'package:atalaia_app/controller/field_controller.dart' show cmdPod;
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/recording_radio.dart';
import '../support/vectors.dart';

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  group('the shared vectors', () {
    final v = loadVectors('pod_config.json');
    final steps = cases(v, 'steps');

    test(
      'every step: the pod\'s answer, its stored form, the CMD\'s bytes',
      () {
        expect(steps.length, greaterThanOrEqualTo(15));
        final model = PodSettingsModel();
        for (final s in steps) {
          final name = s['name'];
          final params = (s['params'] as Map).cast<String, Object?>();
          expect(model.handle(params), s['result'], reason: '$name');
          expect(model.stored(), s['stored'], reason: '$name');
          final cmd = RfCmd(
            cmd: v['opcode'] as int,
            params: params,
            dest: v['dest'] as int,
          );
          expect(
            [
              for (final b in cmd.encode()) b.toRadixString(16).padLeft(2, '0'),
            ].join(),
            s['cmd_cbor'],
            reason: '$name',
          );
          // The controller refuses what the pod would refuse.
          if (s['result'] == 'refused') {
            expect(
              () => checkPodParams(params),
              throwsA(isA<ControllerError>()),
            );
          } else {
            checkPodParams(params);
          }
        }
      },
    );

    test('the longest settings fit a CMD', () {
      final last = (steps.last['params'] as Map).cast<String, Object?>();
      expect(utf8.encode(jsonEncode(last)).length, lessThanOrEqualTo(127));
    });

    test('a body becomes params', () {
      expect(podParamsFromBody({'bright': 5}, 77), {
        'v': 1,
        'rev': 77,
        'bright': 5,
      });
      expect(podParamsFromBody({'bright': 5, 'rev': 9}, 77)['rev'], 9);
      for (final bad in <Map<String, Object?>>[
        {},
        {'rev': 3},
        {'led': 3},
        {'bright': 101},
        {
          'btn': ['red'],
        },
        {
          'btn': ['red', 'x', '', ''],
        },
        {'tamper': 'yes'},
        {'vol': true},
      ]) {
        expect(
          () => podParamsFromBody(bad, 77),
          throwsA(isA<ControllerError>()),
          reason: '$bad',
        );
      }
    });
  });

  group('the service', () {
    late ControllerEngine engine;
    late ControllerPodConfig pods;
    late RecordingRadio radio;
    late ControllerApi api;
    late int gameId;
    var wall = 1000000.0;
    final messages = <Map<String, Object?>>[];

    setUp(() {
      wall = 1000000.0;
      messages.clear();
      radio = RecordingRadio();
      engine = ControllerEngine(
        core: core,
        transport: radio,
        wallSeconds: () => wall,
      );
      pods = ControllerPodConfig(engine);
      engine.addListener(messages.add);
      api = ControllerApi(engine, gmToken: 'gm', readToken: 'rd');
      final game = engine.createGame({
        'name': 'pods',
        'mode_id': 'org.atalaia.domination',
        'teams': ['red', 'blue'],
        'assignments': {'4': 'zone', '5': 'zone'},
      });
      gameId = game['id']! as int;
    });
    tearDown(() => engine.close());

    RfHeader hdr(int source, int seq, int type) => RfHeader.v1(
      gameId: gameId,
      source: source,
      seq: seq,
      hopLimit: 2,
      type: type,
    );

    void hello(int node, int platform) => engine.onPacket(
      hdr(node, 0, RfType.hello),
      RfHello(
        nodeName: 'n-$node',
        platform: platform,
        fwVersion: '0.3.0',
        coreVersion: '0.3.0',
        tier: 0,
        capabilities: const [0],
        transports: 1,
        batteryPct: 80,
        epoch: 1,
      ).encode(),
      epoch: 1,
    );

    /// node.setup_applied, as the phone sends it when its pod took the settings.
    void applied(int node, int rev, int seq, {String kind = 'pod_config'}) {
      final ev = core.encodeEvent(
        node: node,
        seq: seq,
        tMs: 10,
        type: 'node.setup_applied',
        team: 0,
        squad: 0,
        prio: 1,
        dataJson: '{"kind":"$kind","rev":$rev}',
      );
      engine.onPacket(hdr(node, seq, RfType.event), ev.bytes!, epoch: 1);
    }

    List<RfCmd> podCmds() => [
      for (final (t, p) in radio.sent)
        if (t == RfType.cmd) RfCmd.decode(p),
    ].where((c) => c.cmd == cmdPod).toList();

    ApiResponse call(String method, String path, [Object? body, String? as]) =>
        api.handle(
          method,
          Uri.parse(path),
          authorization: 'Bearer ${as ?? 'gm'}',
          body: body == null ? '' : jsonEncode(body),
        );

    test('the whole way', () {
      hello(4, 3); // a phone
      hello(5, 1); // a box
      final st = call('GET', '/api/v1/pod-config').body! as Map;
      expect([for (final n in st['nodes'] as List) (n as Map)['node_id']], [4]);
      expect(st['colours'], podColours);
      expect(st['buttons'], 4);
      expect(st['pushes'], isEmpty);
      final r = call('POST', '/api/v1/pod-config/4', {
        'btn': ['red', '', '', 'blue'],
        'bright': 60,
      });
      expect(r.status, 200, reason: '${r.body}');
      final push = r.body! as Map;
      expect([push['node_id'], push['state'], push['tries']], [4, 'sent', 1]);
      expect(push['rev'], 1000000); // seconds since 1970
      // CMD pod (opcode 10) to the phone's node id alone.
      final cmds = podCmds();
      expect(cmds, hasLength(1));
      expect(cmds.single.dest, 4);
      expect(cmds.single.params, {
        'v': 1,
        'rev': 1000000,
        'btn': ['red', '', '', 'blue'],
        'bright': 60,
      });
      // The pod took it: the phone says so over the radio.
      applied(4, 1000000, 1);
      expect(pods.pushes[4]!['state'], 'applied');
      expect(messages.any((m) => m['type'] == 'pod_config'), isTrue);
      // The next push goes above the last rev even in the same second.
      expect(
        (call('POST', '/api/v1/pod-config/4', {'vol': 30}).body! as Map)['rev'],
        1000001,
      );
      // Another rev, another kind: nothing changes.
      applied(4, 5, 2);
      applied(4, 1000001, 3, kind: 'mode');
      expect(pods.pushes[4]!['state'], 'sent');
      applied(4, 1000001, 4);
      expect(pods.pushes[4]!['state'], 'applied');
    });

    test('resends, then no answer; a late answer is still taken', () {
      hello(4, 3);
      expect(call('POST', '/api/v1/pod-config/4', {'vol': 30}).status, 200);
      pods.tick();
      expect(podCmds(), hasLength(1)); // too soon
      var n = 1;
      for (final wait in [8, 16, 32, 64, 128]) {
        wall += wait;
        pods.tick();
        expect(podCmds(), hasLength(++n), reason: 'after $wait s');
        expect(pods.pushes[4]!['state'], 'sent');
      }
      expect(podCmds().map((c) => jsonEncode(c.params)).toSet(), hasLength(1));
      wall += 128;
      pods.tick();
      expect(podCmds(), hasLength(6));
      expect(pods.pushes[4]!['state'], 'no_answer');
      applied(4, pods.pushes[4]!['rev']! as int, 1);
      expect(pods.pushes[4]!['state'], 'applied');
    });

    test('an answer stops the resends; cancel stops them too', () {
      hello(4, 3);
      final rev =
          (call('POST', '/api/v1/pod-config/4', {'vol': 30}).body!
                  as Map)['rev']!
              as int;
      applied(4, rev, 1);
      wall += 500;
      pods.tick();
      expect(podCmds(), hasLength(1));
      call('POST', '/api/v1/pod-config/4', {'vol': 31});
      expect((call('DELETE', '/api/v1/pod-config').body! as Map)['cancelled'], [
        4,
      ]);
      wall += 500;
      pods.tick();
      expect(podCmds(), hasLength(2));
      expect(pods.pushes[4]!['state'], 'cancelled');
    });

    test('refusals', () {
      // No phone has said hello yet: nothing to send to.
      expect(call('POST', '/api/v1/pod-config/4', {'vol': 30}).status, 404);
      hello(4, 3);
      hello(5, 1);
      for (final (name, path, body, code) in <(String, String, Object, int)>[
        ('a box is not a phone', '/api/v1/pod-config/5', {'vol': 30}, 404),
        ('an unknown node', '/api/v1/pod-config/9', {'vol': 30}, 404),
        ('never broadcast', '/api/v1/pod-config/65535', {'vol': 30}, 400),
        ('nothing to set', '/api/v1/pod-config/4', <String, Object?>{}, 400),
        (
          'a bad colour',
          '/api/v1/pod-config/4',
          {
            'btn': ['red', 'pink-ish', '', ''],
          },
          400,
        ),
        ('out of range', '/api/v1/pod-config/4', {'bright': 200}, 400),
        ('unknown setting', '/api/v1/pod-config/4', {'leds': 12}, 400),
      ]) {
        expect(call('POST', path, body).status, code, reason: name);
      }
      expect(podCmds(), isEmpty);
      // The GM's alone.
      expect(
        call('POST', '/api/v1/pod-config/4', {'vol': 3}, 'rd').status,
        403,
      );
      expect(call('GET', '/api/v1/pod-config', null, 'rd').status, 403);
    });

    test('not during a game', () {
      hello(4, 3);
      engine.startGame(gameId, force: true);
      final r = call('POST', '/api/v1/pod-config/4', {'vol': 30});
      expect(r.status, 409);
      expect('${(r.body! as Map)['detail']}', contains('before a game starts'));
      expect(podCmds(), isEmpty);
    });

    test('a mode script cannot send it', () {
      hello(4, 3);
      expect(
        call('POST', '/api/v1/nodes/4/cmd', {
          'cmd': 'pod',
          'params': {'v': 1, 'rev': 5, 'vol': 1},
        }).status,
        400,
      );
      expect(podCmds(), isEmpty);
    });
  });
}
