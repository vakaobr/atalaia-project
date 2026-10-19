// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The field's branding on the app's screens (decisions BR16-BR21): the
// player's view with the logo in the header, the dimmed wallpaper, the
// accent as the primary colour and the teams' crests and names; the same
// view without branding (the default look); and an Android prop that
// joined the field's game: the wallpaper and logo on its idle screen only,
// the crests and names on its team buttons, the colours unchanged.

import 'dart:typed_data';

import 'package:atalaia_app/branding/branded.dart';
import 'package:atalaia_app/branding/field_branding.dart';
import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/prop/prop_game.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/ui/theme.dart';
import 'package:atalaia_app/ui/widgets.dart';
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

FieldFeed playerFeed({Map<String, Object?>? teamInfo}) {
  final link = FieldLink.parse('10.0.0.1', 'c')!;
  return FieldFeed(link, connect: (_) => Future.error(StateError('offline')))
    ..state = FeedState.open
    ..onMessage({
      'type': 'hello',
      'game': {
        'id': 7,
        'name': 'Domingo no Moinho',
        'teams': ['red', 'blue'],
        'state': 'running',
        'game_time_ms': 600000,
        'live': true,
        'team_info': ?teamInfo,
      },
      'score': {
        'game': 7,
        'teams': {'red': 12, 'blue': 20},
      },
      'nodes': [
        {'node_id': 2, 'name': 'Moinho', 'owner': 'red'},
      ],
    });
}

Color primaryOf(WidgetTester tester, Finder f) =>
    Theme.of(tester.element(f)).colorScheme.primary;

/// The image under [key] was decoded (not its fallback).
void expectDecoded(WidgetTester tester, Key key) {
  final raw = find.descendant(
    of: find.byKey(key),
    matching: find.byType(RawImage),
  );
  expect(raw, findsWidgets, reason: '$key');
  expect(tester.widget<RawImage>(raw.first).image, isNotNull, reason: '$key');
  expect(
    find.descendant(of: find.byKey(key), matching: find.byType(TeamDot)),
    findsNothing,
  );
}

