# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The expansion port's protocol v1, as a Python reference (protocol/expansion-port.md).

What a box reads from a module (IDENT, CHANNEL, STATUS) and refuses, the COMMAND frames it writes, a model
of a module's outputs and lease, node.modules' compact text, and the params of CMD opcode 12 (output). It
is the reference that protocol/vectors/expansion.json and cmd.json's output_params are checked against
(simulator/tests/test_expansion.py); the vectors themselves are assembled independently by
tools/expansion_vectors.py. Nothing in the simulator's games uses it yet: the box's output layer, its port
driver and the module core come in later increments of the draft RFC "The expansion port".
"""

from __future__ import annotations

import re
from typing import Any, Optional

PROTOCOL_VERSION = 1
MAGIC = b"AX"
FIRST_ADDRESS, LAST_ADDRESS = 0x58, 0x5F
REG_IDENT, REG_CHANNEL, REG_STATUS, REG_COMMAND = 0x00, 0x01, 0x02, 0x10
IDENT_LEN, CHANNEL_LEN, STATUS_LEN = 16, 8, 9

KINDS = {0x01: "hit", 0x10: "output"}  # 0x02 contact is reserved: a v1 box does not use such a channel
HINTS = ["generic", "siren", "strobe", "smoke", "light", "horn"]
EVENT_KINDS = {1: "hit", 2: "closed", 3: "opened"}
STATUS_FLAGS = ["event", "more", "overflow", "supply_ok", "lease_expired", "fresh", "cmd_error"]
OPS = {"ACK": 0x01, "ARM": 0x02, "OUTPUT": 0x03, "LEASE": 0x04, "ALL_OFF": 0x05, "CLEAR_FRESH": 0x06,
       "LOCATE": 0x07, "CONFIG": 0x08}
OP_NAMES = {v: k for k, v in OPS.items()}
ARG_BYTES = {"ACK": 1, "ARM": 1, "OUTPUT": 8, "LEASE": 1, "ALL_OFF": 0, "CLEAR_FRESH": 0, "LOCATE": 1, "CONFIG": 4}
MODES = {"off": 0, "on": 1, "pattern": 2}
MODE_NAMES = {v: k for k, v in MODES.items()}
PARAMETERS = {"threshold": 1, "holdoff_ms": 2, "debounce_ms": 3}
PARAMETER_NAMES = {v: k for k, v in PARAMETERS.items()}
MODEL_NAMES = {0x0001: "target", 0x0002: "out4"}

LEASE_DEFAULT_100MS, LEASE_LEAST_100MS, LEASE_MOST_100MS = 15, 5, 50
RELAY_LEAST_CHANGE_MS = 100
RELAY_LEAST_PATTERN_10MS, SOLID_STATE_LEAST_PATTERN_10MS = 10, 1


class ExpansionError(ValueError):
    """A frame refused; reason is the vectors' word for why (crc, length, magic, ...)."""

    def __init__(self, reason: str, message: str = "") -> None:
        super().__init__(f"{reason}: {message}" if message else reason)
        self.reason = reason


def crc8(data: bytes) -> int:
    """CRC-8, polynomial 0x07, initial value 0, no reflection, no final XOR."""
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def model_name(model: int) -> str:
    """target, out4, or m + four hex digits for any other model (community models: 0x8000-0xffff)."""
    return MODEL_NAMES.get(model, f"m{model:04x}")


def _read(frame: bytes, length: int) -> bytes:
    if len(frame) != length:
        raise ExpansionError("length", f"{len(frame)} bytes, not {length}")
    if crc8(frame[:-1]) != frame[-1]:
        raise ExpansionError("crc")
    return frame


# ---- what the box reads ----------------------------------------------------


def decode_ident(frame: bytes) -> dict[str, Any]:
    f = _read(frame, IDENT_LEN)
    if f[0:2] != MAGIC:
        raise ExpansionError("magic")
    if f[2] != PROTOCOL_VERSION:
        raise ExpansionError("version", str(f[2]))
    if f[3] & 0x03 == 0:
        raise ExpansionError("classes", "neither inputs nor outputs")
    if not 1 <= f[4] <= 8:
        raise ExpansionError("channels", str(f[4]))
    model = int.from_bytes(f[5:7], "little")
    return {"version": f[2], "inputs": bool(f[3] & 1), "outputs": bool(f[3] & 2), "channels": f[4],
            "model": model, "model_name": model_name(model), "hw": f[7], "fw": f"{f[8]}.{f[9]}.{f[10]}",
            "uid": f[11:15].hex()}


