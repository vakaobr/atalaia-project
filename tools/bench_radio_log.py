#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Reads the radio_stats lines of a Field Box (and a modem) and prints what the field test asks (decision SL-18).

    python tools/bench_radio_log.py box.log                     a recorded serial log
    python tools/bench_radio_log.py box.log --boxes 5           ... compared with a field of 5
    python tools/bench_radio_log.py --port COM3 --minutes 90 --tee box.log
    python tools/bench_radio_log.py box-*.log --boxes 5          one log per box of a field

Each box logs, once a minute while it is in a game and once more when the game ends, one line

    I (123456) radio_stats: {"t_s":120,"game":4243,"node":7,"sent":9,"retries":31,...}

(firmware/esp32/main/radio/radio_stats.h). This tool takes every such line out of the text,
whatever else surrounds it (ANSI colour, other tags, binary noise), and prints, per box and game,
a per-minute table, a summary (retries per event, % acked, the duty-cycle budget's slope and the
minutes until it is empty, refusals) and the model's expectation for the field size.

Live port: the box's USB-Serial-JTAG port. It is opened without raising DTR or RTS (that would
reset the board), read only. On the bench run it with the Windows Python that has pyserial (the
flasher's venv), with the port closed in every other program. COM4, the modem, is owned by
tools/serial_bridge.py (com_bridge.py): its USB link carries the controller's frames, never logs,
so the modem's own radio_stats lines exist only on its UART0 log console; if you record that, this
tool reads them too (role "modem"). Do not point --port at the bridge's TCP port: the bridge serves one client at a
time and a new one replaces the controller's. Otherwise the modem's STATUS replies to the controller (duty_ms, rx, tx,
tx_fail; protocol/usb-modem.md) are the modem's counters.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

LINE = re.compile(r"radio_stats:\s*(\{.*\})")

# What the study (docs/review/relay-study-results.md, EU868, Domination, all in range, 90 minutes,
# median of 3 seeds) says for a field of N boxes: (air % mean, captures ACKed %, refused per box).
# "built" is rule A_backoff, Amendment 13 (section 6, and section 10 for 20 and 30 boxes against the
# real code); "firmware" the link before it. The study has no row below 5 boxes.
STUDY = {
    5: {"firmware": (10.4, 18.7, 384.8), "built": (2.9, 100.0, 0.0)},
    10: {"firmware": (11.0, 10.3, 300.8), "built": (2.7, 100.0, 0.0)},
    20: {"firmware": (10.7, 14.9, 294.1), "built": (2.65, 99.7, 0.0)},
    30: {"firmware": (11.9, 13.9, 933.2), "built": (2.68, 99.2, 0.0)},
}
# SL-4's arithmetic: one box's own STATE every 15 s plus one relay of every other box's.
SL4_PCT_PER_BOX_EU868 = 0.68

DELTAS = (
    "sent", "retries", "acked", "expired", "relayed", "relay_skipped", "relay_cancelled",
    "relay_no_slot", "dup", "tx_refused",
)  # fmt: skip


def parse(text: str) -> list[dict]:
    """Every radio_stats object in the text, in order; a line that is not JSON is skipped."""
    out = []
    for raw in text.splitlines():
        m = LINE.search(raw)
        if not m:
            continue
        try:
            obj = json.loads(m.group(1))
        except ValueError:
            continue  # cut by the port's start or a torn line
        if isinstance(obj, dict) and "t_s" in obj:
            out.append(obj)
    return out


def split(records: list[dict]) -> dict[tuple, list[dict]]:
    """Per source: (role, node, game), and a new run when a counter goes back (a reboot)."""
    runs: dict[tuple, list[dict]] = {}
    last: dict[tuple, dict] = {}
    serial: dict[tuple, int] = {}
    for r in records:
        base = (r.get("role", "box"), r.get("node"), r.get("game"))
        prev = last.get(base)
        if prev is not None and (r["t_s"] < prev["t_s"] or r.get("sent", 0) < prev.get("sent", 0)):
            serial[base] = serial.get(base, 0) + 1
        key = base + (serial.get(base, 0),)
        runs.setdefault(key, []).append(r)
        last[base] = r
    return runs


def slope_ms_per_min(rows: list[dict]) -> float | None:
    """Least-squares slope of duty_remaining_ms against time, per minute; None if unknown."""
    pts = [(r["t_s"], r["duty_remaining_ms"]) for r in rows if r.get("duty_remaining_ms", -1) >= 0]
    if len(pts) < 3:
        return None
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    den = sum((p[0] - mx) ** 2 for p in pts)
    if den == 0:
        return None
    return sum((p[0] - mx) * (p[1] - my) for p in pts) / den * 60.0


def box_report(key: tuple, rows: list[dict], boxes: int | None) -> str:
    _, node, game, _ = key
    lines = [f"== box node {node}, game {game}: {len(rows)} lines, t_s {rows[0]['t_s']}..{rows[-1]['t_s']}"]
    head = (
        f"{'min':>4} {'t_s':>6} {'sent':>5} {'retry':>5} {'acked':>5} {'exp':>4} {'relay':>6} "
        f"{'skip':>5} {'canc':>5} {'noslot':>6} {'dup':>5} {'refus':>5} {'duty s':>7} {'nbr':>3}"
    )
    lines.append(head)
    prev = dict.fromkeys(DELTAS, 0)
    t0 = rows[0]["t_s"]
    for r in rows:
        d = {k: r.get(k, 0) - prev[k] for k in DELTAS}
        prev = {k: r.get(k, 0) for k in DELTAS}
        duty = r.get("duty_remaining_ms", -1)
        duty_s = "?" if duty < 0 else f"{duty / 1000:.1f}"
        mark = "*" if r.get("final") else " "
        lines.append(
            f"{(r['t_s'] - t0) / 60:>4.0f} {r['t_s']:>6} {d['sent']:>5} {d['retries']:>5} {d['acked']:>5} "
            f"{d['expired']:>4} {d['relayed']:>6} {d['relay_skipped']:>5} {d['relay_cancelled']:>5} "
            f"{d['relay_no_slot']:>6} {d['dup']:>5} {d['tx_refused']:>5} {duty_s:>7} "
            f"{r.get('neighbours', 0):>3}{mark}"
        )
    lines.append("(per-minute deltas; * = the closing line of the game)")
    last = rows[-1]
    sent = last.get("sent", 0)
    lines.append("-- summary")
    if sent:
        lines.append(
            f"events sent {sent}; retries per event {last.get('retries', 0) / sent:.2f}; "
            f"acked {100.0 * last.get('acked', 0) / sent:.1f} %; expired {last.get('expired', 0)}"
        )
    else:
        lines.append("no event sent yet (retries per event and % acked need at least one)")
    own = last.get("sent", 0) + last.get("states", 0) + last.get("hellos", 0) + last.get("retries", 0)
    lines.append(
        f"relayed {last.get('relayed', 0)} (skipped {last.get('relay_skipped', 0)}, cancelled "
        f"{last.get('relay_cancelled', 0)}, no slot {last.get('relay_no_slot', 0)}); the box's own "
        f"frames {own} (events+resends+STATE+HELLO); duplicates heard {last.get('dup', 0)}; "
        f"neighbours {last.get('neighbours', 0)}"
    )
    lines.append(f"refusals by the duty-cycle budget (tx_refused): {last.get('tx_refused', 0)}")
    duty = [r["duty_remaining_ms"] for r in rows if r.get("duty_remaining_ms", -1) >= 0]
    slope = slope_ms_per_min(rows)
    if duty:
        cap = max(duty)
        span_min = (rows[-1]["t_s"] - t0) / 60.0
        text = f"duty budget {duty[0] / 1000:.1f} s -> {duty[-1] / 1000:.1f} s of {cap / 1000:.1f} s"
        if slope is not None:
            text += f"; slope {slope / 1000:+.2f} s/min"
            if slope < -1:
                text += f", empty in {duty[-1] / -slope:.0f} min at this rate"
            else:
                text += ", not draining"
        lines.append(text)
        # The budget is a sliding hour: until the first hour is full, what has been spent is
        # airtime. After an hour the window forgets, so the figure below is only for the first one.
        if 0 < span_min <= 60 and cap > 0:
            used_s = (cap - duty[-1]) / 1000.0
            lines.append(
                f"airtime estimate (first hour only, budget taken as the highest value seen): "
                f"{used_s:.1f} s in {span_min:.0f} min = {100.0 * used_s / (span_min * 60):.2f} % "
                f"(the study's figure is per box, over 90 minutes)"
            )
    else:
        lines.append("duty budget: not reported (duty_remaining_ms -1)")
    lines.extend(expectation(boxes, last, slope))
    return "\n".join(lines)


def expectation(boxes: int | None, last: dict, slope: float | None) -> list[str]:
    """The model's numbers for this field size and a verdict where the log can say."""
    out = ["-- against the model (docs/review/relay-study-results.md, decision SL-18)"]
    if boxes is None or boxes not in STUDY:
        n = boxes or 1
        out.append(
            f"the study has no row for {n} box(es) (it starts at 5), so there is no number to hold this to. "
            f"Compare it with what the rules say alone: acked close to 100 %, retries per event well "
            f"under 1 (a resend is for a lost frame), tx_refused 0, relay_no_slot 0, and an airtime of "
            f"about {SL4_PCT_PER_BOX_EU868 * n:.1f} % (SL-4's arithmetic, {SL4_PCT_PER_BOX_EU868} % per box x {n}, "
            f"EU868, one STATE every 15 s). The bench's first run is the baseline for the 5-box field."
        )
        return out
    fw, built = STUDY[boxes]["firmware"], STUDY[boxes]["built"]
    out.append(
        f"{boxes} boxes, EU868 all in range: the link before Amendment 13 spent {fw[0]} % of airtime per box, "
        f"ACKed {fw[1]} % of captures and was refused {fw[2]} frames per box in 90 minutes; the built rules "
        f"(A_backoff) {built[0]} %, ACKed {built[1]} %, refused {built[2]}."
    )
    sent = last.get("sent", 0)
    if sent:
        acked = 100.0 * last.get("acked", 0) / sent
        side = "the built rules" if acked >= 90 else "the old link" if acked < 40 else "neither"
        out.append(f"this log: acked {acked:.1f} % -> looks like {side}")
    out.append(
        f"this log: tx_refused {last.get('tx_refused', 0)} (the model says 0), relay_no_slot "
        f"{last.get('relay_no_slot', 0)} (the model has 8 slots and says none are short). If the boxes report "
        f"something else, the model is wrong in the first place to look at (SL-18)."
    )
    return out


def modem_report(key: tuple, rows: list[dict]) -> str:
    _, node, game, _ = key
    last = rows[-1]
    lines = [f"== modem, game {game}: {len(rows)} lines, t_s {rows[0]['t_s']}..{last['t_s']}"]
    lines.append(f"{'min':>4} {'t_s':>6} {'rx':>5} {'drop':>5} {'auth':>5} {'dup':>5} {'tx':>5} {'txfail':>6} {'duty s':>7}")
    prev = {k: 0 for k in ("rx_ok", "rx_dropped", "rx_auth_fail", "rx_dupes", "tx_ok", "tx_fail")}
    t0 = rows[0]["t_s"]
    for r in rows:
        d = {k: r.get(k, 0) - prev[k] for k in prev}
        prev = {k: r.get(k, 0) for k in prev}
        duty = r.get("duty_remaining_ms", -1)
        lines.append(
            f"{(r['t_s'] - t0) / 60:>4.0f} {r['t_s']:>6} {d['rx_ok']:>5} {d['rx_dropped']:>5} {d['rx_auth_fail']:>5} "
            f"{d['rx_dupes']:>5} {d['tx_ok']:>5} {d['tx_fail']:>6} {'?' if duty < 0 else f'{duty / 1000:.1f}':>7}"
        )
    slope = slope_ms_per_min(rows)
    lines.append("-- summary")
    lines.append(
        f"tx {last.get('tx_ok', 0)} ok / {last.get('tx_fail', 0)} failed (refusals include the duty-cycle "
        f"budget); rx {last.get('rx_ok', 0)} forwarded, {last.get('rx_dupes', 0)} copies, "
        f"{last.get('rx_auth_fail', 0)} failed authentication"
    )
    if slope is not None:
        lines.append(f"duty budget slope {slope / 1000:+.2f} s/min")
    lines.append("(the modem is the controller's radio: its model figure is the controller's share, not a box's)")
    return "\n".join(lines)


def report(text: str, boxes: int | None = None) -> str:
    records = parse(text)
    if not records:
        return "no radio_stats lines found (is this the box's serial log, from the firmware that logs them?)"
    runs = split(records)
    nodes = {k[1] for k in runs if k[0] == "box"}
    if boxes is None and nodes:
        boxes = len(nodes)
    parts = []
    for key in sorted(runs, key=lambda k: (k[0] != "box", str(k[1]), str(k[2]), k[3])):
        rows = runs[key]
        parts.append(modem_report(key, rows) if key[0] == "modem" else box_report(key, rows, boxes))
    return "\n\n".join(parts)


def read_port(name: str, baud: int, minutes: float, tee: str | None) -> str:
    import serial  # noqa: PLC0415 (pyserial; the Windows venv of the bench has it)

    port = serial.serial_for_url(name, do_not_open=True, baudrate=baud, timeout=0.5)
    port.dtr = False  # raising DTR/RTS resets an ESP32-S3
    port.rts = False
    port.open()
    deadline = time.monotonic() + minutes * 60.0
    chunks: list[bytes] = []
    out = open(tee, "wb") if tee else None  # noqa: SIM115
    try:
        while time.monotonic() < deadline:
            data = port.read(4096)
            if data:
                chunks.append(data)
                if out:
                    out.write(data)
                    out.flush()
    except KeyboardInterrupt:
        pass
    finally:
        port.close()
        if out:
            out.close()
    return b"".join(chunks).decode("utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("log", nargs="*", help="recorded serial logs, one per box (- for standard input)")
    ap.add_argument("--port", help="read a live port instead: COM3, /dev/ttyACM0, socket://host:port")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--minutes", type=float, default=90.0, help="how long to read a live port (default 90)")
    ap.add_argument("--tee", help="also save the raw bytes of the live port to this file")
    ap.add_argument("--boxes", type=int, help="the field's size, for the model's row (default: the nodes in the log)")
    args = ap.parse_args(argv)
    if bool(args.log) == bool(args.port):
        ap.error("give a log file or --port")
    if args.port:
        try:
            text = read_port(args.port, args.baud, args.minutes, args.tee)
        except Exception as exc:  # noqa: BLE001 - serial.SerialException, ImportError
            print(f"bench_radio_log: cannot read {args.port}: {exc}", file=sys.stderr)
            return 1
    else:
        texts = []
        for name in args.log:
            if name == "-":
                texts.append(sys.stdin.read())
            else:
                with open(name, encoding="utf-8", errors="replace") as f:
                    texts.append(f.read())
        text = "\n".join(texts)
    print(report(text, args.boxes))
    return 0


if __name__ == "__main__":
    sys.exit(main())
