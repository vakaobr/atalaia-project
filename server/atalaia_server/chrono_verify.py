# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Verifying a synced chrono reading on the site server (ADR-P4-5 as amended, P4R14, P4R15).

Plain Python, no database and no web stack (P4R16, P4R17): the database
layer (``chrono_registry.py``) hands it a reading's record text, the time the
controller received the reading and the marshal's keys at the field, and gets
a verdict. The checks and the Ed25519 verification are the controller's own,
``atalaia_controller.chrono`` (imported, not rewritten), which both sides test
against ``protocol/vectors/chrono_record.json``.

Which key: the one the controller verified the reading with. A key's period
runs from its first registration until it was replaced (``valid_until``) or
revoked as compromised (``revoked_at``); the controller's clock gives both the
periods and ``received_at``, so a reading is checked against the keys of its
marshal that were valid when the controller received it. An earlier key keeps
verifying the readings of its own period after a rotation; a key revoked as
compromised verifies nothing received after the revocation.

Reasons, in the order a reader checks (protocol/chrono-record.md): ``format``
(not a record of the format, or a signature that is not 64 bytes of canonical
base64), ``unsigned``, ``marshal`` (no key of that marshal was valid then),
``signature``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

from atalaia_controller import chrono


@dataclass(frozen=True)
class Key:
    """A marshal's public key and its period, in seconds since 1970 (``None``: still open)."""

    id: Any
    public_key: bytes
    valid_from: float
    valid_until: Optional[float] = None
    revoked_at: Optional[float] = None

    def valid_at(self, t: float) -> bool:
        if t < self.valid_from:
            return False
        if self.valid_until is not None and t > self.valid_until:
            return False
        return self.revoked_at is None or t < self.revoked_at


@dataclass
class Verdict:
    """A reading verified (``key`` is the key that signed it, ``fields`` the record's checked fields)
    or not (``reason`` and ``detail``)."""

    ok: bool
    reason: Optional[str] = None
    detail: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    record: Any = None
    key: Optional[Key] = None

    @property
    def reading_id(self) -> Optional[str]:
        """The record's reading id, when it has a readable one (a rejected record's too)."""
        rid = self.record.get("reading_id") if isinstance(self.record, dict) else None
        return rid if isinstance(rid, str) and len(rid) <= 64 else None

    def text_field(self, name: str) -> Optional[str]:
        value = self.record.get(name) if isinstance(self.record, dict) else None
        return value if isinstance(value, str) and len(value) <= 64 else None


def _refused(reason: str, detail: str, record: Any = None) -> Verdict:
    return Verdict(ok=False, reason=reason, detail=detail[:256], record=record)


def verify_reading(text: str, received_at: float, keys_of: Callable[[str], Sequence[Key]]) -> Verdict:
    """The verdict on one reading: its record's JSON text, when the controller got it, and a lookup of
    a marshal's keys at the field."""
    try:
        record = json.loads(text)
    except ValueError as exc:
        return _refused("format", f"not JSON: {exc}")
    try:
        fields = chrono.check(record)
    except chrono.ChronoError as exc:
        return _refused(exc.reason, str(exc), record)
    if chrono.SIGNATURE not in record:
        return _refused("unsigned", "the record has no signature", record)
    keys = [k for k in keys_of(fields["marshal_id"]) if k.valid_at(received_at)]
    if not keys:
        return _refused("marshal", f"no key of marshal {fields['marshal_id']} was valid when the controller "
                                   "received the reading", record)
    last: Optional[chrono.ChronoError] = None
    for key in sorted(keys, key=lambda k: k.valid_from, reverse=True):
        try:
            fields = chrono.verify(record, key.public_key)
        except chrono.ChronoError as exc:
            if exc.reason != "signature":
                return _refused(exc.reason, str(exc), record)
            last = exc
            continue
        except ValueError:  # 32 bytes that are not an Ed25519 point: a key that verifies nothing
            last = chrono.ChronoError("signature", "the marshal's key is not an Ed25519 public key")
            continue
        return Verdict(ok=True, fields=fields, record=record, key=key)
    return _refused("signature", str(last) if last else "the signature does not match", record)


def same_record(a: str, b: str) -> bool:
    """Two texts of one record: the same values (members in any order, ``100`` for ``100.0``)."""
    try:
        return json.loads(a) == json.loads(b)
    except ValueError:
        return False
