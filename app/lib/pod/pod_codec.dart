// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Capability proxy protocol v1 (protocol/capability-proxy.md, ADR-P3-2):
/// the Dart codec, the twin of core/src/proxy.c and
/// simulator/atalaia_sim/capability_proxy.py, checked against the same
/// vectors (protocol/vectors/capability_proxy.yaml).
///
/// An I/O pod and the phone exchange frames with the USB modem's framing:
///
///     0xA5 | type (1) | length (2, big-endian) | payload (0-256) | CRC-16 (2, big-endian)
///
/// IDENT, EVT and CMD payloads are CBOR maps with integer keys; ACK is a
/// big-endian uint16; the radio frames carry the modem's payloads.
library;

import 'dart:convert';
import 'dart:typed_data';

import '../protocol/cbor.dart';

const int frameSync = 0xa5;
const int framePayloadMax = 256;
const int proxyVersion = 1;

/// Frame types.
abstract final class FrameType {
  static const ident = 0x01;
  static const evt = 0x02;
  static const cmd = 0x03;
  static const ack = 0x04;
  static const radioRx = 0x05;
  static const radioTx = 0x06;
  static const radioTxAck = 0x07;
  static const radioCmd = 0x08;
  static const radioStatus = 0x09;
  static const radioError = 0x0a;

  /// The modem's NOISE, the answer to MEASURE (decision PF2).
  static const radioNoise = 0x0b;
}

/// The modem's CMD opcodes (protocol/usb-modem.md), carried by RADIO_CMD.
abstract final class RadioOp {
  static const ping = 1;
  static const configure = 2;
  static const setChannel = 3;
  static const status = 4;
  static const setPeerEpoch = 5;
  static const clear = 6;
  static const ident = 7;
  static const measure = 8;
}

const int capabilitiesMax = 16;
final _name = RegExp(r'^[a-z0-9._-]{1,23}$');
final _printable = RegExp(r'^[\x20-\x7e]{1,23}$');

class ProxyException implements Exception {
  ProxyException(this.message);
  final String message;
  @override
  String toString() => 'ProxyException: $message';
}

// ---- framing --------------------------------------------------------------------

/// CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no final XOR.
int crc16(List<int> data) {
  var crc = 0xffff;
  for (final b in data) {
    crc ^= b << 8;
    for (var i = 0; i < 8; i++) {
      crc = (crc & 0x8000) != 0
          ? ((crc << 1) ^ 0x1021) & 0xffff
          : (crc << 1) & 0xffff;
    }
  }
  return crc;
}

Uint8List encodeFrame(int type, [List<int> payload = const []]) {
  if (type < 0 || type > 0xff || payload.length > framePayloadMax) {
    throw ProxyException(
      'a frame has a one-byte type and at most 256 bytes of payload',
    );
  }
  final body = [type, payload.length >> 8, payload.length & 0xff, ...payload];
  final crc = crc16(body);
  return Uint8List.fromList([frameSync, ...body, crc >> 8, crc & 0xff]);
}

/// One frame: its type and payload.
typedef Frame = ({int type, Uint8List payload});

/// Finds frames in a byte stream, resynchronising after junk or a bad CRC.
class FrameDecoder {
  final _buf = <int>[];
  int crcErrors = 0;
  int lengthErrors = 0;
  int droppedBytes = 0;

  List<Frame> feed(List<int> data) {
    _buf.addAll(data);
    final out = <Frame>[];
    for (;;) {
      final start = _buf.indexOf(frameSync);
      if (start < 0) {
        droppedBytes += _buf.length;
        _buf.clear();
        return out;
      }
      if (start > 0) {
        droppedBytes += start;
        _buf.removeRange(0, start);
      }
      if (_buf.length < 4) return out;
      final length = _buf[2] << 8 | _buf[3];
      if (length > framePayloadMax) {
        lengthErrors++;
        droppedBytes++;
        _buf.removeAt(0);
        continue;
      }
      if (_buf.length < 6 + length) return out;
      final body = _buf.sublist(1, 4 + length);
      final crc = _buf[4 + length] << 8 | _buf[5 + length];
      if (crc != crc16(body)) {
        crcErrors++;
        droppedBytes++;
        _buf.removeAt(0);
        continue;
      }
      out.add((type: body[0], payload: Uint8List.fromList(body.sublist(3))));
      _buf.removeRange(0, 6 + length);
    }
  }
}

// ---- IDENT, EVT, CMD, ACK ----------------------------------------------------------

String _text(String name, Object? v, RegExp pattern) {
  if (v is! String || !pattern.hasMatch(v)) {
    throw ProxyException('$name: $v is not 1-23 allowed characters');
  }
  return v;
}

int _uint(String name, Object? v, int hi) {
  if (v is! int || v < 0 || v > hi) {
    throw ProxyException('$name: $v is not an integer from 0 to $hi');
  }
  return v;
}

