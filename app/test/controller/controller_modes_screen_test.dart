// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The phone controller's [modes] settings (slice S7b of PE24, decision
// PE24-82): the settings' tile on Android, the screen in every language at
// 320 px, a key refused with its line, the settings saved, and the
// controller started with them.

import 'package:atalaia_app/controller/controller_modes_screen.dart';
import 'package:atalaia_app/controller/controller_screen.dart';
import 'package:atalaia_app/controller/controller_signed_modes.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/ui/settings_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/vectors.dart';
import 'controller_screen_test.dart' show phone, small, tapKey, onAndroid;

void main() {
  final key =
      (loadVectors('mode_package.json')['signing_key'] as Map)['public_key_b64']
          as String;

  testWidgets(
    'the tile on Android, a bad key refused, the settings saved',
    (tester) async {
      await phone(tester);
      final h = harness();
      await tester.pumpWidget(h.app(home: const SettingsScreen()));
      await tester.pumpAndSettle();
      await tapKey(tester, 'controller-modes');
      expect(find.byType(ControllerModesScreen), findsOneWidget);
      await tester.enterText(find.byKey(const Key('mode-keys')), 'not a key');
      await tapKey(tester, 'modes-save');
      expect(
        find.text(
          Strings(AppLanguage.pt).t('ctl_modes.bad_key', {'line': '1'}),
        ),
        findsOneWidget,
      );
      expect(h.settings.controllerModes, isEmpty);
      // The message goes, so that it covers nothing.
      await tester.pump(const Duration(seconds: 10));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('mode-keys')), ' $key \n\n');
      await tester.enterText(find.byKey(const Key('box-keys')), key);
      await tester.enterText(
        find.byKey(const Key('revoked-keys')),
        '0123456789ABCDEF',
      );
      await tapKey(tester, 'modes-save');
      final saved = ModesConfig.fromJson(h.settings.controllerModes);
      expect(saved.keys, [key]);
      expect(saved.boxKeys, [key]);
      expect(saved.revoked, ['0123456789abcdef']);
      expect(
        ModesConfig.fromJson(
          (await h.store.loadSettings()).controllerModes,
        ).keys,
        [key],
      );
    },
    variant: onAndroid,
  );

  testWidgets('the controller starts with them', (tester) async {
    await phone(tester);
    final h = harness(
      settings: AppSettings()
        ..controllerModes = ModesConfig(keys: [key], boxKeys: [key]).toJson(),
    );
    await tester.pumpWidget(h.app(home: const ControllerScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'ctl-start');
    expect(h.controllerBoots.single.modes.keys, [key]);
    expect(h.controllerBoots.single.modes.boxKeys, [key]);
  }, variant: onAndroid);

  for (final lang in AppLanguage.values) {
    testWidgets('the screen at 320 px (${lang.code})', (tester) async {
      await small(tester);
      final h = harness(language: lang);
      await tester.pumpWidget(h.app(home: const ControllerModesScreen()));
      await tester.pumpAndSettle();
      expect(find.text(Strings(lang).t('ctl_modes.title')), findsOneWidget);
      expect(tester.takeException(), isNull);
      await expectLater(tester, meetsGuideline(textContrastGuideline));
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
    });
  }
}
