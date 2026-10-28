# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field staff's pages on PostgreSQL 16 (Phase 4 follow-up, decisions FU2-1 to FU2-12).

Each page in pt-PT, English, German and Traditional Chinese (Taiwan), its headers (no-store, noindex, the unchanged content security policy), that
it loads only same-origin scripts and runs no inline one, that it holds no data (the API, with its role
rules, gives the data), the pages' texts against what the scripts ask for, what the scripts may not do
(parse HTML, load from elsewhere), the static files' caching, and the per-address limit. In a real browser,
with the API behind it: ``server/tests_browser/`` (``python3 tools/docker_server.py browser``).

    python3 tools/docker_server.py test tests.test_staff_pages
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from atalaia_server import sync
from atalaia_server.ratelimit import Limits, RequestLimit
from atalaia_server.security_headers import HEADERS
from atalaia_server.web import i18n, staff_pages
from atalaia_server.web.staff_i18n import STRINGS

from .base import AppTestCase

STATIC = Path(staff_pages.__file__).resolve().parent / "static" / "staff"
FIELD = "0192f3a4-5b6c-7d8e-9f01-23456789abcd"
GAME = "0192f3a4-5b6c-7d8e-9f01-000000000001"
PAGES = {
    "home": "/staff/", "login": "/staff/login", "account": "/staff/account", "history": f"/staff/fields/{FIELD}/history",
    "game": f"/staff/fields/{FIELD}/games/{GAME}", "scenarios": f"/staff/fields/{FIELD}/scenarios",
    "scenario": f"/staff/fields/{FIELD}/scenarios/org.test.two", "presets": f"/staff/fields/{FIELD}/presets",
    "devices": f"/staff/fields/{FIELD}/devices", "remote": f"/staff/fields/{FIELD}/remote-gm",
    "atak": f"/staff/fields/{FIELD}/atak", "schedule": f"/staff/fields/{FIELD}/schedule",
    "registrations": f"/staff/fields/{FIELD}/schedule/{GAME}/registrations",
    "roster": f"/staff/fields/{FIELD}/schedule/{GAME}/roster",
    # Phase 4 follow-up FU9
    "roles": f"/staff/fields/{FIELD}/roles", "gameroles": f"/staff/fields/{FIELD}/games/{GAME}/roles",
    "synckeys": f"/staff/fields/{FIELD}/sync-keys", "branding": f"/staff/fields/{FIELD}/branding",
    "platforms": f"/staff/fields/{FIELD}/platforms", "clubs": "/staff/clubs", "club": f"/staff/clubs/{GAME}",
    "firmware": "/staff/firmware", "admin": "/staff/admin",
}


