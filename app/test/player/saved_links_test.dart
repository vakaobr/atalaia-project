// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// CA-pinned scoreboard links are remembered per field, by the CA's
// fingerprint (decision APX-2, amending SQR-4): the player does not scan
// again; a link whose CA no longer matches is forgotten.

import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/l10n/strings_en.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/player/saved_links.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_field.dart';
import '../support/fakes.dart';

FieldLink _link(String host, String ca, [String token = 'rd-1']) =>
    FieldLink.parse('https://$host:8443/scoreboard#token=$token&ca=$ca')!;

void main() {
  final field = FakeField();
  final caHex = hexEncode(field.sha256Bytes);
  const hostA = '10.42.0.1';

  group('SavedLinks', () {
    test('remembers by CA, newest first; one per address and per CA', () async {
      final h = harness();
      final saved = SavedLinks(h.store);
      expect(await saved.load(), isEmpty);
      await saved.remember(_link(hostA, 'aa' * 32));
      await saved.remember(_link('10.42.0.2', 'bb' * 32, 'rd-2'));
      var got = await saved.load();
      expect(got.map((l) => l.base.host), ['10.42.0.2', hostA]);
      expect(got.last.token, 'rd-1');
      expect(hexEncode(got.last.caSha256!), 'aa' * 32);
      // The same address with another fingerprint: the CA changed, the old
      // entry is gone.
      await saved.remember(_link(hostA, 'cc' * 32, 'rd-3'));
      got = await saved.load();
      expect(got.map((l) => hexEncode(l.caSha256!)), ['cc' * 32, 'bb' * 32]);
      // The same fingerprint again: replaced, not doubled.
      await saved.remember(_link('10.42.0.9', 'cc' * 32, 'rd-4'));
      got = await saved.load();
      expect(got.map((l) => l.token), ['rd-4', 'rd-2']);
      await saved.forget(hexDecode('bb' * 32));
      expect((await saved.load()).single.token, 'rd-4');
    });

    test('a link without a CA is not remembered; the list is capped', () async {
      final saved = SavedLinks(harness().store);
      await saved.remember(FieldLink.parse('http://10.0.0.1:8080/s#token=t')!);
      expect(await saved.load(), isEmpty);
      for (var i = 0; i < savedLinksMax + 3; i++) {
        await saved.remember(
          _link('10.1.0.$i', i.toRadixString(16).padLeft(64, '0')),
        );
      }
      final got = await saved.load();
      expect(got, hasLength(savedLinksMax));
      expect(got.first.base.host, '10.1.0.${savedLinksMax + 2}');
    });
  });

  group('the player start screen', () {
    Future<void> tall(WidgetTester tester) async {
      tester.view.physicalSize = const Size(800, 2200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
    }

    testWidgets('a scanned CA link is kept and offered next time', (
      tester,
    ) async {
      await tall(tester);
      final h = harness(
        qr: FakeQr('https://$hostA:8443/scoreboard#token=rd-9&ca=$caHex'),
        caFetch: field.fetchCa,
      );
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      expect(
        find.byKey(Key('player-saved-${caHex.substring(0, 8)}')),
        findsNothing,
      );
      await tester.tap(find.byKey(const Key('player-scan')));
      await tester.pumpAndSettle();
      expect(find.byType(PlayerScreen), findsOneWidget);
      // The address field stays as before (no https address without its CA).
      expect(h.settings.controllerUrl, isNull);
      expect((await SavedLinks(h.store).load()).single.token, 'rd-9');

      // A new visit to the start screen offers it; one tap connects, with
      // the CA checked again.
      final fetches = field.caFetches;
      await tester.pumpWidget(const SizedBox());
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      final tile = find.byKey(Key('player-saved-${caHex.substring(0, 8)}'));
      expect(tile, findsOneWidget);
      await tester.tap(tile);
      await tester.pumpAndSettle();
      expect(find.byType(PlayerScreen), findsOneWidget);
      expect(field.caFetches, fetches + 1);
    });

    testWidgets('a CA that changed is refused and forgotten', (tester) async {
      await tall(tester);
      final other = FakeField(
        der: Uint8List.fromList(utf8.encode('another CA')),
      );
      final h = harness(language: AppLanguage.en, caFetch: other.fetchCa);
      await SavedLinks(h.store).remember(_link(hostA, caHex));
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      final tile = find.byKey(Key('player-saved-${caHex.substring(0, 8)}'));
      expect(tile, findsOneWidget);
      await tester.tap(tile);
      await tester.pumpAndSettle();
      expect(find.byType(PlayerScreen), findsNothing);
      expect(find.text(enStrings['player.link_mismatch']!), findsOneWidget);
      expect(tile, findsNothing);
      expect(await SavedLinks(h.store).load(), isEmpty);
    });

    testWidgets('an unreachable field keeps its entry; delete forgets it', (
      tester,
    ) async {
      await tall(tester);
      final off = FakeField()..offline = true;
      final h = harness(caFetch: off.fetchCa);
      await SavedLinks(h.store).remember(_link(hostA, caHex));
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      final tile = find.byKey(Key('player-saved-${caHex.substring(0, 8)}'));
      await tester.tap(tile);
      await tester.pumpAndSettle();
      expect(find.byType(PlayerScreen), findsNothing);
      expect(tile, findsOneWidget);
      await tester.tap(find.byIcon(Icons.delete_outline));
      await tester.pumpAndSettle();
      expect(tile, findsNothing);
      expect(await SavedLinks(h.store).load(), isEmpty);
    });
  });
}
