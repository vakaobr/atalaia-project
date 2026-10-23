// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Pairing by code and slice S7a's channel work together (slice S7c of PE24;
// engine.py `_modem_moved`, `_channel_lock_reason`): listening tunes the
// radio to 869.525 MHz for new boxes, the field's channel set or a scan
// tunes it back and pairing stops saying it listens, and while a scan runs
// the channel is locked for pairing too.

import 'dart:async';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_channel.dart';
import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_pairing.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_modem.dart';

void main() {
  test('listening, the channel set, a scan', () async {
    final radio = RecordingModem();
    final engine = ControllerEngine(modem: radio)
      ..joinKey = Uint8List.fromList(List.generate(32, (i) => i));
    final pairing = ControllerPairing(engine);
    final channel = ControllerChannel(engine, scanDwellS: 1);
    channel.setChannel(869850000, 'manual');
    radio.log.clear();

    // New boxes listen on 869.525 MHz: the radio goes there.
    expect(pairing.listen()['listening'], isTrue);
    expect(radio.log, [
      {'kind': 'channel', 'channel_hz': pairChannelHz},
    ]);
    // The field's channel set: back on it, pairing no longer listens.
    channel.setChannel(869775000, 'manual');
    expect(pairing.status()['listening'], isFalse);
    expect(pairing.status()['radio_channel_hz'], 869775000);

    // A scan locks the channel for pairing as for a game.
    expect(engine.channelLockReason(), isNull);
    radio.held = Completer<void>();
    channel.startScan(1);
    expect(engine.channelLockReason(), 'a channel scan is running');
    expect(
      pairing.listen,
      throwsA(isA<ControllerError>().having((e) => e.status, 'status', 409)),
    );
    radio.held!.complete();
    await Future<void>.delayed(const Duration(milliseconds: 200));
    for (var i = 0; i < 100 && channel.scanRunning; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 20));
    }
    expect(channel.scanRunning, isFalse);
    expect(engine.channelLockReason(), isNull);
  });
}
