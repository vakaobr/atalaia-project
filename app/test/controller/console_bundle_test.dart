// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The GM console a phone controller serves is the Pi's (slice S6 of PE24,
// decision PE24-61): the app's assets hold every file of
// controller/console/src byte for byte, and pubspec.yaml lists every folder
// of it (Flutter's asset folders are not recursive, so a new folder in the
// console would otherwise be left out of the APK); the check-in notices are
// controller/templates'. Then the phone's API serves them as the Pi's api.py
// does: the redirects, a folder's index.html, the types and the security
// headers, no token needed, nothing outside the console.

import 'dart:convert';
import 'dart:io';

import 'package:atalaia_app/controller/console_assets.dart';
import 'package:atalaia_app/controller/console_files.dart';
import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

/// Every file under [dir], by its path relative to it.
Map<String, Uint8List> filesUnder(String dir) {
  final root = Directory(dir).absolute;
  final n = root.path.length + 1;
  return {
    for (final e in root.listSync(recursive: true))
      if (e is File)
        e.path.substring(n).replaceAll(r'\', '/'): e.readAsBytesSync(),
  };
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test("the app's assets are controller/console/src, byte for byte", () async {
    final source = filesUnder('../controller/console/src');
    expect(
      source,
      contains('index.html'),
      reason: 'run from app/ in the repository',
    );
    final bundled = await loadConsoleFiles(rootBundle);
    expect(
      bundled.files.keys.toSet(),
      source.keys.toSet(),
      reason:
          'every console file in the APK: a folder missing from pubspec.yaml '
          "(flutter: assets:) or a copy that is not the console's "
          '(dart tool/sync_console.dart)',
    );
    for (final e in source.entries) {
      expect(bundled.files[e.key], e.value, reason: e.key);
    }
  });

  test('pubspec.yaml lists every folder of the console', () {
    final pubspec = File('pubspec.yaml').readAsStringSync();
    final folders = <String>{
      for (final p in filesUnder('../controller/console/src').keys)
        p.contains('/')
            ? 'assets/console/${p.substring(0, p.lastIndexOf('/'))}/'
            : 'assets/console/',
    };
    for (final f in folders) {
      expect(pubspec, contains('    - $f\n'), reason: f);
    }
  });

  test("the check-in notices are controller/templates'", () async {
    final (pt, en) = await loadNotices(rootBundle);
    expect(
      pt,
      File('../controller/templates/checkin-notice-pt.md').readAsStringSync(),
    );
    expect(
      en,
      File('../controller/templates/checkin-notice-en.md').readAsStringSync(),
    );
    expect(pt, contains('{retention_days}'));
  });

  group("the phone's API serves them as the Pi's", () {
    final files = ConsoleFiles({
      'index.html': Uint8List.fromList(utf8.encode('<!DOCTYPE html>console')),
      'scoreboard.html': Uint8List.fromList(utf8.encode('board')),
      'app.js': Uint8List.fromList(utf8.encode('// js')),
      'icons/icon-192.png': Uint8List.fromList([0x89, 0x50, 0x4e, 0x47]),
      'i18n/pt.json': Uint8List.fromList(utf8.encode('{}')),
    });
    late ControllerApi api;
    setUp(() {
      api = ControllerApi(ControllerEngine(), gmToken: 'gm', readToken: 'rd')
        ..console = files;
    });

    ApiResponse get(String path) => api.handle('GET', Uri.parse(path));

    test('redirects', () {
      for (final (from, to) in [
        ('/', '/console/'),
        ('/console', '/console/'),
        ('/scoreboard', '/console/scoreboard.html'),
      ]) {
        final r = get(from);
        expect(r.status, 307, reason: from);
        expect(r.headers['Location'], to, reason: from);
      }
    });

    test('files, their types and the security headers, with no token', () {
      final index = get('/console/');
      expect(index.status, 200);
      expect(utf8.decode(index.data!), '<!DOCTYPE html>console');
      expect(index.contentType, 'text/html; charset=utf-8');
      expect(
        index.headers['Content-Security-Policy'],
        contains("default-src 'self'"),
      );
      expect(index.headers['X-Content-Type-Options'], 'nosniff');
      expect(index.headers['Referrer-Policy'], 'no-referrer');
      expect(
        get('/console/app.js').contentType,
        'text/javascript; charset=utf-8',
      );
      expect(get('/console/icons/icon-192.png').contentType, 'image/png');
      expect(get('/console/i18n/pt.json').contentType, 'application/json');
    });

    test('nothing else: missing files, other paths, the API untouched', () {
      expect(get('/console/nope.js').status, 404);
      expect(get('/console/../controller/README.md').status, 404);
      expect(get('/console/%2e%2e/x').status, 404);
      expect(get('/healthz').status, 200);
      expect(get('/api/v1/whoami').status, 401);
      // Without the console's files (a Pi without its folder): nothing.
      api.console = ConsoleFiles(const {});
      expect(get('/console/').status, 404);
      expect(get('/').status, 404);
    });

    test(
      'the field CA: 404 with HTTPS off, else the PEM with its fingerprint',
      () {
        expect(get('/api/v1/controller/ca').status, 404);
        api
          ..caPem =
              '-----BEGIN CERTIFICATE-----\nAA==\n-----END CERTIFICATE-----\n'
          ..caSha256Hex = 'ab' * 32;
        final r = get('/api/v1/controller/ca');
        expect(r.status, 200);
        expect(r.contentType, 'application/x-pem-file');
        expect(r.text, startsWith('-----BEGIN CERTIFICATE-----'));
        expect(r.headers['X-Atalaia-CA-SHA256'], 'ab' * 32);
      },
    );
  });
}
