// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The boxes' modules and outputs on the phone controller
// (lib/controller/controller_outputs.dart; draft RFC "The expansion port",
// increment 3): the Pi's controller/tests/test_outputs.py, and node.modules'
// text and CMD 12's params against the shared vectors
// (protocol/vectors/expansion.json, protocol/vectors/cmd.json).

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/controller/controller_outputs.dart';
import 'package:atalaia_app/controller/controller_scenarios.dart';
import 'package:atalaia_app/protocol/capability_types.g.dart';
import 'package:flutter_test/flutter_test.dart';

const zone = {
  'requires': ['team_input'],
  'optional': ['team_display', 'audio', 'display'],
};
const target = {
  'requires': ['hit', 'led'],
  'optional': ['display', 'audio', 'smell'],
};

/// Bomb's role since increment 4: optional outputs, and the ones it switches.
const bomb = {
  'requires': ['team_input'],
  'optional': ['keypad', 'audio', 'led', 'display', 'output'],
  'outputs': ['smoke', 'siren'],
};

/// A role that cannot play without an output.
const alarm = {
  'requires': ['team_input', 'output'],
  'outputs': ['siren'],
};

Map<String, Object?> node(
  int n,
  String role,
  Object? caps, [
  Object? modules,
]) => {
  'node': n,
  'name': 'box-$n',
  'role': role,
  'capabilities': caps,
  'modules': modules,
};

Map<String, List<Map<String, Object?>>> check(
  List<Map<String, Object?>> nodes,
) => checkNodes(
  nodes,
  (r) => {'zone': zone, 'target': target, 'bomb': bomb, 'alarm': alarm}[r],
);

