# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A simulated game: virtual nodes running one mode on a virtual clock."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from typing import TYPE_CHECKING

from . import codec
from .core import Command, Core, Emitted, FieldOps, Node
from .mode import COMMAND_NAME, Mode
from .protocol import MESSAGE_TYPES, RF_PAYLOAD_MAX

if TYPE_CHECKING:
    from .radio_model import RadioModel

# While a team holds an input, shells emit team_input.hold at this interval
# with the time held so far (see modes/README.md).
HOLD_STEP_MS = 250

CONTROLLER = "controller"
# With a field script, time moves in steps this long, so the controller's
# script sees the nodes' events close to when they happened.
FIELD_STEP_MS = 100
# field.send() commands a node understands, as the input events a Field Box
# turns them into (decision E7). "mode" is a mode command (CMD opcode 8, RFC 0001
# Amendment 5): its params carry the command's name, and the node's script gets
# them as cmd.mode.
FIELD_COMMANDS = {"set_owner": "cmd.set_owner", "message": "gm.message", "mode": "cmd.mode"}
# Positions never travel as events (decisions P4R6, P4R25): an event whose data holds one of
# these keys, at any depth, is a problem. The same list as the sync's (protocol/sync.md).
COORDINATE_KEYS = frozenset({"lat", "lon", "lng", "latitude", "longitude", "alt", "altitude", "position",
                             "positions", "gps", "coords", "coordinates", "x", "y"})
# What a VIP's position report gives field.lua (position.fix): the controller's src values.
POSITION_SOURCES = ("gps", "ble")


def coordinate_keys(data: Any) -> list[str]:
    """The position-like keys anywhere in an event's data."""
    found: list[str] = []
    if isinstance(data, dict):
        for k, v in data.items():
            if k in COORDINATE_KEYS:
                found.append(k)
            found += coordinate_keys(v)
    elif isinstance(data, list):
        for v in data:
            found += coordinate_keys(v)
    return found


class SimError(Exception):
    pass


@dataclass
class LogEntry:
    t_ms: int
    node: str
    node_id: int
    seq: int
    type: str
    team: Optional[str]
    prio: str
    data: dict[str, Any]
    wire_bytes: Optional[int] = None  # size of the CBOR payload on LoRa

    def describe(self) -> str:
        team = f" [{self.team}]" if self.team else ""
        data = f" {self.data}" if self.data else ""
        return f"{self.t_ms / 1000:9.3f}s  {self.node:<12} {self.type}{team}{data}"


@dataclass
class VirtualNode:
    name: str
    role: str
    runtime: Node
    commands: list[Command] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    # The last hardware input the shell sent: t_ms, type, data, and whether
    # the node accepted it (it refuses inputs while paused or not running).
    last_input: Optional[dict[str, Any]] = None
    # The parameters this node runs with: its role's part of the game's (its join's).
    params: dict[str, Any] = field(default_factory=dict)

    def last_command(self, target: str, method: str) -> Optional[Command]:
        for cmd in reversed(self.commands):
            if cmd.target == target and cmd.method == method:
                return cmd
        return None


