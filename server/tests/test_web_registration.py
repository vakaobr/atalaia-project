# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registering on the field's public pages in a browser (decisions WREG-*; the browser side is in
``tests_browser/test_register_browser.py``).

What the server gives the page and promises around it: the page itself (only for a public field's public game, no
data, ``no-store``, ``noindex``, no inline script, the four languages, the texts as a JSON block nothing can close),
its three static files, the register page's link to it, a social login that comes back to it and makes the account
under the same rules as the app's, the registration that follows with the app's records, the per-account limit on
registrations and new tickets, and that no cookie alone authorises a change (CSRF).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from atalaia_server import privacy_notice
from atalaia_server.api.login_methods import DEFAULT_RETURN, safe_return_to
from atalaia_server.models import ScheduledGame
from atalaia_server.security_headers import HEADERS
from atalaia_server.web import player_pages

from .base import AppTestCase
from .test_login_methods import LoginTestCase, bearer

UTC = timezone.utc
CONSOLE_QR = Path(__file__).resolve().parents[2] / "controller" / "console" / "src" / "lib" / "qrcode.module.js"


def hour(days: float, hours: float = 0) -> datetime:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return now + timedelta(days=days, hours=hours)


class WebRegisterMixin:
    """A public field with an open game, as the field pages' tests make them."""

    app: Any
    fetch: Any

    async def setup_field(self, public: bool = True) -> None:
        self.field_id = (await self.fetch(
            "INSERT INTO fields (name, slug, public_page, federation_label) VALUES ('Campo Tejo', 'campo-tejo', $1, 'FPA') "
            "RETURNING id", public))[0][0]

    async def game(self, title: str = "Domingo no bosque", status: str = "published",
                   field_id: Optional[uuid.UUID] = None, **values: Any) -> ScheduledGame:
        start = values.pop("start", hour(10))
        values.setdefault("registration_opens_at", hour(-1))
        values.setdefault("registration_closes_at", hour(5))
        async with self.app.state.sessionmaker() as db:
            game = ScheduledGame(field_id=field_id or self.field_id, title=title, starts_at=start,
                                 ends_at=start + timedelta(hours=4), status=status, teams=["red", "blue"], **values)
            db.add(game)
            await db.commit()
            await db.refresh(game)
            return game

    def path(self, game: ScheduledGame, slug: str = "campo-tejo") -> str:
        return f"/f/{slug}/games/{game.id}/register/web"


