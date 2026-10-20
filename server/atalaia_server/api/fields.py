# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fields and per-field roles (ADR-P4-2's roles, ADR-P4-1's ``user_field_roles``).

    POST   /api/v1/fields                                   server administrator: a new field
    GET    /api/v1/fields                                   the fields the caller has a role on (all, for a server administrator)
    PATCH  /api/v1/fields/{field_id}                        the field's admin: {chrono_sharing_enabled} (plan phase 14),
                                                            {public_page, description, address_text,
                                                            federation_label} (plan phase 15)
    GET    /api/v1/fields/{field_id}/roles                  the field's admin or gm
    PUT    /api/v1/fields/{field_id}/roles                  {username, role}: grant
    DELETE /api/v1/fields/{field_id}/roles/{user_id}/{role} revoke
    POST   /api/v1/fields/{field_id}/sync-keys              the field's admin: a controller API key, shown once
    GET    /api/v1/fields/{field_id}/sync-keys              its keys: fingerprint, label, times (never the key)
    DELETE /api/v1/fields/{field_id}/sync-keys/{key_id}     revoke one

Who may grant or revoke what, on one field: its ``admin`` (and a server
administrator) any role; its ``gm`` ``player``, ``squad_leader``, ``vip``
and ``spectator``; nobody else. ``admin``, ``gm`` and ``marshal`` go only to
accounts with TOTP on (409 ``totp_required``). Every change is in the audit
log.

A field's controllers authenticate with an API key (ADR-P4-3 as amended,
P4R13): 32 random bytes, kept only as its SHA-256, shown once when made, at
most two live at a time so a new one can be installed before the old one is
revoked (409 ``too_many_keys``). Only the field's ``admin`` (in a TOTP
session) manages them; making and revoking one is in the audit log.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import sync
from ..services import scheduling
from ..audit import record
from ..auth import Principal, current_principal, require_field_role, server_admin
from ..db import get_session
from ..models import PRIVILEGED_ROLES, ROLE_BY_ID, ROLE_NAMES, Field, FieldApiKey, User, UserFieldRole

router = APIRouter(prefix="/api/v1", tags=["fields"])

FIELD_TYPES = ("outdoor", "cqb", "indoor")
SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?")
GM_GRANTS = frozenset({"player", "squad_leader", "vip", "spectator"})
NO_STORE = {"Cache-Control": "no-store"}


class FieldIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = PydanticField(min_length=1, max_length=128)
    slug: str = PydanticField(max_length=128)
    field_type: str = "outdoor"
    timezone: str = PydanticField(default="Europe/Lisbon", max_length=64)


class FieldPatch(BaseModel):
    """Only the members sent change; ``null`` or ``""`` clears a text."""

    model_config = ConfigDict(extra="forbid")
    chrono_sharing_enabled: Optional[bool] = None
    public_page: Optional[bool] = None
    description: Optional[str] = None
    address_text: Optional[str] = None
    federation_label: Optional[str] = None


class SyncKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Optional[str] = PydanticField(default=None, max_length=64)


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = PydanticField(max_length=64)
    role: str = PydanticField(max_length=32)


def field_json(f: Field, roles: Any = None) -> dict[str, Any]:
    body = {"id": str(f.id), "name": f.name, "slug": f.slug, "field_type": f.field_type, "timezone": f.timezone,
            "chrono_sharing_enabled": f.chrono_sharing_enabled, "public_page": f.public_page,
            "description": f.description, "address_text": f.address_text, "federation_label": f.federation_label}
    if roles is not None:
        body["my_roles"] = sorted(roles)
    return body


@router.post("/fields", status_code=201)
async def create_field(body: FieldIn, request: Request, principal: Principal = Depends(server_admin),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "name_invalid")
    if not SLUG.fullmatch(body.slug):
        raise HTTPException(400, "slug_invalid")
    if body.field_type not in FIELD_TYPES:
        raise HTTPException(400, "field_type_invalid")
    try:
        ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(400, "timezone_invalid") from None
    field = Field(name=name, slug=body.slug, field_type=body.field_type, timezone=body.timezone)
    db.add(field)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "slug_taken") from None
    record(db, "field_create", request, user_id=principal.user.id, resource="field", resource_id=field.id,
           details={"slug": field.slug})
    await db.commit()
    return JSONResponse(field_json(field), status_code=201)


