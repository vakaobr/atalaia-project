# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs a mode's event-sequence tests (modes/<mode>/tests/*.yaml).

A test sets up a game, then runs steps in order. Steps that make time pass
are `wait` and `hold`; everything else happens at the current game time.

    name: Attackers arm and the bomb explodes
    params: { fuse_s: 60 }        # optional overrides of mode.yaml defaults
    teams: [red, blue]            # optional; this is the default
    nodes: { bomb: bomb }         # optional: node name -> role
    steps:
      - hold: { node: bomb, team: red, s: 5 }
      - wait: 59
      - expect_no: bomb.exploded
      - wait: 1
      - expect: { type: bomb.exploded, team: red }

See modes/README.md for every step.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from . import tag as player_tag
from .core import Core
from .mode import Mode, ModeError, compose, load_mode
from .sim import CONTROLLER, LogEntry, SimError, Simulation

DEFAULT_TEAMS = ["red", "blue"]


class TestFailure(Exception):
    pass


@dataclass
class TestResult:
    mode: str
    file: Path
    name: str
    passed: bool
    message: str = ""
    log: list[str] = field(default_factory=list)


def _subset(expected: Any, actual: Any) -> bool:
    """True if every key in expected matches actual (recursively for dicts)."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(
            k in actual and _subset(v, actual[k]) for k, v in expected.items()
        )
    return expected == actual


def _event_filter(spec: Any) -> dict[str, Any]:
    if isinstance(spec, str):
        return {"type": spec}
    if not isinstance(spec, dict) or "type" not in spec:
        raise TestFailure(f"an event match needs a type: {spec!r}")
    return spec


def _matches(entry: LogEntry, spec: dict[str, Any]) -> bool:
    if entry.type != spec["type"]:
        return False
    if "node" in spec and entry.node != spec["node"]:
        return False
    if "team" in spec and entry.team != spec["team"]:
        return False
    if "at" in spec and entry.t_ms != round(spec["at"] * 1000):
        return False
    if "data" in spec and not _subset(spec["data"], entry.data):
        return False
    return True


class _Runner:
    def __init__(self, sim: Simulation):
        self.sim = sim
        self.cursor = 0  # events before this index were consumed by `expect`

    def step(self, step: dict[str, Any]) -> None:
        if not isinstance(step, dict) or len(step) != 1:
            raise TestFailure(f"each step needs exactly one action: {step!r}")
        action, arg = next(iter(step.items()))
        handler = getattr(self, f"do_{action}", None)
        if handler is None:
            raise TestFailure(f"unknown step '{action}'")
        handler(arg)

    def _default_node(self, arg: dict[str, Any]) -> str:
        if "node" in arg:
            return arg["node"]
        if len(self.sim.nodes) == 1:
            return next(iter(self.sim.nodes))
        raise TestFailure("this game has several nodes: say which one with node:")

    # -- actions --

    def do_start(self, _arg: Any) -> None:
        self.sim.start()

    def do_end(self, arg: Any) -> None:
        self.sim.end(arg if isinstance(arg, str) else "time")

    def do_pause(self, _arg: Any) -> None:
        self.sim.broadcast("game.pause", {"reason": "gm"})

    def do_resume(self, _arg: Any) -> None:
        self.sim.broadcast("game.resume", {})

    def do_wait(self, arg: Any) -> None:
        self.sim.wait(float(arg))

    def do_hold(self, arg: dict[str, Any]) -> None:
        self.sim.hold(self._default_node(arg), arg["team"], float(arg["s"]), arg.get("squad"))

    def do_press(self, arg: dict[str, Any]) -> None:
        self.sim.press(self._default_node(arg), arg["team"], arg.get("squad"))

    def do_input(self, arg: dict[str, Any]) -> None:
        self.sim.input(self._default_node(arg), arg["type"], arg.get("data"))

    def do_scan(self, arg: Any) -> None:
        """An NFC tag read: a player's signed tag, a forged one, one from another game, or a
        tag with no Atalaia record (uid only). See modes/README.md."""
        if not isinstance(arg, dict):
            raise TestFailure("scan takes a map: { player, team } or { uid }")
        unknown = set(arg) - {"node", "player", "team", "uid", "forged", "game"}
        if unknown:
            raise TestFailure(f"scan: unknown key(s) {sorted(unknown)}")
        payload = None
        if "player" in arg:
            team = arg.get("team")
            if team is not None and team not in self.sim.teams:
                raise TestFailure(f"scan: unknown team '{team}'")
            team_id = self.sim.teams.index(team) + 1 if team else 0
            key = self.sim.game_key
            if arg.get("forged"):
                key = bytes(b ^ 0x5A for b in key)
            game_id = int(arg.get("game", self.sim.game_id))
            payload = player_tag.encode({"player": str(arg["player"]), "team": team_id,
                                         "game_id": game_id}, key)
        if arg.get("uid"):
            uid = bytes.fromhex(str(arg["uid"]))
        elif "player" in arg:
            uid = b"\x04" + hashlib.sha256(str(arg["player"]).encode()).digest()[:6]
        else:
            raise TestFailure("scan needs a player or a uid")
        self.sim.scan(self._default_node(arg), uid, payload)

    def do_keys(self, arg: Any) -> None:
        if not isinstance(arg, dict):
            arg = {"keys": arg}
        self.sim.keys(self._default_node(arg), str(arg["keys"]))

    # -- checks --

    def do_expect(self, arg: Any) -> None:
        spec = _event_filter(arg)
        events = self.sim.events
        for i in range(self.cursor, len(events)):
            if _matches(events[i], spec):
                self.cursor = i + 1
                return
        raise TestFailure(f"expected event {spec} at or before {self.sim.time_ms / 1000:g}s, not found")

    def do_expect_no(self, arg: Any) -> None:
        spec = _event_filter(arg)
        for entry in self.sim.events[self.cursor:]:
            if _matches(entry, spec):
                raise TestFailure(f"unexpected event: {entry.describe().strip()}")

    def do_expect_score(self, arg: dict[str, Any]) -> None:
        actual = self.sim.score(arg["team"], arg.get("node"))
        if actual != arg["points"]:
            raise TestFailure(f"expected {arg['team']} to have {arg['points']} points, has {actual}")

    def do_expect_status(self, arg: Any) -> None:
        if isinstance(arg, str):
            arg = {"status": arg}
        names = [arg["node"]] if "node" in arg else list(self.sim.nodes)
        for name in names:
            runtime = self.sim.node(name).runtime
            if runtime.status != arg["status"]:
                detail = f" ({runtime.last_error})" if runtime.last_error else ""
                raise TestFailure(f"expected node '{name}' to be {arg['status']}, it is {runtime.status}{detail}")

    def do_expect_screen(self, arg: dict[str, Any]) -> None:
        name = self._default_node(arg)
        cmd = self.sim.node(name).last_command("ui", "screen")
        if cmd is None:
            raise TestFailure(f"node '{name}' has not shown any screen")
        template = cmd.args[0] if cmd.args else None
        data = cmd.args[1] if len(cmd.args) > 1 else {}
        if template != arg["template"] or not _subset(arg.get("data", {}), data):
            raise TestFailure(f"expected screen {arg['template']} {arg.get('data', {})} on '{name}', "
                              f"last screen is {template} {data}")


def _check_problems(sim: Simulation, where: str) -> None:
    """Any event that breaks the protocol schema fails the test."""
    if sim.problems:
        raise TestFailure(f"{where}: " + "; ".join(sim.problems) +
                          " (see protocol/schema/events.yaml)")


def _composed(mode: Mode, spec: dict[str, Any]) -> Mode:
    """The mode a test plays: a modifier's test may name a main mode (`main: domination`) and a
    main mode's test its modifiers (`modifiers: [codes]`), as sibling folders of the mode."""
    main = spec.get("main")
    modifiers = spec.get("modifiers") or []
    if main is None and not modifiers:
        return mode
    if not isinstance(modifiers, list) or (main is not None and not isinstance(main, str)):
        raise ModeError("main is a mode folder name and modifiers a list of them")
    others = [load_mode(mode.path.parent / name) for name in modifiers]
    if main is not None:
        return compose(load_mode(mode.path.parent / main), [mode, *others])
    return compose(mode, others)


