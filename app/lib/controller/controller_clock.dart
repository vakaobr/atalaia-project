// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The Android field controller's wall clock, and a guard against a wrong
/// one: the Pi controller's controller/atalaia_controller/wallclock.py in
/// Dart (decisions CLK-1 to CLK-8; on the phone since STUCK-62, changed by
/// the maintainer on 2026-11-05).
///
/// A phone's clock is usually the network's, but one that was reset, or set
/// by hand far back, or that has no network on the field, can be wrong. Its
/// time goes into the timestamps, the player tokens' expiry, the retention
/// purge, the TIME beacons' `wall_s` (the join time a box keeps) and the
/// field-wide RELEASE's `time`, which the boxes compare with it (RFC 0001
/// Amendment 28). Durations never use it: games, timeouts and rate limits run
/// on the engine's monotonic clock.
///
/// [ClockGuard.now] is the system clock plus an offset that only a GM can
/// move, and only forward ([ClockGuard.set], `PUT /api/v1/clock`): the
/// app does not set the phone's clock, and a GM's browser has the right time.
/// A clock that moved backwards would let an expired player token live again,
/// so a backward move is refused, as is any move below the plausibility
/// floor.
///
/// The floor is the newest of: the release date of this build (the Pi's
/// `RELEASE_DATE`; a test keeps the two equal), the highest wall time this
/// controller saw (kept in the store's settings every few minutes, as
/// `clock.high_water`) and the newest timestamp in the store. A clock below
/// it, less [clockToleranceS], is wrong, whatever the reason: the console
/// says so (`clock` in the status) and the retention purge waits.
///
/// The offset lives as long as the engine, as the Pi's lives as long as the
/// process: after a restart the high-water mark catches a clock that is
/// still wrong.
library;

/// The date of this release, UTC (2026-11-01 00:00): no real clock in the
/// field is earlier. The Pi's wallclock.py `RELEASE_DATE`; a test keeps the
/// two equal.
const clockReleaseDateS = 1793491200;

/// The setting that keeps the highest wall time seen.
const clockHighWaterKey = 'clock.high_water';

/// How often the highest wall time seen is stored.
const clockHighWaterEveryS = 300;

/// A clock this far under the floor is still taken as right.
const clockToleranceS = 60;

/// Wall time that moves this much more or less than monotonic time: a jump.
const clockJumpS = 30;

/// A forward jump this big holds the retention purge ...
const clockBigJumpS = 86400;

/// ... for this long, so a GM sees the banner before anything is deleted.
const clockPurgeHoldS = 3600;

/// A set from a wrong clock: at most this far above the floor ...
const clockSetMaxAheadFloorS = 5 * 365 * 86400;

/// ... and from a plausible clock, at most this far above it.
const clockSetMaxAheadNowS = 14 * 86400;

/// A field-wide RELEASE (RFC 0001 Amendment 28, its addendum of
/// 2026-11-06) is stamped with [ClockGuard.now]: never more than this past a
/// clock the controller can vouch for (wallclock.py `RELEASE_SLACK_S`). The
/// boxes refuse one more than the same 300 s past their game's clock.
const clockReleaseSlackS = 300;

/// A clock setting that is refused; [code] is stable for the console
/// (wallclock.py `ClockError`).
class ClockError implements Exception {
  ClockError(this.code, this.message, {this.status = 409});
  final String code;
  final String message;
  final int status;

  @override
  String toString() => message;
}

/// wallclock.py's `ClockGuard` and its offset, for one engine.
class ClockGuard {
  ClockGuard({
    required this.raw,
    required this.mono,
    required this.newestRecord,
    required this.getSetting,
    required this.setSetting,
    this.releaseDate = clockReleaseDateS,
  }) {
    _refWall = now();
    _refMono = mono();
  }

  /// The system clock, in seconds since 1970.
  final double Function() raw;

  /// Monotonic seconds (the engine's clock).
  final double Function() mono;

  /// The store's newest timestamp (read once).
  final double Function() newestRecord;

  /// The store's settings.
  final String? Function(String key) getSetting;
  final void Function(String key, String value) setSetting;
  final int releaseDate;

  double _offset = 0;
  late double _refWall, _refMono;
  double? _holdUntil;
  double _highStored = 0;
  double? _hw;
  double? _records;
  bool? _wasOk;

  /// The last jump of the wall clock: {at, seconds}.
  Map<String, Object?>? lastJump;

  /// When a GM last set it (by the corrected clock).
  double? setAt;

  /// Seconds since 1970 by the controller's wall clock (the system clock
  /// plus the GM's correction).
  double now() => raw() + _offset;

  /// The GM's correction, in seconds.
  double get offset => _offset;

  // --- what the clock should at least say ----------------------------------

  double highWater() {
    return _hw ??= double.tryParse(getSetting(clockHighWaterKey) ?? '') ?? 0;
  }

  /// The earliest time this clock can honestly show, and what it comes
  /// from ("release", "high_water" or "records").
  (double, String) floor() {
    // Later records are our own clock: the high-water mark.
    final records = _records ??= newestRecord();
    var best = releaseDate.toDouble();
    var why = 'release';
    for (final (value, name) in [
      (highWater(), 'high_water'),
      (records, 'records'),
    ]) {
      if (value > best) {
        best = value;
        why = name;
      }
    }
    return (best, why);
  }

  bool plausible() => now() >= floor().$1 - clockToleranceS;

