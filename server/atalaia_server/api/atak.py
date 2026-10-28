# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote ATAK relay's enrolment (Phase 4 follow-up, decisions FU5-*; ``atak_relay.py``).

    GET  /api/v1/fields/{field_id}/atak                          the relay's state for the field: whether it
                                                                 is on, where devices connect, the field's
                                                                 certificates and the devices connected now
    POST /api/v1/fields/{field_id}/atak/certificates             {device_name, holder?, positions?, days?}: a
                                                                 new certificate, answered once with its TAK
                                                                 data package (base64) and the password of
                                                                 its client certificate
    POST /api/v1/fields/{field_id}/atak/certificates/{id}/revoke {reason?}: revoked now; its connections close
    GET  /api/v1/fields/{field_id}/atak/log                      the audit log's ATAK rows

Who may: the field's ``admin`` or ``gm``, in a session that passed the TOTP step (both are privileged
roles, ADR-P4-2), or a server administrator. A certificate's **holder** is an account with a role on
the field (the issuer unless ``holder`` names another username); ``positions: true`` is refused unless
the holder has the field's ``gm`` or ``marshal`` role (P4R18; ``409 positions_not_allowed``), and the relay
checks it again at every connection; it also needs the **issuer** to hold ``gm`` or ``marshal`` on the
field in this session (``403 positions_need_gm_or_marshal``, FU5-13), since the answer gives the issuer the
certificate's key: the field's ``admin`` alone, or a server administrator without such a role, cannot get
positions by naming a marshal. Issuing in another member's name is allowed (FU5-14); the issuer is in
``atak_cert_issued`` and in every ``atak_connect`` row of the certificate. ``days``: 1-365, ``ATALAIA_ATAK_CERT_DAYS`` (90) by default. At most 20 certificates an hour per account (each makes an RSA
key). Nothing is issued while the relay is off (``409 atak_relay_off``); revoking always works.

