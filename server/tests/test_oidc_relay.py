# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hub-level social login callback of hosted mode (decision LG-14, ADR-P4-13), on PostgreSQL 16.

One redirect address on the hub's own host (``https://hub.test/api/v1/auth/oidc/callback``) stands in for every
field's; the hub reads the state it signed, looks the field up in its registry and sends the browser on to the
field's own callback, which does what it always did. The provider is the fake of tests/login_fakes.py. Tried here:
a whole login through the relay (and that only the field that began it gets an account), the app's return-to-app
flow, the custom host name, the cross-field replay, an unknown or suspended field, an expired or altered state, the
open redirect that is not there, and the relay being off by default.

    python3 tools/docker_server.py test tests.test_oidc_relay
"""

from __future__ import annotations

import dataclasses
import secrets
import tempfile
import time
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

import httpx

from atalaia_server import hosted, oidc
from atalaia_server.config import ConfigError, OidcClient, Settings

from .login_fakes import FakeIdp
from .test_hosted_registry import owner
from .test_tenants import DOMAIN, HubCase

HUB_CALLBACK = f"https://{DOMAIN}/api/v1/auth/oidc/callback"
CUSTOM = "jogos.exemplo.pt"


class RelayCase(HubCase):
    relay = True

    def settings(self, url: Optional[str] = None) -> Settings:
        base = super().settings(url)
        clients = (OidcClient("google", "google-id", client_secret="google-secret"),
                   OidcClient("microsoft", "ms-id", client_secret="ms-secret", tenant="common"))
        return dataclasses.replace(base, oidc=clients, oidc_relay=self.relay)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.idp = FakeIdp()
        self.app.state.oidc.http = self.idp
        self.hubc = self.client("", DOMAIN)
        self.before = {t.slug: await self.accounts(t) for t in (self.ta, self.tb)}

    # One login, step by step ---------------------------------------------------------------------

    async def start(self, client: httpx.AsyncClient, provider: str = "google", **body: Any) -> dict[str, str]:
        r = await client.post(f"/api/v1/auth/oidc/{provider}/start", json={"purpose": "login", "consent": True, **body})
        self.assertEqual(r.status_code, 200, r.text)
        return self.idp.authorize(r.json()["authorization_url"])

    def grant(self, provider: str, params: dict[str, str], subject: str) -> str:
        client_id = {"google": "google-id", "microsoft": "ms-id"}[provider]
        return self.idp.grant(params, self.idp.claims(provider, client_id, subject, params["nonce"]))

    async def at_hub(self, params: dict[str, str], code: str, **extra: str) -> httpx.Response:
        """The provider sends the browser to the redirect address it was given (the hub's)."""
        self.assertTrue(params["redirect_uri"].startswith(f"https://{DOMAIN}/"), params["redirect_uri"])
        return await self.hubc.get(urlsplit(params["redirect_uri"]).path,
                                   params={"code": code, "state": params["state"], **extra})

    @staticmethod
    def where(r: httpx.Response) -> tuple[str, str, dict[str, str]]:
        assert r.status_code == 303, (r.status_code, r.text)
        loc = urlsplit(r.headers["location"])
        return loc.netloc, loc.path, {k: v[0] for k, v in parse_qs(loc.query).items()}

    async def follow(self, client: httpx.AsyncClient, r: httpx.Response) -> httpx.Response:
        _, path, query = self.where(r)
        return await client.get(path, params=query)

    async def accounts(self, tenant: Any) -> int:
        return (await self.sql(tenant, "SELECT count(*) FROM user_identities"))[0][0]

    async def new_accounts(self, tenant: Any) -> int:
        return await self.accounts(tenant) - self.before[tenant.slug]


class RelayTests(RelayCase):
    async def test_a_whole_login_goes_through_the_hubs_one_address(self) -> None:
        params = await self.start(self.a)
        self.assertEqual(params["redirect_uri"], HUB_CALLBACK)
        self.assertTrue(params["state"].startswith("r1.campo-a.") or ".campo-a.google.s." in params["state"])
        code = self.grant("google", params, "sub-relay-1")
        r = await self.at_hub(params, code)
        host, path, query = self.where(r)
        self.assertEqual((host, path), (f"campo-a.{DOMAIN}", "/api/v1/auth/oidc/google/callback"))
        self.assertEqual(set(query), {"code", "state"})
        # What the hub answers carries nothing else: no cookie, no body, nothing cached (a 303 has no page that could
        # refer the code on).
        self.assertNotIn("set-cookie", r.headers)
        self.assertIn("no-store", r.headers["cache-control"])
        self.assertEqual(r.content, b"")
        back = await self.follow(self.a, r)
        self.assertEqual(back.status_code, 303, back.text)
        loc = urlsplit(back.headers["location"])
        self.assertEqual(loc.path, "/staff/login")
        self.assertTrue(loc.fragment.startswith("oidc="), back.headers["location"])
        done = await self.a.post("/api/v1/auth/oidc/complete", json={"ticket": loc.fragment[5:]})
        self.assertEqual(done.status_code, 200, done.text)
        # The token endpoint was told the hub's address (the provider insists it matches), and only field A has
        # an account: the other field never saw the login.
        self.assertEqual(await self.new_accounts(self.ta), 1)
        self.assertEqual(await self.new_accounts(self.tb), 0)

    async def test_the_same_works_for_every_provider_and_field(self) -> None:
        for client, tenant, slug, provider in ((self.a, self.ta, "campo-a", "microsoft"),
                                               (self.b, self.tb, "campo-b", "google")):
            with self.subTest(slug=slug, provider=provider):
                params = await self.start(client, provider)
                self.assertEqual(params["redirect_uri"], HUB_CALLBACK)
                r = await self.at_hub(params, self.grant(provider, params, f"sub-{slug}"))
                self.assertEqual(self.where(r)[:2], (f"{slug}.{DOMAIN}", f"/api/v1/auth/oidc/{provider}/callback"))
                back = await self.follow(client, r)
                self.assertTrue(urlsplit(back.headers["location"]).fragment.startswith("oidc="))

    async def test_the_apps_return_to_the_app_works_through_the_relay(self) -> None:
        r = await self.a.post("/api/v1/auth/oidc/google/start", json={
            "purpose": "login", "consent": True, "return_to": f"https://campo-a.{DOMAIN}/app/oidc?s=abc123"})
        self.assertEqual(r.status_code, 200, r.text)
        browser_url = urlsplit(r.json()["browser_url"])
        self.assertEqual(browser_url.netloc, f"campo-a.{DOMAIN}")
        browser = self.client("campo-a")   # the phone's browser: no cookie yet, the app's address sets it
        went = await browser.get(f"{browser_url.path}?{browser_url.query}")
        self.assertEqual(went.status_code, 303, went.text)
        params = self.idp.authorize(went.headers["location"])
        self.assertEqual(params["redirect_uri"], HUB_CALLBACK)
        relayed = await self.at_hub(params, self.grant("google", params, "app-user"))
        back = await self.follow(browser, relayed)
        loc = urlsplit(back.headers["location"])
        self.assertEqual((loc.path, loc.query), ("/app/oidc", "s=abc123"))
        self.assertTrue(loc.fragment.startswith("oidc="))
        # Without the browser's cookie (another browser) the field refuses, as before.
        again = await self.start(self.a, return_to="/app/oidc?s=zzz")
        other = await self.at_hub(again, self.grant("google", again, "app-user-2"))
        refused = await self.follow(self.client("campo-a"), other)
        self.assertIn("oidc_error=state_invalid", refused.headers["location"])

    async def test_a_custom_host_name_gets_its_own_login_back(self) -> None:
        await hosted.set_custom_domain(self.hub.owner_url, "campo-a", CUSTOM, DOMAIN, "test", actor="test:operator")
        await owner(self.hub, "UPDATE public.atalaia_tenants SET custom_host_status = 'active' WHERE slug = 'campo-a'")
        try:
            custom = self.client("", CUSTOM)
            params = await self.start(custom)
            self.assertEqual(params["redirect_uri"], HUB_CALLBACK)     # one address, whatever the name
            r = await self.at_hub(params, self.grant("google", params, "sub-custom"))
            self.assertEqual(self.where(r)[:2], (CUSTOM, "/api/v1/auth/oidc/google/callback"))
            back = await self.follow(custom, r)
            self.assertTrue(urlsplit(back.headers["location"]).fragment.startswith("oidc="))
            # The name is taken away before the answer comes back: the hub falls back to the field's own host
            # (where the browser has no binding cookie, so the field refuses), never to the name.
            params = await self.start(custom)
            await owner(self.hub, "UPDATE public.atalaia_tenants SET custom_host = NULL, custom_host_status = NULL, "
                                  "custom_host_token = NULL")
            r = await self.at_hub(params, self.grant("google", params, "sub-custom-2"))
            self.assertEqual(self.where(r)[0], f"campo-a.{DOMAIN}")
        finally:
            await owner(self.hub, "UPDATE public.atalaia_tenants SET custom_host = NULL, custom_host_status = NULL, "
                                  "custom_host_token = NULL")

    # Refusals ---------------------------------------------------------------------------------------

    async def test_a_result_made_for_one_field_is_refused_at_another(self) -> None:
        pa = await self.start(self.a)
        pb = await self.start(self.b)
        code_a = self.grant("google", pa, "sub-a")
        r = await self.at_hub(pa, code_a)
        _, path, query = self.where(r)
        # Field A's relayed result, put to field B (an attacker's page sending the browser there, or a mistake):
        # B refuses it, and A's login is untouched.
        replay = await self.b.get(path, params=query)
        self.assertIn("oidc_error=state_invalid", replay.headers["location"])
        self.assertNotIn("oidc=", urlsplit(replay.headers["location"]).fragment)
        # B's own login with A's state in it (B's cookie, A's state): refused as well.
        mixed = await self.b.get(path, params={"code": self.grant("google", pb, "sub-b"), "state": pa["state"]})
        self.assertIn("oidc_error=state_invalid", mixed.headers["location"])
        # A is still able to finish what it began, once.
        ok = await self.a.get(path, params=query)
        self.assertTrue(urlsplit(ok.headers["location"]).fragment.startswith("oidc="))
        twice = await self.a.get(path, params=query)
        self.assertIn("oidc_error=state_invalid", twice.headers["location"])
        self.assertEqual(await self.new_accounts(self.tb), 0)

    async def test_a_state_for_another_provider_is_refused_at_the_field(self) -> None:
        params = await self.start(self.a, "google")
        r = await self.a.get("/api/v1/auth/oidc/microsoft/callback",
                             params={"code": self.grant("google", params, "x"), "state": params["state"]})
        self.assertIn("oidc_error=state_invalid", r.headers["location"])

    async def test_an_unknown_field_is_refused_and_nothing_is_forwarded(self) -> None:
        key = self.app.state.keys.oidc_relay
        now = int(self.app.state.clock())
        for slug in ("campo-zz", "campo-c"):
            state = oidc.make_relay_state(key, slug, "google", False, now + 600)
            r = await self.hubc.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": state})
            with self.subTest(slug=slug):
                self.assertEqual(r.status_code, 400)
                self.assertNotIn("location", r.headers)

    async def test_a_suspended_field_gets_nothing(self) -> None:
        params = await self.start(self.a)
        code = self.grant("google", params, "sub-susp")
        await hosted.set_status(self.hub.owner_url, "campo-a", "suspended", "test", actor="test:operator")
        try:
            r = await self.at_hub(params, code)
            self.assertEqual(r.status_code, 400)
            self.assertNotIn("location", r.headers)
            # The same answer as for a field that does not exist: the relay tells a prober nothing.
            gone = oidc.make_relay_state(self.app.state.keys.oidc_relay, "campo-zz", "google", False,
                                         int(self.app.state.clock()) + 600)
            other = await self.hubc.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": gone})
            self.assertEqual((r.status_code, r.text), (other.status_code, other.text))
        finally:
            await hosted.set_status(self.hub.owner_url, "campo-a", "active", "test", actor="test:operator")
        again = await self.at_hub(params, code)       # active again: the same result goes through
        self.assertEqual(again.status_code, 303)

    async def test_an_expired_result_is_refused(self) -> None:
        params = await self.start(self.a)
        code = self.grant("google", params, "sub-late")
        t0 = time.time()
        self.app.state.clock = lambda: t0 + 601     # ten minutes and a second later
        r = await self.at_hub(params, code)
        self.assertEqual(r.status_code, 400)
        self.assertNotIn("location", r.headers)
        # A state signed with an expiry in the past is no better.
        old = oidc.make_relay_state(self.app.state.keys.oidc_relay, "campo-a", "google", False, int(t0) - 1)
        self.app.state.clock = lambda: t0
        self.assertEqual((await self.hubc.get("/api/v1/auth/oidc/callback",
                                              params={"code": "c", "state": old})).status_code, 400)
        # And the field itself refuses an expired state that reaches it directly.
        self.app.state.clock = lambda: t0 + 601
        direct = await self.a.get("/api/v1/auth/oidc/google/callback", params={"code": code, "state": params["state"]})
        self.assertIn("oidc_error=state_invalid", direct.headers["location"])

    async def test_a_changed_or_forged_state_is_refused(self) -> None:
        params = await self.start(self.a)
        code = self.grant("google", params, "sub-forge")
        parts = params["state"].split(".")
        bad = {"another field": ".".join(parts[:2] + ["campo-b"] + parts[3:]),
               "another provider": ".".join(parts[:3] + ["microsoft"] + parts[4:]),
               "custom flag": ".".join(parts[:4] + ["c"] + parts[5:]),
               "later expiry": ".".join(parts[:5] + [str(int(parts[5]) + 86400)] + parts[6:]),
               "no mac": ".".join(parts[:6]),
               "another key": oidc.make_relay_state(secrets.token_bytes(32), "campo-b", "google", False,
                                                    int(parts[5])),
               "plain": secrets.token_urlsafe(32), "empty": ""}
        for why, state in bad.items():
            r = await self.hubc.get("/api/v1/auth/oidc/callback", params={"code": code, "state": state})
            with self.subTest(why):
                self.assertEqual(r.status_code, 400)
                self.assertNotIn("location", r.headers)
        self.assertEqual((await self.hubc.get("/api/v1/auth/oidc/callback", params={"code": code})).status_code, 400)

    async def test_the_target_is_never_taken_from_the_request(self) -> None:
        params = await self.start(self.a)
        code = self.grant("google", params, "sub-open")
        evil = "https://evil.example"
        r = await self.hubc.get("/api/v1/auth/oidc/callback", params={
            "code": code, "state": params["state"], "redirect_uri": evil, "return_to": evil, "host": "evil.example",
            "next": evil, "url": evil})
        host, path, query = self.where(r)
        self.assertEqual((host, path, set(query)), (f"campo-a.{DOMAIN}", "/api/v1/auth/oidc/google/callback",
                                                    {"code", "state"}))
        # A Host header of another name does not make the relay answer for it either.
        r = await self.client("", "evil.example").get("/api/v1/auth/oidc/callback",
                                                      params={"code": code, "state": params["state"]})
        self.assertEqual(r.status_code, 404)

    async def test_a_denied_login_passes_only_a_fixed_word_on(self) -> None:
        params = await self.start(self.a)
        r = await self.hubc.get("/api/v1/auth/oidc/callback", params={
            "error": "access_denied", "error_description": "<script>alert(1)</script>", "state": params["state"]})
        _, _, query = self.where(r)
        self.assertEqual(query, {"state": params["state"], "error": "denied"})
        back = await self.follow(self.a, r)
        self.assertIn("oidc_error=denied", back.headers["location"])

    async def test_the_hub_callback_is_not_a_field_page(self) -> None:
        # Reached through a field's host the relay does not answer (it has no tenant to be in), and the hub's host
        # serves nothing else.
        params = await self.start(self.a)
        r = await self.a.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": params["state"]})
        self.assertEqual(r.status_code, 404)
        self.assertEqual((await self.hubc.get("/api/v1/fields")).status_code, 404)

    async def test_each_login_keeps_its_own_state_and_cookie(self) -> None:
        # The state and the nonce stay bound to the browser that began: another browser at the field has no cookie.
        params = await self.start(self.a)
        r = await self.at_hub(params, self.grant("google", params, "sub-csrf"))
        refused = await self.follow(self.client("campo-a"), r)
        self.assertIn("oidc_error=state_invalid", refused.headers["location"])
        self.assertEqual(await self.new_accounts(self.ta), 0)


class RelayOffTests(RelayCase):
    relay = False

    async def test_off_by_default_each_field_keeps_its_own_address(self) -> None:
        params = await self.start(self.a)
        self.assertEqual(params["redirect_uri"], f"https://campo-a.{DOMAIN}/api/v1/auth/oidc/google/callback")
        self.assertFalse(params["state"].startswith("r1."))
        code = self.grant("google", params, "sub-own")
        r = await self.a.get("/api/v1/auth/oidc/google/callback", params={"code": code, "state": params["state"]})
        self.assertTrue(urlsplit(r.headers["location"]).fragment.startswith("oidc="))
        # And the hub's address answers nothing.
        r = await self.hubc.get("/api/v1/auth/oidc/callback", params={"code": "c", "state": params["state"]})
        self.assertEqual((r.status_code, r.json()), (404, {"detail": "unknown_field"}))
        # A relay state made anyway is not accepted at a field while the relay is off.
        state = oidc.make_relay_state(self.app.state.keys.oidc_relay, "campo-a", "google", False,
                                      int(self.app.state.clock()) + 600)
        r = await self.a.get("/api/v1/auth/oidc/google/callback", params={"code": "c", "state": state})
        self.assertIn("oidc_error=state_invalid", r.headers["location"])


class RelayConfigTests(HubCase):
    def test_the_relay_is_only_for_hosted_mode(self) -> None:
        with tempfile.TemporaryDirectory():
            with self.assertRaisesRegex(ConfigError, "ATALAIA_OIDC_RELAY is only for hosted mode"):
                Settings(database_url="postgresql+asyncpg://x/y", secret_key="k" * 40, oidc_relay=True)
            env = {"ATALAIA_DATABASE_URL": "postgresql+asyncpg://x/y", "ATALAIA_SECRET_KEY": "k" * 40,
                   "ATALAIA_HOSTED": "on", "ATALAIA_HOSTED_DOMAIN": "hub.example.pt", "ATALAIA_OIDC_RELAY": "on"}
            self.assertTrue(Settings.from_env(env).oidc_relay)
            del env["ATALAIA_OIDC_RELAY"]
            self.assertFalse(Settings.from_env(env).oidc_relay)

    def test_a_state_round_trips_and_has_a_bounded_size(self) -> None:
        key = secrets.token_bytes(32)
        state = oidc.make_relay_state(key, "a" * 40, "microsoft", True, 2_000_000_000)
        self.assertLessEqual(len(state), oidc.MAX_STATE)
        got = oidc.read_relay_state(key, state, 1_000_000_000)
        self.assertEqual((got.slug, got.provider, got.custom, got.expires), ("a" * 40, "microsoft", True, 2_000_000_000))
        with self.assertRaises(oidc.OidcError):
            oidc.read_relay_state(key, state, 2_000_000_000)
