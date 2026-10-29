# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Join payload (ADR-P2-12, protocol/join.md): Python side of core/src/join.c.

    version (1 byte, 1) | body (CBOR map, integer keys) | HMAC-SHA256 (32)

The tag is HMAC-SHA256 over the version byte and the body, keyed with the
field's 32-byte join key. A join is a dict:

    {"game_id": 4242, "game_key": b"...16...", "node_id": 7,
     "controller_id": 0, "channel_hz": 869525000, "max_hops": 2,
     "teams": ["red", "blue"], "mode_id": "org.atalaia.domination",
     "role": "zone", "game_seed": 12345, "params": {...} or None,
     "kind": "node" or "controller",
     "ca_sha256": b"...32..." or None, "urls": ["https://10.42.0.1:8443"] or None,
     "lang": "pt" or None, "fetch_modes": False, "forget_modes": False,
     "region": "eu868" or "as923-tw", "box_beacon": True}

ca_sha256 (key 13) and urls (key 14) are optional (RFC 0001 Amendment 4,
proposed): the field CA's fingerprint and the controller's https addresses,
for an Android prop that links to the controller over Wi-Fi
(protocol/prop-link.md); boxes read them for firmware updates over Wi-Fi
(protocol/firmware-update.md). lang (key 15, RFC 0001 Amendment 10, proposed) is
the language of a box's screens ("pt", "en"...; None: English). fetch_modes
(key 16) and forget_modes (key 17), phase 5 plan phase 13 (protocol/mode-packages.md,
"Fetching missing modes"): CBOR true when set, left out otherwise (false is refused):
a box fetches the signed mode packages its mode_id needs and it lacks from the
controller (keys 13 and 14 give it the address and the field CA), and forgets the
packages it fetched before. region (key 18, RFC 0001 Amendment 12, proposed) is the
field's radio region (regions.py): the key holds the region's number (1: AS923-TW)
and is left out for EU868 (0 is refused, so a join has one encoding); the channel
must fit in that region. box_beacon (key 19, RFC 0001 Amendment 20, decision BBC-5) says whether a
Field Box advertises as an iBeacon in this game (protocol/box-beacon.md): True (the default) is the
key left out, False is CBOR false (true is refused, so a join has one encoding). box_beacons (key 21,
RFC 0001 Amendment 21, decision BBC-20) is for a standby controller only (a box skips it): the boxes the
GM disabled and the rooms the GM gave, {"off": [node ids], "rooms": {node id: "text"}}, so the standby
serves the same registry after a failover. Keys 20 and 22-31 are skipped.

The codecs check protocol/vectors/join.json.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Any, Optional

from . import cbor, eu868, regions
from .codec import CodecError, _check_value

VERSION = 1
MAX_LEN = 448
MAC_SIZE = 32
KEY_SIZE = 32
GAME_KEY_SIZE = 16
TEAMS_MAX = 8
TEAM_MAX = 23
MODE_MAX = 63
ROLE_MAX = 31
PARAMS_MAX = 200
BOX_BEACONS_MAX = 200  # bytes of key 21's CBOR value
BOX_OFF_MAX = 32
BOX_ROOMS_MAX = 32
BOX_ROOM_MAX = 48
TEXT_PREFIX = "atalaia:join:"
NDEF_TYPE = b"application/vnd.atalaia.join"

KEYS = {
    "game_id": 1, "game_key": 2, "node_id": 3, "controller_id": 4, "channel_hz": 5,
    "max_hops": 6, "teams": 7, "mode_id": 8, "role": 9, "game_seed": 10, "params": 11, "kind": 12,
    "ca_sha256": 13, "urls": 14, "lang": 15, "fetch_modes": 16, "forget_modes": 17,
    "region": 18, "box_beacon": 19, "box_beacons": 21,
}
OPTIONAL = ("params", "ca_sha256", "urls", "lang", "box_beacons")
FLAGS = ("fetch_modes", "forget_modes")  # CBOR true when set, left out otherwise
REQUIRED = set(KEYS) - set(OPTIONAL) - set(FLAGS) - {"region", "box_beacon"}
URLS_MAX = 3
URL_MAX = 64
# The same rule as the check-in poster's urls (protocol/checkin.md): https://host[:port], no path.
URL_RE = re.compile(r"https://(?:[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*|\[[0-9A-Fa-f:.]{2,45}\])"
                    r"(?::([1-9][0-9]{0,4}))?")
