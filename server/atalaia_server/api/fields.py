# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fields and per-field roles (ADR-P4-2's roles, ADR-P4-1's ``user_field_roles``).

    POST   /api/v1/fields                                   server administrator: a new field
    GET    /api/v1/fields                                   the fields the caller has a role on (all, for a server administrator)
    GET    /api/v1/fields/{field_id}/roles                  the field's admin or gm
    PUT    /api/v1/fields/{field_id}/roles                  {username, role}: grant
    DELETE /api/v1/fields/{field_id}/roles/{user_id}/{role} revoke

Who may grant or revoke what, on one field: its ``admin`` (and a server
administrator) any role; its ``gm`` ``player``, ``squad_leader``, ``vip``
and ``spectator``; nobody else. ``admin``, ``gm`` and ``marshal`` go only to
accounts with TOTP on (409 ``totp_required``). Every change is in the audit
log.
"""

from __future__ import annotations

import re
import uuid
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..auth import Principal, current_principal, require_field_role, server_admin
from ..db import get_session
from ..models import PRIVILEGED_ROLES, ROLE_BY_ID, ROLE_NAMES, Field, User, UserFieldRole

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


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = PydanticField(max_length=64)
    role: str = PydanticField(max_length=32)


def field_json(f: Field, roles: Any = None) -> dict[str, Any]:
    body = {"id": str(f.id), "name": f.name, "slug": f.slug, "field_type": f.field_type, "timezone": f.timezone}
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
