// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The registration import's format on the phone controller
// (lib/controller/registration_import.dart) against the shared cases
// protocol/vectors/registration_import.json, which the Pi's and the site
// server's import_format.py runs too (controller/tests/test_import_vectors.py):
// one list reads the same everywhere. The endpoint's own cases are in
// controller_api.json (api_contract_test.dart).

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/registration_import.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

Uint8List _dataOf(Map<String, dynamic> c) {
  if (c.containsKey('data')) {
    return Uint8List.fromList(utf8.encode(c['data'] as String));
  }
  if (c.containsKey('data_hex')) {
    final hex = c['data_hex'] as String;
    return Uint8List.fromList([
      for (var i = 0; i < hex.length; i += 2)
        int.parse(hex.substring(i, i + 2), radix: 16),
    ]);
  }
  final g = c['data_gen'] as Map<String, dynamic>;
  return Uint8List.fromList(
    utf8.encode(
      '${g['head']}${(g['unit'] as String) * (g['times'] as int)}${g['tail'] ?? ''}',
    ),
  );
}

void main() {
  final vectors = loadVectors('registration_import.json');
  final base = vectors['rules'] as Map<String, dynamic>;

  test('the shared cases (protocol/vectors/registration_import.json)', () {
    final list = cases(vectors, 'cases');
    expect(list.length, greaterThan(40));
    for (final c in list) {
      final r = {...base, ...((c['rules'] as Map<String, dynamic>?) ?? {})};
      final rules = ImportRules(
        teams: (r['teams'] as List).cast<String>(),
        federation: r['federation'] as String,
        predeclareReplicas: r['predeclare_replicas'] as bool,
        classes: (r['classes'] as List).cast<String>(),
        maxReplicas: r['max_replicas'] as int,
      );
      final want = c['expect'] as Map<String, dynamic>;
      final name = c['name'] as String;
      final ParsedImport parsed;
      try {
        parsed = parseImport(_dataOf(c), c['format']);
      } on ImportFileError catch (e) {
        expect(want['error'], e.code, reason: name);
        expect(want['line'], e.line, reason: '$name (line)');
        continue;
      }
      expect(want.containsKey('error'), isFalse, reason: name);
      expect(parsed.format, want['format'], reason: name);
      expect(parsed.columns, want['columns'], reason: name);
      if (want.containsKey('row_count')) {
        expect(parsed.rows.length, want['row_count'], reason: name);
        continue;
      }
      expect(parsed.ignored, want['ignored'], reason: name);
      expect(parsed.ignoredMore, want['ignored_more'], reason: name);
      final got = <Map<String, Object?>>[];
      for (final raw in parsed.rows) {
        Object? res;
        try {
          final row = checkImportRow(raw, rules);
          res = {
            'display_name': row.displayName,
            'external_ref': row.externalRef,
            'team_preference': row.teamPreference,
            'federation_number': row.federationNumber,
            'replicas': row.replicas,
            'present': row.present.toList()..sort(),
            'warnings': row.warnings,
          };
        } on ImportRowError catch (e) {
          res = e.code;
        }
        got.add({'number': raw.number, 'result': res});
      }
      expect(got, want['rows'], reason: name);
    }
  });

  test('uuid5 is Python\'s uuid.uuid5', () {
    // python3 -c "import uuid; print(uuid.uuid5(uuid.UUID('6f1b5f0e-3c1d-5a7e-9b44-0a7a1a1a0001'), 'clube\0r-1'))"
    expect(
      uuid5('6f1b5f0e-3c1d-5a7e-9b44-0a7a1a1a0001', 'clube\u0000r-1'),
      '1084e935-87ed-5b19-9005-2a73cb5bb657',
    );
  });

  test('the formula guard round-trips', () {
    for (final v in ['=1', '+351', '-1', '@x', '\tx', '\rx']) {
      expect(csvSafe(v), "'$v");
      expect(csvUnsafe(csvSafe(v)), v);
    }
    expect(csvUnsafe("'quoted"), "'quoted");
    expect(csvSafe(null), '');
  });

  test('the source label', () {
    for (final good in ['fpa', 'clube.exemplo', 'a-b_c', 'x' * 32]) {
      expect(checkImportSource(good), good);
    }
    for (final bad in ['site', '', 'Clube', '-x', 'x' * 33, 'a b', null]) {
      expect(() => checkImportSource(bad), throwsA(isA<ImportFileError>()));
    }
  });

  test('a string with a lone surrogate has no bytes', () {
    expect(importBytes('ok'), isNotNull);
    expect(importBytes('\ud800'), isNull);
    expect(importBytes('\u{1F600}'), isNotNull);
  });
}
