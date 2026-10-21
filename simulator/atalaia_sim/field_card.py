# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The NFC field card (protocol/adoption.md): Python side of firmware/esp32/main/adoption.c.

A field card adopts a box: it carries the field's 32-byte join key, the
field's master secret (protocol/join.md), and the field's name to show.

    version (1, = 1) | name_len (1, 0-48) | name (UTF-8) | join_key (32) | check (8)

check is the first 8 bytes of HMAC-SHA256(join_key, "atalaia-field-card" |
version | name_len | name): it catches a card written wrong or damaged and
ties the name to the key. It is no signature: anyone can make a card of
their own key, so a box already adopted takes another field's card only
with its admin PIN.

The card's NDEF record is a MIME record of type application/vnd.atalaia.field
on an NTAG215/216 (the join card's layout, another type). The field's
fingerprint, shown by the box and the console so the two can be compared,
is HMAC-SHA256(join_key, "atalaia-field-fingerprint")[:4] as "XXXX-XXXX".

Both codecs check protocol/vectors/field_card.json.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Optional

from . import join

VERSION = 1
KEY_SIZE = 32
CHECK_SIZE = 8
NAME_MAX = 48
MIN_LEN = 2 + KEY_SIZE + CHECK_SIZE
MAX_LEN = MIN_LEN + NAME_MAX
NDEF_TYPE = b"application/vnd.atalaia.field"
CHECK_LABEL = b"atalaia-field-card"
FINGERPRINT_LABEL = b"atalaia-field-fingerprint"


class FieldCardError(ValueError):
    """A field card that does not decode; reason is one of the vectors' reasons."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def fingerprint(join_key: bytes) -> str:
    """The field's fingerprint: 8 hex digits, "XXXX-XXXX" (nothing of the key can be read from it)."""
    if len(join_key) != KEY_SIZE:
        raise ValueError("the join key is 32 bytes")
    d = hmac.new(join_key, FINGERPRINT_LABEL, hashlib.sha256).digest()[:4].hex().upper()
    return f"{d[:4]}-{d[4:]}"


def name_ok(name: bytes) -> bool:
    """0-48 bytes of UTF-8 without control characters, '"' or '\\'."""
    if len(name) > NAME_MAX or any(b < 0x20 or b == 0x7F or b in (0x22, 0x5C) for b in name):
        return False
    try:
        name.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def clean_name(text: str) -> str:
    """A field's display name made fit for a card: the characters a card refuses dropped,
    then cut to 48 bytes of UTF-8 on a character boundary."""
    out = "".join(c for c in text if c.isprintable() and c not in '"\\').strip()
    data = out.encode("utf-8")[:NAME_MAX]
    return data.decode("utf-8", errors="ignore").strip()


def _check(join_key: bytes, head: bytes) -> bytes:
    return hmac.new(join_key, CHECK_LABEL + head, hashlib.sha256).digest()[:CHECK_SIZE]


def encode(join_key: bytes, name: str = "") -> bytes:
    if len(join_key) != KEY_SIZE:
        raise FieldCardError("key", "the join key is 32 bytes")
    raw = name.encode("utf-8")
    if not name_ok(raw):
        raise FieldCardError("name", "the name: 0-48 bytes of UTF-8, no control characters, '\"' or '\\'")
    head = bytes([VERSION, len(raw)]) + raw
    return head + join_key + _check(join_key, head)


def decode(data: bytes) -> dict:
    """{"join_key": bytes, "name": str, "fingerprint": str}, or FieldCardError."""
    if not MIN_LEN <= len(data) <= MAX_LEN:
        raise FieldCardError("length", f"a field card is {MIN_LEN}-{MAX_LEN} bytes, not {len(data)}")
    if data[0] != VERSION:
        raise FieldCardError("version", f"field card version {data[0]}")
    n = data[1]
    if n > NAME_MAX or len(data) != MIN_LEN + n:
        raise FieldCardError("length", "the name's length does not match the card's")
    raw = data[2:2 + n]
    if not name_ok(raw):
        raise FieldCardError("name", "the name is not clean UTF-8")
    key = data[2 + n:2 + n + KEY_SIZE]
    if not hmac.compare_digest(_check(key, data[:2 + n]), data[2 + n + KEY_SIZE:]):
        raise FieldCardError("check", "the card's check does not match: written wrong or damaged")
    return {"join_key": key, "name": raw.decode("utf-8"), "fingerprint": fingerprint(key)}


def to_ndef_tag(payload: bytes) -> bytes:
    """The bytes for an NTAG215/216's user memory from page 4 (NDEF TLV, then the terminator)."""
    return join.to_ndef_tag(payload, NDEF_TYPE)


def from_ndef_tag(mem: bytes) -> Optional[bytes]:
    return join.from_ndef_tag(mem, NDEF_TYPE)
