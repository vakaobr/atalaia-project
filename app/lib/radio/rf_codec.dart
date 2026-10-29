// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Skirmesh-RF's plaintext side (protocol/schema/messages.yaml, RFC 0001):
/// the 9-byte packet header and the HELLO, STATE, ACK, CMD, TIME and CLAIM
/// payloads, as CBOR maps with the schema's integer keys in key order, in
/// the shortest form. What an Android prop sends and hears on the field's
/// radio through an I/O pod (lib/radio/pod_radio_link.dart); the pod
/// encrypts and decrypts (the USB modem's code). The EVENT payload is the
/// core's own codec, through dart:ffi. The shared vectors
/// (protocol/vectors/{header,hello,state,ack,cmd,time,claim}.json) are checked by
/// test/radio/rf_codec_test.dart, as by the C and Python codecs.
library;

import 'dart:convert';
import 'dart:typed_data';

import '../protocol/cbor.dart';

/// The core's EVENT payload (atalaia/codec.h through dart:ffi), or null when
/// the codec refuses the event.
typedef EventEncoder =
    Uint8List? Function({
      required int node,
      required int seq,
      required int tMs,
      required String type,
      required int team,
      required int squad,
      required int prio,
      required String? dataJson,
    });

/// Message types (the header's last byte).
abstract final class RfType {
  static const hello = 1;
  static const event = 2;
  static const ack = 3;
  static const state = 4;
  static const cmd = 5;
  static const time = 6;
  static const config = 7;
  static const claim = 8;
}

/// Priorities (atalaia/protocol.h): telemetry is never acknowledged.
abstract final class RfPrio {
  static const telemetry = 0;
  static const normal = 1;
  static const critical = 2;

  static int of(String? name) => switch (name) {
    'telemetry' => telemetry,
    'critical' => critical,
    _ => normal,
  };
}

class RfException implements Exception {
  RfException(this.message);
  final String message;
  @override
  String toString() => 'RfException: $message';
}

/// The packet header: version_flags, game_id, source, seq, hop_limit, type.
final class RfHeader {
  const RfHeader({
    required this.versionFlags,
    required this.gameId,
    required this.source,
    required this.seq,
    required this.hopLimit,
    required this.type,
  });

  /// A version 1 header (the pod sets the encrypted bit).
  factory RfHeader.v1({
    required int gameId,
    required int source,
    required int seq,
    required int hopLimit,
    required int type,
    int prio = RfPrio.normal,
    bool ack = false,
  }) => RfHeader(
    versionFlags: 1 << 5 | (prio & 3) << 3 | (ack ? 1 << 2 : 0),
    gameId: gameId,
    source: source,
    seq: seq,
    hopLimit: hopLimit,
    type: type,
  );

  factory RfHeader.decode(List<int> b) {
    if (b.length < 9) throw RfException('a header is 9 bytes');
    final vf = b[0];
    if (vf >> 5 != 1) throw RfException('version ${vf >> 5}, not 1');
    if (vf & 1 != 0) throw RfException('the reserved bit is set');
    return RfHeader(
      versionFlags: vf,
      gameId: b[1] << 8 | b[2],
      source: b[3] << 8 | b[4],
      seq: b[5] << 8 | b[6],
      hopLimit: b[7],
      type: b[8],
    );
  }

  final int versionFlags, gameId, source, seq, hopLimit, type;

  int get prio => versionFlags >> 3 & 3;
  bool get ackRequested => versionFlags & 4 != 0;
  bool get encrypted => versionFlags & 2 != 0;

  Uint8List encode() => Uint8List.fromList([
    versionFlags,
    gameId >> 8 & 0xff,
    gameId & 0xff,
    source >> 8 & 0xff,
    source & 0xff,
    seq >> 8 & 0xff,
    seq & 0xff,
    hopLimit,
    type,
  ]);
}

// ---- helpers ------------------------------------------------------------------------------

Map<Object, Object?> _map(List<int> payload) {
  final Object? m;
  try {
    m = cborDecode(payload, allowBytes: true);
  } on CborException catch (e) {
    throw RfException(e.message);
  }
  if (m is! Map<Object, Object?>) throw RfException('a payload is a map');
  for (final k in m.keys) {
    if (k is! int) throw RfException('payload keys are integers');
  }
  return m;
}

int _uint(Map<Object, Object?> m, int key, String name, int max, {int? dflt}) {
  final v = m[key];
  if (v == null && dflt != null && !m.containsKey(key)) return dflt;
  if (v is! int || v < 0 || v > max) {
    throw RfException('$name is an integer 0-$max');
  }
  return v;
}

