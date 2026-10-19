// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The prop shell's pieces without a node: the team-button tracker (the
// Field Box's button_tracker.c), the game timer, the screen manager
// (ADR-P3-5), the capability mapper and the shell's own screens.

import 'package:atalaia_app/ffi/bindings.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/prop/button_tracker.dart';
import 'package:atalaia_app/prop/capability_mapper.dart';
import 'package:atalaia_app/prop/game_timer.dart';
import 'package:atalaia_app/prop/screen_manager.dart';
import 'package:atalaia_app/prop/shell_screens.dart';
import 'package:atalaia_app/ui/template/screen_template.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/fakes.dart';

void main() {
  group('team buttons', () {
    test('press, holds every 250 ms with the time held, release', () {
      final out = <String>[];
      final t = ButtonTracker((type, data) => out.add('$type $data'));
      t.press('red');
      t.press('red'); // already down
      t.tick(100);
      t.tick(200); // 300 ms: one hold
      t.tick(500); // 800 ms: two more
      t.release('red');
      t.release('red'); // already up
      expect(out, [
        'team_input.press {team: red}',
        'team_input.hold {team: red, ms: 300}',
        'team_input.hold {team: red, ms: 800}',
        'team_input.hold {team: red, ms: 800}',
        'team_input.release {team: red, ms: 800}',
      ]);
    });

    test('two teams at once; releaseAll lets go of both', () {
      final out = <String>[];
      final t = ButtonTracker((type, data) => out.add('$type ${data['team']}'));
      t
        ..press('red')
        ..press('blue')
        ..tick(250);
      expect(t.down.toSet(), {'red', 'blue'});
      t.releaseAll();
      expect(t.down, isEmpty);
      expect(out.where((e) => e.startsWith('team_input.release')).length, 2);
    });
  });

  group('game timer', () {
    test('sends game.end once, when the game time reaches the length', () {
      final t = GameTimer(60000);
      expect(t.remainingMs(0), 60000);
      expect(t.update(59999), isFalse);
      expect(t.remainingMs(59999), 1);
      expect(t.update(60000), isTrue);
      expect(t.update(61000), isFalse);
      expect(t.remainingMs(70000), 0);
      expect(t.expired, isTrue);
    });

    test('no limit', () {
      final t = GameTimer(0);
      expect(t.update(1 << 40), isFalse);
      expect(t.remainingMs(5), isNull);
    });

    test('clock text', () {
      expect(clockText(0), '0:00');
      expect(clockText(1), '0:01');
      expect(clockText(59000), '0:59');
      expect(clockText(299001), '5:00');
      expect(clockText(3600000), '1:00:00');
    });
  });

  group('screen manager', () {
    var now = DateTime(2026, 10, 19, 10);
    DateTime clock() => now;

    test(
      'active, dimmed after 30 s, off after 5 min, active on activity',
      () async {
        final d = FakeDevice();
        final m = ScreenManager(d, now: clock);
        await m.start();
        expect(m.state, ScreenState.active);
        expect(d.calls, ['keepScreenOn true', 'brightness 1.0']);
        d.calls.clear();
        now = now.add(const Duration(seconds: 29));
        await m.tick();
        expect(d.calls, isEmpty);
        now = now.add(const Duration(seconds: 1));
        await m.tick();
        expect(m.state, ScreenState.dimmed);
        expect(d.calls, ['keepScreenOn true', 'brightness 0.1']);
        d.calls.clear();
        now = now.add(const Duration(minutes: 5));
        await m.tick();
        expect(m.state, ScreenState.off);
        expect(d.calls, ['brightness null', 'keepScreenOn false']);
        d.calls.clear();
        await m.activity();
        expect(m.state, ScreenState.active);
        expect(d.calls, ['keepScreenOn true', 'brightness 1.0']);
        await m.stop();
      },
    );

    test(
      'in kiosk mode "off" keeps the screen on at the lowest brightness',
      () async {
        final d = FakeDevice();
        final m = ScreenManager(d, kiosk: true, now: clock);
        await m.start();
        now = now.add(const Duration(minutes: 6));
        await m.tick();
        expect(m.state, ScreenState.off);
        expect(d.calls.sublist(d.calls.length - 2), [
          'keepScreenOn true',
          'brightness 0.01',
        ]);
      },
    );
  });

  group('capabilities', () {
    final catalog = ModeCatalog.builtin();

    test('a phone with GPS, NFC and an accelerometer', () {
      final map = CapabilityMap.of(
        const DeviceFeatures(
          nfc: true,
          location: true,
          accelerometer: true,
          vibrator: true,
        ),
      );
      expect(map.types, {
        'team_input',
        'keypad',
        'display',
        'team_display',
        'led',
        'audio',
        'haptic',
        'nfc',
        'gps',
        'imu',
      });
      final respawn = catalog.byId('org.atalaia.respawn')!.role('respawn')!;
      expect(map.missingFor(respawn), isEmpty);
      expect(map.offers(respawn, 'team_input'), isTrue);
    });

    test('a phone without NFC cannot be a respawn point on its own; a pod '
        'with an NFC reader makes up for it', () {
      final respawn = catalog.byId('org.atalaia.respawn')!.role('respawn')!;
      final phone = CapabilityMap.of(const DeviceFeatures());
      expect(phone.missingFor(respawn), ['nfc']);
      final withPod = CapabilityMap.of(
        const DeviceFeatures(),
        pod: const PodIdent(
          fwVersion: '0.3.0',
          capabilities: [
            {'id': 'nfc', 'type': 'nfc'},
            {'id': 'btn.red', 'type': 'button', 'team': 'red'},
          ],
          hasRadio: false,
        ),
      );
      expect(withPod.missingFor(respawn), isEmpty);
      expect(withPod.descriptors.where((d) => d['source'] == 'pod').length, 2);
    });
  });

  test("the shell's screens parse here and in the core", () {
    final core = AtalaiaCore.open(coreLibraryPath());
    for (final e in shellScreens.entries) {
      expect(core.checkScreen(e.value), isNull, reason: e.key);
      expect(parseScreenTemplate(e.value).name, e.key);
    }
  });
}
