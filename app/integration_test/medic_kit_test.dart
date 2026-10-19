// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// On an Android device or emulator, in real time: a Medic Kit prop
// (modes/medic) on the APK's own core, in a joined game, so player tags are
// checked with the game's key. The emulator has no NFC reader, so the tags
// are given to the prop's session as the phone's reader would (the same
// call its NFC subscription makes); the button is held on the screen.

import 'dart:typed_data';

import 'package:atalaia_app/core/node_runner.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/platform/channels.dart';
import 'package:atalaia_app/platform/services.dart';
import 'package:atalaia_app/prop/prop_game.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/security/ndef.dart';
import 'package:atalaia_app/security/nfc_tag_signer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

import 'support.dart';

Finder inDialog(String text) => find.descendant(
  of: find.byType(AlertDialog),
  matching: find.widgetWithText(FilledButton, text),
);

NfcRead playerTag(String player, List<int> key) => NfcRead(
  uid: Uint8List.fromList([4, 0x4d, 0x4b, player.length]),
  ndef: ndefMimeRecord(
    encodeTag(PlayerTag(player: player, team: 2, gameId: 31), key),
    tagNdefType,
  ),
);

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('a Medic Kit prop: a player tag, a held button, a heal', (
    tester,
  ) async {
    final key = Uint8List.fromList(List.generate(16, (i) => 31 * i + 5));
    const teams = ['red', 'blue'];
    final mode = ModeCatalog.builtin().compose('org.atalaia.medic');
    final setup = PropSetup(
      mode: mode,
      role: 'medic',
      teams: teams,
      params: mode.resolveParams({'heal_hold_s': 2}, teams),
      join: JoinPayload(
        gameId: 31,
        gameKey: key,
        nodeId: 6,
        controllerId: 0,
        channelHz: 869525000,
        maxHops: 2,
        teams: teams,
        modeId: 'org.atalaia.medic',
        role: 'medic',
        gameSeed: 4,
        params: null,
        kind: JoinKind.node,
      ),
    );
    final session = PropSession(
      setup: setup,
      runner: createNodeRunner(),
      device: ChannelDeviceServices(),
      texts: propTexts(const Strings(AppLanguage.pt)),
      modeName: 'Ligaduras',
    );
    addTearDown(session.close);
    await session.open();
    await tester.pumpWidget(
      deviceApp(
        home: PropGameScreen(
          setup: setup,
          session: session,
          modeName: 'Ligaduras',
        ),
      ),
    );
    await waitFor(tester, find.byKey(const Key('prop-start')));
    await tester.tap(find.byKey(const Key('prop-start')));
    await waitFor(tester, inDialog('Começar'));
    await tester.tap(inDialog('Começar'));
    await waitFor(tester, find.text('Lê a tua etiqueta'));
    expect(find.text('Restam 5 ligaduras'), findsOneWidget);

    // A player's signed tag, then the button held for the heal's 2 s.
    await session.tagRead(playerTag('b1', key));
    await waitFor(tester, find.text('Mantém premido para tratar'));
    final button = find.byKey(const Key('team-button-blue'));
    await tester.ensureVisible(button);
    final hold = await tester.startGesture(tester.getCenter(button));
    await pass(tester, const Duration(milliseconds: 2700));
    await hold.up();
    await waitFor(tester, find.text('DE VOLTA AO JOGO'));
    expect(find.text('Tratamento 1 de 2'), findsOneWidget);
    expect(session.log.any((l) => l.startsWith('medic.heal')), isTrue);
    await waitFor(
      tester,
      find.text('Restam 4 ligaduras'),
      timeout: const Duration(seconds: 15),
    );

    // A forged tag (signed with another key) is refused, and says why.
    await session.tagRead(playerTag('b2', Uint8List(16)));
    await waitFor(tester, find.text('Etiqueta falsificada'));
    expect(find.text('RECUSADO'), findsOneWidget);
  });
}
