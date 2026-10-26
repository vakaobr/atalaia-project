// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The scenario validator and compiler on the Android field controller
// (lib/controller/scenarios, decision PE24): the phone reads the manifest's
// text (scenario_manifest.dart) and calls the C core's compiler
// (core/scenario/, decision PE24-109), the one the Pi calls too. Checked
// here: the shared rules (protocol/vectors/scenario.json, as controller/
// tests/test_scenarios.py reads them), the golden outputs
// (protocol/vectors/scenario_compile.json: the same problems, field.lua and
// mode.yaml byte for byte, and what the manifest reader reads from YAML
// texts), the data tree the phone hands the core, the Lua literals, and
// mutated manifests that must give problems, never an exception.

import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:atalaia_app/controller/scenarios/scenario_manifest.dart';
import 'package:atalaia_app/controller/scenarios/scenario_package.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';

Map<String, Object?> _json(String path) =>
    jsonDecode(File(path).readAsStringSync()) as Map<String, Object?>;

final Map<String, Object?> _shared = _json('../protocol/vectors/scenario.json');
final Map<String, Object?> _golden = _json(
  '../protocol/vectors/scenario_compile.json',
);

List<Map<String, Object?>> _cases(Map<String, Object?> file, String key) =>
    (file[key]! as List<Object?>).cast<Map<String, Object?>>();

/// A loaded value as the 'loads' vectors write it: typed.
Object? _typed(Object? v) => switch (v) {
  final bool b => {'bool': b},
  final int i => {'int': '$i'},
  final BigInt b => {'int': '$b'},
  final double d => {'float': pyFloatRepr(d)},
  final String s => {'str': s},
  null => {'null': null},
  final PyTimestamp t => {'timestamp': '$t'},
  final List<Object?> l => {'list': l.map(_typed).toList()},
  final Map<Object?, Object?> m => {
    'map': [
      for (final e in m.entries) [_typed(e.key), _typed(e.value)],
    ],
  },
  _ => throw StateError('no typed form for ${v.runtimeType}'),
};

/// The data tree with each {"alias": n} as the list or map it names, as the
/// 'loads' vectors write it.
Object? _expand(Object? v, List<Object?> shared) {
  final (kind, body) = (v! as Map<String, Object?>).entries
      .map((e) => (e.key, e.value))
      .single;
  switch (kind) {
    case 'alias':
      return shared[body! as int];
    case 'list':
      final out = <String, Object?>{};
      shared.add(out);
      out['list'] = [
        for (final x in body! as List<Object?>) _expand(x, shared),
      ];
      return out;
    case 'map':
      final out = <String, Object?>{};
      shared.add(out);
      out['map'] = [
        for (final pair in (body! as List<Object?>).cast<List<Object?>>())
          [_expand(pair[0], shared), _expand(pair[1], shared)],
      ];
      return out;
  }
  return v;
}

Object? _copy(Object? v) => switch (v) {
  final List<Object?> l => l.map(_copy).toList(),
  final Map<Object?, Object?> m => {
    for (final e in m.entries) e.key: _copy(e.value),
  },
  _ => v,
};

