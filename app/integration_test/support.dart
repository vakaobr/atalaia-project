// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the on-device tests share: the app with the phone's real plugins
/// and the APK's real core, settings in memory, and waiting in real time.
library;

import 'package:atalaia_app/app.dart';
import 'package:atalaia_app/platform/channels.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';

/// The app as on a phone, but with fresh settings that ask nothing of the
/// system (the battery-exemption screen would hide the app).
Widget deviceApp({AppSettings? settings, Widget? home}) {
  final s = (settings ?? AppSettings())..batteryAsked = true;
  return AtalaiaApp(
    services: AppServices.platform(MemoryAppStore(s), ChannelDeviceServices()),
    settings: s,
    home: home,
  );
}

/// Pumps frames until [finder] finds something, in real time.
Future<void> waitFor(
  WidgetTester tester,
  Finder finder, {
  Duration timeout = const Duration(seconds: 30),
}) async {
  final end = DateTime.now().add(timeout);
  while (finder.evaluate().isEmpty) {
    if (DateTime.now().isAfter(end)) {
      throw TestFailure('timed out waiting for $finder');
    }
    await tester.pump(const Duration(milliseconds: 100));
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
}

/// Lets [d] of real time pass, pumping frames.
Future<void> pass(WidgetTester tester, Duration d) async {
  final end = DateTime.now().add(d);
  while (DateTime.now().isBefore(end)) {
    await tester.pump(const Duration(milliseconds: 100));
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
}
