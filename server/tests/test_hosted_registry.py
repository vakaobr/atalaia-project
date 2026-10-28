# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the hosted hub's registry gained (decisions PKC-1, PKC-5, PKC-6): the staff's view of a field's quota use, the
operator's per-field quotas, a stored-bytes quota, the notes a refused field leaves for the operator, and a custom host
name per field (routing, the ``ask`` endpoint, the DNS TXT challenge, the commands, the upgrade of an older registry).

Runs on the hub of ``test_tenants.HubCase`` (two fields, the server's role without BYPASSRLS).

    python3 tools/docker_server.py test tests.test_hosted_registry
"""

from __future__ import annotations

import asyncio
import io
import os
import socket
import struct
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path
from typing import Any, Optional

import httpx

from atalaia_server import cli, dnsquery, hosted, quotas, tenancy, tls_ask
from atalaia_server.app import create_app
from atalaia_server.config import QUOTA_DEFAULTS

from .test_hosted_limits import LimitCase
from .test_tenants import DOMAIN, HubCase, connect, envelope, META

HOST = "jogos.exemplo.pt"


async def owner(hub: Any, statement: str, *args: Any) -> list[Any]:
    conn = await connect(hub.owner_url)
    try:
        return list(await conn.fetch(statement, *args))
    finally:
        await conn.close()


async def owner_script(hub: Any, script: str) -> None:
    """Several statements at once (a prepared statement takes only one)."""
    conn = await connect(hub.owner_url)
    try:
        await conn.execute(script)
    finally:
        await conn.close()


def operator(hub: Any, *argv: str, domain: str = DOMAIN) -> tuple[int, str, str]:
    """One ``python -m atalaia_server hosted ...`` command as the operator runs it."""
    out, err = io.StringIO(), io.StringIO()
    with unittest.mock.patch.dict(os.environ, {"ATALAIA_DATABASE_URL": hub.owner_url, "ATALAIA_APP_ROLE": hub.app_role,
                                               "ATALAIA_HOSTED_DOMAIN": domain}):
        code = cli.main(["hosted", *argv], io.StringIO(), out, err)
    return code, out.getvalue(), err.getvalue()


class FakeDns:
    """A resolver for ``verify_custom_domain``: name -> the TXT strings published there."""

    def __init__(self, records: Optional[dict[str, list[str]]] = None, fail: bool = False) -> None:
        self.records = records or {}
        self.fail = fail
        self.asked: list[str] = []

    def __call__(self, name: str) -> list[str]:
        self.asked.append(name)
        if self.fail:
            raise dnsquery.DnsError("no server answered")
        return self.records.get(name, [])


class QuotaUseTests(LimitCase):
    """The field's own view of its limits (the page's API) and the operator's per-field overrides."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        quotas._reported.clear()
        quotas._stored.clear()
        await owner(self.hub, "DELETE FROM public.atalaia_quota_hits")

    async def asyncTearDown(self) -> None:
        for slug in ("campo-a", "campo-b"):
            await owner(self.hub, "UPDATE public.atalaia_tenants SET quotas = '{}'::jsonb WHERE slug = $1", slug)
        await super().asyncTearDown()

    async def test_a_field_admin_reads_what_it_uses(self) -> None:
        admin = await self.staff(self.ta, self.a, "admin")
        gm = await self.staff(self.ta, self.a, "gm")
        url = f"/api/v1/fields/{self.ta.field_id}/quotas"
        self.assertEqual((await self.a.get(url, headers=gm)).status_code, 403)
        self.assertEqual((await self.a.get(url)).status_code, 401)
        r = await self.a.get(url, headers=admin)
        self.assertEqual((r.status_code, r.headers["cache-control"]), (200, "no-store"))
        body = r.json()
        self.assertTrue(body["hosted"])
        rows = {q["name"]: q for q in body["quotas"]}
        self.assertEqual(list(rows), list(QUOTA_DEFAULTS))
        self.assertEqual(rows["accounts"]["used"], await self.count(self.ta, "users"))
        self.assertEqual(rows["accounts"]["limit"], QUOTA_DEFAULTS["accounts"])
        self.assertEqual(rows["streams"]["used"], 0)
        self.assertGreater(rows["stored_mb"]["used"], 0)  # the schema is never empty
        self.limit(accounts=0)
        self.assertIsNone({q["name"]: q for q in (await self.a.get(url, headers=admin)).json()["quotas"]}
                          ["accounts"]["limit"])  # off: no limit
        # Another field's admin cannot read this field's use.
        other = await self.staff(self.tb, self.b, "admin")
        self.assertEqual((await self.b.get(url, headers=other)).status_code, 403)

    async def fill(self, gm: dict[str, str]) -> None:
        """The field's schedule at its limit (a limit of 0 would mean none): one game, then the limit is the count."""
        r = await self.a.post(f"/api/v1/fields/{self.ta.field_id}/scheduled-games", json=self.game_body("Um"), headers=gm)
        self.assertEqual(r.status_code, 201, r.text)
        self.limit(scheduled_games=await self.count(self.ta, "scheduled_games"))

    async def test_the_operator_gives_one_field_its_own_limit(self) -> None:
        gm_a, gm_b = await self.staff(self.ta, self.a, "gm"), await self.staff(self.tb, self.b, "gm")
        have_a = await self.count(self.ta, "scheduled_games")
        change = await hosted.set_quota(self.hub.owner_url, "campo-a", "scheduled_games", str(have_a + 1),
                                        "plan: small", actor="test:operator")
        self.assertEqual(change, {"old": None, "new": have_a + 1})
        url_a = f"/api/v1/fields/{self.ta.field_id}/scheduled-games"
        r = await self.a.post(url_a, json=self.game_body("Um"), headers=gm_a)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self.a.post(url_a, json=self.game_body("Dois"), headers=gm_a)
        self.assertEqual((r.status_code, r.json()), (409, {"detail": "quota_exceeded", "quota": "scheduled_games",
                                                           "limit": have_a + 1}))
        # B keeps the hub's limit, and the admin's view shows the field's own.
        r = await self.b.post(f"/api/v1/fields/{self.tb.field_id}/scheduled-games", json=self.game_body("B"),
                              headers=gm_b)
        self.assertEqual(r.status_code, 201, r.text)
        admin = await self.staff(self.ta, self.a, "admin")
        rows = {q["name"]: q for q in (await self.a.get(f"/api/v1/fields/{self.ta.field_id}/quotas",
                                                        headers=admin)).json()["quotas"]}
        self.assertEqual(rows["scheduled_games"]["limit"], have_a + 1)
        self.assertEqual(rows["accounts"]["limit"], QUOTA_DEFAULTS["accounts"])
        # off lifts it, default gives the hub's back.
        await hosted.set_quota(self.hub.owner_url, "campo-a", "scheduled_games", "off", "no cap", actor="test:operator")
        r = await self.a.post(url_a, json=self.game_body("Tres"), headers=gm_a)
        self.assertEqual(r.status_code, 201, r.text)
        change = await hosted.set_quota(self.hub.owner_url, "campo-a", "scheduled_games", "default", "back",
                                        actor="test:operator")
        self.assertEqual(change, {"old": 0, "new": None})
        self.assertEqual(await owner(self.hub, "SELECT quotas::text FROM public.atalaia_tenants "
                                               "WHERE slug = 'campo-a'"), [("{}",)])
        actions = [r["action"] for r in await owner(self.hub, "SELECT action FROM public.atalaia_hub_audit "
                                                              "WHERE slug = 'campo-a' ORDER BY id")]
        self.assertEqual(actions.count("tenant_quota"), 3)

    async def test_the_commands_refuse_what_is_not_a_quota(self) -> None:
        for name, value, why in (("nope", "5", "unknown quota"), ("games", "0", "whole number"),
                                 ("games", "-3", "whole number"), ("games", "many", "whole number"),
                                 ("games", "100000001", "whole number")):
            with self.subTest(name=name, value=value), self.assertRaisesRegex(hosted.HostedError, why):
                await hosted.set_quota(self.hub.owner_url, "campo-a", name, value, "x")
        with self.assertRaisesRegex(hosted.HostedError, "--reason"):
            await hosted.set_quota(self.hub.owner_url, "campo-a", "games", "5", " ")
        with self.assertRaisesRegex(hosted.HostedError, "no field"):
            await hosted.set_quota(self.hub.owner_url, "campo-z", "games", "5", "x")

    async def test_the_stored_bytes_quota(self) -> None:
        key = await self.key(self.ta, self.a)
        bearer = {"Authorization": f"Bearer {key}"}
        await hosted.set_quota(self.hub.owner_url, "campo-a", "stored_mb", "1", "tiny", actor="test:operator")
        with unittest.mock.patch.object(quotas, "stored_bytes", unittest.mock.AsyncMock(return_value=quotas.MIB + 1)):
            r = await self.a.post("/api/v1/sync/games", json=envelope(meta=META), headers=bearer)
            self.assertEqual((r.status_code, r.json()), (409, {"detail": "quota_exceeded", "quota": "stored_mb",
                                                               "limit": 1}))
            admin = await self.staff(self.ta, self.a, "admin")
            r = await self.a.put(f"/api/v1/fields/{self.ta.field_id}/branding/logo?rights_confirmed=true",
                                 content=b"x", headers={**admin, "Content-Type": "image/png"})
            self.assertEqual((r.status_code, r.json()["quota"]), (409, "stored_mb"))
            # The other field has the hub's default (2 GiB): the same size is nothing to it.
            r = await self.b.post("/api/v1/sync/games", json=envelope(meta=META),
                                  headers={"Authorization": f"Bearer {await self.key(self.tb, self.b)}"})
            self.assertEqual(r.status_code, 200, r.text)
        # Under the limit the sync works; an image that would pass it is refused by what it adds.
        with unittest.mock.patch.object(quotas, "stored_bytes", unittest.mock.AsyncMock(return_value=quotas.MIB - 5)):
            r = await self.a.post("/api/v1/sync/games", json=envelope(meta=META), headers=bearer)
            self.assertEqual(r.status_code, 200, r.text)
            admin = await self.staff(self.ta, self.a, "admin")
            r = await self.a.put(f"/api/v1/fields/{self.ta.field_id}/branding/logo?rights_confirmed=true",
                                 content=b"x" * 10, headers={**admin, "Content-Type": "image/png"})
            self.assertEqual((r.status_code, r.json()["quota"]), (409, "stored_mb"))

    async def test_the_stored_bytes_are_read_from_the_catalogue_and_cached(self) -> None:
        async with self.app.state.sessionmaker() as db:
            with tenancy.use(self.ta):
                first = await quotas.stored_bytes(db)
                self.assertGreater(first or 0, 100_000)
                self.assertEqual(await quotas.stored_bytes(db), first)  # the cached number
                self.assertGreater(await quotas.stored_bytes(db, fresh=True) or 0, 0)
            self.assertIsNone(await quotas.stored_bytes(db))  # no tenant: single-field mode has none

    async def test_a_refused_field_leaves_one_note_for_the_operator(self) -> None:
        gm = await self.staff(self.ta, self.a, "gm")
        await self.fill(gm)
        url = f"/api/v1/fields/{self.ta.field_id}/scheduled-games"
        for _ in range(3):
            r = await self.a.post(url, json=self.game_body(), headers=gm)
            self.assertEqual(r.status_code, 409, r.text)
        rows = await owner(self.hub, "SELECT slug, quota, limit_value FROM public.atalaia_quota_hits")
        self.assertEqual([tuple(r) for r in rows], [("campo-a", "scheduled_games", self.app.state.settings.quotas[
            "scheduled_games"])])  # three refusals, one note (per field and quota, for ten minutes)
        # The sync's refusal is a note too (another quota: another note); the other field has its own.
        key = await self.key(self.ta, self.a)
        bearer = {"Authorization": f"Bearer {key}"}
        self.limit(scheduled_games=0)
        r = await self.a.post("/api/v1/sync/games", json=envelope(meta=META), headers=bearer)
        self.assertEqual(r.status_code, 200, r.text)
        self.limit(scheduled_games=0, games=await self.count(self.ta, "games"))  # at least the game just stored
        r = await self.a.post("/api/v1/sync/games", json={**envelope(meta=META), "game": {"game_id": 9, "game_seed": 9}},
                              headers=bearer)
        self.assertEqual(r.status_code, 409, r.text)
        quotas._reported[("field_campo_a", "scheduled_games")] -= quotas.REPORT_EVERY_S + 1  # ten minutes on
        self.limit(scheduled_games=await self.count(self.ta, "scheduled_games"))  # (the sync's limit is off again)
        r = await self.a.post(url, json=self.game_body(), headers=gm)
        self.assertEqual(r.status_code, 409, r.text)
        got = sorted((r["slug"], r["quota"]) for r in await owner(
            self.hub, "SELECT slug, quota FROM public.atalaia_quota_hits"))
        self.assertEqual(got, [("campo-a", "games"), ("campo-a", "scheduled_games"), ("campo-a", "scheduled_games")])

    async def test_the_operator_sees_the_notes_and_they_reach_the_audit_log(self) -> None:
        gm = await self.staff(self.ta, self.a, "gm")
        await self.fill(gm)
        r = await self.a.post(f"/api/v1/fields/{self.ta.field_id}/scheduled-games", json=self.game_body(), headers=gm)
        self.assertEqual(r.status_code, 409, r.text)
        code, out, err = await asyncio.to_thread(operator, self.hub, "list")
        self.assertEqual(code, 0, err)
        self.assertIn("1 note(s) of fields refused for a quota are waiting", out)
        report = await hosted.check_hub(self.hub.owner_url, self.hub.app_role)
        self.assertEqual((report.problems, report.quota_hits), ([], 1))
        code, out, err = await asyncio.to_thread(operator, self.hub, "check")
        self.assertEqual(code, 0, err)
        self.assertIn("1 note(s)", out)
        code, out, err = await asyncio.to_thread(operator, self.hub, "quota-hits", "--actor", "test:operator")
        self.assertEqual(code, 0, err)
        self.assertIn("campo-a: refused for scheduled_games", out)
        self.assertIn("recorded in the hub's audit log", out)
        audit = await owner(self.hub, "SELECT slug, actor, details::text FROM public.atalaia_hub_audit "
                                      "WHERE action = 'quota_hit'")
        self.assertEqual([(r["slug"], r["actor"]) for r in audit], [("campo-a", "test:operator")])
        self.assertIn('"quota": "scheduled_games"', audit[0]["details"])
        self.assertEqual(await owner(self.hub, "SELECT count(*) FROM public.atalaia_quota_hits"), [(0,)])
        code, out, _ = await asyncio.to_thread(operator, self.hub, "quota-hits")
        self.assertIn("No field was refused", out)
        self.assertNotIn("waiting", (await asyncio.to_thread(operator, self.hub, "list"))[1])

    async def test_the_note_cannot_be_read_or_changed_by_the_server(self) -> None:
        conn = await connect(self.hub.app_url)
        try:
            await conn.execute("INSERT INTO public.atalaia_quota_hits (slug, quota, limit_value) VALUES ('campo-a', "
                               "'games', 1)")
            for statement in ("SELECT * FROM public.atalaia_quota_hits", "DELETE FROM public.atalaia_quota_hits",
                              "UPDATE public.atalaia_quota_hits SET slug = 'x'",
                              "INSERT INTO public.atalaia_hub_audit (action, actor) VALUES ('x', 'x')",
                              "UPDATE public.atalaia_tenants SET custom_host = 'evil.example.pt'"):
                with self.subTest(statement=statement), self.assertRaisesRegex(Exception, "permission denied"):
                    await conn.execute(statement)
        finally:
            await conn.close()
        await owner(self.hub, "DELETE FROM public.atalaia_quota_hits")

    async def test_usage_command(self) -> None:
        await hosted.set_quota(self.hub.owner_url, "campo-a", "games", "77", "plan", actor="test:operator")
        code, out, err = await asyncio.to_thread(operator, self.hub, "usage", "campo-a")
        self.assertEqual(code, 0, err)
        self.assertIn("campo-a (active)", out)
        self.assertRegex(out, r"games\s+\d+ / 77  \(this field's own\)")
        self.assertRegex(out, rf"accounts\s+\d+ / {QUOTA_DEFAULTS['accounts']}\n")
        self.assertNotIn("campo-b", out)
        code, out, _ = await asyncio.to_thread(operator, self.hub, "usage")
        self.assertIn("campo-b (active)", out)
        code, out, err = await asyncio.to_thread(operator, self.hub, "quota", "campo-a", "games", "off", "--reason",
                                                 "test")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("games limit 77 -> no limit", out)
        code, _, err = await asyncio.to_thread(operator, self.hub, "quota", "campo-a", "games", "zero", "--reason", "x")
        self.assertEqual(code, 1)
        self.assertIn("whole number", err)


