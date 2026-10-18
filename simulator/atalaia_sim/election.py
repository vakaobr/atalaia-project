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
        self.last_heartbeat_ms: Optional[int] = None
        self.candidate_since_ms: Optional[int] = None
        self.history: list[tuple[int, str, int]] = []  # (t_ms, role, term)

    # --- state changes ---------------------------------------------------------

    def _set_role(self, role: str, now_ms: int) -> None:
        if role != self.role:
            self.role = role
            self.history.append((now_ms, role, self.term))

    def lead(self, term: int, now_ms: int) -> None:
        """Take the controller role with ``term`` (the first controller of a game)."""
        self.term = max(self.term, term)
        self.leader = self.node_id
        self.candidate_since_ms = None
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
        self._set_role(CANDIDATE, now_ms)
        return Claim(self.term, self.priority, self.node_id)

    # --- what we hear ----------------------------------------------------------

    def on_time(self, term: int, source: int, now_ms: int) -> bool:
        """A TIME beacon from ``source``. Returns False if it should be ignored (stale term)."""
        if source == self.node_id:
            return True
        if term < self.term:
            return False  # an old controller that has not stepped down yet
        if term == self.term and self.role == LEADER:
            # Two controllers with one term cannot happen through CLAIM; keep
            # the deterministic winner (lower node id) and let the other yield.
            if source > self.node_id:
                return False
        self.term = term
        self.leader = source
        self.last_heartbeat_ms = now_ms
        self.candidate_since_ms = None
        self._set_role(FOLLOWER, now_ms)
        return True

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
        # Follower: an election is under way; wait for its winner's TIME.
        self.term = max(self.term, term)
        self.last_heartbeat_ms = now_ms

    def _yield(self, term: int, now_ms: int) -> None:
        self.term = term
        self.leader = None
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
            if silence >= self.missed_beacons * self.beacon_interval:
                return self._stand(now_ms)
        return None

    @property
    def is_leader(self) -> bool:
        return self.role == LEADER
