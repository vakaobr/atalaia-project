# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The GM console and the scoreboard in a real browser (headless Chromium, Playwright).

    python tools/docker_console.py          (or controller/console/tests/run.sh in its image)

Each test starts the real field controller (main.build(), served by uvicorn
on a free port) with the C host modem as its radio, so everything the page
shows comes from the real engine over REST and the WebSocket. Box traffic
is put on the modem's 'air' as a box would send it (real AES-CCM): the
score and the feed must change on the page without a reload.

Every page is checked for JavaScript errors and console errors.
With ATALAIA_REQUIRE_BROWSER=1 (run.sh, CI) a missing Playwright, Chromium
or zbarimg is an error, never a skip.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTROLLER = HERE.parents[1]
sys.path.insert(0, str(CONTROLLER / "tests"))

from support import (BOX_HOST, CORE, MESSAGE_TYPES, MODEM_HOST, AirHub, BoxHost, HostModem,  # noqa: E402
                     config, free_port, node_packet, packet_decrypt, wait_for)

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from atalaia_controller import checkin_poster  # noqa: E402
from atalaia_controller.main import build  # noqa: E402
from atalaia_sim import codec, join, lobby  # noqa: E402
from atalaia_sim import field_frame as ff  # noqa: E402
from atalaia_sim.packet import cmd_decode, hello_encode, state_encode  # noqa: E402

REQUIRE = os.environ.get("ATALAIA_REQUIRE_BROWSER") == "1"
try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    if REQUIRE:
        raise
    sync_playwright = None
ZBARIMG = shutil.which("zbarimg")
if REQUIRE and not ZBARIMG:
    raise RuntimeError("ATALAIA_REQUIRE_BROWSER=1 but zbarimg (zbar-tools) is not installed")


def read_qr(image: str) -> subprocess.CompletedProcess:
    """The QR codes zbarimg finds in a screenshot, one per line (--raw).

    Only the QR decoder runs: with zbarimg's default every 1D decoder also
    looks at the image, and once a second symbol ("C3$B", Code 39 characters
    only: most likely a false 1D read in the QR code's modules) was printed on
    its own line after the QR text, which made the exact comparison fail
    (decision FU1-8). The text must still be
    exactly the expected one, one symbol, nothing around it."""
    out = subprocess.run([ZBARIMG, "-Sdisable", "-Sqrcode.enable", "--raw", "-q", image],
                         capture_output=True, text=True, timeout=30)
    # --raw ends each symbol with a newline; nothing else is taken away.
    out.stdout = out.stdout.removesuffix("\n")
    return out

GM = "gm-secret"
READ = "read-secret"
JOIN_KEY = bytes(range(32))
DOMINATION = "org.atalaia.domination"
ICON = CONTROLLER / "console" / "src" / "icons" / "icon-512.png"
BOX = 7