/// What JSON can hold: maps with text keys (at every level), lists, text,
/// numbers, booleans, null.
bool _jsonish(Object? v) => switch (v) {
  final Map<Object?, Object?> m => m.entries.every(
    (e) => e.key is String && _jsonish(e.value),
  ),
  final List<Object?> l => l.every(_jsonish),
  null || bool() || int() || double() || String() => true,
  _ => false,
};

Map<String, Object?> _jsonMap(String name, Object? v) {
  if (v is! Map || !_jsonish(v)) {
    throw ProxyException('$name is a map with text keys');
  }
  return v.cast<String, Object?>();
}

Map<String, Object?> _capability(Object? v) {
  final cap = _jsonMap('a capability descriptor', v);
  for (final key in ['id', 'type']) {
    final x = cap[key];
    if (x is! String || x.isEmpty) {
      throw ProxyException("a capability descriptor needs a text '$key'");
    }
  }
  return cap;
}

Map<int, Object?> _decodeMap(
  List<int> payload,
  Set<int> required,
  Set<int> known,
) {
  final Object? value;
  try {
    value = cborDecode(payload);
  } on Exception catch (e) {
    throw ProxyException('not CBOR: $e');
  }
  if (value is! Map) throw ProxyException('the payload is not a map');
  final keys = value.keys.toList();
  if (!keys.every((k) => k is int)) throw ProxyException('keys are integers');
  final ints = keys.cast<int>();
  for (var i = 1; i < ints.length; i++) {
    if (ints[i] < ints[i - 1]) {
      throw ProxyException('keys are written in order');
    }
  }
  for (final k in ints) {
    if (!known.contains(k) && !(k >= 6 && k <= 23)) {
      throw ProxyException('key $k is not allowed');
    }
  }
  final missing = required.difference(ints.toSet());
  if (missing.isNotEmpty) {
    throw ProxyException('missing key(s) ${missing.toList()..sort()}');
  }
  return {
    for (final e in value.entries)
      if (known.contains(e.key)) e.key as int: e.value,
  };
}

Uint8List _fit(Uint8List payload) {
  if (payload.length > framePayloadMax) {
    throw ProxyException(
      'the payload takes ${payload.length} bytes, more than $framePayloadMax',
    );
  }
  return payload;
}

/// What a pod says about itself.
final class PodIdent {
  const PodIdent({
    required this.fwVersion,
    required this.capabilities,
    required this.hasRadio,
    this.batteryPct,
  });

  final String fwVersion;
  final List<Map<String, Object?>> capabilities;
  final int? batteryPct;
  final bool hasRadio;

  Map<String, Object?> toJson() => {
    'fw_version': fwVersion,
    'capabilities': capabilities,
    'battery_pct': ?batteryPct,
    'has_radio': hasRadio,
    'protocol_version': proxyVersion,
  };
}

Uint8List encodeIdent(PodIdent ident) {
  if (ident.capabilities.length > capabilitiesMax) {
    throw ProxyException('capabilities is a list of at most $capabilitiesMax');
  }
  final body = <int, Object?>{
    1: _text('fw_version', ident.fwVersion, _printable),
    2: [for (final c in ident.capabilities) _capability(c)],
    if (ident.batteryPct != null)
      3: _uint('battery_pct', ident.batteryPct, 100),
    4: ident.hasRadio,
    5: proxyVersion,
  };
  return _fit(cborEncode(body));
}

PodIdent decodeIdent(List<int> payload) {
  final m = _decodeMap(payload, {1, 2, 4, 5}, {1, 2, 3, 4, 5});
  final caps = m[2];
  if (caps is! List || caps.length > capabilitiesMax) {
    throw ProxyException('capabilities is a list of at most $capabilitiesMax');
  }
  if (m[4] is! bool) throw ProxyException('has_radio is true or false');
  if (m[5] != proxyVersion) throw ProxyException('protocol_version is 1');
  return PodIdent(
    fwVersion: _text('fw_version', m[1], _printable),
    capabilities: [for (final c in caps) _capability(c)],
    batteryPct: m.containsKey(3) ? _uint('battery_pct', m[3], 100) : null,
    hasRadio: m[4]! as bool,
  );
}

/// An EVT (pod to phone: capability, event, data) or a CMD (phone to pod:
/// capability, method, args), numbered for its ACK.
final class ProxyMessage {
  const ProxyMessage({
    required this.capId,
    required this.name,
    this.data = const {},
    required this.seq,
  });

  final String capId;

  /// The EVT's event or the CMD's method.
  final String name;

  /// The EVT's data or the CMD's args.
  final Map<String, Object?> data;
  final int seq;

  @override
  String toString() => '$capId.$name $data #$seq';
}

Uint8List encodeMessage(ProxyMessage msg) {
  final body = <int, Object?>{
    1: _text('cap_id', msg.capId, _name),
    2: _text('name', msg.name, _name),
    if (_jsonMap('data', msg.data).isNotEmpty) 3: msg.data,
    4: _uint('seq', msg.seq, 0xffff),
  };
  return _fit(cborEncode(body));
}

