// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the on-device tests share: the app with the phone's real plugins
/// and the APK's real core, settings in memory, and waiting in real time.
library;

import 'package:atalaia_app/app.dart';
import 'package:atalaia_app/platform/channels.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
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

/// Scrolls until [finder] is on screen. On a small screen (CI's emulator)
/// part of a page starts below the fold, and a list does not build what is
/// scrolled away, so look downwards first, then upwards.
Future<void> reveal(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isEmpty) {
    final scrollable = find.byType(Scrollable).first;
    try {
      await tester.scrollUntilVisible(finder, 200, scrollable: scrollable);
    } on StateError {
      await tester.scrollUntilVisible(finder, -200, scrollable: scrollable);
    }
  }
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

/// Taps [finder] once it is on screen (a tap below the fold misses).
Future<void> tapVisible(WidgetTester tester, Finder finder) async {
  await reveal(tester, finder);
  await tester.tap(finder);
}

/// Taps the app bar's back button. WidgetTester.pageBack() finds it by its
/// English tooltip ("Back"), so it never finds it in the Portuguese app.
Future<void> goBack(WidgetTester tester) async {
  final back = find.byType(BackButton);
  expect(back, findsOneWidget, reason: 'one back button expected on screen');
  await tester.tap(back);
}

/// Lets [d] of real time pass, pumping frames.
Future<void> pass(WidgetTester tester, Duration d) async {
  final end = DateTime.now().add(d);
  while (DateTime.now().isBefore(end)) {
    await tester.pump(const Duration(milliseconds: 100));
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
}
