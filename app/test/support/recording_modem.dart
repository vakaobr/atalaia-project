// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A radio modem for the Android field controller's tests (slice S4): up
/// unless told otherwise, and keeping what the controller asked of it in one
/// ordered list, as the shared contract cases' `tx` steps see it (the Pi's
/// runner wraps its FakeModem the same way): packets with their header and
/// their payload by the field names of protocol/schema/messages.yaml (bytes
/// in hex), and the modem's commands (configure without the key, clear,
/// channel, peer_epochs, and measure: slice S7a's noise scan, which it
/// answers from [noise] as the Pi's FakeModem does, held while [held]).
library;

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/pod/pod_codec.dart' show RadioNoise;
import 'package:atalaia_app/protocol/cbor.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:yaml/yaml.dart';

/// The message types and their payload fields by name, from the schema.
class MessageSchema {
  MessageSchema._(this.names, this.fields);

  factory MessageSchema.load() {
    final doc =
        loadYaml(File('../protocol/schema/messages.yaml').readAsStringSync())
            as YamlMap;
    final names = <int, String>{
      for (final m in doc['messages'] as YamlList)
        (m as YamlMap)['id'] as int: m['name'] as String,
    };
    final fields = <String, Map<int, String>>{};
    (doc['payloads'] as YamlMap).forEach((name, list) {
      fields['$name'] = {
        for (final f in list as YamlList)
          (f as YamlMap)['key'] as int: f['name'] as String,
      };
    });
    return MessageSchema._(names, fields);
  }

  final Map<int, String> names;
  final Map<String, Map<int, String>> fields;

  /// A payload as JSON: its fields by name, bytes in hex.
  Map<String, Object?> decode(String type, Uint8List payload) {
    final table = fields[type];
    if (table == null) return {};
    final raw = cborDecode(payload, allowBytes: true);
    if (raw is! Map) return {};
    return {
      for (final e in raw.entries)
        (e.key is int ? table[e.key] : null) ?? '${e.key}': plain(e.value),
    };
  }

  static Object? plain(Object? v) => switch (v) {
    Uint8List() => [
      for (final b in v) b.toRadixString(16).padLeft(2, '0'),
    ].join(),
    Map() => {for (final e in v.entries) '${e.key}': plain(e.value)},
    List() => [for (final e in v) plain(e)],
    _ => v,
  };
}

const _prios = ['telemetry', 'normal', 'critical', 'reserved'];

class RecordingModem extends ControllerModem {
  RecordingModem({MessageSchema? schema})
    : schema = schema ?? MessageSchema.load();

  final MessageSchema schema;
  final log = <Map<String, Object?>>[];

  /// The packets sent, as (header, payload).
  final sent = <(RfHeader, Uint8List)>[];

  @override
  String state = ModemState.up;

  @override
  Map<String, Object?>? ident = {
    'fw': 'atalaia-modem',
    'fw_version': 'fake',
    'radio': 'sx1262',
  };

  @override
  Map<String, Object?>? status = {'configured': true};

  @override
  int reconnects = 0;

  /// The modem's link went down or came back.
  void setState(String s) {
    state = s;
    onState?.call(s);
  }

  @override
  void configure({
    required int gameId,
    required int nodeId,
    required int epoch,
    required int maxHops,
    required int channelHz,
    required Uint8List key,
  }) => log.add({
    'kind': 'configure',
    'game_id': gameId,
    'node_id': nodeId,
    'epoch': epoch,
    'max_hops': maxHops,
    'channel_hz': channelHz,
  });

  @override
  void clear() => log.add({'kind': 'clear'});

  /// The languages given for the modem's own OLED (decision MOD-2); not in [log], which the
  /// shared contract cases read.
  final languages = <String?>[];

  @override
  void setLanguage(String? code) => languages.add(code);

  @override
  bool setChannel(int channelHz) {
    log.add({'kind': 'channel', 'channel_hz': channelHz});
    return true;
  }

  @override
  void setPeerEpochs(Map<int, int> epochs) => log.add({
    'kind': 'peer_epochs',
    'epochs': {for (final k in epochs.keys.toList()..sort()) '$k': epochs[k]},
  });

  @override
  bool sendPacket(RfHeader header, Uint8List payload) {
    if (!isUp) return false;
    sent.add((header, payload));
    final type = schema.names[header.type] ?? '${header.type}';
    log.add({
      'kind': type,
      'source': header.source,
      'seq': header.seq,
      'hop_limit': header.hopLimit,
      'prio': _prios[header.prio],
      'ack': header.ackRequested,
      'fields': schema.decode(type, payload),
    });
    return true;
  }

  // --- field and pair frames (slice S7c), as the Pi's FakeModem: kept
  // apart from [log], so the shared cases' `tx` steps see only packets and
  // commands; `field_tx` steps read [fields].

  /// The field and pair frames sent (FIELD_TX), in order.
  final fields = <Uint8List>[];

  @override
  bool get hasFieldFrames => true;

  @override
  bool get hasPairFrames => true;

  @override
  int? sendField(Uint8List frame) {
    if (!isUp) return null;
    fields.add(frame);
    return fields.length;
  }

  /// The noise per channel: (90th percentile in dBm, CAD detections of 10);
  /// -118 dBm and none when not given (the Pi's FakeModem).
  final noise = <int, (int, int)>{};

  /// While set, measurements wait until it completes (the Pi's
  /// FakeModem.measure_gate).
  Completer<void>? held;

  @override
  bool get canMeasure => true;

  @override
  Future<RadioNoise> measure(
    int channelHz,
    int dwellMs, {
    bool cad = true,
  }) async {
    log.add({'kind': 'measure', 'channel_hz': channelHz, 'dwell_ms': dwellMs});
    final gate = held;
    if (gate != null) await gate.future;
    final (p90, hits) = noise[channelHz] ?? (-118, 0);
    return RadioNoise(
      channelHz: channelHz,
      dwellMs: dwellMs,
      samples: dwellMs,
      minDbm: p90 - 6,
      meanDbm: p90 - 3,
      p50Dbm: p90 - 4,
      p90Dbm: p90,
      maxDbm: p90 + 9,
      cadTries: 10,
      cadDetected: hits,
    );
  }

  /// A packet the radio heard, as its RX frame reaches the controller.
  void rx(
    RfHeader header,
    Uint8List payload, {
    int epoch = 0,
    int rssi = -60,
    int snr = 5,
  }) =>
      onRx?.call(RadioRx(header, payload, rssi: rssi, snr: snr, epoch: epoch));
}
