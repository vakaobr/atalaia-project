// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The CLAIM election on the phone (lib/controller/controller_failover.dart,
// PE24 slice S7): simulator/tests/test_election.py's cases, the same
// numbers, so a phone and a Pi elect alike. Then a phone and a phone over a
// shared air: one leads, the other joins as its standby from the leader's
// join payload, the leader goes silent and the standby takes over with
// automatic failover (the cross-controller behaviour against the Pi is
// pinned by the shared contract cases' s7 block).

import 'dart:typed_data';

import 'package:atalaia_app/controller/controller_engine.dart';
import 'package:atalaia_app/controller/controller_failover.dart';
import 'package:atalaia_app/controller/field_controller.dart';
import 'package:atalaia_app/radio/rf_codec.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  group('priority', () {
    test('the formula (ADR-P2-8)', () {
      expect(
        priorityScore(powerMains, 100, true, 100),
        3 * 4096 + 3200 + 512 + 200,
      );
      expect(priorityScore(powerSmallBattery, 50, false, 40), 4096 + 1600 + 80);
    });
    test('a mains Pi beats a phone on battery', () {
      expect(
        priorityScore(powerMains, 0, true, 0),
        greaterThan(priorityScore(powerSmallBattery, 100, true, 100)),
      );
      expect(
        const ControllerConfig().priority,
        priorityScore(powerSmallBattery, 100, true, 100),
      );
    });
    test('clamped to uint16 and the ranges', () {
      expect(priorityScore(9, 500, true, 500), lessThanOrEqualTo(0xffff));
      expect(priorityScore(-1, -5, false, -3), 0);
    });
    test('the beacon interval', () {
      expect(beaconIntervalFor('manual'), 30000);
      expect(beaconIntervalFor('auto'), 10000);
    });
    test('a bad mode', () {
      expect(
        () => Election(1, 100, mode: 'sometimes'),
        throwsA(isA<ElectionException>()),
      );
    });
  });

  group('automatic', () {
    late Election e;
    setUp(() {
      e = Election(5, 1000, mode: 'auto')..follow(0);
      e.onTime(1, 0, 0);
    });

    test('heartbeats keep a follower quiet', () {
      for (var t = 10000; t < 200000; t += 10000) {
        expect(e.onTime(1, 0, t), isTrue);
        expect(e.tick(t + 1), isNull);
      }
      expect(e.role, electionFollower);
    });
    test('three missed beacons start a claim', () {
      expect(e.tick(29999), isNull);
      final claim = e.tick(30000)!;
      expect((claim.term, claim.priority, claim.nodeId), (2, 1000, 5));
      expect(e.role, electionCandidate);
    });
    test('an unopposed candidate leads after the timeout', () {
      e
        ..tick(30000)
        ..tick(34999);
      expect(e.role, electionCandidate);
      e.tick(35000);
      expect(e.role, electionLeader);
      expect(e.term, 2);
    });
    test('a better claim wins', () {
      e
        ..tick(30000)
        ..onClaim(2, 2000, 9, 30100);
      expect(e.role, electionFollower);
      e.tick(40000);
      expect(e.role, electionFollower); // waits for the winner's TIME
    });
    test('a worse claim is ignored', () {
      e
        ..tick(30000)
        ..onClaim(2, 500, 1, 30100);
      expect(e.role, electionCandidate);
      e.tick(35000);
      expect(e.role, electionLeader);
    });
    test('equal priority: the lowest node id wins', () {
      e
        ..tick(30000)
        ..onClaim(2, 1000, 7, 30100);
      expect(e.role, electionCandidate); // 5 < 7
      e.onClaim(2, 1000, 3, 30200);
      expect(e.role, electionFollower); // 3 < 5
    });
    test('a higher term beats priority', () {
      e
        ..tick(30000)
        ..onClaim(3, 1, 99, 30100);
      expect(e.role, electionFollower);
      expect(e.term, 3);
    });
    test('the leader steps down on a higher term', () {
      e
        ..tick(30000)
        ..tick(35000);
      expect(e.isLeader, isTrue);
      expect(e.onTime(1, 0, 36000), isFalse); // the old controller: ignored
      expect(e.isLeader, isTrue);
      expect(e.onTime(3, 8, 37000), isTrue);
      expect(e.role, electionFollower);
      expect(e.leader, 8);
    });
    test('a stale claim is ignored', () {
      e.onClaim(1, 60000, 0, 1000);
      expect(e.term, 1);
      expect(e.role, electionFollower);
    });
    test('the history keeps the role changes', () {
      e
        ..tick(30000)
        ..tick(35000);
      final roles = [for (final h in e.history) h.$2];
      expect(roles.sublist(roles.length - 2), [
        electionCandidate,
        electionLeader,
      ]);
    });
  });

  group('manual', () {
    test('never claims on its own', () {
      final e = Election(5, 1000)..follow(0);
      for (var t = 0; t < 600000; t += 1000) {
        expect(e.tick(t), isNull);
      }
      expect(e.role, electionFollower);
    });
    test('promote', () {
      final e = Election(5, 1000)..follow(0);
      e.onTime(4, 0, 0);
      expect(e.promote(1000).term, 5);
      e.tick(6000);
      expect(e.isLeader, isTrue);
    });
    test('a node that cannot lead cannot be promoted', () {
      final e = Election(5, 0, capable: false);
      expect(() => e.promote(0), throwsA(isA<ElectionException>()));
    });
    test('two leaders with one term resolve by node id', () {
      final a = Election(2, 100)..lead(7, 0);
      expect(a.onTime(7, 4, 10), isFalse); // a higher id: a keeps the role
      expect(a.isLeader, isTrue);
      final b = Election(4, 100)..lead(7, 0);
      expect(b.onTime(7, 2, 10), isTrue); // a lower id: b yields
      expect(b.role, electionFollower);
    });
  });

  group('two FieldControllers on one air', () {
    // Each one's packets reach the other (a radio without loss).
    late _Air air;
    late FieldController a, b;
    setUp(() {
      air = _Air();
      a = FieldController(
        transport: air.port(1),
        gameId: 3,
        teams: const ['red', 'blue'],
        nodeId: 1,
        election: Election(1, 20000, mode: 'auto')..lead(1, 0),
      );
      b = FieldController(
        transport: air.port(2),
        gameId: 3,
        teams: const ['red', 'blue'],
        nodeId: 2,
        election: Election(2, 5000, mode: 'auto')..follow(0),
      );
      air.controllers
        ..[1] = a
        ..[2] = b;
    });

    test('the standby follows, then takes over when the leader falls silent '
        'and the old leader steps down when it comes back', () {
      a.startGame(nowMs: 0, durationMs: 600000);
      expect((b.gameState, b.term, b.election.leader), (gameRunning, 1, 1));
      for (var t = 1000; t <= 25000; t += 1000) {
        a.tick(t);
        b.tick(t);
      }
      expect(a.beaconInterval, 10000);
      expect(b.isController, isFalse);
      air.down.add(1); // the leader's radio goes quiet, both ways
      var t = 25000;
      while (!b.isController && t < 80000) {
        t += 1000;
        a.tick(t);
        b.tick(t);
      }
      expect(b.isController, isTrue);
      expect(b.term, 2);
      expect(b.gameTimeMs, closeTo(t, 1000));
      air.down.remove(1); // it comes back: b's next TIME puts it on standby
      for (var i = 0; i < 11; i++) {
        t += 1000;
        a.tick(t);
        b.tick(t);
      }
      expect(a.isController, isFalse);
      expect((a.term, a.election.leader), (2, 2));
    });
  });
}

class _Air {
  final controllers = <int, FieldController>{};
  final down = <int>{};
  final _seq = <int, int>{};

  FieldTransport port(int node) => _Port(this, node);

  int send(int from, int type, Uint8List payload) {
    final seq = _seq[from] = (_seq[from] ?? -1) + 1;
    if (down.contains(from)) return seq;
    for (final MapEntry(key: id, value: fc) in controllers.entries) {
      if (id == from || down.contains(id)) continue;
      fc.onPacket(
        RfHeader.v1(gameId: 3, source: from, seq: seq, hopLimit: 2, type: type),
        payload,
      );
    }
    return seq;
  }
}

class _Port implements FieldTransport {
  _Port(this.air, this.node);
  final _Air air;
  final int node;
  @override
  String get state => 'up';
  @override
  int? send(
    int type,
    Uint8List payload, {
    required int prio,
    required bool ack,
    required int hopLimit,
  }) => air.send(node, type, payload);
}
