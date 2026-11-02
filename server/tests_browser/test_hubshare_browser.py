# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hub link code page in a real browser (decisions HLC-*; headless Chromium, Playwright).

    python3 tools/docker_server.py browser tests_browser.test_hubshare_browser

The browser tests run the application as a single field, where the hub's API answers 404 ``not_hosted``. So:

- on the real server: the page says there is nothing to link and the account page does not link to it;
- for a hosted hub, the test stands in for the hub's four calls (``GET/DELETE /me/hub-share``, ``POST .../code`` and
  ``.../link``, ``PUT/DELETE /me/consents/chrono-sharing/<field>``) with a small stateful fake in the browser
  (``page.route``) that answers as ``api/hub_share.py`` does, refusals included: the real answers are tried against a
  real hub in ``tests/test_hub_share.py``, and the page's own script, texts and layout run here in Chromium. Tried:
  the link on the account page, the consent (box needed, given, withdrawn), a code made and shown once, a wrong or
  used code and a rate limit in words, a link made, the fields it lists, unlinking; and the four languages at 375 px.
"""

from __future__ import annotations

import json
import re
from typing import Any

from playwright.async_api import Page, Route, expect

from tests_browser.test_login_browser import LoginBrowserCase

ACCOUNT = "/staff/account"
PAGE = "/staff/account/hub-share"
FIELD_ID = "0192f3a4-5b6c-7d8e-9f01-23456789abcd"
GOOD = "ABCD-EFGH-JKLM-NPQR-STUV-WX"


class FakeHub:
    """What a hosted hub's ``/api/v1/me/hub-share`` answers for one account, as ``hub_share.py`` does."""

    def __init__(self) -> None:
        self.linked = False
        self.consent = False
        self.live = True
        self.limited = False
        self.made = 0
        self.calls: list[str] = []

    def state(self) -> dict[str, Any]:
        out: dict[str, Any] = {"linked": self.linked, "linked_at": None, "sharing": False,
                               "field": {"id": FIELD_ID, "name": "Campo Norte", "enabled": self.live,
                                         "live": self.live},
                               "consent": self.consent, "others": []}
        if self.linked:
            out["linked_at"] = "2026-10-30T12:00:00+00:00"
            out["sharing"] = self.consent and self.live
            out["others"] = [{"field_name": "Campo Sul", "sharing": True, "since": "2026-10-30T12:00:00Z"}]
        return out

    def answer(self, method: str, path: str, body: Any) -> tuple[int, Any, dict[str, str]]:
        self.calls.append(f"{method} {path}")
        if path.endswith(("/code", "/link")) and self.limited:
            return 429, {"detail": "too_many_requests"}, {"Retry-After": "120"}
        if path == "/api/v1/me/hub-share" and method == "GET":
            return 200, self.state(), {}
        if path == "/api/v1/me/hub-share" and method == "DELETE":
            if not self.linked:
                return 404, {"detail": "not_linked"}, {}
            self.linked = False
            return 204, None, {}
        if path.endswith("/code"):
            self.linked = True  # a code makes the account's person, as new_code does
            self.made += 1
            return 201, {"code": GOOD, "expires_at": "2026-10-31T12:15:00+00:00", "expires_in": 900}, {}
        if path.endswith("/link"):
            if re.sub(r"[^A-Z0-9]", "", body.get("code", "").upper()) != GOOD.replace("-", ""):  # as normalise()
                return 400, {"detail": "invalid_code"}, {}
            self.linked = True
            return 200, self.state(), {}
        if path.endswith(f"/chrono-sharing/{FIELD_ID}"):
            if method == "PUT":
                self.consent = True
                return 201, {"purpose": "chrono_sharing", "field_id": FIELD_ID, "given": True}, {}
            if not self.consent:
                return 404, {"detail": "consent_not_found"}, {}
            self.consent = False
            return 204, None, {}
        return 404, {"detail": "not_found"}, {}


class HubShareBrowserCase(LoginBrowserCase):
    async def hosted(self, page: Page) -> FakeHub:
        hub = FakeHub()

        async def handle(route: Route) -> None:
            request = route.request
            path = request.url.split(self.base, 1)[1].split("?")[0]
            body = json.loads(request.post_data) if request.post_data else {}
            status, data, headers = hub.answer(request.method, path, body)
            await route.fulfill(status=status, headers={"Content-Type": "application/json", **headers},
                                body="" if data is None else json.dumps(data))

        await page.route(re.compile(r"/api/v1/me/hub-share(/[a-z]+)?(\?.*)?$"), handle)
        await page.route(re.compile(r"/api/v1/me/consents/chrono-sharing/[0-9a-f-]+$"), handle)
        return hub


class SingleFieldTests(HubShareBrowserCase):
    async def test_a_single_field_server_has_nothing_to_link(self) -> None:
        _, name, _ = await self.make_user()
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, None, path=ACCOUNT)
        await expect(page.locator("#passkeys-none")).to_be_visible()  # the account page has loaded its data
        await expect(page.locator("#hub-share-link")).to_be_hidden()
        await page.goto(self.base + PAGE)
        await expect(page.locator("#hub-none")).to_be_visible()
        await expect(page.locator("#hub-none")).to_contain_text("single field")
        await expect(page.locator("#hub-main")).to_be_hidden()


