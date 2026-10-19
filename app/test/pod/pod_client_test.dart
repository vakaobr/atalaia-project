// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The pod client (lib/pod/pod_client.dart) against a pod simulated here:
// IDENT on the first RADIO_CMD IDENT, events acknowledged and acted on once,
// commands retried and the link given up after 3 retries, and the mapping
// from a pod's events and commands to a mode's inputs and hardware.

import 'dart:async';
import 'dart:typed_data';

import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/security/bytes.dart';
import 'package:atalaia_app/security/nfc_tag_signer.dart';
import 'package:flutter_test/flutter_test.dart';

class FakeLink implements PodTransport {
  final _in = StreamController<Uint8List>.broadcast();
  final sent = <Frame>[];
  final _decoder = FrameDecoder();
  void Function(Frame f)? onFrame;

  @override
  String get kind => 'usb';

  @override
  Stream<Uint8List> get incoming => _in.stream;

  @override
  Future<void> send(Uint8List bytes) async {
    for (final f in _decoder.feed(bytes)) {
      sent.add(f);
      onFrame?.call(f);
    }
  }

  /// The pod sends [bytes], split in two to show reassembly.
  void podSends(Uint8List bytes) {
    final half = bytes.length ~/ 2;
    _in
      ..add(Uint8List.sublistView(bytes, 0, half))
      ..add(Uint8List.sublistView(bytes, half));
  }

  @override
  Future<void> close() => _in.close();
}

const ident = PodIdent(
  fwVersion: '0.3.0',
  capabilities: [
    {'id': 'btn.red', 'type': 'button', 'team': 'red'},
    {'id': 'btn.blue', 'type': 'button', 'team': 'blue'},
    {'id': 'ring', 'type': 'led', 'count': 24, 'rgb': true},
    {'id': 'nfc', 'type': 'nfc'},
    {'id': 'keys', 'type': 'keypad'},
  ],
  batteryPct: 80,
  hasRadio: true,
);

Uint8List evt(String cap, String name, int seq, [Map<String, Object?>? d]) =>
    encodeFrame(
      FrameType.evt,
      encodeMessage(
        ProxyMessage(capId: cap, name: name, data: d ?? const {}, seq: seq),
      ),
    );

void expectInput(
  (String, Map<String, Object?>)? got,
  (String, Map<String, Object?>) want,
) {
  expect(got, isNotNull);
  expect(got!.$1, want.$1);
  expect(got.$2, want.$2);
}

Future<void> settle() => Future<void>.delayed(const Duration(milliseconds: 5));