def decode_channel(frame: bytes, index: int) -> dict[str, Any]:
    f = _read(frame, CHANNEL_LEN)
    if f[0] != index or f[0] > 7:
        raise ExpansionError("index", f"asked for {index}, got {f[0]}")
    kind = KINDS.get(f[1])
    if kind is None:
        raise ExpansionError("kind", f"0x{f[1]:02x}")
    if kind == "output" and f[4] == 0:
        raise ExpansionError("max_on", "an output needs a max on of 1-255 s")
    return {"index": f[0], "kind": kind, "relay": bool(f[2] & 1), "solid_state": bool(f[2] & 2),
            "senses_supply": bool(f[2] & 4), "hint": HINTS[f[3]] if f[3] < len(HINTS) else "generic",
            "max_on_s": f[4], "min_off_s": f[5]}


def decode_status(frame: bytes, channels: int) -> dict[str, Any]:
    f = _read(frame, STATUS_LEN)
    out: dict[str, Any] = {"event": None}
    if f[0] & 1:
        ch, kind = f[2] & 0x07, f[2] >> 4
        if ch >= channels:
            raise ExpansionError("channel", f"an event on channel {ch} of {channels}")
        if kind not in EVENT_KINDS:
            raise ExpansionError("event_kind", str(kind))
        out["event"] = {"seq": f[1], "channel": ch, "kind": EVENT_KINDS[kind], "value": f[3],
                        "age_ms": int.from_bytes(f[4:6], "little")}
    for bit, name in enumerate(STATUS_FLAGS[1:], start=1):
        out[name] = bool(f[0] & (1 << bit))
    out["outputs"] = f[6]
    out["armed"] = f[7]
    return out


def event_time(t_read_ms: int, age_ms: int) -> int:
    """An event's time on the box's clock (EXP-10): the read's time less the event's age."""
    return t_read_ms - age_ms


# ---- what the box writes ---------------------------------------------------


def encode_command(fields: dict[str, Any], address: int) -> bytes:
    """A COMMAND write after the address byte: register, op, arguments, CRC (over the address byte as sent)."""
    op = fields["op"]
    if op == "ACK":
        args = bytes([fields["seq"]])
    elif op == "ARM":
        args = bytes([fields["armed"]])
    elif op == "OUTPUT":
        args = (bytes([fields["channel"], MODES[fields["mode"]]]) + fields["duration_100ms"].to_bytes(2, "little")
                + fields["on_10ms"].to_bytes(2, "little") + fields["off_10ms"].to_bytes(2, "little"))
    elif op == "LEASE":
        args = bytes([fields["lease_100ms"]])
    elif op == "LOCATE":
        args = bytes([fields["seconds"]])
    elif op == "CONFIG":
        args = bytes([fields["channel"], PARAMETERS[fields["parameter"]]]) + fields["value"].to_bytes(2, "little")
    else:
        args = b""
    body = bytes([REG_COMMAND, OPS[op]]) + args
    return body + bytes([crc8(bytes([address << 1]) + body)])


def decode_command(frame: bytes, address: int, channels: list[dict[str, Any]]) -> dict[str, Any]:
    """What a module at address with these channels makes of a write; raises ExpansionError if it refuses it."""
    if len(frame) < 2 or crc8(bytes([address << 1]) + frame[:-1]) != frame[-1]:
        raise ExpansionError("crc")
    body = frame[:-1]
    if body[0] != REG_COMMAND:
        raise ExpansionError("register", f"0x{body[0]:02x}")
    if len(body) < 2:
        raise ExpansionError("length", "no op")
    op = OP_NAMES.get(body[1])
    if op is None:
        raise ExpansionError("op", f"0x{body[1]:02x}")
    args = body[2:]
    if len(args) != ARG_BYTES[op]:
        raise ExpansionError("length", f"{op} takes {ARG_BYTES[op]} argument bytes")
    inputs = {c["index"] for c in channels if c["kind"] != "output"}
    outputs = {c["index"]: c for c in channels if c["kind"] == "output"}
    f: dict[str, Any] = {"op": op}
    if op == "ACK":
        f["seq"] = args[0]
    elif op == "ARM":
        if any(args[0] & (1 << i) and i not in inputs for i in range(8)):
            raise ExpansionError("range", "ARM names a channel that is not an input")
        f["armed"] = args[0]
    elif op == "OUTPUT":
        ch, mode = args[0], args[1]
        dur, on, off = (int.from_bytes(args[i:i + 2], "little") for i in (2, 4, 6))
        if ch not in outputs:
            raise ExpansionError("range", f"channel {ch} is not an output")
        if mode not in MODE_NAMES:
            raise ExpansionError("range", f"mode {mode}")
        if mode == MODES["pattern"]:
            least = RELAY_LEAST_PATTERN_10MS if outputs[ch]["relay"] else SOLID_STATE_LEAST_PATTERN_10MS
            if on < least or off < least:
                raise ExpansionError("range", "pattern times below the channel's floor")
        f.update({"channel": ch, "mode": MODE_NAMES[mode], "duration_100ms": dur, "on_10ms": on, "off_10ms": off})
    elif op == "LEASE":
        if not LEASE_LEAST_100MS <= args[0] <= LEASE_MOST_100MS:
            raise ExpansionError("range", f"lease {args[0]}")
        f["lease_100ms"] = args[0]
    elif op == "LOCATE":
        f["seconds"] = args[0]
    elif op == "CONFIG":
        if args[0] not in inputs or args[1] not in PARAMETER_NAMES:
            raise ExpansionError("range", "CONFIG is for an input's threshold, hold-off or debounce")
        f.update({"channel": args[0], "parameter": PARAMETER_NAMES[args[1]],
                  "value": int.from_bytes(args[2:4], "little")})
    return f


