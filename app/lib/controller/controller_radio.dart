// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Android field controller's radio (slice S4 of PE24): what the Pi
/// controller does with its USB radio modem (controller/atalaia_controller/
/// radio_modem.py and engine.py's ModemTransport), for a radio the phone
/// reaches through an I/O pod (pod_modem.dart) or a test's recording modem.
///
/// [ControllerModem] is the modem's side: the game's CONFIGURE (the key, the
/// node id, the epoch, the hops and the channel), the packets to send (the
/// modem encrypts them), what it heard (decrypted), TX_ACKs, SET_CHANNEL,
/// SET_PEER_EPOCH and CLEAR. [RadioTransport] is the controller's own
/// packets for one game on that modem: their (epoch, seq) nonce counter,
/// the epoch stored per game key before its first packet ([nextTxEpoch]),
/// a new epoch when seq wraps, as the Pi's ModemTransport.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:crypto/crypto.dart';

import '../pod/pod_codec.dart' show RadioNoise;
import '../radio/rf_codec.dart';
import 'controller_store.dart';
import 'field_controller.dart';

/// The modem's link states, as the Pi's radio_modem.py names them.
abstract final class ModemState {
  static const up = 'up';
  static const down = 'down';
  static const connecting = 'connecting';
}

/// The modem's TX_ACK statuses (modem_framing.py `TX_STATUS`).
const txStatusNames = {
  0: 'ok',
  1: 'duty_cycle',
  2: 'timeout',
  3: 'not_configured',
  4: 'invalid',
  5: 'nonce_reuse',
  6: 'queue_full',
  7: 'no_radio',
  8: 'busy',
};

/// What the radio heard and authenticated: the header, the plaintext
/// payload, the signal and the sender's epoch.
class RadioRx {
  const RadioRx(
    this.header,
    this.payload, {
    this.rssi,
    this.snr,
    this.epoch = 0,
  });
  final RfHeader header;
  final Uint8List payload;
  final int? rssi;
  final int? snr;
  final int epoch;
}

/// The controller's radio, as the Pi's RadioModem: commands go out at once
/// (a modem that is down answers false or ignores them and gets the game
/// again when it comes back), what it hears comes in through the callbacks.
abstract class ControllerModem {
  /// [ModemState.up], [ModemState.down] or [ModemState.connecting].
  String get state;
  bool get isUp => state == ModemState.up;

  /// The modem's IDENT and its last STATUS, for GET /api/v1/controller.
  Map<String, Object?>? get ident;
  Map<String, Object?>? get status;
  int get reconnects;

  /// The game: kept and given to the modem again whenever it comes back.
  void configure({
    required int gameId,
    required int nodeId,
    required int epoch,
    required int maxHops,
    required int channelHz,
    required Uint8List key,
  });

  /// The game is over: the modem forgets the key.
  void clear();

  /// Each box's last known epoch (also given again when the modem comes
  /// back), so it refuses older packets of theirs.
  void setPeerEpochs(Map<int, int> epochs);

  /// Tunes the modem outside a game (CONFIGURE carries the game's channel).
  bool setChannel(int channelHz);

  /// Queues a packet: the modem encrypts it under the game key and sends
  /// it. False when the link is not up.
  bool sendPacket(RfHeader header, Uint8List payload);

  void Function(RadioRx rx)? onRx;
  void Function(int seq, String status)? onTxAck;
  void Function(String state)? onState;
  void Function(String code, String message)? onError;

  // --- field and pair frames (slice S7c; protocol/usb-modem.md FIELD_*) ---

  /// The radio carries field frames (re-invites, GAME_OVER; the modem's
  /// IDENT `"field": true`). A radio that does not: none of them.
  bool get hasFieldFrames => false;

  /// And pair frames, type 10 (adopting a box by its code; `"pair": true`).
  bool get hasPairFrames => false;

  /// Queues a whole field or pair frame, sealed (or, a pair frame, in the
  /// clear) by the controller, with or without a game: the id its FIELD_ACK
  /// will carry ([onFieldAck]), or null when it was not taken.
  int? sendField(Uint8List frame) => null;

  /// A field or pair frame heard, as it is, with its RSSI and SNR.
  void Function(Uint8List frame, int rssi, int snr)? onFieldRx;

  /// The outcome of a [sendField] (ok, duty_cycle, invalid...).
  void Function(int id, String status)? onFieldAck;
  // --- the noise scan (slice S7a, controller_channel.dart) -----------------

  /// Whether the radio has a radio chip (radio_modem.py's IDENT
  /// `"radio": "sx1262"`; an I/O pod says `has_radio`).
  bool get hasRadioChip => ident?['radio'] == 'sx1262';

  /// Whether the radio can measure noise (MEASURE): the Pi's modem says so
  /// in its IDENT (`"measure": true`).
  bool get canMeasure => hasRadioChip && ident?['measure'] == true;

