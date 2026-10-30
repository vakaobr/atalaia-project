# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Social login, passkeys, optional passwords and the staff second factor, end to end on PostgreSQL 16
(decisions LG-*). The provider is a fake that signs test tokens (tests/login_fakes.py), the authenticator a
soft one; the app, the database and every endpoint are the real ones."""

from __future__ import annotations

import dataclasses
import io
import json
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional
from unittest import mock
from urllib.parse import parse_qs, urlsplit

import httpx

from atalaia_server import personal_data, quotas
from atalaia_server.config import OidcClient, Settings

from .base import METRICS_TOKEN, PASSWORD, SECRET_KEY, AppTestCase
from .login_fakes import FakeIdp, SoftAuthenticator, apple_key_pem

ORIGIN = "https://server.test"
CLIENT_IDS = {"google": "google-id", "microsoft": "ms-id", "apple": "apple.services.id"}


def bearer(body: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {body['access_token']}"}


class LoginTestCase(AppTestCase):
    password_login = True
    providers = True

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.keydir = tempfile.TemporaryDirectory()
        cls.key_file = Path(cls.keydir.name) / "AuthKey.p8"
        cls.key_file.write_bytes(apple_key_pem())

    @classmethod
    def tearDownClass(cls) -> None:
        cls.keydir.cleanup()
        super().tearDownClass()

    def settings(self) -> Settings:
        clients = (OidcClient("google", "google-id", client_secret="google-secret"),
                   OidcClient("microsoft", "ms-id", client_secret="ms-secret", tenant="common"),
                   OidcClient("apple", "apple.services.id", team_id="TEAM123456", key_id="KEY1234567",
                              key_file=str(self.key_file))) if self.providers else ()
        return Settings(database_url=self.database_url, secret_key=SECRET_KEY, metrics_token=METRICS_TOKEN,
                        db_timeout_s=2.0, purge_hour=self.purge_hour, password_login=self.password_login,
                        oidc=clients)

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.idp = FakeIdp()
        self.app.state.oidc.http = self.idp

    # Social login ---------------------------------------------------------------------------------

    async def begin(self, provider: str = "google", *, client: Optional[httpx.AsyncClient] = None,
                    headers: Optional[dict[str, str]] = None, **body: Any) -> tuple[dict[str, str], httpx.Response]:
        client = client or self.client
        r = await client.post(f"/api/v1/auth/oidc/{provider}/start",
                              json={"purpose": "login", "consent": True, **body}, headers=headers or {})
        params = self.idp.authorize(r.json()["authorization_url"]) if r.status_code == 200 else {}
        return params, r

    async def callback(self, provider: str, params: dict[str, str], subject: str, *,
                       client: Optional[httpx.AsyncClient] = None, state: Optional[str] = None,
                       claims: Optional[dict[str, Any]] = None) -> httpx.Response:
        code = self.idp.grant(params, self.idp.claims(provider, CLIENT_IDS[provider], subject, params["nonce"],
                                                      **(claims or {})))
        return await (client or self.client).get(f"/api/v1/auth/oidc/{provider}/callback",
                                                  params={"code": code, "state": state or params["state"]})

    @staticmethod
    def landed(r: httpx.Response) -> tuple[str, dict[str, str], str]:
        """Where a callback sent the browser: the path, the query and the fragment."""
        assert r.status_code == 303, (r.status_code, r.text)
        location = urlsplit(r.headers["location"])
        return location.path, {k: v[0] for k, v in parse_qs(location.query).items()}, location.fragment

    async def social(self, provider: str, subject: str, *, client: Optional[httpx.AsyncClient] = None,
                     consent: bool = True) -> dict[str, Any]:
        """A whole social login: the session's JSON."""
        client = client or self.client
        params, r = await self.begin(provider, client=client, consent=consent)
        self.assertEqual(r.status_code, 200, r.text)
        _, query, fragment = self.landed(await self.callback(provider, params, subject, client=client))
        self.assertEqual(query.get("oidc_error"), None, query)
        self.assertTrue(fragment.startswith("oidc="), fragment)
        r = await client.post("/api/v1/auth/oidc/complete", json={"ticket": fragment[5:]})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def link(self, provider: str, subject: str, headers: dict[str, str], password: str = PASSWORD) -> dict[str, str]:
        params, r = await self.begin(provider, headers=headers, purpose="link", password=password)
        self.assertEqual(r.status_code, 200, r.text)
        return self.landed(await self.callback(provider, params, subject))[1]

    # Passkeys -------------------------------------------------------------------------------------

    async def add_passkey(self, headers: dict[str, str], authenticator: Optional[SoftAuthenticator] = None,
                          password: str = PASSWORD, name: Optional[str] = None) -> tuple[SoftAuthenticator, httpx.Response]:
        authenticator = authenticator or SoftAuthenticator()
        r = await self.client.post("/api/v1/me/passkeys/options", json={"password": password}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        options = r.json()
        credential = authenticator.create(options["options"], ORIGIN)
        r = await self.client.post("/api/v1/me/passkeys", headers=headers, json={
            "challenge_token": options["challenge_token"], "credential": credential, **({"name": name} if name else {})})
        return authenticator, r

    async def second_factor(self, headers: dict[str, str]) -> None:
        """Marks this session as having passed a second factor, as a step-up would (SR-1): a test that is not about
        the step-up itself uses it once the account has a passkey and goes on changing its login methods."""
        me = (await self.client.get("/api/v1/me", headers=headers)).json()
        await self.fetch("UPDATE sessions SET mfa = true WHERE user_id = $1", uuid.UUID(me["id"]))

    async def passkey_login_parts(self) -> dict[str, Any]:
        r = await self.client.post("/api/v1/auth/passkey/login/options")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def passkey_login(self, authenticator: SoftAuthenticator, **kw: Any) -> httpx.Response:
        parts = await self.passkey_login_parts()
        return await self.client.post("/api/v1/auth/passkey/login", json={
            "challenge_token": parts["challenge_token"],
            "credential": authenticator.get(parts["options"], kw.pop("origin", ORIGIN), **kw)})

    async def audit(self, action: str) -> list[Any]:
        return [json.loads(r["details"]) if r["details"] else None
                for r in await self.fetch("SELECT details FROM audit_log WHERE action = $1 ORDER BY id", action)]

    async def user_by(self, subject: str, provider: str = "google") -> Any:
        rows = await self.fetch("SELECT u.* FROM users u JOIN user_identities i ON i.user_id = u.id "
                                "WHERE i.provider = $1 AND i.subject = $2", provider, subject)
        return rows[0] if rows else None

    async def age_confirmation(self) -> None:
        await self.fetch("UPDATE sessions SET confirmed_at = now() - interval '11 minutes'")


SHA = ":".join(["AB", "CD", "EF", "01"] * 8)


class AppLinkTests(LoginTestCase):
    """What the Android and iOS apps need from the site (decision PKA-1): the two well-known files, only when
    configured, and a social login that returns to the app's own path."""

    def settings(self) -> Settings:
        from dataclasses import replace
        base = super().settings()
        return replace(base, app_android_package="org.atalaia.app", app_android_sha256=(SHA, SHA.lower()),
                       app_ios_app_ids=("ABCDE12345.org.atalaia.app",))

    async def test_assetlinks_names_the_app_and_its_certificates(self) -> None:
        r = await self.client.get("/.well-known/assetlinks.json")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("application/json"))
        target = r.json()[0]
        self.assertIn("delegate_permission/common.handle_all_urls", r.json()[0]["relation"])
        self.assertIn("delegate_permission/common.get_login_creds", r.json()[0]["relation"])
        self.assertEqual(target["target"], {"namespace": "android_app", "package_name": "org.atalaia.app",
                                            "sha256_cert_fingerprints": [SHA, SHA]})

    async def test_the_apple_file_has_webcredentials_and_applinks(self) -> None:
        r = await self.client.get("/.well-known/apple-app-site-association")
        self.assertEqual(r.status_code, 200)
        ids = ["ABCDE12345.org.atalaia.app"]
        self.assertEqual(r.json(), {
            "applinks": {"details": [{"appIDs": ids, "components": [{"/": "/app/*"}]}]},
            "webcredentials": {"apps": ids}})

    async def test_a_social_login_can_return_to_the_apps_path(self) -> None:
        for wanted in ("/app/oidc", f"{ORIGIN}/app/oidc", "/app/oidc?x=1"):
            with self.subTest(wanted=wanted):
                answer = await self.app_start(return_to=wanted)
                browser = self.other_client()
                r = await browser.get(answer["browser_url"])
                params = self.idp.authorize(r.headers["location"])
                path, query, fragment = self.landed(await self.callback("google", params, f"app-{wanted}",
                                                                        client=browser))
                self.assertEqual(path, "/app/oidc")
                self.assertTrue(fragment.startswith("oidc="), fragment)
                self.assertEqual(query.get("oidc_error"), None)
                done = await browser.post("/api/v1/auth/oidc/complete", json={"ticket": fragment[5:]})
                self.assertEqual(done.status_code, 200, done.text)
        # Nothing else is a place to send the browser (and it has no address of the app's browser).
        for wanted in ("https://evil.example/app/oidc", "//evil.example/app/oidc", "/app/oidc/../staff/x",
                       "/app/other", "/app/oidcx", "/app/oidc#x", "https://evil.example.app/app/oidc"):
            with self.subTest(wanted=wanted):
                params, r = await self.begin("google", return_to=wanted)
                self.assertNotIn("browser_url", r.json())
                path, _, _ = self.landed(await self.callback("google", params, f"s-{wanted}"))
                self.assertEqual(path, "/staff/login")

    async def app_start(self, provider: str = "google", **body: Any) -> dict[str, Any]:
        r = await self.client.post(f"/api/v1/auth/oidc/{provider}/start", json={
            "purpose": "login", "consent": True, **{"return_to": f"{ORIGIN}/app/oidc?s=abc123", **body}})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertNotIn("set-cookie", r.headers)  # it would land in the app, not in the browser
        return r.json()

    async def test_the_apps_browser_gets_the_binding_cookie_and_goes_on(self) -> None:
        answer = await self.app_start()
        self.assertTrue(answer["browser_url"].startswith(f"{ORIGIN}/api/v1/auth/oidc/google/browser?"))
        # A fresh browser: its own cookie jar, as the Custom Tab's.
        async with self.other_client() as browser:
            r = await browser.get(answer["browser_url"])
            self.assertEqual(r.status_code, 303, r.text)
            self.assertEqual(r.headers["location"], answer["authorization_url"])
            self.assertIn("__Secure-atalaia_oidc", r.headers["set-cookie"])
            self.assertIn("samesite=lax", r.headers["set-cookie"].lower())
            params = self.idp.authorize(r.headers["location"])
            path, query, fragment = self.landed(await self.callback("google", params, "app-user", client=browser))
            self.assertEqual((path, query), ("/app/oidc", {"s": "abc123"}))
            done = await browser.post("/api/v1/auth/oidc/complete", json={"ticket": fragment[5:]})
            self.assertEqual(done.status_code, 200, done.text)
        # Without the browser's cookie the callback is refused, as for the web.
        answer = await self.app_start()
        params = self.idp.authorize(answer["authorization_url"])
        path, query, _ = self.landed(await self.callback("google", params, "app-user", client=self.other_client()))
        self.assertEqual((path, query.get("oidc_error")), ("/app/oidc", "state_invalid"))

    async def test_the_browser_address_is_for_the_app_that_began_it(self) -> None:
        answer = await self.app_start()
        url = urlsplit(answer["browser_url"])
        query = parse_qs(url.query)
        async with self.other_client() as browser:
            for label, path, params in (
                    ("wrong binding", url.path, {"x": "nope", "s": query["s"][0]}),
                    ("wrong state", url.path, {"x": query["x"][0], "s": "nope"}),
                    ("nothing", url.path, {}),
                    ("another provider", "/api/v1/auth/oidc/microsoft/browser", {"x": query["x"][0], "s": query["s"][0]})):
                with self.subTest(label):
                    r = await browser.get(path, params=params)
                    self.assertEqual(r.status_code, 400)
                    self.assertNotIn("set-cookie", r.headers)
        # A login begun on the web has no such address.
        params, r = await self.begin("google")
        self.assertNotIn("browser_url", r.json())
        # An expired attempt.
        await self.fetch("UPDATE oidc_logins SET expires_at = now() - interval '1 minute'")
        async with self.other_client() as browser:
            self.assertEqual((await browser.get(answer["browser_url"])).status_code, 400)

    async def test_linking_from_the_app_asks_before_it_goes_on(self) -> None:
        _, name, _ = await self.make_user()
        login = (await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})).json()
        r = await self.client.post("/api/v1/auth/oidc/google/start", headers=bearer(login), json={
            "purpose": "link", "password": PASSWORD, "return_to": f"{ORIGIN}/app/oidc?s=lnk"})
        self.assertEqual(r.status_code, 200, r.text)
        answer = r.json()
        async with self.other_client() as browser:
            page = await browser.get(answer["browser_url"])
            self.assertEqual(page.status_code, 200)
            self.assertNotIn("set-cookie", page.headers)  # nothing is set until the person taps
            self.assertIn(name, page.text)
            self.assertIn("Google", page.text)
            go = answer["browser_url"] + "&go=1"
            r = await browser.get(go)
            self.assertEqual(r.status_code, 303, r.text)
            self.assertIn("__Secure-atalaia_oidc", r.headers["set-cookie"])
            params = self.idp.authorize(r.headers["location"])
            path, query, _ = self.landed(await self.callback("google", params, "linked-subject", client=browser))
            self.assertEqual((path, query), ("/app/oidc", {"s": "lnk", "oidc": "linked"}))
        user = await self.user_by("linked-subject")
        self.assertEqual(user["username"], name)

    async def test_a_passkey_made_and_used_in_the_app_is_accepted(self) -> None:
        """The origin Credential Manager gives an app is the hash of its signing certificate, from the settings."""
        from atalaia_server.passkeys import android_origin
        origin = android_origin(SHA)
        self.assertEqual(origin, "android:apk-key-hash:" + "q83vAavN7wGrze8Bq83vAavN7wGrze8Bq83vAavN7wE")
        self.assertEqual(self.app.state.settings.app_origins, (origin, origin))
        _, name, _ = await self.make_user()
        headers = bearer((await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})).json())
        authenticator = SoftAuthenticator()
        r = await self.client.post("/api/v1/me/passkeys/options", json={"password": PASSWORD}, headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        options = r.json()
        r = await self.client.post("/api/v1/me/passkeys", headers=headers, json={
            "challenge_token": options["challenge_token"], "credential": authenticator.create(options["options"], origin)})
        self.assertEqual(r.status_code, 201, r.text)
        parts = await self.passkey_login_parts()
        r = await self.client.post("/api/v1/auth/passkey/login", json={
            "challenge_token": parts["challenge_token"], "credential": authenticator.get(parts["options"], origin)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["mfa"])
        # Any other app origin is refused.
        other = android_origin(":".join(["11"] * 32))
        parts = await self.passkey_login_parts()
        r = await self.client.post("/api/v1/auth/passkey/login", json={
            "challenge_token": parts["challenge_token"], "credential": authenticator.get(parts["options"], other)})
        self.assertEqual(r.status_code, 401, r.text)

    async def test_a_browser_that_lands_there_sees_a_short_page_with_no_script(self) -> None:
        r = await self.client.get("/app/oidc", params={"oidc": "linked"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertNotIn("<script", r.text.lower())


class AppLinksOffTests(LoginTestCase):
    """With no app configured the server says nothing about one."""

    async def test_an_app_origin_is_not_accepted(self) -> None:
        from atalaia_server.passkeys import android_origin
        self.assertEqual(self.app.state.settings.app_origins, ())
        _, name, _ = await self.make_user()
        headers = bearer((await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})).json())
        r = await self.client.post("/api/v1/me/passkeys/options", json={"password": PASSWORD}, headers=headers)
        options = r.json()
        r = await self.client.post("/api/v1/me/passkeys", headers=headers, json={
            "challenge_token": options["challenge_token"],
            "credential": SoftAuthenticator().create(options["options"], android_origin(SHA))})
        self.assertEqual(r.status_code, 400, r.text)

    async def test_nothing_is_served(self) -> None:
        for path in ("/.well-known/assetlinks.json", "/.well-known/apple-app-site-association"):
            with self.subTest(path=path):
                self.assertEqual((await self.client.get(path)).status_code, 404)


class SocialLoginTests(LoginTestCase):
    async def test_what_the_server_offers(self) -> None:
        r = await self.client.get("/api/v1/auth/methods")
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.json(), {"password_login": True, "passkeys": True, "oidc": [
            {"provider": "google", "label": "Google"}, {"provider": "microsoft", "label": "Microsoft"},
            {"provider": "apple", "label": "Apple"}]})

    async def test_the_first_login_with_a_new_subject_makes_an_account(self) -> None:
        for provider in ("google", "microsoft", "apple"):
            with self.subTest(provider=provider):
                body = await self.social(provider, f"{provider}-subject-1")
                self.assertFalse(body["mfa"])  # a social login alone never counts as the second factor
                self.assertFalse(body["user"]["has_password"])
                self.assertIsNone(body["user"]["email"])
                row = await self.user_by(f"{provider}-subject-1", provider)
                self.assertIsNone(row["password_hash"])
                self.assertIsNone(row["email"])
                self.assertTrue(row["username"].startswith("user-"))
                self.assertIsNotNone(row["gdpr_consent_at"])
                consents = await self.fetch("SELECT purpose, notice_version FROM consents WHERE user_id = $1", row["id"])
                self.assertEqual([tuple(c) for c in consents], [("account", self.app.state.settings.privacy_notice_version)])
                identities = await self.fetch("SELECT provider, subject FROM user_identities WHERE user_id = $1", row["id"])
                self.assertEqual([tuple(i) for i in identities], [(provider, f"{provider}-subject-1")])
        registered = await self.audit("register")
        self.assertEqual([d["method"] for d in registered], ["oidc"] * 3)
        logged = await self.audit("login")
        self.assertEqual([(d["method"], d["provider"], d["mfa"]) for d in logged],
                         [("oidc", p, False) for p in ("google", "microsoft", "apple")])

    async def test_only_the_provider_and_the_subject_are_stored(self) -> None:
        """The ID token carries an email and a name; the server keeps neither (it never even asked for the scope)."""
        params, _ = await self.begin("google")
        self.assertEqual(params["scope"], "openid")
        r = await self.callback("google", params, "sub-private", claims={"email": "ana@example.pt", "name": "Ana",
                                                                          "email_verified": True})
        _, _, fragment = self.landed(r)
        await self.client.post("/api/v1/auth/oidc/complete", json={"ticket": fragment[5:]})
        dump = json.dumps([dict(r) for r in await self.fetch(
            "SELECT * FROM users u JOIN user_identities i ON i.user_id = u.id", )], default=str)
        self.assertNotIn("ana@example.pt", dump)
        self.assertNotIn("Ana", dump)
        everything = json.dumps([dict(r) for r in await self.fetch("SELECT * FROM audit_log")], default=str)
        self.assertNotIn("ana@example.pt", everything)

    async def test_the_same_subject_logs_in_to_the_same_account(self) -> None:
        first = await self.social("google", "sub-1")
        second = await self.social("google", "sub-1", client=self.other_client())
        self.assertEqual(first["user"]["id"], second["user"]["id"])
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 1)
        self.assertIsNotNone((await self.fetch("SELECT last_login_at FROM user_identities"))[0][0])
        other = await self.social("google", "sub-2")
        self.assertNotEqual(first["user"]["id"], other["user"]["id"])
        # The same subject under another provider is another account: nothing is matched by email or by name.
        third = await self.social("microsoft", "sub-1")
        self.assertNotEqual(first["user"]["id"], third["user"]["id"])

    def set_notice_version(self, version: str) -> None:
        self.app.state.settings = dataclasses.replace(self.app.state.settings, privacy_notice_version=version)

    async def recorded_versions(self) -> list[str]:
        return [r[0] for r in await self.fetch("SELECT notice_version FROM consents WHERE purpose = 'account'")]

    async def test_the_notice_version_the_person_saw_is_recorded(self) -> None:
        """CONS-7: the version named at the start is the one recorded, and it is held on the login row meanwhile."""
        current = self.app.state.settings.privacy_notice_version
        params, r = await self.begin("google", notice_version=current)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.fetch("SELECT notice_version FROM oidc_logins"))[0][0], current)
        _, query, fragment = self.landed(await self.callback("google", params, "sub-1"))
        self.assertEqual((query, fragment.startswith("oidc=")), ({}, True))
        self.assertEqual(await self.recorded_versions(), [current])

    async def test_a_stale_notice_version_is_refused_at_the_start(self) -> None:
        current = self.app.state.settings.privacy_notice_version
        _, r = await self.begin("google", notice_version="an-older-version")
        self.assertEqual((r.status_code, r.json()), (409, {"detail": "notice_version_changed",
                                                           "current_version": current}))
        self.assertEqual((await self.fetch("SELECT count(*) FROM oidc_logins"))[0][0], 0)
        # Without the tick no account is being agreed to, so the version does not matter (and is not kept).
        params, r = await self.begin("google", consent=False, notice_version="an-older-version")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone((await self.fetch("SELECT notice_version FROM oidc_logins"))[0][0])
        too_long = await self.client.post("/api/v1/auth/oidc/google/start",
                                          json={"purpose": "login", "consent": True, "notice_version": "x" * 65})
        self.assertEqual(too_long.status_code, 422)

    async def test_the_callback_rechecks_the_notice_version(self) -> None:
        current = self.app.state.settings.privacy_notice_version
        params, r = await self.begin("google", notice_version=current)
        self.assertEqual(r.status_code, 200, r.text)
        self.set_notice_version("campo-v2")  # the operator publishes a new notice while the person is at Google
        _, query, fragment = self.landed(await self.callback("google", params, "sub-1"))
        self.assertEqual((query, fragment), ({"oidc_error": "notice_version_changed"}, ""))
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 0)
        self.assertEqual(await self.recorded_versions(), [])
        # Starting again with the new version works and records it.
        await self.social_with("google", "sub-1", "campo-v2")
        self.assertEqual(await self.recorded_versions(), ["campo-v2"])

    async def test_a_known_subject_does_not_care_about_the_notice_version(self) -> None:
        await self.social("google", "sub-1")
        client = self.other_client()
        params, _ = await self.begin("google", client=client, notice_version=self.app.state.settings.privacy_notice_version)
        self.set_notice_version("campo-v2")
        _, query, fragment = self.landed(await self.callback("google", params, "sub-1", client=client))
        self.assertEqual((query, fragment.startswith("oidc=")), ({}, True))

    async def test_a_client_that_names_no_version_gets_the_current_one(self) -> None:
        """Older apps and pages send nothing, and neither does a server with no notice published: as before."""
        self.assertEqual((await self.client.get("/api/v1/privacy-notice")).status_code, 404)  # nothing published
        await self.social("google", "sub-1")
        self.assertEqual(await self.recorded_versions(), [self.app.state.settings.privacy_notice_version])

    async def social_with(self, provider: str, subject: str, version: str) -> None:
        params, r = await self.begin(provider, notice_version=version)
        self.assertEqual(r.status_code, 200, r.text)
        _, query, fragment = self.landed(await self.callback(provider, params, subject))
        self.assertEqual(query, {})
        self.assertTrue(fragment.startswith("oidc="), fragment)

    async def test_a_login_makes_no_account_without_consent(self) -> None:
        params, _ = await self.begin("google", consent=False)
        _, query, fragment = self.landed(await self.callback("google", params, "sub-1"))
        self.assertEqual((query, fragment), ({"oidc_error": "consent_required"}, ""))
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 0)
        # ... but a known subject needs none.
        await self.social("google", "sub-1")
        client = self.other_client()
        params, _ = await self.begin("google", consent=False, client=client)
        _, query, fragment = self.landed(await self.callback("google", params, "sub-1", client=client))
        self.assertEqual((query, fragment.startswith("oidc=")), ({}, True))

    async def test_registration_limits_apply(self) -> None:
        limits = self.app.state.limits
        for _ in range(10):
            limits.register.fail("127.0.0.1")
        params, _ = await self.begin("google")
        _, query, _ = self.landed(await self.callback("google", params, "sub-1"))
        self.assertEqual(query, {"oidc_error": "too_many_attempts"})
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 0)

    async def test_the_hosted_accounts_quota_applies(self) -> None:
        async def full(db, name, field_id, adding=1):
            raise quotas.QuotaExceeded(name, 1)

        params, _ = await self.begin("google")
        with mock.patch("atalaia_server.api.login_methods.quotas.check", full):
            _, query, _ = self.landed(await self.callback("google", params, "sub-1"))
        self.assertEqual(query, {"oidc_error": "quota_exceeded"})
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 0)

    async def test_the_state_is_used_once_and_belongs_to_one_browser(self) -> None:
        params, _ = await self.begin("google")
        first = await self.callback("google", params, "sub-1")
        self.assertEqual(self.landed(first)[1], {})
        again = await self.callback("google", params, "sub-1")
        self.assertEqual(self.landed(again)[1], {"oidc_error": "state_invalid"})
        # A callback made by someone else (an attacker's own code and state) in a browser that did not begin it.
        stranger = self.other_client()
        params, _ = await self.begin("google")
        r = await self.callback("google", params, "sub-attacker", client=stranger)
        self.assertEqual(self.landed(r)[1], {"oidc_error": "state_invalid"})
        self.assertEqual((await self.fetch("SELECT count(*) FROM users WHERE username LIKE 'user-%'"))[0][0], 1)
        # The state was spent by that attempt: the right browser cannot use it afterwards either.
        r = await self.callback("google", params, "sub-attacker")
        self.assertEqual(self.landed(r)[1], {"oidc_error": "state_invalid"})
        for state in ("", "x", "y" * 500, "not-a-state"):
            r = await self.client.get("/api/v1/auth/oidc/google/callback", params={"code": "c", "state": state})
            self.assertEqual(self.landed(r)[1], {"oidc_error": "state_invalid"})
        r = await self.client.get("/api/v1/auth/oidc/google/callback", params={"code": "c"})
        self.assertEqual(self.landed(r)[1], {"oidc_error": "state_invalid"})

    async def test_the_state_expires_and_the_provider_may_say_no(self) -> None:
        params, _ = await self.begin("google")
        await self.fetch("UPDATE oidc_logins SET expires_at = now() - interval '1 second'")
        self.assertEqual(self.landed(await self.callback("google", params, "s"))[1], {"oidc_error": "state_invalid"})
        params, _ = await self.begin("google")
        r = await self.client.get("/api/v1/auth/oidc/google/callback",
                                  params={"error": "access_denied", "state": params["state"]})
        self.assertEqual(self.landed(r)[1], {"oidc_error": "denied"})
        self.assertEqual((await self.fetch("SELECT count(*) FROM oidc_logins"))[0][0], 0)

    async def test_the_binding_cookie(self) -> None:
        r = await self.client.post("/api/v1/auth/oidc/google/start", json={"consent": True})
        cookie = r.headers["set-cookie"]
        self.assertTrue(cookie.startswith("__Secure-atalaia_oidc="))
        for part in ("HttpOnly", "Secure", "SameSite=lax", "Path=/api/v1/auth/oidc"):
            self.assertIn(part, cookie)
        self.assertEqual(r.headers["cache-control"], "no-store")
        # The callback clears it.
        params = self.idp.authorize(r.json()["authorization_url"])
        done = await self.callback("google", params, "sub-1")
        self.assertIn("Max-Age=0", done.headers["set-cookie"])
        self.assertEqual(done.headers["cache-control"], "no-store")

    async def test_the_providers_answer_is_checked(self) -> None:
        params, _ = await self.begin("google")
        r = await self.callback("google", params, "sub-1", claims={"aud": "somebody-else"})
        self.assertEqual(self.landed(r)[1], {"oidc_error": "id_token_invalid"})
        params, _ = await self.begin("google")
        r = await self.callback("google", params, "sub-1", claims={"nonce": "someone else's nonce"})
        self.assertEqual(self.landed(r)[1], {"oidc_error": "id_token_invalid"})
        params, _ = await self.begin("google")
        self.idp.token_status = 400
        r = await self.callback("google", params, "sub-1")
        self.assertEqual(self.landed(r)[1], {"oidc_error": "token_exchange_failed"})
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 0)
        failed = await self.audit("oidc_failed")
        self.assertEqual([d["reason"] for d in failed], ["id_token_invalid", "id_token_invalid", "token_exchange_failed"])

    async def test_the_ticket_is_used_once(self) -> None:
        params, _ = await self.begin("google")
        _, _, fragment = self.landed(await self.callback("google", params, "sub-1"))
        ticket = fragment[5:]
        self.assertEqual((await self.client.post("/api/v1/auth/oidc/complete", json={"ticket": ticket})).status_code, 200)
        r = await self.client.post("/api/v1/auth/oidc/complete", json={"ticket": ticket})
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "invalid_ticket"))
        for bad in ("nonsense", ticket[:-3] + "abc"):
            r = await self.client.post("/api/v1/auth/oidc/complete", json={"ticket": bad})
            self.assertEqual(r.status_code, 401)
        # A TOTP step token is not a ticket.
        _, name, _ = await self.make_user(with_totp=True)
        step = (await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})).json()
        r = await self.client.post("/api/v1/auth/oidc/complete", json={"ticket": step["totp_session"]})
        self.assertEqual(r.status_code, 401)

    async def test_the_return_address_is_checked(self) -> None:
        for wanted, expected in (("https://evil.example/staff/", "/staff/login"), ("//evil.example/staff/x", "/staff/login"),
                                 ("/staff/\\evil", "/staff/login"), ("/api/v1/me", "/staff/login"),
                                 ("javascript:alert(1)", "/staff/login"),
                                 ("/staff/login?next=%2Fstaff%2F&lang=en", "/staff/login")):
            with self.subTest(wanted=wanted):
                params, _ = await self.begin("google", return_to=wanted)
                path, query, _ = self.landed(await self.callback("google", params, f"s-{wanted}"))
                self.assertEqual(path, expected)
        params, _ = await self.begin("google", return_to="/staff/login?next=%2Fstaff%2F&lang=en")
        _, query, fragment = self.landed(await self.callback("google", params, "s-last"))
        self.assertEqual(query, {"next": "/staff/", "lang": "en"})

    async def test_unknown_and_unconfigured_providers(self) -> None:
        for provider in ("github", "GOOGLE", "x" * 40):
            r = await self.client.post(f"/api/v1/auth/oidc/{provider}/start", json={"consent": True})
            self.assertEqual((r.status_code, r.json()["detail"]), (404, "provider_not_configured"))
        r = await self.client.post("/api/v1/auth/oidc/google/start", json={"consent": True, "purpose": "other"})
        self.assertEqual(r.status_code, 422)

    async def test_link_and_reauth_need_a_session(self) -> None:
        for purpose in ("link", "reauth"):
            r = await self.client.post("/api/v1/auth/oidc/google/start", json={"purpose": purpose})
            self.assertEqual(r.status_code, 401)