@router.get("/fields")
async def list_fields(principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    query = select(Field).order_by(Field.slug)
    if not principal.is_server_admin:
        query = query.where(Field.id.in_(list(principal.roles)))
    rows = (await db.scalars(query)).all()
    return JSONResponse([field_json(f, principal.roles.get(f.id, set())) for f in rows], headers=NO_STORE)


async def _field(db: AsyncSession, field_id: uuid.UUID) -> Field:
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    return field


@router.patch("/fields/{field_id}")
async def update_field(field_id: uuid.UUID, body: FieldPatch, request: Request,
                       principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """The field's settings: whether it shares chrono records with other sharing fields (ADR-P4-5), for
    the players who consented to it (``PUT /api/v1/me/consents/chrono-sharing/{field_id}``); its public
    page and feeds (``public_page``, off by default) and what they show about the field (ADR-P4-11).
    The audit log names a text that changed, not its value. A new address changes the published games
    that show it, for calendars (``SEQUENCE``)."""
    require_field_role(principal, field_id, "admin")
    field = await _field(db, field_id)
    changed: dict[str, Any] = {}
    for name in ("chrono_sharing_enabled", "public_page"):
        value = getattr(body, name)
        if value is not None and value != getattr(field, name):
            setattr(field, name, value)
            changed[name] = value
    texts = (("description", scheduling.FIELD_DESCRIPTION_MAX, False),
             ("address_text", scheduling.LOCATION_MAX, True),
             ("federation_label", scheduling.FEDERATION_LABEL_MAX, True))
    for name, limit, one_line in texts:
        if name not in body.model_fields_set:
            continue
        try:
            clean = scheduling.clean_line if one_line else scheduling.clean_text
            value = clean(getattr(body, name), name, limit)
        except scheduling.ScheduleError as exc:
            raise HTTPException(400, exc.code) from None
        if value != getattr(field, name):
            setattr(field, name, value)
            changed[name] = "set" if value is not None else "cleared"
    if "address_text" in changed:
        await scheduling.bump_for_field_address(db, field.id, datetime.now(timezone.utc))
    if changed:
        record(db, "field_update", request, user_id=principal.user.id, resource="field", resource_id=field.id,
               details=changed)
    await db.commit()
    await db.refresh(field)
    return JSONResponse(field_json(field, principal.roles.get(field.id, set())), headers=NO_STORE)


def _may_manage(principal: Principal, field_id: uuid.UUID, role: str) -> None:
    if role in GM_GRANTS:
        require_field_role(principal, field_id, "admin", "gm")
    else:
        require_field_role(principal, field_id, "admin")


@router.get("/fields/{field_id}/roles")
async def list_roles(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    await _field(db, field_id)
    rows = await db.execute(
        select(UserFieldRole, User.username).join(User, User.id == UserFieldRole.user_id)
        .where(UserFieldRole.field_id == field_id).order_by(User.username, UserFieldRole.role_id))
    return JSONResponse([{"user_id": str(r.user_id), "username": username, "role": ROLE_BY_ID[r.role_id],
                          "granted_by": str(r.granted_by) if r.granted_by else None,
                          "granted_at": r.granted_at.isoformat()} for r, username in rows], headers=NO_STORE)


@router.put("/fields/{field_id}/roles")
async def grant_role(field_id: uuid.UUID, body: GrantIn, request: Request,
                     principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if body.role not in ROLE_NAMES:
        raise HTTPException(400, "role_invalid")
    _may_manage(principal, field_id, body.role)
    await _field(db, field_id)
    target = await db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if target is None:
        raise HTTPException(404, "user_not_found")
    if body.role in PRIVILEGED_ROLES and not target.totp_enabled:
        raise HTTPException(409, "totp_required")
    inserted = await db.scalar(
        insert(UserFieldRole).values(user_id=target.id, field_id=field_id,
                                     role_id=ROLE_NAMES[body.role], granted_by=principal.user.id)
        .on_conflict_do_nothing(index_elements=["user_id", "field_id", "role_id"]).returning(UserFieldRole.id))
    if inserted is not None:
        record(db, "role_grant", request, user_id=principal.user.id, resource="user", resource_id=target.id,
               details={"field_id": str(field_id), "role": body.role})
    await db.commit()
    return JSONResponse({"user_id": str(target.id), "username": target.username, "role": body.role,
                         "field_id": str(field_id)}, status_code=201 if inserted is not None else 200)


@router.delete("/fields/{field_id}/roles/{user_id}/{role}", status_code=204)
async def revoke_role(field_id: uuid.UUID, user_id: uuid.UUID, role: str, request: Request,
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> Response:
    if role not in ROLE_NAMES:
        raise HTTPException(400, "role_invalid")
    _may_manage(principal, field_id, role)
    gone = await db.scalar(delete(UserFieldRole).where(
        UserFieldRole.field_id == field_id, UserFieldRole.user_id == user_id,
        UserFieldRole.role_id == ROLE_NAMES[role]).returning(UserFieldRole.id))
    if gone is None:
        raise HTTPException(404, "role_not_found")
    record(db, "role_revoke", request, user_id=principal.user.id, resource="user", resource_id=user_id,
           details={"field_id": str(field_id), "role": role})
    await db.commit()
    return Response(status_code=204)


def _key_json(k: FieldApiKey) -> dict[str, Any]:
    return {"id": str(k.id), "fingerprint": sync.fingerprint(k.key_sha256), "label": k.label,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None}


@router.post("/fields/{field_id}/sync-keys", status_code=201)
async def create_sync_key(field_id: uuid.UUID, request: Request, body: Optional[SyncKeyIn] = None,
                          principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    await _field(db, field_id)
    # Lock the field's row: two requests at once cannot both see one live key and make a third.
    await db.execute(select(Field.id).where(Field.id == field_id).with_for_update())
    if await sync.live_keys(db, field_id) >= sync.MAX_LIVE_KEYS:
        raise HTTPException(409, "too_many_keys")
    label = body.label.strip() if body and body.label and body.label.strip() else None
    key = sync.new_key()
    row = FieldApiKey(field_id=field_id, key_sha256=sync.key_hash(key), label=label, created_by=principal.user.id)
    db.add(row)
    await db.flush()
    record(db, "sync_key_create", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"key_id": str(row.id), "fingerprint": sync.fingerprint(row.key_sha256)})
    await db.commit()
    await db.refresh(row)
    return JSONResponse({**_key_json(row), "key": key}, status_code=201, headers=NO_STORE)


@router.get("/fields/{field_id}/sync-keys")
async def list_sync_keys(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    await _field(db, field_id)
    rows = await db.scalars(select(FieldApiKey).where(FieldApiKey.field_id == field_id)
                            .order_by(FieldApiKey.created_at))
    return JSONResponse([_key_json(k) for k in rows], headers=NO_STORE)


@router.delete("/fields/{field_id}/sync-keys/{key_id}", status_code=204)
async def revoke_sync_key(field_id: uuid.UUID, key_id: uuid.UUID, request: Request,
                          principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_session)) -> Response:
    require_field_role(principal, field_id, "admin")
    row = await db.get(FieldApiKey, key_id)
    if row is None or row.field_id != field_id or row.revoked_at is not None:
        raise HTTPException(404, "key_not_found")
    row.revoked_at = datetime.now(timezone.utc)
    record(db, "sync_key_revoke", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"key_id": str(row.id), "fingerprint": sync.fingerprint(row.key_sha256)})
    await db.commit()
    return Response(status_code=204)
