// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A chrono reading (ADR-P3-7, protocol/chrono-record.md): one shot through
/// the chronograph, entered by a marshal and signed with their Ed25519 key
/// (record_signer.dart).
library;

import 'dart:math' as math;
import 'dart:typed_data';

import '../security/canonical_json.dart';
import 'energy.dart';

/// `checkin` (first test of the day), `spotcheck` (during play), `retest`
/// (after a failed check-in, adjusted and tested again).
enum ReadingType { checkin, spotcheck, retest }

/// A record that does not follow protocol/chrono-record.md.
class ChronoFormatException implements Exception {
  ChronoFormatException(this.message);

  final String message;

  @override
  String toString() => 'ChronoFormatException: $message';
}

final _uuid = RegExp(
  r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
);
final _id = RegExp(r'^[A-Za-z0-9._:-]{1,64}$');
final _time = RegExp(r'^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})Z$');

/// Most decimals stored for each number, and its range.
const int velocityDecimals = 2;
const int weightDecimals = 3;
const int energyDecimals = 3;
const double maxVelocityMps = 1000;
const double maxBbWeightG = 10;
const double maxEnergyJ = 5000;
const int marshalNameMax = 64;

const _required = [
  'reading_id',
  'replica_id',
  'player_id',
  'type',
  'velocity_mps',
  'bb_weight_g',
  'energy_j',
  'chrono_id',
  'marshal_id',
  'marshal_name',
  'field_id',
  'timestamp',
];
const _optional = ['game_id', 'ref_reading_id'];

/// A random (version 4) UUID in lowercase, for reading and replica ids.
String newUuid([math.Random? random]) {
  final r = random ?? math.Random.secure();
  final b = List<int>.generate(16, (_) => r.nextInt(256));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
  return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-'
      '${h.substring(16, 20)}-${h.substring(20)}';
}

/// [t] in the records' form, `YYYY-MM-DDTHH:MM:SSZ` (UTC, whole seconds).
String formatTimestamp(DateTime t) {
  final u = t.toUtc();
  String two(int v) => v.toString().padLeft(2, '0');
  return '${u.year.toString().padLeft(4, '0')}-${two(u.month)}-${two(u.day)}'
      'T${two(u.hour)}:${two(u.minute)}:${two(u.second)}Z';
}

/// The time in a record's `timestamp`, or null if it is not in that form or
/// not a real date.
DateTime? parseTimestamp(String text) {
  final m = _time.firstMatch(text);
  if (m == null) return null;
  final p = [for (var i = 1; i <= 6; i++) int.parse(m.group(i)!)];
  if (p[0] < 1) return null; // year 1-9999, as Python's datetime
  final t = DateTime.utc(p[0], p[1], p[2], p[3], p[4], p[5]);
  return formatTimestamp(t) == text ? t : null;
}

int _decimals(double x) {
  final String text;
  try {
    text = canonicalNumber(x);
  } on ArgumentError {
    return 99; // below 1e-4: more decimals than any field allows
  }
  return text.length - text.indexOf('.') - 1;
}

/// Energy as stored in a record: [energyJoules] rounded half away from zero
/// to 3 decimals (millijoules).
double recordEnergy(double bbWeightG, double velocityMps) => roundHalfAway(
  energyJoules(bbWeightG: bbWeightG, velocityMps: velocityMps),
  energyDecimals,
);

class ChronoReading {
  ChronoReading._({
    required this.readingId,
    required this.replicaId,
    required this.playerId,
    required this.type,
    required this.velocityMps,
    required this.bbWeightG,
    required this.energyJ,
    required this.chronoId,
    required this.marshalId,
    required this.marshalName,
    required this.fieldId,
    required this.timestamp,
    this.gameId,
    this.refReadingId,
    this.signature,
  }) {
    _validate();
  }

