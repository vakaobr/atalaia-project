// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The app's version is written in three places that must agree: pubspec.yaml
// (the installed package's), lib/version.dart (what Settings > About shows and
// a phone controller's /whoami gives) and the Pi controller's __version__ (the
// two controllers answer /whoami alike; controller/tests/test_versions.py).
// Settings once showed 0.2.0 on a 0.3.0 install.
import 'dart:io';

import 'package:atalaia_app/controller/controller_api.dart';
import 'package:atalaia_app/version.dart';
import 'package:flutter_test/flutter_test.dart';

String _match(String path, RegExp pattern) {
  final m = pattern.firstMatch(File(path).readAsStringSync());
  if (m == null) fail('no version in $path');
  return m.group(1)!;
}

void main() {
  test('the app version is pubspec.yaml\'s, without its build number', () {
    final pubspec = _match(
      'pubspec.yaml',
      RegExp(r'^version:\s*([^\s+]+)', multiLine: true),
    );
    expect(appVersion, pubspec);
  });

  test('a phone controller gives the app version, as a Pi gives its own', () {
    // The Pi's __version__ is checked against lib/version.dart by
    // controller/tests/test_versions.py: this test's container has no
    // controller/ folder.
    expect(controllerApiVersion, appVersion);
  });
}
