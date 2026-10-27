// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Player positions on the Android field controller and who may see them
/// (ADR-P3-6, constraint 9: filtered on the controller only; decision PE24,
/// slice S5): the Pi controller's controller/atalaia_controller/positions.py
/// with the same reports, checks, answers and stream messages, checked by
/// the shared contract cases (protocol/vectors/controller_api.json). Who
/// sees whom is [VisibilityEngine]'s table (visibility_engine.dart):
///
///     player        their own; their squad's too when the game's parameters say squad_visible
///     squad_leader  their squad
///     vip           their team (the escort)
///     marshal, gm   everyone (the GM token too)
///     spectator     nobody (the read token is a spectator)
///
/// Phones report with POST /api/v1/positions (a player token). The
/// controller keeps each player's latest report for the running game only;
/// a mode grants a team a temporary view of another team with the event
/// `visibility.granted` (its team sees `see_team` for `duration_s`), ended
/// by `visibility.expired`, which the controller logs when the time is up.
/// Positions are deleted when the game ends and never go on the radio or
/// MQTT. A VIP's GPS reports also go to the game's field.lua as the input
/// `position.fix` (decision P4R6), and to nothing else.
///
/// On a multi-story field a report may say the player's level (`level`,
/// 0-9; null: not known); a report without `level` keeps the one the
/// player last gave in this game (decision ML-5).
///
/// The latest positions are kept in the store's "positions" document, so
/// they survive a restart as the Pi's SQLite table does (decision PE24-56).
library;

import 'controller_checkin.dart';
import 'controller_engine.dart';
import 'controller_field.dart';
import 'visibility_engine.dart';

const positionReportsMax = 5;
const positionSources = ['gps', 'ble'];
const visibilityGrantMaxS = 3600;

/// The levels of a multi-story field (field_levels.py LEVELS_MAX).
const fieldLevelsMax = 10;
final _beaconRe = RegExp(r'^[0-9]{1,5}:[0-9]{1,5}$');

double? _num(
  String name,
  Object? v,
  double lo,
  double hi, {
  bool optional = true,
}) {
  if (v == null && optional) return null;
  if (v is! num || !v.isFinite || v < lo || v > hi) {
    throw ControllerError('$name: a number from $lo to $hi');
  }
  return v.toDouble();
}

/// One position report's own fields (the player, team and squad come from
/// the token); throws [ControllerError].
Map<String, Object?> checkPositionReport(Object? r) {
  if (r is! Map) throw ControllerError('a position report is an object');
  const allowed = {
    'lat',
    'lon',
    'accuracy_m',
    'altitude_m',
    'heading_deg',
    'speed_mps',
    'source',
    'beacon_id',
    't',
    'player_id',
    'team',
    'squad',
    'level',
  };
  final unknown = r.keys.where((k) => !allowed.contains(k)).toList()..sort();
  if (unknown.isNotEmpty) {
    throw ControllerError('position report: unknown fields $unknown');
  }
  final source = r.containsKey('source') ? r['source'] : 'gps';
  if (!positionSources.contains(source)) {
    throw ControllerError('source: gps or ble');
  }
  final out = <String, Object?>{'source': source};
  if (source == 'gps') {
    out['lat'] = _num('lat', r['lat'], -90, 90, optional: false);
    out['lon'] = _num('lon', r['lon'], -180, 180, optional: false);
    out['accuracy_m'] = _num('accuracy_m', r['accuracy_m'], 0, 10000);
    for (final (name, lo, hi) in [
      ('altitude_m', -1000.0, 10000.0),
      ('heading_deg', 0.0, 360.0),
      ('speed_mps', 0.0, 200.0),
    ]) {
      final v = _num(name, r[name], lo, hi);
      if (v != null) out[name] = v;
    }
  } else {
    final bid = r['beacon_id'];
    if (bid is! String ||
        !_beaconRe.hasMatch(bid) ||
        !bid.split(':').every((x) => int.parse(x) <= 65535)) {
      throw ControllerError('beacon_id: major:minor of the strongest iBeacon');
    }
    out['beacon_id'] = bid;
  }
  if (r.containsKey('level')) {
    final level = r['level'];
    if (level != null &&
        (level is! int || level < 0 || level >= fieldLevelsMax)) {
      throw ControllerError(
        'level: 0 to ${fieldLevelsMax - 1}, or null when not known',
      );
    }
    out['level'] = level;
  }
  final t = r.containsKey('t') ? r['t'] : 0;
  if (t is! int || t < 0 || t > 9007199254740992) {
    throw ControllerError('t: milliseconds, an integer');
  }
  out['t'] = t;
  return out;
}