  /// GET /api/v1/clock, and `clock` in the status.
  Map<String, Object?> status() {
    final (fl, why) = floor();
    final nowS = now();
    final ok = nowS >= fl - clockToleranceS;
    final hold = _holdUntil != null && mono() < _holdUntil!;
    return {
      'ok': ok,
      'now': _round3(nowS),
      'floor': _round3(fl),
      'reason': ok
          ? null
          : (why == 'release' ? 'before_release' : 'behind_records'),
      'offset_s': _round3(_offset),
      'set_at': setAt,
      'purge_held': hold || !ok,
      'last_jump': lastJump == null ? null : {...lastJump!},
    };
  }

  // --- the tick ---------------------------------------------------------------

  void start() {
    final ok = status()['ok']! as bool;
    _wasOk = ok;
    if (ok) _storeHighWater();
  }

  /// Called every tick: sees a jump of the wall clock, stores the
  /// high-water mark.
  void tick() {
    final wall = now(), m = mono();
    final drift = (wall - _refWall) - (m - _refMono);
    _refWall = wall;
    _refMono = m;
    if (drift.abs() > clockJumpS) {
      lastJump = {'at': _round3(wall), 'seconds': (drift * 10).round() / 10};
      if (drift > clockBigJumpS) _holdUntil = m + clockPurgeHoldS;
    }
    final ok = plausible();
    if (ok != _wasOk) _wasOk = ok;
    if (ok) _storeHighWater();
  }

  void _storeHighWater() {
    final wall = now();
    if (wall > _highStored + clockHighWaterEveryS) {
      _highStored = wall;
      try {
        setSetting(clockHighWaterKey, '$wall');
        final hw = highWater();
        _hw = wall > hw ? wall : hw;
      } on Object {
        // A full disk must not stop the tick.
      }
    }
  }

  /// False while the clock is wrong or just jumped far forward: nothing is
  /// deleted by a wrong date.
  bool purgeAllowed() {
    final held = _holdUntil != null && mono() < _holdUntil!;
    return plausible() && !held;
  }

  // --- the GM's correction ----------------------------------------------------

  /// Moves the controller's wall clock forward to [epoch] (a GM's device
  /// clock). Refused: not a number, below the floor, not forward, or
  /// absurdly far ahead.
  /// Throws [ClockError] unless [now] may stamp a field-wide RELEASE
  /// (wallclock.py `release_check`, decision RLB-4). Its bound is a clock
  /// the controller can vouch for, plus [clockReleaseSlackS]: the GM's
  /// device clock when the request carries it ([deviceTime], the console
  /// sends it), else the system clock without the GM's correction. A phone
  /// whose own clock was set ahead by hand is caught only by a console on
  /// another device.
  void releaseCheck([Object? deviceTime]) {
    if (!plausible()) {
      throw ClockError(
        'not_set',
        "the controller's clock is not set: set it first, so that the boxes "
            'can tell this RELEASE from an older one',
      );
    }
    final nowS = now();
    if (deviceTime != null) {
      if (deviceTime is! num || deviceTime.isNaN || deviceTime.isInfinite) {
        throw ClockError(
          'invalid',
          'device_time: seconds since 1970 as a number',
          status: 400,
        );
      }
      if (nowS > deviceTime + clockReleaseSlackS) {
        throw ClockError(
          'ahead_of_device',
          "the controller's clock (${_iso(nowS)}) is ahead of this device's "
              '(${_iso(deviceTime.toDouble())}): a RELEASE stamped with it '
              'would stay valid too long. Restart the controller to drop the '
              "correction, or set this device's clock",
        );
      }
      return;
    }
    if (_offset > clockReleaseSlackS) {
      throw ClockError(
        'unconfirmed',
        "the controller's clock was moved ${_offset.toStringAsFixed(0)} s "
            'forward and no device confirmed it: send the RELEASE from the '
            "console (it sends its device's clock)",
      );
    }
  }

  Map<String, Object?> set(Object? epoch) {
    if (epoch is! num || epoch.isNaN || epoch.isInfinite) {
      throw ClockError(
        'invalid',
        'epoch: seconds since 1970 as a number',
        status: 400,
      );
    }
    final (fl, _) = floor();
    final nowS = now();
    if (epoch < fl - clockToleranceS) {
      throw ClockError(
        'below_floor',
        '${_iso(epoch.toDouble())} is earlier than ${_iso(fl)}: this '
            "device's clock is wrong too, or the controller has seen a later "
            'time',
      );
    }
    if (epoch < nowS - clockToleranceS) {
      throw ClockError(
        'backwards',
        'the clock only moves forward: a backward move would revive expired '
            'tokens and certificates',
      );
    }
    final limit = nowS < fl - clockToleranceS
        ? fl + clockSetMaxAheadFloorS
        : nowS + clockSetMaxAheadNowS;
    if (epoch > limit) {
      throw ClockError(
        'too_far',
        "${_iso(epoch.toDouble())} is too far ahead of the controller's clock",
      );
    }
    final step = epoch.toDouble() - now();
    if (step > 0) _offset += step;
    // Not a jump: it was asked for.
    _refWall = now();
    _refMono = mono();
    setAt = now();
    _holdUntil = null;
    lastJump = null;
    _highStored = 0;
    _wasOk = null;
    tick();
    return status();
  }

  /// Drops the correction (tests).
  void reset() => _offset = 0;
}

double _round3(double v) => (v * 1000).round() / 1000;

String _iso(double epoch) {
  final t = DateTime.fromMillisecondsSinceEpoch(
    (epoch < 0 ? 0 : epoch * 1000).round(),
    isUtc: true,
  );
  return '${t.toIso8601String().split('.').first}Z';
}
