# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A preview deployment in a real browser (decisions PV-*): the demo's pages with the banner, the feedback form
filled in and sent in two languages, and the server administrator reading, marking and deleting it on the staff
page (a message that is markup stays text).

    python3 tools/docker_server.py browser tests_browser.test_preview_browser
"""

from __future__ import annotations

import asyncio
import re

from atalaia_server import demo_data
from atalaia_server.config import Settings

from .test_staff_browser import BrowserCase, expect

EVIL = '<img src=x onerror="window.pwned=1">'


class PreviewBrowserTests(BrowserCase):
    def settings(self) -> Settings:
        s = super().settings()
        return Settings(database_url=s.database_url, secret_key=s.secret_key, metrics_token=s.metrics_token,
                        db_timeout_s=2.0, purge_hour=None, preview=True)

    async def test_the_visitor_and_the_administrator(self) -> None:
        async with self.app.state.sessionmaker() as db:
            await demo_data.load(db)
        page = await self.new_page("de-DE")
        # The landing page, in the browser's language, and the demo's pages with the banner.
        await page.goto(self.base + "/")
        await expect(page.locator("h1")).to_have_text("Atalaia: Vorschauserver")
        await expect(page.locator(".preview-banner")).to_contain_text("Vorschau, nicht für echte Spiele")
        await self.check_page(page)
        await page.goto(self.base + f"/f/{demo_data.FIELD_SLUG}/?lang=en")
        await expect(page.locator(".preview-banner")).to_contain_text("Preview, not for real games")
        await expect(page.locator("ul.list li")).to_have_count(4)
        await page.goto(self.base + f"/f/{demo_data.FIELD_SLUG}/scoreboard?lang=en")
        await expect(page.locator("table.scores tr")).to_have_count(3)
        # The banner leads to the form, which remembers the page.
        await page.click(".preview-banner a")
        await page.wait_for_url(re.compile(r"/feedback\?lang=en&from=/f/campo-demo/scoreboard$"))
        await expect(page.locator("h1")).to_have_text("Your feedback")
        await self.check_page(page)
        await asyncio.sleep(3.5)  # a person takes longer than the token's minimum age
        await page.check("input[name=kind][value=usability]")
        await page.select_option("#who", "organiser")
        await page.fill("#message", f"Hard to find the scoreboard. {EVIL}")
        await page.fill("#contact", "someone@example.pt")
        await page.click("form.feedback button[type=submit]")
        await page.wait_for_url(re.compile(r"/feedback\?lang=en&sent=1"))
        await expect(page.locator("[role=status]")).to_have_text("Thank you! Your feedback was saved.")
        # And in Traditional Chinese.
        await page.goto(self.base + "/feedback?lang=zh-tw")
        await expect(page.locator("h1")).to_have_text("您的意見")
        await asyncio.sleep(3.5)
        await page.check("input[name=kind][value=good]")
        await page.fill("#message", "計分板很清楚。")
        await page.click("form.feedback button[type=submit]")
        await expect(page.locator("[role=status]")).to_have_text("謝謝！您的意見已儲存。")
        rows = await self.fetch("SELECT kind, who, lang, page FROM preview_feedback ORDER BY created_at")
        self.assertEqual([tuple(r) for r in rows],
                         [("usability", "organiser", "en", f"/f/{demo_data.FIELD_SLUG}/scoreboard"),
                          ("good", None, "zh-tw", None)])
        # The administrator reads it.
        _, name, secret = await self.make_user(server_admin=True)
        admin = await self.new_page("en-GB")
        await self.login(admin, name, secret, "/staff/")
        await expect(admin.locator("#feedback-link a")).to_be_visible()
        await admin.click("#feedback-link a")
        await admin.wait_for_url(re.compile(r"/staff/feedback"))
        table = admin.locator("#feedback tbody tr")
        await expect(table).to_have_count(2)
        await expect(admin.locator("#feedback-counts")).to_have_text("2 new, 0 seen, 0 done")
        await expect(table.nth(1)).to_contain_text("Hard to find the scoreboard.")
        await expect(table.nth(1)).to_contain_text("someone@example.pt")
        self.assertEqual(await admin.locator("#feedback img").count(), 0)  # markup in a message stays text
        self.assertIsNone(await admin.evaluate("() => window.pwned"))
        await self.check_page(admin)
        await table.nth(1).locator("select").select_option("seen")
        await expect(admin.locator("#feedback-counts")).to_have_text("1 new, 1 seen, 0 done")
        await expect(table).to_have_count(1)
        await admin.select_option("#f-status", "all")
        await expect(table).to_have_count(2)
        await table.nth(0).get_by_role("button").click()  # the confirmation is accepted by the test's browser
        await expect(table).to_have_count(1)
        self.assertEqual((await self.fetch("SELECT count(*) FROM preview_feedback"))[0][0], 1)
