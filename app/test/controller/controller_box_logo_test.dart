// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The field's logo for a Field Box (controller_box_logo.dart, decision
// PKG-1): the cases of protocol/vectors/box_logo.json, made with the Pi's
// box_logo.py, give the same bytes here.

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_box_logo.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

void main() {
  final v = loadVectors('box_logo.json');
  final cases = (v['cases'] as List).cast<Map<String, dynamic>>();

  test('the format constants are the shared ones', () {
    expect(boxLogoSide, v['side']);
    expect(boxLogoSize, v['bytes']);
  });

  for (final c in cases) {
    test('vector ${c['name']}', () {
      final png = base64.decode(c['png_b64'] as String);
      expect(sha256.convert(png).toString(), c['png_sha256']);
      final out = convertBoxLogo(png);
      expect(out.length, c['box_bytes']);
      expect(
        out
            .sublist(0, 16)
            .map((b) => b.toRadixString(16).padLeft(2, '0'))
            .join(),
        c['box_head'],
      );
      expect(sha256.convert(out).toString(), c['box_sha256']);
    });
  }

  test('the release text is the shared one', () {
    expect(
      boxLogoReleaseText('ab' * 32, Uint8List.fromList([1, 2, 3])),
      v['release_text'],
    );
  });

  test('not a PNG, too large and damaged logos are refused', () {
    expect(
      () => convertBoxLogo(Uint8List.fromList(List.filled(40, 0xFF))),
      throwsA(isA<BoxLogoError>()),
    );
    final big = Uint8List.fromList(
      base64.decode(cases.first['png_b64'] as String),
    );
    final head = Uint8List.fromList(big);
    ByteData.sublistView(head).setUint32(16, 2000); // IHDR width
    ByteData.sublistView(head).setUint32(20, 2000); // IHDR height
    expect(() => convertBoxLogo(head), throwsA(isA<BoxLogoError>()));
    expect(
      () => convertBoxLogo(Uint8List.sublistView(big, 0, 60)),
      throwsA(isA<BoxLogoError>()),
    );
  });
}
