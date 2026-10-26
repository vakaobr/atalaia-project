// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A squad's objective chain in the player view (decisions SQ-1 to SQ-8): the
// squad leader's phone gets the active objective with its names and the next
// one when it is revealed; a member's phone, in a game that tells the leader
// alone, gets "your squad leader has new orders" and no objective, nothing of
// a later one in its feed, and a short vibration when new orders arrive.

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';

Map<String, Object?> _objective(
  String id,
  String name, {
  bool hidden = false,
}) => {
  'id': id,
  'type': 'capture_and_hold',
  'name': name,
  'i18n': {
    'pt': {'name': '$name (pt)'},
  },
  'team': 'red',
  'squad': 1,
  'visibility': hidden ? 'hidden' : 'squad',
};

Map<String, Object?> _game(List<Map<String, Object?>> objectives) => {
  'id': 7,
  'name': 'Chains',
  'teams': ['red', 'blue'],
  'state': 'running',
  'duration_ms': 3600000,
  'game_time_ms': 1000,
  'live': true,
  'squads': 2,
  'scenario': {
    'id': 'org.club.chains',
    'name': 'Chains',
    'objectives': objectives,
  },
};

Map<String, Object?> _revealed({String? objective}) => {
  'type': 'event',
  'game': 7,
  'event': {
    'node': 0,
    't': 5000,
    'type': 'scenario.objective.revealed',
    'team': 'red',
    'data': {
      'objective': ?objective,
      'team': 'red',
      'squad': '1',
      if (objective == null) 'leader_only': true,
    },
  },
};

FieldFeed _feed(
  Map<String, Object?> game, {
  List<Map<String, Object?>> events = const [],
}) {
  final feed = FieldFeed(
    FieldLink.parse('10.0.0.1', 'c')!,
    connect: (_) => Future.error(StateError('offline')),
    now: () => DateTime(2026, 10, 26, 15),
  );
  return feed
    ..state = FeedState.open
    ..onMessage({'type': 'hello', 'game': game, 'events': events});
}

Future<Harness> _show(
  WidgetTester tester,
  FieldFeed feed,
  AppLanguage lang,
) async {
  tester.view.physicalSize = const Size(360, 2400);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  addTearDown(feed.dispose);
  final h = harness(language: lang, settings: AppSettings()..myTeam = 'red');
  await tester.pumpWidget(
    h.app(
      home: PlayerScreen(link: feed.link, feed: feed),
    ),
  );
  await tester.pumpAndSettle();
  return h;
}

List<String> _vibrations(Harness h) => [
  for (final c in h.device.calls)
    if (c.startsWith('vibrate')) c,
];

void main() {
  testWidgets("the leader's phone shows the active objective, then the next, "
      'and buzzes', (tester) async {
    final feed = _feed(_game([_objective('a1', 'Alpha one')]));
    final h = await _show(tester, feed, AppLanguage.en);
    expect(find.byKey(const Key('player-objective-a1')), findsOneWidget);
    expect(find.byKey(const Key('player-objective-a2')), findsNothing);
    expect(find.byKey(const Key('player-leader-orders')), findsNothing);
    expect(_vibrations(h), isEmpty); // what came with the hello is not news

    // a1 is completed: the controller sends the game again with a2 and the
    // event that reveals it.
    feed
      ..onMessage({
        'type': 'game',
        'game': _game([
          _objective('a1', 'Alpha one'),
          _objective('a2', 'Alpha two', hidden: true),
        ]),
      })
      ..onMessage(_revealed(objective: 'a2'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('player-objective-a2')), findsOneWidget);
    expect(find.text('A new objective for red: Alpha two'), findsOneWidget);
    expect(_vibrations(h), ['vibrate [0, 250, 120, 250]']);
    expect(find.byKey(const Key('player-objective-a3')), findsNothing);
  });

  testWidgets('a member is told only that the leader has orders, in every '
      'language', (tester) async {
    final texts = {
      AppLanguage.en: [
        'Your squad leader has new orders',
        'Orders for your squad: your squad leader will pass them on',
      ],
      AppLanguage.pt: [
        'O teu líder de squad tem novas ordens',
        'Ordens para o teu squad: o líder de squad passa-as',
      ],
      AppLanguage.de: [
        'Dein Squad-Lead hat neue Befehle',
        'Befehle für dein Squad: Dein Squad-Lead gibt sie weiter',
      ],
      AppLanguage.zhTw: ['你的小隊長有新的任務', '給你小隊的任務：小隊長會通知大家'],
    };
    for (final e in texts.entries) {
      final feed = _feed(_game(const []));
      final h = await _show(tester, feed, e.key);
      expect(find.byKey(const Key('player-leader-orders')), findsNothing);
      feed.onMessage(_revealed());
      await tester.pumpAndSettle();
      expect(find.text(e.value[0]), findsOneWidget, reason: '${e.key}');
      expect(find.text(e.value[1]), findsOneWidget, reason: '${e.key}');
      expect(find.byKey(const Key('player-scenario')), findsNothing);
      expect(feed.objectives, isEmpty);
      expect(feed.leaderOrders, 1);
      expect(_vibrations(h), ['vibrate [0, 250, 120, 250]']);
      await tester.pumpWidget(const SizedBox());
    }
  });

  testWidgets('news of another squad does not buzz or say anything', (
    tester,
  ) async {
    final feed = _feed(_game(const []));
    final h = await _show(tester, feed, AppLanguage.en);
    feed.onMessage({
      'type': 'event',
      'game': 7,
      'event': {
        'node': 0,
        't': 6000,
        'type': 'scenario.objective.revealed',
        'team': 'red',
        'data': {'team': 'red', 'squad': '2'},
      },
    });
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('player-leader-orders')), findsNothing);
    expect(_vibrations(h), isEmpty);
    expect(find.text('A new objective for red'), findsOneWidget);
  });

  testWidgets('what the list starts with does not buzz, and the notice stays '
      'after a reconnect', (tester) async {
    final feed = _feed(
      _game(const []),
      events: [(_revealed()['event']! as Map<String, Object?>)],
    );
    final h = await _show(tester, feed, AppLanguage.en);
    expect(find.byKey(const Key('player-leader-orders')), findsOneWidget);
    expect(_vibrations(h), isEmpty);
  });
}