class NoProvidersTests(LoginTestCase):
    providers = False

    async def test_nothing_is_offered_and_nothing_starts(self) -> None:
        self.assertEqual((await self.client.get("/api/v1/auth/methods")).json()["oidc"], [])
        r = await self.client.post("/api/v1/auth/oidc/google/start", json={"consent": True})
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "provider_not_configured"))
        r = await self.client.get("/api/v1/auth/oidc/google/callback", params={"code": "c", "state": "s"})
        self.assertEqual(self.landed(r)[1], {"oidc_error": "state_invalid"})


class LinkingTests(LoginTestCase):
    async def test_a_logged_in_user_links_and_unlinks_providers(self) -> None:
        _, name, _ = await self.make_user()
        headers = await self.auth(name)
        r = await self.client.post("/api/v1/auth/oidc/google/start", headers=headers,
                                   json={"purpose": "link", "password": "wrong"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_password"))
        self.assertEqual(await self.link("google", "g-1", headers), {"oidc": "linked"})
        methods = (await self.client.get("/api/v1/me/login-methods", headers=headers)).json()
        self.assertEqual([i["provider"] for i in methods["identities"]], ["google"])
        self.assertEqual(methods["password"], {"set": True, "login_enabled": True})
        # Now the account logs in with Google, and it is the same account.
        body = await self.social("google", "g-1", client=self.other_client())
        self.assertEqual(body["user"]["username"], name)
        # The second Google subject, a subject somebody else holds, and the same one again: refused.
        self.assertEqual(await self.link("google", "g-2", headers), {"oidc_error": "provider_already_linked"})
        self.assertEqual(await self.link("google", "g-1", headers), {"oidc_error": "already_linked"})
        other = await self.social("microsoft", "m-1", client=self.other_client())
        _, name2, _ = await self.make_user()
        headers2 = await self.auth(name2)
        self.assertEqual(await self.link("microsoft", "m-1", headers2), {"oidc": "merge"})
        self.assertNotEqual(other["user"]["username"], name2)
        # Unlink: the password is asked, the unknown one is a 404.
        r = await self.client.request("DELETE", "/api/v1/me/identities/google", headers=headers, json={"password": "wrong"})
        self.assertEqual(r.status_code, 403)
        r = await self.client.request("DELETE", "/api/v1/me/identities/apple", headers=headers, json={"password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "identity_not_found"))
        r = await self.client.request("DELETE", "/api/v1/me/identities/google", headers=headers, json={"password": PASSWORD})
        self.assertEqual(r.status_code, 204)
        self.assertEqual((await self.fetch("SELECT count(*) FROM user_identities WHERE provider = 'google'"))[0][0], 0)
        self.assertEqual([d["provider"] for d in await self.audit("identity_link")], ["google"])
        self.assertEqual([d["provider"] for d in await self.audit("identity_unlink")], ["google"])

    async def test_nothing_is_ever_linked_by_email(self) -> None:
        user_id, name, _ = await self.make_user()
        await self.fetch("UPDATE users SET email = 'ana@example.pt' WHERE id = $1", user_id)
        params, _ = await self.begin("google")
        r = await self.callback("google", params, "g-ana", claims={"email": "ana@example.pt", "email_verified": True})
        _, _, fragment = self.landed(r)
        body = (await self.client.post("/api/v1/auth/oidc/complete", json={"ticket": fragment[5:]})).json()
        self.assertNotEqual(body["user"]["id"], str(user_id))
        self.assertEqual((await self.fetch("SELECT count(*) FROM user_identities WHERE user_id = $1", user_id))[0][0], 0)

    async def test_the_last_way_to_log_in_stays(self) -> None:
        body = await self.social("google", "only-one")
        headers = bearer(body)
        r = await self.client.request("DELETE", "/api/v1/me/identities/google", headers=headers, json={})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "last_login_method"))
        self.assertEqual((await self.fetch("SELECT count(*) FROM user_identities"))[0][0], 1)
        # With a second way (a password, set now), the first can go.
        r = await self.client.post("/api/v1/me/password", headers=headers, json={"new_password": PASSWORD})
        self.assertEqual(r.status_code, 204, r.text)
        r = await self.client.request("DELETE", "/api/v1/me/identities/google", headers=headers, json={"password": PASSWORD})
        self.assertEqual(r.status_code, 204)
        # ... and the password is now the last.
        r = await self.client.delete("/api/v1/me/password", headers=headers, params={})
        self.assertEqual(r.status_code, 422)  # a body is expected, as for every sensitive change
        r = await self.client.request("DELETE", "/api/v1/me/password", headers=headers, json={"password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "last_login_method"))

    async def test_an_account_with_no_password_confirms_with_a_recent_login(self) -> None:
        body = await self.social("google", "g-1")
        headers = bearer(body)
        r = await self.client.patch("/api/v1/me", headers=headers, json={"username": "ana.silva"})
        self.assertEqual((r.status_code, r.json()["username"]), (200, "ana.silva"))
        await self.age_confirmation()
        r = await self.client.patch("/api/v1/me", headers=headers, json={"username": "ana.costa"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "confirmation_required"))
        # Logging in with the provider again proves it is her: the session is confirmed again.
        params, r = await self.begin("google", headers=headers, purpose="reauth")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.landed(await self.callback("google", params, "g-1"))[1], {"oidc": "reauth"})
        r = await self.client.patch("/api/v1/me", headers=headers, json={"username": "ana.costa"})
        self.assertEqual(r.status_code, 200, r.text)
        # Another subject (the provider account of someone else) confirms nothing.
        await self.age_confirmation()
        params, _ = await self.begin("google", headers=headers, purpose="reauth")
        self.assertEqual(self.landed(await self.callback("google", params, "g-2"))[1], {"oidc_error": "identity_mismatch"})
        r = await self.client.patch("/api/v1/me", headers=headers, json={"username": "ana.rocha"})
        self.assertEqual(r.status_code, 403)
        stepups = await self.audit("stepup")
        self.assertEqual([(d["method"], d["mfa"]) for d in stepups], [("oidc", False)])

    async def test_a_password_account_still_needs_its_password(self) -> None:
        _, name, _ = await self.make_user()
        headers = await self.auth(name)
        r = await self.client.patch("/api/v1/me", headers=headers, json={"username": "novo.nome"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_password"))


class PasswordOptionalTests(LoginTestCase):
    async def test_the_password_can_go_when_another_way_exists(self) -> None:
        _, name, _ = await self.make_user()
        headers = await self.auth(name)
        r = await self.client.request("DELETE", "/api/v1/me/password", headers=headers, json={"password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "last_login_method"))
        authenticator, r = await self.add_passkey(headers)
        self.assertEqual(r.status_code, 201, r.text)
        await self.second_factor(headers)
        r = await self.client.request("DELETE", "/api/v1/me/password", headers=headers, json={"password": "wrong"})
        self.assertEqual(r.status_code, 403)
        r = await self.client.request("DELETE", "/api/v1/me/password", headers=headers, json={"password": PASSWORD})
        self.assertEqual(r.status_code, 204)
        self.assertIsNone((await self.fetch("SELECT password_hash FROM users WHERE username = $1", name))[0][0])
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "invalid_credentials"))
        self.assertEqual((await self.passkey_login(authenticator)).status_code, 200)
        r = await self.client.request("DELETE", "/api/v1/me/password", headers=headers, json={})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "no_password"))
        self.assertEqual(len(await self.audit("password_remove")), 1)
        # A password can be set again, confirmed by a recent login.
        r = await self.client.post("/api/v1/me/password", headers=headers, json={"new_password": "a new long passphrase 9"})
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual((await self.audit("password_change"))[-1]["added"], True)
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": "a new long passphrase 9"})
        self.assertEqual(r.status_code, 200)

    async def test_a_password_that_breaks_the_policy_is_refused_for_a_first_password_too(self) -> None:
        body = await self.social("google", "g-1")
        r = await self.client.post("/api/v1/me/password", headers=bearer(body), json={"new_password": "short"})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "password_too_short"))


class PasswordLoginOffTests(LoginTestCase):
    password_login = False

    async def test_password_login_and_registration_are_off(self) -> None:
        self.assertFalse((await self.client.get("/api/v1/auth/methods")).json()["password_login"])
        _, name, _ = await self.make_user()
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "password_login_disabled"))
        r = await self.client.post("/api/v1/auth/register", json={"username": "nova.pessoa", "password": PASSWORD,
                                                                  "consent": True})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "password_login_disabled"))
        self.assertEqual((await self.fetch("SELECT count(*) FROM users WHERE username = 'nova.pessoa'"))[0][0], 0)

    async def test_the_other_ways_work_and_the_password_no_longer_counts_as_one(self) -> None:
        body = await self.social("google", "g-1")
        headers = bearer(body)
        authenticator, r = await self.add_passkey(headers)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((await self.passkey_login(authenticator)).status_code, 200)
        # A password account: its password is no way to log in now, so the one social login is its last.
        user_id, name, _ = await self.make_user()
        await self.fetch("INSERT INTO user_identities (user_id, provider, subject) VALUES ($1, 'google', 'g-pw')", user_id)
        session = await self.social("google", "g-pw", client=self.other_client())
        r = await self.client.request("DELETE", "/api/v1/me/identities/google", headers=bearer(session),
                                      json={"password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "last_login_method"))
        r = await self.client.post("/api/v1/me/password", headers=bearer(session),
                                   json={"password": PASSWORD, "new_password": "a new long passphrase 9"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "password_login_disabled"))
        # It still confirms a sensitive change (it is a proof of identity, not a login).
        r = await self.client.patch("/api/v1/me", headers=bearer(session), json={"password": PASSWORD, "username": "novo.nome"})
        self.assertEqual(r.status_code, 200, r.text)


class PasskeyTests(LoginTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.user_id, self.name, self.secret = await self.make_user()
        self.headers = await self.auth(self.name)

    async def test_register_list_login_rename_remove(self) -> None:
        authenticator, r = await self.add_passkey(self.headers, name="Portátil")
        self.assertEqual((r.status_code, r.json()["name"], r.json()["backed_up"]), (201, "Portátil", False))
        key_id = r.json()["id"]
        await self.second_factor(self.headers)
        row = (await self.fetch("SELECT * FROM passkeys"))[0]
        self.assertEqual((row["rp_id"], row["sign_count"], row["transports"]), ("server.test", 0, "internal"))
        listing = (await self.client.get("/api/v1/me/login-methods", headers=self.headers)).json()
        self.assertEqual([k["name"] for k in listing["passkeys"]], ["Portátil"])
        self.assertNotIn("public_key", json.dumps(listing))
        self.assertEqual((await self.passkey_login(authenticator)).status_code, 200)
        r = await self.passkey_login(authenticator)
        self.assertEqual(r.status_code, 200, r.text)
        session = r.json()
        self.assertTrue(session["mfa"])  # a passkey login is both factors
        self.assertEqual(session["user"]["username"], self.name)
        self.assertEqual((await self.fetch("SELECT sign_count FROM passkeys"))[0][0], 2)
        self.assertIsNotNone((await self.fetch("SELECT last_used_at FROM passkeys"))[0][0])
        logins = await self.audit("login")
        self.assertEqual(logins[-1], {"mfa": True, "method": "passkey"})
        me = (await self.client.get("/api/v1/me", headers=bearer(session))).json()
        self.assertTrue(me["mfa"])
        r = await self.client.patch(f"/api/v1/me/passkeys/{key_id}", headers=self.headers, json={"name": "  Telemóvel "})
        self.assertEqual(r.json()["name"], "Telemóvel")
        for bad in ("", "   ", "a\x00b"):
            r = await self.client.patch(f"/api/v1/me/passkeys/{key_id}", headers=self.headers, json={"name": bad})
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "name_invalid"))
        r = await self.client.request("DELETE", f"/api/v1/me/passkeys/{key_id}", headers=self.headers, json={"password": "wrong"})
        self.assertEqual(r.status_code, 403)
        r = await self.client.request("DELETE", f"/api/v1/me/passkeys/{key_id}", headers=self.headers, json={"password": PASSWORD})
        self.assertEqual(r.status_code, 204)
        self.assertEqual((await self.fetch("SELECT count(*) FROM passkeys"))[0][0], 0)
        self.assertEqual([d for d in await self.audit("passkey_add")], [{"backed_up": False}])
        self.assertEqual(len(await self.audit("passkey_rename")), 1)
        self.assertEqual(len(await self.audit("passkey_remove")), 1)

    async def test_the_default_name_and_a_synced_passkey(self) -> None:
        _, r = await self.add_passkey(self.headers, SoftAuthenticator(backup=True))
        self.assertEqual((r.json()["name"], r.json()["backed_up"]), ("Passkey 1", True))
        await self.second_factor(self.headers)
        _, r = await self.add_passkey(self.headers)
        self.assertEqual(r.json()["name"], "Passkey 2")

    async def test_a_passkey_login_skips_the_totp_step(self) -> None:
        _, name, secret = await self.make_user(with_totp=True)
        headers = await self.auth(name, secret=secret)
        authenticator, r = await self.add_passkey(headers)
        self.assertEqual(r.status_code, 201)
        r = await self.passkey_login(authenticator)
        self.assertEqual((r.status_code, r.json()["mfa"], "totp_required" in r.json()), (200, True, False))

    async def test_registering_needs_the_confirmation(self) -> None:
        r = await self.client.post("/api/v1/me/passkeys/options", json={"password": "wrong"}, headers=self.headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_password"))
        r = await self.client.post("/api/v1/me/passkeys/options", json={})
        self.assertEqual(r.status_code, 401)
        options = (await self.client.post("/api/v1/me/passkeys/options", json={"password": PASSWORD},
                                          headers=self.headers)).json()["options"]
        self.assertEqual(options["rp"], {"name": "Atalaia", "id": "server.test"})
        self.assertEqual(options["authenticatorSelection"]["userVerification"], "required")
        self.assertEqual(options["authenticatorSelection"]["residentKey"], "required")
        self.assertEqual(options["attestation"], "none")

    async def test_registration_refusals(self) -> None:
        # No user verification at the authenticator.
        _, r = await self.add_passkey(self.headers, SoftAuthenticator(uv=False))
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "passkey_invalid"))
        # Another origin.
        authenticator = SoftAuthenticator()
        parts = (await self.client.post("/api/v1/me/passkeys/options", json={"password": PASSWORD}, headers=self.headers)).json()
        bad = authenticator.create(parts["options"], "https://evil.example")
        r = await self.client.post("/api/v1/me/passkeys", headers=self.headers,
                                   json={"challenge_token": parts["challenge_token"], "credential": bad})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "passkey_invalid"))
        # A challenge is single use, and tied to its account and its purpose.
        parts = (await self.client.post("/api/v1/me/passkeys/options", json={"password": PASSWORD}, headers=self.headers)).json()
        good = authenticator.create(parts["options"], ORIGIN)
        _, name2, _ = await self.make_user()
        other = await self.auth(name2)
        r = await self.client.post("/api/v1/me/passkeys", headers=other,
                                   json={"challenge_token": parts["challenge_token"], "credential": good})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "invalid_challenge"))
        parts = (await self.client.post("/api/v1/me/passkeys/options", json={"password": PASSWORD}, headers=self.headers)).json()
        good = authenticator.create(parts["options"], ORIGIN)
        body = {"challenge_token": parts["challenge_token"], "credential": good}
        self.assertEqual((await self.client.post("/api/v1/me/passkeys", headers=self.headers, json=body)).status_code, 201)
        await self.second_factor(self.headers)
        r = await self.client.post("/api/v1/me/passkeys", headers=self.headers, json=body)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "invalid_challenge"))
        # The same authenticator again: the credential exists.
        parts = (await self.client.post("/api/v1/me/passkeys/options", json={"password": PASSWORD}, headers=self.headers)).json()
        again = authenticator.create(parts["options"], ORIGIN)
        r = await self.client.post("/api/v1/me/passkeys", headers=self.headers,
                                   json={"challenge_token": parts["challenge_token"], "credential": again})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "passkey_exists"))
        # A challenge of another kind, a forged one, and junk.
        login = await self.passkey_login_parts()
        r = await self.client.post("/api/v1/me/passkeys", headers=self.headers,
                                   json={"challenge_token": login["challenge_token"], "credential": good})
        self.assertEqual(r.json()["detail"], "invalid_challenge")
        for token in ("junk", parts["challenge_token"][:-4] + "AAAA"):
            r = await self.client.post("/api/v1/me/passkeys", headers=self.headers,
                                       json={"challenge_token": token, "credential": good})
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "invalid_challenge"))
        r = await self.client.post("/api/v1/me/passkeys", headers=self.headers,
                                   json={"challenge_token": parts["challenge_token"], "credential": {"x": "y" * 20000}})
        self.assertEqual(r.status_code, 400)

    async def test_the_account_holds_a_limited_number(self) -> None:
        for i in range(20):
            await self.fetch("INSERT INTO passkeys (user_id, credential_id, public_key, name, rp_id) "
                             "VALUES ($1, $2, '\\x00', 'k', 'server.test')", self.user_id, bytes([i]) * 8)
        await self.second_factor(self.headers)
        r = await self.client.post("/api/v1/me/passkeys/options", json={"password": PASSWORD}, headers=self.headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "too_many_passkeys"))

    async def test_login_refusals(self) -> None:
        authenticator, _ = await self.add_passkey(self.headers)

        async def refused(**kw: Any) -> None:
            r = await self.passkey_login(authenticator, **kw)
            self.assertEqual((r.status_code, r.json()["detail"]), (401, "invalid_passkey"), kw)

        await refused(origin="https://evil.example")
        await refused(rp_id="evil.example")
        await refused(user_handle=b"someone else")
        authenticator.uv = False
        await refused()                                                  # no user verification
        authenticator.uv = True
        self.assertEqual((await self.passkey_login(authenticator)).status_code, 200)
        stored = authenticator.counter
        await refused(bump=0)                                            # a counter that did not move: a clone
        authenticator.counter = stored - 1
        await refused(bump=0)                                            # ... or went back
        authenticator.counter = stored + 5
        self.assertEqual((await self.passkey_login(authenticator, bump=0)).status_code, 200)
        # A credential the server never saw.
        stranger = SoftAuthenticator()
        stranger.user_handle = self.user_id.bytes
        r = await self.passkey_login(stranger)
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "invalid_passkey"))
        # The failures are logged without the credential or anything typed.
        failed = await self.audit("login_failed")
        self.assertEqual(len(failed), 7)
        self.assertTrue(all(d == {"where": "login", "method": "passkey"} for d in failed))
        # A challenge is single use.
        parts = await self.passkey_login_parts()
        body = {"challenge_token": parts["challenge_token"], "credential": authenticator.get(parts["options"], ORIGIN)}
        self.assertEqual((await self.client.post("/api/v1/auth/passkey/login", json=body)).status_code, 200)
        r = await self.client.post("/api/v1/auth/passkey/login", json=body)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "invalid_challenge"))
        # A signature over another challenge.
        parts = await self.passkey_login_parts()
        other = await self.passkey_login_parts()
        r = await self.client.post("/api/v1/auth/passkey/login", json={
            "challenge_token": parts["challenge_token"], "credential": authenticator.get(other["options"], ORIGIN)})
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "invalid_passkey"))
        # Junk.
        for token in ("junk", ""):
            r = await self.client.post("/api/v1/auth/passkey/login", json={"challenge_token": token, "credential": {}})
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "invalid_challenge"))

    async def test_failures_lock_the_address_like_failed_passwords(self) -> None:
        for _ in range(49):
            self.app.state.limits.login_address.fail("127.0.0.1")
        r = await self.passkey_login(SoftAuthenticator())
        self.assertEqual(r.status_code, 401)                     # the 50th failure locks the address
        r = await self.client.post("/api/v1/auth/passkey/login/options")
        self.assertEqual(r.status_code, 429)
        self.assertEqual((await self.audit("login_locked"))[0], {"where": "login", "scope": "address"})

    async def test_a_passkey_of_another_host_name_does_not_count(self) -> None:
        authenticator, _ = await self.add_passkey(self.headers)
        await self.second_factor(self.headers)
        await self.fetch("UPDATE passkeys SET rp_id = 'other.test'")
        r = await self.passkey_login(authenticator)
        self.assertEqual(r.status_code, 401)
        r = await self.client.request("DELETE", "/api/v1/me/password", headers=self.headers, json={"password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "last_login_method"))

    async def test_another_accounts_passkey_is_not_yours_to_change(self) -> None:
        _, r = await self.add_passkey(self.headers)
        key_id = r.json()["id"]
        _, name2, _ = await self.make_user()
        other = await self.auth(name2)
        r = await self.client.patch(f"/api/v1/me/passkeys/{key_id}", headers=other, json={"name": "mine now"})
        self.assertEqual(r.status_code, 404)
        r = await self.client.request("DELETE", f"/api/v1/me/passkeys/{key_id}", headers=other, json={"password": PASSWORD})
        self.assertEqual(r.status_code, 404)
        self.assertEqual((await self.fetch("SELECT count(*) FROM passkeys"))[0][0], 1)

    async def test_the_last_way_to_log_in_stays(self) -> None:
        body = await self.social("google", "g-1")
        headers = bearer(body)
        authenticator, r = await self.add_passkey(headers)  # a fresh social login confirms
        self.assertEqual(r.status_code, 201, r.text)
        key_id = r.json()["id"]
        await self.second_factor(headers)  # the account has a passkey now: its changes need a second factor
        r = await self.client.request("DELETE", "/api/v1/me/identities/google", headers=headers, json={})
        self.assertEqual(r.status_code, 204)
        r = await self.client.request("DELETE", f"/api/v1/me/passkeys/{key_id}", headers=headers, json={})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "last_login_method"))
        self.assertEqual((await self.passkey_login(authenticator)).status_code, 200)


