// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// On an Android device or emulator (CI's flutter-integration job): the app
// starts on the role selector, each role opens its screen, the language
// changes everywhere, and the APK carries a core it can load.

import 'package:atalaia_app/core/node_runner.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'support.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  test('the APK carries the core, and it loads', () {
    final runner = createNodeRunner();
    expect(runner.supported, isTrue);
    expect(runner.coreVersion, matches(RegExp(r'^\d+\.\d+\.\d+')));
  });

  testWidgets('the roles open their screens; the language follows', (
    tester,
  ) async {
    await tester.pumpWidget(deviceApp());
    await waitFor(tester, find.text('Dispositivo de jogo'));
    expect(find.text('Participante'), findsOneWidget);

    await tester.tap(find.byKey(const Key('role-player')));
    await waitFor(tester, find.byKey(const Key('player-connect')));
    await tester.pumpAndSettle();
    await goBack(tester);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('role-marshal')));
    await waitFor(tester, find.byKey(const Key('marshal-chrono')));
    await tester.pumpAndSettle();
    await goBack(tester);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('role-prop')));
    await waitFor(tester, find.byKey(const Key('prop-new')));
    await tester.pumpAndSettle();
    // The phone's features came from the Kotlin plugin.
    expect(find.text('botões das equipas'), findsOneWidget);
    await goBack(tester);
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('open-settings')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('English'));
    await tester.pumpAndSettle();
    expect(find.text('Settings'), findsOneWidget);
    await goBack(tester);
    await tester.pumpAndSettle();
    expect(find.text('Game prop'), findsOneWidget);
    expect(find.text('Player'), findsOneWidget);
  });
}
