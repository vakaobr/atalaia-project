# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hosted hub's ``ask`` endpoint for Caddy's on-demand TLS (atalaia_server/tls_ask.py; decisions FU4-*).

Only an active field's own name, ``<slug>.<domain>``, may get a certificate;
everything else is refused, a flood is cut off before it reaches the database,
and a database that cannot be read means no certificate. The last class runs
it against a real hub's registry (the operator's commands, the server's role).

    python3 tools/docker_server.py test tests.test_tls_ask
"""

from __future__ import annotations

import asyncio
import unittest
import uuid
from typing import Optional

import httpx

from atalaia_server import hosted, tenancy, tls_ask
from atalaia_server.config import ConfigError

from .test_tenants import DOMAIN, Hub

ACTIVE = tenancy.Tenant(slug="campo-a", schema="field_campo_a", field_id=uuid.uuid4())
SUSPENDED = tenancy.Tenant(slug="campo-s", schema="field_campo_s", field_id=uuid.uuid4(), status="suspended")


class FakeRegistry:
    def __init__(self, fail: bool = False) -> None:
        self.asked: list[str] = []
        self.fail = fail

    async def __call__(self, slug: str) -> Optional[tenancy.Tenant]:
        self.asked.append(slug)
        if self.fail:
            raise OSError("connection refused")
        return {t.slug: t for t in (ACTIVE, SUSPENDED)}.get(slug)


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class TokenBucketTests(unittest.TestCase):
    def test_burst_then_rate(self) -> None:
        clock = Clock()
        bucket = tls_ask.TokenBucket(rate=2.0, burst=3, clock=clock)
        self.assertEqual([bucket.take() for _ in range(4)], [True, True, True, False])
        clock.t += 0.5  # one token back
        self.assertEqual([bucket.take(), bucket.take()], [True, False])
        clock.t += 60  # never more than the burst
        self.assertEqual(sum(bucket.take() for _ in range(10)), 3)


class SlugTests(unittest.TestCase):
    def test_only_a_fields_own_name(self) -> None:
        self.assertEqual(tls_ask.slug_for("campo-a.hub.test", DOMAIN), "campo-a")
        self.assertEqual(tls_ask.slug_for("CAMPO-A.Hub.Test.", DOMAIN), "campo-a")
        for name in ("hub.test", "x.campo-a.hub.test", "campo-a.hub.test.evil.test", "campo-a.hub.test:443",
                     "campo_a.hub.test", "-a.hub.test", "campo-a.otherhub.test", "campo-ahub.test", "",
                     "a" * 41 + ".hub.test", "a." * 200 + "hub.test", "campo-a..hub.test"):
            with self.subTest(name=name):
                self.assertIsNone(tls_ask.slug_for(name, DOMAIN))

    def test_the_domain_is_checked(self) -> None:
        for bad in ("", "localhost", "https://hub.test", "hub.test:443", "hub.test/x"):
            with self.subTest(domain=bad), self.assertRaises(ConfigError):
                tls_ask.AskApp(bad, FakeRegistry())
        with self.assertRaises(ConfigError):
            tls_ask.create_app({"ATALAIA_DATABASE_URL": "postgresql+asyncpg://u:p@db/x"})


class AskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.registry = FakeRegistry()
        self.clock = Clock()
        self.app = tls_ask.AskApp(DOMAIN, self.registry, tls_ask.TokenBucket(5.0, 20, clock=self.clock))
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://tls-ask:8001")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()

    async def ask(self, *names: str) -> int:
        r = await self.client.get("/check", params=[("domain", n) for n in names])
        self.assertEqual(r.headers.get("cache-control"), "no-store")
        return r.status_code

    async def test_yes_only_for_an_active_field(self) -> None:
        self.assertEqual(await self.ask("campo-a.hub.test"), 200)
        self.assertEqual(await self.ask("Campo-A.hub.test."), 200)
        self.assertEqual(await self.ask("campo-s.hub.test"), 404)  # suspended
        self.assertEqual(await self.ask("nobody.hub.test"), 404)  # not registered
        self.assertEqual(self.registry.asked, ["campo-a", "campo-a", "campo-s", "nobody"])
        for name in ("hub.test", "www.campo-a.hub.test", "campo-a.hub.test.evil.test", "example.com", "127.0.0.1"):
            with self.subTest(name=name):
                self.assertEqual(await self.ask(name), 404)
        self.assertEqual(len(self.registry.asked), 4)  # names that are no field's never reach the registry

    async def test_bad_requests(self) -> None:
        self.assertEqual(await self.ask(), 400)
        self.assertEqual(await self.ask("campo-a.hub.test", "nobody.hub.test"), 400)
        self.assertEqual((await self.client.get("/check?domain")).status_code, 400)
        self.assertEqual((await self.client.post("/check", params={"domain": "campo-a.hub.test"})).status_code, 405)
        self.assertEqual((await self.client.get("/")).status_code, 404)
        self.assertEqual((await self.client.get("/check/x", params={"domain": "campo-a.hub.test"})).status_code,
                         404)
        r = await self.client.get("/health")
        self.assertEqual((r.status_code, r.text), (200, "ok\n"))
        self.assertEqual(self.registry.asked, [])

    async def test_a_flood_is_cut_off_before_the_database(self) -> None:
        codes = [await self.ask(f"x{i}.hub.test") for i in range(30)]
        self.assertEqual(codes, [404] * 20 + [429] * 10)
        self.assertEqual(len(self.registry.asked), 20)
        self.assertEqual(await self.ask("campo-a.hub.test"), 429)  # a real field waits too
        self.clock.t += 1.0  # five a second
        self.assertEqual([await self.ask("campo-a.hub.test") for _ in range(6)], [200] * 5 + [429])

    async def test_no_database_no_certificate(self) -> None:
        self.registry.fail = True
        with self.assertLogs("atalaia.tls_ask", "WARNING"):
            self.assertEqual(await self.ask("campo-a.hub.test"), 503)


class RegistryTests(unittest.IsolatedAsyncioTestCase):
    """Against a real hub: the server's role reads the registry; the operator suspends a field."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.hub = Hub()
        try:
            cls.hub.create()
        except BaseException:
            cls.hub.drop()
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        cls.hub.drop()

    async def test_the_registry_decides(self) -> None:
        app = tls_ask.create_app({"ATALAIA_DATABASE_URL": self.hub.app_url, "ATALAIA_HOSTED_DOMAIN": "HUB.test"})
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tls-ask") as c:
                async def ask(name: str) -> int:
                    return (await c.get("/check", params={"domain": name})).status_code

                self.assertEqual([await ask("campo-a.hub.test"), await ask("campo-b.hub.test"),
                                  await ask("campo-c.hub.test")], [200, 200, 404])
                await hosted.set_status(self.hub.owner_url, "campo-b", "suspended", "test", actor="test:operator")
                try:
                    self.assertEqual(await ask("campo-b.hub.test"), 404)
                finally:
                    await hosted.set_status(self.hub.owner_url, "campo-b", "active", "test", actor="test:operator")
                self.assertEqual(await ask("campo-b.hub.test"), 200)
        finally:
            await app.close()

    async def test_lifespan_closes_the_engine(self) -> None:
        app = tls_ask.create_app({"ATALAIA_DATABASE_URL": self.hub.app_url, "ATALAIA_HOSTED_DOMAIN": DOMAIN})
        sent: list[dict] = []
        messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])

        async def receive() -> dict:
            return next(messages)

        async def send(message: dict) -> None:
            sent.append(message)

        await asyncio.wait_for(app({"type": "lifespan"}, receive, send), 5)
        self.assertEqual([m["type"] for m in sent], ["lifespan.startup.complete", "lifespan.shutdown.complete"])


if __name__ == "__main__":
    unittest.main()
