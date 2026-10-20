# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The database layer: SQLAlchemy 2's async engine on asyncpg (ADR-P4-1).

One engine per application, made in the app's lifespan (``app.state.engine``)
and disposed when it stops; request handlers get an ``AsyncSession`` from
``get_session``. Alembic, not this module, creates and changes the schema.
In hosted mode (plan phase 21) the connections start with no schema on their
path and every session is one tenant's (``tenancy.TenantSession``).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from . import tenancy
from .config import Settings


def make_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {"timeout": settings.db_timeout_s}
    if settings.hosted:
        connect_args.update(tenancy.engine_options())
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        pool_timeout=settings.db_timeout_s,
        connect_args=connect_args,
    )


def make_sessionmaker(engine: AsyncEngine, hosted: bool = False) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False,
                              sync_session_class=tenancy.TenantSession if hosted else Session)


async def ping(engine: AsyncEngine, timeout_s: float) -> bool:
    """True when the database answers ``SELECT 1`` within the timeout."""
    try:
        async with asyncio.timeout(timeout_s):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001  (refused, timed out, bad password: all mean "not connected")
        return False


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: a session for one request, closed afterwards."""
    async with request.app.state.sessionmaker() as session:
        yield session