class CustomHostTests(HubCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await owner(self.hub, "UPDATE public.atalaia_tenants SET custom_host = NULL, custom_host_status = NULL, "
                              "custom_host_token = NULL")

    async def test_the_names_a_field_may_have(self) -> None:
        for good in (HOST, "Jogos.Exemplo.PT.", "a.b.c.example.org", "xn--jogos-mt-d5a.example.pt"):
            with self.subTest(good=good):
                self.assertEqual(tenancy.check_custom_host(good, DOMAIN), good.lower().rstrip("."))
        for bad in ("", "localhost", "-a.example.pt", "a_b.example.pt", "*.example.pt", "https://jogos.example.pt",
                    "jogos.example.pt:443", "jogos.example.pt/x", "127.0.0.1", "1.2.3.4", "a..example.pt", DOMAIN,
                    f"campo-c.{DOMAIN}", f"x.campo-a.{DOMAIN}", "a" * 64 + ".example.pt", "café.example.pt"):
            with self.subTest(bad=bad), self.assertRaises(tenancy.TenantError):
                tenancy.check_custom_host(bad, DOMAIN)

    async def test_pending_then_verified_then_removed(self) -> None:
        dns = FakeDns()
        name, value = await hosted.set_custom_domain(self.hub.owner_url, "campo-a", HOST.upper(), DOMAIN, "club's wish",
                                                     actor="test:operator")
        self.assertEqual(name, f"_atalaia-challenge.{HOST}")
        self.assertRegex(value, r"^atalaia-verify=[0-9a-f]{32}$")
        row = (await owner(self.hub, "SELECT custom_host, custom_host_status FROM public.atalaia_tenants "
                                     "WHERE slug = 'campo-a'"))[0]
        self.assertEqual(tuple(row), (HOST, "pending"))
        # Pending: the name routes nowhere, and no certificate.
        r = await self.client("", HOST).get("/api/v1/fields")
        self.assertEqual((r.status_code, r.json()), (404, {"detail": "unknown_field"}))
        # Nothing, or someone else's value, is not a proof; only the field's token is.
        for records, why in (({}, "no TXT record"), ({name: ["atalaia-verify=" + "0" * 32]}, "found")):
            with self.subTest(records=records), self.assertRaisesRegex(hosted.HostedError, why):
                await hosted.verify_custom_domain(self.hub.owner_url, "campo-a", resolver=FakeDns(records))
        with self.assertRaisesRegex(hosted.HostedError, "DNS lookup"):
            await hosted.verify_custom_domain(self.hub.owner_url, "campo-a", resolver=FakeDns(fail=True))
        self.assertEqual((await self.client("", HOST).get("/api/v1/fields")).status_code, 404)
        dns.records = {name: ["unrelated", value]}
        self.assertEqual(await hosted.verify_custom_domain(self.hub.owner_url, "campo-a", actor="test:operator",
                                                           resolver=dns), HOST)
        self.assertEqual(dns.asked, [name])
        # On: the host routes to the field (its own host keeps working), and to no other field.
        c = self.client("", f"{HOST}:443")
        self.assertEqual((await c.get("/api/v1/fields")).status_code, 401)
        self.assertEqual((await self.a.get("/api/v1/fields")).status_code, 401)
        admin = await self.staff(self.ta, c, "admin")
        names = [f["slug"] for f in (await c.get("/api/v1/fields", headers=admin)).json()]
        self.assertEqual(names, ["campo-a"])
        self.assertEqual((await self.b.get("/api/v1/fields", headers=admin)).status_code, 401)  # the token is A's
        with self.assertRaisesRegex(hosted.HostedError, "already verified"):
            await hosted.verify_custom_domain(self.hub.owner_url, "campo-a", resolver=dns)
        # Suspended: the same refusal as at its own name.
        await hosted.set_status(self.hub.owner_url, "campo-a", "suspended", "test", actor="test:operator")
        try:
            r = await c.get("/api/v1/fields")
            self.assertEqual((r.status_code, r.json()), (403, {"detail": "field_suspended"}))
        finally:
            await hosted.set_status(self.hub.owner_url, "campo-a", "active", "test", actor="test:operator")
        removed = await hosted.remove_custom_domain(self.hub.owner_url, "campo-a", "contract ended",
                                                    actor="test:operator")
        self.assertEqual(removed, HOST)
        self.assertEqual((await c.get("/api/v1/fields")).status_code, 404)
        self.assertIsNone(await hosted.remove_custom_domain(self.hub.owner_url, "campo-a", "again"))
        actions = [r["action"] for r in await owner(self.hub, "SELECT action FROM public.atalaia_hub_audit "
                                                              "WHERE action LIKE 'tenant_domain%' ORDER BY id")]
        self.assertEqual(actions[-3:], ["tenant_domain_set", "tenant_domain_verify", "tenant_domain_remove"])

    async def test_a_name_belongs_to_one_field_and_changing_it_starts_over(self) -> None:
        await hosted.set_custom_domain(self.hub.owner_url, "campo-a", HOST, DOMAIN, "x")
        with self.assertRaisesRegex(hosted.HostedError, "already the custom host name of the field campo-a"):
            await hosted.set_custom_domain(self.hub.owner_url, "campo-b", HOST, DOMAIN, "x")
        name, value = await hosted.set_custom_domain(self.hub.owner_url, "campo-a", HOST, DOMAIN, "again")
        dns = FakeDns({name: [value]})
        await hosted.verify_custom_domain(self.hub.owner_url, "campo-a", resolver=dns)
        # A new name replaces the old one and is pending again: the old one stops routing at once.
        new_name, new_value = await hosted.set_custom_domain(self.hub.owner_url, "campo-a", "outro.exemplo.pt", DOMAIN,
                                                             "moved")
        self.assertEqual((await self.client("", HOST).get("/api/v1/fields")).status_code, 404)
        self.assertEqual((await self.client("", "outro.exemplo.pt").get("/api/v1/fields")).status_code, 404)
        self.assertNotEqual(new_value, value)  # a new challenge for the new name
        for bad, why in ((f"x.{DOMAIN}", "hub's own domain"), ("localhost", "DNS name")):
            with self.assertRaisesRegex(Exception, why):
                await hosted.set_custom_domain(self.hub.owner_url, "campo-a", bad, DOMAIN, "x")
        with self.assertRaisesRegex(hosted.HostedError, "--reason"):
            await hosted.set_custom_domain(self.hub.owner_url, "campo-a", HOST, DOMAIN, "")
        with self.assertRaisesRegex(hosted.HostedError, "has no custom host name"):
            await hosted.verify_custom_domain(self.hub.owner_url, "campo-b", resolver=FakeDns())
        # The table refuses a bad name even to the owner; one name for two fields too.
        with self.assertRaises(Exception):
            await owner(self.hub, "UPDATE public.atalaia_tenants SET custom_host = 'Bad Name' WHERE slug = 'campo-b'")
        with self.assertRaises(Exception):
            await owner(self.hub, "UPDATE public.atalaia_tenants SET custom_host = 'outro.exemplo.pt' "
                                  "WHERE slug = 'campo-b'")

    async def test_the_origin_follows_the_name_the_request_came_by(self) -> None:
        tenant = tenancy.Tenant(slug="campo-a", schema="field_campo_a", field_id=self.ta.field_id,
                                custom_host=HOST, custom_host_status="active")
        self.assertEqual(tenant.serving_host(DOMAIN, HOST), HOST)
        self.assertEqual(tenant.serving_host(DOMAIN, f"{HOST}:8443"), HOST)
        self.assertEqual(tenant.serving_host(DOMAIN, f"campo-a.{DOMAIN}"), f"campo-a.{DOMAIN}")
        self.assertEqual(tenant.serving_host(DOMAIN), f"campo-a.{DOMAIN}")
        pending = tenancy.Tenant(slug="campo-a", schema="field_campo_a", field_id=self.ta.field_id,
                                 custom_host=HOST, custom_host_status="pending")
        self.assertEqual(pending.serving_host(DOMAIN, HOST), f"campo-a.{DOMAIN}")
        # A public page reached by the custom name links to it (a passkey's origin follows the same function).
        await owner(self.hub, "UPDATE public.atalaia_tenants SET custom_host = $1, custom_host_status = 'active' "
                              "WHERE slug = 'campo-a'", HOST)
        await self.sql(self.ta, "UPDATE fields SET public_page = true")
        try:
            page = await self.client("", HOST).get("/f/campo-a/games.json")
            self.assertEqual(page.status_code, 200, page.text)
            self.assertIn(f"https://{HOST}/", page.text)
            self.assertNotIn(f"campo-a.{DOMAIN}", page.text)
            own = await self.a.get("/f/campo-a/games.json")
            self.assertIn(f"https://campo-a.{DOMAIN}/", own.text)
        finally:
            await self.sql(self.ta, "UPDATE fields SET public_page = false")

    async def test_the_ask_endpoint_says_yes_only_to_a_verified_name(self) -> None:
        app = tls_ask.create_app({"ATALAIA_DATABASE_URL": self.hub.app_url, "ATALAIA_HOSTED_DOMAIN": DOMAIN})
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tls-ask") as c:
                app.bucket = tls_ask.TokenBucket(1000.0, 1000)

                async def ask(name: str) -> int:
                    return (await c.get("/check", params={"domain": name})).status_code

                self.assertEqual(await ask(HOST), 404)  # nobody's
                name, value = await hosted.set_custom_domain(self.hub.owner_url, "campo-a", HOST, DOMAIN, "x")
                self.assertEqual(await ask(HOST), 404)  # pending
                await hosted.verify_custom_domain(self.hub.owner_url, "campo-a", resolver=FakeDns({name: [value]}))
                self.assertEqual([await ask(HOST), await ask(HOST.upper() + ".")], [200, 200])
                self.assertEqual(await ask("campo-a.hub.test"), 200)
                for other in ("www." + HOST, "evil.pt", f"{HOST}.evil.pt", DOMAIN, f"x.campo-a.{DOMAIN}",
                              "127.0.0.1", "*." + HOST):
                    with self.subTest(other=other):
                        self.assertEqual(await ask(other), 404)
                await hosted.set_status(self.hub.owner_url, "campo-a", "suspended", "t", actor="test:operator")
                try:
                    self.assertEqual(await ask(HOST), 404)  # a suspended field gets no certificate
                finally:
                    await hosted.set_status(self.hub.owner_url, "campo-a", "active", "t", actor="test:operator")
                await hosted.remove_custom_domain(self.hub.owner_url, "campo-a", "x", actor="test:operator")
                self.assertEqual(await ask(HOST), 404)
        finally:
            await app.close()

    async def test_the_commands(self) -> None:
        code, out, err = await asyncio.to_thread(operator, self.hub, "domain", "set", "campo-a", HOST, "--reason", "x")
        self.assertEqual((code, err), (0, ""))
        self.assertIn(f"TXT _atalaia-challenge.{HOST}", out)
        self.assertIn("atalaia-verify=", out)
        self.assertIn("hosted domain verify campo-a", out)
        code, out, err = await asyncio.to_thread(operator, self.hub, "domain", "verify", "campo-a")
        self.assertEqual(code, 1)
        self.assertIn("not verified", err)  # no real DNS for the test name: not there (or not answering)
        code, out, _ = await asyncio.to_thread(operator, self.hub, "list")
        self.assertIn(f"{HOST} (pending)", out)
        code, _, err = await asyncio.to_thread(operator, self.hub, "domain", "set", "campo-a", f"x.{DOMAIN}",
                                               "--reason", "x")
        self.assertEqual(code, 1)
        self.assertIn("hub's own domain", err)
        code, _, err = await asyncio.to_thread(operator, self.hub, "domain", "set", "campo-a", "--reason", "x")
        self.assertEqual(code, 1)
        self.assertIn("host name is missing", err)
        code, out, _ = await asyncio.to_thread(operator, self.hub, "domain", "remove", "campo-a", "--reason", "x")
        self.assertIn(f"Removed {HOST}", out)
        code, out, _ = await asyncio.to_thread(operator, self.hub, "domain", "remove", "campo-a", "--reason", "x")
        self.assertIn("had no custom host name", out)


class UpgradeTests(HubCase):
    """A hub made by the release before this one: ``hosted migrate`` brings the registry up, and until then the
    server refuses to start (it would not find the columns it reads)."""

    async def asyncSetUp(self) -> None:
        pass

    async def asyncTearDown(self) -> None:
        pass

    async def test_an_older_registry(self) -> None:
        await owner_script(self.hub, "DROP TABLE public.atalaia_quota_hits; ALTER TABLE public.atalaia_tenants "
                                     "DROP COLUMN quotas, DROP COLUMN custom_host, DROP COLUMN custom_host_status, "
                                     "DROP COLUMN custom_host_token, DROP COLUMN custom_host_verified_at")
        app = create_app(self.settings())
        with self.assertRaisesRegex(tenancy.RoleProblem, "older release.*hosted migrate"):
            async with app.router.lifespan_context(app):
                pass
        report = await hosted.check_hub(self.hub.owner_url, self.hub.app_role)
        self.assertTrue(any("older release" in p for p in report.problems), report.problems)
        done = await asyncio.to_thread(hosted.migrate_all, self.hub.owner_url, self.hub.app_role, "test:operator")
        self.assertEqual(done, ["campo-a", "campo-b"])
        self.assertEqual((await hosted.check_hub(self.hub.owner_url, self.hub.app_role)).problems, [])
        again = await asyncio.to_thread(hosted.migrate_all, self.hub.owner_url, self.hub.app_role, "test:operator")
        self.assertEqual(again, ["campo-a", "campo-b"])  # idempotent
        app = create_app(self.settings())
        async with app.router.lifespan_context(app):
            r = await httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                        base_url="https://campo-a.hub.test").get("/api/v1/fields")
            self.assertEqual(r.status_code, 401)


