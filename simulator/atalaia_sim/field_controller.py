# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Field controller logic: TIME beacons, ACKs, score merge, event log, CLAIM election.

The :class:`FieldController` holds everything the controller decides about
the radio side of a game, independent of how packets travel:

- in the simulator it sends through the :class:`RadioModel`
  (:class:`RadioTransport`), and ``tick`` delivers the radio's packets;
- in the real field controller (``controller/``) it sends through the USB
  radio modem, and the modem's RX frames are fed to :meth:`on_packet`.

Both use this same class, so what the simulator tests is what runs on the
Raspberry Pi. Hooks (``on_event``, ``on_node``, ``on_scores``, ``on_role``)
let the host store and publish what happens.

Node health (decisions S19-9, FU1-1 to FU1-4): with ``node_offline_ms`` set, the
controller in charge logs ``node.online`` when it first hears a box and
``node.offline`` when a box it heard has been silent that long, at most one
link event per box every ``link_gap_ms`` (a flapping link reports where it
ended up, not every flap); with ``battery_low_pct`` set, it logs
``battery.low`` when a box's STATE or HELLO reports a level below it for
``BATTERY_GRACE_MS`` and the box has not sent its own, once per crossing
(``BATTERY_HYSTERESIS`` points above the threshold rearm it). These events
are about the box, so their node is the box's id; they never go on air.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol

from . import codec
from .election import LEADER, Claim, Election
from .packet import (
    Header,
    ack_encode,
    claim_decode,
    claim_encode,
    cmd_encode,
    hello_decode,
    state_decode,
    time_decode,
    time_encode,
    vf_ack,
)
from .protocol import MESSAGE_TYPES
from .radio_model import RadioModel
from .replay import FRESH, ReplayWindow
from .replay import counter as replay_counter

# Game states (TIME key 2).
GAME_WAITING = 0
GAME_RUNNING = 1
GAME_PAUSED = 2
GAME_ENDED = 3

# A state change (start, pause, resume) goes out as CMD + TIME at once and then as TIME alone
# again after each of these gaps (RFC 0001 Amendment 19, part 2): a TIME carries the game state
# and a box acts on it as on the CMD, so one frame lost in a quiet field (or a box that was in
# the middle of a frame of its own) is repaired in a second or two, not at the next 30 s beacon.
# 4 x about 90 ms of air in all; a new state change replaces the repeats still due.
STATE_REPEAT_GAPS_MS = (1_000, 1_500, 2_500, 5_000)  # +1.0, +2.5, +5.0, +10.0 s

STATE_NAMES = {
    GAME_WAITING: "waiting",
    GAME_RUNNING: "running",
    GAME_PAUSED: "paused",
    GAME_ENDED: "ended",
}
_STATE_NAMES = STATE_NAMES  # kept for older imports

# CMD opcodes (ADR-P2-3, RFC 0001).
CMD_START = 0
CMD_PAUSE = 1
CMD_RESUME = 2
CMD_END = 3
CMD_SET_OWNER = 4
CMD_MESSAGE = 5
CMD_RESET = 6
CMD_REBOOT = 7
# A command for the node's mode script (RFC 0001 Amendment 5): params name it.
CMD_MODE = 8
# A firmware update over Wi-Fi (RFC 0001 Amendment 6, protocol/firmware-update.md):
# params {"id", "version"}; the controller sends it only to boxes between games.
CMD_UPDATE = 9
# The I/O pod's settings (RFC 0001 Amendment 17, protocol/pod-config.md): params {"v", "rev", ...};
# the controller sends it to the node id of the phone a pod serves, and the pod's radio takes it.
CMD_POD = 10
CMD_OPCODES = {
    "start": CMD_START,
    "pause": CMD_PAUSE,
    "resume": CMD_RESUME,
    "end": CMD_END,
    "set_owner": CMD_SET_OWNER,
    "message": CMD_MESSAGE,
    "reset": CMD_RESET,
    "reboot": CMD_REBOOT,
    "mode": CMD_MODE,
    "update": CMD_UPDATE,
    "pod": CMD_POD,
}

PRIO_TELEMETRY = 0
PRIO_NORMAL = 1
PRIO_CRITICAL = 2

BROADCAST = 0xFFFF
# CMD params travel as a CBOR map with text keys; a box's C decoder turns
# them into JSON in a 128-byte buffer, so their JSON form must fit 127 bytes.
CMD_PARAMS_MAX = 127
# Flood copies and replays are refused by the per-source replay window (replay.py, RFC 0001
# Amendment 23): a packet already seen, or 64 or more counters below the source's highest, however
# long ago (this was a 60 s table; a recording played back after a minute got through).

# Node health (decisions FU1-1 to FU1-3).
HEALTH_EVENTS = ("node.online", "node.offline", "battery.low")
LINK_GAP_MS = 60_000      # at most one node.online/node.offline per box this often
BATTERY_GRACE_MS = 30_000  # a low level waits this long for the box's own battery.low
BATTERY_HYSTERESIS = 5     # points above the threshold that rearm battery.low
TIER_NAMES = {0: "full", 1: "reduced", 2: "proxy"}


