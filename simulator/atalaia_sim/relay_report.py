# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tables from relay_study results (the list of dicts ``run_matrix`` returns, or its JSON), and the
whole study as one command::

    python -m atalaia_sim.relay_report --out relay-study-results.md --json results.json

Every cell is the **median over the seeds** run: a congested field is bistable (the same rules recover
on one seed and collapse on the next), so one seed proves nothing.
"""

from __future__ import annotations

import json
import statistics
import sys
from collections import defaultdict
from typing import Any, Iterable, Optional

Result = dict[str, Any]
Group = list[Result]


def _fmt(v: Any, nd: int = 1) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def table(headers: list[str], rows: Iterable[list[Any]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join(" --- " for _ in headers) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_fmt(c) for c in r) + " |")
    return "\n".join(out)


def dig(r: Result, path: str) -> Any:
    cur: Any = r
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def group(results: list[Result]) -> dict[tuple[str, str, int, str, str], Group]:
    """Results by (game, layout, n, region, policy): one group holds the seeds."""
    g: dict[tuple[str, str, int, str, str], Group] = defaultdict(list)
    for r in results:
        g[(r["game"], r["layout"], r["n"], r["region"], r["policy"])].append(r)
    return g


def med(grp: Group, path: str) -> Optional[float]:
    vals = [v for v in (dig(r, path) for r in grp) if isinstance(v, (int, float))]
    return round(statistics.median(vals), 2) if vals else None


def worst(grp: Group, path: str, high_is_bad: bool = True) -> Optional[float]:
    vals = [v for v in (dig(r, path) for r in grp) if isinstance(v, (int, float))]
    if not vals:
        return None
    return round(max(vals) if high_is_bad else min(vals), 2)


def summary_table(results: list[Result]) -> str:
    """One row per configuration (median over seeds): the numbers the maintainer asked for."""
    rows = []
    for key, grp in sorted(group(results).items()):
        game, layout, n, region, policy = key
        rows.append([game, layout, n, region, policy, len(grp),
                     med(grp, "airtime_pct.mean"), med(grp, "airtime_pct.max"), med(grp, "airtime_pct.last30_mean"),
                     med(grp, "dc_dropped.per_box_mean"), med(grp, "boxes_over_budget"),
                     med(grp, "collisions.lost_pct_of_audible"),
                     med(grp, "events.captures.delivered_pct"), med(grp, "events.captures.acked_pct"),
                     med(grp, "events.captures.latency_p50_s"), med(grp, "events.captures.latency_p95_s"),
                     med(grp, "states.heard_pct"), med(grp, "states.age_p95_s")])
    return table(["game", "layout", "N", "region", "policy", "seeds", "air % mean", "air % max box",
                  "air % last 30 min", "DC drops/box", "boxes over budget", "rx lost %", "captures delivered %",
                  "captures ACKed %", "capture lat p50 s", "p95 s", "STATE heard %", "STATE age p95 s"], rows)


COMPARE_HEADERS = ["layout", "N", "rule", "air % mean", "air % worst box", "DC drops/box", "boxes over budget",
                   "captures delivered %", "(worst seed)", "captures ACKed %", "capture lat p95 s",
                   "STATE heard %", "STATE lat p95 s", "STATE age p95 s", "HELLO ACKed %", "longest wait for a TIME s",
                   "CMDs delivered %"]


def _pol_rows(results: list[Result], game: str, region: str, policies: list[str], sizes: list[int],
              layouts: list[str]) -> list[list[Any]]:
    g = group(results)
    rows = []
    ev = "events.all_game_events" if game == "scenario" else "events.captures"  # a scenario has a handful of captures
    for layout in layouts:
        for n in sizes:
            for pol in policies:
                grp = g.get((game, layout, n, region, pol))
                if not grp:
                    continue
                rows.append([LAYOUT_NAMES.get(layout, layout), n, pol, med(grp, "airtime_pct.mean"),
                             med(grp, "airtime_pct.max"), med(grp, "dc_dropped.per_box_mean"),
                             med(grp, "boxes_over_budget"),
                             med(grp, ev + ".delivered_pct"), worst(grp, ev + ".delivered_pct", False),
                             med(grp, ev + ".acked_pct"), med(grp, ev + ".latency_p95_s"),
                             med(grp, "states.heard_pct"), med(grp, "states.latency_p95_s"), med(grp, "states.age_p95_s"),
                             med(grp, "events.hello.acked_pct"), med(grp, "time_sync.max_gap_s"),
                             med(grp, "cmds.delivered_pct")])
    return rows


def compare_table(results: list[Result], game: str, region: str, policies: list[str],
                  sizes: Optional[list[int]] = None, layouts: Optional[list[str]] = None) -> str:
    sizes = sizes or sorted({r["n"] for r in results})
    layouts = layouts or [lay for lay in LAYOUT_NAMES if any(r["layout"] == lay for r in results)]
    return table(COMPARE_HEADERS, _pol_rows(results, game, region, policies, sizes, layouts))


def per_box_table(r: Result, limit: int = 40) -> str:
    rows = [[b["box"], b["air_pct"], b["own_pct"], b["relay_pct"], b["dc_dropped"], b["queue_dropped"],
             b["rx_collided"], b["rx_halfduplex"], b["relays"], b["states"]] for b in r["per_box"][:limit]]
    return table(["box", "air %", "own %", "relay %", "DC drops", "queue drops", "rx lost to collision",
                  "rx lost to own TX", "relays sent", "STATEs sent"], rows)


def decision_tables(results: list[Result]) -> str:
    """One comparison table per (game, region), for whatever the results hold."""
    out: list[str] = ["# Relay study results (generated by `python -m atalaia_sim.relay_study --report`)\n"]
    games = sorted({r["game"] for r in results})
    regions_ = sorted({r["region"] for r in results})
    policies = list(dict.fromkeys(r["policy"] for r in results))
    for game in games:
        for region in regions_:
            out.append(f"\n## {game}, {region}\n")
            out.append(compare_table(results, game, region, policies))
    return "\n".join(out) + "\n"


# --- listen-before-talk on A+backoff (decision SL-25) -----------------------------------------------
# The CAD's cost. The figures are the SX1261/2 datasheet's (DS.SX1261-2 rev 2.1) and Semtech AN1200.48's as
# the study's author remembers them: NOT checked against the PDF in this session, so re-check them before
# building. A two-symbol CAD from standby is two symbols of 1.024 ms (both regions) plus the chip's
# processing and the wake from standby, taken as 4 ms in all. Its current is the receiver's (4.6 mA, DC-DC,
# LoRa), taken as 6 mA to leave some room. A transmission at the box's 13 dBm conducted power is taken as
# the datasheet's +14 dBm, 45 mA (DC-DC). The front-end module's own current (LNA on receive, PA on
# transmit) is excluded from both: it is board-level and to be measured.
CAD_MS = 4.0
# Measured on the bench (SL-25 gate, 2026-10-26): 8.0 ms average, p95 8.9 ms. The rows of the built transmit
# path (the "_hw" policies, SL-30) are priced with it; the earlier rows keep the 4 ms they were run with.
CAD_MS_BENCH = 8.0
CAD_MA = 6.0
TX_MA = 45.0
RX_MA = 4.6

LBT_RULES = [("A_backoff", "A_backoff_lbt"), ("A_backoff_core", "A_backoff_core_lbt"),
             ("A_backoff_core_hw", "A_backoff_core_lbt_hw")]


def lbt_energy(cads_per_hour: float, air_pct: float, cad_ms: float = CAD_MS) -> tuple[float, float]:
    """(CAD mC per hour, TX mC per hour) of one box."""
    return cads_per_hour * cad_ms / 1000.0 * CAD_MA, air_pct / 100.0 * 3600.0 * TX_MA


def lbt_table(results: list[Result], game: str, region: str) -> str:
    """One row per layout, size and rule (with and without the CAD): the numbers of SL-25."""
    g = group(results)
    ev = "events.all_game_events" if game == "scenario" else "events.captures"
    layouts = [lay for lay in LAYOUT_NAMES if any(r["layout"] == lay for r in results)]
    sizes = sorted({r["n"] for r in results})
    rows = []
    for layout in layouts:
        for n in sizes:
            for base, lbt in LBT_RULES:
                for pol in (base, lbt):
                    grp = g.get((game, layout, n, region, pol))
                    if not grp:
                        continue
                    cads = med(grp, "lbt_cads_per_box_hour") or 0.0
                    air = med(grp, "airtime_pct.mean") or 0.0
                    cad_mc, tx_mc = lbt_energy(cads, air, CAD_MS_BENCH if pol.endswith("_hw") else CAD_MS)
                    rows.append([LAYOUT_NAMES.get(layout, layout), n, pol, med(grp, "airtime_pct.mean"),
                                 med(grp, "airtime_pct.max"), med(grp, ev + ".delivered_pct"),
                                 med(grp, ev + ".acked_pct"), med(grp, ev + ".latency_p50_s"),
                                 med(grp, ev + ".latency_p95_s"), med(grp, "states.heard_pct"),
                                 med(grp, "dc_dropped.per_box_mean"), cads if cads else "-",
                                 med(grp, "lbt_gave_up_per_box_hour") if cads else "-",
                                 round(cad_mc / 3.6, 2) if cads else "-", round(tx_mc / 3.6, 0),
                                 round(100.0 * cad_mc / tx_mc, 2) if cads and tx_mc else "-"])
    return table(["layout", "N", "rule", "air % mean", "air % worst box", "captures delivered %",
                  "captures ACKed %", "capture lat p50 s", "p95 s", "STATE heard %", "frames refused/box",
                  "CADs/box/h", "sent after 8 tries/box/h", "CAD uAh/h", "TX uAh/h", "CAD as % of TX energy"], rows)


def lbt_section(results: list[Result]) -> str:
    out = []
    for game in sorted({r["game"] for r in results}):
        for region in sorted({r["region"] for r in results}):
            out.append(f"\n### {game}, {region}\n")
            out.append(lbt_table(results, game, region))
    return "\n".join(out) + "\n"


# --- the full report -------------------------------------------------------------------------------

LAYOUT_NAMES = {"all_in_range": "all in range", "long": "long field", "cqb": "CQB (walls)"}
IDEAS = ["firmware", "G_ackfix", "no_state_relay", "period_adaptive", "state_delta", "spread_jitter", "counter",
         "density", "ack_gated", "backoff", "designated", "no_relay", "lbt", "A_relay", "B_counter", "A_backoff",
         "C_period", "D_backoff", "E_period_backoff", "D_lbt"]
CANDIDATES = ["firmware", "G_ackfix", "A_relay", "A_backoff", "D_backoff"]
CMD_RULES = ["firmware", "A_backoff", "H_paced"]
SENSITIVITY: list[tuple[str, dict[str, Any]]] = [
    ("as modelled (capture 6 dB, no extra loss, clocks +-20 ppm)", {}),
    ("capture effect 3 dB (LoRa locks on more easily)", {"capture_db": 3.0}),
    ("capture effect 10 dB (it locks less)", {"capture_db": 10.0}),
    ("5 % of receptions lost at random (fading, a body in the way)", {"loss": 0.05}),
    ("clocks perfect (0 ppm): periodic frames stay in step", {"drift_ppm": 0.0}),
    ("clocks +-60 ppm", {"drift_ppm": 60.0}),
    ("3x the captures (1 per box per minute)", {"captures_per_box_per_min": 1.0}),
]


def _ideal_vs_real(real: list[Result], ideal: list[Result], sizes: list[int]) -> str:
    from . import regions as _regions
    from .relay_study import STATE_MS, air_us, state_frame_bytes
    g_real, g_ideal = group(real), group(ideal)
    rows = []
    for region in ("eu868", "as923-tw"):
        reg = _regions.get(region)
        for n in sizes:
            predicted = 100.0 * n * air_us(reg, state_frame_bytes(3)) / (STATE_MS * 1000)
            key = ("domination", "all_in_range", n, region, "firmware")
            gi, gr = g_ideal.get(key), g_real.get(key)
            if not gi or not gr:
                continue
            rows.append([region, n, round(predicted, 1), med(gi, "airtime_pct.peak_hour_mean"),
                         med(gi, "dc_dropped.per_box_mean"), med(gr, "airtime_pct.mean"),
                         med(gr, "airtime_pct.peak_hour_mean"), med(gr, "dc_dropped.per_box_mean"),
                         med(gr, "boxes_over_budget"), med(gr, "collisions.lost_pct_of_audible")])
    return table(["region", "N", "SL-4 arithmetic: % per box", "ideal channel: busiest hour %",
                  "ideal: frames refused by the budget per box", "with collisions: % of all 90 min",
                  "busiest hour %", "frames refused by the budget per box", "boxes that were refused",
                  "receptions lost %"], rows)


def _ack_stall(results: list[Result]) -> str:
    g = group(results)
    rows = []
    for n in sorted({r["n"] for r in results}):
        for pol in ("firmware", "G_ackfix", "A_relay"):
            grp = g.get(("domination", "all_in_range", n, "eu868", pol))
            if not grp:
                continue
            first = [v for v in (dig(r, "events.captures_acked_pct_by_period.first_45_min") for r in grp) if v is not None]
            last = [v for v in (dig(r, "events.captures_acked_pct_by_period.last_30_min") for r in grp) if v is not None]
            rows.append([n, pol, round(statistics.median(first), 1) if first else None,
                         round(statistics.median(last), 1) if last else None,
                         med(grp, "events.captures.mean_transmissions")])
    return table(["N", "rule", "captures ACKed %, first 45 min", "captures ACKed %, last 30 min",
                  "transmissions per capture (mean)"], rows)


def _reach_table(sizes: list[int]) -> str:
    from .relay_study import LAYOUTS, layout_long
    rows = []
    for n in sizes:
        for name, make in LAYOUTS.items():
            r = make(n, 1).reach()
            rows.append([LAYOUT_NAMES[name], n, r["neighbours_mean"], r["direct"], r["within_hop_limit"], r["unreachable"]])
        r3 = layout_long(n, 1, k=3).reach()
        rows.append(["long field, 3 neighbours each side", n, r3["neighbours_mean"], r3["direct"],
                     r3["within_hop_limit"], r3["unreachable"]])
    return table(["layout", "N", "boxes heard by a box (mean)", "heard by the controller directly",
                  "within the hop limit (3 hops)", "never heard"], rows)


def _sens_table(blocks: list[tuple[str, list[Result]]], n: int) -> str:
    rows = []
    for label, res in blocks:
        g = group(res)
        for layout in ("all_in_range", "long"):
            for pol in ("firmware", "A_backoff", "D_backoff"):
                grp = g.get(("domination", layout, n, "eu868", pol))
                if not grp:
                    continue
                rows.append([label, LAYOUT_NAMES[layout], pol, med(grp, "airtime_pct.mean"),
                             med(grp, "boxes_over_budget"), med(grp, "events.captures.delivered_pct"),
                             med(grp, "events.captures.acked_pct"), med(grp, "states.heard_pct")])
    return table(["assumption changed", f"layout (N={n})", "rule", "air % mean", "boxes over budget",
                  "captures delivered %", "captures ACKed %", "STATE heard %"], rows)


def run_all(lib: Optional[str] = None, seeds: Optional[list[int]] = None, minutes: int = 90, workers: int = 0,
            quick: bool = False) -> list[Result]:
    """Runs everything the decisions quote; every result carries the ``set`` it belongs to."""
    from .relay_study import run_matrix
    seeds = seeds or [1, 2, 3]
    sizes = [5, 10, 20, 30]
    sens_n = 20
    if quick:
        sizes, minutes, sens_n = [5, 10], min(minutes, 12), 10
    layouts = ["all_in_range", "long", "cqb"]
    both = ["eu868", "as923-tw"]

    def tag(label: str, results: list[Result]) -> list[Result]:
        for r in results:
            r["set"] = label
        return results

    out = tag("big", run_matrix(["domination", "scenario"], sizes, layouts, both, CANDIDATES, minutes, seeds, lib, workers))
    idea_sizes = [s for s in sizes if s >= 20] or sizes
    out += tag("ideas", run_matrix(["domination"], idea_sizes, layouts, ["eu868"], IDEAS, minutes, seeds, lib, workers))
    out += tag("ideal", run_matrix(["domination"], sizes, ["all_in_range"], both, ["firmware"], minutes, [1], lib,
                                   workers, ideal_channel=True))
    out += tag("cmds", run_matrix(["scenario"], [s for s in sizes if s >= 10], layouts, ["eu868"], CMD_RULES, minutes,
                                  seeds + [4, 5], lib, workers))
    for label, kw in SENSITIVITY:
        out += tag("sens:" + label, run_matrix(["domination"], [sens_n], ["all_in_range", "long"], ["eu868"],
                                               ["firmware", "A_backoff", "D_backoff"], minutes, seeds, lib, workers,
                                               **kw))
    return out


PACE_NOTE = (
    "\n`H_paced` is the controller's TX pacing as built (decision SL-39, RFC 0001 Amendment 15): one FIFO for "
    "every frame the controller sends, 800 ms from the end of one frame's air time to the start of the next, a "
    "queue of 8, the gap counted from the modem's TX_ACK. The model's parameters and the built ones are the "
    "same, so the rows above are the built behaviour's numbers (the run was repeated on the built parameters, "
    "five seeds, and gave the same table). The pacing is not free for the controller's ACKs, which wait in the "
    "same queue: in some cells fewer of them are heard by their box and in others more (a box resends an "
    "unacknowledged EVENT or HELLO after 3 s and then at longer gaps, so a late ACK is mostly still in time), "
    "and no frame was dropped by the queue in any run:\n\n"
)


def _cmd_table(results: list[Result]) -> str:
    g = group(results)
    rows = []
    for layout in LAYOUT_NAMES:
        for n in sorted({r["n"] for r in results}):
            row: list[Any] = [LAYOUT_NAMES[layout], n]
            for pol in CMD_RULES:
                grp = g.get(("scenario", layout, n, "eu868", pol))
                row.append(med(grp, "cmds.delivered_pct") if grp else None)
            rows.append(row)
    return table(["layout", "N"] + [f"{p}: CMDs reaching their box %" for p in CMD_RULES], rows)


def _pace_table(results: list[Result]) -> str:
    """What the built TX pacing (SL-13) costs and does, from the same runs as ``_cmd_table``: H_paced against
    A_backoff, the median over the seeds."""
    g = group(results)
    rows = []
    for layout in LAYOUT_NAMES:
        for n in sorted({r["n"] for r in results}):
            for pol in ("A_backoff", "H_paced"):
                grp = g.get(("scenario", layout, n, "eu868", pol))
                if not grp:
                    continue
                dropped = [x["controller"]["queue_dropped"] for x in grp]
                rows.append([LAYOUT_NAMES[layout], n, pol, med(grp, "cmds.delivered_pct"),
                             med(grp, "controller.airtime_pct"), med(grp, "controller.acks_heard_by_their_box_pct"),
                             statistics.median(dropped), max(dropped)])
    return table(["layout", "N", "rule", "CMDs reaching their box %", "controller air %",
                  "controller ACKs heard by their box %", "controller frames dropped by its queue (median)",
                  "(worst seed)"], rows)


def render(results: list[Result]) -> str:
    """The report's Markdown from the results ``run_all`` made (or a saved JSON of them)."""
    big = [r for r in results if r["set"] == "big"]
    ideas = [r for r in results if r["set"] == "ideas"]
    ideal = [r for r in results if r["set"] == "ideal"]
    sens = [(label[5:], [r for r in results if r["set"] == label])
            for label in dict.fromkeys(r["set"] for r in results) if label.startswith("sens:")]
    sizes = sorted({r["n"] for r in big})
    idea_sizes = sorted({r["n"] for r in ideas})
    seeds = sorted({r["seed"] for r in big})
    minutes = big[0]["minutes"] if big else 0
    layouts = [lay for lay in LAYOUT_NAMES if any(r["layout"] == lay for r in big)]
    games, both = sorted({r["game"] for r in big}), sorted({r["region"] for r in big})
    sens_n = sens[0][1][0]["n"] if sens and sens[0][1] else 20
    out = ["<!--\nSPDX-FileCopyrightText: 2026 The Atalaia contributors\nSPDX-License-Identifier: CC-BY-SA-4.0\n-->\n",
           "# Relay study: the numbers behind decisions SL-7 to SL-20\n",
           f"Generated by `python -m atalaia_sim.relay_report` ({minutes}-minute games, seeds {seeds}; every "
           "cell is the median over the seeds unless it says worst). See `simulator/atalaia_sim/relay_study.py` "
           "for the model and its caveats, and decisions SL-7 to SL-20 for what each table means. In the scenario's "
           "tables the *captures* columns count every event the scenario's boxes send (a capture, a code, a bomb, "
           "a reboot: a dozen in 90 minutes) and the last column counts the controller's setup commands reaching "
           "their box.\n"]
    out.append("\n## 1. SL-4's arithmetic against the model\n")
    out.append(_ideal_vs_real(big, ideal, sizes))
    out.append("\n\n## 2. The firmware as it is, per game, layout, size and region\n")
    for game in games:
        for region in both:
            out.append(f"\n### {game}, {region}\n")
            out.append(compare_table(big, game, region, ["firmware"]))
    out.append("\n\n## 3. The ACK window stalls (SL-8): captures ACKed in the first 45 and the last 30 minutes\n")
    out.append(_ack_stall(big))
    out.append("\n\n## 4. How far the controller's frames reach with hop_limit 2 (SL-9)\n")
    out.append(_reach_table(sizes))
    out.append("\n\n## 5. Each idea on its own (EU868, Domination; every rule but `firmware` includes the ACK-gap fix)\n")
    for n in idea_sizes:
        out.append(f"\n### N = {n}\n")
        out.append(table(COMPARE_HEADERS, _pol_rows(ideas, "domination", "eu868", IDEAS, [n], layouts)))
    out.append("\n\n## 6. The candidates, every game, layout, size and region\n")
    for game in games:
        for region in both:
            out.append(f"\n### {game}, {region}\n")
            out.append(compare_table(big, game, region, CANDIDATES))
    cmds = [r for r in results if r["set"] == "cmds"]
    if cmds:
        out.append("\n\n## 7. The controller's commands (the scenario's setup CMDs; EU868, five seeds)\n")
        out.append(_cmd_table(cmds))
        out.append(PACE_NOTE)
        out.append(_pace_table(cmds))
    out.append("\n\n## 8. Sensitivity to the model's assumptions\n")
    out.append(_sens_table(sens, sens_n))
    head = [r for r in big if r["game"] == "domination" and r["layout"] == "all_in_range" and r["n"] == max(sizes)
            and r["region"] == "eu868" and r["seed"] == seeds[0]]
    for pol in ("firmware", "A_backoff", "D_backoff"):
        for r in head:
            if r["policy"] == pol:
                out.append(f"\n\n## 9. Per box: {pol}, all in range, N = {r['n']}, EU868, Domination, seed {r['seed']}\n")
                out.append(per_box_table(r, 40))
    return "\n".join(out) + "\n"


