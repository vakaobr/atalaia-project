// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The field's logo in the form a Field Box draws (decision PKG-1;
/// protocol/mode-packages.md, section 7): the Dart port of the Pi
/// controller's controller/atalaia_controller/box_logo.py, with the same
/// bytes, checked by the cases in protocol/vectors/box_logo.json.
///
/// The box has no PNG or JPEG decoder (its image is nearly full), so the
/// controller prepares the logo: a PNG is decoded here with dart:io's zlib,
/// fitted into 96x96 pixels (area average, whole integers, alpha composited
/// on the box's screen colour #101418) and written as
///
///     "ALG1"  u16le width (96)  u16le height (96)  96 x 96 little-endian
///     RGB565 words
///
/// 18,440 bytes. Only PNG is converted: the controller has no JPEG or WebP
/// decoder (decision BR7), so a field whose logo is one of those keeps the
/// Atalaia logo on its boxes.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

const boxLogoSide = 96;
const _header = 8;
const boxLogoSize = _header + boxLogoSide * boxLogoSide * 2;

/// Whether uploaded bytes are box-ready: exactly [boxLogoSize] bytes with the
/// header above (decision LOGO-1; the console converts JPEG and WebP logos).
bool checkBoxLogo(Uint8List data) {
  if (data.length != boxLogoSize) return false;
  const head = [0x41, 0x4C, 0x47, 0x31, boxLogoSide, 0, boxLogoSide, 0];
  for (var i = 0; i < head.length; i++) {
    if (data[i] != head[i]) return false;
  }
  return true;
}

/// The box's screen colour (COLOR_BG in screen_renderer.c).
const _bg = [0x10, 0x14, 0x18];

/// Larger logos are not converted (the work is bounded).
const _maxPixels = 1 << 20;
const _pngSig = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
const _samples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4};
const _adam7 = [
  [0, 0, 8, 8],
  [4, 0, 8, 8],
  [0, 4, 4, 8],
  [2, 0, 4, 4],
  [0, 2, 2, 4],
  [1, 0, 2, 2],
  [0, 1, 1, 2],
];

/// The logo cannot be made box-ready (not a PNG, too large to convert,
/// damaged).
class BoxLogoError implements Exception {
  BoxLogoError(this.message);
  final String message;
  @override
  String toString() => message;
}

/// What the box asks first: the source image's id, and the SHA-256 and size
/// of the bytes to come.
String boxLogoReleaseText(String imageId, Uint8List data) =>
    'atalaia-box-logo-v1\n'
    'id=$imageId\n'
    'sha256=${sha256.convert(data)}\n'
    'bytes=${data.length}\n';

int _paeth(int a, int b, int c) {
  final p = a + b - c;
  final pa = (p - a).abs(), pb = (p - b).abs(), pc = (p - c).abs();
  if (pa <= pb && pa <= pc) return a;
  return pb <= pc ? b : c;
}

/// Undoes the scanline filters of [rows] lines of [stride] bytes from [pos];
/// the lines, and where the data goes on.
(List<Uint8List>, int) _unfilter(
  Uint8List raw,
  int pos,
  int rows,
  int stride,
  int bpp,
) {
  final out = <Uint8List>[];
  var prev = Uint8List(stride);
  for (var r = 0; r < rows; r++) {
    final ftype = raw[pos];
    final line = Uint8List.fromList(raw.sublist(pos + 1, pos + 1 + stride));
    if (line.length != stride) throw RangeError('short');
    pos += 1 + stride;
    switch (ftype) {
      case 0:
        break;
      case 1:
        for (var i = bpp; i < stride; i++) {
          line[i] = (line[i] + line[i - bpp]) & 255;
        }
      case 2:
        for (var i = 0; i < stride; i++) {
          line[i] = (line[i] + prev[i]) & 255;
        }
      case 3:
        for (var i = 0; i < stride; i++) {
          final left = i >= bpp ? line[i - bpp] : 0;
          line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255;
        }
      case 4:
        for (var i = 0; i < stride; i++) {
          final left = i >= bpp ? line[i - bpp] : 0;
          final upLeft = i >= bpp ? prev[i - bpp] : 0;
          line[i] = (line[i] + _paeth(left, prev[i], upLeft)) & 255;
        }
      default:
        throw BoxLogoError('the PNG has an unknown filter');
    }
    out.add(line);
    prev = line;
  }
  return (out, pos);
}

