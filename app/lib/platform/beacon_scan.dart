// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The iBeacons the phone hears (ADR-P3-6, decisions BLE-1 to BLE-9): Android's
/// Bluetooth LE scanner through the app's Kotlin plugin (BeaconScanPlugin.kt;
/// no Google Play services), asked only for the UUIDs of the field's own
/// registry, so the radio's filter drops every other advertisement before the
/// app wakes. The plugin groups what it hears into one window of the length
/// the Dart side asks for (the game's beacon interval, 3 to 30 s) and sends
/// each beacon once per window, with its average signal strength. Used only
/// while a player chooses to share their position in a running game; nothing
/// is kept on the phone.
///
/// iOS has no plugin for this (decision BLE-9): `ChannelBeaconScanService`
/// answers "not available" there, as it does on any phone without the plugin,
/// and the position reports stay GPS.
library;

import 'dart:async';

import 'package:flutter/services.dart';

/// One beacon heard in a window.
final class BeaconSighting {
  const BeaconSighting({
    required this.uuid,
    required this.major,
    required this.minor,
    required this.rssi,
    this.count = 1,
  });

  /// Upper case, 8-4-4-4-12.
  final String uuid;
  final int major;
  final int minor;

  /// The average signal strength in the window, dBm (negative; nearer is
  /// higher).
  final int rssi;

  /// How many advertisements the average is over.
  final int count;

  String get id => '$major:$minor';

  static BeaconSighting? fromMap(Object? m) {
    if (m is! Map) return null;
    final uuid = m['uuid'], major = m['major'], minor = m['minor'];
    final rssi = m['rssi'], count = m['count'];
    if (uuid is! String ||
        major is! int ||
        minor is! int ||
        rssi is! num ||
        major < 0 ||
        major > 65535 ||
        minor < 0 ||
        minor > 65535) {
      return null;
    }
    return BeaconSighting(
      uuid: uuid.toUpperCase(),
      major: major,
      minor: minor,
      rssi: rssi.round(),
      count: count is int && count > 0 ? count : 1,
    );
  }
}

/// What one window of scanning heard (possibly nothing).
final class BeaconWindow {
  const BeaconWindow({required this.tMs, required this.sightings});

  /// Unix milliseconds at the window's end.
  final int tMs;
  final List<BeaconSighting> sightings;

  static BeaconWindow? fromMap(Object? m) {
    if (m is! Map) return null;
    final t = m['t'], list = m['beacons'];
    if (t is! num || list is! List) return null;
    return BeaconWindow(
      tMs: t.toInt(),
      sightings: [for (final b in list) ?BeaconSighting.fromMap(b)],
    );
  }
}

abstract interface class BeaconScanService {
  /// Whether the phone has Bluetooth LE.
  Future<bool> available();

  /// Whether the permissions a scan needs are granted (ask with
  /// DeviceServices.requestPermission('BLUETOOTH_SCAN'), which on Android
  /// also asks for the location a scan needs).
  Future<bool> granted();

  /// Whether Bluetooth is switched on.
  Future<bool> bluetoothOn();

  /// One [BeaconWindow] every [window] while listened to, for the beacons
  /// advertising one of [uuids] only.
  Stream<BeaconWindow> windows(List<String> uuids, Duration window);
}

class ChannelBeaconScanService implements BeaconScanService {
  static const _ch = MethodChannel('org.atalaia.app/beacons');
  static const _events = EventChannel('org.atalaia.app/beacons/sightings');

  Future<bool> _bool(String method) async {
    try {
      return await _ch.invokeMethod<bool>(method) ?? false;
    } on MissingPluginException {
      return false; // tests, iOS, or a phone without the plugin: not available
    } on PlatformException {
      return false;
    }
  }

  @override
  Future<bool> available() => _bool('available');

  @override
  Future<bool> granted() => _bool('granted');

  @override
  Future<bool> bluetoothOn() => _bool('enabled');

  @override
  Stream<BeaconWindow> windows(List<String> uuids, Duration window) => _events
      .receiveBroadcastStream({
        'uuids': uuids,
        'window_ms': window.inMilliseconds,
      })
      .map(BeaconWindow.fromMap)
      .where((w) => w != null)
      .cast<BeaconWindow>();
}
