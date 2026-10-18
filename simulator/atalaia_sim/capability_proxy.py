# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability proxy protocol v1 (protocol/capability-proxy.md): the Python reference codec.

The I/O pod and the phone exchange frames with the USB modem's framing
(0xA5 | type | length | payload | CRC-16/CCITT-FALSE). IDENT, EVT and CMD
payloads are CBOR maps with integer keys; ACK is a big-endian uint16; the
radio frames carry the modem's payloads. The C codec (core/src/proxy.c and
the modem framing) and this one check protocol/vectors/capability_proxy.yaml.

    ident: {"fw_version": "0.3.0", "capabilities": [{"id": "btn.red", "type": "button"}],
            "battery_pct": 87 (optional), "has_radio": True, "protocol_version": 1}
    evt:   {"cap_id": "btn.red", "event": "hold", "data": {"ms": 5000}, "seq": 7}
    cmd:   {"cap_id": "ring", "method": "fill", "args": {"team": "red"}, "seq": 1}
"""

from __future__ import annotations

import re
from typing import Any, Optional

from . import cbor

SYNC = 0xA5
PAYLOAD_MAX = 256
VERSION = 1

IDENT, EVT, CMD, ACK = 0x01, 0x02, 0x03, 0x04
RADIO_RX, RADIO_TX, RADIO_TX_ACK, RADIO_CMD, RADIO_STATUS, RADIO_ERROR = 0x05, 0x06, 0x07, 0x08, 0x09, 0x0A
TYPE_NAMES = {IDENT: "IDENT", EVT: "EVT", CMD: "CMD", ACK: "ACK", RADIO_RX: "RADIO_RX",
              RADIO_TX: "RADIO_TX", RADIO_TX_ACK: "RADIO_TX_ACK", RADIO_CMD: "RADIO_CMD",
              RADIO_STATUS: "RADIO_STATUS", RADIO_ERROR: "RADIO_ERROR"}

# The modem's CMD opcodes (protocol/usb-modem.md), carried by RADIO_CMD.
OP_PING, OP_CONFIGURE, OP_SET_CHANNEL, OP_STATUS, OP_SET_PEER_EPOCH, OP_CLEAR, OP_IDENT = range(1, 8)

CAPS_MAX = 16
TEXT_MAX = 23
UNKNOWN_KEYS = range(6, 24)  # skipped: a later version's optional fields
_NAME = re.compile(r"^[a-z0-9._-]{1,23}$")
_PRINTABLE = re.compile(r"^[\x20-\x7e]{1,23}$")


class ProxyError(ValueError):
    pass


# ---- framing (the modem's) -------------------------------------------------


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no final XOR."""
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_frame(frame_type: int, payload: bytes = b"") -> bytes:
    if not 0 <= frame_type <= 0xFF or len(payload) > PAYLOAD_MAX:
        raise ProxyError("a frame has a one-byte type and at most 256 bytes of payload")
    body = bytes([frame_type]) + len(payload).to_bytes(2, "big") + payload
    return bytes([SYNC]) + body + crc16(body).to_bytes(2, "big")


