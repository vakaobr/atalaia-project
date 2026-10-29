# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""What a state change, a channel change and a sweep cost in air time (decisions RL-1 onwards).

RFC 0001 Amendment 19 added frames the relay study (relay_study.py, decisions SL-7 to SL-37) did not have:

* a **state change** (start, pause, resume) goes out as CMD + TIME and then TIME alone at +1.0, +2.5, +5.0 and
  +10.0 s (``field_controller.STATE_REPEAT_GAPS_MS``, decision RB-8), and every box relays each TIME with
  the density rule (probability min(1, 3 / neighbours), Amendment 13);
* a **channel change** sends MOVE three times 2.5 s apart on the old channel (RB-4); *Find boxes* sends two
  MOVEs on each of the last four channels, at most once a minute (RB-6).

This module does two things. ``frame_table`` and ``move_cost`` are arithmetic on the project's own formulas
(``regions.airtime_ms``, the frame sizes of the codecs), the figures the RFC quotes; ``measure`` runs the
relay study's engine for a typical game with and without the repeats and returns what they add, per box and
for the controller, against each EU868 sub-band's limit.

    python -m atalaia_sim.state_load --sizes 20 --seeds 1,2,3
"""

from __future__ import annotations

import argparse
import statistics
import sys
from typing import Any, Optional

from . import lobby, regions
from .field_controller import STATE_REPEAT_GAPS_MS
from .packet import cmd_encode
from .relay_study import HEADER, MIC, run_one

# The frame sizes on air (header 9 + body + MIC 8): TIME as the relay study has it (23 bytes of body), a CMD with
# only an opcode and the broadcast destination, a MOVE (45 bytes: Amendment 19 part 1).
TIME_BYTES = HEADER + 23 + MIC
CMD_BYTES = HEADER + len(cmd_encode({"cmd": 1, "dest": 0xFFFF})) + MIC
MOVE_BYTES = 45

# The sub-bands a game can use, as the table of regions.py names them: (label, duty fraction, advice).
BUDGET_S_PER_HOUR = {"10 %": 360.0, "1 %": 36.0, "0.1 %": 3.6}


def frame_ms(nbytes: int, region: str = "eu868") -> float:
    return regions.get(region).airtime_ms(nbytes)


def state_change_air_ms(gaps: tuple[int, ...] = STATE_REPEAT_GAPS_MS, region: str = "eu868") -> dict[str, float]:
    """The controller's own air for one start, pause or resume: CMD, TIME and one TIME per repeat."""
    cmd, time_ = frame_ms(CMD_BYTES, region), frame_ms(TIME_BYTES, region)
    return {"cmd": cmd, "time_first": time_, "time_repeats": len(gaps) * time_,
            "total": cmd + time_ * (1 + len(gaps)), "before_amendment_19": cmd + time_}


def move_cost_ms(old_channels: int = 0, region: str = "eu868") -> dict[str, float]:
    """A channel change (three MOVEs on the old channel) and a sweep (two MOVEs on each remembered channel)."""
    m = frame_ms(MOVE_BYTES, region)
    return {"move": m, "channel_change": lobby.MOVE_REPEATS * m,
            "sweep": old_channels * lobby.SWEEP_REPEATS * m}


def frame_table(region: str = "eu868") -> list[dict[str, Any]]:
    gaps = STATE_REPEAT_GAPS_MS
    rows = [{"frame": "TIME", "bytes": TIME_BYTES, "ms": frame_ms(TIME_BYTES, region)},
            {"frame": "CMD start/pause/resume", "bytes": CMD_BYTES, "ms": frame_ms(CMD_BYTES, region)},
            {"frame": "MOVE", "bytes": MOVE_BYTES, "ms": frame_ms(MOVE_BYTES, region)}]
    for r in rows:
        r["ms"] = round(r["ms"], 1)
    return rows + [{"frame": f"state change ({1 + len(gaps)} TIME + CMD)", "bytes": None,
                    "ms": round(state_change_air_ms(gaps, region)["total"], 1)}]


def typical_game(minutes: int = 60, pause_pairs_per_hour: int = 3) -> list[tuple[int, str]]:
    """A start, then ``pause_pairs_per_hour`` pauses of 3 minutes spread over the hour, each with its resume.
    [(ms after the start, kind)]. Three pairs an hour is a game with a briefing stop, a medic stop and a break."""
    changes: list[tuple[int, str]] = [(0, "start")]
    span_ms = minutes * 60_000
    for k in range(pause_pairs_per_hour):
        t = int(span_ms * (k + 1) / (pause_pairs_per_hour + 1))
        changes += [(t, "pause"), (t + 180_000, "resume")]
    return changes


