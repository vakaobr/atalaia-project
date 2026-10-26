// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A code of Atalaia's own that reaches the wrong screen (found on an iPhone,
// 2026-10-26: the player's join screen read the check-in poster's QR code
// as a bad scoreboard link). A poster on the player's start screen, scanned
// or typed, opens the check-in with it; the other wrong kinds say what they
// are and where to use them, in each language; the scanners of the check-in,
// the prop's join, the site and the replica registry do the same.

import 'package:atalaia_app/checkin/checkin_screen.dart';
import 'package:atalaia_app/chrono/replica_registry_ui.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/l10n/strings_de.dart';
import 'package:atalaia_app/l10n/strings_en.dart';
import 'package:atalaia_app/l10n/strings_pt.dart';
import 'package:atalaia_app/l10n/strings_zh_tw.dart';
import 'package:atalaia_app/marshal/marshal_records.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/prop/join_screen.dart';
import 'package:atalaia_app/site/site_screens.dart';
import 'package:atalaia_app/ui/code_kind.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/fakes.dart';

const _siteLink =
    'atalaia://register?site=https%3A%2F%2Fcampo.example.pt&field=campo-norte';
const _joinCard = 'atalaia:join:AQIDBA';
const _scoreboard = 'http://10.1.1.1:8080/scoreboard#token=read-1';

class _QuietSocket implements FeedSocket {
  @override
  Stream<String> get messages => const Stream.empty();
  @override
  int? get closeCode => null;
  @override
  Future<void> close() async {}
}

