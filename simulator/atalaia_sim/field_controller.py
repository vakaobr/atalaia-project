# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Field controller: TIME beacons, score merge, event log, CLAIM election.

The :class:`FieldController` sits on node 0 and drives a simulated game
through the :class:`RadioModel`.  It sends periodic TIME beacons,
merges conflict-free score counters from STATE messages, records events,
and handles CLAIM-based controller election (failover).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from .packet import (
    Header,
    claim_decode,
    claim_encode,
    cmd_encode,
    hello_decode,
    state_decode,
    time_encode,
)
from .protocol import MESSAGE_TYPES
from .radio_model import RadioModel

# Game states
GAME_WAITING = 0
GAME_RUNNING = 1
GAME_PAUSED = 2
GAME_ENDED = 3

_STATE_NAMES = {
    GAME_WAITING: "waiting",
    GAME_RUNNING: "running",
    GAME_PAUSED: "paused",
    GAME_ENDED: "ended",
}


@dataclass
class FieldNode:
    """A node the controller knows about."""

    node_id: int
    name: str
    role: str
    last_seen_ms: int = 0
    last_seq: int = 0
    epoch: int = 0
    score: dict[str, int] = field(default_factory=dict)


class FieldController:
    """Manages a multi-node game through the radio model."""

    def __init__(
        self,
        radio: RadioModel,
        game_id: int = 1,
        teams: Optional[list[str]] = None,
        beacon_interval_ms: int = 30_000,
    ) -> None:
        self.radio = radio
        self.game_id = game_id
        self.teams: list[str] = teams or []
        self.beacon_interval_ms = beacon_interval_ms

        # The controller is always node 0.
        self.node_id = 0
        self.radio.add_node(self.node_id)

        self.term = 1
        self.game_state: int = GAME_WAITING
        self.game_time_ms: int = 0
        self.duration_ms: int = 0
        self.nodes: dict[int, FieldNode] = {}
        self.event_log: list[dict[str, Any]] = []
        self.seq: int = 0
        self.last_beacon_ms: int = 0

        # Score aggregation: team_name -> counter_name -> max value
        self._scores: dict[str, dict[str, int]] = {t: {} for t in self.teams}

    # --- node management ------------------------------------------------------

    def register_node(self, node_id: int, name: str, role: str) -> None:
        """Register a known field node."""
        self.nodes[node_id] = FieldNode(node_id=node_id, name=name, role=role)
        self.radio.add_node(node_id)

    # --- game lifecycle -------------------------------------------------------

    def start_game(self, duration_ms: int = 0, now_ms: int = 0) -> None:
        """Start the game.  Sends a CMD to all nodes."""
        self.game_state = GAME_RUNNING
        self.duration_ms = duration_ms
        self.game_time_ms = 0
        self.last_beacon_ms = now_ms
        self._send_cmd(1, {"duration_ms": duration_ms}, now_ms=now_ms)  # cmd=1 start
        self.send_time_beacon(now_ms=now_ms)

    def pause_game(self, now_ms: int = 0) -> None:
        """Pause the game."""
        self.game_state = GAME_PAUSED
        self._send_cmd(2, now_ms=now_ms)  # cmd=2 pause

    def end_game(self, now_ms: int = 0) -> None:
        """End the game."""
        self.game_state = GAME_ENDED
        self._send_cmd(3, now_ms=now_ms)  # cmd=3 end

    # --- sending --------------------------------------------------------------

    def _next_seq(self) -> int:
        self.seq = (self.seq + 1) & 0xFFFF
        return self.seq

    def send_time_beacon(self, now_ms: int = 0) -> None:
        """Broadcast a TIME beacon."""
        payload = time_encode({
            "epoch": self.term,
            "game_time_ms": self.game_time_ms,
            "game_state": self.game_state,
            "term": self.term,
            "duration_ms": self.duration_ms,
        })
        self.radio.send(
            from_node=self.node_id,
            payload=payload,
            msg_type=MESSAGE_TYPES["TIME"],
            source=self.node_id,
            seq=self._next_seq(),
            priority=2,  # critical
            hop_limit=self.radio.config.max_hops,
            now_ms=now_ms,
        )
        self.last_beacon_ms = now_ms

    def send_cmd(
        self,
        cmd: int,
        params: Optional[dict[str, Any]] = None,
        dest: Optional[int] = None,
        now_ms: int = 0,
    ) -> None:
        """Send a CMD message (public API)."""
        self._send_cmd(cmd, params, dest, now_ms=now_ms)

    def _send_cmd(
        self,
        cmd: int,
        params: Optional[dict[str, Any]] = None,
        dest: Optional[int] = None,
        now_ms: int = 0,
    ) -> None:
        msg: dict[str, Any] = {"cmd": cmd}
        if params:
            msg["params"] = params
        if dest is not None:
            msg["dest"] = dest
        payload = cmd_encode(msg)
        self.radio.send(
            from_node=self.node_id,
            payload=payload,
            msg_type=MESSAGE_TYPES["CMD"],
            source=self.node_id,
            seq=self._next_seq(),
            priority=2,
            hop_limit=self.radio.config.max_hops,
            now_ms=now_ms,
        )

    # --- receiving ------------------------------------------------------------

    def on_packet(
        self,
        source_node: int,
        header: Header,
        payload: bytes,
    ) -> None:
        """Process a received packet at the controller."""
        msg_type = header.type

        if msg_type == MESSAGE_TYPES["STATE"]:
            self._on_state(source_node, header, payload)
        elif msg_type == MESSAGE_TYPES["HELLO"]:
            self._on_hello(source_node, header, payload)
        elif msg_type == MESSAGE_TYPES["CLAIM"]:
            self._on_claim(source_node, header, payload)
        # EVENT messages: log them
        elif msg_type == MESSAGE_TYPES["EVENT"]:
            self._on_event(source_node, header, payload)

    def _on_state(self, source_node: int, header: Header, payload: bytes) -> None:
        """Process a STATE message: update node info and merge scores."""
        try:
            state = state_decode(payload)
        except Exception:
            return
        node = self.nodes.get(source_node)
        if node is None:
            # Auto-register unknown nodes.
            node = FieldNode(
                node_id=source_node,
                name=f"node-{source_node}",
                role="unknown",
            )
            self.nodes[source_node] = node
        node.last_seen_ms = self._now_ms
        node.last_seq = header.seq
        if "counters" in state and isinstance(state["counters"], dict):
            self.merge_scores(source_node, state["counters"])

    def _on_hello(self, source_node: int, header: Header, payload: bytes) -> None:
        """Process a HELLO message: register or update the node."""
        try:
            hello = hello_decode(payload)
        except Exception:
            return
        name = hello.get("node_name", f"node-{source_node}")
        role = hello.get("role", "unknown")
        if source_node in self.nodes:
            self.nodes[source_node].name = str(name)
            self.nodes[source_node].role = str(role)
            self.nodes[source_node].last_seen_ms = self._now_ms
        else:
            self.register_node(source_node, str(name), str(role))
            self.nodes[source_node].last_seen_ms = self._now_ms

    def _on_claim(self, source_node: int, header: Header, payload: bytes) -> None:
        """Process a CLAIM message for controller election."""
        try:
            claim = claim_decode(payload)
        except Exception:
            return
        self.event_log.append({
            "t_ms": self._now_ms,
            "type": "claim",
            "source": source_node,
            "term": claim.get("term", 0),
            "candidate": claim.get("candidate", source_node),
        })

    def _on_event(self, source_node: int, header: Header, payload: bytes) -> None:
        """Process an EVENT message: add to the event log."""
        self.event_log.append({
            "t_ms": self._now_ms,
            "type": "event",
            "source": source_node,
            "seq": header.seq,
            "payload_len": len(payload),
        })

    # --- tick -----------------------------------------------------------------

    @property
    def _now_ms(self) -> int:
        return self.radio._now_ms

    def tick(self, now_ms: int) -> list[tuple[int, Header, bytes]]:
        """Advance time, deliver pending radio packets, auto-send beacons.

        Returns the radio model's delivery list so callers can inspect
        what was delivered this tick.
        """
        # Update game time if running.
        if self.game_state == GAME_RUNNING:
            elapsed = now_ms - (self.radio._now_ms if self.radio._now_ms > 0 else now_ms)
            if elapsed > 0:
                self.game_time_ms += elapsed

        # Deliver pending radio packets.
        deliveries = self.radio.tick(now_ms)

        # Process packets addressed to us.
        for dest_id, hdr, payload in deliveries:
            if dest_id == self.node_id:
                self.on_packet(hdr.source, hdr, payload)

        # Auto-send TIME beacon if interval has elapsed.
        if self.game_state == GAME_RUNNING:
            if now_ms - self.last_beacon_ms >= self.beacon_interval_ms:
                self.send_time_beacon(now_ms=now_ms)

        return deliveries

    # --- score merging --------------------------------------------------------

    def merge_scores(self, node_id: int, counters: dict[Any, Any]) -> None:
        """Merge scores by taking the maximum per counter (conflict-free).

        *counters* maps team names (or ids) to score values.
        """
        for key, value in counters.items():
            if not isinstance(value, int):
                continue
            team_name = str(key)
            if team_name not in self._scores:
                self._scores[team_name] = {}
            node_key = f"node-{node_id}"
            current = self._scores[team_name].get(node_key, 0)
            if value > current:
                self._scores[team_name][node_key] = value

    @property
    def total_scores(self) -> dict[str, int]:
        """Total score per team, summing the max from each node."""
        result: dict[str, int] = {}
        for team, node_scores in self._scores.items():
            result[team] = sum(node_scores.values())
        return result
