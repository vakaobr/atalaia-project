// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the on-device tests share: the app with the phone's real plugins
/// (and, on Android, the APK's real core), settings in memory unless a test
/// gives a store, and waiting in real time. Android-only tests may assume
/// the core; on iOS the node runner reports none ([deviceHasCore]).
library;

import 'dart:io';

import 'package:atalaia_app/app.dart';
import 'package:atalaia_app/platform/channels.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

/// Which kind of device the test runs on: the real one, whatever the app's
/// own platform checks say (a test may make those pretend, see
/// ios_checklist_test.dart).
bool get onAndroidDevice => Platform.isAndroid;
bool get onIosDevice => Platform.isIOS;

/// Neither: `flutter test integration_test/...` on the development machine.
bool get onHost => !onAndroidDevice && !onIosDevice;

/// Whether the device carries the C core (the APK does; the iOS app does not,
/// ADR-P3-10). On the host it depends on the libraries the run found.
bool get deviceHasCore => !onIosDevice;

/// The app as on a phone, but with fresh settings that ask nothing of the
/// system (the battery-exemption screen would hide the app). [store] and
/// [device] replace the in-memory settings and the phone's device plugin.
Widget deviceApp({
  AppSettings? settings,
  Widget? home,
  AppStore? store,
  DeviceServices? device,
}) {
  final s = (settings ?? AppSettings())..batteryAsked = true;
  return AtalaiaApp(
    services: AppServices.platform(
      store ?? MemoryAppStore(s),
      device ?? ChannelDeviceServices(),
    ),
    settings: s,
    home: home,
  );
}

/// Pumps frames until [done] is true, in real time.
Future<void> waitUntil(
  WidgetTester tester,
  bool Function() done, {
  required String reason,
  Duration timeout = const Duration(seconds: 30),
}) async {
  final end = DateTime.now().add(timeout);
  while (!done()) {
    if (DateTime.now().isAfter(end)) {
      throw TestFailure('timed out waiting for $reason');
    }
    await tester.pump(const Duration(milliseconds: 100));
    await Future<void>.delayed(const Duration(milliseconds: 100));
  }
}

/// Runs [body] and returns the layout overflows the framework reported in
/// it ("A RenderFlex overflowed by ..."), keeping every other error for the
/// test to fail on.
Future<List<String>> collectOverflows(Future<void> Function() body) async {
  final old = FlutterError.onError;
  final overflows = <String>[];
  final others = <FlutterErrorDetails>[];
  FlutterError.onError = (details) {
    final text = details.exceptionAsString();
    if (text.contains('overflowed')) {
      overflows.add(text.split('\n').first);
    } else {
      others.add(details);
    }
  };
  try {
    await body();
  } finally {
    FlutterError.onError = old;
  }
  if (others.isNotEmpty) {
    FlutterError.reportError(others.first);
  }
  return overflows;
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