Future<void> _tall(WidgetTester tester) async {
  tester.view.physicalSize = const Size(800, 1800);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> _tap(WidgetTester tester, String key) async {
  final f = find.byKey(Key(key));
  await tester.ensureVisible(f);
  await tester.pumpAndSettle();
  await tester.tap(f);
  await tester.pumpAndSettle();
}

void main() {
  final poster = FakeField().posterText();

  test('what a text is', () {
    expect(classifyCode(poster), CodeKind.poster);
    expect(classifyCode(' $_joinCard '), CodeKind.joinCard);
    expect(classifyCode(_siteLink), CodeKind.siteLink);
    expect(classifyCode('https://campo.example.pt/f/campo'), CodeKind.siteLink);
    expect(classifyCode(_scoreboard), CodeKind.scoreboard);
    expect(classifyCode('hello'), isNull);
    expect(classifyCode('atalaia:checkin:'), CodeKind.poster);
    expect(wrongCodeMessage(poster, CodeKind.poster), isNull);
    expect(wrongCodeMessage(poster, CodeKind.siteLink), 'code.is_poster');
  });

  test('every wrong-code text is in all four languages', () {
    for (final k in CodeKind.values) {
      for (final m in [enStrings, ptStrings, deStrings, zhTwStrings]) {
        expect(m[k.messageKey], isNotNull, reason: k.messageKey);
      }
    }
  });

  group('the player start screen', () {
    testWidgets('a poster scanned opens the check-in with it', (tester) async {
      await _tall(tester);
      final h = harness(qr: FakeQr(poster));
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      await _tap(tester, 'player-scan');
      expect(find.byType(CheckinScreen), findsOneWidget);
      expect(
        tester.widget<CheckinScreen>(find.byType(CheckinScreen)).posterText,
        poster,
      );
      expect(find.textContaining('Falta o endereço'), findsNothing);
    });

    testWidgets('a poster typed in the address field does the same', (
      tester,
    ) async {
      await _tall(tester);
      final h = harness();
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('player-address')), poster);
      await _tap(tester, 'player-connect');
      expect(find.byType(CheckinScreen), findsOneWidget);
    });

    testWidgets('a poster typed in the code field does the same', (
      tester,
    ) async {
      await _tall(tester);
      final h = harness();
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('player-address')), '');
      await tester.enterText(find.byKey(const Key('player-code')), poster);
      await _tap(tester, 'player-connect');
      expect(find.byType(CheckinScreen), findsOneWidget);
    });

    testWidgets('a scoreboard link connects as before', (tester) async {
      await _tall(tester);
      final uris = <Uri>[];
      final h = harness(
        qr: FakeQr(_scoreboard),
        feedConnect: (uri) async {
          uris.add(uri);
          return _QuietSocket();
        },
      );
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      await _tap(tester, 'player-scan');
      expect(find.byType(PlayerScreen), findsOneWidget);
      expect(uris.single.host, '10.1.1.1');
      expect(h.settings.readToken, 'read-1');
    });

    testWidgets('garbage is still a bad link', (tester) async {
      await _tall(tester);
      final h = harness(qr: FakeQr('hello there'));
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      await _tap(tester, 'player-scan');
      expect(find.text(ptStrings['player.bad_link']!), findsOneWidget);
      expect(find.byType(CheckinScreen), findsNothing);
    });

    testWidgets('a site link says what it is and where to use it', (
      tester,
    ) async {
      await _tall(tester);
      final h = harness(qr: FakeQr(_siteLink));
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      await _tap(tester, 'player-scan');
      expect(find.text(ptStrings['code.is_site_link']!), findsOneWidget);
      expect(find.textContaining('Inscrições online'), findsWidgets);
      expect(find.text(ptStrings['player.bad_link']!), findsNothing);
    });

    testWidgets('a join card says what it is, typed, in English', (
      tester,
    ) async {
      await _tall(tester);
      final h = harness(language: AppLanguage.en);
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const Key('player-address')),
        _joinCard,
      );
      await _tap(tester, 'player-connect');
      expect(find.text(enStrings['code.is_join_card']!), findsOneWidget);
    });

    testWidgets('a corrupt poster opens the check-in, which says so', (
      tester,
    ) async {
      await _tall(tester);
      final h = harness(qr: FakeQr('atalaia:checkin:AAAA'));
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      await _tap(tester, 'player-scan');
      expect(find.byType(CheckinScreen), findsOneWidget);
      expect(find.text(ptStrings['checkin.bad_poster']!), findsOneWidget);
    });
  });

  group('the other scanners', () {
    testWidgets('the check-in: a scoreboard link, a site link, a join card', (
      tester,
    ) async {
      await _tall(tester);
      final qr = FakeQr(_scoreboard);
      final h = harness(qr: qr, language: AppLanguage.de);
      await tester.pumpWidget(h.app(home: const CheckinScreen()));
      await tester.pumpAndSettle();
      for (final (text, key) in [
        (_scoreboard, 'code.is_scoreboard'),
        (_siteLink, 'code.is_site_link'),
        (_joinCard, 'code.is_join_card'),
        ('hello', 'checkin.not_poster'),
      ]) {
        qr.next = text;
        await _tap(tester, 'checkin-scan');
        expect(find.text(deStrings[key]!), findsOneWidget, reason: key);
      }
    });

    testWidgets('the prop join: a poster and a site link', (tester) async {
      await _tall(tester);
      final qr = FakeQr(poster);
      final h = harness(qr: qr, language: AppLanguage.en);
      await tester.pumpWidget(h.app(home: const JoinScreen(title: 'x')));
      await tester.pumpAndSettle();
      await _tap(tester, 'join-scan');
      expect(find.byKey(const Key('join-error')), findsOneWidget);
      expect(find.text(enStrings['code.is_poster']!), findsOneWidget);
      qr.next = _siteLink;
      await _tap(tester, 'join-scan');
      expect(find.text(enStrings['code.is_site_link']!), findsOneWidget);
    });

    testWidgets('the site address: a poster typed', (tester) async {
      await _tall(tester);
      final h = harness(language: AppLanguage.zhTw);
      await tester.pumpWidget(h.app(home: const SiteScreen()));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('site-address')), poster);
      await _tap(tester, 'site-open');
      expect(find.text(zhTwStrings['code.is_poster']!), findsOneWidget);
      await tester.enterText(find.byKey(const Key('site-address')), 'ola');
      await _tap(tester, 'site-open');
      expect(find.text(zhTwStrings['site.bad_address']!), findsOneWidget);
    });

    testWidgets('the replica registry: a poster is not a replica label', (
      tester,
    ) async {
      await _tall(tester);
      final qr = FakeQr(poster);
      final h = harness(qr: qr);
      final records = MarshalRecords(h.store, h.settings);
      await records.load();
      await tester.pumpWidget(h.app(home: ReplicaFormScreen(records: records)));
      await tester.pumpAndSettle();
      await _tap(tester, 'replica-scan');
      expect(find.text(ptStrings['code.is_poster']!), findsOneWidget);
      expect(find.textContaining('Etiqueta:'), findsNothing);
    });
  });
}