void main() {
  testWidgets('player view with the field\'s branding and team crests', (
    tester,
  ) async {
    await phone(tester);
    final field = FakeBrandingField(
      accent: '#ffd400',
      logo: testLogo(),
      wallpaper: testWallpaper(),
    );
    final red = field.addCrest(testCrest(0xFFD7263D));
    final h = harness(brandingSource: (_, _) => field);
    final feed = playerFeed(
      teamInfo: {
        'red': {'display_name': 'Lobos', 'crest_id': red},
        'blue': {'display_name': 'Águias'},
      },
    );
    await tester.pumpWidget(
      h.app(
        home: PlayerScreen(link: feed.link, feed: feed),
      ),
    );
    await tester.pumpAndSettle();
    await decodeImages(tester);
    // The header: logo and name.
    expect(find.byKey(const Key('brand-logo')), findsOneWidget);
    expect(find.byKey(const Key('brand-name')), findsOneWidget);
    expect(find.text('Campo Norte'), findsOneWidget);
    expectDecoded(tester, const Key('brand-logo'));
    expectDecoded(tester, const Key('brand-wallpaper'));
    // The wallpaper under a veil of the theme's background.
    expect(find.byKey(const Key('brand-wallpaper')), findsOneWidget);
    final veil = tester.widget<ColoredBox>(find.byKey(const Key('brand-veil')));
    final light =
        Theme.of(tester.element(find.byType(PlayerView))).brightness ==
        Brightness.light;
    expect(
      veil.color.a,
      closeTo(light ? wallpaperVeilLight : wallpaperVeilDark, 0.01),
    );
    // The accent, made readable, is the primary colour of the view.
    final primary = primaryOf(tester, find.byType(PlayerView));
    expect(
      primary,
      brandPrimary(
        parseAccent('#ffd400')!,
        light ? Brightness.light : Brightness.dark,
      ),
    );
    // Teams: crests and display names; the colour stays the team's.
    expect(find.byKey(const Key('crest-red')), findsWidgets);
    expectDecoded(tester, const Key('crest-red'));
    expect(find.text('LOBOS'), findsOneWidget);
    expect(find.text('ÁGUIAS'), findsOneWidget);
    expect(find.text('Da equipa Lobos'), findsOneWidget);
    final card = tester.widget<Card>(
      find.ancestor(
        of: find.byKey(const Key('player-team-red')),
        matching: find.byType(Card),
      ),
    );
    expect(
      (card.shape! as RoundedRectangleBorder).side.color,
      AtalaiaColors.team('red'),
    );
    // A team without a crest keeps its colour dot.
    expect(find.byKey(const Key('crest-blue')), findsNothing);
    // The stream says the branding changed: the view fetches it again.
    field
      ..fieldName = 'Campo Norte B'
      ..logo = null;
    feed.onMessage({
      'type': 'branding',
      'branding': {'etag': '"new"'},
    });
    await tester.pumpAndSettle();
    expect(find.text('Campo Norte B'), findsOneWidget);
    expect(find.byKey(const Key('brand-logo')), findsNothing);
  });

  testWidgets('player view without branding keeps the default look', (
    tester,
  ) async {
    await phone(tester);
    final h = harness(brandingSource: (_, _) => FakeBrandingField());
    final feed = playerFeed();
    await tester.pumpWidget(
      h.app(
        home: PlayerScreen(link: feed.link, feed: feed),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('brand-logo')), findsNothing);
    expect(find.byKey(const Key('brand-wallpaper')), findsNothing);
    expect(find.byKey(const Key('brand-veil')), findsNothing);
    final theme = Theme.of(tester.element(find.byType(PlayerView)));
    expect(
      theme.colorScheme.primary,
      atalaiaTheme(theme.brightness).colorScheme.primary,
    );
    expect(find.text('VERMELHA'), findsOneWidget);
    // A field that set nothing keeps the default title.
    expect(find.text('Campo Norte'), findsNothing);
    expect(find.text('Participante'), findsOneWidget);
  });

  testWidgets('an image that does not decode falls back to the default', (
    tester,
  ) async {
    await phone(tester);
    final broken = Uint8List.fromList([
      ...testPng(4, 4).sublist(0, 16),
      1,
      2,
      3,
    ]);
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Row(
            children: [
              TeamCrest(team: 'red', crest: broken),
              BrandLogo(
                branding: FieldBranding(
                  fieldId: 'f',
                  fieldName: 'F',
                  logo: BrandImage(id: 'x', bytes: broken),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 200)),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    // The crest's fallback is the colour dot.
    expect(find.byType(TeamDot), findsOneWidget);
  });

  testWidgets(
    'a prop that joined the field: idle wallpaper, crests on buttons',
    (tester) async {
      await phone(tester);
      final ca = FakeField();
      final field = FakeBrandingField(
        accent: '#c0ffee',
        logo: testLogo(),
        wallpaper: testWallpaper(),
      );
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
      final h = harness(caFetch: ca.fetchCa, brandingSource: (_, _) => field);
      await tester.pumpWidget(
        h.app(
          home: PropGameScreen(
            setup: setup,
            session: session,
            modeName: 'Domínio',
          ),
        ),
      );
      await tester.pumpAndSettle();
      await decodeImages(tester);
      expect(field.requests, contains('/api/v1/games/9/teams'));
      // Idle: the wallpaper (dark veil) and the field's logo and name.
      expect(find.byKey(const Key('brand-wallpaper')), findsOneWidget);
      expect(
        tester.widget<ColoredBox>(find.byKey(const Key('brand-veil'))).color.a,
        closeTo(wallpaperVeilDark, 0.01),
      );
      expect(find.byKey(const Key('prop-field-name')), findsOneWidget);
      expect(
        find.byKey(const Key('brand-logo')),
        findsNWidgets(2),
      ); // bar, screen
      // The accent on the start button.
      final bg = tester
          .widget<Material>(
            find
                .descendant(
                  of: find.byKey(const Key('prop-start')),
                  matching: find.byType(Material),
                )
                .first,
          )
          .color;
      expect(bg, brandPrimary(parseAccent('#c0ffee')!, Brightness.dark));
      // Running: the mode's screen without the wallpaper, buttons with crests.
      await tester.runAsync(session.start);
      await tester.pumpAndSettle();
      await decodeImages(tester);
      expect(find.byKey(const Key('brand-wallpaper')), findsNothing);
      expect(find.byKey(const Key('crest-red')), findsOneWidget);
      expect(find.byKey(const Key('crest-blue')), findsOneWidget);
      expectDecoded(tester, const Key('crest-blue'));
      expect(find.text('Manter premido\nLOBOS'), findsOneWidget);
      final button = tester.widget<AnimatedContainer>(
        find.descendant(
          of: find.byKey(const Key('team-button-red')),
          matching: find.byType(AnimatedContainer),
        ),
      );
      expect(
        (button.decoration! as BoxDecoration).color,
        AtalaiaColors.team('red'),
      );
    },
  );
}
