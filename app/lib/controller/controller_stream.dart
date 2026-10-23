// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The live feed behind `WS /api/v1/stream` on the Android field controller
/// (ADR-P3-12, decision PE24, slice S2): the Pi controller's stream
/// (controller/atalaia_controller/ws.py and api.py's `stream`, `_snapshot`
/// and `make_route`) with the same messages, order and filtering, checked by
/// the shared contract cases (protocol/vectors/controller_api.json).
///
/// A client connects with the GM token, the read token or a player token
/// (slice S5; `?token=` or `Authorization: Bearer`); any other token is
/// closed with 4401. Its first message is the hello snapshot: the live
/// game, its score, its nodes, its latest 100 events and the controller's
/// state, so a client that connects mid-game shows what already happened; a
/// player's hello has only the live game's id as its state, and its own
/// check-in (`me`) and the positions it may see. Then every message the
/// engine emits (game, event, score, node, system, field_state, check-in
/// and positions), in the engine's order. `{"type": "ping"}` is answered
/// with `{"type": "pong"}`.
///
/// Filtering (decisions M5-1, PE6; api.py `make_route`): players and the
/// read token get games without their gm_only parameters and events without
/// their gm_only data; messages marked for staff (`_staff`, `_player`:
/// check-in and the chrono list, with names) reach staff (the GM token, a
/// marshal's or gm's token of that game) and, for their own row, the
/// player, whose connection is closed with 4409 after a change of team,
/// squad or role (`_assignment`: fetch a new token); a player position
/// reaches those who may see it (controller_positions.dart); a player's
/// connection gets nothing of the radio or the controller's internals. Keys
/// starting with "_" never leave the controller.
///
/// A client more than [StreamHub.maxQueue] messages behind is closed with
/// 4408 rather than slowing everyone down; it reconnects and its new hello
/// is the catch-up (there is no replay by sequence number, as on the Pi).
/// Here the backlog is the messages handed to a client that its sender has
/// not yet written to the socket; the sender writes them on the next turn
/// of the event loop.
library;

import 'dart:async';
import 'dart:collection';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'controller_checkin.dart';
import 'controller_engine.dart';

/// How many of a game's latest events the hello carries (api.py HELLO_EVENTS).
const helloEvents = 100;

/// The keys of an event in the hello (api.py `_snapshot`).
const _helloEventKeys = [
  'node',
  'seq',
  't',
  'type',
  'team',
  'squad',
  'prio',
  'data',
];

/// What a player-token connection is sent (besides its own check-in
/// messages): ws.py's PLAYER_TYPES.
const playerTypes = {
  'hello',
  'game',
  'score',
  'node',
  'event',
  'field_state',
  'positions',
  'player_position',
  'checkin',
  'chrono_list',
  'checkin_open',
  'pong',
  'branding',
  'map_features',
};

/// A message without its routing marks (keys starting with "_").
Map<String, Object?> publicMessage(Map<String, Object?> msg) => {
  for (final e in msg.entries)
    if (!e.key.startsWith('_')) e.key: e.value,
};

final class _Client {
  _Client(this.socket, this.viewer);

  final WebSocket socket;

  /// Whose connection it is: the GM token, the read token or a player.
  final ApiViewer viewer;
  final pending = Queue<Map<String, Object?>>();
  int? closeWith;
  var scheduled = false;
  var closed = false;
}

class StreamHub {
  StreamHub(this.engine, {this.maxQueue = 256});

  final ControllerEngine engine;

  /// The backlog after which a client is dropped (ws.py's max_queue).
  int maxQueue;

  final _clients = <_Client>{};

  /// Clients closed with 4408 for falling behind.
  int droppedClients = 0;

  int get clientCount => _clients.length;

  /// What [v] gets of [msg], or null (api.py `make_route`).
  Map<String, Object?>? route(ApiViewer v, Map<String, Object?> msg) {
    if (msg['_staff'] == true || msg.containsKey('_player')) {
      final game = msg['game'];
      final staff = v.isStaff && (v.kind != 'player' || v.gameId == game);
      final own = _own(v, msg);
      return staff || own ? publicMessage(msg) : null;
    }
    if (msg['_position'] == true) {
      final pos = engine.positions;
      final p = msg['position'];
      return pos != null && p is Map<String, Object?> && pos.canSee(v, p)
          ? publicMessage(msg)
          : null;
    }
    if (msg['_positions_refresh'] == true) {
      final pos = engine.positions;
      if (pos == null || v.kind == 'read') return null;
      return {
        'type': 'positions',
        'game': msg['game'],
        'positions': pos.visible(v, msg['game'] as int?),
      };
    }
    if (msg['_map_features'] == true) {
      // Each connection gets the features its token may see, whole (MF-10;
      // slice S7a): never another team's or the staff's.
      final field = engine.field;
      if (field == null) return null;
      return {'type': 'map_features', 'features': field.visibleFeatures(v)};
    }
    if (v.kind == 'player' && !playerTypes.contains(msg['type'])) return null;
    final out = publicMessage(msg);
    final ev = out['event'];
    final game = out['game'];
    if (out['type'] == 'event' &&
        ev is Map<String, Object?> &&
        !v.isStaffOf(out['game'] as int?)) {
      out['event'] = engine.eventFor(v, out['game'], ev);
    } else if (out['type'] == 'game' &&
        game is Map<String, Object?> &&
        !v.isStaffOf(game['id'] as int?)) {
      out['game'] = engine.playersGame(game, v);
    }
    return out;
  }

