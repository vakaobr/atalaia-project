// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The phone's position (ADR-P3-6): Android's own LocationManager through
/// the app's Kotlin plugin (LocationPlugin.kt; no Google Play services,
/// decision PD5). Used only while a player chooses to share their position
/// in a running game; nothing is kept on the phone.
library;

import 'dart:async';

import 'package:flutter/services.dart';

final class LocationFix {
  const LocationFix({
    required this.lat,
    required this.lon,
    this.accuracyM,
    this.altitudeM,
    this.headingDeg,
    this.speedMps,
    required this.tMs,
  });

  final double lat;
  final double lon;
  final double? accuracyM;
  final double? altitudeM;
  final double? headingDeg;
  final double? speedMps;

  /// Unix milliseconds.
  final int tMs;

  static LocationFix? fromMap(Object? m) {
    if (m is! Map) return null;
    double? d(String k) => (m[k] as num?)?.toDouble();
    final lat = d('lat');
    final lon = d('lon');
    if (lat == null || lon == null) return null;
    return LocationFix(
      lat: lat,
      lon: lon,
      accuracyM: d('accuracy_m'),
      altitudeM: d('altitude_m'),
      headingDeg: d('heading_deg'),
      speedMps: d('speed_mps'),
      tMs: (m['t'] as num?)?.toInt() ?? 0,
    );
  }

  /// A position report's own fields (POST /api/v1/positions): the controller
  /// adds the player, team and squad from the token.
  Map<String, Object?> toReport() => {
    'source': 'gps',
    'lat': lat,
    'lon': lon,
    if (accuracyM != null) 'accuracy_m': accuracyM!.clamp(0, 10000),
    if (altitudeM != null && altitudeM! >= -1000 && altitudeM! <= 10000)
      'altitude_m': altitudeM,
    if (headingDeg != null && headingDeg! >= 0 && headingDeg! <= 360)
      'heading_deg': headingDeg,
    if (speedMps != null && speedMps! >= 0 && speedMps! <= 200)
      'speed_mps': speedMps,
    't': tMs,
  };
}

abstract interface class LocationService {
  /// Whether the phone has a location provider.
  Future<bool> available();

  /// Whether the location permission is granted (ask with
  /// DeviceServices.requestPermission('ACCESS_FINE_LOCATION')).
  Future<bool> granted();

  /// Fixes about every [interval] while listened to.
  Stream<LocationFix> fixes(Duration interval);
}

class ChannelLocationService implements LocationService {
  static const _ch = MethodChannel('org.atalaia.app/location');
  static const _events = EventChannel('org.atalaia.app/location/fixes');

  Future<bool> _bool(String method) async {
    try {
      return await _ch.invokeMethod<bool>(method) ?? false;
    } on MissingPluginException {
      return false; // iOS and tests: not available
    } on PlatformException {
      return false;
    }
  }

  @override
  Future<bool> available() => _bool('available');

  @override
  Future<bool> granted() => _bool('granted');

  @override
  Stream<LocationFix> fixes(Duration interval) => _events
      .receiveBroadcastStream({'interval_ms': interval.inMilliseconds})
      .map(LocationFix.fromMap)
      .where((f) => f != null)
      .cast<LocationFix>();
}
