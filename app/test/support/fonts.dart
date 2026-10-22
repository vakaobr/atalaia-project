// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Real fonts for golden images: Roboto (Android's font, which the app's
/// theme names) and the Material icons, from the Flutter SDK's own copies
/// ($FLUTTER_ROOT/bin/cache/artifacts/material_fonts/), and for Traditional
/// Chinese a subset of Noto Sans TC (test/fonts/, OFL-1.1) under the name
/// the theme falls back on (cjkFontFallback): Android draws Han characters
/// with its own CJK font, which a widget test does not have. Without them a
/// widget test draws every glyph as a box.
library;

import 'dart:io';

import 'package:atalaia_app/ui/theme.dart';
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
  final cjk = FontLoader(cjkFontFallback.first);
  for (final f in [cjkRegular, 'test/fonts/NotoSansTC-Bold-subset.otf']) {
    cjk.addFont(File(f).readAsBytes().then((b) => ByteData.sublistView(b)));
  }
  await cjk.load();
}

/// The subset of Noto Sans TC the tests draw Chinese with: only the
/// characters of the app's zh-tw texts (strings_zh_tw.dart) and the test
/// data (test/fonts/README.md says how to make it again).
const cjkRegular = 'test/fonts/NotoSansTC-Regular-subset.otf';
