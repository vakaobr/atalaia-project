// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The golden tests draw Traditional Chinese with a subset of Noto Sans TC
// (test/fonts/), since a widget test has no system fonts. A character the
// zh-tw texts use and the subset lacks would be drawn as a box in the
// goldens: this test names it instead (make the subset again, as
// test/fonts/README.md says). On phones Android's own CJK font draws them.

import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/l10n/strings_zh_tw.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/fonts.dart';

/// The code points a font's cmap maps (format 4 subtables: the BMP).
Set<int> cmapCodePoints(Uint8List font) {
  final d = ByteData.sublistView(font);
  final tables = d.getUint16(4);
  int? cmap;
  for (var i = 0; i < tables; i++) {
    final r = 12 + 16 * i;
    if (String.fromCharCodes(font.sublist(r, r + 4)) == 'cmap') {
      cmap = d.getUint32(r + 8);
    }
  }
  if (cmap == null) throw StateError('no cmap table');
  final out = <int>{};
  final subtables = d.getUint16(cmap + 2);
  for (var i = 0; i < subtables; i++) {
    final st = cmap + d.getUint32(cmap + 4 + 8 * i + 4);
    if (d.getUint16(st) != 4) continue;
    final segs = d.getUint16(st + 6) ~/ 2;
    final ends = st + 14;
    final starts = ends + 2 * segs + 2;
    final deltas = starts + 2 * segs;
    final offsets = deltas + 2 * segs;
    for (var s = 0; s < segs; s++) {
      final end = d.getUint16(ends + 2 * s);
      final start = d.getUint16(starts + 2 * s);
      final delta = d.getUint16(deltas + 2 * s);
      final offset = d.getUint16(offsets + 2 * s);
      for (var c = start; c <= end && c != 0xFFFF; c++) {
        var glyph = 0;
        if (offset == 0) {
          glyph = (c + delta) & 0xFFFF;
        } else {
          final at = offsets + 2 * s + offset + 2 * (c - start);
          glyph = d.getUint16(at);
          if (glyph != 0) glyph = (glyph + delta) & 0xFFFF;
        }
        if (glyph != 0) out.add(c);
      }
    }
  }
  return out;
}

void main() {
  test('the test font has every character of the zh-tw texts', () {
    final have = cmapCodePoints(File(cjkRegular).readAsBytesSync());
    expect(have, contains('紅'.runes.single));
    final missing = <String>{
      for (final text in zhTwStrings.values)
        for (final c in text.runes)
          if (c > 0x2000 && !have.contains(c)) String.fromCharCode(c),
    };
    expect(missing, isEmpty, reason: 'make test/fonts/ again');
  });
}
