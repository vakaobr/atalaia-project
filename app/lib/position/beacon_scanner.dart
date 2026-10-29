// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Indoor positions from iBeacons (ADR-P3-6, decisions BLE-1 to BLE-9): the
/// strongest beacon of the field's registry the phone hears, as a position
/// report with `source: ble` and its `beacon_id` (major:minor). The controller
/// turns that into the room, zone and level (beacons.py), so the phone never
/// says more than which beacon.
///
/// The rules, from the ADR and its privacy section:
///
///   - only a registered beacon is ever reported: the registry is the list
///     the controller gave this player (each beacon's id and UUID); an
///     iBeacon of anything else is dropped here and, by the radio's UUID
///     filter, before this code sees it. Nothing heard is kept: the latest
///     reading is replaced by the next, and [stop] forgets it;
///   - the strongest one only, by the window's average signal strength, and
///     only above [minRssi] (a beacon through two walls is not the room the
///     player is in); no triangulation;
///   - one reading per window, the window being the game's beacon interval
///     (5 s by default, 3 to 30: [bleIntervalMin], [bleIntervalMax]);
///   - it runs only while the player shares their position in a running game
///     (PositionReporter starts and stops it), never in the background
///     without the foreground service's notification.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';

import '../platform/beacon_scan.dart';

/// The shortest and longest beacon interval the controller may set (ADR-P3-6).
const bleIntervalMin = Duration(seconds: 3);
const bleIntervalMax = Duration(seconds: 30);
const bleIntervalDefault = Duration(seconds: 5);

/// How long the phone waits after the stream says the registry changed before
/// it reads it again (BLE-20): a GM registering several tags is one read.
const beaconsRereadDelay = Duration(seconds: 2);

/// Weaker than this (dBm) is too far away to say the player is in the beacon's
/// room.
const bleMinRssi = -95;

/// A beacon of the field's registry, as the controller lists it for a player.
final class RegisteredBeacon {
  const RegisteredBeacon({
    required this.uuid,
    required this.major,
    required this.minor,
  });

  /// Upper case, 8-4-4-4-12.
  final String uuid;
  final int major;
  final int minor;

  String get id => '$major:$minor';

  /// From the controller's `{"id": "1:2", "uuid": "..."}`, or null.
  static RegisteredBeacon? fromApi(Object? m) {
    if (m is! Map) return null;
    final id = m['id'], uuid = m['uuid'];
    if (id is! String || uuid is! String) return null;
    final parts = id.split(':');
    if (parts.length != 2) return null;
    final major = int.tryParse(parts[0]), minor = int.tryParse(parts[1]);
    if (major == null ||
        minor == null ||
        major < 0 ||
        major > 65535 ||
        minor < 0 ||
        minor > 65535) {
      return null;
    }
    return RegisteredBeacon(
      uuid: uuid.toUpperCase(),
      major: major,
      minor: minor,
    );
  }
}

/// The beacon heard, as a position report's fields.
final class BeaconReading {
  const BeaconReading({
    required this.beaconId,
    required this.rssi,
    required this.tMs,
  });

  final String beaconId;
  final int rssi;

  /// Unix milliseconds.
  final int tMs;

  /// A position report's own fields (POST /api/v1/positions): the controller
  /// adds the player, team and squad from the token, and the room from its
  /// registry.
  Map<String, Object?> toReport() => {
    'source': 'ble',
    'beacon_id': beaconId,
    't': tMs,
  };
}

/// The interval the controller said, kept within the ADR's range.
Duration clampBleInterval(Duration d) => d < bleIntervalMin
    ? bleIntervalMin
    : d > bleIntervalMax
    ? bleIntervalMax
    : d;

class BeaconScanner extends ChangeNotifier {
  BeaconScanner({
    required this.service,
    required List<RegisteredBeacon> registry,
    Duration window = bleIntervalDefault,
    this.minRssi = bleMinRssi,
  }) : _registry = {for (final b in registry) b.id: b},
       _window = clampBleInterval(window);

