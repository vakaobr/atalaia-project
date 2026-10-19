// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The node runner for this platform: the core through `dart:ffi` where Dart
/// has it (node_runner_android.dart), none on the web (node_runner_stub.dart).
/// iOS has `dart:ffi` but no core (ADR-P3-10): the FFI runner reports itself
/// unsupported there.
library;

export 'node_runner_stub.dart' if (dart.library.ffi) 'node_runner_android.dart';
export 'node_types.dart';
