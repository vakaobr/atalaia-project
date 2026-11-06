# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Controller election by CLAIM (ADR-P2-8, RFC 0001).

A pure state machine with no radio and no clock of its own: the caller
feeds it the TIME and CLAIM messages it hears and the current time, and
sends the CLAIM and TIME messages it asks for. The simulator's
FieldController and the real field controller run the same code.

Rules:

- Every TIME beacon carries the controller's term; it doubles as the
  heartbeat. A follower that misses ``missed_beacons`` beacons in a row
  considers the controller down.
- With ``mode == "auto"``, a controller-capable follower then claims the
  role: term = highest term seen + 1, CLAIM with its priority.
- A candidate yields to any CLAIM or TIME with a higher term, or the same
  term and a better (priority, lower node id). If nothing better is heard
  within ``election_timeout_ms``, it becomes the controller and starts
  sending TIME with its term.
- A controller that hears a TIME or CLAIM with a higher term steps down at
  once, so two controllers never both stay in charge.
- With ``mode == "manual"`` (the Phase 2 default) nobody claims on their
  own: the GM promotes a standby controller with :meth:`promote`.
- A follower counts missed beacons at the interval the **leader** is heard
  beaconing at, not the one its own mode gives (decisions FAIL-1 to FAIL-6):
  a leader on ``manual`` beacons every 30 s, so a standby on ``auto`` that
  counted 10 s beacons took over a working controller after 30 s. The
  follower measures the gaps between the leader's TIMEs; until it has heard
  three in a row about 10 s apart it assumes the slowest interval (30 s, so
  about 90 s of silence before a claim). TIMEs within 12.5 s of a change of
  game state are no evidence (the controller repeats the state as TIME
  1.0, 2.5, 5.0 and 10.0 s after it, RFC 0001 Amendment 19). Nothing
  changes on the wire; :attr:`leader_failover_mode` tells the engines when
  the leader's mode differs from this node's, so they can warn.
