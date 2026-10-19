// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Keeping a field's branding (decisions BR1-BR24): the first download, a
// refresh that costs one 304, a changed or removed image, kept per field id
// across restarts, another field at the same address, out of reach, images
// that are not PNG, JPEG or WebP or too large, crests fetched once and
// checked against their id, and the accent made readable on both themes.

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/branding/field_branding.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/branding.dart';

void main() {
  group('accent', () {
    test('parsed from #rrggbb only', () {
      expect(parseAccent('#C0FFEE'), const Color(0xFFC0FFEE));
      for (final bad in [null, 'red', '#12345', '#1234567', 12, 'c0ffee']) {
        expect(parseAccent(bad), isNull, reason: '$bad');
      }
    });

    test('made readable on both themes (4.5:1)', () {
      for (final hex in [
        '#ffb300',
        '#ffff00',
        '#000080',
        '#101418',
        '#ffffff',
        '#7f7f7f',
        '#d7263d',
      ]) {
        final accent = parseAccent(hex)!;
        for (final b in Brightness.values) {
          final p = brandPrimary(accent, b);
          final bg = b == Brightness.dark
              ? AtalaiaColors.background
              : Colors.white;
          expect(
            contrastRatio(p, bg),
            greaterThanOrEqualTo(4.5),
            reason: '$hex on $b',
          );
        }
      }
      // A colour that already reads is kept as it is.
      const amber = Color(0xFFFFB300);
      expect(brandPrimary(amber, Brightness.dark), amber);
      expect(brandPrimary(amber, Brightness.light), isNot(amber));
    });

    test('image signatures', () {
      expect(isBrandingImage(testPng(2, 2)), isTrue);
      expect(isBrandingImage(Uint8List.fromList([0xFF, 0xD8, 0xFF, 0])), true);
      expect(
        isBrandingImage(Uint8List.fromList(ascii.encode('RIFF....WEBPVP8 '))),
        true,
      );
      expect(
        isBrandingImage(Uint8List.fromList(utf8.encode('<svg xmlns='))),
        false,
      );
      expect(
        isBrandingImage(Uint8List.fromList(ascii.encode('GIF89a......'))),
        false,
      );
    });
  });

  group('the cache', () {
    late MemoryAppStore store;
    late FakeBrandingField field;

    setUp(() {
      store = MemoryAppStore();
      field = FakeBrandingField(
        accent: '#c0ffee',
        logo: testLogo(),
        wallpaper: testWallpaper(64, 64),
      );
    });

    test('first download, then a 304, then kept across a restart', () async {
      final cache = BrandingCache(store);
      final b = (await cache.refresh(field, fieldId: 'campo-norte'))!;
      expect(b.fieldName, 'Campo Norte');
      expect(b.accent, const Color(0xFFC0FFEE));
      expect(b.logo!.bytes, field.logo);
      expect(b.wallpaper!.bytes, field.wallpaper);
      expect(field.requests, [
        '/api/v1/field/branding',
        '/api/v1/field/branding/logo',
        '/api/v1/field/branding/wallpaper',
      ]);
      field.requests.clear();
      final again = await cache.refresh(field, fieldId: 'campo-norte');
      expect(field.requests, ['/api/v1/field/branding (If-None-Match)']);
      expect(again!.logo!.bytes, field.logo);
      // A new process: the same branding from the app's files, no network.
      final fresh = BrandingCache(store);
      field.offline = true;
      final kept = (await fresh.cached('campo-norte'))!;
      expect(kept.logo!.bytes, field.logo);
      expect(kept.wallpaper!.bytes, field.wallpaper);
      expect(kept.accent, const Color(0xFFC0FFEE));
      expect(
        (await fresh.refresh(field, fieldId: 'campo-norte'))!.etag,
        kept.etag,
      );
      expect(await fresh.cached('another-field'), isNull);
    });

    test(
      'a new logo is downloaded alone; a removed wallpaper is dropped',
      () async {
        final cache = BrandingCache(store);
        await cache.refresh(field, fieldId: 'campo-norte');
        field
          ..logo = testCrest(0xFF1B6EE0, 80)
          ..wallpaper = null
          ..accent = null;
        field.requests.clear();
        final b = (await cache.refresh(field, fieldId: 'campo-norte'))!;
        expect(field.requests, [
          '/api/v1/field/branding (If-None-Match)',
          '/api/v1/field/branding/logo',
        ]);
        expect(b.logo!.bytes, field.logo);
        expect(b.wallpaper, isNull);
        expect(b.accent, isNull);
        expect(
          await store.loadBlob('brand-${_key('campo-norte')}-wallpaper'),
          isNull,
        );
      },
    );

    test('another field at the address, out of reach, bad images', () async {
      final cache = BrandingCache(store);
      field.fieldId = 'other';
      expect(await cache.refresh(field, fieldId: 'campo-norte'), isNull);
      field.fieldId = 'campo-norte';
      field.offline = true;
      expect(await cache.refresh(field, fieldId: 'campo-norte'), isNull);
      field.offline = false;
      // An SVG or an oversized logo is not kept: the default look.
      field.logo = Uint8List.fromList(
        utf8.encode('<svg><script>x</script></svg>'),
      );
      field.wallpaper = Uint8List(wallpaperMaxBytes + 1)
        ..setAll(0, testPng(2, 2));
      final b = (await cache.refresh(field, fieldId: 'campo-norte'))!;
      expect(b.logo, isNull);
      expect(b.wallpaper, isNull);
      expect(b.accent, const Color(0xFFC0FFEE));
      // A prop (no field id yet) takes whichever field answers.
      field.fieldId = 'clube-sul';
      field.logo = testLogo();
      final prop = (await BrandingCache(MemoryAppStore()).refresh(field))!;
      expect((prop.fieldId, prop.logo!.bytes), ('clube-sul', field.logo));
    });

    test('forgetting a field drops its branding', () async {
      final cache = BrandingCache(store);
      await cache.refresh(field, fieldId: 'campo-norte');
      await cache.forget('campo-norte');
      expect(await BrandingCache(store).cached('campo-norte'), isNull);
      expect(await store.loadBlob('brand-${_key('campo-norte')}-logo'), isNull);
    });

    test('crests: fetched once, checked against their id', () async {
      final cache = BrandingCache(store);
      final red = field.addCrest(testCrest(0xFFD7263D));
      final blue = field.addCrest(testCrest(0xFF1B6EE0));
      final teams = await cache.teams(field, {
        'red': {'display_name': 'Lobos', 'crest_id': red},
        'blue': {'display_name': 'Águias', 'crest_id': blue},
        'green': {'display_name': 'Verdes'},
      });
      expect(teams.displayName('red'), 'Lobos');
      expect(teams.crest('red'), field.crests[red]);
      expect(teams.crest('green'), isNull);
      expect(teams.displayName('yellow'), isNull);
      field.requests.clear();
      await BrandingCache(store).teams(field, {
        'red': {'crest_id': red},
      });
      expect(field.requests, isEmpty, reason: 'kept in the app files');
      // A crest whose bytes are not its id is refused.
      final fake = 'f' * 64;
      field.crests[fake] = testCrest(0xFF000000);
      expect(await cache.crest(field, fake), isNull);
      expect(await cache.crest(field, '../settings'), isNull);
      // The game's teams for a prop, without a token.
      field.games[9] = {'red': ('Lobos', red), 'blue': (null, null)};
      final g = await cache.gameTeams(field, 9);
      expect(g.displayName('red'), 'Lobos');
      expect(g.crest('red'), isNotNull);
      expect(g.displayName('blue'), isNull);
      expect((await cache.gameTeams(field, 10)).isEmpty, isTrue);
    });

    test('names from a game before the crests arrive', () {
      final t = TeamBranding.namesOf({
        'red': {'display_name': 'Lobos', 'crest_id': 'x'},
        'blue': 'nonsense',
      });
      expect(t.displayName('red'), 'Lobos');
      expect(t.crest('red'), isNull);
      expect(t.displayName('blue'), isNull);
      expect(TeamBranding.namesOf(null).isEmpty, isTrue);
    });
  });
}

String _key(String fieldId) => sha256Hex(utf8.encode(fieldId)).substring(0, 24);
