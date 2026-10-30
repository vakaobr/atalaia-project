# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The staff login's other ways in, in a real browser (decisions LG-*; headless Chromium, Playwright).

    python3 tools/docker_server.py browser tests_browser.test_login_browser

The same setup as ``test_staff_browser`` (the real application under uvicorn over HTTPS next to its own
PostgreSQL database), with Google configured and a fake provider in its place (tests/login_fakes.py):

- a passkey: made in the page with a CDP virtual authenticator (user verification on, a resident key), then
  "Log in with a passkey" on the login page, no username and no code afterwards, and the session counts for a
  gm's role without TOTP;
- a social login: the browser goes to the provider's address (answered by the test with a redirect back, as a
  provider would), the callback sets nothing but a ticket in the address fragment, the page makes the session;
  an unknown subject needs the consent box; a provider's refusal is shown in words; the address is cleaned;
- the second factor of such a session: a gm that logged in with Google is offered the TOTP step-up, and the roles count
  from then on;
- password login off: no password form, the other buttons;
- the four languages and a phone's width.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from playwright.async_api import Page, expect

from atalaia_server.config import OidcClient, Settings
from tests.base import METRICS_TOKEN, PASSWORD, SECRET_KEY
from tests.login_fakes import FakeIdp
from tests_browser.test_staff_browser import BrowserCase


class LoginBrowserCase(BrowserCase):
    password_login = True

    def settings(self) -> Settings:
        return Settings(allow_signup_without_notice=True, database_url=self.database_url, secret_key=SECRET_KEY, metrics_token=METRICS_TOKEN,
                        db_timeout_s=2.0, purge_hour=self.purge_hour, password_login=self.password_login,
                        oidc=(OidcClient("google", "google-id", client_secret="google-secret"),))

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.idp = FakeIdp()
        self.app.state.oidc.http = self.idp
        self.subject = "g-browser"
        self.claims: dict[str, Any] = {}

    async def provider(self, page: Page, *, deny: bool = False) -> None:
        """Answers the browser's trip to Google: a redirect back to the callback, with a code that yields
        ``self.subject`` (or the user's refusal)."""

        async def handle(route: Any) -> None:
            params = self.idp.authorize(route.request.url)
            back = f"{params['redirect_uri']}?state={params['state']}"
            if deny:
                back += "&error=access_denied"
            else:
                code = self.idp.grant(params, self.idp.claims("google", "google-id", self.subject, params["nonce"],
                                                              **self.claims))
                back += f"&code={code}"
            await route.fulfill(status=302, headers={"location": back})

        await page.route("https://accounts.google.com/**", handle)

    async def virtual_authenticator(self, page: Page) -> None:
        cdp = await page.context.new_cdp_session(page)
        await cdp.send("WebAuthn.enable")
        await cdp.send("WebAuthn.addVirtualAuthenticator", {"options": {
            "protocol": "ctap2", "transport": "internal", "hasResidentKey": True, "hasUserVerification": True,
            "isUserVerified": True, "automaticPresenceSimulation": True}})

    async def session_json(self, page: Page) -> dict[str, Any]:
        raw = await page.evaluate("() => sessionStorage.getItem('atalaia.staff.session')")
        return json.loads(raw)


class PasskeyBrowserTests(LoginBrowserCase):
    async def test_log_in_with_a_registered_passkey(self) -> None:
        user_id, name, _ = await self.make_user()
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 5)", user_id,
                         self.field_id)
        page = await self.new_page(lang="en-GB")
        await self.virtual_authenticator(page)
        await page.goto(self.base + "/staff/login")
        # Make the passkey as the app would: a password session, the options, the authenticator, the answer.
        registered = await page.evaluate("""async ([name, password]) => {
            const { creationOptions, attestationJson } = await import('/static/staff/webauthn.js');
            const call = async (path, body, token) => {
                const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json',
                    ...(token ? { Authorization: `Bearer ${token}` } : {}) }, body: JSON.stringify(body) });
                return { status: r.status, body: await r.json() };
            };
            const session = await call('/api/v1/auth/login', { username: name, password });
            const token = session.body.access_token;
            const parts = await call('/api/v1/me/passkeys/options', { password }, token);
            const credential = await navigator.credentials.create({ publicKey: creationOptions(parts.body.options) });
            const added = await call('/api/v1/me/passkeys', { challenge_token: parts.body.challenge_token,
                credential: attestationJson(credential), name: 'Browser' }, token);
            return { status: added.status, name: added.body.name };
        }""", [name, PASSWORD])
        self.assertEqual(registered, {"status": 201, "name": "Browser"})
        await page.goto(self.base + "/staff/login")  # forgets the session
        await page.click("#passkey-login")
        await page.wait_for_url(f"{self.base}/staff/")
        session = await self.session_json(page)
        self.assertTrue(session["mfa"])  # a passkey is both factors
        self.assertEqual(session["user"]["username"], name)
        await expect(page.locator("#stepup")).to_have_count(0)
        await expect(page.locator("#mfa-note")).to_be_hidden()
        # The gm role counts with no TOTP step: the field's history page opens.
        await page.goto(self.base + self.field_path("/history"))
        await expect(page.locator("#field-name")).to_have_text("Field: Campo Norte")
        await expect(page.locator("#sections li[data-section=schedule]")).to_be_visible()
        await page.click("#logout")
        await page.wait_for_url("**/staff/login?out=1")
        rows = await self.fetch("SELECT last_used_at FROM passkeys")
        self.assertIsNotNone(rows[0]["last_used_at"])


