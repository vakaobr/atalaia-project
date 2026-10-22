// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The embedded MQTT 3.1.1 broker of the Android controller role
// (lib/controller/mqtt_broker.dart, ADR-P3-12) over real local sockets,
// with a small client written here from the MQTT 3.1.1 packet layouts:
// connect, subscribe with wildcards, the controller's publications at QoS 0
// and 1, retained topics for late subscribers, ping, unsubscribe, the
// limit of 20 connections, QoS 2 and client publications refused.

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:atalaia_app/controller/mqtt_broker.dart';
import 'package:flutter_test/flutter_test.dart';

List<int> _len(int n) {
  final out = <int>[];
  do {
    var d = n % 128;
    n ~/= 128;
    if (n > 0) d |= 0x80;
    out.add(d);
  } while (n > 0);
  return out;
}

List<int> _str(String s) {
  final b = utf8.encode(s);
  return [b.length >> 8, b.length & 0xff, ...b];
}

List<int> packet(int header, List<int> body) => [
  header,
  ..._len(body.length),
  ...body,
];

/// A test client: raw packets in and out.
class Client {
  Client._(this.socket) {
    socket.listen(
      (d) {
        _buf.addAll(d);
        _parse();
      },
      // A broker that refuses a connection (the 21st) may close it before or
      // after the CONNECT arrives: the client then sees the end, a reset or a
      // broken pipe, depending on the timing (it failed under load). Each is
      // "the broker closed it", never an error of the test.
      onError: (Object _) => _closed(),
      onDone: _closed,
      cancelOnError: true,
    );
    socket.done.then((_) {}, onError: (Object _) => _closed());
  }

  void _closed() {
    if (!closed.isCompleted) closed.complete();
  }

  final Socket socket;
  final _buf = <int>[];
  final packets = StreamController<(int, Uint8List)>.broadcast();
  final got = <(int, Uint8List)>[];
  final closed = Completer<void>();

  static Future<Client> connect(
    int port, {
    String id = 'board',
    int keepAlive = 30,
  }) async {
    final c = Client._(
      await Socket.connect(InternetAddress.loopbackIPv4, port),
    );
    c.send(
      packet(0x10, [
        ..._str('MQTT'),
        4,
        0x02,
        keepAlive >> 8,
        keepAlive & 0xff,
        ..._str(id),
      ]),
    );
    return c;
  }

  void _parse() {
    while (_buf.length >= 2) {
      var len = 0, mult = 1, i = 1;
      while (true) {
        if (i >= _buf.length) return;
        len += (_buf[i] & 0x7f) * mult;
        mult *= 128;
        if (_buf[i] & 0x80 == 0) break;
        i++;
      }
      if (_buf.length < i + 1 + len) return;
      final p = (_buf[0], Uint8List.fromList(_buf.sublist(i + 1, i + 1 + len)));
      _buf.removeRange(0, i + 1 + len);
      got.add(p);
      packets.add(p);
    }
  }

  void send(List<int> bytes) => socket.add(bytes);

  Future<(int, Uint8List)> next(int type) async {
    for (final p in got) {
      if (p.$1 >> 4 == type) {
        got.remove(p);
        return p;
      }
    }
    final p = await packets.stream
        .firstWhere((p) => p.$1 >> 4 == type)
        .timeout(const Duration(seconds: 15));
    got.remove(p);
    return p;
  }

  void subscribe(int id, List<(String, int)> filters) => send(
    packet(0x82, [
      id >> 8,
      id & 0xff,
      for (final f in filters) ...[..._str(f.$1), f.$2],
    ]),
  );

  Future<void> close() async {
    try {
      await socket.close();
    } on SocketException {
      // already closed by the broker
    }
    socket.destroy();
  }
}

/// A PUBLISH's (topic, payload text, qos, retain).
(String, String, int, bool) decodePublish((int, Uint8List) p) {
  final b = p.$2;
  final tlen = b[0] << 8 | b[1];
  final topic = utf8.decode(b.sublist(2, 2 + tlen));
  final qos = (p.$1 >> 1) & 3;
  final start = 2 + tlen + (qos > 0 ? 2 : 0);
  return (topic, utf8.decode(b.sublist(start)), qos, p.$1 & 1 == 1);
}

