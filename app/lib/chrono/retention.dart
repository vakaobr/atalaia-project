// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// GDPR retention and erasure of chrono readings (ADR-P3-7): readings are
/// kept for the field's retention period (default 365 days, 1 day to 10
/// years) and then deleted without notice; a player may have all of their
/// readings erased at any time. Whatever stores readings (the controller,
/// the marshal's phone, the site server) applies these rules.
library;

import 'reading.dart';

class RetentionPolicy {
  RetentionPolicy({this.days = defaultDays}) {
    if (days < minDays || days > maxDays) {
      throw ArgumentError.value(days, 'days', '$minDays-$maxDays');
    }
  }

  static const int defaultDays = 365;
  static const int minDays = 1;
  static const int maxDays = 3653;

  final int days;

  /// When a reading taken at [time] is due for deletion.
  DateTime expiresAt(DateTime time) => time.toUtc().add(Duration(days: days));

  bool isExpired(ChronoReading reading, DateTime now) =>
      !now.toUtc().isBefore(expiresAt(reading.time));

  /// The readings to keep at [now].
  List<ChronoReading> keep(Iterable<ChronoReading> readings, DateTime now) => [
    for (final r in readings)
      if (!isExpired(r, now)) r,
  ];
}

/// [readings] without any of [playerId]'s (right of erasure).
List<ChronoReading> eraseForPlayer(
  Iterable<ChronoReading> readings,
  String playerId,
) => [
  for (final r in readings)
    if (r.playerId != playerId) r,
];
