# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Game history shared across the fields of a hosted hub, by each field's opt-in (decisions HUBH-*; the maintainer's
decision of 2026-11-04).

A hub of three fields: ``campo-a`` and ``campo-b`` opt in, ``campo-c`` never does. Isolation is the acceptance test:
field C's games never reach the hub's tables, its staff read nothing (reciprocity), and as field C's own database role
nothing of A or B can be read or written except through the two functions, which answer C nothing. Tried besides: the
switch is off by default and only the field's admin changes it; what is shared is game-level only (no player id, no
event, no game or team name); turning it off withdraws every game the field shared; a suspended field drops out; the
retention purge takes a game the field no longer holds out of the hub, and nothing older than 365 days is shown; the
hub operator's ``hosted shared-history`` reads what the opted-in fields share, and ``hosted delete`` takes a field's
rows with it; ``hosted check`` passes with the new tables.

    python3 tools/docker_server.py test tests.test_hub_history
"""

from __future__ import annotations

import asyncio
import io
import json
import secrets
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import asyncpg
import httpx2

from atalaia_server import cli, hosted, personal_data, tenancy

from .base import AppTestCase
from .test_tenants import CONTROLLER, HubCase, as_field, connect, connect_driver_safe

PLAYER = "p-sekret-4711"
GAME_NAME = "Aniversario do Rui"
TEAM_NAME = "Equipa do Pedro"


class HistoryCase(HubCase):
    tc: tenancy.Tenant

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        try:
            cls.tc = hosted.create_tenant(cls.hub.owner_url, "campo-c", "Campo C", app_role=cls.hub.app_role,
                                          actor="test:operator")
        except BaseException:
            cls.hub.drop()
            raise

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.c = self.client("campo-c")
        self.admins: dict[str, dict[str, str]] = {}
        for client, tenant in ((self.a, self.ta), (self.b, self.tb), (self.c, self.tc)):
            self.admins[tenant.slug] = await self.staff(tenant, client, "admin")
        self.next_game = 100 + secrets.randbelow(60000)

    def side(self, slug: str) -> tuple[httpx2.AsyncClient, tenancy.Tenant]:
        return {"campo-a": (self.a, self.ta), "campo-b": (self.b, self.tb), "campo-c": (self.c, self.tc)}[slug]

    async def switch(self, slug: str, on: bool, auth: Optional[dict[str, str]] = None) -> httpx2.Response:
        client, tenant = self.side(slug)
        return await client.put(f"/api/v1/fields/{tenant.field_id}/hub-history/settings", json={"enabled": on},
                                headers=auth or self.admins[slug])

    async def view(self, slug: str, auth: Optional[dict[str, str]] = None, **params: Any) -> httpx2.Response:
        client, tenant = self.side(slug)
        return await client.get(f"/api/v1/fields/{tenant.field_id}/hub-history", params=params,
                                headers=auth or self.admins[slug])

    async def ended_game(self, slug: str, red: int = 10, blue: int = 5, mode: str = "org.atalaia.domination",
                         end: bool = True) -> int:
        """One game synced by the field's controller: a team display name, an event naming a player, the scores and
        (``end``) its game.end. Returns its radio game id."""
        client, tenant = self.side(slug)
        bearer = {"Authorization": f"Bearer {await self.key(tenant, client)}"}
        self.next_game += 1
        game = {"game_id": self.next_game, "game_seed": 7000 + self.next_game}
        envelope = {"sync_version": 1, "controller": CONTROLLER, "game": game}
        meta = {"name": GAME_NAME, "mode_id": mode, "teams": ["red", "blue"],
                "team_info": {"red": {"display_name": TEAM_NAME}}, "state": "running", "created_at": 1792000000.0,
                "started_at": 1792000100.0}
        r = await client.post("/api/v1/sync/games", json={**envelope, "meta": meta}, headers=bearer)
        self.assertEqual(r.status_code, 200, r.text)
        r = await client.post("/api/v1/sync/scores", json={**envelope, "counters": {"node-3": {"red": red, "blue": blue}}},
                              headers=bearer)
        self.assertEqual(r.status_code, 200, r.text)
        events = [{"id": 1, "node": 3, "seq": 1, "t": 1000, "type": "zone.captured", "team": "red", "prio": "normal",
                   "data": {"zone": "alpha", "player": PLAYER}}]
        if end:
            events.append({"id": 2, "node": 3, "seq": 2, "t": 2000, "type": "game.end", "prio": "normal", "data": {}})
        r = await client.post("/api/v1/sync/events", json={**envelope, "after_id": 0, "events": events}, headers=bearer)
        self.assertEqual(r.status_code, 200, r.text)
        return self.next_game

    async def hubq(self, query: str, *args: Any) -> list[asyncpg.Record]:
        conn = await connect(self.hub.owner_url)
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()

    async def shared_rows(self, tenant: tenancy.Tenant) -> list[asyncpg.Record]:
        return await self.hubq("SELECT * FROM public.atalaia_hub_games WHERE tenant = $1", tenant.schema)

    async def reset(self) -> None:
        """Every field off (each test starts from the default)."""
        for slug in ("campo-a", "campo-b", "campo-c"):
            r = await self.switch(slug, False)
            self.assertEqual(r.status_code, 200, r.text)


class OptInTests(HistoryCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.reset()

    async def test_off_by_default_and_nothing_crosses(self) -> None:
        await self.ended_game("campo-a")
        r = await self.a.get(f"/api/v1/fields/{self.ta.field_id}/hub-history/settings", headers=self.admins["campo-a"])
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["enabled"], r.json()["since"], r.json()["member"], r.json()["shared_games"]),
                         (False, None, False, 0))
        self.assertEqual(await self.shared_rows(self.ta), [])
        self.assertEqual(await self.hubq("SELECT * FROM public.atalaia_hub_history_members WHERE tenant = $1",
                                         self.ta.schema), [])
        r = await self.view("campo-a")
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "history_sharing_off"))

    async def test_only_the_admin_turns_it_on_and_it_is_audited(self) -> None:
        gm = await self.staff(self.ta, self.a, "gm")
        marshal = await self.staff(self.ta, self.a, "marshal")
        player = await self.staff(self.ta, self.a, "player")
        for auth in (gm, marshal, player):
            r = await self.switch("campo-a", True, auth)
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "role_required"))
        r = await self.a.get(f"/api/v1/fields/{self.ta.field_id}/hub-history/settings", headers=player)
        self.assertEqual(r.status_code, 403)  # a player is no staff
        r = await self.a.get(f"/api/v1/fields/{self.ta.field_id}/hub-history/settings", headers=gm)
        self.assertEqual(r.status_code, 200)
        r = await self.a.put(f"/api/v1/fields/{self.ta.field_id}/hub-history/settings", json={"enabled": "yes"},
                             headers=self.admins["campo-a"])
        self.assertEqual(r.status_code, 422)  # a strict boolean
        r = await self.switch("campo-a", True)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["enabled"] and r.json()["member"] and r.json()["since"])
        rows = await self.sql(self.ta, "SELECT details FROM audit_log WHERE action = 'hub_history_sharing' "
                                       "ORDER BY created_at DESC LIMIT 1")
        self.assertEqual(json.loads(rows[0]["details"]) if isinstance(rows[0]["details"], str) else rows[0]["details"],
                         {"enabled": True})
        # Another field's id through this field's host: no role there, as for every other field id (S21-*).
        r = await self.a.get(f"/api/v1/fields/{self.tb.field_id}/hub-history", headers=self.admins["campo-a"])
        self.assertEqual(r.status_code, 403)

    async def test_game_level_data_only(self) -> None:
        await self.switch("campo-a", True)
        await self.switch("campo-b", True)
        await self.ended_game("campo-b", red=42, blue=17)
        r = await self.view("campo-a")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        theirs = [g for g in body["games"] if not g["own"] and g["teams"][0]["score"] == 42]
        self.assertEqual(len(theirs), 1, body)
        game = theirs[0]
        self.assertEqual(set(game), {"field_name", "own", "mode_id", "started_at", "ended_at", "teams", "winner"})
        self.assertEqual((game["field_name"], game["mode_id"], game["winner"]), ("Campo B", "org.atalaia.domination", "red"))
        self.assertEqual(game["teams"], [{"team": "red", "score": 42}, {"team": "blue", "score": 17}])
        self.assertIsNotNone(game["started_at"])
        self.assertIsNotNone(game["ended_at"])
        text = r.text
        for secret in (PLAYER, GAME_NAME, TEAM_NAME, str(self.tb.field_id), self.tb.schema):
            self.assertNotIn(secret, text)
        stored = json.dumps([dict(x) for x in await self.shared_rows(self.tb)], default=str)
        for secret in (PLAYER, GAME_NAME, TEAM_NAME):
            self.assertNotIn(secret, stored)
        columns = {r["column_name"] for r in await self.hubq(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
            "AND table_name = 'atalaia_hub_games'")}
        self.assertEqual(columns, {"tenant", "game_ref", "mode_id", "started_at", "ended_at", "teams", "winner",
                                   "published_at"})
        self.assertEqual({f["field_name"] for f in body["fields"]}, {"Campo A", "Campo B"})

    async def test_a_live_game_is_not_shared_until_it_ends(self) -> None:
        await self.switch("campo-b", True)
        before = len(await self.shared_rows(self.tb))
        await self.ended_game("campo-b", end=False)
        self.assertEqual(len(await self.shared_rows(self.tb)), before)
        await self.ended_game("campo-b")
        self.assertEqual(len(await self.shared_rows(self.tb)), before + 1)

    async def test_turning_it_on_shares_the_games_the_field_holds(self) -> None:
        await self.ended_game("campo-b")
        await self.ended_game("campo-b")
        r = await self.switch("campo-b", True)
        self.assertGreaterEqual(r.json()["shared_games"], 2)
        self.assertEqual(len(await self.shared_rows(self.tb)), r.json()["shared_games"])


class IsolationTests(HistoryCase):
    """Field C never opted in: nothing of it reaches the hub, and it reads nothing of the others."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.reset()
        await self.switch("campo-a", True)
        await self.switch("campo-b", True)
        await self.ended_game("campo-a")
        await self.ended_game("campo-b")
        await self.ended_game("campo-c", red=99, blue=98)

    async def test_a_field_that_never_opted_in_never_leaks(self) -> None:
        self.assertEqual(await self.shared_rows(self.tc), [])
        self.assertEqual(await self.hubq("SELECT * FROM public.atalaia_hub_history_members WHERE tenant = $1",
                                         self.tc.schema), [])
        for slug in ("campo-a", "campo-b"):
            r = await self.view(slug)
            self.assertEqual(r.status_code, 200, r.text)
            self.assertNotIn("Campo C", r.text)
            self.assertFalse([g for g in r.json()["games"] if g["teams"][0]["score"] == 99])
            self.assertEqual({g["field_name"] for g in r.json()["games"]}, {"Campo A", "Campo B"})
        # The hub operator sees only what was shared: no row of C at all.
        found = await hosted.shared_history(self.hub.owner_url, actor="test:operator")
        self.assertEqual({f["slug"] for f in found["fields"]}, {"campo-a", "campo-b"})
        self.assertNotIn("campo-c", {g["slug"] for g in found["games"]})

    async def test_reciprocity_a_field_that_does_not_share_reads_nothing(self) -> None:
        gm_c = await self.staff(self.tc, self.c, "gm")
        for auth in (self.admins["campo-c"], gm_c):
            r = await self.view("campo-c", auth)
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "history_sharing_off"))
            self.assertNotIn("Campo A", r.text)

    async def test_as_field_c_role_nothing_of_the_others_can_be_read_or_written(self) -> None:
        conn = await connect_driver_safe(self.hub.app_url)
        try:
            async with conn.transaction():
                await as_field(conn, self.tc)
                self.assertEqual(await conn.fetchval("SELECT count(*) FROM public.atalaia_hub_games"), 0)
                self.assertEqual(await conn.fetchval("SELECT count(*) FROM public.atalaia_hub_history_members"), 0)
                self.assertEqual(await conn.fetch("SELECT * FROM public.atalaia_hub_history_read(NULL, NULL, 200)"), [])
                self.assertEqual(await conn.fetch("SELECT * FROM public.atalaia_hub_history_fields()"), [])
                # Writing A's rows, or claiming to be A: the policy refuses (the caller's field is its role's).
                self.assertEqual(await conn.execute("DELETE FROM public.atalaia_hub_games WHERE tenant = $1",
                                                    self.ta.schema), "DELETE 0")
                self.assertEqual(await conn.execute("UPDATE public.atalaia_hub_history_members SET field_name = 'x' "
                                                    "WHERE tenant = $1", self.ta.schema), "UPDATE 0")
                with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                    async with conn.transaction():
                        await conn.execute("INSERT INTO public.atalaia_hub_history_members (tenant, field_name) "
                                           "VALUES ($1, 'Campo A falso')", self.ta.schema)
                with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                    async with conn.transaction():
                        await conn.execute("SELECT set_config('atalaia.tenant', $1, true)", self.ta.schema)
            # As field A's role the policy shows A's own rows only, never B's.
            async with conn.transaction():
                await as_field(conn, self.ta)
                tenants = {r["tenant"] for r in await conn.fetch("SELECT tenant FROM public.atalaia_hub_games")}
                self.assertEqual(tenants, {self.ta.schema})
                read = await conn.fetch("SELECT field_name FROM public.atalaia_hub_history_read(NULL, NULL, 200)")
                self.assertEqual({r["field_name"] for r in read}, {"Campo A", "Campo B"})
        finally:
            await conn.close()
        # The server's login role, outside any field's role: nothing at all.
        conn = await connect(self.hub.app_url)
        try:
            for statement in ("SELECT count(*) FROM public.atalaia_hub_games",
                              "SELECT count(*) FROM public.atalaia_hub_history_members",
                              "SELECT * FROM public.atalaia_hub_history_read(NULL, NULL, 10)",
                              "SELECT * FROM public.atalaia_hub_history_fields()"):
                with self.subTest(statement=statement):
                    with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                        await conn.fetch(statement)
        finally:
            await conn.close()

    async def test_the_hub_check_passes_with_the_new_tables(self) -> None:
        report = await hosted.check_hub(self.hub.owner_url, self.hub.app_role)
        self.assertEqual(report.problems, [])


