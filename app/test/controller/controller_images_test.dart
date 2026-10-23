// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Branding images on the Android field controller (controller_images.dart):
// the image cases of the Pi's test_branding.py, the cross-check cases made
// with the Pi's images.py (fixtures/controller_images.json), and damaged
// files that must only ever give an ImageError.

import 'dart:convert';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_images.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

const _branding = '../controller/tests/fixtures/branding';

Uint8List fixture(String name) => File('$_branding/$name').readAsBytesSync();

Uint8List _bytes(String s) => Uint8List.fromList(latin1.encode(s));

List<int> _be32(int n) => [
  n >> 24 & 0xFF,
  n >> 16 & 0xFF,
  n >> 8 & 0xFF,
  n & 0xFF,
];

Uint8List chunk(String type, List<int> body) {
  final typed = [...latin1.encode(type), ...body];
  return Uint8List.fromList([
    ..._be32(body.length),
    ...typed,
    ..._be32(crc32(typed)),
  ]);
}

/// A truecolour PNG made by hand (no image library): extra chunks go before
/// the image data.
Uint8List png(
  int width,
  int height, {
  List<int> rgb = const [200, 30, 40],
  List<Uint8List> extra = const [],
  List<int>? raw,
  (int, int)? ihdr,
}) {
  final (w, h) = ihdr ?? (width, height);
  raw ??= [
    for (var y = 0; y < height; y++) ...[
      0,
      for (var x = 0; x < width; x++) ...rgb,
    ],
  ];
  return Uint8List.fromList([
    ...pngSignature,
    ...chunk('IHDR', [..._be32(w), ..._be32(h), 8, 2, 0, 0, 0]),
    for (final c in extra) ...c,
    ...chunk('IDAT', ZLibCodec().encode(raw)),
    ...chunk('IEND', const []),
  ]);
}

final svg = _bytes(
  '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="64" '
  'height="64"><script>alert(1)</script><rect width="64" height="64"/></svg>',
);

bool _contains(List<int> data, List<int> needle) {
  for (var i = 0; i + needle.length <= data.length; i++) {
    var j = 0;
    while (j < needle.length && data[i + j] == needle[j]) {
      j++;
    }
    if (j == needle.length) return true;
  }
  return false;
}

bool _endsWith(List<int> data, List<int> tail) =>
    data.length >= tail.length &&
    _contains(data.sublist(data.length - tail.length), tail);

ImageError refused(Uint8List data, String? declared, ImageLimits limits) {
  try {
    checkImage(data, declared, limits);
  } on ImageError catch (e) {
    return e;
  }
  fail('accepted');
}

void expectError(ImageError e, int status, String text) {
  expect(e.status, status, reason: e.message);
  expect(e.message, contains(text));
}