class DnsTests(unittest.TestCase):
    """The TXT lookup against a resolver of its own on localhost (UDP, with a truncated answer, then TCP)."""

    @staticmethod
    def answer(query: bytes, texts: list[bytes], rcode: int = 0, truncated: bool = False) -> bytes:
        records = b"".join(b"\xc0\x0c" + struct.pack("!HHIH", 16, 1, 60, len(t) + 1) + bytes([len(t)]) + t
                           for t in texts)
        flags = 0x8180 | rcode | (0x0200 if truncated else 0)
        header = query[:2] + struct.pack("!HHHHH", flags, 1, 0 if truncated else len(texts), 0, 0)
        return header + query[12:] + (b"" if truncated else records)

    def serve(self, texts: list[bytes], rcode: int = 0) -> tuple[int, threading.Thread, list[bytes]]:
        """A resolver on one port, UDP and TCP; with several records it answers UDP cut short, the rest over TCP."""
        queries: list[bytes] = []
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.bind(("127.0.0.1", 0))
        port = udp.getsockname()[1]
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp.bind(("127.0.0.1", port))
        tcp.listen(1)
        udp.settimeout(5)
        tcp.settimeout(5)
        cut = len(texts) > 1

        def run() -> None:
            try:
                data, peer = udp.recvfrom(512)
                queries.append(data)
                udp.sendto(self.answer(data, texts, rcode=rcode, truncated=cut), peer)
                if cut:
                    conn, _ = tcp.accept()
                    with conn:
                        size = struct.unpack("!H", conn.recv(2))[0]
                        query = conn.recv(size)
                        queries.append(query)
                        full = self.answer(query, texts)
                        conn.sendall(struct.pack("!H", len(full)) + full)
            except OSError:
                pass
            finally:
                udp.close()
                tcp.close()

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return port, thread, queries

    def test_a_txt_record(self) -> None:
        port, thread, queries = self.serve([b"atalaia-verify=abc"])
        self.assertEqual(dnsquery.txt("_atalaia-challenge.jogos.exemplo.pt.", ["127.0.0.1"], port=port),
                         ["atalaia-verify=abc"])
        thread.join(5)
        self.assertEqual(queries[0][12:], b"\x12_atalaia-challenge\x05jogos\x07exemplo\x02pt\x00\x00\x10\x00\x01")

    def test_a_truncated_answer_is_asked_again_over_tcp(self) -> None:
        port, thread, queries = self.serve([b"one", b"two"])
        self.assertEqual(dnsquery.txt("x.example.pt", ["127.0.0.1"], port=port), ["one", "two"])
        thread.join(5)
        self.assertEqual(len(queries), 2)

    def test_no_such_name_and_server_errors(self) -> None:
        port, thread, _ = self.serve([], rcode=3)
        self.assertEqual(dnsquery.txt("x.example.pt", ["127.0.0.1"], port=port), [])
        thread.join(5)
        port, thread, _ = self.serve([], rcode=2)  # SERVFAIL: no answer to trust
        with self.assertRaisesRegex(dnsquery.DnsError, "no DNS server answered"):
            dnsquery.txt("x.example.pt", ["127.0.0.1"], port=port)
        thread.join(5)
        with unittest.mock.patch.object(dnsquery, "nameservers", lambda: []), \
                self.assertRaisesRegex(dnsquery.DnsError, "no nameserver"):
            dnsquery.txt("x.example.pt")
        with self.assertRaises(dnsquery.DnsError):
            dnsquery.build_query("a" * 64 + ".example.pt", 1)

    def test_answers_that_do_not_match_are_refused(self) -> None:
        good = self.answer(dnsquery.build_query("x.example.pt", 7), [b"v"])
        self.assertEqual(dnsquery.parse_answer(good, 7, "x.example.pt"), (["v"], False))
        with self.assertRaisesRegex(dnsquery.DnsError, "not the answer"):
            dnsquery.parse_answer(good, 8, "x.example.pt")  # another question's id
        self.assertEqual(dnsquery.parse_answer(good, 7, "other.example.pt"), ([], False))  # another owner's records
        with self.assertRaises(dnsquery.DnsError):
            dnsquery.parse_answer(good[:20], 7, "x.example.pt")
        loop = good[:12] + b"\xc0\x0c" + good[14:]  # a name that points at itself
        with self.assertRaises(dnsquery.DnsError):
            dnsquery.parse_answer(loop, 7, "x.example.pt")

    def test_resolv_conf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resolv.conf"
            path.write_text("# comment\nnameserver 192.0.2.1\nsearch x\nnameserver fe80::1%eth0\nnameserver\n")
            self.assertEqual(dnsquery.nameservers(path), ["192.0.2.1", "fe80::1"])
            self.assertEqual(dnsquery.nameservers(Path(tmp) / "missing"), [])


if __name__ == "__main__":
    unittest.main()