# ---- a module's outputs and lease ------------------------------------------


class _Output:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.mode = "off"
        self.start = 0  # when the pattern started
        self.on_since: Optional[int] = None  # when it last turned on (max on)
        self.end: Optional[int] = None  # when its duration ends
        self.on_ms = self.off_ms = 0
        self.min_off_until = 0
        self.last_off: Optional[int] = None

    def level(self, t: int) -> bool:
        if self.mode == "on":
            return True
        if self.mode == "pattern":
            return (t - self.start) % (self.on_ms + self.off_ms) < self.on_ms
        return False

    def ms_since_off(self, t: int) -> Optional[int]:
        """How long the load has been off at t: since it was turned off, or since a pattern's last on time
        ended; None when it is on or has not been off. A relay is not turned on again within 100 ms of either
        (decision EXPI7-11, as the module core; aligned in increment 8, EXPI8-15)."""
        if self.mode == "pattern" and not self.level(t):
            return (t - self.start) % (self.on_ms + self.off_ms) - self.on_ms
        if self.mode == "off" and self.last_off is not None:
            return t - self.last_off
        return None

    def off(self, t: int) -> None:
        if self.mode != "off":
            self.last_off = t
        self.mode = "off"
        self.on_since = self.end = None


class ModuleModel:
    """A module's outputs, lease and flags as protocol/expansion-port.md specifies them, in milliseconds.

    Each call first runs the module's timers up to t (a duration, a max on or a lease that ends exactly at t
    has ended). Inputs are not modelled."""

    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.restart(0)

    def restart(self, t: int) -> None:
        self.t = t
        self.outputs = {c["index"]: _Output(c) for c in self.spec["channels"] if c["kind"] == "output"}
        self.lease_ms = LEASE_DEFAULT_100MS * 100
        self.deadline: Optional[int] = None
        self.flags = {"fresh"}

    def _advance(self, t: int) -> None:
        if t < self.t:
            raise ValueError("time goes forward")
        # Events in time order: each output's duration end and max on, and the lease.
        while True:
            due: list[tuple[int, str, Optional[int]]] = []
            for i, o in self.outputs.items():
                if o.mode == "off":
                    continue
                if o.end is not None:
                    due.append((o.end, "end", i))
                if o.on_since is not None:
                    due.append((o.on_since + o.spec["max_on_s"] * 1000, "max_on", i))
            if self.deadline is not None and any(o.mode != "off" for o in self.outputs.values()):
                due.append((self.deadline, "lease", None))
            due = [d for d in due if d[0] <= t]
            if not due:
                break
            # A duration or max on ending at the lease's moment ends first: that is not a lease expiry.
            when, what, i = min(due, key=lambda d: (d[0], d[1] == "lease"))
            if what == "lease":
                for o in self.outputs.values():
                    o.off(when)
                self.flags.add("lease_expired")
                self.deadline = None
            elif what == "max_on":
                o = self.outputs[i]
                o.off(when)
                o.min_off_until = when + o.spec["min_off_s"] * 1000
            else:
                self.outputs[i].off(when)
        self.t = t

    def state(self, t: int) -> tuple[int, set[str]]:
        """The STATUS a read at t would show: the outputs bitmap and the flags lease_expired, fresh, cmd_error."""
        self._advance(t)
        bits = sum(1 << i for i, o in self.outputs.items() if o.level(t))
        return bits, set(self.flags)

    def write(self, t: int, frame: bytes) -> bool:
        """A write reaching the module at t; True if taken, False if refused (cmd_error)."""
        self._advance(t)
        try:
            f = decode_command(frame, self.spec["address"], self.spec["channels"])
            self._apply(t, f)
        except ExpansionError:
            self.flags.add("cmd_error")
            return False
        self.flags.discard("cmd_error")
        return True

    def _apply(self, t: int, f: dict[str, Any]) -> None:
        op = f["op"]
        if op == "ALL_OFF":
            for o in self.outputs.values():
                o.off(t)
        elif op == "CLEAR_FRESH":
            self.flags.discard("fresh")
        elif op == "LEASE":
            self.lease_ms = f["lease_100ms"] * 100
            self.deadline = t + self.lease_ms
            self.flags.discard("lease_expired")
        elif op == "OUTPUT":
            o = self.outputs[f["channel"]]
            if f["mode"] == "off":
                o.off(t)
            else:
                if t < o.min_off_until:
                    raise ExpansionError("min_off")
                since = o.ms_since_off(t)
                if o.spec["relay"] and since is not None and since < RELAY_LEAST_CHANGE_MS:
                    raise ExpansionError("relay_change")
                if o.mode == "off":
                    o.on_since = t
                o.mode = f["mode"]
                o.start = t
                o.on_ms, o.off_ms = f["on_10ms"] * 10, f["off_10ms"] * 10
                o.end = t + f["duration_100ms"] * 100 if f["duration_100ms"] else None
            self.deadline = t + self.lease_ms
            self.flags.discard("lease_expired")


