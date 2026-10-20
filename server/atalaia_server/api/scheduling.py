# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scheduled games (ADR-P4-11; plan phase 15, decisions F13, S15-*).

    POST   /api/v1/fields/{field_id}/scheduled-games              admin or gm: a new draft
    GET    /api/v1/fields/{field_id}/scheduled-games?status=&from= admin or gm: every game, drafts too
    GET    /api/v1/fields/{field_id}/scheduled-games/{id}         admin or gm
    PATCH  /api/v1/fields/{field_id}/scheduled-games/{id}         admin or gm: a draft or a published game
    DELETE /api/v1/fields/{field_id}/scheduled-games/{id}         admin or gm: a draft only
    POST   /api/v1/fields/{field_id}/scheduled-games/{id}/publish admin: on the field page and the feeds
    POST   /api/v1/fields/{field_id}/scheduled-games/{id}/cancel  admin: {reason}; stays visible, cancelled

The roles are the field's, in a TOTP session (``admin`` and ``gm`` count only there). Times
are RFC 3339 with an offset and are kept in UTC; the field's time zone is for showing them.
Every change is in the audit log (``schedule_create``, ``schedule_update`` with the names of
what changed, ``schedule_publish``, ``schedule_cancel``, ``schedule_delete``). The rules are in
``services/scheduling.py``; the public pages and feeds in ``web/field_pages.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import SCHEDULED_STATUSES, Field, ScheduledGame
from ..services import scheduling as svc
from .fields import NO_STORE

router = APIRouter(prefix="/api/v1", tags=["scheduling"])


class ScheduledGameIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    description: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    location_text: Optional[str] = None
    mode_id: Optional[str] = None
    teams: list[str] = []
    max_players: Optional[int] = None
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    federation: str = "off"
    predeclare_replicas: bool = True


class ScheduledGamePatch(BaseModel):
    """Only the members sent change; ``null`` clears an optional one."""

    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = None
    description: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    location_text: Optional[str] = None
    mode_id: Optional[str] = None
    teams: Optional[list[str]] = None
    max_players: Optional[int] = None
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    federation: Optional[str] = None
    predeclare_replicas: Optional[bool] = None


class CancelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str


# Members that cannot be cleared with null.
REQUIRED = frozenset({"title", "starts_at", "ends_at", "teams", "federation", "predeclare_replicas"})


def _values(body: BaseModel, sent: set[str]) -> dict[str, Any]:
    """The sent members, each checked on its own and in its stored form."""
    out: dict[str, Any] = {}
    for name in sent:
        value = getattr(body, name)
        if value is None and name in REQUIRED:
            raise svc.ScheduleError(f"{name}_invalid")
        if name == "title":
            value = svc.clean_line(value, "title", svc.TITLE_MAX, required=True)
        elif name == "description":
            value = svc.clean_text(value, "description", svc.DESCRIPTION_MAX)
        elif name == "location_text":
            value = svc.clean_line(value, "location_text", svc.LOCATION_MAX)
        elif name == "mode_id":
            value = (value or "").strip() or None
        elif name == "teams":
            value = svc.clean_teams(value)
        elif name in ("starts_at", "ends_at", "registration_opens_at", "registration_closes_at"):
            value = svc.aware(value, name)
        out[name] = value
    return out


def _error(exc: svc.ScheduleError) -> HTTPException:
    return HTTPException(exc.status, exc.code)


async def _field(db: AsyncSession, field_id: uuid.UUID) -> Field:
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    return field


async def _game(db: AsyncSession, field_id: uuid.UUID, game_id: uuid.UUID, lock: bool = False) -> ScheduledGame:
    query = select(ScheduledGame).where(ScheduledGame.id == game_id, ScheduledGame.field_id == field_id)
    game = await db.scalar(query.with_for_update() if lock else query)
    if game is None:
        raise HTTPException(404, "scheduled_game_not_found")
    return game


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _answer(db: AsyncSession, game: ScheduledGame, field: Field, status_code: int = 200) -> JSONResponse:
    await db.refresh(game)
    return JSONResponse(svc.staff_json(game, field, _now()), status_code=status_code, headers=NO_STORE)


