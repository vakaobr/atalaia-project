// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Uploaded branding images on the Android field controller, checked and
/// stripped of metadata without an image library: the Dart port of the Pi
/// controller's controller/atalaia_controller/images.py (decisions BR6-BR9),
/// with the same results, byte for byte, and the same status codes, checked
/// by the cases in test/controller/fixtures/controller_images.json.
///
/// A field's logo and wallpaper and a team's crest are PNG, JPEG or WebP.
/// SVG is refused (it can carry scripts), and so is anything else, whatever
/// its Content-Type says: the type is taken from the file's own signature and
/// must match the declared one.
///
/// The controller has no image library (decoders are a large attack surface,
/// decision BR7), so this file reads each format's structure itself:
///
/// - PNG: every chunk's length and CRC, a valid IHDR, the image data inflated
///   with a cap and checked to be exactly as long as the IHDR says (so a
///   truncated file or a decompression bomb is refused), IEND last and
///   nothing after it; animated PNG (acTL) and unknown critical chunks are
///   refused.
/// - JPEG: the segments up to the first scan, exactly one frame header with
///   its size, the end-of-image marker; data after it is dropped.
/// - WebP: the RIFF size, the VP8, VP8L or VP8X header with its size;
///   animation (the ANIM flag or ANIM/ANMF chunks) is refused.
///
/// Metadata is stripped by rewriting the container without it (no pixel is
/// re-encoded): PNG text, time and EXIF chunks and unknown ancillary chunks;
/// JPEG APP1 (EXIF, XMP), APP3-APP13 (IPTC, ...), APP15 and comments; WebP
/// EXIF and XMP chunks (and their VP8X flags). Colour profiles stay. The
/// pixels themselves are decoded only by the browsers and phones that show
/// the image, with their own decoders.
///
/// The PNG image data is inflated with dart:io's zlib filter, which does not
/// say where the zlib stream ends (Python's decompressobj has `eof`) and
/// also takes a gzip stream. So a stream starting as gzip (1f 8b) is refused
/// here, as Python's zlib refuses it, and the end is found by feeding the
/// filter a few bytes once all the data is in: after the end it takes them
/// with no output and no error; before the end they give output or an error
/// (their value is chosen to differ from the Adler-32 the stream would end
/// with, so they can never complete it). The filter also inflates in larger
/// steps than Python's capped calls, so for image data that is both too long
/// and damaged further on, the message may name the damage where Python's
/// names the size; the status (422) is the same.
library;

import 'dart:io';
import 'dart:typed_data';

/// An upload that cannot be accepted: [status] is the HTTP status (413, 415
/// or 422).
class ImageError implements Exception {
  ImageError(this.status, this.message);

  final int status;
  final String message;

  @override
  String toString() => message;
}

/// What one kind of image may be (decision BR6).
class ImageLimits {
  const ImageLimits(
    this.kind,
    this.maxBytes,
    this.minSide,
    this.maxSide,
    this.maxAspect,
  );

  final String kind;
  final int maxBytes;
  final int minSide;
  final int maxSide;

  /// The longer side over the shorter one.
  final double maxAspect;

  static const logo = ImageLimits('logo', 1024 * 1024, 16, 2048, 8.0);
  static const wallpaper = ImageLimits(
    'wallpaper',
    4 * 1024 * 1024,
    320,
    4096,
    8.0,
  );
  static const crest = ImageLimits('crest', 512 * 1024, 16, 1024, 4.0);
  static const kinds = {'logo': logo, 'wallpaper': wallpaper, 'crest': crest};
}

/// An accepted image: [data] is the stripped file, as stored and served.
class CheckedImage {
  const CheckedImage(this.contentType, this.width, this.height, this.data);

  final String contentType;
  final int width;
  final int height;
  final Uint8List data;
}

const imageTypes = ['image/png', 'image/jpeg', 'image/webp'];
const pngSignature = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];

