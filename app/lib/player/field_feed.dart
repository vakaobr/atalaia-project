// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The player view's link to a field controller: its address and an access
/// code (the read token, controller/README.md "REST API v1"), and the live
/// feed of WS /api/v1/stream, as the controller's scoreboard page follows
/// it: a snapshot first, then games, scores, events and nodes. Reconnects
/// after 1 s, doubling up to 15 s; a refused code (close 4401) stops.
///
/// The snapshot holds the game's latest events (plan phase E), so a phone
/// that connects mid-game shows what already happened. With a player token
/// (a field check-in, ADR-P3-13) the link is HTTPS with the field's pinned
/// CA; the feed then also has the player's own check-in ([me]), the
/// positions the controller lets this player see, and when the GM changes
/// the player's team or role (close 4409) it asks [onAssignment] for a new
/// token before it reconnects.
///
/// A scenario's game (plan phase 8, decision P4R24): the game carries the
/// scenario's objectives this connection may know (`game.scenario`, with
/// their names in English and Portuguese), and the objective events say
/// which were revealed, completed or failed: [objectives].
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../checkin/field_trust.dart';

/// A field controller's address and access code.
final class FieldLink {
  const FieldLink(this.base, this.token, {this.field});

  /// http://host:port, or https://host:port with [field].
  final Uri base;
  final String token;

  /// The pinned field of a check-in: its CA is the only one trusted.
  final PinnedField? field;

  FieldLink withToken(String t) => FieldLink(base, t, field: field);

  Uri get stream => base.replace(
    scheme: base.scheme == 'https' ? 'wss' : 'ws',
    path: '/api/v1/stream',
    queryParameters: {'token': token},
  );

  Uri get console => base.replace(path: '/console/');

  /// A link from what a QR code or a person gives: the scoreboard's
  /// address (http://host:8080/scoreboard#token=CODE), or an address and a
  /// separate [token]. Null if there is no host or no code.
  static FieldLink? parse(String text, [String? token]) {
    var t = text.trim();
    if (t.isEmpty) return null;
    if (!t.contains('://')) t = 'http://$t';
    final Uri u;
    try {
      u = Uri.parse(t);
    } on FormatException {
      return null;
    }
    if (u.host.isEmpty || (u.scheme != 'http' && u.scheme != 'https')) {
      return null;
    }
    var code = token?.trim();
    if (code == null || code.isEmpty) {
      for (final part in u.fragment.split('&')) {
        final i = part.indexOf('=');
        if (i > 0 && part.substring(0, i) == 'token') {
          code = Uri.decodeComponent(part.substring(i + 1));
        }
      }
      code ??= u.queryParameters['token'];
    }
    if (code == null || code.isEmpty) return null;
    final base = Uri(
      scheme: u.scheme,
      host: u.host,
      port: u.hasPort ? u.port : 8080,
    );
    return FieldLink(base, code);
  }

  @override
  String toString() => base.toString();
}

/// One live connection's messages (JSON text), and how it ended.
abstract interface class FeedSocket {
  Stream<String> get messages;
  int? get closeCode;
  Future<void> close();
}

typedef FeedConnect = Future<FeedSocket> Function(Uri uri);

class _IoSocket implements FeedSocket {
  _IoSocket(this.ws);
  final WebSocket ws;

  @override
  Stream<String> get messages => ws.where((m) => m is String).cast<String>();

  @override
  int? get closeCode => ws.closeCode;

  @override
  Future<void> close() => ws.close();
}

Future<FeedSocket> ioConnect(Uri uri) async =>
    _IoSocket(await WebSocket.connect(uri.toString()));

/// [ioConnect] trusting only [field]'s CA.
Future<FeedSocket> pinnedConnect(Uri uri, PinnedField field) async => _IoSocket(
  await WebSocket.connect(uri.toString(), customClient: field.client()),
);

enum FeedState { connecting, open, closed, denied }

/// Where a scenario objective stands for the player view.
enum ObjectiveState { waiting, active, done, failed }

/// One objective of the game's scenario, as this player may know it: its
/// names and assignee from the game (controller: scenario_service.Meta's
/// player view) and its state from the objective events.
final class ScenarioObjective {
  const ScenarioObjective(this.info, this.state, {this.team, this.reason});

