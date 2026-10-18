// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import 'package:atalaia_app/security/canonical_json.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

void main() {
  final v = loadVectors('chrono_record.json');

  test('numbers are written as the shared vectors say', () {
    for (final c in cases(v, 'numbers')) {
      expect(canonicalNumber((c['value'] as num).toDouble()), c['text']);
    }
  });

  test('keys sorted, no whitespace, integers and numbers', () {
    expect(
      canonicalJsonString({'b': 1, 'a': 'x', 'c_2': 0.5, 'c': 100.0}),
      '{"a":"x","b":1,"c":100.0,"c_2":0.5}',
    );
  });

  test('only quotes and backslashes are escaped; UTF-8 is kept', () {
    expect(
      canonicalJsonString({'n': 'José "Zé" \\ /'}),
      r'{"n":"José \"Zé\" \\ /"}',
    );
    expect(canonicalJson({'n': 'é'}), [
      ...'{"n":"'.codeUnits,
      0xc3,
      0xa9,
      ...'"}'.codeUnits,
    ]);
  });

  test('control characters and lone surrogates are refused', () {
    for (final s in [
      'a\nb',
      'a\u0000',
      'a\u007f',
      'a\u0085',
      'a\ud800',
      '\udc00a',
    ]) {
      expect(isCanonicalText(s), isFalse, reason: s);
      expect(() => canonicalJsonString({'n': s}), throwsArgumentError);
    }
    expect(isCanonicalText('\u{1F3AF} ok'), isTrue);
  });

  test('numbers outside the plain-notation range are refused', () {
    for (final x in [1e-5, 1e15, double.nan, double.infinity]) {
      expect(() => canonicalNumber(x), throwsArgumentError, reason: '$x');
    }
    expect(canonicalNumber(1e-4), '0.0001');
    expect(canonicalNumber(0.0), '0.0');
  });

  test('keys are a-z, 0-9 and _; values are strings and numbers', () {
    expect(() => canonicalJsonString({'A': 1}), throwsArgumentError);
    expect(() => canonicalJsonString({'a': true}), throwsArgumentError);
    expect(() => canonicalJsonString({'a': <int>[]}), throwsArgumentError);
  });
}
