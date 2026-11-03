# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A box's outputs in the simulator (draft RFC "The expansion port", increment 4).

The box's output layer (firmware/esp32/main/outputs.c) as far as a mode's tests and the web view need it:
which outputs a box has (their functions, each with its max on), what each shows at a game time, and the
rules a mode meets on a real box:

- an output switches on only while the game runs, or in the 10 s grace after its end (an end-of-game
  horn, never past the grace);
- every output goes off when the game starts, is paused (a resumed game does not turn them back on), ends
  or the script is halted;
- a call never runs longer than the output's max on (30 s until the field's admin sets another), a
  simple output shows a change for at least 500 ms (a shorter pulse lasts 500 ms) and a pattern's on and
  off times are 500 ms to 10 s;
- a call to an output the box does not have does nothing (EXP-19).

What is left out: the 2 starts a second a script may make (EXP-30), the 500 ms between an off and the next
on, and the admin's settings at the box (in the simulator every fitted output is enabled). Each start, and
each off before its time, is an ``output.switched`` (capability, ms, source), as the box sends it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

GRACE_MS = 10_000            # OUT_GRACE_MS: after a game's end, an end-of-game horn
SIMPLE_MIN_MS = 500          # OUT_SIMPLE_MIN_MS: the shortest a simple output shows a change
MS_MAX = 600_000             # OUT_MS_MAX: the longest call (CMD 12's ms)
PATTERN_MAX_MS = 10_000      # OUT_PATTERN_MAX_MS
MAX_ON_DEFAULT_S = 30        # OUT_MAX_ON_DEFAULT_S: a channel's max on until its admin sets another
MAX_ON_MAX_S = 600           # OUT_MAX_ON_MAX_S
METHODS = ("on", "off", "pulse", "pattern")


@dataclass
class _Channel:
    id: str
    max_on_ms: int
    start_ms: int = 0
    until_ms: int = 0  # on while the game time is before this
    on_ms: int = 0     # a pattern's on and off times (0: steady)
    off_ms: int = 0
    source: str = ""

    def on(self, t_ms: int) -> bool:
        return t_ms < self.until_ms

    def level(self, t_ms: int) -> bool:
        if not self.on(t_ms):
            return False
        if not self.on_ms:
            return True
        return (t_ms - self.start_ms) % (self.on_ms + self.off_ms) < self.on_ms


def fitted_outputs(spec: Any, where: str) -> dict[str, int]:
    """A test's outputs for one node: a list of functions (each with the default max on) or a map of
    function to its max on in seconds (1-600). Raises ValueError."""
    if isinstance(spec, list):
        spec = {fn: MAX_ON_DEFAULT_S for fn in spec}
    if not isinstance(spec, dict):
        raise ValueError(f"{where}: outputs are a list of functions, or a map of function to max on (s)")
    out: dict[str, int] = {}
    for fn, max_on in spec.items():
        if not isinstance(fn, str) or not fn:
            raise ValueError(f"{where}: an output's function is text, such as siren")
        if not isinstance(max_on, int) or isinstance(max_on, bool) or not 1 <= max_on <= MAX_ON_MAX_S:
            raise ValueError(f"{where}: output {fn}: max on is 1 to {MAX_ON_MAX_S} s")
        out[fn] = max_on * 1000
    return out