class PageTests(WebRegisterMixin, AppTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.setup_field()

    async def test_the_page_holds_no_data_and_runs_no_inline_script(self) -> None:
        game = await self.game("<script>alert(1)</script> Domingo")
        r = await self.client.get(self.path(game))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["content-type"], "text/html; charset=utf-8")
        self.assertEqual(r.headers["cache-control"], "no-store")
        self.assertEqual(r.headers["x-robots-tag"], "noindex")
        for name, value in HEADERS:  # the same content security policy as every page: script-src 'self'
            self.assertEqual(r.headers[name], value)
        page = r.text
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; Domingo", page)
        # Every script is a same-origin module or a data block: nothing inline runs.
        scripts = re.findall(r"<script([^>]*)>(.*?)</script>", page, re.S)
        self.assertEqual(len(scripts), 2)
        for attrs, body in scripts:
            if 'src="' in attrs:
                self.assertIn('type="module" src="/static/player/register.js"', attrs)
                self.assertEqual(body, "")
            else:
                self.assertIn('type="application/json" id="staff-strings"', attrs)
                strings = json.loads(body)
                self.assertNotIn("<", body)
        self.assertEqual(strings["w_register"], "Fazer a inscrição")
        self.assertIn("login_passkey", strings)  # the staff login's texts it shares
        self.assertIn("e_membership_missing", strings)
        self.assertIn("notice_title", strings)  # the "notice shown again" panel's
        # What the script needs, and nothing about anyone.
        self.assertIn(f'data-game="{game.id}"', page)
        self.assertIn(f'data-field="{self.field_id}"', page)
        self.assertIn('data-slug="campo-tejo"', page)
        self.assertIn('href="atalaia://register?site=https%3A%2F%2Fserver.test&amp;field=campo-tejo&amp;game='
                      f'{game.id}"', page)
        self.assertIn('<input type="checkbox" id="notice-seen"', page)
        self.assertIn('id="age-confirmed"', page)
        self.assertNotIn('id="notice-link"', page)  # no notice published: nothing to open
        self.assertIn('data-notice=""', page)
        r = await self.client.head(self.path(game))
        self.assertEqual((r.status_code, r.content), (200, b""))

    async def test_the_four_languages(self) -> None:
        game = await self.game()
        cases = {"pt": ("pt-PT", "Inscrição online"), "en": ("en", "Register online"),
                 "de": ("de", "Online anmelden"), "zh-tw": ("zh-Hant-TW", "線上報名")}
        for lang, (tag, title) in cases.items():
            with self.subTest(lang):
                r = await self.client.get(self.path(game), params={"lang": lang})
                self.assertIn(f'<html lang="{tag}">', r.text)
                self.assertIn(f"<h1>{title}", r.text)
                self.assertIn(f'data-lang="{lang}"', r.text)
                self.assertIn('data-explicit="1"', r.text)
        r = await self.client.get(self.path(game), headers={"Accept-Language": "de-AT,de;q=0.9"})
        self.assertIn('<html lang="de">', r.text)
        self.assertIn('data-explicit=""', r.text)
        self.assertEqual(set(player_pages.strings_for("en")) - set(player_pages.strings_for("de")), set())

    async def test_the_notice_link_when_one_is_published(self) -> None:
        game = await self.game()
        with tempfile.TemporaryDirectory() as folder:
            version = self.app.state.settings.privacy_notice_version
            (Path(folder) / privacy_notice.filename("pt", version)).write_text("# Aviso\n", encoding="utf-8")
            self.app.state.settings = dataclasses.replace(self.app.state.settings, privacy_notice_dir=folder)
            page = (await self.client.get(self.path(game))).text
        self.assertIn('<a id="notice-link" href="/privacy" target="_blank" rel="noopener">Ler o aviso de privacidade</a>',
                      page)
        self.assertIn('data-notice="1"', page)

    async def test_only_a_public_fields_public_game(self) -> None:
        game = await self.game()
        draft = await self.game("Rascunho", status="draft")
        hidden = (await self.fetch("INSERT INTO fields (name, slug, public_page) VALUES ('Oculto', 'oculto', false) "
                                   "RETURNING id"))[0][0]
        other = (await self.fetch("INSERT INTO fields (name, slug, public_page) VALUES ('Arena', 'arena', true) "
                                  "RETURNING id"))[0][0]
        hidden_game = await self.game("Oculto", field_id=hidden)
        arena_game = await self.game("Arena", field_id=other)
        for path in (self.path(draft), self.path(hidden_game, "oculto"), self.path(arena_game),  # another field's game
                     "/f/campo-tejo/games/not-a-uuid/register/web", f"/f/nope/games/{game.id}/register/web"):
            with self.subTest(path):
                r = await self.client.get(path)
                self.assertEqual(r.status_code, 404, path)
                self.assertEqual(r.headers["cache-control"], "no-store")
        # A game whose registration is closed still has the page: a registered player comes back to it for the
        # ticket, and the API says what is open.
        closed = await self.game("Fechado", registration_opens_at=hour(-5), registration_closes_at=hour(-1))
        self.assertEqual((await self.client.get(self.path(closed))).status_code, 200)

    async def test_the_static_files(self) -> None:
        for name, kind in (("register.js", "text/javascript"), ("player.css", "text/css"),
                           ("qrcode.module.js", "text/javascript")):
            with self.subTest(name):
                r = await self.client.get(f"/static/player/{name}")
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.headers["content-type"].startswith(kind))
                self.assertEqual(r.headers["cache-control"], "no-cache")
                again = await self.client.get(f"/static/player/{name}", headers={"If-None-Match": r.headers["etag"]})
                self.assertEqual(again.status_code, 304)
        for name in ("README.md", "../player_pages.py", "nope.js"):
            self.assertEqual((await self.client.get(f"/static/player/{name}")).status_code, 404, name)
        script = (await self.client.get("/static/player/register.js")).text
        self.assertNotIn("innerHTML", script)  # every value as text (FU2-5)
        self.assertNotIn("localStorage", script)  # the ticket is never kept by the page

    def test_the_qr_generator_is_the_consoles_copy(self) -> None:
        mine = hashlib.sha256(player_pages.FILES["qrcode.module.js"]).hexdigest()
        self.assertEqual(mine, "ea91d7118a5395289170da848b7c6758b996163bfbccf312591ab65a4911b7c0")
        if CONSOLE_QR.is_file():  # not in the test image, which holds only the server
            self.assertEqual(hashlib.sha256(CONSOLE_QR.read_bytes()).hexdigest(), mine)

    async def test_the_register_page_leads_here(self) -> None:
        game = await self.game()
        page = (await self.client.get(f"/f/campo-tejo/games/{game.id}/register")).text
        self.assertIn(f'<a class="button" href="{self.path(game)}">Fazer a inscrição aqui</a>', page)
        self.assertIn('href="atalaia://register?', page)  # the app's way stays
        en = (await self.client.get(f"/f/campo-tejo/games/{game.id}/register", params={"lang": "en"})).text
        self.assertIn(f'href="{self.path(game)}?lang=en">Register here</a>', en)
        closed = await self.game("Fechado", registration_opens_at=hour(-5), registration_closes_at=hour(-1))
        page = (await self.client.get(f"/f/campo-tejo/games/{closed.id}/register")).text
        self.assertNotIn("/register/web", page)


