// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Check-in and spot-check decisions (ADR-P3-7).
///
/// A series of shots is judged by its highest energy:
///
/// * check-in (and retest): PASS if it is at or below the class limit,
///   otherwise FAIL;
/// * spot check: FAIL above the class limit; WARN at or below it but above
///   the check-in energy plus the tolerance (default 5%); otherwise PASS.
///   Without a check-in to compare with, only the limit counts.
///
/// The energies compared are the records' `energy_j` (rounded to 0.001 J),
/// so the result is what the marshal sees on screen and anyone can recompute
/// it from the signed records. WARN and FAIL are violations: the app reports
/// `chrono.violation` to the GM and marshals (plan phases D and E).
library;

import 'limit_template.dart';
import 'reading.dart';

enum CheckResult { pass, warn, fail }

const double defaultTolerancePct = 5.0;

class CheckOutcome {
  const CheckOutcome({
    required this.result,
    required this.highestEnergyJ,
    required this.limitJ,
    this.checkinEnergyJ,
    this.tolerancePct,
  });

  final CheckResult result;

  /// The series' highest energy.
  final double highestEnergyJ;

  /// The class limit it was compared with.
  final double limitJ;

  /// The check-in energy (spot checks with a check-in only).
  final double? checkinEnergyJ;
  final double? tolerancePct;

  /// The most a spot check may show without a warning, or null.
  double? get allowedJ => checkinEnergyJ == null
      ? null
      : checkinEnergyJ! * (1 + tolerancePct! / 100);

  bool get isViolation => result != CheckResult.pass;

  @override
  String toString() =>
      'CheckOutcome(${result.name}, ${highestEnergyJ}J, limit ${limitJ}J'
      '${checkinEnergyJ == null ? '' : ', check-in ${checkinEnergyJ}J +$tolerancePct%'})';
}

/// The highest of [energiesJ]; at least one is needed.
double highestEnergy(Iterable<double> energiesJ) {
  if (energiesJ.isEmpty) throw ArgumentError('no readings');
  var best = energiesJ.first;
  for (final e in energiesJ) {
    if (!e.isFinite || e < 0) throw ArgumentError.value(e, 'energy');
    if (e > best) best = e;
  }
  return best;
}

/// A check-in (or retest) series against [limit]: PASS or FAIL.
CheckOutcome checkIn(Iterable<double> energiesJ, ClassLimit limit) {
  final e = highestEnergy(energiesJ);
  return CheckOutcome(
    result: e <= limit.maxEnergyJ ? CheckResult.pass : CheckResult.fail,
    highestEnergyJ: e,
    limitJ: limit.maxEnergyJ,
  );
}

/// A spot-check series against [limit] and, if known, the replica's
/// [checkinEnergyJ] (the highest energy of its last passed check-in).
CheckOutcome spotCheck(
  Iterable<double> energiesJ,
  ClassLimit limit, {
  double? checkinEnergyJ,
  double tolerancePct = defaultTolerancePct,
}) {
  if (!tolerancePct.isFinite || tolerancePct < 0 || tolerancePct > 100) {
    throw ArgumentError.value(tolerancePct, 'tolerancePct', '0-100');
  }
  final e = highestEnergy(energiesJ);
  final CheckResult result;
  if (e > limit.maxEnergyJ) {
    result = CheckResult.fail;
  } else if (checkinEnergyJ != null &&
      e > checkinEnergyJ * (1 + tolerancePct / 100)) {
    result = CheckResult.warn;
  } else {
    result = CheckResult.pass;
  }
  return CheckOutcome(
    result: result,
    highestEnergyJ: e,
    limitJ: limit.maxEnergyJ,
    checkinEnergyJ: checkinEnergyJ,
    tolerancePct: checkinEnergyJ == null ? null : tolerancePct,
  );
}

/// [checkIn] on readings (check-in or retest series).
CheckOutcome checkInReadings(
  Iterable<ChronoReading> readings,
  ClassLimit limit,
) => checkIn(readings.map((r) => r.energyJ), limit);

/// [spotCheck] on readings: [spot] is the spot-check series, [checkin] the
/// series of the replica's last check-in or retest (may be empty).
CheckOutcome spotCheckReadings(
  Iterable<ChronoReading> spot,
  ClassLimit limit, {
  Iterable<ChronoReading> checkin = const [],
  double tolerancePct = defaultTolerancePct,
}) => spotCheck(
  spot.map((r) => r.energyJ),
  limit,
  checkinEnergyJ: checkin.isEmpty
      ? null
      : highestEnergy(checkin.map((r) => r.energyJ)),
  tolerancePct: tolerancePct,
);
