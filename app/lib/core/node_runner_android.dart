// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The node runner with the core: each node in its own game loop isolate
/// (ADR-P3-1). On Android the core is the APK's libatalaia_core.so, built by
/// Gradle with the NDK (android/app/build.gradle.kts); on a desktop or in
/// tests it is the library `$ATALAIA_CORE_LIB` names. iOS ships no core
/// (ADR-P3-10), so the runner is unsupported there.
library;

import 'dart:io';

import '../ffi/bindings.dart';
import '../radio/rf_codec.dart';
import 'game_loop_isolate.dart';
import 'node_types.dart';

NodeRunner createNodeRunner({String? libraryPath}) =>
    FfiNodeRunner(libraryPath: libraryPath);

/// The core's EVENT codec for a prop's radio link (lib/radio/pod_radio_link.dart),
/// as a box encodes its events; null where there is no core (iOS).
EventEncoder? createEventEncoder({String? libraryPath}) {
  if (Platform.isIOS) return null;
  final AtalaiaCore core;
  try {
    core = AtalaiaCore.open(libraryPath);
  } on Object {
    return null;
  }
  return ({
    required int node,
    required int seq,
    required int tMs,
    required String type,
    required int team,
    required int squad,
    required int prio,
    required String? dataJson,
  }) => core
      .encodeEvent(
        node: node,
        seq: seq,
        tMs: tMs,
        type: type,
        team: team,
        squad: squad,
        prio: prio,
        dataJson: dataJson,
      )
      .bytes;
}

final class FfiNodeRunner implements NodeRunner {
  const FfiNodeRunner({this.libraryPath});

  /// The core library; null for the platform default (see resolveCoreLibrary).
  final String? libraryPath;

  @override
  bool get supported => !Platform.isIOS;

  /// Opens the library to read its version (no node is touched).
  @override
  String? get coreVersion {
    if (!supported) return null;
    try {
      return AtalaiaCore.open(libraryPath).version;
    } on Object {
      return null;
    }
  }

  @override
  Future<RunningNode> start(
    NodeSpec spec, {
    GameClock clock = GameClock.realTime,
  }) {
    if (!supported) {
      return Future.error(UnsupportedError('iOS runs no game nodes'));
    }
    return GameLoopIsolate.spawn(spec, libraryPath: libraryPath, clock: clock);
  }
}
