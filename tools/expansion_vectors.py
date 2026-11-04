#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes protocol/vectors/expansion.json: the expansion port's protocol v1 (protocol/expansion-port.md).

    python3 tools/expansion_vectors.py           write it
    python3 tools/expansion_vectors.py --check   fail if it is stale

The CRC-8 (polynomial 0x07, initial 0, a write's covering the address byte), the IDENT, CHANNEL and STATUS
frames a box reads (good ones and the ones it refuses, with the reason), the COMMAND frames it writes (the
ones a module takes and the ones it refuses), the lease's timelines (what the module's outputs are after
each step, written out by hand here from the rules of protocol/expansion-port.md, not computed), and
node.modules' compact text. The bytes are assembled here from the tables alone, with nothing of the
simulator's code, so the implementations that check the file are each compared with an independent
assembly: the Python reference model (simulator/atalaia_sim/expansion.py, simulator/tests/test_expansion.py),
the box's port driver (firmware/esp32/main/expansion.c: firmware/esp32/test/test_expansion.c, every case,
through tools/protogen.py's firmware/esp32/test/expansion_vectors.h and expansion_cases.h, with a C model of
a module in the test tree), and the module core's C (a later increment, which replaces that model).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "protocol" / "vectors" / "expansion.json"

MAGIC = b"AX"
VERSION = 1
REG = {"IDENT": 0x00, "CHANNEL": 0x01, "STATUS": 0x02, "COMMAND": 0x10}
LENGTH = {"IDENT": 16, "CHANNEL": 8, "STATUS": 9}
OPS = {"ACK": 0x01, "ARM": 0x02, "OUTPUT": 0x03, "LEASE": 0x04, "ALL_OFF": 0x05, "CLEAR_FRESH": 0x06,
       "LOCATE": 0x07, "CONFIG": 0x08}
KINDS = {"hit": 0x01, "contact": 0x02, "output": 0x10}
HINTS = ["generic", "siren", "strobe", "smoke", "light", "horn"]
MODES = {"off": 0, "on": 1, "pattern": 2}
PARAMETERS = {"threshold": 1, "holdoff_ms": 2, "debounce_ms": 3}
EVENT_KINDS = {"hit": 1, "closed": 2, "opened": 3}
STATUS_FLAGS = ["event", "more", "overflow", "supply_ok", "lease_expired", "fresh", "cmd_error"]


