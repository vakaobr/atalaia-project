# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller's wall clock, and a guard against a wrong one (decisions CLK-*).

A field has no internet, and a Raspberry Pi 4 has no real-time clock: after a power cycle its clock comes
up at the last shutdown (fake-hwclock) or at 1970. A Pi 5 has one only with its optional battery. So the
wall clock cannot be trusted, and nothing here may need it for a duration: games, timeouts and rate limits
run on ``time.monotonic()``. What does use the wall clock (timestamps, player-token expiry, retention
purges, the TLS certificates) reads it through ``now()``.

``now()`` is ``time.time()`` plus an offset that only a GM can move, and only forward (``ClockGuard.set``):
the service runs as an unprivileged user and cannot set the system clock, and a GM's browser (a phone or
laptop on the field's Wi-Fi) has the right time. A clock that moved backwards would let an expired player
token or certificate live again, so a backward move is refused, as is any move below the plausibility floor.

The floor is the newest of: the release date of this build, the highest wall time this controller saw
(kept in the store every few minutes: a Pi 4 that comes up days behind is caught by it) and the newest
timestamp in the store. A clock below it is wrong, whatever the reason.
"""

from __future__ import annotations

import calendar
import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from .store import Store

log = logging.getLogger(__name__)

# The date of this release, UTC: no real clock in the field is earlier. Bump it with every release (a test
# refuses a date in the future and one older than the CHANGELOG's newest release).
RELEASE_DATE = calendar.timegm((2026, 11, 1, 0, 0, 0))
HIGH_WATER_KEY = "clock.high_water"
HIGH_WATER_EVERY_S = 300        # how often the highest wall time seen is stored
TOLERANCE_S = 60                # a clock this far under the floor is still taken as right (fake-hwclock saves late)
JUMP_S = 30                     # wall time that moves this much more or less than monotonic time: a jump
BIG_JUMP_S = 86400              # a forward jump this big holds the retention purge
PURGE_HOLD_S = 3600             # for this long, so a GM sees the banner before anything is deleted
SET_MAX_AHEAD_FLOOR_S = 5 * 365 * 86400   # a set from a wrong clock: at most this far above the floor ...
SET_MAX_AHEAD_NOW_S = 14 * 86400          # ... and from a plausible clock, at most this far above it
# A field-wide RELEASE (RFC 0001 Amendment 28, its addendum of 2026-11-06) is stamped with now(): never more
# than this past a clock the controller can vouch for. Boxes refuse one that is RELEASE_AHEAD_S (the same
# 300 s) past their game's clock, so a frame stamped ahead never stays valid for long.
RELEASE_SLACK_S = 300

_lock = threading.Lock()
_offset = 0.0


def now() -> float:
    """Seconds since 1970 by the controller's wall clock (the system clock plus the GM's correction)."""
    return time.time() + _offset


def offset() -> float:
    return _offset


def reset() -> None:
    """Drops the correction (tests)."""
    global _offset
    with _lock:
        _offset = 0.0


class ClockError(Exception):
    """A clock setting that is refused; ``code`` is stable for the console."""

    def __init__(self, code: str, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.code, self.status = code, status


class ClockGuard:
    def __init__(self, store: "Store", wall: Callable[[], float] = now,
                 mono: Callable[[], float] = time.monotonic, release_date: float = RELEASE_DATE) -> None:
        self.store = store
        self._wall = wall
        self._mono = mono
        self.release_date = release_date
        self._lock = threading.Lock()
        self._ref_wall, self._ref_mono = wall(), mono()
        self._hold_until: Optional[float] = None
        self._high_stored = 0.0
        self._hw: Optional[float] = None
        self._records: Optional[float] = None   # the store's newest timestamp, read once (a scan of events)
        self._was_ok: Optional[bool] = None
        self.last_jump: Optional[dict[str, Any]] = None
        self.set_at: Optional[float] = None   # when a GM last set it (by the corrected clock)

    # --- what the clock should at least say ---------------------------------------------------

    def high_water(self) -> float:
        if self._hw is None:
            try:
                self._hw = float(self.store.get_setting(HIGH_WATER_KEY) or 0.0)
            except ValueError:
                self._hw = 0.0
        return self._hw

    def floor(self) -> tuple[float, str]:
        """The earliest time this clock can honestly show, and what it comes from."""
        if self._records is None:
            self._records = self.store.newest_wall_time()  # later records are our own clock: the high-water mark
        best, why = self.release_date, "release"
        for value, name in ((self.high_water(), "high_water"), (self._records, "records")):
            if value > best:
                best, why = value, name
        return best, why

    def plausible(self) -> bool:
        return self._wall() >= self.floor()[0] - TOLERANCE_S

    def status(self) -> dict[str, Any]:
        floor, why = self.floor()
        now_s = self._wall()
        ok = now_s >= floor - TOLERANCE_S
        with self._lock:
            hold = self._hold_until is not None and self._mono() < self._hold_until
            jump = dict(self.last_jump) if self.last_jump else None
        return {"ok": ok, "now": round(now_s, 3), "floor": round(floor, 3),
                "reason": None if ok else ("before_release" if why == "release" else "behind_records"),
                "offset_s": round(offset(), 3), "set_at": self.set_at, "purge_held": hold or not ok,
                "last_jump": jump}

    # --- the tick ---------------------------------------------------------------------------

    def start(self) -> None:
        s = self.status()
        self._was_ok = s["ok"]
        if not s["ok"]:
            log.warning("the clock is wrong: %s is earlier than %s (%s); a GM can set it from the console "
                        "(it is not used for any duration, retention purges wait)",
                        _iso(s["now"]), _iso(s["floor"]), s["reason"])
        else:
            self._store_high_water()

    def tick(self) -> None:
        """Called every tick: sees a jump of the wall clock, stores the high-water mark, logs changes."""
        wall, mono = self._wall(), self._mono()
        with self._lock:
            drift = (wall - self._ref_wall) - (mono - self._ref_mono)
            self._ref_wall, self._ref_mono = wall, mono
            if abs(drift) > JUMP_S:
                self.last_jump = {"at": round(wall, 3), "seconds": round(drift, 1)}
                log.warning("the wall clock jumped %+.0f s (NTP, a GM or the system); durations are unaffected",
                            drift)
                if drift > BIG_JUMP_S:
                    self._hold_until = mono + PURGE_HOLD_S
        ok = self.plausible()
        if ok != self._was_ok:
            if ok:
                log.info("the clock is plausible again (%s)", _iso(wall))
            else:
                log.warning("the clock is wrong: %s is behind what this controller has already seen", _iso(wall))
            self._was_ok = ok
        if ok:
            self._store_high_water()

    def _store_high_water(self) -> None:
        wall = self._wall()
        if wall > self._high_stored + HIGH_WATER_EVERY_S:
            self._high_stored = wall
            try:
                self.store.set_setting(HIGH_WATER_KEY, repr(wall))
                self._hw = max(self.high_water(), wall)
            except Exception:  # noqa: BLE001 - a full disk must not stop the tick
                log.warning("the clock's high-water mark was not stored", exc_info=True)

    def purge_allowed(self) -> bool:
        """False while the clock is wrong or just jumped far forward: nothing is deleted by a wrong date."""
        with self._lock:
            held = self._hold_until is not None and self._mono() < self._hold_until
        return self.plausible() and not held

    # --- RELEASE's time (RFC 0001 Amendment 28, addendum of 2026-11-06; decision RLB-4) ----------

    def release_check(self, device_time: Any = None) -> None:
        """Raises ClockError unless now() may stamp a field-wide RELEASE. Its bound is a clock the
        controller can vouch for, plus RELEASE_SLACK_S: the GM's device clock when the request carries it
        (``device_time``, the console sends it), else the system clock without the GM's correction. So a
        correction moved too far forward (a typo, which cannot be undone) is refused until a GM's
        device confirms the time, and a device that disagrees refuses it too."""
        if not self.plausible():
            raise ClockError("not_set", "the controller's clock is not set: set it first, so that the boxes "
                                        "can tell this RELEASE from an older one")
        now_s = self._wall()
        if device_time is not None:
            if isinstance(device_time, bool) or not isinstance(device_time, (int, float)) or device_time != device_time:
                raise ClockError("invalid", "device_time: seconds since 1970 as a number", 400)
            if now_s > device_time + RELEASE_SLACK_S:
                raise ClockError("ahead_of_device",
                                 f"the controller's clock ({_iso(now_s)}) is ahead of this device's "
                                 f"({_iso(device_time)}): a RELEASE stamped with it would stay valid too long. "
                                 "Restart the controller to drop the correction, or set this device's clock")
            return
        if offset() > RELEASE_SLACK_S:
            raise ClockError("unconfirmed",
                             f"the controller's clock was moved {offset():.0f} s forward and no device confirmed "
                             "it: send the RELEASE from the console (it sends its device's clock)")

    # --- the GM's correction ------------------------------------------------------------------

    def set(self, epoch: Any) -> dict[str, Any]:
        """Moves the controller's wall clock forward to ``epoch`` (a GM's device clock). Refused: not a
        number, below the floor, not forward, or absurdly far ahead."""
        global _offset
        if isinstance(epoch, bool) or not isinstance(epoch, (int, float)) or epoch != epoch:
            raise ClockError("invalid", "epoch: seconds since 1970 as a number", 400)
        floor, _ = self.floor()
        now_s = self._wall()
        if epoch < floor - TOLERANCE_S:
            raise ClockError("below_floor", f"{_iso(epoch)} is earlier than {_iso(floor)}: this device's clock is "
                                            "wrong too, or the controller has seen a later time")
        if epoch < now_s - TOLERANCE_S:
            raise ClockError("backwards", "the clock only moves forward: a backward move would revive expired "
                                          "tokens and certificates")
        limit = floor + SET_MAX_AHEAD_FLOOR_S if now_s < floor - TOLERANCE_S else now_s + SET_MAX_AHEAD_NOW_S
        if epoch > limit:
            raise ClockError("too_far", f"{_iso(epoch)} is too far ahead of the controller's clock")
        epoch = float(epoch)
        with _lock:
            _offset += max(0.0, epoch - now())
        log.warning("a GM set the controller's clock: %s -> %s", _iso(now_s), _iso(self._wall()))
        with self._lock:
            self._ref_wall, self._ref_mono = self._wall(), self._mono()   # not a jump: it was asked for
            self.set_at = self._wall()
            self._hold_until = None
            self.last_jump = None
        self._high_stored = 0.0
        self._was_ok = None
        self.tick()
        return self.status()


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(max(0.0, epoch)))