class Scripts(HTMLParser):
    """The page's <script> elements: their attributes and text."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[tuple[dict[str, str], str]] = []
        self.inline_handlers: list[str] = []
        self.ids: list[str] = []
        self._open: dict[str, str] | None = None
        self._text = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k: v or "" for k, v in attrs}
        self.inline_handlers += [k for k in values if k.startswith("on")]
        if "id" in values:
            self.ids.append(values["id"])
        if tag == "script":
            self._open, self._text = values, ""

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._text += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._open is not None:
            self.scripts.append((self._open, self._text))
            self._open = None


def parse(text: str) -> Scripts:
    parser = Scripts()
    parser.feed(text)
    return parser


class StaffPageTests(AppTestCase):
    async def test_every_page_in_every_language(self) -> None:
        csp = dict(HEADERS)["content-security-policy"]
        for name, path in PAGES.items():
            for lang, html_lang, header in (("pt", "pt-PT", "pt"), ("en", "en", "en"), ("de", "de", "de"),
                                            ("zh-tw", "zh-Hant-TW", "zh-Hant-TW")):
                with self.subTest(page=name, lang=lang):
                    r = await self.client.get(path, params={"lang": lang})
                    self.assertEqual(r.status_code, 200, r.text)
                    self.assertEqual(r.headers["content-type"], "text/html; charset=utf-8")
                    self.assertEqual(r.headers["cache-control"], "no-store")
                    self.assertEqual(r.headers["x-robots-tag"], "noindex")
                    self.assertEqual(r.headers["content-language"], header)
                    self.assertEqual(r.headers["content-security-policy"], csp)  # the policy as it was
                    self.assertIn(f'<html lang="{html_lang}">', r.text)
                    self.assertIn(f'data-lang="{lang}"', r.text)
                    for other in i18n.LANGUAGES:  # the switcher names all four
                        tag = i18n.TAGS[other]
                        self.assertIn(f'<span lang="{tag}" aria-current="true">' if other == lang
                                      else f'<a lang="{tag}" hreflang="{tag}" href="{path}?lang={other}">', r.text)
                    self.assertIn("<noscript>", r.text)
                    self.assertNotIn("$", re.sub(r'<script type="application/json".*?</script>', "", r.text,
                                                 flags=re.S))  # every placeholder filled
                    page = parse(r.text)
                    self.assertEqual(page.inline_handlers, [], "no inline event handlers")
                    self.assertEqual(len(page.ids), len(set(page.ids)), "ids are unique")
                    srcs = [a["src"] for a, _ in page.scripts if "src" in a]
                    self.assertEqual(srcs, [f"/static/staff/{name}.js"])
                    for attrs, text in page.scripts:
                        if "src" in attrs:
                            self.assertEqual((attrs.get("type"), text.strip()), ("module", ""))
                        else:  # the one inline block is data, which the policy never runs
                            self.assertEqual(attrs.get("type"), "application/json")
                            self.assertEqual(json.loads(text), STRINGS[lang])
                    if path != "/staff/":
                        self.assertIn(f'href="{path}?lang={"en" if lang == "pt" else "pt"}"', r.text)

    async def test_accept_language_and_head(self) -> None:
        r = await self.client.get("/staff/login", headers={"Accept-Language": "en-GB,en;q=0.9"})
        self.assertIn(STRINGS["en"]["login_title"], r.text)
        r = await self.client.get("/staff/login")
        self.assertIn(STRINGS["pt"]["login_title"], r.text)
        for header, lang, html_lang in (("de-DE,de;q=0.9", "de", "de"), ("zh-Hant-TW", "zh-tw", "zh-Hant-TW"),
                                        ("zh-HK, en;q=0.5", "zh-tw", "zh-Hant-TW"), ("zh-CN, en;q=0.5", "en", "en"),
                                        ("zh-Hans", "pt", "pt-PT")):
            with self.subTest(header=header):
                r = await self.client.get("/staff/login", headers={"Accept-Language": header})
                self.assertIn(f'<html lang="{html_lang}">', r.text)
                self.assertIn(f'data-lang="{lang}"', r.text)
                self.assertIn(f"<title>{STRINGS[lang]['login_title']} · {STRINGS[lang]['site']}</title>", r.text)
        head = await self.client.head("/staff/login")
        self.assertEqual((head.status_code, head.content), (200, b""))
        r = await self.client.get("/staff", params={"lang": "en"})
        self.assertEqual((r.status_code, r.headers["location"]), (308, "/staff/?lang=en"))

    async def test_links_keep_the_language_asked_for(self) -> None:
        r = await self.client.get(PAGES["game"], params={"lang": "en"})
        self.assertIn(f'href="/staff/fields/{FIELD}/history?lang=en"', r.text)
        self.assertIn('data-explicit="1"', r.text)
        r = await self.client.get(PAGES["game"])
        self.assertIn(f'href="/staff/fields/{FIELD}/history"', r.text)
        self.assertIn('data-explicit=""', r.text)

    async def test_a_path_without_a_valid_id_is_a_404(self) -> None:
        for path in ("/staff/fields/nope/history", f"/staff/fields/{FIELD}/games/nope",
                     f"/staff/fields/{FIELD}/scenarios/Not-An-Id", f"/staff/fields/{FIELD}/scenarios/x" + "a.b" * 20,
                     f"/staff/fields/{FIELD}/schedule/nope/registrations", f"/staff/fields/{FIELD}/schedule/nope/roster",
                     f"/staff/fields/{FIELD}/games/nope/roles", f"/staff/fields/nope/roles", "/staff/clubs/nope",
                     "/staff/clubs/%3Cscript%3E", f"/staff/fields/%22onmouseover%3D/branding",
                     f"/staff/fields/{FIELD}/scenarios/%3Cscript%3E.x", "/staff/fields/%22onmouseover%3D/devices"):
            with self.subTest(path=path):
                r = await self.client.get(path)
                self.assertEqual(r.status_code, 404)
                self.assertEqual(r.headers["cache-control"], "no-store")
                self.assertNotIn("<script>", r.text)
                self.assertNotIn('"onmouseover', r.text)  # escaped where the path is echoed (&quot;)
        r = await self.client.get("/staff/nothing-here")
        self.assertEqual(r.status_code, 404)

    async def test_the_pages_hold_no_data(self) -> None:
        """A page is the same for anyone: its data comes from the API, which checks the roles (FU2-2)."""
        field_id = (await self.fetch("INSERT INTO fields (name, slug) VALUES ('Campo Secreto', 'secreto') "
                                     "RETURNING id"))[0][0]
        key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", field_id,
                         sync.key_hash(key))
        r = await self.client.post("/api/v1/sync/games", headers={"Authorization": f"Bearer {key}"}, json={
            "sync_version": 1, "controller": {"id": FIELD, "version": "0.1.0"}, "game": {"game_id": 1, "game_seed": 2},
            "meta": {"name": "Operação Noturna", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"],
                     "state": "running", "created_at": 1792000000.0}})
        self.assertEqual(r.status_code, 200, r.text)
        game = r.json()["game"]
        for path in (f"/staff/fields/{field_id}/history", f"/staff/fields/{field_id}/games/{game}",
                     f"/staff/fields/{field_id}/devices", f"/staff/fields/{field_id}/remote-gm",
                     f"/staff/fields/{field_id}/atak", f"/staff/fields/{field_id}/schedule",
                     f"/staff/fields/{field_id}/schedule/{game}/registrations",
                     f"/staff/fields/{field_id}/schedule/{game}/roster", f"/staff/fields/{field_id}/roles",
                     f"/staff/fields/{field_id}/games/{game}/roles", f"/staff/fields/{field_id}/sync-keys",
                     f"/staff/fields/{field_id}/branding", f"/staff/fields/{field_id}/platforms",
                     "/staff/clubs", f"/staff/clubs/{game}", "/staff/firmware", "/staff/admin"):
            r = await self.client.get(path)
            self.assertEqual(r.status_code, 200)
            self.assertNotIn("Operação Noturna", r.text)
            self.assertNotIn("Campo Secreto", r.text)
        # The API the page calls refuses anyone without a role, as before.
        r = await self.client.get(f"/api/v1/fields/{field_id}/history")
        self.assertEqual(r.status_code, 401)

    async def test_the_texts_block_cannot_be_closed(self) -> None:
        block = staff_pages.strings_block({"x": "</script><script>alert(1)</script>&"})
        self.assertNotIn("<", block)
        self.assertNotIn(">", block)
        self.assertEqual(json.loads(block), {"x": "</script><script>alert(1)</script>&"})

    async def test_static_files(self) -> None:
        for name in staff_pages.FILES:
            with self.subTest(name=name):
                r = await self.client.get(f"/static/staff/{name}")
                self.assertEqual(r.status_code, 200)
                kind = "text/javascript" if name.endswith(".js") else "text/css"
                self.assertEqual(r.headers["content-type"], f"{kind}; charset=utf-8")
                self.assertEqual(r.headers["cache-control"], "no-cache")
                again = await self.client.get(f"/static/staff/{name}", headers={"If-None-Match": r.headers["etag"]})
                self.assertEqual(again.status_code, 304)
        for name in ("nope.js", "..%2Fstaff_pages.py", "staff.js.map", "STAFF.JS"):
            with self.subTest(name=name):
                r = await self.client.get(f"/static/staff/{name}")
                self.assertEqual(r.status_code, 404)
        r = await self.client.get("/static/field.css")
        self.assertEqual(r.status_code, 200)  # the field pages' sheet, which the staff pages build on

    async def test_the_staff_pages_count_towards_the_per_address_limit(self) -> None:
        self.app.state.limits = Limits()
        self.app.state.limits.requests = RequestLimit(3, 60)
        for _ in range(3):
            self.assertEqual((await self.client.get("/staff/login")).status_code, 200)
        r = await self.client.get("/staff/login")
        self.assertEqual(r.status_code, 429)
        self.assertIn("retry-after", r.headers)


class StaffScriptTests(AppTestCase):
    """What the scripts may do, read from their source."""

    def sources(self) -> dict[str, str]:
        return {p.name: p.read_text(encoding="utf-8") for p in sorted(STATIC.glob("*.js"))}

    async def test_every_page_has_its_script_and_every_file_its_licence(self) -> None:
        names = set(staff_pages.FILES)
        for page in staff_pages.page_names() + ["notfound"]:
            self.assertIn(f"{page}.js", names)
        for path in sorted(STATIC.iterdir()):
            head = path.read_text(encoding="utf-8").splitlines()[:2]
            tag = "SPDX-" + "License-Identifier: AGPL-3.0-or-later"  # split, so REUSE does not read it as this file's
            self.assertTrue(any(tag in line for line in head), path.name)

    async def test_no_html_parsing_and_nothing_from_elsewhere(self) -> None:
        banned = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\(|new Function|"
                            r"setTimeout\(\s*['\"`]|https?://(?!www\.w3\.org/2000/svg)")
        for name, text in self.sources().items():
            with self.subTest(name=name):
                self.assertIsNone(banned.search(text), banned.search(text))
                for target in re.findall(r"from '([^']+)'", text):
                    self.assertTrue(target.startswith("./") and (STATIC / target[2:]).is_file(), target)

    async def test_every_text_a_script_asks_for_exists_in_every_language(self) -> None:
        self.assertEqual(tuple(STRINGS), i18n.LANGUAGES)
        for lang, strings in STRINGS.items():
            self.assertEqual(set(strings), set(STRINGS["en"]), lang)
        asked: set[str] = set()
        for text in self.sources().values():
            asked |= set(re.findall(r"\bt\('([a-z0-9_]+)'", text))
        missing = sorted(k for k in asked if k not in STRINGS["en"])
        self.assertEqual(missing, [])
        for lang, strings in STRINGS.items():  # the same {names} in every language
            for key, value in strings.items():
                self.assertEqual(set(re.findall(r"\{(\w+)\}", value)),
                                 set(re.findall(r"\{(\w+)\}", STRINGS["en"][key])), (lang, key))

    async def test_the_texts_a_script_builds_a_key_from_exist(self) -> None:
        """``t(`sched_status_${status}`)`: the keys made from a value, for every value the API can give."""
        built = {"sched_status_": ("draft", "published", "in_progress", "completed", "cancelled"),
                 "reg_window_": ("none", "not_yet", "open", "closed"),
                 "reg_status_": ("registered", "checked_in", "no_show", "cancelled"),
                 "fed_": ("off", "optional", "required"),
                 "oidc_err_": ("state_invalid", "denied", "consent_required", "too_many_attempts",
                               "id_token_invalid", "token_exchange_failed", "provider_unreachable", "try_again",
                               "other"),
                 "replica_state_": ("pending", "passed", "refused", "withdrawn"),
                 "io_res_": ("created", "updated", "unchanged", "skipped", "refused"),
                 "io_warn_": ("same_name", "no_external_ref", "federation_number_dropped"),
                 "image_": ("logo", "wallpaper"), "club_image_": ("logo", "crest"), "club_make_": ("admin", "member"),
                 "club_role_": ("admin", "member"),                  "report_reason_": ("rights", "offensive", "impersonation", "other"),
                 "report_status_": ("open", "dismissed", "actioned", "all"),
                 "e_": ("cancelled", "external_ref_invalid", "external_ref_twice", "row_length", "row_not_object",
                        "display_name_invalid", "team_preference_invalid", "federation_number_invalid",
                        "federation_number_required", "replicas_invalid", "replicas_not_asked",
                        "too_many_replicas", "replica_type_invalid", "replica_class_invalid", "make_model_invalid",
                        "game_full")}
        text = " ".join(self.sources().values())
        for prefix, values in built.items():
            self.assertIn(f"`{prefix}$", text)
            for lang, strings in STRINGS.items():
                for value in values:
                    self.assertIn(prefix + value, strings, (lang, prefix + value))

    async def test_every_answer_code_of_the_fu8_apis_has_words(self) -> None:
        """The codes the APIs the new pages call can answer (read from their source) have a text in every language."""
        api = Path(staff_pages.__file__).resolve().parents[1] / "api"
        codes: set[str] = set()
        for module in ("fields", "branding", "clubs", "integrations", "firmware", "games"):
            text = (api / f"{module}.py").read_text(encoding="utf-8")
            codes |= set(re.findall(r'HTTPException\(\d+, "([a-z_]+)"', text))
        branding = (api.parent / "services" / "branding.py").read_text(encoding="utf-8")
        codes |= set(re.findall(r'BrandingError\("([a-z_]+)"', branding))
        codes |= {f"{name}_invalid" for name in ("field_name", "accent", "name", "short_name", "colour", "slug",
                                                  "reason", "description")}
        # Answers of calls these pages do not make (a field's settings, a scheduled game's pushes to a platform).
        codes -= {"already_cancelled", "capability_missing", "config_unreadable", "game_not_published",
                  "integration_disabled", "limit_template_invalid", "max_replicas_invalid", "not_published_there"}
        self.assertGreater(len(codes), 30)
        for lang, strings in STRINGS.items():
            missing = sorted(c for c in codes if f"e_{c}" not in strings)
            self.assertEqual(missing, [], lang)

    async def test_every_api_path_a_new_script_names_exists(self) -> None:
        """A page is its API (FU2-2): the paths the FU9 scripts call are routes of the application, with that method."""
        scripts = ("roles", "rolestable", "gameroles", "synckeys", "branding", "clubs", "club", "platforms", "firmware",
                   "admin", "imageblock", "remote")
        field = "00000000-0000-0000-0000-000000000000"
        found: set[tuple[str, str]] = set()
        for name in scripts:
            text = (STATIC / f"{name}.js").read_text(encoding="utf-8")
            for method, path in re.findall(r"(?:api|act)\('(GET|POST|PUT|PATCH|DELETE)',\s*[`']([^`']+)[`']", text):
                found.add((method, path))
            for method, path in re.findall(r"api\('(GET|POST|PUT|PATCH|DELETE)',\s*fieldApi\([`']([^`']+)[`']\)", text):
                found.add((method, f"/api/v1/fields/{field}{path}"))
            for path in re.findall(r"stream\(fieldApi\('([^']+)'\)", text):
                found.add(("GET", f"/api/v1/fields/{field}{path}"))
        self.assertGreater(len(found), 25)
        schema = self.app.openapi()["paths"]  # the API's routes (the staff pages are not in it)
        bases = {"${base}": (f"/api/v1/fields/{field}/roles", f"/api/v1/games/{field}/roles"),
                 "${CLUB}": (f"/api/v1/clubs/{field}",)}  # the variables the scripts build their paths from
        for method, path in sorted(found):
            if path.startswith("${put}"):  # imageblock.js's slot: its callers (branding, club) pass the real path
                continue
            starts = next(((prefix, options) for prefix, options in bases.items() if path.startswith(prefix)), None)
            options = [path.replace(starts[0], o, 1) for o in starts[1]] if starts else [path]
            matched = []
            for option in options:
                concrete = re.sub(r"\$\{[^}]*\}", "x1", option).split("?")[0]
                matched += [p for p, ops in schema.items() if method.lower() in ops
                            and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", p), concrete)]
            self.assertTrue(matched, f"{method} {path}")

    async def test_the_roster_has_a_print_style_sheet(self) -> None:
        css = (STATIC / "staff.css").read_text(encoding="utf-8")
        self.assertIn("@media print", css)
        printed = css[css.index("@media print"):]
        hiding = printed.split("display: none", 1)[0]
        for hidden in ("header.staff-top", "footer", ".noprint", "button"):
            self.assertIn(hidden, hiding)
        roster = (staff_pages.TEMPLATE_DIR / "roster.html").read_text(encoding="utf-8")
        self.assertIn('id="print"', roster)  # the button, which the print style sheet hides

    async def test_state_changing_calls_carry_the_bearer_token(self) -> None:
        """No request is authorised by a cookie: the scripts call the API through api() (Authorization:
        Bearer); the only other fetches are the login steps and the refresh, which wants its own header."""
        for name, text in self.sources().items():
            with self.subTest(name=name):
                for call in re.findall(r"fetch\(\s*'([^']+)'|fetch\((\w+)", text):
                    target = call[0] or call[1]
                    self.assertIn(target, ("/api/v1/auth/refresh", "path"), name)
        staff = self.sources()["staff.js"]
        self.assertIn("'X-Atalaia-Refresh': '1'", staff)
        self.assertIn("Authorization: `Bearer ${s.token}`", staff)

    async def test_german_and_chinese_follow_the_glossary(self) -> None:
        de = " ".join(STRINGS["de"].values())
        for word in ("Ihnen", "Ihre ", "Spieler ", "Spieler:in", "Spieler*in", "SpielerInnen", "Schiedsrichter"):
            self.assertNotIn(word, de)  # "du"; neutral forms; "Marshal" as the glossary has it
        for key, zh in STRINGS["zh-tw"].items():
            for letter in ("您", "妳", "他們", "她", "这", "个", "设", "场", "报", "们", "录", "证", "码"):
                self.assertNotIn(letter, zh, key)  # 你 only, no gendered pronoun, no Simplified letter
            self.assertNotRegex(zh, r"[一-鿿][A-Za-z0-9]|[A-Za-z0-9][一-鿿]", key)  # a space
            self.assertNotRegex(zh, r"[一-鿿][,.:;!?()]", key)  # full-width punctuation after Han

    async def test_portuguese_is_inclusive(self) -> None:
        text = " ".join(STRINGS["pt"].values()).lower()
        # "Nome de utilizador" is the app's label for the account name (as the app says it), a field, not a
        # person: allowed, while "utilizador" for a person stays out.
        text = text.replace("nome de utilizador", "nome da conta")
        # "GM remoto" is the maintainer's term (decision FU2-11): the role, not a person.
        for word in ("utilizador", "jogadores", "administrador ", " o gm ", " um gm ", "marshall",
                     "esquadra", "time "):
            self.assertNotIn(word, text)
