# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hosted multi-tenant mode on PostgreSQL 16 (plan phase 21; ADR-P4-4 as built; decisions S21-*).

Each test class gets a hub of its own: a database owned by a non-superuser
owner role (the migrations' and the operator's), a separate server role with
no BYPASSRLS that owns nothing, and two fields made with the operator's own
commands, ``campo-a`` and ``campo-b``. The app runs in hosted mode on the
server role, at ``https://campo-a.hub.test`` and ``https://campo-b.hub.test``.

Isolation is the acceptance test, so every surface is tried with field A's
credentials and ids against field B: the host routing, accounts and tokens,
lockouts, the field and game ids, the sync with an API key (HTTP and the
WebSocket), the remote GM's links, lists, history, the public pages, feeds
and scoreboard, personal-data exports, metrics. Underneath, the row-level
security is tried directly as the server's role: no setting reads nothing,
another field's setting (a routing bug) reads and writes nothing, the setting
is transaction-local and a pooled connection never carries it on. Then the
operator's export (everything of A, nothing of B), import into a single-field
server, suspension, migration and deletion.

    python3 tools/docker_server.py test tests.test_tenants
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import os
import secrets
import stat
import tempfile
import unittest
import unittest.mock
import uuid
import zipfile
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

import asyncpg
import httpx
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from atalaia_server import cli, hosted, passwords, tenancy, totp
from atalaia_server.app import create_app
from atalaia_server.config import Settings
from atalaia_server.models import Field, User, UserFieldRole

from .base import METRICS_TOKEN, PASSWORD, SECRET_KEY, TempDatabase, _admin, next_time, server_url
from .test_remote_gm import LIVE, Stream

DOMAIN = "hub.test"
ROLE = {"player": 1, "marshal": 4, "gm": 5, "admin": 7}
CONTROLLER = {"id": "0192f3a4-5b6c-7d8e-9f01-23456789abcd", "version": "0.1.0"}
GAME = {"game_id": 4242, "game_seed": 3735928559}
META = {"name": "Domingo", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"], "state": "running",
        "created_at": 1792000000.0, "started_at": 1792000100.0}


def envelope(**body: Any) -> dict[str, Any]:
    return {"sync_version": 1, "controller": CONTROLLER, "game": dict(GAME), **body}


def event(eid: int) -> dict[str, Any]:
    return {"id": eid, "node": 3, "seq": eid, "t": eid * 1000, "type": "zone.captured", "team": "red",
            "prio": "normal", "data": {"zone": "alpha"}}


class Hub:
    """A database with a hub in it: the owner and server roles, the registry, two fields."""

    def __init__(self) -> None:
        tag = secrets.token_hex(5)
        self.owner, self.app_role = f"atalaia_owner_{tag}", f"atalaia_app_{tag}"
        self.owner_pw, self.app_pw = secrets.token_hex(16), secrets.token_hex(16)
        self.name = f"atalaia_test_{tag}"
        base = make_url(server_url())
        self.owner_url = base.set(username=self.owner, password=self.owner_pw, database=self.name) \
            .render_as_string(hide_password=False)
        self.app_url = base.set(username=self.app_role, password=self.app_pw, database=self.name) \
            .render_as_string(hide_password=False)
        self.super_url = base.set(database=self.name).render_as_string(hide_password=False)

    async def restrict_set_config(self) -> None:
        """What server/hosted-roles.sh does in the hub's database (as the superuser): only the owner and the server's
        login role may call set_config, so a field's role cannot switch role or setting from inside a statement."""
        conn = await asyncpg.connect(hosted.dsn(self.super_url), timeout=10)
        try:
            await conn.execute(f"REVOKE EXECUTE ON FUNCTION {hosted.SET_CONFIG} FROM PUBLIC; "
                               f"GRANT EXECUTE ON FUNCTION {hosted.SET_CONFIG} TO {self.owner}, {self.app_role}")
        finally:
            await conn.close()

    async def _tenant_roles(self) -> list[str]:
        try:
            conn = await asyncpg.connect(hosted.dsn(self.super_url), timeout=10)
        except Exception:  # noqa: BLE001  (the database was never made)
            return []
        try:
            return [r["role_name"] for r in await conn.fetch("SELECT role_name FROM public.atalaia_tenants")]
        except asyncpg.PostgresError:
            return []
        finally:
            await conn.close()

    def create(self) -> None:
        asyncio.run(_admin(f"CREATE ROLE {self.owner} LOGIN PASSWORD '{self.owner_pw}' NOSUPERUSER NOBYPASSRLS CREATEROLE"))
        asyncio.run(_admin(f"CREATE ROLE {self.app_role} LOGIN PASSWORD '{self.app_pw}' NOSUPERUSER NOBYPASSRLS"))
        asyncio.run(_admin(f'CREATE DATABASE "{self.name}" OWNER {self.owner}'))
        asyncio.run(self.restrict_set_config())
        asyncio.run(hosted.init_hub(self.owner_url, self.app_role, actor="test:operator"))
        self.a = hosted.create_tenant(self.owner_url, "campo-a", "Campo A", app_role=self.app_role,
                                      actor="test:operator")
        self.b = hosted.create_tenant(self.owner_url, "campo-b", "Campo B", app_role=self.app_role,
                                      actor="test:operator")

    def drop(self) -> None:
        roles = asyncio.run(self._tenant_roles())
        asyncio.run(_admin(f'DROP DATABASE IF EXISTS "{self.name}" WITH (FORCE)'))
        for role in roles:  # the fields' database roles belong to the cluster, not the database
            asyncio.run(_admin(f'DROP ROLE IF EXISTS "{role}"'))
        asyncio.run(_admin(f"DROP ROLE IF EXISTS {self.app_role}"))
        asyncio.run(_admin(f"DROP ROLE IF EXISTS {self.owner}"))


async def connect(url: str) -> asyncpg.Connection:
    return await asyncpg.connect(hosted.dsn(url), timeout=10)


async def connect_driver_safe(url: str) -> asyncpg.Connection:
    """A connection that, like the server's engine, never lets asyncpg's type introspection call ``set_config``
    (a field's role may not: ``tenancy.keep_set_config_to_the_server``)."""
    conn = await connect(url)
    conn._server_caps = conn._server_caps._replace(jit=False)
    return conn


