# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Device health (plan phase 19; RESEARCH section 8; decisions S19-7, S19-8).

    GET /api/v1/fields/{field_id}/devices?days=90   the field's admin or gm: each device (by its name) as the
                                                    latest synced game saw it: battery, link, firmware against
                                                    the catalogue, and its health flags
    GET /api/v1/games/{game}/devices                the field's admin or gm: one game's nodes with their health

Read from the synced nodes and events (``services/devices.py``); nothing is
stored for it and nothing is sent to a controller.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import Game
from ..services import devices

router = APIRouter(prefix="/api/v1", tags=["devices"])
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/fields/{field_id}/devices")
async def field_devices(field_id: uuid.UUID, request: Request,
                        days: int = Query(devices.DEVICE_DAYS, ge=1, le=devices.MAX_DEVICE_DAYS),
                        principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    keys = request.app.state.settings.firmware_keys
    return JSONResponse({"devices": await devices.field_devices(db, field_id, keys, days),
                         "battery_low_pct": devices.BATTERY_LOW_PCT, "silent_s": devices.SILENT_S},
                        headers=NO_STORE)


@router.get("/games/{game_id}/devices")
async def game_devices(game_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(404, "game_not_found")
    require_field_role(principal, game.field_id, "admin", "gm")
    keys = request.app.state.settings.firmware_keys
    return JSONResponse({"game": str(game.id), "devices": await devices.game_devices(db, game, keys)},
                        headers=NO_STORE)
