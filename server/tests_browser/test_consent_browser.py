# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The privacy notice page and the "consent again" panel in a real browser (decisions CONS-*; headless Chromium).

    python3 tools/docker_server.py browser tests_browser.test_consent_browser

The real application under uvicorn over HTTPS with a notice folder: the public page `/privacy`, and the staff pages'
panel after login when the notice's version changed (it reads the notice, needs the tick, consents, and is gone
for the session; an account that is current is not asked).
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

from playwright.async_api import expect

from atalaia_server import privacy_notice
from atalaia_server.config import Settings
from tests_browser.test_staff_browser import BrowserCase

V1, V2 = "campo-v1", "campo-v2"


class ConsentBrowserTests(BrowserCase):
    async def asyncSetUp(self) -> None:
        self.folder = tempfile.TemporaryDirectory()
        base = Path(self.folder.name)
        for version in (V1, V2):
            (base / privacy_notice.filename("en", version)).write_text(
                f"# Privacy notice {version}\n\nThe operator is **Tejo Field**.\n", encoding="utf-8")
        await super().asyncSetUp()

    async def asyncTearDown(self) -> None:
        await super().asyncTearDown()
        self.folder.cleanup()

    def settings(self) -> Settings:
        return dataclasses.replace(super().settings(), privacy_notice_dir=self.folder.name,
                                   privacy_notice_version=V1)

    async def test_the_public_page(self) -> None:
        page = await self.new_page(lang="en-GB")
        await page.goto(self.base + "/privacy")
        await expect(page.locator("h1")).to_have_text(f"Privacy notice {V1}")
        await expect(page.locator("article.privacy strong")).to_have_text("Tejo Field")
        await self.check_page(page)
        await page.goto(self.base + "/privacy?lang=de")
        await expect(page.locator("p.notice")).to_contain_text("Deutsch")  # no German file: said in German

    async def test_a_changed_notice_asks_for_consent_once(self) -> None:
        _, name, _ = await self.make_user()
        await self.fetch("INSERT INTO consents (user_id, purpose, notice_version) "
                         "SELECT id, 'account', $2 FROM users WHERE username = $1", name, V1)
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, None)
        await expect(page.locator("#who")).to_contain_text(name)
        await expect(page.locator("#consent")).to_have_count(0)  # consented to the current version: not asked
        # The operator raises the version; the next login is asked.
        self.app.state.settings = dataclasses.replace(self.app.state.settings, privacy_notice_version=V2)
        await page.click("#logout")
        await page.wait_for_url("**/staff/login?out=1")
        await self.login(page, name, None)
        panel = page.locator("#consent")
        await expect(panel).to_be_visible()
        await expect(panel).to_contain_text(f"version {V1}, now {V2}")
        await expect(panel.locator("a")).to_have_attribute("href", "/privacy")
        await self.check_page(page)
        # Without the tick nothing is sent.
        await page.click("#consent-button")
        await expect(page.locator("#status")).to_contain_text("Tick first")
        await expect(panel).to_be_visible()
        await page.check("#consent-tick")
        await page.click("#consent-button")
        await expect(page.locator("#status")).to_contain_text("Consent recorded")
        await expect(panel).to_have_count(0)
        rows = await self.fetch("SELECT notice_version, withdrawn_at IS NULL AS live FROM consents ORDER BY given_at")
        self.assertEqual([(r["notice_version"], r["live"]) for r in rows], [(V1, False), (V2, True)])
        await page.reload()
        await expect(page.locator("#who")).to_contain_text(name)
        await expect(page.locator("#consent")).to_have_count(0)