  /// A message about [v]'s own check-in.
  static bool _own(ApiViewer v, Map<String, Object?> msg) =>
      v.kind == 'player' &&
      v.playerId != null &&
      v.playerId == msg['_player'] &&
      v.gameId == msg['game'];

  /// After [msg], [v]'s connection is closed with 4409: the GM changed the
  /// player's team, squad or role, and the app fetches a new token.
  static bool closesAfter(ApiViewer v, Map<String, Object?> msg) =>
      msg['_assignment'] == true && _own(v, msg);

  /// The first message of a connection (api.py `_snapshot`).
  Map<String, Object?> snapshot(ApiViewer viewer) {
    final status = engine.status();
    final gameId = status['live_game'] as int?;
    final staff = viewer.isStaffOf(gameId);
    var events = <Map<String, Object?>>[];
    Map<String, Object?>? game;
    if (gameId != null) {
      final all = engine.log(gameId);
      events = [
        for (final e in all.skip(max(0, all.length - helloEvents)))
          {for (final k in _helloEventKeys) k: e[k]},
      ];
      if (!staff) {
        events = [for (final e in events) engine.eventFor(viewer, gameId, e)];
      }
      game = engine.getGame(gameId);
      if (!staff) game = engine.playersGame(game, viewer);
    }
    final out = <String, Object?>{
      'type': 'hello',
      'game': game,
      'score': gameId == null ? null : engine.score(gameId),
      'nodes': gameId == null ? const <Object?>[] : engine.nodes(gameId),
      'events': events,
    };
    // Public: the field's name, images and accent (slice S7b).
    final branding = engine.branding;
    if (branding != null) out['branding'] = branding.view();
    if (viewer.kind != 'player') return out..['status'] = status;
    out['status'] = {'live_game': gameId};
    final me = engine.checkin?.me(viewer, forHello: true);
    if (me != null) out['me'] = me;
    final pos = engine.positions;
    if (pos != null) out['positions'] = pos.visible(viewer);
    return out;
  }

  /// Takes an accepted connection for [viewer]: sends the hello and follows
  /// the feed until either side closes.
  void connect(WebSocket socket, ApiViewer viewer) {
    final c = _Client(socket, viewer);
    socket.add(jsonEncode(snapshot(viewer)));
    _clients.add(c);
    socket.listen(
      (data) {
        if (data is! String) return;
        Object? msg;
        try {
          msg = jsonDecode(data);
        } on FormatException {
          return;
        }
        if (msg is Map && msg['type'] == 'ping' && !c.closed) {
          socket.add(jsonEncode({'type': 'pong'}));
        }
      },
      onDone: () => _remove(c),
      onError: (Object _) => _remove(c),
      cancelOnError: true,
    );
  }

  void _remove(_Client c) {
    c.closed = true;
    c.pending.clear();
    _clients.remove(c);
  }

  /// Hands [msg] to every client as its token may see it (the engine's
  /// listener).
  void publish(Map<String, Object?> msg) {
    for (final c in List.of(_clients)) {
      if (c.closeWith != null) continue;
      final Map<String, Object?>? out;
      try {
        out = route(c.viewer, msg);
      } on Object {
        continue; // a routing bug must not stop the feed for everyone
      }
      if (out == null) continue;
      if (c.pending.length >= maxQueue) {
        droppedClients++;
        _remove(c);
        unawaited(c.socket.close(4408)); // too slow: reconnect for a new hello
        continue;
      }
      c.pending.add(out);
      if (closesAfter(c.viewer, msg)) c.closeWith = 4409;
      if (!c.scheduled) {
        c.scheduled = true;
        Timer.run(() => _send(c));
      }
    }
  }

  void _send(_Client c) {
    c.scheduled = false;
    while (c.pending.isNotEmpty && !c.closed) {
      c.socket.add(jsonEncode(c.pending.removeFirst()));
    }
    final code = c.closeWith;
    if (code != null && !c.closed) {
      _remove(c);
      unawaited(c.socket.close(code)); // e.g. 4409: fetch a new token
    }
  }

  /// Closes every connection (the controller is stopping).
  Future<void> close() async {
    for (final c in List.of(_clients)) {
      _remove(c);
      await c.socket.close(WebSocketStatus.goingAway);
    }
  }
}
