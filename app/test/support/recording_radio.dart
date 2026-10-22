// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A radio for the Android field controller's tests: up, and keeping what
/// the controller sends (as the Pi controller's tests use a FakeModem).
library;

import 'dart:typed_data';

import 'package:atalaia_app/controller/field_controller.dart';

class RecordingRadio implements FieldTransport {
  /// (message type, payload) in the order sent.
  final sent = <(int, Uint8List)>[];
  var seq = -1;

  @override
  String get state => 'up';

  @override
  int? send(
    int type,
    Uint8List payload, {
    required int prio,
    required bool ack,
    required int hopLimit,
  }) {
    sent.add((type, payload));
    return ++seq;
  }
}