int _be32(Uint8List d, int o) =>
    (d[o] << 24) | (d[o + 1] << 16) | (d[o + 2] << 8) | d[o + 3];

/// The PNG as width, height and 8-bit RGBA (4 bytes a pixel).
(int, int, Uint8List) decodePngRgba(Uint8List data) {
  if (data.length < 8) throw BoxLogoError('not a PNG');
  for (var i = 0; i < 8; i++) {
    if (data[i] != _pngSig[i]) throw BoxLogoError('not a PNG');
  }
  var pos = 8;
  List<int>? header;
  var palette = Uint8List(0);
  var trns = Uint8List(0);
  final idat = BytesBuilder(copy: false);
  while (pos + 12 <= data.length) {
    final length = _be32(data, pos);
    final kind = latin1.decode(data.sublist(pos + 4, pos + 8));
    final end = pos + 8 + length;
    if (end > data.length) throw BoxLogoError('the PNG is damaged');
    final body = Uint8List.sublistView(data, pos + 8, end);
    pos += 12 + length;
    if (kind == 'IHDR') {
      if (body.length != 13) throw BoxLogoError('the PNG is damaged');
      header = [
        _be32(body, 0),
        _be32(body, 4),
        body[8],
        body[9],
        body[10],
        body[11],
        body[12],
      ];
    } else if (kind == 'PLTE') {
      palette = body;
    } else if (kind == 'tRNS') {
      trns = body;
    } else if (kind == 'IDAT') {
      idat.add(body);
    } else if (kind == 'IEND') {
      break;
    }
  }
  if (header == null) throw BoxLogoError('the PNG has no header');
  final width = header[0], height = header[1];
  final depth = header[2], colour = header[3], interlace = header[6];
  if (width * height > _maxPixels) {
    throw BoxLogoError(
      'the logo is ${width}x$height pixels; boxes get logos up to '
      '$_maxPixels pixels',
    );
  }
  final Uint8List raw;
  try {
    raw = Uint8List.fromList(ZLibCodec().decode(idat.takeBytes()));
  } on FormatException {
    throw BoxLogoError('the PNG is damaged (zlib)');
  } on Exception {
    throw BoxLogoError('the PNG is damaged (zlib)');
  }
  final samples = _samples[colour]!;
  final bits = depth * samples;
  final bpp = bits ~/ 8 < 1 ? 1 : bits ~/ 8;
  final rgba = Uint8List(width * height * 4);
  // The colour a gray or truecolour PNG's tRNS makes transparent, at the
  // PNG's own depth.
  List<int>? key;
  if ((colour == 0 || colour == 2) && trns.isNotEmpty) {
    key = [
      for (var i = 0; i + 1 < trns.length; i += 2) (trns[i] << 8) | trns[i + 1],
    ];
  }
  final top = (1 << depth) - 1;
  final passes = interlace == 0
      ? const [
          [0, 0, 1, 1],
        ]
      : _adam7;
  var at = 0;
  try {
    for (final p in passes) {
      final x0 = p[0], y0 = p[1], dx = p[2], dy = p[3];
      final pw = width > x0 ? (width - x0 + dx - 1) ~/ dx : 0;
      final ph = height > y0 ? (height - y0 + dy - 1) ~/ dy : 0;
      if (pw == 0 || ph == 0) continue;
      final stride = (pw * bits + 7) ~/ 8;
      final (lines, next) = _unfilter(raw, at, ph, stride, bpp);
      at = next;
      for (var ry = 0; ry < ph; ry++) {
        final line = lines[ry];
        final y = y0 + ry * dy;
        for (var rx = 0; rx < pw; rx++) {
          final v = _pixelSamples(line, rx, depth, samples);
          final c = _rgba(v, colour, depth, top, palette, trns, key);
          final o = (y * width + x0 + rx * dx) * 4;
          rgba[o] = c[0];
          rgba[o + 1] = c[1];
          rgba[o + 2] = c[2];
          rgba[o + 3] = c[3];
        }
      }
    }
  } on RangeError {
    throw BoxLogoError("the PNG's image data is short");
  }
  return (width, height, rgba);
}

