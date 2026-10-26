#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The bench gate of listen-before-talk (decision SL-25), from the prober board's serial log.

    python3 tools/bench_lbt_gate.py prober.log             the table and PASS / FAIL
    python3 tools/bench_lbt_gate.py prober.log --gate 90   another gate (percent, default 90)
    python3 tools/bench_lbt_gate.py prober.log --cad-assumed-us 4000
    python3 tools/bench_lbt_gate.py --selftest             checks this tool on a made-up log

    python tools/bench_lbt_gate.py --capture COM3 --send "@lbt probe 300" --out prober.log
                                                           (Windows, pip install pyserial) types the
                                                           command on the board's console, saves what
                                                           it prints until the test ends, then reports

The AS923-TW proxy ("@lbt probe 100 proxy=as923"): AS923-TW's modulation (SF9/500 kHz) and CAD
settings run on 868.3 MHz, inside EU868 sub-band g, because a bench in Europe may not transmit on
921.5 MHz. The report then names the profile, the CAD settings under test (detPeak / detMin and
whether they are bench-proven) and the duty limit, and the tool REFUSES (exit 66) a proxy log whose
channel is not inside 868.0-868.6 MHz or touches 920-925 MHz.

The log is what a board flashed with the bench image (docker_fw.py bench) prints after
"@lbt probe" (docs/runbooks/lbt-bench-gate.md): lines "LBT,..." among whatever else the console
says. This script does not trust the firmware's own summary: it rebuilds every received frame's
window on the air (its RxDone time minus its airtime) from the "LBT,r" lines, places every
"LBT,p" probe against those windows, and counts. The firmware's totals are only compared at the
end, as a cross-check of the two implementations.

A probe is a hit if the radio's busy test (channel_busy) found the channel busy: its CAD saw a
preamble, or its receiver had a preamble or a valid header flagged. The gate (SL-25): more than
90 % of the probes inside frames are hits, and so are those in every tenth of the frame, so that
"busy" covers the frame and not only its first 12.5 ms. Probes between frames that found the
channel busy are false busy. A frame the prober did not receive (a gap in the sequence numbers)
leaves a stretch whose probes cannot be placed: they count for nothing, and so do those before
the first frame heard and after the last.

Exit status: 0 PASS, 1 FAIL, 2 not enough data to say, 64 a log with no probes.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

WHY_NAMES = {0: "free", 1: "cad", 2: "preamble", 3: "header", 4: "rx_done", 5: "error"}
BUSY = {1, 2, 3}
DECILES = 10
GATE_DEFAULT = 90.0
CAD_ASSUMED_US = 4000  # SL-25's constant, from the SX1261/2 datasheet "from memory"
MIN_FRAMES = 20  # fewer frames, or probes per tenth, than these cannot say PASS or FAIL
MIN_PER_DECILE = 20
WRAP = 1 << 32

LINE = re.compile(r"LBT,(\w+)(?:,(.*))?$")


@dataclass
class Frame:
    end: int  # unwrapped microseconds
    length: int
    seq: int  # -1: not one of the bench's frames
    airtime: int
    rssi: int
    lost_before: int

    @property
    def start(self) -> int:
        return self.end - self.airtime


@dataclass
class Probe:
    t: int
    why: int
    cad_us: int
    rearm_us: int


@dataclass
class Log:
    cfg: dict[str, str] = field(default_factory=dict)
    probes: list[Probe] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    sums: list[dict[str, str]] = field(default_factory=list)  # every "sum" line, as a dict
    tims: list[dict[str, str]] = field(default_factory=list)
    end: dict[str, str] = field(default_factory=dict)
    bad_lines: int = 0


