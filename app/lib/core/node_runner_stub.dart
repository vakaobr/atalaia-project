// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The node runner where there is no core (the web; ADR-P3-10): it starts
/// nothing. The player, GM and spectator roles do not need it.
library;

import '../radio/rf_codec.dart';
import 'node_types.dart';

/// [libraryPath] is ignored: there is no core to load.
NodeRunner createNodeRunner({String? libraryPath}) =>
    const UnsupportedNodeRunner();

/// No core, no EVENT codec: a prop's radio link needs one.
EventEncoder? createEventEncoder({String? libraryPath}) => null;

final class UnsupportedNodeRunner implements NodeRunner {
  const UnsupportedNodeRunner();

  @override
  bool get supported => false;

  @override
  String? get coreVersion => null;

  @override
  Future<RunningNode> start(
    NodeSpec spec, {
    GameClock clock = GameClock.realTime,
  }) => Future.error(
    UnsupportedError('this platform runs no game nodes (no core)'),
  );
}
