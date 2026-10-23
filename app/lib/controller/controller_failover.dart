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
  int? lastHeartbeatMs;
  int? candidateSinceMs;

  /// (t_ms, role, term) at each change of role.
  final history = <(int, String, int)>[];

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
    candidateSinceMs = null;
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
    _setRole(electionCandidate, nowMs);
    return Claim(term, priority, nodeId);
  }

  /// A TIME beacon from [source]. False when it is to be ignored (a stale
  /// term).
  bool onTime(int t, int source, int nowMs) {
    if (source == nodeId) return true;
    if (t < term) return false; // an old controller that has not stepped down
    if (t == term && role == electionLeader) {
      // Two controllers with one term cannot happen through CLAIM; keep the
      // deterministic winner (the lower node id) and let the other yield.
      if (source > nodeId) return false;
    }
    term = t;
    leader = source;
    lastHeartbeatMs = nowMs;
    candidateSinceMs = null;
    _setRole(electionFollower, nowMs);
    return true;
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
    // A follower: an election is under way; wait for its winner's TIME.
    term = max(term, t);
    lastHeartbeatMs = nowMs;
  }

  void _yield(int t, int nowMs) {
    term = t;
    leader = null;
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
      if (nowMs - last >= missed * beaconInterval) return _stand(nowMs);
    }
    return null;
  }
}
