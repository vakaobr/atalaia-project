# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The FastAPI application factory.

    uvicorn --factory atalaia_server.app:create_app --host 0.0.0.0 --port 8000

``create_app`` reads the settings from the environment unless it is given
them (the tests do). The database engine is made when the app starts and
disposed when it stops. The interactive API pages are off: they load scripts
from a CDN, which the content security policy forbids; the OpenAPI document
is at /api/v1/openapi.json.

The app's own state: ``keys`` (derived from ATALAIA_SECRET_KEY), ``seed_box``
(TOTP seeds), ``limits`` (rate limits and lockouts), ``used_totp_steps``
(spent TOTP login steps), ``purge_task`` (the daily retention purge, unless
ATALAIA_PURGE_HOUR is off) and ``clock`` (the time TOTP codes are checked at;
the tests move it). All of it is in memory, for the one worker process the
image runs (ADR-P4-2).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__, personal_data
from .api import auth, chrono, fields, games, health, me, sync
from .config import Settings, redact_url
from .db import make_engine, make_sessionmaker
from .ratelimit import Limits, RequestLimitMiddleware
from .security_headers import SecurityHeadersMiddleware
from .tokens import Keys, UsedTokens
from .totp import SeedBox

log = logging.getLogger("atalaia.server")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.getLogger("atalaia").setLevel(settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        log.info("site server %s starting, database %s", __version__, redact_url(settings.database_url))
        purge = None
        if settings.purge_hour is not None:  # the daily retention purge (ADR-P4-8)
            purge = asyncio.create_task(personal_data.purge_daily(app.state.sessionmaker, settings.purge_hour),
                                        name="retention-purge")
        app.state.purge_task = purge
        try:
            yield
        finally:
            if purge is not None:
                purge.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await purge
            await app.state.engine.dispose()

    app = FastAPI(title="Atalaia site server", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json")
    app.state.settings = settings
    app.state.started = time.monotonic()
    app.state.keys = Keys(settings.secret_key)
    app.state.seed_box = SeedBox(app.state.keys.totp_seed)
    app.state.limits = Limits()
    app.state.used_totp_steps = UsedTokens()
    app.state.clock = time.time
    app.add_exception_handler(RequestValidationError, _invalid_request)
    # The last one added runs first: security headers wrap everything, the 429s included.
    app.add_middleware(RequestLimitMiddleware, get_limits=lambda: app.state.limits)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(fields.router)
    app.include_router(me.router)
    app.include_router(games.router)
    app.include_router(chrono.router)
    app.include_router(sync.router)
    return app


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's 422, without the ``input`` and ``ctx`` it would echo back (a password, say)."""
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
              for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)