/// The positions service of one controller ([ControllerEngine.positions]).
class ControllerPositions {
  ControllerPositions(this.engine) {
    final doc = engine.store.document('positions');
    if (doc is Map) {
      for (final g in doc.entries) {
        final id = int.tryParse('${g.key}');
        if (id == null || g.value is! Map) continue;
        _positions[id] = {
          for (final p in (g.value as Map).entries)
            if (p.value is Map)
              '${p.key}': (p.value as Map).cast<String, Object?>(),
        };
      }
    }
    engine.positions = this;
  }

  final ControllerEngine engine;

  /// Game -> player -> the latest report, as stored.
  final _positions = <int, Map<String, Map<String, Object?>>>{};

  /// Game -> its temporary views (team ids; their expiry on the wall clock).
  final _grants = <int, VisibilityEngine>{};

  DateTime _now() => DateTime.fromMicrosecondsSinceEpoch(
    (engine.wallSeconds() * 1e6).round(),
    isUtc: true,
  );

  VisibilityEngine _grantsOf(int gameId) =>
      _grants.putIfAbsent(gameId, () => VisibilityEngine(now: _now));

  void _save() => engine.store.putDocument('positions', {
    for (final e in _positions.entries) '${e.key}': e.value,
  });

  /// The positions kept for [gameId] (player id -> report).
  Map<String, Map<String, Object?>> playerPositions(int gameId) => {
    for (final e in (_positions[gameId] ?? const {}).entries)
      e.key: Map.of(e.value),
  };

  // --- who sees whom -------------------------------------------------------------

  int _teamId(int gameId, String? name) {
    final teams = (engine.store.game(gameId)?['teams'] as List?) ?? const [];
    return name == null ? 0 : teams.indexOf(name) + 1;
  }

  bool canSee(ApiViewer viewer, Map<String, Object?> pos) {
    if (viewer.kind == 'gm') return true;
    final gameId = pos['game_id']! as int;
    if (viewer.kind != 'player' || viewer.gameId != gameId) return false;
    final game = engine.store.game(gameId);
    final params = game?['params'];
    final grants = _grantsOf(gameId)
      ..squadVisible = params is Map && _truthy(params['squad_visible']);
    return grants.canSee(
      Viewer(
        role: viewer.role,
        playerId: viewer.playerId,
        team: viewer.team,
        squad: viewer.squad,
        gameId: viewer.gameId,
      ),
      PlayerPosition(
        gameId: gameId,
        playerId: pos['player_id']! as String,
        team: pos['team']! as int,
        squad: pos['squad']! as int,
      ),
    );
  }

  /// The positions [viewer] may see in [gameId] (default: a player's own
  /// game, else the live game).
  List<Map<String, Object?>> visible(ApiViewer viewer, [int? gameId]) {
    gameId ??= viewer.kind == 'player'
        ? viewer.gameId
        : engine.liveGame?['id'] as int?;
    if (gameId == null) return [];
    final kept = _positions[gameId] ?? const {};
    // By player id, as the Pi's store gives them (decision PE24-57).
    return [
      for (final pid in kept.keys.toList()..sort())
        if (canSee(viewer, kept[pid]!)) Map.of(kept[pid]!),
    ];
  }

  // --- reports -----------------------------------------------------------------

  /// POST /api/v1/positions: one report, or `{"reports": [...]}` (1-5).
  Map<String, Object?> report(ApiViewer viewer, Object? body) {
    if (viewer.kind != 'player') {
      throw ControllerError("positions come from a player's token");
    }
    final items = body is Map && body.containsKey('reports')
        ? body['reports']
        : [body];
    if (items is! List || items.isEmpty || items.length > positionReportsMax) {
      throw ControllerError(
        'reports: 1 to $positionReportsMax position reports',
      );
    }
    final checked = [for (final r in items) checkPositionReport(r)];
    for (final raw in items) {
      final pid = (raw as Map)['player_id'];
      if (pid != null && pid != viewer.playerId) {
        throw ControllerError('player_id: only your own position');
      }
    }
    final game = engine.store.game(viewer.gameId!);
    final live = engine.liveGame;
    if (game == null ||
        (game['state'] != 'running' && game['state'] != 'paused') ||
        live == null ||
        live['id'] != game['id']) {
      throw ControllerError.conflict(
        'positions are kept only while the game runs',
      );
    }
    final gid = game['id']! as int;
    // A beacon is accepted only from the field's registry, and gives the
    // room, zone, level and plan place (beacons.py, BLE-1 to BLE-9).
    for (var i = 0; i < checked.length; i++) {
      if (checked[i]['source'] != 'ble') continue;
      final id = checked[i]['beacon_id']! as String;
      final place = engine.field?.beaconPlace(id);
      if (place == null) {
        throw ControllerError(
          "beacon_id: $id is not a beacon of this field's registry",
        );
      }
      checked[i] = {...checked[i], ...place};
    }
    var latest = checked.reduce(
      (a, b) => (b['t']! as int) > (a['t']! as int) ? b : a,
    );
    if (!latest.containsKey('level')) {
      final before = _positions[gid]?[viewer.playerId]?['level'];
      if (before is int) latest = {...latest, 'level': before};
    }
    if (latest.containsKey('level') && latest['level'] == null) {
      latest = Map.of(latest)..remove('level'); // not known: no level
    }
    final pos = <String, Object?>{
      'game_id': gid,
      'player_id': viewer.playerId,
      'team': viewer.team,
      'squad': viewer.squad,
      ...latest,
      'received_at': engine.wallSeconds(),
    };
    (_positions[gid] ??= {})[viewer.playerId!] = pos;
    _save();
    engine.emit({
      'type': 'player_position',
      'game': gid,
      'position': pos,
      '_position': true,
    });
    if (viewer.role == 'vip') _toField(game, viewer, checked);
    return {
      'stored': checked.length,
      'interval_s': interval(game),
      'ble_interval_s': bleIntervalS(game),
    };
  }

