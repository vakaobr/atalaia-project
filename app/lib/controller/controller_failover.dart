// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: GPL-3.0-or-later

/// Failover on the Android field controller (PE24 slice S7, decisions PE24-2
/// and PE24-118 onward): the controller election by CLAIM (ADR-P2-8, RFC
/// 0001), the Dart counterpart of the simulator's election.py, which the Pi
/// controller runs. The same rules, the same numbers, so a phone and a Pi
/// can be each other's standby on one game:
///
/// - Every TIME beacon carries the controller's term; it doubles as the
///   heartbeat. A follower that misses [missedBeacons] beacons in a row
///   considers the controller down.
/// - With `failover_mode = auto`, a controller-capable follower then claims
///   the role: term = highest term seen + 1, CLAIM with its priority.
/// - A candidate yields to any CLAIM or TIME with a higher term, or the
///   same term and a better (priority, lower node id). If nothing better is
///   heard within [electionTimeoutMs], it becomes the controller and starts
///   sending TIME with its term.
/// - A controller that hears a TIME or CLAIM with a higher term steps down
///   at once, so two controllers never both stay in charge.
/// - With `failover_mode = manual` (the default) nobody claims on their
///   own: the GM promotes a standby with [Election.promote]
///   (`POST /api/v1/controller/promote`).
/// - A follower counts missed beacons at the interval the **leader** is
///   heard beaconing at, not the one its own mode gives (decisions FAIL-1 to
///   FAIL-6): a leader on `manual` beacons every 30 s, so a standby on `auto`
///   that counted 10 s beacons took over a working controller after 30 s.
///   The follower measures the gaps between the leader's TIMEs; until it has
///   heard three in a row about 10 s apart it assumes the slowest interval
///   (30 s, so about 90 s of silence before a claim). TIMEs within 12.5 s of
///   a change of game state are no evidence (the controller repeats the
///   state as TIME 1.0, 2.5, 5.0 and 10.0 s after it, RFC 0001 Amendment
///   19). Nothing changes on the wire; [Election.leaderFailoverMode] tells
///   the engine when the leader's mode differs from this node's, so it can
///   warn.
/// - The leader's liveness and cadence come from the leader alone
///   (decisions FLC-1 to FLC-6). A follower recognises the node whose TIME
///   (header `source`, authenticated by the MIC) it first takes at a term; a
///   TIME at that term from any other source neither refreshes the leader's
///   liveness nor touches its measured cadence, and is ignored, unless its
///   source has a lower node id and the recognised leader has missed a
///   beacon (silence past its interval plus 25 %): the survivor of a split
///   election, where the leader with the higher id yields. Within one leader
///   and term the cadence is the shortest steady one heard: a gap shorter
///   than 7.5 s (an extra TIME) is skipped without moving the measuring
///   point, a long silence starts the count again without forgetting the
///   10 s already measured, and only two steady 30 s gaps in a row turn it
///   back to 30 s. A same-term CLAIM does not refresh the recognised
///   leader's liveness either. What this cannot stop: a node with the game
///   key that forges the leader's own `source`, outbids it with a higher
///   term, or beacons at the term under a lower id once the real leader is
///   gone; the key is shared by every node of the game (RFC 0001 section 3).
///
/// A pure state machine with no radio and no clock: the FieldController
/// (field_controller.dart) feeds it the TIME and CLAIM it hears and sends
/// the CLAIM and TIME it asks for. The engine (controller_engine.dart) joins
/// a game as a standby from a join payload of kind "controller"
/// (`POST /api/v1/controller/join`), follows the leader's TIME beacons and
/// takes over its field.lua when it wins (engine.py's `join_as_standby`,
/// `promote`, `_follow_state`, `_on_role`).
library;

import 'dart:math';

const electionFollower = 'follower';
const electionCandidate = 'candidate';
const electionLeader = 'leader';

/// The power source in the priority score (ADR-P2-8).
const powerUnknown = 0;
const powerSmallBattery = 1;
const powerLargeBattery = 2;
const powerMains = 3;

const beaconIntervalManualMs = 30000;
const beaconIntervalFailoverMs = 10000;
const missedBeacons = 3;
const electionTimeoutMs = 5000;

/// The leader's cadence as a follower measures it (election.py; decisions
/// FAIL-1 to FAIL-6): gaps of about 10 s in a row before a follower counts
/// 10 s beacons, gaps of about 30 s in a row before the leader counts as
/// manual (the warning), the tolerance of a gap, and how long a state
/// change's TIME repeats last (Amendment 19: the last at 10 s).
const steadyFastGaps = 3;
const steadySlowGaps = 2;
const cadenceTolerance = 0.25;
const stateRepeatWindowMs = 12500;

bool _fits(int gapMs, int intervalMs) =>
    (gapMs - intervalMs).abs() <= intervalMs * cadenceTolerance;

/// The failover modes (config.py's `failover_mode`).
const failoverModes = ['manual', 'auto'];

