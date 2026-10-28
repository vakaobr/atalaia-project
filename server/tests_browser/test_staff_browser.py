# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field staff's pages in a real browser (headless Chromium, Playwright; decisions FU2-1 to FU2-12).

    python3 tools/docker_server.py browser      (or server/tests_browser/run.sh in its image)

Each test runs the real application under uvicorn on a free port of localhost, over HTTPS with a
certificate made for the test (the refresh cookie is Secure), next to its own PostgreSQL
database (``tests/base.py``), and drives the pages as staff would: log in with the password and the TOTP
code, then the game history and a game's timeline and log, the history settings, the scenario library (a
manifest with problems, checked; fixed, saved, revised, archived), the presets, the device health and the
remote GM against a controller's socket (``tests/test_remote_gm.Stream``) and the remote ATAK relay's
enrolment (a data package downloaded, a certificate revoked), and the schedule, a game's registrations and
its printable roster (decisions FU6-1 to FU6-7, at 375 px too). The roles are the API's: a
player's session sees its role refused. Every page is checked for script errors and content security
policy violations, for labels on its form controls, and for sideways scrolling at a phone's width.

With ATALAIA_REQUIRE_BROWSER=1 (run.sh, CI) a missing Playwright or Chromium is an error, never a skip.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import socket
import tempfile
import unittest
import uuid
import zipfile
from pathlib import Path
from typing import Any, Optional

import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from atalaia_server import sync
from atalaia_server.config import Settings
from atalaia_server.ratelimit import RequestLimit

from tests.base import PASSWORD, AppTestCase
from tests.test_remote_gm import Stream
from tests.test_scenarios_api import BAD, MANIFEST

REQUIRE = os.environ.get("ATALAIA_REQUIRE_BROWSER") == "1"
try:
    from playwright.async_api import Page, async_playwright, expect
except ImportError:
    if REQUIRE:
        raise
    async_playwright = None  # type: ignore[assignment]

CTRL = {"id": "0192f3a4-5b6c-7d8e-9f01-23456789abcd", "version": "0.1.0"}
GAME = {"game_id": 4242, "game_seed": 3735928559}
EVIL = '<img src=x onerror="window.pwned=1">'
SHORT_EVIL = '<img src=x onerror="pwned=1">'  # within a display name's 32 characters
ROLE = {"player": 1, "marshal": 4, "gm": 5, "admin": 7}
PHONE = {"width": 360, "height": 740}
LIVE = {"game": GAME, "name": "Domingo", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"],
        "state": "ready", "in_charge": True, "totals": {"red": 3, "blue": 5}, "game_time_ms": None, "duration_ms": 0,
        "nodes": [{"node_id": 7, "name": "alpha", "role": "zone", "last_seen": 1792000000.0,
                   "info": {"battery_pct": 80}}],
        "events": [], "mode_commands": [{"name": "refill", "roles": ["gm"]}]}


def self_signed(folder: Path) -> tuple[str, str]:
    """A certificate for localhost, so the pages are served over HTTPS as in a deployment: the refresh token is a
    Secure cookie with the __Secure- prefix, which a browser keeps only from an https:// page."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
            .sign(key, hashes.SHA256()))
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                           serialization.NoEncryption()))
    return str(cert_path), str(key_path)


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipIf(async_playwright is None, "Playwright is not installed (python3 tools/docker_server.py browser)")
class BrowserCase(AppTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.tls = tempfile.TemporaryDirectory()
        cls.cert, cls.cert_key = self_signed(Path(cls.tls.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.tls.cleanup()
        super().tearDownClass()

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.app.state.limits.requests = RequestLimit(100000, 60)  # the browser and the test share 127.0.0.1
        port = free_port()
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=port, lifespan="off",
                                                    log_level="warning", ssl_certfile=self.cert,
                                                    ssl_keyfile=self.cert_key))
        self.serving = asyncio.create_task(self.server.serve())
        for _ in range(200):
            if self.server.started:
                break
            await asyncio.sleep(0.025)
        self.assertTrue(self.server.started, "uvicorn did not start")
        self.base = f"https://localhost:{port}"
        self.field_id = (await self.fetch("INSERT INTO fields (name, slug) VALUES ('Campo Norte', 'campo-norte') "
                                          "RETURNING id"))[0][0]
        self.key = sync.new_key()
        await self.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field_id,
                         sync.key_hash(self.key))
        self.playwright = await async_playwright().start()
        # The test's certificate is accepted, for the test's browser only.
        self.browser = await self.playwright.chromium.launch(args=["--ignore-certificate-errors"])
        self.problems: list[str] = []
        self.dialogs: list[str] = []  # what each confirm() said (every one is accepted)
        self.pages: list[Page] = []

    async def asyncTearDown(self) -> None:
        for page in self.pages:
            await page.close()
        await self.browser.close()
        await self.playwright.stop()
        self.server.should_exit = True
        await self.serving
        await super().asyncTearDown()
        self.assertEqual(self.problems, [], "script errors or policy violations on the pages")

    async def new_page(self, lang: str = "pt-PT", viewport: Optional[dict[str, int]] = None) -> Page:
        context = await self.browser.new_context(locale=lang, viewport=viewport or {"width": 1200, "height": 900},
                                                 ignore_https_errors=True)  # the test's own certificate
        page = await context.new_page()

        def console(msg: Any) -> None:
            # A refused API call shows as "Failed to load resource" (the pages show it in words); anything
            # else is a problem: a script error, a CSP violation.
            if msg.type == "error" and not msg.text.startswith("Failed to load resource"):
                self.problems.append(f"{page.url}: {msg.text}")

        page.on("console", console)
        page.on("pageerror", lambda exc: self.problems.append(f"{page.url}: {exc}"))

        def on_dialog(dialog: Any) -> None:
            self.dialogs.append(dialog.message)
            asyncio.ensure_future(dialog.accept())

        page.on("dialog", on_dialog)
        self.pages.append(page)
        return page

    # Data -----------------------------------------------------------------------------------

    async def staff(self, *roles: str, with_totp: bool = True) -> tuple[str, Optional[str]]:
        user_id, name, secret = await self.make_user(with_totp=with_totp)
        for role in roles:
            await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                             user_id, self.field_id, ROLE[role])
        return name, secret

    async def push(self, kind: str, game: dict[str, int], **body: Any) -> dict[str, Any]:
        r = await self.client.post(f"/api/v1/sync/{kind}", json={"sync_version": 1, "controller": CTRL, "game": game,
                                                                   **body},
                                   headers={"Authorization": f"Bearer {self.key}"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    async def make_game(self, game: dict[str, int], name: str, state: str = "ended", **meta: Any) -> str:
        answer = await self.push("games", game, meta={"name": name, "mode_id": "org.atalaia.domination",
                                                      "teams": ["red", "blue"], "state": state,
                                                      "created_at": 1792000000.0 + game["game_id"],
                                                      "started_at": 1792000100.0 + game["game_id"], **meta})
        return answer["game"]

    # Pages ----------------------------------------------------------------------------------

    async def login(self, page: Page, name: str, secret: Optional[str], path: str = "/staff/") -> None:
        await page.goto(self.base + path)
        await page.wait_for_url("**/staff/login?next=*")
        await page.fill("#username", name)
        await page.fill("#password", PASSWORD)
        await page.click("#login-form button[type=submit]")
        if secret is not None:
            await expect(page.locator("#code")).to_be_visible()
            await page.fill("#code", self.code(secret))
            await page.click("#totp-form button[type=submit]")
        await page.wait_for_url(f"{self.base}{path}")

    async def check_page(self, page: Page, width: int = PHONE["width"]) -> None:
        """Every visible form control has a label, and nothing scrolls sideways at a phone's width."""
        unlabelled = await page.evaluate("""() => [...document.querySelectorAll('input, select, textarea')]
            .filter((e) => e.offsetParent !== null && e.type !== 'hidden' && !(e.labels && e.labels.length)
                    && !e.getAttribute('aria-label'))
            .map((e) => e.id || e.outerHTML.slice(0, 60))""")
        self.assertEqual(unlabelled, [], page.url)
        await page.set_viewport_size({"width": width, "height": PHONE["height"]})
        wide = await page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
        culprits = await page.evaluate("""() => [...document.querySelectorAll('body *')]
            .filter((e) => e.getBoundingClientRect().right > window.innerWidth + 1 && !(e.parentElement && e.parentElement.closest('.table-wrap')))
            .map((e) => e.tagName + '#' + e.id + '.' + e.className).slice(0, 8)""")
        self.assertLessEqual(wide, 0, f"{page.url} scrolls sideways at {width} px: {culprits}")
        await page.set_viewport_size({"width": 1200, "height": 900})

    def field_path(self, rest: str) -> str:
        return f"/staff/fields/{self.field_id}{rest}"


