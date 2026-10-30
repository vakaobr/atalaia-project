# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Game history views (plan phase 20; ``services/history.py`` has the rules).

    GET /api/v1/fields/{field_id}/history?state=&mode=&since=&until=&before=&limit=
                                     anyone with a role on the field: its games, newest first, with their
                                     teams, totals and winner (a live game's totals delayed for non-staff)
    GET /api/v1/games/{game}/timeline
                                     a role on the field or the game: the totals after each batch the site
                                     server received, derived from the per-node counters
    GET /api/v1/games/{game}/log?type=&team=&from_ms=&to_ms=&after=&limit=
                                     a role on the field or the game: the event log by type and game time,
                                     with the count of each type; whole for staff, without secrets, telemetry
                                     and player ids for the others, and delayed while the game is live
    GET /api/v1/fields/{field_id}/history/settings   the field's admin or gm
    PUT /api/v1/fields/{field_id}/history/settings   the field's admin: {public_scoreboard, spectator_delay_s,
                                                     retention_days}

``GET /api/v1/games/{game}`` and ``/events`` (plan phase 13) stay as they were; the public scoreboard is
``web/scoreboard.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..history_models import MAX_DELAY_S, MAX_RETENTION_DAYS, MIN_RETENTION_DAYS, FieldHistorySettings
from ..models import Field, Game, GameEvent, GameResult
from ..services import history
from .fields import NO_STORE
from .games import game_json, game_roles

router = APIRouter(prefix="/api/v1", tags=["history"])
STATES = ("ready", "running", "paused", "ended")


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    public_scoreboard: Optional[bool] = None
    spectator_delay_s: Optional[int] = None
    retention_days: Optional[int] = None


def _time(value: Optional[str], name: str) -> Optional[datetime]:
    if value is None:
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(400, f"{name}_invalid") from None
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


async def _viewer(db: AsyncSession, principal: Principal, game: Game) -> bool:
    """403 unless the caller has a role on the game's field or on the game; True for staff."""
    field_roles = principal.field_roles(game.field_id) | ({"admin"} if principal.is_server_admin else set())
    mine = await game_roles(db, principal, game.id)
    if not field_roles and not mine:
        raise HTTPException(403, "role_required")
    return history.is_staff(field_roles, mine)


async def _game(db: AsyncSession, game_id: uuid.UUID) -> Game:
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(404, "game_not_found")
    return game