/// ADR-P2-8: power * 4096 + battery * 32 + storage * 512 + link * 2, as a
/// uint16 (election.py `priority_score`).
int priorityScore(
  int powerSource,
  int batteryPct,
  bool storageOk,
  int linkQuality,
) {
  final score =
      powerSource.clamp(0, 3) * 4096 +
      batteryPct.clamp(0, 100) * 32 +
      (storageOk ? 512 : 0) +
      linkQuality.clamp(0, 100) * 2;
  return min(score, 0xffff);
}

/// TIME every 30 s, or every 10 s when automatic failover is on (spec
/// section 11).
int beaconIntervalFor(String mode) =>
    mode == 'auto' ? beaconIntervalFailoverMs : beaconIntervalManualMs;

/// A CLAIM to send: the payload fields of message type 8.
final class Claim {
  const Claim(this.term, this.priority, this.nodeId);
  final int term, priority, nodeId;
}

/// True when candidate a beats candidate b: higher term, then priority,
/// then the lower node id.
bool _better(int aTerm, int aPrio, int aNode, int bTerm, int bPrio, int bNode) {
  if (aTerm != bTerm) return aTerm > bTerm;
  if (aPrio != bPrio) return aPrio > bPrio;
  return aNode < bNode;
}

class ElectionException implements Exception {
  ElectionException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// One node's view of the controller election.
class Election {
  Election(
    this.nodeId,
    this.priority, {
    this.mode = 'manual',
    this.capable = true,
    this.missed = missedBeacons,
    this.timeoutMs = electionTimeoutMs,
    int? beaconInterval,
  }) : beaconInterval = beaconInterval ?? beaconIntervalFor(mode) {
    if (!failoverModes.contains(mode)) {
      throw ElectionException(
        "failover mode must be 'manual' or 'auto', not '$mode'",
      );
    }
  }

  final int nodeId;
  final int priority;
  final String mode;
  final bool capable;
  final int missed;
  final int timeoutMs;
  final int beaconInterval;

  String role = electionFollower;

  /// The highest term seen (ours when leading).
  int term = 0;
  int? leader;
  int? _leaderTerm; // the term the recognised leader was taken at
  int? lastHeartbeatMs;
  int? candidateSinceMs;

  /// (t_ms, role, term) at each change of role.
  final history = <(int, String, int)>[];

  /// The leader's beacon interval as measured from its TIMEs (null: not
  /// known yet).
  int? leaderBeaconMs;
  (int, int)? _cadenceOf; // (leader, term) being measured
  int? _lastTimeMs;
  int? _lastState;
  int? _stateChangedMs;
  int _fastGaps = 0;
  int _slowGaps = 0;

  void _resetCadence() {
    leaderBeaconMs = null;
    _cadenceOf = null;
    _lastTimeMs = null;
    _lastState = null;
    _stateChangedMs = null;
    _fastGaps = 0;
    _slowGaps = 0;
  }

  /// One more TIME of the recognised leader: measures the gap since its last
  /// regular one. The cadence is kept per leader and term (decision FLC-1)
  /// and is the shortest steady one heard (FLC-2).
  void _observe(int source, int t, int nowMs, int? gameState) {
    if (_cadenceOf != (source, t)) {
      _resetCadence();
      _cadenceOf = (source, t);
    }
    if (gameState != null) {
      // Its repeats follow (or a leader heard for the first time).
      if (_lastState == null || gameState != _lastState) {
        _stateChangedMs = nowMs;
      }
      _lastState = gameState;
    }
    final prev = _lastTimeMs;
    final changed = _stateChangedMs;
    if (prev == null ||
        (changed != null && nowMs - changed < stateRepeatWindowMs)) {
      // The first TIME, or a state change's repeats: no evidence either way.
      _lastTimeMs = nowMs;
      return;
    }
    final gap = nowMs - prev;
    if (gap < beaconIntervalFailoverMs * (1 - cadenceTolerance)) {
      // An extra TIME: no evidence, and the next gap is measured from the
      // last regular one.
      return;
    }
    _lastTimeMs = nowMs;
    if (_fits(gap, beaconIntervalFailoverMs)) {
      _fastGaps++;
      _slowGaps = 0;
    } else if (_fits(gap, beaconIntervalManualMs)) {
      _slowGaps++; // one lost pair of 10 s beacons is not yet a manual leader
      _fastGaps = 0;
    } else if (gap > beaconIntervalFailoverMs && gap < beaconIntervalManualMs) {
      return; // a lost 10 s beacon, a late one: neither interval's evidence
    } else {
      // A long silence: count again, keep what was measured.
      _fastGaps = 0;
      _slowGaps = 0;
      return;
    }
    if (_fastGaps >= steadyFastGaps) {
      leaderBeaconMs = beaconIntervalFailoverMs;
    } else if (_slowGaps >= steadySlowGaps) {
      leaderBeaconMs = beaconIntervalManualMs;
    }
  }

