// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

// The CLAIM election on the phone (lib/controller/controller_failover.dart,
// PE24 slice S7): simulator/tests/test_election.py's cases, the same
// numbers, so a phone and a Pi elect alike. Then a phone and a phone over a
// shared air: one leads, the other joins as its standby from the leader's
// join payload, the leader goes silent and the standby takes over with
// automatic failover (the cross-controller behaviour against the Pi is
// pinned by the shared contract cases' s7 block).

import 'dart:math';
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
      // A leader on auto, heard beaconing every 10 s (the first TIME's gap
      // is no evidence, then three steady gaps: decisions FAIL-1 to FAIL-3),
      // the last one at 0.
      e = Election(5, 1000, mode: 'auto')..follow(-40000);
      for (var t = -40000; t <= 0; t += 10000) {
        e.onTime(1, 0, t, gameState: 1);
      }
      expect(e.leaderBeaconMs, 10000);
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

  group('mixed failover modes (decisions FAIL-1 to FAIL-6)', () {
    const running = 1, paused = 2;
    const repeats = [1000, 2500, 5000, 10000]; // Amendment 19

    /// Feeds the leader's TIMEs at [times] and ticks every 100 ms; the first
    /// CLAIM's time, or null.
    int? runBeacons(
      Election e,
      List<int> times, {
      List<int>? states,
      int? until,
    }) {
      final beacons = <int, int>{
        for (var i = 0; i < times.length; i++)
          times[i]: states == null ? running : states[i],
      };
      final end = until ?? times.reduce(max);
      for (var t = 0; t <= end; t += 100) {
        final s = beacons[t];
        if (s != null) e.onTime(1, 0, t, gameState: s);
        if (e.tick(t) != null) return t;
      }
      return null;
    }

    test('an auto standby never takes over a working manual leader', () {
      final e = Election(5, 1000, mode: 'auto')..follow(0);
      // Before the fix: a claim 30 s after the first beacon.
      expect(runBeacons(e, [for (var t = 0; t <= 600000; t += 30000) t]), null);
      expect(e.role, electionFollower);
      expect(e.leaderBeaconMs, 30000);
      expect(e.leaderFailoverMode, 'manual');
      expect(e.takeoverAfterMs, 90000);
    });
    test('a late manual beacon is not three missed ones', () {
      // No game state given, as an older caller.
      final e = Election(5, 1000, mode: 'auto')..follow(0);
      for (var i = 0; i < 20; i++) {
        e.onTime(1, 0, i * 30200);
        for (var t = i * 30200; t < (i + 1) * 30200; t += 100) {
          expect(e.tick(t), null, reason: 'a claim at $t ms');
        }
      }
      expect(e.leaderFailoverMode, 'manual');
    });
    test('it takes over when the manual leader falls silent', () {
      final e = Election(5, 1000, mode: 'auto')..follow(0);
      expect(
        runBeacons(e, [
          for (var t = 0; t <= 120000; t += 30000) t,
        ], until: 400000),
        120000 + 90000,
      );
    });
    test('a state change repeated as TIME is not taken for auto', () {
      final e = Election(5, 1000, mode: 'auto')..follow(0);
      final times = [0, 30000], states = [running, running];
      var state = running, t = 30000;
      for (final after in [10000, 10000, 12000, 9000, 10000]) {
        t += after;
        state = state == running ? paused : running;
        final burst = [t, for (final r in repeats) t + r];
        times.addAll(burst);
        states.addAll([for (final _ in burst) state]);
        t = burst.last;
      }
      for (var i = 0; i < 4; i++) {
        t += 30000;
        times.add(t);
        states.add(state);
      }
      expect(runBeacons(e, times, states: states), null);
      expect(e.leaderBeaconMs, isNot(10000));
    });
    test('a manual standby sees an auto leader and waits for the GM', () {
      final e = Election(5, 1000)..follow(0);
      expect(
        runBeacons(e, [
          for (var t = 0; t <= 100000; t += 10000) t,
        ], until: 600000),
        null,
      );
      expect(e.leaderFailoverMode, 'auto');
      expect(e.takeoverAfterMs, null);
    });
    test('until the leader is heard the slowest interval counts', () {
      final e = Election(5, 1000, mode: 'auto')..follow(0);
      expect(e.leaderBeaconMs, null);
      expect(e.takeoverAfterMs, 90000);
      expect(e.tick(89999), null);
      expect(e.tick(90000), isNotNull);
    });
    test('an auto leader is learned and a lost beacon keeps it', () {
      final e = Election(5, 1000, mode: 'auto')..follow(0);
      expect(runBeacons(e, [0, 10000, 20000, 30000]), null);
      expect(e.leaderBeaconMs, null);
      expect(runBeacons(e, [40000]), null);
      expect(e.leaderBeaconMs, 10000);
      e.onTime(1, 0, 60000, gameState: running); // 50 s was lost
      expect(e.leaderBeaconMs, 10000);
      expect(e.tick(89999), null);
      expect(e.tick(90000), isNotNull);
    });
    test('two lost beacons keep the auto cadence, two steady 30 s gaps do not '
        '(FLC-2)', () {
      final e = Election(5, 1000)..follow(0);
      runBeacons(e, [0, 10000, 20000, 30000, 40000]);
      expect(e.leaderBeaconMs, 10000);
      e.onTime(1, 0, 70000, gameState: running);
      expect(e.leaderBeaconMs, 10000);
      e.onTime(1, 0, 100000, gameState: running);
      expect(e.leaderBeaconMs, 30000);
      expect(e.leaderFailoverMode, 'manual');
    });
    test('a new leader or term is measured afresh', () {
      final e = Election(5, 1000, mode: 'auto')..follow(0);
      runBeacons(e, [0, 10000, 20000, 30000, 40000]);
      e.onTime(2, 7, 45000, gameState: running);
      expect(e.leaderBeaconMs, null);
      expect(e.takeoverAfterMs, 90000);
    });
  });

  group('the leader alone is its liveness (decisions FLC-1 to FLC-6)', () {
    const running = 1, leaderId = 10, other = 11;

    /// A standby on auto behind a leader on auto (10 s); with
    /// [hostileOffset], another source sends a TIME at the same term that long
    /// after each of the leader's. Returns the election and the last TIME.
    (Election, int) fastLeader({int? hostileOffset, int beacons = 8}) {
      final e = Election(50, 100, mode: 'auto')..follow(0);
      var t = 0;
      e.onTime(1, leaderId, t, gameState: running);
      for (var i = 0; i < beacons; i++) {
        t += 10000;
        expect(e.onTime(1, leaderId, t, gameState: running), isTrue);
        if (hostileOffset != null) {
          expect(
            e.onTime(1, other, t + hostileOffset, gameState: running),
            isFalse,
          );
        }
      }
      return (e, t);
    }

    test(
      'same-term TIMEs from another source do not hide the fast cadence',
      () {
        for (final offset in [0, 1, 3000, 5000, 8000, 9900]) {
          final (e, _) = fastLeader(hostileOffset: offset);
          expect(e.leader, leaderId, reason: 'offset $offset');
          expect(e.leaderBeaconMs, 10000, reason: 'offset $offset');
          expect(e.livenessInterval, 10000, reason: 'offset $offset');
          expect(e.takeoverAfterMs, 30000, reason: 'offset $offset');
        }
      },
    );
    test('they do not keep a dead leader alive', () {
      final (e, t) = fastLeader(beacons: 4);
      expect(e.takeoverAfterMs, 30000);
      int? claimed;
      for (var now = t + 100; now <= t + 330000; now += 100) {
        if ((now - t) % 5000 == 0 && now - t <= 12000) {
          e.onTime(1, other, now, gameState: running);
        }
        if (e.tick(now) != null) {
          claimed = now;
          break;
        }
      }
      expect(claimed, t + 30000);
    });
    test('continuous TIMEs from a higher id after the leader died do not '
        'block the takeover', () {
      final (e, t) = fastLeader(beacons: 4);
      int? claimed;
      for (var now = t + 100; now <= t + 330000; now += 100) {
        if ((now - t) % 30000 == 0) {
          expect(e.onTime(1, other, now, gameState: running), isFalse);
        }
        if (e.tick(now) != null) {
          claimed = now;
          break;
        }
      }
      expect(claimed, t + 30000);
      expect(e.role, electionCandidate);
    });
    test('the survivor of a split election is followed once the other leader '
        'stops', () {
      final (e, t) = fastLeader(beacons: 4);
      expect(e.onTime(1, 4, t + 5000), isFalse);
      expect(e.onTime(1, 12, t + 12600), isFalse); // a higher id: never
      expect(e.onTime(1, 4, t + 12600), isTrue); // past 10 s + 25 %
      expect(e.leader, 4);
      expect(e.leaderBeaconMs, null);
      for (var now = t + 12600; now < t + 200000; now += 100) {
        if ((now - t - 12600) % 10000 == 0) e.onTime(1, 4, now);
        expect(e.tick(now), null, reason: 'a claim at $now');
      }
    });
    test('a manual leader is still not taken over', () {
      final e = Election(50, 100, mode: 'auto')..follow(0);
      for (var t = 0; t <= 600000; t += 100) {
        if (t % 30000 == 0) e.onTime(1, leaderId, t, gameState: running);
        if (t % 10000 == 5000) e.onTime(1, other, t, gameState: running);
        expect(e.tick(t), null, reason: 'a claim at $t');
      }
      expect(e.leader, leaderId);
      expect(e.leaderBeaconMs, 30000);
    });
    test('an extra TIME from the leader does not reset its cadence', () {
      var (e, t) = fastLeader(beacons: 4);
      expect(e.leaderBeaconMs, 10000);
      for (var k = 0; k < 5; k++) {
        e.onTime(1, leaderId, t + 4000, gameState: running);
        t += 10000;
        e.onTime(1, leaderId, t, gameState: running);
        expect(e.leaderBeaconMs, 10000, reason: 'round $k');
      }
    });
    test('a long silence keeps the measured cadence', () {
      final e = Election(50, 100)..follow(0);
      for (var t = 0; t <= 40000; t += 10000) {
        e.onTime(1, leaderId, t, gameState: running);
      }
      expect(e.leaderBeaconMs, 10000);
      e.onTime(1, leaderId, 140000, gameState: running);
      expect(e.leaderBeaconMs, 10000);
    });
    test('a same-term CLAIM is not the leader\'s liveness', () {
      final (e, t) = fastLeader(beacons: 4);
      for (var k = 1; k <= 5; k++) {
        e.onClaim(1, 60000, other, t + k * 5000);
        if (k * 5000 < 30000) expect(e.tick(t + k * 5000), null);
      }
      expect(e.tick(t + 30000), isNotNull);
    });
    test('a CLAIM at a higher term still opens the election', () {
      final (e, t) = fastLeader(beacons: 4);
      e.onClaim(2, 60000, other, t + 20000);
      expect(e.term, 2);
      expect(e.tick(t + 49999), null);
      expect(e.onTime(2, other, t + 25000), isTrue);
      expect(e.leader, other);
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
      // Long enough for b to hear a's 10 s beacons (decision FAIL-2).
      for (var t = 1000; t <= 55000; t += 1000) {
        a.tick(t);
        b.tick(t);
      }
      expect(a.beaconInterval, 10000);
      expect(b.election.leaderBeaconMs, 10000);
      expect(b.isController, isFalse);
      air.down.add(1); // the leader's radio goes quiet, both ways
      var t = 55000;
      while (!b.isController && t < 110000) {
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

  test('an auto standby behind a manual leader on one air never takes over '
      'while the leader works, and does once it falls silent (FAIL-1)', () {
    final air = _Air();
    final a = FieldController(
      transport: air.port(1),
      gameId: 3,
      teams: const ['red', 'blue'],
      nodeId: 1,
      election: Election(1, 20000)..lead(1, 0),
    );
    final b = FieldController(
      transport: air.port(2),
      gameId: 3,
      teams: const ['red', 'blue'],
      nodeId: 2,
      election: Election(2, 5000, mode: 'auto')..follow(0),
    );
    air.controllers
      ..[1] = a
      ..[2] = b;
    a.startGame(nowMs: 0, durationMs: 900000);
    var t = 0;
    void run(int until) {
      while (t < until) {
        t += 500;
        a.tick(t);
        b.tick(t);
      }
    }

    run(100000);
    air.down.add(1); // one beacon lost: a 60 s gap, under 3 x 30 s
    run(125000);
    air.down.remove(1);
    run(600000);
    expect(a.beaconInterval, 30000);
    expect(a.isController, isTrue);
    expect(b.isController, isFalse);
    expect(b.election.history.where((h) => h.$2 != electionFollower), isEmpty);
    expect(b.election.leaderFailoverMode, 'manual');
    final lastBeacon = b.election.lastHeartbeatMs!;
    air.down.add(1);
    run(800000);
    expect(b.isController, isTrue);
    final stood = b.election.history.firstWhere(
      (h) => h.$2 == electionCandidate,
    );
    expect(stood.$1 - lastBeacon, inInclusiveRange(90000, 90500));
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