class WithdrawalTests(HistoryCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.reset()
        await self.switch("campo-a", True)
        await self.switch("campo-b", True)
        await self.ended_game("campo-a")
        await self.ended_game("campo-b")

    async def test_turning_it_off_withdraws_what_was_shared(self) -> None:
        self.assertTrue(await self.shared_rows(self.tb))
        r = await self.switch("campo-b", False)
        self.assertEqual((r.json()["enabled"], r.json()["since"], r.json()["member"], r.json()["shared_games"]),
                         (False, None, False, 0))
        self.assertEqual(await self.shared_rows(self.tb), [])
        r = await self.view("campo-a")
        self.assertEqual({g["field_name"] for g in r.json()["games"]}, {"Campo A"})
        self.assertEqual({f["field_name"] for f in r.json()["fields"]}, {"Campo A"})
        r = await self.view("campo-b")
        self.assertEqual(r.status_code, 403)  # and B no longer reads the others'
        # A game B ends while off stays at B.
        await self.ended_game("campo-b")
        self.assertEqual(await self.shared_rows(self.tb), [])

    async def test_a_suspended_field_drops_out_of_the_view(self) -> None:
        await hosted.set_status(self.hub.owner_url, "campo-b", "suspended", "test", "test:operator")
        try:
            r = await self.view("campo-a")
            self.assertEqual({g["field_name"] for g in r.json()["games"]}, {"Campo A"})
            self.assertNotIn("Campo B", {f["field_name"] for f in r.json()["fields"]})
        finally:
            await hosted.set_status(self.hub.owner_url, "campo-b", "active", "test", "test:operator")

    async def test_the_purge_takes_out_what_the_field_no_longer_holds(self) -> None:
        self.assertTrue(await self.shared_rows(self.tb))
        await self.sql(self.tb, "DELETE FROM games")  # gone at the field (as past its retention, results included)
        with tenancy.use(self.tb):
            async with self.app.state.sessionmaker() as db:
                await personal_data.purge(db)
        self.assertEqual(await self.shared_rows(self.tb), [])
        self.assertTrue(await self.hubq("SELECT 1 FROM public.atalaia_hub_history_members WHERE tenant = $1",
                                        self.tb.schema))  # still sharing, nothing to share

    async def test_nothing_older_than_365_days_is_shown(self) -> None:
        old = datetime.now(timezone.utc) - timedelta(days=366)
        await self.hubq("UPDATE public.atalaia_hub_games SET ended_at = $2 WHERE tenant = $1", self.tb.schema, old)
        r = await self.view("campo-a")
        self.assertEqual({g["field_name"] for g in r.json()["games"]}, {"Campo A"})
        self.assertEqual(next(f["games"] for f in r.json()["fields"] if f["field_name"] == "Campo B"), 0)

    async def test_the_mode_filter_and_paging(self) -> None:
        await self.ended_game("campo-b", mode="org.atalaia.bomb")
        r = await self.view("campo-a", mode="org.atalaia.bomb")
        self.assertEqual([g["mode_id"] for g in r.json()["games"]], ["org.atalaia.bomb"])
        r = await self.view("campo-a", limit=1)
        self.assertEqual(len(r.json()["games"]), 1)
        self.assertIsNotNone(r.json()["next_before"])
        r = await self.view("campo-a", before="not a time")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "before_invalid"))


