// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The USB radio modem's own OLED language (decision MOD-2, protocol/usb-modem.md
// SET_LANG) as the phone controller sends it (lib/controller/serial_modem.dart),
// against a scripted modem link: sent once IDENT says the firmware takes it, again
// when the modem identifies itself anew (it forgot), cleared with null, never to an
// older firmware. The Pi's twin is controller/tests/test_radio_modem.py.
@Timeout(Duration(minutes: 1))
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/serial_modem.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:flutter_test/flutter_test.dart';

/// A modem link the test plays: what the phone sends, as (type, payload).
class ScriptedModem implements PodTransport {
  final _in = StreamController<Uint8List>.broadcast();
  final _dec = FrameDecoder();
  final sent = <Frame>[];

  @override
  String get kind => 'usb';

  @override
  Stream<Uint8List> get incoming => _in.stream;

  @override
  Future<void> send(Uint8List bytes) async => sent.addAll(_dec.feed(bytes));

  @override
  Future<void> close() async => _in.close();

  void ident({required bool lang}) => _in.add(
    encodeFrame(
      ModemFrame.ident,
      utf8.encode(
        jsonEncode({
          'fw': 'atalaia-modem',
          'fw_version': 'test',
          'radio': 'sx1262',
          'lang': ?(lang ? true : null),
        }),
      ),
    ),
  );

  /// The SET_LANG commands sent, each as its code ("" clears).
  List<String> get languages => [
    for (final f in sent)
      if (f.type == ModemFrame.cmd && f.payload[0] == RadioOp.setLang)
        ascii.decode(f.payload.sublist(1)),
  ];

  /// Answers the last PING, so the modem is up.
  void pong() {
    final ping = sent.lastWhere(
      (f) => f.type == ModemFrame.cmd && f.payload[0] == RadioOp.ping,
    );
    _in.add(
      encodeFrame(
        ModemFrame.status,
        utf8.encode(
          jsonEncode({
            'cmd': 1,
            'ping':
                ping.payload[1] << 24 |
                ping.payload[2] << 16 |
                ping.payload[3] << 8 |
                ping.payload[4],
            'configured': false,
          }),
        ),
      ),
    );
  }
}

Future<void> settle() => Future<void>.delayed(const Duration(milliseconds: 20));

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

  test('sent after IDENT says lang, and on every IDENT again', () async {
    modem.setLanguage('pt'); // before the modem identified itself: kept
    await settle();
    expect(link.languages, isEmpty);
    link.ident(lang: true);
    await settle();
    expect(link.languages, ['pt']);
    expect(modem.hasLanguage, isTrue);
    link.pong();
    await settle();
    expect(modem.isUp, isTrue);
    modem.setLanguage('zh-TW'); // up: at once, in lower case
    await settle();
    expect(link.languages, ['pt', 'zh-tw']);
    link.ident(lang: true); // the modem rebooted and forgot it
    await settle();
    expect(link.languages, ['pt', 'zh-tw', 'zh-tw']);
    modem.setLanguage(null); // back to the build's
    await settle();
    expect(link.languages.last, '');
    link.ident(lang: true);
    await settle();
    expect(link.languages.length, 4); // nothing held, nothing to clear
  });

  test('never to an older firmware, and only a code is taken', () async {
    modem.setLanguage('de');
    link.ident(lang: false);
    link.pong();
    await settle();
    expect(modem.hasLanguage, isFalse);
    modem.setLanguage('pt');
    await settle();
    expect(link.languages, isEmpty);
    expect(() => modem.setLanguage('zh-tw-hant'), throwsArgumentError);
    expect(() => modem.setLanguage('p t'), throwsArgumentError);
  });
}