/// The image type of a file from its signature, or null.
String? sniffImage(List<int> data) {
  if (_startsWith(data, pngSignature)) return 'image/png';
  if (_startsWith(data, const [0xFF, 0xD8, 0xFF])) return 'image/jpeg';
  if (data.length >= 12 &&
      _startsWith(data, const [0x52, 0x49, 0x46, 0x46]) &&
      data[8] == 0x57 &&
      data[9] == 0x45 &&
      data[10] == 0x42 &&
      data[11] == 0x50) {
    return 'image/webp';
  }
  return null;
}

/// The upload as it will be stored, or an [ImageError].
CheckedImage checkImage(
  Uint8List data,
  String? declaredContentType,
  ImageLimits limits,
) {
  final declared = _pyStrip(
    (declaredContentType ?? '').split(';').first,
  ).toLowerCase();
  if (data.length > limits.maxBytes) {
    throw ImageError(
      413,
      'the ${limits.kind} is over ${limits.maxBytes} bytes',
    );
  }
  if (data.isEmpty) throw ImageError(422, 'empty image');
  if (!imageTypes.contains(declared)) {
    throw ImageError(
      415,
      'the ${limits.kind} must be PNG, JPEG or WebP (not '
      '${declared.isEmpty ? 'untyped' : declared}; SVG is not accepted)',
    );
  }
  final found = sniffImage(data);
  if (found == null) {
    throw ImageError(415, 'the ${limits.kind} is not a PNG, JPEG or WebP file');
  }
  if (found != declared) {
    throw ImageError(415, 'the file is $found, not $declared as declared');
  }
  final _Parsed parsed;
  try {
    if (found == 'image/png') {
      parsed = _png(data, limits);
    } else if (found == 'image/jpeg') {
      parsed = _jpeg(data);
    } else {
      parsed = _webp(data);
    }
  } on RangeError {
    // Python's IndexError (or struct.error) on an out-of-range read.
    throw ImageError(422, 'the ${limits.kind} is damaged (IndexError)');
  } on FormatException {
    // The zlib filter's "bad data": Python's zlib.error.
    throw ImageError(422, 'the ${limits.kind} is damaged (error)');
  }
  final width = parsed.width, height = parsed.height;
  final lo = width < height ? width : height;
  final hi = width < height ? height : width;
  if (lo < limits.minSide || hi > limits.maxSide) {
    throw _sideError(limits, width, height);
  }
  if (hi / lo > limits.maxAspect) {
    throw ImageError(
      422,
      'the ${limits.kind} is ${width}x$height pixels; at most '
      '${_g(limits.maxAspect)} times as long as it is wide',
    );
  }
  return CheckedImage(found, width, height, parsed.data);
}

class _Parsed {
  _Parsed(this.width, this.height, this.data);

  final int width;
  final int height;
  final Uint8List data;
}

ImageError _bad(String message) => ImageError(422, message);

ImageError _sideError(ImageLimits limits, int width, int height) => _bad(
  'the ${limits.kind} is ${width}x$height pixels; each side must be '
  '${limits.minSide} to ${limits.maxSide}',
);

/// Python's `{x:g}` for the aspect limits (8.0 is "8").
String _g(double x) =>
    x == x.truncateToDouble() ? x.toInt().toString() : x.toString();

/// Python's str.strip(): the characters str.isspace() is true for.
String _pyStrip(String s) {
  bool space(int c) =>
      (c >= 0x09 && c <= 0x0D) ||
      (c >= 0x1C && c <= 0x20) ||
      c == 0x85 ||
      c == 0xA0 ||
      c == 0x1680 ||
      (c >= 0x2000 && c <= 0x200A) ||
      c == 0x2028 ||
      c == 0x2029 ||
      c == 0x202F ||
      c == 0x205F ||
      c == 0x3000;
  var start = 0, end = s.length;
  while (start < end && space(s.codeUnitAt(start))) {
    start++;
  }
  while (end > start && space(s.codeUnitAt(end - 1))) {
    end--;
  }
  return s.substring(start, end);
}