  /// A VIP's GPS reports, oldest first, to the game's field.lua as
  /// position.fix (decision P4R6). Indoor (BLE) reports carry no
  /// coordinates.
  void _toField(
    Map<String, Object?> game,
    ApiViewer viewer,
    List<Map<String, Object?>> reports,
  ) {
    final teams = game['teams']! as List;
    final team = viewer.team >= 1 && viewer.team <= teams.length
        ? teams[viewer.team - 1]
        : null;
    final gps = [
      for (final r in reports)
        if (r['source'] == 'gps') r,
    ]..sort((a, b) => (a['t']! as int).compareTo(b['t']! as int));
    for (final r in gps) {
      final fix = <String, Object?>{
        'player': viewer.playerId,
        'role': viewer.role,
        'lat': r['lat'],
        'lon': r['lon'],
        'src': 'gps',
        'team': ?team,
        if (r['accuracy_m'] != null) 'acc': r['accuracy_m'],
      };
      if (!engine.fieldPosition(game['id']! as int, fix)) return;
    }
  }

  /// How often the players' phones report (the game's
  /// `position_interval_s`, 5-60; else 10).
  static int interval(Map<String, Object?> game) {
    final params = game['params'];
    final v = params is Map ? params['position_interval_s'] : null;
    return v is int && v >= 5 && v <= 60 ? v : 10;
  }

  // --- temporary visibility ------------------------------------------------------

  /// visibility.granted from a node or field.lua: its team sees see_team for
  /// duration_s.
  void onEvent(int gameId, Map<String, Object?> record) {
    if (record['type'] != 'visibility.granted') return;
    final data = (record['data'] as Map?) ?? const {};
    final team = record['team'],
        see = data['see_team'],
        dur = data['duration_s'];
    if (team is! String ||
        see is! String ||
        dur is! num ||
        dur <= 0 ||
        dur > visibilityGrantMaxS) {
      return;
    }
    _grantsOf(gameId).grant(
      _teamId(gameId, team),
      _teamId(gameId, see),
      Duration(microseconds: (dur * 1e6).round()),
    );
    engine.emit({
      'type': 'positions',
      'game': gameId,
      '_positions_refresh': true,
    });
  }

  /// Ends grants whose time is up, with visibility.expired from the
  /// controller.
  void tick() {
    for (final e in _grants.entries.toList()) {
      final gameId = e.key;
      final teams =
          (engine.store.game(gameId)?['teams'] as List?)?.cast<String>() ??
          const <String>[];
      for (final (team, see) in e.value.expire()) {
        String? name(int id) =>
            id >= 1 && id <= teams.length ? teams[id - 1] : null;
        engine.logControllerEvent(gameId, 'visibility.expired', {
          'see_team': name(see),
          'text': 'time',
        }, team: name(team));
        engine.emit({
          'type': 'positions',
          'game': gameId,
          '_positions_refresh': true,
        });
      }
    }
  }

  /// ADR-P3-6: positions last only as long as the game.
  void endGame(int gameId) {
    _grants.remove(gameId);
    if (_positions.remove(gameId) != null) _save();
  }

  /// A player's data is erased (DELETE /api/v1/players/{id}).
  void erasePlayer(String pid) {
    var changed = false;
    for (final m in _positions.values) {
      changed = m.remove(pid) != null || changed;
    }
    if (changed) _save();
  }
}

bool _truthy(Object? v) => switch (v) {
  null || false || 0 || '' => false,
  final List<Object?> l => l.isNotEmpty,
  final Map<Object?, Object?> m => m.isNotEmpty,
  _ => true,
};
