# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chrono sharing across the tenants of a hosted hub (SVX-2; ADR-P4-4's amendment of 2026-10-28).

A person with an account at two hosted fields links them with a code, consents at each field, and the fields (when
both switch sharing on) show each other's signed records of them, through the hub's tables in ``public`` and
one SECURITY DEFINER function, never a query across schemas. Tried here: the code (once, expiry, the wrong
field), every condition of the consent-gated view (the person's consent at either field, either field's switch,
the link, a suspended field), what is published by the new reading path, the erasures, and, as the server's own
database role, that it can read and write only its own tenant's rows in the hub's tables and that the function
answers nobody else.

    python3 tools/docker_server.py test tests.test_hub_share
"""

from __future__ import annotations

import asyncio
import base64
import secrets
import unittest
import uuid
from typing import Any, Optional

import asyncpg

from atalaia_controller import chrono
from atalaia_server import chrono_registry, hosted, sharing_terms, tenancy
from atalaia_server.models import FieldPlayerId

from .base import PASSWORD
from .test_chrono import Marshal, field_body, reading
from .test_tenants import HubCase, as_field, connect, connect_driver_safe


class ShareCase(HubCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.admin_a = await self.staff(self.ta, self.a, "admin")
        self.admin_b = await self.staff(self.tb, self.b, "admin")
        self.gm_a = await self.staff(self.ta, self.a, "gm")
        for client, tenant, admin in ((self.a, self.ta, self.admin_a), (self.b, self.tb, self.admin_b)):
            r = await client.patch(f"/api/v1/fields/{tenant.field_id}", json={"chrono_sharing_enabled": True,
                                                     "sharing_terms_accepted": sharing_terms.current()}, headers=admin)
            self.assertEqual(r.status_code, 200, r.text)
        self.key_b = await self.key(self.tb, self.b)
        self.marshal = Marshal()
        r = await self.b.post("/api/v1/sync/marshals", json=field_body(marshals=[self.marshal.entry()]),
                              headers={"Authorization": f"Bearer {self.key_b}"})
        self.assertEqual(r.status_code, 200, r.text)

    async def person(self) -> "Person":
        """One person with an account at each field, each holding a player id there (not linked yet)."""
        tag = secrets.token_hex(4)
        p = Person()
        for attr, tenant, client in (("a", self.ta, self.a), ("b", self.tb, self.b)):
            user_id, name, _ = await self.user(tenant, f"ana-{attr}-{tag}")
            pid = f"p-{secrets.token_hex(6)}"
            with tenancy.use(tenant):
                async with self.app.state.sessionmaker() as db:
                    db.add(FieldPlayerId(field_id=tenant.field_id, player_id=pid, user_id=user_id))
                    await db.commit()
            setattr(p, f"user_{attr}", user_id)
            setattr(p, f"pid_{attr}", pid)
            setattr(p, f"auth_{attr}", await self.auth(client, name))
        return p

    async def link(self, p: "Person") -> None:
        r = await self.a.post("/api/v1/me/hub-share/code", headers=p.auth_a)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self.b.post("/api/v1/me/hub-share/link", json={"code": r.json()["code"]}, headers=p.auth_b)
        self.assertEqual(r.status_code, 200, r.text)

    async def consent(self, p: "Person", side: str, give: bool = True) -> None:
        client, tenant, auth = (self.a, self.ta, p.auth_a) if side == "a" else (self.b, self.tb, p.auth_b)
        url = f"/api/v1/me/consents/chrono-sharing/{tenant.field_id}"
        r = await (client.put(url, headers=auth) if give else client.delete(url, headers=auth))
        self.assertIn(r.status_code, (200, 201, 204), r.text)

    async def b_reading(self, p: "Person", **extra: Any) -> dict[str, Any]:
        record = self.marshal.record(player=p.pid_b, **extra)
        r = await self.b.post("/api/v1/sync/chrono", json=field_body(readings=[reading(record)]),
                              headers={"Authorization": f"Bearer {self.key_b}"})
        self.assertEqual((r.status_code, r.json()["accepted"]), (200, 1), r.text)
        return record

    async def shared_at_a(self, p: "Person") -> list[dict[str, Any]]:
        r = await self.a.get(f"/api/v1/fields/{self.ta.field_id}/chrono/players/{p.pid_a}", headers=self.gm_a)
        self.assertEqual(r.status_code, 200, r.text)
        return list(r.json()["shared"])

    async def switch(self, side: str, on: bool) -> None:
        client, tenant, admin = (self.a, self.ta, self.admin_a) if side == "a" else (self.b, self.tb, self.admin_b)
        r = await client.patch(f"/api/v1/fields/{tenant.field_id}", json={"chrono_sharing_enabled": on,
                                                                              "sharing_terms_accepted": sharing_terms.current()},
                               headers=admin)
        self.assertEqual(r.status_code, 200, r.text)

    async def person_id(self, p: "Person") -> uuid.UUID:
        return uuid.UUID(str((await self.sql(self.tb, "SELECT person_id FROM hub_share_links WHERE user_id = $1",
                                             p.user_b))[0][0]))

    async def count_published(self, p: "Person") -> int:
        """How many of the person's records field B has in the hub."""
        return int((await self.hubq("SELECT count(*) AS n FROM public.atalaia_share_records WHERE person_id = $1",
                                   await self.person_id(p)))[0]["n"])

    async def hubq(self, query: str, *args: Any) -> list[asyncpg.Record]:
        conn = await connect(self.hub.owner_url)
        try:
            return await conn.fetch(query, *args)
        finally:
            await conn.close()


