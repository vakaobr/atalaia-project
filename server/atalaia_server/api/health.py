# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""``GET /api/v1/health`` (public) and ``GET /api/v1/metrics`` (token), ADR-P4-10.

Health answers 200 ``{"status": "healthy", "database": "connected", ...}``
when PostgreSQL answers, and 503 with ``"unhealthy"`` and
``"unreachable"`` when it does not, so an uptime monitor or the container's
health check sees an outage. Metrics need ``Authorization: Bearer`` with
ATALAIA_METRICS_TOKEN until admin accounts exist (plan phase 11); with no
token configured the endpoint does not exist (404). They report only what
the base tables hold; later plan phases add their counters.
"""

from __future__ import annotations

import hmac
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from .. import __version__
from ..db import ping
from ..models import Field, User

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


def _check_token(request: Request) -> None:
    token = request.app.state.settings.metrics_token
    if token is None:
        raise HTTPException(404, "Not Found")
    scheme, _, given = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(given.strip().encode(), token.encode()):
        raise HTTPException(401, "a valid metrics token is required", headers={"WWW-Authenticate": "Bearer"})


@router.get("/metrics")
async def metrics(request: Request) -> JSONResponse:
    _check_token(request)
    engine = request.app.state.engine
    body: dict[str, Any] = {"version": __version__, "uptime_s": _uptime(request)}
    pool = engine.pool
    body["db_pool_size"] = pool.size()
    body["db_pool_checked_out"] = pool.checkedout()
    try:
        async with request.app.state.sessionmaker() as session:
            body["fields_total"] = await session.scalar(select(func.count()).select_from(Field))
            body["users_total"] = await session.scalar(select(func.count()).select_from(User))
    except Exception:  # noqa: BLE001  (the database is down: say so, as health does)
        return JSONResponse({**body, "database": "unreachable"}, status_code=503,
                            headers={"Cache-Control": "no-store"})
    body["database"] = "connected"
    return JSONResponse(body, headers={"Cache-Control": "no-store"})