class Field:
    """A running controller (uvicorn, real port) with the C host modem."""

    def __init__(self, *modem_args: str, hub: "AirHub | None" = None, cfg: "dict | None" = None) -> None:
        self.host = HostModem(0, *modem_args, hub=hub)
        if hub is not None:  # host boxes share the air (plan phase 8's scenario test)
            hub.add(self.host.air_port)
        self.tmp = tempfile.TemporaryDirectory()
        self.port = free_port()
        # The address the boxes and the poster are given: in a container only configured ones (OT-10).
        cfg = {"tls_names": ["10.42.0.1"], **(cfg or {})}
        cfg = config(self.tmp.name, port=self.host.url, api_port=self.port, host="127.0.0.1",
                     join_key=JOIN_KEY.hex(), scan_dwell_s=1.1, **(cfg or {}))
        self.bundle = build(cfg, core=CORE, load_core_lib=False)
        self.server = uvicorn.Server(uvicorn.Config(self.bundle.app, host="127.0.0.1", port=self.port,
                                                    log_level="error", lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        if not wait_for(lambda: self.server.started, 10) or not self.bundle.modem.wait_up(10):
            raise RuntimeError("the controller did not start")
        self.base = f"http://127.0.0.1:{self.port}"
        self.http = httpx.Client(base_url=self.base, headers={"Authorization": f"Bearer {GM}"}, timeout=10)
        self.box_seq = 0

    def close(self) -> None:
        self.http.close()
        self.server.should_exit = True
        self.thread.join(10)
        self.bundle.store.close()
        self.host.close()
        self.tmp.cleanup()

    def create_game(self, name: str = "Domingo", start: bool = False, **spec) -> dict:
        r = self.http.post("/api/v1/games", json={"name": name, "mode_id": DOMINATION,
                                                  "teams": ["red", "blue"], **spec})
        assert r.status_code == 201, r.text
        game = r.json()
        if start:
            assert self.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True}).status_code == 200
        return game

    def box(self, msg_type: str, payload: bytes, ack: bool = False) -> None:
        """A packet from box 7 (epoch 1) heard by the modem."""
        game = self.bundle.controller.game
        key = self.bundle.controller.game_key(game["id"])
        self.host.hear(node_packet(key, game["id"], BOX, self.box_seq, 1, msg_type, payload, ack=ack))
        self.box_seq += 1

    def box_hello(self, fw: str = "0.3.0", device: "bytes | None" = None) -> None:
        fields = {"node_name": "box-7", "platform": 1, "fw_version": fw, "core_version": "0.2.0", "tier": 0,
                  "capabilities": [0, 2], "transports": 1, "battery_pct": 87, "epoch": 1}
        if device is not None:
            fields["device_id"] = device  # HELLO key 10 (protocol/field-frames.md)
        self.box("HELLO", hello_encode(fields))

    def box_state(self, red: int, blue: int = 0, owner: int = 1, battery: int = 86) -> None:
        counters = {1: red}
        if blue:
            counters[2] = blue
        self.box("STATE", state_encode({"owner_team": owner, "phase": 1, "game_time_ms": 5000,
                                        "counters": counters, "battery_pct": battery, "epoch": 1}))

    def box_capture(self, team_id: int = 1, team: str = "red") -> None:
        ev = codec.encode_event({"node": BOX, "seq": 1, "t": 4000, "type": "zone.captured",
                                 "team": team_id, "data": {"team": team}})
        self.box("EVENT", ev, ack=True)


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
@unittest.skipUnless(MODEM_HOST, "host modem not built")
class ConsoleBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.field = Field()
        self.contexts = []
        self.errors: list[str] = []
        self.ignore_errors = False

    def tearDown(self):
        for ctx in self.contexts:
            ctx.close()
        self.field.close()
        if not self.ignore_errors:
            self.assertEqual(self.errors, [], "JavaScript or console errors on the page")

    # --- helpers --------------------------------------------------------------

    def page(self, path: str = "/console/", width: int = 1280, height: int = 900):
        ctx = self.browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=2)
        self.contexts.append(ctx)
        page = ctx.new_page()
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: self.errors.append(f"console: {m.text}") if m.type == "error" else None)
        page.on("response", lambda r: self.errors.append(f"HTTP {r.status} {r.request.method} {r.url}")
                if r.status >= 400 else None)
        page.goto(self.field.base + path)
        return page

    def console(self, token: str = GM, **kw):
        page = self.page(**kw)
        page.get_by_test_id("token").fill(token)
        page.get_by_test_id("login").click()
        expect(page.get_by_test_id("tab-game")).to_be_visible()
        return page

    def no_horizontal_scroll(self, page) -> None:
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        self.assertLessEqual(width[0], width[1], "the page scrolls sideways")

    # --- tests ----------------------------------------------------------------

    def test_gm_creates_and_runs_a_game_with_live_updates(self):
        page = self.console()
        expect(page.get_by_test_id("tab-game")).to_have_text("Jogo")  # European Portuguese by default
        page.get_by_test_id("game-name").fill("Domingo de manhã")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        page.locator("#game-tick_s").fill("5")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual((game["name"], game["mode_id"], game["params"]["tick_s"]),
                         ("Domingo de manhã", DOMINATION, 5))

        page.get_by_test_id("game-start").click()
        page.get_by_test_id("game-start-yes").click()
        expect(page.get_by_test_id("game-state")).to_have_text("a decorrer")
        self.assertEqual(self.field.bundle.controller.game["state"], "running")
        page.evaluate("window.__sameDocument = 42")

        # A box joins the air: HELLO, then a capture and its score counters.
        expect(page.get_by_test_id("score-red")).to_have_text("0")
        self.field.box_hello()
        self.field.box_capture()
        self.field.box_state(red=30)
        expect(page.get_by_test_id("score-red")).to_have_text("30")
        self.field.box_state(red=45, blue=5)
        expect(page.get_by_test_id("score-red")).to_have_text("45")
        expect(page.get_by_test_id("score-blue")).to_have_text("5")

        page.get_by_test_id("tab-feed").click()
        expect(page.locator('[data-testid=feed] [data-type="zone.captured"]')).to_have_count(1)
        expect(page.locator('[data-testid=feed] [data-type="game.start"]')).to_have_count(1)
        page.get_by_test_id("tab-nodes").click()
        row = page.locator(f'[data-testid=node-list] tr[data-node="{BOX}"]')
        expect(row).to_contain_text("box-7")
        expect(row).to_contain_text("86%")
        self.assertEqual(page.evaluate("window.__sameDocument"), 42, "the page reloaded")

        # Node health (decision FU1-5): a low battery is marked; node.offline flags the box at once,
        # with its real last-heard time (the controller's threshold made short for the test).
        self.field.box_state(red=45, blue=5, battery=12)
        expect(page.get_by_test_id(f"node-battery-{BOX}")).to_have_text("12% fraca")
        expect(page.get_by_test_id(f"node-seen-{BOX}")).not_to_contain_text("sem notícias")
        ctrl = self.field.bundle.controller
        with ctrl._lock:
            ctrl.fc.node_offline_ms = ctrl.fc.link_gap_ms = 1500
        expect(page.get_by_test_id(f"node-seen-{BOX}")).to_contain_text("sem notícias", timeout=10_000)
        self.assertEqual(ctrl.fc.nodes[BOX].link, "offline")
        self.field.box_state(red=45, blue=5, battery=12)
        expect(page.get_by_test_id(f"node-seen-{BOX}")).not_to_contain_text("sem notícias", timeout=10_000)
        with ctrl._lock:
            ctrl.fc.node_offline_ms, ctrl.fc.link_gap_ms = 120_000, 60_000

        # One join used on two boxes (decision BN-18): HELLOs from two device ids on node 7.
        expect(page.get_by_test_id(f"node-conflict-{BOX}")).to_have_count(0)
        self.field.box_hello(device=bytes(range(8)))
        self.field.box_hello(device=bytes(range(8, 16)))
        expect(page.get_by_test_id(f"node-conflict-{BOX}")).to_contain_text(f"Duas caixas partilham o n.º {BOX}")

        # A GM score adjustment and a pause, through the page.
        page.get_by_test_id("tab-game").click()
        page.locator("[data-testid=adjust] select").select_option("blue")
        page.locator("[data-testid=adjust] input[type=number]").fill("10")
        page.locator("[data-testid=adjust] button[type=submit]").click()
        expect(page.get_by_test_id("score-blue")).to_have_text("15")
        page.get_by_test_id("game-pause").click()
        page.get_by_test_id("game-pause-yes").click()
        expect(page.get_by_test_id("game-state")).to_have_text("em pausa")
        self.assertEqual(self.field.bundle.controller.game["state"], "paused")

    def test_boxes_for_the_next_game_and_the_start_guard(self):
        """Decisions RJ-1 and RJ-5 in the console: after a game, the next one's dialog lists the free
        boxes heard over the radio with the last game's ticked; the invite goes out sealed through the
        modem; the box's answer and its HELLO show as they come; until then Start says what is missing."""
        device = bytes.fromhex("5a17c0de0b0e1234")
        key = ff.field_key(JOIN_KEY)
        first = self.field.create_game("Sábado", assignments={str(BOX): "zone"})
        self.field.box_hello(device=device)
        self.assertTrue(wait_for(lambda: self.field.bundle.controller.start_check()["ok"], 5))
        self.assertEqual(self.field.http.post(f"/api/v1/games/{first['id']}/start").status_code, 200)
        self.assertEqual(self.field.http.post(f"/api/v1/games/{first['id']}/end", json={}).status_code, 200)
        # The box, free again, announces itself (the simulator's model of main/box_lobby.c).
        box = lobby.IdleBox(JOIN_KEY, "Zona Norte", device_id=device, rng=random.Random(2))
        box.last_game, box.last_role = first["id"], "zone"
        self.field.host.hear(ff.encode(key, box._announce(), box.nonces.next()))
        reinvite = self.field.bundle.controller.reinvite
        self.assertTrue(wait_for(lambda: device.hex() in reinvite.inviter.boxes, 5))

        page = self.console()
        page.get_by_test_id("game-name").fill("Domingo")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        page.get_by_test_id("game-create").click()
        dialog = page.get_by_test_id("invite-dialog")
        expect(dialog).to_be_visible()
        expect(page.get_by_test_id("invite-previous")).to_contain_text("Sábado")
        row = page.get_by_test_id(f"invite-row-{device.hex()}")
        expect(row).to_contain_text("Zona Norte")
        expect(row).to_contain_text("último jogo")
        expect(page.get_by_test_id(f"invite-box-{device.hex()}")).to_be_checked()
        self.field.host.transmitted_all()  # what the modem sent so far (the DISCOVER, TIME)
        page.get_by_test_id("invite-send").click()
        status = page.get_by_test_id(f"invite-status-{device.hex()}")
        expect(status).to_have_text(re.compile("convidada|a enviar"))
        # On air: the invite, sealed; the box reads it, joins, and answers.
        invites: list[bytes] = []

        def heard_invite() -> bool:  # every part: they go out one at a time, paced
            for f in self.field.host.transmitted_all(0.2):
                if ff.is_frame(f) and ff.decode(key, f)["kind"] == "invite":
                    invites.append(f)
            return bool(invites) and len(invites) >= ff.decode(key, invites[0])["parts"]
        self.assertTrue(wait_for(heard_invite, 5))
        for f in invites:
            box.on_frame(f, 1000)
        self.assertEqual(box.phase, "joined")
        for answer in box.tick(10_000):
            self.field.host.hear(answer)
        expect(status).to_have_text("aceitou, a juntar-se")
        page.get_by_test_id("invite-close").click()
        expect(dialog).to_be_hidden()
        # Until the box's HELLO, Start says which role is missing and starts only "anyway".
        expect(page.get_by_test_id("start-missing")).to_contain_text("zone")
        expect(page.get_by_test_id("game-start")).to_have_text("Começar mesmo assim")
        game = self.field.bundle.controller.game
        game_key = self.field.bundle.controller.game_key(game["id"])
        self.field.host.hear(node_packet(game_key, game["id"], box.game["node_id"], 0, 1, "HELLO", hello_encode(
            {"node_name": "Zona Norte", "platform": 1, "fw_version": "0.4.0", "core_version": "0.2.0", "tier": 0,
             "capabilities": [0], "transports": 1, "epoch": 1, "device_id": device}), ack=True))
        expect(page.get_by_test_id("start-missing")).to_be_hidden()
        expect(page.get_by_test_id("game-start")).to_have_text("Começar")
        page.get_by_test_id("game-invite").click()
        expect(status).to_have_text("juntou-se")
        page.get_by_test_id("invite-close").click()
        page.get_by_test_id("game-start").click()
        page.get_by_test_id("game-start-yes").click()
        expect(page.get_by_test_id("game-state")).to_have_text("a decorrer")

    def test_start_anyway_without_a_box(self):
        """No box has joined and none was heard: no dialog, Start names the missing role and asks;
        the GM's "Start anyway" starts the game (force), which the controller logs."""
        page = self.console()
        page.get_by_test_id("lang").select_option("en")
        page.get_by_test_id("game-name").fill("Sunday")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("ready")
        expect(page.get_by_test_id("invite-dialog")).to_have_count(0)
        expect(page.get_by_test_id("start-missing")).to_contain_text("zone")
        page.get_by_test_id("game-invite").click()
        expect(page.get_by_test_id("invite-empty")).to_contain_text("No free box heard yet")
        page.get_by_test_id("invite-close").click()
        page.get_by_test_id("game-start").click()
        expect(page.locator(".confirm-q")).to_have_text("No box has joined for: zone. Start anyway?")
        page.get_by_test_id("game-start-yes").click()
        expect(page.get_by_test_id("game-state")).to_have_text("running")
        self.assertEqual(self.field.bundle.controller.game["state"], "running")

    def test_ending_a_game_whose_key_was_lost(self):
        """Decisions OT-7 and OT-13: a controller that restarted without the game's key says so on the
        game card; its End asks to tell the boxes over the field radio, and does (GAME_OVER)."""
        game = self.field.create_game("Domingo", start=True)
        ctrl = self.field.bundle.controller
        with ctrl._lock:  # as a restart with persist_game_key = false leaves it (engine._restore)
            ctrl._deactivate()
            ctrl.game, ctrl.key_lost = ctrl.store.game(game["id"]), True
        page = self.console()
        expect(page.get_by_test_id("game-key-lost")).to_contain_text("reiniciou sem a chave do jogo")
        page.get_by_test_id("game-end").click()
        expect(page.locator(".confirm-q")).to_have_text("Terminar o jogo e avisar as caixas pelo rádio do campo?")
        page.get_by_test_id("game-end-yes").click()
        expect(page.get_by_test_id("toast")).to_contain_text("As caixas do jogo foram avisadas pelo rádio do campo")
        expect(page.get_by_test_id("game-ended")).to_be_visible()
        self.assertEqual(ctrl.store.game(game["id"])["state"], "ended")

    def ready_game_with_the_dialog(self, lang: str = "en", **spec):
        """A Hold-All game (min_zones 2 by default) waiting for its zone box (node 7), and the
        console with the invite dialog open."""
        self.field.create_game("Sunday", mode_id="org.atalaia.holdall", assignments={str(BOX): "zone"}, **spec)
        page = self.console()
        if lang != "pt":
            page.get_by_test_id("lang").select_option(lang)
        expect(page.get_by_test_id("game-state")).to_have_text("ready" if lang == "en" else "pronto")
        page.get_by_test_id("game-invite").click()
        expect(page.get_by_test_id("invite-dialog")).to_be_visible()
        return page

    def test_invite_dialog_says_ready_and_starts_the_game(self):
        """Decisions GM-1 and GM-2: the dialog says, live, when every role the game needs has a box
        (with the count per role) and warns about the mode's minimum still unmet; its Start asks
        whether to review the settings first, and "Start now" starts the game (not forced)."""
        told: list[dict] = []
        self.field.bundle.controller.add_listener(told.append)
        page = self.ready_game_with_the_dialog()
        expect(page.get_by_test_id("invite-waiting")).to_have_text(
            "Still waiting for a box for: zone. Joined so far: 0 × zone.")
        expect(page.get_by_test_id("invite-ready")).to_have_count(0)
        expect(page.get_by_test_id("invite-start")).to_have_text("Start anyway")
        self.field.box_hello()  # the last (only) needed box joins
        expect(page.get_by_test_id("invite-ready")).to_have_text(
            "Ready to start: every role has a box (1 × zone). You can close this dialog.")
        expect(page.get_by_test_id("invite-waiting")).to_have_count(0)
        expect(page.get_by_test_id("invite-warnings")).to_have_text(
            "1 × zone joined; the mode asks for 2 (min_zones).")
        expect(page.get_by_test_id("invite-readiness")).to_have_attribute("aria-live", "polite")
        start = page.get_by_test_id("invite-start")
        expect(start).to_have_text("Start game")
        start.click()
        expect(page.locator("#inv-start-q")).to_have_text("Review the game's other settings first?")
        expect(page.get_by_test_id("invite-review")).to_be_focused()
        expect(page.get_by_test_id("invite-start-missing")).to_have_count(0)
        page.keyboard.press("Escape")  # back to the Start button, the dialog still open
        expect(page.get_by_test_id("invite-start-confirm")).to_have_count(0)
        expect(start).to_be_focused()
        start.press("Enter")
        page.get_by_test_id("invite-start-now").click()
        expect(page.get_by_test_id("game-state")).to_have_text("running")
        expect(page.get_by_test_id("invite-dialog")).to_have_count(0)
        self.assertEqual(self.field.bundle.controller.game["state"], "running")
        self.assertFalse(any(m.get("kind") == "start.forced" for m in told))

    def test_invite_dialog_review_settings(self):
        """Decision GM-3, in European Portuguese: "Rever definições" closes the dialog and opens
        the game's settings (its parameters as created), focused; the game stays ready."""
        page = self.ready_game_with_the_dialog("pt", params={"min_zones": 1})
        self.field.box_hello()
        expect(page.get_by_test_id("invite-ready")).to_contain_text("Tudo pronto para começar: cada papel tem uma caixa")
        expect(page.get_by_test_id("invite-warnings")).to_have_count(0)  # min_zones 1 is met
        page.get_by_test_id("invite-start").click()
        expect(page.locator("#inv-start-q")).to_have_text("Rever primeiro as outras definições do jogo?")
        page.get_by_test_id("invite-review").click()
        expect(page.get_by_test_id("invite-dialog")).to_have_count(0)
        settings = page.get_by_test_id("game-settings")
        expect(settings).to_have_attribute("open", "")
        expect(page.get_by_test_id("game-settings-summary")).to_be_focused()
        expect(page.get_by_test_id("game-param-min_zones")).to_have_text("1")
        expect(settings).to_contain_text("Caixas em jogo antes de alguém poder pontuar")
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        self.assertEqual(self.field.bundle.controller.game["state"], "ready")
        page.set_viewport_size({"width": 360, "height": 800})  # the long labels wrap on a phone
        self.no_horizontal_scroll(page)

    def test_invite_dialog_start_anyway(self):
        """Decision GM-2's guard path: with the zone box missing, the dialog's Start says "Start
        anyway", names the missing role in the confirmation, and starts with force (logged)."""
        page = self.ready_game_with_the_dialog()
        start = page.get_by_test_id("invite-start")
        expect(start).to_have_text("Start anyway")
        start.click()
        expect(page.get_by_test_id("invite-start-missing")).to_have_text("No box has joined for: zone.")
        now = page.get_by_test_id("invite-start-now")
        expect(now).to_have_text("Start anyway")
        with self.assertLogs("atalaia.controller", "WARNING") as logs:
            now.click()
            expect(page.get_by_test_id("game-state")).to_have_text("running")
        self.assertTrue(any("started anyway (forced)" in line for line in logs.output))
        expect(page.get_by_test_id("invite-dialog")).to_have_count(0)
        self.assertEqual(self.field.bundle.controller.game["state"], "running")

    def test_presets_and_commands_to_boxes(self):
        page = self.console()
        page.get_by_test_id("tab-presets").click()
        page.locator("#preset-name").fill("Rápido")
        page.locator("#preset-mode").select_option(DOMINATION)
        page.locator("#preset-tick_s").fill("2")
        page.locator("#preset-points_per_tick").fill("3")
        page.get_by_test_id("preset-save").click()
        expect(page.get_by_test_id("preset-list")).to_contain_text("Rápido")
        preset = next(p for p in self.field.http.get("/api/v1/presets").json() if p["name"] == "Rápido")
        self.assertEqual((preset["mode_id"], preset["params"]["tick_s"], preset["params"]["points_per_tick"]),
                         (DOMINATION, 2, 3))

        # A game from that preset, then a message to every box and an owner override.
        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-name").fill("Do preset")
        page.get_by_test_id("game-source").select_option(f"preset:{preset['id']}")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual((game["preset_id"], game["params"]["tick_s"]), (preset["id"], 2))
        page.get_by_test_id("game-start").click()
        page.get_by_test_id("game-start-yes").click()
        expect(page.get_by_test_id("game-state")).to_have_text("a decorrer")
        self.field.host.transmitted_all(0.3)  # CMD start and TIME
        page.locator("#g-msg").fill("Cessar fogo")
        page.locator("#g-msg").press("Enter")
        self.field.box_hello()
        page.get_by_test_id("tab-nodes").click()
        page.locator(f'[data-testid=node-list] tr[data-node="{BOX}"] select').select_option("blue")
        key = self.field.bundle.controller.game_key(game["id"])
        epoch = self.field.bundle.controller.transport.epoch
        cmds = []

        def heard_cmds() -> bool:
            for pkt in self.field.host.transmitted_all(0.2):
                hdr, plain = packet_decrypt(pkt, epoch, key)
                if hdr.type == MESSAGE_TYPES["CMD"]:
                    cmds.append(cmd_decode(plain))
            return len(cmds) >= 2
        self.assertTrue(wait_for(heard_cmds, 5), cmds)
        self.assertEqual(cmds[0], {"cmd": 5, "params": {"text": "Cessar fogo"}})
        self.assertEqual(cmds[1], {"cmd": 4, "params": {"team": "blue"}, "dest": BOX})

    def test_mode_pack_lists_and_starts(self):
        """Hold-All and Last Stand (field.lua on the controller), and a mode with the Codes modifier."""
        page = self.console()
        source = page.get_by_test_id("game-source")
        expect(source.locator('option[value="mode:org.atalaia.holdall"]')).to_have_text("Domínio Total")
        expect(source.locator('option[value="mode:org.atalaia.laststand"]')).to_have_text("Último Elemento")
        expect(source.locator('option[value="mode:org.atalaia.codes"]')).to_have_count(0)  # a modifier
        page.get_by_test_id("game-name").fill("Tudo ou nada")
        source.select_option("mode:org.atalaia.holdall")
        expect(page.locator('label[for="game-min_zones"]')).to_contain_text("Caixas em jogo")
        page.locator("#game-min_zones").fill("3")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual((game["mode_id"], game["params"]["min_zones"]), ("org.atalaia.holdall", 3))
        page.get_by_test_id("game-start").click()
        page.get_by_test_id("game-start-yes").click()
        expect(page.get_by_test_id("game-state")).to_have_text("a decorrer")
        self.assertIsNotNone(self.field.bundle.controller.field)  # its field.lua runs
        self.field.http.post(f"/api/v1/games/{game['id']}/end", json={})

        # Domination with the Codes modifier, from the same form.
        expect(page.get_by_test_id("game-ended")).to_be_visible()
        page.get_by_test_id("game-name").fill("Com códigos")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        modifiers = page.get_by_test_id("game-modifiers")
        expect(modifiers).to_contain_text("Códigos")
        modifiers.locator('input[value="org.atalaia.codes"]').check()
        page.locator("#game-codes").fill("4711:points:50,0815:hint")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual(game["mode_id"], f"{DOMINATION}+org.atalaia.codes")
        self.assertEqual(game["params"]["codes"], "4711:points:50,0815:hint")
        expect(page.get_by_text("Domínio + Códigos", exact=True)).to_be_visible()
        page.get_by_test_id("tab-join").click()
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual((j["mode_id"], j["role"]), (game["mode_id"], "zone"))

        # A preset with the modifier.
        page.get_by_test_id("tab-presets").click()
        page.locator("#preset-name").fill("Bomba com pistas")
        page.locator("#preset-mode").select_option("org.atalaia.bomb")
        page.get_by_test_id("preset-modifiers").locator('input[value="org.atalaia.codes"]').check()
        page.locator("#preset-team_codes").fill("red=1234,blue=5678")
        page.locator("#preset-codes").fill("0815:hint")
        page.get_by_test_id("preset-save").click()
        expect(page.get_by_test_id("preset-list")).to_contain_text("Bomba / Rush + Códigos")
        preset = next(p for p in self.field.http.get("/api/v1/presets").json() if p["name"] == "Bomba com pistas")
        self.assertEqual(preset["mode_id"], "org.atalaia.bomb+org.atalaia.codes")
        self.assertEqual((preset["params"]["team_codes"], preset["params"]["codes"]), ("red=1234,blue=5678", "0815:hint"))

    def test_adopt_tab_field_card_and_usb(self):
        """Adopting boxes (protocol/adoption.md): the Adopt tab shows the field's fingerprint, makes the
        NFC field card with its warning (the bytes decode to the field join key), and adopts two C host
        boxes reached as socket:// ports (a COM-to-TCP bridge): an unadopted one, then one of another
        field with its admin PIN (the page asks for it); the records list both; in both languages; a read
        token sees none of it."""
        sys.path.insert(0, str(CONTROLLER / "tests"))
        from test_adoption import OTHER, BridgedBox  # noqa: PLC0415

        from atalaia_sim import field_card  # noqa: PLC0415

        boxes = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, boxes, True)
        (boxes / "new").mkdir()
        (boxes / "stranger").mkdir()
        new = BridgedBox(str(boxes / "new"), mac="02:00:00:00:00:0A", name="porta-norte")
        self.addCleanup(new.close)
        stranger = BridgedBox(str(boxes / "stranger"), join_key=OTHER, mac="02:00:00:00:00:0B", name="vizinho")
        self.addCleanup(stranger.close)
        self.field.bundle.cfg.adopt_usb_ports = [new.url, stranger.url]
        self.field.bundle.controller.adoption.lister = lambda: []

        page = self.console()
        page.get_by_test_id("tab-adopt").click()
        expect(page.get_by_test_id("tab-adopt")).to_have_text("Adotar")
        expect(page.get_by_test_id("adopt-field")).to_contain_text("604A-0A95")
        expect(page.get_by_test_id("adopt-card-warning")).to_contain_text("segredo-mestre")
        expect(page.get_by_test_id("adopt-card-lost")).to_contain_text("join-key --rotate")
        expect(page.get_by_test_id("adopt-code")).to_be_visible()

        page.get_by_test_id("adopt-card-make").click()
        ndef = page.get_by_test_id("adopt-card-ndef").inner_text().strip()
        card = field_card.decode(field_card.from_ndef_tag(bytes.fromhex(ndef)))
        self.assertEqual(card["join_key"], JOIN_KEY)

        page.get_by_test_id("adopt-scan").click()
        row = page.get_by_test_id("adopt-box-02:00:00:00:00:0A")
        expect(row).to_contain_text("porta-norte")
        expect(row).to_contain_text("não adotada")
        other = page.get_by_test_id("adopt-box-02:00:00:00:00:0B")
        expect(other).to_contain_text(f"adotada por outro campo: — ({field_card.fingerprint(OTHER)})")
        row.get_by_test_id("adopt-box-adopt").click()
        expect(page.get_by_test_id("adopt-confirm")).to_contain_text("porta-norte (02:00:00:00:00:0A)")
        expect(page.get_by_test_id("adopt-pin")).to_have_count(0)
        page.get_by_test_id("adopt-confirm-yes").click()
        expect(page.get_by_test_id("adopt-result")).to_contain_text("está adotada")
        expect(row).to_contain_text("adotada por este campo")
        self.assertEqual((boxes / "new" / "join_key").read_bytes(), JOIN_KEY)

        other.get_by_test_id("adopt-box-adopt").click()
        page.get_by_test_id("adopt-pin").fill("1234")
        page.get_by_test_id("adopt-confirm-yes").click()
        expect(page.get_by_test_id("adopt-result")).to_contain_text("passou para este campo")
        self.assertEqual((boxes / "stranger" / "join_key").read_bytes(), JOIN_KEY)
        expect(page.get_by_test_id("adopt-log")).to_contain_text("vizinho (02:00:00:00:00:0B)")
        expect(page.get_by_test_id("adopt-log")).to_contain_text("cartão de campo")

        page.get_by_test_id("lang").first.select_option("en")
        expect(page.get_by_test_id("adopt-card-warning")).to_contain_text("master secret")
        expect(other).to_contain_text("adopted by this field")
        self.no_horizontal_scroll(page)

        # A read token sees no adoption at all.
        read = self.console(READ)
        read.get_by_test_id("tab-adopt").click()
        expect(read.get_by_test_id("adopt-scan")).to_have_count(0)
        expect(read.get_by_test_id("adopt-card-make")).to_have_count(0)

    def test_adopt_pair_by_code(self):
        """Pairing by code over the radio (protocol/adoption.md section 7): an unadopted C host box
        (main/box_pair.c) shows a code and offers itself on the C host modem's air; in the Adopt tab
        the GM looks for boxes, types a wrong code (the run fails, the box shows a new one), then the
        box's new code: the box is adopted with the field join key, in both languages."""
        import re  # noqa: PLC0415

        self.field.close()
        hub = AirHub()
        self.addCleanup(hub.close)
        self.field = Field(hub=hub)
        boxdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, boxdir, True)
        box = BoxHost(hub, str(boxdir), b"", name="porta-norte", extra=("--pair",))
        self.addCleanup(box.close)
        self.assertTrue(wait_for(lambda: box.logged("pairing: code"), 5))

        def code() -> str:
            found = [m.group(1) + m.group(2) for m in (re.search(r"code (\d{3}) (\d{3})", x) for x in box.lines) if m]
            return found[-1]

        page = self.console()
        page.get_by_test_id("tab-adopt").click()
        expect(page.get_by_test_id("adopt-code")).to_contain_text("6 algarismos")
        page.get_by_test_id("adopt-pair-listen").click()
        expect(page.get_by_test_id("adopt-pair-channel")).to_contain_text("869.525")
        offers = page.get_by_test_id("adopt-pair-offers")
        expect(offers).to_contain_text("porta-norte", timeout=10000)
        # The id the box's screen shows is the one beside its entry (decision AD-26).
        short = next(m.group(1) for m in (re.search(r'"id":"([0-9a-f]{4})"', x) for x in box.lines) if m)
        expect(page.get_by_test_id("adopt-pair-id")).to_have_text(f"id {short}")
        expect(page.get_by_test_id("adopt-pair-warn")).to_have_count(0)
        first = code()
        page.get_by_test_id("adopt-pair-code").fill(f"{(int(first) + 1) % 1000000:06d}")
        page.get_by_test_id("adopt-pair-go").click()
        run = page.get_by_test_id("adopt-pair-run")
        expect(run).to_contain_text("o código não era o que a caixa mostra", timeout=15000)
        self.assertTrue(wait_for(lambda: box.logged("pairing: new code"), 12))
        self.assertFalse((boxdir / "join_key").exists())
        page.get_by_test_id("adopt-pair-code").fill(code()[:3] + " " + code()[3:])
        page.get_by_test_id("adopt-pair-go").click()
        expect(run).to_contain_text("porta-norte está adotada por este campo", timeout=15000)
        self.assertEqual((boxdir / "join_key").read_bytes(), JOIN_KEY)
        expect(page.get_by_test_id("adopt-log")).to_contain_text("código por rádio")
        page.get_by_test_id("lang").first.select_option("en")
        expect(run).to_contain_text("porta-norte is adopted by this field")
        self.no_horizontal_scroll(page)

    def test_firmware_update_from_the_boxes_tab(self):
        """Firmware updates (protocol/firmware-update.md): the GM uploads a signed release in the
        Boxes tab and updates a box before the game starts; the CMD update goes on the air; the box's
        report and its next HELLO show on the page, in both languages."""
        sys.path.insert(0, str(CONTROLLER / "tests"))
        from test_firmware_updates import SIGNING, box_image, sign  # noqa: PLC0415

        from atalaia_controller import firmware_release as fr  # noqa: PLC0415

        self.field.close()
        self.field = Field(cfg={"firmware_release_keys": [SIGNING["public_key_b64"]]})
        ctrl = self.field.bundle.controller
        ctrl.ca_sha256 = bytes(range(32))  # as with [api] tls_port: the joins carry the field CA
        ctrl.link_urls = ["https://10.42.0.1:8443"]
        game = self.field.create_game()
        self.field.box_hello("0.3.0")
        image = box_image("0.4.0")
        files = Path(self.field.tmp.name)
        (files / "atalaia_esp32.bin").write_bytes(image)
        (files / "atalaia_esp32.bin.release.json").write_text(json.dumps({
            "platform": "esp32s3", "version": "0.4.0", "size": len(image),
            "sha256": hashlib.sha256(image).hexdigest(), "signature": sign(image, "0.4.0")}))
        release_id = hashlib.sha256(image).hexdigest()[:16]

        page = self.console()
        page.get_by_test_id("tab-nodes").click()
        panel = page.get_by_test_id("firmware-panel")
        expect(panel).to_contain_text("Atualizações de firmware")
        page.get_by_test_id("firmware-image").set_input_files(str(files / "atalaia_esp32.bin"))
        page.get_by_test_id("firmware-release").set_input_files(str(files / "atalaia_esp32.bin.release.json"))
        page.get_by_test_id("firmware-upload").click()
        expect(page.get_by_test_id("firmware-releases")).to_contain_text("0.4.0")
        expect(page.get_by_test_id("firmware-releases")).to_contain_text("heltec_v4_3")
        update = page.get_by_test_id(f"firmware-update-{BOX}")
        expect(update).to_have_text("Atualizar para 0.4.0")

        key = ctrl.game_key(game["id"])
        epoch = ctrl.transport.epoch
        self.field.host.transmitted_all(0.3)
        update.click()
        state = page.get_by_test_id(f"firmware-state-{BOX}")
        expect(state).to_contain_text("0.4.0: enviada, à espera da caixa")
        cmds = []

        def heard_update() -> bool:
            for pkt in self.field.host.transmitted_all(0.2):
                hdr, plain = packet_decrypt(pkt, epoch, key)
                if hdr.type == MESSAGE_TYPES["CMD"]:
                    cmds.append(cmd_decode(plain))
            return {"cmd": 9, "params": {"id": release_id, "version": "0.4.0"}, "dest": BOX} in cmds
        self.assertTrue(wait_for(heard_update, 5), cmds)
        expect(page.get_by_test_id("firmware-cancel")).to_be_visible()
        expect(page.get_by_test_id("firmware-boxes")).to_contain_text("Versão instalada")
        expect(page.get_by_test_id(f"firmware-again-{BOX}")).to_have_text("Enviar de novo")

        # The box found no Wi-Fi: it says so over LoRa (OT-8) and the GM sends the update again at once.
        self.field.box("EVENT", codec.encode_event({
            "node": BOX, "seq": 2, "t": 0, "type": "node.update_failed",
            "data": {"release": release_id, "reason": "no_wifi", "fw": "0.3.0"}}), ack=True)
        expect(state).to_contain_text("0.4.0: falhou (a caixa não tem o Wi-Fi do campo)")
        expect(page.get_by_test_id(f"firmware-again-{BOX}")).to_have_count(0)
        expect(page.get_by_test_id("firmware-cancel")).to_have_count(0)
        update.click()
        expect(state).to_contain_text("0.4.0: enviada, à espera da caixa")

        # The box reports over HTTPS (its MAC is the game key's), restarts and says hello again.
        body = fr.report_body(game["id"], BOX, release_id, "installed", "0.4.0")
        r = httpx.post(self.field.base + "/api/v1/firmware/report", content=body,
                       headers={"X-Atalaia-Mac": fr.report_mac(key, body)})
        self.assertEqual(r.json(), {"accepted": True})
        expect(state).to_contain_text("0.4.0: instalada, a reiniciar")
        self.field.box_hello("0.4.0")
        expect(state).to_contain_text("0.4.0: concluída")
        expect(update).to_have_count(0)  # nothing newer for it now
        page.get_by_test_id("lang").first.select_option("en")
        expect(state).to_contain_text("0.4.0: done")
        expect(page.get_by_test_id("firmware-not-ready")).to_have_count(0)

        # Once the game runs, no update goes out: the buttons say so.
        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-start").click()
        page.get_by_test_id("game-start-yes").click()
        expect(page.get_by_test_id("game-state")).to_have_text("running")
        page.get_by_test_id("tab-nodes").click()
        expect(page.get_by_test_id("firmware-not-ready")).to_be_visible()
        expect(page.get_by_test_id(f"firmware-all-{release_id}")).to_be_disabled()

    def test_medic_kits_next_to_a_mode(self):
        """The Medic Kit (a role package) from the game form; a kit's join names the kit alone;
        a heal reads as words in the feed; the GM refills a kit from the Boxes tab."""
        page = self.console()
        page.get_by_test_id("game-name").fill("Com ligaduras")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        roles = page.get_by_test_id("game-roles")
        expect(roles).to_contain_text("Props com uma função própria")
        expect(roles).to_contain_text("Ligaduras")
        expect(page.get_by_test_id("game-modifiers")).not_to_contain_text("Ligaduras")
        roles.locator('input[value="org.atalaia.medic"]').check()
        expect(page.locator('label[for="game-heal_hold_s"]')).to_contain_text("Segundos a premir")
        expect(page.locator("#game-team option").first).to_have_text("todas as equipas")
        page.locator("#game-heal_hold_s").fill("5")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual(game["mode_id"], f"{DOMINATION}+org.atalaia.medic")
        self.assertEqual(game["params"]["heal_hold_s"], 5)
        self.assertNotIn("team", game["params"])  # every team

        # The kit's join: the role list has "medic", and the payload names the kit alone.
        page.get_by_test_id("tab-join").click()
        page.locator("#j-role").select_option("medic")
        page.locator("#j-node").fill(str(BOX))
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual((j["mode_id"], j["role"], j["node_id"]), ("org.atalaia.medic", "medic", BOX))
        self.assertEqual(j["params"]["heal_hold_s"], 5)
        self.assertNotIn("tick_s", j["params"])

        # A heal from the kit, in words in the log.
        self.field.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True})
        self.field.host.transmitted_all(0.3)  # CMD start and TIME
        self.field.box_hello()
        ev = codec.encode_event({"node": BOX, "seq": 1, "t": 9000, "type": "medic.heal", "team": 2,
                                 "data": {"team": "blue", "player": "b1", "remaining": 4,
                                          "player_heals_used": 1}})
        self.field.box("EVENT", ev, ack=True)
        page.get_by_test_id("tab-feed").click()
        heal = page.locator('[data-testid=feed] [data-type="medic.heal"]')
        expect(heal).to_contain_text("b1 recebeu tratamento (ligaduras no kit: 4; tratamentos neste jogo: 1)")

        # The GM refills the kit: a mode command (CMD opcode 8) for that box only.
        page.get_by_test_id("tab-nodes").click()
        refill = page.get_by_test_id(f"node-cmd-{BOX}-refill")
        expect(refill).to_have_text("Repor as ligaduras")
        key = self.field.bundle.controller.game_key(game["id"])
        epoch = self.field.bundle.controller.transport.epoch
        self.field.host.transmitted_all(0.3)
        refill.click()
        expect(page.locator(f'[data-testid=node-list] tr[data-node="{BOX}"]')).to_contain_text("enviado")
        cmds = []

        def heard_refill() -> bool:
            for pkt in self.field.host.transmitted_all(0.2):
                hdr, plain = packet_decrypt(pkt, epoch, key)
                if hdr.type == MESSAGE_TYPES["CMD"]:
                    cmds.append(cmd_decode(plain))
            return {"cmd": 8, "params": {"name": "refill"}, "dest": BOX} in cmds
        self.assertTrue(wait_for(heard_refill, 5), cmds)

        # In English, the command's label and the heal follow the language.
        page.get_by_test_id("lang").first.select_option("en")
        expect(refill).to_have_text("Refill the kit")
        page.get_by_test_id("tab-feed").click()
        expect(heal).to_contain_text("b1 was healed (heals left in the kit: 4; heals in this game: 1)")

    def test_hacking_terminal_game_and_its_event(self):
        """A Hacking Terminal game from the form (its parameters in Portuguese); the terminal's
        join; a solved terminal reads as words in the feed, with the code it revealed for the GM,
        in both languages; the GM's "New puzzle" command on the Boxes tab."""
        page = self.console()
        page.get_by_test_id("game-name").fill("Terminal")
        page.get_by_test_id("game-source").select_option("mode:org.atalaia.hacking_terminal")
        expect(page.locator('label[for="game-lockout_s"]')).to_contain_text("Segundos de bloqueio")
        page.locator("#game-puzzle").fill("wires")
        page.locator("#game-reveal_code").fill("4711")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual(game["mode_id"], "org.atalaia.hacking_terminal")
        self.assertEqual((game["params"]["puzzle"], game["params"]["reveal_code"]), ("wires", "4711"))

        page.get_by_test_id("tab-join").click()
        page.locator("#j-node").fill(str(BOX))
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual((j["mode_id"], j["role"]), ("org.atalaia.hacking_terminal", "terminal"))

        self.field.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True})
        self.field.host.transmitted_all(0.3)
        self.field.box_hello()
        for seq, data in ((1, {"puzzle": "wires", "code": "4711", "team": "red"}), (2, {"puzzle": "code"})):
            ev = {"node": BOX, "seq": seq, "t": 9000 * seq, "type": "hacking.solved", "data": data}
            if "team" in data:
                ev["team"] = 1
            self.field.box("EVENT", codec.encode_event(ev), ack=True)
        page.get_by_test_id("tab-feed").click()
        solved = page.locator('[data-testid=feed] [data-type="hacking.solved"]')
        expect(solved).to_have_count(2)
        expect(solved.nth(1)).to_contain_text("red resolveu um terminal de hacking (fios) e recebeu o código 4711")
        expect(solved.nth(0)).to_contain_text("Alguém por identificar resolveu um terminal de hacking (código)")

        page.get_by_test_id("tab-nodes").click()
        expect(page.get_by_test_id(f"node-cmd-{BOX}-reset")).to_have_text("Novo enigma")

        page.get_by_test_id("lang").first.select_option("en")
        expect(page.get_by_test_id(f"node-cmd-{BOX}-reset")).to_have_text("New puzzle")
        page.get_by_test_id("tab-feed").click()
        expect(solved.nth(1)).to_contain_text("red solved a hacking terminal (wires) and got the code 4711")
        expect(solved.nth(0)).to_contain_text("Nobody known solved a hacking terminal (code)")

    def test_vip_payload_game_and_its_events(self):
        """A VIP / Payload game from the form (the extraction zone in Portuguese); a checkpoint's
        join; the payload's and the VIP's extractions read as words in the feed, in both languages."""
        page = self.console()
        page.get_by_test_id("game-name").fill("Escolta")
        page.get_by_test_id("game-source").select_option("mode:org.atalaia.vip_payload")
        expect(page.locator('label[for="game-extraction"]')).to_contain_text("Centro da zona de extração")
        page.locator("#game-extraction").fill("38.722345,-9.139312")
        page.locator("#game-end_on_extract").uncheck()
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual((game["mode_id"], game["params"]["extraction"], game["params"]["end_on_extract"]),
                         ("org.atalaia.vip_payload", "38.722345,-9.139312", False))

        page.get_by_test_id("tab-join").click()
        page.locator("#j-node").fill(str(BOX))
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual((j["mode_id"], j["role"]), ("org.atalaia.vip_payload", "checkpoint"))

        self.field.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True})
        self.field.host.transmitted_all(0.3)
        self.field.box_hello()
        # The payload prop's extraction (from a node), then a VIP's (the controller's own event).
        self.field.box("EVENT", codec.encode_event({"node": BOX, "seq": 1, "t": 9000, "type": "vip.extracted",
                                                    "team": 2, "data": {"team": "blue"}}), ack=True)
        self.field.bundle.controller.fc.controller_event("vip.extracted", {"player": "p-k7m2q4x9z3ab"},
                                                         team="red", prio="critical")
        page.get_by_test_id("tab-feed").click()
        extracted = page.locator('[data-testid=feed] [data-type="vip.extracted"]')
        expect(extracted).to_have_count(2)
        # Newest game time first: the payload's (9 s) above the controller's (at 0 s here).
        expect(extracted.nth(0)).to_contain_text("A carga da equipa blue chegou à zona de extração")
        expect(extracted.nth(1)).to_contain_text("A equipa red extraiu o seu VIP (p-k7m2q4x9z3ab)")
        page.get_by_test_id("lang").first.select_option("en")
        expect(extracted.nth(0)).to_contain_text("blue's payload reached the extraction zone")
        expect(extracted.nth(1)).to_contain_text("red extracted its VIP (p-k7m2q4x9z3ab)")

    def test_a_scenario_over_the_objectives_package(self):
        """A scenario package (kind: scenario, the hand-written example of plan phase 6) uploaded,
        then a game of it from the form with the objectives package ticked; a box's join names the
        objectives package; the scenario's events read as words in the feed, which objective
        included for the GM, in both languages."""
        fixture = HERE.parents[2] / "modes" / "objectives" / "tests" / "fixtures" / "foxhound"
        files = {n: (fixture / n).read_text(encoding="utf-8") for n in ("mode.yaml", "field.lua")}
        self.assertEqual(self.field.http.post("/api/v1/modes", json={"files": files}).status_code, 201)
        page = self.console()
        page.get_by_test_id("game-name").fill("Foxhound")
        page.get_by_test_id("game-source").select_option("mode:org.club.foxhound")
        roles = page.get_by_test_id("game-roles")
        expect(roles).to_contain_text("Objetivos")
        roles.locator('input[value="org.atalaia.objectives"]').check()
        expect(page.locator('label[for="game-vault_points"]')).to_contain_text("Pontos do cofre")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual(game["mode_id"], "org.club.foxhound+org.atalaia.objectives")

        page.get_by_test_id("tab-join").click()
        page.locator("#j-node").fill(str(BOX))
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual((j["mode_id"], j["role"]), ("org.atalaia.objectives", "objective"))

        self.field.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True})
        self.field.host.transmitted_all(0.3)
        self.field.bundle.controller.fc.controller_event(
            "scenario.objective.completed", {"objective": "bridge"}, team="red", prio="critical")
        page.get_by_test_id("tab-feed").click()
        feed = page.get_by_test_id("feed")
        expect(feed.locator('[data-type="scenario.started"]')).to_contain_text("O cenário org.club.foxhound começou")
        expect(feed.locator('[data-type="scenario.objective.revealed"]').first).to_contain_text("foi revelado")
        done = feed.locator('[data-type="scenario.objective.completed"]')
        expect(done).to_contain_text("A equipa red cumpriu o objetivo bridge")
        page.get_by_test_id("lang").first.select_option("en")
        expect(done).to_contain_text("red completed the objective bridge")
        expect(feed.locator('[data-type="scenario.objective.revealed"]')).to_have_count(3)
        expect(feed).to_contain_text("The objective intel is revealed to every team")

    @unittest.skipUnless(BOX_HOST, "host box not built")
    def test_scenario_builder_to_a_two_objective_game_on_host_boxes(self):
        """Plan phase 8: the GM writes a scenario in the builder (the example, a mistake shown
        with its place in the manifest, fixed), installs it, makes a game of it with the
        objectives package, names two host boxes in the Join tab with the scenario's names,
        and plays it: the bridge's capture completes it and reveals the vault, whose code
        typed on the other box completes the vault; the score and the feed follow."""
        self.field.close()
        hub = AirHub()
        self.addCleanup(hub.close)
        self.field = Field(hub=hub)
        page = self.console()
        page.get_by_test_id("tab-scenarios").click()
        expect(page.get_by_test_id("scenario-none")).to_be_visible()
        page.get_by_test_id("scenario-example").click()
        expect(page.get_by_test_id("scenario-ok")).to_contain_text("Sem problemas")
        expect(page.get_by_test_id("scenario-nodes")).to_contain_text("vault · objetivo")
        editor = page.get_by_test_id("scenario-text")
        example = editor.input_value()
        editor.fill(example.replace("depends_on: [bridge]", "depends_on: [brige]"))
        problem = page.locator('[data-testid=scenario-problems] [data-code="unknown_reference"]')
        expect(problem).to_contain_text("objectives[1].depends_on[0]")
        expect(page.get_by_test_id("scenario-install")).to_be_disabled()
        editor.fill(example)
        expect(page.get_by_test_id("scenario-ok")).to_be_visible()
        page.get_by_test_id("scenario-install").click()
        expect(page.get_by_test_id("scenario-installed")).to_contain_text("Ponte e cofre 1")
        expect(page.get_by_test_id("scenario-list")).to_contain_text("Tomar a ponte, Abrir o cofre")
        self.no_horizontal_scroll(page)

        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-name").fill("Ponte")
        page.get_by_test_id("game-source").select_option("mode:org.club.bridge-and-vault")
        page.get_by_test_id("game-roles").locator('input[value="org.atalaia.objectives"]').check()
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")

        page.get_by_test_id("tab-join").click()
        boxes = {}
        for name in ("bridge", "vault"):
            box = BoxHost(hub, os.path.join(self.field.tmp.name, name), JOIN_KEY, name=f"caixa-{name}")
            self.addCleanup(box.close)
            page.get_by_test_id("join-name").select_option(name)
            expect(page.locator("#j-role")).to_have_count(0)  # the scenario says the role
            page.get_by_test_id("join-generate").click()
            expect(page.get_by_test_id("join-result")).to_contain_text(f": {name} (objective)")
            box.join(page.get_by_test_id("join-text").input_value())
            self.assertTrue(wait_for(lambda b=box: b.logged("LOG join: joined"), 5), box.lines[-5:])
            boxes[name] = box
        expect(page.get_by_test_id("join-names")).to_contain_text("2 de 2")

        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-start").click()
        page.get_by_test_id("game-start-yes").click()
        expect(page.get_by_test_id("game-state")).to_have_text("a decorrer")

        def screens(box, template):
            return [line for line in list(box.lines) if line.startswith(f"SCREEN {template} ")]

        self.assertTrue(wait_for(lambda: screens(boxes["bridge"], "obj_capture"), 10), boxes["bridge"].lines[-8:])
        boxes["bridge"].hold(1, 3300)
        page.get_by_test_id("tab-feed").click()
        feed = page.get_by_test_id("feed")
        done = feed.locator('[data-type="scenario.objective.completed"]')
        expect(done).to_contain_text("A equipa red cumpriu o objetivo bridge", timeout=10000)
        expect(feed).to_contain_text("O objetivo vault foi revelado à equipa red")
        self.assertTrue(wait_for(lambda: screens(boxes["vault"], "obj_code"), 10), boxes["vault"].lines[-8:])
        boxes["vault"].send("keys 4711#")
        expect(done).to_have_count(2, timeout=10000)
        expect(done.first).to_contain_text("A equipa red cumpriu o objetivo vault")
        page.get_by_test_id("tab-game").click()
        expect(page.get_by_test_id("score-red")).to_have_text("150", timeout=10000)

    def test_scenario_builder_with_the_read_token(self):
        """The read token checks a manifest but cannot install it or open one."""
        page = self.console(READ)
        page.get_by_test_id("tab-scenarios").click()
        page.get_by_test_id("lang").first.select_option("en")
        page.get_by_test_id("scenario-text").fill("id: org.club.x\nversion: 1\nname: X\nobjectives: []\n")
        expect(page.get_by_test_id("scenario-problems")).to_contain_text("Error")
        expect(page.get_by_test_id("scenario-install")).to_have_count(0)
        expect(page.get_by_test_id("tab-scenarios")).to_have_text("Scenarios")
        expect(page.locator("main")).to_contain_text("The read-only code checks only")

    def test_join_qr_code_reads_back_as_the_join_text(self):
        if not ZBARIMG:
            self.skipTest("zbarimg is not installed")
        game = self.field.create_game()
        page = self.console()
        page.get_by_test_id("tab-join").click()
        page.get_by_test_id("join-generate").click()
        text = page.get_by_test_id("join-text").input_value()
        self.assertTrue(text.startswith("atalaia:join:"))
        j = join.decode(join.from_text(text), JOIN_KEY)
        self.assertEqual((j["game_id"], j["node_id"], j["role"], j["kind"]), (game["id"], 1, "zone", "node"))
        self.assertEqual(j["game_key"], self.field.bundle.controller.game_key(game["id"]))
        with tempfile.TemporaryDirectory() as tmp:
            shot = os.path.join(tmp, "qr.png")
            page.get_by_test_id("join-qr").screenshot(path=shot)
            out = read_qr(shot)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, text)
        ndef = page.get_by_test_id("join-ndef").text_content().strip()
        self.assertEqual(join.from_ndef_tag(bytes.fromhex(ndef)), join.from_text(text))

        # A standby controller payload too.
        page.get_by_test_id("join-kind").select_option("controller")
        page.get_by_test_id("join-generate").click()
        expect(page.get_by_test_id("join-result")).to_contain_text("2")
        standby = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual((standby["kind"], standby["node_id"]), ("controller", 2))

    def test_language_switch_is_remembered(self):
        page = self.console()
        expect(page.get_by_test_id("tab-nodes")).to_have_text("Caixas")
        page.get_by_test_id("lang").first.select_option("en")
        expect(page.get_by_test_id("tab-nodes")).to_have_text("Boxes")
        expect(page.get_by_test_id("tab-game")).to_have_text("Game")
        self.assertEqual(page.evaluate("document.documentElement.lang"), "en")
        page.reload()
        expect(page.get_by_test_id("tab-nodes")).to_have_text("Boxes")  # language and token kept
        page.get_by_test_id("lang").first.select_option("pt")
        expect(page.get_by_test_id("tab-nodes")).to_have_text("Caixas")
        self.assertEqual(page.evaluate("document.documentElement.lang"), "pt-PT")

    def test_read_token_sees_no_gm_controls(self):
        self.field.create_game(start=True)
        page = self.console(READ)
        expect(page.get_by_test_id("readonly")).to_be_visible()
        expect(page.get_by_test_id("game-state")).to_have_text("a decorrer")
        expect(page.get_by_test_id("game-actions")).to_have_count(0)
        expect(page.get_by_test_id("adjust")).to_have_count(0)
        page.get_by_test_id("tab-join").click()
        expect(page.get_by_test_id("join-form")).to_have_count(0)
        page.get_by_test_id("tab-presets").click()
        expect(page.get_by_test_id("preset-form")).to_have_count(0)
        page.get_by_test_id("tab-field").click()
        expect(page.get_by_test_id("field-upload")).to_have_count(0)
        # Live updates still arrive for a read-only viewer.
        self.field.box_hello()
        self.field.box_state(red=12)
        page.get_by_test_id("tab-game").click()
        expect(page.get_by_test_id("score-red")).to_have_text("12")

    def test_scoreboard_page_follows_the_score(self):
        game = self.field.create_game(name="Final", start=True)
        page = self.page(f"/scoreboard#token={READ}&lang=en")
        self.assertTrue(page.url.endswith(f"/console/scoreboard.html#token={READ}&lang=en"), page.url)
        expect(page.get_by_test_id("board-title")).to_have_text("Final")
        expect(page.get_by_test_id("board-state")).to_have_text("running")
        expect(page.get_by_test_id("board-score-red")).to_have_text("0")
        self.field.box_hello()
        self.field.box_state(red=20, blue=35)
        expect(page.get_by_test_id("board-score-red")).to_have_text("20")
        expect(page.get_by_test_id("board-score-blue")).to_have_text("35")
        self.field.http.post(f"/api/v1/games/{game['id']}/end", json={})
        expect(page.get_by_test_id("board-state")).to_have_text("ended")
        expect(page.get_by_test_id("board-result")).to_have_text("blue wins")
        # Without a token the page says how to open it.
        bare = self.page("/console/scoreboard.html")
        expect(bare.get_by_test_id("board-token")).to_be_visible()

    def test_phone_layout_has_no_sideways_scroll(self):
        self.field.create_game(name="Um nome de jogo bastante comprido para um ecrã pequeno", start=True)
        self.field.box_hello()
        self.field.box_state(red=3)
        page = self.console(width=390, height=844)
        for tab in ("game", "checkin", "field", "nodes", "join", "presets", "feed", "controller", "settings"):
            page.get_by_test_id(f"tab-{tab}").click()
            page.wait_for_timeout(150)
            self.no_horizontal_scroll(page)
        page.get_by_test_id("tab-join").click()
        page.get_by_test_id("join-generate").click()
        expect(page.get_by_test_id("join-qr")).to_be_visible()
        self.no_horizontal_scroll(page)
        board = self.page(f"/console/scoreboard.html#token={READ}", width=390, height=844)
        expect(board.get_by_test_id("board-score-red")).to_have_text("3")
        self.no_horizontal_scroll(board)

    # --- the field's radio channel (Settings) ------------------------------------

    def test_channel_first_setup_default_and_manual(self):
        page = self.console()
        notice = page.get_by_test_id("radio-first-setup")
        expect(notice).to_contain_text("869,525 MHz")
        page.get_by_test_id("radio-first-setup-go").click()
        expect(page.get_by_test_id("tab-settings")).to_have_text("Definições")
        expect(page.get_by_test_id("radio-channel")).to_have_text("869,525 MHz")
        expect(page.get_by_test_id("radio-limits")).to_have_text("10% do tempo · 500 mW ERP")
        expect(page.get_by_test_id("radio-source")).to_contain_text("ainda não escolhido")
        why = page.get_by_test_id("radio-why")
        why.locator("summary").click()
        expect(why).to_contain_text("869,4–869,65 MHz")
        expect(why).to_contain_text("Meshtastic")
        # (a) Keep the recommended channel: it counts as the choice.
        page.get_by_test_id("radio-keep-default").click()
        expect(page.get_by_test_id("radio-source")).to_have_text("recomendado (por omissão)")
        settings = self.field.http.get("/api/v1/radio").json()
        self.assertEqual((settings["confirmed"], settings["source"]), (True, "default"))
        page.get_by_test_id("tab-game").click()
        expect(page.get_by_test_id("radio-first-setup")).to_have_count(0)
        # (d) Pick one from the list: a 25 mW, 1% channel, with its warning.
        page.get_by_test_id("tab-settings").click()
        page.get_by_test_id("radio-manual").select_option("868300000")
        page.get_by_test_id("radio-apply-manual").click()
        expect(page.get_by_test_id("radio-channel")).to_have_text("868,300 MHz")
        expect(page.get_by_test_id("radio-limits")).to_have_text("1% do tempo · 25 mW ERP")
        expect(page.get_by_test_id("radio-low-power")).to_be_visible()
        self.assertEqual(self.field.bundle.controller.field_channel, 868_300_000)
        # The modem was retuned (SET_CHANNEL): its STATUS reports the channel.
        self.assertTrue(wait_for(lambda: (self.field.bundle.modem.status or {}).get("channel_hz")
                                 == 868_300_000, 8))
        # A game takes the channel and locks it until it ends.
        game = self.field.create_game()
        self.assertEqual(game["channel_hz"], 868_300_000)
        expect(page.get_by_test_id("radio-locked")).to_be_visible()
        expect(page.get_by_test_id("radio-keep-default")).to_be_disabled()
        expect(page.get_by_test_id("radio-apply-manual")).to_be_disabled()
        page.get_by_test_id("tab-game").click()
        expect(page.get_by_test_id("game-channel")).to_have_text("868,300 MHz")
        page.get_by_test_id("tab-join").click()
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual(j["channel_hz"], 868_300_000)
        self.field.http.post(f"/api/v1/games/{game['id']}/end", json={})
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("radio-locked")).to_have_count(0)
        expect(page.get_by_test_id("radio-keep-default")).to_be_enabled()

    def test_channel_scan_and_random_in_english(self):
        self.field.close()
        self.field = Field("--noise", "868100000:-96", "--noise", "868300000:-117:60",
                           "--noise", "869475000:-109", "--noise", "869525000:-104",
                           "--noise", "869850000:-114", "--noise-floor", "-100")
        page = self.console()
        page.get_by_test_id("lang").first.select_option("en")
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("tab-settings")).to_have_text("Settings")
        page.get_by_test_id("radio-scan").click()
        expect(page.get_by_test_id("radio-suggestion")).to_contain_text(
            "Suggested: 869.475 MHz, the quietest full-power channel", timeout=15000)
        rows = page.locator("[data-testid=radio-results] tbody tr")
        expect(rows).to_have_count(11)
        expect(rows.first).to_have_attribute("data-channel", "869850000")
        expect(rows.last).to_have_attribute("data-channel", "868300000")  # LoRa activity
        expect(page.locator('[data-testid=radio-results] tr[data-channel="869475000"]')).to_contain_text("suggested")
        self.assertEqual(self.field.bundle.controller.field_channel, 869_525_000)  # nothing changed yet
        page.get_by_test_id("radio-accept-suggestion").click()
        expect(page.get_by_test_id("radio-channel")).to_have_text("869.475 MHz")
        expect(page.get_by_test_id("radio-source")).to_have_text("from the noise scan")
        self.assertEqual(self.field.bundle.controller.field_channel, 869_475_000)
        # (c) Random: a suggestion first, with the odds; accepted on request.
        page.get_by_test_id("radio-random").click()
        result = page.get_by_test_id("radio-random-result")
        expect(result).to_contain_text("3 of 11 candidate channels give 500 mW.")
        drawn = int(float(result.locator("p").first.text_content().split()[1]) * 1e6 + 0.5)
        self.assertEqual(self.field.bundle.controller.field_channel, 869_475_000)
        page.get_by_test_id("radio-accept-random").click()
        expect(page.get_by_test_id("radio-source")).to_have_text("at random")
        self.assertEqual(self.field.bundle.controller.field_channel, drawn)
        # The choice survives a page reload (it is the controller's setting).
        page.reload()
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("radio-source")).to_have_text("at random")

    def test_channel_scan_without_a_radio(self):
        self.field.close()
        self.field = Field("--no-radio")
        page = self.console()
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("radio-scan-unavailable")).to_have_text(
            "O modem USB não tem chip de rádio, por isso não consegue medir o ruído.")
        expect(page.get_by_test_id("radio-scan")).to_be_disabled()
        expect(page.get_by_test_id("radio-channel")).to_have_text("869,525 MHz")  # the default stays
        r = self.field.http.post("/api/v1/radio/scan")
        self.assertEqual(r.status_code, 503)

    def test_box_language_follows_the_console_or_the_setting(self):
        """Join key 15 (RFC 0001 Amendment 10): with "auto" a game takes the language of the console it
        was created in; the setting in Settings fixes one for the field's next games."""
        page = self.console()  # European Portuguese by default
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("box-language-settings")).to_contain_text("Língua das caixas")
        expect(page.get_by_test_id("box-language")).to_have_value("auto")
        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-name").fill("Domingo")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        page.get_by_test_id("tab-join").click()
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual(j["lang"], "pt")
        self.field.http.post(f"/api/v1/games/{self.field.bundle.controller.game['id']}/end", json={})
        # Fixed to English in Settings: the next game's joins say so, whatever the console's language.
        page.get_by_test_id("tab-settings").click()
        page.get_by_test_id("box-language").select_option("en")
        expect(page.get_by_test_id("box-language-settings")).to_contain_text("Guardado")
        self.assertEqual(self.field.http.get("/api/v1/settings/box-language").json()["box_language"], "en")
        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-name").fill("Segunda")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        page.get_by_test_id("tab-join").click()
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual(j["lang"], "en")

    def test_channel_settings_read_only(self):
        page = self.console(READ)
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("radio-channel")).to_have_text("869,525 MHz")
        expect(page.get_by_test_id("radio-keep-default")).to_have_count(0)
        expect(page.get_by_test_id("radio-scan")).to_have_count(0)
        page.get_by_test_id("tab-game").click()
        expect(page.get_by_test_id("radio-first-setup")).to_have_count(0)

    def test_field_view_image_and_dragging(self):
        game = self.field.create_game(start=True)
        self.field.box_hello()
        page = self.console()
        page.get_by_test_id("tab-field").click()
        marker = page.locator(f'[data-testid=field-area] .marker[data-node="{BOX}"]')
        expect(marker).to_be_visible()
        expect(page.locator("[data-testid=field-area] img")).to_have_count(0)  # grid without an image
        page.get_by_test_id("field-upload").set_input_files(str(ICON))
        expect(page.locator("[data-testid=field-area] img")).to_be_visible()
        self.assertEqual(self.field.http.get("/api/v1/field").json()["image"]["content_type"], "image/png")
        marker.scroll_into_view_if_needed()
        area = page.get_by_test_id("field-area").bounding_box()  # viewport coordinates, after scrolling
        box = marker.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(area["x"] + area["width"] * 0.25, area["y"] + area["height"] * 0.6, steps=8)
        page.mouse.up()
        self.assertTrue(wait_for(lambda: str(BOX) in self.field.http.get(
            f"/api/v1/games/{game['id']}/positions").json(), 5))
        pos = self.field.http.get(f"/api/v1/games/{game['id']}/positions").json()[str(BOX)]
        self.assertAlmostEqual(pos["x"], 0.25, delta=0.03)
        self.assertAlmostEqual(pos["y"], 0.6, delta=0.03)
        # The marker stays where it was dropped, and so does a second page's.
        other = self.console()
        other.get_by_test_id("tab-field").click()
        moved = other.locator(f'[data-testid=field-area] .marker[data-node="{BOX}"]')
        expect(moved).to_have_attribute("style", re.compile(r"left: 2[45](\.\d+)?%"))

    def test_field_georeference_two_corners(self):
        """Plan phase 9 (P4R18): the GM gives two corners of the field image a latitude and longitude."""
        page = self.console()
        page.get_by_test_id("tab-field").click()
        expect(page.get_by_test_id("georef")).to_have_count(0)  # nothing to place without an image
        page.get_by_test_id("field-upload").set_input_files(str(ICON))
        expect(page.get_by_test_id("georef-none")).to_be_visible()
        expect(page.get_by_test_id("atak-status")).to_contain_text("desligado")  # [atak] enabled = false
        # A corner that is not "latitude, longitude" is refused in the page, before any request.
        page.get_by_test_id("georef-top_left-input").fill("38.7240")
        page.get_by_test_id("georef-bottom_right-input").fill("38.7200, -9.1360")
        page.get_by_test_id("georef-save").click()
        expect(page.get_by_test_id("georef-error")).to_contain_text("Canto superior esquerdo")
        self.assertIsNone(self.field.http.get("/api/v1/field/georef").json()["georef"])
        # Pasted from a map app.
        page.get_by_test_id("georef-top_left-input").fill("38.7240, -9.1420")
        page.get_by_test_id("georef-save").click()
        expect(page.get_by_test_id("georef-top_right")).to_have_text("38.724000, -9.136000")
        expect(page.get_by_test_id("georef-bottom_left")).to_have_text("38.720000, -9.142000")
        expect(page.locator("[data-testid=field-area] .georef-pin")).to_have_count(2)
        got = self.field.http.get("/api/v1/field/georef").json()["georef"]
        self.assertEqual(got["points"], [{"x": 0, "y": 0, "lat": 38.724, "lon": -9.142},
                                         {"x": 1, "y": 1, "lat": 38.72, "lon": -9.136}])
        # Another page shows the corners back, in its form too; a read-only viewer sees no form.
        other = self.console()
        other.get_by_test_id("tab-field").click()
        expect(other.get_by_test_id("georef-top_left-input")).to_have_value("38.724000, -9.142000")
        viewer = self.console(READ)
        viewer.get_by_test_id("tab-field").click()
        expect(viewer.get_by_test_id("georef-bottom_right")).to_have_text("38.720000, -9.136000")
        expect(viewer.get_by_test_id("georef-form")).to_have_count(0)
        # Removed on one page, gone from the other through the live stream.
        page.get_by_test_id("georef-remove").click()
        page.get_by_test_id("georef-remove-yes").click()
        expect(page.get_by_test_id("georef-none")).to_be_visible()
        expect(other.get_by_test_id("georef-none")).to_be_visible()
        self.assertIsNone(self.field.http.get("/api/v1/field/georef").json()["georef"])
        self.no_horizontal_scroll(page)

    def test_field_levels_a_plan_per_level(self):
        """The maintainer's request (ML-0): a multi-story building, a floor plan per level, a box on level 2,
        levels turned off with a confirmation; in pt-PT, by keyboard too, and at phone width."""
        game = self.field.create_game(start=True)
        self.field.box_hello()
        page = self.console()
        page.get_by_test_id("tab-field").click()
        marker = page.locator(f'[data-testid=field-area] .marker[data-node="{BOX}"]')
        expect(marker).to_be_visible()
        expect(page.get_by_test_id("level-tabs")).to_have_count(0)
        expect(page.get_by_label("Edifício com vários pisos")).not_to_be_checked()  # the checkbox, by its label
        page.get_by_test_id("levels-toggle").check()
        expect(page.get_by_test_id("level-tab-0")).to_have_text("R/C")
        expect(page.get_by_test_id("level-tab-1")).to_have_text("1.º andar")
        page.get_by_test_id("levels-count").select_option("3")
        expect(page.get_by_test_id("levels-name-2")).to_have_value("2.º andar")
        page.get_by_test_id("levels-save").click()
        expect(page.get_by_test_id("level-tab-2")).to_have_text("2.º andar")
        levels = self.field.http.get("/api/v1/field/levels").json()
        self.assertEqual((levels["enabled"], levels["names"]), (True, ["R/C", "1.º andar", "2.º andar"]))
        # A plan per level, each uploaded on its tab.
        for i, name in enumerate(("R/C", "1.º andar", "2.º andar")):
            page.get_by_test_id(f"level-tab-{i}").click()
            expect(page.get_by_test_id(f"level-tab-{i}")).to_have_attribute("aria-selected", "true")
            expect(page.get_by_text(f"Carregar planta: {name}")).to_be_visible()
            page.get_by_test_id("field-upload").set_input_files(str(ICON))
            expect(page.locator("[data-testid=field-area] img")).to_have_attribute("alt", f"Planta: {name}")
        view = self.field.http.get("/api/v1/field/levels").json()["levels"]
        self.assertEqual([lv["image"] is not None for lv in view], [True, True, True])
        # The box is on the ground floor: not on level 2's plan until the GM moves it there.
        expect(marker).to_have_count(0)
        page.locator("[data-testid=node-levels] summary").click()
        page.get_by_test_id(f"node-level-{BOX}").select_option("2")
        expect(marker).to_be_visible()
        self.assertTrue(wait_for(lambda: self.field.http.get(
            f"/api/v1/games/{game['id']}/positions").json().get(str(BOX), {}).get("level") == 2, 5))
        # Dragged on level 2's plan, it stays on level 2.
        marker.scroll_into_view_if_needed()
        area = page.get_by_test_id("field-area").bounding_box()
        box = marker.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(area["x"] + area["width"] * 0.3, area["y"] + area["height"] * 0.4, steps=8)
        page.mouse.up()
        self.assertTrue(wait_for(lambda: abs(self.field.http.get(f"/api/v1/games/{game['id']}/positions")
                                             .json()[str(BOX)]["x"] - 0.3) < 0.03, 5))
        self.assertEqual(self.field.http.get(f"/api/v1/games/{game['id']}/positions").json()[str(BOX)]["level"], 2)
        # The tabs by keyboard: Home goes to the ground floor, where the box is not.
        page.get_by_test_id("level-tab-2").focus()
        page.keyboard.press("Home")
        expect(page.get_by_test_id("level-tab-0")).to_have_attribute("aria-selected", "true")
        expect(page.get_by_test_id("level-tab-0")).to_be_focused()
        expect(marker).to_have_count(0)
        page.keyboard.press("ArrowLeft")
        expect(page.get_by_test_id("level-tab-2")).to_have_attribute("aria-selected", "true")
        expect(marker).to_be_visible()
        # A read-only page and a phone see the tabs and the box on its level, and no settings.
        viewer = self.console(READ, width=390, height=844)
        viewer.get_by_test_id("tab-field").click()
        expect(viewer.get_by_test_id("levels-toggle")).to_have_count(0)
        viewer.get_by_test_id("level-tab-2").click()
        expect(viewer.locator(f'[data-testid=field-area] .marker[data-node="{BOX}"]')).to_be_visible()
        self.no_horizontal_scroll(viewer)
        # Turning levels off asks first and says what is kept (the box stays ticked meanwhile); "No" keeps them.
        page.get_by_test_id("levels-toggle").click()
        expect(page.get_by_test_id("levels-confirm")).to_contain_text("Só a planta de R/C fica em uso")
        expect(page.get_by_test_id("levels-confirm")).to_contain_text("ficam guardados")
        page.get_by_test_id("levels-confirm-no").click()
        expect(page.get_by_test_id("levels-toggle")).to_be_checked()
        self.assertTrue(self.field.http.get("/api/v1/field/levels").json()["enabled"])
        page.get_by_test_id("levels-toggle").click()
        page.get_by_test_id("levels-confirm-yes").click()
        expect(page.get_by_test_id("level-tabs")).to_have_count(0)
        expect(viewer.get_by_test_id("level-tabs")).to_have_count(0)  # through the live stream
        expect(marker).to_be_visible()  # every box on the one field image
        expect(page.get_by_text("Carregar imagem do campo")).to_be_visible()
        levels = self.field.http.get("/api/v1/field/levels").json()
        self.assertEqual((levels["enabled"], levels["count"]), (False, 3))
        self.assertIsNotNone(levels["levels"][2]["image"])  # kept
        self.no_horizontal_scroll(viewer)

    def test_field_levels_in_english_and_fewer_levels(self):
        """English defaults, and fewer levels asking before their plans are deleted."""
        page = self.console()
        page.get_by_test_id("lang").select_option("en")
        page.get_by_test_id("tab-field").click()
        page.get_by_test_id("levels-toggle").check()
        expect(page.get_by_test_id("level-tab-0")).to_have_text("Ground floor")
        expect(page.get_by_test_id("level-tab-1")).to_have_text("Floor 1")
        page.get_by_test_id("level-tab-1").click()
        page.get_by_test_id("field-upload").set_input_files(str(ICON))
        expect(page.locator("[data-testid=field-area] img")).to_have_attribute("alt", "Floor plan: Floor 1")
        page.get_by_test_id("levels-name-1").fill("Mezzanine")
        page.get_by_test_id("levels-save").click()
        expect(page.get_by_test_id("level-tab-1")).to_have_text("Mezzanine")
        page.get_by_test_id("levels-count").select_option("3")
        page.get_by_test_id("levels-save").click()
        expect(page.get_by_test_id("level-tab-2")).to_be_visible()
        page.get_by_test_id("level-tab-2").click()
        page.get_by_test_id("field-upload").set_input_files(str(ICON))
        expect(page.locator("[data-testid=field-area] img")).to_have_attribute("alt", "Floor plan: Floor 2")
        page.get_by_test_id("levels-count").select_option("2")
        page.get_by_test_id("levels-save").click()
        expect(page.get_by_test_id("levels-confirm")).to_contain_text("the plans of Floor 2 are deleted")
        page.get_by_test_id("levels-confirm-yes").click()
        expect(page.get_by_test_id("level-tab-2")).to_have_count(0)
        expect(page.get_by_test_id("level-tab-0")).to_have_attribute("aria-selected", "true")
        levels = self.field.http.get("/api/v1/field/levels").json()
        self.assertEqual((levels["count"], levels["names"]), (2, ["Ground floor", "Mezzanine"]))
        self.assertIsNone(self.field.bundle.controller.store.field_image(2))

    def test_reconnects_after_the_stream_drops(self):
        self.field.create_game(start=True)
        page = self.console()
        expect(page.get_by_test_id("reconnecting")).to_have_count(0)
        hub = self.field.bundle.hub

        def drop_clients() -> None:
            for queue in list(hub._clients):
                queue.put_nowait(None)  # the server closes that client's stream (code 4408)

        hub._loop.call_soon_threadsafe(drop_clients)
        expect(page.get_by_test_id("reconnecting")).to_be_visible(timeout=3000)
        expect(page.get_by_test_id("reconnecting")).to_have_count(0, timeout=10000)
        self.assertTrue(wait_for(lambda: hub.client_count == 1, 5))
        self.field.box_hello()
        self.field.box_state(red=9)
        expect(page.get_by_test_id("score-red")).to_have_text("9")

    def test_service_worker_serves_the_shell_offline(self):
        page = self.console()
        scope = page.evaluate("navigator.serviceWorker.ready.then((r) => r.scope)")
        self.assertTrue(scope.endswith("/console/"), scope)
        cached = page.evaluate("caches.open('atalaia-console-v5').then((c) => c.keys())"
                               ".then((k) => k.map((r) => new URL(r.url).pathname))")
        for path in ("/console/app.js", "/console/lib/preact.module.js", "/console/i18n/en.json",
                     "/console/components/georef-panel.js"):
            self.assertIn(path, cached)
        # Offline, the page still opens from the cache (the API is unreachable, so
        # failed requests are expected in the console from here on).
        self.ignore_errors = True
        page.context.set_offline(True)
        page.reload()
        expect(page.locator("#app")).not_to_be_empty()
        self.assertIn("Atalaia", page.title())
        page.context.set_offline(False)


    # --- field check-in (ADR-P3-13) ------------------------------------------------

    def check_in(self, game_id: int, name: str, **extra) -> dict:
        import base64 as b64
        import secrets as sec
        pid = "p-" + "".join(sec.choice("abcdefghijklmnopqrstuvwxyz234567") for _ in range(12))
        secret = b64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode("ascii")
        r = httpx.post(self.field.base + "/api/v1/checkin", json={
            "game_id": game_id, "player_id": pid, "player_secret": secret, "display_name": name,
            "notice_version": 1, **extra}, timeout=10)
        self.assertIn(r.status_code, (200, 201), r.text)
        return r.json()

    def test_checkin_tab_follows_check_ins_live(self):
        game = self.field.create_game()
        self.field.http.put("/api/v1/checkin/settings", json={"confirm": "staff", "federation": "optional"})
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id("checkin-empty")).to_be_visible()
        expect(page.get_by_test_id("checkin-open")).to_contain_text("aberto")
        me = self.check_in(game["id"], "Coruja", federation_number="FPA-77", replicas=[
            {"declaration_id": "6f1d2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b", "type": "aeg", "class": "rifle"},
            {"declaration_id": "0a1b2c3d-4e5f-4a6b-9c7d-8e9f0a1b2c3d", "type": "bolt_action", "class": "sniper",
             "make_model": "Well MB4402"}])
        row = page.get_by_test_id(f"checkin-row-{me['player_id']}")
        expect(row.get_by_test_id("checkin-name")).to_have_text("Coruja")  # live, no reload
        expect(row).to_contain_text("à espera de confirmação")
        expect(row.get_by_test_id("checkin-replicas")).to_contain_text("2")
        expect(page.get_by_test_id("chrono-counts")).to_contain_text("por cronografar: 2")
        expect(page.get_by_test_id(f"chrono-player-{me['player_id']}")).to_contain_text("Well MB4402")
        row.get_by_test_id("checkin-confirm").click()
        expect(row).to_contain_text("com check-in")
        row.get_by_test_id("checkin-card-seen").check()
        expect(row).to_contain_text("cartão visto")
        # A game without squads: teams only, no squad picker or squad-leader role.
        expect(row.get_by_test_id("checkin-squad")).to_have_count(0)
        expect(row.locator("[data-testid=checkin-role] option[value=squad_leader]")).to_have_count(0)
        expect(page.get_by_test_id("checkin-table")).not_to_contain_text("squad")
        row.get_by_test_id("checkin-role").select_option("marshal")
        self.assertTrue(wait_for(lambda: self.field.bundle.store.checkin(game["id"], me["player_id"])["role"]
                                 == "marshal", 5))
        stored = self.field.bundle.store.checkin(game["id"], me["player_id"])
        self.assertEqual((stored["status"], stored["federation_seen"]), ("checked_in", True))
        # A player without the app, checked in by hand.
        page.get_by_test_id("checkin-manual").click()
        page.get_by_test_id("checkin-manual-name").fill("Sem Telemóvel")
        page.get_by_test_id("checkin-manual-add").click()
        page.get_by_test_id("checkin-manual-save").click()
        expect(page.get_by_test_id("checkin-table")).to_contain_text("Sem Telemóvel")
        expect(page.get_by_test_id("chrono-counts")).to_contain_text("por cronografar: 3")
        # The start warning counts the replicas still to chronograph.
        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-start").click()
        expect(page.locator(".confirm-q")).to_contain_text("3 réplica")
        page.get_by_test_id("game-start-yes").click()
        expect(page.get_by_test_id("game-state")).to_have_text("a decorrer")
        # The read token sees no check-in tab content and no names.
        read = self.console(READ)
        read.get_by_test_id("tab-checkin").click()
        expect(read.locator("main.content")).not_to_contain_text("Coruja")

    def test_a_game_from_the_schedule_and_its_registered_players(self):
        """Plan phase 16: the site server's schedule, a game made from it, the roster's players expected."""
        import hashlib
        import uuid

        from atalaia_controller import checkin_ticket

        class Sync:  # the sync client's part the console sees; no site server in this test
            def kick(self) -> None:
                pass

            def status(self) -> dict:
                return {"enabled": True}

        ctrl = self.field.bundle.controller
        ctrl.sync = Sync()
        sid = "0192f3a4-0000-7000-8000-00000000a001"
        now = __import__("time").time()
        self.field.bundle.store.set_schedule([{
            "scheduled_game_id": sid, "title": "Domingo no pinhal", "starts_at": now + 3600, "ends_at": now + 4 * 3600,
            "status": "published", "mode_id": DOMINATION, "teams": ["red", "blue"], "federation": "off",
            "predeclare_replicas": True, "registered": 2}], now)
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id(f"schedule-{sid}")).to_contain_text("Domingo no pinhal")
        expect(page.get_by_test_id(f"schedule-{sid}")).to_contain_text("2 inscrições")
        page.get_by_test_id("schedule-create").click()
        self.assertTrue(wait_for(lambda: self.field.bundle.store.schedule_links(), 5))
        gid = self.field.bundle.store.schedule_links()[0]["game_id"]
        raw = os.urandom(32)
        regs = [{"registration_id": str(uuid.uuid4()), "player_id": pid, "display_name": name,
                 "ticket_sha256": hashlib.sha256(raw).hexdigest() if name == "Mocho" else None,
                 "replicas": [{"declaration_id": str(uuid.uuid4()), "type": "aeg", "class": "rifle"}]}
                for pid, name in (("p-falcaofalcao", "Falcão"), ("p-mochomochomo", "Mocho"))]
        regs[0].pop("ticket_sha256")
        ctrl.checkin.apply_roster(gid, {"registrations": regs})
        row = page.get_by_test_id("checkin-row-p-falcaofalcao")
        expect(row).to_contain_text("por chegar")  # the roster message reloads the tab
        expect(row.get_by_test_id("checkin-registered-badge")).to_be_visible()
        expect(page.get_by_test_id("checkin-registered")).to_contain_text("2 por chegar")
        expect(page.get_by_test_id("chrono-counts")).to_contain_text("por cronografar: 2")
        row.get_by_test_id("checkin-arrived").click()
        expect(row).to_contain_text("com check-in")
        ticket = checkin_ticket.make({"registration_id": regs[1]["registration_id"], "player_id": "p-mochomochomo",
                                      "secret": raw})
        page.get_by_test_id("ticket-input").fill(ticket)
        page.get_by_test_id("ticket-submit").click()
        expect(page.get_by_test_id("checkin-row-p-mochomochomo")).to_contain_text("com check-in")
        self.check_in(gid, "Zé")
        expect(page.get_by_test_id("checkin-registered")).to_contain_text("2 já chegaram · sem inscrição: 1")

    def test_checkin_tab_with_squads(self):
        page = self.console()
        page.get_by_test_id("game-name").fill("Milsim")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        page.get_by_test_id("game-squads").fill("2")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual(game["squads"], 2)
        expect(page.locator("dl.facts")).to_contain_text("2 squads por equipa")
        me = self.check_in(game["id"], "Lince")
        page.get_by_test_id("tab-checkin").click()
        row = page.get_by_test_id(f"checkin-row-{me['player_id']}")
        expect(page.get_by_test_id("checkin-table")).to_contain_text("Equipa › squad")
        expect(row.get_by_test_id("checkin-squad")).to_have_count(0)  # a squad is inside a team
        row.get_by_test_id("checkin-team").select_option("blue")
        expect(row.get_by_test_id("checkin-squad")).to_be_visible()
        row.get_by_test_id("checkin-squad").select_option("2")
        row.get_by_test_id("checkin-role").select_option("squad_leader")
        self.assertTrue(wait_for(lambda: self.field.bundle.store.checkin(game["id"], me["player_id"])["role"]
                                 == "squad_leader", 5))
        stored = self.field.bundle.store.checkin(game["id"], me["player_id"])
        self.assertEqual((stored["team"], stored["squad"]), (2, 2))

    def test_poster_renders_a_qr_code_with_the_poster_text(self):
        if not ZBARIMG:
            self.skipTest("zbarimg is not installed")
        self.field.create_game()
        self.field.http.put("/api/v1/checkin/poster", json={"wifi_ssid": "Atalaia Campo"})
        expected = self.field.http.get("/api/v1/checkin/poster").json()
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id("poster-ca")).to_have_text(expected["ca_short"])
        with page.expect_popup() as popup:
            page.get_by_test_id("checkin-poster-link").click()
        poster = popup.value
        poster.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        expect(poster.get_by_test_id("poster-qr")).to_be_visible()
        expect(poster.get_by_test_id("poster-field")).to_have_text(expected["field_name"])
        expect(poster.get_by_test_id("poster-ca-short")).to_have_text(expected["ca_short"])
        expect(poster.locator("#step1-pt")).to_contain_text("Atalaia Campo")
        with tempfile.TemporaryDirectory() as tmp:
            shot = os.path.join(tmp, "poster.png")
            poster.get_by_test_id("poster-qr").screenshot(path=shot)
            out = read_qr(shot)
        self.assertEqual(out.returncode, 0, out.stderr)
        text = out.stdout
        self.assertEqual(text, expected["text"])
        decoded = checkin_poster.parse(text)
        self.assertEqual(decoded["ca_sha256"], self.field.bundle.tls.ca_sha256)
        self.assertEqual(decoded["wifi_ssid"], "Atalaia Campo")
        # The Wi-Fi code, drawn from a password that is not kept.
        poster.get_by_test_id("poster-wifi-pass").fill("segredo;1")
        poster.get_by_test_id("poster-wifi-draw").click()
        expect(poster.get_by_test_id("poster-wifi-svg")).to_be_visible()
        self.assertEqual(poster.get_by_test_id("poster-wifi-pass").input_value(), "")
        with tempfile.TemporaryDirectory() as tmp:
            shot = os.path.join(tmp, "wifi.png")
            poster.get_by_test_id("poster-wifi-svg").screenshot(path=shot)
            out = read_qr(shot)
        self.assertEqual(out.stdout, "WIFI:T:WPA;S:Atalaia Campo;P:segredo\\;1;;")
        self.assertNotIn("segredo", self.field.http.get("/api/v1/checkin/poster").text)
        # A phone-sized window has no sideways scroll; printing hides the tools.
        poster.set_viewport_size({"width": 390, "height": 844})
        self.no_horizontal_scroll(poster)
        poster.emulate_media(media="print")
        expect(poster.get_by_test_id("poster-print")).to_be_hidden()

    # --- field and team branding (decisions BR1-BR24) -------------------------------

    def loaded(self, locator) -> None:
        """The image is shown and the browser decoded it."""
        expect(locator).to_be_visible()
        self.assertTrue(wait_for(lambda: locator.evaluate("img => img.complete && img.naturalWidth > 0"), 5),
                        "the image did not decode")

    def forget_refusal(self, path: str) -> None:
        """A refusal the test asked for is not a page error."""
        self.errors = [e for e in self.errors if path not in e and "status of 4" not in e]

    def test_field_branding_from_settings_to_header_scoreboard_and_poster(self):
        if not ZBARIMG:
            self.skipTest("zbarimg is not installed")
        page = self.console()
        expect(page.get_by_test_id("header-logo")).to_have_count(0)  # the default look
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("branding-rights")).to_contain_text("responsabilidade")
        page.get_by_test_id("branding-name").fill("Campo Norte")
        page.get_by_test_id("branding-accent").fill("#c0ffee")
        page.get_by_test_id("branding-save").click()
        expect(page.get_by_test_id("header-field-name")).to_have_text("Campo Norte")
        accent = page.get_by_test_id("header").evaluate("h => getComputedStyle(h).getPropertyValue('--accent')")
        self.assertEqual(accent.strip(), "#c0ffee")
        self.assertEqual(self.field.http.get("/api/v1/checkin/poster").json()["field_name"], "Campo Norte")
        # Uploads: a logo with metadata (stripped by the controller) and a WebP wallpaper.
        page.get_by_test_id("branding-logo-upload").set_input_files(str(BRANDING / "logo.png"))
        self.loaded(page.get_by_test_id("branding-logo-img"))
        self.loaded(page.get_by_test_id("header-logo"))
        page.get_by_test_id("branding-wallpaper-upload").set_input_files(str(BRANDING / "wallpaper.webp"))
        self.loaded(page.get_by_test_id("branding-wallpaper-img"))
        served = httpx.get(self.field.base + "/api/v1/field/branding/logo")  # no token
        self.assertEqual(served.status_code, 200)
        self.assertNotIn(b"Someone Private", served.content)
        # Refused in the page (SVG, GIF: never sent) and by the controller (8x8 pixels).
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp) / "logo.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>')
            page.get_by_test_id("branding-logo-upload").set_input_files(str(svg))
            expect(page.get_by_test_id("toast")).to_contain_text("PNG, JPEG ou WebP")
            page.get_by_test_id("branding-logo-upload").set_input_files(str(BRANDING / "not-allowed.gif"))
            expect(page.get_by_test_id("toast")).to_contain_text("PNG, JPEG ou WebP")
            page.get_by_test_id("branding-logo-upload").set_input_files(str(BRANDING / "animated.png"))
            expect(page.get_by_test_id("toast")).to_contain_text("animated PNG")
            self.forget_refusal("/field/branding/logo")
        self.loaded(page.get_by_test_id("header-logo"))  # the earlier logo stays
        # Another page (the login screen, before any token) shows it at once.
        login = self.page()
        self.loaded(login.get_by_test_id("login-logo"))
        expect(login.get_by_test_id("login-field")).to_have_text("Campo Norte")
        # The scoreboard: the logo and name above the game, the wallpaper behind it.
        self.field.create_game(name="Final", start=True)
        board = self.page(f"/console/scoreboard.html#token={READ}")
        self.loaded(board.get_by_test_id("board-logo"))
        expect(board.get_by_test_id("board-field-name")).to_have_text("Campo Norte")
        self.assertTrue(board.evaluate("document.body.classList.contains('with-wallpaper')"))
        self.assertIn("/api/v1/field/branding/wallpaper",
                      board.evaluate("getComputedStyle(document.body).backgroundImage"))
        # The poster: the logo above the field's name, and the QR code still reads back.
        expected = self.field.http.get("/api/v1/checkin/poster").json()
        poster = page.context.new_page()  # the console's context: the poster uses its GM token
        poster.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        poster.goto(self.field.base + "/console/poster.html")
        self.loaded(poster.get_by_test_id("poster-logo"))
        expect(poster.get_by_test_id("poster-field")).to_have_text("Campo Norte")
        with tempfile.TemporaryDirectory() as tmp:
            for target in ("poster-qr", None):
                shot = os.path.join(tmp, "poster.png")
                (poster.get_by_test_id(target) if target else poster.locator("#poster")).screenshot(path=shot)
                out = read_qr(shot)
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertEqual(out.stdout, expected["text"], target or "the whole poster")
        poster.set_viewport_size({"width": 390, "height": 844})
        self.no_horizontal_scroll(poster)
        # Removing the logo brings the default look back, live.
        page.get_by_test_id("branding-logo-remove").click()
        expect(page.get_by_test_id("header-logo")).to_have_count(0)
        expect(board.get_by_test_id("board-logo")).to_have_count(0)

    def test_team_presets_and_a_game_with_crests(self):
        page = self.console()
        page.get_by_test_id("tab-settings").click()
        page.get_by_test_id("team-preset-name").fill("Lobos")
        page.get_by_test_id("team-preset-colour").select_option("red")
        page.get_by_test_id("team-preset-crest").set_input_files(str(BRANDING / "crest-red.png"))
        self.loaded(page.get_by_test_id("team-preset-crest-img"))
        page.get_by_test_id("team-preset-add").click()
        self.assertTrue(wait_for(lambda: self.field.http.get("/api/v1/team-presets").json(), 5))
        preset = self.field.http.get("/api/v1/team-presets").json()[0]
        self.assertEqual((preset["name"], preset["colour"]), ("Lobos", "red"))
        self.loaded(page.get_by_test_id(f"team-preset-{preset['id']}").locator("img"))
        # A game: red from the saved team, blue with its own name and crest.
        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-name").fill("Sábado")
        page.get_by_test_id("game-team-branding").locator("summary").click()
        page.get_by_test_id("game-team-preset-red").select_option(label="Lobos")
        self.loaded(page.get_by_test_id("game-team-crest-img-red"))
        page.get_by_test_id("game-team-name-blue").fill("Águias")
        page.get_by_test_id("game-team-crest-blue").set_input_files(str(BRANDING / "crest-blue.webp"))
        self.loaded(page.get_by_test_id("game-team-crest-img-blue"))
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_be_visible()
        game = self.field.http.get("/api/v1/games").json()[-1]
        self.assertEqual(game["teams"], ["red", "blue"])
        self.assertEqual(game["team_info"]["red"]["team_preset_id"], preset["id"])
        self.assertEqual(game["team_info"]["red"]["display_name"], "Lobos")
        self.assertEqual(game["team_info"]["blue"]["display_name"], "Águias")
        self.assertIn("crest_id", game["team_info"]["blue"])
        expect(page.get_by_test_id("game-teams-list")).to_have_text("Lobos (red), Águias (blue)")
        scores = page.get_by_test_id("scores")
        expect(scores).to_contain_text("Lobos")
        self.loaded(scores.locator('[data-team="blue"] img'))
        # A name changed while the game is ready, from the game card.
        page.get_by_test_id("teams-editor").locator("summary").click()
        page.get_by_test_id("live-team-name-blue").fill("Águias Negras")
        page.get_by_test_id("teams-save").click()
        expect(scores).to_contain_text("Águias Negras")
        self.assertEqual(self.field.http.get(f"/api/v1/games/{game['id']}/teams").json()["teams"][1]["display_name"],
                         "Águias Negras")
        # The scoreboard: crests and names, live; the colours stay.
        self.field.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True})
        board = self.page(f"/console/scoreboard.html#token={READ}&lang=en")
        expect(board.get_by_test_id("board-name-red")).to_have_text("Lobos")
        self.loaded(board.get_by_test_id("board-crest-red"))
        self.loaded(board.get_by_test_id("board-crest-blue"))
        self.field.box_hello()
        self.field.box_state(red=20, blue=35)
        expect(board.get_by_test_id("board-score-blue")).to_have_text("35")
        self.field.http.post(f"/api/v1/games/{game['id']}/end", json={})
        expect(board.get_by_test_id("board-result")).to_have_text("Águias Negras wins")
        # Phone width: the settings and the game form with team rows do not scroll sideways.
        phone = self.console(width=390, height=844)
        phone.get_by_test_id("tab-settings").click()
        phone.wait_for_timeout(150)
        self.no_horizontal_scroll(phone)
        phone.get_by_test_id("tab-game").click()
        phone.get_by_test_id("game-team-branding").locator("summary").click()
        phone.wait_for_timeout(150)
        self.no_horizontal_scroll(phone)
        board.set_viewport_size({"width": 390, "height": 844})
        self.no_horizontal_scroll(board)

    def test_read_token_sees_branding_without_controls(self):
        self.field.http.put("/api/v1/field/branding/logo", content=(BRANDING / "logo.jpg").read_bytes(),
                            headers={"Content-Type": "image/jpeg"})
        page = self.console(READ)
        self.loaded(page.get_by_test_id("header-logo"))
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("branding-settings")).to_contain_text("Só a organização")
        expect(page.get_by_test_id("branding-form")).to_have_count(0)
        expect(page.get_by_test_id("branding-logo-upload")).to_have_count(0)
        expect(page.get_by_test_id("team-preset-form")).to_have_count(0)
        self.loaded(page.get_by_test_id("branding-logo-img"))


BRANDING = CONTROLLER / "tests" / "fixtures" / "branding"


if __name__ == "__main__":
    unittest.main()
