// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The platform-channel side of services.dart: each class talks to one
/// Kotlin plugin (android/app/src/main/kotlin/org/atalaia/app/) and, for the
/// device, QR, links and location channels, to its Swift twin on iOS
/// (ios/Runner/, decisions iOS-3, iOS-13 to iOS-15). A missing plugin (the
/// web, a widget test, NFC and the rest on iOS) means "not available", never
/// a crash.
library;

import 'dart:async';

import 'package:flutter/services.dart';

import '../storage/secret_vault.dart';
import 'services.dart';

const _prefix = 'org.atalaia.app';

Future<T> _call<T>(
  MethodChannel channel,
  String method,
  T fallback, [
  Object? args,
]) async {
  try {
    final r = await channel.invokeMethod<Object?>(method, args);
    return r is T ? r : fallback;
  } on MissingPluginException {
    return fallback;
  }
}

class ChannelDeviceServices implements DeviceServices {
  static const _ch = MethodChannel('$_prefix/device');

  @override
  Future<String?> filesDir() => _call<String?>(_ch, 'filesDir', null);

  @override
  Future<String> manufacturer() => _call<String>(_ch, 'manufacturer', '');

  @override
  Future<DeviceFeatures> features() async {
    final m = await _call<Map<Object?, Object?>>(_ch, 'features', const {});
    return DeviceFeatures.fromMap(m);
  }

  @override
  Future<void> vibrate(List<int> pattern) =>
      _call<void>(_ch, 'vibrate', null, {'pattern': pattern});

  @override
  Future<void> tone(DeviceTone tone, int ms) =>
      _call<void>(_ch, 'tone', null, {'tone': tone.name, 'ms': ms});

  @override
  Future<void> keepScreenOn(bool on) =>
      _call<void>(_ch, 'keepScreenOn', null, {'on': on});

  @override
  Future<void> setBrightness(double? level) =>
      _call<void>(_ch, 'setBrightness', null, {'level': level});

  @override
  Future<bool> ignoringBatteryOptimizations() =>
      _call<bool>(_ch, 'ignoringBatteryOptimizations', true);

  @override
  Future<void> requestIgnoreBatteryOptimizations() =>
      _call<void>(_ch, 'requestIgnoreBatteryOptimizations', null);

  @override
  Future<void> openBatterySettings() =>
      _call<void>(_ch, 'openBatterySettings', null);

  @override
  Future<bool> requestPermission(String name) =>
      _call<bool>(_ch, 'requestPermission', false, {'name': name});
}

class ChannelKioskService implements KioskService {
  static const _ch = MethodChannel('$_prefix/kiosk');

  @override
  Future<bool> start() => _call<bool>(_ch, 'start', false);

  @override
  Future<void> stop() => _call<void>(_ch, 'stop', null);

  @override
  Future<bool> isActive() => _call<bool>(_ch, 'isActive', false);

  @override
  Future<bool> isDeviceOwner() => _call<bool>(_ch, 'isDeviceOwner', false);
}

class ChannelForegroundService implements ForegroundService {
  static const _ch = MethodChannel('$_prefix/foreground');

  @override
  Future<bool> start({
    required String title,
    required String text,
    bool location = false,
  }) => _call<bool>(_ch, 'start', false, {
    'title': title,
    'text': text,
    'location': location,
  });

  @override
  Future<void> update({required String title, required String text}) =>
      _call<void>(_ch, 'update', null, {'title': title, 'text': text});

  @override
  Future<void> stop() => _call<void>(_ch, 'stop', null);
}

class ChannelFieldWifi implements FieldWifiService {
  static const _ch = MethodChannel('$_prefix/wifi');

  @override
  Future<FieldWifiInfo> info() async {
    final m = await _call<Map<Object?, Object?>>(_ch, 'info', const {});
    return FieldWifiInfo.fromMap(m);
  }

  @override
  Future<bool> openHotspotSettings() =>
      _call<bool>(_ch, 'openHotspotSettings', false);

  @override
  Future<bool> openWifiSettings() =>
      _call<bool>(_ch, 'openWifiSettings', false);

  @override
  Future<LocalHotspot> startLocalHotspot() async {
    try {
      final m = await _call<Map<Object?, Object?>>(
        _ch,
        'startLocalHotspot',
        const {'error': 'unavailable'},
      );
      return LocalHotspot.fromMap(m);
    } on PlatformException catch (e) {
      return LocalHotspot(error: e.code);
    }
  }

  @override
  Future<void> stopLocalHotspot() => _call<void>(_ch, 'stopLocalHotspot', null);
}

class ChannelNfcService implements NfcService {
  static const _ch = MethodChannel('$_prefix/nfc');
  static const _events = EventChannel('$_prefix/nfc/reads');

  Stream<NfcRead>? _reads;

  @override
  Future<NfcState> state() async {
    final s = await _call<String>(_ch, 'state', 'unavailable');
    return NfcState.values.asNameMap()[s] ?? NfcState.unavailable;
  }

