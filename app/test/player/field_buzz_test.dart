// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The player's buzzes on key game events (decisions VB-1 to VB-9): which
// events buzz (a GM message, a box of the player's team captured or lost, the
// game starting and ending, and Progressive Domination's next box), the setting that turns them off, one buzz for a
// burst, and none for what a connection starts with (a reconnect's snapshot).

import 'package:atalaia_app/l10n/strings.dart';
import 'package:atalaia_app/player/field_buzz.dart';
import 'package:atalaia_app/player/field_feed.dart';
import 'package:atalaia_app/player/player_screens.dart';
import 'package:atalaia_app/storage/app_store.dart';
import 'package:atalaia_app/ui/settings_screen.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/app_harness.dart';

FeedEvent _ev(String type, {String? team, Map<String, Object?>? data}) =>
    FeedEvent(type, team, data ?? const {}, 1000, 1);

Map<String, Object?> _wire(
  String type, {
  String? team,
  Map<String, Object?> data = const {},
}) => {'node': 1, 't': 9000, 'type': type, 'team': ?team, 'data': data};

Map<String, Object?> _live(Map<String, Object?> event) => {
  'type': 'event',
  'game': 7,
  'event': event,
};

void main() {
  group('FieldBuzzer', () {
    late List<List<int>> played;
    late DateTime clock;
    late bool on;
    late String? team;

    FieldBuzzer make({String? role}) => FieldBuzzer(
      vibrate: played.add,
      enabled: () => on,
      team: () => team,
      role: () => role,
      now: () => clock,
    );

    setUp(() {
      played = [];
      clock = DateTime(2026, 10, 26, 15);
      on = true;
      team = 'red';
    });

    test('the events that buzz, each with its own pattern', () {
      final b = make();
      void at(FeedEvent e, Buzz? expected) {
        clock = clock.add(const Duration(seconds: 5));
        expect(b.onEvent(e), expected, reason: e.type);
      }

      at(_ev('gm.message', data: {'text': 'hi'}), Buzz.gmMessage);
      at(_ev('game.start'), Buzz.gameStart);
      at(_ev('game.end'), Buzz.gameEnd);
      at(_ev('zone.captured', team: 'red'), Buzz.captured);
      at(
        _ev('zone.captured', team: 'blue', data: {'previous_team': 'red'}),
        Buzz.lost,
      );
      at(_ev('zone.neutralized', data: {'previous_team': 'red'}), Buzz.lost);
      expect(played.length, 6);
      // distinct patterns, short; the GM's is the longest single pulse of the
      // routine ones
      expect({for (final b in Buzz.values) b.pattern.join(',')}.length, 6);
      for (final b in Buzz.values) {
        expect(b.pattern.first, 0);
        expect(b.pattern.fold(0, (a, x) => a + x), lessThan(600));
      }
      expect(Buzz.gmMessage.pattern[1], greaterThan(Buzz.captured.pattern[1]));
      expect(Buzz.gmMessage.pattern[1], greaterThan(Buzz.lost.pattern[1]));
      expect(Buzz.gmMessage.pattern[1], greaterThan(Buzz.gameStart.pattern[1]));
    });

    test(
      'Progressive Domination: the next box buzzes both teams (PD-MODE-21)',
      () {
        final b = make();
        void at(FeedEvent e, Buzz? expected) {
          clock = clock.add(const Duration(seconds: 5));
          expect(b.onEvent(e), expected, reason: e.type);
        }

        // activation: no team in the event, felt by every team, and by a phone
        // that does not know its team yet
        at(
          _ev('progressive.activated', data: {'zone': 'A', 'step': 1}),
          Buzz.boxActivated,
        );
        team = null;
        at(
          _ev('progressive.activated', data: {'zone': 'B', 'step': 2}),
          Buzz.boxActivated,
        );
        team = 'red';
        // completed by the player's own team: a capture; by the other: a loss
        at(
          _ev('progressive.completed', team: 'red', data: {'zone': 'A'}),
          Buzz.captured,
        );
        at(
          _ev('progressive.completed', team: 'blue', data: {'zone': 'B'}),
          Buzz.lost,
        );
        // no team known, or no team in the event: nothing to say
        at(_ev('progressive.completed', data: {'zone': 'C'}), null);
        team = null;
        at(_ev('progressive.completed', team: 'red'), null);
        expect(played, [
          Buzz.boxActivated.pattern,
          Buzz.boxActivated.pattern,
          Buzz.captured.pattern,
          Buzz.lost.pattern,
        ]);
        expect(Buzz.boxActivated.pattern, isNot(Buzz.gameEnd.pattern));
      },
    );

    test(
      'the activation buzz follows the setting, the spectator rule and the rate limit',
      () {
        on = false;
        final off = make();
        expect(off.onEvent(_ev('progressive.activated')), isNull);
        on = true;
        expect(
          make(role: 'spectator').onEvent(_ev('progressive.activated')),
          isNull,
        );
        final b = make();
        // activation right after a completion of the player's team: one buzz
        expect(
          b.onEvent(_ev('progressive.completed', team: 'red')),
          Buzz.captured,
        );
        expect(b.onEvent(_ev('progressive.activated')), isNull);
        clock = clock.add(const Duration(seconds: 2));
        expect(b.onEvent(_ev('progressive.activated')), Buzz.boxActivated);
        expect(played, [Buzz.captured.pattern, Buzz.boxActivated.pattern]);
      },
    );

    test('events that do not buzz', () {
      final b = make();
      void none(FeedEvent e) {
        clock = clock.add(const Duration(seconds: 5));
        expect(b.onEvent(e), isNull, reason: e.type);
      }

      // another team's boxes
      none(
        _ev('zone.captured', team: 'blue', data: {'previous_team': 'green'}),
      );
      none(_ev('zone.captured', team: 'blue'));
      none(_ev('zone.neutralized', data: {'previous_team': 'blue'}));
      none(_ev('zone.neutralized'));
      // the team's own box taken again by the same team
      none(_ev('zone.captured', team: 'red', data: {'previous_team': 'red'}));
      // others
      none(_ev('game.pause'));
      none(_ev('game.resume'));
      none(_ev('scenario.objective.revealed', team: 'red'));
      none(_ev('player.respawn'));
      none(_ev('node.online'));
      expect(played, isEmpty);
    });

    test('a capture from a neutral box, and a take-over, buzz', () {
      final b = make();
      expect(
        b.onEvent(
          _ev('zone.captured', team: 'red', data: {'previous_team': 'blue'}),
        ),
        Buzz.captured,
      );
    });

    test('with no team known only the game-wide events buzz', () {
      team = null;
      final b = make();
      clock = clock.add(const Duration(seconds: 5));
      expect(b.onEvent(_ev('zone.captured', team: 'red')), isNull);
      expect(b.onEvent(_ev('zone.neutralized')), isNull);
      expect(b.onEvent(_ev('game.start')), Buzz.gameStart);
    });

    test('the setting off silences everything, and is read at each event', () {
      final b = make();
      on = false;
      expect(b.onEvent(_ev('gm.message')), isNull);
      expect(b.onEvent(_ev('game.start')), isNull);
      expect(b.onEvent(_ev('zone.captured', team: 'red')), isNull);
      expect(played, isEmpty);
      on = true;
      expect(b.onEvent(_ev('game.end')), Buzz.gameEnd);
      expect(played, [Buzz.gameEnd.pattern]);
    });

    test('a spectator is not buzzed', () {
      final b = make(role: 'spectator');
      expect(b.onEvent(_ev('gm.message')), isNull);
      expect(played, isEmpty);
    });

    test('a burst gives one buzz; a later event buzzes again', () {
      final b = make();
      expect(b.onEvent(_ev('zone.captured', team: 'red')), Buzz.captured);
      clock = clock.add(const Duration(milliseconds: 300));
      expect(
        b.onEvent(_ev('zone.captured', team: 'red')),
        isNull,
        reason: 'a second capture within the window',
      );
      clock = clock.add(const Duration(milliseconds: 300));
      expect(
        b.onEvent(
          _ev('zone.captured', team: 'blue', data: {'previous_team': 'red'}),
        ),
        isNull,
        reason: 'a loss within the window of a capture',
      );
      expect(played.length, 1);
      clock = clock.add(const Duration(milliseconds: 1100));
      expect(b.onEvent(_ev('zone.captured', team: 'red')), Buzz.captured);
      expect(played.length, 2);
    });

    test('a GM message still buzzes right after a weaker buzz, not twice', () {
      final b = make();
      expect(b.onEvent(_ev('zone.captured', team: 'red')), Buzz.captured);
      clock = clock.add(const Duration(milliseconds: 200));
      expect(b.onEvent(_ev('gm.message')), Buzz.gmMessage);
      clock = clock.add(const Duration(milliseconds: 200));
      expect(b.onEvent(_ev('gm.message')), isNull);
      expect(b.onEvent(_ev('game.end')), isNull);
      expect(played, [Buzz.captured.pattern, Buzz.gmMessage.pattern]);
    });
  });

  group('the player view', () {
    var clock = DateTime(2026, 10, 26, 15);
    setUp(() => clock = DateTime(2026, 10, 26, 15));

    Future<Harness> show(
      WidgetTester tester,
      FieldFeed feed, {
      AppSettings? settings,
    }) async {
      tester.view.physicalSize = const Size(360, 2400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      addTearDown(feed.dispose);
      final h = harness(
        language: AppLanguage.en,
        settings: (settings ?? AppSettings())..myTeam = 'red',
      );
      await tester.pumpWidget(
        h.app(
          home: PlayerScreen(link: feed.link, feed: feed, buzzNow: () => clock),
        ),
      );
      await tester.pumpAndSettle();
      return h;
    }

    FieldFeed feedOf({List<Map<String, Object?>> events = const []}) {
      final feed = FieldFeed(
        FieldLink.parse('10.0.0.1', 'c')!,
        connect: (_) => Future.error(StateError('offline')),
        now: () => DateTime(2026, 10, 26, 15),
      );
      return feed
        ..state = FeedState.open
        ..onMessage({
          'type': 'hello',
          'game': {
            'id': 7,
            'name': 'Field',
            'teams': ['red', 'blue'],
            'state': 'running',
            'duration_ms': 3600000,
            'game_time_ms': 1000,
            'live': true,
          },
          'events': events,
        });
    }

    List<String> buzzes(Harness h) => [
      for (final c in h.device.calls)
        if (c.startsWith('vibrate')) c,
    ];

    testWidgets('live events buzz, with the patterns of the table', (
      tester,
    ) async {
      final feed = feedOf();
      final h = await show(tester, feed);
      expect(buzzes(h), isEmpty);

      Future<void> live(Map<String, Object?> e) async {
        feed.onMessage(_live(e));
        await tester.pumpAndSettle();
        clock = clock.add(const Duration(milliseconds: 1100));
      }

      await live(_wire('gm.message', data: {'text': 'Move up'}));
      await live(_wire('game.pause'));
      await live(_wire('zone.captured', team: 'red'));
      await live(
        _wire('zone.captured', team: 'blue', data: {'previous_team': 'red'}),
      );
      await live(_wire('zone.captured', team: 'blue'));
      await live(_wire('game.start'));
      await live(_wire('game.end'));
      expect(buzzes(h), [
        'vibrate ${Buzz.gmMessage.pattern}',
        'vibrate ${Buzz.captured.pattern}',
        'vibrate ${Buzz.lost.pattern}',
        'vibrate ${Buzz.gameStart.pattern}',
        'vibrate ${Buzz.gameEnd.pattern}',
      ]);
    });

    testWidgets('the setting off: no buzz for any of them', (tester) async {
      final feed = feedOf();
      final h = await show(
        tester,
        feed,
        settings: AppSettings()..vibrateOnEvents = false,
      );
      feed
        ..onMessage(_live(_wire('gm.message', data: {'text': 'hi'})))
        ..onMessage(_live(_wire('zone.captured', team: 'red')))
        ..onMessage(_live(_wire('game.start')))
        ..onMessage(_live(_wire('game.end')));
      await tester.pumpAndSettle();
      expect(buzzes(h), isEmpty);
      expect(find.text('Game master: hi'), findsWidgets); // still shown
    });

    testWidgets('several captures in a second give one buzz', (tester) async {
      final feed = feedOf();
      final h = await show(tester, feed);
      for (var i = 0; i < 4; i++) {
        feed.onMessage(_live(_wire('zone.captured', team: 'red')));
      }
      await tester.pumpAndSettle();
      expect(buzzes(h), ['vibrate ${Buzz.captured.pattern}']);
    });

    testWidgets('what a connection starts with does not buzz, also after a '
        'reconnect', (tester) async {
      final starting = [
        _wire('gm.message', data: {'text': 'before'}),
        _wire('zone.captured', team: 'red'),
        _wire('game.start'),
      ];
      final feed = feedOf(events: starting);
      final h = await show(tester, feed);
      expect(buzzes(h), isEmpty);
      // The connection drops and comes back: a new hello, with one more event
      // that happened while the phone was away.
      feed.onMessage({
        'type': 'hello',
        'game': feed.game,
        'events': [
          ...starting,
          _wire('gm.message', data: {'text': 'while away'}),
          _wire('zone.captured', team: 'blue', data: {'previous_team': 'red'}),
          _wire('game.end'),
        ],
      });
      await tester.pumpAndSettle();
      expect(buzzes(h), isEmpty);
      expect(find.text('Game master: while away'), findsWidgets);
      // and the next live one does
      feed.onMessage(_live(_wire('gm.message', data: {'text': 'now'})));
      await tester.pumpAndSettle();
      expect(buzzes(h), ['vibrate ${Buzz.gmMessage.pattern}']);
    });
  });

  group('the setting', () {
    test('is on by default and is kept', () {
      expect(AppSettings().vibrateOnEvents, isTrue);
      final off = AppSettings()..vibrateOnEvents = false;
      expect(AppSettings.fromJson(off.toJson()).vibrateOnEvents, isFalse);
      // settings saved before it existed
      expect(AppSettings.fromJson(const {}).vibrateOnEvents, isTrue);
    });

    testWidgets('the Settings switch turns it off and on', (tester) async {
      final h = harness(language: AppLanguage.en);
      await tester.pumpWidget(h.app(home: const SettingsScreen()));
      await tester.pumpAndSettle();
      final tile = find.byKey(const Key('vibrate-on-events'));
      await tester.scrollUntilVisible(tile, 200);
      expect(tile, findsOneWidget);
      expect(find.text('Vibrate on game events'), findsOneWidget);
      expect(tester.widget<SwitchListTile>(tile).value, isTrue);
      await tester.tap(tile);
      await tester.pumpAndSettle();
      expect(tester.widget<SwitchListTile>(tile).value, isFalse);
      expect(h.settings.vibrateOnEvents, isFalse);
      await tester.tap(tile);
      await tester.pumpAndSettle();
      expect(h.settings.vibrateOnEvents, isTrue);
    });
  });
}
