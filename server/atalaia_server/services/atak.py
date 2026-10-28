# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote ATAK relay's enrolment (Phase 4 follow-up, decisions FU5-*): a field's CA, issuing, revoking.

Used by the API (``api/atak.py``: a field's admin or gm, in a TOTP session) and by the operator's
command (``python -m atalaia_server atak ...``). Every function works in the current tenant (hosted
mode) and leaves the commit to its caller, so a certificate and its audit row are committed together.

Who may hold what (P4R18; decision FU5-3): a certificate issued through the API names its **holder**, an
account with a role on the field (the issuer, unless another is named). Player positions are relayed to
it only if it was issued with ``positions`` and its holder has the field's ``gm`` or ``marshal`` role,
checked when it is issued and again at every connection (``holder_state``); never by default. Issuing
one with ``positions`` also needs the **issuer** to hold ``gm`` or ``marshal`` on the field (FU5-13): the
answer hands the certificate to the issuer, so the field's ``admin`` alone, or a server administrator
with no such role, cannot get positions by naming a marshal as holder. The operator's command issues
certificates with no holder: props and zones only.

A field's first CA is made under a transaction-scoped advisory lock on the field (FU5-20): two first
issues at once wait for each other and share one CA instead of one of them failing on the unique field.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from cryptography import x509
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import atak_pki, quotas
from ..atak_models import AtakCa, AtakCert
from ..models import ROLE_BY_ID, Field, User, UserFieldRole

POSITION_ROLES = frozenset({"gm", "marshal"})  # who sees every position on the controller (positions.py)
REVOKE_REASONS = ("revoked", "lost", "replaced", "erasure", "ca_rotated")


class AtakProblem(Exception):
    """An enrolment that cannot be done: HTTP status and ``detail`` code."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


async def field_roles(db: AsyncSession, user_id: uuid.UUID, field_id: uuid.UUID) -> set[str]:
    rows = await db.execute(select(UserFieldRole.role_id).where(UserFieldRole.user_id == user_id,
                                                                UserFieldRole.field_id == field_id))
    return {ROLE_BY_ID[r] for (r,) in rows}


@dataclass
class HolderState:
    ok: bool
    positions: bool
    reason: Optional[str] = None


async def holder_state(db: AsyncSession, cert: AtakCert) -> HolderState:
    """Whether a certificate's holder still may use it, and whether it gets player positions."""
    if cert.issued_via == "command":
        return HolderState(True, False)  # the operator's: props and zones only, never positions
    if cert.holder_id is None:
        return HolderState(False, False, "holder_gone")
    roles = await field_roles(db, cert.holder_id, cert.field_id)
    if not roles:
        return HolderState(False, False, "holder_has_no_role")
    return HolderState(True, bool(cert.positions and roles & POSITION_ROLES))


def refusal(cert: Optional[AtakCert], field_id: uuid.UUID, now: dt.datetime) -> Optional[str]:
    """Why a certificate's row does not allow a connection (before its holder is looked at), or None."""
    if cert is None:
        return "unknown_certificate"
    if cert.field_id != field_id:
        return "other_field"
    if cert.revoked_at is not None:
        return "revoked"
    if cert.not_after <= now or cert.issued_at > now + atak_pki.BACKDATE:
        return "expired"
    return None


async def current_ca(db: AsyncSession, field_id: uuid.UUID) -> Optional[AtakCa]:
    return (await db.execute(select(AtakCa).where(AtakCa.field_id == field_id))).scalar_one_or_none()


def _lock_key(field_id: uuid.UUID) -> int:
    """The advisory lock's key for a field's CA: the field id's first 8 bytes, as a signed bigint."""
    return int.from_bytes(field_id.bytes[:8], "big", signed=True)


async def _usable(box: atak_pki.CaBox, field_id: uuid.UUID, row: Optional[AtakCa],
                  now: dt.datetime) -> Optional[tuple[x509.Certificate, Any]]:
    if row is None:
        return None
    cert = x509.load_pem_x509_certificate(row.cert_pem.encode("ascii"))
    key = await asyncio.to_thread(box.open, field_id, row.key_sealed)  # the RSA key's checks: off the loop
    if key is not None and cert.not_valid_after_utc > now + dt.timedelta(days=atak_pki.MAX_DAYS + 1):
        return cert, key
    return None


async def ensure_ca(db: AsyncSession, box: atak_pki.CaBox, field: Field, now: Optional[dt.datetime] = None,
                    rotated: Optional[list[uuid.UUID]] = None) -> tuple[AtakCa, x509.Certificate, Any, bool]:
    """The field's CA, made on first use, or made again when its key no longer opens (the secret key
    changed) or it expires within a certificate's longest lifetime; its old certificates are then
    revoked (``ca_rotated``, their ids added to ``rotated`` so the caller closes their connections once
    it has committed). Returns (row, certificate, key, made).

    Making one takes the field's advisory lock (held to the end of the transaction) and looks again:
    a request that made it meanwhile has committed by then, and its CA is used."""
    now = now or dt.datetime.now(dt.timezone.utc)
    row = await current_ca(db, field.id)
    found = await _usable(box, field.id, row, now)
    if found is not None and row is not None:
        return row, found[0], found[1], False
    await db.execute(select(func.pg_advisory_xact_lock(_lock_key(field.id))))
    row = (await db.execute(select(AtakCa).where(AtakCa.field_id == field.id)
                            .execution_options(populate_existing=True))).scalar_one_or_none()
    found = await _usable(box, field.id, row, now)
    if found is not None and row is not None:
        return row, found[0], found[1], False
    if row is not None:
        live = await db.execute(select(AtakCert).where(AtakCert.field_id == field.id, AtakCert.revoked_at.is_(None)))
        for old in live.scalars():
            old.revoked_at, old.revoke_reason = now, "ca_rotated"
            if rotated is not None:
                rotated.append(old.id)
        await db.delete(row)
        await db.flush()
    cert, key = await asyncio.to_thread(atak_pki.new_ca, field.id, field.name)  # RSA 3072: off the event loop
    row = AtakCa(field_id=field.id, cert_pem=atak_pki.pem(cert), key_sealed=box.seal(field.id, key),
                 ski=atak_pki.ski_hex(cert), not_after=cert.not_valid_after_utc)
    db.add(row)
    await db.flush()
    return row, cert, key, True


@dataclass
class Enrolment:
    row: AtakCert
    ca: x509.Certificate
    issued: atak_pki.Issued
    ca_made: bool
    rotated: list[uuid.UUID]  # certificates the CA's rotation revoked: their connections close after the commit


async def issue(db: AsyncSession, box: atak_pki.CaBox, field: Field, *, device_name: Any, days: Any,
                holder: Optional[User], positions: bool, issued_by: Optional[uuid.UUID],
                via: str = "api", issuer_roles: frozenset[str] | set[str] = frozenset()) -> Enrolment:
    """A new certificate for a device of the field (the caller has checked that the issuer may issue at
    all; ``issuer_roles`` are the issuer's roles on the field in this session, which ``positions`` needs)."""
    try:
        name = atak_pki.check_device_name(device_name)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= atak_pki.MAX_DAYS:
            raise atak_pki.PkiError("days")
    except atak_pki.PkiError:
        raise AtakProblem(400, "invalid_request") from None
    if via == "api":
        if holder is None:
            raise AtakProblem(400, "invalid_request")
        if positions and not set(issuer_roles) & POSITION_ROLES:
            raise AtakProblem(403, "positions_need_gm_or_marshal")  # FU5-13: the issuer gets the key
        roles = await field_roles(db, holder.id, field.id)
        if not roles:
            raise AtakProblem(409, "holder_has_no_role")
        if positions and not roles & POSITION_ROLES:
            raise AtakProblem(409, "positions_not_allowed")
    elif holder is not None or positions:
        raise AtakProblem(400, "invalid_request")  # the operator's certificates: no holder, no positions
    await quotas.check(db, "atak_certs", field.id)  # hosted mode's quota of live certificates
    rotated: list[uuid.UUID] = []
    ca_row, ca_cert, ca_key, made = await ensure_ca(db, box, field, rotated=rotated)
    issued = await asyncio.to_thread(atak_pki.issue_client, ca_cert, ca_key, name, days)
    row = AtakCert(field_id=field.id, serial=issued.serial, sha256=issued.sha256, device_name=name,
                   holder_id=holder.id if holder else None, positions=bool(positions), issued_by=issued_by,
                   issued_via=via, issued_at=issued.cert.not_valid_before_utc + atak_pki.BACKDATE,
                   not_after=issued.cert.not_valid_after_utc)
    db.add(row)
    await db.flush()
    return Enrolment(row, ca_cert, issued, made, rotated)


async def revoke(db: AsyncSession, field_id: uuid.UUID, cert_id: uuid.UUID, by: Optional[uuid.UUID],
                 reason: str = "revoked") -> AtakCert:
    if reason not in REVOKE_REASONS:
        raise AtakProblem(400, "invalid_request")
    row = await db.get(AtakCert, cert_id)
    if row is None or row.field_id != field_id:
        raise AtakProblem(404, "certificate_not_found")
    if row.revoked_at is None:
        row.revoked_at, row.revoked_by, row.revoke_reason = dt.datetime.now(dt.timezone.utc), by, reason
    return row


def cert_json(row: AtakCert, holder: Optional[str] = None, now: Optional[dt.datetime] = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    state = "revoked" if row.revoked_at else ("expired" if row.not_after <= now else "valid")
    return {"id": str(row.id), "device_name": row.device_name, "serial": row.serial, "sha256": row.sha256,
            "holder": holder, "positions": row.positions, "issued_via": row.issued_via,
            "issued_at": row.issued_at.isoformat(), "not_after": row.not_after.isoformat(), "state": state,
            "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None, "revoke_reason": row.revoke_reason,
            "last_connected_at": row.last_connected_at.isoformat() if row.last_connected_at else None}


async def list_certs(db: AsyncSession, field_id: uuid.UUID, limit: int = 200) -> list[dict[str, Any]]:
    rows = await db.execute(select(AtakCert, User.username).outerjoin(User, User.id == AtakCert.holder_id)
                            .where(AtakCert.field_id == field_id)
                            .order_by(AtakCert.issued_at.desc(), AtakCert.id.desc()).limit(limit))
    now = dt.datetime.now(dt.timezone.utc)
    return [cert_json(row, username, now) for row, username in rows]
