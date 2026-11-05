// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Other games' packets (RFC 0001 Amendment 27, protocol/usb-modem.md
// WATCH_GAMES and OTHER_GAME) as the phone controller asks for and hears them
// (lib/controller/serial_modem.dart), against a scripted modem link:
// WATCH_GAMES once IDENT says `games`, again on every IDENT (a rebooted modem
// forgot it), never to an older firmware; OTHER_GAME reports reach the
// callback, a malformed one is dropped. The Pi's twin is
// controller/tests/test_radio_modem.py.
@Timeout(Duration(minutes: 1))
library;

import 'dart:convert';

import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/controller/serial_modem.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import 'serial_modem_language_test.dart' show ScriptedModem, settle;

extension on ScriptedModem {
  void identGames({required bool games}) => push(
    ModemFrame.ident,
    utf8.encode(
      jsonEncode({
        'fw': 'atalaia-modem',
        'fw_version': 'test',
        'radio': 'sx1262',
        'field': true,
        'games': ?(games ? true : null),
      }),
    ),
  );

  /// The WATCH_GAMES commands sent, each as its on byte.
  List<int> get watches => [
    for (final f in sent)
      if (f.type == ModemFrame.cmd && f.payload[0] == RadioOp.watchGames)
        f.payload[1],
  ];
}

void main() {
  late ScriptedModem link;
  late SerialModem modem;

  setUp(() async {
    link = ScriptedModem();
    modem = SerialModem(link, pingInterval: const Duration(minutes: 5));
    await modem.start();
    await settle();
  });

  tearDown(() async {
    await modem.close();
  });

  test('WATCH_GAMES after an IDENT that says games, and again on every '
      'IDENT; its reports reach the controller', () async {
    final heard = <OtherGame>[];
    modem
      ..onOtherGame = heard.add
      ..watchGames(true); // before the modem identified itself: kept
    await settle();
    expect(link.watches, isEmpty);
    link.identGames(games: true);
    await settle();
    expect(link.watches, [1]);
    expect(modem.hasOtherGames, isTrue);
    link.push(ModemFrame.otherGame, [0, 240, 0, 5, 0xba, 4]);
    await settle();
    expect(heard, [const OtherGame(240, 5, -70, 4)]);
    link.identGames(games: true); // it rebooted and forgot
    await settle();
    expect(link.watches, [1, 1]);
    link.push(ModemFrame.otherGame, [0, 240]); // malformed: dropped
    await settle();
    expect(heard, hasLength(1));
    modem.watchGames(false);
    await settle();
    expect(link.watches, [1, 1, 0]);
  });

  test('an older modem is never asked', () async {
    modem.watchGames(true);
    link.identGames(games: false);
    await settle();
    modem.watchGames(true);
    await settle();
    expect(modem.hasOtherGames, isFalse);
    expect(link.watches, isEmpty);
  });

  test('OTHER_GAME decodes as modem_framing.py does', () {
    expect(
      OtherGame.decode([0xff, 0xfe, 0x12, 0x34, 0x80, 0x7f]),
      const OtherGame(0xfffe, 0x1234, -128, 127),
    );
    expect(() => OtherGame.decode([1, 2, 3]), throwsFormatException);
  });
}
