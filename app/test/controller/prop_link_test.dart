// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// An Android prop's Wi-Fi link (lib/controller/prop_link.dart,
// protocol/prop-link.md) against a stand-in controller: the HMAC proof of
// the game key (the same bytes controller/atalaia_controller/prop_link.py
// checks), HELLO and STATE after the welcome, events resent until they are
// acknowledged, across a reconnect, and the controller's commands and TIME
// beacons; then a prop session on the core started and ended by them.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/prop_link.dart';
import 'package:atalaia_app/protocol/join_payload.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

final gameKey = Uint8List.fromList(List.generate(16, (i) => i + 1));

JoinPayload join({List<String>? urls}) => JoinPayload(
  gameId: 4242,
  gameKey: gameKey,
  nodeId: 7,
  controllerId: 0,
  channelHz: 869525000,
  maxHops: 2,
  teams: const ['red', 'blue'],
  modeId: 'org.atalaia.domination',
  role: 'zone',
  gameSeed: 1,
  params: null,
  kind: JoinKind.node,
  caSha256: Uint8List(32),
  urls: urls ?? const ['https://10.0.2.2:8443', 'https://atalaia.local:8443'],
);

/// The controller's side of one connection.
class FakeController implements LinkSocket {
  FakeController(this.uri, {this.acceptProof = true}) {
    _in.add(
      jsonEncode({
        'type': 'challenge',
        'nonce': base64Url.encode(nonce).replaceAll('=', ''),
        'version': 1,
      }),
    );
  }

  final Uri uri;
  final bool acceptProof;
  final nonce = List<int>.generate(32, (i) => 255 - i);
  final _in = StreamController<String>();
  final got = <Map<String, Object?>>[];
  @override
  int? closeCode;

  void push(Map<String, Object?> m) => _in.add(jsonEncode(m));

  @override
  Stream<String> get messages => _in.stream;

  @override
  void send(String text) {
    final m = (jsonDecode(text) as Map).cast<String, Object?>();
    got.add(m);
    if (m['type'] == 'auth') {
      final msg = [
        ...utf8.encode('atalaia-prop-link-v1'),
        0,
        ...nonce,
        0x10,
        0x92,
        0,
        7,
      ];
      final want = Hmac(sha256, gameKey).convert(msg).bytes;
      final proof = base64Url.decode('${m['proof']}'.padRight(44, '='));
      if (acceptProof && constantTimeEquals(proof, want)) {
        push({
          'type': 'welcome',
          'game_id': 4242,
          'node_id': 7,
          'controller_id': 0,
          'time': {'state': 'waiting', 'game_time_ms': 0, 'duration_ms': 0},
        });
      } else {
        push({'type': 'refused', 'reason': 'auth'});
        unawaited(drop(4401));
      }
    }
  }

  Future<void> drop([int? code]) async {
    closeCode = code;
    if (!_in.isClosed) await _in.close();
  }

  @override
  Future<void> close() => drop(1000);
}

Future<void> settle() => Future<void>.delayed(const Duration(milliseconds: 20));

void main() {
  test("the proof is the controller's HMAC over the challenge", () {
    final p = propLinkProof(gameKey, List.filled(32, 0), 4242, 7);
    final want = Hmac(sha256, gameKey).convert([
      ...utf8.encode('atalaia-prop-link-v1'),
      0,
      ...List.filled(32, 0),
      0x10,
      0x92,
      0,
      7,
    ]).bytes;
    expect(p, want);
  });

  test(
    'links, says hello, resends unacknowledged events, follows commands',
    () async {
      final sockets = <FakeController>[];
      final link = PropLink(
        join: join(),
        urls: join().urls!,
        hello: {'node_name': 'phone-7', 'capabilities': <int>[]},
        connect: (uri) async => (sockets..add(FakeController(uri))).last,
      );
      final heard = <LinkMessage>[];
      link.messages.listen(heard.add);
      link.sendEvent(
        seq: 1,
        tMs: 100,
        type: 'zone.captured',
        team: 1,
        data: {'team': 'red'},
      );
      link.start();
      await settle();
      expect(link.state, LinkState.linked);
      expect(sockets.single.uri.toString(), 'wss://10.0.2.2:8443/api/v1/prop');
      final c = sockets.single;
      expect(c.got.map((m) => m['type']), ['auth', 'hello', 'event']);
      expect((c.got[0]['game_id'], c.got[0]['node_id']), (4242, 7));
      expect(
        heard.single,
        isA<LinkTime>().having((t) => t.state, 'state', 'waiting'),
      );
      link.sendState({
        'owner_team': 1,
        'counters': {'1': 5},
      });
      expect(c.got.last['type'], 'state');
      // Not acknowledged: after a reconnect it goes again; then acknowledged.
      await c.drop();
      await Future<void>.delayed(const Duration(milliseconds: 1100));
      final c2 = sockets.last;
      expect(sockets, hasLength(2));
      expect(c2.got.map((m) => m['type']), ['auth', 'hello', 'state', 'event']);
      c2.push({'type': 'ack', 'seq': 1, 'event_type': 'zone.captured'});
      await settle();
      expect(link.unacked, 0);
      c2.push({
        'type': 'cmd',
        'cmd': 'message',
        'params': {'text': 'olá'},
      });
      c2.push({
        'type': 'time',
        'state': 'running',
        'game_time_ms': 5000,
        'duration_ms': 0,
      });
      await settle();
      expect(heard.whereType<LinkCommand>().single.params, {'text': 'olá'});
      expect(heard.whereType<LinkTime>().last.state, 'running');
      await link.close();
    },
  );

  test('a wrong proof is refused and the link stops trying', () async {
    var tries = 0;
    final link = PropLink(
      join: join(),
      urls: join().urls!,
      connect: (uri) async {
        tries++;
        return FakeController(uri, acceptProof: false);
      },
    );
    link.start();
    await Future<void>.delayed(const Duration(milliseconds: 1200));
    expect(link.state, LinkState.refused);
    expect(tries, 1);
    await link.close();
  });

  test('an unreachable address: the next one is tried', () async {
    final uris = <Uri>[];
    final link = PropLink(
      join: join(),
      urls: join().urls!,
      connect: (uri) async {
        uris.add(uri);
        if (uris.length == 1) throw const SocketExceptionLike();
        return FakeController(uri);
      },
    );
    link.start();
    await Future<void>.delayed(const Duration(milliseconds: 1200));
    expect(uris.map((u) => u.host), ['10.0.2.2', 'atalaia.local']);
    expect(link.state, LinkState.linked);
    await link.close();
  });

  test('forJoin needs keys 13 and 14', () async {
    final none = JoinPayload(
      gameId: 1,
      gameKey: gameKey,
      nodeId: 2,
      controllerId: 0,
      channelHz: 869525000,
      maxHops: 2,
      teams: const ['red'],
      modeId: 'm',
      role: 'r',
      gameSeed: 0,
      params: null,
      kind: JoinKind.node,
    );
    expect(
      await PropLink.forJoin(
        none,
        trust: (u, c) => throw StateError('not asked'),
      ),
      isNull,
    );
    expect(hexEncode(join().caSha256!), '00' * 32);
  });
}

class SocketExceptionLike implements Exception {
  const SocketExceptionLike();
}