String _text(Map<Object, Object?> m, int key, String name, {int? maxBytes}) {
  final v = m[key];
  if (v is! String) throw RfException('$name is text');
  if (maxBytes != null && utf8.encode(v).length > maxBytes) {
    throw RfException('$name is at most $maxBytes bytes');
  }
  return v;
}

void _only(Map<Object, Object?> m, int maxKey) {
  for (final k in m.keys) {
    if ((k as int) < 1 || k > maxKey) throw RfException('unknown key $k');
  }
}

int _checked(String name, int v, int max) {
  if (v < 0 || v > max) throw RfException('$name is 0-$max');
  return v;
}

// ---- HELLO --------------------------------------------------------------------------------

final class RfHello {
  const RfHello({
    required this.nodeName,
    required this.platform,
    required this.fwVersion,
    required this.coreVersion,
    required this.tier,
    required this.capabilities,
    required this.transports,
    required this.epoch,
    this.batteryPct,
    this.deviceId,
  });

  factory RfHello.decode(List<int> payload) {
    final m = _map(payload);
    _only(m, 10);
    final dev = m[10];
    if (m.containsKey(10) && (dev is! Uint8List || dev.length != 8)) {
      throw RfException('device_id is 8 bytes');
    }
    final caps = m[6];
    if (caps is! List || caps.any((c) => c is! int || c < 0 || c > 255)) {
      throw RfException('capabilities is a list of 0-255');
    }
    return RfHello(
      nodeName: _text(m, 1, 'node_name', maxBytes: 24),
      platform: _uint(m, 2, 'platform', 255),
      fwVersion: _text(m, 3, 'fw_version'),
      coreVersion: _text(m, 4, 'core_version'),
      tier: _uint(m, 5, 'tier', 255),
      capabilities: caps.cast<int>(),
      transports: _uint(m, 7, 'transports', 255),
      batteryPct: m.containsKey(8) ? _uint(m, 8, 'battery_pct', 100) : null,
      epoch: _uint(m, 9, 'epoch', 0xffff),
      deviceId: dev is Uint8List ? dev : null,
    );
  }

  final String nodeName, fwVersion, coreVersion;
  final int platform, tier, transports, epoch;
  final List<int> capabilities;
  final int? batteryPct;

  /// The box's stable device id (key 10, optional; protocol/field-frames.md).
  final Uint8List? deviceId;

  Uint8List encode() {
    if (utf8.encode(nodeName).length > 24) {
      throw RfException('node_name is at most 24 bytes');
    }
    return cborEncode(<int, Object?>{
      1: nodeName,
      2: _checked('platform', platform, 255),
      3: fwVersion,
      4: coreVersion,
      5: _checked('tier', tier, 255),
      6: [for (final c in capabilities) _checked('capability', c, 255)],
      7: _checked('transports', transports, 255),
      if (batteryPct != null) 8: _checked('battery_pct', batteryPct!, 100),
      9: _checked('epoch', epoch, 0xffff),
      if (deviceId != null) 10: _deviceId(deviceId!),
    });
  }

  static Uint8List _deviceId(Uint8List id) {
    if (id.length != 8) throw RfException('device_id is 8 bytes');
    return id;
  }
}

/// HELLO's transports bits.
abstract final class RfTransport {
  static const lora = 1;
  static const wifi = 2;
  static const ble = 4;
}

// ---- STATE --------------------------------------------------------------------------------

/// The team points of a STATE's JSON form (the prop link's and the radio
/// link's input): `{"1": 40}` as {1: 40}; an entry that is not a team id
/// with a non-negative integer is left out, anything but a map is empty.
Map<int, int> teamPointsOf(Object? raw) {
  final out = <int, int>{};
  if (raw is Map) {
    raw.forEach((k, v) {
      final team = int.tryParse('$k');
      if (team != null && v is int && v >= 0) out[team] = v;
    });
  }
  return out;
}

final class RfState {
  const RfState({
    required this.ownerTeam,
    required this.phase,
    required this.gameTimeMs,
    required this.counters,
    required this.epoch,
    this.rssi,
    this.batteryPct,
    this.flags,
    this.lost = const {},
  });