  /// A new, unsigned reading from what the marshal entered: the velocity is
  /// rounded to 0.01 m/s, the weight to 0.001 g, and the energy computed
  /// from those and rounded to 0.001 J. Throws [ChronoFormatException].
  factory ChronoReading.measure({
    String? readingId,
    required String replicaId,
    required String playerId,
    required ReadingType type,
    required double velocityMps,
    required double bbWeightG,
    required String chronoId,
    required String marshalId,
    required String marshalName,
    required String fieldId,
    required DateTime timestamp,
    String? gameId,
    String? refReadingId,
  }) {
    if (!velocityMps.isFinite || !bbWeightG.isFinite) {
      throw ChronoFormatException('velocity and weight are finite numbers');
    }
    final v = roundHalfAway(velocityMps, velocityDecimals);
    final w = roundHalfAway(bbWeightG, weightDecimals);
    if (v <= 0 || w <= 0) {
      throw ChronoFormatException('velocity and weight are more than 0');
    }
    return ChronoReading._(
      readingId: readingId ?? newUuid(),
      replicaId: replicaId,
      playerId: playerId,
      type: type,
      velocityMps: v,
      bbWeightG: w,
      energyJ: recordEnergy(w, v),
      chronoId: chronoId,
      marshalId: marshalId,
      marshalName: marshalName,
      fieldId: fieldId,
      timestamp: formatTimestamp(timestamp),
      gameId: gameId,
      refReadingId: refReadingId,
    );
  }

  /// A record from its decoded JSON object, checked field by field
  /// (protocol/chrono-record.md); the signature, if any, is kept but not
  /// verified here (see verifyReading). Throws [ChronoFormatException].
  factory ChronoReading.fromJson(Object? json) {
    if (json is! Map<String, Object?>) {
      throw ChronoFormatException('a record is a JSON object');
    }
    final unknown = json.keys.where(
      (k) =>
          !_required.contains(k) && !_optional.contains(k) && k != 'signature',
    );
    if (unknown.isNotEmpty) {
      throw ChronoFormatException('unknown fields ${unknown.toList()}');
    }
    final missing = _required.where((k) => !json.containsKey(k));
    if (missing.isNotEmpty) {
      throw ChronoFormatException('missing fields ${missing.toList()}');
    }
    String text(String k) {
      final v = json[k];
      if (v is! String) throw ChronoFormatException('$k is a string');
      return v;
    }

    String? optional(String k) => json.containsKey(k) ? text(k) : null;
    double number(String k) {
      final v = json[k];
      if (v is! num) throw ChronoFormatException('$k is a number');
      return v.toDouble();
    }

    final typeText = text('type');
    final type = ReadingType.values.where((t) => t.name == typeText);
    if (type.isEmpty) {
      throw ChronoFormatException('type is checkin, spotcheck or retest');
    }
    return ChronoReading._(
      readingId: text('reading_id'),
      replicaId: text('replica_id'),
      playerId: text('player_id'),
      type: type.single,
      velocityMps: number('velocity_mps'),
      bbWeightG: number('bb_weight_g'),
      energyJ: number('energy_j'),
      chronoId: text('chrono_id'),
      marshalId: text('marshal_id'),
      marshalName: text('marshal_name'),
      fieldId: text('field_id'),
      timestamp: text('timestamp'),
      gameId: optional('game_id'),
      refReadingId: optional('ref_reading_id'),
      signature: json.containsKey('signature') ? text('signature') : null,
    );
  }

  final String readingId;
  final String replicaId;
  final String playerId;
  final ReadingType type;
  final double velocityMps;
  final double bbWeightG;
  final double energyJ;
  final String chronoId;
  final String marshalId;
  final String marshalName;
  final String fieldId;

  /// `YYYY-MM-DDTHH:MM:SSZ`.
  final String timestamp;

  /// The game the reading was taken in; null before a game (a check-in).
  final String? gameId;

  /// The reading this one repeats (a retest) or is compared with (a spot
  /// check, optional).
  final String? refReadingId;