def kv(text: str) -> dict[str, str]:
    out = {}
    for part in text.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def unwrap(prev: int | None, value: int) -> int:
    """The 32-bit microsecond clock made monotonic: the nearest value to the previous one."""
    if prev is None:
        return value
    return prev + (((value - prev) + WRAP // 2) % WRAP - WRAP // 2)


def parse(lines) -> Log:
    log = Log()
    last = None
    for raw in lines:
        m = LINE.search(raw.strip().replace("\x1b[0m", ""))
        if not m:
            continue
        kind, rest = m.group(1), m.group(2) or ""
        f = rest.split(",") if rest else []
        try:
            if kind == "p" and len(f) >= 4:
                t = unwrap(last, int(f[0]))
                last = t
                log.probes.append(Probe(t, int(f[1]), int(f[2]), int(f[3])))
            elif kind == "r" and len(f) >= 7:
                t = unwrap(last, int(f[1]))
                last = max(last or t, t) if last is not None else t
                log.frames.append(Frame(t, int(f[2]), int(f[3]), int(f[4]), int(f[5]), int(f[6])))
            elif kind == "cfg":
                log.cfg.update(kv(rest))
            elif kind == "sum":
                log.sums.append(kv(rest))
            elif kind == "tim":
                log.tims.append(kv(rest))
            elif kind == "end":
                log.end = kv(rest)
        except ValueError:
            log.bad_lines += 1
    return log


@dataclass
class Result:
    frames: int = 0
    lost: int = 0
    in_n: list[int] = field(default_factory=lambda: [0] * DECILES)
    in_hit: list[int] = field(default_factory=lambda: [0] * DECILES)
    seg_n: list[int] = field(default_factory=lambda: [0] * 3)
    seg_hit: list[int] = field(default_factory=lambda: [0] * 3)
    by_why: dict[int, int] = field(default_factory=lambda: {1: 0, 2: 0, 3: 0})
    out_n: int = 0
    out_busy: int = 0
    amb: int = 0
    err: int = 0
    unjudged: int = 0  # after the last frame heard
    airtime_min: int = 0
    airtime_max: int = 0


def classify(log: Log, sym_us: int) -> Result:
    """The firmware's rule (radio/lbt_stats.c) on the whole log."""
    r = Result()
    frames = sorted(log.frames, key=lambda f: f.end)
    probes = sorted(log.probes, key=lambda p: p.t)
    if frames:
        r.airtime_min = min(f.airtime for f in frames)
        r.airtime_max = max(f.airtime for f in frames)
    i = 0
    for k, fr in enumerate(frames):
        # Probes up to this frame's end, not yet judged.
        while i < len(probes) and probes[i].t <= fr.end:
            p = probes[i]
            i += 1
            if p.why == 5:
                r.err += 1
                continue
            if p.t < fr.start:
                if fr.lost_before > 0 or k == 0:
                    r.amb += 1
                else:
                    r.out_n += 1
                    r.out_busy += p.why in BUSY
                continue
            off = p.t - fr.start
            d = min(DECILES - 1, off * DECILES // fr.airtime) if fr.airtime else 0
            seg = 0 if off < sym_us * 49 // 4 else 1 if off < sym_us * 81 // 4 else 2
            hit = p.why in BUSY
            r.in_n[d] += 1
            r.seg_n[seg] += 1
            if hit:
                r.in_hit[d] += 1
                r.seg_hit[seg] += 1
                r.by_why[p.why] += 1
        r.frames += 1
        r.lost += fr.lost_before
    r.unjudged = len(probes) - i
    return r


PROXY_PROFILE = "as923-eu868"
PROXY_BAND = (868_000_000, 868_600_000)  # EU868 sub-band g
AS923_BAND = (920_000_000, 925_000_000)


def proxy_channel_ok(freq: int, bw: int) -> bool:
    """The whole channel inside sub-band g and nowhere near AS923 (firmware: lbt_profile_channel_ok)."""
    lo, hi = freq - bw // 2, freq + bw // 2
    return PROXY_BAND[0] <= lo and hi <= PROXY_BAND[1] and not (hi >= AS923_BAND[0] and lo <= AS923_BAND[1])


def pct(a: int, b: int) -> float:
    return 100.0 * a / b if b else 0.0


def timing(log: Log) -> dict[str, float]:
    cads = [p.cad_us for p in log.probes if p.cad_us > 0]
    rearms = [p.rearm_us for p in log.probes if p.rearm_us > 0]
    out: dict[str, float] = {"n": len(cads)}
    if cads:
        out.update(avg=sum(cads) / len(cads), min=min(cads), max=max(cads), p95=sorted(cads)[int(0.95 * (len(cads) - 1))])
    if rearms:
        out.update(re_avg=sum(rearms) / len(rearms), re_max=max(rearms))
    return out


def report(log: Log, gate: float, cad_assumed_us: int, out=sys.stdout) -> int:
    def p(*a):
        print(*a, file=out)

    sf = int(log.cfg.get("sf", "7"))
    bw = int(log.cfg.get("bw", "125000"))
    freq = int(log.cfg.get("freq", "0"))
    sym_us = int(log.cfg.get("sym_us", str((1 << sf) * 1_000_000 // bw)))
    profile = log.cfg.get("profile", "")
    proxy = profile == PROXY_PROFILE
    if proxy and not proxy_channel_ok(freq, bw):
        p(f"REFUSED: the log says profile {profile} on {freq / 1e6:.3f} MHz / {bw // 1000} kHz wide: the "
          f"proxy's channel must lie inside {PROXY_BAND[0] / 1e6:.1f}-{PROXY_BAND[1] / 1e6:.1f} MHz "
          f"(EU868 sub-band g) and clear of {AS923_BAND[0] / 1e6:.0f}-{AS923_BAND[1] / 1e6:.0f} MHz. "
          "Do not transmit on it; flash the bench image from this checkout.")
        return 66
    r = classify(log, sym_us)
    p(f"Listen-before-talk bench gate (SL-25): "
      f"{'profile ' + profile + ', ' if profile else ''}region {log.cfg.get('region', '?')}"
      f"{', modulation of ' + log.cfg['mod'] if 'mod' in log.cfg else ''}, "
      f"{freq / 1e6:.3f} MHz, SF{sf} / {bw // 1000} kHz, symbol {sym_us} us")
    if "det_peak" in log.cfg:
        proven = log.cfg.get("peak_proven", "0") == "1"
        duty = int(log.cfg.get("duty_ppm", "0")) / 10000
        p(f"CAD under test: {log.cfg.get('cad_sym', '?')} symbols, detPeak {log.cfg['det_peak']} "
          f"({'proven on a board' if proven else 'UNPROVEN: this run tests it'}), detMin {log.cfg.get('det_min', '?')}; "
          f"duty limit {duty:g} % of the hour, {log.cfg.get('limit_dbm', '?')} dBm, "
          f"TX power {log.cfg.get('tx_dbm', '?')} dBm conducted")
    p(f"Log: {len(log.probes)} probes, {len(log.frames)} frames received"
      f"{', ended: ' + log.end.get('reason', '?') if log.end else ', no end line (cut short?)'}")
    if not log.probes:
        p("No probes in the log: is it the prober's (\"@lbt probe\"), and is the line prefix LBT, intact?")
        return 64

    if not log.frames:
        # No frame at all: a quiet channel, which is the false-detect measurement SL-25 asks for.
        judged = [pr for pr in log.probes if pr.why != 5]
        busy = sum(pr.why in BUSY for pr in judged)
        by = {w: sum(pr.why == w for pr in judged) for w in (1, 2, 3)}
        span = (log.probes[-1].t - log.probes[0].t) / 1e6
        p(f"No frame was received: {len(judged)} probes over {span:.0f} s on a channel that was quiet "
          f"(if nothing else was transmitting): {busy} found it busy ({pct(busy, len(judged)):.3f} %: "
          f"CAD {by[1]}, preamble flag {by[2]}, header flag {by[3]}), {len(log.probes) - len(judged)} radio errors.")
        t = timing(log)
        if t.get("n"):
            p(f"CAD: {int(t['n'])} run, {t['avg'] / 1000:.2f} ms average (max {t['max'] / 1000:.2f}); "
              f"SL-25 assumed {cad_assumed_us / 1000:.1f} ms.")
        p("INCONCLUSIVE for the gate (no frames); this is the channel's false-detect rate.")
        return 2

    total_n, total_hit = sum(r.in_n), sum(r.in_hit)
    sent = None
    if log.frames:
        seqs = [f.seq for f in log.frames if f.seq >= 0]
        if seqs:
            sent = max(seqs) - min(seqs) + 1
    p(f"Frames: {r.frames} received" + (f" of {sent} sent in the span ({pct(r.frames, sent):.0f} %), "
      f"{r.lost} missed by sequence gap" if sent else "")
      + (f"; airtime {r.airtime_min / 1000:.1f}-{r.airtime_max / 1000:.1f} ms" if r.frames else ""))
    p("")
    p("  tenth of frame   probes   busy   hit rate")
    worst = 100.0
    thin = False
    air = (r.airtime_min + r.airtime_max) / 2 if r.frames else 0
    for d in range(DECILES):
        rate = pct(r.in_hit[d], r.in_n[d])
        lo, hi = air * d / DECILES / 1000, air * (d + 1) / DECILES / 1000
        flag = ""
        if r.in_n[d] < MIN_PER_DECILE:
            thin = True
            flag = "  (too few)"
        elif rate <= gate:
            flag = "  < gate"
        if r.in_n[d]:
            worst = min(worst, rate)
        p(f"  {d * 10:3d}-{d * 10 + 10:3d} % ({lo:5.1f}-{hi:5.1f} ms) {r.in_n[d]:6d} {r.in_hit[d]:6d}  {rate:6.1f} %{flag}")
    p(f"  {'whole frame':<24} {total_n:6d} {total_hit:6d}  {pct(total_hit, total_n):6.1f} %")
    p("")
    names = ("preamble (0-12.25 symbols)", "header (next 8 symbols)", "payload (rest)")
    for s in range(3):
        p(f"  {names[s]:<28} {r.seg_n[s]:6d} {r.seg_hit[s]:6d}  {pct(r.seg_hit[s], r.seg_n[s]):6.1f} %")
    p(f"  found busy by: CAD {r.by_why[1]}, receiver's preamble flag {r.by_why[2]}, "
      f"receiver's header-valid flag {r.by_why[3]}")
    p(f"  false busy (probes between frames): {r.out_busy} of {r.out_n} ({pct(r.out_busy, r.out_n):.2f} %); "
      f"unplaced (a frame was missed, or before the first / after the last): {r.amb + r.unjudged}; "
      f"radio errors: {r.err}")
    p("")

    t = timing(log)
    if t.get("n"):
        ratio = t["avg"] / cad_assumed_us
        p(f"CAD: {int(t['n'])} run, {t['avg'] / 1000:.2f} ms average (min {t['min'] / 1000:.2f}, p95 "
          f"{t['p95'] / 1000:.2f}, max {t['max'] / 1000:.2f}); SL-25 assumed {cad_assumed_us / 1000:.1f} ms: "
          f"{'within' if t['avg'] <= cad_assumed_us else 'OVER'} ({ratio:.2f}x). "
          f"SL-25's CAD energy (6-35 uAh/h, 0.7-2.4 % of TX energy) scales to "
          f"{6 * ratio:.0f}-{35 * ratio:.0f} uAh/h, {0.7 * ratio:.1f}-{2.4 * ratio:.1f} % at {ratio:.2f}x, "
          f"if its 6 mA holds (measure that too).")
    else:
        p("CAD: none ran (every probe was answered by the receiver's flags).")
    if "re_avg" in t:
        p(f"RX re-arm after a CAD: {t['re_avg'] / 1000:.2f} ms average, {t['re_max'] / 1000:.2f} ms max "
          "(the radio is deaf from the CAD's start to its end).")
    p("")

    # Cross-checks and warnings: what makes the table worth less than it looks.
    warns = []
    if sent and pct(r.frames, sent) < 80:
        warns.append(f"only {pct(r.frames, sent):.0f} % of the frames were received: the CAD and the re-arm "
                     "may be costing the prober its frames, and their probes are unplaced")
    if log.sums:
        s = log.sums[-1]
        try:
            if (int(s["in"]), int(s["hit"])) != (total_n, total_hit) and len(log.probes) and not log.end.get("reason") == "stop":
                warns.append(f"the firmware's last summary says {s['in']} in-frame probes, {s['hit']} hits; "
                             f"this script counted {total_n}, {total_hit}: log lines were lost or the "
                             "last frames are missing from it")
        except (KeyError, ValueError):
            pass
    if log.tims:
        tm = log.tims[-1]
        if int(tm.get("lines_dropped", "0")) or int(tm.get("probes_dropped", "0")):
            warns.append(f"the firmware dropped {tm.get('lines_dropped', '0')} log lines and "
                         f"{tm.get('probes_dropped', '0')} probes: the log is incomplete")
    if log.bad_lines:
        warns.append(f"{log.bad_lines} LBT lines could not be read")
    for w in warns:
        p(f"WARNING: {w}")

    enough = r.frames >= MIN_FRAMES and not thin
    ok = total_n > 0 and pct(total_hit, total_n) > gate and worst > gate
    if not enough:
        p(f"INCONCLUSIVE: need at least {MIN_FRAMES} frames and {MIN_PER_DECILE} probes in every tenth "
          f"(have {r.frames} frames); the rate so far is {pct(total_hit, total_n):.1f} %, worst tenth {worst:.1f} %.")
        return 2
    peak = log.cfg.get("det_peak")
    if ok:
        p(f"PASS: {pct(total_hit, total_n):.1f} % of the probes inside frames found the channel busy, "
          f"every tenth of the frame above {gate:g} % (worst {worst:.1f} %): the busy test covers the whole frame"
          + (f", with detPeak {peak} at SF{sf} / {bw // 1000} kHz." if proxy and peak else "."))
        return 0
    p(f"FAIL: {pct(total_hit, total_n):.1f} % of the probes inside frames found the channel busy, worst "
      f"tenth {worst:.1f} % (gate {gate:g} %): the busy test does not cover the whole frame; "
      "SL-25's answer becomes \"don't\".")
    if proxy:
        p(f"detPeak {peak} did not hold at SF{sf} / {bw // 1000} kHz. Sweep it (the same run on both boards, "
          f"one value at a time): \"@lbt probe 100 proxy=as923 peak=N\" and \"@lbt tx 100 proxy=as923 peak=N\"; "
          "the tx side ignores peak=, so give it on the prober. See docs/runbooks/lbt-bench-gate.md.")
    return 1


# ---- the self-test: a made-up log, built the way the firmware's would be -------------------------


PROXY_CFG = ("LBT,cfg,role=probe,profile=as923-eu868,region=eu868,mod=as923-tw,freq={freq},sf=9,bw=500000,"
             "sym_us=1024,cad_sym=2,det_peak=23,det_min=10,peak_proven=0,duty_ppm=10000,limit_dbm=14,tx_dbm=-9")


def synthetic(blind_after_us: int | None, frames: int = 40, seed: int = 7, wrap: bool = False,
              proxy_freq: int | None = None) -> list[str]:
    """A prober log of `frames` frames of 92.416 ms. A probe finds the channel busy inside a frame
    if its position is before blind_after_us (a CAD that sees only the preamble: 12544) or always
    (None). Probes every 2-5 ms; lost frames none; the clock may start just before its wrap."""
    import random

    rng = random.Random(seed)
    air, sym = (82176 if proxy_freq else 92416), 1024
    t = (WRAP - 3_000_000) if wrap else 1_000_000
    cfg = PROXY_CFG.format(freq=proxy_freq) if proxy_freq else \
        f"LBT,cfg,role=probe,region=eu868,freq=869525000,sf=7,bw=125000,sym_us={sym}"
    lines = [cfg,
             "LBT,start,role=probe,frames=%d,gap_us=2000-5000" % frames,
             "I (1234) lbt: some other log line"]
    seq = 0
    probes_in = hits_in = 0
    next_frame_end = t + 400_000 + air
    while seq < frames:
        end = next_frame_end
        start = end - air
        while t < end:
            if t >= start:
                off = t - start
                busy = blind_after_us is None or off < blind_after_us
                if blind_after_us is None:
                    why = 1 if off < 12544 else 2 if off < 20736 else 3
                else:
                    why = 1 if busy else 0
                probes_in += 1
                hits_in += busy
            else:
                why = 0
            cad = 3500 + rng.randrange(0, 500) if why in (0, 1) else 0
            lines.append(f"LBT,p,{t % WRAP},{why},{cad},{400 if cad else 0}")
            t += rng.randrange(2000, 5001)
        lines.append(f"LBT,r,{seq + 1},{end % WRAP},{52},{seq},{air},-37,0")
        seq += 1
        next_frame_end = end + 300_000 + rng.randrange(0, 400_000) + air
    lines.append(f"LBT,sum,frames={frames},lost=0,in={probes_in},hit={hits_in},hit_pm=0,out=0,out_busy=0,amb=0,err=0")
    lines.append("LBT,tim,cad_n=1,cad_avg_us=3700,cad_min_us=3500,cad_max_us=4000,rearm_avg_us=400,"
                 "rearm_max_us=400,probes_dropped=0,lines_dropped=0")
    lines.append(f"LBT,end,role=probe,reason=frames,frames={frames}")
    return lines


def selftest() -> int:
    import io

    failures = 0

    def check(cond: bool, what: str) -> None:
        nonlocal failures
        if not cond:
            failures += 1
            print(f"selftest FAIL: {what}", file=sys.stderr)

    for wrap in (False, True):
        # Covers the whole frame: PASS.
        log = parse(synthetic(None, wrap=wrap))
        buf = io.StringIO()
        check(report(log, 90.0, 4000, buf) == 0 and "PASS" in buf.getvalue(), f"full coverage passes (wrap={wrap})")
        r = classify(log, 1024)
        check(r.frames == 40 and sum(r.in_n) > 40 * 20 and sum(r.in_hit) == sum(r.in_n), "all in-frame probes hit")
        check(r.out_busy == 0 and r.out_n > 100, "no false busy")
        check(all(n >= 20 for n in r.in_n), "every tenth has probes")
        # A CAD that sees only the preamble: FAIL, with the cliff in the table.
        log = parse(synthetic(12544, wrap=wrap))
        buf = io.StringIO()
        code = report(log, 90.0, 4000, buf)
        check(code == 1 and "FAIL" in buf.getvalue(), f"preamble-only fails (wrap={wrap})")
        r = classify(log, 1024)
        check(pct(sum(r.in_hit), sum(r.in_n)) < 20 and r.in_hit[9] == 0, "the payload tenths are blind")
    # The AS923-TW proxy on 868.3 MHz: the report names the profile, the CAD under test, the duty limit.
    log = parse(synthetic(None, proxy_freq=868_300_000))
    buf = io.StringIO()
    code = report(log, 90.0, 4000, buf)
    text = buf.getvalue()
    check(code == 0 and "PASS" in text and "detPeak 23 at SF9 / 500 kHz" in text, "the proxy passes and says detPeak")
    check("profile as923-eu868" in text and "868.300 MHz, SF9 / 500 kHz" in text, "the proxy's profile and channel are reported")
    check("UNPROVEN" in text and "duty limit 1 % of the hour" in text and "TX power -9 dBm" in text,
          "the proxy's CAD status and duty limit are reported")
    log = parse(synthetic(12544, proxy_freq=868_300_000))
    buf = io.StringIO()
    check(report(log, 90.0, 4000, buf) == 1 and "peak=N" in buf.getvalue(), "a failing proxy points at the detPeak sweep")
    # The proxy is refused outside sub-band g, and on any AS923 frequency.
    for bad in (921_500_000, 868_600_000, 868_249_999, 868_350_001, 869_525_000, 920_000_000):
        buf = io.StringIO()
        check(report(parse(synthetic(None, proxy_freq=bad)), 90.0, 4000, buf) == 66 and "REFUSED" in buf.getvalue(),
              f"the proxy on {bad} Hz is refused")
    check(proxy_channel_ok(868_300_000, 500_000) and proxy_channel_ok(868_250_000, 500_000)
          and proxy_channel_ok(868_350_000, 500_000), "the proxy's channel edges")
    # A log of the build's own profile without the new fields (older firmware) still reads.
    check(report(parse(synthetic(None)), 90.0, 4000, io.StringIO()) == 0, "an older log still reports")
    # Too little data.
    log = parse(synthetic(None, frames=5))
    buf = io.StringIO()
    check(report(log, 90.0, 4000, buf) == 2 and "INCONCLUSIVE" in buf.getvalue(), "5 frames cannot pass")
    # A quiet channel: no frames, the false-detect rate.
    quiet = ["LBT,cfg,role=probe,region=eu868,freq=869525000,sf=7,bw=125000,sym_us=1024"]
    quiet += [f"LBT,p,{1000 + 3000 * i},{1 if i % 100 == 0 else 0},3600,400" for i in range(1000)]
    buf = io.StringIO()
    check(report(parse(quiet), 90.0, 4000, buf) == 2 and "1.000 %" in buf.getvalue(), "a quiet channel's false detect")
    # A log with no probes.
    check(report(parse(["nothing here"]), 90.0, 4000, io.StringIO()) == 64, "an empty log")
    # The CAD against SL-25's 4 ms.
    buf = io.StringIO()
    report(parse(synthetic(None)), 90.0, 3000, buf)
    check("OVER" in buf.getvalue(), "a CAD over the assumed time is called out")
    # A lost frame leaves its probes unplaced, not false busy.
    lines = synthetic(None)
    idx = [i for i, ln in enumerate(lines) if ln.startswith("LBT,r,")]
    del lines[idx[10]]  # the 11th frame (seq 10) was not received
    log = parse(lines)
    # The frame after the removed one says one was lost before it.
    nxt = [f for f in log.frames if f.seq == 11][0]  # sequence 10 never arrived
    nxt.lost_before = 1
    r = classify(log, 1024)
    check(r.amb > 0 and r.out_busy == 0, "a lost frame's probes are unplaced")
    return 1 if failures else 0


def capture(port_name: str, commands: list[str], out_path: str, seconds: float) -> None:
    """Types each command on the board's console, then saves what it prints until an "LBT,end"
    line (the test is over) or `seconds` pass. The port is opened without raising DTR or RTS, which
    would reset an ESP32-S3 (as tools/serial_bridge.py)."""
    import time

    import serial  # noqa: PLC0415 (pyserial)

    port = serial.serial_for_url(port_name, do_not_open=True, baudrate=115200, timeout=0.1)
    port.dtr = False
    port.rts = False
    port.open()
    deadline = time.monotonic() + seconds
    buf = b""
    with open(out_path, "w", encoding="utf-8") as out:
        sent = False
        ended = False
        while time.monotonic() < deadline and not ended:
            if not sent:
                for cmd in commands:
                    for ch in cmd + "\n":
                        port.write(ch.encode())
                        time.sleep(0.01)  # the console takes a character at a time
                    time.sleep(0.3)
                sent = True
            buf += port.read(4096)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", errors="replace").rstrip("\r")
                out.write(text + "\n")
                if text.startswith("LBT,end") or " LBT,end" in text:
                    ended = True
                if text.startswith("LBT,sum") or text.startswith("LBT,tsum") or text.startswith("LBT,end") \
                        or text.startswith("LBT,start") or not text.startswith("LBT,"):
                    print(text, flush=True)
        out.flush()
    if not ended:
        print(f"bench_lbt_gate: no LBT,end line within {seconds:g} s; what came is in {out_path}", file=sys.stderr)
    port.close()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("log", nargs="?", help="the prober's serial log (a text file)")
    ap.add_argument("--capture", metavar="PORT", help="read the board on this serial port (COM3, /dev/ttyACM0)")
    ap.add_argument("--send", action="append", default=[], metavar="LINE",
                    help="a console line to type first, e.g. \"@lbt probe 300\" (repeatable)")
    ap.add_argument("--out", default="lbt.log", help="where --capture saves the log (default lbt.log)")
    ap.add_argument("--seconds", type=float, default=900.0, help="--capture gives up after this long (900)")
    ap.add_argument("--gate", type=float, default=GATE_DEFAULT, help="hit rate to beat, percent (default 90)")
    ap.add_argument("--cad-assumed-us", type=int, default=CAD_ASSUMED_US, help="SL-25's CAD time (default 4000)")
    ap.add_argument("--selftest", action="store_true", help="check this script on a made-up log")
    args = ap.parse_args(argv)
    if args.selftest:
        code = selftest()
        print("bench_lbt_gate: selftest ok" if code == 0 else "bench_lbt_gate: selftest FAILED")
        return code
    if args.capture:
        capture(args.capture, args.send, args.out, args.seconds)
        args.log = args.out
        if not any("LBT,p," in ln for ln in Path(args.out).read_text(encoding="utf-8", errors="replace").splitlines()):
            return 0  # the transmitter's log: its own lines say what was sent
    if not args.log:
        ap.error("the prober's log file, --capture, or --selftest")
    text = Path(args.log).read_text(encoding="utf-8", errors="replace").splitlines()
    return report(parse(text), args.gate, args.cad_assumed_us)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
