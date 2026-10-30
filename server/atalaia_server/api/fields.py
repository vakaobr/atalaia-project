# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fields and per-field roles (ADR-P4-2's roles, ADR-P4-1's ``user_field_roles``).

    POST   /api/v1/fields                                   server administrator: a new field
    GET    /api/v1/fields                                   the fields the caller has a role on (all, for a server administrator)
    PATCH  /api/v1/fields/{field_id}                        the field's admin: {chrono_sharing_enabled} (plan phase 14),
                                                            {public_page, description, address_text,
                                                            federation_label} (plan phase 15), {limit_template,
                                                            max_replicas} (plan phase 16: registration's replicas)
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

from atalaia_controller import apd as apd_core, sync_format

from .. import chrono_registry, hub_share, sync
from ..services import branding, registration, scheduling
from ..audit import record
from ..auth import Principal, current_principal, require_field_role, server_admin
from ..db import get_session
from ..models import PRIVILEGED_ROLES, ROLE_BY_ID, ROLE_NAMES, Field, FieldApiKey, User, UserFieldRole
from .auth import has_second_factor

router = APIRouter(prefix="/api/v1", tags=["fields"])

FIELD_TYPES = ("outdoor", "cqb", "indoor")
SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?")
SYNC_LABEL_MAX = 64   # a sync key's label (the staff page's input shows the same limit)
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
    limit_template: Optional[str] = PydanticField(default=None, max_length=32)
    max_replicas: Optional[int] = None
    apd: Optional[dict[str, Any]] = None  # the whole APD rule (protocol/apd.md); {} puts the default back
    country: Optional[str] = PydanticField(default=None, max_length=8)  # ISO 3166-1 alpha-2; null or "" unsets it
    # Days the field's controllers keep chrono records (also this server's registry) and an ended game's data (RET-1/2).
    chrono_retention_days: Optional[int] = None
    game_retention_days: Optional[int] = None
    # PRIV-2: how long a "ban" outcome lasts (days; null puts the default back: 12 months, within the chrono retention).
    chrono_ban_days: Optional[int] = None


class SyncKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Optional[str] = PydanticField(default=None, max_length=SYNC_LABEL_MAX)


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = PydanticField(max_length=64)
    role: str = PydanticField(max_length=32)


def _days_ok(days: Any) -> bool:
    """A retention period the controllers take (``sync_format.RETENTION_DAYS_MIN`` to ``_MAX``)."""
    return (isinstance(days, int) and not isinstance(days, bool)
            and sync_format.RETENTION_DAYS_MIN <= days <= sync_format.RETENTION_DAYS_MAX)


def field_json(f: Field, roles: Any = None) -> dict[str, Any]:
    body = {"id": str(f.id), "name": f.name, "slug": f.slug, "field_type": f.field_type, "timezone": f.timezone,
            "chrono_sharing_enabled": f.chrono_sharing_enabled, "public_page": f.public_page,
            "description": f.description, "address_text": f.address_text, "federation_label": f.federation_label,
            "limit_template": f.limit_template, "max_replicas": f.max_replicas, "apd": registration.field_rule(f),
            "country": f.country, "chrono_retention_days": f.default_retention_days,
            "game_retention_days": f.game_retention_days, "chrono_ban_days": f.chrono_ban_days}
    if roles is not None:
        body["my_roles"] = sorted(roles)
    return body


@router.post("/fields", status_code=201)
async def create_field(body: FieldIn, request: Request, principal: Principal = Depends(server_admin),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if request.app.state.settings.hosted:  # one field per tenant, made by the hub's operator (S21-2)
        raise HTTPException(403, "hosted_one_field")
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
    field = Field(name=name, slug=body.slug, field_type=body.field_type, timezone=body.timezone,
                  country=apd_core.default_country(body.timezone))  # PT in Portugal's time zones (decision MEM-2)
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
    # Registration's replica rules: the same as the field controller's [checkin] settings.
    if body.limit_template is not None and body.limit_template != field.limit_template:
        if body.limit_template not in registration.limit_templates():
            raise HTTPException(400, "limit_template_invalid")
        field.limit_template = changed["limit_template"] = body.limit_template
    if body.max_replicas is not None and body.max_replicas != field.max_replicas:
        if isinstance(body.max_replicas, bool) or not 1 <= body.max_replicas <= registration.MAX_REPLICAS:
            raise HTTPException(400, "max_replicas_invalid")
        field.max_replicas = changed["max_replicas"] = body.max_replicas
    if "apd" in body.model_fields_set:
        try:
            rule = apd_core.check_rule(body.apd)
        except apd_core.ApdError:
            raise HTTPException(400, "apd_rule_invalid") from None
        if rule != registration.field_rule(field):
            field.apd_rule = rule
            changed["apd"] = "set"  # the audit log names the change, not the field's own entries
    if "country" in body.model_fields_set:
        typed = (body.country or "").strip().upper()  # null and "" unset it; the case typed does not matter
        try:
            country = apd_core.check_country(typed or None)
        except apd_core.ApdError:
            raise HTTPException(400, "country_invalid") from None
        if country != field.country:
            field.country = country
            changed["country"] = country or "cleared"
    if body.chrono_retention_days is not None:
        if not _days_ok(body.chrono_retention_days):
            raise HTTPException(400, "chrono_retention_days_invalid")
        if body.chrono_retention_days != field.default_retention_days:
            field.default_retention_days = changed["chrono_retention_days"] = body.chrono_retention_days
    if body.game_retention_days is not None:
        if not _days_ok(body.game_retention_days):
            raise HTTPException(400, "game_retention_days_invalid")
        if body.game_retention_days != field.game_retention_days:
            field.game_retention_days = changed["game_retention_days"] = body.game_retention_days
    if "chrono_ban_days" in body.model_fields_set:  # null: the field's chrono retention (the most a ban can last)
        days = body.chrono_ban_days
        if days is not None and (isinstance(days, bool) or not 1 <= days <= field.default_retention_days):
            raise HTTPException(400, "chrono_ban_days_invalid")
        if days != field.chrono_ban_days:
            field.chrono_ban_days = days
            changed["chrono_ban_days"] = days
    if "address_text" in changed:
        await scheduling.bump_for_field_address(db, field.id, datetime.now(timezone.utc))
    if "chrono_sharing_enabled" in changed:
        await hub_share.sync_all(db)  # a hosted hub's shared view follows the field's switch (SVX-2)
    if changed:
        record(db, "field_update", request, user_id=principal.user.id, resource="field", resource_id=field.id,
               details=changed)
    await db.commit()
    if changed.keys() & {"limit_template", "max_replicas", "federation_label", "apd", "country",
                             "chrono_retention_days", "game_retention_days"}:
        branding.announce(request, [field.id])  # the controllers take over the field's check-in settings (BR24)
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
    if body.role in PRIVILEGED_ROLES and (target is None or not await has_second_factor(db, target)):
        raise HTTPException(409, "totp_required")  # one answer for "no such account" and "no second factor" (SRV-4)
    if target is None:
        raise HTTPException(404, "user_not_found")
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
    request.app.state.remote_hub.detach_key(row.id)  # its controllers' links take no more remote commands
    return Response(status_code=204)