class HubCase(unittest.IsolatedAsyncioTestCase):
    hub: Hub
    pool_size = 5

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.hub = Hub()
        try:
            cls.hub.create()
        except BaseException:
            cls.hub.drop()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.hub.drop()
        super().tearDownClass()

    def settings(self, url: Optional[str] = None) -> Settings:
        return Settings(allow_signup_without_notice=True, database_url=url or self.hub.app_url, secret_key=SECRET_KEY, metrics_token=METRICS_TOKEN,
                        db_timeout_s=2.0, purge_hour=None, hosted=True, hosted_domain=DOMAIN,
                        db_pool_size=self.pool_size, db_max_overflow=0)

    async def asyncSetUp(self) -> None:
        self.stack = AsyncExitStack()
        self.app = create_app(self.settings())
        await self.stack.enter_async_context(self.app.router.lifespan_context(self.app))
        self.a = self.client("campo-a")
        self.b = self.client("campo-b")
        self.ta, self.tb = self.hub.a, self.hub.b

    async def asyncTearDown(self) -> None:
        await self.stack.aclose()

    def client(self, slug: str, host: Optional[str] = None) -> httpx.AsyncClient:
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                   base_url=f"https://{host or f'{slug}.{DOMAIN}'}")
        self.stack.push_async_callback(client.aclose)
        return client

    # The tenant's data, as the operator sees it (owner role, the tenant's setting) ------------------

    async def sql(self, tenant: tenancy.Tenant, query: str, *args: Any) -> list[asyncpg.Record]:
        conn = await connect(self.hub.owner_url)
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('search_path', $1, true), set_config('atalaia.tenant', $1, "
                                   "true)", tenant.schema)
                return await conn.fetch(query, *args)
        finally:
            await conn.close()

    # Accounts ---------------------------------------------------------------------------------------

    async def user(self, tenant: tenancy.Tenant, name: Optional[str] = None, *roles: str, totp_on: bool = False,
                   server_admin: bool = False) -> tuple[uuid.UUID, str, Optional[str]]:
        name = name or f"user-{secrets.token_hex(4)}"
        secret = totp.new_secret() if totp_on or server_admin or set(roles) & {"admin", "gm", "marshal"} else None
        with tenancy.use(tenant):
            async with self.app.state.sessionmaker() as db:
                user = User(username=name, password_hash=await passwords.hash_password(PASSWORD),
                            totp_enabled=secret is not None, server_admin=server_admin,
                            totp_secret_enc=self.app.state.seed_box.seal(secret) if secret else None)
                db.add(user)
                await db.flush()
                for role in roles:
                    db.add(UserFieldRole(user_id=user.id, field_id=tenant.field_id, role_id=ROLE[role]))
                await db.commit()
                return user.id, name, secret

    async def login(self, client: httpx.AsyncClient, name: str, secret: Optional[str] = None,
                    password: str = PASSWORD) -> httpx.Response:
        r = await client.post("/api/v1/auth/login", json={"username": name, "password": password})
        if r.status_code != 200 or not r.json().get("totp_required"):
            return r
        t = next_time()
        self.app.state.clock = lambda: t
        return await client.post("/api/v1/auth/login/totp", json={"totp_session": r.json()["totp_session"],
                                                                  "code": totp.code_at(secret or "", t)})

    async def auth(self, client: httpx.AsyncClient, name: str, secret: Optional[str] = None) -> dict[str, str]:
        r = await self.login(client, name, secret)
        self.assertEqual(r.status_code, 200, r.text)
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    async def staff(self, tenant: tenancy.Tenant, client: httpx.AsyncClient, *roles: str,
                    server_admin: bool = False) -> dict[str, str]:
        _, name, secret = await self.user(tenant, None, *roles, server_admin=server_admin)
        return await self.auth(client, name, secret)

    async def key(self, tenant: tenancy.Tenant, client: httpx.AsyncClient) -> str:
        """The field's API key, made through the API once per class (a field has at most two live keys)."""
        keys = type(self).__dict__.get("_keys")
        if keys is None:
            keys = {}
            type(self)._keys = keys
        if tenant.slug not in keys:
            admin = await self.staff(tenant, client, "admin")
            r = await client.post(f"/api/v1/fields/{tenant.field_id}/sync-keys", headers=admin, json={})
            self.assertEqual(r.status_code, 201, r.text)
            keys[tenant.slug] = r.json()["key"]
        return keys[tenant.slug]

    async def synced_game(self, tenant: tenancy.Tenant, client: httpx.AsyncClient, key: str) -> str:
        bearer = {"Authorization": f"Bearer {key}"}
        r = await client.post("/api/v1/sync/games", json=envelope(meta=META), headers=bearer)
        self.assertEqual(r.status_code, 200, r.text)
        game: str = r.json()["game"]
        r = await client.post("/api/v1/sync/events", json=envelope(after_id=0, events=[event(1)]), headers=bearer)
        self.assertEqual(r.status_code, 200, r.text)
        return game


# Host routing, accounts, tokens ---------------------------------------------------------------------

class RoutingTests(HubCase):
    async def test_the_host_name_picks_the_field(self) -> None:
        for host in (DOMAIN, f"campo-c.{DOMAIN}", f"x.campo-a.{DOMAIN}", "campo-a.example.pt", "campo-a",
                     f"Campo_A.{DOMAIN}", "127.0.0.1:8000"):
            with self.subTest(host=host):
                r = await self.client("", host).get("/api/v1/fields")
                self.assertEqual((r.status_code, r.json()), (404, {"detail": "unknown_field"}))
                self.assertIn("content-security-policy", r.headers)  # the security headers wrap the refusal
        r = await self.client("", f"CAMPO-A.{DOMAIN.upper()}:443").get("/api/v1/fields")
        self.assertEqual(r.status_code, 401)  # found (case and port do not matter), then asks for a login
        # The health check needs no field: the container calls 127.0.0.1.
        r = await self.client("", "127.0.0.1:8000").get("/api/v1/health")
        self.assertEqual((r.status_code, r.json()), (200, {"status": "ok"}))

    async def test_slugs_and_hosts(self) -> None:
        self.assertEqual(tenancy.schema_for("campo-a"), "field_campo_a")
        self.assertEqual(tenancy.slug_from_host(f"campo-a.{DOMAIN}:8443", DOMAIN), "campo-a")
        self.assertEqual(tenancy.slug_from_host(f"campo-a.{DOMAIN}.", DOMAIN), "campo-a")
        for bad in ("", "-a", "a-", "a_b", "A", "a" * 41, "a.b", "café"):
            with self.subTest(bad=bad), self.assertRaises(tenancy.TenantError):
                tenancy.schema_for(bad)
        for host in (f"[::1]:{DOMAIN}", f"a.b.{DOMAIN}", f"evil{DOMAIN}", DOMAIN):
            with self.subTest(host=host):
                self.assertIsNone(tenancy.slug_from_host(host, DOMAIN))

    async def test_accounts_are_per_field(self) -> None:
        # The same username in both fields: two accounts, two passwords.
        await self.user(self.ta, "ana")
        with tenancy.use(self.tb):
            async with self.app.state.sessionmaker() as db:
                db.add(User(username="ana", password_hash=await passwords.hash_password("another password 4 B!")))
                await db.commit()
        self.assertEqual((await self.login(self.a, "ana")).status_code, 200)
        self.assertEqual((await self.login(self.b, "ana")).status_code, 401)
        self.assertEqual((await self.login(self.b, "ana", password="another password 4 B!")).status_code, 200)
        # A login lockout in one field does not lock the same name out of the other.
        for _ in range(5):
            await self.login(self.a, "ana", password="wrong password, five times")
        self.assertEqual((await self.login(self.a, "ana")).status_code, 429)
        self.assertEqual((await self.login(self.b, "ana", password="another password 4 B!")).status_code, 200)
        # Registration in one field makes no account in the other.
        r = await self.b.post("/api/v1/auth/register", json={"username": "rui", "password": PASSWORD,
                                                             "notice_seen": True, "age_confirmed": True})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(len(await self.sql(self.ta, "SELECT 1 FROM users WHERE username = 'rui'")), 0)
        self.assertEqual(len(await self.sql(self.tb, "SELECT 1 FROM users WHERE username = 'rui'")), 1)

    async def test_a_token_works_only_where_it_was_made(self) -> None:
        _, name, _ = await self.user(self.ta, None, "player")
        token = await self.auth(self.a, name)
        self.assertEqual((await self.a.get("/api/v1/me/data", headers=token)).status_code, 200)
        self.assertEqual((await self.b.get("/api/v1/me/data", headers=token)).status_code, 401)
        # Even with an account of the same id in B (a copied database, say), the tenant claim refuses it.
        admin_a = await self.staff(self.ta, self.a, server_admin=True)
        for path in ("/api/v1/fields", f"/api/v1/fields/{self.tb.field_id}/roles", "/api/v1/clubs",
                     f"/api/v1/fields/{self.ta.field_id}/history"):
            with self.subTest(path=path):
                self.assertEqual((await self.b.get(path, headers=admin_a)).status_code, 401)
        # A's refresh token, presented at B: B has no such session.
        r = await self.login(self.a, name)
        refresh = r.cookies.get("__Secure-atalaia_refresh")
        self.assertIsNotNone(refresh)
        stranger = self.client("campo-b")
        stranger.cookies.set("__Secure-atalaia_refresh", refresh or "", domain=f"campo-b.{DOMAIN}",
                             path="/api/v1/auth/refresh")
        r = await stranger.post("/api/v1/auth/refresh", headers={"X-Atalaia-Refresh": "1"})
        self.assertEqual(r.status_code, 401, r.text)

    async def test_staff_see_only_their_field(self) -> None:
        game_b = await self.synced_game(self.tb, self.b, await self.key(self.tb, self.b))
        admin_a = await self.staff(self.ta, self.a, server_admin=True)
        r = await self.a.get("/api/v1/fields", headers=admin_a)
        self.assertEqual([f["id"] for f in r.json()], [str(self.ta.field_id)])  # a server admin: every field it has
        for method, path in (("GET", f"/api/v1/fields/{self.tb.field_id}/roles"),
                             ("PATCH", f"/api/v1/fields/{self.tb.field_id}"),
                             ("GET", f"/api/v1/fields/{self.tb.field_id}/sync-keys"),
                             ("POST", f"/api/v1/fields/{self.tb.field_id}/sync-keys"),
                             ("GET", f"/api/v1/fields/{self.tb.field_id}/history"),
                             ("GET", f"/api/v1/fields/{self.tb.field_id}/games"),
                             ("GET", f"/api/v1/fields/{self.tb.field_id}/scenarios"),
                             ("GET", f"/api/v1/fields/{self.tb.field_id}/remote-gm")):
            with self.subTest(method=method, path=path):
                r = await self.a.request(method, path, headers=admin_a, json={} if method != "GET" else None)
                # Refused, or (a server administrator's list of a field that is not there) empty: never B's.
                self.assertIn(r.status_code, (200, 403, 404), r.text)
                self.assertNotIn(game_b, r.text)
                if r.status_code == 200:
                    self.assertIn(r.json(), ([], {"games": [], "next_before": None}))
        for path in (f"/api/v1/games/{game_b}", f"/api/v1/games/{game_b}/events"):
            with self.subTest(path=path):
                self.assertEqual((await self.a.get(path, headers=admin_a)).status_code, 404)
        # The hosted field's administrator cannot make a second field (S21-2).
        r = await self.a.post("/api/v1/fields", headers=admin_a, json={"name": "Outro", "slug": "outro"})
        self.assertEqual((r.status_code, r.json()), (403, {"detail": "hosted_one_field"}))
        self.assertEqual(len(await self.sql(self.ta, "SELECT 1 FROM fields")), 1)

    async def test_metrics_count_one_field(self) -> None:
        await self.user(self.tb, None)
        await self.user(self.tb, None)
        bearer = {"Authorization": f"Bearer {METRICS_TOKEN}"}
        a = (await self.a.get("/api/v1/metrics", headers=bearer)).json()
        b = (await self.b.get("/api/v1/metrics", headers=bearer)).json()
        self.assertEqual(a["fields_total"], 1)
        self.assertEqual(a["users_total"], len(await self.sql(self.ta, "SELECT 1 FROM users")))
        self.assertEqual(b["users_total"], len(await self.sql(self.tb, "SELECT 1 FROM users")))
        # The hub operator's monitoring token reads counts, nothing else.
        for path in ("/api/v1/fields", "/api/v1/me/data", f"/api/v1/fields/{self.ta.field_id}/history",
                     "/api/v1/clubs"):
            with self.subTest(path=path):
                self.assertEqual((await self.a.get(path, headers=bearer)).status_code, 401)


