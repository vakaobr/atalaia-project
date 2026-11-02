// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// A controller names a box's epoch to the other receivers (RFC 0001
// Amendment 24, decision SR-110): the same rule and repeats as the Pi's
// (simulator/atalaia_sim/peer_epoch.py), from protocol/vectors/peer_epoch.json,
// and the phone controller's use of it (CMD peer, opcode 11, from cmd.json).

import 'dart:typed_data';

import 'package:atalaia_app/controller/field_controller.dart';
import 'package:atalaia_app/controller/peer_epoch.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';
import '../support/vectors.dart';

RfHeader header(int source, int seq, int type) =>
    RfHeader.v1(gameId: 9, source: source, seq: seq, hopLimit: 2, type: type);

void main() {
  final v = loadVectors('peer_epoch.json');

  test('the constants are the ones in the vectors', () {
    expect(peerEpochWindow, v['window']);
    expect(peerEpochRepeatAfterMs, v['repeat_after_ms']);
    expect(cmdPeerEpoch, 11);
  });

  for (final c in cases(v, 'rule')) {
    test('rule: ${c['name']}', () {
      expect(
        shouldAnnouncePeerEpoch(
          c['prior'] as int,
          c['heard'] as int,
          isHello: c['type'] == 'HELLO',
        ),
        c['announce'],
      );
    });
  }

  for (final c in cases(v, 'sequences')) {
    test('sequence: ${c['name']}', () {
      final t = PeerEpochs();
      var n = 0;
      for (final step
          in (c['steps'] as List<dynamic>).cast<Map<String, dynamic>>()) {
        if (step.containsKey('heard')) {
          final a = step['heard'] as List<dynamic>;
          expect(
            t.heard(
              a[0] as int,
              a[1] as int,
              a[2] as int,
              a[3] == 'HELLO',
              a[4] as int,
            ),
            step['announce'],
            reason: 'step $n',
          );
        } else {
          final now = (step['due'] as List<dynamic>)[0] as int;
          expect(
            [
              for (final (s, e) in t.due(now)) [s, e],
            ],
            step['sends'],
            reason: 'step $n',
          );
        }
        n++;
      }
    });
  }

  group('the phone controller', () {
    late RecordingRadio radio;
    late FieldController fc;
    late List<(int, int)> told;

    setUp(() {
      radio = RecordingRadio();
      told = [];
      fc = FieldController(
        transport: radio,
        gameId: 9,
        teams: const ['red', 'blue'],
        decodeEvent: (payload) => throw StateError('no events here'),
        wallSeconds: () => 1000,
      )..registerNode(4, 'node-4', 'zone');
      fc.onPeerEpoch = (node, epoch) => told.add((node, epoch));
    });

    List<RfCmd> peerCmds() => [
      for (final (t, p) in radio.sent)
        if (t == RfType.cmd && RfCmd.decode(p).cmd == cmdPeerEpoch)
          RfCmd.decode(p),
    ];

    void hear(int source, int seq, int type, int epoch) => fc.onPacket(
      header(source, seq, type),
      Uint8List.fromList([0xa0]),
      epoch: epoch,
    );

    test('a box that lost its store is named to the modem and the boxes', () {
      hear(4, 0, RfType.hello, 1);
      hear(4, 1, RfType.state, 2);
      expect(peerCmds(), isEmpty);
      hear(4, 0, RfType.hello, 41000);
      expect(told, [(4, 41000)]);
      expect(peerCmds().single.params, {'src': 4, 'epoch': 41000});
      expect(peerCmds().single.dest, isNull);
      hear(4, 1, RfType.hello, 41000); // its retry: once is enough
      expect(peerCmds(), hasLength(1));
      fc
        ..tick(1000 + peerEpochRepeatAfterMs[0] + 1)
        ..tick(peerEpochRepeatAfterMs[1] + 1)
        ..tick(60000);
      expect(peerCmds(), hasLength(3));
      expect(told, hasLength(1));
    });

    test('an ordinary box, a new box and a Wi-Fi prop are not announced', () {
      for (var seq = 0; seq < 5; seq++) {
        hear(4, seq, RfType.state, 1);
      }
      hear(4, 0, RfType.state, 2);
      hear(5, 0, RfType.hello, 1);
      hear(6, 0, RfType.hello, 0);
      expect(peerCmds(), isEmpty);
      expect(told, isEmpty);
    });

    test('a restarted box says hello one epoch up', () {
      hear(4, 0, RfType.hello, 3);
      hear(4, 0, RfType.hello, 4);
      expect(peerCmds().single.params, {'src': 4, 'epoch': 4});
    });

    test('an old recording cannot move an epoch back', () {
      hear(4, 0, RfType.hello, 41000);
      hear(4, 0, RfType.hello, 7);
      hear(4, 9, RfType.state, 40900);
      expect(peerCmds(), hasLength(1));
      expect(told, [(4, 41000)]);
    });

    test('a standby tells its modem and sends nothing', () {
      fc.election.follow(0);
      hear(4, 0, RfType.hello, 41000);
      expect(told, [(4, 41000)]);
      expect(peerCmds(), isEmpty);
      fc.tick(60000);
      expect(peerCmds(), isEmpty);
    });
  });
}
