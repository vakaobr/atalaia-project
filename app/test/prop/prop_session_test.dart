// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The prop session (lib/prop/prop_session.dart) running real modes on the
// real core, in a game loop isolate with a manual clock: the team buttons,
// the mode's screens, its sounds, NFC tags checked with the game key, the
// game's length ending the game (decision PC6), kiosk tamper detection and
// the services started and stopped with the game.

import 'dart:typed_data';

import 'package:atalaia_app/core/node_runner.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/security/ndef.dart';
import 'package:atalaia_app/security/nfc_tag_signer.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/core_libs.dart';
import '../support/fakes.dart';

const texts = PropTexts(
  notificationTitle: 'Atalaia: {mode}',
  notificationRunning: 'running',
  notificationLeft: '{time} left',
);

final catalog = ModeCatalog.builtin();

PropSession session(
  String modeId,
  String role, {
  Map<String, Object?> params = const {},
  int durationMs = 0,
  FakeDevice? device,
  FakeForeground? fg,
  FakeKiosk? kiosk,
  JoinPayload? join,
}) {
  final mode = catalog.compose(modeId);
  const teams = ['red', 'blue'];
  return PropSession(
    setup: PropSetup(
      mode: mode,
      role: role,
      teams: teams,
      params: mode.resolveParams(params, teams),
      durationMs: durationMs,
      join: join,
    ),
    runner: createNodeRunner(libraryPath: coreLibraryPath()),
    device: device ?? FakeDevice(),
    texts: texts,
    foreground: fg,
    kiosk: kiosk,
    kioskEnabled: kiosk != null,
    clock: GameClock.manual,
    modeName: 'Bomb',
  );
}

Future<void> run(PropSession s, int ms, {int step = 50}) async {
  for (var t = 0; t < ms; t += step) {
    await s.advance(step);
  }
}

