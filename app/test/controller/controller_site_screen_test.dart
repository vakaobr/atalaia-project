// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The phone controller's slice S7 settings (decisions PE24-118 onward):
// failover, the site server and ATAK. The tile on Android, a bad address
// refused, the key shown afterwards only by its fingerprint, the controller
// started with them, and the screen in every language at 320 px.

import 'package:atalaia_app/controller/controller_screen.dart';
import 'package:atalaia_app/controller/controller_site_screen.dart';
import 'package:atalaia_app/controller/controller_sync.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/ui/settings_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import 'controller_screen_test.dart' show phone, small, tapKey, onAndroid;

void main() {
  final key = 'A1b2' * 10 + 'xyz';

  testWidgets(
    'the tile on Android, a bad address refused, the settings saved and the '
    'key only by its fingerprint',
    (tester) async {
      await phone(tester);
      final h = harness();
      await tester.pumpWidget(h.app(home: const SettingsScreen()));
      await tester.pumpAndSettle();
      await tapKey(tester, 'controller-site');
      expect(find.byType(ControllerSiteScreen), findsOneWidget);
      await tapKey(tester, 'sync-on');
      await tester.enterText(
        find.byKey(const Key('sync-url')),
        'http://site.example.org',
      );
      await tester.enterText(find.byKey(const Key('sync-key')), key);
      await tapKey(tester, 'site-save');
      expect(h.settings.controllerSync, isNull);
      expect(find.textContaining('https://'), findsWidgets);
      await tester.pump(const Duration(seconds: 10));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const Key('sync-url')),
        -200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.enterText(
        find.byKey(const Key('sync-url')),
        'https://site.example.org',
      );
      await tapKey(tester, 'sync-remote-gm');
      await tapKey(tester, 'failover-auto');
      await tapKey(tester, 'site-save');
      final saved = SyncConfig.fromJson(h.settings.controllerSync)!;
      expect(
        (saved.url, saved.apiKey, saved.remoteGm),
        ('https://site.example.org', key, true),
      );
      expect(h.settings.failoverMode, 'auto');
      expect(h.settings.controllerAtak, isNull);
      expect(find.textContaining(keyFingerprint(key)), findsOneWidget);
      expect(find.text(key), findsNothing);
      expect((await h.store.loadSettings()).controllerSync?['api_key'], key);
    },
    variant: onAndroid,
  );

  testWidgets('the controller starts with them', (tester) async {
    await phone(tester);
    final sync = SyncConfig(url: 'https://site.example.org', apiKey: key);
    final h = harness(
      settings: AppSettings()
        ..failoverMode = 'auto'
        ..controllerSync = sync.toJson()
        ..controllerAtak = {'enabled': true},
    );
    await tester.pumpWidget(h.app(home: const ControllerScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'ctl-start');
    final boot = h.controllerBoots.single;
    expect(boot.failoverMode, 'auto');
    expect(boot.sync, sync.toJson());
    expect(boot.atak, {'enabled': true});
  }, variant: onAndroid);

  for (final lang in AppLanguage.values) {
    testWidgets('the screen at 320 px (${lang.code})', (tester) async {
      await small(tester);
      final h = harness(
        language: lang,
        settings: AppSettings()
          ..language = lang
          ..controllerSync = SyncConfig(
            url: 'https://site.example.org',
            apiKey: key,
          ).toJson()
          ..controllerAtak = {'enabled': true, 'remote': true},
      );
      await tester.pumpWidget(h.app(home: const ControllerSiteScreen()));
      await tester.pumpAndSettle();
      expect(find.text(Strings(lang).t('ctl_site.title')), findsOneWidget);
      expect(tester.takeException(), isNull);
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    });
  }
}
