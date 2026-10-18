// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import 'dart:math' as math;

import 'package:atalaia_app/chrono/energy.dart';
import 'package:atalaia_app/chrono/reading.dart';
import 'package:flutter_test/flutter_test.dart';

Matcher get badFormat => throwsA(isA<ChronoFormatException>());

ChronoReading measure({
  ReadingType type = ReadingType.checkin,
  double velocityMps = 102.5,
  double bbWeightG = 0.2,
  String? refReadingId,
  String marshalName = 'Jose',
  String playerId = 'p-17',
  DateTime? at,
}) => ChronoReading.measure(
  readingId: '3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b',
  replicaId: '8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50',
  playerId: playerId,
  type: type,
  velocityMps: velocityMps,
  bbWeightG: bbWeightG,
  chronoId: 'chrono-field-1',
  marshalId: 'm-xyz789',
  marshalName: marshalName,
  fieldId: 'field-cqb-porto',
  gameId: '4242',
  timestamp: at ?? DateTime.utc(2026, 10, 18, 14, 30),
  refReadingId: refReadingId,
);

void main() {
  test('measure rounds and computes the energy', () {
    final r = measure(velocityMps: fpsToMps(350), bbWeightG: 0.25);
    expect(r.velocityMps, 106.68);
    expect(r.bbWeightG, 0.25);
    expect(r.energyJ, 1.423);
    expect(r.signature, isNull);
    expect(r.timestamp, '2026-10-18T14:30:00Z');
  });

  test('JSON round trip', () {
    final r = measure();
    final back = ChronoReading.fromJson(r.toJson());
    expect(back.toJson(), r.toJson());
    expect(back.time, DateTime.utc(2026, 10, 18, 14, 30));
    expect(r.toJson().containsKey('signature'), isFalse);
    expect(r.toJson().containsKey('ref_reading_id'), isFalse);
  });

  test('timestamps are UTC whole seconds', () {
    final local = DateTime.utc(2026, 1, 2, 3, 4, 5, 678).toLocal();
    expect(formatTimestamp(local), '2026-01-02T03:04:05Z');
    expect(parseTimestamp('2026-02-29T00:00:00Z'), isNull);
    expect(
      parseTimestamp('2028-02-29T23:59:59Z'),
      DateTime.utc(2028, 2, 29, 23, 59, 59),
    );
    expect(parseTimestamp('2026-10-18 14:30:00Z'), isNull);
    expect(parseTimestamp('0000-01-01T00:00:00Z'), isNull);
    expect(parseTimestamp('2026-10-18T14:30:60Z'), isNull);
    expect(parseTimestamp('2026-10-18T24:00:00Z'), isNull);
  });

  test('retests name the reading they repeat; check-ins do not', () {
    expect(() => measure(type: ReadingType.retest), badFormat);
    expect(
      measure(
        type: ReadingType.retest,
        refReadingId: '3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b',
      ).type,
      ReadingType.retest,
    );
    expect(
      () => measure(refReadingId: '3f2b8c1e-5d4a-4e6f-9a7b-1c2d3e4f5a6b'),
      badFormat,
    );
    expect(measure(type: ReadingType.spotcheck).refReadingId, isNull);
  });

  test('values out of range are refused', () {
    expect(() => measure(velocityMps: 0), badFormat);
    expect(() => measure(velocityMps: 0.001), badFormat); // rounds to 0
    expect(() => measure(velocityMps: 1000.01), badFormat);
    expect(() => measure(bbWeightG: 0), badFormat);
    expect(() => measure(bbWeightG: 10.5), badFormat);
    expect(() => measure(velocityMps: double.nan), badFormat);
  });

  test('names and ids are checked', () {
    expect(() => measure(marshalName: ''), badFormat);
    expect(() => measure(marshalName: 'a' * 65), badFormat);
    expect(measure(marshalName: '\u{1F3AF}' * 64).marshalName.runes.length, 64);
    expect(() => measure(marshalName: 'Ana\tRita'), badFormat);
    expect(() => measure(playerId: 'p 17'), badFormat);
    expect(() => measure(playerId: 'x' * 65), badFormat);
  });

  test('fromJson is strict', () {
    final json = measure().toJson();
    expect(() => ChronoReading.fromJson({...json, 'notes': 'x'}), badFormat);
    expect(
      () => ChronoReading.fromJson({...json}..remove('chrono_id')),
      badFormat,
    );
    expect(
      () => ChronoReading.fromJson({...json, 'energy_j': 1.05}),
      badFormat,
    );
    expect(
      () => ChronoReading.fromJson({...json, 'velocity_mps': '102.5'}),
      badFormat,
    );
    expect(
      () => ChronoReading.fromJson({...json, 'velocity_mps': 0.00001}),
      badFormat,
    );
    expect(
      () => ChronoReading.fromJson({...json, 'type': 'check-in'}),
      badFormat,
    );
    expect(() => ChronoReading.fromJson(<Object>[]), badFormat);
    // Whole numbers may arrive as JSON integers.
    final whole = measure(velocityMps: 100).toJson();
    expect(
      ChronoReading.fromJson({
        ...whole,
        'velocity_mps': 100,
        'energy_j': 1,
      }).velocityMps,
      100.0,
    );
  });

  test('new UUIDs are version 4 and lowercase', () {
    final ids = {for (var i = 0; i < 50; i++) newUuid()};
    expect(ids.length, 50);
    for (final id in ids) {
      expect(
        id,
        matches(
          RegExp(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
          ),
        ),
      );
    }
    expect(newUuid(math.Random(1)), newUuid(math.Random(1)));
  });
}