class Person:
    user_a: uuid.UUID
    user_b: uuid.UUID
    pid_a: str
    pid_b: str
    auth_a: dict[str, str]
    auth_b: dict[str, str]


class SharingTests(ShareCase):
    async def test_every_condition_of_the_view(self) -> None:
        p = await self.person()
        record = await self.b_reading(p)
        await self.link(p)
        person = await self.person_id(p)
        self.assertEqual(await self.shared_at_a(p), [])  # linked, nobody consented
        await self.consent(p, "b")
        self.assertEqual(await self.shared_at_a(p), [])  # not for this field
        await self.consent(p, "a")
        shared = await self.shared_at_a(p)
        self.assertEqual([s["reading_id"] for s in shared], [record["reading_id"]])
        self.assertEqual((shared[0]["field"], shared[0]["public_key"]), ("Campo B", self.marshal.public))
        chrono.parse(shared[0]["record_json"], base64.b64decode(shared[0]["public_key"]))  # checkable at A
        # The person's consent, at either field, ends it at once.
        await self.consent(p, "b", give=False)
        self.assertEqual(await self.shared_at_a(p), [])
        await self.consent(p, "b")
        self.assertEqual(len(await self.shared_at_a(p)), 1)
        await self.consent(p, "a", give=False)
        self.assertEqual(await self.shared_at_a(p), [])
        await self.consent(p, "a")
        # ... and so does either field's switch.
        for side in ("a", "b"):
            await self.switch(side, False)
            self.assertEqual(await self.shared_at_a(p), [], side)
            await self.switch(side, True)
            self.assertEqual(len(await self.shared_at_a(p)), 1, side)
        # A suspended field is not read.
        await hosted.set_status(self.hub.owner_url, "campo-b", "suspended", "test", actor="test:operator")
        try:
            self.assertEqual(await self.shared_at_a(p), [])
        finally:
            await hosted.set_status(self.hub.owner_url, "campo-b", "active", "test", actor="test:operator")
        self.assertEqual(len(await self.shared_at_a(p)), 1)
        # Another person's records are not this person's.
        other = await self.person()
        await self.b_reading(other)
        self.assertEqual(await self.shared_at_a(other), [])
        # Unlinked: gone for the other field at once.
        r = await self.b.delete("/api/v1/me/hub-share", headers=p.auth_b)
        self.assertEqual(r.status_code, 204)
        self.assertEqual(await self.shared_at_a(p), [])
        self.assertEqual(await self.hubq("SELECT 1 FROM public.atalaia_share_members WHERE person_id = $1 AND "
                                        "tenant = $2", person, self.tb.schema), [])

    async def test_new_readings_reach_the_hub_only_while_active(self) -> None:
        p = await self.person()
        await self.link(p)
        first = await self.b_reading(p)  # linked, but nobody consented: nothing published
        self.assertEqual(await self.count_published(p), 0)
        await self.consent(p, "b")
        await self.consent(p, "a")
        self.assertEqual([s["reading_id"] for s in await self.shared_at_a(p)], [first["reading_id"]])  # caught up
        self.assertEqual(await self.count_published(p), 1)
        second = await self.b_reading(p, at=1792333805.0 - 30)
        self.assertEqual(sorted(s["reading_id"] for s in await self.shared_at_a(p)),
                         sorted([first["reading_id"], second["reading_id"]]))  # published as it arrived
        # What this field's roster pull answers (S14-5).
        with tenancy.use(self.ta):
            async with self.app.state.sessionmaker() as db:
                found = await chrono_registry.shared_for_players(db, self.ta.field_id, [p.pid_a, "p-nobody"])
        self.assertEqual([f["player_id"] for f in found], [p.pid_a])
        self.assertEqual({r["field"] for r in found[0]["readings"]}, {"Campo B"})

    async def test_a_players_erasure_and_an_accounts_erasure_take_the_copies_too(self) -> None:
        p = await self.person()
        await self.b_reading(p)
        await self.link(p)
        await self.consent(p, "b")
        await self.consent(p, "a")
        self.assertEqual(len(await self.shared_at_a(p)), 1)
        r = await self.b.delete(f"/api/v1/fields/{self.tb.field_id}/chrono/players/{p.pid_b}", headers=self.admin_b)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(await self.shared_at_a(p), [])
        self.assertEqual(await self.count_published(p), 0)
        q = await self.person()
        await self.b_reading(q)
        await self.link(q)
        await self.consent(q, "b")
        await self.consent(q, "a")
        self.assertEqual(len(await self.shared_at_a(q)), 1)
        before = (await self.hubq("SELECT count(*) AS n FROM public.atalaia_share_members WHERE tenant = $1",
                                 self.tb.schema))[0]["n"]
        person = await self.person_id(q)
        r = await self.b.request("DELETE", "/api/v1/me", json={"password": PASSWORD}, headers=q.auth_b)
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual(await self.shared_at_a(q), [])
        after = (await self.hubq("SELECT count(*) AS n FROM public.atalaia_share_members WHERE tenant = $1",
                                self.tb.schema))[0]["n"]
        self.assertEqual(before - after, 1)
        self.assertEqual(await self.hubq("SELECT 1 FROM public.atalaia_share_records WHERE person_id = $1", person), [])

    async def test_the_retention_purge_resyncs(self) -> None:
        p = await self.person()
        await self.b_reading(p)
        await self.link(p)
        await self.consent(p, "b")
        await self.consent(p, "a")
        self.assertEqual(len(await self.shared_at_a(p)), 1)
        await self.sql(self.tb, "DELETE FROM chrono_readings")  # what a purge does to the field's own copy
        from atalaia_server import personal_data
        with tenancy.use(self.tb):
            async with self.app.state.sessionmaker() as db:
                await personal_data.purge(db)
        self.assertEqual(await self.shared_at_a(p), [])


