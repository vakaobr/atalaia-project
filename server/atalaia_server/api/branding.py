# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A field's branding and saved teams (P4R19; plan phase 18), which its controllers pull with
``[sync] branding = "site"`` (``GET /api/v1/sync/field``).

    GET    /api/v1/fields/{field_id}/branding                    the field's admin or gm
    PATCH  /api/v1/fields/{field_id}/branding                    admin: {field_name, accent} (null clears)
    PUT    /api/v1/fields/{field_id}/branding/{logo|wallpaper}?rights_confirmed=true   admin: the raw image
    DELETE /api/v1/fields/{field_id}/branding/{logo|wallpaper}   admin
    GET    /api/v1/fields/{field_id}/teams                       admin or gm: the saved teams
    POST   /api/v1/fields/{field_id}/teams                       admin or gm: {name?, colour?, club_slug?}
    PATCH  /api/v1/fields/{field_id}/teams/{team_id}             admin or gm: {name?, colour?}
    DELETE /api/v1/fields/{field_id}/teams/{team_id}             admin or gm
    PUT    /api/v1/fields/{field_id}/teams/{team_id}/crest?rights_confirmed=true      admin or gm: the team's own
    DELETE /api/v1/fields/{field_id}/teams/{team_id}/crest       the team's own crest (a club's team: the club's again)

Images are the raw body with its ``Content-Type`` (PNG, JPEG or WebP), checked by the controller's
``images.py`` with the controller's limits; each upload must say ``rights_confirmed=true`` and its answer
carries the rights reminder (decision S18-4). A club's team uses the club's short name and crest unless
the team sets its own; a club whose page is not public can be added only by one of its members
(decision S18-6). Every change is in the audit log.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from atalaia_controller import images
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import Club, Field, FieldTeam
from ..services import branding as svc

router = APIRouter(prefix="/api/v1", tags=["branding"])
NO_STORE = {"Cache-Control": "no-store"}
FIELD_SLOTS = ("logo", "wallpaper")
STAFF = ("admin", "gm")


class BrandingPatch(BaseModel):
    """Only the members sent change; ``null`` or ``""`` clears."""

    model_config = ConfigDict(extra="forbid")
    field_name: Optional[str] = PydanticField(default=None, max_length=256)
    accent: Optional[str] = PydanticField(default=None, max_length=16)


class TeamIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = PydanticField(default=None, max_length=256)
    colour: Optional[str] = PydanticField(default=None, max_length=64)
    club_slug: Optional[str] = PydanticField(default=None, max_length=128)


class TeamPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Optional[str] = PydanticField(default=None, max_length=256)
    colour: Optional[str] = PydanticField(default=None, max_length=64)


def problem(exc: svc.BrandingError) -> HTTPException:
    return HTTPException(exc.status, exc.code)


async def read_upload(request: Request, kind: str) -> tuple[bytes, str]:
    """The raw body, at most the kind's limit (413 past it, without reading the rest), and its type; the upload
    must confirm the uploader's rights (``rights_confirmed=true``)."""
    if request.query_params.get("rights_confirmed") != "true":
        raise HTTPException(400, "rights_not_confirmed")
    limit = images.KINDS[kind].max_bytes
    try:
        declared = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared = 0
    if declared > limit:
        raise HTTPException(413, f"the {kind} is over {limit} bytes")
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > limit:
            raise HTTPException(413, f"the {kind} is over {limit} bytes")
    return bytes(data), request.headers.get("content-type", "")


async def checked_image(db: AsyncSession, request: Request, kind: str) -> str:
    """The upload checked and stored: its SHA-256 (ImageError becomes its 413, 415 or 422)."""
    data, content_type = await read_upload(request, kind)
    try:
        row = await svc.store_image(db, data, content_type, kind)
    except images.ImageError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    return row.sha256


async def _field(db: AsyncSession, field_id: uuid.UUID, lock: bool = False) -> Field:
    query = select(Field).where(Field.id == field_id)
    field = await db.scalar(query.with_for_update() if lock else query)
    if field is None:
        raise HTTPException(404, "field_not_found")
    return field


