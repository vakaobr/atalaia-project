# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The staff page for the game history shared between a hosted hub's fields (decisions HUBH-*):
``/staff/fields/<field>/hub-history``.

The page is its API (FU2-1): these tests read what it is made of. That it is in the navigation of a hosted hub only, that
every API call its script makes is a route of the application with that method, that the switch's body carries the
API's field name, that turning sharing off asks first, and that every refusal the API can give has its words in every
language. The API against a real hub: ``tests/test_hub_history.py``; the page in a browser:
``tests_browser/test_hubhistory_browser.py``.

    python3 tools/docker_server.py test tests.test_hub_history_page
"""

from __future__ import annotations

import re
from pathlib import Path

from atalaia_server.web import i18n, staff_pages
from atalaia_server.web.staff_i18n import STRINGS

from .base import AppTestCase

SERVER = Path(staff_pages.__file__).resolve().parents[2]
SCRIPT = (staff_pages.STATIC / "hubhistory.js").read_text(encoding="utf-8")
FIELD = "0192f3a4-5b6c-7d8e-9f01-23456789abcd"
CALL = re.compile(r"""api\(\s*'(GET|POST|PATCH|DELETE|PUT)',\s*fieldApi\([`']([^`']+)[`']\)""")


class HubHistoryPageTests(AppTestCase):
    async def test_the_page_in_every_language_and_the_navigation_of_a_hub_only(self) -> None:
        self.assertIn("hubhistory", staff_pages.page_names())
        self.assertIn("hubhistory.js", staff_pages.FILES)
        for lang in i18n.LANGUAGES:
            with self.subTest(lang=lang):
                r = await self.client.get(f"/staff/fields/{FIELD}/hub-history", params={"lang": lang})
                self.assertEqual(r.status_code, 200)
                self.assertIn(f"<h1>{STRINGS[lang]['hh_title']}</h1>", r.text)
                self.assertIn('data-page="hubhistory"', r.text)
                self.assertNotIn('data-section="hubhistory"', r.text)  # a single-field server: not in the navigation
        r = await self.client.get("/staff/fields/not-a-field/hub-history")
        self.assertEqual(r.status_code, 404)
        page = staff_pages.StaffPage.__new__(staff_pages.StaffPage)
        page.lang, page.explicit, page.t, page.path = "en", False, STRINGS["en"], "/"
        hub = page.sections(FIELD, "hubhistory", hosted=True)  # type: ignore[arg-type]
        self.assertIn(f'<li data-section="hubhistory"><a href="/staff/fields/{FIELD}/hub-history" aria-current="page">'
                      f'{STRINGS["en"]["nav_hubhistory"]}</a>', hub)
        self.assertNotIn("hubhistory", page.sections(FIELD, "history"))  # type: ignore[arg-type]
        self.assertIn("hubhistory: (r) => r.has('admin') || r.has('gm') || r.has('marshal')",
                      (staff_pages.STATIC / "staff.js").read_text(encoding="utf-8"))

    async def test_every_call_is_a_route_with_that_method(self) -> None:
        calls = {(m, re.sub(r"\$\{[^}]*\}", "x", p).split("?")[0]) for m, p in CALL.findall(SCRIPT)}
        self.assertEqual(calls, {("GET", "/hub-history/settings"), ("PUT", "/hub-history/settings"),
                                 ("GET", "/hub-history")})
        schema = self.app.openapi()["paths"]
        for method, path in calls:
            concrete = f"/api/v1/fields/{FIELD}{path}"
            found = [p for p, ops in schema.items() if method.lower() in ops
                     and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", p), concrete)]
            self.assertTrue(found, f"{method} {path}")
        self.assertIn("{ enabled }", SCRIPT)  # the API's SettingsIn
        self.assertIn("window.confirm(t('hh_off_confirm'))", SCRIPT)  # off withdraws: it asks first

    async def test_every_refusal_has_words_in_every_language(self) -> None:
        codes: set[str] = set()
        for source in (SERVER / "atalaia_server" / "api" / "hub_history.py",
                       SERVER / "atalaia_server" / "history_share.py"):
            text = source.read_text(encoding="utf-8")
            codes |= set(re.findall(r'HTTPException\(\d{3}, "([a-z_]+)"', text))
            codes |= set(re.findall(r'HistoryShareProblem\(\d{3}, "([a-z_]+)"', text))
        codes -= {"before_invalid"}  # the page never sends a time it did not get from the API
        self.assertTrue({"not_hosted", "field_not_found", "history_sharing_off"} <= codes, codes)
        for lang, strings in STRINGS.items():
            for code in sorted(codes):
                with self.subTest(lang=lang, code=code):
                    self.assertIn(f"hh_e_{code}", strings)
        # What is shared and what never is, said on the page in every language.
        for lang, strings in STRINGS.items():
            self.assertIn("365", strings["hh_what_keep"], lang)
