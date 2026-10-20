# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed chrono readings (ADR-P3-7, protocol/chrono-record.md): checks and Ed25519 verification.

The marshal's phone signs each reading (app/lib/chrono/record_signer.dart);
the controller (checkin.py, POST /api/v1/chrono/readings) and the site server
(server/atalaia_server/chrono_verify.py, the synced readings) verify it with
the marshal's public key, with this module. Both sides check
protocol/vectors/chrono_record.json.

    canonical = json.dumps(record without "signature", sort_keys=True,
                           separators=(",", ":"), ensure_ascii=False).encode()
    signature = Ed25519.sign(marshal_key, canonical)     # base64, 88 characters
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
from datetime import datetime, timezone
from typing import Any

FORMAT_VERSION = 1
TYPES = ("checkin", "spotcheck", "retest")
REQUIRED = ("reading_id", "replica_id", "player_id", "type", "velocity_mps", "bb_weight_g", "energy_j",
            "chrono_id", "marshal_id", "marshal_name", "field_id", "timestamp")
OPTIONAL = ("game_id", "ref_reading_id")
SIGNATURE = "signature"
ID_RE = re.compile(r"[A-Za-z0-9._:-]{1,64}")
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TIME_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")  # ASCII digits, as Dart's \d
NAME_MAX = 64
# (lowest, highest, most decimals): the ranges keep every value's shortest
# round-trip form in plain notation, in Python and Dart alike.
NUMBERS = {
    "velocity_mps": (0.0, 1000.0, 2),
    "bb_weight_g": (0.0, 10.0, 3),
    "energy_j": (0.0, 5000.0, 3),
}


class ChronoError(ValueError):
    """A record that cannot be trusted. ``reason``: format, unsigned or signature."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _fail(message: str) -> ChronoError:
    return ChronoError("format", message)


def round_half_away(x: float, decimals: int) -> float:
    """x rounded to decimals places, halves away from zero, as Dart's roundToDouble()."""
    if x < 0:
        return -round_half_away(-x, decimals)
    scale = 10.0 ** decimals
    y = x * scale
    whole = math.floor(y)
    if y - whole >= 0.5:
        whole += 1
    return whole / scale


def energy_j(bb_weight_g: float, velocity_mps: float) -> float:
    """E = 0.5 * m * v^2, in this exact order of floating-point operations."""
    return 0.5 * (bb_weight_g / 1000) * velocity_mps * velocity_mps


def _decimals(x: float) -> int:
    text = repr(x)
    if "e" in text:
        return 99  # below 1e-4 (the ranges keep out the large ones): more than any field allows
    return len(text.split(".", 1)[1]) if "." in text else 0


def _text_ok(value: str) -> bool:
    return all(not (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or 0xD800 <= ord(c) <= 0xDFFF) for c in value)


def check(record: Any) -> dict[str, Any]:
    """The record's fields (numbers as floats, without the signature); raises ChronoError("format")."""
    if not isinstance(record, dict):
        raise _fail("a record is a JSON object")
    unknown = set(record) - set(REQUIRED) - set(OPTIONAL) - {SIGNATURE}
    if unknown:
        raise _fail(f"unknown fields {sorted(unknown)}")
    missing = [k for k in REQUIRED if k not in record]
    if missing:
        raise _fail(f"missing fields {missing}")
    out: dict[str, Any] = {}
    for key in REQUIRED + OPTIONAL:
        if key not in record:
            continue
        value = record[key]
        if key in NUMBERS:
            lo, hi, places = NUMBERS[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise _fail(f"{key} is a number")
            value = float(value)
            if not math.isfinite(value) or not lo <= value <= hi or (key != "energy_j" and value == lo):
                raise _fail(f"{key} {value} is out of range")
            if _decimals(value) > places:
                raise _fail(f"{key} has more than {places} decimals")
        elif not isinstance(value, str):
            raise _fail(f"{key} is a string")
        elif key in ("reading_id", "replica_id", "ref_reading_id"):
            if not UUID_RE.fullmatch(value):
                raise _fail(f"{key} is a lowercase UUID")
        elif key == "type":
            if value not in TYPES:
                raise _fail(f"type is one of {TYPES}")
        elif key == "timestamp":
            if not TIME_RE.fullmatch(value):
                raise _fail("timestamp is YYYY-MM-DDTHH:MM:SSZ")
            try:
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except ValueError as exc:
                raise _fail(f"timestamp: {exc}") from None
        elif key == "marshal_name":
            if not 1 <= len(value) <= NAME_MAX or not _text_ok(value):
                raise _fail("marshal_name is 1-64 characters without control characters")
        elif not ID_RE.fullmatch(value):
            raise _fail(f"{key} is 1-64 letters, digits, '.', '_', ':' or '-'")
        out[key] = value
    if out["energy_j"] != round_half_away(energy_j(out["bb_weight_g"], out["velocity_mps"]), 3):
        raise _fail("energy_j does not match bb_weight_g and velocity_mps")
    if out["type"] == "retest" and "ref_reading_id" not in out:
        raise _fail("a retest names the reading it repeats (ref_reading_id)")
    if out["type"] == "checkin" and "ref_reading_id" in out:
        raise _fail("a check-in has no ref_reading_id")
    return out


def canonical(record: dict[str, Any]) -> bytes:
    """The signed bytes: the checked record without its signature, as canonical JSON in UTF-8."""
    fields = check(record)
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _signature(record: dict[str, Any]) -> bytes:
    sig = record.get(SIGNATURE)
    if sig is None:
        raise ChronoError("unsigned", "the record has no signature")
    if not isinstance(sig, str) or len(sig) != 88:
        raise _fail("the signature is 64 bytes in base64 (88 characters)")
    try:
        raw = base64.b64decode(sig.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError):
        raise _fail("the signature is not base64") from None
    if len(raw) != 64 or base64.b64encode(raw).decode("ascii") != sig:
        raise _fail("the signature is not canonical base64 of 64 bytes")
    return raw


def verify(record: Any, public_key: bytes) -> dict[str, Any]:
    """The record's fields if the marshal's key signed it; raises ChronoError."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    message = canonical(record)
    sig = _signature(record)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(sig, message)
    except InvalidSignature:
        raise ChronoError("signature", "the signature does not match the marshal's key") from None
    return check(record)


def parse(text: str | bytes, public_key: bytes) -> dict[str, Any]:
    """A record from its JSON text, verified."""
    try:
        record = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _fail(f"not JSON: {exc}") from None
    return verify(record, public_key)
