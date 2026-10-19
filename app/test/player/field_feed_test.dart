// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The player view's model: the controller's address and code from a
// scoreboard link, and the live feed (WS /api/v1/stream) turned into the
// game, the points, objectives, lives, eliminations and events; the
// connection's states and reconnection. The messages are the shapes the
// controller sends (controller/atalaia_controller/api.py, engine.py).

import 'dart:async';
import 'dart:convert';

import 'package:atalaia_app/player/field_feed.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeSocket implements FeedSocket {
  final _messages = StreamController<String>();
  @override
  int? closeCode;

  void send(Map<String, Object?> m) => _messages.add(jsonEncode(m));

  Future<void> drop([int? code]) async {
    closeCode = code;
    await _messages.close();
  }

  @override
  Stream<String> get messages => _messages.stream;

  @override
  Future<void> close() => drop(1000);
}

final hello = {
  'type': 'hello',
  'status': {'live_game': 7},
  'game': {
    'id': 7,
    'name': 'Domingo',
    'teams': ['red', 'blue'],
    'state': 'running',
    'duration_ms': 600000,
    'game_time_ms': 60000,
    'live': true,
  },
  'score': {
    'game': 7,
    'teams': {'red': 3, 'blue': 5},
  },
  'nodes': [
    {'node_id': 2, 'name': 'Moinho', 'owner': null, 'role': 'zone'},
    {'node_id': 3, 'owner': 'blue', 'role': 'zone'},
  ],
};

