# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The page for the game history shared between a hosted hub's fields, in a real browser (decisions HUBH-*; headless
Chromium, Playwright).

    python3 tools/docker_server.py browser tests_browser.test_hubhistory_browser

The browser tests run the application as a single field, where the API answers 404 ``not_hosted``. So, as for the hub
link code page (HLC-10):

- on the real server: the page says there is no other field, and the navigation has no such section;
- for a hosted hub, the test stands in for the page's three calls (``GET``/``PUT .../hub-history/settings`` and
  ``GET .../hub-history``) with a small stateful fake in the browser (``page.route``) that answers as
  ``api/hub_history.py`` does, refusals included: the real answers are tried against a real hub in
  ``tests/test_hub_history.py``, and the page's own script, texts and layout run here in Chromium. Tried: off by
  default with the reciprocity note, the admin turns it on and sees the fields and games (never a player), the mode
  filter and the next page, turning it off asks first and withdraws, a gm sees the list but not the switch, and the four
  languages at 375 px.
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

from playwright.async_api import Page, Route, expect

from tests_browser.test_staff_browser import BrowserCase

GAMES = [
    {"field_name": "Campo Sul", "own": False, "mode_id": "org.atalaia.domination", "started_at": "2026-11-01T10:00:00+00:00",
     "ended_at": "2026-11-01T11:00:00+00:00", "teams": [{"team": "red", "score": 42}, {"team": "blue", "score": 17}],
     "winner": "red"},
    {"field_name": "Campo Norte", "own": True, "mode_id": "org.atalaia.bomb", "started_at": "2026-10-31T10:00:00+00:00",
     "ended_at": "2026-10-31T10:40:00+00:00", "teams": [{"team": "red", "score": 3}, {"team": "blue", "score": 3}],
     "winner": None},
    {"field_name": "Campo Sul", "own": False, "mode_id": "org.atalaia.domination", "started_at": "2026-10-30T10:00:00+00:00",
     "ended_at": "2026-10-30T11:00:00+00:00", "teams": [{"team": "red", "score": 1}, {"team": "blue", "score": 9}],
     "winner": "blue"},
]


class FakeHubHistory:
    """What a hosted hub's ``/api/v1/fields/<field>/hub-history`` answers, as ``api/hub_history.py`` does."""

    def __init__(self, field_id: str) -> None:
        self.field_id = field_id
        self.enabled = False
        self.admin = True
        self.calls: list[str] = []

    def state(self) -> dict[str, Any]:
        return {"hosted": True, "field": {"id": self.field_id, "name": "Campo Norte"}, "enabled": self.enabled,
                "since": "2026-11-04T09:00:00+00:00" if self.enabled else None, "member": self.enabled,
                "shared_games": 1 if self.enabled else 0}

    def answer(self, method: str, path: str, query: dict[str, list[str]], body: Any) -> tuple[int, Any]:
        self.calls.append(f"{method} {path}")
        if path.endswith("/hub-history/settings"):
            if method == "PUT":
                if not self.admin:
                    return 403, {"detail": "role_required"}
                self.enabled = bool(body.get("enabled"))
            return 200, self.state()
        if not self.enabled:
            return 403, {"detail": "history_sharing_off"}
        games = [g for g in GAMES if not query.get("mode") or g["mode_id"] == query["mode"][0]]
        if query.get("before"):
            games = [g for g in games if g["ended_at"] < query["before"][0]]
        limit = int(query.get("limit", ["50"])[0])
        page = games[:limit]
        return 200, {"fields": [{"field_name": "Campo Norte", "own": True, "since": "2026-11-04T09:00:00+00:00", "games": 1},
                                {"field_name": "Campo Sul", "own": False, "since": "2026-10-20T09:00:00+00:00", "games": 2}],
                     "games": page, "next_before": page[-1]["ended_at"] if len(page) == limit and page else None}


class HubHistoryBrowserCase(BrowserCase):
    async def hosted(self, page: Page) -> FakeHubHistory:
        hub = FakeHubHistory(str(self.field_id))

        async def handle(route: Route) -> None:
            request = route.request
            parts = urlsplit(request.url)
            body = json.loads(request.post_data) if request.post_data else {}
            status, data = hub.answer(request.method, parts.path, parse_qs(parts.query), body)
            await route.fulfill(status=status, headers={"Content-Type": "application/json"}, body=json.dumps(data))

        await page.route(re.compile(r"/api/v1/fields/[0-9a-f-]+/hub-history(/settings)?(\?.*)?$"), handle)
        return hub


