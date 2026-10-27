// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// On an Android device or emulator: the indoor iBeacon scan's plugin
// (BeaconScanPlugin.kt, decisions BLE-1 to BLE-9) is compiled into the APK,
// registered on its channel, and answers its three questions with booleans
// whatever the hardware is. What it cannot test here is a real beacon: the
// emulator has no Bluetooth LE radio to hear one (its adapter is absent or
// off, so `available` or `enabled` is false) and no beacon to put in front of
// it, so the scan itself, the strongest beacon and the position reports are
// tested with a fake scan channel in test/position/beacon_scanner_test.dart,
// and are still to be run on a phone with real beacons. On iOS there is no
// plugin by design (the position stays GPS), and the service says "not
// available".

import 'package:atalaia_app/platform/beacon_scan.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'support.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  group('on Android', () {
    testWidgets('the plugin is registered and answers with booleans', (
      _,
    ) async {
      const channel = MethodChannel('org.atalaia.app/beacons');
      for (final method in ['available', 'granted', 'enabled']) {
        // A missing plugin would throw MissingPluginException here.
        expect(
          await channel.invokeMethod<bool>(method),
          isA<bool>(),
          reason: method,
        );
      }
    }, skip: !onAndroidDevice);

    testWidgets(
      'without Bluetooth the scan says so instead of failing',
      (_) async {
        final service = ChannelBeaconScanService();
        if (await service.available() &&
            await service.granted() &&
            await service.bluetoothOn()) {
          // A device with Bluetooth on and the permissions granted: listening
          // for nothing in particular must neither fail nor hear a beacon.
          final first = await service
              .windows([
                'FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F',
              ], const Duration(seconds: 3))
              .first
              .timeout(const Duration(seconds: 10));
          expect(first.sightings, isEmpty);
        } else {
          // The usual emulator: nothing to scan with, and the stream's error
          // names it.
          await expectLater(
            service.windows([
              'FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F',
            ], const Duration(seconds: 3)).first,
            throwsA(isA<PlatformException>()),
          );
        }
      },
      skip: !onAndroidDevice,
    );
  });

  group('on iOS', () {
    testWidgets('there is no plugin: not available, GPS only', (_) async {
      final service = ChannelBeaconScanService();
      expect(await service.available(), isFalse);
      expect(await service.granted(), isFalse);
      expect(await service.bluetoothOn(), isFalse);
    }, skip: !onIosDevice);
  });
}