  /// The marshal's Ed25519 signature in base64; null until signed.
  final String? signature;

  DateTime get time => parseTimestamp(timestamp)!;

  void _validate() {
    void id(String name, String v) {
      if (!_id.hasMatch(v)) {
        throw ChronoFormatException(
          "$name is 1-64 letters, digits, '.', '_', ':' or '-'",
        );
      }
    }

    void uuid(String name, String v) {
      if (!_uuid.hasMatch(v)) {
        throw ChronoFormatException('$name is a lowercase UUID');
      }
    }

    void number(String name, double v, double hi, int places, bool zeroOk) {
      if (!v.isFinite || v < 0 || v > hi || (v == 0 && !zeroOk)) {
        throw ChronoFormatException('$name $v is out of range');
      }
      if (_decimals(v) > places) {
        throw ChronoFormatException('$name has more than $places decimals');
      }
    }

    uuid('reading_id', readingId);
    uuid('replica_id', replicaId);
    if (refReadingId != null) uuid('ref_reading_id', refReadingId!);
    id('player_id', playerId);
    id('chrono_id', chronoId);
    id('marshal_id', marshalId);
    id('field_id', fieldId);
    if (gameId != null) id('game_id', gameId!);
    number(
      'velocity_mps',
      velocityMps,
      maxVelocityMps,
      velocityDecimals,
      false,
    );
    number('bb_weight_g', bbWeightG, maxBbWeightG, weightDecimals, false);
    number('energy_j', energyJ, maxEnergyJ, energyDecimals, true);
    final runes = marshalName.runes.length;
    if (runes < 1 || runes > marshalNameMax || !isCanonicalText(marshalName)) {
      throw ChronoFormatException(
        'marshal_name is 1-64 characters without control characters',
      );
    }
    if (parseTimestamp(timestamp) == null) {
      throw ChronoFormatException('timestamp is YYYY-MM-DDTHH:MM:SSZ');
    }
    if (energyJ != recordEnergy(bbWeightG, velocityMps)) {
      throw ChronoFormatException(
        'energy_j does not match bb_weight_g and velocity_mps',
      );
    }
    if (type == ReadingType.retest && refReadingId == null) {
      throw ChronoFormatException(
        'a retest names the reading it repeats (ref_reading_id)',
      );
    }
    if (type == ReadingType.checkin && refReadingId != null) {
      throw ChronoFormatException('a check-in has no ref_reading_id');
    }
  }

  /// Every field except the signature: what is signed.
  Map<String, Object> signedFields() => {
    'reading_id': readingId,
    'replica_id': replicaId,
    'player_id': playerId,
    'type': type.name,
    'velocity_mps': velocityMps,
    'bb_weight_g': bbWeightG,
    'energy_j': energyJ,
    'chrono_id': chronoId,
    'marshal_id': marshalId,
    'marshal_name': marshalName,
    'game_id': ?gameId,
    'field_id': fieldId,
    'timestamp': timestamp,
    'ref_reading_id': ?refReadingId,
  };

  /// The bytes the marshal signs (protocol/chrono-record.md).
  Uint8List canonicalBytes() => canonicalJson(signedFields());

  /// The record as a JSON object, with its signature if it has one.
  Map<String, Object> toJson() => {...signedFields(), 'signature': ?signature};

  /// This reading with [signature] (base64): see signReading.
  ChronoReading withSignature(String? signature) => ChronoReading._(
    readingId: readingId,
    replicaId: replicaId,
    playerId: playerId,
    type: type,
    velocityMps: velocityMps,
    bbWeightG: bbWeightG,
    energyJ: energyJ,
    chronoId: chronoId,
    marshalId: marshalId,
    marshalName: marshalName,
    fieldId: fieldId,
    timestamp: timestamp,
    gameId: gameId,
    refReadingId: refReadingId,
    signature: signature,
  );

  @override
  String toString() => 'ChronoReading(${toJson()})';
}
