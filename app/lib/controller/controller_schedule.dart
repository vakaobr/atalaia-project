// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Games made from the site server's schedule on the Android field
/// controller (PE24 slice S7; ADR-P4-11, plan phase 16): the Pi's
/// controller/atalaia_controller/schedule.py with the store's
/// `schedule_games` and `schedule_links` tables kept in one store document
/// ("schedule").
///
/// With the site sync on (controller_sync.dart), the sync client pulls the
/// field's published games of the coming days into it. The GM picks one in
/// the console (*Create from the schedule*): the controller game takes its
/// title, mode and teams unless the GM gives others, and the two are linked.
/// From then on the sync client pulls that scheduled game's roster until the
/// game starts (`ControllerCheckin.applyRoster`), the game's metadata names
/// the scheduled game, and after the game its registrations' outcomes go
/// back (`ControllerCheckin.outcomes`).
///
/// The schedule never drives the controller: nothing here runs unless the GM
/// asks, and a game made from the schedule is an ordinary game.
///
///     GET  /api/v1/schedule                  the scheduled games as last pulled
///     POST /api/v1/schedule/{id}/game        GM: a game made from one (201)
library;

import 'dart:convert';
import 'dart:math';

import 'controller_engine.dart';

const _teamMax = 23;
const _nameMax = 64;
const _usable = ['published', 'in_progress'];

class ControllerSchedule {
  ControllerSchedule(this.engine) {
    engine.schedule = this;
  }

  final ControllerEngine engine;

  /// The sync client: told to pull at once after a game is made from the
  /// schedule (set by controller_sync.dart).
  void Function()? kick;

  /// Whether a sync client is set up (GET /api/v1/schedule's `enabled`).
  bool syncEnabled = false;

  static const _doc = 'schedule';

  Map<String, Object?> _load() {
    final d = engine.store.document(_doc);
    if (d is Map) {
      return {
        'games': [...?(d['games'] as List?)],
        'links': [...?(d['links'] as List?)],
      };
    }
    return {'games': <Object?>[], 'links': <Object?>[]};
  }

  void _put(Map<String, Object?> d) => engine.store.putDocument(_doc, d);

  List<Map<String, Object?>> _list(Object? v) => [
    for (final e in (v as List?) ?? const [])
      if (e is Map) e.cast<String, Object?>(),
  ];

  /// The field's schedule as just pulled: it replaces the last one
  /// (store.py `set_schedule`).
  void setSchedule(List<Map<String, Object?>> games, double now) {
    final d = _load();
    d['games'] = [
      for (final g in games) {...g, 'pulled_at': now},
    ];
    _put(d);
  }

  List<Map<String, Object?>> schedule() {
    final out = _list(_load()['games']);
    out.sort((a, b) {
      final c = (a['starts_at']! as num).compareTo(b['starts_at']! as num);
      return c != 0
          ? c
          : '${a['scheduled_game_id']}'.compareTo('${b['scheduled_game_id']}');
    });
    return out;
  }

  Map<String, Object?>? scheduleGame(String id) {
    for (final g in _list(_load()['games'])) {
      if (g['scheduled_game_id'] == id) return g;
    }
    return null;
  }

  void linkSchedule(int gameId, int gameSeed, String scheduledId, double now) {
    final d = _load();
    final links = [
      for (final l in _list(d['links']))
        if (!(l['game_id'] == gameId && l['game_seed'] == gameSeed)) l,
      {
        'game_id': gameId,
        'game_seed': gameSeed,
        'scheduled_game_id': scheduledId,
        'linked_at': now,
        'roster_pulled_at': null,
        'roster_count': null,
        'roster_error': null,
      },
    ];
    d['links'] = links;
    _put(d);
  }

  /// A game is gone (the retention purge, decision RET-1): its link goes with it.
  void forgetGame(int gameId, int gameSeed) {
    final d = _load();
    final links = _list(d['links']);
    final kept = [
      for (final l in links)
        if (!(l['game_id'] == gameId && l['game_seed'] == gameSeed)) l,
    ];
    if (kept.length == links.length) return;
    d['links'] = kept;
    _put(d);
  }

  Map<String, Object?>? scheduleLink(int gameId, int gameSeed) {
    for (final l in _list(_load()['links'])) {
      if (l['game_id'] == gameId && l['game_seed'] == gameSeed) return l;
    }
    return null;
  }