bool _startsWith(List<int> data, List<int> prefix) {
  if (data.length < prefix.length) return false;
  for (var i = 0; i < prefix.length; i++) {
    if (data[i] != prefix[i]) return false;
  }
  return true;
}

/// Python's repr() of a chunk name decoded as Latin-1, for the messages.
String _repr(String s) {
  final quote = s.contains("'") && !s.contains('"') ? '"' : "'";
  final out = StringBuffer(quote);
  for (final c in s.codeUnits) {
    if (c == 0x5C) {
      out.write(r'\\');
    } else if (c == 0x09) {
      out.write(r'\t');
    } else if (c == 0x0A) {
      out.write(r'\n');
    } else if (c == 0x0D) {
      out.write(r'\r');
    } else if (c == quote.codeUnitAt(0)) {
      out.write('\\$quote');
    } else if (c < 0x20 || (c >= 0x7F && c <= 0xA0) || c == 0xAD) {
      out.write('\\x${c.toRadixString(16).padLeft(2, '0')}');
    } else {
      out.writeCharCode(c);
    }
  }
  out.write(quote);
  return out.toString();
}

int _u16be(List<int> d, int p) => d[p] << 8 | d[p + 1];
int _u32be(List<int> d, int p) =>
    d[p] << 24 | d[p + 1] << 16 | d[p + 2] << 8 | d[p + 3];
int _u16le(List<int> d, int p) => d[p] | d[p + 1] << 8;
int _u24le(List<int> d, int p) => d[p] | d[p + 1] << 8 | d[p + 2] << 16;
int _u32le(List<int> d, int p) =>
    d[p] | d[p + 1] << 8 | d[p + 2] << 16 | d[p + 3] << 24;

Uint8List _join(List<List<int>> parts) {
  final out = BytesBuilder(copy: false);
  for (final p in parts) {
    out.add(p);
  }
  return out.takeBytes();
}

// --- PNG ---------------------------------------------------------------------

/// Ancillary chunks kept (colour and layout); everything else ancillary is
/// dropped.
const pngKeep = {
  'tRNS',
  'gAMA',
  'cHRM',
  'sRGB',
  'iCCP',
  'sBIT',
  'bKGD',
  'pHYs',
  'cICP',
};

/// Bit depths allowed per colour type, and samples per pixel.
const _pngDepths = {
  0: [1, 2, 4, 8, 16],
  2: [8, 16],
  3: [1, 2, 4, 8],
  4: [8, 16],
  6: [8, 16],
};
const _pngSamples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4};

/// Adam7: (x start, y start, x step, y step) of each pass.
const _adam7 = [
  [0, 0, 8, 8],
  [4, 0, 8, 8],
  [0, 4, 4, 8],
  [2, 0, 4, 4],
  [0, 2, 2, 4],
  [1, 0, 2, 2],
  [0, 1, 1, 2],
];

final Uint32List _crcTable = () {
  final table = Uint32List(256);
  for (var n = 0; n < 256; n++) {
    var c = n;
    for (var k = 0; k < 8; k++) {
      c = (c & 1) != 0 ? 0xEDB88320 ^ (c >> 1) : c >> 1;
    }
    table[n] = c;
  }
  return table;
}();

/// The CRC-32 (as zlib.crc32) of data[start:end].
int crc32(List<int> data, [int start = 0, int? end]) {
  var c = 0xFFFFFFFF;
  for (var i = start; i < (end ?? data.length); i++) {
    c = _crcTable[(c ^ data[i]) & 0xFF] ^ (c >> 8);
  }
  return c ^ 0xFFFFFFFF;
}

