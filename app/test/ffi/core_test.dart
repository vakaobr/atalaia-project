// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The real core through the bindings: the same shared vectors the C tests
// and the simulator check (events, player tags), the screen-template helpers
// and a node running a real mode script. The full mode tests are in
// test/modes/mode_tests_test.dart.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/ffi/callbacks.dart';
import 'package:atalaia_app/ffi/core_node.dart';
import 'package:atalaia_app/ffi/native_types.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

import '../support/core_libs.dart';
import '../support/event_schema.dart';
import '../support/mode_runner.dart' show plain;
import '../support/vectors.dart';

void main() {
  late AtalaiaCore core;

  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  test('the version is the one core/CMakeLists.txt declares', () {
    final cmake = File('../core/CMakeLists.txt').readAsStringSync();
    final declared = RegExp(
      r'project\(atalaia_core VERSION (\S+)',
    ).firstMatch(cmake)!.group(1);
    expect(core.version, declared);
  });

  group('event vectors (protocol/vectors/events.yaml) through the C codec', () {
    final doc =
        plain(
              loadYaml(
                File('../protocol/vectors/events.yaml').readAsStringSync(),
              ),
            )
            as Map<String, Object?>;
    final schema = EventSchema.load();
    for (final c in (doc['valid']! as List).cast<Map<String, Object?>>()) {
      test(c['name']! as String, () {
        final ev = c['event']! as Map<String, Object?>;
        final type = ev['type']! as String;
        final prio = ev.containsKey('prio')
            ? prioNames.indexOf(ev['prio']! as String)
            : schema.defaultPrio(type);
        final encoded = core.encodeEvent(
          node: ev['node']! as int,
          seq: ev['seq']! as int,
          tMs: ev['t']! as int,
          type: type,
          team: (ev['team'] as int?) ?? 0,
          squad: (ev['squad'] as int?) ?? 0,
          prio: prio,
          dataJson: ev.containsKey('data') ? jsonEncode(ev['data']) : null,
        );
        expect(encoded.error, isNull);
        expect(
          hexEncode(encoded.bytes!),
          (c['cbor']! as String).replaceAll(' ', ''),
        );
      });
    }
  });

  test('the codec refuses what cannot travel, and says why', () {
    final broken = core.encodeEvent(
      node: 1,
      seq: 1,
      tMs: 0,
      type: 'zone.captured',
      team: 1,
      squad: 0,
      prio: 1,
      dataJson: '{"team":',
    );
    expect(broken.bytes, isNull);
    expect(broken.error, isNotEmpty);
    final huge = core.encodeEvent(
      node: 1,
      seq: 1,
      tMs: 0,
      type: 'gm.message',
      team: 0,
      squad: 0,
      prio: 1,
      dataJson: jsonEncode({'text': 'x' * 300}),
    );
    expect(huge.size, greaterThan(rfPayloadMax));
  });

  group('nfc.tag data from the core (protocol/vectors/tag.json)', () {
    final v = loadVectors('tag.json');
    final key = hexDecode(v['game_key'] as String);
    final uid = hexDecode(v['uid'] as String);
    final teams = (v['teams'] as List<dynamic>).cast<String>();
    for (final c in cases(v, 'events')) {
      test(c['name'] as String, () {
        final payload = c['payload'] as String?;
        expect(
          core.tagEventJson(
            uid: uid,
            payload: payload == null ? null : hexDecode(payload),
            gameId: v['game_id'] as int,
            gameKey: c['game_key'] == true ? key : null,
            teams: teams,
          ),
          c['json'],
        );
      });
    }
  });

  test('screen templates: the core parses, refuses and fills in', () {
    final countdown = File(
      '../modes/bomb/assets/screens/countdown.yaml',
    ).readAsStringSync();
    expect(core.checkScreen(countdown), isNull);
    expect(core.checkScreen('template: x\nwidgets: 3\n'), isNotNull);
    expect(
      core.screenText('{left} s left', {'left': 42}, {'fuse_s': 60}),
      '42 s left',
    );
  });

  test('a node runs a real mode script: Domination captures and scores', () {
    final events = <EmittedEvent>[];
    final commands = <NodeCommand>[];
    final node = CoreNode.create(
      core,
      NodeSpec(
        source: File('../modes/domination/node.lua').readAsStringSync(),
        chunkName: '@domination/node.lua',
        params: const {
          'capture_hold_ms': 3000,
          'tick_s': 10,
          'points_per_tick': 1,
        },
      ),
      handlers: NodeHandlers(onEvent: events.add, onCommand: commands.add),
    );
    addTearDown(node.close);
    expect(node.loaded, isTrue, reason: node.lastError);
    expect(
      node.input('game.start', {'preset': 'org.atalaia.domination'}),
      isTrue,
    );
    expect(commands.last.args.first, 'standby');
    for (var ms = 250; ms <= 3000; ms += 250) {
      node.advance(ms);
      node.input('team_input.hold', {'team': 'red', 'ms': ms});
    }
    final captured = events.singleWhere((e) => e.type == 'zone.captured');
    expect(captured.team, 1);
    expect(captured.tMs, 3000);
    expect(captured.prioName, 'normal');
    node.advance(60000);
    expect(node.score('red'), 6);
    expect(node.score('blue'), 0);
    expect(node.memUsed, greaterThan(0));
    expect(node.memUsed, lessThan(256 * 1024));
    expect(commands.last.tMs, 60000);
  });

  test(
    'a script that fails to compile leaves the node halted with the error',
    () {
      final node = CoreNode.create(
        core,
        const NodeSpec(
          source: 'this is not lua',
          chunkName: '@broken/node.lua',
        ),
      );
      addTearDown(node.close);
      expect(node.loaded, isFalse);
      expect(node.status, NodeStatus.halted);
      expect(node.lastError, contains('broken/node.lua'));
    },
  );

  test('the sandbox has no io, os or package', () {
    final logs = <String>[];
    final node = CoreNode.create(
      core,
      const NodeSpec(
        source:
            'log(tostring(io) .. " " .. tostring(os) .. " " .. tostring(package))',
        chunkName: '@sandbox.lua',
      ),
      handlers: NodeHandlers(onLog: logs.add),
    );
    addTearDown(node.close);
    expect(logs, ['nil nil nil']);
  });
}
