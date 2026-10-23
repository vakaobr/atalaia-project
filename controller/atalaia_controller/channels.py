# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's radio channel: the candidate list, the noise scan, the suggestion.

The channel is a field setting (decisions CH1-CH8 in
docs/review/decisions-to-review.md, RFC 0001 Amendment 3), in the field's
radio region (atalaia_sim/regions.py, Amendment 12: EU868 or AS923-TW;
every function here takes the region, EU868 when not given). The EU868
default, 869.525 MHz, sits in the only EU868 sub-band that allows 10% duty
cycle and 500 mW ERP; AS923-TW's, 921.5 MHz, keeps clear of LoRaWAN's and
Meshtastic's defaults. The GM can keep it, scan for a quieter one, draw one
at random or pick one from the list: only channels of the region.

A scan asks the USB modem to measure each candidate (MEASURE, protocol/
usb-modem.md) for an equal share of the dwell, and ranks the results:
channels where LoRa preambles were detected in more than 5% of the tries
come last, the rest go quietest first by their 90th-percentile noise. The
suggestion is the quietest full-power (869.4-869.65 MHz) channel if it is
quiet enough (90th percentile at or below the threshold, little LoRa
activity), otherwise the quietest channel of all.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import asdict
from typing import Any, Callable, Optional

from atalaia_sim import regions
from atalaia_sim.regions import Region

from . import modem_framing as mf

log = logging.getLogger("atalaia.channels")

BUSY_ACTIVITY = 0.05      # CAD detections above this share: other LoRa traffic (decision CH4)
PER_CHANNEL_MAX_S = 10.0  # one MEASURE command dwells at most 10 s (protocol/usb-modem.md)
PER_CHANNEL_MIN_S = 0.01

SOURCES = ("default", "scan", "random", "manual")


def candidates(region: Region = regions.EU868) -> list[dict[str, Any]]:
    """Every channel the GM can pick in the region, with its sub-band's limits."""
    return [region.describe(hz) for hz in region.candidates]


def rank_key(n: mf.Noise) -> tuple:
    return (n.activity > BUSY_ACTIVITY, n.p90_dbm, n.activity, n.mean_dbm, n.channel_hz)


def is_quiet(n: mf.Noise, threshold_dbm: int) -> bool:
    return n.p90_dbm <= threshold_dbm and n.activity <= BUSY_ACTIVITY


def suggest(results: list[mf.Noise], threshold_dbm: int,
            region: Region = regions.EU868) -> Optional[dict[str, Any]]:
    """The channel to suggest after a scan, and why (decision CH3)."""
    if not results:
        return None
    ranked = sorted(results, key=rank_key)
    full = [n for n in ranked if region.band_of(n.channel_hz).full_power]
    if full and is_quiet(full[0], threshold_dbm):
        return {"channel_hz": full[0].channel_hz, "reason": "quiet_full_power"}
    reason = "quietest" if is_quiet(ranked[0], threshold_dbm) else "quietest_but_noisy"
    return {"channel_hz": ranked[0].channel_hz, "reason": reason}


def random_choice(rng: Optional[random.Random] = None, region: Region = regions.EU868) -> dict[str, Any]:
    """A random legal channel of the region with enough airtime for a game (decision CH5)."""
    pool = region.scan_candidates()
    hz = (rng or random.SystemRandom()).choice(pool)
    full = sum(1 for c in pool if region.band_of(c).full_power)
    return {**region.describe(hz), "pool": len(pool), "pool_full_power": full}


def per_channel_dwell_s(total_s: float, count: int) -> float:
    return max(PER_CHANNEL_MIN_S, min(PER_CHANNEL_MAX_S, total_s / max(1, count)))


class Scan:
    """One noise scan over the candidates, run in its own thread.

    ``measure(channel_hz, dwell_ms)`` is RadioModem.measure; ``on_change``
    gets the public state after every channel and at the end.
    """

    def __init__(self, measure: Callable[[int, int], mf.Noise], total_s: float,
                 threshold_dbm: int, on_change: Callable[[dict[str, Any]], None],
                 channels: Optional[list[int]] = None, region: Region = regions.EU868) -> None:
        self.region = region
        self.channels = list(channels or region.scan_candidates())
        self.dwell_ms = int(round(per_channel_dwell_s(total_s, len(self.channels)) * 1000))
        self.threshold_dbm = threshold_dbm
        self._measure = measure
        self._on_change = on_change
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self.state = "running"           # running, done, failed, cancelled
        self.error: Optional[str] = None
        self.results: list[mf.Noise] = []
        self.current: Optional[int] = None
        self.started_at = time.time()
        self.finished_at: Optional[float] = None
        self._thread = threading.Thread(target=self._run, name="channel-scan", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def join(self, timeout: Optional[float] = None) -> None:
        self._thread.join(timeout)

    @property
    def running(self) -> bool:
        return self.state == "running"

    def _run(self) -> None:
        try:
            for hz in self.channels:
                if self._cancel.is_set():
                    self._finish("cancelled")
                    return
                with self._lock:
                    self.current = hz
                self._notify()
                noise = self._measure(hz, self.dwell_ms)
                with self._lock:
                    self.results.append(noise)
            self._finish("done")
        except Exception as exc:  # MeasureError, a link failure: the scan stops
            log.warning("channel scan failed: %s", exc)
            self.error = str(exc)
            self._finish("failed")

    def _finish(self, state: str) -> None:
        with self._lock:
            self.state = state
            self.current = None
            self.finished_at = time.time()
        self._notify()

    def _notify(self) -> None:
        try:
            self._on_change(self.public())
        except Exception:
            log.exception("scan listener failed")

    def public(self) -> dict[str, Any]:
        with self._lock:
            results = list(self.results)
            ranked = sorted(results, key=rank_key)
            return {
                "state": self.state, "error": self.error,
                "channels": len(self.channels), "measured": len(results),
                "current_hz": self.current, "dwell_ms": self.dwell_ms,
                "total_s": round(self.dwell_ms * len(self.channels) / 1000, 1),
                "threshold_dbm": self.threshold_dbm,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "region": self.region.code,
                "results": [result_row(n, self.threshold_dbm, self.region) for n in ranked],
                "suggestion": (suggest(results, self.threshold_dbm, self.region)
                               if self.state == "done" else None),
            }


def result_row(n: mf.Noise, threshold_dbm: int, region: Region = regions.EU868) -> dict[str, Any]:
    return {**region.describe(n.channel_hz), **asdict(n), "activity_pct": round(n.activity * 100, 1),
            "quiet": is_quiet(n, threshold_dbm)}
