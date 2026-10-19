# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base classes for the tests that need PostgreSQL.

``DatabaseTestCase`` makes a fresh database for each test class (on the
server ATALAIA_DATABASE_URL points at), migrates it to head unless the class
sets ``migrate = False``, and drops it afterwards; each test gets its own
engine (``self.engine``, no pool, so nothing outlives the test's event loop).
``AppTestCase`` adds the application, started through its lifespan, and an
httpx client on its ASGI transport (``self.client``).

Without ATALAIA_DATABASE_URL these tests fail; they never fall back to
another database (decision P4R17).
"""

from __future__ import annotations

import asyncio
import os
import secrets
import unittest
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

import asyncpg
import httpx
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from atalaia_server.app import create_app
from atalaia_server.config import Settings

SERVER = Path(__file__).resolve().parents[1]
METRICS_TOKEN = "t" * 40


def server_url() -> str:
    url = os.environ.get("ATALAIA_DATABASE_URL", "")
    if not url:
        raise RuntimeError("ATALAIA_DATABASE_URL is not set: run the tests with python3 tools/docker_server.py test")
    return url


def _asyncpg_dsn(url: str) -> str:
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


async def _admin(sql: str) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn(server_url()), timeout=10)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(SERVER / "alembic.ini"))
    cfg.attributes["database_url"] = database_url
    cfg.attributes["skip_logging"] = True
    return cfg


class TempDatabase:
    """A database of its own on the test server, made by ``create`` and dropped by ``drop``."""

    def __init__(self) -> None:
        self.name = f"atalaia_test_{secrets.token_hex(6)}"
        self.url = make_url(server_url()).set(database=self.name).render_as_string(hide_password=False)

    def create(self, migrate: bool = True) -> None:
        asyncio.run(_admin(f'CREATE DATABASE "{self.name}"'))
        if migrate:
            command.upgrade(alembic_config(self.url), "head")

    def drop(self) -> None:
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))

    def fetch(self, sql: str, *args: Any) -> list[asyncpg.Record]:
        """Rows of a plain SQL query, from synchronous code."""
        return asyncio.run(fetch(self.url, sql, *args))


async def fetch(database_url: str, sql: str, *args: Any) -> list[asyncpg.Record]:
    """Rows of a plain SQL query on that database (asyncpg, not the ORM)."""
    conn = await asyncpg.connect(_asyncpg_dsn(database_url), timeout=10)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


class DatabaseTestCase(unittest.IsolatedAsyncioTestCase):
    migrate = True
    database: TempDatabase
    database_url: str

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.database = TempDatabase()
        cls.database.create(migrate=cls.migrate)
        cls.database_url = cls.database.url

    @classmethod
    def tearDownClass(cls) -> None:
        cls.database.drop()
        super().tearDownClass()

    async def asyncSetUp(self) -> None:
        self.engine: AsyncEngine = create_async_engine(self.database_url, poolclass=NullPool)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def fetch(self, sql: str, *args: Any) -> list[asyncpg.Record]:
        return await fetch(self.database_url, sql, *args)


class AppTestCase(DatabaseTestCase):
    metrics_token: Optional[str] = METRICS_TOKEN

    def settings(self) -> Settings:
        return Settings(database_url=self.database_url, metrics_token=self.metrics_token, db_timeout_s=2.0)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.stack = AsyncExitStack()
        self.app = create_app(self.settings())
        await self.stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.client = await self.stack.enter_async_context(
            httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://server.test"))

    async def asyncTearDown(self) -> None:
        await self.stack.aclose()
        await super().asyncTearDown()
