# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The check-in ticket's text (ADR-P4-11, protocol/checkin.md): the check-in poster's sibling.

    atalaia:ticket:<base64url without padding of: version (1) | body (CBOR map)>

A site server gives each registration for a scheduled game a random 32-byte
ticket secret and keeps only its SHA-256, which travels to the field
controller in the roster. The player's app keeps the secret and sends it
with its check-in; a player without the app prints the ticket, a QR code of
this text, and shows it to a marshal's scanner. The ticket is not a game
credential: it only lets the controller match an arrival to a registration,
offline. A ticket is a dict:

    {"registration_id": "0192...-...", "player_id": "p-abcdefgh2345", "secret": b"...32..."}

The body's keys: 1 the registration's id (a lowercase UUID, text), 2 the
player's id at the field (``p-`` and 12 of ``a-z2-7``), 3 the secret (32
bytes). The decoding rules are the poster's: a missing key, a repeated key, a
wrong type, a ``null``, trailing bytes, a key of 32 or more, a negative or text
key are refused; keys 0 and 4-31 are skipped (kept for later optional fields).
The Dart side is app/lib/protocol/checkin_ticket.dart; both check the
``tickets`` vectors of protocol/vectors/checkin.json.
"""

from __future__ import annotations

import base64
import hashlib
import re
from typing import Any

from atalaia_sim import cbor

VERSION = 1
MAX_LEN = 128
TEXT_PREFIX = "atalaia:ticket:"
KEYS = {"registration_id": 1, "player_id": 2, "secret": 3}
_NAMES = {v: k for k, v in KEYS.items()}
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PLAYER_ID_RE = re.compile(r"p-[a-z2-7]{12}")
SECRET_LEN = 32
SECRET_TEXT_RE = re.compile(r"[A-Za-z0-9_-]{43}")


class TicketError(ValueError):
    """A ticket that cannot be used. ``reason``: text, length, version or body."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _body(message: str) -> TicketError:
    return TicketError("body", message)


def validate(ticket: dict[str, Any]) -> dict[str, Any]:
    unknown = set(ticket) - set(KEYS)
    if unknown:
        raise _body(f"unknown ticket fields: {', '.join(sorted(unknown))}")
    missing = [k for k in KEYS if ticket.get(k) is None]
    if missing:
        raise _body(f"missing ticket fields: {', '.join(missing)}")
    rid = ticket["registration_id"]
    if not isinstance(rid, str) or not UUID_RE.fullmatch(rid):
        raise _body("registration_id: a lowercase UUID")
    pid = ticket["player_id"]
    if not isinstance(pid, str) or not PLAYER_ID_RE.fullmatch(pid):
        raise _body("player_id: p- and 12 of a-z 2-7")
    secret = ticket["secret"]
    if not isinstance(secret, (bytes, bytearray)) or len(secret) != SECRET_LEN:
        raise _body("secret: 32 bytes")
    return {"registration_id": rid, "player_id": pid, "secret": bytes(secret)}


def encode(ticket: dict[str, Any]) -> bytes:
    """version | CBOR body, keys in order, shortest form."""
    v = validate(ticket)
    out = bytes([VERSION]) + cbor.encode({KEYS[k]: v[k] for k in KEYS})
    if len(out) > MAX_LEN:  # cannot happen with the fields' own limits; kept as the decoder's bound
        raise TicketError("length", f"the ticket is {len(out)} bytes")
    return out


def decode(data: bytes) -> dict[str, Any]:
    if not 2 <= len(data) <= MAX_LEN:
        raise TicketError("length", f"a ticket is 2 to {MAX_LEN} bytes, not {len(data)}")
    if data[0] != VERSION:
        raise TicketError("version", f"unknown ticket version {data[0]}")
    try:
        raw = cbor.decode(data[1:], allow_bytes=True)
    except cbor.CBORError as exc:
        raise _body(f"ticket body: {exc}") from None
    if not isinstance(raw, dict):
        raise _body("the ticket body is a map")
    t: dict[str, Any] = {}
    for k, val in raw.items():
        if not isinstance(k, int) or isinstance(k, bool) or not 0 <= k < 32:
            raise _body(f"ticket key {k!r}: keys are integers below 32")
        name = _NAMES.get(k)
        if name is None:
            continue  # 0 and 4-31: kept for later optional fields
        if val is None:
            raise _body(f"{name} is null")
        if name == "secret":
            if not isinstance(val, bytes):
                raise _body("secret is a byte string")
        elif not isinstance(val, str):
            raise _body(f"{name} is text")
        t[name] = val
    return validate(t)


def to_text(data: bytes) -> str:
    return TEXT_PREFIX + base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def from_text(text: str) -> bytes:
    if not isinstance(text, str):
        raise TicketError("text", "a ticket text is a string")
    text = text.strip()
    if not text.startswith(TEXT_PREFIX):
        raise TicketError("text", f"a ticket text starts with {TEXT_PREFIX!r}")
    b64 = text[len(TEXT_PREFIX):]
    if not b64 or len(b64) % 4 == 1 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in b64):
        raise TicketError("text", "the ticket text is not base64url")
    raw = base64.urlsafe_b64decode(b64 + "=" * (-len(b64) % 4))
    if to_text(raw) != TEXT_PREFIX + b64:
        raise TicketError("text", "the ticket text is not in canonical base64url")
    return raw


def parse(text: str) -> dict[str, Any]:
    """A ticket from its text (a printed QR code), checked."""
    return decode(from_text(text))


def make(ticket: dict[str, Any]) -> str:
    return to_text(encode(ticket))


def secret_text(secret: bytes) -> str:
    """The secret as the app sends it in a check-in: 43 characters of base64url without padding."""
    return base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")


def secret_from_text(value: Any) -> bytes:
    """The 32-byte secret from its canonical base64url form; raises TicketError("body", ...)."""
    if not isinstance(value, str) or not SECRET_TEXT_RE.fullmatch(value):
        raise _body("ticket: 32 bytes in base64url without padding (43 characters)")
    raw = base64.urlsafe_b64decode(value + "=")
    if secret_text(raw) != value:
        raise _body("ticket: not canonical base64url")
    return raw


def secret_sha256(secret: bytes) -> str:
    """What the site server keeps and the roster carries: the secret's SHA-256 in lowercase hex."""
    return hashlib.sha256(secret).hexdigest()
