# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""An interactive game for the web view: a Simulation driven by people.

Tests drive a Simulation step by step. Here a person drives it instead: a
clock that runs at some multiple of real time, buttons that a team holds
down for as long as it likes, and game controls for the GM. The web server
(web.py) calls into a LiveGame from several threads, so every public method
takes the game's lock.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .sim import CONTROLLER, HOLD_STEP_MS, SimError, Simulation

SPEEDS = (1, 2, 5, 10, 30, 60)
# Longest stretch of real time one clock tick catches up on, so a laptop
# waking from sleep does not fast-forward the game.
MAX_CATCH_UP_S = 0.5


class LiveError(Exception):
    pass


@dataclass
class Hold:
    team: str
    squad: Optional[str]
    start_ms: int
    held_ms: int = 0


class LiveGame:
    def __init__(self, make_sim: Callable[[], Simulation]):
        self._make_sim = make_sim
        self._lock = threading.RLock()
        self.generation = 0  # changes on every reset, so viewers start over
        self._reset()

    # -- state shared with the web view --

    def _reset(self) -> None:
        old = getattr(self, "sim", None)
        if old is not None:
            old.close()
        self.sim = self._make_sim()
        self.generation += 1
        self.started = False
        self.paused = False
        self.running = False  # the clock
        self.speed = 1
        self.holds: dict[str, Hold] = {}
        self._carry_ms = 0.0
        self._last_tick: Optional[float] = None

    @property
    def ended(self) -> bool:
        return any(v.runtime.status == "ended" for v in self.sim.nodes.values()) or any(
            e.type == "game.end" and e.node == CONTROLLER for e in self.sim.arrivals)

    # -- time --

    def _advance_to(self, target_ms: int) -> None:
        """Moves time forward, sending team_input.hold every HOLD_STEP_MS of each hold."""
        while True:
            next_ms = target_ms
            for hold in self.holds.values():
                next_ms = min(next_ms, hold.start_ms + hold.held_ms + HOLD_STEP_MS)
            self.sim.advance_to(next_ms)
            for node, hold in list(self.holds.items()):
                if hold.start_ms + hold.held_ms + HOLD_STEP_MS == next_ms:
                    hold.held_ms += HOLD_STEP_MS
                    self.sim.input(node, "team_input.hold", _team_data(hold, ms=hold.held_ms))
            if next_ms >= target_ms:
                return

    def step(self, seconds: float) -> None:
        """Lets game time pass now, whether or not the clock runs."""
        with self._lock:
            if not self.started or self.paused or self.ended:
                raise LiveError("game time only passes while the game is on")
            self._advance_to(self.sim.time_ms + round(seconds * 1000))

    def tick(self, now: Optional[float] = None) -> None:
        """Called often by the server: advances game time by the real time passed."""
        now = time.monotonic() if now is None else now
        with self._lock:
            last, self._last_tick = self._last_tick, now
            if last is None or not self.running:
                return
            if not self.started or self.paused or self.ended:
                self.running = self.running and not self.ended
                return
            self._carry_ms += min(now - last, MAX_CATCH_UP_S) * 1000 * self.speed
            whole = int(self._carry_ms)
            if whole > 0:
                self._carry_ms -= whole
                self._advance_to(self.sim.time_ms + whole)

    # -- actions --

    def act(self, action: str, args: dict[str, Any]) -> None:
        handler = getattr(self, f"_do_{action}", None)
        if handler is None:
            raise LiveError(f"unknown action '{action}'")
        with self._lock:
            try:
                handler(args)
            except (SimError, KeyError, ValueError, TypeError) as exc:
                raise LiveError(str(exc)) from exc

    def _require_on(self) -> None:
        if not self.started:
            raise LiveError("the game has not started")
        if self.ended:
            raise LiveError("the game is over")

    def _do_start(self, _args: dict[str, Any]) -> None:
        if self.started:
            raise LiveError("the game has already started")
        self.sim.start()
        self.started = True
        self.running = True

    def _do_pause(self, _args: dict[str, Any]) -> None:
        self._require_on()
        if self.paused:
            raise LiveError("the game is already paused")
        self._release_all()
        self.sim.broadcast("game.pause", {"reason": "gm"})
        self.paused = True

    def _do_resume(self, _args: dict[str, Any]) -> None:
        self._require_on()
        if not self.paused:
            raise LiveError("the game is not paused")
        self.sim.broadcast("game.resume", {})
        self.paused = False

    def _do_end(self, _args: dict[str, Any]) -> None:
        self._require_on()
        self._release_all()
        self.sim.end("gm")
        self.running = False

    def _do_reset(self, _args: dict[str, Any]) -> None:
        self._reset()

    def _do_clock(self, args: dict[str, Any]) -> None:
        if "running" in args:
            self.running = bool(args["running"])
            self._carry_ms = 0.0
        if "speed" in args:
            if args["speed"] not in SPEEDS:
                raise LiveError(f"speed must be one of {', '.join(map(str, SPEEDS))}")
            self.speed = args["speed"]

    def _do_step(self, args: dict[str, Any]) -> None:
        self.step(float(args["seconds"]))

    def _do_press(self, args: dict[str, Any]) -> None:
        self._require_on()
        self.sim.press(args["node"], args["team"], args.get("squad"))

    def _do_hold(self, args: dict[str, Any]) -> None:
        """A team starts holding a node's input; release ends it."""
        self._require_on()
        node, team = args["node"], args["team"]
        self.sim.node(node)
        if team not in self.sim.teams:
            raise LiveError(f"unknown team '{team}'")
        if node in self.holds:
            raise LiveError(f"{self.holds[node].team} is already holding {node}")
        self.holds[node] = Hold(team, args.get("squad"), self.sim.time_ms)

    def _do_release(self, args: dict[str, Any]) -> None:
        hold = self.holds.pop(args["node"], None)
        if hold is not None:
            self.sim.input(args["node"], "team_input.release",
                           _team_data(hold, ms=self.sim.time_ms - hold.start_ms))

    def _release_all(self) -> None:
        for node in list(self.holds):
            self._do_release({"node": node})

    # -- the view --

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        """Everything the page shows; events from index `since` onwards."""
        with self._lock:
            sim = self.sim
            nodes = []
            for name, vnode in sim.nodes.items():
                outputs: dict[str, dict[str, Any]] = {}
                screen = audio = None
                for cmd in vnode.commands:
                    entry = {"t": cmd.t_ms, "target": cmd.target, "method": cmd.method, "args": cmd.args}
                    if cmd.target == "ui" and cmd.method == "screen":
                        screen = entry
                    elif cmd.target == "audio":
                        audio = entry
                    else:
                        outputs[cmd.target] = entry
                hold = self.holds.get(name)
                nodes.append({
                    "name": name,
                    "role": vnode.role,
                    "status": vnode.runtime.status,
                    "error": vnode.runtime.last_error,
                    "mem": vnode.runtime.mem_used,
                    "scores": {t: vnode.runtime.score(t) for t in sim.teams},
                    "screen": screen,
                    "audio": audio,
                    "outputs": list(outputs.values()),
                    "input": vnode.last_input,
                    "hold": None if hold is None else {"team": hold.team, "ms": sim.time_ms - hold.start_ms},
                    "logs": vnode.logs[-20:],
                })
            arrivals = sim.arrivals
            since = since if 0 <= since <= len(arrivals) else 0
            return {
                "generation": self.generation,
                "mode": {"id": sim.mode.id, "name": sim.mode.name, "version": sim.mode.version},
                "teams": sim.teams,
                "params": sim.params,
                "time_ms": sim.time_ms,
                "clock": {"running": self.running, "speed": self.speed, "speeds": list(SPEEDS)},
                "game": {"started": self.started, "paused": self.paused, "ended": self.ended},
                "scores": {t: sim.score(t) for t in sim.teams},
                "nodes": nodes,
                "events_total": len(arrivals),
                "events_from": since,
                "events": [{
                    "t": e.t_ms, "node": e.node, "seq": e.seq, "type": e.type, "team": e.team,
                    "prio": e.prio, "data": e.data, "bytes": e.wire_bytes,
                } for e in arrivals[since:]],
                "problems": list(sim.problems),
            }

    def close(self) -> None:
        with self._lock:
            self.sim.close()


def _team_data(hold: Hold, **extra: Any) -> dict[str, Any]:
    data: dict[str, Any] = {"team": hold.team}
    if hold.squad:
        data["squad"] = hold.squad
    return {**data, **extra}