class OperatorTests(HistoryCase):
    async def test_shared_history_command_and_delete(self) -> None:
        await self.reset()
        await self.switch("campo-a", True)
        await self.ended_game("campo-a")
        found = await hosted.shared_history(self.hub.owner_url, "campo-a", 10, actor="test:operator")
        self.assertEqual([f["slug"] for f in found["fields"]], ["campo-a"])
        self.assertEqual({g["slug"] for g in found["games"]}, {"campo-a"})
        self.assertNotIn(PLAYER, json.dumps(found, default=str))
        audit = await self.hubq("SELECT details FROM public.atalaia_hub_audit WHERE action = 'hub_history_read' "
                                "ORDER BY id DESC LIMIT 1")
        self.assertTrue(audit)
        with self.assertRaises(hosted.HostedError):
            await hosted.shared_history(self.hub.owner_url, limit=0)
        # A field that shares and is deleted takes its shared rows with it.
        td = await asyncio.to_thread(hosted.create_tenant, self.hub.owner_url, "campo-d", "Campo D",
                                     app_role=self.hub.app_role, actor="test:operator")
        d = self.client("campo-d")
        admin_d = await self.staff(td, d, "admin")
        r = await d.put(f"/api/v1/fields/{td.field_id}/hub-history/settings", json={"enabled": True}, headers=admin_d)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(await self.hubq("SELECT 1 FROM public.atalaia_hub_history_members WHERE tenant = $1", td.schema))
        counts = await hosted.delete_tenant(self.hub.owner_url, "campo-d", "campo-d", "test", "test:operator")
        self.assertIn("hub_games", counts)
        self.assertEqual(await self.hubq("SELECT 1 FROM public.atalaia_hub_history_members WHERE tenant = $1",
                                         td.schema), [])