class StaffSecondFactorTests(LoginTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        _, self.admin, secret = await self.make_user("chefe", server_admin=True)
        self.as_admin = await self.auth(self.admin, secret=secret)
        r = await self.client.post("/api/v1/fields", headers=self.as_admin, json={"name": "Campo", "slug": "campo"})
        self.field = r.json()["id"]

    async def grant(self, name: str, role: str = "gm") -> httpx.Response:
        return await self.client.put(f"/api/v1/fields/{self.field}/roles", headers=self.as_admin,
                                     json={"username": name, "role": role})

    def roles_ok(self, headers: dict[str, str]) -> Any:
        return self.client.get(f"/api/v1/fields/{self.field}/roles", headers=headers)

    async def test_a_passkey_is_a_second_factor_for_granting_roles(self) -> None:
        _, name, _ = await self.make_user()
        r = await self.grant(name)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "totp_required"))
        _, added = await self.add_passkey(await self.auth(name))
        self.assertEqual(added.status_code, 201)
        self.assertEqual((await self.grant(name)).status_code, 201)
        self.assertEqual((await self.grant(name, "marshal")).status_code, 201)

    async def test_a_passkey_login_counts_for_the_staff_roles(self) -> None:
        user_id, name, _ = await self.make_user()
        authenticator, _ = await self.add_passkey(await self.auth(name))
        await self.grant(name)
        # A password login alone: the role is held and does not count.
        plain = await self.auth(name)
        self.assertEqual((await self.roles_ok(plain)).status_code, 403)
        session = (await self.passkey_login(authenticator)).json()
        self.assertEqual((await self.roles_ok(bearer(session))).status_code, 200)
        # A step-up with the passkey makes the password session count.
        parts = (await self.client.post("/api/v1/auth/stepup/passkey/options", headers=plain)).json()
        credential = authenticator.get(parts["options"], ORIGIN)
        r = await self.client.post("/api/v1/auth/stepup/passkey", headers=plain,
                                   json={"challenge_token": parts["challenge_token"], "credential": credential})
        self.assertEqual((r.status_code, r.json()), (200, {"mfa": True}))
        self.assertEqual((await self.roles_ok(plain)).status_code, 200)
        self.assertEqual((await self.audit("stepup"))[-1], {"method": "passkey", "mfa": True})

    async def test_a_social_login_alone_does_not_count(self) -> None:
        user_id, name, secret = await self.make_user(with_totp=True)
        headers = await self.auth(name, secret=secret)
        await self.link("google", "g-staff", headers)
        await self.grant(name)
        self.assertEqual((await self.roles_ok(headers)).status_code, 200)         # the TOTP session
        social = bearer(await self.social("google", "g-staff", client=self.other_client()))
        me = (await self.client.get("/api/v1/me", headers=social)).json()
        self.assertEqual((me["mfa"], me["roles"][self.field]), (False, ["gm"]))     # held, not counting
        r = await self.roles_ok(social)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "role_required"))
        # A wrong code, then the right one: the session counts from then on.
        r = await self.client.post("/api/v1/auth/stepup/totp", headers=social, json={"code": "000000"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_code"))
        r = await self.client.post("/api/v1/auth/stepup/totp", headers=social, json={"code": self.code(secret)})
        self.assertEqual((r.status_code, r.json()), (200, {"mfa": True}))
        self.assertEqual((await self.roles_ok(social)).status_code, 200)
        self.assertEqual((await self.audit("stepup"))[-1], {"method": "totp", "mfa": True})
        # The same code is not accepted twice (RFC 6238), as at login.
        again = bearer(await self.social("google", "g-staff", client=self.other_client()))
        r = await self.client.post("/api/v1/auth/stepup/totp", headers=again, json={"code": self.code(secret)})
        self.assertEqual(r.status_code, 200)

    async def test_a_social_session_of_a_server_administrator(self) -> None:
        _, name, secret = await self.make_user("ana.adm", server_admin=True)
        await self.link("google", "g-adm", await self.auth(name, secret=secret))
        social = bearer(await self.social("google", "g-adm", client=self.other_client()))
        r = await self.client.post("/api/v1/fields", headers=social, json={"name": "X", "slug": "x"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "server_admin_required"))
        await self.client.post("/api/v1/auth/stepup/totp", headers=social, json={"code": self.code(secret)})
        r = await self.client.post("/api/v1/fields", headers=social, json={"name": "X", "slug": "x"})
        self.assertEqual(r.status_code, 201, r.text)

    async def test_the_step_up_refusals(self) -> None:
        user_id, name, secret = await self.make_user()
        headers = await self.auth(name)
        r = await self.client.post("/api/v1/auth/stepup/totp", headers=headers, json={"code": "123456"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "totp_not_enabled"))
        r = await self.client.post("/api/v1/auth/stepup/passkey/options", headers=headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "no_passkey"))
        for path in ("/api/v1/auth/stepup/totp", "/api/v1/auth/stepup/passkey/options"):
            self.assertEqual((await self.client.post(path, json={"code": "1"})).status_code, 401)
        # A passkey of another account, and a challenge made for another session, do not step this one up.
        mine, _ = await self.add_passkey(headers)
        _, name2, _ = await self.make_user()
        other_headers = await self.auth(name2)
        theirs, _ = await self.add_passkey(other_headers)
        parts = (await self.client.post("/api/v1/auth/stepup/passkey/options", headers=headers)).json()
        r = await self.client.post("/api/v1/auth/stepup/passkey", headers=headers, json={
            "challenge_token": parts["challenge_token"], "credential": theirs.get(parts["options"], ORIGIN)})
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "invalid_passkey"))
        parts = (await self.client.post("/api/v1/auth/stepup/passkey/options", headers=headers)).json()
        second_session = await self.auth(name)
        r = await self.client.post("/api/v1/auth/stepup/passkey", headers=second_session, json={
            "challenge_token": parts["challenge_token"], "credential": mine.get(parts["options"], ORIGIN)})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "invalid_challenge"))

    async def test_removing_the_last_second_factor_of_a_staff_account(self) -> None:
        user_id, name, _ = await self.make_user()
        headers = await self.auth(name)
        authenticator, r = await self.add_passkey(headers)
        key_id = r.json()["id"]
        await self.second_factor(headers)
        _, added = await self.add_passkey(headers)
        await self.grant(name)
        second_id = added.json()["id"]
        r = await self.client.request("DELETE", f"/api/v1/me/passkeys/{second_id}", headers=headers, json={"password": PASSWORD})
        self.assertEqual(r.status_code, 204)
        r = await self.client.request("DELETE", f"/api/v1/me/passkeys/{key_id}", headers=headers, json={"password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "second_factor_required_by_role"))
        # TOTP off is refused while TOTP is the only second factor, and fine while a passkey stays.
        _, tname, tsecret = await self.make_user(with_totp=True)
        theaders = await self.auth(tname, secret=tsecret)
        await self.grant(tname)
        r = await self.client.post("/api/v1/auth/totp/disable", headers=theaders,
                                   json={"password": PASSWORD, "code": self.code(tsecret)})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "totp_required_by_role"))
        await self.add_passkey(theaders)
        r = await self.client.post("/api/v1/auth/totp/disable", headers=theaders,
                                   json={"password": PASSWORD, "code": self.code(tsecret)})
        self.assertEqual(r.status_code, 204, r.text)


