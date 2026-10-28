#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The projected score's bench report (decision BSC-2, docs/runbooks/projected-score-bench.md).

    python3 tools/bench_projected_score.py report controller.log [--points 1]
    python3 tools/bench_projected_score.py poll --token read-or-gm-token [--url http://127.0.0.1:8080] \\
                                               [--game N] [--seconds 300] [--out poll.csv]
    python3 tools/bench_projected_score.py --selftest

`report` reads the controller's log (for the bench container: `docker logs atalaia-controller-bench`)
and rebuilds the table of the runbook from the lines the controller writes for each box's STATE:

    projection node 4 team red: projected 13, reported 13, drift +0 (9800 ms after its last STATE)

Drift is the projection minus what the box then said it had (0 = the projection was right). It
prints how many STATEs were compared, how many were off, the largest drift, the histogram, and PASS or
FAIL against the runbook's gate: never more than one scoring tick (`--points`) off, and at most
`--off-pct` (default 20) percent of the STATEs off. `poll` records GET /games/{id}/score
(`teams` and `projected`) every second to a CSV, for the plot of the two curves.
Only the standard library is needed.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
import urllib.request
from collections import Counter

LINE = re.compile(r"projection node (\d+) team (\S+): projected (-?\d+), reported (-?\d+), "
                  r"drift ([+-]\d+) \((\d+) ms after its last STATE\)")


def parse(text: str) -> list[dict]:
    """The drift samples in a log, in order."""
    out = []
    for m in LINE.finditer(text):
        node, team, projected, reported, drift, age = m.groups()
        out.append({"node": int(node), "team": team, "projected": int(projected),
                    "reported": int(reported), "drift": int(drift), "age_ms": int(age)})
    return out


def summarise(samples: list[dict], points: int, off_pct: float) -> tuple[str, bool]:
    """The report text and whether the gate passes."""
    n = len(samples)
    if n == 0:
        return "no projection lines found: is the game's mode opted in and a box holding?", False
    off = [s for s in samples if s["drift"] != 0]
    worst = max(abs(s["drift"]) for s in samples)
    hist = Counter(s["drift"] for s in samples)
    ahead = sum(1 for s in off if s["drift"] > 0)
    lines = [f"STATEs compared : {n}",
             f"off             : {len(off)} ({100 * len(off) / n:.1f} %), {ahead} ahead of the box, "
             f"{len(off) - ahead} behind",
             f"largest drift   : {worst} point(s) (one tick = {points})",
             "histogram       : " + ", ".join(f"{d:+d}: {hist[d]}" for d in sorted(hist)),
             f"mean STATE gap  : {sum(s['age_ms'] for s in samples) / n / 1000:.1f} s"]
    ok = worst <= points and 100 * len(off) / n <= off_pct
    lines.append(f"gate            : {'PASS' if ok else 'FAIL'} (never more than one tick off, at most "
                 f"{off_pct:g} % of the STATEs off)")
    return "\n".join(lines), ok


def poll(url: str, token: str, game: int | None, seconds: int, out: str) -> None:
    def get(path: str):
        req = urllib.request.Request(url + "/api/v1" + path, headers={"Authorization": "Bearer " + token})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    if game is None:
        game = get("/controller")["live_game"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "game_time_ms", "team", "reported", "projected"])
        start = time.time()
        while time.time() - start < seconds:
            tick = time.time()
            score = get(f"/games/{game}/score")
            game_ms = get(f"/games/{game}")["game_time_ms"]
            for team, value in score["teams"].items():
                w.writerow([f"{tick - start:.1f}", game_ms, team, value, (score.get("projected") or {}).get(team, "")])
            f.flush()
            time.sleep(max(0.0, 1.0 - (time.time() - tick)))
    print(f"wrote {out}")


def selftest() -> int:
    log = "\n".join([
        "INFO atalaia_controller.engine: projection node 4 team red: projected 3, reported 3, drift +0 (15000 ms after its last STATE)",
        "INFO atalaia_controller.engine: projection node 4 team red: projected 6, reported 5, drift +1 (14900 ms after its last STATE)",
        "noise line",
        "INFO atalaia_controller.engine: projection node 4 team red: projected 8, reported 8, drift +0 (15100 ms after its last STATE)",
        "INFO atalaia_controller.engine: projection node 5 team blue: projected 2, reported 3, drift -1 (15000 ms after its last STATE)",
    ])
    samples = parse(log)
    assert len(samples) == 4 and samples[1]["drift"] == 1 and samples[3]["team"] == "blue", samples
    text, ok = summarise(samples, 1, 50)
    assert ok and "largest drift   : 1 point(s)" in text and "-1: 1" in text, text
    text, ok = summarise(samples, 1, 25)
    assert not ok, text  # 2 of 4 off is 50 %
    text, ok = summarise(samples + [{"node": 4, "team": "red", "projected": 9, "reported": 6, "drift": 3,
                                     "age_ms": 15000}], 1, 90)
    assert not ok, text  # one STATE three points off
    assert summarise([], 1, 20)[1] is False
    print("bench_projected_score: selftest ok")
    return 0


def main() -> int:
    if "--selftest" in sys.argv[1:]:
        return selftest()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="the drift table from the controller's log")
    r.add_argument("log")
    r.add_argument("--points", type=int, default=1, help="points per tick: the largest drift allowed")
    r.add_argument("--off-pct", type=float, default=20.0, help="the share of STATEs allowed to be off")
    p = sub.add_parser("poll", help="record the score and its projection every second to a CSV")
    p.add_argument("--token", required=True)
    p.add_argument("--url", default="http://127.0.0.1:8080")
    p.add_argument("--game", type=int)
    p.add_argument("--seconds", type=int, default=300)
    p.add_argument("--out", default="poll.csv")
    args = ap.parse_args()
    if args.cmd == "poll":
        poll(args.url, args.token, args.game, args.seconds, args.out)
        return 0
    with open(args.log, encoding="utf-8", errors="replace") as f:
        text, ok = summarise(parse(f.read()), args.points, args.off_pct)
    print(text)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
