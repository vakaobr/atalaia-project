// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The player's own game history in the app (lib/site/history_screens.dart,
// decision S20-8) against a fake site server (test/support/fake_site.dart):
// the list newest first, a game's scores and winner, the player's own
// events in words with their own id shown as "you", a tie, a game with no
// events, no games, the site not reachable, and both languages' texts.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/l10n/strings_en.dart';
import 'package:atalaia_app/l10n/strings_pt.dart';
import 'package:atalaia_app/site/history_screens.dart';
import 'package:atalaia_app/site/site_api.dart';
import 'package:atalaia_app/site/site_screens.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';
import '../support/fake_site.dart';
import 'site_screens_test.dart' show back, login, tapKey;

const gameA = '0192f3a0-0000-7000-8000-0000000000a1';
const gameB = '0192f3a0-0000-7000-8000-0000000000a2';

/// The field's page, logged in.
Future<void> openField(WidgetTester tester, FakeSite site) async {
  await tester.enterText(
    find.byKey(const Key('site-address')),
    'https://campo.example.pt/f/campo-norte',
  );
  await tapKey(tester, 'site-open');
  await tapKey(tester, 'site-confirm');
  await login(tester, site);
}

void main() {
  testWidgets('the games, newest first; a game\'s scores, winner and own '
      'events', (tester) async {
    final site = FakeSite();
    final h = harness(language: AppLanguage.en, siteHttp: site.http);
    await tester.pumpWidget(h.app(home: const SiteScreen()));
    await tester.pumpAndSettle();
    await openField(tester, site);
    await tapKey(tester, 'site-history');
    expect(site.requests, contains('GET /me/data'));

    final newer = find.byKey(const Key('history-game-$gameB'));
    final older = find.byKey(const Key('history-game-$gameA'));
    expect(newer, findsOneWidget);
    expect(older, findsOneWidget);
    expect(
      tester.getTopLeft(newer).dy,
      lessThan(tester.getTopLeft(older).dy),
      reason: 'newest first',
    );
    // The older game has a winner in its line; the other ended in a tie.
    expect(
      find.descendant(of: older, matching: find.textContaining('Winner: red')),
      findsOneWidget,
    );
    expect(
      find.descendant(of: newer, matching: find.textContaining('Winner')),
      findsNothing,
    );

    await tester.tap(older);
    await tester.pumpAndSettle();
    expect(find.text('Sábado de Domination'), findsOneWidget);
    expect(find.textContaining('At Campo Norte'), findsOneWidget);
    expect(find.text('You were checked in to this game.'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('history-score-red')),
        matching: find.text('120'),
      ),
      findsOneWidget,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('history-score-blue')),
        matching: find.text('90'),
      ),
      findsOneWidget,
    );
    expect(find.text('Winner: red'), findsOneWidget);
    // Own events, in words, with the player's own id as "you"; game time.
    expect(find.text('you checked in'), findsOneWidget);
    expect(find.text('1:05'), findsOneWidget);
    expect(find.text('Points for red: 5'), findsOneWidget);
    expect(find.text('1:02:05'), findsOneWidget);
    expect(find.textContaining('p-sitemade2345'), findsNothing);
    await back(tester);

    await tester.tap(newer);
    await tester.pumpAndSettle();
    expect(find.text('No winner (a tie, or no points).'), findsOneWidget);
    expect(find.byKey(const Key('history-no-events')), findsOneWidget);
  });

  testWidgets('no games yet, and the site out of reach', (tester) async {
    final site = FakeSite()..history.clear();
    final h = harness(language: AppLanguage.pt, siteHttp: site.http);
    await tester.pumpWidget(h.app(home: const SiteScreen()));
    await tester.pumpAndSettle();
    await openField(tester, site);
    await tapKey(tester, 'site-history');
    expect(find.byKey(const Key('history-none')), findsOneWidget);
    expect(find.text('Histórico de jogos'), findsWidgets);

    site.offline = true;
    await tester.tap(find.byKey(const Key('history-reload')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('history-error')), findsOneWidget);
    expect(find.byKey(const Key('history-none')), findsNothing);

    site.offline = false;
    site.history.add({
      'game': gameA,
      'field': 'Campo Norte',
      'name': 'Domingo',
      'teams': ['red', 'blue'],
      'state': 'running',
      'started_at': '2026-10-25T09:00:00+00:00',
      'ended_at': null,
      'player_ids': ['p-1'],
      'registered': false,
      'events': <Object?>[],
      'totals': <String, Object?>{},
    });
    await tester.tap(find.byKey(const Key('history-reload')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('history-game-$gameA')), findsOneWidget);
    expect(find.textContaining('A decorrer'), findsOneWidget);
  });

  testWidgets('the game history hides housekeeping events', (tester) async {
    final h = harness(language: AppLanguage.en);
    final g = HistoryGame({
      'game': 'g',
      'name': 'Sábado',
      'teams': ['red', 'blue'],
      'player_ids': ['p-1'],
      'totals': {'red': 5, 'blue': 0},
      'events': [
        {
          't': 1000,
          'type': 'node.setup_applied',
          'data': {'kind': 'scenario'},
        },
        {
          't': 2000,
          'type': 'zone.captured',
          'team': 'red',
          'data': {'zone': 'Bridge'},
        },
      ],
    });
    await tester.pumpWidget(h.app(home: GameHistoryDetailScreen(g)));
    await tester.pumpAndSettle();
    expect(find.text('node.setup_applied'), findsNothing);
    expect(find.text('red captured Bridge'), findsOneWidget);
  });

  test('the model: the site server\'s winner rule, and a sparse answer', () {
    final g = HistoryGame({
      'game': 'g',
      'totals': {'red': 3, 'blue': 3},
    });
    expect(g.winner, isNull);
    expect(g.events, isEmpty);
    expect(g.state, 'ended');
    expect(
      HistoryGame({
        'game': 'g',
        'totals': {'red': 0, 'blue': 0},
      }).winner,
      isNull,
    );
    expect(
      HistoryGame({
        'game': 'g',
        'totals': {'red': 4, 'blue': 1},
      }).winner,
      'red',
    );
    expect(historyClock(0), '0:00');
    expect(historyClock(59999), '0:59');
    expect(historyClock(3600000), '1:00:00');
  });

  test('the texts exist in every language, with the same placeholders', () {
    final keys = [
      for (final k in enStrings.keys)
        if (k.startsWith('history.') ||
            k == 'prop.pod_reconnecting' ||
            k == 'pod.reconnecting')
          k,
    ];
    expect(keys.length, greaterThan(15));
    for (final k in keys) {
      expect(ptStrings.containsKey(k), isTrue, reason: k);
    }
    for (final s in ['running', 'paused', 'ready', 'ended']) {
      expect(enStrings, contains('history.state.$s'));
    }
  });
}
