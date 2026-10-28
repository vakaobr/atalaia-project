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
      'field-map.html': Uint8List.fromList(utf8.encode('map')),
      'field-map.js': Uint8List.fromList(utf8.encode('// map')),
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

    Map<String, String> policy(String csp) => {
      for (final d in csp.split(';'))
        d.trim().split(' ').first: d.trim().substring(
          d.trim().indexOf(' ') + 1,
        ),
    };

    test('only the field-map page has its own policy (MF-64)', () {
      final page = get(fieldMapPage);
      expect(page.status, 200);
      expect(page.headers, fieldMapSecurityHeaders);
      final csp = policy(page.headers['Content-Security-Policy']!);
      expect(csp['script-src'], "'self'");
      expect(csp['style-src'], "'self'");
      expect(csp['default-src'], "'self'");
      expect(csp['img-src'], contains('https://tile.openstreetmap.org'));
      expect(csp['connect-src'], contains('https://overpass-api.de'));
      expect(csp['connect-src'], contains('https://overpass.private.coffee'));
      expect(
        csp['connect-src'],
        contains('https://nominatim.openstreetmap.org'),
      );
      expect(csp['img-src'], contains('https://wmts1.geoportail.lu'));
      expect(csp['connect-src'], isNot(contains('wmts')));
      expect(
        page.headers['Content-Security-Policy'],
        isNot(anyOf(contains('unsafe'), contains('mail.ru'))),
      );
      expect(page.headers['Permissions-Policy'], 'geolocation=(self)');
      expect(page.headers['X-Content-Type-Options'], 'nosniff');
      expect(page.headers['Referrer-Policy'], 'no-referrer');
      // Every other file of the console keeps the strict policy.
      for (final path in [
        '/console/',
        '/console/index.html',
        '/console/field-map.js',
        '/console/scoreboard.html',
        '/console/app.js',
        '/console/nope.html',
      ]) {
        final h = get(path).headers;
        expect(
          h['Content-Security-Policy'],
          consoleSecurityHeaders['Content-Security-Policy'],
          reason: path,
        );
        expect(
          h['Content-Security-Policy'],
          isNot(contains('https://')),
          reason: path,
        );
        expect(h['Permissions-Policy'], 'geolocation=()', reason: path);
      }
    });

    test("the field-map origins are the Pi's api.py's (MF-64)", () {
      final src = File(
        '../controller/atalaia_controller/api.py',
      ).readAsStringSync();
      final start = src.indexOf('FIELD_MAP_ORTHOPHOTOS = (');
      final end = src.indexOf('_ORTHOPHOTOS = " ".join');
      final origins = RegExp(
        r'"(https://[^"]+)"',
      ).allMatches(src.substring(start, end)).map((m) => m[1]!).toList();
      expect(origins.length, greaterThan(20));
      final csp = policy(fieldMapSecurityHeaders['Content-Security-Policy']!);
      final imgs = csp['img-src']!
          .split(' ')
          .where((o) => o.startsWith('https://'))
          .toSet();
      final conns = csp['connect-src']!
          .split(' ')
          .where((o) => o.startsWith('https://'))
          .toSet();
      expect(imgs.union(conns), {
        ...origins,
        'https://tile.openstreetmap.org',
        'https://overpass-api.de',
        'https://overpass.private.coffee',
        'https://nominatim.openstreetmap.org',
      });
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
      expect(index.headers['Permissions-Policy'], 'geolocation=()');
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

    // Decision PE24-70: whoami's `features` names the console's areas this
    // controller serves; the console hides the rest. One endpoint per area
    // (the Pi's controller/tests/test_console.py has the same list): served
    // when listed, unknown (the router's 404) when not, so the list cannot
    // drift from the routes.
    const areas = {
      'checkin': ('GET', '/api/v1/checkin/poster'),
      'join': ('POST', '/api/v1/join'),
      'box_language': ('GET', '/api/v1/settings/box-language'),
      'positions': ('GET', '/api/v1/positions'),
      'presets': ('GET', '/api/v1/presets'),
      'branding': ('GET', '/api/v1/field/branding'),
      'radio': ('GET', '/api/v1/radio'),
      'boxes': ('GET', '/api/v1/boxes'),
      'adoption': ('GET', '/api/v1/adopt'),
      'firmware': ('GET', '/api/v1/firmware'),
      'pod_config': ('GET', '/api/v1/pod-config'),
      'atak': ('GET', '/api/v1/atak'),
      'field': ('GET', '/api/v1/field/features'),
      'scenarios': ('GET', '/api/v1/scenarios'),
      'schedule': ('GET', '/api/v1/schedule'),
      'mode_packages': ('GET', '/api/v1/mode-fetch'),
      'failover': ('POST', '/api/v1/controller/promote'),
    };

    /// Whether the router knows [method] [path] (not its 404 or 405).
    Future<bool> routed(String method, String path) async {
      final r = await api.handleAsync(
        method,
        Uri.parse(path),
        authorization: 'Bearer gm',
        body: method == 'GET' ? '' : '{}',
      );
      final body = r.body;
      final unknown =
          body is Map && body['detail'] == 'Not Found' && r.status == 404;
      return !(unknown || r.status == 405);
    }

    test("whoami's features: the areas served, the rest unknown", () async {
      for (final token in ['gm', 'rd']) {
        final who = api.handle(
          'GET',
          Uri.parse('/api/v1/whoami'),
          authorization: 'Bearer $token',
        );
        expect(who.status, 200);
        expect(
          (who.body! as Map<String, Object?>)['features'],
          controllerFeatures,
          reason: token,
        );
      }
      expect(
        controllerFeatures.toSet().difference(areas.keys.toSet()),
        isEmpty,
      );
      for (final MapEntry(key: area, value: (method, path)) in areas.entries) {
        expect(
          await routed(method, path),
          controllerFeatures.contains(area),
          reason: '$area: $method $path',
        );
      }
      // The console's other calls in the areas served since slice S7b.
      for (final (method, path) in [
        ('GET', '/api/v1/team-presets'),
        ('POST', '/api/v1/crests'),
        ('PUT', '/api/v1/games/1/teams/red'),
        ('GET', '/api/v1/mode-packages'),
        ('POST', '/api/v1/modes'),
        ('POST', '/api/v1/scenarios/check'),
      ]) {
        expect(await routed(method, path), isTrue, reason: '$method $path');
      }
      // The other calls of the areas slice S7 added: a standby's join
      // (failover) and a game made from the schedule. Every area is served
      // since slice S7, as on the Pi.
      expect(await routed('POST', '/api/v1/controller/join'), isTrue);
      expect(await routed('POST', '/api/v1/schedule/1/game'), isTrue);
      expect(controllerFeatures.toSet(), areas.keys.toSet());
      // The console's other calls in the areas slice S7a added (field, radio).
      for (final (method, path) in [
        ('GET', '/api/v1/field'),
        ('GET', '/api/v1/games/1/positions'),
        ('PUT', '/api/v1/games/1/positions/2'),
        ('PUT', '/api/v1/field/levels'),
        ('POST', '/api/v1/field/levels/0/from-map'),
        ('POST', '/api/v1/radio/scan'),
        ('DELETE', '/api/v1/radio/scan'),
        ('POST', '/api/v1/radio/random'),
      ]) {
        expect(await routed(method, path), isTrue, reason: '$method $path');
      }
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
