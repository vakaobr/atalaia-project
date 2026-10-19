# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The check-in poster's text (ADR-P3-13, protocol/checkin.md): Python side.

    atalaia:checkin:<base64url without padding of: version (1) | body (CBOR map)>

The poster is printed for the field's check-in area. It carries no secret
and no MAC: the field's id and name, the controller's HTTPS addresses, the
SHA-256 of the field CA's certificate (which the app pins per field on the
first scan), and optionally the Wi-Fi network's name and one game. A
poster is a dict:

    {"field_id": "campo-norte", "field_name": "Campo Norte",
     "urls": ["https://10.42.0.1:8443"], "ca_sha256": b"...32...",
     "wifi_ssid": "Atalaia" or None, "game_id": 4242 or None}

The Dart side is app/lib/protocol/checkin_poster.dart; both check
protocol/vectors/checkin.json.
"""

from __future__ import annotations

import base64
import re
from typing import Any, Optional

from atalaia_sim import cbor

VERSION = 1
MAX_LEN = 192
TEXT_PREFIX = "atalaia:checkin:"
KEYS = {"field_id": 1, "field_name": 2, "urls": 3, "ca_sha256": 4, "wifi_ssid": 5, "game_id": 6}
OPTIONAL = ("wifi_ssid", "game_id")
_NAMES = {v: k for k, v in KEYS.items()}
FIELD_ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}")
FIELD_NAME_MAX = 48  # characters
URLS_MAX = 3
URL_MAX = 64  # bytes
# https://host[:port]: a DNS name or IPv4 address, or an IPv6 address in brackets; no path.
URL_RE = re.compile(r"https://(?:[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*|\[[0-9A-Fa-f:.]{2,45}\])"
                    r"(?::([1-9][0-9]{0,4}))?")
SSID_MAX = 32  # bytes


class PosterError(ValueError):
    """A poster that cannot be used. ``reason``: text, length, version or body."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _body(message: str) -> PosterError:
    return PosterError("body", message)


def _printable(value: str) -> bool:
    return all(not (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or 0xD800 <= ord(c) <= 0xDFFF) for c in value)


def url_ok(url: Any) -> bool:
    """An https base URL: https://host[:port], nothing after it, at most 64 bytes."""
    if not isinstance(url, str) or not url.isascii() or len(url) > URL_MAX:
        return False
    m = URL_RE.fullmatch(url)
    return m is not None and (m.group(1) is None or int(m.group(1)) <= 65535)


def validate(poster: dict[str, Any]) -> dict[str, Any]:
    """Checks a poster's fields as both codecs do; returns a normalised copy (absent optionals None)."""
    unknown = set(poster) - set(KEYS)
    if unknown:
        raise _body(f"unknown poster fields: {', '.join(sorted(unknown))}")
    missing = [k for k in KEYS if k not in OPTIONAL and poster.get(k) is None]
    if missing:
        raise _body(f"missing poster fields: {', '.join(missing)}")
    out: dict[str, Any] = {}
    fid = poster["field_id"]
    if not isinstance(fid, str) or not FIELD_ID_RE.fullmatch(fid):
        raise _body("field_id: 1-64 of A-Z a-z 0-9 . _ : -")
    out["field_id"] = fid
    name = poster["field_name"]
    if not isinstance(name, str) or not 1 <= len(name) <= FIELD_NAME_MAX or not _printable(name) \
            or name != name.strip():
        raise _body(f"field_name: 1-{FIELD_NAME_MAX} characters, no control characters or "
                    "spaces at the ends")
    out["field_name"] = name
    urls = poster["urls"]
    if not isinstance(urls, list) or not 1 <= len(urls) <= URLS_MAX:
        raise _body(f"urls: 1 to {URLS_MAX} addresses")
    for u in urls:
        if not url_ok(u):
            raise _body(f"urls: {u!r} is not https://host[:port] of at most {URL_MAX} bytes")
    if len(set(urls)) != len(urls):
        raise _body("urls: each address once")
    out["urls"] = list(urls)
    ca = poster["ca_sha256"]
    if not isinstance(ca, (bytes, bytearray)) or len(ca) != 32:
        raise _body("ca_sha256: 32 bytes")
    out["ca_sha256"] = bytes(ca)
    ssid = poster.get("wifi_ssid")
    if ssid is not None:
        if not isinstance(ssid, str) or not 1 <= len(ssid.encode("utf-8")) <= SSID_MAX or "\0" in ssid:
            raise _body(f"wifi_ssid: 1-{SSID_MAX} bytes of UTF-8 without NUL")
    out["wifi_ssid"] = ssid
    gid = poster.get("game_id")
    if gid is not None:
        if isinstance(gid, bool) or not isinstance(gid, int) or not 1 <= gid <= 0xFFFE:
            raise _body("game_id: 1-65534")
    out["game_id"] = gid
    return out