class ReturnToTests(AppTestCase):
    def test_a_social_login_may_come_back_to_a_web_registration_page(self) -> None:
        game = uuid.uuid4()
        ok = [f"/f/campo-tejo/games/{game}/register/web", f"/f/a/games/{game}/register/web?lang=zh-tw",
              f"/f/campo-tejo/games/{game}/register/web?lang=en"]
        for path in ok:
            self.assertEqual(safe_return_to(path), path)
        bad = [f"/f/campo-tejo/games/{game}/register", f"/f/campo-tejo/games/{game}/register/web?next=/x",
               f"/f/campo-tejo/games/{game}/register/web?lang=fr", f"/f/Campo/games/{game}/register/web",
               f"/f/campo-tejo/games/{game}/register/web#x", f"https://evil.test/f/c/games/{game}/register/web",
               f"//evil.test/f/c/games/{game}/register/web", f"/f/campo-tejo/games/{game}/register/web/../../x",
               "/f/campo-tejo/", f"/f/campo-tejo/games/{str(game).upper()}/register/web"]
        for path in bad:
            self.assertEqual(safe_return_to(path), DEFAULT_RETURN, path)


class WebSignupTests(WebRegisterMixin, LoginTestCase):
    """A social login begun on the page, back to the page, then the registration: the app's rules and records."""

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.setup_field()

    async def test_a_new_account_registers_from_the_page(self) -> None:
        game = await self.game(federation="required")
        back = self.path(game) + "?lang=en"
        params, r = await self.begin("google", return_to=back)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("__Secure-atalaia_oidc", r.headers["set-cookie"])  # the login-CSRF binding (LG-*)
        path, query, fragment = self.landed(await self.callback("google", params, "g-web-1"))
        self.assertEqual((path, query.get("lang"), query.get("oidc_error")), (self.path(game), "en", None))
        self.assertTrue(fragment.startswith("oidc="))
        r = await self.client.post("/api/v1/auth/oidc/complete", json={"ticket": fragment[5:]})
        self.assertEqual(r.status_code, 200, r.text)
        session = r.json()
        self.assertTrue(session["new_account"])
        user_id = (await self.user_by("g-web-1"))["id"]
        notices = await self.fetch("SELECT kind, age_confirmed FROM notice_records WHERE user_id = $1", user_id)
        self.assertEqual([(n["kind"], n["age_confirmed"]) for n in notices], [("signup", True)])
        # The page's next calls: what registering needs, then the registration, as the app makes them.
        r = await self.client.get("/api/v1/fields-by-slug/campo-tejo", headers=bearer(session))
        self.assertEqual(r.status_code, 200)
        self.assertIn(str(game.id), [g["id"] for g in r.json()["games"]])
        url = f"/api/v1/fields/{self.field_id}/scheduled-games/{game.id}/registrations"
        r = await self.client.post(url, headers=bearer(session), json={"display_name": "Raposa", "team_preference": "red"})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "federation_number_required"))  # the same checks
        r = await self.client.post(url, headers=bearer(session), json={
            "display_name": "Raposa", "team_preference": "red", "federation_number": "FPA-123"})
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertTrue(body["ticket_text"].startswith("atalaia:ticket:"))
        self.assertEqual((body["source"], body["display_name"], body["status"]), ("site", "Raposa", "registered"))
        rows = await self.fetch("SELECT action FROM audit_log WHERE user_id = $1 ORDER BY id", user_id)
        self.assertIn("registration_create", [row["action"] for row in rows])

    async def test_the_page_cannot_skip_the_notice_or_the_age(self) -> None:
        game = await self.game()
        for seen, age, error in ((True, False, "age_confirmation_required"), (False, True, "notice_required")):
            with self.subTest(error):
                params, r = await self.begin("google", return_to=self.path(game), notice_seen=seen, age_confirmed=age)
                path, query, fragment = self.landed(await self.callback("google", params, f"g-{error}"))
                self.assertEqual((path, query.get("oidc_error"), fragment), (self.path(game), error, ""))
        self.assertEqual(await self.fetch("SELECT id FROM users"), [])