# Key 15: 2-8 bytes of a-z, 0-9 and "-", the first two a-z ("pt", "en", "pt-br").
LANG_RE = re.compile(r"[a-z]{2}[a-z0-9-]{0,6}")
KINDS = {"node": 0, "controller": 1}
_KIND_NAMES = {v: k for k, v in KINDS.items()}
_NAMES = {v: k for k, v in KEYS.items()}

# EU868 sub-bands g, g1, g2, g3 (RFC 0001 Amendment 1); a channel must fit inside one (Amendment 3).
SUB_BANDS = tuple((b.lo_hz, b.hi_hz) for b in eu868.SUB_BANDS)


class JoinError(ValueError):
    """A payload that cannot be used. ``reason`` is one of length, version, mac, body."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def channel_ok(hz: int) -> bool:
    """The whole 125 kHz channel inside one EU868 sub-band (RFC 0001 Amendment 3)."""
    return eu868.channel_ok(hz)


def params_json(params: dict[str, Any]) -> str:
    """The parameters' compact JSON form, whose size the format limits."""
    return json.dumps(params, separators=(",", ":"), ensure_ascii=False)


def _text(name: str, value: Any, max_bytes: int) -> str:
    if not isinstance(value, str):
        raise JoinError("body", f"{name} must be text")
    raw = value.encode("utf-8")
    if not 1 <= len(raw) <= max_bytes or "\0" in value:
        raise JoinError("body", f"{name}: 1 to {max_bytes} bytes of UTF-8 without NUL")
    return value