class FrameDecoder:
    """Finds frames in a byte stream, resynchronising after junk or a bad CRC."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.crc_errors = 0
        self.length_errors = 0
        self.dropped_bytes = 0

    def feed(self, data: bytes) -> list[tuple[int, bytes]]:
        self.buf += data
        out: list[tuple[int, bytes]] = []
        while True:
            start = self.buf.find(SYNC)
            if start < 0:
                self.dropped_bytes += len(self.buf)
                self.buf.clear()
                return out
            if start:
                self.dropped_bytes += start
                del self.buf[:start]
            if len(self.buf) < 4:
                return out
            length = int.from_bytes(self.buf[2:4], "big")
            if length > PAYLOAD_MAX:
                self.length_errors += 1
                self.dropped_bytes += 1
                del self.buf[:1]
                continue
            if len(self.buf) < 6 + length:
                return out
            body = bytes(self.buf[1:4 + length])
            crc = int.from_bytes(self.buf[4 + length:6 + length], "big")
            if crc != crc16(body):
                self.crc_errors += 1
                self.dropped_bytes += 1
                del self.buf[:1]
                continue
            out.append((body[0], body[3:]))
            del self.buf[:6 + length]


# ---- IDENT, EVT, CMD, ACK --------------------------------------------------


def _text(name: str, value: Any, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ProxyError(f"{name}: {value!r} is not 1-{TEXT_MAX} allowed characters")
    return value


def _uint(name: str, value: Any, hi: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= hi:
        raise ProxyError(f"{name}: {value!r} is not an integer from 0 to {hi}")
    return value


def _jsonish(value: Any) -> bool:
    """What JSON can hold: maps with text keys (at every level), lists, text, numbers, bools, null."""
    if isinstance(value, dict):
        return all(isinstance(k, str) and _jsonish(v) for k, v in value.items())
    if isinstance(value, list):
        return all(_jsonish(v) for v in value)
    return value is None or isinstance(value, (bool, int, float, str))


def _json_map(name: str, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not _jsonish(value):
        raise ProxyError(f"{name} is a map with text keys")
    return value


def _capability(value: Any) -> dict[str, Any]:
    cap = _json_map("a capability descriptor", value)
    for key in ("id", "type"):
        if not isinstance(cap.get(key), str) or not cap[key]:
            raise ProxyError(f"a capability descriptor needs a text {key!r}")
    return cap


def _decode_map(payload: bytes, required: set[int], known: set[int]) -> dict[int, Any]:
    try:
        value = cbor.decode(payload)
    except cbor.CBORError as exc:
        raise ProxyError(f"not CBOR: {exc}") from exc
    if not isinstance(value, dict):
        raise ProxyError("the payload is not a map")
    keys = list(value)
    if not all(isinstance(k, int) and not isinstance(k, bool) for k in keys):
        raise ProxyError("keys are integers")
    if keys != sorted(keys):
        raise ProxyError("keys are written in order")
    for k in keys:
        if k not in known and k not in UNKNOWN_KEYS:
            raise ProxyError(f"key {k} is not allowed")
    missing = required - set(keys)
    if missing:
        raise ProxyError(f"missing key(s) {sorted(missing)}")
    return {k: v for k, v in value.items() if k in known}


def encode_ident(ident: dict[str, Any]) -> bytes:
    caps = ident["capabilities"]
    if not isinstance(caps, list) or len(caps) > CAPS_MAX:
        raise ProxyError(f"capabilities is a list of at most {CAPS_MAX}")
    body: dict[int, Any] = {
        1: _text("fw_version", ident["fw_version"], _PRINTABLE),
        2: [_capability(c) for c in caps],
    }
    if ident.get("battery_pct") is not None:
        body[3] = _uint("battery_pct", ident["battery_pct"], 100)
    if not isinstance(ident["has_radio"], bool):
        raise ProxyError("has_radio is true or false")
    body[4] = ident["has_radio"]
    if ident.get("protocol_version", VERSION) != VERSION:
        raise ProxyError("protocol_version is 1")
    body[5] = VERSION
    return _fit(cbor.encode(body))


def decode_ident(payload: bytes) -> dict[str, Any]:
    m = _decode_map(payload, {1, 2, 4, 5}, {1, 2, 3, 4, 5})
    caps = m[2]
    if not isinstance(caps, list) or len(caps) > CAPS_MAX:
        raise ProxyError(f"capabilities is a list of at most {CAPS_MAX}")
    if not isinstance(m[4], bool):
        raise ProxyError("has_radio is true or false")
    if m[5] != VERSION or isinstance(m[5], bool):
        raise ProxyError("protocol_version is 1")
    out = {"fw_version": _text("fw_version", m[1], _PRINTABLE),
           "capabilities": [_capability(c) for c in caps]}
    if 3 in m:
        out["battery_pct"] = _uint("battery_pct", m[3], 100)
    out["has_radio"] = m[4]
    out["protocol_version"] = VERSION
    return out


_MSG_FIELDS = {EVT: ("event", "data"), CMD: ("method", "args")}


def encode_msg(frame_type: int, msg: dict[str, Any]) -> bytes:
    """An EVT or a CMD payload."""
    name, extra = _MSG_FIELDS[frame_type]
    body: dict[int, Any] = {1: _text("cap_id", msg["cap_id"], _NAME), 2: _text(name, msg[name], _NAME)}
    data = msg.get(extra) or {}
    if _json_map(extra, data):
        body[3] = data
    body[4] = _uint("seq", msg["seq"], 0xFFFF)
    return _fit(cbor.encode(body))


def decode_msg(frame_type: int, payload: bytes) -> dict[str, Any]:
    name, extra = _MSG_FIELDS[frame_type]
    m = _decode_map(payload, {1, 2, 4}, {1, 2, 3, 4})
    out: dict[str, Any] = {"cap_id": _text("cap_id", m[1], _NAME), name: _text(name, m[2], _NAME)}
    data = _json_map(extra, m.get(3, {}))
    if 3 in m and not data:
        raise ProxyError(f"an empty {extra} map is left out")
    out[extra] = data
    out["seq"] = _uint("seq", m[4], 0xFFFF)
    return out


def encode_ack(seq: int) -> bytes:
    return _uint("seq", seq, 0xFFFF).to_bytes(2, "big")


def decode_ack(payload: bytes) -> int:
    if len(payload) != 2:
        raise ProxyError("an ACK is two bytes")
    return int.from_bytes(payload, "big")


def _fit(payload: bytes) -> bytes:
    if len(payload) > PAYLOAD_MAX:
        raise ProxyError(f"the payload takes {len(payload)} bytes, more than {PAYLOAD_MAX}")
    return payload


# ---- radio frames (the modem's payloads) -----------------------------------


def radio_rx(header: bytes, payload: bytes, rssi: int, snr: int, epoch: int) -> bytes:
    if len(header) != 9:
        raise ProxyError("a packet header is 9 bytes")
    return (header + payload + rssi.to_bytes(1, "big", signed=True) +
            snr.to_bytes(1, "big", signed=True) + epoch.to_bytes(2, "big"))


def radio_tx(header: bytes, payload: bytes) -> bytes:
    if len(header) != 9 or len(payload) > 200:
        raise ProxyError("a packet header is 9 bytes and its payload at most 200")
    return header + payload


def radio_tx_ack(seq: int, status: int) -> bytes:
    return _uint("seq", seq, 0xFFFF).to_bytes(2, "big") + bytes([_uint("status", status, 7)])


def radio_configure(game_id: int, node_id: int, epoch: int, max_hops: int, channel_hz: int,
                    key: bytes) -> bytes:
    if len(key) != 16:
        raise ProxyError("the game key is 16 bytes")
    return (bytes([OP_CONFIGURE]) + game_id.to_bytes(2, "big") + node_id.to_bytes(2, "big") +
            epoch.to_bytes(2, "big") + bytes([max_hops]) + channel_hz.to_bytes(4, "big") + key)


def radio_error(code: int, message: str) -> bytes:
    return bytes([_uint("code", code, 255)]) + message.encode()


def describe(frame_type: int) -> Optional[str]:
    return TYPE_NAMES.get(frame_type)