class NotController(RuntimeError):
    """Raised when a command needs the controller role and this node is on standby."""


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
    owner_team: int = 0
    phase: int = 0
    game_time_ms: int = 0
    battery_pct: Optional[int] = None
    rssi: Optional[int] = None
    snr: Optional[int] = None
    hello: dict[str, Any] = field(default_factory=dict)
    # Health: heard in this run, the game time of the last packet, the link as the
    # last node.online/node.offline said it (None: neither yet) and when that was
    # logged (the controller's ms), and whether battery.low is logged for this crossing.
    heard: bool = False
    last_seen_game_ms: int = 0
    link: Optional[str] = None
    link_changed_ms: Optional[int] = None
    battery_low: bool = False
    battery_low_since: Optional[int] = None
    # Projected score (decision BSC-2): a STATE from this box was heard in this run.
    reported: bool = False
    # Ownership changes the box's own events announced since its last STATE: (game ms, team id,
    # 0 = nobody) in the box's game time. The projection follows them; every STATE clears them.
    changes: list[tuple[int, int]] = field(default_factory=list)

    def owner_name(self, teams: list[str]) -> Optional[str]:
        if 1 <= self.owner_team <= len(teams):
            return teams[self.owner_team - 1]
        return None


class Transport(Protocol):
    """How the controller's own packets leave: returns the seq used, or None if refused."""

    def send(self, msg_type: int, payload: bytes, *, priority: int, ack_req: bool,
             hop_limit: int, now_ms: int) -> Optional[int]: ...


class RadioTransport:
    """Sends through the simulator's RadioModel from one node."""

    def __init__(self, radio: RadioModel, node_id: int) -> None:
        self.radio = radio
        self.node_id = node_id
        self.seq = 0
        radio.add_node(node_id)

    def send(self, msg_type: int, payload: bytes, *, priority: int, ack_req: bool,
             hop_limit: int, now_ms: int) -> Optional[int]:
        self.seq = (self.seq + 1) & 0xFFFF
        self.radio.send(
            from_node=self.node_id,
            payload=payload,
            msg_type=msg_type,
            source=self.node_id,
            seq=self.seq,
            priority=priority,
            ack_req=ack_req,
            hop_limit=hop_limit,
            now_ms=now_ms,
        )
        return self.seq