class LinkTests(ShareCase):
    async def test_codes_are_once_timed_and_for_another_field(self) -> None:
        p = await self.person()
        r = await self.a.get("/api/v1/me/hub-share", headers=p.auth_a)
        first = r.json()
        self.assertEqual((first["linked"], first["linked_at"], first["sharing"]), (False, None, False))
        self.assertEqual((first["consent"], first["others"]), (False, []))  # HLC-2: what the staff page reads too
        r = await self.a.post("/api/v1/me/hub-share/code", headers=p.auth_a)
        self.assertEqual(r.status_code, 201)
        code = r.json()["code"]
        self.assertEqual(r.json()["expires_in"], 900)
        stored = await self.hubq("SELECT code_hash FROM public.atalaia_share_codes")
        self.assertTrue(all(code.replace("-", "").encode() not in bytes(s["code_hash"]) for s in stored))
        # The same field cannot redeem it, nor can a wrong or malformed one.
        for bad in (code, "WRONG", "", "!!!"):
            r = await self.a.post("/api/v1/me/hub-share/link", json={"code": bad}, headers=p.auth_a)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "invalid_code"), bad)
        r = await self.b.post("/api/v1/me/hub-share/link", json={"code": "x" * 65}, headers=p.auth_b)
        self.assertEqual(r.status_code, 422)
        # At the other field it works once (case and dashes do not matter).
        r = await self.b.post("/api/v1/me/hub-share/link", json={"code": code.lower().replace("-", " ")},
                              headers=p.auth_b)
        self.assertEqual((r.status_code, r.json()["linked"]), (200, True))
        r = await self.b.post("/api/v1/me/hub-share/link", json={"code": code}, headers=self.admin_b)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "invalid_code"))  # used up
        status = (await self.b.get("/api/v1/me/hub-share", headers=p.auth_b)).json()
        self.assertEqual((status["linked"], status["sharing"]), (True, False))
        # An expired code is refused, and nothing is used up by a refusal.
        r = await self.a.post("/api/v1/me/hub-share/code", headers=p.auth_a)
        await self.hubq("UPDATE public.atalaia_share_codes SET expires_at = now() - interval '1 minute'")
        stranger_id, stranger, _ = await self.user(self.tb)
        auth = await self.auth(self.b, stranger)
        r = await self.b.post("/api/v1/me/hub-share/link", json={"code": r.json()["code"]}, headers=auth)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "invalid_code"))

    async def test_the_state_the_staff_page_reads(self) -> None:
        """HLC-2: this field (id, name, its switch and terms), whether the account's consent is live, and the other
        fields the person is linked at with whether sharing is on there: each side sees only the other's name and
        state, and it follows consent, the field's switch and unlinking."""
        p = await self.person()

        async def state(side: str) -> dict[str, Any]:
            client, auth = (self.a, p.auth_a) if side == "a" else (self.b, p.auth_b)
            r = await client.get("/api/v1/me/hub-share", headers=auth)
            self.assertEqual(r.status_code, 200, r.text)
            return r.json()

        a0, b0 = await state("a"), await state("b")
        self.assertEqual(a0["field"], {"id": str(self.ta.field_id), "name": a0["field"]["name"], "enabled": True,
                                       "live": True})
        self.assertNotEqual(a0["field"]["name"], b0["field"]["name"])
        self.assertEqual(b0["field"]["id"], str(self.tb.field_id))
        await self.link(p)
        a1, b1 = await state("a"), await state("b")
        self.assertEqual((a1["linked"], a1["others"]), (True, [{"field_name": b0["field"]["name"], "sharing": False,
                                                                 "since": a1["others"][0]["since"]}]))
        self.assertEqual([o["field_name"] for o in b1["others"]], [a0["field"]["name"]])
        self.assertEqual({k: v for k, v in b1["others"][0].items() if k != "since"},
                         {"field_name": a0["field"]["name"], "sharing": False})
        await self.consent(p, "a")
        a2, b2 = await state("a"), await state("b")
        self.assertEqual((a2["consent"], a2["sharing"], b2["consent"]), (True, True, False))
        self.assertTrue(b2["others"][0]["sharing"])   # A is sharing; B is told so
        self.assertFalse(a2["others"][0]["sharing"])  # B's consent is still missing
        await self.consent(p, "b")
        self.assertTrue((await state("a"))["others"][0]["sharing"])
        # The field's switch off: its own state says so, and the other field's list follows.
        await self.switch("a", False)
        a3, b3 = await state("a"), await state("b")
        self.assertEqual((a3["field"]["enabled"], a3["field"]["live"], a3["consent"], a3["sharing"]),
                         (False, False, True, False))
        self.assertFalse(b3["others"][0]["sharing"])
        await self.switch("a", True)
        await self.consent(p, "a", give=False)
        a4, b4 = await state("a"), await state("b")
        self.assertEqual((a4["consent"], a4["sharing"], b4["others"][0]["sharing"]), (False, False, False))
        # Unlinking at B: B has no link left and A no longer lists B; A's own link stays (it is still the person's).
        r = await self.b.delete("/api/v1/me/hub-share", headers=p.auth_b)
        self.assertEqual(r.status_code, 204)
        a5, b5 = await state("a"), await state("b")
        self.assertEqual((b5["linked"], b5["others"], a5["others"]), (False, [], []))

    async def test_one_person_one_account_per_field(self) -> None:
        p = await self.person()
        await self.link(p)
        # A second account at field B cannot take the person; a linked account cannot take another person.
        _, name, _ = await self.user(self.tb)
        second = await self.auth(self.b, name)
        r = await self.a.post("/api/v1/me/hub-share/code", headers=p.auth_a)
        r = await self.b.post("/api/v1/me/hub-share/link", json={"code": r.json()["code"]}, headers=second)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "person_already_linked_here"))
        q = await self.person()
        code = (await self.a.post("/api/v1/me/hub-share/code", headers=q.auth_a)).json()["code"]
        r = await self.b.post("/api/v1/me/hub-share/link", json={"code": code}, headers=p.auth_b)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "already_linked"))
        # Not used up by the refusal: the right account redeems it.
        r = await self.b.post("/api/v1/me/hub-share/link", json={"code": code}, headers=q.auth_b)
        self.assertEqual((r.status_code, r.json()["linked"]), (200, True))
        self.assertEqual((await self.b.delete("/api/v1/me/hub-share", headers=second)).status_code, 404)
        self.assertEqual((await self.a.get("/api/v1/me/hub-share")).status_code, 401)

    async def test_codes_are_rate_limited_and_audited_without_the_code(self) -> None:
        p = await self.person()
        codes = []
        for _ in range(10):
            r = await self.a.post("/api/v1/me/hub-share/code", headers=p.auth_a)
            self.assertEqual(r.status_code, 201)
            codes.append(r.json()["code"])
        r = await self.a.post("/api/v1/me/hub-share/code", headers=p.auth_a)
        self.assertEqual(r.status_code, 429)
        logged = str(await self.sql(self.ta, "SELECT action, details FROM audit_log WHERE action LIKE 'hub_share%'"))
        self.assertIn("hub_share_code", logged)
        self.assertFalse(any(c.replace("-", "") in logged.replace("-", "") for c in codes))


