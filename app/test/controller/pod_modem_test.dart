// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The I/O pod as the phone controller's radio (lib/controller/pod_modem.dart)
// against a scripted pod link, for what the end-to-end tests with the host
// pod (pod_controller_test.dart) do not reach: missed pings, a pod that
// says who it is again (it lost the key) or has no radio, and each RADIO_*
// frame's fields. The time is real: the ping interval is short only in the
// test that is about pings, and what a test waits for it polls with a
// deadline from that interval, not a fixed sleep (a loaded machine runs the
// timers late, never early).
@Timeout(Duration(minutes: 3))
library;

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_radio.dart';
import 'package:atalaia_app/controller/pod_modem.dart';
import 'package:atalaia_app/pod/pod_client.dart';
import 'package:atalaia_app/pod/pod_codec.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

/// A pod link the test plays: what the phone sends, frame by frame.
class ScriptedPod implements PodTransport {
  final _in = StreamController<Uint8List>.broadcast();
  final _dec = FrameDecoder();
  final sent = <Frame>[];

  @override
  String get kind => 'usb';

  @override
  Stream<Uint8List> get incoming => _in.stream;

  @override
  Future<void> send(Uint8List bytes) async => sent.addAll(_dec.feed(bytes));

  @override
  Future<void> close() async => _in.close();

  void frame(int type, List<int> payload) =>
      _in.add(encodeFrame(type, payload));

  void ident({
    bool radio = true,
    bool field = false,
    bool pair = false,
    bool? measure,
  }) => frame(
    FrameType.ident,
    encodeIdent(
      PodIdent(
        fwVersion: 'test',
        capabilities: const [],
        hasRadio: radio,
        fieldFrames: field,
        pairFrames: pair,
        measure: measure,
      ),
    ),
  );

  /// The RADIO_CMD frames sent, as (opcode, rest).
  List<(int, List<int>)> get commands => [
    for (final f in sent)
      if (f.type == FrameType.radioCmd) (f.payload[0], f.payload.sublist(1)),
  ];

  /// Answers the last PING with its STATUS.
  void pong() {
    final ping = commands.lastWhere((c) => c.$1 == RadioOp.ping).$2;
    final token = ping[0] << 24 | ping[1] << 16 | ping[2] << 8 | ping[3];
    frame(
      FrameType.radioStatus,
      utf8.encode(jsonEncode({'cmd': 1, 'ping': token, 'configured': false})),
    );
  }
}

Future<void> settle([int ms = 20]) =>
    Future<void>.delayed(Duration(milliseconds: ms));

/// Room for a machine under load (several Docker suites at once): timers run
/// late, never early, so a wait for a state that a timer brings adds this.
const loadSlack = Duration(seconds: 30);