class SocialBrowserTests(LoginBrowserCase):
    async def test_a_new_account_needs_the_consent_box(self) -> None:
        page = await self.new_page(lang="en-GB")
        await self.provider(page)
        await page.goto(self.base + "/staff/login?next=%2Fstaff%2F&lang=en")
        button = page.locator("button.provider[data-provider=google]")
        await expect(button).to_have_text("Continue with Google")
        await button.click()
        await page.wait_for_url("**/staff/login?next=*")
        # The refusal is at the box (LG-12): an error with role=alert next to it, the box marked and focused.
        error = page.locator("#consent-error")
        await expect(error).to_be_visible()
        await expect(error).to_contain_text("tick the agreement box")
        self.assertEqual(await error.get_attribute("role"), "alert")
        await expect(page.locator("#consent")).to_be_focused()
        await expect(page.locator("#consent")).to_have_attribute("aria-invalid", "true")
        await expect(page.locator("#status")).to_be_empty()
        self.assertNotIn("oidc", page.url)  # the address is cleaned
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 0)
        await page.check("#consent")
        await expect(error).to_be_hidden()
        await button.click()
        # A new account is taken to the "choose your username" step first; skipping it goes on.
        await page.wait_for_url("**/staff/account?*welcome=1*")
        await expect(page.locator("#username-title")).to_have_text("Choose your username")
        await expect(page.locator("#username-name")).to_have_text("Use my Google name")
        await page.click("#username-skip")
        await page.wait_for_url(f"{self.base}/staff/")
        session = await self.session_json(page)
        self.assertFalse(session["mfa"])
        self.assertTrue(session["user"]["username"].startswith("user-"))
        users = await self.fetch("SELECT password_hash, email FROM users")
        self.assertEqual([(u["password_hash"], u["email"]) for u in users], [(None, None)])
        await expect(page.locator("#stepup")).to_have_count(0)  # no role, nothing to confirm
        # The same Google account again is the same account.
        await page.click("#logout")
        await page.wait_for_url("**/staff/login?out=1*")
        await page.locator("button.provider[data-provider=google]").click()
        await page.wait_for_url(f"{self.base}/staff/")
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 1)

    async def test_the_provider_may_say_no(self) -> None:
        page = await self.new_page(lang="en-GB")
        await self.provider(page, deny=True)
        await page.goto(self.base + "/staff/login")
        await page.check("#consent")
        await page.locator("button.provider").click()
        await expect(page.locator("#status")).to_have_text("The login was refused at the provider.")
        self.assertEqual(urlsplit(page.url).query, "")
        self.assertEqual(urlsplit(page.url).fragment, "")

    async def test_a_gm_that_logged_in_with_google_confirms_with_totp(self) -> None:
        name, secret = await self.staff("gm")
        user_id = (await self.fetch("SELECT id FROM users WHERE username = $1", name))[0][0]
        await self.fetch("INSERT INTO user_identities (user_id, provider, subject) VALUES ($1, 'google', $2)", user_id,
                         self.subject)
        page = await self.new_page(lang="en-GB")
        await self.provider(page)
        await page.goto(self.base + self.field_path("/history"))
        await page.wait_for_url("**/staff/login?next=*")
        await page.locator("button.provider").click()
        await page.wait_for_url(f"{self.base}{self.field_path('/history')}")
        session = await self.session_json(page)
        self.assertFalse(session["mfa"])  # a social login alone does not count
        panel = page.locator("#stepup")
        await expect(panel).to_be_visible()
        await expect(panel).to_contain_text("Confirm the second factor")
        await expect(page.locator("#settings")).to_be_hidden()  # the admin/gm sections do not count yet
        await page.fill("#stepup-code", "000000")
        await page.click("#stepup button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Wrong code.")
        await page.fill("#stepup-code", self.code(secret))
        await page.click("#stepup button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Second factor confirmed.")
        await expect(page.locator("#stepup")).to_have_count(0)  # the page reloads, now with the role counting
        await expect(page.locator("#field-name")).to_have_text("Field: Campo Norte")
        self.assertTrue((await self.session_json(page))["mfa"])
        await expect(page.locator("#sections li[data-section=schedule]")).to_be_visible()

    async def test_the_login_page_in_four_languages_and_at_a_phones_width(self) -> None:
        for lang, text in (("pt-PT", "Continuar com Google"), ("en-GB", "Continue with Google"),
                           ("de-DE", "Weiter mit Google"), ("zh-TW", "使用 Google 繼續")):
            with self.subTest(lang=lang):
                page = await self.new_page(lang=lang)
                await page.goto(self.base + "/staff/login")
                await expect(page.locator("button.provider")).to_have_text(text)
                await expect(page.locator("#consent-row")).to_be_visible()
                await self.check_page(page)


class PasswordOffBrowserTests(LoginBrowserCase):
    password_login = False

    async def test_no_password_form(self) -> None:
        page = await self.new_page(lang="en-GB")
        await page.goto(self.base + "/staff/login")
        await expect(page.locator("button.provider")).to_be_visible()
        await expect(page.locator("#login-form")).to_be_hidden()
        await expect(page.locator("#login-or")).to_be_hidden()
        await self.check_page(page)
        # The API agrees.
        _, name, _ = await self.make_user()
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        self.assertEqual(r.status_code, 403)

