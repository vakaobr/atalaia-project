# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Health, metrics, security headers and the served app (PostgreSQL 16)."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request
from typing import Optional

from sqlalchemy.engine import make_url

from atalaia_server import __version__
from atalaia_server.config import Settings
from atalaia_server.models import Field
from atalaia_server.security_headers import HEADERS

from .base import METRICS_TOKEN, SECRET_KEY, SERVER, AppTestCase


def assert_security_headers(case: unittest.TestCase, headers) -> None:
    for name, value in HEADERS:
        case.assertEqual(headers.get(name), value, name)


class HealthTests(AppTestCase):
    async def test_healthy(self) -> None:
        r = await self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body, {"status": "ok"})  # LIVE-3: no version, no database state, no uptime
        metrics = (await self.client.get("/api/v1/metrics", headers={"Authorization": f"Bearer {METRICS_TOKEN}"})).json()
        self.assertEqual(metrics["version"], __version__)
        self.assertEqual(metrics["database"], "connected")
        self.assertIsInstance(metrics["uptime_s"], int)
        self.assertEqual(r.headers["cache-control"], "no-store")
        assert_security_headers(self, r.headers)

    async def test_security_headers_on_errors_too(self) -> None:
        for path in ("/no/such/page", "/api/v1/openapi.json", "/api/v1/metrics"):
            with self.subTest(path=path):
                r = await self.client.get(path)
                assert_security_headers(self, r.headers)

    async def test_no_interactive_api_pages(self) -> None:
        # They load scripts from a CDN, which the content security policy forbids.
        for path in ("/docs", "/redoc"):
            self.assertEqual((await self.client.get(path)).status_code, 404, path)
        spec = (await self.client.get("/api/v1/openapi.json")).json()
        self.assertIn("/api/v1/health", spec["paths"])

    async def test_metrics_need_the_token_or_an_administrator(self) -> None:
        for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {METRICS_TOKEN}"},
                        {"Authorization": f"Bearer {METRICS_TOKEN}x"}):
            with self.subTest(headers=headers):
                r = await self.client.get("/api/v1/metrics", headers=headers)
                self.assertEqual(r.status_code, 401)
                self.assertEqual(r.headers["www-authenticate"], "Bearer")

    async def test_metrics(self) -> None:
        auth = {"Authorization": f"Bearer {METRICS_TOKEN}"}
        r = await self.client.get("/api/v1/metrics", headers=auth)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["database"], "connected")
        self.assertEqual((body["fields_total"], body["users_total"], body["sessions_active"]), (0, 0, 0))
        self.assertEqual(body["db_pool_size"], self.settings().db_pool_size)
        self.assertIsInstance(body["db_pool_checked_out"], int)
        self.assertEqual(body["version"], __version__)
        async with self.app.state.sessionmaker() as session:
            session.add(Field(name="Campo", slug="campo-metrics"))
            await session.commit()
        self.assertEqual((await self.client.get("/api/v1/metrics", headers=auth)).json()["fields_total"], 1)
        await self.fetch("DELETE FROM fields WHERE slug = 'campo-metrics'")


class MetricsAccountTests(AppTestCase):
    """Without ATALAIA_METRICS_TOKEN only server administrators read the metrics (S10-2, S11-9)."""

    metrics_token = None

    async def test_server_administrators_only(self) -> None:
        r = await self.client.get("/api/v1/metrics", headers={"Authorization": f"Bearer {METRICS_TOKEN}"})
        self.assertEqual(r.status_code, 401)
        _, admin, secret = await self.make_user(server_admin=True)
        r = await self.client.get("/api/v1/metrics", headers=await self.auth(admin, secret=secret))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["users_total"], r.json()["sessions_active"]), (1, 1))
        _, player, _ = await self.make_user()
        r = await self.client.get("/api/v1/metrics", headers=await self.auth(player))
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.json()["detail"], "server_admin_required")


class DatabaseDownTests(AppTestCase):
    """The app starts, and says so, when PostgreSQL does not answer."""

    def settings(self) -> Settings:
        closed = _free_port()  # nothing listens there: the connection is refused at once
        url = make_url(self.database_url).set(host="127.0.0.1", port=closed).render_as_string(hide_password=False)
        return Settings(database_url=url, secret_key=SECRET_KEY, metrics_token=METRICS_TOKEN, db_timeout_s=2.0)

    async def test_unhealthy(self) -> None:
        r = await self.client.get("/api/v1/health")
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json(), {"status": "unhealthy"})
        assert_security_headers(self, r.headers)

    async def test_metrics_say_so(self) -> None:
        r = await self.client.get("/api/v1/metrics", headers={"Authorization": f"Bearer {METRICS_TOKEN}"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["database"], "unreachable")


class ModelDefaultsTests(AppTestCase):
    async def test_keys_and_defaults(self) -> None:
        async with self.app.state.sessionmaker() as session:
            field = Field(name="Campo", slug="campo-defaults")
            session.add(field)
            await session.commit()
            await session.refresh(field)
        self.assertEqual(field.id.version, 7)
        self.assertEqual((field.field_type, field.timezone, field.default_retention_days),
                         ("outdoor", "Europe/Lisbon", 365))
        self.assertFalse(field.chrono_sharing_enabled or field.public_scoreboard)
        self.assertIsNotNone(field.created_at.tzinfo)
        # The database's own default is a UUID too, for rows written without the ORM.
        rows = await self.fetch("INSERT INTO fields (name, slug) VALUES ('Outro', 'outro') RETURNING id")
        self.assertEqual(rows[0]["id"].version, 4)
        await self.fetch("DELETE FROM fields")


class ServeTests(AppTestCase):
    """The command the image runs (uvicorn's factory) serves the health check over real HTTP."""

    async def test_uvicorn_serves_health_and_stops_cleanly(self) -> None:
        port = _free_port()
        env = {**os.environ, "ATALAIA_DATABASE_URL": self.database_url, "ATALAIA_SECRET_KEY": SECRET_KEY,
               "ATALAIA_PUBLIC_URL": "http://localhost:8000"}  # the server refuses to start without it (SRV-7)
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "--factory", "atalaia_server.app:create_app",
                                 "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
                                cwd=SERVER, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            body = await asyncio.to_thread(_poll_health, port, proc)
        finally:
            proc.terminate()  # SIGTERM, as `docker stop` sends it
            out, _ = await asyncio.to_thread(proc.communicate, timeout=20)
        log = out.decode(errors="replace")
        self.assertIsNotNone(body, log)
        self.assertEqual(body["status"], "ok")
        # uvicorn shuts the app down (the lifespan disposes the engine), then exits by the signal it got.
        self.assertIn("Application shutdown complete.", log)
        self.assertIn(proc.returncode, (0, -signal.SIGTERM), log)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _poll_health(port: int, proc: subprocess.Popen) -> Optional[dict]:
    """The same request as the Compose files' health check (the standard library only)."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and proc.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=2) as r:
                return json.load(r)
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    return None


if __name__ == "__main__":
    unittest.main()
