# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Game traffic for the relay study (relay_study.py), made by the real core.

A *trace* is what a game asks of the radio, with the radio left out: the events
the boxes' scripts emit (the real Lua scripts in modes/, run by the C core through
``Simulation``, so the event types, priorities and CBOR sizes are the core's own), the
commands a field script sends to boxes, and, for STATE, when each box's counters and
owner changed (a box that holds a zone scores every tick; a STATE is "unchanged" only
when its box owned nothing and emitted nothing since the last one).

Two games:

* Domination (``modes/domination``): N zone boxes, three teams, players capturing at
  random (``captures_per_box_per_min`` hold attempts per box, three seconds each).
  Only attempts that change the owner make an event, as in the field.
* A scenario (the Foxhound example, ``modes/objectives/tests/fixtures/foxhound`` over
  the objectives package): four active boxes (bridge capture, intel tags, the vault's
  code, the bomb site), the setup commands the scenario's ``field.lua`` sends them,
  and a bomb that is armed and explodes; the other boxes of the field only report
  STATE. A scenario is a low-event game: its radio cost is what the STATEs and the
  controller's TIME and ACK frames make.
"""

from __future__ import annotations

import json
import random
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[2]


@dataclass
class TraceEvent:
    t_ms: int
    box: int  # index 0..N-1 of the box that emits it
    type: str
    prio: str  # "telemetry", "normal" or "critical"
    payload_len: int  # CBOR payload bytes on LoRa (the core's own count)


@dataclass
class TraceCommand:
    t_ms: int
    dest: Optional[int]  # box index, or None for every box
    params_len: int  # the JSON params' bytes


@dataclass
class Trace:
    game: str
    n_boxes: int
    minutes: int
    teams: int
    events: list[TraceEvent] = field(default_factory=list)
    commands: list[TraceCommand] = field(default_factory=list)
    # box -> sorted [(start_ms, end_ms)] while it owned a zone (its score counters move)
    owned: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    scores: bool = True  # whether the boxes' counters move at all (scenario boxes never score)

    def events_of(self, box: int) -> list[int]:
        return [e.t_ms for e in self.events if e.box == box]

    def changed(self, box: int, t0_ms: float, t1_ms: float) -> bool:
        """Whether the box's STATE content (owner, counters) moved in (t0, t1]."""
        times = self._event_times.get(box, [])
        i = bisect_right(times, t0_ms)
        if i < len(times) and times[i] <= t1_ms:
            return True
        if not self.scores:
            return False
        for a, b in self.owned.get(box, []):
            if a < t1_ms and b > t0_ms and min(b, t1_ms) - max(a, t0_ms) >= 10_000:
                return True
        return False

    def __post_init__(self) -> None:
        self._event_times: dict[int, list[int]] = {}

    def finish(self) -> "Trace":
        self.events.sort(key=lambda e: e.t_ms)
        self._event_times = {}
        for e in self.events:
            self._event_times.setdefault(e.box, []).append(e.t_ms)
        return self


def _load_sim(lib: Optional[str], mode_dirs: list[str], nodes: dict[str, str], teams: list[str],
              seed: int):
    from .core import Core, find_library
    from .mode import compose, load_mode
    from .sim import Simulation

    core = Core(find_library(lib))
    modes = [load_mode(REPO / d) for d in mode_dirs]
    mode = modes[0] if len(modes) == 1 else compose(modes[0], modes[1:])
    params = mode.resolve_params({}, teams)
    return Simulation(core, mode, nodes, teams, params, seed=seed)


def domination_trace(n_boxes: int, minutes: int = 90, seed: int = 1, lib: Optional[str] = None,
                     captures_per_box_per_min: float = 0.33) -> Trace:
    """Domination with N zone boxes and three teams, played by the real core."""
    teams = ["red", "blue", "green"]
    names = [f"b{i:02d}" for i in range(n_boxes)]
    sim = _load_sim(lib, ["modes/domination"], {n: "zone" for n in names}, teams, seed)
    try:
        sim.start()
        rng = random.Random(seed * 7919 + n_boxes)
        end_ms = minutes * 60_000
        rate = max(n_boxes * captures_per_box_per_min / 60.0, 1e-9)  # attempts per second
        while sim.time_ms < end_ms:
            sim.wait(rng.expovariate(rate))
            if sim.time_ms >= end_ms:
                break
            sim.hold(rng.choice(names), rng.choice(teams), 3.2)
        trace = Trace("domination", n_boxes, minutes, len(teams))
        index = {n: i for i, n in enumerate(names)}
        open_since: dict[int, int] = {}
        for e in sim.events:
            if e.node_id == 0 or e.node not in index:
                continue
            box = index[e.node]
            trace.events.append(TraceEvent(e.t_ms, box, e.type, e.prio, int(e.wire_bytes or 0)))
            if e.type == "zone.captured":
                open_since.setdefault(box, e.t_ms)
        for box, t0 in open_since.items():
            trace.owned[box] = [(t0, end_ms)]  # a zone stays owned until the game ends
        return trace.finish()
    finally:
        sim.close()


def scenario_trace(n_boxes: int, minutes: int = 90, seed: int = 1, lib: Optional[str] = None) -> Trace:
    """The Foxhound scenario over the objectives package, played by the real core."""
    if n_boxes < 4:
        raise ValueError("the Foxhound scenario needs four boxes")
    teams = ["red", "blue"]
    roles = {"alpha": "objective", "bravo": "objective", "charlie": "objective", "site": "bomb_site"}
    sim = _load_sim(lib, ["modes/objectives/tests/fixtures/foxhound", "modes/objectives"], roles,
                    teams, seed)
    try:
        sim.start()
        sim.wait(20)
        sim.hold("alpha", "red", 3)  # the bridge: completes, reveals the vault
        sim.wait(15)
        sim.keys("charlie", "4711#")  # the vault's code
        sim.wait(10)
        sim.hold("site", "red", 5.2)  # arm the bomb: fuse 60 s
        sim.wait(70)
        sim.reboot("bravo")  # a box loses power: node.rebooted, then a new setup command
        sim.wait(max(0, minutes * 60 - sim.time_ms / 1000.0))
        index = {n: i for i, n in enumerate(roles)}
        trace = Trace("scenario", n_boxes, minutes, len(teams), scores=False)
        for e in sim.events:
            # the boxes' node.setup_applied are the radio model's own to make (relay_study's cmd_mode), so that
            # the setup commands can be measured with and without them (PKB-3)
            if e.node in index and e.type != "node.setup_applied":
                trace.events.append(TraceEvent(e.t_ms, index[e.node], e.type, e.prio, int(e.wire_bytes or 0)))
        for t_ms, node, _cmd, params in sim.field_commands:
            trace.commands.append(TraceCommand(
                t_ms, index.get(node), len(json.dumps(params, separators=(",", ":")))))
        return trace.finish()
    finally:
        sim.close()


def get_trace(game: str, n_boxes: int, minutes: int = 90, seed: int = 1, lib: Optional[str] = None,
              **kw: Any) -> Trace:
    if game == "domination":
        return domination_trace(n_boxes, minutes, seed, lib, **kw)
    if game == "scenario":
        return scenario_trace(n_boxes, minutes, seed, lib)
    raise ValueError(f"unknown game {game!r}")