void main() {
  test('role names are met by their types (capabilities.yaml role_names)', () {
    expect(capabilityRoleNames, {
      'team_input': ['button', 'keypad', 'nfc'],
      'team_display': ['led', 'display'],
    });
    for (final (types, name, want) in [
      ({'button'}, 'team_input', true),
      ({'keypad'}, 'team_input', true),
      ({'nfc'}, 'team_input', true),
      ({'display', 'led'}, 'team_input', false),
      ({'led'}, 'team_display', true),
      ({'display'}, 'team_display', true),
      ({'audio'}, 'team_display', false),
      ({'hit'}, 'hit', true),
      ({'button'}, 'hit', false),
      ({'button'}, 'smell', null),
      (<String>{}, 'gps', false),
    ]) {
      expect(hasCapability(types, name), want, reason: '$name $types');
    }
    expect(
      typesOf([
        capabilityTypeIds['button'],
        capabilityTypeIds['output'],
        0,
        200,
        true,
        'x',
      ]),
      {'button', 'output'},
    );
    expect(typesOf(null), <String>{});
  });

  group('start check', () {
    test('a box without what its role requires', () {
      final out = check([
        node(4, 'zone', [1, 3, 5]),
        node(5, 'zone', [3, 12]),
        node(6, 'target', [3, 4, 5]),
      ]);
      expect(out['missing_caps'], [
        {
          'node': 5,
          'name': 'box-5',
          'role': 'zone',
          'capability': 'team_input',
        },
        {'node': 6, 'name': 'box-6', 'role': 'target', 'capability': 'hit'},
      ]);
      final w = out['warnings']!.single;
      expect(w['node'], 5);
      expect(w['capabilities'], ['audio']);
      expect(out['warnings']!.single['code'], 'optional_caps');
    });

    test('nodes that report nothing are not checked', () {
      final out = check([
        node(4, 'zone', []),
        node(5, 'zone', null),
        node(6, 'target', [0, 99]),
        node(7, 'nosuchrole', [3]),
      ]);
      expect(out, {
        'missing_caps': <Object?>[],
        'warnings': <Object?>[],
        'not_checked': <Object?>[],
      });
    });

    test('a simple output counts and is not checked', () {
      final mods = modulesOf('g46:servo:siren;5c:out4/1.0.0:strobe,smoke');
      final out = check([
        node(4, 'zone', [1, 3, 5, 11], mods),
      ]);
      expect(out['missing_caps'], isEmpty);
      expect(
        out['not_checked']!.map((u) => '${u['node']}:${u['capability']}'),
        ['4:siren'],
      );
      expect(
        out['not_checked']!.single['text'],
        'siren on box-4: not checked (simple output)',
      );
    });

    test("a role's outputs (increment 4, outputs.py)", () {
      final b = capabilityTypeIds['button']!, o = capabilityTypeIds['output']!;
      String codes(Map<String, List<Map<String, Object?>>> out) =>
          out['warnings']!
              .map((w) => '${w['code']}:${w['node']}:${w['capabilities']}')
              .join(' ');
      var out = check([
        node(4, 'bomb', [b]),
        node(5, 'alarm', [b]),
      ]);
      expect(out['missing_caps'], [
        {'node': 5, 'name': 'box-5', 'role': 'alarm', 'capability': 'output'},
      ]);
      expect(
        codes(out),
        'optional_caps:4:[keypad, audio, led, display, output]',
      );
      final horn = modulesOf('g46:servo:horn');
      out = check([
        node(4, 'bomb', [
          b,
          capabilityTypeIds['keypad']!,
          capabilityTypeIds['audio']!,
          capabilityTypeIds['led']!,
          capabilityTypeIds['display']!,
          o,
        ], horn),
        node(5, 'alarm', [b, o], horn),
      ]);
      expect(out['missing_caps'], isEmpty);
      expect(codes(out), 'outputs:4:[smoke, siren] outputs:5:[siren]');
      expect(
        out['warnings']!.first['text'],
        'box-4 (bomb) has none of the outputs the mode would switch: smoke, siren',
      );
      out = check([
        node(4, 'bomb', [b, o], modulesOf('g46:servo:smoke')),
        node(5, 'alarm', [b, o], null),
      ]);
      expect(out['warnings']!.map((w) => w['code']), ['optional_caps']);
      final lost = markLost(
        modulesOf('5c:out4/1.0.0:siren'),
        '5c:out4/1.0.0:siren',
      );
      out = check([
        node(5, 'alarm', [b, o], lost),
      ]);
      expect(codes(out), 'outputs:5:[siren]');
    });

    test("a scenario's triggers count as the role's outputs (outputs.py)", () {
      const objective = {
        'requires': ['team_input'],
        'optional': ['keypad', 'display'],
      };
      final b = capabilityTypeIds['button']!, o = capabilityTypeIds['output']!;
      final k = capabilityTypeIds['keypad']!, d = capabilityTypeIds['display']!;
      expect(withOutputs(objective, ['siren', 'horn', 'siren']), {
        'requires': ['team_input'],
        'optional': ['keypad', 'display', 'output'],
        'outputs': ['siren', 'horn'],
      });
      expect(identical(withOutputs(objective, const []), objective), isTrue);
      expect(identical(withOutputs(objective, null), objective), isTrue);
      expect((withOutputs(bomb, ['horn', 'smoke'])! as Map)['outputs'], [
        'smoke',
        'siren',
        'horn',
      ]);
      expect((withOutputs(alarm, ['horn'])! as Map)['optional'], isEmpty);
      expect(withOutputs(null, ['horn']), {
        'optional': ['output'],
        'outputs': ['horn'],
      });
      Map<String, Object?> scenarioNode(
        int n,
        Object? caps,
        Object? modules,
        List<String> fns,
      ) => {...node(n, 'objective', caps, modules), 'outputs': fns};
      Map<String, List<Map<String, Object?>>> run(
        List<Map<String, Object?>> nodes,
      ) => checkNodes(nodes, (r) => {'objective': objective}[r]);
      final strobe = modulesOf('g46:servo:strobe');
      var out = run([
        scenarioNode(4, [b, k, d, o], strobe, ['siren', 'horn']),
        scenarioNode(5, [b, k, d], null, ['horn']),
        scenarioNode(6, [b, k, d, o], strobe, []),
      ]);
      expect(out['missing_caps'], isEmpty);
      expect(
        out['warnings']!
            .map((w) => '${w['code']}:${w['node']}:${w['capabilities']}')
            .join(' '),
        'outputs:4:[siren, horn] optional_caps:5:[output]',
      );
      expect(
        out['warnings']!.first['text'],
        'box-4 (objective) has none of the outputs the mode would switch: '
        'siren, horn',
      );
      out = run([
        scenarioNode(
          4,
          [b, k, d, o],
          modulesOf('g46:servo:horn'),
          ['siren', 'horn'],
        ),
      ]);
      expect(out['warnings'], isEmpty);
    });
  });

  test("a compiled scenario's outputs in its meta (scenario_service.py)", () {
    expect(
      boxOutputs({
        'alpha': ['siren', 'horn'],
        'bravo': <Object?>[],
        'c': 'x',
        'd': [1, 'light'],
      }),
      {
        'alpha': ['siren', 'horn'],
        'd': ['light'],
      },
    );
    expect(boxOutputs(null), isEmpty);
    const text =
        "id: org.club.s\nversion: '1'\nkind: scenario\nname: S\nscenario:\n"
        '  nodes: {alpha: {role: objective}}\n  objectives: []\n'
        '  outputs: {alpha: [siren, horn]}\n';
    final meta = ScenarioMeta.parse(text)!;
    expect(meta.nodeOutputs('alpha'), ['siren', 'horn']);
    expect(meta.nodeOutputs('bravo'), isEmpty);
    expect(meta.nodeOutputs(null), isEmpty);
    final before = ScenarioMeta.parse(
      text.replaceFirst('  outputs: {alpha: [siren, horn]}\n', ''),
    )!;
    expect(before.outputs, isEmpty);
  });

  test('modules and a lost one', () {
    final mods = modulesOf('g46:servo:siren;58:target/1.0.0:hit')!;
    expect(mods.first, {
      'address': 'g46',
      'model': 'servo',
      'fw': null,
      'caps': ['siren'],
      'feedback': false,
    });
    expect(modulesOf('nonsense'), isNull);
    expect(modulesOf(5), isNull);
    final lost = markLost(mods, '58:target/1.0.0:hit')!;
    expect(lost.map((m) => m['lost'] ?? false), [false, true]);
    expect(markLost(mods, '5c:out4/1.0.0:strobe'), isNull);
    expect(outputCaps(lost), {'siren'});
    expect(simpleOutputs(lost), ['siren']);
  });

  test("node.modules' text: the shared vectors", () {
    final v = jsonDecode(
      File('../protocol/vectors/expansion.json').readAsStringSync(),
    ) as Map;
    final mods = v['modules_text']! as Map;
    for (final c in mods['valid']! as List) {
      final got = parseModules(c['text'] as String);
      expect(jsonEncode(got), jsonEncode(c['modules']), reason: '${c['text']}');
    }
    for (final c in mods['invalid']! as List) {
      expect(
        () => parseModules(c['text'] as String),
        throwsFormatException,
        reason: '${c['text']}',
      );
    }
  });

  test("CMD 12's params: the shared vectors (cmd.json output_params)", () {
    final v = jsonDecode(
      File('../protocol/vectors/cmd.json').readAsStringSync(),
    ) as Map;
    final p = v['output_params']! as Map;
    for (final c in p['valid']! as List) {
      expect(outputParamsProblem(c['params']), isNull, reason: '${c['name']}');
    }
    for (final c in p['refused']! as List) {
      expect(
        outputParamsProblem(c['params']),
        c['reason'],
        reason: '${c['name']}',
      );
    }
  });

  test('the controller sets src and the GM default', () {
    expect(
      outputParams({
        'capability': 'siren',
        'act': 'on',
        'src': 'field',
      }, 'gm').$1,
      {'capability': 'siren', 'act': 'on', 'ms': 5000, 'src': 'gm'},
    );
    expect(outputParams({'capability': 'siren', 'act': 'on'}, 'field'), (
      null,
      'ms is required for on, pulse and pattern',
    ));
    expect(
      outputParams({
        'capability': 'siren',
        'act': 'off',
        'ms': 3,
        'on_ms': 9,
      }, 'gm').$1,
      {'capability': 'siren', 'act': 'off', 'src': 'gm'},
    );
    expect(
      outputParams({
        'capability': 's',
        'act': 'pulse',
        'ms': 9,
        'on_ms': 5,
      }, 'gm').$1,
      {'capability': 's', 'act': 'pulse', 'ms': 9, 'src': 'gm'},
    );
    expect(outputParams(['siren'], 'gm').$1, isNull);
  });

  test('the rate limit', () {
    final rate = OutputRateLimit();
    expect(rate.waitMs(4, 'on', 0), 0);
    rate.sent(4, 'on', 1000);
    expect(rate.waitMs(4, 'pulse', 2000), 1000);
    expect(rate.waitMs(4, 'off', 2000), 0);
    expect(rate.waitMs(5, 'on', 2000), 0);
    rate.sent(4, 'off', 2500); // an off never moves the next start
    expect(rate.waitMs(4, 'on', 3000), 0);
  });
}
