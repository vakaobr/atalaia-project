// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Real fonts for golden images: Roboto (Android's font, which the app's
/// theme names) and the Material icons, from the Flutter SDK's own copies
/// ($FLUTTER_ROOT/bin/cache/artifacts/material_fonts/). Without them a
/// widget test draws every glyph as a box.
library;

import 'dart:io';

import 'package:flutter/services.dart';

String _fontsDir() {
  final root =
      Platform.environment['FLUTTER_ROOT'] ??
      File(Platform.resolvedExecutable).parent.parent.parent.parent.parent.path;
  final dir = Directory('$root/bin/cache/artifacts/material_fonts');
  if (!dir.existsSync()) {
    throw StateError('${dir.path} not found: set FLUTTER_ROOT');
  }
  return dir.path;
}

var _loaded = false;

Future<void> loadAppFonts() async {
  if (_loaded) return;
  _loaded = true;
  final dir = _fontsDir();
  Future<ByteData> read(String name) async =>
      ByteData.sublistView(await File('$dir/$name').readAsBytes());
  final roboto = FontLoader('Roboto');
  for (final f in [
    'Roboto-Regular.ttf',
    'Roboto-Medium.ttf',
    'Roboto-Bold.ttf',
    'Roboto-Black.ttf',
    'Roboto-Light.ttf',
    'Roboto-Italic.ttf',
  ]) {
    roboto.addFont(read(f));
  }
  await roboto.load();
  final icons = FontLoader('MaterialIcons')
    ..addFont(read('MaterialIcons-Regular.otf'));
  await icons.load();
}
