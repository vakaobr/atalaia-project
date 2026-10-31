# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The staff account page (decisions ACC-1 to ACC-8): ``/staff/account``, the logged-in account's own login methods.

The page is its API (FU2-1): these tests read what it is made of. That it is in the list of pages, linked from
every page's header, in every language, that every API call its script makes is a route of the application with
that method, and that every refusal the API can give to the calls it makes has its words in every language. What it
does in a browser: ``tests_browser/test_account_browser.py``.

    python3 tools/docker_server.py test tests.test_account_page
"""

from __future__ import annotations

import re
from pathlib import Path

from atalaia_server.ratelimit import RequestLimit
from atalaia_server.web import i18n, staff_pages
from atalaia_server.web.staff_i18n import STRINGS

from .base import AppTestCase
from .test_staff_pages import FIELD, PAGES

SERVER = Path(staff_pages.__file__).resolve().parents[2]
SCRIPT = (staff_pages.STATIC / "account.js").read_text(encoding="utf-8")
CALL = re.compile(r"""api\(\s*'(GET|POST|PATCH|DELETE|PUT)',\s*[`']([^`']+)[`']""")


def called() -> list[tuple[str, str]]:
    """The (method, path) of every ``api(...)`` call in the script, a ``${...}`` made a path value."""
    return [(m, re.sub(r"\$\{[^}]*\}", "x", p)) for m, p in CALL.findall(SCRIPT)]


class AccountPageTests(AppTestCase):
    async def test_the_page_is_listed_and_linked_from_every_page(self) -> None:
        self.assertIn("account", staff_pages.page_names())
        self.assertIn("account.js", staff_pages.FILES)
        self.app.state.limits.requests = RequestLimit(100000, 60)  # every page in every language is many requests
        for name, path in {**PAGES, "account": "/staff/account"}.items():
            for lang in i18n.LANGUAGES:
                with self.subTest(page=name, lang=lang):
                    r = await self.client.get(path, params={"lang": lang})
                    word = STRINGS[lang]["nav_account"]
                    self.assertIn(f'id="account-link" href="/staff/account?lang={lang}">{word}</a>', r.text)
        r = await self.client.get("/staff/fields/nope/history")  # the 404 page has the header too
        self.assertIn('href="/staff/account"', r.text)
        r = await self.client.get("/staff/account", params={"lang": "de"})
        self.assertIn(f"<h1>{STRINGS['de']['acct_title']}</h1>", r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.headers["x-robots-tag"], "noindex")
        self.assertNotIn(FIELD, r.text)

    async def test_every_api_path_the_script_calls_exists(self) -> None:
        calls = called()
        self.assertGreaterEqual(len(calls), 16)
        spec = (await self.client.get("/api/v1/openapi.json")).json()["paths"]
        for method, path in calls:
            with self.subTest(call=f"{method} {path}"):
                found = [p for p, ops in spec.items() if method.lower() in ops
                         and re.fullmatch(re.sub(r"\\\{[^}]*\\\}", "[^/]+", re.escape(p)), path)]
                self.assertTrue(found, f"{method} {path} is no route of the application")
        # Every ending of the account's own API the page is for, called at least once.
        have = {f"{m} {p}" for m, p in calls}
        for wanted in ("GET /api/v1/me/login-methods", "GET /api/v1/auth/methods", "POST /api/v1/auth/oidc/x/start",
                       "DELETE /api/v1/me/identities/x", "POST /api/v1/me/passkeys/options", "POST /api/v1/me/passkeys",
                       "PATCH /api/v1/me/passkeys/x", "DELETE /api/v1/me/passkeys/x", "POST /api/v1/me/password",
                       "DELETE /api/v1/me/password", "POST /api/v1/auth/totp/enrol", "POST /api/v1/auth/totp/confirm",
                       "POST /api/v1/auth/totp/disable", "POST /api/v1/auth/stepup/totp",
                       "POST /api/v1/auth/stepup/passkey/options", "POST /api/v1/auth/stepup/passkey",
                       "PATCH /api/v1/me", "POST /api/v1/me/merge/preview", "POST /api/v1/me/merge"):
            self.assertIn(wanted, have)

    async def test_the_script_sends_what_the_api_reads(self) -> None:
        """The bodies' field names are the API's: a typo would be a 422 only a browser run finds."""
        self.assertRegex(SCRIPT, r"purpose, return_to: link\(HOME\)")
        self.assertIn("new_password: next", SCRIPT)
        self.assertIn("challenge_token: first.challenge_token", SCRIPT)
        self.assertIn("{ password: currentPassword() }", SCRIPT)
        self.assertIn("'/api/v1/auth/totp/disable', { password: currentPassword(), code }", SCRIPT)
        # The return address is one the server accepts after a login (api/login_methods.RETURN_TO).
        from atalaia_server.api.login_methods import RETURN_TO, safe_return_to
        for lang_part in ("", "?lang=de", "?lang=zh-tw"):
            self.assertEqual(safe_return_to("/staff/account" + lang_part), "/staff/account" + lang_part)
        self.assertTrue(RETURN_TO.fullmatch("/staff/account?lang=pt"))

    async def test_every_refusal_has_words_in_every_language(self) -> None:
        """The codes the account's endpoints give (read from their source), each with a text, and the codes the
        provider's return can carry."""
        codes = set()
        for name in ("login_methods.py", "account_merge.py"):
            source = (SERVER / "atalaia_server" / "api" / name).read_text(encoding="utf-8")
            codes |= set(re.findall(r'HTTPException\(\d{3}, "([a-z_]+)"', source))
        codes |= {"username_invalid", "username_reserved", "username_or_email_taken", "merge_staff_account",
                  "merge_provider_conflict", "merge_too_many_passkeys"}
        codes |= {"confirmation_required", "invalid_password", "invalid_code", "password_login_disabled",
                  "totp_already_enabled", "totp_not_pending", "totp_not_enabled", "totp_required_by_role",
                  "password_too_short", "password_too_long", "password_is_username", "password_breached"}
        # Nothing the page shows as its own words: a session that ended goes to the login page, and a ticket is the
        # login page's.
        codes -= {"not_authenticated", "invalid_ticket"}
        self.assertIn("last_login_method", codes)
        self.assertIn("second_factor_required_by_role", codes)
        for lang, strings in STRINGS.items():
            for code in sorted(codes):
                with self.subTest(lang=lang, code=code):
                    self.assertIn(f"acct_e_{code}", strings)
            for code in ("already_linked", "identity_taken", "provider_already_linked", "identity_mismatch",
                         "denied", "state_invalid", "other", "name_unusable", "notice_required", "age_confirmation_required"):
                self.assertIn(f"oidc_err_{code}", strings, (lang, code))

    async def test_every_text_of_the_page_is_in_the_four_languages(self) -> None:
        template = (staff_pages.TEMPLATE_DIR / "account.html").read_text(encoding="utf-8")
        used = set(re.findall(r"\$([a-z][a-z0-9_]*)", template)) - {"hub_share_href"}  # an address, not a text
        used |= set(re.findall(r"\bt\('([a-z0-9_]+)'", SCRIPT))
        self.assertGreater(len(used), 40)
        for lang, strings in STRINGS.items():
            self.assertEqual([k for k in sorted(used) if k not in strings], [], lang)
        for key in sorted(k for k in STRINGS["en"] if k.startswith(("acct_", "nav_account"))):
            texts = {lang: STRINGS[lang][key] for lang in STRINGS}
            self.assertGreater(len(set(texts.values())), 1, key)  # not one text copied into every language

    async def test_the_page_runs_no_rule_of_its_own(self) -> None:
        """What may be done is the server's word (the refusals): the script names no role and no count."""
        for word in ("last_login_method", "second_factor_required_by_role", "totp_required_by_role", "admin", "gm",
                     "marshal", "server_admin", "privileged"):
            self.assertIsNone(re.search(rf"\b{word}\b", SCRIPT), word)