class LoginAndHistoryTests(BrowserCase):
    async def test_login_history_game_and_settings(self) -> None:
        ended = await self.make_game(GAME, "Domingo de manhã", state="ended", ended_at=1792003700.0)
        await self.push("events", GAME, after_id=0, events=[
            {"id": 1, "node": 3, "seq": 1, "t": 60000, "type": "zone.captured", "team": "red", "prio": "normal",
             "data": {"zone": "alpha"}},
            {"id": 2, "node": 4, "seq": 2, "t": 120000, "type": "zone.captured", "team": "blue", "prio": "normal",
             "data": {"zone": "bravo"}},
            {"id": 3, "node": 0, "seq": 3, "t": 3500000, "type": "game.end", "team": None, "prio": "normal",
             "data": {"reason": "time", "winner": "red"}}])
        await self.push("scores", GAME, counters={"node-3": {"red": 20}})
        await self.push("scores", GAME, counters={"node-3": {"red": 40}, "node-4": {"blue": 10}})
        await self.push("nodes", GAME, nodes=[{"node_id": 3, "name": "alpha", "role": "zone", "last_seen": 1792000500.0,
                                               "info": {"battery_pct": 15, "fw_version": "0.4.0", "platform": "1"}}])
        await self.make_game({"game_id": 7, "game_seed": 1}, EVIL, state="running", started_at=1792100000.0)
        name, secret = await self.staff("admin", "gm")
        page = await self.new_page()
        await self.login(page, name, secret, self.field_path("/history"))
        await expect(page.locator("#field-name")).to_have_text("Campo: Campo Norte")
        rows = page.locator("#games tbody tr")
        await expect(rows).to_have_count(2)
        await expect(rows.nth(1)).to_contain_text("Domingo de manhã")  # newest first
        await expect(rows.nth(1)).to_contain_text("red 40 · blue 10")
        await expect(rows.nth(1)).to_contain_text("terminado")
        # A game's name is text, never markup.
        await expect(rows.nth(0).locator("a")).to_have_text(EVIL)
        self.assertEqual(await page.locator("#games img").count(), 0)
        self.assertIsNone(await page.evaluate("() => window.pwned"))
        # The filters.
        await page.select_option("#f-state", "running")
        await page.click("#filters button[type=submit]")
        await expect(rows).to_have_count(1)
        await page.select_option("#f-state", "")
        await page.click("#filters button[type=submit]")
        await expect(rows).to_have_count(2)
        # The settings: the field's admin changes them.
        await expect(page.locator("#settings")).to_be_visible()
        await expect(page.locator("#s-delay")).to_have_value("60")
        await page.fill("#s-delay", "120")
        await page.check("#s-public")
        await page.click("#settings-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Guardado.")
        row = (await self.fetch("SELECT spectator_delay_s FROM field_history_settings WHERE field_id = $1",
                                self.field_id))[0]
        self.assertEqual(row["spectator_delay_s"], 120)
        self.assertTrue((await self.fetch("SELECT public_scoreboard FROM fields WHERE id = $1",
                                          self.field_id))[0]["public_scoreboard"])
        await self.check_page(page)
        # One game: the summary, the timeline, the log, its boxes.
        await rows.nth(1).locator("a").click()
        await page.wait_for_url(f"**/games/{ended}")
        await expect(page.locator("#game-name")).to_have_text("Domingo de manhã")
        await expect(page.locator("#summary")).to_contain_text("red")  # the winner
        await expect(page.locator("#teams tbody tr")).to_have_count(2)
        await expect(page.locator("#chart polyline")).to_have_count(2)
        await page.click("#timeline-details summary")
        await expect(page.locator("#timeline tbody tr")).to_have_count(3)  # the start and two arrivals
        log = page.locator("#log tbody tr")
        await expect(log).to_have_count(3)
        await page.select_option("#l-type", "zone.captured")
        await page.click("#log-filters button[type=submit]")
        await expect(log).to_have_count(2)
        await page.select_option("#l-team", "blue")
        await page.click("#log-filters button[type=submit]")
        await expect(log).to_have_count(1)
        await expect(log.first).to_contain_text("2:00")
        await expect(page.locator("#game-devices-section")).to_be_visible()
        await expect(page.locator("#game-devices")).to_contain_text("bateria fraca")
        await self.check_page(page)

    async def test_a_gm_reads_the_settings_and_the_session_survives_a_new_tab(self) -> None:
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/history"))
        await expect(page.locator("#settings-readonly")).to_be_visible()
        await expect(page.locator("#s-delay")).to_be_disabled()  # its fieldset stays disabled
        await expect(page.locator("#games-none")).to_have_text("No games with these filters.")
        # A new tab has no access token: it gets one from the refresh cookie, without logging in again.
        second = await page.context.new_page()
        second.on("pageerror", lambda exc: self.problems.append(str(exc)))
        self.pages.append(second)
        await second.goto(self.base + self.field_path("/devices"))
        await expect(second.locator("#devices-none")).to_be_visible()
        self.assertTrue(second.url.endswith("/devices"))
        # Logging out ends the session for every tab: the refresh cookie no longer works.
        await page.click("#logout")
        await page.wait_for_url("**/staff/login?out=1")
        await expect(page.locator("#status")).to_have_text("Logged out.")
        await second.evaluate("() => sessionStorage.clear()")
        await second.reload()
        await second.wait_for_url("**/staff/login?next=*")

    async def test_wrong_password_and_wrong_code(self) -> None:
        name, secret = await self.staff("gm")
        page = await self.new_page()
        await page.goto(self.base + "/staff/login")
        await page.fill("#username", name)
        await page.fill("#password", "not the password at all")
        await page.click("#login-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Nome de utilizador ou palavra-passe errados.")
        await page.fill("#password", PASSWORD)
        await page.click("#login-form button[type=submit]")
        await expect(page.locator("#code")).to_be_visible()
        await page.fill("#code", "000000")
        await page.click("#totp-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Código errado.")
        await self.check_page(page)


class LibraryTests(BrowserCase):
    async def test_check_save_revise_archive(self) -> None:
        name, secret = await self.staff("gm")
        page = await self.new_page()
        await self.login(page, name, secret, self.field_path("/scenarios"))
        await expect(page.locator("#scenarios-none")).to_be_visible()
        await page.click("#new-scenario")
        await page.wait_for_url("**/scenarios/new")
        # A manifest with a problem: the check names it and stores nothing.
        await page.fill("#manifest-text", BAD)
        await page.click("#check")
        problems = page.locator("#check-result table.problems tbody tr")
        await expect(problems.first).to_be_visible()
        self.assertIn("nowhere", await page.locator("#check-result").inner_text())
        await expect(page.locator("#check-result p.status")).to_have_class("status error")
        await page.click("#editor-form button[type=submit]")  # saving it is refused, with the same problems
        await expect(page.locator("#status")).to_have_text("O cenário tem problemas: ver a lista.")
        self.assertEqual(await self.fetch("SELECT * FROM field_scenarios"), [])
        # Fixed: the check passes (in the core too), and saving makes revision 1.
        await page.fill("#manifest-text", MANIFEST)
        await page.click("#check")
        await expect(page.locator("#check-result p.status")).to_have_text("Sem erros. O núcleo carregou o cenário.")
        await expect(page.locator("#check-result")).to_contain_text("bridge (objective)")
        await page.click("#editor-form button[type=submit]")
        await page.wait_for_url("**/scenarios/org.test.two")
        await expect(page.locator("#scenario-heading")).to_have_text("Two objectives (org.test.two)")
        await expect(page.locator("#revisions tbody tr")).to_have_count(1)
        await page.click("#package summary")
        await expect(page.locator("#package-files")).to_contain_text("field.lua")
        # A new revision.
        await page.click("#edit")
        await expect(page.locator("#manifest-text")).to_have_value(MANIFEST)
        await page.fill("#manifest-text", MANIFEST.replace("version: 1", "version: 2"))
        await page.click("#editor-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Revisão 2 guardada.")
        await expect(page.locator("#revisions tbody tr")).to_have_count(2)
        await page.locator("#revisions tbody tr").nth(1).locator("button").click()
        await expect(page.locator("#revision-title")).to_have_text("Revisão 1")
        await expect(page.locator("#revision-manifest")).to_contain_text("version: 1")
        await self.check_page(page)
        # Archived: no longer sent to the controllers.
        await page.click("#archive")
        await expect(page.locator("#archived-notice")).to_be_visible()
        archived = await self.fetch("SELECT archived_at FROM field_scenarios")
        self.assertIsNotNone(archived[0]["archived_at"])
        await page.click("#back")
        await expect(page.locator("#scenarios-none")).to_be_visible()
        await page.check("#show-archived")
        await expect(page.locator("#scenarios tbody tr")).to_contain_text("arquivado")
        await self.check_page(page)

    async def test_presets(self) -> None:
        name, secret = await self.staff("admin")
        page = await self.new_page()
        await self.login(page, name, secret, self.field_path("/presets"))
        await expect(page.locator("#presets-none")).to_be_visible()
        await page.fill("#p-name", "Domingo curto")
        await page.fill("#p-mode", "org.atalaia.domination")
        await page.fill("#p-params", "{not json")
        await page.click("#preset-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Os parâmetros não são um objeto JSON válido.")
        await page.fill("#p-params", '{"duration_s": 900}')
        await page.click("#preset-form button[type=submit]")
        rows = page.locator("#presets tbody tr")
        await expect(rows).to_have_count(1)
        await expect(rows.first).to_contain_text("duration_s")
        await rows.first.get_by_role("button", name="Editar: Domingo curto").click()
        await expect(page.locator("#preset-form-title")).to_have_text("Editar «Domingo curto»")
        await page.fill("#p-name", "Domingo longo")
        await page.click("#preset-form button[type=submit]")
        await expect(rows.first).to_contain_text("Domingo longo")
        stored = await self.fetch("SELECT name, params FROM field_presets")
        self.assertEqual((stored[0]["name"], json.loads(stored[0]["params"])), ("Domingo longo", {"duration_s": 900}))
        await self.check_page(page)
        await rows.first.get_by_role("button", name="Apagar: Domingo longo").click()
        await expect(page.locator("#presets-none")).to_be_visible()
        self.assertEqual(await self.fetch("SELECT * FROM field_presets"), [])


class DeviceTests(BrowserCase):
    async def test_flags_in_words(self) -> None:
        game = {"game_id": 9, "game_seed": 9}
        await self.make_game(game, "Treino", state="running")
        await self.push("nodes", game, nodes=[
            {"node_id": 3, "name": "alpha", "role": "zone", "last_seen": 1792000500.0, "info": {"battery_pct": 12}},
            {"node_id": 4, "name": "bravo", "role": "zone", "last_seen": 1792000500.0, "info": {"battery_pct": 90}}])
        await self.push("events", game, after_id=0, events=[
            {"id": 1, "node": 4, "seq": 1, "t": 1000, "type": "node.tamper", "prio": "telemetry",
             "data": {"reason": "kiosk_broken"}}])
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/devices"))
        rows = page.locator("#devices tbody tr")
        await expect(rows).to_have_count(2)
        await expect(rows.nth(0)).to_contain_text("battery low")
        await expect(rows.nth(0)).to_contain_text("12 %")
        await expect(rows.nth(1)).to_contain_text("tampered")
        await expect(rows.nth(1).locator("a")).to_have_text("Treino")
        await self.check_page(page)


