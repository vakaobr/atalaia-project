// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The CBOR decoder (lib/protocol/cbor.dart) on hostile input (security review
// SR-90): nesting is bounded and a length or count larger than the bytes left
// is refused before anything is allocated or looped over. Every payload
// decoder of the app (join payloads, field frames, pair frames, check-in
// tickets, pod and radio frames) goes through it. The Python twin is
// simulator/tests/test_cbor_limits.py.

import 'dart:typed_data';

import 'package:atalaia_app/protocol/cbor.dart';
import 'package:flutter_test/flutter_test.dart';

Matcher get _refused => throwsA(isA<CborException>());

Uint8List _repeat(List<int> unit, int times, [List<int> tail = const []]) {
  final out = <int>[];
  for (var i = 0; i < times; i++) {
    out.addAll(unit);
  }
  return Uint8List.fromList([...out, ...tail]);
}

void main() {
  group('nesting', () {
    test('the deepest allowed decodes and one more is refused', () {
      expect(cborDecode(_repeat([0x81], cborMaxDepth - 1, [0x80])), isList);
      expect(() => cborDecode(_repeat([0x81], cborMaxDepth, [0x80])), _refused);
    });

    test('a huge nesting is refused without a stack overflow', () {
      expect(() => cborDecode(_repeat([0x81], 200000)), _refused);
      expect(() => cborDecode(_repeat([0xa1, 0x00], 200000)), _refused);
    });

    test('maps count as nesting in keys and values', () {
      expect(
        () => cborDecode([
          0xa1,
          ..._repeat([0x81], 40, [0x00, 0x00]),
        ]),
        _refused,
      );
      expect(
        () => cborDecode([
          0xa1,
          0x00,
          ..._repeat([0x81], 40, [0x00]),
        ]),
        _refused,
      );
    });
  });

  group('counts and lengths', () {
    final hostile = <String, List<int>>{
      'array, 8-byte count': [0x9b, ...List.filled(8, 0xff)],
      'array, 8-byte count below 2^63': [0x9b, 0x7f, ...List.filled(7, 0xff)],
      'array, 4-byte count': [0x9a, 0xff, 0xff, 0xff, 0xff, 0x00],
      'array, 2-byte count': [0x99, 0xff, 0xff, 0x00],
      'array, 1 byte left for 2': [0x82, 0x00],
      'map, 8-byte count': [0xbb, ...List.filled(8, 0xff)],
      'map, 4-byte count': [0xba, 0x7f, 0xff, 0xff, 0xff, 0x00],
      'map, 4 pairs, 4 bytes': [0xa4, 0x00, 0x00, 0x01, 0x01],
      'text, 8-byte length': [0x7b, ...List.filled(8, 0xff)],
      'text, 3 bytes for 4': [0x64, 0x61, 0x62, 0x63],
      'text, 4-byte length': [0x7a, 0xff, 0xff, 0xff, 0xff],
      'truncated 8-byte head': [0x1b, 0, 0, 0, 0, 0, 0, 0],
      'empty input': <int>[],
    };
    for (final e in hostile.entries) {
      test(e.key, () => expect(() => cborDecode(e.value), _refused));
    }

    test('a byte string longer than the input is refused', () {
      for (final data in <List<int>>[
        [0x5b, ...List.filled(8, 0xff)],
        [0x58, 0x05, 0x61, 0x62, 0x63],
        [0x5a, 0xff, 0xff, 0xff, 0xff],
      ]) {
        expect(() => cborDecode(data, allowBytes: true), _refused);
      }
    });

    test('a count equal to the bytes left is accepted', () {
      expect(cborDecode([0x83, 0x00, 0x01, 0x02]), [0, 1, 2]);
      expect(cborDecode([0xa1, 0x00, 0x01]), {0: 1});
      expect(cborDecode([0x43, 0x61, 0x62, 0x63], allowBytes: true), [
        0x61,
        0x62,
        0x63,
      ]);
    });
  });
}
