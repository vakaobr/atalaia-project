# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registering for a game on the field's pages in a real browser (decisions WREG-*; headless Chromium, Playwright).

    python3 tools/docker_server.py browser tests_browser.test_register_browser

The staff login's browser setup (``test_login_browser``: the real application under uvicorn over HTTPS next to its
own PostgreSQL database, Google configured with a fake provider in its place), with the field's public page on:

- a new player at a phone's width: Google with neither box is refused at the boxes, then with both makes the account
  (the notice and the age recorded); the form (name, team, a replica), the ticket as a QR code and as text, the way
  into the app; back on the page the registration is shown, changed and cancelled;
- the membership rule checked in the page and by the server, a password account with its TOTP code;
- a passkey added after registering, then used to log in again;
- a closed game, the four languages, labels on every control, no sideways scrolling, and no script error or content
  security policy violation on any page (``BrowserCase``).
"""

from __future__ import annotations

import datetime
import json
from typing import Any

from playwright.async_api import Page, expect

from tests.base import PASSWORD
from tests_browser.test_login_browser import LoginBrowserCase
from tests_browser.test_staff_browser import PHONE

UTC = datetime.timezone.utc


def hour(days: float, hours: float = 0) -> datetime.datetime:
    now = datetime.datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    return now + datetime.timedelta(days=days, hours=hours)


class RegisterBrowserCase(LoginBrowserCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        await self.fetch("UPDATE fields SET public_page = true, federation_label = 'FPA' WHERE id = $1", self.field_id)

    async def open_game(self, title: str = "Domingo no bosque", **values: Any) -> str:
        start = values.pop("start", hour(10))
        row = await self.fetch(
            "INSERT INTO scheduled_games (field_id, title, starts_at, ends_at, status, teams, registration_opens_at, "
            "registration_closes_at, predeclare_replicas, federation) "
            "VALUES ($1, $2, $3, $4, 'published', $5, $6, $7, $8, $9) RETURNING id",
            self.field_id, title, start, start + datetime.timedelta(hours=4), json.dumps(["red", "blue"]),
            values.get("opens", hour(-1)), values.get("closes", hour(5)), values.get("replicas", True),
            values.get("federation", "off"))
        return str(row[0][0])

    def page_path(self, game: str, lang: str = "en") -> str:
        return f"/f/campo-norte/games/{game}/register/web" + (f"?lang={lang}" if lang else "")

    async def checks(self, page: Page) -> None:
        """No sideways scrolling, and a name for every control."""
        overflow = await page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
        self.assertLessEqual(overflow, 0, "the page scrolls sideways")
        unnamed = await page.evaluate("""() => [...document.querySelectorAll('input, select, textarea')]
            .filter((n) => n.offsetParent !== null)
            .filter((n) => !(n.labels && n.labels.length) && !n.getAttribute('aria-label'))
            .map((n) => n.id || n.outerHTML)""")
        self.assertEqual(unnamed, [])

    async def google_signup(self, page: Page, game: str, subject: str = "g-player") -> None:
        self.subject = subject
        await self.provider(page)
        await page.goto(self.base + self.page_path(game))
        await page.check("#notice-seen")
        await page.check("#age-confirmed")
        await page.click("button.provider[data-provider=google]")
        await expect(page.locator("#reg-form")).to_be_visible()


class NewPlayerTests(RegisterBrowserCase):
    async def test_a_new_player_registers_at_a_phones_width(self) -> None:
        game = await self.open_game()
        page = await self.new_page(lang="en-GB", viewport=PHONE)
        await self.provider(page)
        await page.goto(self.base + self.page_path(game))
        await expect(page.locator("h1")).to_have_text("Register online: Domingo no bosque")
        await expect(page.locator("#login-section")).to_be_visible()
        await expect(page.locator("#reg-form")).to_be_hidden()
        await expect(page.locator("#no-notice")).to_be_visible()  # no notice published on this test server
        await self.checks(page)
        # Neither box: the refusal is at the boxes, the age first, as on the server; no account is made.
        await page.click("button.provider[data-provider=google]")
        error = page.locator("#signup-error")
        await expect(error).to_contain_text("You must be 16 or older")
        await expect(page.locator("#age-confirmed")).to_be_focused()
        self.assertNotIn("oidc", page.url)  # the address is cleaned
        self.assertTrue(page.url.endswith(self.page_path(game)))
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 0)
        await page.check("#notice-seen")
        await page.check("#age-confirmed")
        await page.click("button.provider[data-provider=google]")
        await expect(page.locator("#reg-form")).to_be_visible()
        await expect(page.locator("#who")).to_contain_text("Logged in as user-")
        notices = await self.fetch("SELECT kind, age_confirmed FROM notice_records")
        self.assertEqual([(n["kind"], n["age_confirmed"]) for n in notices], [("signup", True)])
        # The form: a made-up username is not offered as the name; the name is needed.
        await expect(page.locator("#reg-name")).to_have_value("")
        await page.click("#reg-submit")
        await expect(page.locator("#reg-error")).to_have_text("Type a name or a callsign.")
        await page.fill("#reg-name", "Raposa")
        await page.select_option("#reg-team", "blue")
        await page.click("#replica-add")
        await page.click("#reg-submit")
        await expect(page.locator("#reg-error")).to_have_text("Pick each replica's class.")
        row = page.locator("#replicas li").first
        await row.locator(".replica-type").select_option("gbb")
        classes = await row.locator(".replica-class option").evaluate_all("(os) => os.map((o) => o.value)")
        await row.locator(".replica-class").select_option(classes[1])
        await row.locator(".replica-make").fill("Tokyo Marui Hi-Capa")
        await self.checks(page)
        await page.click("#reg-submit")
        # The ticket, once: a QR code and its text; the way into the app; a passkey for next time.
        await expect(page.locator("#ticket")).to_be_visible()
        await expect(page.locator("#status")).to_contain_text("You are registered.")
        await expect(page.locator("[data-testid=ticket-qr]")).to_be_visible()
        text = await page.locator("#ticket-text").text_content()
        self.assertTrue(text.startswith("atalaia:ticket:"), text)
        href = await page.locator("#open-app").get_attribute("href")
        self.assertTrue(href.startswith("atalaia://register?site="), href)
        self.assertIn(f"game={game}", href)
        await expect(page.locator("#passkey-add")).to_be_visible()
        await expect(page.locator("#pk-add")).to_be_visible()
        regs = await self.fetch("SELECT id, display_name, team_preference, source, status, ticket_hash "
                                "FROM game_registrations")
        self.assertEqual([(r["display_name"], r["team_preference"], r["source"], r["status"]) for r in regs],
                         [("Raposa", "blue", "site", "registered")])
        replicas = await self.fetch("SELECT replica_type, replica_class, make_model FROM registration_replicas")
        self.assertEqual([(r["replica_type"], r["make_model"]) for r in replicas], [("gbb", "Tokyo Marui Hi-Capa")])
        self.assertNotIn(text, json.dumps(await page.evaluate("() => ({...sessionStorage})")))  # never kept
        await self.checks(page)
        # Back on the page later: the registration, the form to change it, a new ticket on request.
        await page.reload()
        await expect(page.locator("#reg-state-text")).to_have_text("You are registered for this game.")
        await expect(page.locator("#ticket")).to_be_hidden()
        await expect(page.locator("#ticket-lost")).to_be_visible()
        await expect(page.locator("#reg-legend")).to_have_text("Change your registration")
        await expect(page.locator("#reg-name")).to_have_value("Raposa")
        await expect(page.locator("#replicas li")).to_have_count(1)
        await page.fill("#reg-name", "Raposa Velha")
        await page.click("#reg-submit")
        await expect(page.locator("#status")).to_contain_text("Registration changed.")
        self.assertEqual((await self.fetch("SELECT display_name FROM game_registrations"))[0][0], "Raposa Velha")
        await page.click("#new-ticket")
        await expect(page.locator("#ticket")).to_be_visible()
        second = await page.locator("#ticket-text").text_content()
        self.assertNotEqual(second, text)
        self.assertNotEqual((await self.fetch("SELECT ticket_hash FROM game_registrations"))[0][0], regs[0]["ticket_hash"])
        await page.click("#reg-cancel")
        await expect(page.locator("#status")).to_contain_text("Registration cancelled.")
        await expect(page.locator("#reg-legend")).to_have_text("Registration")
        self.assertEqual((await self.fetch("SELECT status FROM game_registrations"))[0][0], "cancelled")
        self.assertTrue(any("Cancel your registration for Domingo no bosque?" in d for d in self.dialogs))
        # The register page leads here.
        await page.goto(self.base + f"/f/campo-norte/games/{game}/register?lang=en")
        await page.click("text=Register here")
        await page.wait_for_url(f"**{self.page_path(game)}")
        await expect(page.locator("#reg-form")).to_be_visible()  # still logged in

    async def test_a_passkey_added_after_registering_logs_in_next_time(self) -> None:
        game = await self.open_game(replicas=False)
        page = await self.new_page(lang="en-GB")
        await self.virtual_authenticator(page)
        await self.google_signup(page, game)
        await page.fill("#reg-name", "Lince")
        await page.click("#reg-submit")
        await expect(page.locator("#ticket")).to_be_visible()
        await page.click("#pk-add")
        await expect(page.locator("#status")).to_contain_text("Passkey added.")
        await expect(page.locator("#passkey-add")).to_be_hidden()
        self.assertEqual((await self.fetch("SELECT count(*) FROM passkeys"))[0][0], 1)
        await page.click("#logout")
        await expect(page.locator("#login-section")).to_be_visible()
        await expect(page.locator("#status")).to_contain_text("Logged out.")
        await page.click("#passkey-login")
        await expect(page.locator("#login-section")).to_be_hidden()
        await expect(page.locator("#reg-state")).to_be_visible()
        await expect(page.locator("#reg-state-text")).to_have_text("You are registered for this game.")
        session = await self.session_json(page)
        self.assertTrue(session["mfa"])


class RulesTests(RegisterBrowserCase):
    async def test_a_password_account_and_the_membership_rule(self) -> None:
        await self.fetch("UPDATE fields SET country = 'PT', apd_rule = $1 WHERE id = $2",
                         json.dumps({"register": True, "checkin": False, "expiry": True}), self.field_id)
        game = await self.open_game(replicas=False, federation="optional")
        name, secret = await self.staff(with_totp=True)
        page = await self.new_page(lang="pt-PT", viewport=PHONE)
        await page.goto(self.base + self.page_path(game, lang=""))
        await expect(page.locator("#login-form")).to_be_visible()
        await page.fill("#username", name)
        await page.fill("#password", "wrong password")
        await page.click("#login-form button[type=submit]")
        await expect(page.locator("#status")).not_to_be_empty()
        await page.fill("#password", PASSWORD)
        await page.click("#login-form button[type=submit]")
        await expect(page.locator("#code")).to_be_visible()
        await page.fill("#code", self.code(secret))
        await page.click("#totp-form button[type=submit]")
        await expect(page.locator("#reg-form")).to_be_visible()
        await expect(page.locator("#reg-name")).to_have_value(name)  # a username the person chose is the default
        await expect(page.locator("#apd-title")).to_have_text("Filiação numa APD")
        await expect(page.locator("#fed-block")).to_be_hidden()
        await page.click("#reg-submit")
        await expect(page.locator("#reg-error")).to_have_text("Este campo pede o número de associado da APD.")
        await page.fill("#apd-number", "12345")
        await page.fill("#apd-expires", "2027-02-30")
        await page.click("#reg-submit")
        await expect(page.locator("#reg-error")).to_contain_text("AAAA-MM-DD")
        # A membership that ended before the game: the page lets it through, the server refuses it (protocol/apd.md).
        await page.fill("#apd-expires", "2020-01-31")
        await page.click("#reg-submit")
        await expect(page.locator("#reg-error")).to_be_visible()
        self.assertEqual((await self.fetch("SELECT count(*) FROM game_registrations"))[0][0], 0)
        await page.fill("#apd-expires", (hour(400)).date().isoformat())
        await page.click("#reg-submit")
        await expect(page.locator("#ticket")).to_be_visible()
        rows = await self.fetch("SELECT federation_number, membership_expires FROM game_registrations")
        self.assertEqual(rows[0]["federation_number"], "12345")
        await self.checks(page)
        # The account has no notice record: the page asks it to read the notice again (CONS-*), as the staff pages do.
        await expect(page.locator("#notice-again")).to_be_visible()

    async def test_a_closed_game_and_the_languages(self) -> None:
        closed = await self.open_game("Fechado", opens=hour(-5), closes=hour(-1))
        page = await self.new_page(lang="en-GB", viewport=PHONE)
        await self.google_signup(page, await self.open_game("Aberto", replicas=False))
        await page.goto(self.base + self.page_path(closed))
        await expect(page.locator("#closed")).to_be_visible()
        await expect(page.locator("#reg-form")).to_be_hidden()
        for lang, title, button in (("pt", "Inscrição online: Fechado", "Sair"), ("de", "Online anmelden: Fechado", "Abmelden"),
                                    ("zh-tw", "線上報名：Fechado", "登出")):
            await page.goto(self.base + self.page_path(closed, lang=lang))
            await expect(page.locator("h1")).to_have_text(title)
            await expect(page.locator("#logout")).to_have_text(button)
            await expect(page.locator("#closed")).to_be_visible()
            await self.checks(page)
        await page.click("#logout")
        await expect(page.locator("#login-section")).to_be_visible()
        await expect(page.locator("button.provider[data-provider=google]")).to_have_text("使用 Google 繼續")
        await self.checks(page)
