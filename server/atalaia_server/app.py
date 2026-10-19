# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The FastAPI application factory.

    uvicorn --factory atalaia_server.app:create_app --host 0.0.0.0 --port 8000

``create_app`` reads the settings from the environment unless it is given
them (the tests do). The database engine is made when the app starts and
disposed when it stops. The interactive API pages are off: they load scripts
from a CDN, which the content security policy forbids; the OpenAPI document
is at /api/v1/openapi.json.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI

from . import __version__
from .api import health
from .config import Settings, redact_url
from .db import make_engine, make_sessionmaker
from .security_headers import SecurityHeadersMiddleware

log = logging.getLogger("atalaia.server")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.getLogger("atalaia").setLevel(settings.log_level.upper())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(settings)
        app.state.sessionmaker = make_sessionmaker(app.state.engine)
        log.info("site server %s starting, database %s", __version__, redact_url(settings.database_url))
        try:
            yield
        finally:
            await app.state.engine.dispose()

    app = FastAPI(title="Atalaia site server", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url="/api/v1/openapi.json")
    app.state.settings = settings
    app.state.started = time.monotonic()
    app.add_middleware(SecurityHeadersMiddleware)
    app.include_router(health.router)
    return app