/// Waits until [ok], polling; on the deadline the failure says what the
/// phone had sent and the states seen.
Future<void> until(
  bool Function() ok,
  String what,
  ScriptedPod link,
  List<String> states, {
  Duration timeout = loadSlack,
}) async {
  final end = DateTime.now().add(timeout);
  while (!ok()) {
    if (DateTime.now().isAfter(end)) {
      throw TimeoutException(
        'no $what after $timeout; states $states; the phone sent '
        '${[for (final c in link.commands.reversed.take(8)) c.$1]} (latest first)',
      );
    }
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
}

void main() {
  late ScriptedPod link;
  late PodModem modem;
  late List<String> states;

  /// The modem on a fresh pod link. Only the test about missed pings wants
  /// a short interval; the others must not see a ping come due between
  /// their steps, however late a loaded machine runs them.
  Future<void> open({Duration ping = const Duration(seconds: 30)}) async {
    link = ScriptedPod();
    modem = PodModem(PodClient(link), pingInterval: ping);
    states = [];
    modem.onState = states.add;
    await modem.start();
  }

  setUp(open);

  tearDown(() async => modem.close());

  test('up after the IDENT and a PING answered; down after 3 missed', () async {
    // Replaces the modem of setUp: 200 ms pings, so 3 missed take 600 ms,
    // and the wait for DOWN is that plus slack.
    await modem.close();
    const ping = Duration(milliseconds: 200);
    await open(ping: ping);
    expect(modem.state, ModemState.connecting);
    expect(link.commands.first.$1, RadioOp.ident);
    link.ident();
    await settle();
    expect(link.commands.last.$1, RadioOp.ping);
    link.pong();
    await until(() => modem.state == ModemState.up, 'UP', link, states);
    expect(modem.ident, containsPair('has_radio', true));
    // Nobody answers now: down after three missed pings (the 4th tick sees
    // the 3rd unanswered), up again on a reply.
    await until(
      () => modem.state == ModemState.down,
      'DOWN',
      link,
      states,
      timeout: ping * 4 + loadSlack,
    );
    link.pong();
    await until(() => modem.state == ModemState.up, 'UP again', link, states);
    expect(states, [ModemState.up, ModemState.down, ModemState.up]);
  });

  test('the game and the peers again when the pod says who it is', () async {
    link.ident();
    await settle();
    link.pong();
    await settle();
    final key = Uint8List.fromList(List.generate(16, (i) => i));
    modem
      ..configure(
        gameId: 0x1234,
        nodeId: 0,
        epoch: 3,
        maxHops: 2,
        channelHz: 869525000,
        key: key,
      )
      ..setPeerEpochs({4: 1, 9: 2});
    await settle();
    final configure = link.commands.lastWhere((c) => c.$1 == RadioOp.configure);
    expect(configure.$2.sublist(0, 6), [0x12, 0x34, 0, 0, 0, 3]);
    expect(configure.$2.sublist(11), key);
    expect(link.commands.lastWhere((c) => c.$1 == RadioOp.setPeerEpoch).$2, [
      0,
      4,
      0,
      1,
      0,
      9,
      0,
      2,
    ]);
    // The pod restarted (it forgot the key): everything again.
    final before = link.commands.length;
    link.ident();
    await settle();
    final again = [
      for (final c in link.commands.sublist(before))
        if (c.$1 != RadioOp.ping) c.$1,
    ];
    expect(again, [RadioOp.configure, RadioOp.setPeerEpoch]);
    expect(modem.reconnects, 1);
    final mark = link.commands.length;
    modem.clear();
    await settle();
    expect(
      link.commands.sublist(mark).map((c) => c.$1),
      contains(RadioOp.clear),
    );
  });

  test('a pod without a radio is never up', () async {
    link.ident(radio: false);
    await settle();
    expect(modem.state, ModemState.down);
    expect(
      modem.sendPacket(
        RfHeader.v1(gameId: 1, source: 0, seq: 0, hopLimit: 2, type: 6),
        Uint8List(1),
      ),
      isFalse,
    );
  });

  test('RADIO_RX, RADIO_TX_ACK, RADIO_ERROR and TX', () async {
    link.ident();
    await settle();
    link.pong();
    await settle();
    final rx = <RadioRx>[];
    final acks = <(int, String)>[];
    final errors = <(String, String)>[];
    modem
      ..onRx = rx.add
      ..onTxAck = ((s, st) => acks.add((s, st)))
      ..onError = ((c, m) => errors.add((c, m)));
    final h = RfHeader.v1(
      gameId: 7,
      source: 4,
      seq: 300,
      hopLimit: 2,
      type: RfType.state,
    );
    link
      ..frame(FrameType.radioRx, radioRx(h.encode(), [0xa1, 0x01], -70, -3, 2))
      ..frame(FrameType.radioTxAck, radioTxAck(12, 1))
      ..frame(FrameType.radioError, radioError(5, 'radio busy'));
    await settle();
    expect(rx.single.header.source, 4);
    expect(rx.single.header.seq, 300);
    expect(rx.single.payload, [0xa1, 0x01]);
    expect([rx.single.rssi, rx.single.snr, rx.single.epoch], [-70, -3, 2]);
    expect(acks, [(12, 'duty_cycle')]);
    expect(errors, [('radio', 'radio busy')]);
    expect(modem.sendPacket(h, Uint8List.fromList([1, 2, 3])), isTrue);
    await settle();
    final tx = link.sent.lastWhere((f) => f.type == FrameType.radioTx);
    expect(tx.payload, [...h.encode(), 1, 2, 3]);
  });

  // Slice S7c, decision PE24-91: the field and pair frames a pod would
  // relay as RADIO_FIELD_TX, RADIO_FIELD_RX and RADIO_FIELD_ACK (the
  // modem's FIELD_* plus 3), only when its IDENT says so; today's pod
  // firmware does not, and then nothing goes.
  test(
    'field frames only with a pod whose IDENT says it relays them',
    () async {
      link.ident();
      await settle();
      link.pong();
      await settle();
      expect(modem.isUp, isTrue);
      expect([modem.hasFieldFrames, modem.hasPairFrames], [false, false]);
      expect(modem.sendField(Uint8List(40)), isNull);
      expect(link.sent.where((f) => f.type == FrameType.radioFieldTx), isEmpty);

      link.ident(field: true, pair: true);
      await settle();
      link.pong();
      await settle();
      expect([modem.hasFieldFrames, modem.hasPairFrames], [true, true]);
      expect(modem.ident, containsPair('field', true));
      final heard = <(List<int>, int, int)>[];
      final acks = <(int, String)>[];
      modem
        ..onFieldRx = ((f, rssi, snr) => heard.add((f, rssi, snr)))
        ..onFieldAck = ((id, st) => acks.add((id, st)));
      final frame = Uint8List.fromList(List.generate(40, (i) => i));
      expect(modem.sendField(frame), 1);
      expect(modem.sendField(frame), 2);
      await settle();
      final tx = link.sent
          .where((f) => f.type == FrameType.radioFieldTx)
          .toList();
      expect(tx.first.payload, [0, 1, ...frame]);
      expect(tx.last.payload.sublist(0, 2), [0, 2]);
      link
        ..frame(FrameType.radioFieldRx, [...frame, 0xc0, 0xfb])
        ..frame(FrameType.radioFieldAck, [0, 2, 1]);
      await settle();
      expect(heard.single.$1, frame);
      expect([heard.single.$2, heard.single.$3], [-64, -5]);
      expect(acks, [(2, 'duty_cycle')]);
    },
  );
}