  List<Map<String, Object?>> scheduleLinks() => _list(
    _load()['links'],
  )..sort((a, b) => (a['linked_at']! as num).compareTo(b['linked_at']! as num));

  void rosterPulled(
    int gameId,
    int gameSeed,
    double now,
    int? count,
    String? error,
  ) {
    final d = _load();
    final links = _list(d['links']);
    for (final l in links) {
      if (l['game_id'] == gameId && l['game_seed'] == gameSeed) {
        if (error == null) {
          l
            ..['roster_pulled_at'] = now
            ..['roster_count'] = count
            ..['roster_error'] = null;
        } else {
          l['roster_error'] = error;
        }
      }
    }
    d['links'] = links;
    _put(d);
  }

  /// GET /api/v1/schedule: the scheduled games as last pulled, each with the
  /// controller games made from it.
  Map<String, Object?> view() {
    final links = <String, List<int>>{};
    for (final link in scheduleLinks()) {
      final game = engine.store.game(link['game_id']! as int);
      if (game != null && game['game_seed'] == link['game_seed']) {
        links
            .putIfAbsent('${link['scheduled_game_id']}', () => [])
            .add(link['game_id']! as int);
      }
    }
    final games = [
      for (final g in schedule())
        {...g, 'games': links['${g['scheduled_game_id']}'] ?? <int>[]},
    ];
    num? pulled;
    for (final g in games) {
      final p = g['pulled_at'];
      if (p is num && (pulled == null || p > pulled)) pulled = p;
    }
    return {'enabled': syncEnabled, 'pulled_at': pulled, 'games': games};
  }

  List<String> _teams(Map<String, Object?> scheduled) {
    final teams = [
      for (final t in (scheduled['teams'] as List?) ?? const [])
        if (t is String) t,
    ];
    if (teams.isNotEmpty &&
        (teams.length > 8 ||
            teams.any((t) {
              final n = utf8.encode(t).length;
              return n == 0 || n > _teamMax;
            }))) {
      throw ControllerError(
        "the scheduled game's teams do not fit the radio (1-8 names of up to "
        '$_teamMax bytes): give the teams',
      );
    }
    return teams;
  }

  /// POST /api/v1/schedule/{id}/game: a controller game made from a
  /// scheduled game, linked to it (schedule.py `create_game`).
  Map<String, Object?> createGame(String scheduledId, Object? spec) {
    final scheduled = scheduleGame(scheduledId);
    if (scheduled == null) {
      throw ControllerError.notFound(
        'no such scheduled game in the last schedule pulled',
      );
    }
    if (!_usable.contains(scheduled['status'])) {
      throw ControllerError.conflict(
        'the scheduled game is ${scheduled['status']}',
      );
    }
    if (spec is! Map) throw ControllerError("a game's settings are an object");
    final body = Map<String, Object?>.of(spec.cast<String, Object?>());
    if (!body.containsKey('name')) {
      var title = '${scheduled['title']}'.trim();
      final runes = title.runes.toList();
      if (runes.length > _nameMax) {
        title = String.fromCharCodes(runes.sublist(0, _nameMax));
      }
      title = title.trim();
      body['name'] = title.isEmpty ? 'Jogo' : title;
    }
    bool truthy(Object? v) => v != null && v != '' && v != 0 && v != false;
    if (!truthy(body['mode_id']) &&
        !truthy(body['preset_id']) &&
        truthy(scheduled['mode_id'])) {
      body['mode_id'] = scheduled['mode_id'];
    }
    if (!body.containsKey('teams')) {
      final teams = _teams(scheduled);
      if (teams.isNotEmpty) body['teams'] = teams;
    }
    if (!body.containsKey('duration_ms')) {
      final span =
          (scheduled['ends_at']! as num) - (scheduled['starts_at']! as num);
      final s = max(0, min(span, 0xffffffff ~/ 1000));
      body['duration_ms'] = (s * 1000).truncate();
    }
    final game = engine.createGame(body);
    linkSchedule(
      game['id']! as int,
      game['game_seed']! as int,
      scheduledId,
      engine.wallSeconds(),
    );
    kick?.call(); // the roster comes at once
    return {...game, 'scheduled_game_id': scheduledId};
  }
}