class SingleFieldTests(HubHistoryBrowserCase):
    async def test_a_single_field_server_has_no_other_field(self) -> None:
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/hub-history"))
        await expect(page.locator("#hh-none")).to_be_visible()
        await expect(page.locator("#hh-none")).to_contain_text("single field")
        await expect(page.locator("#hh-main")).to_be_hidden()
        await expect(page.locator('#sections li[data-section="hubhistory"]')).to_have_count(0)


class HostedFlowTests(HubHistoryBrowserCase):
    async def test_the_admin_opts_in_reads_and_opts_out(self) -> None:
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        hub = await self.hosted(page)
        await self.login(page, name, secret, self.field_path("/hub-history"))
        await expect(page.locator("h1")).to_have_text("Game history across fields")
        await expect(page.locator("#hh-main")).to_be_visible()
        # Off by default; the list says a field must share to see the others'.
        await expect(page.locator("#hh-state")).to_have_text("This field does not share its game history.")
        await expect(page.locator("#hh-enabled")).not_to_be_checked()
        await expect(page.locator("#hh-off")).to_be_visible()
        await expect(page.locator("#hh-list")).to_be_hidden()
        await expect(page.locator("#hh-switch-section")).to_contain_text("Never: who played")
        self.assertNotIn("GET /api/v1/fields/%s/hub-history" % self.field_id, hub.calls)  # not even asked
        # Saving with nothing changed says so; turning it on shares and shows the fields and games.
        await page.click("#hh-save")
        await expect(page.locator("#status")).to_have_text("Nothing changed.")
        await page.check("#hh-enabled")
        await page.click("#hh-save")
        await expect(page.locator("#status")).to_have_text("Sharing on: this field's ended games are shared.")
        await expect(page.locator("#hh-state")).to_contain_text("1 game shared")
        await expect(page.locator("#hh-off")).to_be_hidden()
        await expect(page.locator("#hh-fields li")).to_have_count(2)
        await expect(page.locator("#hh-fields")).to_contain_text("Campo Norte (this field)")
        rows = page.locator("#hh-table tbody tr")
        await expect(rows).to_have_count(3)
        await expect(rows.first).to_contain_text("Campo Sul")
        await expect(rows.first).to_contain_text("red 42 · blue 17")
        await expect(rows.nth(1)).to_contain_text("draw")
        # The mode filter, then the next page.
        await page.fill("#hh-mode", "org.atalaia.bomb")
        await page.click("#hh-apply")
        await expect(rows).to_have_count(1)
        await expect(rows.first).to_contain_text("org.atalaia.bomb")
        await page.fill("#hh-mode", "")
        await page.click("#hh-apply")
        await expect(rows).to_have_count(3)
        await expect(page.locator("#hh-more")).to_be_hidden()
        # Turning it off asks first (the dialog is accepted) and withdraws.
        await page.uncheck("#hh-enabled")
        await page.click("#hh-save")
        await expect(page.locator("#status")).to_have_text("Sharing off: this field's games were withdrawn.")
        self.assertIn("Every game this field shared is withdrawn now", self.dialogs[-1])
        await expect(page.locator("#hh-off")).to_be_visible()
        await expect(page.locator("#hh-list")).to_be_hidden()
        self.assertFalse(hub.enabled)
        await self.check_page(page)

    async def test_a_gm_reads_but_does_not_switch(self) -> None:
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        hub = await self.hosted(page)
        hub.enabled = True
        hub.admin = False
        await self.login(page, name, secret, self.field_path("/hub-history"))
        await expect(page.locator("#hh-admin-only")).to_be_visible()
        await expect(page.locator("#hh-form")).to_be_hidden()
        await expect(page.locator("#hh-table tbody tr")).to_have_count(3)

    async def test_the_four_languages_at_375_px(self) -> None:
        name, secret = await self.staff("admin")
        for lang, title, label in (("pt-PT", "Histórico de jogos entre campos", "Jogos partilhados"),
                                   ("en-GB", "Game history across fields", "Shared games"),
                                   ("de-DE", "Spielverlauf zwischen Spielfeldern", "Geteilte Spiele"),
                                   ("zh-TW", "跨場地的遊戲紀錄", "分享的遊戲")):
            with self.subTest(lang=lang):
                page = await self.new_page(lang=lang)
                hub = await self.hosted(page)
                hub.enabled = True
                await self.login(page, name, secret, self.field_path("/hub-history"))
                await expect(page.locator("h1")).to_have_text(title)
                await expect(page.locator("#hh-list-title")).to_have_text(label)
                await expect(page.locator("#hh-table tbody tr")).to_have_count(3)
                await self.check_page(page, 375)