  /// The beacon interval a follower counts missed beacons at: its own, but
  /// never shorter than the leader's measured one, and the slowest (30 s)
  /// while the leader's is not known.
  int get livenessInterval =>
      max(beaconInterval, leaderBeaconMs ?? beaconIntervalManualMs);

  /// The silence after which this follower stands for election (auto
  /// only), else null.
  int? get takeoverAfterMs =>
      role == electionFollower && mode == 'auto' && capable
      ? missed * livenessInterval
      : null;

  /// The leader's failover mode as its cadence shows it (`auto`, `manual`),
  /// or null while it is not known.
  String? get leaderFailoverMode => switch (leaderBeaconMs) {
    null => null,
    beaconIntervalFailoverMs => 'auto',
    _ => 'manual',
  };

  bool get isLeader => role == electionLeader;

  void _setRole(String r, int nowMs) {
    if (r != role) {
      role = r;
      history.add((nowMs, r, term));
    }
  }

  /// Takes the controller role with [t] (the first controller of a game).
  void lead(int t, int nowMs) {
    term = max(term, t);
    leader = nodeId;
    _leaderTerm = term;
    candidateSinceMs = null;
    _resetCadence();
    _setRole(electionLeader, nowMs);
  }

  /// Starts as a follower that has just heard from the controller.
  void follow(int nowMs) {
    lastHeartbeatMs = nowMs;
    _setRole(electionFollower, nowMs);
  }

  /// Manual failover: the GM makes this node a candidate now. Returns the
  /// CLAIM to send.
  Claim promote(int nowMs) {
    if (!capable) throw ElectionException('this node cannot be the controller');
    return _stand(nowMs);
  }

  Claim _stand(int nowMs) {
    term += 1;
    candidateSinceMs = nowMs;
    leader = null;
    _leaderTerm = null;
    _resetCadence();
    _setRole(electionCandidate, nowMs);
    return Claim(term, priority, nodeId);
  }

  /// A TIME beacon from [source] (with its game state, when known). False
  /// when it is to be ignored (a stale term).
  bool onTime(int t, int source, int nowMs, {int? gameState}) {
    if (source == nodeId) return true;
    if (t < term) return false; // an old controller that has not stepped down
    if (t == term && role == electionLeader) {
      // Two controllers with one term cannot happen through CLAIM; keep the
      // deterministic winner (the lower node id) and let the other yield.
      if (source > nodeId) return false;
    }
    if (role == electionFollower &&
        _fromAnotherThanTheLeader(t, source, nowMs)) {
      return false;
    }
    term = t;
    leader = source;
    _leaderTerm = t;
    lastHeartbeatMs = nowMs;
    candidateSinceMs = null;
    _setRole(electionFollower, nowMs);
    _observe(source, t, nowMs, gameState);
    return true;
  }

  /// True for a TIME at the recognised leader's term from another source
  /// (decision FLC-3): it is not the leader's liveness and is ignored. The
  /// one exception is the survivor of a split election: two leaders at one
  /// term resolve to the lower node id (the other yields, [onTime]), so a
  /// source with a lower id is taken once the recognised leader has missed a
  /// beacon (silence past its interval plus the tolerance).
  bool _fromAnotherThanTheLeader(int t, int source, int nowMs) {
    final current = leader;
    if (current == null || source == current || _leaderTerm != t) {
      return false;
    }
    final last = lastHeartbeatMs;
    if (source > current || last == null) return source > current;
    return nowMs - last <= livenessInterval * (1 + cadenceTolerance);
  }

  /// A CLAIM from another candidate.
  void onClaim(int t, int prio, int node, int nowMs) {
    if (node == nodeId || t < term) return;
    if (role == electionCandidate && t > term) {
      _yield(t, nowMs);
      return;
    }
    if (role == electionCandidate && t == term) {
      if (_better(t, prio, node, term, priority, nodeId)) _yield(t, nowMs);
      return;
    }
    if (role == electionLeader) {
      if (t > term) _yield(t, nowMs);
      return;
    }
    // A follower: an election is under way; wait for its winner's TIME. A
    // CLAIM at the term of the leader it follows is no election after that
    // leader, and not its liveness (decision FLC-4).
    if (leader != null && _leaderTerm == t) return;
    term = max(term, t);
    lastHeartbeatMs = nowMs;
  }

  void _yield(int t, int nowMs) {
    term = t;
    leader = null;
    _leaderTerm = null;
    candidateSinceMs = null;
    lastHeartbeatMs = nowMs; // a full timeout for the winner to beacon
    _setRole(electionFollower, nowMs);
  }

  /// Moves to [nowMs]. Returns a CLAIM to send when this node stands for
  /// election.
  Claim? tick(int nowMs) {
    if (role == electionCandidate) {
      if (nowMs - candidateSinceMs! >= timeoutMs) lead(term, nowMs);
      return null;
    }
    if (role == electionFollower && mode == 'auto' && capable) {
      final last = lastHeartbeatMs ??= nowMs;
      if (nowMs - last >= missed * livenessInterval) return _stand(nowMs);
    }
    return null;
  }
}