def _uint(name: str, value: Any, lo: int, hi: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not lo <= value <= hi:
        raise JoinError("body", f"{name} must be an integer from {lo} to {hi}")
    return value


def validate(j: dict[str, Any]) -> dict[str, Any]:
    """Checks a join's fields as both codecs do; returns a normalised copy."""
    unknown = set(j) - set(KEYS)
    if unknown:
        raise JoinError("body", f"unknown join fields: {', '.join(sorted(unknown))}")
    missing = REQUIRED - set(j)
    if missing:
        raise JoinError("body", f"missing join fields: {', '.join(sorted(missing))}")
    out: dict[str, Any] = {}
    out["game_id"] = _uint("game_id", j["game_id"], 1, 0xFFFE)
    key = j["game_key"]
    if not isinstance(key, (bytes, bytearray)) or len(key) != GAME_KEY_SIZE:
        raise JoinError("body", "game_key must be 16 bytes")
    out["game_key"] = bytes(key)
    out["node_id"] = _uint("node_id", j["node_id"], 0, 0xFFFE)
    out["controller_id"] = _uint("controller_id", j["controller_id"], 0, 0xFFFE)
    if out["node_id"] == out["controller_id"]:
        raise JoinError("body", "node_id and controller_id must differ")
    region = j.get("region", regions.EU868.code)
    if region not in regions.BY_CODE:
        raise JoinError("body", f"region: one of {', '.join(regions.BY_CODE)}")
    out["region"] = region
    channel = _uint("channel_hz", j["channel_hz"], 0, 0xFFFFFFFF)
    if not regions.BY_CODE[region].channel_ok(channel):
        raise JoinError("body", f"channel_hz: the whole channel must fit inside a sub-band of {region}")
    out["channel_hz"] = channel
    out["max_hops"] = _uint("max_hops", j["max_hops"], 1, 3)
    teams = j["teams"]
    if not isinstance(teams, list) or not 1 <= len(teams) <= TEAMS_MAX:
        raise JoinError("body", f"teams: 1 to {TEAMS_MAX} names")
    out["teams"] = [_text("team name", t, TEAM_MAX) for t in teams]
    if len(set(out["teams"])) != len(out["teams"]):
        raise JoinError("body", "team names must differ")
    out["mode_id"] = _text("mode_id", j["mode_id"], MODE_MAX)
    out["role"] = _text("role", j["role"], ROLE_MAX)
    out["game_seed"] = _uint("game_seed", j["game_seed"], 0, 0xFFFFFFFF)
    params = j.get("params")
    if params is not None:
        if not isinstance(params, dict) or not all(isinstance(k, str) for k in params):
            raise JoinError("body", "params must be a map with text keys")
        try:
            _check_value(params)
        except CodecError as exc:
            raise JoinError("body", f"params: {exc}") from None
        if len(params_json(params).encode("utf-8")) > PARAMS_MAX:
            raise JoinError("body", f"params: the JSON form is over {PARAMS_MAX} bytes")
    out["params"] = params
    ca = j.get("ca_sha256")
    if ca is not None and (not isinstance(ca, (bytes, bytearray)) or len(ca) != 32):
        raise JoinError("body", "ca_sha256 must be 32 bytes")
    out["ca_sha256"] = bytes(ca) if ca is not None else None
    urls = j.get("urls")
    if urls is not None:
        if not isinstance(urls, list) or not 1 <= len(urls) <= URLS_MAX or len(set(urls)) != len(urls):
            raise JoinError("body", f"urls: 1 to {URLS_MAX} different addresses")
        for u in urls:
            m = URL_RE.fullmatch(u) if isinstance(u, str) and u.isascii() and len(u) <= URL_MAX else None
            if m is None or (m.group(1) is not None and int(m.group(1)) > 65535):
                raise JoinError("body", f"urls: {u!r} is not https://host[:port] of at most {URL_MAX} bytes")
        urls = list(urls)
    out["urls"] = urls
    lang = j.get("lang")
    if lang is not None and not (isinstance(lang, str) and LANG_RE.fullmatch(lang)):
        raise JoinError("body", f"lang: {lang!r} is not 2-8 of a-z, 0-9 and -, starting with two letters")
    out["lang"] = lang
    for name in FLAGS:
        flag = j.get(name, False)
        if not isinstance(flag, bool):
            raise JoinError("body", f"{name} must be true or false")
        out[name] = flag
    beacon = j.get("box_beacon", True)
    if not isinstance(beacon, bool):
        raise JoinError("body", "box_beacon must be true or false")
    out["box_beacon"] = beacon
    kind = j["kind"]
    if kind not in KINDS:
        raise JoinError("body", f"kind must be one of {sorted(KINDS)}")
    out["kind"] = kind
    out["box_beacons"] = _box_beacons(j.get("box_beacons"), kind)
    return out


def _box_beacons(value: Any, kind: str) -> Optional[dict[str, Any]]:
    """Key 21 as a dict ``{"off": [node ids, ascending], "rooms": {node id: text}}`` (either part left out when
    empty), None when there is none. For a standby controller only; at most BOX_BEACONS_MAX bytes of CBOR."""
    if value is None:
        return None
    if kind != "controller":
        raise JoinError("body", "box_beacons: only a standby controller's join carries it")
    if not isinstance(value, dict) or not value or set(value) - {"off", "rooms"}:
        raise JoinError("body", "box_beacons: a map with off and/or rooms, not empty")
    out: dict[str, Any] = {}
    if "off" in value:
        off = value["off"]
        if (not isinstance(off, list) or not 1 <= len(off) <= BOX_OFF_MAX
                or any(not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 0xFFFE for n in off)
                or off != sorted(set(off))):
            raise JoinError("body", f"box_beacons.off: 1 to {BOX_OFF_MAX} different node ids, ascending")
        out["off"] = list(off)
    if "rooms" in value:
        rooms = value["rooms"]
        if (not isinstance(rooms, dict) or not 1 <= len(rooms) <= BOX_ROOMS_MAX
                or any(not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 0xFFFE for n in rooms)):
            raise JoinError("body", f"box_beacons.rooms: 1 to {BOX_ROOMS_MAX} rooms by node id")
        out["rooms"] = {n: _text("room", rooms[n], BOX_ROOM_MAX) for n in sorted(rooms)}
    if len(cbor.encode(_box_beacons_wire(out))) > BOX_BEACONS_MAX:
        raise JoinError("body", f"box_beacons: over {BOX_BEACONS_MAX} bytes (shorter room names)")
    return out


def _box_beacons_wire(v: dict[str, Any]) -> dict[int, Any]:
    return {k: v[name] for k, name in ((1, "off"), (2, "rooms")) if name in v}


def encode(j: dict[str, Any], join_key: bytes) -> bytes:
    """The payload for join j, tagged with join_key (32 bytes)."""
    if len(join_key) != KEY_SIZE:
        raise ValueError("the join key is 32 bytes")
    v = validate(j)
    body: dict[int, Any] = {}
    for name in KEYS:
        if (name in OPTIONAL and v[name] is None) or (name in FLAGS and not v[name]):
            continue
        if name == "box_beacons":
            body[KEYS[name]] = _box_beacons_wire(v[name])
            continue
        if name == "box_beacon":
            if not v[name]:  # on is the key's absence; only false is written
                body[KEYS[name]] = False
            continue
        if name == "region":
            if v[name] != regions.EU868.code:  # EU868 is the key's absence
                body[KEYS[name]] = regions.BY_CODE[v[name]].number
            continue
        body[KEYS[name]] = KINDS[v["kind"]] if name == "kind" else v[name]
    signed = bytes([VERSION]) + cbor.encode(body)
    out = signed + hmac.new(join_key, signed, hashlib.sha256).digest()
    if len(out) > MAX_LEN:
        raise JoinError("length", f"the join payload is {len(out)} bytes; at most {MAX_LEN} fit "
                                  "(shorter team names or fewer parameters)")
    return out


def decode(data: bytes, join_key: bytes) -> dict[str, Any]:
    """Checks the tag (constant time), then the body. Raises JoinError."""
    if not 1 + 1 + MAC_SIZE <= len(data) <= MAX_LEN:
        raise JoinError("length", f"a join payload is 34 to {MAX_LEN} bytes, not {len(data)}")
    if data[0] != VERSION:
        raise JoinError("version", f"unknown join format version {data[0]}")
    signed, tag = data[:-MAC_SIZE], data[-MAC_SIZE:]
    if not hmac.compare_digest(hmac.new(join_key, signed, hashlib.sha256).digest(), tag):
        raise JoinError("mac", "the join payload's tag does not match this field's join key")
    try:
        raw = cbor.decode(signed[1:], allow_bytes=True)
    except cbor.CBORError as exc:
        raise JoinError("body", f"join body: {exc}") from None
    if not isinstance(raw, dict):
        raise JoinError("body", "the join body must be a map")
    j: dict[str, Any] = {}
    for k, v in raw.items():
        if not isinstance(k, int) or isinstance(k, bool) or not 0 <= k < 32:
            raise JoinError("body", f"join body key {k!r}: keys are integers below 32")
        name = _NAMES.get(k)
        if name is None:
            continue  # reserved for an optional field a newer controller adds
        if name == "kind":
            if not isinstance(v, int) or isinstance(v, bool) or v not in _KIND_NAMES:
                raise JoinError("body", f"unknown join kind {v!r}")
            v = _KIND_NAMES[v]
        if name in ("ca_sha256", "urls", "lang", "box_beacons") and v is None:
            raise JoinError("body", f"{name} is null: leave an optional field out instead")
        if name in FLAGS and v is not True:
            raise JoinError("body", f"{name} is only ever true: leave it out instead")
        if name == "box_beacon" and v is not False:
            raise JoinError("body", "box_beacon is only ever false: leave it out instead")
        if name == "box_beacons":
            if not isinstance(v, dict) or any(k not in (1, 2) for k in v):
                raise JoinError("body", "box_beacons: a map with keys 1 (off) and 2 (rooms)")
            v = {name2: v[k] for k, name2 in ((1, "off"), (2, "rooms")) if k in v}
        if name == "region":
            if not isinstance(v, int) or isinstance(v, bool) or v not in regions.BY_NUMBER or v == 0:
                raise JoinError("body", f"region {v!r}: a known region from 1 up (EU868 leaves the key out)")
            v = regions.BY_NUMBER[v].code
        j[name] = v
    for name in ("game_key", "ca_sha256"):
        if name in j and not isinstance(j[name], bytes):
            raise JoinError("body", f"{name} must be a byte string")
    if "urls" in j and _has_bytes(j["urls"]):
        raise JoinError("body", "urls must be text")
    for name in ("teams", "mode_id", "role", "lang"):
        if name in j and _has_bytes(j[name]):
            raise JoinError("body", f"{name} must be text")
    if "params" in j and _has_bytes(j["params"]):
        raise JoinError("body", "params cannot hold byte strings")
    return validate(j)


def _has_bytes(value: Any) -> bool:
    if isinstance(value, bytes):
        return True
    if isinstance(value, list):
        return any(_has_bytes(v) for v in value)
    if isinstance(value, dict):
        return any(_has_bytes(v) for v in value.values())
    return False


# ---- carriers --------------------------------------------------------------


def to_text(payload: bytes) -> str:
    """The QR code and serial-console form: "atalaia:join:" + base64url without padding."""
    return TEXT_PREFIX + base64.urlsafe_b64encode(payload).rstrip(b"=").decode("ascii")


def from_text(text: str) -> bytes:
    text = text.strip()
    if not text.startswith(TEXT_PREFIX):
        raise JoinError("length", f"a join text starts with {TEXT_PREFIX!r}")
    b64 = text[len(TEXT_PREFIX):]
    if len(b64) % 4 == 1 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in b64):
        raise JoinError("length", "the join text is not base64url")
    raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
    if to_text(raw) != TEXT_PREFIX + b64:
        raise JoinError("length", "the join text is not in canonical base64url")
    return raw


