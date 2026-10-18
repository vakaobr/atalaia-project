// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

import 'package:atalaia_app/chrono/energy.dart';
import 'package:atalaia_app/chrono/reading.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/vectors.dart';

void main() {
  test('0.20 g at 100 m/s is 1.0 J', () {
    expect(
      energyJoules(bbWeightG: 0.20, velocityMps: 100),
      closeTo(1.0, 1e-12),
    );
  });

  test('0.25 g at 90 m/s is 1.0125 J', () {
    expect(
      energyJoules(bbWeightG: 0.25, velocityMps: 90),
      closeTo(1.0125, 1e-12),
    );
  });

  test('0.20 g at 350 fps is about 1.14 J (the common rifle limit)', () {
    final e = energyJoules(bbWeightG: 0.20, velocityMps: fpsToMps(350));
    expect(e, closeTo(1.138, 0.001));
    expect(fpsWith020(1.14), closeTo(350.3, 0.1));
  });

  test('no velocity or no weight is no energy', () {
    expect(energyJoules(bbWeightG: 0.20, velocityMps: 0), 0);
    expect(energyJoules(bbWeightG: 0, velocityMps: 100), 0);
  });

  test('negative or non-finite inputs are refused', () {
    expect(
      () => energyJoules(bbWeightG: -0.2, velocityMps: 100),
      throwsArgumentError,
    );
    expect(
      () => energyJoules(bbWeightG: 0.2, velocityMps: double.nan),
      throwsArgumentError,
    );
    expect(() => fpsToMps(-1), throwsArgumentError);
    expect(
      () => velocityForEnergy(energyJ: 1, bbWeightG: 0),
      throwsArgumentError,
    );
  });

  test('fps and m/s convert both ways (1 ft = 0.3048 m exactly)', () {
    expect(fpsToMps(1000), closeTo(304.8, 1e-9));
    expect(mpsToFps(304.8), closeTo(1000, 1e-9));
    expect(mpsToFps(fpsToMps(412.5)), closeTo(412.5, 1e-9));
  });

  test('velocityForEnergy inverts energyJoules', () {
    final v = velocityForEnergy(energyJ: 1.0, bbWeightG: 0.20);
    expect(v, closeTo(100, 1e-9));
    expect(
      energyJoules(
        bbWeightG: 0.28,
        velocityMps: velocityForEnergy(energyJ: 1.5, bbWeightG: 0.28),
      ),
      closeTo(1.5, 1e-9),
    );
  });

  test('rounding is half away from zero', () {
    expect(roundHalfAway(2.5, 0), 3);
    expect(roundHalfAway(-2.5, 0), -3);
    expect(roundHalfAway(0.0625, 3), 0.063);
    expect(roundHalfAway(1.050625, 3), 1.051);
    expect(() => roundHalfAway(1, 7), throwsArgumentError);
  });

  group('shared vectors (the Python verifier computes the same)', () {
    final v = loadVectors('chrono_record.json');
    test('energies', () {
      for (final c in cases(v, 'energies')) {
        final w = (c['bb_weight_g'] as num).toDouble();
        final mps = (c['velocity_mps'] as num).toDouble();
        expect(
          recordEnergy(w, mps),
          (c['energy_j'] as num).toDouble(),
          reason: '$c',
        );
      }
    });
    test('fps', () {
      for (final c in cases(v, 'fps')) {
        final fps = (c['fps'] as num).toDouble();
        expect(
          roundHalfAway(fpsToMps(fps), 2),
          (c['velocity_mps'] as num).toDouble(),
          reason: '$c',
        );
      }
    });
  });
}
