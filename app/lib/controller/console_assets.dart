// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The phone controller's files from the app's assets, read on the UI
/// isolate (rootBundle needs the Flutter binding) and handed to the
/// controller's isolate (slice S6 of PE24): the GM console
/// (controller/console/src) and the check-in notices
/// (controller/templates/checkin-notice-*.md), both copied into assets/ at
/// build time by tool/sync_console.dart (decision PE24-61).
library;

import 'dart:convert';

import 'package:flutter/services.dart';

import 'console_files.dart';

/// Where the console's files are in the app's assets.
const consoleAssetPrefix = 'assets/console/';

/// Where the check-in notices are.
const noticeAssetPrefix = 'assets/notices/';

/// The console's files from the app's assets (the UI isolate: [bundle] is
/// rootBundle there). Empty when the app was built without them.
Future<ConsoleFiles> loadConsoleFiles(AssetBundle bundle) async {
  final manifest = await AssetManifest.loadFromAssetBundle(bundle);
  final out = <String, Uint8List>{};
  for (final key in manifest.listAssets()) {
    if (!key.startsWith(consoleAssetPrefix)) continue;
    final data = await bundle.load(key);
    out[key.substring(consoleAssetPrefix.length)] = data.buffer.asUint8List(
      data.offsetInBytes,
      data.lengthInBytes,
    );
  }
  return ConsoleFiles(out);
}

/// The check-in privacy notices (pt, en) from the app's assets, as the Pi
/// reads controller/templates/checkin-notice-*.md; empty texts when the app
/// was built without them.
Future<(String, String)> loadNotices(AssetBundle bundle) async {
  Future<String> one(String lang) async {
    try {
      final data = await bundle.load(
        '${noticeAssetPrefix}checkin-notice-$lang.md',
      );
      return utf8.decode(
        data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
      );
    } on Object {
      return '';
    }
  }

  return (await one('pt'), await one('en'));
}
