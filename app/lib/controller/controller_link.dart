// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// An Android prop's link to the field controller, whatever carries it: the
/// field's Wi-Fi ([PropLink], protocol/prop-link.md), the field's radio
/// through an I/O pod ([PodRadioLink], lib/radio/pod_radio_link.dart), or
/// both ([DualLink]): HELLO, STATE and events up, TIME beacons and commands
/// down, as a box does over the radio.
library;

import 'package:flutter/foundation.dart';

/// What the controller sends: a TIME beacon or a command.
sealed class LinkMessage {
  const LinkMessage();
}

final class LinkTime extends LinkMessage {
  const LinkTime(this.state, this.gameTimeMs, this.durationMs);

  /// waiting, running, paused, ended
  final String state;
  final int gameTimeMs;
  final int durationMs;
}

final class LinkCommand extends LinkMessage {
  const LinkCommand(this.cmd, this.params);

  /// start, pause, resume, end, set_owner, message, reset, reboot, mode
  final String cmd;
  final Map<String, Object?> params;
}

abstract interface class ControllerLink implements Listenable {
  /// TIME beacons and commands.
  Stream<LinkMessage> get messages;

  /// Whether the controller can be reached on this link now.
  bool get linked;

  void start();

  /// An event of the prop's mode (or the shell's own, such as node.tamper).
  /// [dataJson] is the core's own JSON of [data] when there is one (the
  /// radio encodes the event exactly as a box does).
  void sendEvent({
    required int seq,
    required int tMs,
    required String type,
    int team = 0,
    int squad = 0,
    String? prio,
    Map<String, Object?> data = const {},
    String? dataJson,
  });

  /// The prop's STATE: owner, phase, game time, counters by team id.
  void sendState(Map<String, Object?> fields);

  Future<void> close();
}
