// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The placeholder screen of lib/main.dart (plan phase D replaces it).

import 'dart:io';

import 'package:atalaia_app/core/node_runner.dart';
import 'package:atalaia_app/core/node_runner_stub.dart' as web;
import 'package:atalaia_app/main.dart';
import 'package:flutter_test/flutter_test.dart';

import 'support/core_libs.dart';

void main() {
  testWidgets('shows the version of the core it can load', (tester) async {
    final declared = RegExp(
      r'project\(atalaia_core VERSION (\S+)',
    ).firstMatch(File('../core/CMakeLists.txt').readAsStringSync())!.group(1);
    await tester.pumpWidget(
      AtalaiaApp(runner: createNodeRunner(libraryPath: coreLibraryPath())),
    );
    expect(find.text('Atalaia'), findsOneWidget);
    expect(find.text('Core $declared'), findsOneWidget);
  });

  testWidgets('says so where there is no core', (tester) async {
    await tester.pumpWidget(AtalaiaApp(runner: web.createNodeRunner()));
    expect(find.text('No game core on this device'), findsOneWidget);
  });
}
