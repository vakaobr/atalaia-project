// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A field's branding on a 360x780 phone (decisions BR16-BR21): the
// player's view with the field's logo, its wallpaper under the veil (bright
// stripes, the hardest case for the text on top), a yellow accent made
// readable, and two teams with crests and names; and an Android prop of
// that field before its game (the idle screen with the wallpaper and logo)
// and during it (the mode's own screen, no wallpaper, crests on the team
// buttons). The default look without branding is the other golden files,
// which this feature must leave unchanged.

import 'dart:typed_data';

import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/prop/prop_game.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/branding.dart';
import '../support/fake_field.dart';
import '../support/fakes.dart';

Future<void> phone(WidgetTester tester) async {
  tester.view.physicalSize = const Size(360, 780);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> snap(WidgetTester tester, String name, AppLanguage lang) =>
    expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('images/branding/${name}_${lang.code}.png'),
    );

FakeBrandingField brandedField() {
  final f = FakeBrandingField(
    fieldName: 'Campo Norte',
    accent: '#ffd400',
    logo: testLogo(),
    wallpaper: testWallpaper(),
  );
  return f;
}

void main() {
  for (final lang in AppLanguage.values) {
    testWidgets('player view, branded (${lang.code})', (tester) async {
      await phone(tester);
      final field = brandedField();
      final red = field.addCrest(testCrest(0xFFD7263D));
      final blue = field.addCrest(testCrest(0xFF1B6EE0));
      final link = FieldLink.parse('10.0.0.1', 'c')!;
      final feed = FieldFeed(
        link,
        connect: (_) => Future.error(StateError('offline')),
        now: () => DateTime(2026, 10, 19, 15),
      );
      feed
        ..state = FeedState.open
        ..onMessage({
          'type': 'hello',
          'game': {
            'id': 7,
            'name': 'Domingo no Moinho',
            'teams': ['red', 'blue'],
            'state': 'running',
            'duration_ms': 1800000,
            'game_time_ms': 600000,
            'live': true,
            'team_info': {
              'red': {'display_name': 'Lobos', 'crest_id': red},
              'blue': {'display_name': 'Águias', 'crest_id': blue},
            },
          },
          'score': {
            'game': 7,
            'teams': {'red': 12, 'blue': 20},
          },
          'nodes': [
            {'node_id': 2, 'name': 'Moinho', 'owner': 'blue'},
            {'node_id': 3, 'name': 'Ponte', 'owner': 'red'},
          ],
        });
      final h = harness(
        language: lang,
        settings: AppSettings()..myTeam = 'blue',
        brandingSource: (_, _) => field,
      );
      await tester.pumpWidget(
        h.app(
          home: PlayerScreen(link: link, feed: feed),
        ),
      );
      await tester.pumpAndSettle();
      await decodeImages(tester);
      await snap(tester, 'player', lang);
    });

    testWidgets('prop, branded: idle and running (${lang.code})', (
      tester,
    ) async {
      await phone(tester);
      final ca = FakeField();
      final field = brandedField();
      final red = field.addCrest(testCrest(0xFFD7263D));
      final blue = field.addCrest(testCrest(0xFF1B6EE0));
      field.games[9] = {'red': ('Lobos', red), 'blue': ('Águias', blue)};
      final join = JoinPayload(
        gameId: 9,
        gameKey: Uint8List(16),
        nodeId: 3,
        controllerId: 0,
        channelHz: 869525000,
        maxHops: 2,
        teams: const ['red', 'blue'],
        modeId: 'org.atalaia.domination',
        role: 'zone',
        gameSeed: 1,
        params: null,
        kind: JoinKind.node,
        caSha256: ca.sha256Bytes,
        urls: const ['https://10.0.2.2:8443'],
      );
      final mode = ModeCatalog.builtin().compose('org.atalaia.domination');
      const teams = ['red', 'blue'];
      final setup = PropSetup(
        mode: mode,
        role: 'zone',
        teams: teams,
        params: mode.resolveParams(const {}, teams),
        join: join,
      );
      final node = FakeRunningNode();
      final session = PropSession(
        setup: setup,
        runner: FakeNodeRunner(node),
        device: FakeDevice(),
        texts: const PropTexts(
          notificationTitle: 'Atalaia: {mode}',
          notificationRunning: 'running',
          notificationLeft: '{time} left',
        ),
        clock: GameClock.manual,
      );
      addTearDown(session.dispose);
      await tester.runAsync(session.open);
      final h = harness(
        language: lang,
        caFetch: ca.fetchCa,
        brandingSource: (_, _) => field,
      );
      await tester.pumpWidget(
        h.app(
          home: PropGameScreen(
            setup: setup,
            session: session,
            modeName: mode.name(lang.code),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await decodeImages(tester);
      await snap(tester, 'prop_idle', lang);
      await tester.runAsync(session.start);
      node.screen('captured', {'team': 'red', 'points': 12, 'since': 30});
      await tester.pumpAndSettle();
      await decodeImages(tester);
      await snap(tester, 'prop_running', lang);
    });
  }
}