class CsrfAndLimitTests(WebRegisterMixin, AppTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.setup_field()

    async def test_no_cookie_alone_authorises_a_registration(self) -> None:
        game = await self.game()
        _, name, _ = await self.make_user()
        await self.login(name)  # the client now holds the refresh cookie, as the browser would
        self.assertTrue(any(c.name == "__Secure-atalaia_refresh" for c in self.client.cookies.jar))
        url = f"/api/v1/fields/{self.field_id}/scheduled-games/{game.id}/registrations"
        # A cross-site form can send only cookies: refused, and nothing is made.
        r = await self.client.post(url, data={"display_name": "x"},
                                   headers={"Origin": "https://evil.test", "Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(r.status_code, 401)
        r = await self.client.post(url, json={"display_name": "x"})
        self.assertEqual(r.status_code, 401)
        self.assertEqual(await self.fetch("SELECT id FROM game_registrations"), [])
        # The refresh cookie is good only with the header a cross-site form cannot send.
        self.assertNotEqual((await self.client.post("/api/v1/auth/refresh")).status_code, 200)

    async def test_registrations_and_new_tickets_are_limited_per_account(self) -> None:
        games = [await self.game(f"Jogo {i}") for i in range(11)]
        _, name, _ = await self.make_user()
        headers = await self.auth(name)
        _, other, _ = await self.make_user()
        other_headers = await self.auth(other)
        regs = []
        for g in games[:10]:
            r = await self.client.post(f"/api/v1/fields/{self.field_id}/scheduled-games/{g.id}/registrations",
                                       headers=headers, json={})
            self.assertEqual(r.status_code, 201, r.text)
            regs.append(r.json()["id"])
        for reg in regs:  # ten new tickets: twenty in the hour
            r = await self.client.post(f"/api/v1/me/registrations/{reg}/ticket", headers=headers)
            self.assertEqual(r.status_code, 200, r.text)
        r = await self.client.post(f"/api/v1/fields/{self.field_id}/scheduled-games/{games[10].id}/registrations",
                                   headers=headers, json={})
        self.assertEqual((r.status_code, r.json()["detail"]), (429, "too_many_requests"))
        self.assertGreater(int(r.headers["retry-after"]), 0)
        r = await self.client.post(f"/api/v1/me/registrations/{regs[0]}/ticket", headers=headers)
        self.assertEqual(r.status_code, 429)
        # Another account (the same address: players at a field share one) is not affected.
        r = await self.client.post(f"/api/v1/fields/{self.field_id}/scheduled-games/{games[10].id}/registrations",
                                   headers=other_headers, json={})
        self.assertEqual(r.status_code, 201, r.text)