void main() {
  group('links', () {
    test("the scoreboard's address with its code", () {
      final l = FieldLink.parse(
        'http://192.168.4.1:8080/scoreboard#token=abc-123&lang=en',
      )!;
      expect(l.base.toString(), 'http://192.168.4.1:8080');
      expect(l.token, 'abc-123');
      expect(
        l.stream.toString(),
        'ws://192.168.4.1:8080/api/v1/stream?token=abc-123',
      );
      expect(l.console.toString(), 'http://192.168.4.1:8080/console/');
    });

    test('an address and a separate code; the default port; https', () {
      expect(
        FieldLink.parse('field.local', 'x')!.base.toString(),
        'http://field.local:8080',
      );
      expect(
        FieldLink.parse(
          'https://campo.pt/scoreboard.html#token=t',
        )!.stream.scheme,
        'wss',
      );
    });

    test('no host or no code: none', () {
      expect(FieldLink.parse(''), isNull);
      expect(FieldLink.parse('http://10.0.0.1:8080/scoreboard'), isNull);
      expect(FieldLink.parse('ftp://x/#token=a'), isNull);
      expect(FieldLink.parse('atalaia:join:AAAA'), isNull);
    });
  });

  group('the feed', () {
    late FakeSocket socket;
    late FieldFeed feed;
    var now = DateTime(2026, 10, 19, 15);

    setUp(() {
      socket = FakeSocket();
      feed = FieldFeed(
        FieldLink.parse('10.0.0.1', 'code')!,
        connect: (uri) async {
          expect(uri.queryParameters['token'], 'code');
          return socket;
        },
        now: () => now,
      );
    });

    tearDown(() => feed.dispose());

    Future<void> settle() => Future<void>.delayed(Duration.zero);

    test('a snapshot, then scores, nodes and events', () async {
      unawaited(feed.start());
      await settle();
      expect(feed.state, FeedState.open);
      socket.send(hello);
      await settle();
      expect(feed.game!['name'], 'Domingo');
      expect(feed.totals, {'red': 3, 'blue': 5});
      expect(feed.ranking, [('blue', 5), ('red', 3)]);
      expect(feed.nodes.keys, [2, 3]);
      expect(feed.remainingMs, 540000);
      now = now.add(const Duration(seconds: 10));
      expect(feed.gameTimeMs, 70000); // the clock runs between messages

      socket
        ..send({
          'type': 'score',
          'game': 7,
          'teams': {'red': 9, 'blue': 5},
        })
        ..send({
          'type': 'event',
          'game': 7,
          'event': {
            'node': 2,
            't': 61000,
            'type': 'zone.captured',
            'team': 'red',
            'data': {'zone': 'Moinho'},
          },
        })
        ..send({
          'type': 'event',
          'game': 7,
          'event': {
            'node': 4,
            't': 62000,
            'type': 'player.respawn',
            'team': 'blue',
            'data': {'player': 'b3', 'lives_left': 4},
          },
        })
        ..send({
          'type': 'event',
          'game': 7,
          'event': {
            'node': 4,
            't': 63000,
            'type': 'team.eliminated',
            'team': 'red',
          },
        })
        ..send({
          'type': 'node',
          'game': 7,
          'kind': 'update',
          'node': {'node_id': 3, 'battery': 80},
        });
      await settle();
      expect(feed.ranking.first, ('red', 9));
      expect(feed.nodes[2]!['owner'], 'red');
      expect(feed.nodes[3]!['owner'], 'blue');
      expect(feed.nodes[3]!['battery'], 80);
      expect(feed.lives, {'b3': 4});
      expect(feed.eliminated, {'red'});
      expect(feed.events.first.type, 'team.eliminated');
      expect(feed.events.length, 3);
    });

    test('ties keep the teams in their order', () async {
      unawaited(feed.start());
      await settle();
      socket.send({
        ...hello,
        'score': {
          'game': 7,
          'teams': {'red': 4, 'blue': 4},
        },
      });
      await settle();
      expect(feed.ranking, [('red', 4), ('blue', 4)]);
    });

    test('a score for another game is ignored; a new live game starts '
        'afresh', () async {
      unawaited(feed.start());
      await settle();
      socket
        ..send(hello)
        ..send({
          'type': 'score',
          'game': 99,
          'teams': {'red': 50},
        });
      await settle();
      expect(feed.totals['red'], 3);
      socket.send({
        'type': 'game',
        'game': {
          'id': 8,
          'name': 'Tarde',
          'teams': ['red', 'blue'],
          'state': 'ready',
          'live': true,
        },
      });
      await settle();
      expect(feed.game!['id'], 8);
      expect(feed.totals, isEmpty);
      expect(feed.events, isEmpty);
      expect(feed.gameTimeMs, isNull);
    });

    test('a refused code stops; a dropped link reconnects', () async {
      var attempts = 0;
      final sockets = <FakeSocket>[];
      final f = FieldFeed(
        FieldLink.parse('10.0.0.1', 'code')!,
        connect: (uri) async {
          attempts++;
          final s = FakeSocket();
          sockets.add(s);
          return s;
        },
      );
      addTearDown(f.dispose);
      unawaited(f.start());
      await settle();
      await sockets.last.drop(1006);
      await settle();
      expect(f.state, FeedState.closed);
      await Future<void>.delayed(const Duration(milliseconds: 1100));
      expect(attempts, 2);
      expect(f.state, FeedState.open);
      await sockets.last.drop(4401);
      await settle();
      expect(f.state, FeedState.denied);
      await Future<void>.delayed(const Duration(milliseconds: 2100));
      expect(attempts, 2);
    });
  });

  group('with a player token (plan phase E)', () {
    Future<void> settle() => Future<void>.delayed(Duration.zero);

    test(
      "the snapshot's history, the player's own row and positions",
      () async {
        final socket = FakeSocket();
        final feed = FieldFeed(
          FieldLink(Uri.parse('https://10.0.2.2:8443'), 'apt1.a'),
          connect: (uri) async {
            expect(
              uri.toString(),
              'wss://10.0.2.2:8443/api/v1/stream?token=apt1.a',
            );
            return socket;
          },
        );
        addTearDown(feed.dispose);
        unawaited(feed.start());
        await settle();
        socket.send({
          ...hello,
          'events': [
            {
              'node': 0,
              't': 0,
              'type': 'game.start',
              'data': {'preset': 'x'},
            },
            {
              'node': 2,
              't': 4000,
              'type': 'zone.captured',
              'team': 'red',
              'data': <String, Object?>{},
            },
            {
              'node': 5,
              't': 9000,
              'type': 'player.respawn',
              'team': 'blue',
              'data': {'lives_left': 2},
            },
          ],
          'me': {
            'player_id': 'p-abcdefgh2345',
            'role': 'player',
            'team': 'red',
          },
          'positions': [
            {'player_id': 'p-abcdefgh2345', 'lat': 38.7, 'lon': -9.1},
          ],
        });
        await settle();
        // Events from before the phone connected, newest first.
        expect(feed.events.map((e) => e.type), [
          'player.respawn',
          'zone.captured',
          'game.start',
        ]);
        expect(feed.lives, {'blue': 2});
        expect(feed.me!['team'], 'red');
        expect(feed.positions.keys, ['p-abcdefgh2345']);
        socket
          ..send({
            'type': 'player_position',
            'game': 7,
            'position': {'player_id': 'p-bbbbbbbbbbbb', 'lat': 1, 'lon': 2},
          })
          ..send({
            'type': 'checkin',
            'game': 7,
            'checkin': {
              'player_id': 'p-abcdefgh2345',
              'role': 'player',
              'team': 'blue',
            },
          })
          ..send({
            'type': 'checkin',
            'game': 7,
            'checkin': {'player_id': 'p-zzzzzzzzzzzz', 'team': 'red'},
          });
        await settle();
        expect(feed.positions, hasLength(2));
        expect(feed.me!['team'], 'blue'); // only the player's own row
        // A reconnect's snapshot starts the history over, without duplicates.
        socket.send({
          ...hello,
          'events': [
            {
              'node': 0,
              't': 0,
              'type': 'game.start',
              'data': <String, Object?>{},
            },
          ],
        });
        await settle();
        expect(feed.events, hasLength(1));
      },
    );

    test('closed with 4409: a new token, then the stream again', () async {
      final sockets = <FakeSocket>[];
      final tokens = <String>[];
      final feed = FieldFeed(
        FieldLink.parse('https://10.0.2.2:8443', 'apt1.old')!,
        connect: (uri) async {
          tokens.add(uri.queryParameters['token']!);
          return (sockets..add(FakeSocket())).last;
        },
        onAssignment: () async => 'apt1.new',
      );
      addTearDown(feed.dispose);
      unawaited(feed.start());
      await settle();
      await sockets.single.drop(4409);
      await Future<void>.delayed(const Duration(milliseconds: 300));
      expect(tokens, ['apt1.old', 'apt1.new']);
    });
  });
}