void main() {
  late AtalaiaCore core;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  group('protocol/vectors/scenario.json', () {
    test('valid manifests give no error and exactly their warnings', () {
      for (final c in _cases(_shared, 'valid')) {
        final manifest = c['manifest'];
        final got = {
          for (final p in validate(manifest, core)) (p.path, p.code, p.level),
        };
        final want = {
          for (final w in (c['warnings'] as List<Object?>? ?? const []))
            ((w! as Map<String, Object?>)['path'], w['code'], levelWarning),
        };
        expect(got, want, reason: c['name'] as String);
        compileScenario(manifest, core);
      }
    });

    test('invalid manifests give exactly their errors', () {
      for (final c in _cases(_shared, 'invalid')) {
        final manifest = c['manifest'];
        final got = {
          for (final p in errors(validate(manifest, core))) (p.path, p.code),
        };
        final want = {
          for (final e
              in (c['errors']! as List<Object?>).cast<Map<String, Object?>>())
            (e['path'], e['code']),
        };
        expect(got, want, reason: c['name'] as String);
        expect(
          () => compileScenario(manifest, core),
          throwsA(
            isA<ScenarioError>().having(
              (e) => e.problems,
              'problems',
              isNotEmpty,
            ),
          ),
        );
        for (final p in validate(manifest, core)) {
          expect(p.message, isNotEmpty);
          expect('$p', contains(p.code));
        }
      }
    });
  });

  group('protocol/vectors/scenario_compile.json', () {
    final cases = _cases(_golden, 'compile');

    test('has cases that compile and cases that do not', () {
      expect(cases.where((c) => c.containsKey('field_lua')), hasLength(17));
      expect(cases, hasLength(greaterThanOrEqualTo(20)));
    });

    for (final c in cases) {
      test(c['name']! as String, () {
        final text = c['manifest_text']! as String;
        if (c['manifest_error'] == true) {
          expect(() => loadManifest(text), throwsA(isA<ManifestError>()));
          return;
        }
        final manifest = loadManifest(text);
        final problems = [
          for (final p in validate(manifest, core)) [p.path, p.code, p.level],
        ];
        final want = [
          for (final p
              in (c['problems']! as List<Object?>).cast<Map<String, Object?>>())
            [p['path'], p['code'], p['level']],
        ];
        expect(problems, want);
        if (!c.containsKey('field_lua')) {
          expect(
            () => compileScenario(manifest, core),
            throwsA(isA<ScenarioError>()),
          );
          return;
        }
        final package = compileScenario(manifest, core);
        expect(package.fieldLua, c['field_lua']);
        expect(package.modeYaml, c['mode_yaml']);
        expect(package.files.keys, ['mode.yaml', 'field.lua']);
        expect(package.id, manifest['id']);
        // mode.yaml reads back, as PyYAML reads it, to the Pi's data.
        expect(
          jsonEncode(loadManifest(package.modeYaml)),
          jsonEncode(c['mode_yaml_data']),
        );
      });
    }

    test('the reader reads YAML as PyYAML does', () {
      for (final c in _cases(_golden, 'loads')) {
        final text = c['text']! as String;
        if (c['error'] == true) {
          expect(
            () => loadText(text),
            throwsA(isA<ManifestError>()),
            reason: text,
          );
        } else {
          expect(
            jsonEncode(_typed(loadText(text))),
            jsonEncode(c['data']),
            reason: text,
          );
        }
      }
    });

    test('what the reader read reaches the core as the same data tree', () {
      for (final c in _cases(_golden, 'loads')) {
        if (c['error'] == true) continue;
        final text = c['text']! as String;
        final tree = jsonDecode(utf8.decode(encodeTree(loadText(text))));
        expect(
          jsonEncode(_expand(tree, [])),
          jsonEncode(c['data']),
          reason: text,
        );
      }
    });
  });

  group('the data tree', () {
    test('a map two objectives share is written once, with an anchor', () {
      final points = <Object?, Object?>{'param': 'points'};
      final manifest = <Object?, Object?>{
        'id': 'org.test.shared',
        'version': '1',
        'name': 'Shared',
        'params': {
          'points': {'type': 'int', 'default': 3},
        },
        'nodes': {
          'a': {'role': 'objective'},
          'b': {'role': 'objective'},
        },
        'objectives': [
          {
            'id': 'one',
            'name': 'One',
            'type': 'capture_and_hold',
            'target': 'a',
            'effect': {'points': points},
          },
          {
            'id': 'two',
            'name': 'Two',
            'type': 'capture_and_hold',
            'target': 'b',
            'effect': {'points': points},
          },
        ],
      };
      final written = compileScenario(manifest, core).modeYaml;
      expect(written, contains('points: &id001\n'));
      expect(written, contains('points: *id001\n'));
    });

    test('half of a surrogate pair built in code is bad_unicode', () {
      final manifest = loadManifest(
        File('../controller/tests/scenarios/foxhound.yaml').readAsStringSync(),
      );
      manifest['name'] = 'X \ud83d';
      expect(
        [for (final p in validate(manifest, core)) (p.path, p.code)],
        [('name', 'bad_unicode')],
      );
      manifest['name'] = 'X 😀';
      expect(validate(manifest, core), isEmpty);
    });

    test('a manifest nested too deep is refused in words', () {
      Object? deep = 'x';
      for (var i = 0; i < 150; i++) {
        deep = [deep];
      }
      final problems = validate({'id': 'org.test.deep', 'extra': deep}, core);
      expect(
        [for (final p in problems) (p.path, p.code)],
        [('', 'bad_manifest')],
      );
    });

    test('a core without the compiler is refused', () {
      final stub = AtalaiaCore.open(stubLibraryPath());
      expect(() => validate({}, stub), throwsArgumentError);
    });
  });

  group('Lua literals', () {
    String luaValue(Object? v) => luaLiteral(v, core);

    test('every text is a quoted literal', () {
      expect(luaValue('a"b\\c\nd\re\tf'), r'"a\"b\\c\nd\re\tf"');
      expect(luaValue(']]--[['), '"]]--[["');
      expect(luaValue('\x00\x1b\x7f'), r'"\000\027\127"');
      expect(luaValue('Informações'), '"Informações"');
      expect(
        luaValue('\u202e\u2028'),
        r'"\226\128\174\226\128\168"',
      ); // bidi, line separator
      expect(luaValue('\ue000'), r'"\238\128\128"'); // private use
      expect(luaValue('😀'), '"😀"');
      expect(
        luaValue({
          'end': 1,
          'a b': true,
          'x': null,
          'n': [1, 2.5],
        }),
        '{ ["end"] = 1, ["a b"] = true, n = { 1, 2.5 } }',
      );
      expect(luaValue(38.0), '38.0');
      expect(luaValue(1e-05), '1e-05');
      expect(luaValue(1e16), '1e+16');
      expect(luaValue(-0.0), '-0.0');
      for (final bad in [
        double.nan,
        double.infinity,
        BigInt.two.pow(64),
        Object(),
      ]) {
        expect(() => luaValue(bad), throwsA(isA<LuaError>()));
      }
    });

    test("Python's float repr", () {
      final cases = <(double, String)>[
        (0.1, '0.1'),
        (100.0, '100.0'),
        (1234567890123456.0, '1234567890123456.0'),
        (1e16, '1e+16'),
        (0.0001, '0.0001'),
        (0.00001, '1e-05'),
        (1.5e-7, '1.5e-07'),
        (1e100, '1e+100'),
        (5e-324, '5e-324'),
        (1.7976931348623157e308, '1.7976931348623157e+308'),
        (0.30000000000000004, '0.30000000000000004'),
        (-2.5, '-2.5'),
      ];
      for (final (value, text) in cases) {
        // The reader's (the data tree's floats) and the core's (field.lua).
        expect(pyFloatRepr(value), text);
        expect(luaValue(value), text);
      }
    });
  });

  group('not a manifest', () {
    test('texts that are not manifests are refused', () {
      for (final text in [
        '- a\n- b\n',
        'id: [',
        'id: a\nid: b\n',
        'objectives:\n  - { id: a, id: b }\n',
        'x: ${'a' * 300000}',
        "id: !!python/object/apply:os.system ['true']\n",
        'id: x\n\tname: y\n',
      ]) {
        expect(
          () => loadManifest(text),
          throwsA(isA<ManifestError>()),
          reason: text,
        );
      }
      expect(validate([1], core).single.code, 'bad_manifest');
    });

    test('a manifest in JSON is a manifest too', () {
      final foxhound = loadManifest(
        File('../controller/tests/scenarios/foxhound.yaml').readAsStringSync(),
      );
      expect(validate(loadManifest(jsonEncode(foxhound)), core), isEmpty);
    });
  });

  test('any value anywhere is a problem, not an exception', () {
    // As controller/tests/test_scenarios.py mutates the vectors.
    final rng = Random(7);
    final values = <Object?>[
      null, 0, -1, 1.5, true, 'x', '', <Object?>[], <Object?, Object?>{}, //
      [1], {'a': 1}, 'a\nb', BigInt.from(10).pow(30), double.nan,
      ['nowhere'], {'team': 'red'},
    ];
    void mutate(Object? o, [int depth = 0]) {
      if (o is Map<Object?, Object?> && o.isNotEmpty) {
        final key = o.keys.elementAt(rng.nextInt(o.length));
        if (rng.nextDouble() < 0.3 || depth > 4) {
          o[key] = _copy(values[rng.nextInt(values.length)]);
        } else {
          mutate(o[key], depth + 1);
        }
      } else if (o is List<Object?> && o.isNotEmpty) {
        final i = rng.nextInt(o.length);
        if (rng.nextDouble() < 0.3 || depth > 4) {
          o[i] = _copy(values[rng.nextInt(values.length)]);
        } else {
          mutate(o[i], depth + 1);
        }
      }
    }

    final manifests = [
      for (final c in [
        ..._cases(_shared, 'valid'),
        ..._cases(_shared, 'invalid'),
      ])
        c['manifest'],
    ];
    for (var n = 0; n < 1000; n++) {
      final manifest = _copy(manifests[rng.nextInt(manifests.length)]);
      for (var k = 0; k < 1 + rng.nextInt(3); k++) {
        mutate(manifest);
      }
      try {
        compileScenario(manifest, core);
      } on ScenarioError {
        // Problems, as expected.
      }
    }
  });
}