async def _answer(db: AsyncSession, field: Field, extra: Optional[dict[str, Any]] = None) -> JSONResponse:
    body = await svc.field_branding(db, field)
    return JSONResponse({**body, **(extra or {})}, headers=NO_STORE)


@router.get("/fields/{field_id}/branding")
async def get_branding(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    return await _answer(db, await _field(db, field_id))


@router.patch("/fields/{field_id}/branding")
async def patch_branding(field_id: uuid.UUID, body: BrandingPatch, request: Request,
                         principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    field = await _field(db, field_id)
    changed: dict[str, Any] = {}
    try:
        if "field_name" in body.model_fields_set:
            name = svc.one_line(body.field_name, "field_name", svc.FIELD_NAME_MAX)
            if name != field.branding_name:
                field.branding_name = name
                changed["field_name"] = "set" if name else "cleared"
        if "accent" in body.model_fields_set:
            value = svc.accent(body.accent)
            if value != field.accent:
                field.accent = changed["accent"] = value
    except svc.BrandingError as exc:
        raise problem(exc) from None
    if changed:
        record(db, "field_branding_update", request, user_id=principal.user.id, resource="field",
               resource_id=field.id, details=changed)
    await db.commit()
    await db.refresh(field)
    return await _answer(db, field)


def _slot(slot: str) -> str:
    if slot not in FIELD_SLOTS:
        raise HTTPException(404, "slot_not_found")
    return slot


@router.put("/fields/{field_id}/branding/{slot}")
async def put_field_image(field_id: uuid.UUID, slot: str, request: Request,
                          principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    field = await _field(db, field_id)
    sha = await checked_image(db, request, _slot(slot))
    setattr(field, f"{slot}_sha256", sha)
    record(db, "field_branding_image", request, user_id=principal.user.id, resource="field", resource_id=field.id,
           details={"slot": slot, "sha256": sha})
    await db.commit()
    await db.refresh(field)
    return await _answer(db, field, {"rights_notice": svc.RIGHTS_NOTICE})


@router.delete("/fields/{field_id}/branding/{slot}")
async def delete_field_image(field_id: uuid.UUID, slot: str, request: Request,
                             principal: Principal = Depends(current_principal),
                             db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    field = await _field(db, field_id)
    if getattr(field, f"{_slot(slot)}_sha256") is not None:
        setattr(field, f"{slot}_sha256", None)
        record(db, "field_branding_image", request, user_id=principal.user.id, resource="field",
               resource_id=field.id, details={"slot": slot, "sha256": None})
    await db.commit()
    await db.refresh(field)
    return await _answer(db, field)


# --- saved teams ---------------------------------------------------------------------------

async def _teams(db: AsyncSession, field_id: uuid.UUID) -> list[dict[str, Any]]:
    return [await svc.team_json(db, t, c) for t, c in await svc.field_teams(db, field_id)]


async def _team(db: AsyncSession, field_id: uuid.UUID, team_id: uuid.UUID) -> tuple[FieldTeam, Optional[Club]]:
    team = await db.get(FieldTeam, team_id)
    if team is None or team.field_id != field_id:
        raise HTTPException(404, "team_not_found")
    club = await db.get(Club, team.club_id) if team.club_id is not None else None
    return team, club


async def _saved(db: AsyncSession, team: FieldTeam, club: Optional[Club], status: int = 200,
                 extra: Optional[dict[str, Any]] = None) -> JSONResponse:
    """Checks the field's names are still unique, commits and answers the team."""
    try:
        await svc.check_team_names(db, team.field_id)
    except svc.BrandingError as exc:
        await db.rollback()
        raise problem(exc) from None
    await db.commit()
    await db.refresh(team)
    return JSONResponse({**await svc.team_json(db, team, club), **(extra or {})}, status_code=status,
                        headers=NO_STORE)


@router.get("/fields/{field_id}/teams")
async def list_teams(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    await _field(db, field_id)
    return JSONResponse(await _teams(db, field_id), headers=NO_STORE)


@router.post("/fields/{field_id}/teams", status_code=201)
async def add_team(field_id: uuid.UUID, body: TeamIn, request: Request,
                   principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    await _field(db, field_id, lock=True)  # one change to the field's teams at a time: names stay unique
    club = None
    if body.club_slug is not None:
        club = await db.scalar(select(Club).where(Club.slug == body.club_slug.strip().lower()))
        # A club that is not public is there only for its members (and a server administrator).
        if club is None or not (svc.club_visible(club) or principal.is_server_admin
                                or await svc.club_role(db, club.id, principal.user.id) is not None):
            raise HTTPException(404, "club_not_found")
    try:
        name = svc.one_line(body.name, "name", svc.TEAM_NAME_MAX, required=club is None)
        colour = svc.team_colour(body.colour)
    except svc.BrandingError as exc:
        raise problem(exc) from None
    count = len(await svc.field_teams(db, field_id))
    if count >= svc.MAX_TEAMS:
        raise HTTPException(409, "too_many_teams")
    team = FieldTeam(field_id=field_id, club_id=club.id if club else None, name=name, colour=colour)
    db.add(team)
    await db.flush()
    record(db, "field_team_create", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"team_id": str(team.id), "club": club.slug if club else None})
    return await _saved(db, team, club, status=201)


@router.patch("/fields/{field_id}/teams/{team_id}")
async def patch_team(field_id: uuid.UUID, team_id: uuid.UUID, body: TeamPatch, request: Request,
                     principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    await _field(db, field_id, lock=True)
    team, club = await _team(db, field_id, team_id)
    changed: dict[str, Any] = {}
    try:
        if "name" in body.model_fields_set:
            name = svc.one_line(body.name, "name", svc.TEAM_NAME_MAX, required=club is None)
            if name != team.name:
                team.name = name
                changed["name"] = "set" if name else "cleared"
        if "colour" in body.model_fields_set:
            colour = svc.team_colour(body.colour)
            if colour != team.colour:
                team.colour = changed["colour"] = colour
    except svc.BrandingError as exc:
        raise problem(exc) from None
    if changed:
        record(db, "field_team_update", request, user_id=principal.user.id, resource="field", resource_id=field_id,
               details={"team_id": str(team.id), **changed})
    return await _saved(db, team, club)


@router.delete("/fields/{field_id}/teams/{team_id}", status_code=204)
async def delete_team(field_id: uuid.UUID, team_id: uuid.UUID, request: Request,
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> Response:
    require_field_role(principal, field_id, *STAFF)
    team, _ = await _team(db, field_id, team_id)
    await db.delete(team)
    record(db, "field_team_delete", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"team_id": str(team_id)})
    await db.commit()
    return Response(status_code=204)


@router.put("/fields/{field_id}/teams/{team_id}/crest")
async def put_team_crest(field_id: uuid.UUID, team_id: uuid.UUID, request: Request,
                         principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    team, club = await _team(db, field_id, team_id)
    team.crest_sha256 = await checked_image(db, request, "crest")
    record(db, "field_team_crest", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"team_id": str(team.id), "sha256": team.crest_sha256})
    return await _saved(db, team, club, extra={"rights_notice": svc.RIGHTS_NOTICE})


@router.delete("/fields/{field_id}/teams/{team_id}/crest")
async def delete_team_crest(field_id: uuid.UUID, team_id: uuid.UUID, request: Request,
                            principal: Principal = Depends(current_principal),
                            db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    team, club = await _team(db, field_id, team_id)
    if team.crest_sha256 is not None:
        team.crest_sha256 = None
        record(db, "field_team_crest", request, user_id=principal.user.id, resource="field",
               resource_id=field_id, details={"team_id": str(team.id), "sha256": None})
    return await _saved(db, team, club)
