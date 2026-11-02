// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The player view's scenario objectives (phase 4 plan phase 8, decision
// P4R24): each objective the controller lets this player know, with the
// scenario's translated name and where it stands, and the objective events
// named in the list of what happened, in both languages.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/scenario_feed.dart';

Future<void> show(WidgetTester tester, AppLanguage lang) async {
  tester.view.physicalSize = const Size(360, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final feed = scenarioFeed();
  addTearDown(feed.dispose);
  final h = harness(language: lang, settings: AppSettings()..myTeam = 'red');
  await tester.pumpWidget(
    h.app(
      home: PlayerScreen(link: feed.link, feed: feed),
    ),
  );
  await tester.pumpAndSettle();
}

String subtitle(WidgetTester tester, String id) {
  final tile = tester.widget<ListTile>(find.byKey(Key('player-objective-$id')));
  return (tile.subtitle! as Text).data!;
}

String title(WidgetTester tester, String id) {
  final tile = tester.widget<ListTile>(find.byKey(Key('player-objective-$id')));
  return (tile.title! as Text).data!;
}

void main() {
  testWidgets('the objectives in Portuguese', (tester) async {
    await show(tester, AppLanguage.pt);
    expect(find.text('Objetivos do cenário'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('player-scenario')),
        matching: find.text('Operação Moinho'),
      ),
      findsOneWidget,
    );
    expect(title(tester, 'bridge'), 'Tomar a ponte');
    expect(subtitle(tester, 'bridge'), 'Cumprido pela equipa vermelha');
    expect(title(tester, 'vault'), 'Abrir o cofre');
    expect(
      subtitle(tester, 'vault'),
      'Em curso · Para a equipa vermelha, squad 1',
    );
    expect(
      subtitle(tester, 'mill'),
      'Falhado: o tempo acabou · Para a equipa vermelha',
    );
    expect(find.text('+100'), findsOneWidget);
    // What happened names the objectives too.
    expect(
      find.text('A equipa vermelha cumpriu: Tomar a ponte'),
      findsOneWidget,
    );
    expect(
      find.text('Novo objetivo para a equipa vermelha: Abrir o cofre'),
      findsOneWidget,
    );
    expect(find.text('Novo objetivo: Tomar a ponte'), findsOneWidget);
    expect(
      find.text('A equipa vermelha falhou: Defender o moinho'),
      findsOneWidget,
    );
  });

  testWidgets('the objectives in English', (tester) async {
    await show(tester, AppLanguage.en);
    expect(find.text('Scenario objectives'), findsOneWidget);
    expect(title(tester, 'bridge'), 'Take the bridge');
    expect(subtitle(tester, 'bridge'), 'Completed by red');
    expect(subtitle(tester, 'vault'), 'In progress · For red, squad 1');
    expect(subtitle(tester, 'mill'), 'Failed: out of time · For red');
    expect(find.text('red completed: Take the bridge'), findsOneWidget);
  });

  test('an objective is named only when the game names it', () {
    const s = Strings(AppLanguage.pt);
    final feed = scenarioFeed();
    addTearDown(feed.dispose);
    final names = {for (final o in feed.objectives) o.id: o.name('pt')};
    final hidden = feed.events.firstWhere((e) => e.type.endsWith('failed'));
    expect(
      eventText(s, hidden, null, names),
      'A equipa vermelha falhou: Defender o moinho',
    );
    expect(eventText(s, hidden), 'A equipa vermelha falhou um objetivo');
  });

  testWidgets('housekeeping events stay out of the list, game events stay', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(360, 2400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);
    final feed = scenarioFeed();
    addTearDown(feed.dispose);
    Map<String, Object?> msg(Map<String, Object?> e) => {
      'type': 'event',
      'event': e,
    };
    feed
      ..onMessage(
        msg({
          'node': 3,
          't': 700000,
          'type': 'node.setup_applied',
          'data': {'kind': 'scenario'},
        }),
      )
      ..onMessage(
        msg({
          'node': 3,
          't': 710000,
          'type': 'zone.captured',
          'team': 'red',
          'data': {'zone': 'Bridge'},
        }),
      );
    final h = harness(
      language: AppLanguage.en,
      settings: AppSettings()..myTeam = 'red',
    );
    await tester.pumpWidget(
      h.app(
        home: PlayerScreen(link: feed.link, feed: feed),
      ),
    );
    await tester.pumpAndSettle();
    // The feed keeps both; the list draws only what a player cares about.
    expect(feed.events.map((e) => e.type), contains('node.setup_applied'));
    expect(find.text('node.setup_applied'), findsNothing);
    expect(find.text('red captured Bridge'), findsOneWidget);
    expect(isPlayerFeedEvent('node.setup_applied'), isFalse);
    expect(isPlayerFeedEvent('zone.captured'), isTrue);
  });
}
