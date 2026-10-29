// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The radio side of a game on the Android field controller
// (lib/controller/field_controller.dart), as the simulator's tests check
// its FieldController: the packets it sends, scores merged by maximum, flood
// copies and replays dropped, ACKs, TIME beacons and node health.

import 'dart:typed_data';

import 'package:atalaia_app/controller/field_controller.dart';
import 'package:atalaia_app/core/node_types.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

import '../support/recording_radio.dart';

RfHeader header(int source, int seq, int type, {bool ack = false}) =>
    RfHeader.v1(
      gameId: 9,
      source: source,
      seq: seq,
      hopLimit: 2,
      type: type,
      ack: ack,
    );

Uint8List state(
  int owner,
  Map<int, int> counters, {
  int? battery,
  Map<int, int> lost = const {},
  int gameTimeMs = 0,
}) => RfState(
  ownerTeam: owner,
  phase: 1,
  gameTimeMs: gameTimeMs,
  counters: counters,
  lost: lost,
  batteryPct: battery,
  epoch: 1,
).encode();

void main() {
  late RecordingRadio radio;
  late FieldController fc;
  late List<Map<String, Object?>> events;
  late List<Map<String, int>> totals;

  setUp(() {
    radio = RecordingRadio();
    events = [];
    totals = [];
    fc = FieldController(
      transport: radio,
      gameId: 9,
      teams: const ['red', 'blue'],
      decodeEvent: (payload) => EmittedEvent(
        node: payload[0],
        seq: payload[1],
        tMs: payload[2],
        team: payload[3],
        squad: 0,
        prio: 1,
        type: 'zone.captured',
        dataJson: '{}',
      ),
      wallSeconds: () => 1000,
    )..registerNode(4, 'node-4', 'zone');
    fc
      ..onEvent = events.add
      ..onScores = totals.add;
  });

  List<RfCmd> cmds() => [
    for (final (t, p) in radio.sent)
      if (t == RfType.cmd) RfCmd.decode(p),
  ];

  List<RfTime> beacons() => [
    for (final (t, p) in radio.sent)
      if (t == RfType.time) RfTime.decode(p),
  ];

  test('start, pause, resume and end: a CMD and a TIME beacon each', () {
    fc.startGame(durationMs: 60000, nowMs: 1000);
    fc.pauseGame(nowMs: 3000, reason: 'medic');
    expect(fc.gameTimeMs, 2000);
    fc.resumeGame(nowMs: 10000);
    fc.tick(11000);
    expect(fc.gameTimeMs, 3000);
    fc.endGame(nowMs: 12000);
    expect(cmds().map((c) => c.name), ['start', 'pause', 'resume', 'end']);
    expect(cmds()[1].params, {'reason': 'medic'});
    expect(cmds().every((c) => c.dest == null), isTrue);
    expect(beacons().map((b) => b.stateName), [
      'running',
      'paused',
      'running',
      'ended',
    ]);
    expect(beacons().last.gameTimeMs, 4000);
    expect(beacons().first.durationMs, 60000);
    expect(beacons().first.wallS, 1000);
  });

  test('TIME every 30 s while the game runs', () {
    fc.startGame(nowMs: 0);
    fc.tick(29999);
    expect(beacons(), hasLength(1));
    fc.tick(30000);
    expect(beacons(), hasLength(2));
  });

  test('a command to one node, and parameters too big for a CMD', () {
    expect(fc.sendCmd('set_owner', {'team': 'red'}, dest: 4), 0);
    expect(cmds().single.dest, 4);
    expect(
      () => fc.sendCmd('message', {'text': 'x' * 130}),
      throwsA(isA<FieldControllerException>()),
    );
    expect(
      () => fc.sendCmd('update', null),
      throwsA(isA<FieldControllerException>()),
    );
  });

  test('penalties (STATE key 9): the highest per node, subtracted (BSC-1)', () {
    fc.onPacket(header(4, 0, RfType.state), state(1, {1: 10, 2: 8}), epoch: 1);
    expect(fc.totalScores, {'red': 10, 'blue': 8});
    fc.onPacket(
      header(4, 1, RfType.state),
      state(1, {1: 10, 2: 8}, lost: {2: 3}),
      epoch: 1,
    );
    expect(fc.totalScores, {'red': 10, 'blue': 5});
    expect(totals.last, {'red': 10, 'blue': 5});
    // Less, or nothing (an older box): merged by maximum, so no change.
    fc.onPacket(
      header(4, 2, RfType.state),
      state(1, {1: 10, 2: 8}, lost: {2: 1}),
      epoch: 1,
    );
    fc.onPacket(header(4, 3, RfType.state), state(1, {1: 10, 2: 8}), epoch: 1);
    expect(fc.totalScores, {'red': 10, 'blue': 5});
    expect(fc.lostOf('blue', 'node-4'), 3);
    // Another box's penalties add, and the GM's adjustment applies on top.
    fc.onPacket(
      header(5, 0, RfType.state),
      state(2, {2: 4}, lost: {2: 2}),
      epoch: 1,
    );
    fc.adjustScore('blue', -1, 'gm');
    expect(fc.totalScores, {'red': 10, 'blue': 5 + 4 - 2 - 1});
  });

  test('projected score: ticks since the last STATE, replaced by the next '
      '(BSC-2)', () {
    fc.scoringHold = (10000, 2);
    final drifts = <Map<String, Object?>>[];
    fc.onDrift = drifts.add;
    expect(fc.projectedScores(), {'red': 0, 'blue': 0});
    fc.startGame(nowMs: 0);
    fc.onPacket(header(4, 1, RfType.state), state(1, {}), epoch: 1);
    fc.tick(25000);
    expect(fc.projectedScores(), {'red': 4, 'blue': 0});
    expect(fc.totalScores, {'red': 0, 'blue': 0}); // reports only
    fc.onPacket(
      header(4, 2, RfType.state),
      state(1, {1: 4}, gameTimeMs: 20000),
      epoch: 1,
    );
    expect(fc.projectedScores(), {'red': 4, 'blue': 0});
    expect(drifts.single['drift'], 0);
    fc.tick(35000);
    expect(fc.projectedScores(), {'red': 6, 'blue': 0});
    // A box that missed a tick: the drift is measured, nothing accumulates.
    fc.onPacket(
      header(4, 3, RfType.state),
      state(1, {1: 4}, gameTimeMs: 35000),
      epoch: 1,
    );
    expect(fc.projectedScores(), {'red': 4, 'blue': 0});
    expect(drifts.last['drift'], 2);
    expect(fc.projectionStats['samples'], 2);
    expect(fc.projectionStats['max_abs'], 2);
    // An offline box and a paused game project nothing.
    fc.tick(45000);
    expect(fc.projectedScores()!['red'], 6);
    fc.nodes[4]!.link = 'offline';
    expect(fc.projectedScores()!['red'], 4);
    fc.nodes[4]!.link = 'online';
    fc.pauseGame(nowMs: 45000);
    fc.tick(65000);
    expect(fc.projectedScores()!['red'], 4); // paused: no ticks counted
    // A mode that does not opt in has no projection at all.
    fc.scoringHold = null;
    expect(fc.projectedScores(), isNull);
  });

  group('projected score follows a capture until the next STATE (BSC-4)', () {
    // 2 points every 10 s; an event is [node, seq, t in s, team, 0 captured | 1
    // neutralized].
    late FieldController pc;
    late List<Map<String, Object?>> drifts;

    setUp(() {
      drifts = [];
      pc = FieldController(
        transport: radio,
        gameId: 9,
        teams: const ['red', 'blue'],
        decodeEvent: (p) => EmittedEvent(
          node: p[0],
          seq: p[1],
          tMs: p[2] * 1000,
          team: p[3],
          squad: 0,
          prio: 1,
          type: p[4] == 0 ? 'zone.captured' : 'zone.neutralized',
          dataJson: '{"previous_team":"red"}',
        ),
        wallSeconds: () => 1000,
      )..registerNode(4, 'node-4', 'zone');
      pc
        ..scoringHold = (10000, 2)
        ..onDrift = drifts.add
        ..startGame(nowMs: 0);
    });

    void st(int seq, int owner, Map<int, int> counters, int gameMs) =>
        pc.onPacket(
          header(4, seq, RfType.state),
          state(owner, counters, gameTimeMs: gameMs),
          epoch: 1,
        );
    void captured(int seq, int team, int tSec, {bool neutral = false}) =>
        pc.onPacket(
          header(4, 100 + seq, RfType.event),
          Uint8List.fromList([4, seq, tSec, team, neutral ? 1 : 0]),
          epoch: 1,
        );

    test('a capture, then a lost STATE: the new owner scores from it', () {
      st(0, 1, {1: 4}, 20000);
      pc.tick(33000);
      expect(pc.projectedScores(), {'red': 4 + 2, 'blue': 0});
      captured(1, 2, 33);
      expect(pc.projectedScores(), {'red': 4 + 2, 'blue': 0});
      pc.tick(60000);
      // Red kept the tick of 30 s; from 33 s the ticks are blue's.
      expect(pc.projectedScores(), {'red': 4 + 2, 'blue': 6});
      expect(pc.totalScores, {'red': 4, 'blue': 0}); // reports only
      st(1, 2, {1: 6, 2: 6}, 60000);
      expect(pc.projectedScores(), {'red': 6, 'blue': 6});
      expect(pc.nodes[4]!.changes, isEmpty);
      expect(drifts.last['team'], 'red');
      expect(drifts.last['drift'], 0);
    });

    test('a capture, then its STATE: nothing of the event is left', () {
      st(0, 1, {1: 2}, 10000);
      pc.tick(24000);
      captured(1, 2, 22);
      expect(pc.projectedScores(), {'red': 2 + 2, 'blue': 0});
      st(1, 2, {1: 4, 2: 0}, 24000);
      expect(pc.projectedScores(), {'red': 4, 'blue': 0});
      pc.tick(30000);
      expect(pc.projectedScores(), {'red': 4, 'blue': 2});
      captured(2, 2, 22); // reordered: not newer than the STATE
      expect(pc.nodes[4]!.changes, isEmpty);
      expect(pc.projectedScores(), {'red': 4, 'blue': 2});
    });

    test('two captures and a neutralization between STATEs', () {
      st(0, 1, {}, 0);
      pc.tick(50000);
      captured(1, 2, 12);
      captured(2, 1, 31);
      captured(3, 0, 41, neutral: true);
      // red 0-12 s (10 s), blue 12-31 s (20 s, 30 s), red 31-41 s (40 s).
      expect(pc.projectedScores(), {'red': 4, 'blue': 4});
    });

    test('a capture during a pause counts after the resume', () {
      st(0, 1, {}, 0);
      pc.tick(14000);
      pc.pauseGame(nowMs: 14000);
      captured(1, 2, 13);
      expect(pc.projectedScores(), {'red': 0, 'blue': 0});
      pc.tick(40000);
      expect(pc.projectedScores(), {'red': 0, 'blue': 0});
      pc.resumeGame(nowMs: 40000);
      pc.tick(56000);
      expect(pc.gameTimeMs, 30000);
      expect(pc.projectedScores(), {'red': 2, 'blue': 4});
    });

    test('events that say nothing new are ignored', () {
      captured(1, 2, 5); // the box never reported
      expect(pc.nodes[4]!.changes, isEmpty);
      st(0, 1, {}, 8000);
      pc.tick(12000);
      captured(2, 2, 8); // not after the STATE
      captured(3, 9, 11); // a team the game does not have
      expect(pc.nodes[4]!.changes, isEmpty);
      captured(4, 2, 99); // in the controller's future: counts from now
      expect(pc.nodes[4]!.changes, [(12000, 2)]);
    });
  });

  test('scores: the highest value per node, summed, plus adjustments', () {
    fc.onPacket(header(4, 0, RfType.state), state(1, {1: 5}), epoch: 1);
    fc.onPacket(header(4, 1, RfType.state), state(1, {1: 3}), epoch: 1);
    fc.onPacket(header(5, 0, RfType.state), state(2, {1: 2, 2: 4}), epoch: 1);
    fc.mergeCounters('field-1', {'blue': 1});
    fc.adjustScore('red', -1, 'penalty');
    expect(fc.totalScores, {'red': 6, 'blue': 5});
    expect(fc.counter('red', 'node-4'), 5);
    expect(fc.nodes[4]!.ownerName(fc.teams), 'red');
    expect(fc.nodes[5]!.role, 'unknown');
    expect(events.last['type'], 'score.delta');
    expect(events.last['data'], {
      'team': 'red',
      'amount': -1,
      'reason': 'penalty',
    });
    expect(totals.last, {'red': 6, 'blue': 5});
  });

  test('flood copies and replayed events are dropped', () {
    final ev = Uint8List.fromList([4, 1, 50, 1]);
    fc.onPacket(header(4, 7, RfType.event), ev, epoch: 1);
    fc.onPacket(header(4, 7, RfType.event), ev, epoch: 1); // flood copy
    fc.onPacket(header(4, 8, RfType.event), ev, epoch: 1); // replay
    fc.onPacket(
      header(4, 7, RfType.event),
      ev,
      epoch: 2,
    ); // new epoch, same event
    expect(events.where((e) => e['type'] == 'zone.captured'), hasLength(1));
    final e = events.firstWhere((e) => e['type'] == 'zone.captured');
    expect(e['team'], 'red');
    expect(e['pkt_seq'], 7);
    expect(e['epoch'], 1);
  });

  test('an ACK when the packet asks for one, with the bitmap', () {
    fc.onPacket(header(4, 0, RfType.state, ack: true), state(0, {}));
    fc.onPacket(header(4, 2, RfType.state, ack: true), state(0, {}));
    final acks = [
      for (final (t, p) in radio.sent)
        if (t == RfType.ack) RfAck.decode(p),
    ];
    expect(acks, hasLength(2));
    expect(acks.last.node, 4);
    expect(acks.last.seq, 0);
    expect(acks.last.bitmap, [2]); // bit 1: seq 2 = contiguous + 1 + 1
    expect(acks.last.covers(2), isTrue);
    expect(acks.last.covers(1), isFalse);
  });

  test('node.online when heard, node.offline after the silence', () {
    fc
      ..nodeOfflineMs = 120000
      ..linkGapMsSetting = 60000
      ..startGame(nowMs: 0)
      ..tick(1000);
    fc.onPacket(
      header(4, 0, RfType.hello),
      const RfHello(
        nodeName: 'box',
        platform: 1,
        fwVersion: '1.2.3',
        coreVersion: '0.2.0',
        tier: 1,
        capabilities: [1],
        transports: 1,
        epoch: 1,
      ).encode(),
      epoch: 1,
    );
    expect(events.last['type'], 'node.online');
    expect(events.last['data'], {'fw': '1.2.3', 'tier': 'reduced'});
    expect(events.last['origin'], 'controller');
    fc.tick(120999);
    expect(events.last['type'], 'node.online');
    fc.tick(121000);
    expect(events.last['type'], 'node.offline');
    expect(events.last['data'], {'last_seen': 1000});
    expect(events.last['seq'], 2);
  });

  test('battery.low after the grace period, once per crossing', () {
    fc
      ..batteryLowPct = 20
      ..startGame(nowMs: 0);
    fc.onPacket(header(4, 0, RfType.state), state(0, {}, battery: 15));
    fc.tick(29999);
    expect(events.where((e) => e['type'] == 'battery.low'), isEmpty);
    fc.tick(30000);
    fc.tick(90000);
    final low = events.where((e) => e['type'] == 'battery.low').toList();
    expect(low, hasLength(1));
    expect(low.single['data'], {'percent': 15});
  });

  test('a higher term from another controller: this one steps down and '
      'mirrors its clock (slice S7)', () {
    final roles = <(String, int)>[];
    fc.onRole = (role, term) => roles.add((role, term));
    fc.startGame(nowMs: 0);
    fc.onPacket(
      header(2, 0, RfType.time),
      const RfTime(
        gameTimeMs: 5,
        gameState: 2,
        durationMs: 9000,
        wallS: 0,
        term: 9,
      ).encode(),
    );
    expect(fc.term, 9);
    expect(fc.isController, isFalse);
    expect(fc.election.leader, 2);
    expect((fc.gameState, fc.gameTimeMs, fc.durationMs), (gamePaused, 5, 9000));
    expect(roles, [('follower', 9)]);
    expect(fc.nodes.containsKey(2), isFalse);
    expect(
      () => fc.pauseGame(nowMs: 10),
      throwsA(isA<FieldControllerException>()),
    );
    // A follower neither beacons nor acknowledges.
    radio.sent.clear();
    fc.tick(100000);
    fc.onPacket(header(4, 1, RfType.state, ack: true), state(1, {1: 3}));
    expect(radio.sent, isEmpty);
  });

  test('promoted: a CLAIM with the ACKs heard, then the role and a TIME '
      'with the new term', () {
    fc.onPacket(header(4, 0, RfType.state), state(1, {1: 3}));
    fc.onPacket(
      header(2, 0, RfType.time),
      const RfTime(
        gameTimeMs: 0,
        gameState: 1,
        durationMs: 0,
        wallS: 0,
        term: 4,
      ).encode(),
    );
    radio.sent.clear();
    fc.promote(1000);
    final claim = RfClaim.decode(radio.sent.single.$2);
    expect((claim.term, claim.nodeId), (5, 0));
    expect(claim.lastAckSeq, {4: 0});
    expect(fc.election.role, 'candidate');
    fc.tick(5999);
    expect(fc.isController, isFalse);
    fc.tick(6000);
    expect(fc.isController, isTrue);
    expect(beacons().single.term, 5);
    expect(fc.electionLog.map((e) => e['type']), [
      'role',
      'claim_sent',
      'role',
      'role',
    ]);
  });

  test('an event the codec refuses is kept as a problem, not logged', () {
    final bad = FieldController(
      transport: radio,
      gameId: 9,
      teams: const ['red'],
    )..onEvent = events.add;
    bad.onPacket(header(4, 0, RfType.event), Uint8List(3));
    expect(events, isEmpty);
    expect(bad.problems.single['error'], contains('no event codec'));
  });
}
