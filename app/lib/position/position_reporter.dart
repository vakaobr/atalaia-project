// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Position reports while a player shares their position (ADR-P3-6): the
/// phone's fixes, sent to the field controller every [interval] (the
/// controller says how often; 10 s by default), at most 5 per request. The
/// controller decides who sees them; the phone keeps nothing. Stops by
/// itself when the controller says the game is not running (409) or the
/// token is no longer valid (401).
///
/// Indoors, with a field that has iBeacons (decisions BLE-1 to BLE-9): the
/// [beacons] scanner reports the strongest registered beacon every beacon
/// interval (5 s by default; 3 to 30), and a phone that has heard one in the
/// last two intervals is indoors: its GPS fixes, which a building leaves
/// stale or far off, are not sent, and the beacon is its position (the
/// controller shows the room). Two intervals without a beacon and the GPS
/// fixes go on as before. The controller keeps the latest report of either
/// source, so the two never need merging on the phone.
///
/// On a field with levels the player says which floor they are on (decision
/// ML-5, PM-1): the GPS reports then carry that `level` (null: "not sure",
/// said explicitly) and, until the player says anything, none (the
/// controller keeps the level they last gave). A beacon report never carries
/// one: the beacon's own level, which the controller knows, wins (PM-2).
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../checkin/checkin_client.dart';
import '../platform/location.dart';
import 'beacon_scanner.dart';

typedef SendReports =
    Future<Map<String, Object?>> Function(List<Map<String, Object?>> reports);

class PositionReporter extends ChangeNotifier {
  PositionReporter({
    required this.location,
    required this.send,
    this.interval = const Duration(seconds: 10),
    this.onFix,
    this.beacons,
    DateTime Function()? now,
  }) : _now = now ?? DateTime.now {
    beacons?.addListener(_onScanner);
  }

  final LocationService location;
  final SendReports send;
  Duration interval;

  /// The indoor beacons' scanner, when the field has beacons and the phone
  /// may scan (null: GPS only).
  BeaconScanner? beacons;
  final DateTime Function() _now;
  bool _scanning = false;

  /// A scanner for a field whose first beacon was registered after the
  /// sharing began (BLE-20); the reporter owns it from here.
  void attachBeacons(BeaconScanner scanner) {
    if (beacons != null) return;
    beacons = scanner;
    scanner.addListener(_onScanner);
    if (running) {
      _beaconSub = scanner.readings.listen(_onBeacon);
      scanner.start();
      _retime();
    }
  }

  /// The radio went on or off (a registry change): the period follows.
  void _onScanner() {
    final on = beacons?.running ?? false;
    if (on == _scanning) return;
    _scanning = on;
    if (running) _retime();
  }

  /// Each fix as it arrives, for the out-of-bounds warning (field_bounds.dart,
  /// decision MF-31): the same fixes the reports carry, no extra GPS.
  void Function(LocationFix fix)? onFix;

  StreamSubscription<LocationFix>? _sub;
  StreamSubscription<BeaconReading>? _beaconSub;
  Timer? _timer;
  final _pending = <LocationFix>[];
  BeaconReading? _pendingBeacon;
  DateTime? _beaconAt;
  LocationFix? _lastFix;
  int? _level;
  bool _levelGiven = false;
  bool get running => _sub != null;

  /// The floor the player chose (null: "not sure" once [levelGiven]).
  int? get level => _level;

  /// Whether the player has said anything about their floor yet: until then
  /// no report carries a level.
  bool get levelGiven => _levelGiven;

  /// The player's floor (null: not sure). The next GPS reports carry it, and
  /// the last fix goes again now, so the controller (and the team) learn it
  /// at once; indoors the beacon's level stays the position's (PM-2).
  void setLevel(int? level) {
    _level = level;
    _levelGiven = true;
    final f = _lastFix;
    if (running && !indoors && f != null) {
      if (!_pending.contains(f)) _pending.add(f);
      unawaited(flush());
    }
    notifyListeners();
  }

  /// Whether a registered beacon was heard in the last two beacon intervals:
  /// the phone is indoors, and the beacon is its position.
  bool get indoors {
    final b = beacons, at = _beaconAt;
    return b != null && at != null && _now().difference(at) <= b.window * 2;
  }

  /// The room's beacon the phone last reported (null: none, or outdoors).
  String? get beaconId => indoors ? beacons?.latest?.beaconId : null;

  /// Reports the controller stored.
  int sent = 0;
  String? stopReason;

  /// How often the pending reports go: the GPS interval, or the beacon
  /// interval when that is shorter and beacons are being listened for.
  Duration get _period {
    final b = beacons;
    return b != null && b.running && b.window < interval ? b.window : interval;
  }

  void _retime() {
    _timer?.cancel();
    _timer = Timer.periodic(_period, (_) => unawaited(flush()));
  }

  void start() {
    if (running) return;
    stopReason = null;
    _sub = location
        .fixes(interval)
        .listen(_onFix, onError: (Object e) => stop('$e'));
    final b = beacons;
    if (b != null) {
      _beaconSub = b.readings.listen(_onBeacon);
      b.start();
      _scanning = b.running;
    }
    _retime();
    notifyListeners();
  }

  void _onFix(LocationFix f) {
    onFix?.call(f);
    _lastFix = f;
    if (indoors) return; // a beacon is the position now (BLE-4)
    _pending.add(f);
    if (_pending.length > 5) _pending.removeAt(0);
  }

  void _onBeacon(BeaconReading r) {
    _beaconAt = _now();
    _pendingBeacon = r;
    notifyListeners();
  }

  /// Sends what is waiting (tests call it directly).
  Future<void> flush() async {
    final beacon = _pendingBeacon;
    if (_pending.isEmpty && beacon == null) return;
    _pendingBeacon = null;
    final batch = List.of(_pending);
    _pending.clear();
    final reports = [
      for (final f in batch)
        {...f.toReport(), if (_levelGiven) 'level': _level},
      if (beacon != null) beacon.toReport(),
    ];
    // At most 5 a request: the oldest fixes give way to the beacon.
    final kept = reports.length > 5
        ? reports.sublist(reports.length - 5)
        : reports;
    try {
      final out = await send(kept);
      sent += kept.length;
      final s = out['interval_s'];
      var retime = false;
      if (s is int && s >= 5 && s <= 60 && s != interval.inSeconds) {
        interval = Duration(seconds: s);
        retime = true;
      }
      final ble = out['ble_interval_s'];
      if (ble is int &&
          ble >= bleIntervalMin.inSeconds &&
          ble <= bleIntervalMax.inSeconds &&
          ble != beacons?.window.inSeconds) {
        beacons?.setWindow(Duration(seconds: ble));
        retime = true;
      }
      if (retime) _retime();
      notifyListeners();
    } on CheckinException catch (e) {
      if (e.status == 409 || e.status == 401 || e.status == 403) {
        stop(e.message);
      } else {
        _pending.insertAll(0, batch.take(5 - _pending.length));
        _pendingBeacon ??= beacon;
      }
    }
  }

  void stop([String? reason]) {
    unawaited(_sub?.cancel());
    _sub = null;
    unawaited(_beaconSub?.cancel());
    _beaconSub = null;
    beacons?.stop();
    _timer?.cancel();
    _timer = null;
    _pending.clear();
    _pendingBeacon = null;
    _beaconAt = null;
    _lastFix = null;
    stopReason = reason;
    notifyListeners();
  }

  @override
  void dispose() {
    stop();
    beacons?.removeListener(_onScanner);
    beacons?.dispose(); // the reporter owns its scanner
    super.dispose();
  }
}