class IsolationTests(ShareCase):
    """As the server's own database role: its rows in the hub's tables are its tenant's, and only the
    function crosses, only for what both fields are active for."""

    async def published(self) -> Person:
        p = await self.person()
        await self.b_reading(p)
        await self.link(p)
        await self.consent(p, "b")
        await self.consent(p, "a")
        return p

    async def test_the_server_role_sees_and_writes_only_its_own_tenant(self) -> None:
        """As a field's database role (S2113-3 keys the policy on it, not on the ``atalaia.tenant`` setting)."""
        p = await self.published()
        total = (await self.hubq("SELECT count(*) AS n FROM public.atalaia_share_records WHERE tenant = $1",
                                self.tb.schema))[0]["n"]
        self.assertGreaterEqual(total, 1)
        conn = await connect(self.hub.app_url)
        try:
            for tenant, other, expected in ((self.ta, self.tb, 0), (self.tb, self.ta, total)):
                async with conn.transaction():
                    # The setting names the other field, as an injected set_config would: it changes nothing.
                    await conn.execute("SELECT set_config('atalaia.tenant', $1, true)", other.schema)
                    await as_field(conn, tenant)
                    self.assertEqual(await conn.fetchval("SELECT count(*) FROM public.atalaia_share_records WHERE "
                                                         "tenant = $1", self.tb.schema), expected)
                    self.assertEqual(await conn.fetchval("SELECT count(*) FROM public.atalaia_share_records WHERE "
                                                         "tenant <> $1", tenant.schema), 0)
            # The server's login role itself holds nothing in the hub's sharing tables.
            for table in ("records", "members", "codes"):
                with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                    await conn.fetchval(f"SELECT count(*) FROM public.atalaia_share_{table}")
            # Another tenant's rows cannot be changed or planted.
            async with conn.transaction():
                await as_field(conn, self.ta)
                self.assertEqual(await conn.execute("DELETE FROM public.atalaia_share_records"), "DELETE 0")
                self.assertEqual(await conn.execute("UPDATE public.atalaia_share_members SET active = true "
                                                    "WHERE tenant = $1", self.tb.schema), "UPDATE 0")
            for statement in (
                    "INSERT INTO public.atalaia_share_members (person_id, tenant, active) VALUES ($1, $2, true)",
                    "INSERT INTO public.atalaia_share_codes (code_hash, person_id, tenant, expires_at) "
                    "VALUES ('\\x00', $1, $2, now())"):
                with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                    async with conn.transaction():
                        await as_field(conn, self.ta)
                        await conn.execute(statement, uuid.uuid4(), self.tb.schema)
            with self.assertRaises(asyncpg.InsufficientPrivilegeError):  # no TRUNCATE, no DDL
                async with conn.transaction():
                    await as_field(conn, self.ta)
                    await conn.execute("TRUNCATE public.atalaia_share_records")
            with self.assertRaises(asyncpg.InsufficientPrivilegeError):
                async with conn.transaction():
                    await as_field(conn, self.ta)
                    await conn.execute("CREATE TABLE public.x (a int)")
        finally:
            await conn.close()
        self.assertEqual(len(await self.shared_at_a(p)), 1)  # nothing above changed it

    async def test_the_function_answers_only_a_member_for_the_callers_own_tenant(self) -> None:
        p = await self.published()
        with tenancy.use(self.ta):
            async with self.app.state.sessionmaker() as db:
                from atalaia_server import hub_share
                person = (await db.get(hub_share.HubShareLink, p.user_a)).person_id
        query = "SELECT count(*) FROM public.atalaia_share_read($1::uuid[], 100)"
        conn = await connect_driver_safe(self.hub.app_url)
        try:
            async def count(tenant: Optional[tenancy.Tenant], setting: Optional[str] = None) -> int:
                async with conn.transaction():
                    if setting is not None:  # what an injected set_config could say: it is not what answers
                        await conn.execute("SELECT set_config('atalaia.tenant', $1, true)", setting)
                    if tenant is not None:
                        await as_field(conn, tenant)
                    return int(await conn.fetchval(query, [person]))
            self.assertEqual(await count(self.ta), 1)   # field A reads B's record
            self.assertEqual(await count(self.tb), 0)   # field B reads none of A's (A has none)
            self.assertEqual(await count(self.tb, setting=self.ta.schema), 0)  # B naming A's setting: still B
            self.assertEqual(await count(self.ta, setting=self.tb.schema), 1)  # A naming B's setting: still A
            self.assertEqual(await count(self.ta, setting="field_campo_z"), 1)
            with self.assertRaises(asyncpg.InsufficientPrivilegeError):  # the login role: no right to the function
                await count(None, setting=self.ta.schema)
            async with conn.transaction():  # a person nobody asked about
                await as_field(conn, self.ta)
                self.assertEqual(await conn.fetchval(query, [uuid.uuid4()]), 0)
        finally:
            await conn.close()


    async def test_the_peers_function_names_fields_only_for_a_member_of_the_callers_tenant(self) -> None:
        """HLC-2: ``atalaia_share_peers`` answers the other fields' names and states for a person the caller is a
        member for, nobody else's, and not to the server's login role."""
        p = await self.published()
        with tenancy.use(self.ta):
            async with self.app.state.sessionmaker() as db:
                from atalaia_server import hub_share
                person = (await db.get(hub_share.HubShareLink, p.user_a)).person_id
        query = "SELECT field_name, active FROM public.atalaia_share_peers($1)"
        conn = await connect_driver_safe(self.hub.app_url)
        try:
            for tenant, other in ((self.ta, "Campo B"), (self.tb, "Campo A")):
                async with conn.transaction():
                    await as_field(conn, tenant)
                    rows = await conn.fetch(query, person)
                    self.assertEqual([(r["field_name"], r["active"]) for r in rows], [(other, True)])
            async with conn.transaction():  # a person the caller is no member for: nothing
                await as_field(conn, self.ta)
                self.assertEqual(await conn.fetch(query, uuid.uuid4()), [])
            async with conn.transaction():  # the caller's tenant is not the one asked about
                await conn.execute("SELECT set_config('atalaia.tenant', $1, true)", self.tb.schema)
                await as_field(conn, self.ta)
                self.assertEqual(len(await conn.fetch(query, person)), 1)
            with self.assertRaises(asyncpg.InsufficientPrivilegeError):  # the login role: no right to it
                async with conn.transaction():
                    await conn.fetch(query, person)
        finally:
            await conn.close()


