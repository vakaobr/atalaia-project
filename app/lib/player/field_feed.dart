// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The player view's link to a field controller: its address and an access
/// code (the read token, controller/README.md "REST API v1"), and the live
/// feed of WS /api/v1/stream, as the controller's scoreboard page follows
/// it: a snapshot first, then games, scores, events and nodes. Reconnects
/// after 1 s, doubling up to 15 s; a refused code (close 4401) stops.
///
/// Player tokens with roles, and positions, are plan phase E: the feed here
/// is what every holder of the read code sees.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

/// A field controller's address and access code.
final class FieldLink {
  const FieldLink(this.base, this.token);

  /// http://host:port
  final Uri base;
  final String token;

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

enum FeedState { connecting, open, closed, denied }

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
  FieldFeed(this.link, {FeedConnect? connect, DateTime Function()? now})
    : _connect = connect ?? ioConnect,
      _now = now ?? DateTime.now;

  final FieldLink link;
  final FeedConnect _connect;
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
      case 'game':
        final g = m['game'] as Map<String, Object?>?;
        if (g != null &&
            (game == null || g['live'] == true || g['id'] == game!['id'])) {
          if (game != null && g['id'] != game!['id']) {
            events.clear();
            eliminated.clear();
            lives.clear();
            totals = const {};
          }
          _setGame(g);
        }
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
        if (e is Map<String, Object?>) _onEvent(e);
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
    }
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