def crc8(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def sealed(body: bytes) -> bytes:
    """A frame the box reads: the body and its CRC."""
    return body + bytes([crc8(body)])


def written(address: int, body: bytes) -> bytes:
    """A frame the box writes (register first), with the CRC over the address byte as sent and the body."""
    return body + bytes([crc8(bytes([address << 1]) + body)])


def flip_last(frame: bytes) -> bytes:
    return frame[:-1] + bytes([frame[-1] ^ 0xFF])


# ---- the reference modules -------------------------------------------------

def channel(index: int, kind: str, *, relay: bool = False, solid_state: bool = False, senses_supply: bool = False,
            hint: str = "generic", max_on_s: int = 0, min_off_s: int = 0) -> dict:
    return {"index": index, "kind": kind, "relay": relay, "solid_state": solid_state,
            "senses_supply": senses_supply, "hint": hint, "max_on_s": max_on_s, "min_off_s": min_off_s}


MODULES = {
    "target": {
        "address": 0x58,
        "ident": {"version": 1, "inputs": True, "outputs": False, "channels": 1, "model": 0x0001,
                  "model_name": "target", "hw": 1, "fw": "1.0.0", "uid": "e6614103"},
        "channels": [channel(0, "hit")],
    },
    "out4": {
        "address": 0x5C,
        "ident": {"version": 1, "inputs": False, "outputs": True, "channels": 4, "model": 0x0002,
                  "model_name": "out4", "hw": 2, "fw": "1.0.0", "uid": "a1b2c3d4"},
        "channels": [
            channel(0, "output", relay=True, hint="siren", max_on_s=60),
            channel(1, "output", relay=True, hint="strobe", max_on_s=120),
            channel(2, "output", relay=True, senses_supply=True, hint="smoke", max_on_s=30, min_off_s=30),
            channel(3, "output", solid_state=True, max_on_s=255),
        ],
    },
    "m8001": {
        "address": 0x5D,
        "ident": {"version": 1, "inputs": True, "outputs": True, "channels": 2, "model": 0x8001,
                  "model_name": "m8001", "hw": 3, "fw": "0.2.1", "uid": "00000001"},
        "channels": [channel(0, "hit"), channel(1, "output", solid_state=True, hint="light", max_on_s=255)],
    },
}


def ident_body(f: dict, *, magic: bytes = MAGIC, classes: int | None = None, channels: int | None = None,
               version: int | None = None) -> bytes:
    cls = (1 if f["inputs"] else 0) | (2 if f["outputs"] else 0) if classes is None else classes
    major, minor, patch = (int(x) for x in f["fw"].split("."))
    return (magic + bytes([f["version"] if version is None else version, cls,
                           f["channels"] if channels is None else channels])
            + f["model"].to_bytes(2, "little") + bytes([f["hw"], major, minor, patch]) + bytes.fromhex(f["uid"]))


def channel_body(c: dict, *, kind: int | None = None, index: int | None = None, max_on: int | None = None) -> bytes:
    flags = (1 if c["relay"] else 0) | (2 if c["solid_state"] else 0) | (4 if c["senses_supply"] else 0)
    return bytes([c["index"] if index is None else index, KINDS[c["kind"]] if kind is None else kind, flags,
                  HINTS.index(c["hint"]), c["max_on_s"] if max_on is None else max_on, c["min_off_s"], 0])


def status_body(s: dict, *, event_kind: int | None = None, event_channel: int | None = None) -> bytes:
    flags = 0
    for bit, name in enumerate(STATUS_FLAGS):
        if name == "event":
            flags |= (1 << bit) if s["event"] is not None else 0
        elif s.get(name):
            flags |= 1 << bit
    ev = s["event"]
    if ev is None:
        ev_bytes = bytes(5)
    else:
        ch = ev["channel"] if event_channel is None else event_channel
        kind = EVENT_KINDS[ev["kind"]] if event_kind is None else event_kind
        ev_bytes = bytes([ev["seq"], (kind << 4) | ch, ev["value"]]) + ev["age_ms"].to_bytes(2, "little")
    return bytes([flags]) + ev_bytes + bytes([s["outputs"], s["armed"]])


def status(event: dict | None = None, *, outputs: int = 0, armed: int = 0, **flags: bool) -> dict:
    out = {"event": event}
    for name in STATUS_FLAGS[1:]:
        out[name] = bool(flags.get(name, False))
    out["outputs"] = outputs
    out["armed"] = armed
    return out


def command_body(f: dict) -> bytes:
    op = f["op"]
    args = b""
    if op == "ACK":
        args = bytes([f["seq"]])
    elif op == "ARM":
        args = bytes([f["armed"]])
    elif op == "OUTPUT":
        args = (bytes([f["channel"], MODES[f["mode"]]]) + f["duration_100ms"].to_bytes(2, "little")
                + f["on_10ms"].to_bytes(2, "little") + f["off_10ms"].to_bytes(2, "little"))
    elif op == "LEASE":
        args = bytes([f["lease_100ms"]])
    elif op == "LOCATE":
        args = bytes([f["seconds"]])
    elif op == "CONFIG":
        args = bytes([f["channel"], PARAMETERS[f["parameter"]]]) + f["value"].to_bytes(2, "little")
    return bytes([REG["COMMAND"], OPS[op]]) + args


def output(ch: int, mode: str, duration_100ms: int = 0, on_10ms: int = 0, off_10ms: int = 0) -> dict:
    return {"op": "OUTPUT", "channel": ch, "mode": mode, "duration_100ms": duration_100ms, "on_10ms": on_10ms,
            "off_10ms": off_10ms}


def lease(units: int = 15) -> dict:
    return {"op": "LEASE", "lease_100ms": units}


ALL_OFF = {"op": "ALL_OFF"}
CLEAR_FRESH = {"op": "CLEAR_FRESH"}


# ---- sections --------------------------------------------------------------

def crc_cases() -> list[dict]:
    cases = [("empty", b""), ("check value 123456789", b"123456789"), ("one zero byte", b"\x00"),
             ("one 0xff byte", b"\xff"), ("the out4 module's IDENT body", ident_body(MODULES["out4"]["ident"])),
             ("a LEASE 15 write to 0x5c, address byte first", bytes([0x5C << 1, 0x10, 0x04, 0x0F])),
             ("the same write to 0x5d", bytes([0x5D << 1, 0x10, 0x04, 0x0F]))]
    return [{"name": n, "data": d.hex(), "crc": crc8(d)} for n, d in cases]


def ident_section() -> dict:
    valid = [{"name": f"{name}_module", "module": name, "fields": m["ident"], "bytes": sealed(ident_body(m["ident"])).hex()}
             for name, m in MODULES.items()]
    t = MODULES["target"]["ident"]
    good = sealed(ident_body(t))
    invalid = [
        {"name": "bad_crc", "bytes": flip_last(good).hex(), "reason": "crc"},
        {"name": "short_read", "bytes": good[:15].hex(), "reason": "length"},
        {"name": "long_read", "bytes": (good + b"\x00").hex(), "reason": "length"},
        {"name": "bad_magic", "bytes": sealed(ident_body(t, magic=b"AY")).hex(), "reason": "magic"},
        {"name": "all_ones_bus", "bytes": ("ff" * 16), "reason": "crc"},
        {"name": "version_2", "bytes": sealed(ident_body(t, version=2)).hex(), "reason": "version"},
        {"name": "version_0", "bytes": sealed(ident_body(t, version=0)).hex(), "reason": "version"},
        {"name": "no_class", "bytes": sealed(ident_body(t, classes=0)).hex(), "reason": "classes"},
        {"name": "no_channel", "bytes": sealed(ident_body(t, channels=0)).hex(), "reason": "channels"},
        {"name": "nine_channels", "bytes": sealed(ident_body(t, channels=9)).hex(), "reason": "channels"},
    ]
    return {"register": REG["IDENT"], "length": LENGTH["IDENT"], "valid": valid, "invalid": invalid}


def channel_section() -> dict:
    valid = []
    for name, m in MODULES.items():
        for c in m["channels"]:
            valid.append({"name": f"{name}_channel_{c['index']}", "module": name, "index": c["index"],
                          "fields": c, "bytes": sealed(channel_body(c)).hex()})
    hit = MODULES["target"]["channels"][0]
    siren = MODULES["out4"]["channels"][0]
    good = sealed(channel_body(hit))
    invalid = [
        {"name": "bad_crc", "index": 0, "bytes": flip_last(good).hex(), "reason": "crc"},
        {"name": "short_read", "index": 0, "bytes": good[:7].hex(), "reason": "length"},
        {"name": "answer_for_another_channel", "index": 1, "bytes": good.hex(), "reason": "index"},
        {"name": "index_8", "index": 8, "bytes": sealed(channel_body(hit, index=8)).hex(), "reason": "index"},
        {"name": "unknown_kind", "index": 0, "bytes": sealed(channel_body(hit, kind=0x20)).hex(), "reason": "kind"},
        {"name": "contact_not_in_v1", "index": 0, "bytes": sealed(channel_body(hit, kind=KINDS["contact"])).hex(),
         "reason": "kind"},
        {"name": "output_without_max_on", "index": 0, "bytes": sealed(channel_body(siren, max_on=0)).hex(),
         "reason": "max_on"},
    ]
    return {"register": REG["CHANNEL"], "length": LENGTH["CHANNEL"],
            "kinds": KINDS, "hints": HINTS, "valid": valid, "invalid": invalid}


def status_section() -> dict:
    hit7 = {"seq": 7, "channel": 0, "kind": "hit", "value": 200, "age_ms": 35}
    cases = [
        ("target_idle_armed", "target", status(armed=1), None),
        ("target_hit_with_more", "target", status(hit7, more=True, armed=1), {"t_read_ms": 10000, "t_event_ms": 9965}),
        ("target_hit_age_saturated", "target", status({"seq": 255, "channel": 0, "kind": "hit", "value": 0,
                                                       "age_ms": 65535}, overflow=True, armed=1), None),
        ("target_fresh_after_restart", "target", status(fresh=True), None),
        ("out4_two_on_supply_ok", "out4", status(outputs=0b0101, supply_ok=True), None),
        ("out4_lease_expired", "out4", status(lease_expired=True, supply_ok=True), None),
        ("out4_command_refused", "out4", status(outputs=0b0001, cmd_error=True), None),
        ("m8001_hit_on_channel_0_light_on", "m8001", status({"seq": 1, "channel": 0, "kind": "hit", "value": 90,
                                                             "age_ms": 1000}, outputs=0b10, armed=0b01), None),
    ]
    valid = []
    for name, module, fields, clock in cases:
        v = {"name": name, "module": module, "channels": MODULES[module]["ident"]["channels"], "fields": fields,
             "bytes": sealed(status_body(fields)).hex()}
        if clock:
            v.update(clock)
        valid.append(v)
    hit_status = status(hit7, armed=1)
    good = sealed(status_body(hit_status))
    invalid = [
        {"name": "bad_crc", "module": "target", "channels": 1, "bytes": flip_last(good).hex(), "reason": "crc"},
        {"name": "short_read", "module": "target", "channels": 1, "bytes": good[:8].hex(), "reason": "length"},
        {"name": "event_on_a_missing_channel", "module": "target", "channels": 1,
         "bytes": sealed(status_body(hit_status, event_channel=1)).hex(), "reason": "channel"},
        {"name": "event_kind_0", "module": "target", "channels": 1,
         "bytes": sealed(status_body(hit_status, event_kind=0)).hex(), "reason": "event_kind"},
        {"name": "event_kind_4", "module": "target", "channels": 1,
         "bytes": sealed(status_body(hit_status, event_kind=4)).hex(), "reason": "event_kind"},
    ]
    return {"register": REG["STATUS"], "length": LENGTH["STATUS"], "flags": STATUS_FLAGS,
            "event_kinds": EVENT_KINDS, "valid": valid, "invalid": invalid}


def command_section() -> dict:
    t, o, m = MODULES["target"]["address"], MODULES["out4"]["address"], MODULES["m8001"]["address"]
    good = [
        ("ack_seq_7", "target", t, {"op": "ACK", "seq": 7}),
        ("arm_channel_0", "target", t, {"op": "ARM", "armed": 0b1}),
        ("disarm_all", "target", t, {"op": "ARM", "armed": 0}),
        ("siren_on_10_s", "out4", o, output(0, "on", 100)),
        ("siren_on_until_off", "out4", o, output(0, "on")),
        ("siren_off", "out4", o, output(0, "off")),
        ("strobe_pattern_500_500_for_30_s", "out4", o, output(1, "pattern", 300, 50, 50)),
        ("relay_pattern_at_the_100_ms_floor", "out4", o, output(1, "pattern", 10, 10, 10)),
        ("solid_state_pattern_50_50", "out4", o, output(3, "pattern", 10, 5, 5)),
        ("lease_1_5_s", "out4", o, lease(15)),
        ("lease_shortest", "out4", o, lease(5)),
        ("lease_longest", "out4", o, lease(50)),
        ("all_off", "out4", o, ALL_OFF),
        ("clear_fresh", "out4", o, CLEAR_FRESH),
        ("locate_10_s", "out4", o, {"op": "LOCATE", "seconds": 10}),
        ("threshold_40", "target", t, {"op": "CONFIG", "channel": 0, "parameter": "threshold", "value": 40}),
        ("holdoff_150_ms", "target", t, {"op": "CONFIG", "channel": 0, "parameter": "holdoff_ms", "value": 150}),
        ("debounce_20_ms", "target", t, {"op": "CONFIG", "channel": 0, "parameter": "debounce_ms", "value": 20}),
        ("mixed_module_light_on_5_s", "m8001", m, output(1, "on", 50)),
    ]
    valid = [{"name": n, "module": mod, "address": a, "fields": f, "bytes": written(a, command_body(f)).hex()}
             for n, mod, a, f in good]

    def bad(name: str, module: str, address: int, frame: bytes, reason: str) -> dict:
        return {"name": name, "module": module, "address": address, "bytes": frame.hex(), "reason": reason}

    lease15 = command_body(lease(15))
    invalid = [
        bad("bad_crc", "out4", o, flip_last(written(o, lease15)), "crc"),
        bad("meant_for_another_address", "out4", 0x5D, written(o, lease15), "crc"),
        bad("crc_without_the_address", "out4", o, sealed(lease15), "crc"),
        bad("unknown_register", "out4", o, written(o, bytes([0x11, 0x04, 0x0F])), "register"),
        bad("read_only_register", "out4", o, written(o, bytes([REG["STATUS"], 0x00])), "register"),
        bad("no_op", "out4", o, written(o, bytes([0x10])), "length"),
        bad("op_0", "out4", o, written(o, bytes([0x10, 0x00])), "op"),
        bad("op_9", "out4", o, written(o, bytes([0x10, 0x09])), "op"),
        bad("lease_without_its_argument", "out4", o, written(o, bytes([0x10, 0x04])), "length"),
        bad("all_off_with_an_extra_byte", "out4", o, written(o, bytes([0x10, 0x05, 0x00])), "length"),
        bad("output_one_byte_short", "out4", o, written(o, command_body(output(0, "on", 100))[:-1]), "length"),
        bad("lease_too_short", "out4", o, written(o, command_body(lease(4))), "range"),
        bad("lease_too_long", "out4", o, written(o, command_body(lease(51))), "range"),
        bad("output_on_channel_4", "out4", o, written(o, command_body(output(4, "on", 10))), "range"),
        bad("output_mode_3", "out4", o, written(o, command_body(output(0, "on", 10))[:3] + b"\x03"
                                                + command_body(output(0, "on", 10))[4:]), "range"),
        bad("output_on_an_input", "target", t, written(t, command_body(output(0, "on", 10))), "range"),
        bad("relay_pattern_below_100_ms", "out4", o, written(o, command_body(output(1, "pattern", 10, 5, 5))), "range"),
        bad("pattern_without_on_time", "out4", o, written(o, command_body(output(3, "pattern", 10, 0, 5))), "range"),
        bad("pattern_without_off_time", "out4", o, written(o, command_body(output(3, "pattern", 10, 5, 0))), "range"),
        bad("arm_an_output", "out4", o, written(o, command_body({"op": "ARM", "armed": 0b1})), "range"),
        bad("arm_a_missing_channel", "target", t, written(t, command_body({"op": "ARM", "armed": 0b10})), "range"),
        bad("config_an_output", "out4", o, written(o, command_body({"op": "CONFIG", "channel": 0,
                                                                     "parameter": "threshold", "value": 1})), "range"),
        bad("config_parameter_4", "target", t, written(t, bytes([0x10, 0x08, 0x00, 0x04, 0x01, 0x00])), "range"),
    ]
    return {"register": REG["COMMAND"], "ops": OPS, "modes": MODES, "parameters": PARAMETERS,
            "valid": valid, "invalid": invalid}


# ---- timelines -------------------------------------------------------------
# Each step happens at t_ms (never going back): the module first runs its own timers up to t_ms (a duration
# or a lease ending exactly at t_ms has ended), then the step's write (delivered or lost on the cable), restart
# or nothing; "expect" is the module's state just after: the outputs bitmap and which of lease_expired, fresh
# and cmd_error its STATUS shows. Written by hand from protocol/expansion-port.md's rules.


class Steps:
    def __init__(self, address: int) -> None:
        self.address = address
        self.steps: list[dict] = []

    def write(self, t: int, fields: dict, *, accepted: bool = True, delivered: bool = True,
              outputs: int | None = None, flags: tuple[str, ...] | None = None) -> None:
        s: dict = {"t_ms": t, "write": fields, "bytes": written(self.address, command_body(fields)).hex()}
        if not delivered:
            s["delivered"] = False
        else:
            s["accepted"] = accepted
        self._expect(s, outputs, flags)

    def restart(self, t: int, outputs: int, flags: tuple[str, ...]) -> None:
        self._expect({"t_ms": t, "restart": True}, outputs, flags)

    def check(self, t: int, outputs: int, flags: tuple[str, ...] = ()) -> None:
        self._expect({"t_ms": t}, outputs, flags)

    def refresh(self, start: int, end: int, every: int = 500) -> None:
        for t in range(start, end + 1, every):
            self.write(t, lease(15))

    def found(self) -> None:
        """What a box does when it finds a module (EXP-14): ALL_OFF, then CLEAR_FRESH."""
        self.write(0, ALL_OFF, outputs=0, flags=("fresh",))
        self.write(0, CLEAR_FRESH, outputs=0, flags=())

    def _expect(self, s: dict, outputs: int | None, flags: tuple[str, ...] | None) -> None:
        if outputs is not None or flags is not None:
            s["expect"] = {"outputs": outputs, "flags": sorted(flags or ())}
        self.steps.append(s)


def timelines() -> list[dict]:
    out4 = MODULES["out4"]["address"]
    lines = []

    s = Steps(out4)
    s.found()
    s.write(0, output(0, "on"), outputs=0b1, flags=())
    s.refresh(500, 1000)
    s.check(2499, 0b1)
    s.check(2500, 0, ("lease_expired",))
    s.write(3000, output(0, "on"), outputs=0b1, flags=())
    s.write(3100, ALL_OFF, outputs=0, flags=())
    lines.append({"name": "lease_runs_out", "module": "out4",
                  "description": "The siren is on until off; the box refreshes the 1.5 s lease at 500 and 1000 ms "
                                 "and then stops (a crash): the module turns it off at 2500 ms and says "
                                 "lease_expired until the box writes again.", "steps": s.steps})

    s = Steps(out4)
    s.found()
    s.write(0, output(1, "on", 50), delivered=False, outputs=0, flags=())
    s.write(250, output(1, "on", 48), outputs=0b10, flags=())
    s.refresh(750, 4750)
    s.check(5049, 0b10)
    s.check(5050, 0)
    lines.append({"name": "lost_write_repaired", "module": "out4",
                  "description": "A 5 s strobe is lost on the cable; the next STATUS (250 ms) shows it off and the "
                                 "box sends what is left, rounded up to 100 ms (4.8 s), which ends on the module's own "
                                 "timer at 5050 ms.", "steps": s.steps})

    s = Steps(out4)
    s.found()
    s.write(0, output(0, "on", 100), outputs=0b1, flags=())
    s.write(500, lease(15))
    s.restart(800, 0, ("fresh",))
    s.write(1000, CLEAR_FRESH, outputs=0, flags=())
    s.write(1000, output(0, "on", 90), outputs=0b1, flags=())
    s.refresh(1500, 9500)
    s.check(9999, 0b1)
    s.check(10000, 0)
    lines.append({"name": "module_restart", "module": "out4",
                  "description": "A 10 s siren; the module restarts (a brown-out) at 800 ms and comes back off and "
                                 "fresh; the box sees fresh at 1000 ms, clears it and sends the 9 s left.",
                  "steps": s.steps})

    s = Steps(out4)
    s.found()
    s.write(0, output(0, "on", 10), outputs=0b1, flags=())
    s.write(500, lease(15), delivered=False)
    s.check(999, 0b1)
    s.check(1000, 0)
    lines.append({"name": "pulse_spanning_missed_polls", "module": "out4",
                  "description": "A 1 s pulse: the polls at 250 and 750 ms are missed and the refresh at 500 ms is "
                                 "lost; the module ends the pulse on its own timer at 1000 ms, with no lease_expired.",
                  "steps": s.steps})

    s = Steps(out4)
    s.found()
    s.write(0, output(2, "on"), outputs=0b100, flags=())
    s.refresh(500, 29500)
    s.check(29999, 0b100)
    s.check(30000, 0)
    s.write(40000, output(2, "on"), accepted=False, outputs=0, flags=("cmd_error",))
    s.write(59999, output(2, "on"), accepted=False, outputs=0, flags=("cmd_error",))
    s.write(60000, output(2, "on", 10), outputs=0b100, flags=())
    s.check(60999, 0b100)
    s.check(61000, 0)
    lines.append({"name": "max_on_and_min_off", "module": "out4",
                  "description": "The smoke channel (max on 30 s, min off 30 s) is turned on until off and kept "
                                 "leased: the module turns it off at 30 s by itself, refuses it until 60 s, then takes "
                                 "a 1 s pulse.", "steps": s.steps})

    s = Steps(out4)
    s.found()
    s.write(0, output(1, "pattern", 10, 5, 5), accepted=False, outputs=0, flags=("cmd_error",))
    s.write(0, output(3, "pattern", 10, 5, 5), outputs=0b1000, flags=())
    s.check(49, 0b1000)
    s.check(50, 0)
    s.check(99, 0)
    s.check(100, 0b1000)
    s.check(999, 0)
    s.check(1000, 0)
    s.write(1000, output(1, "pattern", 10, 10, 10), outputs=0b10, flags=())
    s.check(1099, 0b10)
    s.check(1100, 0)
    s.check(1200, 0b10)
    s.check(2000, 0)
    lines.append({"name": "relay_pattern_floor", "module": "out4",
                  "description": "A 50 ms pattern is refused on a relay channel and runs on the solid-state one "
                                 "(on first, then off, repeated, for its duration); a relay takes 100 ms.",
                  "steps": s.steps})

    s = Steps(out4)
    s.found()
    s.write(0, output(0, "on"), outputs=0b1, flags=())
    s.write(50, output(0, "off"), outputs=0, flags=())
    s.write(100, output(0, "on"), accepted=False, outputs=0, flags=("cmd_error",))
    s.write(150, output(0, "on"), outputs=0b1, flags=())
    s.write(160, output(0, "off"), outputs=0, flags=())
    s.write(170, ALL_OFF, outputs=0, flags=())
    lines.append({"name": "relay_switches_at_most_every_100_ms", "module": "out4",
                  "description": "A relay channel turned off at 50 ms refuses to turn on again before 150 ms; off "
                                 "is never refused.", "steps": s.steps})
    return lines


# ---- node.modules' compact text --------------------------------------------

def modules_text() -> dict:
    def mod(address: str, model: str, fw: str | None, caps: list[str]) -> dict:
        return {"address": address, "model": model, "fw": fw, "caps": caps, "feedback": fw is not None}

    valid = [
        {"name": "none", "text": "", "modules": []},
        {"name": "rfc_example", "text": "g46:servo:siren;58:target/1.0.0:hit;5c:out4/1.0.0:strobe,smoke,out.3,out.4",
         "modules": [mod("g46", "servo", None, ["siren"]), mod("58", "target", "1.0.0", ["hit"]),
                     mod("5c", "out4", "1.0.0", ["strobe", "smoke", "out.3", "out.4"])]},
        {"name": "two_targets", "text": "58:target/1.0.0:hit;59:target/1.0.1:hit.2",
         "modules": [mod("58", "target", "1.0.0", ["hit"]), mod("59", "target", "1.0.1", ["hit.2"])]},
        {"name": "community_model", "text": "5d:m8001/0.2.1:hit,light",
         "modules": [mod("5d", "m8001", "0.2.1", ["hit", "light"])]},
        {"name": "two_simple_outputs", "text": "g45:servo:out.1;g46:servo:horn",
         "modules": [mod("g45", "servo", None, ["out.1"]), mod("g46", "servo", None, ["horn"])]},
    ]
    long_text = ";".join(f"5{c}:out4/10.10.10:siren.2,strobe.2" for c in "cdef") + ";g46:servo:x"
    assert len(long_text) > 100
    invalid = [
        {"name": "over_100_bytes", "text": long_text, "reason": "longer than 100 bytes"},
        {"name": "address_below_the_range", "text": "57:target/1.0.0:hit", "reason": "addresses are 58-5f"},
        {"name": "address_upper_case", "text": "5C:out4/1.0.0:siren", "reason": "lower-case hex"},
        {"name": "module_without_version", "text": "58:target:hit", "reason": "a module has model/version"},
        {"name": "simple_output_with_version", "text": "g46:servo/1.0.0:siren", "reason": "a simple output has none"},
        {"name": "simple_output_two_functions", "text": "g46:servo:siren,horn", "reason": "one GPIO, one channel"},
        {"name": "simple_output_not_servo", "text": "g46:relay:siren", "reason": "the only simple output is servo"},
        {"name": "gpio_49", "text": "g49:servo:siren", "reason": "GPIOs are 0-48"},
        {"name": "no_capability", "text": "58:target/1.0.0:", "reason": "at least one capability"},
        {"name": "same_address_twice", "text": "58:target/1.0.0:hit;58:target/1.0.0:hit.2", "reason": "twice"},
        {"name": "trailing_separator", "text": "58:target/1.0.0:hit;", "reason": "empty entry"},
        {"name": "capability_upper_case", "text": "58:target/1.0.0:Hit", "reason": "capability ids are lower-case"},
    ]
    return {"max_bytes": 100, "valid": valid, "invalid": invalid}


def build() -> dict:
    return {
        "description": "The expansion port's protocol v1 (protocol/expansion-port.md; draft RFC 'The expansion "
                       "port', decisions EXP-7 to EXP-14, EXP-21, EXP-36): the CRC-8 (polynomial 0x07, initial 0, "
                       "no reflection; a write's CRC covers the address byte as sent, address << 1), the frames a "
                       "box reads and writes with their bytes after the address byte, good and refused with the "
                       "reason, the reference modules they belong to, the lease's timelines, and node.modules' "
                       "compact text. Made by tools/expansion_vectors.py; checked by "
                       "simulator/tests/test_expansion.py (the Python reference model) and "
                       "firmware/esp32/test/test_expansion.c (the box's port driver and a C model of a module, "
                       "every case).",
        "protocol_version": VERSION,
        "magic": MAGIC.decode(),
        "addresses": {"first": 0x58, "last": 0x5F, "input_default": 0x58, "output_default": 0x5C,
                      "most_modules": 4},
        "polling": {"input_ms": 20, "output_only_ms": 250, "gone_after_failed_reads": 25,
                    "probe_every_ms": 2000},
        "lease": {"default_100ms": 15, "least_100ms": 5, "most_100ms": 50, "refresh_ms": 500,
                  "relay_least_change_ms": 100, "relay_least_pattern_10ms": 10,
                  "solid_state_least_pattern_10ms": 1},
        "crc8": crc_cases(),
        "modules": MODULES,
        "ident": ident_section(),
        "channel": channel_section(),
        "status": status_section(),
        "command": command_section(),
        "timelines": timelines(),
        "modules_text": modules_text(),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = ap.parse_args(argv)
    text = json.dumps(build(), indent=2, ensure_ascii=False) + "\n"
    current = OUT.read_text(encoding="utf-8") if OUT.exists() else None
    if args.check:
        if current != text:
            print(f"expansion_vectors: {OUT.relative_to(ROOT)} is stale; run python3 tools/expansion_vectors.py",
                  file=sys.stderr)
            return 1
        return 0
    if current != text:
        OUT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
