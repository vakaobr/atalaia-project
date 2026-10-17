# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A simulated game: virtual nodes running one mode on a virtual clock."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from . import codec
from .core import Command, Core, Emitted, Node
from .mode import Mode
from .protocol import RF_PAYLOAD_MAX

# While a team holds an input, shells emit team_input.hold at this interval
# with the time held so far (see modes/README.md).
HOLD_STEP_MS = 250

CONTROLLER = "controller"


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
    ):
        self.mode = mode
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

        for node_id, (name, role) in enumerate(nodes.items(), start=1):
            if role not in mode.roles:
                raise SimError(f"node '{name}': mode {mode.id} has no role '{role}'")
            vnode = VirtualNode(name=name, role=role, runtime=None)  # type: ignore[arg-type]
            vnode.runtime = Node(
                core,
                node_id=node_id,
                game_seed=seed,
                teams=self.teams,
                params=params,
                source=mode.node_script,
                chunk_name=f"@{mode.path.name}/node.lua",
                mem_limit=mem_limit,
                instr_limit=instr_limit,
                on_event=lambda ev, n=vnode: self._record(n, ev),
                on_command=vnode.commands.append,
                on_log=vnode.logs.append,
            )
            self.nodes[name] = vnode
            if not vnode.runtime.loaded:
                raise SimError(f"node '{name}' failed to load {mode.id}: {vnode.runtime.last_error}")

    def close(self) -> None:
        for vnode in self.nodes.values():
            vnode.runtime.close()

    # -- the event log --

    def _team_name(self, team_id: int) -> Optional[str]:
        return self.teams[team_id - 1] if 1 <= team_id <= len(self.teams) else None

    def _record(self, vnode: VirtualNode, ev: Emitted) -> None:
        size = self._check_wire(vnode.name, {"node": ev.node, "seq": ev.seq, "t": ev.t_ms,
                                             "type": ev.type, "team": ev.team, "squad": ev.squad,
                                             "prio": ev.prio, "data": ev.data})
        self._log.append(LogEntry(ev.t_ms, vnode.name, ev.node, ev.seq, ev.type,
                                  self._team_name(ev.team), ev.prio, ev.data, size))

    def _record_controller(self, type_: str, data: dict[str, Any]) -> None:
        self._controller_seq += 1
        prio = codec.default_prio(type_)
        size = self._check_wire(CONTROLLER, {"node": 0, "seq": self._controller_seq & 0xFFFF,
                                             "t": self.time_ms, "type": type_, "prio": prio,
                                             "data": data})
        self._log.append(LogEntry(self.time_ms, CONTROLLER, 0, self._controller_seq, type_,
                                  None, prio, data, size))

    def _check_wire(self, who: str, event: dict[str, Any]) -> Optional[int]:
        """Checks an event against the schema and the LoRa payload size; returns the size."""
        problems = codec.schema_problems(event["type"], event["data"])
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
        """The merged game log, ordered by (time, node, sequence) as on the controller."""
        return sorted(self._log, key=lambda e: (e.t_ms, e.node_id, e.seq))

    # -- driving the game --

    def node(self, name: str) -> VirtualNode:
        if name not in self.nodes:
            raise SimError(f"no node named '{name}' (nodes: {', '.join(self.nodes)})")
        return self.nodes[name]

    def broadcast(self, type_: str, data: Optional[dict[str, Any]] = None) -> None:
        """A game event from the controller to every node."""
        self._record_controller(type_, data or {})
        for vnode in self.nodes.values():
            vnode.runtime.input(type_, data or {})

    def start(self) -> None:
        self.broadcast("game.start", {"preset": self.mode.id})

    def end(self, reason: str = "time") -> None:
        self.broadcast("game.end", {"reason": reason})

    def wait(self, seconds: float) -> None:
        self.advance_to(self.time_ms + round(seconds * 1000))

    def advance_to(self, t_ms: int) -> None:
        if t_ms < self.time_ms:
            raise SimError("time cannot go backwards")
        for vnode in self.nodes.values():
            vnode.runtime.advance(t_ms)
        self.time_ms = t_ms

    def input(self, node: str, type_: str, data: Optional[dict[str, Any]] = None) -> bool:
        vnode = self.node(node)
        accepted = vnode.runtime.input(type_, data or {})
        vnode.last_input = {"t": self.time_ms, "type": type_, "data": data or {}, "accepted": accepted}
        return accepted

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

    def score(self, team: str, node: Optional[str] = None) -> int:
        self._check_team(team)
        if node is not None:
            return self.node(node).runtime.score(team)
        return sum(v.runtime.score(team) for v in self.nodes.values())


def _team_data(team: str, squad: Optional[str]) -> dict[str, Any]:
    data: dict[str, Any] = {"team": team}
    if squad:
        data["squad"] = squad
    return data
