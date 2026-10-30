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
``atak_box`` (seals the fields' ATAK CA keys), ``tenant_watch`` (hosted mode's open sockets, closed when
their field is deleted or suspended), ``export_state`` (the field data export's one-at-a-time lock and cooldown),
``purge_task`` (the daily retention purge, unless ATALAIA_PURGE_HOUR is off) and ``clock`` (the time TOTP codes are checked at;
the tests move it). All of it is in memory, for the one worker process the
image runs (ADR-P4-2).

In hosted mode (``ATALAIA_HOSTED=on``, plan phase 21) ``tenancy.TenantMiddleware``
picks each request's field from its host name, the app refuses to start when
its database role could bypass the isolation (``tenancy.check_app_role``) and
the daily purge runs once per field.

With ``ATALAIA_PREVIEW=on`` (decisions PV-*) the app is a preview deployment: ``web/preview.py`` adds a landing
page, a feedback form, ``robots.txt`` and a banner on every page, and ``X-Robots-Tag: noindex`` on every answer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from atalaia_controller.stream_auth import install_redaction
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from . import __version__, atak_pki, integrations, personal_data, privacy_notice, quotas, tenancy, tenant_watch
from .api import (app_links, atak, auth, branding, chrono, clubs, devices, export, feedback, fields, firmware, games,
                  hub_share as hub_share_api, health, history, integrations as integrations_api, me, registration_import,
                  registrations, privacy as privacy_api, remote_gm, scenarios, login_methods, oidc_relay, account_merge, scheduling, sync)
from .atak_relay import AtakRelay
from .body_limit import BodyLimitMiddleware
from .https_redirect import HttpsRedirectMiddleware
from .config import Settings, redact_url, require_public_url
from .db import make_engine, make_sessionmaker
from .oidc import OidcService
from .ratelimit import Limits, RequestLimitMiddleware
from .remote_gm import RemoteHub
from .security_headers import SecurityHeadersMiddleware
from .tokens import Keys, UsedTokens
from .totp import SeedBox
from .web import club_pages, field_pages, preview, privacy_pages, scoreboard, staff_pages

log = logging.getLogger("atalaia.server")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    if settings is None:  # the server's own start (uvicorn --factory): the tests give their settings
        settings = Settings.from_env()
        if not require_public_url(settings):
            log.warning("ATALAIA_PUBLIC_URL is not set: this preview takes its WebAuthn origin and OpenID redirect "
                        "address from the request's Host header; set it (SRV-7)")
    logging.getLogger("atalaia").setLevel(settings.log_level.upper())
    install_redaction()  # no credential-like query value (token=, code=, state=...) in uvicorn's logs (LIVE2-1)

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
        if settings.hosted and settings.privacy_notice_version.startswith("template-"):
            # SR-89: a hosted hub shows every field's players a privacy notice; a template is a draft, not the operator's.
            log.warning("hosted mode with the privacy notice version %r: that is a template, not a notice the operator "
                        "has adopted; set ATALAIA_PRIVACY_NOTICE_VERSION and ATALAIA_PRIVACY_NOTICE_DIR (a lawyer "
                        "should have read it)", settings.privacy_notice_version)
        if privacy_notice.signup_blocked(settings):
            log.warning("no privacy notice is published for version %r (ATALAIA_PRIVACY_NOTICE_DIR): new accounts are "
                        "REFUSED (409 privacy_notice_unpublished) until one is; existing accounts still log in",
                        settings.privacy_notice_version)
        elif settings.allow_signup_without_notice and not privacy_notice.available(settings.privacy_notice_dir,
                                                                                    settings.privacy_notice_version):
            log.warning("sign-up is open and no privacy notice is published (ATALAIA_ALLOW_SIGNUP_WITHOUT_NOTICE=on): "
                        "accounts consent to no text; never for a real deployment")
        purge = None
        if settings.purge_hour is not None:  # the daily retention purge (ADR-P4-8)
            engine = app.state.engine
            tenants = (lambda: tenancy.active_tenants(engine)) if settings.hosted else None
            purge = asyncio.create_task(personal_data.purge_daily(app.state.sessionmaker, settings.purge_hour,
                                                                  tenants=tenants, policy=settings.retention,
                                                                  ledger=settings.erasure_ledger),
                                        name="retention-purge")
        app.state.purge_task = purge
        relay = None
        if settings.atak_relay:  # the remote ATAK relay's TLS listener (FU5): off by default
            relay = AtakRelay(settings, app.state.sessionmaker, app.state.engine)
            await relay.start()
        app.state.atak_relay = relay
        watcher = None
        if settings.hosted:  # closes the sockets of a field that was deleted or suspended (S21-12)
            watcher = asyncio.create_task(
                app.state.tenant_watch.run(app.state.engine, settings.hosted_watch_s, app.state.remote_hub,
                                           lambda: app.state.atak_relay), name="tenant-watch")
        try:
            yield
        finally:
            if watcher is not None:
                watcher.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await watcher
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
    app.state.used_challenges = UsedTokens()  # spent passkey challenges and social login tickets (LG-1, LG-2)
    app.state.oidc = OidcService(settings)    # the social login providers, if any are configured
    app.state.clock = time.time
    app.state.remote_hub = RemoteHub()  # the remote GM's open controller links (plan phase 19)
    app.state.tenant_watch = tenant_watch.TenantWatch()  # open sockets of hosted mode, closed when a field goes
    app.state.export_state = {}  # per (tenant, field): an export running, when the last one ended
    app.state.atak_relay = None  # the remote ATAK relay, started with the app when ATALAIA_ATAK_RELAY=on (FU5)
    app.state.atak_box = atak_pki.CaBox(settings.secret_key)
    app.add_exception_handler(RequestValidationError, _invalid_request)
    app.add_exception_handler(quotas.QuotaExceeded, _quota_exceeded)
    # The last one added runs first: security headers wrap everything, the 429s and the hosted mode's
    # refusals included; the tenant is chosen before anything else reads the database.
    app.add_middleware(BodyLimitMiddleware)  # innermost: the headers and the limits wrap its 413 (SRV-2)
    app.add_middleware(RequestLimitMiddleware, get_limits=lambda: app.state.limits)
    app.add_middleware(tenancy.TenantMiddleware, get_state=lambda: app.state)
    app.add_middleware(HttpsRedirectMiddleware, get_public_url=lambda: settings.public_url)  # LIVE-1
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.preview:  # a preview deployment (decisions PV-*): noindex everywhere, the landing page, the form
        app.add_middleware(preview.PreviewHeadersMiddleware)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(login_methods.router)  # social login, passkeys, step-up (LG-*)
    app.include_router(oidc_relay.router)  # the hub-level social login callback, hosted mode, opt-in (LG-14)
    app.include_router(account_merge.router)  # merging two accounts of one person (LG-11)
    app.include_router(app_links.router)  # the app's well-known files and its login return (PKA-1)
    app.include_router(fields.router)
    app.include_router(export.router)  # a field's data export for its administrator (S21-12)
    app.include_router(me.router)
    app.include_router(privacy_api.router)  # the published privacy notice (CONS-1)
    app.include_router(hub_share_api.router)  # chrono sharing across a hosted hub's tenants (SVX-2)
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
    app.include_router(privacy_pages.router)  # /privacy: the same notice as a page (CONS-1)
    app.include_router(history.router)  # plan phase 20: game history, the scenario library, the scoreboard
    app.include_router(scenarios.router)
    app.include_router(scoreboard.router)
    app.include_router(staff_pages.router)  # the field staff's pages (Phase 4 follow-up, FU2-1)
    if settings.preview:
        app.include_router(feedback.router)  # the administrators' side of the feedback form (PV-8)
        app.include_router(preview.router)  # /, /feedback, /robots.txt, /staff/feedback
    return app


async def _quota_exceeded(request: Request, exc: Exception) -> JSONResponse:
    """409 ``quota_exceeded`` with the quota's name and limit (hosted mode's per-field quotas)."""
    assert isinstance(exc, quotas.QuotaExceeded)
    await quotas.report(request.app.state, exc.name, exc.limit)  # hosted mode: a note for the hub operator
    return JSONResponse(exc.body(), status_code=409, headers={"Cache-Control": "no-store"})


async def _invalid_request(request: Request, exc: Exception) -> JSONResponse:
    """FastAPI's 422, without the ``input`` and ``ctx`` it would echo back (a password, say)."""
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
              for e in exc.errors()]
    return JSONResponse({"detail": errors}, status_code=422)