int _pngRawSize(int width, int height, int depth, int ctype, int interlace) {
  final bits = depth * _pngSamples[ctype]!;
  int rows(int w, int h) =>
      w == 0 || h == 0 ? 0 : h * (1 + (w * bits + 7) ~/ 8);
  if (interlace == 0) return rows(width, height);
  var total = 0;
  for (final [x0, y0, dx, dy] in _adam7) {
    total += rows(
      width > x0 ? (width - x0 + dx - 1) ~/ dx : 0,
      height > y0 ? (height - y0 + dy - 1) ~/ dy : 0,
    );
  }
  return total;
}

_Parsed _png(Uint8List data, ImageLimits limits) {
  var pos = pngSignature.length;
  final out = <List<int>>[pngSignature];
  int? width, height, colour;
  _Inflater? inflater;
  var seenIdat = false, idatDone = false, seenEnd = false, seenPalette = false;
  var first = true;
  while (pos < data.length) {
    if (pos + 12 > data.length) throw _bad('the PNG ends inside a chunk');
    final length = _u32be(data, pos);
    if (length > 0x7FFFFFFF || pos + 12 + length > data.length) {
      throw _bad('a PNG chunk is longer than the file');
    }
    final type = String.fromCharCodes(data, pos + 4, pos + 8);
    final crc = _u32be(data, pos + 8 + length);
    if (crc32(data, pos + 4, pos + 8 + length) != crc) {
      throw _bad('the PNG chunk ${_repr(type)} has a bad checksum');
    }
    final body = Uint8List.sublistView(data, pos + 8, pos + 8 + length);
    final chunk = Uint8List.sublistView(data, pos, pos + 12 + length);
    pos += 12 + length;
    if (!type.codeUnits.every(
      (c) => (c >= 65 && c <= 90) || (c >= 97 && c <= 122),
    )) {
      throw _bad('a PNG chunk has an invalid name');
    }
    if (first) {
      if (type != 'IHDR' || length != 13) {
        throw _bad('the PNG does not start with its header');
      }
      final w = _u32be(body, 0), h = _u32be(body, 4);
      final depth = body[8], ctype = body[9], comp = body[10];
      final filt = body[11], interlace = body[12];
      if (!(w > 0 && w <= 0x7FFFFFFF && h > 0 && h <= 0x7FFFFFFF)) {
        throw _bad('the PNG has no size');
      }
      final depths = _pngDepths[ctype];
      if (depths == null ||
          !depths.contains(depth) ||
          comp != 0 ||
          filt != 0 ||
          (interlace != 0 && interlace != 1)) {
        throw _bad('the PNG header is invalid');
      }
      width = w;
      height = h;
      colour = ctype;
      // Checked before inflating, so the size cap bounds the work.
      if ((w > h ? w : h) > limits.maxSide ||
          (w < h ? w : h) < limits.minSide) {
        throw _sideError(limits, w, h);
      }
      inflater = _Inflater(_pngRawSize(w, h, depth, ctype, interlace));
      first = false;
      out.add(chunk);
      continue;
    }
    if (type == 'IHDR') throw _bad('the PNG has two headers');
    if (type == 'acTL' || type == 'fcTL' || type == 'fdAT') {
      throw _bad('animated PNG is not accepted');
    }
    if (type == 'IDAT') {
      if (idatDone) throw _bad("the PNG's image data is split");
      seenIdat = true;
      inflater!.feed(body);
      out.add(chunk);
      continue;
    }
    if (seenIdat) idatDone = true;
    if (type == 'IEND') {
      seenEnd = true;
      out.add(chunk);
      break;
    }
    if (type == 'PLTE') {
      if (length == 0 || length % 3 != 0 || length > 768) {
        throw _bad('the PNG palette is invalid');
      }
      seenPalette = true;
      out.add(chunk);
      continue;
    }
    if (type.codeUnitAt(0) < 97) {
      // An upper-case first letter: a critical chunk this checker does not know.
      throw _bad('the PNG has an unknown critical chunk ${_repr(type)}');
    }
    if (pngKeep.contains(type)) out.add(chunk);
    // Anything else (tEXt, zTXt, iTXt, eXIf, tIME, private chunks) is
    // metadata: dropped.
  }
  if (width == null || !seenIdat || !seenEnd) {
    throw _bad('the PNG is incomplete (no image data or no end)');
  }
  if (colour == 3 && !seenPalette) {
    throw _bad('the PNG has a palette colour type and no palette');
  }
  if (!inflater!.finish()) {
    throw _bad("the PNG's image data is not as long as its size says");
  }
  return _Parsed(width, height!, _join(out));
}