def run_test(core: Core, mode: Mode, path: Path) -> TestResult:
    try:
        spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return TestResult(mode.id, path, path.stem, False, f"invalid YAML: {exc}")
    name = spec.get("name", path.stem)
    teams = spec.get("teams", DEFAULT_TEAMS)

    sim: Optional[Simulation] = None
    try:
        mode = _composed(mode, spec)
        default_node = next(iter(mode.roles))
        nodes = spec.get("nodes", {default_node: default_node})
        params = mode.resolve_params(spec.get("params") or {}, teams)
        sim = Simulation(core, mode, nodes, teams, params, seed=spec.get("seed", 1))
        runner = _Runner(sim)
        if spec.get("autostart", True):
            sim.start()
            _check_problems(sim, "start")
        for i, step in enumerate(spec.get("steps") or [], start=1):
            try:
                runner.step(step)
            except (TestFailure, SimError, KeyError) as exc:
                raise TestFailure(f"step {i} {step!r}: {exc}") from exc
            _check_problems(sim, f"step {i} {step!r}")
        return TestResult(mode.id, path, name, True)
    except (TestFailure, SimError, ModeError) as exc:
        log = [e.describe() for e in sim.events] if sim else []
        if sim:
            for vnode in sim.nodes.values():
                log += [f"{'':10}  {vnode.name:<12} log: {line}" for line in vnode.logs]
            log += [f"{'':10}  {CONTROLLER:<12} log: {line}" for line in sim.field_logs]
            if sim.field is not None and sim.field.last_error:
                log.append(f"{'':10}  {CONTROLLER:<12} error: {sim.field.last_error}")
        return TestResult(mode.id, path, name, False, str(exc), log)
    finally:
        if sim:
            sim.close()
