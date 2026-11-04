# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Game history shared across the fields of a hosted hub, by each field's opt-in (decisions HUBH-*;
``history_share.py`` has the rules). Hosted mode only: a single-field server answers 404 ``not_hosted``.

    GET /api/v1/fields/{field_id}/hub-history/settings   the field's admin, gm or marshal:
                                                         {hosted, field: {id, name}, enabled, since, member,
                                                          shared_games}
    PUT /api/v1/fields/{field_id}/hub-history/settings   the field's admin: {enabled}; on publishes the field's ended
                                                         games (game-level results only), off withdraws every game it
                                                         shared, at once (audited: ``hub_history_sharing``)
    GET /api/v1/fields/{field_id}/hub-history?before=&mode=&limit=
                                                         the field's admin, gm or marshal, and only while the field
                                                         shares itself (403 ``history_sharing_off``): {fields:
                                                         [{field_name, own, since, games}], games: [{field_name, own,
                                                         mode_id, started_at, ended_at, teams: [{team, score}],
                                                         winner}], next_before}, newest first, at most 200

Only fields that opted in and are active on the hub are listed; never a player, an event, a member list or a
squad. The hub's operator reads the same with ``python -m atalaia_server hosted shared-history`` (audited).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import StrictBool
from sqlalchemy.ext.asyncio import AsyncSession

from .. import history_share
from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import Field
from .auth import Strict
from .fields import NO_STORE

router = APIRouter(prefix="/api/v1", tags=["shared game history"])
STAFF = ("admin", "gm", "marshal")


class SettingsIn(Strict):
    enabled: StrictBool


async def _checked(db: AsyncSession, principal: Principal, field_id: uuid.UUID, *roles: str) -> None:
    if not history_share.available():
        raise HTTPException(404, "not_hosted")
    require_field_role(principal, field_id, *roles)
    if await db.get(Field, field_id) is None:
        raise HTTPException(404, "field_not_found")


@router.get("/fields/{field_id}/hub-history/settings")
async def get_settings(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _checked(db, principal, field_id, *STAFF)
    return JSONResponse(await history_share.state(db), headers=NO_STORE)


@router.put("/fields/{field_id}/hub-history/settings")
async def put_settings(field_id: uuid.UUID, body: SettingsIn, request: Request,
                       principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _checked(db, principal, field_id, "admin")
    if await history_share.set_enabled(db, body.enabled):
        record(db, "hub_history_sharing", request, user_id=principal.user.id, resource="field", resource_id=field_id,
               details={"enabled": body.enabled})
    await db.commit()
    return JSONResponse(await history_share.state(db), headers=NO_STORE)


@router.get("/fields/{field_id}/hub-history")
async def shared(field_id: uuid.UUID, before: Optional[str] = Query(None, max_length=64),
                 mode: Optional[str] = Query(None, max_length=128),
                 limit: int = Query(50, ge=1, le=history_share.MAX_LIMIT),
                 principal: Principal = Depends(current_principal),
                 db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _checked(db, principal, field_id, *STAFF)
    when = None
    if before is not None:
        try:
            when = datetime.fromisoformat(before)
        except ValueError:
            raise HTTPException(400, "before_invalid") from None
        when = when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)
    try:
        out = await history_share.shared_history(db, when, mode, limit)
    except history_share.HistoryShareProblem as e:
        raise HTTPException(e.status, e.detail) from None
    return JSONResponse(out, headers=NO_STORE)