  /// id, type, name, i18n, team, squad, visibility, points, win.
  final Map<String, Object?> info;
  final ObjectiveState state;

  /// The team that completed or failed it.
  final String? team;

  /// Why it failed (captured, defused, time, blocked, lives).
  final String? reason;

  String get id => '${info['id']}';

  /// Its name in [lang] (the scenario's `i18n`), else in English.
  String name(String lang) => _text(info, lang, 'name') ?? id;

  String? description(String lang) => _text(info, lang, 'description');

  int? get points => info['points'] is int ? info['points']! as int : null;

  String? get assigneeTeam =>
      info['team'] is String ? info['team']! as String : null;

  int? get assigneeSquad => info['squad'] is int ? info['squad']! as int : null;
}

String? _text(Map<String, Object?> entry, String lang, String key) {
  final i18n = entry['i18n'];
  if (i18n is Map && i18n[lang] is Map) {
    final v = (i18n[lang] as Map)[key];
    if (v is String && v.isNotEmpty) return v;
  }
  final v = entry[key];
  return v is String && v.isNotEmpty ? v : null;
}

/// One event of the game, as the controller logged it.
final class FeedEvent {
  const FeedEvent(this.type, this.team, this.data, this.tMs, this.node);
  final String type;
  final String? team;
  final Map<String, Object?> data;
  final int tMs;
  final int node;
}

class FieldFeed extends ChangeNotifier {
  FieldFeed(
    this.link, {
    FeedConnect? connect,
    DateTime Function()? now,
    this.onAssignment,
  }) : _connect =
           connect ??
           (link.field == null
               ? ioConnect
               : (uri) => pinnedConnect(uri, link.field!)),
       _now = now ?? DateTime.now;

  FieldLink link;
  final FeedConnect _connect;

  /// Asked for a new token when the controller closes the stream with 4409
  /// (the GM changed this player's team, squad or role); null keeps the old.
  final Future<String?> Function()? onAssignment;

  /// The player's own check-in (a player token's stream only).
  Map<String, Object?>? me;

  /// The positions this connection may see, by player id (ADR-P3-6).
  final positions = <String, Map<String, Object?>>{};
  final DateTime Function() _now;

  FeedState state = FeedState.connecting;
  Map<String, Object?>? game;
  Map<String, int> totals = const {};

  /// The game's nodes by id: owner, role, battery...
  final nodes = <int, Map<String, Object?>>{};

  /// The game's events, newest first (at most 100).
  final events = <FeedEvent>[];

  /// Teams with no lives left (team.eliminated).
  final eliminated = <String>{};

  /// Lives left by player or team, from player.respawn.
  final lives = <String, int>{};

  /// How many new orders came on the live stream since the connection (SQ-5):
  /// an objective revealed to this player, or the news that their squad
  /// leader has orders. The player view buzzes when it grows; the list the
  /// connection starts with does not count.
  int ordersSeq = 0;

  /// The reveals of orders for this player's squad leader alone (SQ-3): the
  /// event comes without the objective, with `leader_only`.
  int get leaderOrders => events
      .where(
        (e) =>
            e.type == 'scenario.objective.revealed' &&
            e.data['leader_only'] == true,
      )
      .length;

  /// What the objective events said of each objective (by id): the state,
  /// and the team that completed or failed it, and why.
  final _objectiveNews = <String, (ObjectiveState, String?, String?)>{};

  /// The field's map features as the stream last sent them (`map_features`,
  /// decision MF-10: the whole list this connection may see, sent when one
  /// changes); null until then (the hello has none: fetch them over REST).
  List<Map<String, Object?>>? mapFeatures;

  /// The ETag of the field's branding as the stream last told it (the
  /// snapshot, then `branding` messages): the view fetches it when it changes.
  String? brandingEtag;

  FeedSocket? _socket;
  Timer? _retry;
  var _delay = const Duration(seconds: 1);
  var _stopped = false;
  int? _baseMs;
  DateTime? _baseAt;
  bool _baseRunning = false;

  List<String> get teams =>
      ((game?['teams'] as List?) ?? const []).map((t) => '$t').toList();

  String? get gameState => game?['state'] as String?;

  Future<void> start() => _open();

