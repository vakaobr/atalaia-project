# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base classes for the tests that need PostgreSQL.

``DatabaseTestCase`` makes a fresh database for each test class (on the
server ATALAIA_DATABASE_URL points at), migrates it to head unless the class
sets ``migrate = False``, and drops it afterwards; each test gets its own
engine (``self.engine``, no pool, so nothing outlives the test's event loop).
``AppTestCase`` adds the application, started through its lifespan, an
httpx client on its ASGI transport (``self.client``, over https:// so the
Secure refresh cookie is kept), and helpers that make accounts and log in.

TOTP codes in the tests are made for the app's clock (``app.state.clock``),
which every ``code`` call moves 30 seconds further on: a code is accepted only
once per account (RFC 6238 section 5.2), so two logins of one account in the
same real half-minute would otherwise refuse the second.

Without ATALAIA_DATABASE_URL these tests fail; they never fall back to
another database (decision P4R17).
"""

from __future__ import annotations

import asyncio
import os
import secrets
import time
import unittest
import uuid
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

from atalaia_server import passwords, totp
from atalaia_server.app import create_app
from atalaia_server.config import Settings
from atalaia_server.models import User

SERVER = Path(__file__).resolve().parents[1]
METRICS_TOKEN = "t" * 40
SECRET_KEY = "s" * 43
PASSWORD = "correct horse battery staple 42"
# The tables tests write to (not roles, which the migrations seed).
DATA_TABLES = ("player_id_claims", "registration_replicas", "game_registrations", "scheduled_games", "audit_log", "consents", "refresh_tokens", "sessions", "user_field_roles",
               "user_game_roles",
               "chrono_violations", "chrono_rejects", "chrono_readings", "replicas", "marshal_keys",
               "field_player_ids", "game_nodes", "game_node_scores", "game_events", "games", "controllers",
               "field_api_keys", "users", "fields")
_clock = [time.time()]


def next_time() -> float:
    """A moment 30 seconds after the last one any test used (one TOTP step later)."""
    _clock[0] += totp.PERIOD_S
    return _clock[0]


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
    purge_hour: Optional[int] = None  # no daily purge task unless a test asks for one

    def settings(self) -> Settings:
        return Settings(database_url=self.database_url, secret_key=SECRET_KEY, metrics_token=self.metrics_token,
                        db_timeout_s=2.0, purge_hour=self.purge_hour)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        if self.migrate:  # every test starts with no data (the class shares one database)
            await self.fetch("TRUNCATE " + ", ".join(DATA_TABLES) + " RESTART IDENTITY CASCADE")
        self.stack = AsyncExitStack()
        self.app = create_app(self.settings())
        await self.stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.client = await self.stack.enter_async_context(
            httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="https://server.test"))

    async def asyncTearDown(self) -> None:
        await self.stack.aclose()
        await super().asyncTearDown()

    # Accounts -------------------------------------------------------------------------

    async def make_user(self, username: Optional[str] = None, password: str = PASSWORD, with_totp: bool = False,
                        server_admin: bool = False) -> tuple[uuid.UUID, str, Optional[str]]:
        """A new account written straight to the database: (id, username, TOTP secret or None)."""
        username = username or f"user-{secrets.token_hex(4)}"
        secret = totp.new_secret() if with_totp or server_admin else None
        async with self.app.state.sessionmaker() as db:
            user = User(username=username, password_hash=await passwords.hash_password(password),
                        totp_enabled=secret is not None, server_admin=server_admin,
                        totp_secret_enc=self.app.state.seed_box.seal(secret) if secret else None)
            db.add(user)
            await db.commit()
            return user.id, username, secret

    def code(self, secret: str) -> str:
        """A TOTP code the app accepts now: the app's clock moves one step on and the code is for it."""
        t = next_time()
        self.app.state.clock = lambda: t
        return totp.code_at(secret, t)

    async def login(self, username: str, password: str = PASSWORD, secret: Optional[str] = None,
                    client: Optional[httpx.AsyncClient] = None) -> dict[str, Any]:
        """Logs in (with the TOTP step when the account has it); returns the session's JSON."""
        client = client or self.client
        r = await client.post("/api/v1/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, (r.status_code, r.text)
        body = r.json()
        if body.get("totp_required"):
            assert secret is not None, "the account has TOTP: pass its secret"
            r = await client.post("/api/v1/auth/login/totp",
                                  json={"totp_session": body["totp_session"], "code": self.code(secret)})
            assert r.status_code == 200, (r.status_code, r.text)
            body = r.json()
        return body

    async def auth(self, username: str, password: str = PASSWORD, secret: Optional[str] = None) -> dict[str, str]:
        """The Authorization header of a fresh login."""
        body = await self.login(username, password, secret)
        return {"Authorization": f"Bearer {body['access_token']}"}

    def other_client(self) -> httpx.AsyncClient:
        """A second client (its own cookies) on the same app; closed with the test."""
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="https://server.test")
        self.stack.push_async_callback(client.aclose)
        return client
