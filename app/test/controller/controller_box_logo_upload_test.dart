// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A JPEG or WebP logo for a Field Box (decision LOGO-1): the GM console
// converts it in the browser and uploads the box-ready bytes to
// PUT /api/v1/field/branding/logo/box?id=; the box-logo endpoints serve them
// for exactly that logo. The Pi's test_box_logo.py has the same cases.

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_box_logo.dart';
import 'package:atalaia_app/controller/controller_branding.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_store.dart';
import 'package:atalaia_app/ffi/bindings.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/recording_radio.dart';

const _branding = '../controller/tests/fixtures/branding';

Uint8List fixture(String name) => File('$_branding/$name').readAsBytesSync();

void main() {
  late AtalaiaCore core;
  late ControllerApi api;
  setUpAll(() => core = AtalaiaCore.open(coreLibraryPath()));

  setUp(() {
    final e = ControllerEngine(
      store: MemoryControllerStore(),
      core: core,
      transport: RecordingRadio(),
      wallSeconds: () => 1800007200.0,
    );
    ControllerBranding(e);
    api = ControllerApi(e, gmToken: 'g', readToken: 'r');
  });

  ApiResponse put(String path, Uint8List data, String type, {String? token}) =>
      api.handle(
        'PUT',
        Uri.parse(path),
        authorization: token == null
            ? 'Bearer g'
            : (token.isEmpty ? null : token),
        bytes: data,
        contentType: type,
      );

  ApiResponse get(String path) => api.handle('GET', Uri.parse(path));

  String putLogo(String name, String type) {
    final r = put('/api/v1/field/branding/logo', fixture(name), type);
    expect(r.status, 200, reason: '${r.body}');
    return ((r.body! as Map)['logo']! as Map)['id']! as String;
  }

  ApiResponse putBox(String id, Uint8List data, {String? token}) => put(
    '/api/v1/field/branding/logo/box?id=$id',
    data,
    'application/octet-stream',
    token: token,
  );

  // What the console makes in the browser: stood in for by the controller's
  // own conversion of a PNG.
  Uint8List ready() => convertBoxLogo(fixture('logo.png'));

  test('a JPEG logo is served from the console\'s bytes', () {
    expect(get('/api/v1/field/box-logo').status, 404);
    final id = putLogo('logo.jpg', 'image/jpeg');
    expect(get('/api/v1/field/box-logo').status, 404);
    final box = ready();
    expect(putBox(id, box).status, 200);
    final r = get('/api/v1/field/box-logo');
    expect(r.status, 200);
    expect(r.data, box);
    expect(r.headers['ETag'], '"$id"');
    final rel = utf8
        .decode(get('/api/v1/field/box-logo/release').data!)
        .split('\n');
    expect(rel[1], 'id=$id');
    expect(rel[2], 'sha256=${sha256.convert(box)}');
    // A new logo makes the bytes stale.
    putLogo('wallpaper.jpg', 'image/jpeg');
    expect(get('/api/v1/field/box-logo').status, 404);
  });

  test('the controller checks the uploaded bytes', () {
    final id = putLogo('logo.jpg', 'image/jpeg');
    final box = ready();
    final wrongSide = Uint8List.fromList(box)..[4] = 95;
    final wrongMagic = Uint8List.fromList(box)..[0] = 0x58;
    for (final bad in [
      Uint8List.sublistView(box, 0, box.length - 1),
      Uint8List(0),
      wrongMagic,
      wrongSide,
    ]) {
      expect(putBox(id, bad).status, 400, reason: '${bad.length}');
    }
    expect(putBox(id, Uint8List(boxLogoSize + 1)).status, 413);
    expect(get('/api/v1/field/box-logo').status, 404);
    expect(putBox(id, box, token: '').status, 401);
    expect(putBox('0' * 64, box).status, 409);
    expect(get('/api/v1/field/box-logo').status, 404);
  });

  test('a PNG logo is never replaced by uploaded bytes', () {
    final id = putLogo('logo.png', 'image/png');
    expect(putBox(id, ready()).status, 409);
  });

  test('no logo, no box logo', () {
    expect(putBox('0' * 64, ready()).status, 409);
  });
}
