// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The app's first screen (the role selector) in both languages, and the
// core's version it reports in the settings.

import 'dart:io';

import 'package:atalaia_app/core/node_runner.dart';
import 'package:atalaia_app/core/node_runner_stub.dart' as web;
import 'package:atalaia_app/l10n/strings.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/app_harness.dart';
import 'support/core_libs.dart';

void main() {
  testWidgets('the roles, in European Portuguese by default', (tester) async {
    await tester.pumpWidget(harness().app());
    await tester.pumpAndSettle();
    expect(find.text('Dispositivo de jogo'), findsOneWidget);
    expect(find.text('Participante'), findsOneWidget);
    expect(find.text('Marshal'), findsOneWidget);
    expect(find.text('Organização'), findsOneWidget);
  });

  testWidgets('in English', (tester) async {
    await tester.pumpWidget(harness(language: AppLanguage.en).app());
    await tester.pumpAndSettle();
    expect(find.text('Game prop'), findsOneWidget);
    expect(find.text('Player'), findsOneWidget);
    expect(find.text('Game master'), findsOneWidget);
  });

  testWidgets('on iOS the prop role is not offered (ADR-P3-10)', (
    tester,
  ) async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    try {
      await tester.pumpWidget(harness().app());
      await tester.pumpAndSettle();
      expect(find.text('Dispositivo de jogo'), findsNothing);
      expect(find.text('Participante'), findsOneWidget);
      expect(find.textContaining('só o Android'), findsOneWidget);
    } finally {
      debugDefaultTargetPlatformOverride = null;
    }
  });

  testWidgets('the settings show the version of the core it can load', (
    tester,
  ) async {
    final number = RegExp(
      r'project\(atalaia_core VERSION (\S+)',
    ).firstMatch(File('../core/CMakeLists.txt').readAsStringSync())!.group(1);
    // A development core adds version.h's pre-release ("0.3.0-dev", FV-1).
    final pre = RegExp(r'#define ATALAIA_VERSION_PRERELEASE "([^"]*)"')
        .firstMatch(
          File('../core/include/atalaia/version.h').readAsStringSync(),
        )!
        .group(1)!;
    final declared = pre.isEmpty ? number : '$number-$pre';
    final h = harness(runner: createNodeRunner(libraryPath: coreLibraryPath()));
    await tester.pumpWidget(h.app());
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-settings')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.textContaining('Núcleo de jogo'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Núcleo de jogo $declared'), findsOneWidget);
  });

  testWidgets('without a core the settings say so', (tester) async {
    await tester.pumpWidget(harness(runner: web.createNodeRunner()).app());
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('open-settings')));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.textContaining('Sem núcleo'),
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(find.text('Sem núcleo de jogo neste telemóvel.'), findsOneWidget);
  });
}
