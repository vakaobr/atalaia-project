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
        await expect(rows.nth(1).locator("button")).to_have_count(0)
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
        await expect(page.locator("#regs tbody button")).to_have_count(0)
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