class DeleteTests(HubCase):
    async def test_deleting_a_field_removes_its_rows_in_the_hub(self) -> None:
        url = self.hub.owner_url
        await asyncio.to_thread(hosted.create_tenant, url, "campo-d", "Campo D", "outdoor", "Europe/Lisbon",
                                self.hub.app_role, "test:operator")
        person = uuid.uuid4()
        conn = await connect(url)
        try:
            for slug in ("campo_d", "campo_a"):
                await conn.execute("INSERT INTO public.atalaia_share_members (person_id, tenant, active, field_name) "
                                   "VALUES ($1, $2, true, 'x')", person, f"field_{slug}")
                await conn.execute("INSERT INTO public.atalaia_share_records (tenant, person_id, reading_id, taken_at, "
                                   "record_json, public_key) VALUES ($1, $2, $3, now(), '{}', 'k')",
                                   f"field_{slug}", person, uuid.uuid4())
            await conn.execute("INSERT INTO public.atalaia_share_codes VALUES ('\\x01', $1, 'field_campo_d', "
                               "now() + interval '1 hour')", person)
        finally:
            await conn.close()
        counts = await hosted.delete_tenant(url, "campo-d", "campo-d", "contract ended", actor="test:operator")
        self.assertEqual((counts["hub_share_records"], counts["hub_share_members"]), (1, 1))
        conn = await connect(url)
        try:
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM public.atalaia_share_members WHERE tenant = "
                                                 "'field_campo_d'"), 0)
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM public.atalaia_share_codes"), 0)
            self.assertEqual(await conn.fetchval("SELECT count(*) FROM public.atalaia_share_records WHERE "
                                                 "tenant = 'field_campo_a'"), 1)  # another field's rows stay
            await conn.execute("DELETE FROM public.atalaia_share_members WHERE person_id = $1", person)
        finally:
            await conn.close()


if __name__ == "__main__":
    unittest.main()
