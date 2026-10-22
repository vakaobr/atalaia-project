// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// The live feed behind `WS /api/v1/stream` on the Android field controller
/// (ADR-P3-12, decision PE24, slice S2): the Pi controller's stream
/// (controller/atalaia_controller/ws.py and api.py's `stream`, `_snapshot`
/// and `make_route`) with the same messages, order and filtering, checked by
/// the shared contract cases (protocol/vectors/controller_api.json).
///
/// A client connects with the GM token or the read token (`?token=` or
/// `Authorization: Bearer`); any other token is closed with 4401. Its first
/// message is the hello snapshot: the live game, its score, its nodes, its
/// latest 100 events and the controller's state, so a client that connects
/// mid-game shows what already happened. Then every message the engine
/// emits (game, event, score, node, system, field_state), in the engine's
/// order. `{"type": "ping"}` is answered with `{"type": "pong"}`.
///
/// Filtering (decisions M5-1, PE6): the read token gets games without their
/// gm_only parameters and events without their gm_only data; messages
/// marked for staff (`_staff`, `_player`: check-in, from slice S5) reach the
/// GM token only; keys starting with "_" never leave the controller.
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

/// A message without its routing marks (keys starting with "_").
Map<String, Object?> publicMessage(Map<String, Object?> msg) => {
  for (final e in msg.entries)
    if (!e.key.startsWith('_')) e.key: e.value,
};

final class _Client {
  _Client(this.socket, this.role);

  final WebSocket socket;

  /// "gm" or "read" (player tokens: slice S5).
  final String role;
  final pending = Queue<Map<String, Object?>>();
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

  /// What [role] gets of [msg], or null (api.py `make_route`).
  Map<String, Object?>? route(String role, Map<String, Object?> msg) {
    final staff = role == 'gm';
    if (msg['_staff'] == true || msg.containsKey('_player')) {
      return staff ? publicMessage(msg) : null;
    }
    if (msg['_position'] == true || msg['_positions_refresh'] == true) {
      return null; // player positions: slice S5
    }
    final out = publicMessage(msg);
    if (staff) return out;
    final ev = out['event'];
    final game = out['game'];
    if (out['type'] == 'event' && ev is Map<String, Object?>) {
      out['event'] = publicEvent(ev);
    } else if (out['type'] == 'game' && game is Map<String, Object?>) {
      out['game'] = engine.playersGame(game);
    }
    return out;
  }

  /// The first message of a connection (api.py `_snapshot`).
  Map<String, Object?> snapshot(String role) {
    final staff = role == 'gm';
    final status = engine.status();
    final gameId = status['live_game'] as int?;
    var events = <Map<String, Object?>>[];
    Map<String, Object?>? game;
    if (gameId != null) {
      final all = engine.log(gameId);
      events = [
        for (final e in all.skip(max(0, all.length - helloEvents)))
          {for (final k in _helloEventKeys) k: e[k]},
      ];
      if (!staff) events = [for (final e in events) publicEvent(e)];
      game = engine.getGame(gameId);
      if (!staff) game = engine.playersGame(game);
    }
    return {
      'type': 'hello',
      'game': game,
      'score': gameId == null ? null : engine.score(gameId),
      'nodes': gameId == null ? const <Object?>[] : engine.nodes(gameId),
      'events': events,
      'status': status,
    };
  }

  /// Takes an accepted connection for [role] ("gm" or "read"): sends the
  /// hello and follows the feed until either side closes.
  void connect(WebSocket socket, String role) {
    final c = _Client(socket, role);
    socket.add(jsonEncode(snapshot(role)));
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
      final Map<String, Object?>? out;
      try {
        out = route(c.role, msg);
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
  }

  /// Closes every connection (the controller is stopping).
  Future<void> close() async {
    for (final c in List.of(_clients)) {
      _remove(c);
      await c.socket.close(WebSocketStatus.goingAway);
    }
  }
}
