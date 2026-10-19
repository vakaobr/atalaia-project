// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// Joining a game (decision P3-10): the join text, a join card's NDEF
// message, the field join key from the settings, and what the screen says
// for each way it can go wrong; then the joined game's setup.

import 'package:atalaia_app/prop/join_screen.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/security/ndef.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fakes.dart';
import '../support/vectors.dart';

void main() {
  final v = loadVectors('join.json');
  final key = hexDecode(v['join_key'] as String);
  final wrong = hexDecode(v['wrong_key'] as String);
  final zone = cases(
    v,
    'valid',
  ).firstWhere((c) => c['name'] == 'node_domination_zone');
  final standby = cases(
    v,
    'valid',
  ).firstWhere((c) => c['name'] == 'standby_controller');
  final text = zone['text'] as String;

  test('a join text or card, checked with the join key', () {
    final (j, err) = readJoin(text: text, joinKey: key);
    expect(err, isNull);
    expect(j!.modeId, 'org.atalaia.domination');
    expect(j.nodeId, 7);
    final card = ndefMimeRecord(
      hexDecode(zone['payload'] as String),
      joinNdefType,
    );
    expect(readJoin(ndef: card, joinKey: key).$1!.gameId, 4242);
  });

  test('what goes wrong, in words the screen shows', () {
    expect(readJoin(text: text, joinKey: null).$2, 'join.no_key');
    expect(readJoin(text: text, joinKey: wrong).$2, 'join.other_field');
    expect(readJoin(text: 'hello', joinKey: key).$2, 'join.bad_text');
    expect(readJoin(ndef: [0xd0, 0, 0], joinKey: key).$2, 'join.not_a_card');
    expect(
      readJoin(text: standby['text'] as String, joinKey: key).$2,
      'join.for_controller',
    );
    final body = cases(v, 'invalid').firstWhere((c) => c['reason'] == 'body');
    expect(
      readJoin(
        text: joinToText(hexDecode(body['payload'] as String)),
        joinKey: key,
      ).$2,
      'join.bad_body',
    );
  });

  testWidgets('pasting the text joins; the setup is the payload\'s', (
    tester,
  ) async {
    final h = harness(settings: AppSettings()..joinKeyHex = hexEncode(key));
    JoinPayload? got;
    await tester.pumpWidget(
      h.app(
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: FilledButton(
                onPressed: () async {
                  got = await Navigator.push<JoinPayload>(
                    context,
                    MaterialPageRoute(
                      builder: (_) => const JoinScreen(title: 'Entrar'),
                    ),
                  );
                },
                child: const Text('go'),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();
    expect(h.nfc.calls, contains('start'));
    await tester.enterText(find.byKey(const Key('join-text')), 'nonsense');
    await tester.tap(find.byKey(const Key('join-use-text')));
    await tester.pumpAndSettle();
    expect(
      find.text('Isto não é um código de entrada válido.'),
      findsOneWidget,
    );
    await tester.enterText(find.byKey(const Key('join-text')), text);
    await tester.tap(find.byKey(const Key('join-use-text')));
    await tester.pumpAndSettle();
    expect(got!.gameId, 4242);
    expect(h.nfc.calls, contains('stop'));
  });

  testWidgets('a join card held to the phone joins too', (tester) async {
    final h = harness(settings: AppSettings()..joinKeyHex = hexEncode(key));
    JoinPayload? got;
    await tester.pumpWidget(
      h.app(
        home: Builder(
          builder: (context) => FilledButton(
            onPressed: () async => got = await Navigator.push<JoinPayload>(
              context,
              MaterialPageRoute(builder: (_) => const JoinScreen(title: 'x')),
            ),
            child: const Text('go'),
          ),
        ),
      ),
    );
    await tester.tap(find.text('go'));
    await tester.pumpAndSettle();
    h.nfc.tap(
      NfcReadFake.card(
        ndefMimeRecord(hexDecode(zone['payload'] as String), joinNdefType),
      ),
    );
    await tester.pumpAndSettle();
    expect(got!.role, 'zone');
  });

  testWidgets('without the join key the screen says where to set it', (
    tester,
  ) async {
    final h = harness(qr: FakeQr(text));
    await tester.pumpWidget(h.app(home: const JoinScreen(title: 'x')));
    await tester.pumpAndSettle();
    expect(
      find.text('Primeiro define a chave de entrada do campo nas definições.'),
      findsOneWidget,
    );
    await tester.tap(find.byKey(const Key('join-scan')));
    await tester.pumpAndSettle();
    expect(h.qr.hints.single, 'Aponta para o código QR de entrada.');
  });
}