  factory RfState.decode(List<int> payload) {
    final m = _map(payload);
    _only(m, 9);
    final counters = _teamPoints(m[4], 'counters');
    // Key 9 (RFC 0001 Amendment 18): the points each team lost to penalties on
    // the node; absent from a box that has none and from an older one.
    final lost = m.containsKey(9)
        ? _teamPoints(m[9], 'lost')
        : const <int, int>{};
    final rssi = m[5];
    if (rssi != null && (rssi is! int || rssi < -128 || rssi > 127)) {
      throw RfException('rssi is -128-127');
    }
    return RfState(
      ownerTeam: _uint(m, 1, 'owner_team', 255),
      phase: _uint(m, 2, 'phase', 255),
      gameTimeMs: _uint(m, 3, 'game_time_ms', 0xffffffff),
      counters: counters,
      lost: lost,
      rssi: rssi as int?,
      batteryPct: m.containsKey(6) ? _uint(m, 6, 'battery_pct', 100) : null,
      flags: m.containsKey(7) ? _uint(m, 7, 'flags', 255) : null,
      epoch: _uint(m, 8, 'epoch', 0xffff),
    );
  }

  final int ownerTeam, phase, gameTimeMs, epoch;
  final Map<int, int> counters;

  /// Points lost to penalties per team id (STATE key 9); empty when none.
  final Map<int, int> lost;
  final int? rssi, batteryPct, flags;

  Uint8List encode() => cborEncode(<int, Object?>{
    1: _checked('owner_team', ownerTeam, 255),
    2: _checked('phase', phase, 255),
    3: _checked('game_time_ms', gameTimeMs, 0xffffffff),
    4: <int, Object?>{
      for (final e in counters.entries)
        _checked('team', e.key, 255): _checked('counter', e.value, 0xffffffff),
    },
    if (rssi != null) 5: rssi,
    if (batteryPct != null) 6: _checked('battery_pct', batteryPct!, 100),
    if (flags != null) 7: _checked('flags', flags!, 255),
    8: _checked('epoch', epoch, 0xffff),
    if (lost.isNotEmpty)
      9: <int, Object?>{
        for (final e in lost.entries)
          _checked('team', e.key, 255): _checked('lost', e.value, 0xffffffff),
      },
  });

  static Map<int, int> _teamPoints(Object? c, String name) {
    if (c is! Map) throw RfException('$name is a map');
    final out = <int, int>{};
    c.forEach((k, v) {
      if (k is! int ||
          k < 0 ||
          k > 255 ||
          v is! int ||
          v < 0 ||
          v > 0xffffffff) {
        throw RfException('$name map team ids to 0-4294967295');
      }
      out[k] = v;
    });
    return out;
  }
}

// ---- ACK ----------------------------------------------------------------------------------

final class RfAck {
  const RfAck({required this.node, required this.seq, this.bitmap});

  factory RfAck.decode(List<int> payload) {
    final m = _map(payload);
    _only(m, 3);
    final bm = m[3];
    if (bm != null && (bm is! Uint8List || bm.length > 32)) {
      throw RfException('ack_bitmap is at most 32 bytes');
    }
    return RfAck(
      node: _uint(m, 1, 'ack_node', 0xffff),
      seq: _uint(m, 2, 'ack_seq', 0xffff),
      bitmap: bm as Uint8List?,
    );
  }

  /// The node acknowledged.
  final int node;

  /// The highest contiguous seq received (0xFFFF: none yet).
  final int seq;

  /// Bit i (byte i ~/ 8, bit i % 8): seq + 1 + i received too.
  final Uint8List? bitmap;

  /// Whether packet [pktSeq] is acknowledged (decision D7).
  bool covers(int pktSeq) {
    final contig = seq == 0xffff ? -1 : seq;
    if (pktSeq <= contig) return true;
    final bit = pktSeq - contig - 1;
    final b = bitmap;
    return b != null &&
        bit ~/ 8 < b.length &&
        (b[bit ~/ 8] >> (bit % 8)) & 1 == 1;
  }

  Uint8List encode() => cborEncode(<int, Object?>{
    1: _checked('ack_node', node, 0xffff),
    2: _checked('ack_seq', seq, 0xffff),
    if (bitmap != null) 3: bitmap,
  });
}

// ---- CMD ----------------------------------------------------------------------------------

/// CMD opcodes (ADR-P2-3; 8: RFC 0001 Amendment 5) and their names on the
/// Wi-Fi link (protocol/prop-link.md).
const rfCommands = [
  'start',
  'pause',
  'resume',
  'end',
  'set_owner',
  'message',
  'reset',
  'reboot',
  'mode',
];

final class RfCmd {
  const RfCmd({required this.cmd, this.params, this.dest});