@router.get("/fields/{field_id}/history")
async def field_history(field_id: uuid.UUID, state: Optional[str] = None,
                        mode: Optional[str] = Query(None, max_length=128), since: Optional[str] = None, until: Optional[str] = None, before: Optional[str] = None,
                        limit: int = Query(50, ge=1, le=200), principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    roles = principal.field_roles(field_id) | ({"admin"} if principal.is_server_admin else set())
    if not roles:
        raise HTTPException(403, "role_required")
    staff = history.is_staff(roles, set())
    stmt = select(Game).where(Game.field_id == field_id)
    if state is not None:
        if state not in STATES:
            raise HTTPException(400, "state_invalid")
        stmt = stmt.where(Game.state == state)
    if mode:
        stmt = stmt.where(Game.mode_id == mode)
    when = func.coalesce(Game.started_at, Game.controller_created_at)
    for value, name, op in ((since, "since", "ge"), (until, "until", "lt"), (before, "before", "lt")):
        t = _time(value, name)
        if t is not None:
            stmt = stmt.where(when >= t if op == "ge" else when < t)
    rows = list(await db.scalars(stmt.order_by(when.desc(), Game.id.desc()).limit(limit)))
    delay = (await history.settings(db, field_id))["spectator_delay_s"]
    now = datetime.now(timezone.utc)
    out = []
    for g in rows:
        cut = history.cutoff(g, delay, staff, now)
        out.append({**game_json(g), **history.game_summary(g, await history.totals_until(db, g, cut)),
                    "delayed": cut is not None})
    nxt = (rows[-1].started_at or rows[-1].controller_created_at).isoformat() if len(rows) == limit else None
    return JSONResponse({"games": out, "next_before": nxt}, headers=NO_STORE)


@router.get("/fields/{field_id}/history/results")
async def field_results(field_id: uuid.UUID, limit: int = Query(100, ge=1, le=500),
                        principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """The team results of games whose per-player history is gone (90 days by default), kept 365 days after the game: name,
    mode, teams, the teams' final totals, the winner, when. No player and no member list (maintainer decision
    2026-10-30). Any role on the field."""
    roles = principal.field_roles(field_id) | ({"admin"} if principal.is_server_admin else set())
    if not roles:
        raise HTTPException(403, "role_required")
    rows = await db.scalars(select(GameResult).where(GameResult.field_id == field_id)
                            .order_by(GameResult.ended_at.desc(), GameResult.id.desc()).limit(limit))
    return JSONResponse({"results": [
        {"name": r.name, "mode_id": r.mode_id, "teams": r.teams, "team_totals": r.team_totals, "winner": r.winner,
         "state": r.state, "duration_ms": r.duration_ms, "started_at": r.started_at.isoformat() if r.started_at else None,
         "ended_at": r.ended_at.isoformat()} for r in rows]}, headers=NO_STORE)


@router.get("/games/{game_id}/timeline")
async def game_timeline(game_id: uuid.UUID, principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    game = await _game(db, game_id)
    staff = await _viewer(db, principal, game)
    delay = (await history.settings(db, game.field_id))["spectator_delay_s"]
    cut = history.cutoff(game, delay, staff)
    points = await history.timeline(db, game, cut)
    totals = await history.totals_until(db, game, cut)
    return JSONResponse({"game": {**history.game_summary(game, totals), "field_id": str(game.field_id)},
                         "points": points, "delayed_until": cut.isoformat() if cut else None}, headers=NO_STORE)


@router.get("/games/{game_id}/log")
async def game_log(game_id: uuid.UUID, type: Optional[str] = Query(None, max_length=512),  # noqa: A002
                   team: Optional[str] = Query(None, max_length=32), from_ms: Optional[int] = Query(None, ge=0),
                   to_ms: Optional[int] = Query(None, ge=0), after: int = Query(0, ge=0),
                   limit: int = Query(500, ge=1, le=1000), principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    game = await _game(db, game_id)
    staff = await _viewer(db, principal, game)
    delay = (await history.settings(db, game.field_id))["spectator_delay_s"]
    cut = history.cutoff(game, delay, staff)
    base = [GameEvent.game == game.id]
    if cut is not None:
        base.append(GameEvent.received_at <= cut)
    if not staff:
        base.append(GameEvent.priority != "telemetry")
    counts = {t: int(n) for t, n in await db.execute(
        select(GameEvent.event_type, func.count()).where(*base).group_by(GameEvent.event_type)
        .order_by(GameEvent.event_type))}
    where = list(base)
    if type:
        types = [t.strip() for t in type.split(",") if t.strip()]
        where.append(GameEvent.event_type.in_(types))
    if team:
        where.append(GameEvent.team == team)
    if from_ms is not None:
        where.append(GameEvent.game_time_ms >= from_ms)
    if to_ms is not None:
        where.append(GameEvent.game_time_ms <= to_ms)
    rows = list(await db.scalars(select(GameEvent).where(*where, GameEvent.id > after)
                                 .order_by(GameEvent.game_time_ms, GameEvent.id).limit(limit)))
    events = [e for e in (history.event_json(r, staff) for r in rows) if e is not None]
    return JSONResponse({"events": events, "types": counts, "next": rows[-1].id if len(rows) == limit else None,
                         "delayed_until": cut.isoformat() if cut else None}, headers=NO_STORE)


async def _settings_json(db: AsyncSession, field: Field) -> dict[str, Any]:
    return {"public_scoreboard": field.public_scoreboard, **await history.settings(db, field.id)}


@router.get("/fields/{field_id}/history/settings")
async def get_settings(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    return JSONResponse(await _settings_json(db, field), headers=NO_STORE)


@router.put("/fields/{field_id}/history/settings")
async def put_settings(field_id: uuid.UUID, body: SettingsIn, request: Request,
                       principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    current = await history.settings(db, field_id)
    changed: dict[str, Any] = {}
    if body.spectator_delay_s is not None:
        if isinstance(body.spectator_delay_s, bool) or not 0 <= body.spectator_delay_s <= MAX_DELAY_S:
            raise HTTPException(400, "spectator_delay_s_invalid")
        if body.spectator_delay_s != current["spectator_delay_s"]:
            current["spectator_delay_s"] = changed["spectator_delay_s"] = body.spectator_delay_s
    if body.retention_days is not None:
        if isinstance(body.retention_days, bool) or not MIN_RETENTION_DAYS <= body.retention_days \
                <= MAX_RETENTION_DAYS:
            raise HTTPException(400, "retention_days_invalid")
        if body.retention_days != current["retention_days"]:
            current["retention_days"] = changed["retention_days"] = body.retention_days
    if body.public_scoreboard is not None and body.public_scoreboard != field.public_scoreboard:
        field.public_scoreboard = changed["public_scoreboard"] = body.public_scoreboard
    if {"spectator_delay_s", "retention_days"} & changed.keys():
        stmt = insert(FieldHistorySettings).values(field_id=field_id, spectator_delay_s=current["spectator_delay_s"],
                                                   retention_days=current["retention_days"])
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["field_id"], set_={"spectator_delay_s": stmt.excluded.spectator_delay_s,
                                               "retention_days": stmt.excluded.retention_days,
                                               "updated_at": func.now()}))
    if changed:
        record(db, "history_settings", request, user_id=principal.user.id, resource="field", resource_id=field_id,
               details=changed)
    await db.commit()
    await db.refresh(field)
    return JSONResponse(await _settings_json(db, field), headers=NO_STORE)