# ---- node.modules' compact text (EXP-21, EXP-36) ---------------------------

MODULES_TEXT_MAX = 100
_CAP_ID = re.compile(r"^[a-z0-9._-]{1,23}$")
_MODULE = re.compile(r"^(5[89a-f]):([a-z0-9][a-z0-9_-]{0,15})/(\d{1,3}\.\d{1,3}\.\d{1,3}):(.+)$")
_SIMPLE = re.compile(r"^g(\d{1,2}):servo:([^,:;/]+)$")


def parse_modules(text: str) -> list[dict[str, Any]]:
    """node.modules' text: entries joined by ';', each a module (<address hex>:<model>/<version>:<caps>) or a
    simple output (g<gpio>:servo:<function>). Raises ValueError if it is not well formed."""
    if len(text.encode()) > MODULES_TEXT_MAX:
        raise ValueError("longer than 100 bytes")
    if text == "":
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in text.split(";"):
        m = _MODULE.match(entry)
        s = _SIMPLE.match(entry)
        if m:
            address, model, fw, caps = m.group(1), m.group(2), m.group(3), m.group(4).split(",")
        elif s and int(s.group(1)) <= 48:
            address, model, fw, caps = f"g{int(s.group(1))}", "servo", None, [s.group(2)]
        else:
            raise ValueError(f"not a module or a simple output: {entry!r}")
        if not all(_CAP_ID.match(c) for c in caps):
            raise ValueError(f"bad capability id in {entry!r}")
        if address in seen:
            raise ValueError(f"{address} twice")
        seen.add(address)
        out.append({"address": address, "model": model, "fw": fw, "caps": caps, "feedback": fw is not None})
    return out


# ---- CMD opcode 12, output (RFC 0001 Amendment 26, EXP-23) -----------------

OUTPUT_ACTS = ("on", "off", "pulse", "pattern")
OUTPUT_MS_MOST = 600000


def _int_in(params: dict[str, Any], key: str, lo: int, hi: int) -> bool:
    v = params.get(key)
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def output_params_problem(params: Any) -> Optional[str]:
    """None when a box takes these CMD 12 params, else why it refuses them. Unknown keys are ignored."""
    if not isinstance(params, dict):
        return "params is a map"
    cap = params.get("capability")
    if not isinstance(cap, str):
        return "capability is required"
    if cap != "*" and not _CAP_ID.match(cap):
        return "a capability id is 1-23 bytes of a-z 0-9 . _ -"
    act = params.get("act")
    if act not in OUTPUT_ACTS:
        return "act is on, off, pulse or pattern"
    if params.get("src") not in ("field", "gm"):
        return "src is field or gm"
    if cap == "*" and act != "off":
        return "* only with off"
    if act == "off":
        return None
    if "ms" not in params:
        return "ms is required for on, pulse and pattern"
    if not isinstance(params["ms"], int) or isinstance(params["ms"], bool):
        return "ms is an integer"
    if not _int_in(params, "ms", 1, OUTPUT_MS_MOST):
        return "ms is 1 to 600000"
    if act == "pattern":
        if "on_ms" not in params or "off_ms" not in params:
            return "on_ms and off_ms are required for pattern"
        if not (_int_in(params, "on_ms", 10, 10000) and _int_in(params, "off_ms", 10, 10000)):
            return "on_ms and off_ms are 10 to 10000"
    return None
