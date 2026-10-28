# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What hosted mode adds for S21-12: per-field quotas, the export of a field's own data and the immediate end of a
deleted or suspended field's sockets (``quotas.py``, ``field_export.py``, ``tenant_watch.py``).

Runs on the hub of ``test_tenants.HubCase`` (two fields, the server's role without BYPASSRLS):

- quotas: each resource refused with 409 ``quota_exceeded`` past its limit, at one field only, the other field's
  count untouched; ``off`` lifts a limit; the sync (HTTP and the stream) and the stream quota answer in their own
  ways;
- the export: a hosted field's archive holds the whole tenant (accounts without a role, the clubs), nothing of
  the other field, is audit-logged in the field, and a field's admin cannot ask for another field's;
- the watch: the sockets, the remote GM's link and the ATAK relay's connections of a deleted field close at once
  (4404), those of a suspended field with 4403, a field made again under the same name is another field.

    python3 tools/docker_server.py test tests.test_hosted_limits
"""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import unittest
import unittest.mock
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from atalaia_server import hosted, quotas, tenancy
from atalaia_server.config import QUOTA_DEFAULTS, Settings
from atalaia_server.models import ScheduledGame

from .base import PASSWORD
from .test_registration_import import CSV, ImportCase
from .test_remote_gm import LIVE
from .test_tenants import CONTROLLER, DOMAIN, META, HostStream, HubCase, envelope


def hour(hours: float) -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0) + timedelta(hours=hours)


class LimitCase(HubCase):
    watch_s = 60.0  # no sweep by itself unless a test wants one

    def settings(self, url: Optional[str] = None) -> Settings:
        return dataclasses.replace(super().settings(url), hosted_watch_s=self.watch_s)

    def limit(self, **limits: int) -> None:
        """Quotas for the running app (the middleware reads them per request); the rest as the defaults."""
        settings: Settings = self.app.state.settings
        self.app.state.settings = dataclasses.replace(settings, quotas={**QUOTA_DEFAULTS, **limits})

    async def count(self, tenant: tenancy.Tenant, table: str) -> int:
        return int((await self.sql(tenant, f"SELECT count(*) FROM {table}"))[0][0])

    def game_body(self, title: str = "Domingo") -> dict[str, Any]:
        start = hour(48)
        return {"title": title, "starts_at": start.isoformat(), "ends_at": (start + timedelta(hours=4)).isoformat(),
                "mode_id": "org.atalaia.domination", "teams": ["red", "blue"]}


class QuotaTests(LimitCase):
    async def test_defaults_are_generous_and_configurable(self) -> None:
        settings: Settings = self.app.state.settings
        self.assertEqual(dict(settings.quotas), QUOTA_DEFAULTS)
        self.assertTrue(all(v > 0 for v in settings.quotas.values()))

    async def test_scheduled_games_quota_is_per_field(self) -> None:
        gm_a = await self.staff(self.ta, self.a, "gm")
        gm_b = await self.staff(self.tb, self.b, "gm")
        have = await self.count(self.ta, "scheduled_games")
        self.limit(scheduled_games=have + 2)
        url_a = f"/api/v1/fields/{self.ta.field_id}/scheduled-games"
        for i in range(2):
            r = await self.a.post(url_a, json=self.game_body(f"Jogo {i}"), headers=gm_a)
            self.assertEqual(r.status_code, 201, r.text)
        r = await self.a.post(url_a, json=self.game_body("Um a mais"), headers=gm_a)
        self.assertEqual((r.status_code, r.json()), (409, {"detail": "quota_exceeded", "quota": "scheduled_games",
                                                           "limit": have + 2}))
        self.assertEqual(await self.count(self.ta, "scheduled_games"), have + 2)
        # B has its own count: with the same limit it still has room (A's rows never count at B).
        self.limit(scheduled_games=(await self.count(self.tb, "scheduled_games")) + 1)
        r = await self.b.post(f"/api/v1/fields/{self.tb.field_id}/scheduled-games", json=self.game_body(),
                              headers=gm_b)
        self.assertEqual(r.status_code, 201, r.text)
        # Off: no limit.
        self.limit(scheduled_games=0)
        r = await self.a.post(url_a, json=self.game_body("Sem limite"), headers=gm_a)
        self.assertEqual(r.status_code, 201, r.text)

    async def test_accounts_quota(self) -> None:
        self.limit(accounts=(await self.count(self.ta, "users")) + 1)
        body = {"username": "nova-conta", "password": PASSWORD, "consent": True}
        r = await self.a.post("/api/v1/auth/register", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self.a.post("/api/v1/auth/register", json={**body, "username": "uma-a-mais"})
        self.assertEqual((r.status_code, r.json()["detail"], r.json()["quota"]), (409, "quota_exceeded", "accounts"))
        self.assertEqual(await self.sql(self.ta, "SELECT 1 FROM users WHERE username = 'uma-a-mais'"), [])
        # B counts its own accounts.
        self.limit(accounts=(await self.count(self.tb, "users")) + 1)
        r = await self.b.post("/api/v1/auth/register", json={**body, "username": "conta-do-b"})
        self.assertEqual(r.status_code, 201, r.text)

    async def test_games_quota_on_the_sync(self) -> None:
        key = await self.key(self.ta, self.a)
        bearer = {"Authorization": f"Bearer {key}"}
        have = await self.count(self.ta, "games")
        self.limit(games=have + 1)
        r = await self.a.post("/api/v1/sync/games", json=envelope(meta=META), headers=bearer)
        self.assertEqual(r.status_code, 200, r.text)
        other = {**envelope(meta=META), "game": {"game_id": 777, "game_seed": 5}}
        r = await self.a.post("/api/v1/sync/games", json=other, headers=bearer)
        self.assertEqual((r.status_code, r.json()), (409, {"detail": "quota_exceeded", "quota": "games",
                                                           "limit": have + 1}))
        self.assertEqual(await self.count(self.ta, "games"), have + 1)  # the refused game is not stored
        # A game that is already there is updated, never counted again.
        r = await self.a.post("/api/v1/sync/games", json=envelope(meta={**META, "state": "ended",
                                                                          "ended_at": 1792003000.0}), headers=bearer)
        self.assertEqual(r.status_code, 200, r.text)
        # The stream answers the same body.
        stream = HostStream(self.app, key, f"campo-a.{DOMAIN}")
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        try:
            await stream.send({"type": "games", **other})
            self.assertEqual(await stream.receive(), {"type": "error", "detail": "quota_exceeded", "quota": "games",
                                                      "limit": have + 1})
        finally:
            await stream.close()

    async def test_registrations_quota(self) -> None:
        with tenancy.use(self.ta):
            async with self.app.state.sessionmaker() as db:
                game = ScheduledGame(field_id=self.ta.field_id, title="Aberto", starts_at=hour(48), ends_at=hour(52),
                                     status="published", registration_opens_at=hour(-24),
                                     registration_closes_at=hour(40), teams=["red", "blue"])
                db.add(game)
                await db.commit()
                game_id = game.id
        url = f"/api/v1/fields/{self.ta.field_id}/scheduled-games/{game_id}/registrations"
        self.limit(registrations=(await self.count(self.ta, "game_registrations")) + 1)
        first = await self.auth(self.a, (await self.user(self.ta, None))[1])
        second = await self.auth(self.a, (await self.user(self.ta, None))[1])
        r = await self.a.post(url, json={}, headers=first)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self.a.post(url, json={}, headers=second)
        self.assertEqual((r.status_code, r.json()["detail"], r.json()["quota"]),
                         (409, "quota_exceeded", "registrations"))

    async def test_a_stream_quota(self) -> None:
        key_a = await self.key(self.ta, self.a)
        key_b = await self.key(self.tb, self.b)
        self.limit(streams=1)
        first = HostStream(self.app, key_a, f"campo-a.{DOMAIN}")
        self.assertEqual((await first.open())["type"], "websocket.accept")
        try:
            second = HostStream(self.app, key_a, f"campo-a.{DOMAIN}")
            self.assertEqual((await second.open())["code"], quotas.STREAM_CLOSE)
            await second.close()
            other = HostStream(self.app, key_b, f"campo-b.{DOMAIN}")  # another field's count
            self.assertEqual((await other.open())["type"], "websocket.accept")
            await other.close()
        finally:
            await first.close()
        await asyncio.sleep(0.05)
        again = HostStream(self.app, key_a, f"campo-a.{DOMAIN}")  # room again once the first is gone
        self.assertEqual((await again.open())["type"], "websocket.accept")
        await again.close()

    async def test_a_single_field_server_has_no_quotas(self) -> None:
        self.assertEqual(quotas.limit("games"), 0)  # outside a request: no limits are in force
        with quotas.use({"games": 3}):
            self.assertEqual(quotas.limit("games"), 3)
        self.assertEqual(quotas.limit("games"), 0)


class ImportQuotaTests(ImportCase):
    """The registration import honours the registrations' quota row by row (the limits are read from the context
    the tenant middleware sets; here the test sets it, on a single-field database)."""

    async def test_rows_past_the_quota_are_refused_with_a_code(self) -> None:
        game = await self.game(federation="optional")
        with quotas.use({"registrations": 2}):
            preview = await self.run_import(game, CSV, dry_run=True, confirmed=False)
            self.assertEqual(preview["counts"]["created"], 2)
            out = await self.run_import(game, CSV)
        self.assertEqual([(r["result"], r.get("code")) for r in out["results"]],
                         [("created", None), ("created", None), ("refused", "quota_exceeded")])
        self.assertEqual(len(await self.regs(game)), 2)
        with quotas.use({"registrations": 2}):  # the same file again: the two are unchanged, nothing new fits
            again = await self.run_import(game, CSV)
        self.assertEqual([r["result"] for r in again["results"]], ["unchanged", "unchanged", "refused"])


class ExportTests(LimitCase):
    async def test_a_hosted_export_holds_the_whole_tenant_and_nothing_of_another(self) -> None:
        key_a = await self.key(self.ta, self.a)
        await self.synced_game(self.ta, self.a, key_a)
        await self.synced_game(self.tb, self.b, await self.key(self.tb, self.b))
        await self.user(self.ta, "ana-sem-papel")
        await self.user(self.tb, "bruno-do-b")
        _, captain, _ = await self.user(self.ta, "capitao-a")
        r = await self.a.post("/api/v1/clubs", headers=await self.auth(self.a, captain),
                              json={"name": "Lobos A", "short_name": "Lobos", "slug": "lobos-a"})
        self.assertEqual(r.status_code, 201, r.text)
        admin_a = await self.staff(self.ta, self.a, "admin")
        r = await self.a.get(f"/api/v1/fields/{self.ta.field_id}/export", headers=admin_a)
        self.assertEqual(r.status_code, 200, r.text)
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            files = {n: zf.read(n) for n in zf.namelist()}
        manifest = json.loads(files["manifest.json"])
        self.assertEqual(manifest["mode"], "hosted")
        by_name = {d["name"]: d for d in manifest["datasets"]}
        self.assertIn("clubs", by_name)  # a tenant's clubs are its own
        for table in ("games", "users", "clubs", "game_events"):
            self.assertEqual(by_name[table]["rows"], await self.count(self.ta, table), table)
        # The export's own audit row is made once the archive is ready, so it is not in the archive.
        self.assertEqual(by_name["audit_log"]["rows"], await self.count(self.ta, "audit_log") - 1)
        users = {json.loads(line)["username"] for line in files["data/users.jsonl"].decode().splitlines()}
        self.assertIn("ana-sem-papel", users)  # an account of this field, with or without a role
        blob = b"\n".join(files.values())
        for marker in (b"bruno-do-b", str(self.tb.field_id).encode(), b"campo-b", b"Campo B"):
            self.assertNotIn(marker, blob, marker)
        for marker in (b"password_hash\":", b"totp_secret_enc\":", b"key_sha256\":", b"\"ip_address\":"):
            self.assertNotIn(marker, b"\n".join(v for n, v in files.items() if n.startswith("data/")))
        audit = await self.sql(self.ta, "SELECT details FROM audit_log WHERE action = 'field_export'")
        self.assertEqual(json.loads(audit[-1][0])["sha256"], r.headers["x-content-sha256"])
        self.assertEqual(await self.sql(self.tb, "SELECT 1 FROM audit_log WHERE action = 'field_export'"), [])

    async def test_a_fields_admin_cannot_export_another_field(self) -> None:
        admin_b = await self.staff(self.tb, self.b, "admin")
        for client in (self.a, self.b):
            r = await client.get(f"/api/v1/fields/{self.ta.field_id}/export", headers=admin_b)
            self.assertIn(r.status_code, (401, 403), r.text)  # B's token at A is no session of A's; at B no role
        admin_sa = await self.staff(self.tb, self.b, server_admin=True)
        r = await self.b.get(f"/api/v1/fields/{self.ta.field_id}/export", headers=admin_sa)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "field_not_found"))  # not in B's schema

    async def test_the_cooldown_is_per_field(self) -> None:
        self.app.state.settings = dataclasses.replace(self.app.state.settings, export_min_interval_s=300)
        admin_a = await self.staff(self.ta, self.a, "admin")
        admin_b = await self.staff(self.tb, self.b, "admin")
        url_a = f"/api/v1/fields/{self.ta.field_id}/export"
        self.assertEqual((await self.a.get(url_a, headers=admin_a)).status_code, 200)
        self.assertEqual((await self.a.get(url_a, headers=admin_a)).status_code, 429)
        self.assertEqual((await self.b.get(f"/api/v1/fields/{self.tb.field_id}/export",
                                           headers=admin_b)).status_code, 200)


class WatchCase(LimitCase):
    async def open_stream(self, tenant: tenancy.Tenant, client: Any, remote: bool = True) -> HostStream:
        key = await self.key(tenant, client)
        stream = HostStream(self.app, key, f"{tenant.slug}.{DOMAIN}")
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        if remote:
            await stream.send({"type": "hello", "sync_version": 1, "controller": CONTROLLER, "remote_gm": True})
            self.assertEqual((await stream.receive())["type"], "hello.ack")
            await stream.send({"type": "live", "sync_version": 1, "controller": CONTROLLER, "live": LIVE})
            await asyncio.sleep(0.05)
        return stream

    async def new_field(self, slug: str) -> tuple[tenancy.Tenant, Any]:
        tenant = await asyncio.to_thread(hosted.create_tenant, self.hub.owner_url, slug, slug.title(), "outdoor",
                                         "Europe/Lisbon", self.hub.app_role, "test:operator")
        return tenant, self.client(slug)

    async def drop(self, slug: str) -> None:
        await hosted.delete_tenant(self.hub.owner_url, slug, slug, "test: the contract ended", actor="test:operator")


class WatchTests(WatchCase):
    watch_s = 0.1

    async def test_deleting_a_field_closes_its_open_sockets_at_once(self) -> None:
        tc, c = await self.new_field("campo-w1")
        stream = await self.open_stream(tc, c)
        other = await self.open_stream(self.ta, self.a)  # a field that stays
        try:
            self.assertEqual(len(self.app.state.remote_hub.tenants()), 2)
            await self.drop("campo-w1")
            self.assertEqual(await stream.receive(timeout=3), {"type": "closed", "code": 4404})
            await asyncio.wait_for(stream.task, 3)  # the handler ended: no socket is left to fail at its next message
            self.assertEqual(self.app.state.remote_hub.tenants(), {self.ta.schema})
            self.assertEqual(self.app.state.tenant_watch.count(tc.schema, tc.field_id), 0)
            await other.send({"type": "ping"})  # the other field's socket is untouched
            self.assertEqual(await other.receive(), {"type": "pong"})
        finally:
            await other.close()
            await stream.close()

    async def test_a_command_waiting_on_a_deleted_fields_controller_fails_at_once(self) -> None:
        tc, c = await self.new_field("campo-w2")
        stream = await self.open_stream(tc, c)
        gm = await self.staff(tc, c, "gm")
        try:
            post = asyncio.create_task(c.post(f"/api/v1/fields/{tc.field_id}/remote-gm/commands", headers=gm,
                                              json={"game": {"game_id": 4242, "game_seed": 3735928559},
                                                    "command": "pause"}))
            self.assertEqual((await stream.receive())["type"], "command")
            await asyncio.sleep(0.05)
            await self.drop("campo-w2")
            done, _ = await asyncio.wait({post}, timeout=3)  # not the 10 s timeout
            self.assertEqual(len(done), 1)
            # The request ended (409 controller_offline, or an error because the schema went under it): the command
            # did not wait for an answer that cannot come.
            if post.exception() is None:
                self.assertEqual(post.result().status_code, 409)
        finally:
            await stream.close()

    async def test_suspending_closes_with_another_code_and_resuming_serves_again(self) -> None:
        tc, c = await self.new_field("campo-w3")
        stream = await self.open_stream(tc, c, remote=False)
        try:
            await hosted.set_status(self.hub.owner_url, "campo-w3", "suspended", "unpaid", actor="test:operator")
            self.assertEqual(await stream.receive(timeout=3), {"type": "closed", "code": 4403})
            await hosted.set_status(self.hub.owner_url, "campo-w3", "active", "paid", actor="test:operator")
            again = await self.open_stream(tc, c, remote=False)
            await again.send({"type": "ping"})
            self.assertEqual(await again.receive(), {"type": "pong"})
            await again.close()
        finally:
            await stream.close()
            await self.drop("campo-w3")

    async def test_the_watch_survives_a_registry_it_cannot_read(self) -> None:
        stream = await self.open_stream(self.ta, self.a, remote=False)
        try:
            watch = self.app.state.tenant_watch
            before = watch.sweeps
            with unittest.mock.patch.object(type(watch), "sweep", side_effect=RuntimeError("database away")):
                await asyncio.sleep(0.35)
            await asyncio.sleep(0.35)  # patched out: the loop went on and sweeps again
            self.assertGreater(watch.sweeps, before)
        finally:
            await stream.close()


class SweepTests(WatchCase):
    """One sweep by hand, with the periodic one out of the way."""

    async def test_a_field_made_again_under_the_same_name_is_another_field(self) -> None:
        tc, c = await self.new_field("campo-w4")
        stream = await self.open_stream(tc, c)
        try:
            await self.drop("campo-w4")
            await self.new_field("campo-w4")  # the registry has the schema again, with a new field id
            closed = await self.app.state.tenant_watch.sweep(self.app.state.engine, self.app.state.remote_hub, None)
            self.assertEqual(closed, 2)  # the socket and its remote GM link
            self.assertEqual(await stream.receive(timeout=3), {"type": "closed", "code": 4404})
            self.assertEqual(self.app.state.remote_hub.tenants(), set())
        finally:
            await stream.close()
            await self.drop("campo-w4")

    async def test_nothing_open_reads_nothing(self) -> None:
        self.assertEqual(await self.app.state.tenant_watch.sweep(self.app.state.engine, self.app.state.remote_hub,
                                                                 None), 0)

    async def test_an_active_field_keeps_its_sockets(self) -> None:
        stream = await self.open_stream(self.ta, self.a)
        try:
            closed = await self.app.state.tenant_watch.sweep(self.app.state.engine, self.app.state.remote_hub, None)
            self.assertEqual(closed, 0)
            await stream.send({"type": "ping"})
            self.assertEqual(await stream.receive(), {"type": "pong"})
        finally:
            await stream.close()


if __name__ == "__main__":
    unittest.main()
