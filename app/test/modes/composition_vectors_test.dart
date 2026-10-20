// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// How the parts of a game compose (protocol/vectors/composition.yaml, the
// same vectors as simulator/tests/test_scenario.py): main modes, modifiers,
// role packages and scenarios (decision P4R7) in the Dart test runner's
// compose (test/support/mode_runner.dart), the port of mode.py that runs the
// mode tests through the core.

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:yaml/yaml.dart';

import '../support/mode_runner.dart';

void main() {
  final vectors =
      plain(
            loadYaml(
              File('../protocol/vectors/composition.yaml').readAsStringSync(),
            ),
          )!
          as Map<String, Object?>;

  Mode package(String id, Map<String, Object?> spec) {
    final kind = (spec['kind'] ?? 'mode') as String;
    final roles = {
      for (final r in spec['roles']! as List) '$r': <String, Object?>{},
    };
    final params = {
      for (final p in spec['params']! as List)
        '$p': <String, Object?>{'type': 'int', 'default': 1},
    };
    checkManifest({'id': id, 'kind': kind, 'roles': roles}, id);
    final node = spec['node_lua'] == true;
    final field = spec['field_lua'] == true;
    checkFiles(kind, node, field, id);
    return Mode(
      dir: Directory(id),
      id: id,
      name: id,
      kind: kind,
      roles: roles,
      params: params,
      nodeScript: node ? '-- node $id\n' : '',
      fieldScript: field ? '-- field $id\n' : null,
    );
  }

  final packages = {
    for (final e in (vectors['packages']! as Map<String, Object?>).entries)
      e.key: package(e.key, e.value! as Map<String, Object?>),
  };

  Mode composeId(String id) {
    final parts = [for (final p in id.split('+')) packages[p]!];
    return compose(parts.first, parts.sublist(1));
  }

  group('valid', () {
    for (final c in (vectors['valid']! as List).cast<Map<String, Object?>>()) {
      test(c['name']! as String, () {
        final game = composeId(c['id']! as String);
        expect(game.id, c['id']);
        expect(game.roles.keys.toList(), c['roles']);
        if (c.containsKey('main_id')) expect(game.mainId, c['main_id']);
        final params = game.resolveParams(const {}, const ['red', 'blue']);
        for (final e in (c['joins']! as Map<String, Object?>).entries) {
          final join = e.value! as List;
          expect(game.nodeModeId(e.key), join[0], reason: e.key);
          expect(
            game.paramsFor(e.key, params).keys.toSet(),
            (join[1] as List).toSet(),
            reason: e.key,
          );
        }
        final fields = [
          for (final line in (game.fieldScript ?? '').split('\n'))
            if (line.startsWith('-- field ')) line.split(' ')[2],
        ];
        expect(fields, c['fields']);
      });
    }
  });

  group('invalid', () {
    for (final c
        in (vectors['invalid']! as List).cast<Map<String, Object?>>()) {
      test(c['name']! as String, () {
        expect(
          () => composeId(c['id']! as String),
          throwsA(
            isA<ModeError>().having(
              (e) => e.message,
              'message',
              contains(c['error']! as String),
            ),
          ),
        );
      });
    }
  });

  group('packages_invalid', () {
    for (final c
        in (vectors['packages_invalid']! as List)
            .cast<Map<String, Object?>>()) {
      test(c['name']! as String, () {
        expect(
          () => package('org.t.bad', c['package']! as Map<String, Object?>),
          throwsA(
            isA<ModeError>().having(
              (e) => e.message,
              'message',
              contains(c['error']! as String),
            ),
          ),
        );
      });
    }
  });
}