List<int> _pixelSamples(Uint8List line, int index, int depth, int samples) {
  if (depth == 8) {
    return [for (var k = 0; k < samples; k++) line[index * samples + k]];
  }
  if (depth == 16) {
    final base = index * samples * 2;
    return [
      for (var k = 0; k < samples; k++)
        (line[base + 2 * k] << 8) | line[base + 2 * k + 1],
    ];
  }
  final bit = index * depth; // 1, 2 or 4 bits: one sample a pixel
  return [(line[bit >> 3] >> (8 - depth - (bit & 7))) & ((1 << depth) - 1)];
}

int _to8(int v, int depth, int top) {
  if (depth == 8) return v;
  if (depth == 16) return v >> 8;
  return v * 255 ~/ top;
}

List<int> _rgba(
  List<int> v,
  int colour,
  int depth,
  int top,
  Uint8List palette,
  Uint8List trns,
  List<int>? key,
) {
  if (colour == 3) {
    final i = v[0];
    if (3 * i + 2 >= palette.length) throw RangeError('palette');
    return [
      palette[3 * i],
      palette[3 * i + 1],
      palette[3 * i + 2],
      i < trns.length ? trns[i] : 255,
    ];
  }
  if (colour == 0) {
    final g = _to8(v[0], depth, top);
    return [g, g, g, key != null && key.isNotEmpty && v[0] == key[0] ? 0 : 255];
  }
  if (colour == 4) {
    final g = _to8(v[0], depth, top);
    return [g, g, g, _to8(v[1], depth, top)];
  }
  final r = _to8(v[0], depth, top);
  final g = _to8(v[1], depth, top);
  final b = _to8(v[2], depth, top);
  if (colour == 6) return [r, g, b, _to8(v[3], depth, top)];
  final keyed =
      key != null &&
      key.length >= 3 &&
      v[0] == key[0] &&
      v[1] == key[1] &&
      v[2] == key[2];
  return [r, g, b, keyed ? 0 : 255];
}

/// The box-ready bytes of a PNG logo ([boxLogoSize] bytes), or a
/// [BoxLogoError].
Uint8List convertBoxLogo(Uint8List png) {
  final (width, height, rgba) = decodePngRgba(png);
  final int tw, th;
  if (width >= height) {
    tw = boxLogoSide;
    final h = (height * boxLogoSide + width ~/ 2) ~/ width;
    th = h < 1 ? 1 : h;
  } else {
    th = boxLogoSide;
    final w = (width * boxLogoSide + height ~/ 2) ~/ height;
    tw = w < 1 ? 1 : w;
  }
  final ox = (boxLogoSide - tw) ~/ 2, oy = (boxLogoSide - th) ~/ 2;
  final out = Uint8List(boxLogoSize);
  final view = ByteData.sublistView(out);
  out.setRange(0, 4, ascii.encode('ALG1'));
  view.setUint16(4, boxLogoSide, Endian.little);
  view.setUint16(6, boxLogoSide, Endian.little);
  final bg565 = ((_bg[0] >> 3) << 11) | ((_bg[1] >> 2) << 5) | (_bg[2] >> 3);
  for (var i = 0; i < boxLogoSide * boxLogoSide; i++) {
    view.setUint16(_header + 2 * i, bg565, Endian.little);
  }
  for (var dy = 0; dy < th; dy++) {
    final y0 = dy * height ~/ th;
    final y1 = (dy + 1) * height ~/ th > y0 + 1
        ? (dy + 1) * height ~/ th
        : y0 + 1;
    for (var dx = 0; dx < tw; dx++) {
      final x0 = dx * width ~/ tw;
      final x1 = (dx + 1) * width ~/ tw > x0 + 1
          ? (dx + 1) * width ~/ tw
          : x0 + 1;
      final n = (x1 - x0) * (y1 - y0);
      var sa = 0, sr = 0, sg = 0, sb = 0;
      for (var y = y0; y < y1; y++) {
        var o = (y * width + x0) * 4;
        for (var x = x0; x < x1; x++) {
          final a = rgba[o + 3];
          sa += a;
          sr += rgba[o] * a;
          sg += rgba[o + 1] * a;
          sb += rgba[o + 2] * a;
          o += 4;
        }
      }
      final full = 255 * n;
      final back = full - sa;
      final half = full ~/ 2;
      final r = (sr + _bg[0] * back + half) ~/ full;
      final g = (sg + _bg[1] * back + half) ~/ full;
      final b = (sb + _bg[2] * back + half) ~/ full;
      view.setUint16(
        _header + 2 * ((oy + dy) * boxLogoSide + ox + dx),
        ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3),
        Endian.little,
      );
    }
  }
  return out;
}