  /// Measures the noise on a channel for [dwellMs] (MEASURE, answered by a
  /// NOISE frame, [RadioNoise] of pod_codec.dart; radio_modem.py `measure`). Throws [MeasureException] when
  /// the radio refuses or cannot finish it.
  Future<RadioNoise> measure(int channelHz, int dwellMs, {bool cad = true}) =>
      Future.error(
        MeasureException('unknown_cmd', 'this radio cannot measure'),
      );
}

/// A MEASURE the radio refused or could not finish (radio_modem.py
/// `MeasureError`: the modem's error name, "timeout" or "link").
class MeasureException implements Exception {
  MeasureException(this.code, this.message);
  final String code;
  final String message;
  @override
  String toString() => message;
}

/// The epoch store's name for a game key (RFC 0001 amendment of 2026-10-22,
/// protocol/vectors/epoch_tag.json): the first 8 bytes of
/// HMAC-SHA256(key, "atalaia epoch tag"), in hex. Not secret.
String epochTag(List<int> key) {
  final mac = Hmac(sha256, key).convert(utf8.encode('atalaia epoch tag'));
  return [
    for (final b in mac.bytes.take(8)) b.toRadixString(16).padLeft(2, '0'),
  ].join();
}

/// Game keys whose TX epoch is kept (as a box's epoch store).
const epochKeys = 8;

/// The controller's epoch for this run in the game with [key], written
/// before any packet is sent with it (ADR-P2-2; store.py `next_tx_epoch`):
/// the setting `tx_epochs` keeps `[tag, epoch]` for the last [epochKeys]
/// keys, most recent first. A key with a record goes on at its epoch + 1; a
/// new key starts at 1.
int nextTxEpoch(ControllerStore store, List<int> key) {
  final tag = epochTag(key);
  final saved = store.getSetting('tx_epochs');
  final table = <List<Object?>>[
    if (saved != null)
      for (final row in jsonDecode(saved) as List) (row as List).toList(),
  ];
  int? current;
  for (final row in table) {
    if (row[0] == tag) {
      current = row[1]! as int;
      break;
    }
  }
  if (current != null && current >= 0xffff) {
    throw StateError(
      "the controller's nonce epochs for this game are exhausted; "
      'start a new game',
    );
  }
  final epoch = current == null ? 1 : current + 1;
  final rows = [
    [tag, epoch],
    for (final row in table)
      if (row[0] != tag) row,
  ];
  store.setSetting('tx_epochs', jsonEncode(rows.take(epochKeys).toList()));
  return epoch;
}

/// The controller's own packets for one game, as TX frames to the modem
/// (engine.py `ModemTransport`). [wifi] also hands TIME beacons and
/// commands to the Android props linked over Wi-Fi (slice S4's prop links).
class RadioTransport implements FieldTransport {
  RadioTransport({
    required this.modem,
    required this.store,
    required this.gameId,
    required this.nodeId,
    required this.maxHops,
    required this.channelHz,
    required Uint8List key,
    this.wifi,
  }) : _key = key {
    epoch = nextTxEpoch(store, key);
    configureModem();
  }

  final ControllerModem? modem;
  final ControllerStore store;
  final int gameId;
  final int nodeId;
  final int maxHops;
  final int channelHz;
  final Uint8List _key;

  /// Android props on Wi-Fi: true when one of them took the message.
  bool Function(int type, Uint8List payload)? wifi;

  /// The epoch of this run's packets.
  late int epoch;
  var _next = 0;

  /// The last seq sent, and the packets nothing could send.
  var seq = 0;
  var refused = 0;

  @override
  String get state => modem?.state ?? 'none';

  void configureModem() => modem?.configure(
    gameId: gameId,
    nodeId: nodeId,
    epoch: epoch,
    maxHops: maxHops,
    channelHz: channelHz,
    key: _key,
  );

  @override
  int? send(
    int type,
    Uint8List payload, {
    required int prio,
    required bool ack,
    required int hopLimit,
  }) {
    final onWifi = wifi?.call(type, payload) ?? false;
    final m = modem;
    if (m == null || !m.isUp) {
      refused++;
      return onWifi ? seq : null;
    }
    if (_next > 0xffff) {
      // Every seq of this epoch is spent: a new one, stored before use.
      epoch = nextTxEpoch(store, _key);
      _next = 0;
      configureModem();
    }
    final s = _next;
    final header = RfHeader(
      // Version 1, the priority, the ACK request and the encrypted bit.
      versionFlags: 1 << 5 | (prio & 3) << 3 | (ack ? 1 << 2 : 0) | 1 << 1,
      gameId: gameId,
      source: nodeId,
      seq: s,
      hopLimit: hopLimit,
      type: type,
    );
    if (!m.sendPacket(header, payload)) {
      refused++;
      return null;
    }
    _next = s + 1;
    seq = s;
    return s;
  }
}