void main() {
  test('real files are accepted and stripped', () {
    final cases = [
      (
        'logo.png',
        'image/png',
        ImageLimits.logo,
        (256, 128),
        ['tEXt', 'Someone Private'],
      ),
      (
        'logo.jpg',
        'image/jpeg',
        ImageLimits.logo,
        (200, 200),
        ['Exif\x00', 'private comment', 'PhoneMaker'],
      ),
      (
        'wallpaper.webp',
        'image/webp',
        ImageLimits.wallpaper,
        (640, 400),
        ['EXIF', 'PhoneMaker'],
      ),
      (
        'wallpaper.jpg',
        'image/jpeg',
        ImageLimits.wallpaper,
        (800, 500),
        ['Exif\x00', 'PhoneMaker'],
      ),
      ('crest-red.png', 'image/png', ImageLimits.crest, (128, 128), <String>[]),
      (
        'crest-blue.webp',
        'image/webp',
        ImageLimits.crest,
        (128, 128),
        <String>[],
      ),
    ];
    for (final (name, type, limits, size, private) in cases) {
      final data = fixture(name);
      for (final marker in private) {
        expect(
          _contains(data, _bytes(marker)),
          isTrue,
          reason: '$name carries $marker',
        );
      }
      final out = checkImage(data, type, limits);
      expect(
        (out.contentType, out.width, out.height),
        (type, size.$1, size.$2),
        reason: name,
      );
      for (final marker in private) {
        expect(
          _contains(out.data, _bytes(marker)),
          isFalse,
          reason: '$name keeps $marker',
        );
      }
      expect(out.data.length, lessThanOrEqualTo(data.length));
      expect(
        checkImage(out.data, type, limits).data,
        out.data,
        reason: 'stripping is stable',
      );
    }
  });

  test('the WebP extended header loses its metadata flags', () {
    final out = checkImage(
      fixture('wallpaper.webp'),
      'image/webp',
      ImageLimits.wallpaper,
    ).data;
    expect(latin1.decode(out.sublist(12, 16)), 'VP8X');
    expect(out[20] & (vp8xExif | vp8xXmp), 0);
    expect(
      ByteData.sublistView(out).getUint32(4, Endian.little) + 8,
      out.length,
    );
  });

  test('refused types', () {
    final cases = [
      (fixture('not-allowed.gif'), 'image/gif', 415),
      (svg, 'image/svg+xml', 415),
      (svg, 'image/png', 415),
      (_bytes('<html><script>x</script></html>'), 'image/webp', 415),
      (fixture('logo.png'), 'image/jpeg', 415),
      (fixture('logo.png'), '', 415),
      (Uint8List(0), 'image/png', 422),
    ];
    for (final (data, type, status) in cases) {
      expect(
        refused(data, type, ImageLimits.logo).status,
        status,
        reason: type,
      );
    }
    final untyped = refused(fixture('logo.png'), null, ImageLimits.logo);
    expectError(untyped, 415, 'not untyped');
  });

  test('size, dimension and animation limits', () {
    final over = Uint8List(ImageLimits.logo.maxBytes + 4)
      ..setAll(0, [0x89, 0x50, 0x4E, 0x47]);
    final big = refused(over, 'image/png', ImageLimits.logo);
    expectError(big, 413, '1048576');
    final cases = [
      (png(8, 8), ImageLimits.logo, 'each side'),
      (png(20, 20), ImageLimits.wallpaper, 'each side'),
      // A header claiming 5000 pixels is refused before any inflating.
      (png(20, 20, ihdr: (5000, 20)), ImageLimits.logo, '5000x20'),
      (png(400, 40), ImageLimits.logo, 'times as long'),
      (png(100, 20), ImageLimits.crest, 'times as long'),
    ];
    for (final (data, limits, text) in cases) {
      final e = refused(data, 'image/png', limits);
      expectError(e, 422, text);
    }
    expect(
      refused(fixture('animated.png'), 'image/png', ImageLimits.crest).status,
      422,
    );
    expect(
      refused(fixture('animated.webp'), 'image/webp', ImageLimits.crest).status,
      422,
    );
    expect(checkImage(png(64, 64), 'image/png', ImageLimits.crest).width, 64);
    expect(checkImage(png(128, 16), 'image/png', ImageLimits.logo).width, 128);
  });

  test('broken files', () {
    final good = png(32, 32);
    final badCrc = Uint8List.fromList(good)
      ..[29] ^= 0xFF; // inside IHDR's checksum
    final jpeg = fixture('logo.jpg');
    var half = jpeg.sublist(0, jpeg.length ~/ 2);
    while (half.isNotEmpty && (half.last == 0xFF || half.last == 0xD9)) {
      half = half.sublist(0, half.length - 1);
    }
    final webp = fixture('crest-blue.webp');
    final cases = {
      'crc': (badCrc, 'image/png'),
      'truncated': (good.sublist(0, good.length - 20), 'image/png'),
      // The header says 32x32 and the data inflates to more (a small
      // decompression bomb) or less.
      'bomb': (png(32, 32, raw: Uint8List(33 * 97 * 50)), 'image/png'),
      'short': (png(32, 32, raw: Uint8List(100)), 'image/png'),
      'unknown critical chunk': (
        png(
          32,
          32,
          extra: [
            chunk('ZZZZ', [0x78]),
          ],
        ),
        'image/png',
      ),
      'jpeg without end': (half, 'image/jpeg'),
      'jpeg header only': (jpeg.sublist(0, 20), 'image/jpeg'),
      'webp size': (webp.sublist(0, webp.length - 10), 'image/webp'),
    };
    cases.forEach((name, c) {
      expect(refused(c.$1, c.$2, ImageLimits.logo).status, 422, reason: name);
    });
  });

  test('a decompression bomb is refused without inflating it all', () {
    // 64 MB of zeros in about 64 KB, behind a 2048x2048 header (12 MB).
    final encoder = ZLibEncoder(level: 9);
    final raw = Uint8List(1 << 20);
    final sink = _Collect();
    final conv = encoder.startChunkedConversion(sink);
    for (var i = 0; i < 64; i++) {
      conv.add(raw);
    }
    conv.close();
    final data = Uint8List.fromList([
      ...pngSignature,
      ...chunk('IHDR', [..._be32(2048), ..._be32(2048), 8, 2, 0, 0, 0]),
      ...chunk('IDAT', sink.bytes),
      ...chunk('IEND', const []),
    ]);
    final e = refused(data, 'image/png', ImageLimits.logo);
    expectError(e, 422, 'larger than its size says');
  });

  test('the end of the zlib stream is checked', () {
    final raw = [
      for (var y = 0; y < 32; y++) ...[
        0,
        for (var x = 0; x < 96; x++) (x * y) & 0xFF,
      ],
    ];
    final z = ZLibCodec().encode(raw);
    Uint8List withData(List<int> zdata, {List<int>? second}) =>
        Uint8List.fromList([
          ...pngSignature,
          ...chunk('IHDR', [..._be32(32), ..._be32(32), 8, 2, 0, 0, 0]),
          ...chunk('IDAT', zdata),
          if (second != null) ...chunk('IDAT', second),
          ...chunk('IEND', const []),
        ]);
    expect(checkImage(withData(z), 'image/png', ImageLimits.logo).width, 32);
    // Data after the stream's end is ignored, as Python's zlib does.
    expect(
      checkImage(
        withData([...z, 1, 2, 3]),
        'image/png',
        ImageLimits.logo,
      ).width,
      32,
    );
    expect(
      checkImage(
        withData(z, second: [0xFF, 0xFF]),
        'image/png',
        ImageLimits.logo,
      ).width,
      32,
    );
    // The header split over two chunks.
    expect(
      checkImage(
        withData(z.sublist(0, 1), second: z.sublist(1)),
        'image/png',
        ImageLimits.logo,
      ).width,
      32,
    );
    for (var cut = 1; cut <= 6; cut++) {
      expect(
        refused(
          withData(z.sublist(0, z.length - cut)),
          'image/png',
          ImageLimits.logo,
        ).status,
        422,
        reason: 'cut $cut',
      );
    }
    // The same data as gzip: dart:io would take it, Python's zlib does not.
    expect(
      refused(
        withData(GZipCodec().encode(raw)),
        'image/png',
        ImageLimits.logo,
      ).message,
      contains('damaged'),
    );
  });

  test('trailing data and private chunks are dropped', () {
    final text = chunk('tEXt', _bytes('Author\x00Someone'));
    final private = chunk('prVt', _bytes('secret'));
    final data = Uint8List.fromList([
      ...png(40, 40, extra: [text, private]),
      ..._bytes('PK\x03\x04 appended zip'),
    ]);
    final out = checkImage(data, 'image/png', ImageLimits.logo).data;
    expect(_contains(out, _bytes('Someone')), isFalse);
    expect(_contains(out, _bytes('secret')), isFalse);
    expect(_endsWith(out, chunk('IEND', const [])), isTrue);
    final jpeg = Uint8List.fromList([
      ...fixture('logo.jpg'),
      ..._bytes('trailing'),
    ]);
    expect(
      _endsWith(checkImage(jpeg, 'image/jpeg', ImageLimits.logo).data, [
        0xFF,
        0xD9,
      ]),
      isTrue,
    );
  });

  group('the same results as images.py', () {
    final doc =
        jsonDecode(
              File(
                'test/controller/fixtures/controller_images.json',
              ).readAsStringSync(),
            )
            as Map<String, dynamic>;
    final cases = (doc['cases'] as List<dynamic>).cast<Map<String, dynamic>>();
    test('there are cases', () => expect(cases.length, greaterThan(100)));
    for (final c in cases) {
      test(c['name'] as String, () {
        final data = base64.decode(c['data'] as String);
        final limits = ImageLimits.kinds[c['kind'] as String]!;
        final declared = c['declared'] as String;
        if (c.containsKey('status')) {
          final e = refused(data, declared, limits);
          expect((e.status, e.message), (c['status'], c['message']));
        } else {
          final out = checkImage(data, declared, limits);
          expect(
            (
              out.contentType,
              out.width,
              out.height,
              out.data.length,
              sha256.convert(out.data).toString(),
            ),
            (
              c['content_type'],
              c['width'],
              c['height'],
              c['size'],
              c['sha256'],
            ),
          );
        }
      });
    }
  });

  test('damaged files only ever give an ImageError', () {
    final rng = Random(7);
    final seeds = [
      ('image/png', fixture('logo.png')),
      ('image/png', fixture('crest-red.png')),
      ('image/png', fixture('animated.png')),
      ('image/jpeg', fixture('logo.jpg')),
      ('image/webp', fixture('crest-blue.webp')),
      ('image/webp', fixture('animated.webp')),
      ('image/png', png(40, 40)),
    ];
    var tried = 0;
    for (final (type, seed) in seeds) {
      for (var n = 0; n < 300; n++) {
        final data = Uint8List.fromList(seed);
        final edits = 1 + rng.nextInt(4);
        for (var k = 0; k < edits; k++) {
          data[3 + rng.nextInt(data.length - 3)] = rng.nextInt(256);
        }
        final cut = rng.nextBool()
            ? data
            : data.sublist(0, 3 + rng.nextInt(data.length - 3));
        try {
          checkImage(cut, type, ImageLimits.wallpaper);
        } on ImageError catch (e) {
          expect([413, 415, 422], contains(e.status));
        }
        tried++;
      }
    }
    expect(tried, 2100);
  });
}

class _Collect implements Sink<List<int>> {
  final _b = BytesBuilder();

  Uint8List get bytes => _b.toBytes();

  @override
  void add(List<int> data) => _b.add(data);

  @override
  void close() {}
}