class RemoteGmTests(BrowserCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.streams: list[Stream] = []

    async def asyncTearDown(self) -> None:
        for stream in self.streams:
            await stream.close()
        await super().asyncTearDown()

    async def controller(self, live: dict[str, Any]) -> Stream:
        stream = Stream(self.app, self.key)
        self.streams.append(stream)
        self.assertEqual((await stream.open())["type"], "websocket.accept")
        await stream.send({"type": "hello", "sync_version": 1, "controller": CTRL, "remote_gm": True})
        self.assertEqual(await stream.receive(), {"type": "hello.ack", "remote_gm": True, "atak_relay": False})
        await stream.send({"type": "live", "sync_version": 1, "controller": CTRL, "live": live})
        await asyncio.sleep(0.05)
        return stream

    async def answer(self, stream: Stream, code: str = "done", detail: Optional[str] = None,
                     **result: Any) -> dict[str, Any]:
        cmd = await stream.receive(timeout=15)
        self.assertEqual(cmd["type"], "command")
        await stream.send({"type": "command.result", "sync_version": 1, "controller": CTRL, "id": cmd["id"],
                           "code": code, **({"detail": detail} if detail else {}), **result})
        return cmd

    async def test_the_players_positions_are_listed(self) -> None:
        """PKD-5: the controller's ``positions`` come to the page as a list (no plan), pushed with the view."""
        stream = await self.controller(LIVE)
        name, secret = await self.staff("gm")
        page = await self.new_page()
        await self.login(page, name, secret, self.field_path("/remote-gm"))
        card = page.locator("article.controller")
        await expect(card).to_have_count(1)
        await expect(card.locator(".positions")).to_contain_text("Ninguém está a partilhar a posição.")
        await stream.send({"type": "positions", "sync_version": 1, "controller": CTRL, "game": GAME, "positions": [
            {"player_id": "p-abcdef234567", "source": "gps", "age_s": 2, "team": "red", "role": "player",
             "lat": 41.1579, "lon": -8.6291, "accuracy_m": 6.4},
            {"player_id": "p-bcdefg234567", "source": "ble", "age_s": 9, "team": "blue", "room": "Hangar 2",
             "zone": "Norte", "level": 1}]})
        rows = card.locator(".positions tbody tr")
        await expect(rows).to_have_count(2, timeout=15000)
        await expect(rows.first).to_contain_text("p-abcdef234567")
        await expect(rows.first).to_contain_text("41.15790, -8.62910")
        await expect(rows.nth(1)).to_contain_text("Hangar 2 (Norte), piso 1")
        await stream.send({"type": "positions", "sync_version": 1, "controller": CTRL, "game": None,
                           "positions": []})
        await expect(rows).to_have_count(0, timeout=15000)
        await self.check_page(page)

    async def test_live_view_commands_and_log(self) -> None:
        stream = await self.controller(LIVE)
        name, secret = await self.staff("gm")
        page = await self.new_page()
        await self.login(page, name, secret, self.field_path("/remote-gm"))
        card = page.locator("article.controller")
        await expect(card).to_have_count(1)
        await expect(card.locator("h3")).to_have_text("Domingo")
        await expect(card).to_contain_text("a preparar")
        start = card.get_by_role("button", name="Começar")
        await expect(start).to_be_enabled()
        await expect(card.get_by_role("button", name="Pausa")).to_be_disabled()
        await start.click()
        cmd = await self.answer(stream)
        self.assertEqual((cmd["command"], cmd["params"], cmd["game"]), ("start", {}, GAME))
        await expect(page.locator("#command-result")).to_have_text("Feito: Começar.")
        # The view follows the controller's next live message.
        await stream.send({"type": "live", "sync_version": 1, "controller": CTRL,
                           "live": {**LIVE, "state": "running", "game_time_ms": 65000, "duration_ms": 1800000}})
        await expect(card).to_contain_text("a decorrer", timeout=15000)
        await expect(card).to_contain_text("1:05 / 30:00")
        # A message, a mode command to one box, a refused pause.
        await card.get_by_label("Mensagem para as caixas (até 100 caracteres)").fill("5 minutos")
        await card.get_by_role("button", name="Enviar mensagem").click()
        cmd = await self.answer(stream)
        self.assertEqual((cmd["command"], cmd["params"]), ("message", {"text": "5 minutos"}))
        await expect(page.locator("#command-result")).to_have_text("Feito: Enviar mensagem.")
        await card.get_by_label("Caixa", exact=True).select_option("7")
        await card.get_by_role("button", name="Enviar comando do modo").click()
        cmd = await self.answer(stream)
        self.assertEqual((cmd["command"], cmd["params"]), ("mode", {"name": "refill", "node": 7}))
        await card.get_by_label("Motivo (opcional)").fill("ferido")
        await card.get_by_role("button", name="Pausa").click()
        cmd = await self.answer(stream, code="conflict", detail="the game is on standby")
        self.assertEqual(cmd["params"], {"reason": "ferido"})
        await expect(page.locator("#command-result")).to_have_text(
            "O controlador recusou: conflict: the game is on standby.")
        # Every attempt is in the log.
        await page.click("#log-refresh")
        await expect(page.locator("#remote-log tbody tr")).to_have_count(4)
        await expect(page.locator("#remote-log tbody tr").first).to_contain_text("conflict")
        await self.check_page(page)

    async def test_the_view_is_pushed_and_not_polled(self) -> None:
        """S19-11: a stream delivers the view; the page's polling (GET .../remote-gm) stays silent meanwhile."""
        stream = await self.controller(LIVE)
        name, secret = await self.staff("gm")
        page = await self.new_page()
        polls: list[str] = []
        streams: list[str] = []
        page.on("request", lambda r: (polls if r.url.endswith("/api/v1/fields/" + str(self.field_id) + "/remote-gm") else streams).append(r.url)
                if "/api/v1/" in r.url and "/remote-gm" in r.url and not r.url.endswith("/log") else None)
        await self.login(page, name, secret, self.field_path("/remote-gm"))
        card = page.locator("article.controller")
        await expect(card).to_have_count(1)
        await stream.send({"type": "live", "sync_version": 1, "controller": CTRL,
                           "live": {**LIVE, "state": "running", "game_time_ms": 65000, "duration_ms": 1800000}})
        await expect(card).to_contain_text("a decorrer", timeout=3000)  # well under the 5 s polling period
        await asyncio.sleep(6)
        self.assertTrue(any(u.endswith("/remote-gm/stream") for u in streams), streams)
        self.assertLessEqual(len(polls), 1, polls)  # at most the first look, before the stream was open

    async def test_a_start_refused_for_missing_roles_asks_start_anyway(self) -> None:
        """Decision RG-1: the controller refuses the start naming the roles; the page asks (the console's
        "Start anyway?", with the roles) and sends the same start again with force."""
        stream = await self.controller(LIVE)
        name, secret = await self.staff("gm")
        page = await self.new_page()
        await self.login(page, name, secret, self.field_path("/remote-gm"))
        card = page.locator("article.controller")
        await expect(card.get_by_role("button", name="Começar")).to_be_enabled()
        await card.get_by_role("button", name="Começar").click()
        refusal = "no box or prop has joined for: zone; join them, or start anyway (force)"
        cmd = await self.answer(stream, code="conflict", detail=refusal, missing=["zone"])
        self.assertEqual(cmd["params"], {})
        cmd = await self.answer(stream)  # the page asked, and sent it again
        self.assertEqual((cmd["command"], cmd["params"]), ("start", {"force": True}))
        self.assertEqual(self.dialogs, ["Falta uma caixa (ou um telemóvel ligado) para: zone. Começar mesmo assim?"])
        await expect(page.locator("#command-result")).to_have_text("Feito: Começar.")
        await page.click("#log-refresh")
        await expect(page.locator("#remote-log tbody tr")).to_have_count(2)
        await expect(page.locator("#remote-log tbody tr").first).to_contain_text("force")
        await self.check_page(page)

    async def test_a_refusal_without_roles_is_only_shown(self) -> None:
        stream = await self.controller(LIVE)
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/remote-gm"))
        await page.locator("article.controller").get_by_role("button", name="Start").click()
        await self.answer(stream, code="conflict", detail="the game is on standby")
        await expect(page.locator("#command-result")).to_have_text(
            "The controller refused: conflict: the game is on standby.")
        self.assertEqual(self.dialogs, [])
        self.assertEqual(stream.pending(), 0)  # no second start

    async def test_a_field_admin_sees_the_log_but_not_the_live_view(self) -> None:
        await self.controller(LIVE)
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/remote-gm"))
        await expect(page.locator("#status")).to_contain_text("This part needs the GM role on this field")
        await expect(page.locator("article.controller")).to_have_count(0)
        await expect(page.locator("#remote-log-none")).to_be_visible()


class AtakTests(BrowserCase):
    """The remote ATAK relay's page (Phase 4 follow-up FU5): a gm issues a device's certificate, downloads its
    data package (made in the page from the API's answer), sees it listed, revokes it."""

    def settings(self) -> Settings:
        return Settings(**{**super().settings().__dict__, "atak_relay": True, "atak_relay_port": 0,
                           "atak_relay_host": "localhost"})

    async def test_issue_download_and_revoke(self) -> None:
        name, secret = await self.staff("gm")
        page = await self.new_page()
        await self.login(page, name, secret, self.field_path("/atak"))
        await expect(page.locator("#atak-connect")).to_have_text(
            "Os dispositivos ligam-se a localhost:8089 (TLS com certificado de cliente).")
        await expect(page.locator("#atak-certs-none")).to_be_visible()
        await page.fill("#a-device", EVIL)
        await page.fill("#a-days", "3")
        await page.check("#a-positions")
        await page.click("#atak-form button[type=submit]")
        await expect(page.locator("#atak-issued")).to_be_visible()
        password = await page.locator("#atak-password").text_content() or ""
        self.assertGreaterEqual(len(password), 20)
        async with page.expect_download() as info:
            await page.click("#atak-download")
        download = await info.value
        self.assertRegex(download.suggested_filename, r"^atalaia-campo-norte-[A-Za-z0-9._-]+\.zip$")
        path = await download.path()
        assert path is not None
        with zipfile.ZipFile(path) as z:
            client = pkcs12.load_pkcs12(z.read("certs/client.p12"), password.encode())
            self.assertIn(b"localhost:8089:ssl", z.read("certs/atalaia.pref"))
        assert client.cert is not None
        self.assertEqual(client.cert.certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value, EVIL)
        rows = page.locator("#atak-certs tbody tr")
        await expect(rows).to_have_count(1)
        await expect(rows.first).to_contain_text("válido")
        await expect(page.locator("#atak-expiring")).to_be_visible()  # 3 days: near expiry (SVX-1)
        await expect(rows.first).to_contain_text("expira em breve")
        await expect(rows.first.locator("th")).to_have_text(EVIL)  # a device's name is text, never markup
        self.assertIsNone(await page.evaluate("() => window.pwned"))
        await rows.first.get_by_role("button").click()  # the confirmation is accepted
        await expect(page.locator("#status")).to_contain_text("Certificado revogado")
        await expect(rows.first).to_contain_text("revogado")
        await expect(page.locator("#atak-log tbody tr")).to_have_count(2)
        self.assertIsNotNone((await self.fetch("SELECT revoked_at FROM atak_certs"))[0]["revoked_at"])
        await self.check_page(page)

    async def test_positions_for_a_player_and_a_marshal_without_the_role(self) -> None:
        name, secret = await self.staff("admin")
        player, _ = await self.staff("player", with_totp=False)
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/atak"))
        await page.fill("#a-device", "Phone")
        await page.fill("#a-holder", player)
        await page.check("#a-positions")
        await page.click("#atak-form button[type=submit]")
        # The field's admin alone may not issue positions at all (FU5-13: the issuer receives the key).
        await expect(page.locator("#status")).to_have_text(
            "Only someone with the GM or marshal role on this field may issue a certificate that sees positions.")
        await page.uncheck("#a-positions")
        await page.click("#atak-form button[type=submit]")
        await expect(page.locator("#atak-certs tbody tr")).to_have_count(1)
        await expect(page.locator("#atak-certs tbody tr").first).to_contain_text(player)
        marshal, marshal_secret = await self.staff("marshal")
        other = await self.new_page()
        await self.login(other, marshal, marshal_secret, self.field_path("/atak"))
        await expect(other.locator("#status")).to_contain_text("precisa da função administração ou GM neste campo")
        await expect(other.locator('#sections li[data-section="atak"]')).to_be_hidden()


class ScheduleTests(BrowserCase):
    """The schedule, a game's registrations and its roster (Phase 4 follow-up FU6), at 375 px too."""

    async def lisbon(self) -> None:
        # The browser runs in UTC: a time typed on the page must be read in the field's zone.
        await self.fetch("UPDATE fields SET timezone = 'Europe/Lisbon' WHERE id = $1", self.field_id)

    async def published_game(self, title: str = "Domingo", starts: datetime.timedelta = datetime.timedelta(days=2)) -> str:
        row = await self.fetch(
            "INSERT INTO scheduled_games (field_id, title, starts_at, ends_at, status, teams, max_players, federation, "
            "registration_opens_at, registration_closes_at) VALUES ($1, $2, now() + $3::interval, "
            "now() + $3::interval + interval '4 hours', 'published', $4::jsonb, 10, 'optional', "
            "now() - interval '1 day', now() + interval '1 day') RETURNING id",
            self.field_id, title, starts, json.dumps(["red", "blue"]))
        return str(row[0]["id"])

    async def register(self, game: str, username: str, **body: Any) -> dict[str, Any]:
        await self.make_user(username)
        # (not self.auth: this class's login() is the page's)
        session = await self.client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
        headers = {"Authorization": f"Bearer {session.json()['access_token']}"}
        r = await self.client.post(f"/api/v1/fields/{self.field_id}/scheduled-games/{game}/registrations",
                                   json=body, headers=headers)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    async def test_create_edit_publish_cancel_and_delete_in_the_fields_time_zone(self) -> None:
        await self.lisbon()
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/schedule"))
        await expect(page.locator("#zone-note")).to_contain_text("Europe/Lisbon")
        await expect(page.locator("#schedule-none")).to_be_visible()
        await page.fill("#g-title", EVIL)
        await page.fill("#g-starts", "2030-07-06T10:00")
        await page.fill("#g-ends", "2030-07-06T14:00")
        await page.fill("#g-teams", "red\nblue\n")
        await page.fill("#g-max", "12")
        await page.fill("#g-opens", "2030-06-01T08:00")
        await page.fill("#g-closes", "2030-07-05T20:00")
        await page.select_option("#g-federation", "required")
        await page.click("#g-submit")
        await expect(page.locator("#status")).to_contain_text("Draft created")
        rows = page.locator("#schedule tbody tr")
        await expect(rows).to_have_count(1)
        # A title is text, never markup; the time is shown as typed, in the field's zone.
        await expect(rows.first.locator("th")).to_have_text(EVIL)
        self.assertEqual(await page.locator("#schedule img").count(), 0)
        self.assertIsNone(await page.evaluate("() => window.pwned"))
        await expect(rows.first).to_contain_text("10:00")
        await expect(rows.first).to_contain_text("draft")
        await expect(rows.first).to_contain_text("0 of 12")
        await expect(rows.first.locator("td").nth(3)).to_have_text("—")  # a draft has no registration state
        stored = (await self.fetch("SELECT title, starts_at, teams, max_players, federation, registration_closes_at, "
                                   "status FROM scheduled_games"))[0]
        self.assertEqual(stored["starts_at"].isoformat(), "2030-07-06T09:00:00+00:00")  # 10:00 in Lisbon's summer
        self.assertEqual(stored["registration_closes_at"].isoformat(), "2030-07-05T19:00:00+00:00")
        self.assertEqual((stored["title"], json.loads(stored["teams"]), stored["max_players"], stored["federation"],
                          stored["status"]), (EVIL, ["red", "blue"], 12, "required", "draft"))
        await self.check_page(page, 375)
        # Edit: the form comes back as typed (in the zone), and saves.
        await rows.first.locator("button", has_text="Edit").click()
        await expect(page.locator("#game-form-title")).to_have_text(f"Edit “{EVIL}”")
        await expect(page.locator("#g-starts")).to_have_value("2030-07-06T10:00")
        await page.fill("#g-title", "Sunday game")
        await page.fill("#g-max", "")
        await page.click("#g-submit")
        await expect(page.locator("#status")).to_have_text("Saved.")
        await expect(rows.first).to_contain_text("Sunday game")
        await expect(rows.first).to_contain_text("(no limit)")
        await expect(page.locator("#game-form-title")).to_have_text("New game")
        # A refusal is in words: the end before the start.
        await page.fill("#g-title", "Bad times")
        await page.fill("#g-starts", "2030-08-01T10:00")
        await page.fill("#g-ends", "2030-08-01T09:00")
        await page.click("#g-submit")
        await expect(page.locator("#status")).to_have_text("The end must be after the start, at most 14 days long.")
        await page.reload()
        # Publish (the admin's), then cancel with a reason.
        await rows.first.locator("button", has_text="Publish").click()
        await expect(page.locator("#status")).to_have_text("Game published.")
        await expect(rows.first).to_contain_text("published")
        await expect(rows.first).to_contain_text("not open yet")
        self.assertIn("Sunday game", self.dialogs[-1])
        await rows.first.locator("button", has_text="Cancel game").click()
        await expect(page.locator("#cancel-section")).to_be_visible()
        await page.fill("#c-reason", "Heavy rain")
        await page.click("#cancel-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Game cancelled.")
        await expect(rows.first).to_contain_text("cancelled")
        await expect(page.locator("#cancel-section")).to_be_hidden()
        await expect(rows.first.locator("button", has_text="Edit")).to_have_count(0)
        await expect(rows.first.locator("a", has_text="Registrations")).to_have_count(1)
        row = (await self.fetch("SELECT status, cancelled_reason FROM scheduled_games"))[0]
        self.assertEqual((row["status"], row["cancelled_reason"]), ("cancelled", "Heavy rain"))
        # The views: the game ends in 2030, so it is upcoming, not past.
        await page.select_option("#v-view", "past")
        await page.click("#view-form button[type=submit]")
        await expect(page.locator("#schedule-none")).to_be_visible()
        await page.select_option("#v-view", "all")
        await page.click("#view-form button[type=submit]")
        await expect(rows).to_have_count(1)
        # A draft is deleted after a question.
        await page.fill("#g-title", "To delete")
        await page.fill("#g-starts", "2030-09-01T10:00")
        await page.fill("#g-ends", "2030-09-01T12:00")
        await page.click("#g-submit")
        await expect(rows).to_have_count(2)
        await page.locator("#schedule tbody tr", has_text="To delete").locator("button", has_text="Delete draft").click()
        await expect(page.locator("#status")).to_have_text("Draft deleted.")
        await expect(rows).to_have_count(1)
        self.assertIn("To delete", self.dialogs[-1])
        await self.check_page(page, 375)

    async def test_a_gm_edits_but_does_not_publish_or_cancel(self) -> None:
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/schedule"))
        await page.fill("#g-title", "GM's draft")
        await page.fill("#g-starts", "2030-07-06T10:00")
        await page.fill("#g-ends", "2030-07-06T14:00")
        await page.click("#g-submit")
        row = page.locator("#schedule tbody tr").first
        await expect(row).to_contain_text("GM's draft")
        await expect(row.locator("button", has_text="Edit")).to_have_count(1)
        await expect(row.locator("button", has_text="Delete draft")).to_have_count(1)
        await expect(row.locator("button", has_text="Publish")).to_have_count(0)
        # Published by someone else, the game offers the GM no cancel either (the API would refuse it).
        await self.fetch("UPDATE scheduled_games SET status = 'published'")
        await page.reload()
        await expect(page.locator("#schedule tbody tr").first).to_contain_text("published")
        await expect(page.locator("#schedule tbody tr").first.locator("button", has_text="Cancel game")).to_have_count(0)

    async def test_a_player_and_a_marshal_meet_the_apis_rules(self) -> None:
        game = await self.published_game()
        for role, with_totp in (("player", False), ("marshal", True)):
            with self.subTest(role=role):
                name, secret = await self.staff(role, with_totp=with_totp)
                page = await self.new_page(lang="en-GB")
                await self.login(page, name, secret, self.field_path("/schedule"))
                await expect(page.locator("#status")).to_contain_text("This part needs the admin or GM role")
                await expect(page.locator('#sections li[data-section="schedule"]')).to_be_hidden()
                await expect(page.locator("#g-title")).to_be_disabled()  # nothing to submit
                await page.goto(self.base + self.field_path(f"/schedule/{game}/registrations"))
                await expect(page.locator("#status")).to_contain_text("This part needs the admin or GM role")
                await expect(page.locator("#regs")).to_be_hidden()

    async def test_registrations_and_the_roster(self) -> None:
        await self.lisbon()
        game = await self.published_game()
        first = await self.register(game, "falcao", display_name=SHORT_EVIL, team_preference="red", federation_number="FPA-9",
                                    replicas=[{"type": "aeg", "class": "rifle", "make_model": "M4"}])
        await self.register(game, "ana", display_name="Ana")
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path(f"/schedule/{game}/registrations"))
        rows = page.locator("#regs tbody tr")
        await expect(rows).to_have_count(2)
        await expect(page.locator("#regs-heading")).to_have_text("Registrations: Domingo")
        await expect(page.locator("#counts")).to_contain_text("Active: 2")
        await expect(rows.nth(0).locator("th")).to_have_text(SHORT_EVIL)  # text, never markup
        self.assertEqual(await page.locator("#regs img").count(), 0)
        self.assertIsNone(await page.evaluate("() => window.pwned"))
        await expect(rows.nth(0)).to_contain_text("aeg, rifle, M4")
        await expect(rows.nth(0)).to_contain_text("issued")
        await expect(rows.nth(0)).to_contain_text("FPA-9")
        await expect(rows.nth(0)).to_contain_text("active")
        await self.check_page(page, 375)
        # Change a name and a team.
        await rows.nth(0).locator("button", has_text="Edit").click()
        await expect(page.locator("#reg-edit")).to_be_visible()
        await page.fill("#r-name", "Falcão")
        await page.select_option("#r-team", "blue")
        await page.click("#reg-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved.")
        await expect(rows.nth(0).locator("th")).to_have_text("Falcão")
        await expect(rows.nth(0)).to_contain_text("blue")
        stored = (await self.fetch("SELECT display_name, team_preference FROM game_registrations WHERE id = $1",
                                   uuid.UUID(first["id"])))[0]
        self.assertEqual((stored["display_name"], stored["team_preference"]), ("Falcão", "blue"))
        # A name the API refuses is shown in words.
        await rows.nth(1).locator("button", has_text="Edit").click()
        await page.fill("#r-name", "   ")  # the field stops at 32 characters; a blank name is the API's to refuse
        await page.click("#reg-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Invalid display name (1 to 32 characters).")
        await page.click("#r-cancel")
        # Withdraw one: it stays listed as withdrawn.
        await rows.nth(1).locator("button", has_text="Withdraw").click()
        await expect(page.locator("#status")).to_have_text("Registration withdrawn.")
        self.assertIn("Ana", self.dialogs[-1])
        await expect(rows.nth(1)).to_contain_text("withdrawn")
        await expect(rows.nth(1).locator("button")).to_have_text(["Restore"])  # nothing else is done to a withdrawn one
        await expect(page.locator("#counts")).to_contain_text("Withdrawn: 1")
        # The roster: only the active one, with what the controller gets, and a paper version.
        await page.locator("#roster-link a").click()
        await page.wait_for_url(f"**/schedule/{game}/roster")
        roster = page.locator("#roster tbody tr")
        await expect(roster).to_have_count(1)
        await expect(roster.first).to_contain_text("Falcão")
        await expect(roster.first).to_contain_text("blue")
        await expect(roster.first).to_contain_text("aeg, rifle, M4")
        await expect(roster.first).to_contain_text("FPA-9")
        await expect(roster.first).to_contain_text("☐")
        await expect(page.locator("#roster-meta")).to_contain_text("1 on the list")
        await expect(page.locator("#roster-meta")).to_contain_text("none yet")
        await expect(page.locator("#print")).to_be_enabled()
        await self.check_page(page, 375)
        await page.emulate_media(media="print")
        await expect(page.locator("header.staff-top")).to_be_hidden()
        await expect(page.locator("#print")).to_be_hidden()
        await expect(page.locator("footer")).to_be_hidden()
        await expect(page.locator("#roster")).to_be_visible()
        await expect(roster.first).to_contain_text("Falcão")
        colour = await page.evaluate("() => getComputedStyle(document.body).backgroundColor")
        self.assertEqual(colour, "rgb(255, 255, 255)")
        await page.emulate_media(media="screen")
        # The sync's own answer is the same list.
        pulled = await self.client.get(f"/api/v1/sync/roster?scheduled_game_id={game}",
                                       headers={"Authorization": f"Bearer {self.key}"})
        self.assertEqual([r["display_name"] for r in pulled.json()["registrations"]], ["Falcão"])

    async def test_a_started_game_offers_no_change(self) -> None:
        started = await self.published_game("Já começou", starts=datetime.timedelta(hours=-1))
        await self.fetch("INSERT INTO game_registrations (scheduled_game, field_id, player_id, display_name, status) "
                         "VALUES ($1, $2, 'p-aaaaaaaaaaaa', 'Rui', 'registered')", uuid.UUID(started), self.field_id)
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path(f"/schedule/{started}/registrations"))
        await expect(page.locator("#regs tbody tr")).to_have_count(1)
        await expect(page.locator("#locked")).to_be_visible()
        # Nothing to change, move, withdraw or restore, and it is not over: only the note of payment is offered.
        await expect(page.locator("#regs tbody button")).to_have_text(["Mark paid"])
        await expect(page.locator("#io-locked")).to_be_visible()  # a list is imported only before the start
        await expect(page.locator("#io-check")).to_be_disabled()
        await expect(page.locator("#io-run")).to_be_disabled()
        # A draft has no roster to print.
        draft = (await self.fetch("INSERT INTO scheduled_games (field_id, title, starts_at, ends_at, status) VALUES "
                                  "($1, 'Rascunho', now() + interval '3 days', now() + interval '3 days 2 hours', "
                                  "'draft') RETURNING id", self.field_id))[0]["id"]
        await page.goto(self.base + self.field_path(f"/schedule/{draft}/roster"))
        await expect(page.locator("#roster-draft")).to_be_visible()
        await expect(page.locator("#roster")).to_be_hidden()
        await self.check_page(page, 375)

    async def test_portuguese_pages_at_a_phones_width(self) -> None:
        game = await self.published_game()
        await self.register(game, "joana")
        name, secret = await self.staff("admin")
        page = await self.new_page()
        await self.login(page, name, secret, self.field_path("/schedule"))
        await expect(page.locator("#schedule tbody tr")).to_have_count(1)
        await expect(page.locator("#schedule tbody tr").first).to_contain_text("publicado")
        await self.check_page(page, 375)
        await page.goto(self.base + self.field_path(f"/schedule/{game}/registrations"))
        await expect(page.locator("#regs tbody tr")).to_have_count(1)
        await self.check_page(page, 375)
        await page.goto(self.base + self.field_path(f"/schedule/{game}/roster"))
        await expect(page.locator("#roster-meta")).to_contain_text("1 na lista")
        await self.check_page(page, 375)


    async def test_pay_move_restore_and_the_replicas(self) -> None:
        game = await self.published_game("Sábado")
        second = await self.published_game("Segundo", starts=datetime.timedelta(days=3))
        await self.register(game, "falcao", display_name="Falcão", team_preference="red", federation_number="FPA-9",
                            replicas=[{"type": "aeg", "class": "rifle", "make_model": "M4"}])
        await self.register(game, "ana", display_name="Ana")
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path(f"/schedule/{game}/registrations"))
        rows = page.locator("#regs tbody tr")
        await expect(rows).to_have_count(2)
        # Payment is a note: who and when, undone the same way.
        await expect(rows.nth(1)).to_contain_text("Not paid")
        await rows.nth(1).locator("button", has_text="Mark paid").click()
        await expect(page.locator("#status")).to_have_text("Registration marked as paid.")
        await expect(rows.nth(1)).to_contain_text("Paid (")
        await expect(rows.nth(1)).to_contain_text(f"marked by {name}")
        stored = (await self.fetch("SELECT paid_at, paid_by FROM game_registrations WHERE display_name = 'Ana'"))[0]
        self.assertIsNotNone(stored["paid_at"])
        await rows.nth(1).locator("button", has_text="Mark unpaid").click()
        await expect(page.locator("#status")).to_have_text("Paid mark removed.")
        await expect(rows.nth(1)).to_contain_text("Not paid")
        # The replicas: add one (type, class, make and model) and save.
        await rows.nth(1).locator("button", has_text="Edit").click()
        await expect(page.locator("#r-replicas li")).to_have_count(0)
        await expect(page.locator("#r-rep-none")).to_be_visible()
        await page.click("#r-rep-add")
        item = page.locator("#r-replicas li").first
        await item.locator("select").nth(0).select_option("dmr")
        await item.locator("select").nth(1).select_option("dmr")
        await item.locator("input").fill("VSR-10")
        await self.check_page(page, 375)
        await page.click("#reg-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved.")
        await expect(rows.nth(1)).to_contain_text("dmr, dmr, VSR-10")
        decl = await self.fetch("SELECT replica_type, replica_class, make_model FROM registration_replicas "
                                "JOIN game_registrations ON game_registrations.id = registration "
                                "WHERE display_name = 'Ana'")
        self.assertEqual([tuple(r) for r in decl], [("dmr", "dmr", "VSR-10")])
        # Saving the form as it was keeps a registration's replicas (their ids); then one is removed.
        sql = ("SELECT declaration_id FROM registration_replicas JOIN game_registrations "
               "ON game_registrations.id = registration WHERE display_name = 'Falcão'")
        before = (await self.fetch(sql))[0][0]
        await rows.nth(0).locator("button", has_text="Edit").click()
        await expect(page.locator("#r-replicas li")).to_have_count(1)
        await page.click("#reg-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved.")
        self.assertEqual((await self.fetch(sql))[0][0], before)
        await rows.nth(0).locator("button", has_text="Edit").click()
        await page.locator("#r-replicas li button").first.click()
        await page.click("#reg-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved.")
        # "Saved." is still there from the save above: wait for this save to reach the database.
        for _ in range(200):
            if await self.fetch(sql) == []:
                break
            await asyncio.sleep(0.025)
        self.assertEqual(await self.fetch(sql), [])
        # Move one to the other game: the ticket stays, the team and number are fitted to that game.
        await self.fetch("UPDATE scheduled_games SET teams = '[\"blue\"]', federation = 'off' WHERE id = $1",
                         uuid.UUID(second))
        ticket = (await self.fetch("SELECT ticket_hash FROM game_registrations WHERE display_name = 'Falcão'"))[0][0]
        await rows.nth(0).locator("button", has_text="Move to another game").click()
        await expect(page.locator("#reg-move")).to_be_visible()
        await expect(page.locator("#m-game option")).to_have_count(1)
        await expect(page.locator("#m-game option")).to_contain_text("Segundo")
        await expect(page.locator("#reg-move .hint").last).to_contain_text("the ticket belongs to the registration")
        await self.check_page(page, 375)
        await page.click("#m-go")
        await expect(page.locator("#status")).to_contain_text("Registration moved to “Segundo”.")
        await expect(page.locator("#status")).to_contain_text("The team asked for was dropped")
        await expect(page.locator("#status")).to_contain_text("The federation number was dropped")
        await expect(rows).to_have_count(1)
        moved = (await self.fetch("SELECT scheduled_game, ticket_hash, team_preference, federation_number "
                                  "FROM game_registrations WHERE display_name = 'Falcão'"))[0]
        self.assertEqual((str(moved["scheduled_game"]), moved["ticket_hash"], moved["team_preference"],
                          moved["federation_number"]), (second, ticket, None, None))
        # Withdraw the other, bring it back: it has no ticket (the player asks for one in the app).
        await rows.nth(0).locator("button", has_text="Withdraw").click()
        await expect(rows.nth(0)).to_contain_text("withdrawn")
        await rows.nth(0).locator("button", has_text="Restore").click()
        await expect(page.locator("#status")).to_contain_text("Registration restored.")
        await expect(rows.nth(0)).to_contain_text("active")
        # Without another game to move to, the form says so.
        await self.fetch("UPDATE scheduled_games SET status = 'cancelled' WHERE id = $1", uuid.UUID(second))
        await rows.nth(0).locator("button", has_text="Move to another game").click()
        await expect(page.locator("#m-none")).to_be_visible()
        await expect(page.locator("#m-go")).to_be_disabled()
        await page.click("#m-cancel")
        await expect(page.locator("#reg-move")).to_be_hidden()
        actions = [a["action"] for a in await self.fetch("SELECT action FROM audit_log WHERE action LIKE 'registration_%'")]
        for action in ("registration_move", "registration_restore", "registration_paid"):
            self.assertIn(action, actions)
        self.assertNotIn("Falcão", json.dumps([str(r["details"]) for r in await self.fetch("SELECT details FROM audit_log")]))

    async def test_a_no_show_after_the_game(self) -> None:
        over = await self.published_game("Ontem", starts=datetime.timedelta(hours=-6))
        for who, pid, state in (("Rui", "p-aaaaaaaaaaaa", "registered"), ("Ana", "p-bbbbbbbbbbbb", "checked_in")):
            await self.fetch("INSERT INTO game_registrations (scheduled_game, field_id, player_id, display_name, status) "
                             "VALUES ($1, $2, $3, $4, $5)", uuid.UUID(over), self.field_id, pid, who, state)
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path(f"/schedule/{over}/registrations"))
        rows = page.locator("#regs tbody tr")
        await expect(rows).to_have_count(2)
        # The controller's check-in is not marked here: only a registered player is offered a no-show.
        await expect(rows.nth(0).locator("button")).to_have_text(["No-show", "Mark paid"])
        await expect(rows.nth(1).locator("button")).to_have_text(["Mark paid"])
        await rows.nth(0).locator("button", has_text="No-show").click()
        self.assertIn("Rui", self.dialogs[-1])
        await expect(page.locator("#status")).to_have_text("Marked as a no-show.")
        await expect(rows.nth(0)).to_contain_text("no-show")
        await expect(page.locator("#counts")).to_contain_text("No-shows: 1")
        await rows.nth(0).locator("button", has_text="Undo no-show").click()
        await expect(page.locator("#status")).to_have_text("No-show mark removed.")
        await expect(rows.nth(0)).to_contain_text("active")
        # A no-show the controller reported is not undone here.
        await self.fetch("UPDATE game_registrations SET status = 'no_show', outcome_at = now() WHERE display_name = 'Rui'")
        await page.reload()
        await expect(rows.nth(0).locator("button")).to_have_text(["Mark paid"])
        await self.check_page(page, 375)

    async def test_the_export_and_the_import(self) -> None:
        game = await self.published_game()
        await self.register(game, "falcao", display_name="Falcão")
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path(f"/schedule/{game}/registrations"))
        await expect(page.locator("#io-export")).to_be_enabled()
        async with page.expect_download() as download:
            await page.click("#io-export")
        saved = await (await download.value).path()
        text = Path(saved).read_text(encoding="utf-8-sig")
        self.assertTrue(text.startswith("display_name,external_ref,"), text)
        self.assertIn("Falcão", text)
        await expect(page.locator("#status")).to_have_text("File exported.")
        self.assertEqual((await self.fetch("SELECT count(*) FROM audit_log WHERE action = 'registration_export'"))[0][0], 1)
        # The import: a check first (nothing is written), then the import, which needs the field's confirmation.
        folder = Path(tempfile.mkdtemp())
        csv = folder / "list.csv"
        csv.write_text("display_name,external_ref,team_preference\r\nRui,r-1,red\r\n,r-2,\r\nAna,r-3,green\r\n",
                       encoding="utf-8")
        await page.set_input_files("#io-file", str(csv))
        await page.fill("#io-source", "club")
        await expect(page.locator("#io-run")).to_be_disabled()
        await page.click("#io-check")
        await expect(page.locator("#status")).to_have_text("Check done: nothing was saved.")
        await expect(page.locator("#io-summary")).to_contain_text("3 rows: 1 new, 0 changed, 0 the same, 0 skipped, 2 refused.")
        issues = page.locator("#io-rows tbody tr")
        await expect(issues).to_have_count(2)
        await expect(issues.nth(0)).to_contain_text("Invalid display name")
        await expect(issues.nth(1)).to_contain_text("That team is not in this game.")
        self.assertEqual((await self.fetch("SELECT count(*) FROM game_registrations"))[0][0], 1)
        await self.check_page(page, 375)
        await page.check("#io-basis")
        await expect(page.locator("#io-run")).to_be_enabled()
        await page.click("#io-run")
        await expect(page.locator("#status")).to_have_text("Import done.")
        await expect(page.locator("#regs tbody tr")).to_have_count(2)
        stored = await self.fetch("SELECT display_name, source, user_id FROM game_registrations WHERE source = 'club'")
        self.assertEqual([tuple(r) for r in stored], [("Rui", "club", None)])
        imported = (await self.fetch("SELECT details FROM audit_log WHERE action = 'registration_import'"))[0][0]
        self.assertNotIn("Rui", str(imported))
        # A file the API refuses is shown in words.
        bad = folder / "bad.csv"
        bad.write_text("name\r\nRui\r\n", encoding="utf-8")
        await page.set_input_files("#io-file", str(bad))
        await page.click("#io-run")
        await expect(page.locator("#status")).to_have_text("The display_name column is missing.")
        await page.set_input_files("#io-file", [])
        await page.click("#io-check")
        await expect(page.locator("#status")).to_have_text("Choose a file first.")
        # The same page in Portuguese, at a phone's width.
        await page.goto(self.base + self.field_path(f"/schedule/{game}/registrations") + "?lang=pt")
        await expect(page.locator("#io-title")).to_have_text("Exportar e importar")
        await self.check_page(page, 375)

    async def test_the_apd_membership_and_its_verdict(self) -> None:
        """protocol/apd.md: with a field rule that checks it, the registrations page and the roster show the APD,
        the number, the expiry and the verdict; staff change them and the verdict follows."""
        await self.lisbon()
        await self.fetch("UPDATE fields SET country = 'PT'")
        await self.fetch("UPDATE fields SET apd_rule = $1::jsonb", json.dumps(
            {"accepted": ["apd-a", "x-norte"], "register": False, "checkin": True, "expiry": True,
             "custom": [{"id": "x-norte", "name": "Clube Norte, APD", "short_name": "Norte", "website": None}]}))
        game = await self.published_game()
        await self.register(game, "falcao", display_name="Falcão", federation_number="FPA-9", apd_id="apd-b",
                            membership_expires="2031-01-31")
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path(f"/schedule/{game}/registrations"))
        row = page.locator("#regs tbody tr").nth(0)
        await expect(row).to_contain_text("apd-b · FPA-9 · expires 2031-01-31 — APD not accepted")
        await row.locator("button", has_text="Edit").click()
        await expect(page.locator("#r-apd option")).to_have_text(["APD unknown", "ALA", "APACORP", "APAP", "Norte", "apd-b"])
        await page.select_option("#r-apd", "x-norte")
        await page.click("#reg-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved.")
        await expect(row).to_contain_text("Norte · FPA-9 · expires 2031-01-31 — valid")
        await row.locator("button", has_text="Edit").click()
        await page.fill("#r-expires", "2020-01-01")
        await page.click("#reg-form button[type=submit]")
        await expect(row).to_contain_text("expired")
        await self.check_page(page, 375)
        await page.goto(self.base + self.field_path(f"/schedule/{game}/roster"))
        await expect(page.locator("#roster tbody tr").first).to_contain_text("Norte · FPA-9 · expires 2020-01-01 — expired")

    async def test_a_field_outside_portugal_says_association_membership(self) -> None:
        """Decisions MEM-3 and MEM-4: the registrations page of a Spanish field names the association, not the APD,
        and offers only its own entries; the same field in Portugal's words is the test above."""
        await self.fetch("UPDATE fields SET country = 'ES'")
        await self.fetch("UPDATE fields SET apd_rule = $1::jsonb", json.dumps(
            {"accepted": ["x-norte"], "register": False, "checkin": True, "expiry": False,
             "custom": [{"id": "x-norte", "name": "Club Norte", "short_name": "Norte", "website": None}]}))
        game = await self.published_game()
        await self.register(game, "falcao", display_name="Falcão", federation_number="ES-9", apd_id="apd-b")
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path(f"/schedule/{game}/registrations"))
        await expect(page.locator("#th-fed")).to_have_text("Membership (association)")
        row = page.locator("#regs tbody tr").nth(0)
        await expect(row).to_contain_text("apd-b · ES-9 — association not accepted")
        await row.locator("button", has_text="Edit").click()
        await expect(page.locator("label[for=r-apd]")).to_have_text("Member's association")
        await expect(page.locator("#r-apd option")).to_have_text(["Association unknown", "Norte", "apd-b"])
        await self.check_page(page, 375)
        await page.goto(self.base + self.field_path(f"/schedule/{game}/registrations") + "?lang=pt")
        await expect(page.locator("#th-fed")).to_have_text("Filiação (associação)")

    async def test_the_roster_says_when_a_controller_last_pulled_it(self) -> None:
        game = await self.published_game()
        await self.register(game, "falcao", display_name="Falcão")
        await self.fetch("UPDATE field_api_keys SET label = 'Pi do campo'")
        name, secret = await self.staff("gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path(f"/schedule/{game}/roster"))
        await expect(page.locator("#roster-pull")).to_have_text("No controller has pulled this list so far.")
        pulled = await self.client.get(f"/api/v1/sync/roster?scheduled_game_id={game}",
                                       headers={"Authorization": f"Bearer {self.key}",
                                                "User-Agent": "atalaia-controller/1.0"})
        self.assertEqual(pulled.status_code, 200)
        await page.reload()
        await expect(page.locator("#roster-pull")).to_contain_text("A controller last pulled the list:")
        await expect(page.locator("#roster-pull")).to_contain_text("Key: Pi do campo (")
        await expect(page.locator("#roster-pull")).to_contain_text("Program: atalaia-controller/1.0.")
        await self.check_page(page, 375)


class SettingsTests(BrowserCase):
    """FS-*: a field's settings page is its API (PATCH /api/v1/fields/{field}); the membership words follow the country."""

    async def row(self) -> Any:
        return (await self.fetch("SELECT country, apd_rule, chrono_sharing_enabled, public_page, description, max_replicas "
                                 "FROM fields WHERE id = $1", self.field_id))[0]

    async def test_the_country_changes_the_words_and_the_membership_rule_is_edited(self) -> None:
        await self.fetch("UPDATE fields SET country = 'PT'")
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/settings"))
        await expect(page.locator("#country-form fieldset")).to_be_enabled()
        # Portugal: the APD words and the three shipped entries.
        await expect(page.locator("#fs-member-title")).to_have_text("APD membership")
        await expect(page.locator("#m-any-label")).to_have_text("Any APD")
        await expect(page.locator("#m-entries li")).to_have_count(3)
        await expect(page.locator("#m-offered")).to_contain_text("PT")
        # A new country (typed in lower case): the words and the list change at once, and the API has it.
        await page.fill("#f-country", "es")
        await page.click("#country-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved. The controllers get the change at once.")
        await expect(page.locator("#fs-member-title")).to_have_text("Association membership")
        await expect(page.locator("#m-any-label")).to_have_text("Any association")
        await expect(page.locator("#m-only-label")).to_have_text("Only the ticked associations")
        await expect(page.locator("#m-entries li")).to_have_count(0)
        self.assertEqual((await self.row())[0], "ES")
        await page.fill("#f-country", "")  # no country
        await page.click("#country-form button[type=submit]")
        await expect(page.locator("#m-offered")).to_have_text("With no country set, only the field's own entries are offered.")
        self.assertIsNone((await self.row())[0])
        await page.fill("#f-country", "PT")
        await page.click("#country-form button[type=submit]")
        await expect(page.locator("#fs-member-title")).to_have_text("APD membership")  # and back again
        await expect(page.locator("#m-entries li")).to_have_count(3)
        # The membership rule: the field's own entry, the accepted list, the switches.
        await page.fill("#c-id", "x-norte")
        await page.fill("#c-name", "Clube Norte")
        await page.fill("#c-short", "Norte")
        await page.click("#custom-form button[type=submit]")
        await expect(page.locator("#m-entries li")).to_have_count(4)
        await expect(page.locator("#m-custom li")).to_contain_text("x-norte")
        await page.check("#m-only")
        await page.check("#m-e-3")  # the field's own entry
        await page.check("#m-e-0")
        await page.check("#m-register")
        await page.check("#m-expiry")
        await page.click("#member-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved. The controllers get the change at once.")
        rule = json.loads((await self.row())[1]) if isinstance((await self.row())[1], str) else (await self.row())[1]
        self.assertEqual(rule["register"], True)
        self.assertEqual(rule["checkin"], False)
        self.assertEqual(rule["expiry"], True)
        self.assertEqual(len(rule["accepted"]), 2)
        self.assertIn("x-norte", rule["accepted"])
        self.assertEqual([e["id"] for e in rule["custom"]], ["x-norte"])
        # Removing the own entry and going back to any.
        await page.locator("#m-custom li button").click()
        await page.check("#m-any")
        await page.click("#member-form button[type=submit]")
        await expect(page.locator("#status")).to_contain_text("Saved.")
        await page.reload()
        await expect(page.locator("#m-any")).to_be_checked()
        await expect(page.locator("#m-register")).to_be_checked()
        await expect(page.locator("#m-custom-none")).to_be_visible()
        await self.check_page(page, 375)

    async def test_the_other_sections_and_a_refusal_in_words(self) -> None:
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/settings"))
        await expect(page.locator("#public-form fieldset")).to_be_enabled()
        await page.check("#f-public")
        await page.fill("#f-description", "Campo de bosque.\nChegada às 9h.")
        await page.click("#public-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved.")
        await page.fill("#f-replicas", "3")
        await page.click("#checkin-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved. The controllers get the change at once.")
        await page.check("#f-chrono")
        await page.click("#chrono-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved.")
        row = await self.row()
        self.assertEqual((row[2], row[3], row[4], row[5]), (True, True, "Campo de bosque.\nChegada às 9h.", 3))
        # The data retention (RET-1, RET-2): 365 days each at first; both are saved and a refusal is in words.
        await expect(page.locator("#f-chrono-days")).to_have_value("365")
        await expect(page.locator("#f-game-days")).to_have_value("365")
        await page.fill("#f-chrono-days", "180")
        await page.fill("#f-game-days", "90")
        await page.click("#retention-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Saved. The controllers get the change at once.")
        days = (await self.fetch("SELECT default_retention_days, game_retention_days FROM fields WHERE id = $1",
                                 self.field_id))[0]
        self.assertEqual((days[0], days[1]), (180, 90))
        await page.fill("#f-game-days", "7")
        await page.click("#retention-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text(
            "Invalid game data retention (a whole number of days, from 30 to 3653).")
        self.assertEqual((await self.fetch("SELECT game_retention_days FROM fields WHERE id = $1",
                                           self.field_id))[0][0], 90)
        # Refusals, each in words: a country that is not two letters, a one-line text with a tab, a rule
        # that accepts only the ticked ones with none ticked, a number the API refuses.
        await page.fill("#f-country", "PORTUGAL")
        await page.click("#country-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Invalid country: use a two-letter ISO 3166-1 code, for example PT.")
        await page.fill("#f-fedlabel", "a\tb")
        await page.click("#public-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Invalid label: one line, at most 16 characters.")
        await page.fill("#f-fedlabel", "")
        await page.fill("#f-address", "Rua um\u0007")
        await page.click("#public-form button[type=submit]")
        await expect(page.locator("#status")).to_contain_text("Invalid address")
        await page.fill("#f-address", "")
        await page.check("#m-only")
        await page.click("#member-form button[type=submit]")
        await expect(page.locator("#status")).to_contain_text("Invalid")
        await expect(page.locator("#status")).to_contain_text("rule")
        await page.fill("#f-replicas", "999")
        await page.click("#checkin-form button[type=submit]")
        await expect(page.locator("#status")).to_contain_text("Invalid most-replicas value")
        self.assertEqual((await self.row())[5], 3)  # nothing of the refused ones was kept
        # A gm sees the page's link no more and the API refuses the page's writes.
        gm, gm_secret = await self.staff("gm")
        other = await self.new_page(lang="en-GB")
        await self.login(other, gm, gm_secret, self.field_path("/settings"))
        await expect(other.locator('#sections li[data-section="settings"]')).to_be_hidden()
        await other.click("#chrono-form button[type=submit]")
        await expect(other.locator("#status")).to_contain_text("This part needs")

    async def test_german_at_a_phones_width(self) -> None:
        await self.fetch("UPDATE fields SET country = 'PT'")
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="de-DE", viewport={"width": 375, "height": 740})
        await self.login(page, name, secret, self.field_path("/settings") + "?lang=de")
        await expect(page.locator("h1")).to_have_text("Einstellungen des Spielfelds")
        await expect(page.locator("#fs-member-title")).to_have_text("APD-Mitgliedschaft")
        await page.fill("#f-country", "AT")
        await page.click("#country-form button[type=submit]")
        await expect(page.locator("#fs-member-title")).to_have_text("Verbandsmitgliedschaft")
        await expect(page.locator("#m-only-label")).to_have_text("Nur die angehakten Verbände")
        await page.fill("#f-country", "Österreich")
        await page.click("#country-form button[type=submit]")
        await expect(page.locator("#status")).to_have_text("Ungültiges Land: Verwende einen zweistelligen ISO-3166-1-Code, zum Beispiel PT.")
        await self.check_page(page, 375)


