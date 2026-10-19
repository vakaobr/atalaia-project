// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The whole app for widget tests, with the phone replaced by fakes and
/// settings kept in memory.
library;

import 'package:atalaia_app/app.dart';
import 'package:atalaia_app/core/node_runner.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';

import 'fakes.dart';

class Harness {
  Harness({
    required this.settings,
    required this.runner,
    this.feedConnect,
    FakeQr? qr,
  }) : qr = qr ?? FakeQr();

  final AppSettings settings;
  final NodeRunner runner;
  final FeedConnect? feedConnect;
  final device = FakeDevice();
  final kiosk = FakeKiosk();
  final foreground = FakeForeground();
  final nfc = FakeNfc();
  final FakeQr qr;
  late final store = MemoryAppStore(settings);

  late final AppServices services = AppServices(
    runner: runner,
    device: device,
    kiosk: kiosk,
    foreground: foreground,
    nfc: nfc,
    qr: qr,
    store: store,
    feedConnect: feedConnect ?? _noFeed,
    consoleView: (context, url) =>
        Center(child: Text('console $url', key: const Key('console-view'))),
  );

  /// The app; a new harness is a new app (its own state), even when pumped
  /// over another one in the same test.
  Widget app({Widget? home}) => AtalaiaApp(
    key: ObjectKey(this),
    services: services,
    settings: settings,
    home: home,
  );
}

Future<FeedSocket> _noFeed(Uri uri) => Future.error(StateError('no network'));

Harness harness({
  AppLanguage language = AppLanguage.pt,
  NodeRunner? runner,
  FeedConnect? feedConnect,
  AppSettings? settings,
  FakeQr? qr,
}) => Harness(
  settings: (settings ?? AppSettings())..language = language,
  runner: runner ?? FakeNodeRunner(),
  feedConnect: feedConnect,
  qr: qr,
);
