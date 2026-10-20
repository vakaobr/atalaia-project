// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// A player's feed of a scenario's game (phase 4 plan phase 8), as the
/// controller sends it to a player of red's squad 1: the game's scenario
/// block with the objectives that player may know (scenario_service.Meta's
/// player view) and the objective events so far. For the widget and golden
/// tests of the player view.
library;

import 'package:atalaia_app/player/field_feed.dart';

/// The bridge (anyone's) completed by red, the vault (hidden, red's squad 1)
/// revealed, and a defence that failed when its time ran out.
FieldFeed scenarioFeed() {
  final feed = FieldFeed(
    FieldLink.parse('10.0.0.1', 'c')!,
    connect: (_) => Future.error(StateError('offline')),
    now: () => DateTime(2026, 10, 20, 15),
  );
  Map<String, Object?> event(
    int t,
    String type,
    String objective, {
    String? team,
    String? reason,
  }) => {
    'node': 1,
    't': t,
    'type': type,
    'team': ?team,
    'data': {'objective': objective, 'team': ?team, 'reason': ?reason},
  };
  return feed
    ..state = FeedState.open
    ..onMessage({
      'type': 'hello',
      'game': {
        'id': 7,
        'name': 'Operação Moinho',
        'teams': ['red', 'blue'],
        'state': 'running',
        'duration_ms': 3600000,
        'game_time_ms': 900000,
        'live': true,
        'squads': 2,
        'scenario': {
          'id': 'org.club.moinho',
          'name': 'Operation Mill',
          'i18n': {
            'pt': {'name': 'Operação Moinho'},
          },
          'objectives': [
            {
              'id': 'bridge',
              'type': 'capture_and_hold',
              'name': 'Take the bridge',
              'i18n': {
                'pt': {'name': 'Tomar a ponte'},
              },
              'visibility': 'public',
              'points': 50,
            },
            {
              'id': 'vault',
              'type': 'enter_code',
              'name': 'Open the vault',
              'i18n': {
                'pt': {'name': 'Abrir o cofre'},
              },
              'team': 'red',
              'squad': 1,
              'visibility': 'hidden',
              'points': 100,
            },
            {
              'id': 'mill',
              'type': 'defend',
              'name': 'Hold the mill',
              'i18n': {
                'pt': {'name': 'Defender o moinho'},
              },
              'team': 'red',
              'visibility': 'team',
            },
          ],
        },
      },
      'score': {
        'game': 7,
        'teams': {'red': 50, 'blue': 0},
      },
      'nodes': <Object?>[],
      'events': [
        event(0, 'scenario.objective.revealed', 'bridge'),
        event(0, 'scenario.objective.revealed', 'mill', team: 'red'),
        event(600000, 'scenario.objective.completed', 'bridge', team: 'red'),
        event(600000, 'scenario.objective.revealed', 'vault', team: 'red'),
        event(
          840000,
          'scenario.objective.failed',
          'mill',
          team: 'red',
          reason: 'time',
        ),
      ],
      'me': {
        'player_id': 'p-k7m2q4x9z3ab',
        'role': 'player',
        'team': 'red',
        'squad': 1,
      },
    });
}