def per_hour(changes_per_hour: float, per_change_s: float) -> dict[str, float]:
    """Seconds of air an hour and the share of each sub-band's budget."""
    s = changes_per_hour * per_change_s
    return {"air_s": round(s, 2), **{f"pct_of_{k.replace(' ', '')}": round(100 * s / v, 2) for k, v in BUDGET_S_PER_HOUR.items()}}


def measure(n: int = 20, seeds: tuple[int, ...] = (1, 2, 3), minutes: int = 60, pause_pairs: int = 3,
            policy: str = "A_backoff_core_lbt_hw", layout: str = "all_in_range", region: str = "eu868",
            gaps: Optional[tuple[int, ...]] = None, lib: Optional[str] = None) -> dict[str, Any]:
    """The same field and seeds with the repeats as built (``gaps``, default STATE_REPEAT_GAPS_MS) and with none:
    the difference is what the repeats cost. Means over the seeds; air in seconds per box-hour."""
    changes = typical_game(minutes, pause_pairs)
    gaps = STATE_REPEAT_GAPS_MS if gaps is None else gaps
    rows = {"with": [], "without": []}
    for sd in seeds:
        for name, g in (("with", gaps), ("without", ())):
            rows[name].append(run_one("domination", n, layout, region, policy, minutes, sd, lib,
                                      state_changes=changes, time_repeat_gaps_ms=g))

    def mean(name: str, f) -> float:
        return statistics.fmean(f(r) for r in rows[name])

    out: dict[str, Any] = {"n": n, "minutes": minutes, "changes": len(changes), "gaps_ms": list(gaps), "seeds": list(seeds)}
    hours = minutes / 60.0
    for name in rows:
        out[name] = {
            "box_air_pct": mean(name, lambda r: r["airtime_pct"]["mean"]),
            "box_air_pct_max": mean(name, lambda r: r["airtime_pct"]["max"]),
            "box_time_s_per_hour": mean(name, lambda r: r["time_air_s_per_box_hour"]["all"]),
            "controller_air_pct": mean(name, lambda r: r["controller"]["airtime_pct"]),
            "controller_time_s_per_hour": mean(name, lambda r: r["controller"]["air_s_by_type"].get("TIME", 0.0)) / hours,
            "dc_dropped": mean(name, lambda r: r["dc_dropped"]["total"]),
            "captures_acked_pct": mean(name, lambda r: r["events"]["captures"].get("acked_pct", 100.0)),
        }
    w, wo = out["with"], out["without"]
    out["added"] = {
        "box_time_s_per_hour": round(w["box_time_s_per_hour"] - wo["box_time_s_per_hour"], 2),
        "box_air_points": round(w["box_air_pct"] - wo["box_air_pct"], 2),
        "controller_time_s_per_hour": round(w["controller_time_s_per_hour"] - wo["controller_time_s_per_hour"], 2),
        "controller_air_points": round(w["controller_air_pct"] - wo["controller_air_pct"], 2),
    }
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m atalaia_sim.state_load", description=__doc__.split("\n")[0])
    ap.add_argument("--sizes", default="20")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--pause-pairs", type=int, default=3, help="pause + resume pairs in the hour")
    ap.add_argument("--policy", default="A_backoff_core_lbt_hw")
    ap.add_argument("--gaps", default=None, help="comma-separated ms between TIME repeats (default: the built ones)")
    ap.add_argument("--lib", default=None)
    a = ap.parse_args(argv)
    print("| frame | bytes | air ms |\n| --- | --- | --- |")
    for r in frame_table():
        print(f"| {r['frame']} | {r['bytes'] if r['bytes'] else ''} | {r['ms']} |")
    mv = move_cost_ms(4)
    print(f"\nchannel change {mv['channel_change']:.0f} ms, sweep of 4 channels {mv['sweep']:.0f} ms\n")
    gaps = tuple(int(x) for x in a.gaps.split(",")) if a.gaps else None
    for n in (int(x) for x in a.sizes.split(",")):
        r = measure(n, tuple(int(x) for x in a.seeds.split(",")), 60, a.pause_pairs, a.policy, gaps=gaps, lib=a.lib)
        print(f"N={n}: {r['changes']} state changes in the hour")
        for k in ("without", "with"):
            print(f"  {k:8} {r[k]}")
        print(f"  added    {r['added']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