class Fu8PageTests(BrowserCase):
    """The pages FU9 added for APIs that had none (decisions FU9-1 to FU9-7): each is its API."""

    async def test_sync_keys_are_labelled_shown_once_and_revoked(self) -> None:
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/sync-keys"))
        rows = page.locator("#keys-table tbody tr")
        await expect(rows).to_have_count(1)  # the key the test made
        await page.fill("#k-label", EVIL)
        await page.click("#key-form button[type=submit]")
        await expect(page.locator("#key-issued")).to_be_visible()
        key = await page.locator("#key-value").text_content() or ""
        self.assertTrue(key.startswith("atk_") or len(key) >= 20, key)
        await expect(rows).to_have_count(2)
        await expect(rows.nth(1)).to_contain_text(EVIL)  # text, never markup
        self.assertIsNone(await page.evaluate("() => window.pwned"))
        self.assertNotIn(key, await rows.nth(1).text_content() or "")  # only the fingerprint afterwards
        await page.fill("#k-label", "third")  # the API allows two live keys
        await page.click("#key-form button[type=submit]")
        await expect(page.locator("#status")).not_to_be_empty()
        await expect(rows).to_have_count(2)
        await rows.nth(1).get_by_role("button").click()  # confirmation accepted
        await expect(page.locator("#status")).to_contain_text("revoked")
        await self.check_page(page)

    async def test_roles_are_granted_and_revoked(self) -> None:
        name, secret = await self.staff("admin")
        other, _ = await self.staff(with_totp=False)
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/roles"))
        await expect(page.locator("#roles-table tbody tr")).to_have_count(1)
        await page.fill("#g-user", other)
        await page.select_option("#g-role", "player")
        await page.click("#grant-form button[type=submit]")
        await expect(page.locator("#roles-table tbody tr")).to_have_count(2)
        self.assertEqual(len(await self.fetch("SELECT 1 FROM user_field_roles WHERE role_id = $1", ROLE["player"])), 1)
        await page.locator("#roles-table tbody tr", has_text=other).get_by_role("button").click()
        await expect(page.locator("#roles-table tbody tr")).to_have_count(1)
        self.assertEqual(await self.fetch("SELECT 1 FROM user_field_roles WHERE role_id = $1", ROLE["player"]), [])
        await self.check_page(page)

    async def test_the_data_page_exports_the_field_and_shows_its_limits(self) -> None:
        """PKC-1: the export is the API's (a ZIP read with the bearer token, offered from a blob: address, its
        SHA-256 shown); a single-field server says it has no limits; a refusal is shown in words."""
        await self.make_game(GAME, "Domingo")
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path("/data"))
        await expect(page.locator("#export-run")).to_be_enabled()
        await expect(page.locator("#quotas-none")).to_be_visible()
        await expect(page.locator("#quotas-table")).to_be_hidden()
        async with page.expect_download() as download:
            await page.click("#export-run")
            await expect(page.locator("#export-done")).to_be_visible()
            await page.click("#export-download")
        saved = Path(await (await download.value).path())
        with zipfile.ZipFile(saved) as zf:
            self.assertIn("manifest.json", zf.namelist())
        sha = (await page.locator("#export-sha").text_content() or "").strip()
        self.assertRegex(sha, r"^[0-9a-f]{64}$")
        import hashlib

        self.assertEqual(sha, hashlib.sha256(saved.read_bytes()).hexdigest())
        logged = (await self.fetch("SELECT details FROM audit_log WHERE action = 'field_export'"))[0][0]
        self.assertIn(sha, str(logged))
        # A second one at once is refused by the API's rate rule, in words.
        await page.click("#export-run")
        await expect(page.locator("#status")).to_contain_text("Too many requests")
        await self.check_page(page, 375)
        await page.goto(self.base + self.field_path("/data") + "?lang=pt")
        await expect(page.locator("h1")).to_have_text("Dados e limites do campo")
        await self.check_page(page, 375)
        # A gm has no data page: the API's refusal.
        gm, gm_secret = await self.staff("gm")
        other = await self.new_page(lang="en-GB")
        await self.login(other, gm, gm_secret, self.field_path("/data"))
        await expect(other.locator("#status")).to_contain_text("This part needs")

    async def test_a_game_page_under_another_fields_address_shows_nothing(self) -> None:
        """PKC-4 (FU2-12): access is checked per game by the API, which does not look at the address; the page does."""
        game = await self.make_game(GAME, "Domingo secreto", state="ended", ended_at=1792003700.0)
        other = (await self.fetch("INSERT INTO fields (name, slug) VALUES ('Campo Sul', 'campo-sul') RETURNING id"))[0][0]
        name, secret = await self.staff("admin", "gm")
        page = await self.new_page(lang="en-GB")
        await self.login(page, name, secret, self.field_path(f"/games/{game}"))
        await expect(page.locator("#game-name")).to_have_text("Domingo secreto")
        await page.goto(f"{self.base}/staff/fields/{other}/games/{game}")
        await expect(page.locator("#status")).to_have_text("Not found.")
        await expect(page.locator("main section").first).to_be_hidden()
        self.assertNotIn("Domingo secreto", await page.locator("main").inner_text())
        await self.check_page(page, 375)

    async def test_a_club_page_lists_the_fields_where_it_plays(self) -> None:
        """SV8-1: a member sees every field with a team of the club (a public one as a link to its page), in words
        and at a phone's width; a club with no team says so."""
        name, _ = await self.staff("player", with_totp=False)
        user = (await self.fetch("SELECT id FROM users WHERE username = $1", name))[0][0]
        club = (await self.fetch("INSERT INTO clubs (name, short_name, slug) VALUES ('Lobos do Pinhal', 'Lobos', "
                                 "'lobos') RETURNING id"))[0][0]
        empty = (await self.fetch("INSERT INTO clubs (name, short_name, slug) VALUES ('Corvos', 'Corvos', 'corvos') "
                                  "RETURNING id"))[0][0]
        for c in (club, empty):
            await self.fetch("INSERT INTO club_members (club_id, user_id, role, accepted_at) "
                             "VALUES ($1, $2, 'member', now())", c, user)
        public = (await self.fetch("INSERT INTO fields (name, slug, public_page) VALUES ('Campo Aberto', "
                                   "'campo-aberto', true) RETURNING id"))[0][0]
        for field in (self.field_id, public, public):  # the default field has no public page; two teams, one entry
            await self.fetch("INSERT INTO field_teams (field_id, club_id) VALUES ($1, $2)", field, club)
        page = await self.new_page(lang="en")
        await self.login(page, name, None, f"/staff/clubs/{club}")
        items = page.locator("#club-fields-list li")
        await expect(items).to_have_text(["Campo Aberto (public page)", "Campo Norte (no public page)"])
        await expect(items.locator("a")).to_have_count(1)
        self.assertEqual(await items.locator("a").get_attribute("href"), "/f/campo-aberto/")
        await page.goto(self.base + f"/staff/clubs/{club}?lang=en")  # a language asked for in the address is kept
        await expect(items.locator("a")).to_have_attribute("href", "/f/campo-aberto/?lang=en")
        await expect(page.locator("#club-fields-none")).to_be_hidden()
        await self.check_page(page)
        await page.goto(self.base + f"/staff/clubs/{empty}")
        await expect(page.locator("#club-fields-none")).to_have_text("It does not play at any field yet.")
        await expect(page.locator("#club-fields-list li")).to_have_count(0)
        await self.check_page(page)

    async def test_every_new_page_loads_for_its_role_at_a_phones_width(self) -> None:
        name, secret = await self.staff("admin")
        page = await self.new_page(lang="de-DE")
        await self.login(page, name, secret, self.field_path("/branding"))
        for path in ("/branding", "/platforms", "/roles", "/sync-keys", "/data"):
            await page.goto(self.base + self.field_path(path))
            await expect(page.locator("h1")).to_be_visible()
            await expect(page.locator("#status")).to_be_empty()
            await self.check_page(page)
        await page.goto(self.base + "/staff/clubs")
        await expect(page.locator("h1")).to_be_visible()
        await self.check_page(page)
        await page.goto(self.base + "/staff/firmware")
        await expect(page.locator("#fw-latest-none, #fw-latest li").first).to_be_visible()
        await self.check_page(page)
        # Server administration is the server administrator's: this account meets the API's refusal.
        await page.goto(self.base + "/staff/admin")
        await expect(page.locator("#status")).not_to_be_empty()
        # A player meets the API's refusal on the key page.
        player, _ = await self.staff("player", with_totp=False)
        other = await self.new_page()
        await self.login(other, player, None, self.field_path("/sync-keys"))
        await expect(other.locator("#status")).to_contain_text("neste campo")