def build_report(lib: Optional[str] = None, seeds: Optional[list[int]] = None, minutes: int = 90,
                 workers: int = 0, quick: bool = False) -> tuple[str, list[Result]]:
    results = run_all(lib, seeds, minutes, workers, quick)
    return render(results), results


def load(path: str) -> list[Result]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: Optional[list[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m atalaia_sim.relay_report",
                                 description="Run the whole relay study and write its tables.")
    ap.add_argument("--lib", default=None, help="the core's shared library")
    ap.add_argument("--seeds", default="1,2,3")
    ap.add_argument("--minutes", type=int, default=90)
    ap.add_argument("--workers", type=int, default=0)
    ap.add_argument("--quick", action="store_true", help="two sizes, 12 minutes: a smoke test of the report")
    ap.add_argument("--out", default=None, help="write the Markdown here (default: stdout)")
    ap.add_argument("--json", default=None, help="also write every result as JSON here")
    ap.add_argument("--from-json", default=None, help="do not run anything: render the report from this JSON")
    ap.add_argument("--lbt-json", default=None, help="print SL-25's listen-before-talk tables from this JSON")
    args = ap.parse_args(argv)
    if args.lbt_json:
        print(lbt_section(load(args.lbt_json)))
        return 0
    if args.from_json:
        text, results = render(load(args.from_json)), []
    else:
        text, results = build_report(args.lib, [int(x) for x in args.seeds.split(",")], args.minutes, args.workers,
                                     args.quick)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