# The sync, the WebSocket, the remote GM ----------------------------------------------------------------

class SyncTests(HubCase):
    async def test_an_api_key_works_only_at_its_field(self) -> None:
        key_a = await self.key(self.ta, self.a)
        bearer = {"Authorization": f"Bearer {key_a}"}
        r = await self.b.post("/api/v1/sync/games", json=envelope(meta=META), headers=bearer)
        self.assertEqual((r.status_code, r.json()), (401, {"detail": "invalid_api_key"}))
        for path in ("/api/v1/sync/schedule", f"/api/v1/sync/roster?scheduled_game_id={uuid.uuid4()}", "/api/v1/sync/field", "/api/v1/sync/presets",
                     "/api/v1/sync/claims"):
            with self.subTest(path=path):
                self.assertEqual((await self.b.get(path, headers=bearer)).status_code, 401)
        await self.synced_game(self.ta, self.a, key_a)
        self.assertEqual(len(await self.sql(self.ta, "SELECT 1 FROM games")), 1)
        self.assertEqual(len(await self.sql(self.tb, "SELECT 1 FROM games")), 0)

    async def test_the_stream_only_at_its_field(self) -> None:
        key_a = await self.key(self.ta, self.a)
        for host, code in ((f"campo-b.{DOMAIN}", 4401), (f"campo-z.{DOMAIN}", 4404), ("server.test", 4404)):
            with self.subTest(host=host):
                stream = HostStream(self.app, key_a, host)
                self.assertEqual(await stream.open(), {"type": "websocket.close", "code": code,
                                                       **({"reason": ""} if code == 4401 else {})})
                await stream.close()
        stream = HostStream(self.app, key_a, f"campo-a.{DOMAIN}")
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        await stream.send({"type": "games", **envelope(meta=META)})
        self.assertEqual((await stream.receive())["type"], "games.ack")
        await stream.close()

    async def test_remote_gm_links_stay_in_their_field(self) -> None:
        key_a = await self.key(self.ta, self.a)
        stream = HostStream(self.app, key_a, f"campo-a.{DOMAIN}")
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        try:
            await stream.send({"type": "hello", "sync_version": 1, "controller": CONTROLLER, "remote_gm": True})
            self.assertEqual(await stream.receive(), {"type": "hello.ack", "remote_gm": True, "atak_relay": False})
            await stream.send({"type": "live", "sync_version": 1, "controller": CONTROLLER, "live": LIVE})
            await asyncio.sleep(0.05)
            gm_a = await self.staff(self.ta, self.a, "gm")
            gm_b = await self.staff(self.tb, self.b, "gm")
            view = (await self.a.get(f"/api/v1/fields/{self.ta.field_id}/remote-gm", headers=gm_a)).json()
            self.assertEqual([c["controller_id"] for c in view["controllers"]], [CONTROLLER["id"]])
            self.assertEqual((await self.b.get(f"/api/v1/fields/{self.tb.field_id}/remote-gm",
                                               headers=gm_b)).json()["controllers"], [])
            for path in ("", "/commands"):
                with self.subTest(path=path):
                    r = await self.b.request("GET" if not path else "POST",
                                             f"/api/v1/fields/{self.ta.field_id}/remote-gm{path}", headers=gm_b,
                                             json={"game": GAME, "command": "pause"} if path else None)
                    self.assertEqual(r.status_code, 403, r.text)
            # A routing bug that handed B's request A's field id still finds no link: they are keyed by tenant.
            hub = self.app.state.remote_hub
            with tenancy.use(self.tb):
                self.assertEqual(hub.links(self.ta.field_id), [])
            with tenancy.use(self.ta):
                self.assertEqual(len(hub.links(self.ta.field_id)), 1)
        finally:
            await stream.close()


class HostStream(Stream):
    def __init__(self, app: Any, key: str, host: str) -> None:
        super().__init__(app, key)
        self.scope["headers"] = [(b"host", host.encode()), (b"authorization", f"Bearer {key}".encode())]


# Lists, history, public pages, personal data -----------------------------------------------------------

