// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The app's entry point: the phone's services (lib/platform/), the
/// settings from the app's private folder, then the role selector.
library;

import 'package:flutter/material.dart';

import 'app.dart';
import 'platform/channels.dart';
import 'storage/app_store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final device = ChannelDeviceServices();
  final dir = await device.filesDir();
  final AppStore store = dir == null ? MemoryAppStore() : FileAppStore(dir);
  final settings = await store.loadSettings();
  runApp(
    AtalaiaApp(
      services: AppServices.platform(store, device),
      settings: settings,
    ),
  );
}
