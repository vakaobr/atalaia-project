// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The platform-channel side of services.dart: each class talks to one
/// Kotlin plugin (android/app/src/main/kotlin/org/atalaia/app/). A missing
/// plugin (iOS, the web, a widget test) means "not available", never a crash.
library;

import 'dart:async';

import 'package:flutter/services.dart';

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
  Future<bool> start({required String title, required String text}) =>
      _call<bool>(_ch, 'start', false, {'title': title, 'text': text});

  @override
  Future<void> update({required String title, required String text}) =>
      _call<void>(_ch, 'update', null, {'title': title, 'text': text});

  @override
  Future<void> stop() => _call<void>(_ch, 'stop', null);
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

class ChannelQrScanner implements QrScanner {
  static const _ch = MethodChannel('$_prefix/qr');

  @override
  Future<bool> get available => _call<bool>(_ch, 'available', false);

  @override
  Future<String?> scan({required String hint, required String cancel}) =>
      _call<String?>(_ch, 'scan', null, {'hint': hint, 'cancel': cancel});
}