class HostedFlowTests(HubShareBrowserCase):
    async def test_consent_make_link_and_unlink(self) -> None:
        _, name, _ = await self.make_user()
        page = await self.new_page(lang="en-GB")
        hub = await self.hosted(page)
        await self.login(page, name, None, path=ACCOUNT)
        await expect(page.locator("#hub-share-link a")).to_be_visible()  # a hosted hub: the link shows
        await page.click("#hub-share-link a")
        await page.wait_for_url(f"{self.base}{PAGE}")
        await expect(page.locator("h1")).to_have_text("Chrono sharing between fields")
        await expect(page.locator("#hub-main")).to_be_visible()
        await expect(page.locator("#hub-field")).to_have_text("This field: Campo Norte.")
        await expect(page.locator("#hub-state")).to_contain_text("not linked to your accounts at other fields yet")
        await expect(page.locator("#hub-others-none")).to_be_visible()
        await expect(page.locator("#hub-unlink-section")).to_be_hidden()
        await expect(page.locator("#hub-field-off")).to_be_hidden()
        # The consent: the text says what is shared; the box is needed; then it is recorded for this field.
        await expect(page.locator("#hub-consent-section")).to_contain_text("signed chrono records")
        await expect(page.locator("#consent-state")).to_have_text("No consent given at this field yet.")
        await page.click("#consent-give")
        await expect(page.locator("#status")).to_have_text("Tick the box to give consent.")
        self.assertNotIn(f"PUT /api/v1/me/consents/chrono-sharing/{FIELD_ID}", hub.calls)
        await page.check("#consent-tick")
        await page.click("#consent-give")
        await expect(page.locator("#status")).to_have_text("Consent recorded.")
        await expect(page.locator("#consent-state")).to_have_text("Consent given at this field.")
        await expect(page.locator("#consent-form")).to_be_hidden()
        self.assertTrue(hub.consent)
        # A code: shown once with its time; making it makes the account's person, so the page says "linked".
        await page.click("#code-make")
        await expect(page.locator("#code-value")).to_have_text(GOOD)
        await expect(page.locator("#code-note")).to_have_text("Valid for 15 minutes and can be used once. It is not shown again.")
        # A wrong code, a used or expired one (the API says the same for all three), and the rate limit, in words.
        await page.fill("#link-code", "")
        await page.click("#link-go")
        await expect(page.locator("#status")).to_have_text("Enter the code.")
        await page.fill("#link-code", "WRONG-CODE")
        await page.click("#link-go")
        await expect(page.locator("#status")).to_contain_text("wrong, has expired or was already used")
        hub.limited = True
        await page.fill("#link-code", GOOD)
        await page.click("#link-go")
        await expect(page.locator("#status")).to_have_text("Too many requests. Try again in 120 s.")
        await page.click("#code-make")
        await expect(page.locator("#status")).to_have_text("Too many requests. Try again in 120 s.")
        hub.limited = False
        # The right code links; the other field is listed with its state; the unlink button appears.
        await page.fill("#link-code", GOOD.lower().replace("-", " "))
        await page.click("#link-go")
        await expect(page.locator("#status")).to_have_text("Accounts linked.")
        await expect(page.locator("#link-code")).to_have_value("")
        await expect(page.locator("#hub-state")).to_contain_text("This account has been linked since")
        await expect(page.locator("#hub-sharing")).to_contain_text("Sharing:")
        await expect(page.locator("#hub-others li")).to_have_count(2)
        await expect(page.locator("#hub-others")).to_contain_text("Campo Sul")
        await expect(page.locator("#hub-others-none")).to_be_hidden()
        await expect(page.locator("#hub-unlink-section")).to_be_visible()
        # Withdrawing the consent asks first (the dialog is accepted), and sharing stops.
        await page.click("#consent-withdraw")
        await expect(page.locator("#status")).to_have_text("Consent withdrawn.")
        await expect(page.locator("#hub-sharing")).to_contain_text("Nothing is shared yet")
        self.assertIn("Withdraw your consent at this field?", self.dialogs[-1])
        # Unlinking asks first, then the page is as at the start.
        await page.click("#unlink")
        await expect(page.locator("#status")).to_have_text("Account unlinked.")
        self.assertIn("Unlink this account", self.dialogs[-1])
        await expect(page.locator("#hub-state")).to_contain_text("not linked")
        await expect(page.locator("#hub-unlink-section")).to_be_hidden()
        self.assertFalse(hub.linked)

    async def test_a_field_with_sharing_off_says_so(self) -> None:
        _, name, _ = await self.make_user()
        page = await self.new_page(lang="en-GB")
        hub = await self.hosted(page)
        hub.live = False
        await self.login(page, name, None, path=PAGE)
        await expect(page.locator("#hub-field-off")).to_be_visible()
        await expect(page.locator("#hub-field-off")).to_contain_text("nothing is shared until that changes")

    async def test_the_four_languages_at_375_px(self) -> None:
        _, name, _ = await self.make_user()
        for lang, title, button in (("de-DE", "Chrono-Freigabe zwischen Spielfeldern", "Code erzeugen"),
                                    ("pt-PT", "Cronografagem entre campos", "Gerar código"),
                                    ("en-GB", "Chrono sharing between fields", "Make a code"),
                                    ("zh-TW", "場地之間的測速分享", "產生代碼")):
            with self.subTest(lang=lang):
                page = await self.new_page(lang=lang)
                hub = await self.hosted(page)
                hub.linked = True
                hub.consent = True
                await self.login(page, name, None, path=PAGE)
                await expect(page.locator("h1")).to_have_text(title)
                await expect(page.locator("#code-make")).to_have_text(button)
                await page.click("#code-make")
                await expect(page.locator("#code-box")).to_be_visible()
                await expect(page.locator("#hub-others li")).to_have_count(2)
                await self.check_page(page, 375)
