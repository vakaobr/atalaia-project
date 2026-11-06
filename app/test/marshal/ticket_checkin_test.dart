// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A marshal takes a registered player's printed ticket (lib/marshal/
// ticket_checkin.dart, decisions TKT-1 to TKT-6) against a fake field
// controller: scanned or typed, sent with the marshal's own token; the
// answers said in words (checked in, waiting for the card check, already
// there, not the newest ticket, not on the list, refused); a text that is no
// ticket never leaves the phone.

import 'package:atalaia_app/checkin/checkin_client.dart';
import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/marshal/ticket_checkin.dart';
import 'package:atalaia_app/ui/widgets.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/fakes.dart';

const _reg1 = '7a000000-0000-4000-8000-000000000001';
const _reg2 = '7a000000-0000-4000-8000-000000000002';

void main() {
  late FakeField field;
  late PinnedField pinned;
  late FieldCheckin marshal;
  late FieldCheckin plain;

  FieldCheckin checkin(String pid, String token) => FieldCheckin(
    fieldId: field.fieldId,
    gameId: 42,
    gameName: 'Domingo de manhã',
    playerId: pid,
    token: token,
    exp: 4102444800,
    status: 'checked_in',
    role: 'marshal',
  );

  setUp(() {
    field = FakeField();
    pinned = PinnedField(
      fieldId: field.fieldId,
      fieldName: field.fieldName,
      caPem: field.pem,
      caSha256: field.sha256Bytes,
      urls: field.urls,
    );
    String token(String pid, String name) =>
        field.handle('POST', '/checkin', {
              'game_id': 42,
              'player_id': pid,
              'player_secret': pid,
              'display_name': name,
              'notice_version': 1,
            }, null).json['token']!
            as String;

    final t0 = token('p-marshalmarsh', 'Rui');
    field.listMarshal('p-marshalmarsh', id: 'm-rui', name: 'Rui');
    marshal = checkin(
      'p-marshalmarsh',
      field.handle('POST', '/checkin/token', null, t0).json['token']! as String,
    );
    plain = checkin('p-abcdefgh2345', token('p-abcdefgh2345', 'Coruja'));
  });

  Future<(Harness, Strings)> open(
    WidgetTester tester,
    FieldCheckin who, {
    FakeQr? qr,
  }) async {
    tester.view.physicalSize = const Size(400, 1000);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final h = harness(fieldHttp: field.http, qr: qr);
    await tester.pumpWidget(
      h.app(
        home: TicketCheckinScreen(checkin: who, field: pinned),
      ),
    );
    await tester.pumpAndSettle();
    return (h, Strings(h.settings.language));
  }

  Future<void> type(WidgetTester tester, String text) async {
    await tester.enterText(find.byKey(const Key('ticket-text')), text);
    await tester.tap(find.byKey(const Key('ticket-submit')));
    await tester.pumpAndSettle();
  }

  Notice result(WidgetTester tester) =>
      tester.widget<Notice>(find.byKey(const Key('ticket-result')));

  testWidgets('a scanned ticket checks the player in; again changes nothing', (
    tester,
  ) async {
    final text = field.registerExpected('p-falcaofalcao', 'Falcão', _reg1);
    final (h, s) = await open(tester, marshal, qr: FakeQr(text));
    await tester.tap(find.byKey(const Key('ticket-scan')));
    await tester.pumpAndSettle();
    expect(h.qr.hints.single, s.t('ticket.scan_hint'));
    expect(field.ticketRequests.single, text);
    expect(field.rows['p-falcaofalcao']!['status'], 'checked_in');
    // Who took the ticket: the marshal's own token, so their player id.
    expect(
      field.rows['p-falcaofalcao']!['ticket_scanned_by'],
      'p-marshalmarsh',
    );
    expect(result(tester).text, s.t('ticket.done', {'name': 'Falcão'}));
    expect(result(tester).kind, NoticeKind.ok);
    expect(find.text(s.t('ticket.recent')), findsOneWidget);

    await tester.tap(find.byKey(const Key('ticket-scan')));
    await tester.pumpAndSettle();
    expect(result(tester).text, s.t('ticket.already', {'name': 'Falcão'}));
  });

  testWidgets('under the APD rule the ticket is not the card: pending', (
    tester,
  ) async {
    field.cardRule = true;
    final text = field.registerExpected('p-corvocorvoco', 'Corvo', _reg1);
    final (_, s) = await open(tester, marshal);
    // Typed from paper, with the line break and spaces of a copy.
    await type(tester, '  ${text.substring(0, 30)}\n${text.substring(30)} ');
    expect(field.ticketRequests.single, text);
    expect(field.rows['p-corvocorvoco']!['status'], 'pending');
    expect(result(tester).text, s.t('ticket.pending', {'name': 'Corvo'}));
    expect(result(tester).kind, NoticeKind.warning);
    // The typed text is cleared for the next player.
    expect(
      tester
          .widget<TextField>(find.byKey(const Key('ticket-text')))
          .controller!
          .text,
      isEmpty,
    );
    await type(tester, text);
    expect(
      result(tester).text,
      s.t('ticket.already_pending', {'name': 'Corvo'}),
    );
  });

  testWidgets('the code after the prefix alone is taken as the ticket', (
    tester,
  ) async {
    final text = field.registerExpected('p-gaiogaiogaio', 'Gaio', _reg1);
    final (_, s) = await open(tester, marshal);
    await type(tester, text.substring('atalaia:ticket:'.length));
    expect(field.ticketRequests.single, text);
    expect(result(tester).text, s.t('ticket.done', {'name': 'Gaio'}));
  });

  testWidgets('an old ticket, a stranger and a bad text are said', (
    tester,
  ) async {
    field.registerExpected('p-falcaofalcao', 'Falcão', _reg1, seed: 2);
    final (_, s) = await open(tester, marshal);
    // A newer ticket replaced this one (seed 2 is the newest).
    await type(tester, field.ticketFor('p-falcaofalcao', _reg1));
    expect(result(tester).text, s.t('ticket.not_newest'));
    expect(field.rows['p-falcaofalcao']!['status'], 'expected');
    // A registration this game's list does not have.
    await type(tester, field.ticketFor('p-falcaofalcao', _reg2));
    expect(result(tester).text, s.t('ticket.not_listed'));
    expect(field.ticketRequests, hasLength(2));
    // Not a ticket, or another code of ours: never sent.
    await type(tester, 'atalaia:ticket:AAAA');
    expect(result(tester).text, s.t('ticket.bad'));
    await type(tester, field.posterText());
    expect(result(tester).text, s.t('code.is_poster'));
    expect(field.ticketRequests, hasLength(2));
    expect(find.text(s.t('ticket.recent')), findsNothing);
  });

  testWidgets('no network and a player who is not a marshal are said', (
    tester,
  ) async {
    final text = field.registerExpected('p-falcaofalcao', 'Falcão', _reg1);
    final (_, s) = await open(tester, plain);
    await type(tester, text);
    expect(
      result(tester).text,
      s.t('ticket.refused', {
        'error': "staff only: the GM token or a marshal's token",
      }),
    );
    field.offline = true;
    await type(tester, text);
    expect(result(tester).text, s.t('ticket.offline'));
    expect(field.rows['p-falcaofalcao']!['status'], 'expected');
  });

  test('what each answer means', () {
    TicketOutcome err(int status, [String m = 'x']) =>
        TicketOutcome.fromError(CheckinException(status, m));
    expect(err(0).key, 'ticket.offline');
    expect(err(400).key, 'ticket.bad');
    expect(err(401).key, 'ticket.session');
    expect(err(403, 'ticket_not_newest: ...').key, 'ticket.not_newest');
    expect(err(403, 'staff removed this check-in').key, 'ticket.refused');
    expect(err(404).key, 'ticket.not_listed');
    expect(err(409).key, 'ticket.ended');
    expect(err(429).key, 'ticket.too_many');
    expect(
      TicketOutcome.fromRow({'player_id': 'p-x', 'status': 'checked_in'}).args,
      {'name': 'p-x'},
    );
    expect(normaliseTicketText(' AB\nCD '), 'atalaia:ticket:ABCD');
    expect(normaliseTicketText('atalaia:ticket:AB CD'), 'atalaia:ticket:ABCD');
    expect(normaliseTicketText('   '), '');
  });
}
