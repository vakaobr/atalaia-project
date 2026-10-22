// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// What the Android field controller keeps about its games (PE24): games,
/// their event log, scores, the nodes heard and a few settings, as the Pi
/// controller's SQLite store keeps them (controller/atalaia_controller/
/// store.py), with the same record shapes so the API answers alike.
///
/// [MemoryControllerStore] keeps everything in memory: a phone controller
/// that restarts loses its games (slice S1). Keeping them on the phone's
/// storage, and the game key only when the GM asks (persist_game_key), is
/// slice S3 (PLAN.md, "PE24 slices").
library;

/// Game states a game can be in and still be the live game.
const liveStates = ['ready', 'running', 'paused'];

abstract interface class ControllerStore {
  void createGame(Map<String, Object?> game);
  Map<String, Object?>? game(int id);

  /// Every game, oldest first.
  List<Map<String, Object?>> games();
  Map<String, Object?>? liveGame();
  Set<int> gameIds();
  void updateGame(int id, Map<String, Object?> fields);

  /// Stores one event; false when the log already had it (a replay).
  bool insertEvent(int gameId, Map<String, Object?> event);

  /// The game's events in game-time order (then node, then seq).
  List<Map<String, Object?>> events(int gameId, {int? sinceMs, String? type});
  void saveScores(int gameId, Map<String, int> totals);
  Map<String, int> scores(int gameId);
  void upsertNode(int gameId, Map<String, Object?> info);
  List<Map<String, Object?>> nodes(int gameId);
  String? getSetting(String key);
  void setSetting(String key, String value);
}

class MemoryControllerStore implements ControllerStore {
  MemoryControllerStore({double Function()? wallSeconds})
    : _wall =
          wallSeconds ?? (() => DateTime.now().microsecondsSinceEpoch / 1e6);

  final double Function() _wall;
  final _games = <int, Map<String, Object?>>{};
  final _events = <int, List<Map<String, Object?>>>{};
  final _eventKeys = <int, Set<(int, int, int, String)>>{};
  final _scores = <int, Map<String, int>>{};
  final _nodes = <int, Map<int, Map<String, Object?>>>{};
  final _settings = <String, String>{};

  static const _gameFields = {
    'state',
    'term',
    'started_at',
    'ended_at',
    'assignments',
    'duration_ms',
    'team_info',
  };

  @override
  void createGame(Map<String, Object?> game) {
    _games[game['id']! as int] = {
      'started_at': null,
      'ended_at': null,
      'controller_id': null,
      ...game,
    };
  }

  @override
  Map<String, Object?>? game(int id) {
    final g = _games[id];
    return g == null ? null : _copy(g);
  }

  @override
  List<Map<String, Object?>> games() {
    final out = [for (final g in _games.values) _copy(g)];
    out.sort(
      (a, b) => (a['created_at']! as num).compareTo(b['created_at']! as num),
    );
    return out;
  }

  @override
  Map<String, Object?>? liveGame() {
    for (final g in games().reversed) {
      if (liveStates.contains(g['state'])) return g;
    }
    return null;
  }

  @override
  Set<int> gameIds() => _games.keys.toSet();

  @override
  void updateGame(int id, Map<String, Object?> fields) {
    final unknown = fields.keys.toSet().difference(_gameFields);
    if (unknown.isNotEmpty) throw ArgumentError('cannot update $unknown');
    _games[id]?.addAll(fields);
  }

  @override
  bool insertEvent(int gameId, Map<String, Object?> ev) {
    final key = (
      ev['node']! as int,
      ev['seq']! as int,
      ev['t']! as int,
      ev['type']! as String,
    );
    if (!(_eventKeys[gameId] ??= {}).add(key)) return false;
    (_events[gameId] ??= []).add({
      'node': ev['node'],
      'seq': ev['seq'],
      't': ev['t'],
      'type': ev['type'],
      'team': ev['team'],
      'squad': ev['squad'],
      'prio': ev['prio'] ?? 'normal',
      'data': _copy((ev['data'] as Map?)?.cast<String, Object?>() ?? {}),
      'epoch': ev['epoch'],
      'pkt_seq': ev['pkt_seq'],
      'received_at': _wall(),
    });
    return true;
  }

  @override
  List<Map<String, Object?>> events(int gameId, {int? sinceMs, String? type}) {
    final out = [
      for (final e in _events[gameId] ?? const <Map<String, Object?>>[])
        if ((sinceMs == null || (e['t']! as int) >= sinceMs) &&
            (type == null || e['type'] == type))
          _copy(e),
    ];
    out.sort((a, b) {
      for (final k in ['t', 'node', 'seq']) {
        final c = (a[k]! as int).compareTo(b[k]! as int);
        if (c != 0) return c;
      }
      return 0;
    });
    return out;
  }

  @override
  void saveScores(int gameId, Map<String, int> totals) =>
      (_scores[gameId] ??= {}).addAll(totals);

  @override
  Map<String, int> scores(int gameId) => Map.of(_scores[gameId] ?? const {});

  @override
  void upsertNode(int gameId, Map<String, Object?> info) {
    (_nodes[gameId] ??= {})[info['node_id']! as int] = {
      ..._copy(info),
      'last_seen': _wall(),
    };
  }

  @override
  List<Map<String, Object?>> nodes(int gameId) {
    final m = _nodes[gameId] ?? const <int, Map<String, Object?>>{};
    return [for (final k in m.keys.toList()..sort()) _copy(m[k]!)];
  }

  @override
  String? getSetting(String key) => _settings[key];

  @override
  void setSetting(String key, String value) => _settings[key] = value;
}

/// A deep copy of JSON-like data, so callers never share the store's maps.
Map<String, Object?> _copy(Map<String, Object?> m) =>
    _deep(m) as Map<String, Object?>;

Object? _deep(Object? v) => switch (v) {
  Map() => <String, Object?>{
    for (final e in v.entries) '${e.key}': _deep(e.value),
  },
  List() => [for (final e in v) _deep(e)],
  _ => v,
};