  @override
  Stream<NfcRead> get reads => _reads ??= _events
      .receiveBroadcastStream()
      .handleError((Object _) {}, test: (e) => e is MissingPluginException)
      .map((e) {
        final m = e as Map<Object?, Object?>;
        return NfcRead(
          uid: m['uid']! as Uint8List,
          ndef: m['ndef'] as Uint8List?,
          writable: m['writable'] == true,
        );
      })
      .asBroadcastStream();

  @override
  Future<void> startReading() => _call<void>(_ch, 'startReading', null);

  @override
  Future<void> stopReading() => _call<void>(_ch, 'stopReading', null);

  @override
  Future<Uint8List> writeNext(Uint8List ndefMessage) async {
    try {
      final uid = await _ch.invokeMethod<Uint8List>('writeNext', {
        'ndef': ndefMessage,
      });
      if (uid == null) throw NfcWriteException('io');
      return uid;
    } on MissingPluginException {
      throw NfcWriteException('unavailable');
    } on PlatformException catch (e) {
      throw NfcWriteException(e.code);
    }
  }

  @override
  Future<void> cancelWrite() => _call<void>(_ch, 'cancelWrite', null);
}

/// QrScanPlugin.kt on Android, QrScanPlugin.swift on iOS. "scan" answers the
/// text of the first code, or null for a cancel, a refused camera or no camera.
class ChannelQrScanner implements QrScanner {
  static const _ch = MethodChannel('$_prefix/qr');

  @override
  Future<bool> get available => _call<bool>(_ch, 'available', false);

  @override
  Future<String?> scan({required String hint, required String cancel}) =>
      _call<String?>(_ch, 'scan', null, {'hint': hint, 'cancel': cancel});
}

/// ShareFilePlugin.kt on Android; no twin on iOS yet, where "not available"
/// is the answer and the label screen is what the player has.
class ChannelFileSharer implements FileSharer {
  static const _ch = MethodChannel('$_prefix/share');

  @override
  Future<bool> get available => _call<bool>(_ch, 'available', false);

  @override
  Future<bool> sharePng(List<SharedFile> files, {String title = ''}) =>
      _call<bool>(_ch, 'share', false, {
        'mime': 'image/png',
        'title': title,
        'files': [
          for (final f in files) {'name': f.name, 'bytes': f.bytes},
        ],
      });
}

/// The AndroidKeyStore's AES-GCM key (KeystorePlugin.kt). A missing plugin
/// (iOS, the web, a widget test) is "not available", never a crash.
class ChannelSecretVault implements SecretVault {
  static const _ch = MethodChannel('$_prefix/keystore');

  @override
  Future<bool> available() async {
    try {
      return await _call<bool>(_ch, 'available', false);
    } on PlatformException {
      return false;
    }
  }

  @override
  Future<Uint8List> seal(Uint8List plain) => _go('seal', plain);

  @override
  Future<Uint8List> open(Uint8List sealed) => _go('open', sealed);

  Future<Uint8List> _go(String method, Uint8List data) async {
    try {
      final r = await _ch.invokeMethod<Object?>(method, {'data': data});
      if (r is Uint8List) return r;
      throw const VaultException(VaultFailure.unavailable, 'no answer');
    } on MissingPluginException {
      throw const VaultException(VaultFailure.unavailable, 'no plugin');
    } on PlatformException catch (e) {
      throw VaultException(
        e.code == 'key_lost' ? VaultFailure.keyLost : VaultFailure.unavailable,
        '${e.code} ${e.message ?? ''}',
      );
    }
  }
}

/// BrowserPlugin.kt on Android (Custom Tabs). Not available elsewhere.
class ChannelAuthBrowser implements AuthBrowser {
  static const _ch = MethodChannel('$_prefix/browser');

  @override
  Future<bool> open(Uri url) async {
    if (url.scheme != 'https') return false;
    try {
      return await _call<bool>(_ch, 'open', false, {'url': '$url'});
    } on PlatformException {
      return false;
    }
  }
}

/// PasskeyPlugin.kt on Android (androidx.credentials). A missing plugin is
/// "not available".
class ChannelPasskeyService implements PasskeyService {
  static const _ch = MethodChannel('$_prefix/passkeys');

  @override
  Future<bool> available() async {
    try {
      return await _call<bool>(_ch, 'available', false);
    } on PlatformException {
      return false;
    }
  }

  @override
  Future<String> create(String optionsJson) => _go('create', optionsJson);

  @override
  Future<String> get(String optionsJson) => _go('get', optionsJson);

  Future<String> _go(String method, String optionsJson) async {
    try {
      final r = await _ch.invokeMethod<String>(method, {
        'request': optionsJson,
      });
      if (r == null) throw PasskeyException('failed');
      return r;
    } on MissingPluginException {
      throw PasskeyException('unsupported');
    } on PlatformException catch (e) {
      throw PasskeyException(e.code);
    }
  }
}