  factory RfCmd.decode(List<int> payload) {
    final m = _map(payload);
    _only(m, 3);
    final p = m[2];
    if (p != null && (p is! Map || p.keys.any((k) => k is! String))) {
      throw RfException('params is a map with text keys');
    }
    return RfCmd(
      cmd: _uint(m, 1, 'cmd', 255),
      params: p == null ? null : (p as Map).cast<String, Object?>(),
      dest: m.containsKey(3) ? _uint(m, 3, 'dest', 0xffff) : null,
    );
  }

  final int cmd;
  final Map<String, Object?>? params;

  /// Null (or 0xFFFF): every node.
  final int? dest;

  String get name => cmd < rfCommands.length ? rfCommands[cmd] : 'cmd_$cmd';

  bool isFor(int node) => dest == null || dest == 0xffff || dest == node;

  Uint8List encode() => cborEncode(<int, Object?>{
    1: _checked('cmd', cmd, 255),
    if (params != null) 2: params,
    if (dest != null) 3: _checked('dest', dest!, 0xffff),
  });
}

// ---- TIME ---------------------------------------------------------------------------------

/// TIME's game states.
const rfGameStates = ['waiting', 'running', 'paused', 'ended'];

final class RfTime {
  const RfTime({
    required this.gameTimeMs,
    required this.gameState,
    required this.durationMs,
    required this.wallS,
    required this.term,
    this.txTimeUs,
  });

  factory RfTime.decode(List<int> payload) {
    final m = _map(payload);
    _only(m, 6);
    return RfTime(
      gameTimeMs: _uint(m, 1, 'game_time_ms', 0xffffffff),
      gameState: _uint(m, 2, 'game_state', 255),
      durationMs: _uint(m, 3, 'duration_ms', 0xffffffff),
      wallS: _uint(m, 4, 'wall_s', 0xffffffff),
      term: _uint(m, 5, 'term', 0xffffffff),
      txTimeUs: m.containsKey(6) ? _uint(m, 6, 'tx_time_us', 0xffff) : null,
    );
  }

  final int gameTimeMs, gameState, durationMs, wallS, term;
  final int? txTimeUs;

  String get stateName =>
      gameState < rfGameStates.length ? rfGameStates[gameState] : 'waiting';

  Uint8List encode() => cborEncode(<int, Object?>{
    1: _checked('game_time_ms', gameTimeMs, 0xffffffff),
    2: _checked('game_state', gameState, 255),
    3: _checked('duration_ms', durationMs, 0xffffffff),
    4: _checked('wall_s', wallS, 0xffffffff),
    5: _checked('term', term, 0xffffffff),
    if (txTimeUs != null) 6: _checked('tx_time_us', txTimeUs!, 0xffff),
  });
}

// ---- CLAIM --------------------------------------------------------------------------------

/// CLAIM (message type 8): a candidate stands for the controller role with
/// a term (ADR-P2-8; the phone's failover, PE24 slice S7,
/// controller_failover.dart).
final class RfClaim {
  const RfClaim({
    required this.term,
    required this.priority,
    required this.nodeId,
    this.lastAckSeq,
  });

  factory RfClaim.decode(List<int> payload) {
    final m = _map(payload);
    _only(m, 4);
    Map<int, int>? lastAck;
    if (m.containsKey(4)) {
      final acks = m[4];
      if (acks is! Map) throw RfException('last_ack_seq is a map');
      lastAck = {};
      for (final e in acks.entries) {
        final k = e.key, v = e.value;
        if (k is! int || k < 0 || k > 0xffff) {
          throw RfException('last_ack_seq: node ids 0-65535');
        }
        if (v is! int || v < 0 || v > 0xffff) {
          throw RfException('last_ack_seq: seqs 0-65535');
        }
        lastAck[k] = v;
      }
    }
    return RfClaim(
      term: _uint(m, 1, 'term', 0xffffffff),
      priority: _uint(m, 2, 'priority', 0xffff),
      nodeId: _uint(m, 3, 'node_id', 0xffff),
      lastAckSeq: lastAck,
    );
  }

  final int term, priority, nodeId;

  /// Per node, the highest contiguous seq this candidate heard (in the
  /// order given; the Python codec keeps its dict's order).
  final Map<int, int>? lastAckSeq;

  Uint8List encode() {
    final acks = lastAckSeq;
    return cborEncode(<int, Object?>{
      1: _checked('term', term, 0xffffffff),
      2: _checked('priority', priority, 0xffff),
      3: _checked('node_id', nodeId, 0xffff),
      if (acks != null && acks.isNotEmpty)
        4: <int, int>{
          for (final e in acks.entries)
            _checked('last_ack_seq node', e.key, 0xffff): _checked(
              'last_ack_seq seq',
              e.value,
              0xffff,
            ),
        },
    });
  }
}