def encode(poster: dict[str, Any]) -> bytes:
    """version | CBOR body, keys in order, shortest form, optionals left out when absent."""
    v = validate(poster)
    body = {KEYS[k]: v[k] for k in KEYS if v[k] is not None}
    out = bytes([VERSION]) + cbor.encode(body)
    if len(out) > MAX_LEN:
        raise PosterError("length", f"the poster is {len(out)} bytes; at most {MAX_LEN} fit "
                                    "(fewer or shorter addresses, a shorter name)")
    return out


def decode(data: bytes) -> dict[str, Any]:
    if not 2 <= len(data) <= MAX_LEN:
        raise PosterError("length", f"a poster is 2 to {MAX_LEN} bytes, not {len(data)}")
    if data[0] != VERSION:
        raise PosterError("version", f"unknown poster version {data[0]}")
    try:
        raw = cbor.decode(data[1:], allow_bytes=True)
    except cbor.CBORError as exc:
        raise _body(f"poster body: {exc}") from None
    if not isinstance(raw, dict):
        raise _body("the poster body is a map")
    p: dict[str, Any] = {}
    for k, val in raw.items():
        if not isinstance(k, int) or isinstance(k, bool) or not 0 <= k < 32:
            raise _body(f"poster key {k!r}: keys are integers below 32")
        name = _NAMES.get(k)
        if name is None:
            continue  # 0 and 7-31: kept for optional fields a newer controller adds
        if val is None:
            raise _body(f"{name} is null: leave an optional field out instead")
        if name == "ca_sha256":
            if not isinstance(val, bytes):
                raise _body("ca_sha256 is a byte string")
        elif _has_bytes(val):
            raise _body(f"{name} cannot hold byte strings")
        p[name] = val
    return validate(p)


def _has_bytes(value: Any) -> bool:
    if isinstance(value, bytes):
        return True
    if isinstance(value, list):
        return any(_has_bytes(v) for v in value)
    if isinstance(value, dict):
        return any(_has_bytes(v) for v in value.values())
    return False


def to_text(data: bytes) -> str:
    return TEXT_PREFIX + base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def from_text(text: str) -> bytes:
    if not isinstance(text, str):
        raise PosterError("text", "a poster text is a string")
    text = text.strip()
    if not text.startswith(TEXT_PREFIX):
        raise PosterError("text", f"a poster text starts with {TEXT_PREFIX!r}")
    b64 = text[len(TEXT_PREFIX):]
    if not b64 or len(b64) % 4 == 1 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in b64):
        raise PosterError("text", "the poster text is not base64url")
    raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
    if to_text(raw) != TEXT_PREFIX + b64:
        raise PosterError("text", "the poster text is not in canonical base64url")
    return raw


def parse(text: str) -> dict[str, Any]:
    """A poster from its text (a QR code), checked."""
    return decode(from_text(text))


def make(poster: dict[str, Any]) -> str:
    return to_text(encode(poster))


def short_fingerprint(sha256: bytes) -> str:
    """The CA fingerprint's short form people compare: the first 8 bytes as 4 groups of 4 hex digits."""
    h = sha256.hex().upper()
    return " ".join(h[i:i + 4] for i in range(0, 16, 4))


def fingerprint_text(sha256: Optional[bytes]) -> Optional[str]:
    return None if sha256 is None else ":".join(f"{b:02X}" for b in sha256)