ProxyMessage decodeMessage(List<int> payload) {
  final m = _decodeMap(payload, {1, 2, 4}, {1, 2, 3, 4});
  final data = _jsonMap('data', m[3] ?? const <String, Object?>{});
  if (m.containsKey(3) && data.isEmpty) {
    throw ProxyException('an empty data map is left out');
  }
  return ProxyMessage(
    capId: _text('cap_id', m[1], _name),
    name: _text('name', m[2], _name),
    data: data,
    seq: _uint('seq', m[4], 0xffff),
  );
}

Uint8List encodeAck(int seq) {
  _uint('seq', seq, 0xffff);
  return Uint8List.fromList([seq >> 8, seq & 0xff]);
}

int decodeAck(List<int> payload) {
  if (payload.length != 2) throw ProxyException('an ACK is two bytes');
  return payload[0] << 8 | payload[1];
}

// ---- radio frames (the modem's payloads) --------------------------------------------

Uint8List radioRx(
  List<int> header,
  List<int> payload,
  int rssi,
  int snr,
  int epoch,
) {
  if (header.length != 9) throw ProxyException('a packet header is 9 bytes');
  return Uint8List.fromList([
    ...header,
    ...payload,
    rssi & 0xff,
    snr & 0xff,
    epoch >> 8,
    epoch & 0xff,
  ]);
}

Uint8List radioTx(List<int> header, List<int> payload) {
  if (header.length != 9 || payload.length > 200) {
    throw ProxyException(
      'a packet header is 9 bytes and its payload at most 200',
    );
  }
  return Uint8List.fromList([...header, ...payload]);
}

Uint8List radioTxAck(int seq, int status) => Uint8List.fromList([
  _uint('seq', seq, 0xffff) >> 8,
  seq & 0xff,
  _uint('status', status, 7),
]);

Uint8List radioConfigure({
  required int gameId,
  required int nodeId,
  required int epoch,
  required int maxHops,
  required int channelHz,
  required List<int> key,
}) {
  if (key.length != 16) throw ProxyException('the game key is 16 bytes');
  return Uint8List.fromList([
    RadioOp.configure,
    gameId >> 8,
    gameId & 0xff,
    nodeId >> 8,
    nodeId & 0xff,
    epoch >> 8,
    epoch & 0xff,
    maxHops,
    (channelHz >> 24) & 0xff,
    (channelHz >> 16) & 0xff,
    (channelHz >> 8) & 0xff,
    channelHz & 0xff,
    ...key,
  ]);
}

Uint8List radioError(int code, String message) =>
    Uint8List.fromList([_uint('code', code, 255), ...utf8.encode(message)]);

/// RADIO_CMD MEASURE: noise on a channel for dwell ms (with CAD: LoRa activity too).
Uint8List radioMeasure(int channelHz, int dwellMs, {bool cad = false}) =>
    Uint8List.fromList([
      RadioOp.measure,
      (_uint('channel_hz', channelHz, 0xffffffff) >> 24) & 0xff,
      (channelHz >> 16) & 0xff,
      (channelHz >> 8) & 0xff,
      channelHz & 0xff,
      _uint('dwell_ms', dwellMs, 0xffff) >> 8,
      dwellMs & 0xff,
      cad ? 1 : 0,
    ]);

/// A RADIO_NOISE payload (17 bytes), as the modem's NOISE frame lays it out.
final class RadioNoise {
  const RadioNoise({
    required this.channelHz,
    required this.dwellMs,
    required this.samples,
    required this.minDbm,
    required this.meanDbm,
    required this.p50Dbm,
    required this.p90Dbm,
    required this.maxDbm,
    required this.cadTries,
    required this.cadDetected,
  });

  factory RadioNoise.decode(List<int> p) {
    if (p.length != 17) throw ProxyException('a NOISE payload is 17 bytes');
    int u16(int i) => p[i] << 8 | p[i + 1];
    int i8(int i) => p[i] >= 128 ? p[i] - 256 : p[i];
    return RadioNoise(
      channelHz: p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3],
      dwellMs: u16(4),
      samples: u16(6),
      minDbm: i8(8),
      meanDbm: i8(9),
      p50Dbm: i8(10),
      p90Dbm: i8(11),
      maxDbm: i8(12),
      cadTries: u16(13),
      cadDetected: u16(15),
    );
  }

  final int channelHz, dwellMs, samples;
  final int minDbm, meanDbm, p50Dbm, p90Dbm, maxDbm;
  final int cadTries, cadDetected;

  Uint8List encode() => Uint8List.fromList([
    channelHz >> 24 & 0xff,
    channelHz >> 16 & 0xff,
    channelHz >> 8 & 0xff,
    channelHz & 0xff,
    dwellMs >> 8 & 0xff,
    dwellMs & 0xff,
    samples >> 8 & 0xff,
    samples & 0xff,
    minDbm & 0xff,
    meanDbm & 0xff,
    p50Dbm & 0xff,
    p90Dbm & 0xff,
    maxDbm & 0xff,
    cadTries >> 8 & 0xff,
    cadTries & 0xff,
    cadDetected >> 8 & 0xff,
    cadDetected & 0xff,
  ]);
}
