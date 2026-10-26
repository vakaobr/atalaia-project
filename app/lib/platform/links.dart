// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Links that open the app (decision S16-13): the Android activity's
/// `atalaia://register?...` intents, through LinkPlugin.kt, and on iOS the
/// URL scheme's scene events, through LinkPlugin.swift (decision iOS-14). The app checks
/// every link itself (lib/site/site_link.dart) before acting on it.
library;

import 'dart:async';

import 'package:flutter/services.dart';

abstract interface class AppLinks {
  /// The link that started the app, once (null: none).
  Future<String?> initial();

  /// Links that arrive while the app runs.
  Stream<String> get links;
}

class ChannelAppLinks implements AppLinks {
  ChannelAppLinks() {
    _ch.setMethodCallHandler((call) async {
      if (call.method == 'link' && call.arguments is String) {
        _out.add(call.arguments as String);
      }
      return null;
    });
  }

  static const _ch = MethodChannel('org.atalaia.app/links');
  final _out = StreamController<String>.broadcast();

  @override
  Future<String?> initial() async {
    try {
      final r = await _ch.invokeMethod<Object?>('initial');
      return r is String ? r : null;
    } on MissingPluginException {
      return null;
    }
  }

  @override
  Stream<String> get links => _out.stream;
}