/// The PNG image data inflated piece by piece and counted, never kept: it is
/// refused as soon as it is longer than [expected].
class _Inflater {
  _Inflater(this.expected);

  final int expected;
  final _filter = RawZLibFilter.inflateFilter();
  final _head = <int>[];
  var _started = false;
  var _inflated = 0;
  var _a = 1, _b = 0; // the Adler-32 of the output so far

  void feed(Uint8List body) {
    if (body.isEmpty) return;
    List<int> input = body;
    if (!_started) {
      // The filter would also take a gzip stream; Python's zlib does not.
      _head.addAll(body);
      if (_head.length < 2) return;
      if (_head[0] == 0x1F && _head[1] == 0x8B) {
        throw const FormatException('incorrect header check');
      }
      input = _head;
      _started = true;
    }
    _filter.process(input, 0, input.length);
    for (;;) {
      final piece = _filter.processed(flush: false);
      if (piece == null) break;
      _inflated += piece.length;
      if (_inflated > expected) {
        throw _bad("the PNG's image data is larger than its size says");
      }
      _adler(piece);
    }
  }

  /// Whether the zlib stream ended with exactly [expected] bytes.
  bool finish() {
    if (!_started || _inflated != expected) return false;
    // The filter does not say whether the stream ended: probe it. After the
    // end it takes more input with no output and no error. Before the end
    // the probe is read as compressed data (giving output or an error) or as
    // the Adler-32 at the end, which it cannot match: its byte differs from
    // each of the four.
    final check = [_b >> 8, _b & 0xFF, _a >> 8, _a & 0xFF];
    var byte = 0xFF;
    while (check.contains(byte)) {
      byte--;
    }
    final probe = Uint8List(4096)..fillRange(0, 4096, byte);
    try {
      _filter.process(probe, 0, probe.length);
      return _filter.processed(flush: false) == null;
    } on FormatException {
      return false;
    }
  }

  void _adler(List<int> data) {
    var a = _a, b = _b;
    var i = 0;
    while (i < data.length) {
      final end = i + 5552 < data.length ? i + 5552 : data.length;
      for (; i < end; i++) {
        a += data[i];
        b += a;
      }
      a %= 65521;
      b %= 65521;
    }
    _a = a;
    _b = b;
  }
}

// --- JPEG --------------------------------------------------------------------

/// Frame headers: SOF0-SOF15 apart from DHT (C4), JPG (C8) and DAC (CC).
const _sof = {
  0xC0,
  0xC1,
  0xC2,
  0xC3,
  0xC5,
  0xC6,
  0xC7,
  0xC9,
  0xCA,
  0xCB,
  0xCD,
  0xCE,
  0xCF,
};

/// Application segments kept: APP0 (JFIF), APP2 (ICC profile), APP14 (Adobe
/// colour transform).
const jpegKeepApp = {0xE0, 0xE2, 0xEE};

