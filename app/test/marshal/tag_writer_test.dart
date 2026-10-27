// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The marshal's tag writer (lib/marshal/tag_writer.dart, decision TW-1)
// against a fake field controller: the controller signs each tag with the
// game's key and the phone, which holds no key, writes the record it gets;
// what the controller sends is checked before it goes to the tag; a
// controller out of reach, a refusal and a game with no key are said.

import 'dart:typed_data';

import 'package:atalaia_app/checkin/field_trust.dart';
import 'package:atalaia_app/checkin/my_replicas.dart';
import 'package:atalaia_app/controller/controller_tags_screen.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/marshal/tag_writer.dart';
import 'package:atalaia_app/security/ndef.dart';
import 'package:atalaia_app/security/nfc_tag_signer.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';

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
    String token(String pid, String name) {
      final t = field.handle('POST', '/checkin', {
        'game_id': 42,
        'player_id': pid,
        'player_secret': pid,
        'display_name': name,
        'notice_version': 1,
      }, null);
      return t.json['token']! as String;
    }

    final t0 = token('p-marshalmarsh', 'Rui');
    field.listMarshal('p-marshalmarsh', id: 'm-rui', name: 'Rui');
    final mt =
        field.handle('POST', '/checkin/token', null, t0).json['token']!
            as String;
    marshal = checkin('p-marshalmarsh', mt);
    plain = checkin('p-abcdefgh2345', token('p-abcdefgh2345', 'Coruja'));
  });

  Future<Harness> open(WidgetTester tester, FieldCheckin who) async {
    tester.view.physicalSize = const Size(400, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final h = harness(fieldHttp: field.http);
    await tester.pumpWidget(
      h.app(
        home: TagWriterScreen(checkin: who, field: pinned),
      ),
    );
    await tester.pumpAndSettle();
    return h;
  }

  testWidgets("a player's tag: signed by the controller, written as it is", (
    tester,
  ) async {
    final h = await open(tester, marshal);
    expect(find.byKey(const Key('tags-write')), findsOneWidget);
    // A bad id never leaves the phone.
    await tester.enterText(find.byKey(const Key('tags-player')), 'bad id!');
    await tester.tap(find.byKey(const Key('tags-write')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('tags-error')), findsOneWidget);
    expect(field.tagRequests, isEmpty);

    await tester.enterText(find.byKey(const Key('tags-player')), 'b3');
    await tester.tap(find.byKey(const Key('tags-team-blue')));
    await tester.tap(find.byKey(const Key('tags-write')));
    await tester.pumpAndSettle();
    expect(field.tagRequests.single, {'player': 'b3', 'team': 'blue'});
    expect(find.byKey(const Key('tags-waiting')), findsOneWidget);
    h.nfc.tapToWrite(Uint8List.fromList([4, 0xab, 0xcd]));
    await tester.pumpAndSettle();
    expect(find.text('04abcd'), findsOneWidget);
    // The record the controller made, byte for byte; the phone has no key
    // to check it with, a box does.
    final payload = payloadFromNdefMessage(h.nfc.written.single, tagNdefType)!;
    expect(
      decodeTag(payload, gameId: 42, gameKey: field.gameKey, teamCount: 2),
      const PlayerTag(player: 'b3', team: 2, gameId: 42),
    );
    // No team: the request leaves it out.
    await tester.enterText(find.byKey(const Key('tags-player')), 'c4');
    await tester.tap(find.text(Strings(h.settings.language).t('tags.no_team')));
    await tester.tap(find.byKey(const Key('tags-write')));
    await tester.pumpAndSettle();
    expect(field.tagRequests.last, {'player': 'c4'});
  });

  testWidgets('no network, a refusal and a game with no key are said', (
    tester,
  ) async {
    final h = await open(tester, marshal);
    final s = Strings(h.settings.language);
    Future<void> ask() async {
      await tester.enterText(find.byKey(const Key('tags-player')), 'b3');
      await tester.tap(find.byKey(const Key('tags-write')));
      await tester.pumpAndSettle();
    }

    field.offline = true;
    await ask();
    expect(find.text(s.t('tags.offline')), findsOneWidget);
    expect(h.nfc.written, isEmpty);
    field.offline = false;

    field.tagsLive = false;
    await ask();
    expect(find.text(s.t('tags.no_key')), findsOneWidget);
    expect(h.nfc.written, isEmpty);
  });

  testWidgets('a player who is not a marshal is refused', (tester) async {
    await open(tester, plain);
    final s = Strings(harness().settings.language);
    expect(find.text(s.t('tags.not_marshal')), findsOneWidget);
    expect(find.byKey(const Key('tags-write')), findsNothing);
  });

  testWidgets("the phone controller's own screen writes the same tag", (
    tester,
  ) async {
    final h = harness();
    String? asked;
    await tester.pumpWidget(
      h.app(
        home: ControllerTagsScreen(
          gameId: 42,
          gameName: 'Domingo',
          teams: const ['red', 'blue'],
          request: (player, team) async {
            asked = '$player/$team';
            final answer = field.handle('POST', '/games/42/tags', {
              'player': player,
              'team': ?team,
            }, marshal.token);
            return answer.json;
          },
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('tags-player')), 'r1');
    await tester.tap(find.byKey(const Key('tags-team-red')));
    await tester.tap(find.byKey(const Key('tags-write')));
    await tester.pumpAndSettle();
    expect(asked, 'r1/red');
    h.nfc.tapToWrite(Uint8List.fromList([1, 2, 3, 4]));
    await tester.pumpAndSettle();
    final payload = payloadFromNdefMessage(h.nfc.written.single, tagNdefType)!;
    expect(
      decodeTag(payload, gameId: 42, gameKey: field.gameKey, teamCount: 2),
      const PlayerTag(player: 'r1', team: 1, gameId: 42),
    );
  });

  testWidgets('an answer that is not the tag asked for is never written', (
    tester,
  ) async {
    final h = harness();
    await tester.pumpWidget(
      h.app(
        home: ControllerTagsScreen(
          gameId: 42,
          gameName: 'Domingo',
          teams: const ['red', 'blue'],
          // A tag for another player: a controller that answers wrongly.
          request: (player, team) async => field.handle(
            'POST',
            '/games/42/tags',
            {'player': 'someone-else'},
            marshal.token,
          ).json,
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('tags-player')), 'r1');
    await tester.tap(find.byKey(const Key('tags-write')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('tags-error')), findsOneWidget);
    expect(find.byKey(const Key('tags-waiting')), findsNothing);
    expect(h.nfc.written, isEmpty);
  });
}