def ndef_record(payload: bytes, mime: bytes = NDEF_TYPE) -> bytes:
    """One NDEF MIME record (MB, ME, TNF 2), by default of type application/vnd.atalaia.join."""
    short = len(payload) < 256
    flags = 0x80 | 0x40 | (0x10 if short else 0) | 0x02
    length = bytes([len(payload)]) if short else len(payload).to_bytes(4, "big")
    return bytes([flags, len(mime)]) + length + mime + payload


def to_ndef_tag(payload: bytes, mime: bytes = NDEF_TYPE) -> bytes:
    """A Type 2 tag's user memory from page 4: NDEF message TLV, then the terminator TLV."""
    message = ndef_record(payload, mime)
    if len(message) < 0xFF:
        head = bytes([0x03, len(message)])
    else:
        head = bytes([0x03, 0xFF]) + len(message).to_bytes(2, "big")
    return head + message + b"\xfe"


def from_ndef_tag(mem: bytes, mime: bytes = NDEF_TYPE) -> Optional[bytes]:
    """The join payload (or the first record of type mime) in a Type 2 tag's user memory, or None."""
    i = 0
    while i < len(mem):
        t = mem[i]
        i += 1
        if t == 0x00:
            continue
        if t == 0xFE or i >= len(mem):
            return None
        length = mem[i]
        i += 1
        if length == 0xFF:
            if len(mem) - i < 2:
                return None
            length = int.from_bytes(mem[i:i + 2], "big")
            i += 2
        if length > len(mem) - i:
            return None
        if t == 0x03:
            return _find_record(mem[i:i + length], mime)
        i += length
    return None


def _find_record(m: bytes, mime: bytes) -> Optional[bytes]:
    i = 0
    while i < len(m):
        hdr = m[i]
        i += 1
        if hdr & 0x20 or i >= len(m):
            return None
        tlen = m[i]
        i += 1
        if hdr & 0x10:
            if i >= len(m):
                return None
            plen = m[i]
            i += 1
        else:
            if len(m) - i < 4:
                return None
            plen = int.from_bytes(m[i:i + 4], "big")
            i += 4
        idlen = 0
        if hdr & 0x08:
            if i >= len(m):
                return None
            idlen = m[i]
            i += 1
        if tlen > len(m) - i:
            return None
        rtype = m[i:i + tlen]
        i += tlen
        if idlen > len(m) - i:
            return None
        i += idlen
        if plen > len(m) - i:
            return None
        if hdr & 0x07 == 0x02 and rtype == mime:
            return m[i:i + plen]
        i += plen
        if hdr & 0x40:
            return None
    return None
