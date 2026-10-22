// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the app asks of the phone, as Dart interfaces. On Android each is a
/// small Kotlin plugin in android/app/src/main/kotlin/org/atalaia/app/
/// reached over a platform channel (channels.dart); tests use fakes
/// (test/support/fakes.dart). Where a plugin does not exist (iOS, which has
/// no Kotlin plugins and whose runner is not in the repository yet:
/// decision PD10), the channel implementations answer "not available"
/// instead of throwing, so the roles iOS keeps still work.
library;

import 'dart:typed_data';

/// The phone's own hardware and settings: vibration, sounds, the screen,
/// battery optimisation and where the app may keep its files.
abstract interface class DeviceServices {
  /// The app's private folder (Android's Context.filesDir), or null.
  Future<String?> filesDir();

  /// The maker, as Build.MANUFACTURER says it (lower case), or "".
  Future<String> manufacturer();

  /// What the phone has, for the prop's capabilities (capability_mapper.dart).
  Future<DeviceFeatures> features();

  /// Vibrates: [pattern] alternates off and on times in ms, starting with off.
  Future<void> vibrate(List<int> pattern);

  /// Plays one of the phone's tones (ToneGenerator) for [ms].
  Future<void> tone(DeviceTone tone, int ms);

  /// FLAG_KEEP_SCREEN_ON on the app's window.
  Future<void> keepScreenOn(bool on);

  /// The window's brightness, 0-1, or null for the system's.
  Future<void> setBrightness(double? level);

  /// Whether Android exempts the app from battery optimisation.
  Future<bool> ignoringBatteryOptimizations();

  /// Asks once for the exemption (ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).
  Future<void> requestIgnoreBatteryOptimizations();

  /// Opens the system's battery optimisation settings.
  Future<void> openBatterySettings();

  /// Asks for a runtime permission (Android's names without the prefix:
  /// CAMERA, POST_NOTIFICATIONS, BLUETOOTH_CONNECT...); true if granted.
  Future<bool> requestPermission(String name);
}

enum DeviceTone { beep, ack, alarm, warning, success }

final class DeviceFeatures {
  const DeviceFeatures({
    this.nfc = false,
    this.nfcEnabled = false,
    this.camera = false,
    this.location = false,
    this.vibrator = false,
    this.accelerometer = false,
    this.bluetoothLe = false,
    this.usbHost = false,
    this.touchscreen = true,
  });

  final bool nfc;
  final bool nfcEnabled;
  final bool camera;
  final bool location;
  final bool vibrator;
  final bool accelerometer;
  final bool bluetoothLe;
  final bool usbHost;
  final bool touchscreen;

  static DeviceFeatures fromMap(Map<Object?, Object?> m) => DeviceFeatures(
    nfc: m['nfc'] == true,
    nfcEnabled: m['nfc_enabled'] == true,
    camera: m['camera'] == true,
    location: m['location'] == true,
    vibrator: m['vibrator'] == true,
    accelerometer: m['accelerometer'] == true,
    bluetoothLe: m['bluetooth_le'] == true,
    usbHost: m['usb_host'] == true,
    touchscreen: m['touchscreen'] != false,
  );
}

/// Kiosk mode (ADR-P3-5, ADR-P3-9): Android's lock task. As device owner the
/// app pins itself silently; otherwise Android asks the user to confirm
/// screen pinning.
abstract interface class KioskService {
  Future<bool> start();
  Future<void> stop();

  /// Whether lock task mode is active now (the tamper check polls this).
  Future<bool> isActive();

  /// Whether the app is the device owner (lock task without confirmation).
  Future<bool> isDeviceOwner();
}

/// The prop's foreground service (ADR-P3-5): keeps the process and the CPU
/// running (partial wake lock, Wi-Fi lock) with a persistent notification
/// while a game runs.
abstract interface class ForegroundService {
  /// [location]: a player sharing their position (the service's location
  /// type, so fixes go on with the screen off; ADR-P3-6).
  Future<bool> start({
    required String title,
    required String text,
    bool location = false,
  });
  Future<void> update({required String title, required String text});
  Future<void> stop();
}

/// A tag the NFC reader saw: its UID and, if it holds one, its NDEF message.
final class NfcRead {
  const NfcRead({required this.uid, this.ndef, this.writable = false});

  final Uint8List uid;

  /// The whole NDEF message (the records), or null.
  final Uint8List? ndef;
  final bool writable;
}

