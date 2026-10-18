// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import 'package:atalaia_app/chrono/limit_template.dart';
import 'package:atalaia_app/chrono/reading.dart';
import 'package:atalaia_app/chrono/spot_check.dart';
import 'package:flutter_test/flutter_test.dart';

final rifle = ClassLimit(
  name: 'rifle',
  maxEnergyJ: 1.14,
  maxFps020: 350,
  medM: 0,
  fireMode: FireMode.fullAuto,
);

ChronoReading shot(double mps, {ReadingType type = ReadingType.spotcheck}) =>
    ChronoReading.measure(
      replicaId: '8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50',
      playerId: 'p-17',
      type: type,
      velocityMps: mps,
      bbWeightG: 0.20,
      chronoId: 'c-1',
      marshalId: 'm-1',
      marshalName: 'Ana',
      fieldId: 'f-1',
      timestamp: DateTime.utc(2026, 10, 18, 12),
    );

void main() {
  group('spot check', () {
    test('PASS: under the limit and within 5% of check-in', () {
      final o = spotCheck([1.00, 1.04, 1.02], rifle, checkinEnergyJ: 1.0);
      expect(o.result, CheckResult.pass);
      expect(o.highestEnergyJ, 1.04);
      expect(o.isViolation, isFalse);
      expect(o.allowedJ, closeTo(1.05, 1e-12));
    });

    test('WARN: under the limit but more than 5% above check-in', () {
      final o = spotCheck([1.00, 1.06], rifle, checkinEnergyJ: 1.0);
      expect(o.result, CheckResult.warn);
      expect(o.isViolation, isTrue);
    });

    test('FAIL: over the limit, whatever the check-in said', () {
      expect(
        spotCheck([1.141], rifle, checkinEnergyJ: 1.13).result,
        CheckResult.fail,
      );
      expect(spotCheck([1.2], rifle).result, CheckResult.fail);
    });

    test('exactly at the limit, or at check-in + 5%, passes', () {
      expect(spotCheck([1.14], rifle).result, CheckResult.pass);
      expect(
        spotCheck([1.05], rifle, checkinEnergyJ: 1.0).result,
        CheckResult.pass,
      );
    });

    test('the tolerance is configurable', () {
      expect(
        spotCheck([1.06], rifle, checkinEnergyJ: 1.0, tolerancePct: 10).result,
        CheckResult.pass,
      );
      expect(
        spotCheck([1.01], rifle, checkinEnergyJ: 1.0, tolerancePct: 0).result,
        CheckResult.warn,
      );
      expect(
        () => spotCheck([1.0], rifle, tolerancePct: -1),
        throwsArgumentError,
      );
      expect(
        () => spotCheck([1.0], rifle, tolerancePct: 101),
        throwsArgumentError,
      );
    });

    test('without a check-in only the limit counts', () {
      final o = spotCheck([1.13], rifle);
      expect(o.result, CheckResult.pass);
      expect(o.checkinEnergyJ, isNull);
      expect(o.allowedJ, isNull);
    });

    test('no readings is an error', () {
      expect(() => spotCheck([], rifle), throwsArgumentError);
      expect(() => spotCheck([double.nan], rifle), throwsArgumentError);
    });
  });

  group('check-in', () {
    test('PASS at or under the limit, FAIL over it', () {
      expect(checkIn([1.10, 1.14, 1.12], rifle).result, CheckResult.pass);
      expect(checkIn([1.10, 1.15], rifle).result, CheckResult.fail);
      expect(checkIn([1.15], rifle).highestEnergyJ, 1.15);
    });
  });

  group('from readings', () {
    test('350 fps with 0.20 g passes a 1.14 J rifle limit (1.138 J)', () {
      final o = checkInReadings([
        shot(106.68, type: ReadingType.checkin),
      ], rifle);
      expect(o.highestEnergyJ, 1.138);
      expect(o.result, CheckResult.pass);
    });

    test('a hotter spot check than at check-in warns', () {
      final checkin = [
        shot(99.0, type: ReadingType.checkin),
        shot(100.0, type: ReadingType.checkin),
      ];
      final spot = [shot(103.0), shot(102.0)];
      final o = spotCheckReadings(spot, rifle, checkin: checkin);
      expect(o.checkinEnergyJ, 1.0);
      expect(o.highestEnergyJ, 1.061);
      expect(o.result, CheckResult.warn);
    });

    test('over the limit at a spot check fails', () {
      final o = spotCheckReadings(
        [shot(110.0)],
        rifle,
        checkin: [shot(100.0, type: ReadingType.checkin)],
      );
      expect(o.highestEnergyJ, 1.21);
      expect(o.result, CheckResult.fail);
    });

    test('a spot check without check-in readings', () {
      expect(spotCheckReadings([shot(100.0)], rifle).result, CheckResult.pass);
    });
  });
}