class StepUpTests(LoginTestCase):
    """Changing how an account logs in needs a session that passed a second factor, when the account has one or a
    staff role (SRV-1, decisions SR-*): a social login alone must not add its own passkey to a staff account."""

    async def staff_google_only(self, subject: str = "g-staff") -> tuple[uuid.UUID, dict[str, str]]:
        """A passwordless account made by a Google login, with a passkey of its owner and a gm role; the session is
        a fresh Google login (``mfa`` false), as an attacker holding only the Google account would have."""
        body = await self.social("google", subject)
        user = uuid.UUID(body["user"]["id"])
        await self.fetch("INSERT INTO passkeys (id, user_id, credential_id, public_key, name, rp_id) VALUES "
                         "(gen_random_uuid(), $1, $2, $3, 'owner', 'server.test')", user, b"owner-credential", b"x")
        field = (await self.fetch("INSERT INTO fields (id, name, slug) VALUES (gen_random_uuid(), 'F', 'f') RETURNING id"))[0][0]
        await self.fetch("INSERT INTO user_field_roles (id, user_id, field_id, role_id) VALUES (gen_random_uuid(), $1, $2, 5)",
                         user, field)
        return user, bearer(body)

    async def test_a_google_session_cannot_give_a_staff_account_a_passkey_of_its_own(self) -> None:
        user, headers = await self.staff_google_only()
        r = await self.client.post("/api/v1/me/passkeys/options", json={}, headers=headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "mfa_required"))
        # Even with a registration prepared while the session had a second factor: the finishing call asks again.
        await self.second_factor(headers)
        authenticator = SoftAuthenticator()
        parts = (await self.client.post("/api/v1/me/passkeys/options", json={}, headers=headers)).json()
        credential = authenticator.create(parts["options"], ORIGIN)
        await self.fetch("UPDATE sessions SET mfa = false WHERE user_id = $1", user)
        r = await self.client.post("/api/v1/me/passkeys", headers=headers,
                                   json={"challenge_token": parts["challenge_token"], "credential": credential})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "mfa_required"))
        self.assertEqual((await self.fetch("SELECT count(*) FROM passkeys WHERE user_id = $1", user))[0][0], 1)
        self.assertEqual((await self.passkey_login(authenticator)).status_code, 401)  # no way in with it
        self.assertGreaterEqual(len(await self.audit("step_up_refused")), 2)

    async def test_every_change_of_the_login_methods_asks_for_it(self) -> None:
        _, name, secret = await self.make_user(with_totp=True)
        headers = await self.auth(name, secret=secret)
        await self.link("google", "g-1", headers)
        _, added = await self.add_passkey(headers)
        key_id = added.json()["id"]
        social = bearer(await self.social("google", "g-1", client=self.other_client()))
        call = self.client.request
        asked = [
            await call("POST", "/api/v1/me/passkeys/options", headers=social, json={"password": PASSWORD}),
            await call("PATCH", f"/api/v1/me/passkeys/{key_id}", headers=social, json={"name": "x"}),
            await call("DELETE", f"/api/v1/me/passkeys/{key_id}", headers=social, json={"password": PASSWORD}),
            await call("POST", "/api/v1/auth/totp/disable", headers=social, json={"password": PASSWORD, "code": "123456"}),
            await call("POST", "/api/v1/me/password", headers=social,
                       json={"password": PASSWORD, "new_password": "a new long passphrase 9"}),
            await call("DELETE", "/api/v1/me/password", headers=social, json={"password": PASSWORD}),
            await call("POST", "/api/v1/auth/oidc/microsoft/start", headers=social,
                       json={"purpose": "link", "password": PASSWORD}),
            await call("DELETE", "/api/v1/me/identities/google", headers=social, json={"password": PASSWORD}),
        ]
        self.assertEqual([(r.status_code, r.json()["detail"]) for r in asked], [(403, "mfa_required")] * len(asked))
        self.assertEqual((await self.fetch("SELECT count(*) FROM passkeys"))[0][0], 1)
        self.assertIsNotNone((await self.fetch("SELECT password_hash FROM users WHERE username = $1", name))[0][0])
        # An account with a passkey and no TOTP: starting TOTP is a change too.
        _, pname, _ = await self.make_user()
        pheaders = await self.auth(pname)
        await self.add_passkey(pheaders)
        r = await call("POST", "/api/v1/auth/totp/enrol", headers=pheaders, json={"password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "mfa_required"))
        # What does not change how the account is entered stays as it was.
        r = await call("PATCH", "/api/v1/me", headers=social, json={"username": "novo.nome", "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)

    async def test_a_second_factor_step_up_unlocks_them(self) -> None:
        _, name, secret = await self.make_user(with_totp=True)
        headers = await self.auth(name, secret=secret)
        await self.link("google", "g-1", headers)
        social = bearer(await self.social("google", "g-1", client=self.other_client()))
        me = (await self.client.get("/api/v1/me/login-methods", headers=social)).json()
        self.assertEqual((me["mfa"], me["step_up_needed"]), (False, True))
        r = await self.client.post("/api/v1/auth/stepup/totp", headers=social, json={"code": self.code(secret)})
        self.assertEqual(r.status_code, 200, r.text)
        me = (await self.client.get("/api/v1/me/login-methods", headers=social)).json()
        self.assertEqual((me["mfa"], me["step_up_needed"]), (True, False))
        authenticator, r = await self.add_passkey(social)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((await self.passkey_login(authenticator)).status_code, 200)

    async def test_the_first_factor_of_a_plain_account_is_not_blocked(self) -> None:
        # A player with only a Google login adds a first passkey with a fresh login; the second needs the first.
        body = await self.social("google", "g-player")
        headers = bearer(body)
        me = (await self.client.get("/api/v1/me/login-methods", headers=headers)).json()
        self.assertEqual(me["step_up_needed"], False)
        _, r = await self.add_passkey(headers)
        self.assertEqual(r.status_code, 201, r.text)
        r = await self.client.post("/api/v1/me/passkeys/options", json={}, headers=headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "mfa_required"))
        # A password account with no factor and no role starts TOTP as before.
        _, name, _ = await self.make_user()
        r = await self.client.post("/api/v1/auth/totp/enrol", headers=await self.auth(name), json={"password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)

    async def test_a_staff_account_with_a_password_and_no_second_factor_can_get_its_first(self) -> None:
        user_id, name, _ = await self.make_user()
        field = (await self.fetch("INSERT INTO fields (id, name, slug) VALUES (gen_random_uuid(), 'F', 'f') RETURNING id"))[0][0]
        await self.fetch("INSERT INTO user_field_roles (id, user_id, field_id, role_id) VALUES (gen_random_uuid(), $1, $2, 5)",
                         user_id, field)
        headers = await self.auth(name)
        # The password is the proof (a wrong one is refused as ever) ...
        r = await self.client.post("/api/v1/me/passkeys/options", json={"password": "wrong"}, headers=headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_password"))
        _, r = await self.add_passkey(headers)
        self.assertEqual(r.status_code, 201, r.text)
        # ... and from then on a second factor is.
        r = await self.client.post("/api/v1/me/passkeys/options", json={"password": PASSWORD}, headers=headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "mfa_required"))

    async def test_a_staff_account_with_neither_password_nor_second_factor_gets_nothing_from_a_social_login(self) -> None:
        body = await self.social("google", "g-adm")
        await self.fetch("UPDATE users SET server_admin = true WHERE id = $1", uuid.UUID(body["user"]["id"]))
        r = await self.client.post("/api/v1/me/passkeys/options", json={}, headers=bearer(body))
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "mfa_required"))


class PersonalDataTests(LoginTestCase):
    async def test_export_and_access_cover_the_new_rows_without_secrets(self) -> None:
        body = await self.social("google", "g-export")
        headers = bearer(body)
        authenticator, r = await self.add_passkey(headers, name="Chave")
        self.assertEqual(r.status_code, 201, r.text)
        data = (await self.client.get("/api/v1/me/data", headers=headers)).json()
        self.assertEqual([(i["provider"], i["subject"]) for i in data["identities"]], [("google", "g-export")])
        self.assertEqual([(k["name"], k["rp_id"]) for k in data["passkeys"]], [("Chave", "server.test")])
        self.assertFalse(data["user"]["has_password"])
        r = await self.client.get("/api/v1/me/export", headers=headers)
        files = zipfile.ZipFile(io.BytesIO(r.content))
        names = files.namelist()
        self.assertIn("export/identities.json", names)
        self.assertIn("export/passkeys.json", names)
        readme = files.read("export/README.txt").decode()
        self.assertIn("identities.json", readme)
        self.assertIn("passkeys.json", readme)
        passkeys = files.read("export/passkeys.json").decode()
        self.assertNotIn("public_key", passkeys)
        self.assertNotIn(authenticator.credential_id.hex(), passkeys)
        self.assertEqual(json.loads(files.read("export/identities.json"))[0]["provider"], "google")
        self.assertEqual(set(personal_data.PURPOSES), {"account", "chrono_sharing"})

    async def test_erasure_deletes_them(self) -> None:
        body = await self.social("google", "g-erase")
        headers = bearer(body)
        await self.add_passkey(headers)
        user_id = uuid.UUID(body["user"]["id"])
        await self.fetch("INSERT INTO oidc_logins (state_hash, binding_hash, provider, purpose, user_id, nonce, "
                         "code_verifier, redirect_uri, return_to, expires_at) VALUES ('h', 'b', 'google', 'link', $1, "
                         "'n', 'v', 'u', '/staff/login', now() + interval '1 minute')", user_id)
        # No password: a recent login confirms the erasure.
        await self.age_confirmation()
        r = await self.client.request("DELETE", "/api/v1/me", headers=headers, json={})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "confirmation_required"))
        await self.fetch("UPDATE sessions SET confirmed_at = now()")
        r = await self.client.request("DELETE", "/api/v1/me", headers=headers, json={})
        self.assertEqual(r.status_code, 204, r.text)
        for table in ("user_identities", "passkeys", "oidc_logins", "sessions"):
            self.assertEqual((await self.fetch(f"SELECT count(*) FROM {table}"))[0][0], 0, table)
        # The audit trail stays, and holds no subject.
        self.assertTrue(await self.audit("register"))
        self.assertNotIn("g-erase", json.dumps([dict(r) for r in await self.fetch("SELECT * FROM audit_log")], default=str))
        # The subject can make a new account afterwards.
        again = await self.social("google", "g-erase", client=self.other_client())
        self.assertNotEqual(again["user"]["id"], str(user_id))

    async def test_the_purge_drops_social_logins_never_finished(self) -> None:
        await self.begin("google")
        self.assertEqual((await self.fetch("SELECT count(*) FROM oidc_logins"))[0][0], 1)
        await self.fetch("UPDATE oidc_logins SET expires_at = now() - interval '1 minute'")
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db)
        self.assertEqual(counts["oidc_logins"], 1)
        # An unfinished attempt is also cleared by the next one.
        await self.begin("google")
        await self.fetch("UPDATE oidc_logins SET expires_at = now() - interval '1 minute'")
        await self.begin("google", client=self.other_client())
        self.assertEqual((await self.fetch("SELECT count(*) FROM oidc_logins"))[0][0], 1)
