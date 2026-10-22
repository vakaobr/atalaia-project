// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The field controller role's screen and shell (slice S6 of PE24;
// lib/controller/controller_screen.dart, controller_shell.dart) with the
// phone replaced by fakes: the role on the home screen on Android only;
// Start keeps the phone running with the foreground service (its wake and
// Wi-Fi locks) and launches the controller with the app's join key (made
// once and kept), the console's files and the Wi-Fi opening; the
// notification follows the live game; the codes stay hidden until asked;
// the console opens on the phone's own address; the Wi-Fi opening restarts
// it; a controller that ends by itself says so and lets the service go;
// the field's Wi-Fi and a local hotspot with its QR code. In both
// languages, at 320 px wide, with the accessibility guidelines.

import 'package:atalaia_app/controller/controller_isolate.dart';
import 'package:atalaia_app/controller/controller_screen.dart';
import 'package:atalaia_app/controller/controller_shell.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/ui/home_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';

Future<void> small(WidgetTester tester) async {
  tester.view.physicalSize = const Size(320, 640);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> phone(WidgetTester tester) async {
  tester.view.physicalSize = const Size(420, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

final onAndroid = TargetPlatformVariant.only(TargetPlatform.android);

bool onScreen(WidgetTester tester, Finder f) {
  if (f.evaluate().isEmpty) return false;
  final r = tester.getRect(f.first);
  final height = tester.view.physicalSize.height / tester.view.devicePixelRatio;
  return r.top >= 0 && r.bottom <= height;
}

/// From the top of the screen, scrolls down until [f] is on screen.
Future<void> see(WidgetTester tester, Finder f) async {
  await top(tester);
  if (!onScreen(tester, f)) {
    await tester.scrollUntilVisible(
      f,
      200,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
  }
}

/// Taps what [key] names, scrolled into view first.
Future<void> tapKey(WidgetTester tester, String key) async {
  final f = find.byKey(Key(key));
  await see(tester, f);
  await tester.tap(f);
  await tester.pumpAndSettle();
}

/// Back to the top of the screen.
Future<void> top(WidgetTester tester) async {
  await tester.drag(find.byType(Scrollable).first, const Offset(0, 5000));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the role is on the home screen on Android', (tester) async {
    await phone(tester);
    final h = harness();
    await tester.pumpWidget(h.app(home: const HomeScreen()));
    await tester.pumpAndSettle();
    await see(tester, find.text('Controlador de campo'));
    await tapKey(tester, 'role-controller');
    expect(find.byType(ControllerScreen), findsOneWidget);
  }, variant: onAndroid);

  testWidgets('and not on iOS', (tester) async {
    await phone(tester);
    await tester.pumpWidget(harness().app(home: const HomeScreen()));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('role-controller')), findsNothing);
  }, variant: TargetPlatformVariant.only(TargetPlatform.iOS));

  for (final lang in AppLanguage.values) {
    testWidgets('start, the codes, the console and stop (${lang.code})', (
      tester,
    ) async {
      await phone(tester);
      final h = harness(language: lang);
      final s = Strings(lang);
      await tester.pumpWidget(h.app(home: const ControllerScreen()));
      await tester.pumpAndSettle();
      expect(find.text(s.t('ctl.phase_stopped')), findsOneWidget);

      await tapKey(tester, 'ctl-start');
      // The foreground service (wake and Wi-Fi locks) first, then the isolate.
      expect(
        h.foreground.calls.first,
        startsWith('start ${s.t('ctl.notif_title')}'),
      );
      expect(h.device.calls, contains('permission POST_NOTIFICATIONS'));
      final boot = h.controllerBoots.single;
      expect(boot.open, isTrue);
      expect(boot.pod, isFalse);
      expect(boot.dir, '/controller');
      expect(boot.console, isNotEmpty);
      // The app's join key, made once and kept in the settings.
      expect(boot.joinKey, hasLength(32));
      expect(h.settings.joinKey, boot.joinKey);
      expect(find.text(s.t('ctl.phase_running')), findsOneWidget);
      expect(find.text(s.t('ctl.no_game')), findsOneWidget);
      // Asked once for the battery exemption.
      expect(h.device.calls, contains('requestBattery'));
      expect(h.settings.batteryAsked, isTrue);
      await see(tester, find.text('https://192.168.43.1:8443/console/'));
      await see(
        tester,
        find.text('ABAB ABAB ABAB ABAB\n${s.t('ctl.ca_hint')}'),
      );

      // The codes are hidden until asked.
      await see(tester, find.byKey(const Key('ctl-code-gm')));
      expect(find.text('gm-secret-token'), findsNothing);
      await tapKey(tester, 'ctl-show-codes');
      await see(tester, find.text('gm-secret-token'));
      await see(tester, find.text('rd-read-token'));

      // The live game in the screen and the notification.
      h.controllerRuns.single.emit({
        'game': {'id': 1, 'name': 'Domingo', 'state': 'running'},
      });
      await tester.pumpAndSettle();
      final line = s.t('ctl.game', {
        'name': 'Domingo',
        'state': s.t('ctl.game_running'),
      });
      await top(tester);
      expect(find.text(line), findsOneWidget);
      expect(
        h.foreground.calls.last,
        'update ${s.t('ctl.notif_title')} | $line',
      );

      // The console on the phone's own address.
      await tapKey(tester, 'ctl-console');
      // Logged in with the GM token and the app's language in the fragment.
      expect(
        find.text(
          'console http://127.0.0.1:8080/console/'
          '#token=gm-secret-token&lang=${lang.code}',
        ),
        findsOneWidget,
      );
      tester.state<NavigatorState>(find.byType(Navigator).last).pop();
      await tester.pumpAndSettle();

      await tapKey(tester, 'ctl-stop');
      expect(h.controllerRuns.single.stopped, isTrue);
      expect(h.foreground.calls.last, 'stop');
      expect(find.text(s.t('ctl.phase_stopped')), findsOneWidget);
      expect(find.byKey(const Key('ctl-code-gm')), findsNothing);

      // A second start uses the same join key.
      await tapKey(tester, 'ctl-start');
      expect(h.controllerBoots.last.joinKey, boot.joinKey);
      await h.services.controller.stop();
    }, variant: onAndroid);
  }

  testWidgets('the Wi-Fi opening restarts a running controller', (
    tester,
  ) async {
    await phone(tester);
    final h = harness(language: AppLanguage.en);
    await tester.pumpWidget(h.app(home: const ControllerScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'ctl-start');
    await tapKey(tester, 'ctl-open');
    expect(h.controllerBoots.map((b) => b.open), [true, false]);
    expect(h.controllerRuns.first.stopped, isTrue);
    expect(h.controllerRuns.last.stopped, isFalse);
    expect(h.controllerBoots.last.joinKey, h.controllerBoots.first.joinKey);
    await see(
      tester,
      find.text(Strings(AppLanguage.en).t('ctl.poster_hint_closed')),
    );
    await h.services.controller.stop();
  }, variant: onAndroid);

  testWidgets('a controller that fails or ends by itself says so', (
    tester,
  ) async {
    await phone(tester);
    final h = harness(
      controllerLauncher: (boot, {PodTransport? pod}) async =>
          throw ControllerStartException('the core did not load: x'),
    );
    await tester.pumpWidget(h.app(home: const ControllerScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'ctl-start');
    final s = Strings(AppLanguage.pt);
    expect(
      find.text('${s.t('ctl.error_start')}\nthe core did not load: x'),
      findsOneWidget,
    );
    expect(h.foreground.calls.last, 'stop');
    expect(find.byKey(const Key('ctl-start')), findsOneWidget);

    // One that starts and then ends by itself.
    final h2 = harness();
    await tester.pumpWidget(h2.app(home: const ControllerScreen()));
    await tester.pumpAndSettle();
    await tapKey(tester, 'ctl-start');
    h2.controllerRuns.single.crash('out of memory');
    await tester.pumpAndSettle();
    expect(
      find.text('${s.t('ctl.error_ended')}\nout of memory'),
      findsOneWidget,
    );
    expect(h2.foreground.calls.last, 'stop');
    expect(h2.services.controller.phase, ControllerPhase.stopped);
  }, variant: onAndroid);

  testWidgets("the field's Wi-Fi and a local hotspot with its QR code", (
    tester,
  ) async {
    await phone(tester);
    final h = harness(language: AppLanguage.en);
    final s = Strings(AppLanguage.en);
    await tester.pumpWidget(h.app(home: const ControllerScreen()));
    await tester.pumpAndSettle();
    await see(tester, find.text(s.t('ctl.wifi_network', {'ssid': 'Campo'})));
    expect(find.text(s.t('ctl.hotspot_off')), findsOneWidget);
    await tapKey(tester, 'ctl-hotspot-settings');
    await tapKey(tester, 'ctl-wifi-settings');
    expect(h.wifi.calls, ['hotspotSettings', 'wifiSettings']);
    await tapKey(tester, 'ctl-local-start');
    expect(h.device.calls, contains('permission NEARBY_WIFI_DEVICES'));
    await see(tester, find.byKey(const Key('ctl-local-on')));
    await see(
      tester,
      find.text(s.t('ctl.local_password', {'password': 'abc;def'})),
    );
    await see(
      tester,
      find.bySemanticsLabel(s.t('ctl.local_qr', {'ssid': 'AndroidShare_1234'})),
    );
    await tapKey(tester, 'ctl-local-stop');
    expect(h.wifi.calls.last, 'stopLocal');
    // Android refusing: the reason in words.
    h.wifi.next = const LocalHotspot(error: 'incompatible_mode');
    await tapKey(tester, 'ctl-local-start');
    await see(tester, find.text(s.t('ctl.local_error_incompatible_mode')));
  }, variant: onAndroid);

  test("a local hotspot's QR code text escapes what the format needs", () {
    expect(
      const LocalHotspot(ssid: 'A;B', passphrase: r'p:w\"').qrText,
      r'WIFI:T:WPA;S:A\;B;P:p\:w\\\";;',
    );
    expect(const LocalHotspot(ssid: 'Open').qrText, 'WIFI:T:nopass;S:Open;;');
    expect(const LocalHotspot(error: 'generic').qrText, isNull);
    final info = FieldWifiInfo.fromMap({
      'wifi_enabled': true,
      'ssid': '',
      'hotspot': 'on',
      'local': {'ssid': 'X', 'passphrase': 'y'},
    });
    expect(info.available, isTrue);
    expect(info.ssid, isNull);
    expect(info.hotspot, HotspotState.on);
    expect(info.localHotspot!.started, isTrue);
    expect(FieldWifiInfo.fromMap(const {}).available, isFalse);
  });

  for (final lang in AppLanguage.values) {
    testWidgets(
      '320 px wide and the accessibility guidelines (${lang.code})',
      (tester) async {
        await small(tester);
        final h = harness(language: lang);
        final handle = tester.ensureSemantics();
        await tester.pumpWidget(h.app(home: const ControllerScreen()));
        await tester.pumpAndSettle();
        Future<void> guidelines() async {
          await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
          await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
          await expectLater(tester, meetsGuideline(textContrastGuideline));
        }

        // Start is on the first screen, with no scroll.
        final start = tester.getRect(find.byKey(const Key('ctl-start')));
        expect(start.bottom, lessThan(640));
        await guidelines();
        await tester.tap(find.byKey(const Key('ctl-start')));
        await tester.pumpAndSettle();
        h.controllerRuns.single.emit({
          'game': {
            'id': 1,
            'name': 'Um nome de jogo bem comprido',
            'state': 'paused',
          },
        });
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(
          tester.getRect(find.byKey(const Key('ctl-stop'))).bottom,
          lessThan(640),
        );
        await guidelines();
        // Down the whole screen, nothing overflows, every part meets them.
        for (var i = 0; i < 12; i++) {
          await tester.drag(
            find.byType(Scrollable).first,
            const Offset(0, -400),
          );
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
          await guidelines();
        }
        await h.services.controller.stop();
        handle.dispose();
      },
      variant: onAndroid,
    );
  }

  test('the console gets the GM token in the fragment, never the query', () {
    final u = consoleAddress(
      Uri.parse('http://127.0.0.1:8080/console/'),
      'gm-a&b=c#d',
      'en',
    );
    expect(
      u.toString(),
      'http://127.0.0.1:8080/console/#token=gm-a%26b%3Dc%23d&lang=en',
    );
    expect(u.query, isEmpty);
    expect(u.path, '/console/');
  });
}
