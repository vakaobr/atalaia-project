// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The main screens in European Portuguese and English, on a 360x780 phone:
// the role selector, a prop's game (Bomb counting down, its team buttons),
// setting up a prop's game, the player's view (and of a scenario's game,
// phase 4 plan phase 8), the marshal's chrono with a
// PASS, and the settings. Drawn with Roboto, as on Android.

import 'dart:io';

import 'package:atalaia_app/chrono/chrono_ui.dart';
import 'package:atalaia_app/chrono/limit_template.dart';
import 'package:atalaia_app/chrono/reading.dart';
import 'package:atalaia_app/chrono/replica.dart';
import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/marshal/marshal_records.dart';
import 'package:atalaia_app/modes/mode_catalog.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/gm_screen.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/prop/prop_game.dart';
import 'package:atalaia_app/prop/prop_session.dart';
import 'package:atalaia_app/prop/prop_setup.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/ui/settings_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fakes.dart';
import '../support/scenario_feed.dart';

Future<void> phone(WidgetTester tester) async {
  tester.view.physicalSize = const Size(360, 780);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
}

Future<void> snap(WidgetTester tester, String name, AppLanguage lang) =>
    expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('images/screens/${name}_${lang.code}.png'),
    );

void main() {
  for (final lang in AppLanguage.values) {
    testWidgets('home (${lang.code})', (tester) async {
      await phone(tester);
      await tester.pumpWidget(harness(language: lang).app());
      await tester.pumpAndSettle();
      await snap(tester, 'home', lang);
    });

    testWidgets('player start with a prefilled address (${lang.code})', (
      tester,
    ) async {
      await phone(tester);
      final h = harness(
        language: lang,
        settings: AppSettings()..controllerUrl = 'http://192.168.4.1:8080',
      );
      await tester.pumpWidget(h.app(home: const PlayerStartScreen()));
      await tester.pumpAndSettle();
      await snap(tester, 'player_start', lang);
    });

    testWidgets('GM console address, prefilled (${lang.code})', (tester) async {
      await phone(tester);
      final h = harness(
        language: lang,
        settings: AppSettings()
          ..consoleUrl = 'http://192.168.4.1:8080/console/',
      );
      await tester.pumpWidget(h.app(home: const GmScreen()));
      await tester.pumpAndSettle();
      await snap(tester, 'gm_address', lang);
    });

    testWidgets('settings (${lang.code})', (tester) async {
      await phone(tester);
      final h = harness(
        language: lang,
        settings: AppSettings()..joinKeyHex = 'ab' * 32,
      );
      await tester.pumpWidget(h.app(home: const SettingsScreen()));
      await tester.pumpAndSettle();
      await snap(tester, 'settings', lang);
    });

    testWidgets('prop setup (${lang.code})', (tester) async {
      await phone(tester);
      await tester.pumpWidget(
        harness(language: lang).app(home: const PropSetupScreen()),
      );
      await tester.pumpAndSettle();
      await snap(tester, 'prop_setup', lang);
    });

    testWidgets('prop game: Bomb counting down (${lang.code})', (tester) async {
      await phone(tester);
      final runner = FakeNodeRunner();
      final catalog = ModeCatalog.builtin();
      final mode = catalog.compose('org.atalaia.bomb');
      const teams = ['red', 'blue'];
      final setup = PropSetup(
        mode: mode,
        role: 'bomb',
        teams: teams,
        params: mode.resolveParams(const {}, teams),
        durationMs: 30 * 60000,
      );
      final h = harness(language: lang, runner: runner);
      await tester.pumpWidget(
        h.app(
          home: PropGameScreen(setup: setup, modeName: mode.name(lang.code)),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('prop-start')));
      await tester.pumpAndSettle();
      await tester.tap(
        find.descendant(
          of: find.byType(AlertDialog),
          matching: find.byType(FilledButton),
        ),
      );
      await tester.pumpAndSettle();
      runner.node
        ..timeMs = 13000
        ..screen('countdown', {'left': 287});
      await tester.pump(const Duration(milliseconds: 300));
      await snap(tester, 'prop_game', lang);
    });

    testWidgets('player view (${lang.code})', (tester) async {
      await phone(tester);
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
          },
          'score': {
            'game': 7,
            'teams': {'red': 12, 'blue': 20},
          },
          'nodes': [
            {'node_id': 2, 'name': 'Moinho', 'owner': 'blue'},
            {'node_id': 3, 'name': 'Ponte', 'owner': 'red'},
          ],
        })
        ..onMessage({
          'type': 'event',
          'game': 7,
          'event': {
            'node': 2,
            't': 590000,
            'type': 'zone.captured',
            'team': 'blue',
            'data': {'zone': 'Moinho'},
          },
        });
      final h = harness(
        language: lang,
        settings: AppSettings()..myTeam = 'blue',
      );
      await tester.pumpWidget(
        h.app(
          home: PlayerScreen(link: link, feed: feed),
        ),
      );
      await tester.pumpAndSettle();
      await snap(tester, 'player', lang);
    });

    testWidgets('player view of a scenario (${lang.code})', (tester) async {
      await phone(tester);
      tester.view.physicalSize = const Size(360, 1100);
      final feed = scenarioFeed();
      final h = harness(
        language: lang,
        settings: AppSettings()..myTeam = 'red',
      );
      await tester.pumpWidget(
        h.app(
          home: PlayerScreen(link: feed.link, feed: feed),
        ),
      );
      await tester.pumpAndSettle();
      await snap(tester, 'player_scenario', lang);
    });

    testWidgets('chrono check-in: PASS (${lang.code})', (tester) async {
      await phone(tester);
      tester.view.physicalSize = const Size(360, 1500);
      final settings = AppSettings()
        ..marshalName = 'Ana'
        ..marshalId = 'm-1';
      final h = harness(language: lang, settings: settings);
      final records = MarshalRecords(
        h.store,
        settings,
        now: () => DateTime.utc(2026, 10, 19, 9),
      );
      final replica = Replica(
        replicaId: newUuid(),
        ownerPlayerId: 'p-17',
        type: ReplicaType.aeg,
        replicaClass: 'rifle',
        makeModel: 'M4 CQB',
        registeredAt: '2026-10-19T08:00:00Z',
        tagType: TagType.nfc,
        tagUid: '04:A1:B2:C3',
      );
      await tester.runAsync(() async {
        await records.load();
        await records.newKey();
        await records.addReplica(replica);
      });
      final templates = [
        LimitTemplate.parse(
          File('lib/chrono/limit_templates/portugal.yaml').readAsStringSync(),
        ),
      ];
      await tester.pumpWidget(
        h.app(
          home: ChronoScreen(records: records, templates: templates),
        ),
      );
      await tester.pumpAndSettle();
      h.nfc.tap(NfcReadFake.card(const [], [4, 0xa1, 0xb2, 0xc3]));
      await tester.pumpAndSettle();
      for (final k in ['9', '6', '.', '2']) {
        await tester.tap(find.byKey(Key('chrono-key-$k')));
        await tester.pump();
      }
      await tester.runAsync(() async {
        await tester.tap(find.byKey(const Key('chrono-record')));
        await Future<void>.delayed(const Duration(milliseconds: 200));
      });
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('chrono-result-pass')), findsOneWidget);
      // On the phone's own screen size, scrolled to the keypad and the result.
      tester.view.physicalSize = const Size(360, 780);
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byKey(const Key('chrono-result-pass')),
        300,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.pumpAndSettle();
      await snap(tester, 'chrono', lang);
    });
  }
}
