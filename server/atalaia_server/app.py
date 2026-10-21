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
(spent TOTP login steps), ``remote_hub`` (the remote GM's controller links, plan phase 19), ``atak_relay`` (the
remote ATAK relay's TLS listener with ATALAIA_ATAK_RELAY=on, else None; Phase 4 follow-up FU5),
``atak_box`` (seals the fields' ATAK CA keys), ``purge_task`` (the daily retention purge, unless
ATALAIA_PURGE_HOUR is off) and ``clock`` (the time TOTP codes are checked at;
the tests move it). All of it is in memory, for the one worker process the
image runs (ADR-P4-2).

In hosted mode (``ATALAIA_HOSTED=on``, plan phase 21) ``tenancy.TenantMiddleware``
picks each request's field from its host name, the app refuses to start when
its database role could bypass the isolation (``tenancy.check_app_role``) and
the daily purge runs once per field.
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

from . import __version__, atak_pki, integrations, personal_data, tenancy
from .api import (atak, auth, branding, chrono, clubs, devices, fields, firmware, games, health, history,
                  integrations as integrations_api, me, registration_import, registrations, remote_gm, scenarios,
                  scheduling, sync)
from .atak_relay import AtakRelay
from .config import Settings, redact_url
from .db import make_engine, make_sessionmaker
from .ratelimit import Limits, RequestLimitMiddleware
from .remote_gm import RemoteHub
from .security_headers import SecurityHeadersMiddleware
from .tokens import Keys, UsedTokens
from .totp import SeedBox
from .web import club_pages, field_pages, scoreboard, staff_pages

log = logging.getLogger("atalaia.server")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.getLogger("atalaia").setLevel(settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine, hosted=settings.hosted)
        log.info("site server %s starting%s, database %s", __version__,
                 f" in hosted mode for *.{settings.hosted_domain}" if settings.hosted else "",
                 redact_url(settings.database_url))
        if settings.hosted:
            try:
                await tenancy.check_app_role(app.state.engine)
            except BaseException:
                await app.state.engine.dispose()
                raise
        purge = None
        if settings.purge_hour is not None:  # the daily retention purge (ADR-P4-8)
            engine = app.state.engine
            tenants = (lambda: tenancy.active_tenants(engine)) if settings.hosted else None
            purge = asyncio.create_task(personal_data.purge_daily(app.state.sessionmaker, settings.purge_hour,
                                                                  tenants=tenants),
                                        name="retention-purge")
        app.state.purge_task = purge
        relay = None
        if settings.atak_relay:  # the remote ATAK relay's TLS listener (FU5): off by default
            relay = AtakRelay(settings, app.state.sessionmaker, app.state.engine)
            await relay.start()
        app.state.atak_relay = relay
        try:
            yield
        finally:
            if relay is not None:
                await relay.stop()
                app.state.atak_relay = None
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
    app.state.config_box = integrations.ConfigBox(app.state.keys.platform_config)
    app.state.adapters = integrations.default_registry(settings.test_adapter)
    app.state.limits = Limits()
    app.state.used_totp_steps = UsedTokens()
    app.state.clock = time.time
    app.state.remote_hub = RemoteHub()  # the remote GM's open controller links (plan phase 19)
    app.state.atak_relay = None  # the remote ATAK relay, started with the app when ATALAIA_ATAK_RELAY=on (FU5)
    app.state.atak_box = atak_pki.CaBox(settings.secret_key)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    # The last one added runs first: security headers wrap everything, the 429s and the hosted mode's
    # refusals included; the tenant is chosen before anything else reads the database.
    app.add_middleware(RequestLimitMiddleware, get_limits=lambda: app.state.limits)
    app.add_middleware(tenancy.TenantMiddleware, get_state=lambda: app.state)
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(fields.router)
    app.include_router(me.router)
    app.include_router(games.router)
    app.include_router(chrono.router)
    app.include_router(sync.router)
    app.include_router(scheduling.router)
    app.include_router(registration_import.router)  # before registrations' /registrations/{reg_id}
    app.include_router(registrations.router)
    app.include_router(integrations_api.router)
    app.include_router(branding.router)
    app.include_router(clubs.router)
    app.include_router(devices.router)
    app.include_router(firmware.router)
    app.include_router(remote_gm.router)
    app.include_router(atak.router)  # the remote ATAK relay's enrolment (Phase 4 follow-up FU5)
    app.include_router(field_pages.router)
    app.include_router(club_pages.router)
    app.include_router(history.router)  # plan phase 20: game history, the scenario library, the scoreboard
    app.include_router(scenarios.router)
    app.include_router(scoreboard.router)
    app.include_router(staff_pages.router)  # the field staff's pages (Phase 4 follow-up, FU2-1)
    return app


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's 422, without the ``input`` and ``ctx`` it would echo back (a password, say)."""
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
              for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)