class SurfaceTests(HubCase):
    async def test_history_scoreboard_and_games(self) -> None:
        game_a = await self.synced_game(self.ta, self.a, await self.key(self.ta, self.a))
        admin_a = await self.staff(self.ta, self.a, "admin")
        admin_b = await self.staff(self.tb, self.b, "admin")
        r = await self.a.put(f"/api/v1/fields/{self.ta.field_id}/history/settings", headers=admin_a,
                             json={"public_scoreboard": True})
        self.assertEqual(r.status_code, 200, r.text)
        hist = (await self.a.get(f"/api/v1/fields/{self.ta.field_id}/history", headers=admin_a)).json()
        self.assertEqual([g["id"] for g in hist["games"]], [game_a])
        self.assertEqual((await self.b.get(f"/api/v1/fields/{self.tb.field_id}/history",
                                           headers=admin_b)).json()["games"], [])
        for path in (f"/api/v1/games/{game_a}", f"/api/v1/games/{game_a}/events", f"/api/v1/games/{game_a}/timeline",
                     f"/api/v1/games/{game_a}/log", f"/api/v1/games/{game_a}/roles"):
            with self.subTest(path=path):
                self.assertEqual((await self.a.get(path, headers=admin_a)).status_code, 200)
                self.assertEqual((await self.b.get(path, headers=admin_b)).status_code, 404)
        self.assertEqual((await self.a.get("/f/campo-a/scoreboard.json")).status_code, 200)
        for path in ("/f/campo-a/scoreboard.json", "/f/campo-a/scoreboard"):
            self.assertEqual((await self.b.get(path)).status_code, 404)

    async def test_public_pages_feeds_and_clubs(self) -> None:
        admin_a = await self.staff(self.ta, self.a, "admin")
        r = await self.a.patch(f"/api/v1/fields/{self.ta.field_id}", headers=admin_a, json={"public_page": True})
        self.assertEqual(r.status_code, 200, r.text)
        page = await self.a.get("/f/campo-a/")
        self.assertEqual(page.status_code, 200)
        feed = await self.a.get("/f/campo-a/games.json")
        self.assertEqual(feed.status_code, 200)
        self.assertIn(f"https://campo-a.{DOMAIN}/f/campo-a", feed.text)  # the field's own address (S21-4)
        for path in ("/f/campo-a/", "/f/campo-a/games.json", "/f/campo-a/games.ics"):
            with self.subTest(path=path):
                self.assertEqual((await self.b.get(path)).status_code, 404)
        # A club made in A is unknown in B, by list, by id and by its page.
        _, name, _ = await self.user(self.ta, None)
        player_a = await self.auth(self.a, name)
        r = await self.a.post("/api/v1/clubs", headers=player_a,
                              json={"name": "Lobos do Tejo", "short_name": "Lobos", "slug": "lobos-tejo"})
        self.assertEqual(r.status_code, 201, r.text)
        club = r.json()["id"]
        admin_b = await self.staff(self.tb, self.b, server_admin=True)
        self.assertEqual((await self.b.get("/api/v1/clubs", headers=admin_b)).json(), [])
        self.assertEqual((await self.b.get(f"/api/v1/clubs/{club}", headers=admin_b)).status_code, 404)
        self.assertEqual((await self.b.get("/c/lobos-tejo/")).status_code, 404)
        self.assertEqual((await self.b.put(f"/api/v1/admin/clubs/{club}/hidden", headers=admin_b)).status_code, 404)

    async def test_personal_data_exports_hold_one_field(self) -> None:
        _, name, _ = await self.user(self.ta, "marta")
        await self.user(self.tb, "marta")
        await self.user(self.tb, "outsider-b")
        token = await self.auth(self.a, name)
        data = (await self.a.get("/api/v1/me/data", headers=token)).json()
        self.assertEqual(data["user"]["username"], "marta")
        r = await self.a.get("/api/v1/me/export", headers=token)
        self.assertEqual(r.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            blob = b"".join(zf.read(n) for n in zf.namelist())
        self.assertNotIn(b"outsider-b", blob)
        self.assertNotIn(str(self.tb.field_id).encode(), blob)
        # Erasure in A leaves B's account of the same name alone.
        r = await self.a.request("DELETE", "/api/v1/me", headers=token, json={"password": PASSWORD})
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual(len(await self.sql(self.tb, "SELECT 1 FROM users WHERE username = 'marta'")), 1)
        self.assertEqual(len(await self.sql(self.ta, "SELECT 1 FROM users WHERE username = 'marta'")), 0)

    async def test_the_purge_runs_per_field(self) -> None:
        out = io.StringIO()
        counts = await cli.run_purge(self.settings(), dry_run=True, out=out)
        self.assertIn("(campo-a)", out.getvalue())
        self.assertIn("(campo-b)", out.getvalue())
        self.assertIn("sessions", counts)

    async def test_the_purge_deletes_anonymised_accounts_under_each_field_role(self) -> None:
        """Per field, under the field's own database role: a free ``deleted-...`` row goes, a referenced one stays,
        and the other field's rows are not touched."""
        ids = {}
        for tenant in (self.ta, self.tb):
            free, kept = uuid.uuid4(), uuid.uuid4()
            ids[tenant.slug] = (free, kept)
            for user_id, tag in ((free, "free"), (kept, "kept")):
                await self.sql(tenant, "INSERT INTO users (id, username, password_hash) VALUES ($1, $2, 'DELETED')",
                               user_id, f"deleted-{tag}".ljust(24, "0"))
            await self.sql(tenant, "INSERT INTO audit_log (user_id, action) VALUES ($1, 'login')", kept)
        await self.sql(self.tb, "INSERT INTO users (id, username, password_hash) VALUES ($1, 'deleted-only-b-0000000', "
                       "'DELETED')", uuid.UUID(int=7))
        counts = await cli.run_purge(self.settings(), dry_run=False, out=io.StringIO())
        self.assertEqual(counts["anonymised_users"], 3)
        for tenant in (self.ta, self.tb):
            free, kept = ids[tenant.slug]
            self.assertEqual(await self.sql(tenant, "SELECT 1 FROM users WHERE id = $1", free), [])
            self.assertEqual(len(await self.sql(tenant, "SELECT 1 FROM users WHERE id = $1", kept)), 1)
        self.assertEqual(await self.sql(self.tb, "SELECT 1 FROM users WHERE id = $1", uuid.UUID(int=7)), [])

    async def test_create_admin_needs_a_field(self) -> None:
        def code(uri: str, secret: str) -> str:
            return totp.code_at(secret, next_time())

        with self.assertRaises(cli.CommandError):
            await cli.create_admin(self.settings(), "chefe-a", None, PASSWORD, code, io.StringIO())
        with self.assertRaises(cli.CommandError):
            await cli.create_admin(self.settings(), "chefe-a", None, PASSWORD, code, io.StringIO(), field="campo-z")
        t = next_time()
        user_id = await cli.create_admin(self.settings(), "chefe-a", None, PASSWORD,
                                         lambda uri, secret: totp.code_at(secret, t), io.StringIO(),
                                         clock=lambda: t, field="campo-a")
        self.assertEqual(len(await self.sql(self.ta, "SELECT 1 FROM users WHERE id = $1 AND server_admin", user_id)),
                         1)
        self.assertEqual(len(await self.sql(self.tb, "SELECT 1 FROM users WHERE username = 'chefe-a'")), 0)


# Row-level security and the fields' database roles, directly as the server's login role ---------------------

async def as_field(conn: asyncpg.Connection, tenant: tenancy.Tenant) -> None:
    """What every request of the field does first (``tenancy.TenantSession``), minus the path and the setting."""
    await conn.execute("SELECT set_config('role', $1, true)", tenant.role)


class RowSecurityTests(HubCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.user(self.ta, f"rls-a-{secrets.token_hex(3)}")
        await self.user(self.tb, f"rls-b-{secrets.token_hex(3)}")

    async def test_the_server_login_role_reads_no_field_at_all(self) -> None:
        conn = await connect(self.hub.app_url)
        try:
            self.assertEqual(await conn.fetchval("SHOW search_path"), '"$user", public')  # the role's default
            for schema in (self.ta.schema, self.tb.schema):
                for table in ("users", "fields", "alembic_version"):
                    with self.subTest(schema=schema, table=table):
                        with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                            await conn.fetchval(f"SELECT count(*) FROM {schema}.{table}")
                        await conn.execute("SELECT set_config('atalaia.tenant', $1, false)", schema)  # no help
                        with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                            await conn.fetchval(f"SELECT count(*) FROM {schema}.{table}")
            with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                await conn.execute(f"INSERT INTO {self.ta.schema}.users (username, password_hash) VALUES ('x', 'y')")
        finally:
            await conn.close()

    async def test_a_field_role_without_the_setting_reads_nothing(self) -> None:
        conn = await connect(self.hub.app_url)
        try:
            async with conn.transaction():
                await as_field(conn, self.ta)
                self.assertEqual(await conn.fetchval(f"SELECT count(*) FROM {self.ta.schema}.users"), 0)
                with self.assertRaises(asyncpg.InsufficientPrivilegeError):  # WITH CHECK: no setting writes nothing
                    await conn.execute(f"INSERT INTO {self.ta.schema}.users (username, password_hash) "
                                       "VALUES ('x', 'y')")
        finally:
            await conn.close()

    async def test_a_field_cannot_reach_another_fields_rows_by_setting_its_tenant(self) -> None:
        """S21-13: the setting is no longer what keeps the fields apart. A connection that runs as field A and
        sets ``atalaia.tenant`` to B (what an injected ``set_config`` would do) is refused B's schema, tables
        and sequences outright, for reading and for writing, and keeps reading only A's own rows. The setting is
        put on first, as the server's role (a field's role may not call ``set_config`` at all: the next test)."""
        b_rows = len(await self.sql(self.tb, "SELECT 1 FROM users"))
        self.assertGreater(b_rows, 0)
        conn = await connect(self.hub.app_url)
        a, b = self.ta.schema, self.tb.schema
        try:
            async with conn.transaction():
                await conn.execute("SELECT set_config('atalaia.tenant', $1, true)", b)
                await as_field(conn, self.ta)
                for sql in (f"SELECT count(*) FROM {b}.users", f"SELECT count(*) FROM {b}.fields",
                            f"UPDATE {b}.users SET email = 'x@y.pt'", f"DELETE FROM {b}.fields",
                            f"INSERT INTO {b}.users (username, password_hash) VALUES ('intruder', 'y')",
                            f"SELECT 1 FROM {b}.sessions", f"SELECT * FROM {b}.alembic_version",
                            f"TRUNCATE {b}.users"):
                    with self.subTest(sql=sql):
                        sp = conn.transaction()
                        await sp.start()
                        try:
                            with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                                await conn.execute(sql)
                        finally:
                            await sp.rollback()
                # A's own rows are read only while A's own setting is on (the policy, under the grants)
                self.assertEqual(await conn.fetchval(f"SELECT count(*) FROM {a}.users"), 0)
            async with conn.transaction():
                await conn.execute("SELECT set_config('atalaia.tenant', $1, true)", a)
                await as_field(conn, self.ta)
                self.assertGreater(await conn.fetchval(f"SELECT count(*) FROM {a}.users"), 0)
            # SET LOCAL ROLE and the setting are gone with the transaction.
            self.assertIn(await conn.fetchval("SELECT current_setting('atalaia.tenant', true)"), (None, ""))
            self.assertEqual(await conn.fetchval("SELECT current_user"), self.hub.app_role)
        finally:
            await conn.close()
        self.assertEqual(len(await self.sql(self.tb, "SELECT 1 FROM users")), b_rows)  # nothing of B changed

    async def test_a_savepoint_keeps_the_field_role(self) -> None:
        """A savepoint (``begin_nested``, as registration and the like use) begins inside a transaction that already
        runs as the field's role: it must not set the scope again (that needs ``set_config``), and keeps the role."""
        with tenancy.use(self.ta):
            async with self.app.state.sessionmaker() as db:
                self.assertEqual(await db.scalar(text("SELECT current_user")), self.ta.role)
                async with db.begin_nested():
                    self.assertEqual(await db.scalar(text("SELECT current_user")), self.ta.role)
                    self.assertGreater(len((await db.scalars(select(User))).all()), 0)
            async with self.app.state.sessionmaker() as db:  # a savepoint as the very first thing
                async with db.begin_nested():
                    self.assertEqual(await db.scalar(text("SELECT current_user")), self.ta.role)
                    self.assertGreater(len((await db.scalars(select(User))).all()), 0)

    async def test_a_field_role_cannot_call_set_config(self) -> None:
        """What an SQL injection in a request of field A could try from inside a statement: ``set_config`` of the
        tenant setting, of the search path or of the role itself (to B's, or back to the server's). Every one is
        refused to a field's role, because ``set_config`` is callable by the server's role and the owner only."""
        conn = await connect(self.hub.app_url)
        try:
            for call in (f"set_config('atalaia.tenant', '{self.tb.schema}', true)",
                         f"set_config('search_path', '{self.tb.schema}', true)",
                         f"set_config('role', '{self.tb.role}', true)", "set_config('role', 'none', true)",
                         "set_config('row_security', 'off', true)"):
                with self.subTest(call=call):
                    async with conn.transaction():
                        await as_field(conn, self.ta)
                        with self.assertRaises(asyncpg.InsufficientPrivilegeError) as caught:
                            await conn.fetchval(f"SELECT {call}")
                        self.assertIn("set_config", str(caught.exception))
            # the same call as the server's own role, outside a field's transaction, is what TenantSession does
            self.assertEqual(await conn.fetchval("SELECT set_config('atalaia.tenant', 'x', true)"), "x")
        finally:
            await conn.close()

    async def test_the_known_limit_the_role_command_still_works_for_the_session_user(self) -> None:
        """What this design does not stop, stated so it is a decision and not a surprise (README, hosted mode):
        PostgreSQL authorises ``SET ROLE`` by the *session* user, so a second statement that is a ``SET ROLE``
        command (not a function call) switches to another field. The server's driver sends one statement per
        request (extended protocol, parameters bound), so an injection cannot add one; closing it for good takes
        a login role and a pool per field. If that day comes, this test is the one to turn around."""
        conn = await connect(self.hub.app_url)
        try:
            async with conn.transaction():
                await as_field(conn, self.ta)
                await conn.execute(f'SET LOCAL ROLE "{self.tb.role}"')  # simple protocol: a command of its own
                self.assertEqual(await conn.fetchval("SELECT current_user"), self.tb.role)
        finally:
            await conn.close()

    async def test_one_statement_at_a_time_through_the_server_driver(self) -> None:
        """The premise of the last test: the server's own engine refuses a second statement in one call."""
        with tenancy.use(self.ta):
            async with self.app.state.sessionmaker() as db:
                with self.assertRaises(DBAPIError):
                    await db.execute(text(f'SELECT 1; SET LOCAL ROLE "{self.tb.role}"'))

    async def test_the_server_role_cannot_get_around_it(self) -> None:
        conn = await connect(self.hub.app_url)
        s = self.ta.schema
        attempts = {
            "row_security off": "SET row_security = off; SELECT count(*) FROM {s}.users",
            "truncate": "TRUNCATE {s}.users CASCADE",
            "disable rls": "ALTER TABLE {s}.users DISABLE ROW LEVEL SECURITY",
            "no force": "ALTER TABLE {s}.users NO FORCE ROW LEVEL SECURITY",
            "drop policy": "DROP POLICY atalaia_tenant ON {s}.users",
            "drop table": "DROP TABLE {s}.users",
            "create table": "CREATE TABLE {s}.mine (x int)",
            "create in public": "CREATE TABLE public.mine (x int)",
            "drop schema": "DROP SCHEMA {s} CASCADE",
            "alembic_version": "SELECT * FROM {s}.alembic_version",
            "registry write": "UPDATE public.atalaia_tenants SET status = 'active'",
            "registry insert": "INSERT INTO public.atalaia_tenants (slug, schema_name, field_id) "
                               "VALUES ('x', 'field_x', gen_random_uuid())",
            "hub audit": "SELECT * FROM public.atalaia_hub_audit",
            "bypassrls": "ALTER ROLE CURRENT_USER BYPASSRLS",
            "set role": "SET ROLE {owner}",
            "sharing tables": "SELECT * FROM public.atalaia_share_members",
            "sharing function": "SELECT * FROM public.atalaia_share_read(ARRAY[gen_random_uuid()], 5)",
            "grant to itself": "GRANT SELECT ON {s}.users TO CURRENT_USER",
        }
        try:
            for name, sql in attempts.items():
                with self.subTest(name=name):
                    with self.assertRaises(asyncpg.PostgresError):
                        await conn.execute("SELECT set_config('atalaia.tenant', $1, false)", "")
                        await conn.execute(sql.format(s=s, owner=self.hub.owner))
            # Reading the registry is allowed (the host routing needs it), and nothing else in it is secret.
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM public.atalaia_tenants"), 2)
        finally:
            await conn.close()

    async def test_every_table_is_covered(self) -> None:
        for tenant in (self.ta, self.tb):
            rows = await self.sql(tenant, """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies,
                       pg_get_userbyid(c.relowner) AS owner,
                       has_table_privilege($2, c.oid, 'TRUNCATE') OR has_table_privilege($3, c.oid, 'TRUNCATE')
                           AS truncate
                  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = $1 AND c.relkind = 'r' AND c.relname <> 'alembic_version'""",
                                  tenant.schema, self.hub.app_role, tenant.role)
            self.assertGreater(len(rows), 30)
            for r in rows:
                with self.subTest(schema=tenant.schema, table=r["relname"]):
                    self.assertEqual((r["relrowsecurity"], r["relforcerowsecurity"], r["policies"], r["owner"],
                                      r["truncate"]), (True, True, 1, self.hub.owner, False))
        policy = await self.sql(self.ta, "SELECT pg_get_expr(polqual, polrelid) AS q FROM pg_policy p "
                                         "JOIN pg_class c ON c.oid = p.polrelid WHERE c.relname = 'users' "
                                         "AND c.relnamespace = $1::regnamespace", self.ta.schema)
        self.assertIn(f"'{self.ta.schema}'", policy[0]["q"])

    async def test_a_session_without_a_field_finds_no_table(self) -> None:
        async with self.app.state.sessionmaker() as db:  # no tenant: search_path is pg_catalog
            self.assertEqual(await db.scalar(text("SELECT current_setting('search_path')")), "pg_catalog")
            with self.assertRaises(DBAPIError):
                await db.execute(select(User))
        async with self.app.state.engine.connect() as conn:  # a plain connection: the same
            with self.assertRaises(DBAPIError):
                await conn.execute(text("SELECT count(*) FROM users"))

    async def test_a_simulated_routing_bug_reads_nothing(self) -> None:
        """The bug: the path points at B's schema while the session is A's. Under the fields' own roles it does not
        even read nothing, it is refused (before S2113-1 the policy alone made it read nothing)."""
        with tenancy.use(self.ta):
            async with self.app.state.sessionmaker() as db:
                self.assertGreater(len((await db.scalars(select(User))).all()), 0)
                await db.execute(text(f"SET LOCAL search_path TO {self.tb.schema}"))
                with self.assertRaises(DBAPIError):
                    await db.scalars(select(User))
            async with self.app.state.sessionmaker() as db:
                await db.execute(text(f"SET LOCAL search_path TO {self.tb.schema}"))
                db.add(User(username="planted", password_hash="x"))
                with self.assertRaises(DBAPIError):
                    await db.flush()
        self.assertEqual(len(await self.sql(self.tb, "SELECT 1 FROM users WHERE username = 'planted'")), 0)


class PoolTests(HubCase):
    pool_size = 1  # one connection, reused by every request and session

    async def test_a_pooled_connection_carries_no_field_on(self) -> None:
        _, name_a, _ = await self.user(self.ta, None)
        _, name_b, _ = await self.user(self.tb, None)
        for _ in range(3):
            self.assertEqual((await self.login(self.a, name_a)).status_code, 200)
            self.assertEqual((await self.login(self.b, name_a)).status_code, 401)
            self.assertEqual((await self.login(self.b, name_b)).status_code, 200)
        for tenant in (self.ta, self.tb, None):
            with tenancy.use(tenant):
                async with self.app.state.sessionmaker() as db:
                    path, setting, user = (await db.execute(text(
                        "SELECT current_setting('search_path'), current_setting('atalaia.tenant', true), "
                        "current_user"))).one()
                    self.assertEqual((path, setting, user), (tenant.schema, tenant.schema, tenant.role) if tenant
                                     else ("pg_catalog", "", self.hub.app_role))  # a field's requests run as its role
                    await db.commit()
                    # After the commit the next transaction is set up again, the same way.
                    again = await db.scalar(text("SELECT current_setting('atalaia.tenant', true)"))
                    self.assertEqual(again, tenant.schema if tenant else "")
        async with self.app.state.engine.connect() as conn:
            path, setting, user = (await conn.execute(text(
                "SELECT current_setting('search_path'), current_setting('atalaia.tenant', true), "
                "current_user"))).one()
            self.assertEqual(path, "pg_catalog")
            self.assertIn(setting, (None, ""))
            self.assertEqual(user, self.hub.app_role)  # the role went back with the transaction
        self.assertEqual(self.app.state.engine.pool.size(), 1)


class StartTests(HubCase):
    async def asyncSetUp(self) -> None:
        pass  # no app: each test starts its own

    async def asyncTearDown(self) -> None:
        pass

    async def test_the_server_refuses_a_role_that_could_bypass(self) -> None:
        for url, why in ((self.hub.owner_url, "owns tenant tables"), (self.hub.super_url, "is a superuser")):
            with self.subTest(why=why):
                app = create_app(self.settings(url))
                with self.assertRaisesRegex(tenancy.RoleProblem, why):
                    async with app.router.lifespan_context(app):
                        pass

    async def test_single_field_mode_ignores_the_host(self) -> None:
        database = TempDatabase()
        await asyncio.to_thread(database.create)
        try:
            app = create_app(Settings(allow_signup_without_notice=True, database_url=database.url, secret_key=SECRET_KEY, purge_hour=None))
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url=f"https://campo-a.{DOMAIN}") as client:
                    self.assertEqual((await client.get("/api/v1/fields")).status_code, 401)
        finally:
            await asyncio.to_thread(database.drop)


# The operator's commands: export, import, suspend, migrate, delete ---------------------------------------

class OperatorTests(HubCase):
    async def seed(self, tenant: tenancy.Tenant, client: httpx.AsyncClient, marker: str) -> None:
        await self.user(tenant, f"{marker}-player", "player")
        await self.synced_game(tenant, client, await self.key(tenant, client))
        _, name, _ = await self.user(tenant, f"{marker}-captain")
        r = await client.post("/api/v1/clubs", headers=await self.auth(client, name),
                              json={"name": f"Club {marker}", "short_name": marker[:10], "slug": f"{marker}-club"})
        self.assertEqual(r.status_code, 201, r.text)

    async def test_export_holds_everything_of_the_field_and_nothing_of_another(self) -> None:
        await self.seed(self.ta, self.a, "alfa")
        await self.seed(self.tb, self.b, "bravo")
        b_keys = [r[0] for r in await self.sql(self.tb, "SELECT key_sha256 FROM field_api_keys")]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "campo-a.zip"
            result = await hosted.export_tenant(self.hub.owner_url, "campo-a", out, "controller's request 1/2026",
                                                actor="test:operator")
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
            with self.assertRaises(FileExistsError):  # never overwrites
                await hosted.export_tenant(self.hub.owner_url, "campo-a", out, "again")
            with zipfile.ZipFile(out) as zf:
                names = set(zf.namelist())
                blob = b"".join(zf.read(n) for n in names)
                manifest = json.loads(zf.read("manifest.json"))
                users_csv = list(csv.DictReader(io.StringIO(zf.read("tables/users.csv").decode())))
        tables = {r[0] for r in await self.sql(self.ta, "SELECT tablename FROM pg_tables WHERE schemaname = $1 "
                                                        "AND tablename <> 'alembic_version'", self.ta.schema)}
        self.assertEqual({t["name"] for t in manifest["tables"]}, tables)  # every table of the field
        self.assertEqual(names, {"manifest.json", "README.txt"} | {f"tables/{t}.csv" for t in tables})
        for t in manifest["tables"]:  # every row of the field
            count = (await self.sql(self.ta, f'SELECT count(*) FROM "{t["name"]}"'))[0][0]
            self.assertEqual(t["rows"], count, t["name"])
        self.assertEqual(manifest["field_id"], str(self.ta.field_id))
        self.assertIn("alfa-player", {u["username"] for u in users_csv})
        for marker in (b"bravo", str(self.tb.field_id).encode(), b"campo-b", b"Campo B", *[k.encode() for k in b_keys]):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, blob)  # nothing of another field
        audit = await self.hub_audit("tenant_export")
        self.assertEqual((audit[-1]["slug"], audit[-1]["actor"]), ("campo-a", "test:operator"))
        self.assertEqual(json.loads(audit[-1]["details"])["sha256"], result.sha256)

        # The export runs as a single-field server (ADR-P4-4's migration to self-hosting).
        target = TempDatabase()
        await asyncio.to_thread(target.create)
        try:
            with tempfile.TemporaryDirectory() as tmp2:
                again = Path(tmp2) / "a.zip"
                await hosted.export_tenant(self.hub.owner_url, "campo-a", again, "for the import test")
                counts = await hosted.import_field(target.url, again)
                with self.assertRaisesRegex(hosted.HostedError, "not empty"):
                    await hosted.import_field(target.url, again)
            self.assertEqual(counts["users"], len(await self.sql(self.ta, "SELECT 1 FROM users")))
            rows = await asyncio.to_thread(target.fetch, "SELECT username, totp_enabled FROM users "
                                                         "WHERE username = 'alfa-player'")
            self.assertEqual([tuple(r) for r in rows], [("alfa-player", False)])
            self.assertEqual(await asyncio.to_thread(target.fetch, "SELECT 1 FROM sessions"), [])
            app = create_app(Settings(allow_signup_without_notice=True, database_url=target.url, secret_key="another server's own secret key 0123456",
                                      purge_hour=None))
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                             base_url="https://campo.example.pt") as client:
                    r = await client.post("/api/v1/auth/login", json={"username": "alfa-player",
                                                                      "password": PASSWORD})
                    self.assertEqual(r.status_code, 200, r.text)
                    r = await client.post("/api/v1/sync/games", json=envelope(meta=META),
                                          headers={"Authorization": f"Bearer {b_keys[0]}"})
                    self.assertEqual(r.status_code, 401)
        finally:
            await asyncio.to_thread(target.drop)

    async def hub_audit(self, action: str) -> list[asyncpg.Record]:
        conn = await connect(self.hub.owner_url)
        try:
            return await conn.fetch("SELECT * FROM public.atalaia_hub_audit WHERE action = $1 ORDER BY id", action)
        finally:
            await conn.close()

    async def test_suspend_migrate_and_delete(self) -> None:
        url = self.hub.owner_url
        tc = await asyncio.to_thread(hosted.create_tenant, url, "campo-c", "Campo C", "cqb", "Europe/Lisbon",
                                     self.hub.app_role, "test:operator")
        c = self.client("campo-c")
        # S2113-1: creating a field made its database role (named from the field's id, no login), and the server's
        # login role may only SET ROLE to it.
        role_c = tc.role
        self.assertRegex(role_c, r"^atalaia_t_[0-9a-f]{32}$")
        self.assertEqual(role_c, "atalaia_t_" + tc.field_id.hex)
        row = (await self.sql(self.tb, "SELECT rolcanlogin, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                                       "FROM pg_roles WHERE rolname = $1", role_c))[0]
        self.assertEqual(tuple(row), (False, False, False, False, False))
        self.assertTrue((await self.sql(self.tb, "SELECT pg_has_role($1, $2, 'SET')", self.hub.app_role, role_c))[0][0])
        self.assertFalse((await self.sql(self.tb, "SELECT pg_has_role($1, $2, 'USAGE')", self.hub.app_role,
                                         role_c))[0][0])  # no INHERIT: the login role does not hold its grants
        await self.seed(tc, c, "charlie")
        await self.seed(self.tb, self.b, "bravissimo")
        before_b = {r[0]: r[1] for r in await self.sql(self.tb, "SELECT 'users', count(*) FROM users UNION ALL "
                                                                "SELECT 'games', count(*) FROM games")}
        # Suspended: every request refused, data kept.
        await hosted.set_status(url, "campo-c", "suspended", "unpaid", actor="test:operator")
        r = await c.get("/f/campo-c/")
        self.assertEqual((r.status_code, r.json()), (403, {"detail": "field_suspended"}))
        await hosted.set_status(url, "campo-c", "active", "paid", actor="test:operator")
        self.assertEqual((await c.post("/api/v1/auth/login", json={"username": "charlie-player",
                                                                   "password": PASSWORD})).status_code, 200)
        # Migrating every field is idempotent and keeps the security.
        done = await asyncio.to_thread(hosted.migrate_all, url, self.hub.app_role, "test:operator")
        self.assertEqual(done, ["campo-a", "campo-b", "campo-c"])
        # Deletion: confirmed, with a reason; everything of C goes, B is untouched, the hub's log keeps counts.
        with self.assertRaisesRegex(hosted.HostedError, "--confirm"):
            await hosted.delete_tenant(url, "campo-c", "campo-b", "contract ended")
        with self.assertRaisesRegex(hosted.HostedError, "--reason"):
            await hosted.delete_tenant(url, "campo-c", "campo-c", " ")
        counts = await hosted.delete_tenant(url, "campo-c", "campo-c", "contract ended 2026-10-20",
                                            actor="test:operator")
        self.assertGreater(counts["users"], 0)
        self.assertGreater(counts["games"], 0)
        conn = await connect(url)
        try:
            self.assertIsNone(await conn.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = 'field_campo_c'"))
            self.assertIsNone(await conn.fetchval("SELECT 1 FROM public.atalaia_tenants WHERE slug = 'campo-c'"))
            # S2113-1: the field's database role went with it, and nobody else's did.
            self.assertIsNone(await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role_c))
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM pg_roles WHERE rolname = ANY($1)",
                                                 [self.ta.role, self.tb.role]), 2)
        finally:
            await conn.close()
        audit = await self.hub_audit("tenant_delete")
        details = json.loads(audit[-1]["details"])
        self.assertEqual((audit[-1]["slug"], details["reason"], details["rows"]["users"]),
                         ("campo-c", "contract ended 2026-10-20", counts["users"]))
        self.assertNotIn("charlie", audit[-1]["details"])  # counts, never rows or names
        r = await c.get("/f/campo-c/")
        self.assertEqual((r.status_code, r.json()), (404, {"detail": "unknown_field"}))
        after_b = {r[0]: r[1] for r in await self.sql(self.tb, "SELECT 'users', count(*) FROM users UNION ALL "
                                                               "SELECT 'games', count(*) FROM games")}
        self.assertEqual(after_b, before_b)
        self.assertEqual([a["action"] for a in await self.hub_audit("tenant_suspend")], ["tenant_suspend"])
        with self.assertRaisesRegex(hosted.HostedError, "no field"):
            await hosted.delete_tenant(url, "campo-c", "campo-c", "again")

    async def test_create_refusals(self) -> None:
        url = self.hub.owner_url
        with self.assertRaisesRegex(hosted.HostedError, "already exists"):
            await asyncio.to_thread(hosted.create_tenant, url, "campo-a", "Again", app_role=self.hub.app_role)
        with self.assertRaises(tenancy.TenantError):
            await asyncio.to_thread(hosted.create_tenant, url, "Campo_D", "Bad", app_role=self.hub.app_role)
        with self.assertRaisesRegex(hosted.HostedError, "time zone"):
            await asyncio.to_thread(hosted.create_tenant, url, "campo-d", "D", "outdoor", "Mars/Olympus",
                                    self.hub.app_role)
        with self.assertRaisesRegex(hosted.HostedError, "does not exist"):
            await asyncio.to_thread(hosted.create_tenant, url, "campo-d", "D", app_role="nobody_here")
        # A failure after the schema was made leaves nothing behind.
        with unittest.mock.patch.object(hosted, "migrate_schema", side_effect=RuntimeError("migration broke")):
            with self.assertRaisesRegex(RuntimeError, "migration broke"):
                await asyncio.to_thread(hosted.create_tenant, url, "campo-d", "D", app_role=self.hub.app_role)
        conn = await connect(url)
        try:
            self.assertIsNone(await conn.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = 'field_campo_d'"))
        finally:
            await conn.close()
        # The server's role may not be a superuser, and a single-field database is no hub.
        with self.assertRaisesRegex(hosted.HostedError, "superuser"):
            await hosted.init_hub(url, make_url(server_url()).username or "")
        single = TempDatabase()
        await asyncio.to_thread(single.create)
        try:
            with self.assertRaisesRegex(hosted.HostedError, "database of its own"):
                await hosted.init_hub(single.url, self.hub.app_role)
        finally:
            await asyncio.to_thread(single.drop)

    async def test_the_commands(self) -> None:
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.dict(os.environ, {"ATALAIA_DATABASE_URL": self.hub.owner_url,
                                                   "ATALAIA_APP_ROLE": self.hub.app_role}):
            code = await asyncio.to_thread(cli.main, ["hosted", "list"], io.StringIO(), out, err)
            self.assertEqual(code, 0, err.getvalue())
            self.assertIn("campo-a\tactive\tfield_campo_a", out.getvalue())
            code = await asyncio.to_thread(cli.main, ["hosted", "delete", "campo-a", "--confirm", "campo-b",
                                                      "--reason", "x"], io.StringIO(), out, err)
            self.assertEqual(code, 1)
            self.assertIn("--confirm", err.getvalue())
        self.assertEqual(len(await self.sql(self.ta, "SELECT 1 FROM fields")), 1)


class HubCheckTests(HubCase):
    """``hosted check`` (Phase 4 follow-up, decisions FU4-*): what restore.sh runs after restoring a hub."""

    async def asyncSetUp(self) -> None:
        pass  # no app

    async def asyncTearDown(self) -> None:
        pass

    async def owner(self, statement: str) -> None:
        conn = await connect(self.hub.owner_url)
        try:
            await conn.execute(statement)
        finally:
            await conn.close()

    async def check(self) -> hosted.HubCheck:
        return await hosted.check_hub(self.hub.owner_url, self.hub.app_role)

    async def test_a_sound_hub_passes(self) -> None:
        report = await self.check()
        self.assertEqual(report.problems, [])
        self.assertEqual(report.fields, 2)
        self.assertGreaterEqual(report.tables, 60)  # two fields, every table of each
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch.dict(os.environ, {"ATALAIA_DATABASE_URL": self.hub.owner_url,
                                                   "ATALAIA_APP_ROLE": self.hub.app_role}):
            code = await asyncio.to_thread(cli.main, ["hosted", "check"], io.StringIO(), out, err)
        self.assertEqual(code, 0, err.getvalue())
        self.assertIn("Hub check passed: 2 fields", out.getvalue())

    async def test_every_weakening_is_found(self) -> None:
        app = self.hub.app_role
        ra, rb = self.hub.a.role, self.hub.b.role
        breaks = [
            ("ALTER TABLE field_campo_b.users NO FORCE ROW LEVEL SECURITY", "field_campo_b.users: row-level"),
            ("ALTER TABLE field_campo_a.games DISABLE ROW LEVEL SECURITY", "field_campo_a.games: row-level"),
            (f"GRANT TRUNCATE ON field_campo_a.game_events TO {ra}", "TRUNCATE"),
            (f"GRANT SELECT ON field_campo_a.game_events TO {app}", "field_campo_a.game_events, not nothing"),
            (f"REVOKE DELETE ON field_campo_b.sessions FROM {rb}", "field_campo_b.sessions, not"),
            ("CREATE POLICY open_door ON field_campo_a.users USING (true)", "field_campo_a.users: the policies"),
            ("DROP POLICY atalaia_tenant ON field_campo_b.clubs", "field_campo_b.clubs: the policies"),
            (f"GRANT SELECT ON field_campo_a.alembic_version TO {ra}", "field_campo_a.alembic_version"),
            (f"GRANT SELECT ON field_campo_a.alembic_version TO {app}", "field_campo_a.alembic_version"),
            (f"GRANT SELECT ON public.atalaia_hub_audit TO {app}", "public.atalaia_hub_audit"),
            (f"GRANT UPDATE ON public.atalaia_tenants TO {app}", "public.atalaia_tenants"),
            (f"GRANT SELECT ON public.atalaia_quota_hits TO {app}", "public.atalaia_quota_hits"),
            (f"REVOKE INSERT ON public.atalaia_quota_hits FROM {app}", "public.atalaia_quota_hits"),
            (f"REVOKE USAGE ON SCHEMA field_campo_b FROM {rb}", f"{rb} has no USAGE on field_campo_b"),
            (f"GRANT USAGE ON SCHEMA field_campo_b TO {app}", f"{app} has privileges on field_campo_b itself"),
            (f"GRANT USAGE ON SCHEMA field_campo_b TO {ra}", f"{ra} has privileges on field_campo_b, another"),
            # The fields' database roles (S2113-1).
            (f"ALTER ROLE {rb} LOGIN", f"{rb} has rolcanlogin"),
            (f"REVOKE {rb} FROM {app}", f"{app} cannot SET ROLE to {rb}"),
            (f"GRANT {rb} TO {app} WITH INHERIT TRUE", f"{app} inherits the grants of {rb}"),

            ("CREATE SCHEMA field_orphan", "field_orphan is not registered"),
            # The hub-level chrono sharing (SVX-2).
            ("ALTER TABLE public.atalaia_share_records FORCE ROW LEVEL SECURITY", "atalaia_share_records: row-level"),
            ("ALTER TABLE public.atalaia_share_members DISABLE ROW LEVEL SECURITY", "atalaia_share_members: row-level"),
            ("DROP POLICY atalaia_tenant ON public.atalaia_share_codes", "atalaia_share_codes: the policies"),
            ("CREATE POLICY open_door ON public.atalaia_share_records USING (true)",
             "atalaia_share_records: the policies"),
            (f"GRANT TRUNCATE ON public.atalaia_share_records TO {ra}", "public.atalaia_share_records"),
            (f"GRANT SELECT ON public.atalaia_share_records TO {app}", f"{app} has ['SELECT'] on public.atalaia"),
            (f"REVOKE DELETE ON public.atalaia_share_members FROM {rb}", "public.atalaia_share_members"),
            ("CREATE POLICY open_door ON public.atalaia_share_members USING (tenant = 'field_campo_a')",
             "atalaia_share_members: the policies"),
            ("GRANT EXECUTE ON FUNCTION public.atalaia_share_read(uuid[], integer) TO PUBLIC",
             "can be run by anyone"),
            ("ALTER FUNCTION public.atalaia_share_read(uuid[], integer) SECURITY INVOKER", "not a SECURITY DEFINER"),
            ("ALTER FUNCTION public.atalaia_share_redeem(bytea) RESET search_path", "no fixed search_path"),
            (f"REVOKE EXECUTE ON FUNCTION public.atalaia_share_redeem(bytea) FROM {ra}", "cannot run"),
            (f"REVOKE EXECUTE ON FUNCTION public.atalaia_caller_tenant() FROM {rb}", "cannot run"),
            (f"GRANT EXECUTE ON FUNCTION public.atalaia_share_redeem(bytea) TO {app}", f"{app} can run"),
        ]
        for statement, problem in breaks:
            with self.subTest(statement=statement):
                await self.owner(statement)
                try:
                    problems = (await self.check()).problems
                    self.assertTrue(any(problem in p for p in problems), problems)
                finally:  # the operator's own repair: the grants and policies again
                    await self.owner(f"DROP SCHEMA IF EXISTS field_orphan; DROP POLICY IF EXISTS open_door ON "
                                     f"field_campo_a.users; DROP POLICY IF EXISTS open_door ON "
                                     f"public.atalaia_share_records; DROP POLICY IF EXISTS open_door ON public.atalaia_share_members; "
                                     f"REVOKE ALL ON SCHEMA field_campo_b FROM {ra}; "
                                     f"REVOKE ALL ON public.atalaia_hub_audit FROM {app}; "
                                     f"REVOKE ALL ON public.atalaia_tenants FROM {app}; "
                                     f"GRANT SELECT ON public.atalaia_tenants TO {app}")
                    await asyncio.to_thread(hosted.migrate_all, self.hub.owner_url, app, "test:operator")
                self.assertEqual((await self.check()).problems, [])
        await self.owner("ALTER TABLE field_campo_a.users NO FORCE ROW LEVEL SECURITY")
        out, err = io.StringIO(), io.StringIO()
        try:
            with unittest.mock.patch.dict(os.environ, {"ATALAIA_DATABASE_URL": self.hub.owner_url,
                                                       "ATALAIA_APP_ROLE": app}):
                code = await asyncio.to_thread(cli.main, ["hosted", "check"], io.StringIO(), out, err)
            self.assertEqual(code, 1)
            self.assertIn("the hub check found 1 problems", err.getvalue())
        finally:
            await asyncio.to_thread(hosted.migrate_all, self.hub.owner_url, app, "test:operator")

    async def test_the_server_role_and_a_missing_schema(self) -> None:
        with self.assertRaisesRegex(hosted.HostedError, "does not exist"):
            await hosted.check_hub(self.hub.owner_url, "nobody_here")
        report = await hosted.check_hub(self.hub.app_url, self.hub.app_role)  # run as the wrong role
        self.assertTrue(any("must run as the owner role" in p for p in report.problems), report.problems)
        conn = await connect(self.hub.owner_url)
        try:
            await conn.execute("ALTER SCHEMA field_campo_b RENAME TO field_campo_b_moved")
            try:
                problems = (await self.check()).problems
            finally:
                await conn.execute("ALTER SCHEMA field_campo_b_moved RENAME TO field_campo_b")
        finally:
            await conn.close()
        self.assertTrue(any("campo-b is registered but its schema field_campo_b is missing" in p for p in problems))
        self.assertTrue(any("field_campo_b_moved is not registered" in p for p in problems))


if __name__ == "__main__":
    unittest.main()