class BoxOutputs:
    """One box's outputs. ``on_switched(t_ms, data)`` gets each output.switched's data."""

    def __init__(self, fitted: dict[str, int], on_switched: Optional[Callable[[int, dict[str, Any]], None]] = None):
        self.channels = {fn: _Channel(fn, max_on_ms) for fn, max_on_ms in fitted.items()}
        self._on_switched = on_switched
        self.game = "none"  # none, running, paused, ended, halted
        self.grace_until = 0

    def has(self, capability: str) -> bool:
        return capability in self.channels

    # -- the game's state (outputs_game_start, outputs_tick, outputs_game_end) --

    def _all_off(self, t_ms: int) -> None:
        for c in self.channels.values():
            if c.on(t_ms):
                c.until_ms = t_ms

    def game_start(self, t_ms: int) -> None:
        self._all_off(t_ms)
        self.game = "running"

    def pause(self, t_ms: int) -> None:
        if self.game == "running":
            self._all_off(t_ms)
            self.game = "paused"

    def resume(self, _t_ms: int) -> None:
        if self.game == "paused":
            self.game = "running"

    def end(self, t_ms: int) -> None:
        """The game ends: every output off, then the grace (before the mode's game.end handlers run)."""
        if self.game in ("running", "paused"):
            self._all_off(t_ms)
            self.game = "ended"
            self.grace_until = t_ms + GRACE_MS

    def boot(self, t_ms: int, running: bool) -> None:
        """The box restarted: every output off, then it plays on in the running game (or waits for one)."""
        self._all_off(t_ms)
        self.game = "running" if running else "none"

    def halt(self, t_ms: int) -> None:
        if self.game != "halted":
            self._all_off(t_ms)
            self.game = "halted"

    # -- switching --

    def _tell(self, t_ms: int, capability: str, ms: int, source: str) -> None:
        if self._on_switched is not None:
            self._on_switched(t_ms, {"capability": capability, "ms": ms, "source": source})

    def _off(self, t_ms: int, c: _Channel, source: str) -> None:
        if c.on(t_ms):
            c.until_ms = t_ms
            self._tell(t_ms, c.id, 0, source)

    def switch(self, t_ms: int, capability: str, act: str, ms: int = 0, on_ms: int = 0, off_ms: int = 0,
               source: str = "script") -> str:
        """outputs_switch: ``ok``, ``no_such``, ``not_now`` or ``bad_args``. ms: how long (on: 0 is its
        max on; pulse and pattern need one)."""
        if capability == "*":
            if act != "off":
                return "bad_args"
            for c in self.channels.values():
                self._off(t_ms, c, source)
            return "ok"
        c = self.channels.get(capability)
        if c is None:
            return "no_such"
        if act == "off":
            self._off(t_ms, c, source)
            return "ok"
        grace = self.game == "ended" and t_ms < self.grace_until
        if self.game != "running" and not grace:
            return "not_now"
        if act == "on":
            ms = c.max_on_ms if ms <= 0 or ms > c.max_on_ms else ms
        elif act in ("pulse", "pattern"):
            if not 1 <= ms <= MS_MAX:
                return "bad_args"
            ms = min(ms, c.max_on_ms)
        else:
            return "bad_args"
        if act == "pattern" and not (SIMPLE_MIN_MS <= on_ms <= PATTERN_MAX_MS and SIMPLE_MIN_MS <= off_ms <= PATTERN_MAX_MS):
            return "bad_args"
        ms = max(ms, SIMPLE_MIN_MS)
        if grace:
            left = self.grace_until - t_ms
            if left < SIMPLE_MIN_MS:
                return "not_now"
            ms = min(ms, left)
        c.start_ms, c.until_ms, c.source = t_ms, t_ms + ms, source
        c.on_ms, c.off_ms = (on_ms, off_ms) if act == "pattern" else (0, 0)
        self._tell(t_ms, c.id, ms, source)
        return "ok"

    def script_call(self, t_ms: int, target: str, method: str, args: list[Any]) -> bool:
        """A script's cap(target):method(args) (command_dispatch_output): True when it was for an output of
        this box (whatever the output layer then said)."""
        if target not in self.channels or method not in METHODS:
            return False

        def ms(i: int) -> int:
            v = args[i] if i < len(args) else None
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not v >= 1:
                return 0
            return MS_MAX if v > MS_MAX else int(v)

        if method == "pulse":
            if ms(0):
                self.switch(t_ms, target, "pulse", ms(0))
        elif method == "on":
            self.switch(t_ms, target, "on", ms(0))
        elif method == "off":
            self.switch(t_ms, target, "off")
        elif ms(0) and ms(1) and ms(2):
            self.switch(t_ms, target, "pattern", ms(2), ms(0), ms(1))
        return True

    # -- what it shows --

    def level(self, capability: str, t_ms: int) -> bool:
        c = self.channels.get(capability)
        return c is not None and self.game != "halted" and c.level(t_ms)

    def states(self, t_ms: int) -> list[dict[str, Any]]:
        """Each output as the web view draws it: its function, on (now), left_ms, the pattern, the source."""
        out = []
        for c in self.channels.values():
            running = c.on(t_ms) and self.game != "halted"
            out.append({"capability": c.id, "on": self.level(c.id, t_ms),
                        "left_ms": c.until_ms - t_ms if running else 0,
                        "pattern": [c.on_ms, c.off_ms] if running and c.on_ms else None,
                        "source": c.source if running else None,
                        "max_on_s": c.max_on_ms // 1000})
        return out
