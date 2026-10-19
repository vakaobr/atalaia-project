// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// For the branding tests (decisions BR1-BR24): PNG images made here (no
/// image package), a stand-in for a controller's branding endpoints with
/// the same paths, JSON and ETags as controller/atalaia_controller/
/// branding.py, and a helper that lets Flutter decode the images on screen.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/branding/field_branding.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

final _crcTable = List<int>.generate(256, (n) {
  var c = n;
  for (var k = 0; k < 8; k++) {
    c = (c & 1) != 0 ? 0xEDB88320 ^ (c >> 1) : c >> 1;
  }
  return c;
});

int _crc32(List<int> bytes) {
  var c = 0xFFFFFFFF;
  for (final b in bytes) {
    c = _crcTable[(c ^ b) & 0xFF] ^ (c >> 8);
  }
  return c ^ 0xFFFFFFFF;
}

List<int> _chunk(String type, List<int> body) {
  final t = ascii.encode(type);
  final len = ByteData(4)..setUint32(0, body.length);
  final crc = ByteData(4)..setUint32(0, _crc32([...t, ...body]));
  return [
    ...len.buffer.asUint8List(),
    ...t,
    ...body,
    ...crc.buffer.asUint8List(),
  ];
}

/// A [width]x[height] RGBA PNG: [paint] gives each pixel's 0xAARRGGBB
/// (default: a solid colour).
Uint8List testPng(
  int width,
  int height, {
  int argb = 0xFFD7263D,
  int Function(int x, int y)? paint,
}) {
  final raw = BytesBuilder();
  for (var y = 0; y < height; y++) {
    raw.addByte(0);
    for (var x = 0; x < width; x++) {
      final c = paint?.call(x, y) ?? argb;
      raw
        ..addByte((c >> 16) & 0xFF)
        ..addByte((c >> 8) & 0xFF)
        ..addByte(c & 0xFF)
        ..addByte((c >> 24) & 0xFF);
    }
  }
  final ihdr = ByteData(13)
    ..setUint32(0, width)
    ..setUint32(4, height)
    ..setUint8(8, 8)
    ..setUint8(9, 6);
  return Uint8List.fromList([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, //
    ..._chunk('IHDR', ihdr.buffer.asUint8List()),
    ..._chunk('IDAT', ZLibCodec().encode(raw.takeBytes())),
    ..._chunk('IEND', const []),
  ]);
}

/// A logo: a yellow disc on a dark green square, with a transparent corner.
Uint8List testLogo([int size = 96]) => testPng(
  size,
  size,
  paint: (x, y) {
    final dx = x - size / 2, dy = y - size / 2;
    if (dx * dx + dy * dy < size * size / 9) return 0xFFFFB300;
    return x + y < size / 4 ? 0x00000000 : 0xFF1F3A2B;
  },
);

/// A wallpaper: bright diagonal stripes, the hardest background for text.
Uint8List testWallpaper([int w = 360, int h = 640]) => testPng(
  w,
  h,
  paint: (x, y) => ((x + y) ~/ 24).isEven ? 0xFFFFFFFF : 0xFF2A9D4B,
);

/// A crest: a shield-like block in [argb] with a white bar.
Uint8List testCrest(int argb, [int size = 64]) => testPng(
  size,
  size,
  paint: (x, y) {
    if (y > size * 0.75 && (x - size / 2).abs() > (size - y) * 1.2) {
      return 0x00000000;
    }
    if ((x - size / 2).abs() < size / 10) return 0xFFFFFFFF;
    return argb;
  },
);

String sha256Hex(List<int> b) => sha256.convert(b).toString();

/// A controller's branding endpoints, in memory.
class FakeBrandingField implements BrandingSource {
  FakeBrandingField({
    this.fieldId = 'campo-norte',
    this.fieldName = 'Campo Norte',
    this.accent,
    this.logo,
    this.wallpaper,
  });

  String fieldId;
  String fieldName;
  String? accent;
  Uint8List? logo;
  Uint8List? wallpaper;
  final crests = <String, Uint8List>{};

  /// Each game's teams: team -> (display name, crest id).
  final games = <int, Map<String, (String?, String?)>>{};
  final requests = <String>[];
  bool offline = false;

  /// Adds a crest; its id.
  String addCrest(Uint8List bytes) {
    final id = sha256Hex(bytes);
    crests[id] = bytes;
    return id;
  }

  Map<String, Object?>? _ref(String slot, Uint8List? b) => b == null
      ? null
      : {
          'url': '/api/v1/field/branding/$slot',
          'id': sha256Hex(b),
          'etag': '"${sha256Hex(b)}"',
          'content_type': 'image/png',
          'width': 0,
          'height': 0,
          'bytes': b.length,
        };

  Map<String, Object?> view() {
    final out = <String, Object?>{
      'version': 1,
      'field_id': fieldId,
      'field_name': fieldName,
      'accent': accent,
      'logo': _ref('logo', logo),
      'wallpaper': _ref('wallpaper', wallpaper),
    };
    out['etag'] =
        '"${sha256Hex(utf8.encode(jsonEncode(out))).substring(0, 32)}"';
    return out;
  }

  BrandingResponse _bytes(Uint8List? b, String? ifNoneMatch) {
    if (b == null) return BrandingResponse(404, Uint8List(0));
    final tag = '"${sha256Hex(b)}"';
    if (ifNoneMatch == tag) return BrandingResponse(304, Uint8List(0));
    return BrandingResponse(200, b, etag: tag);
  }

  @override
  Future<BrandingResponse> get(String path, {String? ifNoneMatch}) async {
    requests.add(ifNoneMatch == null ? path : '$path (If-None-Match)');
    if (offline) throw const SocketException('unreachable');
    if (path == '/api/v1/field/branding') {
      final v = view();
      final tag = v['etag']! as String;
      if (ifNoneMatch == tag) return BrandingResponse(304, Uint8List(0));
      return BrandingResponse(
        200,
        Uint8List.fromList(utf8.encode(jsonEncode(v))),
        etag: tag,
      );
    }
    if (path == '/api/v1/field/branding/logo') return _bytes(logo, ifNoneMatch);
    if (path == '/api/v1/field/branding/wallpaper') {
      return _bytes(wallpaper, ifNoneMatch);
    }
    if (path.startsWith('/api/v1/crests/')) {
      return _bytes(crests[path.substring(15)], ifNoneMatch);
    }
    final game = RegExp(r'^/api/v1/games/(\d+)/teams$').firstMatch(path);
    if (game != null) {
      final teams = games[int.parse(game.group(1)!)];
      if (teams == null) return BrandingResponse(404, Uint8List(0));
      return BrandingResponse(
        200,
        Uint8List.fromList(
          utf8.encode(
            jsonEncode({
              'game_id': int.parse(game.group(1)!),
              'teams': [
                for (final e in teams.entries)
                  {
                    'team': e.key,
                    'display_name': e.value.$1,
                    'crest_id': e.value.$2,
                  },
              ],
            }),
          ),
        ),
      );
    }
    return BrandingResponse(404, Uint8List(0));
  }
}

/// Lets Flutter decode every image on screen (decoding is real I/O, which
/// a widget test's fake clock does not run by itself), then redraws.
Future<void> decodeImages(WidgetTester tester) async {
  for (var round = 0; round < 3; round++) {
    final images = find.byType(Image).evaluate().toList();
    await tester.runAsync(() async {
      for (final e in images) {
        await precacheImage((e.widget as Image).image, e);
      }
    });
    await tester.pumpAndSettle();
  }
}
