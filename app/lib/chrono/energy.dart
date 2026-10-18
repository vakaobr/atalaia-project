// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Muzzle energy and velocity units for chrono check-in (ADR-P3-7).
///
/// `E = 0.5 * m * v^2`, with m in kilograms and v in metres per second, so
/// a 0.20 g BB at 100 m/s carries 1.0 J. The operations always run in the
/// same order (`0.5 * (g / 1000) * v * v`), so the controller's and the site
/// server's Python gets the same binary64 result as this code.
library;

import 'dart:math' as math;

/// One foot in metres, exactly (the international foot).
const double metresPerFoot = 0.3048;

/// The BB weight that `max_fps_020` in the limit templates refers to.
const double referenceBbWeightG = 0.20;

void _check(String name, double v) {
  if (!v.isFinite || v < 0) {
    throw ArgumentError.value(v, name, 'a finite number, 0 or more');
  }
}

/// Muzzle energy in joules of a [bbWeightG] gram BB at [velocityMps] m/s.
double energyJoules({required double bbWeightG, required double velocityMps}) {
  _check('bbWeightG', bbWeightG);
  _check('velocityMps', velocityMps);
  return 0.5 * (bbWeightG / 1000) * velocityMps * velocityMps;
}

/// Feet per second to metres per second.
double fpsToMps(double fps) {
  _check('fps', fps);
  return fps * metresPerFoot;
}

/// Metres per second to feet per second.
double mpsToFps(double mps) {
  _check('mps', mps);
  return mps / metresPerFoot;
}

/// The velocity (m/s) at which a [bbWeightG] gram BB carries [energyJ] joules.
double velocityForEnergy({required double energyJ, required double bbWeightG}) {
  _check('energyJ', energyJ);
  _check('bbWeightG', bbWeightG);
  if (bbWeightG == 0) {
    throw ArgumentError.value(bbWeightG, 'bbWeightG', 'more than 0');
  }
  return math.sqrt(2 * energyJ / (bbWeightG / 1000));
}

/// The velocity in fps with 0.20 g BBs that carries [energyJ] joules: the
/// figure players usually quote (`max_fps_020` in the limit templates).
double fpsWith020(double energyJ) => mpsToFps(
  velocityForEnergy(energyJ: energyJ, bbWeightG: referenceBbWeightG),
);

/// [x] rounded to [decimals] places, halves away from zero (as the Python
/// side's `round_half_away`).
double roundHalfAway(double x, int decimals) {
  if (decimals < 0 || decimals > 6) {
    throw ArgumentError.value(decimals, 'decimals', '0-6');
  }
  final scale = math.pow(10, decimals).toDouble();
  return (x * scale).roundToDouble() / scale;
}