void main() {
  test('the phone asks for IDENT first; the pod answers', () async {
    final link = FakeLink();
    link.onFrame = (f) {
      if (f.type == FrameType.radioCmd && f.payload.single == RadioOp.ident) {
        link.podSends(encodeFrame(FrameType.ident, encodeIdent(ident)));
      }
    };
    final client = PodClient(link);
    final events = <PodEvent>[];
    client.events.listen(events.add);
    await client.start();
    await settle();
    expect(link.sent.first.type, FrameType.radioCmd);
    expect(events.single, isA<PodIdentified>());
    expect(client.ident!.capabilities.length, 5);
    expect(client.ident!.batteryPct, 80);
    await client.close();
  });

  test('events are acknowledged every time and acted on once', () async {
    final link = FakeLink();
    final client = PodClient(link);
    final got = <ProxyMessage>[];
    client.events.listen((e) {
      if (e is PodCapabilityEvent) got.add(e.message);
    });
    await client.start();
    link
      ..podSends(evt('btn.red', 'hold', 7, {'ms': 5000}))
      ..podSends(evt('btn.red', 'hold', 7, {'ms': 5000})) // a retry
      ..podSends(evt('btn.blue', 'press', 8));
    await settle();
    expect(got.map((m) => '${m.capId}.${m.name}#${m.seq}'), [
      'btn.red.hold#7',
      'btn.blue.press#8',
    ]);
    final acks = link.sent.where((f) => f.type == FrameType.ack).toList();
    expect(acks.map((f) => decodeAck(f.payload)), [7, 7, 8]);
    // A payload that does not decode is dropped and not acknowledged.
    link.podSends(encodeFrame(FrameType.evt, hexDecode('a2016762746e')));
    await settle();
    expect(link.sent.where((f) => f.type == FrameType.ack).length, 3);
    await client.close();
  });

  test('a command is done when the pod acknowledges it', () async {
    final link = FakeLink();
    link.onFrame = (f) {
      if (f.type == FrameType.cmd) {
        final m = decodeMessage(f.payload);
        link.podSends(encodeFrame(FrameType.ack, encodeAck(m.seq)));
      }
    };
    final client = PodClient(link);
    await client.start();
    expect(await client.command('ring', 'fill', {'team': 'red'}), isTrue);
    expect(await client.command('ring', 'fill', {'team': 'blue'}), isTrue);
    final cmds = link.sent.where((f) => f.type == FrameType.cmd).toList();
    expect(cmds.map((f) => decodeMessage(f.payload).seq), [0, 1]);
    expect(decodeMessage(cmds.last.payload).data, {'team': 'blue'});
    await client.close();
  });

  test(
    'an unacknowledged command is sent 4 times, then the link is broken',
    () async {
      final link = FakeLink();
      final client = PodClient(
        link,
        retryAfter: const Duration(milliseconds: 20),
      );
      final events = <PodEvent>[];
      client.events.listen(events.add);
      await client.start();
      expect(await client.command('ring', 'fill', {'team': 'red'}), isFalse);
      expect(link.sent.where((f) => f.type == FrameType.cmd).length, 4);
      expect(events.whereType<PodLinkBroken>(), hasLength(1));
      expect(client.broken, isTrue);
      expect(await client.command('ring', 'fill'), isFalse);
      await client.close();
    },
  );

  test(
    'radio frames pass through untouched; unknown types are ignored',
    () async {
      final link = FakeLink();
      final client = PodClient(link);
      final events = <PodEvent>[];
      client.events.listen(events.add);
      await client.start();
      link
        ..podSends(encodeFrame(FrameType.radioTxAck, radioTxAck(513, 1)))
        ..podSends(encodeFrame(0x42, [1, 2, 3]))
        ..podSends(encodeFrame(FrameType.radioError, radioError(4, 'x')));
      await settle();
      final radio = events.whereType<PodRadioFrame>().toList();
      expect(radio.map((r) => r.type), [
        FrameType.radioTxAck,
        FrameType.radioError,
      ]);
      await client.sendRadio(
        FrameType.radioTx,
        radioTx(List.filled(9, 0), [1]),
      );
      expect(link.sent.last.type, FrameType.radioTx);
      await client.close();
    },
  );

  group('a pod as a mode sees it', () {
    final inputs = PodInputs(ident);
    final key = List<int>.generate(16, (i) => i);
    Map<String, Object?> tagData(List<int> uid, List<int>? tag) => podTagData(
      uid,
      tag,
      gameId: 4242,
      gameKey: key,
      teams: const ['red', 'blue'],
    );

    test('buttons are team inputs', () {
      ProxyMessage m(String n, [Map<String, Object?> d = const {}]) =>
          ProxyMessage(capId: 'btn.blue', name: n, data: d, seq: 1);
      expectInput(inputs.input(m('press'), tagData: tagData), (
        'team_input.press',
        {'team': 'blue'},
      ));
      expectInput(inputs.input(m('hold', {'ms': 250}), tagData: tagData), (
        'team_input.hold',
        {'team': 'blue', 'ms': 250},
      ));
      expectInput(inputs.input(m('release', {'ms': 900}), tagData: tagData), (
        'team_input.release',
        {'team': 'blue', 'ms': 900},
      ));
    });

    test('a card read is nfc.tag, checked with the game key', () {
      final tag = encodeTag(
        const PlayerTag(player: 'p-17', team: 2, gameId: 4242),
        key,
      );
      final r = inputs.input(
        ProxyMessage(
          capId: 'nfc',
          name: 'tag',
          data: {'uid': '04a1b2c3d4e5f6', 'tag': hexEncode(tag)},
          seq: 3,
        ),
        tagData: tagData,
      )!;
      expect(r.$1, 'nfc.tag');
      expect(r.$2, {
        'uid': '04a1b2c3d4e5f6',
        'valid': true,
        'player': 'p-17',
        'team': 'blue',
      });
      final unsigned = inputs.input(
        const ProxyMessage(
          capId: 'nfc',
          name: 'tag',
          data: {'uid': '04a1'},
          seq: 4,
        ),
        tagData: tagData,
      )!;
      expect(unsigned.$2['reason'], 'unsigned');
    });

    test('keypad keys; unknown capabilities map to nothing', () {
      expectInput(
        inputs.input(
          const ProxyMessage(
            capId: 'keys',
            name: 'key',
            data: {'key': '7'},
            seq: 1,
          ),
          tagData: tagData,
        ),
        ('keypad.key', {'key': '7'}),
      );
      expect(
        inputs.input(
          const ProxyMessage(capId: 'imu', name: 'shock', seq: 1),
          tagData: tagData,
        ),
        isNull,
      );
    });

    test('a hit sensor lent by a target addon: hit.hit, and arm', () {
      final target = PodInputs(
        const PodIdent(
          fwVersion: '0.4.0',
          capabilities: [
            {'id': 'hit', 'type': 'hit'},
            {'id': 'ring', 'type': 'led', 'count': 24, 'rgb': true},
          ],
          hasRadio: false,
        ),
      );
      expectInput(
        target.input(
          const ProxyMessage(
            capId: 'hit',
            name: 'hit',
            data: {'strength': 200},
            seq: 12,
          ),
          tagData: tagData,
        ),
        ('hit.hit', {'strength': 200}),
      );
      expectInput(
        target.input(
          const ProxyMessage(capId: 'hit', name: 'hit', seq: 13),
          tagData: tagData,
        ),
        ('hit.hit', {'strength': 0}),
      );
      final arm = target.command('hit', 'arm', const [])!;
      expect([arm.$1, arm.$2, arm.$3], ['hit', 'arm', <String, Object?>{}]);
    });

    test("a script's commands for the pod's hardware", () {
      final fill = inputs.command('ring', 'fill', ['red'])!;
      expect(
        [fill.$1, fill.$2, fill.$3],
        [
          'ring',
          'fill',
          {'team': 'red'},
        ],
      );
      final b = inputs.command('ring', 'set_brightness', [50])!;
      expect(b.$3, {
        'args': [50],
      });
      expect(inputs.command('ui', 'screen', ['x']), isNull);
    });
  });
}