  Future<void> _open() async {
    if (_stopped) return;
    state = FeedState.connecting;
    notifyListeners();
    try {
      final s = await _connect(link.stream);
      if (_stopped) {
        await s.close();
        return;
      }
      _socket = s;
      state = FeedState.open;
      _delay = const Duration(seconds: 1);
      notifyListeners();
      await for (final text in s.messages) {
        try {
          final m = jsonDecode(text);
          if (m is Map<String, Object?>) onMessage(m);
        } on FormatException {
          // not JSON: skipped
        }
      }
      if (s.closeCode == 4401) {
        state = FeedState.denied;
        notifyListeners();
        return;
      }
      if (s.closeCode == 4409 && onAssignment != null) {
        final t = await onAssignment!();
        if (t != null) link = link.withToken(t);
        _delay = const Duration(milliseconds: 200);
      }
    } on Object {
      // connection refused or dropped
    }
    if (_stopped) return;
    state = FeedState.closed;
    notifyListeners();
    _retry = Timer(_delay, _open);
    _delay = _delay * 2 > const Duration(seconds: 15)
        ? const Duration(seconds: 15)
        : _delay * 2;
  }

  void _setBranding(Object? b) {
    if (b is Map && b['etag'] is String) brandingEtag = b['etag']! as String;
  }

  /// One message of the stream (public for the tests).
  void onMessage(Map<String, Object?> m) {
    switch (m['type']) {
      case 'hello':
        _setGame(m['game'] as Map<String, Object?>?);
        final score = m['score'];
        if (score is Map && score['teams'] is Map) {
          totals = _ints(score['teams']! as Map);
        }
        nodes.clear();
        for (final n in (m['nodes'] as List?) ?? const []) {
          if (n is Map<String, Object?> && n['node_id'] is int) {
            nodes[n['node_id']! as int] = n;
          }
        }
        // The game's latest events, oldest first: what happened before this
        // connection (a reconnect starts the list over, without duplicates).
        events.clear();
        eliminated.clear();
        lives.clear();
        _objectiveNews.clear();
        for (final e in (m['events'] as List?) ?? const []) {
          if (e is Map<String, Object?>) _onEvent(e);
        }
        if (m['me'] is Map) me = (m['me']! as Map).cast<String, Object?>();
        _setBranding(m['branding']);
        positions.clear();
        for (final p in (m['positions'] as List?) ?? const []) {
          if (p is Map && p['player_id'] is String) {
            positions[p['player_id']! as String] = p.cast<String, Object?>();
          }
        }
      case 'game':
        final g = m['game'] as Map<String, Object?>?;
        if (g != null &&
            (game == null || g['live'] == true || g['id'] == game!['id'])) {
          if (game != null && g['id'] != game!['id']) {
            events.clear();
            eliminated.clear();
            lives.clear();
            _objectiveNews.clear();
            totals = const {};
          }
          _setGame(g);
        }
      case 'branding':
        _setBranding(m['branding']);
      case 'score':
        if (game != null && m['game'] == game!['id'] && m['teams'] is Map) {
          totals = _ints(m['teams']! as Map);
        }
      case 'node':
        final n = m['node'];
        if (n is Map<String, Object?> && n['node_id'] is int) {
          nodes[n['node_id']! as int] = {...?nodes[n['node_id']], ...n};
        }
      case 'event':
        final e = m['event'];
        if (e is Map<String, Object?>) {
          _onEvent(e);
          final d = e['data'];
          if (e['type'] == 'scenario.objective.revealed' &&
              d is Map &&
              (d['objective'] is String || d['leader_only'] == true)) {
            ordersSeq++;
          }
        }
      case 'checkin':
        final c = m['checkin'];
        if (c is Map && (me == null || c['player_id'] == me!['player_id'])) {
          me = c.cast<String, Object?>();
        }
      case 'chrono_list':
        final mine = me;
        if (mine != null && m['player_id'] == mine['player_id']) {
          me = {...mine, 'declarations': m['declarations']};
        }
      case 'player_position':
        final p = m['position'];
        if (p is Map && p['player_id'] is String) {
          positions[p['player_id']! as String] = p.cast<String, Object?>();
        }
      case 'map_features':
        mapFeatures = [
          for (final f in (m['features'] as List?) ?? const [])
            if (f is Map) f.cast<String, Object?>(),
        ];
      case 'positions':
        positions.clear();
        for (final p in (m['positions'] as List?) ?? const []) {
          if (p is Map && p['player_id'] is String) {
            positions[p['player_id']! as String] = p.cast<String, Object?>();
          }
        }
    }
    notifyListeners();
  }