_Parsed _jpeg(Uint8List data) {
  final out = <List<int>>[
    const [0xFF, 0xD8],
  ];
  var pos = 2;
  int? width, height;
  for (;;) {
    if (pos + 4 > data.length) {
      throw _bad('the JPEG ends before its image data');
    }
    if (data[pos] != 0xFF) throw _bad("the JPEG's segments are damaged");
    final marker = data[pos + 1];
    if (marker == 0xFF) {
      pos += 1; // fill byte
      continue;
    }
    if (marker == 0xD8 ||
        marker == 0xD9 ||
        (marker >= 0xD0 && marker <= 0xD7) ||
        marker == 0x01) {
      throw _bad('the JPEG has a misplaced marker');
    }
    final length = _u16be(data, pos + 2);
    if (length < 2 || pos + 2 + length > data.length) {
      throw _bad('a JPEG segment is longer than the file');
    }
    final seg = Uint8List.sublistView(data, pos, pos + 2 + length);
    final body = Uint8List.sublistView(data, pos + 4, pos + 2 + length);
    pos += 2 + length;
    if (_sof.contains(marker)) {
      if (width != null) throw _bad('the JPEG has two frames');
      if (body.length < 6) throw _bad('the JPEG frame header is short');
      final h = _u16be(body, 1), w = _u16be(body, 3), comps = body[5];
      if (w == 0 ||
          h == 0 ||
          !(comps == 1 || comps == 3 || comps == 4) ||
          body.length != 6 + 3 * comps) {
        throw _bad('the JPEG frame header is invalid');
      }
      width = w;
      height = h;
      out.add(seg);
    } else if (marker == 0xDA) {
      // Start of scan: image data, more tables and scans, then the end.
      if (width == null) {
        throw _bad('the JPEG has no frame header before its image data');
      }
      out.add(seg);
      _jpegScans(data, pos, out);
      // Anything after the end marker is dropped.
      return _Parsed(width, height!, _join(out));
    } else if (marker >= 0xE0 && marker <= 0xEF) {
      if (jpegKeepApp.contains(marker)) out.add(seg);
      // APP1 (EXIF, XMP), APP13 (IPTC) and the other application segments:
      // dropped.
    } else if (marker == 0xFE) {
      // A comment: dropped.
    } else {
      out.add(seg); // tables (DQT, DHT, DRI, ...)
    }
  }
}

/// Copies the entropy-coded data from [pos] to the end marker into [out]
/// (dropping comments and application segments between scans); returns the
/// end marker's position.
int _jpegScans(Uint8List data, int pos, List<List<int>> out) {
  var start = pos;
  for (;;) {
    final i = data.indexOf(0xFF, pos);
    if (i < 0 || i + 1 >= data.length) throw _bad('the JPEG has no end');
    final marker = data[i + 1];
    if (marker == 0x00 ||
        (marker >= 0xD0 && marker <= 0xD7) ||
        marker == 0xFF) {
      // A stuffed byte, a restart marker or a fill byte.
      pos = marker == 0xFF ? i + 1 : i + 2;
      continue;
    }
    out.add(Uint8List.sublistView(data, start, i));
    if (marker == 0xD9) {
      out.add(const [0xFF, 0xD9]);
      return i;
    }
    if (marker == 0xD8 || marker == 0x01 || _sof.contains(marker)) {
      throw _bad('the JPEG has a misplaced marker in its image data');
    }
    if (i + 4 > data.length) throw _bad('the JPEG ends inside a segment');
    final length = _u16be(data, i + 2);
    if (length < 2 || i + 2 + length > data.length) {
      throw _bad('a JPEG segment is longer than the file');
    }
    if (!((marker >= 0xE0 && marker <= 0xEF) || marker == 0xFE) ||
        jpegKeepApp.contains(marker)) {
      // Tables and the next scan's header.
      out.add(Uint8List.sublistView(data, i, i + 2 + length));
    }
    pos = start = i + 2 + length;
  }
}

// --- WebP --------------------------------------------------------------------

const vp8xExif = 0x08;
const vp8xXmp = 0x04;
const vp8xAnim = 0x02;

