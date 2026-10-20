# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""``GET /api/v1/health`` (public) and ``GET /api/v1/metrics`` (administrators), ADR-P4-10.

Health answers 200 ``{"status": "healthy", "database": "connected", ...}``
when PostgreSQL answers, and 503 with ``"unhealthy"`` and
``"unreachable"`` when it does not, so an uptime monitor or the container's
health check sees an outage. Metrics need ``Authorization: Bearer`` with a
server administrator's access token from a login that passed TOTP (plan
phase 11, decision S10-2), or with ATALAIA_METRICS_TOKEN when one is set,
for a monitoring system that cannot log in (decision S11-9): 401 without
either, 403 for any other account. They report only what the tables so far
hold; later plan phases add their counters.
"""

from __future__ import annotations

import hmac
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from .. import __version__
from ..auth import UNAUTHORISED, bearer, principal_from_token
from ..db import ping
from ..models import ChronoReading, ChronoReject, Controller, Field, Game, GameEvent, User, UserSession

router = APIRouter(prefix="/api/v1", tags=["health"])


def _uptime(request: Request) -> int:
    return int(time.monotonic() - request.app.state.started)


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    up = await ping(request.app.state.engine, settings.db_timeout_s)
    body = {
        "status": "healthy" if up else "unhealthy",
        "database": "connected" if up else "unreachable",
        "version": __version__,
        "uptime_s": _uptime(request),
    }
    return JSONResponse(body, status_code=200 if up else 503, headers={"Cache-Control": "no-store"})


async def _check_access(request: Request) -> None:
    given = bearer(request)
    if given is None:
        raise HTTPException(401, "not_authenticated", headers=UNAUTHORISED)
    token = request.app.state.settings.metrics_token
    if token is not None and hmac.compare_digest(given.encode(), token.encode()):
        return
    try:
        async with request.app.state.sessionmaker() as db:
            principal = await principal_from_token(request, db, given)
    except Exception:  # noqa: BLE001  (the database is down: no account can be checked)
        raise HTTPException(503, "database_unreachable") from None
    if principal is None:
        raise HTTPException(401, "not_authenticated", headers=UNAUTHORISED)
    if not principal.is_server_admin:
        raise HTTPException(403, "server_admin_required")


@router.get("/metrics")
async def metrics(request: Request) -> JSONResponse:
    await _check_access(request)
    engine = request.app.state.engine
    body: dict[str, Any] = {"version": __version__, "uptime_s": _uptime(request)}
    pool = engine.pool
    body["db_pool_size"] = pool.size()
    body["db_pool_checked_out"] = pool.checkedout()
    try:
        async with request.app.state.sessionmaker() as session:
            body["fields_total"] = await session.scalar(select(func.count()).select_from(Field))
            body["users_total"] = await session.scalar(select(func.count()).select_from(User))
            body["sessions_active"] = await session.scalar(
                select(func.count()).select_from(UserSession).where(
                    UserSession.revoked_at.is_(None), UserSession.expires_at > datetime.now(timezone.utc)))
            body["games_total"] = await session.scalar(select(func.count()).select_from(Game))
            body["game_events_total"] = await session.scalar(select(func.count()).select_from(GameEvent))
            body["controllers_total"] = await session.scalar(select(func.count()).select_from(Controller))
            body["chrono_readings_total"] = await session.scalar(select(func.count()).select_from(ChronoReading))
            body["chrono_rejects_total"] = await session.scalar(select(func.count()).select_from(ChronoReject))
    except Exception:  # noqa: BLE001  (the database is down: say so, as health does)
        return JSONResponse({**body, "database": "unreachable"}, status_code=503,
                            headers={"Cache-Control": "no-store"})
    body["database"] = "connected"
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