  void _onEvent(Map<String, Object?> e) {
    final data = (e['data'] as Map?)?.cast<String, Object?>() ?? const {};
    final team = e['team'] is String ? e['team']! as String : data['team'];
    final ev = FeedEvent(
      '${e['type']}',
      team is String ? team : null,
      data,
      e['t'] is int ? e['t']! as int : 0,
      e['node'] is int ? e['node']! as int : 0,
    );
    events.insert(0, ev);
    if (events.length > 100) events.removeLast();
    switch (ev.type) {
      case 'team.eliminated':
        if (ev.team != null) eliminated.add(ev.team!);
      case 'player.respawn':
        final left = data['lives_left'];
        final who = data['player'] ?? ev.team;
        if (left is int && who is String) lives[who] = left;
      case 'zone.captured':
        final n = nodes[ev.node];
        if (n != null && ev.team != null) n['owner'] = ev.team;
      case 'scenario.objective.revealed':
        final id = data['objective'];
        if (id is String && _objectiveNews[id] == null) {
          _objectiveNews[id] = (ObjectiveState.active, null, null);
        }
      case 'scenario.objective.completed' || 'scenario.objective.failed':
        final id = data['objective'];
        final reason = data['reason'];
        if (id is String) {
          _objectiveNews[id] = (
            ev.type.endsWith('completed')
                ? ObjectiveState.done
                : ObjectiveState.failed,
            ev.team,
            reason is String ? reason : null,
          );
        }
    }
  }

  /// The game's scenario as this connection may see it (its name and
  /// objectives), or null.
  Map<String, Object?>? get scenario {
    final s = game?['scenario'];
    return s is Map ? s.cast<String, Object?>() : null;
  }

  /// The scenario's objectives this player may know, in the scenario's
  /// order. The controller sends only those (a hidden one once revealed);
  /// one with no event yet is waiting before the game starts and active
  /// after (its reveal may be older than the events the stream kept).
  List<ScenarioObjective> get objectives {
    final list = scenario?['objectives'];
    if (list is! List) return const [];
    final started = gameState != null && gameState != 'ready';
    return [
      for (final o in list)
        if (o is Map && o['id'] is String)
          _objective(o.cast<String, Object?>(), started),
    ];
  }

  ScenarioObjective _objective(Map<String, Object?> info, bool started) {
    final news = _objectiveNews[info['id']];
    return ScenarioObjective(
      info,
      news?.$1 ?? (started ? ObjectiveState.active : ObjectiveState.waiting),
      team: news?.$2,
      reason: news?.$3,
    );
  }

  void _setGame(Map<String, Object?>? g) {
    game = g;
    final ms = g?['game_time_ms'];
    if (ms is int) {
      _baseMs = ms;
      _baseAt = _now();
      _baseRunning = g!['state'] == 'running';
    } else {
      _baseMs = null;
    }
  }

  static Map<String, int> _ints(Map<Object?, Object?> m) => {
    for (final e in m.entries)
      if (e.value is int) '${e.key}': e.value! as int,
  };

  /// The game time now, following the clock between messages.
  int? get gameTimeMs {
    final b = _baseMs;
    if (b == null) return null;
    if (!_baseRunning) return b;
    return b + _now().difference(_baseAt!).inMilliseconds;
  }

  /// Time left with a game length, else null.
  int? get remainingMs {
    final d = game?['duration_ms'];
    final t = gameTimeMs;
    if (d is! int || d <= 0 || t == null) return null;
    return (d - t).clamp(0, d);
  }

  /// The teams by points, best first; ties keep the game's order.
  List<(String, int)> get ranking {
    final t = teams;
    final r = [for (var i = 0; i < t.length; i++) (t[i], totals[t[i]] ?? 0, i)];
    r.sort((a, b) => a.$2 != b.$2 ? b.$2.compareTo(a.$2) : a.$3 - b.$3);
    return [for (final x in r) (x.$1, x.$2)];
  }

  @override
  void dispose() {
    _stopped = true;
    _retry?.cancel();
    unawaited(_socket?.close());
    super.dispose();
  }
}