void main() {
  test('Bomb: standby, armed by holding the button, the countdown, the '
      'explosion', () async {
    final device = FakeDevice();
    final fg = FakeForeground();
    final s = session(
      'org.atalaia.bomb',
      'bomb',
      params: {'fuse_s': 20},
      device: device,
      fg: fg,
    );
    addTearDown(s.close);
    await s.open();
    expect(s.phase, PropPhase.ready);
    await s.start();
    await s.advance(0);
    expect(s.phase, PropPhase.running);
    expect(s.screenName, 'standby');
    expect(s.template?.name, 'standby');
    expect(s.screenData, {'arm': 'red'});
    expect(fg.calls.first, 'start Atalaia: Bomb | running');
    expect(device.calls, containsAll(['keepScreenOn true', 'brightness 1.0']));

    s.pressTeam('red');
    await run(s, 5000);
    s.releaseTeam('red');
    await s.advance(0);
    expect(s.screenName, 'countdown');
    expect(s.screenData['left'], 20);
    expect(device.calls, contains('tone warning 600'));
    expect(s.log.any((l) => l.startsWith('bomb.armed')), isTrue);

    await run(s, 20000, step: 500);
    expect(s.screenName, 'exploded');
    expect(s.screenData['team'], 'red');
    expect(device.calls, contains('tone alarm 2000'));
  });

  test("the game's length ends the game: the shell sends game.end", () async {
    final fg = FakeForeground();
    final s = session(
      'org.atalaia.domination',
      'zone',
      durationMs: 3000,
      fg: fg,
    );
    addTearDown(s.close);
    await s.open();
    await s.start();
    await run(s, 2900, step: 100);
    expect(s.phase, PropPhase.running);
    expect(s.remainingMs, 100);
    await run(s, 200, step: 100);
    expect(s.phase, PropPhase.ended);
    expect(s.remainingMs, 0);
    expect(s.log, contains('time is up: game.end'));
    expect(fg.calls.last, 'stop');
    expect(s.screenName, 'final_score');
  });

  test('pause and resume stop the clock; an admin can end the game', () async {
    final s = session('org.atalaia.domination', 'zone', durationMs: 60000);
    addTearDown(s.close);
    await s.open();
    await s.start();
    await run(s, 1000, step: 250);
    await s.pause();
    await s.advance(0);
    expect(s.phase, PropPhase.paused);
    final at = s.gameTimeMs;
    await run(s, 2000, step: 250);
    expect(s.gameTimeMs, at);
    await s.resume();
    await run(s, 1000, step: 250);
    expect(s.phase, PropPhase.running);
    expect(s.gameTimeMs, greaterThan(at));
    await s.end();
    await s.advance(0);
    expect(s.phase, PropPhase.ended);
  });

  test('Respawn: a signed tag of a joined game takes a life; a forged one '
      'is refused', () async {
    final key = Uint8List.fromList(List.generate(16, (i) => i * 7));
    final join = JoinPayload(
      gameId: 4242,
      gameKey: key,
      nodeId: 3,
      controllerId: 0,
      channelHz: 869525000,
      maxHops: 2,
      teams: const ['red', 'blue'],
      modeId: 'org.atalaia.respawn',
      role: 'respawn',
      gameSeed: 9,
      params: null,
      kind: JoinKind.node,
    );
    final s = session(
      'org.atalaia.respawn',
      'respawn',
      params: {'lives': 5, 'respawn_cooldown_s': 0},
      join: join,
    );
    addTearDown(s.close);
    await s.open();
    await s.start();
    final tag = encodeTag(
      const PlayerTag(player: 'p-17', team: 2, gameId: 4242),
      key,
    );
    await s.tagRead(
      NfcRead(
        uid: Uint8List.fromList([4, 1, 2, 3]),
        ndef: ndefMimeRecord(tag, tagNdefType),
      ),
    );
    await s.advance(0);
    expect(s.screenName, 'respawn');
    expect(s.screenData['lives'], 4);
    expect(s.screenData['team'], 'blue');
    expect(s.log.any((l) => l.startsWith('player.respawn')), isTrue);

    final forged = Uint8List.fromList(tag)..[tag.length - 1] ^= 1;
    await s.tagRead(
      NfcRead(
        uid: Uint8List.fromList([4, 9]),
        ndef: ndefMimeRecord(forged, tagNdefType),
      ),
    );
    await s.advance(0);
    expect(s.screenData['error'], isTrue);
  });

  test(
    'a stand-alone prop has no game key: tags are refused (no_game)',
    () async {
      final s = session('org.atalaia.player_checkin', 'checkpoint');
      addTearDown(s.close);
      await s.open();
      await s.start();
      await s.tagRead(NfcRead(uid: Uint8List.fromList([1, 2, 3, 4])));
      await s.advance(0);
      expect(s.screenData['error'], isTrue);
      expect(s.screenData['total'], 0);
    },
  );

  test(
    'kiosk mode: started with the game; leaving it is reported once',
    () async {
      final kiosk = FakeKiosk();
      final device = FakeDevice();
      final s = session(
        'org.atalaia.domination',
        'zone',
        kiosk: kiosk,
        device: device,
      );
      await s.open();
      await s.start();
      expect(kiosk.active, isTrue);
      await run(s, 2000, step: 500);
      expect(s.tamper, isFalse);
      kiosk.active = false; // someone got out of the lock task
      await run(s, 2000, step: 500);
      expect(s.tamper, isTrue);
      expect(s.log.where((l) => l.contains('kiosk_broken')).length, 1);
      await s.close();
      expect(kiosk.calls.last, 'stop');
      expect(device.calls.last, 'keepScreenOn false');
    },
  );

  test(
    'a script that does not load fails the session, with the reason',
    () async {
      final mode = catalog.compose('org.atalaia.domination');
      final broken = PropSession(
        setup: PropSetup(
          mode: GameMode(
            ModeManifest(
              folder: 'broken',
              id: 'x.broken',
              version: '0',
              kind: 'mode',
              names: const {'en': 'Broken'},
              descriptions: const {},
              roles: mode.main.roles,
              params: const [],
              nodeScript: 'this is not lua',
              fieldScript: null,
              screens: const {},
            ),
            const [],
          ),
          role: 'zone',
          teams: const ['red', 'blue'],
          params: const {},
        ),
        runner: createNodeRunner(libraryPath: coreLibraryPath()),
        device: FakeDevice(),
        texts: texts,
        clock: GameClock.manual,
      );
      addTearDown(broken.close);
      await broken.open();
      expect(broken.phase, PropPhase.failed);
      expect(broken.error, isNotEmpty);
    },
  );
}