enum NfcState { unavailable, off, ready }

/// NFC in reader mode while a screen that wants tags is open (ADR-P3-10:
/// foreground only).
abstract interface class NfcService {
  Future<NfcState> state();

  /// Tags read while listening.
  Stream<NfcRead> get reads;

  Future<void> startReading();
  Future<void> stopReading();

  /// Writes [ndefMessage] to the next tag held to the phone; resolves to the
  /// tag's UID, or throws [NfcWriteException].
  Future<Uint8List> writeNext(Uint8List ndefMessage);

  /// Stops waiting for a tag to write.
  Future<void> cancelWrite();
}

class NfcWriteException implements Exception {
  NfcWriteException(this.reason);

  /// not_ndef, read_only, too_small, io, cancelled, unavailable
  final String reason;

  @override
  String toString() => 'NfcWriteException($reason)';
}

/// The camera QR scanner (CameraX and ZXing on Android: no Google Play
/// services, decision PD5).
abstract interface class QrScanner {
  Future<bool> get available;

  /// Scans one QR code; null if the user cancels. [hint] is shown under the
  /// camera picture.
  Future<String?> scan({required String hint, required String cancel});
}

/// The field's Wi-Fi for a phone that is the field controller (slice S6 of
/// PE24; FieldWifiPlugin.kt): what network the phone is on, its hotspot,
/// Android's settings for both, and a local-only hotspot the app starts
/// itself (a network of its own whose name and password Android chooses,
/// with no internet, gone when the app lets it go).
abstract interface class FieldWifiService {
  Future<FieldWifiInfo> info();

  /// Opens Android's hotspot (tethering) settings; false when it cannot.
  Future<bool> openHotspotSettings();

  /// Opens Android's Wi-Fi settings; false when it cannot.
  Future<bool> openWifiSettings();

  /// Starts a local-only hotspot, or says why Android refused
  /// ([LocalHotspot.error]).
  Future<LocalHotspot> startLocalHotspot();
  Future<void> stopLocalHotspot();
}

enum HotspotState { on, off, unknown }

final class FieldWifiInfo {
  const FieldWifiInfo({
    this.available = false,
    this.wifiEnabled = false,
    this.ssid,
    this.hotspot = HotspotState.unknown,
    this.localHotspot,
  });

  /// The plugin answered (false: iOS, a test without a fake).
  final bool available;
  final bool wifiEnabled;

  /// The network the phone is on, when Android tells (it needs location).
  final String? ssid;
  final HotspotState hotspot;

  /// The local-only hotspot the app holds now, if any.
  final LocalHotspot? localHotspot;

  static FieldWifiInfo fromMap(Map<Object?, Object?> m) {
    final ssid = m['ssid'];
    final local = m['local'];
    return FieldWifiInfo(
      available: m.isNotEmpty,
      wifiEnabled: m['wifi_enabled'] == true,
      ssid: ssid is String && ssid.isNotEmpty ? ssid : null,
      hotspot:
          HotspotState.values.asNameMap()[m['hotspot']] ?? HotspotState.unknown,
      localHotspot: local is Map ? LocalHotspot.fromMap(local) : null,
    );
  }
}

final class LocalHotspot {
  const LocalHotspot({this.ssid, this.passphrase, this.error});

  final String? ssid;
  final String? passphrase;

  /// Why it did not start: permission, location_off, incompatible_mode,
  /// tethering_disallowed, no_channel, generic, unavailable.
  final String? error;

  bool get started => ssid != null && error == null;

  /// The text of a Wi-Fi QR code (the "WIFI:" form phones' cameras read):
  /// players join the network by scanning it.
  String? get qrText {
    final s = ssid;
    if (s == null) return null;
    String esc(String v) {
      final out = StringBuffer();
      for (final c in v.split('')) {
        if (r'\;,:"'.contains(c)) out.write(r'\');
        out.write(c);
      }
      return out.toString();
    }

    final p = passphrase;
    return p == null || p.isEmpty
        ? 'WIFI:T:nopass;S:${esc(s)};;'
        : 'WIFI:T:WPA;S:${esc(s)};P:${esc(p)};;';
  }

  static LocalHotspot fromMap(Map<Object?, Object?> m) => LocalHotspot(
    ssid: m['ssid'] as String?,
    passphrase: m['passphrase'] as String?,
    error: m['error'] as String?,
  );
}