class SingleFieldTests(AppTestCase):
    async def test_a_single_field_server_has_no_shared_history(self) -> None:
        field_id = (await self.fetch("INSERT INTO fields (name, slug) VALUES ('Arena', 'arena') RETURNING id"))[0][0]
        _, name, secret = await self.make_user(server_admin=True)
        auth = await self.auth(name, secret=secret)
        for method, path in (("GET", f"/api/v1/fields/{field_id}/hub-history"),
                             ("GET", f"/api/v1/fields/{field_id}/hub-history/settings"),
                             ("PUT", f"/api/v1/fields/{field_id}/hub-history/settings")):
            with self.subTest(path=path, method=method):
                r = await self.client.request(method, path, headers=auth,
                                              json={"enabled": True} if method == "PUT" else None)
                self.assertEqual((r.status_code, r.json()["detail"]), (404, "not_hosted"))
        rows = await self.fetch("SELECT history_sharing_enabled FROM fields WHERE id = $1", field_id)
        self.assertFalse(rows[0][0])
        # The staff pages' navigation has no such section on a single-field server.
        r = await self.client.get(f"/staff/fields/{field_id}/history")
        self.assertNotIn('data-section="hubhistory"', r.text)


class OperatorOutputTests(unittest.TestCase):
    def test_the_command_prints_fields_then_games(self) -> None:
        when = datetime(2026, 11, 1, 11, 0, tzinfo=timezone.utc)
        found = {"fields": [{"slug": "campo-a", "status": "active", "field_name": "Campo A", "since": when, "games": 1}],
                 "games": [{"slug": "campo-a", "field_name": "Campo A", "mode_id": "org.atalaia.domination",
                            "started_at": when, "ended_at": when, "winner": "red",
                            "teams": [{"team": "red", "score": 4}, {"team": "blue", "score": 2}]}]}
        out = io.StringIO()
        cli._print_shared_history(found, False, out)
        self.assertIn("campo-a\tactive\tCampo A\tsharing since 2026-11-01T11:00:00+00:00\t1 game", out.getvalue())
        self.assertIn("org.atalaia.domination\tred 4, blue 2\twinner red", out.getvalue())
        out = io.StringIO()
        cli._print_shared_history(found, True, out)
        self.assertEqual(json.loads(out.getvalue())["games"][0]["teams"][0], {"team": "red", "score": 4})
        out = io.StringIO()
        cli._print_shared_history({"fields": [], "games": []}, False, out)
        self.assertIn("No field shares", out.getvalue())