void main() {
  late MqttBroker broker;

  setUp(() async {
    broker = MqttBroker(port: 0, address: InternetAddress.loopbackIPv4);
    await broker.start();
  });

  tearDown(() => broker.stop());

  test('wildcards', () {
    expect(topicMatches('field/v1/+/score', 'field/v1/42/score'), isTrue);
    expect(
      topicMatches('field/v1/#', 'field/v1/42/events/zone.captured'),
      isTrue,
    );
    expect(topicMatches('field/v1/#', 'field/v1'), isTrue);
    expect(topicMatches('field/v1/+', 'field/v1/42/score'), isFalse);
    expect(topicMatches('field/v1/42/score', 'field/v1/43/score'), isFalse);
  });

  test(
    'connect, subscribe, QoS 0 and 1, retained for late subscribers, ping',
    () async {
      final c = await Client.connect(broker.boundPort);
      expect((await c.next(2)).$2, [0, 0]); // CONNACK accepted
      c.subscribe(1, [('field/v1/+/events/#', 0), ('field/v1/42/score', 1)]);
      expect((await c.next(9)).$2, [0, 1, 0, 1]); // SUBACK: granted 0 and 1
      broker.publish('field/v1/42/events/zone.captured', {'team': 'red'});
      broker.publish('field/v1/42/score', {'red': 5}, qos: 1, retain: true);
      broker.publish('field/v1/42/nodes/2/state', {
        'owner': 'red',
      }); // not subscribed
      final e = decodePublish(await c.next(3));
      expect(e, (
        'field/v1/42/events/zone.captured',
        '{"team":"red"}',
        0,
        false,
      ));
      final s = decodePublish(await c.next(3));
      expect(s, ('field/v1/42/score', '{"red":5}', 1, false));
      c.send(packet(0xc0, const [])); // PINGREQ
      await c.next(13);
      // A scoreboard that connects later gets the retained score at once.
      final late = await Client.connect(broker.boundPort, id: 'late');
      await late.next(2);
      late.subscribe(7, [('field/v1/42/#', 1)]);
      await late.next(9);
      expect(decodePublish(await late.next(3)), (
        'field/v1/42/score',
        '{"red":5}',
        1,
        true,
      ));
      // Unsubscribed: nothing more.
      c.send(packet(0xa2, [0, 2, ..._str('field/v1/+/events/#')]));
      await c.next(11);
      broker.publish('field/v1/42/events/game.end', {});
      c.send(packet(0xc0, const []));
      await c.next(13);
      expect(c.got.where((p) => p.$1 >> 4 == 3), isEmpty);
      await c.close();
      await late.close();
    },
  );

  test(
    'clients cannot publish unless allowed; QoS 2 and junk close them',
    () async {
      final c = await Client.connect(broker.boundPort);
      await c.next(2);
      c.subscribe(1, [('#', 0)]);
      await c.next(9);
      c.send(
        packet(0x32, [
          ..._str('field/v1/42/cmd/all'),
          0,
          9,
          ...utf8.encode('{}'),
        ]),
      ); // QoS 1
      expect((await c.next(4)).$2, [0, 9]); // acknowledged, not forwarded
      c.send(packet(0xc0, const []));
      await c.next(13);
      expect(c.got.where((p) => p.$1 >> 4 == 3), isEmpty);
      c.send(packet(0x34, [..._str('a'), 0, 1])); // QoS 2: not supported
      await c.closed.future.timeout(const Duration(seconds: 15));
      final junk = await Socket.connect(
        InternetAddress.loopbackIPv4,
        broker.boundPort,
      );
      final done = Completer<void>();
      junk.listen((_) {}, onDone: done.complete);
      junk.add([0x82, 0x02, 0, 1]); // SUBSCRIBE before CONNECT
      await done.future.timeout(const Duration(seconds: 15));
      junk.destroy();
    },
  );

  test('a GM integration may publish where allowed', () async {
    await broker.stop();
    broker = MqttBroker(
      port: 0,
      address: InternetAddress.loopbackIPv4,
      allowPublish: (id, topic) =>
          id == 'gm' && topic.startsWith('field/v1/42/cmd/'),
    );
    await broker.start();
    final heard = <(String, String, Uint8List)>[];
    broker.received.listen(heard.add);
    final c = await Client.connect(broker.boundPort, id: 'gm');
    await c.next(2);
    c.send(
      packet(0x30, [
        ..._str('field/v1/42/cmd/all'),
        ...utf8.encode('{"cmd":"message"}'),
      ]),
    );
    c.send(packet(0xc0, const []));
    await c.next(13);
    expect(heard.single.$2, 'field/v1/42/cmd/all');
    await c.close();
  });

  test('at most 20 connections', () async {
    final clients = <Client>[];
    for (var i = 0; i < 20; i++) {
      final c = await Client.connect(broker.boundPort, id: 'c$i');
      await c.next(2);
      clients.add(c);
    }
    expect(broker.clientCount, 20);
    final extra = await Client.connect(broker.boundPort, id: 'extra');
    await extra.closed.future.timeout(const Duration(seconds: 15));
    expect(extra.got, isEmpty);
    for (final c in clients) {
      await c.close();
    }
  });
}
