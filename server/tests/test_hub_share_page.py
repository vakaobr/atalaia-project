# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hub link code page (decisions HLC-*): ``/staff/account/hub-share``, in hosted mode a person's way to tie their
accounts at different fields with a one-time link code (SVX-2), linked from the account page.

The page is its API (FU2-1): these tests read what it is made of. That it is listed, in every language, linked from
the account page (hidden until the API says the server is a hub), that every API call its script makes is a route of
the application with that method, that the bodies carry the API's field names, and that every refusal the hub's API
and the consent endpoints can give has its words in every language. The API against a real hub:
``tests/test_hub_share.py``; the page in a browser: ``tests_browser/test_hubshare_browser.py``.

    python3 tools/docker_server.py test tests.test_hub_share_page
"""

from __future__ import annotations

import re
from pathlib import Path

from atalaia_server import hub_share
from atalaia_server.web import i18n, staff_pages
from atalaia_server.web.staff_i18n import STRINGS

from .base import AppTestCase

SERVER = Path(staff_pages.__file__).resolve().parents[2]
SCRIPT = (staff_pages.STATIC / "hubshare.js").read_text(encoding="utf-8")
ACCOUNT_SCRIPT = (staff_pages.STATIC / "account.js").read_text(encoding="utf-8")
CALL = re.compile(r"""api\(\s*'(GET|POST|PATCH|DELETE|PUT)',\s*[`']([^`']+)[`']""")


def called(script: str) -> list[tuple[str, str]]:
    """The (method, path) of every ``api(...)`` call in the script, a ``${...}`` made a path value."""
    return [(m, re.sub(r"\$\{[^}]*\}", "x", p)) for m, p in CALL.findall(script)]


class HubSharePageTests(AppTestCase):
    async def test_the_page_is_listed_in_every_language_and_holds_no_data(self) -> None:
        self.assertIn("hubshare", staff_pages.page_names())
        self.assertIn("hubshare.js", staff_pages.FILES)
        for lang in i18n.LANGUAGES:
            with self.subTest(lang=lang):
                r = await self.client.get("/staff/account/hub-share", params={"lang": lang})
                self.assertEqual(r.status_code, 200)
                self.assertIn(f"<h1>{STRINGS[lang]['hub_title']}</h1>", r.text)
                self.assertEqual(r.headers["cache-control"], "no-store")
                self.assertEqual(r.headers["x-robots-tag"], "noindex")
                self.assertIn(f'href="/staff/account?lang={lang}"', r.text)  # the way back keeps the language
                self.assertIn('data-page="hubshare"', r.text)
        # No notice published here: no link to one (it is the consent's reading text only when there is one).
        self.assertNotIn('id="notice-link"', r.text)

    async def test_the_account_page_links_to_it_and_only_a_hub_shows_the_link(self) -> None:
        for lang in i18n.LANGUAGES:
            with self.subTest(lang=lang):
                r = await self.client.get("/staff/account", params={"lang": lang})
                self.assertIn(f'<p id="hub-share-link" hidden><a href="/staff/account/hub-share?lang={lang}">'
                              f'{STRINGS[lang]["hub_link"]}</a>', r.text)
        r = await self.client.get("/staff/account")
        self.assertIn('<a href="/staff/account/hub-share">', r.text)  # no ?lang= when none was asked
        # The link shows only when the API answers (a single-field server answers 404 not_hosted).
        self.assertEqual(called(ACCOUNT_SCRIPT).count(("GET", "/api/v1/me/hub-share")), 1)
        self.assertIn("$('hub-share-link').hidden = false", ACCOUNT_SCRIPT)
        r = await self.client.get("/api/v1/me/hub-share")
        self.assertEqual(r.status_code, 401)
        _, name, _ = await self.make_user()
        auth = await self.auth(name)
        r = await self.client.get("/api/v1/me/hub-share", headers=auth)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "not_hosted"))

    async def test_every_api_path_the_script_calls_exists(self) -> None:
        calls = called(SCRIPT)
        spec = (await self.client.get("/api/v1/openapi.json")).json()["paths"]
        for method, path in calls:
            with self.subTest(call=f"{method} {path}"):
                found = [p for p, ops in spec.items() if method.lower() in ops
                         and re.fullmatch(re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(p)), path)]
                self.assertTrue(found, f"{method} {path} is no route of the application")
        have = {f"{m} {p}" for m, p in calls}
        for wanted in ("GET /api/v1/me/hub-share", "POST /api/v1/me/hub-share/code", "DELETE /api/v1/me/hub-share",
                       "PUT /api/v1/me/consents/chrono-sharing/x", "DELETE /api/v1/me/consents/chrono-sharing/x"):
            self.assertIn(wanted, have)
        self.assertIn("{ code }", SCRIPT)  # the body the link call sends: the API's LinkIn
        self.assertIn("('POST', '/api/v1/me/hub-share/link', { code })", SCRIPT)

    async def test_every_refusal_has_words_in_every_language(self) -> None:
        """The codes the hub's endpoints and the consent endpoints give (read from their source) each have a text on
        this page, apart from the rate limit, which the shared texts word with the seconds to wait."""
        codes: set[str] = set()
        for source in ((SERVER / "atalaia_server" / "api" / "hub_share.py"),
                       (SERVER / "atalaia_server" / "hub_share.py")):
            text = source.read_text(encoding="utf-8")
            codes |= set(re.findall(r'HTTPException\(\d{3}, "([a-z_]+)"', text))
            codes |= set(re.findall(r'HubShareProblem\(\d{3}, "([a-z_]+)"', text))
        codes |= {"consent_not_found"}  # DELETE /me/consents/chrono-sharing/<field>
        codes -= {"too_many_requests", "not_authenticated"}
        self.assertTrue({"invalid_code", "already_linked", "person_already_linked_here", "not_linked", "not_hosted",
                         "field_not_found"} <= codes, codes)
        for lang, strings in STRINGS.items():
            for code in sorted(codes):
                with self.subTest(lang=lang, code=code):
                    self.assertIn(f"hub_e_{code}", strings)
        self.assertIn("err_rate", STRINGS["en"])
        self.assertIn("errorText(err)", SCRIPT)
        # The one answer for a wrong, an expired and a used code names all three, in every language.
        self.assertIn("expired", STRINGS["en"]["hub_e_invalid_code"])
        self.assertIn("used", STRINGS["en"]["hub_e_invalid_code"])
        self.assertIn("wrong", STRINGS["en"]["hub_e_invalid_code"])
        self.assertEqual(hub_share.CODE_TTL_S, 900)  # the "15 minutes" the page computes from expires_in

    async def test_the_consent_is_recorded_the_way_the_api_requires(self) -> None:
        """The page sends the consent the API wants: a PUT for this field's id (from the API's own answer), never a
        body; the tick must be set first; the withdrawal is the DELETE."""
        self.assertIn("/api/v1/me/consents/chrono-sharing/${encodeURIComponent(current.field.id)}", SCRIPT)
        self.assertRegex(SCRIPT, r"if \(!\$\('consent-tick'\)\.checked\)")
        self.assertIn("hub_consent_tick_needed", SCRIPT)
        self.assertIn("window.confirm(t('hub_consent_withdraw_confirm'))", SCRIPT)
        self.assertIn("window.confirm(t('hub_unlink_confirm'))", SCRIPT)
        for lang, strings in STRINGS.items():  # the text the box is ticked under says what crosses, and that it can end
            self.assertTrue(strings["hub_consent_text"] and strings["hub_consent_tick"], lang)
