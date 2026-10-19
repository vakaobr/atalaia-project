// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Every golden test in this folder runs with real fonts. The images are
// drawn in ghcr.io/cirruslabs/flutter:3.44.0 (python tools/docker_app.py
// goldens) and compared in the same image by `check` and CI's flutter-test.

import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import '../support/fonts.dart';

Future<void> testExecutable(FutureOr<void> Function() testMain) async {
  TestWidgetsFlutterBinding.ensureInitialized();
  await loadAppFonts();
  await testMain();
}