class RoleTests(BrowserCase):
    async def test_a_player_without_totp_meets_the_apis_rules(self) -> None:
        name, _ = await self.staff("player", with_totp=False)
        page = await self.new_page()
        await self.login(page, name, None)
        item = page.locator("#fields > li")
        await expect(item).to_have_count(1)
        await expect(item).to_contain_text("Campo Norte")
        await expect(item).to_contain_text("jogador/a")
        await expect(item.locator(".links a")).to_have_text(["Histórico"])
        await self.check_page(page)
        for path, roles in (("/scenarios", "administração ou GM"), ("/remote-gm", "GM"),
                            ("/devices", "administração ou GM")):
            with self.subTest(path=path):
                await page.goto(self.base + self.field_path(path))
                await expect(page.locator("#status")).to_contain_text(f"precisa da função {roles} neste campo")
                await expect(page.locator('#sections li[data-section="scenarios"]')).to_be_hidden()
        # The pages' data is the API's: the history is open to any role on the field.
        await page.goto(self.base + self.field_path("/history"))
        await expect(page.locator("#games-none")).to_be_visible()
        await expect(page.locator("#settings")).to_be_hidden()

    async def test_a_staff_page_without_a_session_goes_to_the_login(self) -> None:
        page = await self.new_page()
        target = self.field_path(f"/games/{uuid.uuid4()}")
        await page.goto(self.base + target + "?lang=en")
        await page.wait_for_url("**/staff/login?next=*")
        await expect(page.locator("h1")).to_have_text("Log in")
        # A next that is not a staff page is ignored.
        name, secret = await self.staff("gm")
        await page.goto(self.base + "/staff/login?next=//evil.example/")
        await page.fill("#username", name)
        await page.fill("#password", PASSWORD)
        await page.click("#login-form button[type=submit]")
        await page.fill("#code", self.code(secret or ""))
        await page.click("#totp-form button[type=submit]")
        await page.wait_for_url(f"{self.base}/staff/")
        await expect(page.locator("#fields > li")).to_have_count(1)


if __name__ == "__main__":
    unittest.main()