  final BeaconScanService service;
  final int minRssi;
  Map<String, RegisteredBeacon> _registry;
  Duration _window;
  StreamSubscription<BeaconWindow>? _sub;

  /// Whether [start] was called and [stop] has not been since: a scanner with
  /// an empty registry waits for a beacon to be registered (BLE-20).
  bool _wanted = false;

  /// The window's length: how often a reading may come.
  Duration get window => _window;

  /// Whether it is listening.
  bool get running => _sub != null;

  /// Which registered beacons are listened for.
  List<RegisteredBeacon> get registry => _registry.values.toList();

  /// The latest window's strongest registered beacon (null: none heard).
  BeaconReading? latest;

  /// Each window's reading, when there is one.
  final _readings = StreamController<BeaconReading>.broadcast();
  Stream<BeaconReading> get readings => _readings.stream;

  /// The strongest registered beacon of [w] above [minRssi] (ties: more
  /// advertisements, then the lower id), or null.
  BeaconReading? strongest(BeaconWindow w) {
    BeaconSighting? best;
    for (final s in w.sightings) {
      final known = _registry[s.id];
      if (known == null || known.uuid != s.uuid || s.rssi < minRssi) continue;
      if (best == null ||
          s.rssi > best.rssi ||
          (s.rssi == best.rssi &&
              (s.count > best.count ||
                  (s.count == best.count && _before(s, best))))) {
        best = s;
      }
    }
    return best == null
        ? null
        : BeaconReading(beaconId: best.id, rssi: best.rssi, tMs: w.tMs);
  }

  static bool _before(BeaconSighting a, BeaconSighting b) =>
      a.major != b.major ? a.major < b.major : a.minor < b.minor;

  void start() {
    _wanted = true;
    if (running || _registry.isEmpty) return;
    _listen();
    notifyListeners();
  }

  /// The registry the controller gives now (BLE-20: a tag or a box was added,
  /// moved or removed during the game). The scan restarts, through the same
  /// call, only when the UUIDs to listen for changed; a changed id or room
  /// alone costs nothing. An empty registry stops the radio but keeps the
  /// scanner, which listens again when a beacon is registered. Returns
  /// whether the radio was (re)started or stopped.
  bool update(List<RegisteredBeacon> registry) {
    final before = _uuids();
    _registry = {for (final b in registry) b.id: b};
    if (!_wanted) return false;
    final after = _uuids();
    if (after.isEmpty) {
      if (!running) return false;
      unawaited(_sub?.cancel());
      _sub = null;
      latest = null;
      notifyListeners();
      return true;
    }
    if (running && listEquals(before, after)) return false;
    unawaited(_sub?.cancel());
    _listen();
    notifyListeners();
    return true;
  }

  /// The distinct UUIDs of the registry, sorted: what the radio filters on.
  List<String> _uuids() =>
      {for (final b in _registry.values) b.uuid}.toList()..sort();

  void _listen() {
    _sub = service
        .windows(_uuids(), _window)
        .listen(_onWindow, onError: (Object _) => stop());
  }

  void _onWindow(BeaconWindow w) {
    final r = strongest(w);
    latest = r;
    if (r != null) _readings.add(r);
    notifyListeners();
  }

  /// A new interval from the controller: the scan restarts with it.
  void setWindow(Duration d) {
    final next = clampBleInterval(d);
    if (next == _window) return;
    _window = next;
    if (running) {
      unawaited(_sub?.cancel());
      _listen();
    }
  }

  void stop() {
    _wanted = false;
    final was = running;
    unawaited(_sub?.cancel());
    _sub = null;
    latest = null; // nothing heard is kept
    if (was) notifyListeners();
  }

  @override
  void dispose() {
    stop();
    unawaited(_readings.close());
    super.dispose();
  }
}