The client certificate's private key and password exist only in this answer (``Cache-Control:
no-store``): the server keeps neither. Every issue and revocation is in the audit log
(``atak_cert_issued``, ``atak_cert_revoked``), as every connection the relay accepts or refuses.
"""

from __future__ import annotations

import asyncio
import base64
import functools
import json
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import atak_pki, tenancy
from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import AuditLog, Field, User
from ..services import atak as enrolment

router = APIRouter(prefix="/api/v1/fields/{field_id}/atak", tags=["atak"])
NO_STORE = {"Cache-Control": "no-store"}
ACTIONS = ("atak_cert_issued", "atak_cert_revoked", "atak_connect", "atak_refused")
MAX_BODY = 2048


async def _field(db: AsyncSession, principal: Principal, field_id: uuid.UUID) -> Field:
    require_field_role(principal, field_id, "admin", "gm")
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    return field


def _connect(request: Request, field: Field) -> Optional[dict[str, Any]]:
    settings = request.app.state.settings
    tenant = tenancy.current()
    host = settings.relay_host(tenant.slug if tenant else None)
    return {"host": host, "port": settings.relay_public_port()} if host else None


async def _body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    try:
        body = json.loads(raw) if raw and len(raw) <= MAX_BODY else ({} if not raw else None)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        raise HTTPException(400, "invalid_request")
    return body


@router.get("")
async def state(field_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                db: AsyncSession = Depends(get_session)) -> JSONResponse:
    field = await _field(db, principal, field_id)
    relay = request.app.state.atak_relay
    ca = await enrolment.current_ca(db, field.id)
    return JSONResponse({
        "enabled": relay is not None, "connect": _connect(request, field) if relay is not None else None,
        "max_days": atak_pki.MAX_DAYS, "default_days": request.app.state.settings.atak_cert_days,
        "warn_days": atak_pki.EXPIRY_WARN_DAYS,
        "ca": {"ski": ca.ski, "not_after": ca.not_after.isoformat(), "created_at": ca.created_at.isoformat()}
        if ca is not None else None,
        "relay_ca_sha256": relay.status(field.id)["relay_ca_sha256"] if relay is not None else None,
        "connected": relay.connected(field.id) if relay is not None else [],
        "certificates": await enrolment.list_certs(db, field.id)}, headers=NO_STORE)


@router.post("/certificates")
async def issue(field_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                db: AsyncSession = Depends(get_session)) -> JSONResponse:
    field = await _field(db, principal, field_id)
    relay = request.app.state.atak_relay
    if relay is None:
        raise HTTPException(409, "atak_relay_off")
    wait = request.app.state.limits.atak_issue.hit(str(principal.user.id))
    if wait:
        return JSONResponse({"detail": "too_many_requests"}, status_code=429, headers={"Retry-After": str(wait)})
    body = await _body(request)
    if set(body) - {"device_name", "holder", "positions", "days"}:
        raise HTTPException(400, "invalid_request")
    positions = body.get("positions", False)
    if not isinstance(positions, bool):
        raise HTTPException(400, "invalid_request")
    holder: Optional[User] = principal.user
    named = body.get("holder")
    if named is not None:
        if not isinstance(named, str) or not 1 <= len(named) <= 64:
            raise HTTPException(400, "invalid_request")
        holder = (await db.execute(select(User).where(User.username == named.lower()))).scalar_one_or_none()
        if holder is None:
            raise HTTPException(404, "holder_not_found")
    try:
        done = await enrolment.issue(db, request.app.state.atak_box, field, device_name=body.get("device_name"),
                                     days=body.get("days", request.app.state.settings.atak_cert_days), holder=holder,
                                     positions=positions, issued_by=principal.user.id,
                                     issuer_roles=principal.field_roles(field.id))
    except enrolment.AtakProblem as exc:
        raise HTTPException(exc.status, exc.detail) from None
    connect = _connect(request, field)
    assert connect is not None  # the settings refuse a relay without a host name
    password = atak_pki.new_package_password()
    name = atak_pki.package_name(field.slug, done.row.device_name)
    package = await asyncio.to_thread(functools.partial(  # PBKDF2 for the two PKCS#12 files: off the event loop
        atak_pki.data_package, issued=done.issued, field_ca=done.ca, relay_ca=relay.identity.ca, password=password,
        host=connect["host"], port=connect["port"], description=f"Atalaia {field.name}"[:64], name=name))
    record(db, "atak_cert_issued", request, user_id=principal.user.id, resource="field", resource_id=field.id,
           details={"certificate": str(done.row.id), "device_name": done.row.device_name, "serial": done.row.serial,
                    "holder_id": str(holder.id) if holder else None, "positions": done.row.positions,
                    "not_after": done.row.not_after.isoformat(), "ca_made": done.ca_made})
    await db.commit()
    relay.add_ca(tenancy.current(), field.id, atak_pki.pem(done.ca))
    for cert_id in done.rotated:  # the CA's rotation revoked them: their connections close now (FU5-19)
        relay.drop_cert(cert_id)
    return JSONResponse({"certificate": enrolment.cert_json(done.row, holder.username if holder else None),
                         "connect": connect, "password": password,
                         "package": {"name": name, "content_type": "application/zip",
                                     "base64": base64.b64encode(package).decode("ascii")}},
                        status_code=201, headers=NO_STORE)


@router.post("/certificates/{cert_id}/revoke")
async def revoke(field_id: uuid.UUID, cert_id: uuid.UUID, request: Request,
                 principal: Principal = Depends(current_principal),
                 db: AsyncSession = Depends(get_session)) -> JSONResponse:
    field = await _field(db, principal, field_id)
    body = await _body(request)
    if set(body) - {"reason"}:
        raise HTTPException(400, "invalid_request")
    reason = body.get("reason", "revoked")
    if reason not in ("revoked", "lost", "replaced"):
        raise HTTPException(400, "invalid_request")
    try:
        row = await enrolment.revoke(db, field.id, cert_id, principal.user.id, reason)
    except enrolment.AtakProblem as exc:
        raise HTTPException(exc.status, exc.detail) from None
    record(db, "atak_cert_revoked", request, user_id=principal.user.id, resource="field", resource_id=field.id,
           details={"certificate": str(row.id), "device_name": row.device_name, "reason": row.revoke_reason})
    await db.commit()
    relay = request.app.state.atak_relay
    closed = relay.drop_cert(row.id) if relay is not None else 0
    holder = await db.get(User, row.holder_id) if row.holder_id else None
    return JSONResponse({"certificate": enrolment.cert_json(row, holder.username if holder else None),
                         "closed": closed}, headers=NO_STORE)


@router.get("/log")
async def log(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
              db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _field(db, principal, field_id)
    rows = await db.execute(
        select(AuditLog, User.username, func.host(AuditLog.ip_address)).outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.resource == "field", AuditLog.resource_id == field_id, AuditLog.action.in_(ACTIONS))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(200))
    return JSONResponse([{"action": a.action, "at": a.created_at.isoformat(), "username": username,
                          "address": address, "details": a.details} for a, username, address in rows],
                        headers=NO_STORE)