class Simulation:
    def __init__(
        self,
        core: Core,
        mode: Mode,
        nodes: dict[str, str],
        teams: list[str],
        params: dict[str, Any],
        seed: int = 1,
        mem_limit: int = 0,
        instr_limit: int = 0,
        radio: Optional["RadioModel"] = None,
        game_id: int = 1,
        game_key: Optional[bytes] = None,
    ):
        self.core = core
        self.mode = mode
        # The game's id and 16-byte key, as a join gives them to a box: player tags
        # (protocol/nfc-tag.md) are signed with them. The default key is fixed per seed.
        self.game_id = game_id
        self.game_key = game_key or hashlib.sha256(b"atalaia-sim-game-key:%d" % seed).digest()[:16]
        self.teams = list(teams)
        self.params = params
        self.time_ms = 0
        self._log: list[LogEntry] = []
        self._controller_seq = 0
        # Events that break protocol/schema/events.yaml or would not fit in a
        # LoRa packet. They are collected here because the C core calls
        # _record, and exceptions cannot cross that boundary.
        self.problems: list[str] = []
        self.nodes: dict[str, VirtualNode] = {}
        # Optional radio model for field-network simulation.
        self.radio: Optional["RadioModel"] = radio
        self._pending: list[tuple[int, str, bytes]] = []  # (deliver_at_ms, dest_node, data)
        # The mode's field.lua (if any) runs as the controller would run it
        # (ADR-P2-14): node events reach it, field.send reaches the nodes.
        self.field: Optional[Node] = None
        self.field_logs: list[str] = []
        self.field_commands: list[tuple[int, str, str, dict[str, Any]]] = []  # (t, node, cmd, params)
        self.owners: dict[int, Optional[str]] = {}  # node id -> team, as box STATE reports it
        self._to_field: list[tuple[int, str, dict[str, Any]]] = []
        self._to_nodes: list[tuple[str, str, dict[str, Any]]] = []
        self._field_end: Optional[tuple[int, dict[str, Any]]] = None  # (t_ms, game.end data)
        self._ended = False
        # Nodes out of the controller's reach (set_reachable): their events wait for the
        # link to come back, as a box's retries would, and commands to them are lost.
        self._unreachable: set[str] = set()
        self._held: list[tuple[str, int, str, dict[str, Any]]] = []

        for node_id, (name, role) in enumerate(nodes.items(), start=1):
            if role not in mode.roles:
                raise SimError(f"node '{name}': mode {mode.id} has no role '{role}'")
            # A node runs what its role runs, with that part's parameters, as its join
            # gives them (a role package's roles run the package alone, modes/README.md).
            vnode = VirtualNode(name=name, role=role, runtime=None,  # type: ignore[arg-type]
                                params=mode.params_for(role, params))
            vnode.runtime = Node(
                core,
                node_id=node_id,
                game_seed=seed,
                teams=self.teams,
                params=vnode.params,
                source=mode.node_script_for(role),
                chunk_name=mode.chunk_name_for(role),
                mem_limit=mem_limit,
                instr_limit=instr_limit,
                on_event=lambda ev, n=vnode: self._record(n, ev),
                on_command=vnode.commands.append,
                on_log=vnode.logs.append,
            )
            self.nodes[name] = vnode
            if not vnode.runtime.loaded:
                raise SimError(f"node '{name}' failed to load {mode.id}: {vnode.runtime.last_error}")
        if mode.field_script is not None:
            ops = FieldOps(nodes=self._field_nodes, owner=self.owners.get, send=self._field_send)
            self.field = Node(core, 0, seed, self.teams, params, mode.field_script,
                              f"@{mode.path.name}/field.lua", mem_limit=mem_limit,
                              instr_limit=instr_limit, on_event=self._record_field,
                              on_log=self.field_logs.append, field_ops=ops)
            if not self.field.loaded:
                raise SimError(f"field.lua of {mode.id} failed to load: {self.field.last_error}")

    def close(self) -> None:
        for vnode in self.nodes.values():
            vnode.runtime.close()
        if self.field is not None:
            self.field.close()

    # -- the event log --

    def _team_name(self, team_id: int) -> Optional[str]:
        return self.teams[team_id - 1] if 1 <= team_id <= len(self.teams) else None

    def _record(self, vnode: VirtualNode, ev: Emitted) -> None:
        size = self._check_wire(vnode.name, {"node": ev.node, "seq": ev.seq, "t": ev.t_ms,
                                             "type": ev.type, "team": ev.team, "squad": ev.squad,
                                             "prio": ev.prio, "data": ev.data})
        team = self._team_name(ev.team)
        self._log.append(LogEntry(ev.t_ms, vnode.name, ev.node, ev.seq, ev.type,
                                  team, ev.prio, ev.data, size))
        # A box reports the team of its last capture as its owner (decision E6).
        if ev.type == "zone.captured":
            self.owners[ev.node] = team
        elif ev.type == "zone.neutralized":
            self.owners[ev.node] = None
        if self.field is not None:
            data = dict(ev.data)
            data.setdefault("node", ev.node)
            if team:
                data.setdefault("team", team)
            if vnode.name in self._unreachable:
                self._held.append((vnode.name, ev.t_ms, ev.type, data))
            else:
                self._to_field.append((ev.t_ms, ev.type, data))

    def _record_field(self, ev: Emitted) -> None:
        """An event from field.lua: logged as the controller's; game.end ends the game."""
        if ev.type == "game.end":
            self._field_end = (ev.t_ms, dict(ev.data))
            return
        self._controller_seq += 1
        team = self._team_name(ev.team)
        size = self._check_wire(CONTROLLER, {"node": 0, "seq": self._controller_seq & 0xFFFF,
                                             "t": ev.t_ms, "type": ev.type, "team": ev.team,
                                             "prio": ev.prio, "data": ev.data})
        self._log.append(LogEntry(ev.t_ms, CONTROLLER, 0, self._controller_seq, ev.type, team,
                                  ev.prio, ev.data, size))

    def _field_nodes(self, role: Optional[str]) -> list[dict[str, Any]]:
        return [{"id": v.runtime.node_id, "name": v.name, "role": v.role,
                 "owner": self.owners.get(v.runtime.node_id)}
                for v in self.nodes.values() if role is None or v.role == role]

    def _field_send(self, node_id: int, cmd: str, params: dict[str, Any]) -> bool:
        target = next((v for v in self.nodes.values() if v.runtime.node_id == node_id), None)
        if target is None or cmd not in FIELD_COMMANDS:
            return False
        if cmd == "mode" and not COMMAND_NAME.match(str((params or {}).get("name", ""))):
            return False  # a mode command names itself: 1-24 of a-z, 0-9 and _
        self.field_commands.append((self.time_ms, target.name, cmd, dict(params)))
        if target.name not in self._unreachable:
            self._to_nodes.append((target.name, FIELD_COMMANDS[cmd], dict(params)))
        return True

    def set_reachable(self, node: str, reachable: bool) -> None:
        """Takes a node out of the controller's reach, or brings it back.

        Out of reach, the node keeps playing on its own: its events reach the
        field script only when it is back (a box resends what was not
        acknowledged), and the field script's commands to it are lost.
        """
        self.node(node)
        if reachable:
            self._unreachable.discard(node)
            back = [h for h in self._held if h[0] == node]
            self._held = [h for h in self._held if h[0] != node]
            self._to_field += [(self.time_ms, type_, data) for _, _, type_, data in back]
            self._pump()
        else:
            self._unreachable.add(node)

    def _pump(self) -> None:
        """Delivers what the nodes and the field script sent each other, until nothing is left.

        Deliveries wait until the call that produced them has returned, so the
        core is never re-entered from its own callbacks.
        """
        for _ in range(10_000):
            if self._to_field:
                t_ms, type_, data = self._to_field.pop(0)
                assert self.field is not None
                if t_ms > self.field.time_ms:
                    self.field.advance(t_ms)
                self.field.input(type_, data)
            elif self._to_nodes:
                name, type_, data = self._to_nodes.pop(0)
                self.nodes[name].runtime.input(type_, data)
            elif self._field_end is not None:
                (t_ms, data), self._field_end = self._field_end, None
                if not self._ended:
                    self.end(data.get("reason", "finished"), data.get("winner"), t_ms=t_ms)
            else:
                return
        raise SimError("the nodes and the field script keep sending each other events")

    def _record_controller(self, type_: str, data: dict[str, Any], t_ms: Optional[int] = None) -> None:
        t_ms = self.time_ms if t_ms is None else t_ms
        self._controller_seq += 1
        prio = codec.default_prio(type_)
        size = self._check_wire(CONTROLLER, {"node": 0, "seq": self._controller_seq & 0xFFFF,
                                             "t": t_ms, "type": type_, "prio": prio,
                                             "data": data})
        self._log.append(LogEntry(t_ms, CONTROLLER, 0, self._controller_seq, type_,
                                  None, prio, data, size))

    def _check_wire(self, who: str, event: dict[str, Any]) -> Optional[int]:
        """Checks an event against the schema and the LoRa payload size; returns the size."""
        problems = codec.schema_problems(event["type"], event["data"])
        coords = coordinate_keys(event["data"])
        if coords:
            problems.append(f"'{event['type']}' carries a position ({', '.join(sorted(set(coords)))}): "
                            "positions never travel as events (P4R6)")
        size = None
        try:
            size = len(codec.encode_event(event))
            if size > RF_PAYLOAD_MAX:
                problems.append(f"'{event['type']}' takes {size} bytes on the wire, more than "
                                f"the {RF_PAYLOAD_MAX} bytes of a LoRa payload")
        except codec.CodecError as exc:
            problems.append(f"'{event['type']}' cannot be sent: {exc}")
        self.problems += [f"{who}: {p}" for p in problems]
        return size

    @property
    def arrivals(self) -> list[LogEntry]:
        """Every event in the order the simulator saw it (a live view appends to this)."""
        return list(self._log)

    @property
    def events(self) -> list[LogEntry]:
        """The merged game log, ordered by time. Events at the same time keep their arrival
        order, so a field script's reaction comes after the event it reacts to."""
        order = {id(e): i for i, e in enumerate(self._log)}
        return sorted(self._log, key=lambda e: (e.t_ms, order[id(e)]))

    # -- driving the game --

    def node(self, name: str) -> VirtualNode:
        if name not in self.nodes:
            raise SimError(f"no node named '{name}' (nodes: {', '.join(self.nodes)})")
        return self.nodes[name]

    def broadcast(self, type_: str, data: Optional[dict[str, Any]] = None,
                  t_ms: Optional[int] = None) -> None:
        """A game event from the controller to every node (and to the field script)."""
        self._record_controller(type_, data or {}, t_ms)
        if type_ == "game.end":
            self._ended = True
        for vnode in self.nodes.values():
            vnode.runtime.input(type_, data or {})
        if self.field is not None:
            reason = (data or {}).get("reason")
            self.field.input(type_, {"reason": reason} if reason else {})
        self._pump()

    def start(self) -> None:
        self.broadcast("game.start", {"preset": self.mode.id})

    def end(self, reason: str = "time", winner: Optional[str] = None,
            t_ms: Optional[int] = None) -> None:
        data = {"reason": reason}
        if winner:
            data["winner"] = winner
        self.broadcast("game.end", data, t_ms)

    def wait(self, seconds: float) -> None:
        self.advance_to(self.time_ms + round(seconds * 1000))

    def advance_to(self, t_ms: int) -> None:
        if t_ms < self.time_ms:
            raise SimError("time cannot go backwards")
        self._deliver_pending(t_ms)
        if self.field is None:
            for vnode in self.nodes.values():
                vnode.runtime.advance(t_ms)
            self.time_ms = t_ms
            return
        step = self.time_ms
        while step < t_ms:
            step = min(t_ms, step - step % FIELD_STEP_MS + FIELD_STEP_MS)
            self.time_ms = step
            for vnode in self.nodes.values():
                vnode.runtime.advance(step)
            self._pump()
            self.field.advance(step)
            self._pump()
        self.time_ms = t_ms

    def _deliver_pending(self, t_ms: int) -> None:
        """Deliver radio packets that are due by *t_ms*."""
        if self.radio is None:
            return
        deliveries = self.radio.tick(t_ms)
        for dest_id, hdr, payload in deliveries:
            # Find the VirtualNode with this node_id.
            for vnode in self.nodes.values():
                if vnode.runtime.node_id == dest_id:
                    # Inject the payload as a radio-received event.
                    try:
                        from . import codec as _codec
                        ev = _codec.decode_event(payload)
                        vnode.runtime.input(ev["type"], ev.get("data", {}))
                    except Exception:
                        pass  # not an EVENT payload or decode failure
                    break

    def send_packet(
        self,
        from_node: str,
        payload: bytes,
        msg_type: int,
        priority: int = 1,
        ack_req: bool = False,
        hop_limit: int = 2,
    ) -> Optional[bytes]:
        """Send a packet from *from_node* through the radio model.

        Returns the raw packet bytes, or ``None`` if no radio model is
        attached.
        """
        if self.radio is None:
            return None
        vnode = self.node(from_node)
        seq = (vnode.runtime.node_id * 1000 + self.time_ms) & 0xFFFF
        return self.radio.send(
            from_node=vnode.runtime.node_id,
            payload=payload,
            msg_type=msg_type,
            source=vnode.runtime.node_id,
            seq=seq,
            priority=priority,
            ack_req=ack_req,
            hop_limit=hop_limit,
            now_ms=self.time_ms,
        )

    def partition(self, group_a: set[str], group_b: set[str]) -> None:
        """Partition the radio network between two groups of named nodes."""
        if self.radio is None:
            raise SimError("no radio model attached")
        ids_a = {self.node(n).runtime.node_id for n in group_a}
        ids_b = {self.node(n).runtime.node_id for n in group_b}
        self.radio.partition(ids_a, ids_b)

    def heal(self) -> None:
        """Restore full radio connectivity."""
        if self.radio is None:
            raise SimError("no radio model attached")
        self.radio.heal()

    def link(self, a: str, b: str, connected: bool) -> None:
        """Set the radio link between two named nodes."""
        if self.radio is None:
            raise SimError("no radio model attached")
        self.radio.set_link(
            self.node(a).runtime.node_id,
            self.node(b).runtime.node_id,
            connected,
        )

    def input(self, node: str, type_: str, data: Optional[dict[str, Any]] = None) -> bool:
        vnode = self.node(node)
        accepted = vnode.runtime.input(type_, data or {})
        vnode.last_input = {"t": self.time_ms, "type": type_, "data": data or {}, "accepted": accepted}
        self._pump()
        return accepted

    def position(self, player: str, team: Optional[str], role: str, lat: float, lon: float,
                 acc: Optional[float] = None, src: str = "gps") -> None:
        """A checked-in player's position report, as the field controller hands it to field.lua
        (position.fix, decision P4R6): only the field script gets it; it is never an event, never
        on the radio and never in the log."""
        if self.field is None:
            raise SimError(f"position: {self.mode.id} has no field.lua to give it to")
        if team is not None:
            self._check_team(team)
        if src not in POSITION_SOURCES:
            raise SimError(f"position: src is one of {', '.join(POSITION_SOURCES)}")
        data: dict[str, Any] = {"player": player, "role": role, "lat": float(lat), "lon": float(lon),
                                "src": src}
        if team is not None:
            data["team"] = team
        if acc is not None:
            data["acc"] = float(acc)
        if self.time_ms > self.field.time_ms:
            self.field.advance(self.time_ms)
        self.field.input("position.fix", data)
        self._pump()

    def gps(self, node: str, lat: Optional[float] = None, lon: Optional[float] = None,
            acc: Optional[float] = None) -> bool:
        """A fix from a prop's own GPS (gps.fix: lat, lon, acc), as the Android prop shell gives
        it to the node's script; without lat and lon, the phone has no fix yet."""
        data: dict[str, Any] = {}
        if lat is not None and lon is not None:
            data = {"lat": float(lat), "lon": float(lon)}
        if acc is not None:
            data["acc"] = float(acc)
        return self.input(node, "gps.fix", data)

    def scan(self, node: str, uid: bytes, payload: Optional[bytes]) -> bool:
        """An NFC tag read on a node: the core checks the tag against this game (atalaia/tag.h)
        and the node gets nfc.tag with the result, as a box's shell gives it."""
        data = json.loads(self.core.tag_event_json(uid, payload, self.game_id, self.game_key,
                                                   self.teams))
        return self.input(node, "nfc.tag", data)

    def _check_team(self, team: str) -> None:
        if team not in self.teams:
            raise SimError(f"unknown team '{team}' (teams: {', '.join(self.teams)})")

    def press(self, node: str, team: str, squad: Optional[str] = None) -> None:
        self._check_team(team)
        self.input(node, "team_input.press", _team_data(team, squad))

    def hold(self, node: str, team: str, seconds: float, squad: Optional[str] = None) -> None:
        """A team holds the node's input for this long, then lets go. Time passes."""
        self._check_team(team)
        total = round(seconds * 1000)
        start = self.time_ms
        held = 0
        while held < total:
            held = min(held + HOLD_STEP_MS, total)
            self.advance_to(start + held)
            self.input(node, "team_input.hold", {**_team_data(team, squad), "ms": held})
        self.input(node, "team_input.release", {**_team_data(team, squad), "ms": total})

    def keys(self, node: str, keys: str) -> None:
        """Keypad presses: one keypad.key event per character (digits, * and #)."""
        for key in keys:
            self.input(node, "keypad.key", {"key": key})

    def score(self, team: str, node: Optional[str] = None) -> int:
        """Field total (every node plus the field script), or one node's (CONTROLLER: the script's)."""
        self._check_team(team)
        if node == CONTROLLER:
            return self.field.score(team) if self.field is not None else 0
        if node is not None:
            return self.node(node).runtime.score(team)
        total = sum(v.runtime.score(team) for v in self.nodes.values())
        return total + (self.field.score(team) if self.field is not None else 0)


def _team_data(team: str, squad: Optional[str]) -> dict[str, Any]:
    data: dict[str, Any] = {"team": team}
    if squad:
        data["squad"] = squad
    return data