_Parsed _webp(Uint8List data) {
  final riff = _u32le(data, 4);
  if (riff + 8 != data.length && riff + 8 + 1 != data.length) {
    throw _bad("the WebP file's size does not match its header");
  }
  var pos = 12;
  final chunks = <(String, Uint8List)>[];
  while (pos < riff + 8) {
    if (pos + 8 > data.length) throw _bad('the WebP ends inside a chunk');
    final fourcc = String.fromCharCodes(data, pos, pos + 4);
    final length = _u32le(data, pos + 4);
    if (pos + 8 + length > data.length) {
      throw _bad('a WebP chunk is longer than the file');
    }
    chunks.add((
      fourcc,
      Uint8List.sublistView(data, pos + 8, pos + 8 + length),
    ));
    pos += 8 + length + (length & 1);
  }
  if (chunks.isEmpty) throw _bad('the WebP has no image');
  final (first, body) = chunks[0];
  if (chunks.any((c) => c.$1 == 'ANIM' || c.$1 == 'ANMF')) {
    throw _bad('animated WebP is not accepted');
  }
  final int width, height;
  final List<(String, List<int>)> kept;
  if (first == 'VP8 ') {
    (width, height) = _vp8(body);
    kept = [chunks[0]];
  } else if (first == 'VP8L') {
    (width, height) = _vp8l(body);
    kept = [chunks[0]];
  } else if (first == 'VP8X') {
    if (body.length < 10) throw _bad('the WebP extended header is short');
    final flags = body[0];
    if (flags & vp8xAnim != 0) throw _bad('animated WebP is not accepted');
    width = 1 + _u24le(body, 4);
    height = 1 + _u24le(body, 7);
    final frames = [
      for (final c in chunks)
        if (c.$1 == 'VP8 ' || c.$1 == 'VP8L') c,
    ];
    if (frames.length != 1) {
      throw _bad('the WebP must hold exactly one image');
    }
    final (fw, fh) = frames[0].$1 == 'VP8 '
        ? _vp8(frames[0].$2)
        : _vp8l(frames[0].$2);
    if (fw != width || fh != height) {
      throw _bad('the WebP image does not fill its canvas');
    }
    final header = Uint8List.fromList(body)
      ..[0] = flags & ~(vp8xExif | vp8xXmp) & 0xFF;
    kept = [
      ('VP8X', header),
      for (final c in chunks.skip(1))
        if (const {'ICCP', 'ALPH', 'VP8 ', 'VP8L'}.contains(c.$1)) c,
    ];
  } else {
    throw _bad('the WebP has no image header');
  }
  final payload = BytesBuilder(copy: false);
  for (final (fourcc, b) in kept) {
    payload
      ..add(fourcc.codeUnits)
      ..add(_le32(b.length))
      ..add(b);
    if (b.length & 1 != 0) payload.addByte(0);
  }
  final out = BytesBuilder(copy: false)
    ..add('RIFF'.codeUnits)
    ..add(_le32(4 + payload.length))
    ..add('WEBP'.codeUnits)
    ..add(payload.takeBytes());
  return _Parsed(width, height, out.takeBytes());
}

List<int> _le32(int n) => [
  n & 0xFF,
  n >> 8 & 0xFF,
  n >> 16 & 0xFF,
  n >> 24 & 0xFF,
];

(int, int) _vp8(Uint8List body) {
  if (body.length < 10 ||
      body[3] != 0x9D ||
      body[4] != 0x01 ||
      body[5] != 0x2A ||
      body[0] & 1 != 0) {
    throw _bad("the WebP's VP8 image is not a key frame");
  }
  return (_u16le(body, 6) & 0x3FFF, _u16le(body, 8) & 0x3FFF);
}

(int, int) _vp8l(Uint8List body) {
  if (body.length < 5 || body[0] != 0x2F) {
    throw _bad("the WebP's lossless image header is invalid");
  }
  final bits = _u32le(body, 1);
  if (bits >> 29 != 0) {
    // The version must be 0.
    throw _bad("the WebP's lossless image has an unknown version");
  }
  return (1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF));
}