- The leader's liveness and cadence come from the leader alone (decisions
  FLC-1 to FLC-6). A follower recognises the node whose TIME (header
  ``source``, authenticated by the MIC) it first takes at a term; a TIME at
  that term from any other source neither refreshes the leader's liveness
  nor touches its measured cadence, and is ignored, unless its source has a
  lower node id and the recognised leader has missed a beacon (silence past
  its interval plus 25 %): the survivor of a split election, where the
  leader with the higher id yields (section "two controllers" below). Within one leader
  and term the cadence is the shortest steady one heard: a gap shorter than
  7.5 s (an extra TIME) is skipped without moving the measuring point, a
  long silence starts the count again without forgetting the 10 s already
  measured, and only two steady 30 s gaps in a row turn it back to 30 s. A
  same-term CLAIM does not refresh the recognised leader's liveness either.
  What this cannot stop: a node with the game key that forges the leader's
  own ``source``, outbids it with a higher term, or beacons at the term
  under a lower id once the real leader is gone (it is then the leader as
  far as the radio can tell); the key is shared by every node of the game (RFC 0001
  section 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

FOLLOWER = "follower"
CANDIDATE = "candidate"
LEADER = "leader"

# Power source values for the priority score (ADR-P2-8).
POWER_UNKNOWN = 0
POWER_SMALL_BATTERY = 1
POWER_LARGE_BATTERY = 2
POWER_MAINS = 3

BEACON_INTERVAL_MS = 30_000
BEACON_INTERVAL_FAILOVER_MS = 10_000
MISSED_BEACONS = 3
ELECTION_TIMEOUT_MS = 5_000

# The leader's cadence as a follower measures it (decisions FAIL-1 to FAIL-6).
STEADY_FAST_GAPS = 3  # gaps of about 10 s in a row before a follower counts 10 s beacons
STEADY_SLOW_GAPS = 2  # gaps of about 30 s in a row before the leader counts as manual (the warning)
CADENCE_TOLERANCE = 0.25  # a gap within 25 % of an interval fits it
STATE_REPEAT_WINDOW_MS = 12_500  # the TIME repeats of a state change end at 10 s (Amendment 19)


def priority_score(power_source: int, battery_pct: int, storage_ok: bool, link_quality: int) -> int:
    """ADR-P2-8: power * 4096 + battery * 32 + storage * 512 + link * 2, as a uint16."""
    power_source = max(0, min(3, int(power_source)))
    battery_pct = max(0, min(100, int(battery_pct)))
    link_quality = max(0, min(100, int(link_quality)))
    score = power_source * 4096 + battery_pct * 32 + (512 if storage_ok else 0) + link_quality * 2
    return min(score, 0xFFFF)


def beacon_interval_ms(mode: str) -> int:
    """TIME every 30 s, or every 10 s when automatic failover is on (spec section 11)."""
    return BEACON_INTERVAL_FAILOVER_MS if mode == "auto" else BEACON_INTERVAL_MS


@dataclass(frozen=True)
class Claim:
    """A CLAIM to send: the payload fields of message type 8."""

    term: int
    priority: int
    node_id: int


def _fits(gap_ms: int, interval_ms: int) -> bool:
    return abs(gap_ms - interval_ms) <= interval_ms * CADENCE_TOLERANCE


def _better(a_term: int, a_prio: int, a_node: int, b_term: int, b_prio: int, b_node: int) -> bool:
    """True when candidate a beats candidate b: higher term, then priority, then lower node id."""
    if a_term != b_term:
        return a_term > b_term
    if a_prio != b_prio:
        return a_prio > b_prio
    return a_node < b_node


class Election:
    """One node's view of the controller election."""

    def __init__(
        self,
        node_id: int,
        priority: int,
        *,
        mode: str = "manual",
        capable: bool = True,
        missed_beacons: int = MISSED_BEACONS,
        election_timeout_ms: int = ELECTION_TIMEOUT_MS,
        beacon_interval: Optional[int] = None,
    ) -> None:
        if mode not in ("manual", "auto"):
            raise ValueError(f"failover mode must be 'manual' or 'auto', not {mode!r}")
        self.node_id = node_id
        self.priority = priority
        self.mode = mode
        self.capable = capable
        self.missed_beacons = missed_beacons
        self.election_timeout_ms = election_timeout_ms
        self.beacon_interval = beacon_interval if beacon_interval is not None else beacon_interval_ms(mode)

        self.role = FOLLOWER
        self.term = 0  # highest term seen (ours when leading)
        self.leader: Optional[int] = None
        self._leader_term: Optional[int] = None  # the term the recognised leader was taken at
        self.last_heartbeat_ms: Optional[int] = None
        self.candidate_since_ms: Optional[int] = None
        self.history: list[tuple[int, str, int]] = []  # (t_ms, role, term)
        # The leader's beacon interval as measured from its TIMEs (None: not known yet).
        self.leader_beacon_ms: Optional[int] = None
        self._reset_cadence()

    # --- the leader's cadence --------------------------------------------------

    def _reset_cadence(self) -> None:
        self.leader_beacon_ms = None
        self._cadence_of: Optional[tuple[int, int]] = None  # (leader, term) being measured
        self._last_time_ms: Optional[int] = None
        self._last_state: Optional[int] = None
        self._state_changed_ms: Optional[int] = None
        self._fast_gaps = 0
        self._slow_gaps = 0

    def _observe(self, source: int, term: int, now_ms: int, game_state: Optional[int]) -> None:
        """One more TIME of the recognised leader: measures the gap since its last regular one. The
        cadence is kept per leader and term (decision FLC-1) and is the shortest steady one heard (FLC-2)."""
        if self._cadence_of != (source, term):
            self._reset_cadence()
            self._cadence_of = (source, term)
        if game_state is not None:
            if self._last_state is None or game_state != self._last_state:
                self._state_changed_ms = now_ms  # its repeats follow (or a leader heard first)
            self._last_state = game_state
        prev = self._last_time_ms
        if prev is None or (self._state_changed_ms is not None
                            and now_ms - self._state_changed_ms < STATE_REPEAT_WINDOW_MS):
            self._last_time_ms = now_ms
            return  # the first TIME, or a state change's repeats: no evidence either way
        gap = now_ms - prev
        if gap < BEACON_INTERVAL_FAILOVER_MS * (1 - CADENCE_TOLERANCE):
            return  # an extra TIME: no evidence, and the next gap is measured from the last regular one
        self._last_time_ms = now_ms
        if _fits(gap, BEACON_INTERVAL_FAILOVER_MS):
            self._fast_gaps += 1
            self._slow_gaps = 0
        elif _fits(gap, BEACON_INTERVAL_MS):
            self._slow_gaps += 1  # one lost pair of 10 s beacons is not yet a leader on manual
            self._fast_gaps = 0
        elif BEACON_INTERVAL_FAILOVER_MS < gap < BEACON_INTERVAL_MS:
            return  # a lost 10 s beacon, a late one: neither interval's evidence
        else:
            self._fast_gaps = self._slow_gaps = 0  # a long silence: count again, keep what was measured
            return
        if self._fast_gaps >= STEADY_FAST_GAPS:
            self.leader_beacon_ms = BEACON_INTERVAL_FAILOVER_MS
        elif self._slow_gaps >= STEADY_SLOW_GAPS:
            self.leader_beacon_ms = BEACON_INTERVAL_MS

    @property
    def liveness_interval(self) -> int:
        """The beacon interval a follower counts missed beacons at: its own, but never shorter than the
        leader's measured one, and the slowest (30 s) while the leader's is not known."""
        measured = self.leader_beacon_ms if self.leader_beacon_ms is not None else BEACON_INTERVAL_MS
        return max(self.beacon_interval, measured)

    @property
    def takeover_after_ms(self) -> Optional[int]:
        """The silence after which this follower stands for election (auto only), else None."""
        if self.role != FOLLOWER or self.mode != "auto" or not self.capable:
            return None
        return self.missed_beacons * self.liveness_interval

    @property
    def leader_failover_mode(self) -> Optional[str]:
        """The leader's failover mode as its cadence shows it ("auto", "manual"), or None not known."""
        if self.leader_beacon_ms is None:
            return None
        return "auto" if self.leader_beacon_ms == BEACON_INTERVAL_FAILOVER_MS else "manual"

    # --- state changes ---------------------------------------------------------

    def _set_role(self, role: str, now_ms: int) -> None:
        if role != self.role:
            self.role = role
            self.history.append((now_ms, role, self.term))

    def lead(self, term: int, now_ms: int) -> None:
        """Take the controller role with ``term`` (the first controller of a game)."""
        self.term = max(self.term, term)
        self.leader = self.node_id
        self._leader_term = self.term
        self.candidate_since_ms = None
        self._reset_cadence()
        self._set_role(LEADER, now_ms)

    def follow(self, now_ms: int) -> None:
        """Start as a follower that has just heard from the controller."""
        self.last_heartbeat_ms = now_ms
        self._set_role(FOLLOWER, now_ms)

    def promote(self, now_ms: int) -> Claim:
        """Manual failover: the GM makes this node a candidate now. Returns the CLAIM to send."""
        if not self.capable:
            raise ValueError("this node cannot be the controller")
        return self._stand(now_ms)

    def _stand(self, now_ms: int) -> Claim:
        self.term += 1
        self.candidate_since_ms = now_ms
        self.leader = None
        self._leader_term = None
        self._reset_cadence()
        self._set_role(CANDIDATE, now_ms)
        return Claim(self.term, self.priority, self.node_id)

    # --- what we hear ----------------------------------------------------------

    def on_time(self, term: int, source: int, now_ms: int, game_state: Optional[int] = None) -> bool:
        """A TIME beacon from ``source`` (with its game state, when known). Returns False if it should
        be ignored (stale term)."""
        if source == self.node_id:
            return True
        if term < self.term:
            return False  # an old controller that has not stepped down yet
        if term == self.term and self.role == LEADER:
            # Two controllers with one term cannot happen through CLAIM; keep
            # the deterministic winner (lower node id) and let the other yield.
            if source > self.node_id:
                return False
        if self.role == FOLLOWER and self._from_another_than_the_leader(term, source, now_ms):
            return False
        self.term = term
        self.leader = source
        self._leader_term = term
        self.last_heartbeat_ms = now_ms
        self.candidate_since_ms = None
        self._set_role(FOLLOWER, now_ms)
        self._observe(source, term, now_ms, game_state)
        return True

    def _from_another_than_the_leader(self, term: int, source: int, now_ms: int) -> bool:
        """True for a TIME at the recognised leader's term from another source (decision FLC-3): it is
        not the leader's liveness and is ignored. The one exception is the survivor of a split election:
        two leaders at one term resolve to the lower node id (the other yields, :meth:`on_time`), so a
        source with a lower id is taken once the recognised leader has missed a beacon (silence past its
        interval plus the tolerance)."""
        if self.leader is None or source == self.leader or self._leader_term != term:
            return False
        if source > self.leader or self.last_heartbeat_ms is None:
            return source > self.leader
        silence = now_ms - self.last_heartbeat_ms
        return silence <= self.liveness_interval * (1 + CADENCE_TOLERANCE)

    def on_claim(self, term: int, priority: int, node_id: int, now_ms: int) -> None:
        """A CLAIM from another candidate."""
        if node_id == self.node_id or term < self.term:
            return
        if self.role == CANDIDATE and term > self.term:
            self._yield(term, now_ms)
            return
        if self.role == CANDIDATE and term == self.term:
            if _better(term, priority, node_id, self.term, self.priority, self.node_id):
                self._yield(term, now_ms)
            return
        if self.role == LEADER:
            if term > self.term:
                self._yield(term, now_ms)
            return
        # Follower: an election is under way; wait for its winner's TIME. A CLAIM at the term of the
        # leader it follows is no election after that leader, and not its liveness (decision FLC-4).
        if self.leader is not None and self._leader_term == term:
            return
        self.term = max(self.term, term)
        self.last_heartbeat_ms = now_ms

    def _yield(self, term: int, now_ms: int) -> None:
        self.term = term
        self.leader = None
        self._leader_term = None
        self.candidate_since_ms = None
        self.last_heartbeat_ms = now_ms  # give the winner a full timeout to beacon
        self._set_role(FOLLOWER, now_ms)

    # --- time passing ----------------------------------------------------------

    def tick(self, now_ms: int) -> Optional[Claim]:
        """Advance to ``now_ms``. Returns a CLAIM to send when this node stands for election."""
        if self.role == CANDIDATE:
            assert self.candidate_since_ms is not None
            if now_ms - self.candidate_since_ms >= self.election_timeout_ms:
                self.lead(self.term, now_ms)
            return None
        if self.role == FOLLOWER and self.mode == "auto" and self.capable:
            if self.last_heartbeat_ms is None:
                self.last_heartbeat_ms = now_ms
            silence = now_ms - self.last_heartbeat_ms
            if silence >= self.missed_beacons * self.liveness_interval:
                return self._stand(now_ms)
        return None

    @property
    def is_leader(self) -> bool:
        return self.role == LEADER