class AckTracker:
    """Which packet seqs arrived from each (node, epoch), as ACK payloads.

    A box restarts its seq at 0 with every new epoch (reboot or seq wrap),
    so seqs are tracked per epoch. ``ack_seq`` is the highest seq received
    with every seq below it also received (0xFFFF when seq 0 is missing:
    "nothing contiguous yet"); ``ack_bitmap`` bit n says whether
    ``ack_seq + 1 + n`` arrived, for the next 256 seqs.

    A packet lost for good (a STATE is never sent again, an event's resend
    takes a new seq) would hold ``ack_seq`` back for ever, and 256 packets
    later the box's newest seq would be outside the bitmap and unACKable
    (decision SL-8). So every seq more than ``GAP_WINDOW`` below the highest
    one received counts as received. The Dart port (AckTracker in
    app/lib/controller/field_controller.dart) does the same;
    protocol/vectors/ack_tracker.json pins both.
    """

    #: A seq this far below the highest received is given up on. The box's
    #: outbox holds 32 entries resent every 3 s at most (3 s is the
    #: shortest gap of Amendment 13's backoff), so one still
    #: waiting is never this old; and 128 is half the bitmap, so the highest
    #: seq always stays inside it.
    GAP_WINDOW = 128

    def __init__(self) -> None:
        self._contig: dict[tuple[int, int], int] = {}
        self._above: dict[tuple[int, int], set[int]] = {}

    def record(self, node: int, epoch: int, seq: int) -> None:
        key = (node, epoch)
        contig = self._contig.get(key, -1)
        if seq <= contig:
            return
        above = self._above.setdefault(key, set())
        above.add(seq)
        floor = max(above) - self.GAP_WINDOW - 1
        if floor > contig:
            contig = floor
            above = {x for x in above if x > contig}
            self._above[key] = above
        while contig + 1 in above:
            contig += 1
            above.discard(contig)
        self._contig[key] = contig

    def contiguous(self, node: int, epoch: int) -> int:
        """Highest contiguous seq from 0, or -1."""
        return self._contig.get((node, epoch), -1)

    def ack_payload(self, node: int, epoch: int) -> dict[str, Any]:
        contig = self.contiguous(node, epoch)
        msg: dict[str, Any] = {"ack_node": node, "ack_seq": contig & 0xFFFF}
        above = self._above.get((node, epoch), set())
        bits = bytearray(32)
        for seq in above:
            n = seq - contig - 1
            if 0 <= n < 256:
                bits[n // 8] |= 1 << (n % 8)
        used = len(bits.rstrip(b"\0"))
        if used:
            msg["ack_bitmap"] = bytes(bits[:used])
        return msg

    def latest_epoch(self, node: int) -> Optional[int]:
        epochs = [e for (n, e) in self._contig if n == node]
        return max(epochs) if epochs else None


class FieldController:
    """The controller's side of a multi-node game."""

    def __init__(
        self,
        radio: Optional[RadioModel] = None,
        game_id: int = 1,
        teams: Optional[list[str]] = None,
        beacon_interval_ms: Optional[int] = None,
        *,
        node_id: int = 0,
        transport: Optional[Transport] = None,
        election: Optional[Election] = None,
        max_hops: Optional[int] = None,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if transport is None:
            if radio is None:
                raise ValueError("FieldController needs a radio model or a transport")
            transport = RadioTransport(radio, node_id)
        self.radio = radio
        self.transport = transport
        self.node_id = node_id
        self.game_id = game_id
        self.teams: list[str] = list(teams or [])
        if max_hops is None:
            max_hops = radio.config.max_hops if radio is not None else 2
        self.max_hops = max_hops
        if election is None:
            # A lone controller: in charge from the start, term 1.
            election = Election(node_id, priority=0)
            election.lead(1, 0)
        self.election = election
        self.beacon_interval_ms = (beacon_interval_ms if beacon_interval_ms is not None
                                   else election.beacon_interval)
        self._wall = wall_clock

        self.game_state: int = GAME_WAITING
        self.game_time_ms: int = 0
        self.duration_ms: int = 0
        self.nodes: dict[int, FieldNode] = {}
        self.event_log: list[dict[str, Any]] = []
        self.last_beacon_ms: int = 0
        self.state_repeat_gaps_ms: tuple[int, ...] = STATE_REPEAT_GAPS_MS
        self._repeats: list[int] = []  # when the TIMEs repeating the last state change are due
        self.state_repeats_sent = 0
        self._now: int = 0
        self._last_tick: Optional[int] = None
        self._role_seen = election.role
        self._event_seq = 0  # the controller's own events (score adjustments)
        # Node health (module docstring); 0 = off. The field controller turns both on.
        self.node_offline_ms = 0
        self.link_gap_ms = LINK_GAP_MS
        self.battery_low_pct = 0
        self.health_seq = 0  # seq of the health events this controller logs about boxes

        # Score aggregation: team name -> node key -> max value.
        self._scores: dict[str, dict[str, int]] = {t: {} for t in self.teams}
        # Penalties the boxes report in STATE (key 9, RFC 0001 Amendment 18): the same shape.
        self._lost: dict[str, dict[str, int]] = {t: {} for t in self.teams}
        self._adjust: dict[str, int] = {}
        # The mode's optional scoring contract (modes/README.md "Projected score", decision BSC-2):
        # (every in game ms, points) for the team that owns a box, or None = no projection.
        self.scoring_hold: Optional[tuple[int, int]] = None
        # How far the projection was from each box's next STATE (the bench's drift measure).
        self.projection_stats: dict[str, Any] = {"samples": 0, "off": 0, "max_abs": 0, "sum_abs": 0,
                                                 "last": None}
        self.on_drift: Optional[Callable[[dict[str, Any]], None]] = None

        self.acks = AckTracker()
        self._replay: dict[int, ReplayWindow] = {}  # source -> its replay window
        self.replays_refused = 0  # authenticated packets the windows refused (copies and replays)
        self._events_seen: set[tuple[int, int, int, str]] = set()

        # Hooks for the host (all optional).
        self.on_event: Optional[Callable[[dict[str, Any]], None]] = None
        self.on_node: Optional[Callable[[FieldNode, str], None]] = None
        self.on_scores: Optional[Callable[[dict[str, int]], None]] = None
        self.on_role: Optional[Callable[[str, int], None]] = None

    # --- properties -----------------------------------------------------------

    @property
    def term(self) -> int:
        return self.election.term

    @property
    def seq(self) -> int:
        return int(getattr(self.transport, "seq", 0))

    @property
    def is_controller(self) -> bool:
        return self.election.is_leader

    @property
    def _now_ms(self) -> int:
        return self._now

    # --- node management ------------------------------------------------------

    def register_node(self, node_id: int, name: str, role: str) -> FieldNode:
        """Register a known field node."""
        node = self.nodes.get(node_id)
        if node is None:
            node = FieldNode(node_id=node_id, name=name, role=role)
            self.nodes[node_id] = node
        else:
            node.name, node.role = name, role
        if self.radio is not None:
            self.radio.add_node(node_id)
        return node

    def _node(self, node_id: int) -> FieldNode:
        node = self.nodes.get(node_id)
        if node is None:
            node = self.register_node(node_id, f"node-{node_id}", "unknown")
        return node

    def team_name(self, team_id: int) -> Optional[str]:
        if 1 <= team_id <= len(self.teams):
            return self.teams[team_id - 1]
        return None

    # --- game lifecycle -------------------------------------------------------

    def _require_controller(self) -> None:
        if not self.election.is_leader:
            raise NotController(f"node {self.node_id} is not the controller (role {self.election.role})")

    def _advance_time(self, now_ms: int) -> None:
        if self.game_state == GAME_RUNNING and self._last_tick is not None and now_ms > self._last_tick:
            self.game_time_ms += now_ms - self._last_tick
        self._last_tick = now_ms
        self._now = max(self._now, now_ms)

    def start_game(self, duration_ms: int = 0, now_ms: int = 0) -> None:
        """Start the game: CMD start to every node, then a TIME beacon."""
        self._require_controller()
        self.game_state = GAME_RUNNING
        self.duration_ms = duration_ms
        self.game_time_ms = 0
        self._last_tick = now_ms
        self._now = max(self._now, now_ms)
        self.last_beacon_ms = now_ms
        self._send_cmd(CMD_START, now_ms=now_ms)
        self.send_time_beacon(now_ms=now_ms)
        self._repeat_state(now_ms)

    def pause_game(self, now_ms: int = 0, reason: Optional[str] = None) -> None:
        """Pause the game: the game clock stops."""
        self._require_controller()
        self._advance_time(now_ms)
        self.game_state = GAME_PAUSED
        self._send_cmd(CMD_PAUSE, {"reason": reason} if reason else None, now_ms=now_ms)
        self.send_time_beacon(now_ms=now_ms)
        self._repeat_state(now_ms)

    def resume_game(self, now_ms: int = 0) -> None:
        """Resume a paused game."""
        self._require_controller()
        self._advance_time(now_ms)
        self.game_state = GAME_RUNNING
        self._send_cmd(CMD_RESUME, now_ms=now_ms)
        self.send_time_beacon(now_ms=now_ms)
        self._repeat_state(now_ms)

    def end_game(self, now_ms: int = 0, reason: Optional[str] = None) -> None:
        """End the game."""
        self._require_controller()
        self._advance_time(now_ms)
        self.game_state = GAME_ENDED
        self._send_cmd(CMD_END, {"reason": reason} if reason else None, now_ms=now_ms)
        self.send_time_beacon(now_ms=now_ms)
        self._repeats = []  # the end is repeated by GAME_OVER (field frames), not by TIME

    def _repeat_state(self, now_ms: int) -> None:
        """Schedules the TIME repeats of a state change (the ones of an earlier change go)."""
        due, at = [], now_ms
        for gap in self.state_repeat_gaps_ms:
            at += gap
            due.append(at)
        self._repeats = due

    # --- sending --------------------------------------------------------------

    def _send(self, msg_type: str, payload: bytes, priority: int, now_ms: int,
              ack_req: bool = False) -> Optional[int]:
        return self.transport.send(MESSAGE_TYPES[msg_type], payload, priority=priority,
                                   ack_req=ack_req, hop_limit=self.max_hops, now_ms=now_ms)

    def send_time_beacon(self, now_ms: int = 0) -> Optional[int]:
        """Broadcast a TIME beacon (the controller heartbeat)."""
        payload = time_encode({
            "game_time_ms": self.game_time_ms & 0xFFFFFFFF,
            "game_state": self.game_state,
            "duration_ms": self.duration_ms & 0xFFFFFFFF,
            "wall_s": int(self._wall()) & 0xFFFFFFFF,
            "term": self.election.term & 0xFFFFFFFF,
        })
        self.last_beacon_ms = now_ms
        return self._send("TIME", payload, PRIO_CRITICAL, now_ms)

    def send_cmd(
        self,
        cmd: int | str,
        params: Optional[dict[str, Any]] = None,
        dest: Optional[int] = None,
        now_ms: int = 0,
    ) -> Optional[int]:
        """Send a CMD (opcode or name; dest None = every node). Returns the packet seq.

        params is a JSON-like object with text keys; its compact JSON form
        must fit in 127 bytes (the boxes' buffer).
        """
        self._require_controller()
        if isinstance(cmd, str) and cmd not in CMD_OPCODES:
            raise ValueError(f"unknown command {cmd!r}")
        opcode = CMD_OPCODES[cmd] if isinstance(cmd, str) else int(cmd)
        if not 0 <= opcode <= CMD_POD:
            raise ValueError(f"unknown command opcode {opcode}")
        return self._send_cmd(opcode, params, dest, now_ms=now_ms)

    def _send_cmd(
        self,
        cmd: int,
        params: Optional[dict[Any, Any]] = None,
        dest: Optional[int] = None,
        now_ms: int = 0,
    ) -> Optional[int]:
        msg: dict[str, Any] = {"cmd": cmd}
        if params:
            text = json.dumps(params, separators=(",", ":"), ensure_ascii=False)
            if len(text.encode()) > CMD_PARAMS_MAX:
                raise ValueError(f"command parameters are {len(text.encode())} bytes; "
                                 f"at most {CMD_PARAMS_MAX} fit in a CMD")
            if not all(isinstance(k, str) for k in params):
                raise ValueError("command parameter names must be text")
            msg["params"] = dict(params)
        if dest is not None and dest != BROADCAST:
            msg["dest"] = dest
        return self._send("CMD", cmd_encode(msg), PRIO_CRITICAL, now_ms)

    def _send_ack(self, node_id: int, epoch: int, now_ms: int) -> None:
        self._send("ACK", ack_encode(self.acks.ack_payload(node_id, epoch)), PRIO_NORMAL, now_ms)

    def _send_claim(self, claim: Claim, now_ms: int) -> None:
        last_ack: dict[int, int] = {}
        for node_id in self.nodes:
            epoch = self.acks.latest_epoch(node_id)
            if epoch is not None and self.acks.contiguous(node_id, epoch) >= 0:
                last_ack[node_id] = self.acks.contiguous(node_id, epoch)
        msg: dict[str, Any] = {"term": claim.term, "priority": claim.priority, "node_id": claim.node_id}
        if last_ack:
            msg["last_ack_seq"] = last_ack
        self.event_log.append({"t_ms": now_ms, "type": "claim_sent", "term": claim.term,
                               "priority": claim.priority})
        self._send("CLAIM", claim_encode(msg), PRIO_CRITICAL, now_ms)

    def promote(self, now_ms: int) -> None:
        """Manual failover: stand for election now (the GM's "promote" button)."""
        self._send_claim(self.election.promote(now_ms), now_ms)
        self._check_role(now_ms)

    # --- receiving ------------------------------------------------------------

    def on_packet(
        self,
        source_node: int,
        header: Header,
        payload: bytes,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        """Process one decrypted packet. meta may carry epoch, rssi and snr (from the modem)."""
        meta = meta or {}
        epoch = int(meta.get("epoch", 0))
        window = self._replay.setdefault(header.source, ReplayWindow())
        if window.accept(replay_counter(epoch, header.seq)) != FRESH:
            self.replays_refused += 1
            return  # a flood copy of a packet already handled, or a recording played back
        msg_type = header.type

        if msg_type == MESSAGE_TYPES["TIME"]:
            self._on_time(source_node, payload)
            return
        if msg_type == MESSAGE_TYPES["CLAIM"]:
            self._on_claim(source_node, payload)
            return

        self.acks.record(source_node, epoch, header.seq)
        node = self._node(source_node)
        node.last_seen_ms = self._now
        node.last_seen_game_ms = self.game_time_ms
        node.heard = True
        node.last_seq = header.seq
        node.epoch = epoch
        if "rssi" in meta:
            node.rssi = meta["rssi"]
        if "snr" in meta:
            node.snr = meta["snr"]

        if msg_type == MESSAGE_TYPES["STATE"]:
            self._on_state(node, payload)
        elif msg_type == MESSAGE_TYPES["HELLO"]:
            self._on_hello(node, payload)
        elif msg_type == MESSAGE_TYPES["EVENT"]:
            self._on_event(node, header, payload, epoch)

        if vf_ack(header.version_flags) and self.election.is_leader:
            self._send_ack(source_node, epoch, self._now)
        self._check_health(node, self._now)

    def _on_state(self, node: FieldNode, payload: bytes) -> None:
        """STATE: node snapshot and score counters (merged by maximum)."""
        try:
            state = state_decode(payload)
        except Exception:
            return
        drift_before = self._projection_before(node) if self.scoring_hold else None
        for name in ("owner_team", "phase", "game_time_ms"):
            if isinstance(state.get(name), int):
                setattr(node, name, state[name])
        node.reported = True
        node.changes.clear()  # the STATE is the authority: it replaces what the events said
        if isinstance(state.get("battery_pct"), int):
            node.battery_pct = state["battery_pct"]
        if isinstance(state.get("rssi"), int):
            node.rssi = state["rssi"]
        counters = state.get("counters")
        if isinstance(counters, dict):
            self.merge_scores(node.node_id, counters)
        lost = state.get("lost")
        if isinstance(lost, dict):
            self.merge_lost(node.node_id, lost)
        if drift_before is not None:
            self._record_drift(node, drift_before)
        if self.on_node:
            self.on_node(node, "state")

    def _on_hello(self, node: FieldNode, payload: bytes) -> None:
        """HELLO: register or update the node."""
        try:
            hello = hello_decode(payload)
        except Exception:
            return
        node.hello = hello
        node.name = str(hello.get("node_name", node.name))
        node.role = str(hello.get("role", node.role))
        if isinstance(hello.get("battery_pct"), int):
            node.battery_pct = hello["battery_pct"]
        if self.on_node:
            self.on_node(node, "hello")

    def _on_event(self, node: FieldNode, header: Header, payload: bytes, epoch: int) -> None:
        """EVENT: decode, drop replays already logged, record."""
        entry: dict[str, Any] = {
            "t_ms": self._now,
            "type": "event",
            "source": node.node_id,
            "seq": header.seq,
            "payload_len": len(payload),
            "epoch": epoch,
        }
        try:
            ev = codec.decode_event(payload)
        except Exception as exc:
            entry["error"] = str(exc)
            self.event_log.append(entry)
            return
        # A box's event seq restarts at 1 after a reboot, so the event's own
        # identity is (node, seq, game time, type); replays match it exactly.
        ident = (node.node_id, int(ev["seq"]), int(ev["t"]), str(ev["type"]))
        if ident in self._events_seen:
            return
        self._events_seen.add(ident)
        record = {
            "node": node.node_id,
            "seq": int(ev["seq"]),
            "t": int(ev["t"]),
            "type": str(ev["type"]),
            "team": self.team_name(int(ev.get("team") or 0)),
            "team_id": int(ev.get("team") or 0),
            "squad": int(ev.get("squad") or 0),
            "prio": ev.get("prio", "normal"),
            "data": ev.get("data") or {},
            "epoch": epoch,
            "pkt_seq": header.seq,
            "received_ms": self._now,
        }
        entry["event"] = record
        self.event_log.append(entry)
        if record["type"] in ("zone.captured", "zone.neutralized"):
            self._note_owner_change(node, record)
        if record["type"] == "battery.low":
            node.battery_low = True  # the box spoke for itself: no second one from here
            node.battery_low_since = None
        if self.on_event:
            self.on_event(record)

    def _on_time(self, source: int, payload: bytes) -> None:
        """TIME from another controller: follow it if its term is current."""
        try:
            beacon = time_decode(payload)
        except Exception:
            return
        term = int(beacon.get("term", 0))
        if not self.election.on_time(term, source, self._now):
            return
        # On standby, mirror the game clock so a takeover continues it.
        if isinstance(beacon.get("game_state"), int):
            self.game_state = beacon["game_state"]
        if isinstance(beacon.get("game_time_ms"), int):
            self.game_time_ms = beacon["game_time_ms"]
            self._last_tick = self._now
        if isinstance(beacon.get("duration_ms"), int):
            self.duration_ms = beacon["duration_ms"]
        self._check_role(self._now)

    def _on_claim(self, source: int, payload: bytes) -> None:
        """CLAIM from a candidate."""
        try:
            claim = claim_decode(payload)
        except Exception:
            return
        term = int(claim.get("term", 0))
        priority = int(claim.get("priority", 0))
        candidate = int(claim.get("node_id", source))
        self.event_log.append({
            "t_ms": self._now,
            "type": "claim",
            "source": source,
            "term": term,
            "priority": priority,
            "node_id": candidate,
        })
        self.election.on_claim(term, priority, candidate, self._now)
        self._check_role(self._now)

    def _check_role(self, now_ms: int) -> None:
        role = self.election.role
        if role == self._role_seen:
            return
        self._role_seen = role
        self.event_log.append({"t_ms": now_ms, "type": "role", "role": role, "term": self.election.term})
        if role == LEADER:
            # Took over: announce the new term at once (nodes follow the highest term).
            self._last_tick = now_ms
            self.send_time_beacon(now_ms)
        if self.on_role:
            self.on_role(role, self.election.term)

    # --- tick -----------------------------------------------------------------

    def tick(
        self,
        now_ms: int,
        deliveries: Optional[list[tuple[int, Header, bytes]]] = None,
    ) -> list[tuple[int, Header, bytes]]:
        """Advance to now_ms: deliver packets, run the election, send due beacons.

        With a RadioModel and no ``deliveries``, the radio is ticked here.
        When several controllers share one RadioModel, tick the radio once
        and pass its deliveries to each controller.
        """
        self._advance_time(now_ms)
        if deliveries is None:
            deliveries = self.radio.tick(now_ms) if self.radio is not None else []
        for dest_id, hdr, payload in deliveries:
            if dest_id == self.node_id:
                self.on_packet(hdr.source, hdr, payload)

        claim = self.election.tick(now_ms)
        if claim is not None:
            self._send_claim(claim, now_ms)
        self._check_role(now_ms)

        if self.election.is_leader and self.game_state in (GAME_RUNNING, GAME_PAUSED):
            if self._repeats and now_ms >= self._repeats[0]:
                # One TIME for every repeat that is due (a late tick does not send a burst).
                self._repeats = [t for t in self._repeats if t > now_ms]
                self.state_repeats_sent += 1
                self.send_time_beacon(now_ms=now_ms)
            elif now_ms - self.last_beacon_ms >= self.beacon_interval_ms:
                self.send_time_beacon(now_ms=now_ms)
        else:
            self._repeats = []
        for node in list(self.nodes.values()):
            self._check_health(node, now_ms)
        return deliveries

    # --- score merging --------------------------------------------------------

    def merge_scores(self, node_id: int, counters: dict[Any, Any]) -> None:
        """Merge scores by taking the maximum per counter (conflict-free).

        *counters* maps team ids (as STATE carries them) or team names to values.
        """
        self.merge_counters(f"node-{node_id}", counters)

    def merge_counters(self, node_key: str, counters: dict[Any, Any]) -> None:
        """Like merge_scores, for any counter source: a node ("node-ID") or a run of the
        controller's field script ("field-N"), whose points never travel in STATE."""
        if self._merge_max(self._scores, node_key, counters) and self.on_scores:
            self.on_scores(self.total_scores)

    def merge_lost(self, node_id: int, lost: dict[Any, Any]) -> None:
        """The points a node lost to penalties (STATE key 9), merged by maximum like the gains and
        subtracted in total_scores. A box that never sends the key (an older firmware) loses none."""
        if self._merge_max(self._lost, f"node-{node_id}", lost) and self.on_scores:
            self.on_scores(self.total_scores)

    def _merge_max(self, table: dict[str, dict[str, int]], node_key: str,
                   counters: dict[Any, Any]) -> bool:
        changed = False
        for key, value in counters.items():
            if not isinstance(value, int) or isinstance(value, bool):
                continue
            team_name = self.team_name(key) if isinstance(key, int) else None
            team_name = team_name or str(key)
            per_node = table.setdefault(team_name, {})
            if value > per_node.get(node_key, 0):
                per_node[node_key] = value
                changed = True
        return changed

    # --- projected score (decision BSC-2) -------------------------------------

    def _note_owner_change(self, node: FieldNode, record: dict[str, Any]) -> None:
        """A zone.captured (or zone.neutralized) from a box: the projection follows it until the
        box's next STATE (decision BSC-4). Its game time `t` is the box's own, like the STATE's. An
        event not newer than the box's last STATE is already in that STATE and changes nothing; one
        dated after the controller's own game time counts from now. `previous_team` is not used:
        the old owner is whoever the last STATE (or the event before) said."""
        if not node.reported or self.scoring_hold is None:
            return
        t = record.get("t")
        if not isinstance(t, int) or isinstance(t, bool) or t <= node.game_time_ms:
            return
        team = int(record.get("team_id") or 0) if record["type"] == "zone.captured" else 0
        if not 0 <= team <= len(self.teams):
            return
        if node.changes and t < node.changes[-1][0]:
            return  # out of order: keep the later one
        node.changes.append((min(t, max(self.game_time_ms, node.game_time_ms)), team))
        del node.changes[:-8]  # a bounded list: the STATE soon says it all

    def _projected_ticks(self, node: FieldNode) -> dict[int, int]:
        """Scoring ticks of the mode that happened on this box since its last STATE, by game time,
        per owner (team id): the boundaries k x every between the box's own report time and the
        controller's game time, split at the ownership changes its events announced since (the
        old owner's ticks up to the change, the new owner's after it). Empty unless the game runs,
        the box is online, it reported and it is running."""
        if (self.scoring_hold is None or self.game_state != GAME_RUNNING or not node.reported
                or node.phase != GAME_RUNNING or node.link == "offline"):
            return {}
        every = self.scoring_hold[0]
        out: dict[int, int] = {}
        start, owner = node.game_time_ms, node.owner_team
        for when, team in [*node.changes, (self.game_time_ms, 0)]:
            when = max(start, min(when, self.game_time_ms))
            ticks = when // every - start // every
            if ticks > 0 and 1 <= owner <= len(self.teams):
                out[owner] = out.get(owner, 0) + ticks
            start, owner = when, team
        return out

    def _ticks_since_report(self, node: FieldNode) -> int:
        """The ticks the box's owner at its last STATE made since it (the drift measure's side)."""
        return self._projected_ticks(node).get(node.owner_team, 0)

    def projected_gains(self) -> dict[str, int]:
        """Points each team has probably made since its boxes' last STATEs: every box that holds
        for a team adds `points` per tick boundary crossed since its report, to whoever held it at
        the time. Display only."""
        out: dict[str, int] = {}
        if self.scoring_hold is None:
            return out
        points = self.scoring_hold[1]
        for node in self.nodes.values():
            for team_id, ticks in self._projected_ticks(node).items():
                team = self.teams[team_id - 1]
                out[team] = out.get(team, 0) + ticks * points
        return out

    def projected_scores(self) -> Optional[dict[str, int]]:
        """The totals with the projection added, or None when the mode does not opt in. The stored
        totals, score.delta and the final result never use it: every STATE replaces it."""
        if self.scoring_hold is None:
            return None
        totals = self.total_scores
        for team, gain in self.projected_gains().items():
            totals[team] = totals.get(team, 0) + gain
        return totals

    def _projection_before(self, node: FieldNode) -> Optional[dict[str, Any]]:
        """What this box's projection said just before its STATE (None: nothing to compare)."""
        if not node.reported or self.game_state != GAME_RUNNING:
            return None
        team = node.owner_name(self.teams)
        if team is None:
            return None
        return {"team": team, "reported": self._scores.get(team, {}).get(f"node-{node.node_id}", 0),
                "ticks": self._ticks_since_report(node),
                "age_ms": max(0, self.game_time_ms - node.game_time_ms)}

    def _record_drift(self, node: FieldNode, before: dict[str, Any]) -> None:
        """The projection against what the box really said: projected = its old report plus the
        ticks since; reported = its new counter for the team. Zero is a perfect projection."""
        assert self.scoring_hold is not None
        team = before["team"]
        projected = before["reported"] + before["ticks"] * self.scoring_hold[1]
        reported = self._scores.get(team, {}).get(f"node-{node.node_id}", 0)
        drift = projected - reported
        stats = self.projection_stats
        stats["samples"] += 1
        stats["off"] += 1 if drift else 0
        stats["max_abs"] = max(stats["max_abs"], abs(drift))
        stats["sum_abs"] += abs(drift)
        stats["last"] = {"node": node.node_id, "team": team, "projected": projected,
                         "reported": reported, "drift": drift, "age_ms": before["age_ms"]}
        if self.on_drift:
            self.on_drift(dict(stats["last"]))

    def controller_event(self, type_: str, data: Optional[dict[str, Any]] = None,
                         team: Optional[str] = None, prio: str = "normal") -> dict[str, Any]:
        """Logs an event the controller itself originates (GM actions, field scripts)."""
        self._event_seq = (self._event_seq % 0xFFFF) + 1
        team_id = self.teams.index(team) + 1 if team in self.teams else 0
        record = {
            "node": self.node_id,
            "seq": self._event_seq,
            "t": self.game_time_ms,
            "type": type_,
            "team": team if team_id else None,
            "team_id": team_id,
            "squad": 0,
            "prio": prio,
            "data": dict(data or {}),
            "epoch": None,
            "pkt_seq": None,
            "received_ms": self._now,
        }
        self.event_log.append({"t_ms": self._now, "type": "event", "source": self.node_id,
                               "event": record})
        if self.on_event:
            self.on_event(record)
        return record

    # --- node health ----------------------------------------------------------

    def _check_health(self, node: FieldNode, now_ms: int) -> None:
        """node.online/node.offline and battery.low for one box (module docstring)."""
        if not self.election.is_leader or self.game_state == GAME_ENDED:
            return
        # A box restored as online after a restart and not heard since counts from then.
        since = node.last_seen_ms if node.heard else node.link_changed_ms if node.link == "online" else None
        if self.node_offline_ms > 0 and since is not None:
            want = "online" if now_ms - since < self.node_offline_ms else "offline"
            if want != node.link and (node.link_changed_ms is None
                                      or now_ms - node.link_changed_ms >= self.link_gap_ms):
                if want == "online":
                    hello = node.hello
                    data: dict[str, Any] = {}
                    if isinstance(hello.get("fw_version"), str):
                        data["fw"] = hello["fw_version"]
                    if hello.get("tier") in TIER_NAMES:
                        data["tier"] = TIER_NAMES[hello["tier"]]
                else:
                    data = {"last_seen": node.last_seen_game_ms}
                node.link, node.link_changed_ms = want, now_ms
                self.node_event(node.node_id, f"node.{want}", data)
                if self.on_node:
                    self.on_node(node, want)
        pct = node.battery_pct
        if self.battery_low_pct > 0 and isinstance(pct, int) and 0 <= pct <= 100:
            if pct >= self.battery_low_pct + BATTERY_HYSTERESIS:
                node.battery_low, node.battery_low_since = False, None
            elif pct >= self.battery_low_pct or node.battery_low:
                node.battery_low_since = None
            elif node.battery_low_since is None:
                node.battery_low_since = now_ms
            elif now_ms - node.battery_low_since >= BATTERY_GRACE_MS:
                node.battery_low, node.battery_low_since = True, None
                self.node_event(node.node_id, "battery.low", {"percent": pct})

    def node_event(self, node_id: int, type_: str, data: Optional[dict[str, Any]] = None,
                   prio: str = "telemetry") -> dict[str, Any]:
        """Logs an event the controller originates about a box: its node is the box's id,
        its seq this controller's own count of such events (``health_seq``, which the host
        continues after a restart), and it has no epoch (it never went on air)."""
        self.health_seq = (self.health_seq % 0xFFFF) + 1
        record = {
            "node": node_id,
            "seq": self.health_seq,
            "t": self.game_time_ms,
            "type": type_,
            "team": None,
            "team_id": 0,
            "squad": 0,
            "prio": prio,
            "data": dict(data or {}),
            "epoch": None,
            "pkt_seq": None,
            "received_ms": self._now,
            "origin": "controller",
        }
        self.event_log.append({"t_ms": self._now, "type": "event", "source": self.node_id,
                               "event": record})
        if self.on_event:
            self.on_event(record)
        return record

    def adjust_score(self, team: str, amount: int, reason: str = "", now_ms: Optional[int] = None
                     ) -> dict[str, Any]:
        """A GM's manual adjustment, logged as a score.delta event from the controller."""
        if now_ms is not None:
            self._advance_time(now_ms)
        self._adjust[team] = self._adjust.get(team, 0) + int(amount)
        record = self.controller_event("score.delta", {"team": team, "amount": int(amount),
                                                       "reason": reason}, team=team)
        if self.on_scores:
            self.on_scores(self.total_scores)
        return record

    def restore_adjustments(self, adjustments: dict[str, int]) -> None:
        """Puts back GM adjustments (after a controller restart)."""
        self._adjust = dict(adjustments)

    @property
    def total_scores(self) -> dict[str, int]:
        """Total per team: the max gained reported by each node, summed, minus the max lost the
        boxes reported (their penalties), plus GM adjustments."""
        result: dict[str, int] = {}
        for team, node_scores in self._scores.items():
            result[team] = sum(node_scores.values())
        for team, node_lost in self._lost.items():
            result[team] = result.get(team, 0) - sum(node_lost.values())
        for team, amount in self._adjust.items():
            result[team] = result.get(team, 0) + amount
        return result