@router.post("/fields/{field_id}/scheduled-games", status_code=201)
async def create_game(field_id: uuid.UUID, body: ScheduledGameIn, request: Request,
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    field = await _field(db, field_id)
    try:
        values = _values(body, set(ScheduledGameIn.model_fields))
        game = ScheduledGame(field_id=field_id, created_by=principal.user.id, status="draft", ical_sequence=0,
                             **values)
        svc.check(game)
    except svc.ScheduleError as exc:
        raise _error(exc) from None
    db.add(game)
    await db.flush()
    record(db, "schedule_create", request, user_id=principal.user.id, resource="scheduled_game",
           resource_id=game.id, details={"field_id": str(field_id)})
    await db.commit()
    return await _answer(db, game, field, 201)


@router.get("/fields/{field_id}/scheduled-games")
async def list_games(field_id: uuid.UUID, status: Optional[str] = Query(default=None),
                     since: Optional[datetime] = Query(default=None, alias="from"),
                     principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """The field's games by start, drafts included; ``status`` filters, ``from`` keeps the games that
    end after that time."""
    require_field_role(principal, field_id, "admin", "gm")
    field = await _field(db, field_id)
    query = select(ScheduledGame).where(ScheduledGame.field_id == field_id)
    if status is not None:
        if status not in SCHEDULED_STATUSES:
            raise HTTPException(400, "status_invalid")
        query = query.where(ScheduledGame.status == status)
    if since is not None:
        try:
            query = query.where(ScheduledGame.ends_at > svc.aware(since, "from"))
        except svc.ScheduleError as exc:
            raise _error(exc) from None
    rows = await db.scalars(query.order_by(ScheduledGame.starts_at, ScheduledGame.id))
    now = _now()
    return JSONResponse([svc.staff_json(g, field, now) for g in rows], headers=NO_STORE)


@router.get("/fields/{field_id}/scheduled-games/{game_id}")
async def get_game(field_id: uuid.UUID, game_id: uuid.UUID, principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    field = await _field(db, field_id)
    game = await _game(db, field_id, game_id)
    return JSONResponse(svc.staff_json(game, field, _now()), headers=NO_STORE)


@router.patch("/fields/{field_id}/scheduled-games/{game_id}")
async def update_game(field_id: uuid.UUID, game_id: uuid.UUID, body: ScheduledGamePatch, request: Request,
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    field = await _field(db, field_id)
    game = await _game(db, field_id, game_id, lock=True)
    if game.status not in svc.EDITABLE:
        raise HTTPException(409, "not_editable")
    try:
        values = _values(body, set(body.model_fields_set))
        changed = sorted(name for name, value in values.items() if getattr(game, name) != value)
        for name in changed:
            setattr(game, name, values[name])
        svc.check(game)
    except svc.ScheduleError as exc:
        await db.rollback()
        raise _error(exc) from None
    if changed:
        svc.note_change(game, changed)
        record(db, "schedule_update", request, user_id=principal.user.id, resource="scheduled_game",
               resource_id=game.id, details={"field_id": str(field_id), "changed": changed})
    await db.commit()
    return await _answer(db, game, field)


@router.delete("/fields/{field_id}/scheduled-games/{game_id}", status_code=204)
async def delete_game(field_id: uuid.UUID, game_id: uuid.UUID, request: Request,
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> Response:
    """A draft only: anything published may be on someone's calendar, so it is cancelled instead."""
    require_field_role(principal, field_id, "admin", "gm")
    game = await _game(db, field_id, game_id, lock=True)
    if game.status != "draft":
        raise HTTPException(409, "not_a_draft")
    await db.delete(game)
    record(db, "schedule_delete", request, user_id=principal.user.id, resource="scheduled_game",
           resource_id=game_id, details={"field_id": str(field_id)})
    await db.commit()
    return Response(status_code=204)


@router.post("/fields/{field_id}/scheduled-games/{game_id}/publish")
async def publish_game(field_id: uuid.UUID, game_id: uuid.UUID, request: Request,
                       principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    field = await _field(db, field_id)
    game = await _game(db, field_id, game_id, lock=True)
    try:
        svc.publish(game, _now())
    except svc.ScheduleError as exc:
        raise _error(exc) from None
    record(db, "schedule_publish", request, user_id=principal.user.id, resource="scheduled_game",
           resource_id=game.id, details={"field_id": str(field_id)})
    await db.commit()
    return await _answer(db, game, field)


@router.post("/fields/{field_id}/scheduled-games/{game_id}/cancel")
async def cancel_game(field_id: uuid.UUID, game_id: uuid.UUID, body: CancelIn, request: Request,
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    field = await _field(db, field_id)
    game = await _game(db, field_id, game_id, lock=True)
    try:
        svc.cancel(game, body.reason, _now())
    except svc.ScheduleError as exc:
        raise _error(exc) from None
    record(db, "schedule_cancel", request, user_id=principal.user.id, resource="scheduled_game",
           resource_id=game.id, details={"field_id": str(field_id)})
    await db.commit()
    return await _answer(db, game, field)
