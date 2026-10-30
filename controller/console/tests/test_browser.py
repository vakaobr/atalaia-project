# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
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
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
CONTROLLER = HERE.parents[1]
sys.path.insert(0, str(CONTROLLER / "tests"))

from support import (BOX_HOST, CORE, MESSAGE_TYPES, MODEM_HOST, AirHub, BoxHost, HostModem,  # noqa: E402
                     config, free_port, node_packet, packet_decrypt, wait_for)

import httpx  # noqa: E402
import uvicorn  # noqa: E402

from atalaia_controller import checkin_poster  # noqa: E402
from atalaia_controller.addresses import FieldAddresses  # noqa: E402
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
# Load the field from a map (MF-19 to MF-30): the network is never reached; OSM's tiles, the Overpass API
# and the DGT's WMS answer with these made-up fixtures.
FIXTURES = HERE / "fixtures"
CORS = {"Access-Control-Allow-Origin": "*"}
OUTLINE = [(39.6015, -8.4030), (39.6012, -8.3990), (39.5990, -8.3985), (39.5984, -8.4010), (39.5995, -8.4035)]
# The open orthophotos' origins (api.py FIELD_MAP_ORTHOPHOTOS, its WMS, and FIELD_MAP_ORTHO_TILES, WMTS on
# origins of their own; MF-65 to MF-80), every one answered by a fixture.
ORTHO_WMS_ORIGINS = (
    "https://ortos.dgterritorio.gov.pt", "https://www.ign.es", "https://data.geopf.fr", "https://service.pdok.nl",
    "https://wms.ngi.be", "https://geo.api.vlaanderen.be", "https://geoservices.wallonie.be",
    "https://wms.geoportail.lu", "https://wms.geo.admin.ch", "https://gdi.berlin.de", "https://isk.geobasis-bb.de",
    "https://geoservices.bayern.de", "https://geodienste.bremen.de", "https://www.gds-srv.hessen.de",
    "https://www.geodaten-mv.de", "https://www.wms.nrw.de", "https://geo4.service24.rlp.de",
    "https://geoportal.saarland.de", "https://geodienste.sachsen.de", "https://www.geoproxy.geoportal-th.de",
    "https://mapy.geoportal.gov.pl", "https://ags.cuzk.gov.cz")
ORTHO_TILE_ORIGINS = ("https://wmts1.geoportail.lu", "https://wmts.geo.admin.ch", "https://www.wmts.nrw.de")
ORTHO_ORIGINS = ORTHO_WMS_ORIGINS + ORTHO_TILE_ORIGINS


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
        addrs = FieldAddresses.current(cfg.tls_names, cfg.tls_port, extra_interfaces=cfg.tls_names)
        self.bundle = build(cfg, core=CORE, load_core_lib=False, addresses=addrs)
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

    def box_hello(self, fw: str = "0.3.0", device: "bytes | None" = None, platform: int = 1) -> None:
        fields = {"node_name": "box-7", "platform": platform, "fw_version": fw, "core_version": "0.2.0", "tier": 0,
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
        # atalaia-field.test is a name that is not the controller's own loopback (as the Pi's address is for a
        # laptop on the field), but reaches this test's controller.
        cls.browser = cls.pw.chromium.launch(args=["--host-resolver-rules=MAP atalaia-field.test 127.0.0.1"])

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

    def page(self, path: str = "/console/", width: int = 1280, height: int = 900, setup=None,
             poster_prompt: bool = False, **ctx_kw):
        ctx = self.browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=2, **ctx_kw)
        self.contexts.append(ctx)
        if not poster_prompt:
            # "Print the check-in poster?" (check-R10) covers the page for ten seconds after a game is
            # created; the tests that are not about it have chosen "Don't show this again".
            ctx.add_init_script("try { localStorage.setItem('atalaia.posterPrompt', 'off'); } catch (e) {}")
        page = ctx.new_page()
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: self.errors.append(f"console: {m.text}") if m.type == "error" else None)
        page.on("response", lambda r: self.errors.append(f"HTTP {r.status} {r.request.method} {r.url}")
                if r.status >= 400 else None)
        if setup is not None:
            setup(page)  # routes or listeners before the first request
        page.goto(self.field.base + path)
        return page

    def console(self, token: str = GM, **kw):
        page = self.page(**kw)
        page.get_by_test_id("token").fill(token)
        page.get_by_test_id("login").click()
        expect(page.get_by_test_id("tab-game")).to_be_visible()
        return page

    def drop_errors(self, *needles: str) -> None:
        """Forgets the console's reports of failures a test caused on purpose (a busy server, no answer)."""
        self.errors = [e for e in self.errors if not any(n in e for n in needles)]

    def no_horizontal_scroll(self, page) -> None:
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        self.assertLessEqual(width[0], width[1], "the page scrolls sideways")

    # --- tests ----------------------------------------------------------------

    def test_login_on_plain_http_from_another_machine_sends_no_code_and_says_where_to_go(self):
        # FLD-4: the GM code is refused over HTTP, so the console does not even send it; it says the https address.
        ctx = self.browser.new_context()
        self.contexts.append(ctx)
        page = ctx.new_page()
        asked: list[str] = []
        page.on("request", lambda r: asked.append(r.url))
        page.goto(f"http://atalaia-field.test:{self.field.port}/console/")
        page.get_by_test_id("token").fill(GM)
        page.get_by_test_id("login").click()
        expect(page.get_by_role("alert")).to_contain_text("https://atalaia-field.test:8443/console/")
        self.assertFalse([u for u in asked if "/api/v1/whoami" in u], "the code was sent over plain HTTP")
        self.assertTrue([u for u in asked if u.endswith("/api/v1/controller/https")])
        # The same page on the controller's own address (what every other test does) logs in as before.

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

    def test_signed_mode_packages_in_the_presets_tab(self):
        """Signed mode packages (phase 5 plan phase 6, protocol/mode-packages.md): the GM uploads a
        package signed with a trusted mode key, then installs one from the field's registry index;
        each shows who signed it and whether the project reviewed it, in both languages, and a
        phone-width page does not scroll sideways."""
        from test_signed_modes import KEY, OTHER_SIGNING, package  # noqa: PLC0415

        registry = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, registry, True)
        (registry / "packages").mkdir()
        entries = []
        for (archive, release), verified in ((package("org.club.second"), True),
                                             (package("org.club.foreign", key=OTHER_SIGNING), False)):
            name = f"{release['id']}.tar"
            (registry / "packages" / name).write_bytes(archive)
            entries.append({"id": release["id"], "name": release["id"].split(".")[-1].title(), "author": "A club",
                            "versions": [{**{k: release[k] for k in ("version", "kind", "min_tier", "size", "sha256",
                                                                      "signature", "key_id", "license")},
                                          "url": f"packages/{name}", "verified": verified}]})
        (registry / "index.json").write_text(json.dumps({"schema_version": 1, "modes": entries}))
        (registry / "revoked.json").write_text(json.dumps({"schema_version": 1, "keys": []}))  # FLD-7: a missing list refuses installs
        self.field.close()
        self.field = Field(cfg={"modes_keys": [KEY["public_key_b64"]], "modes_index": str(registry / "index.json")})

        archive, release = package()
        files = Path(self.field.tmp.name)
        (files / "tagger.tar").write_bytes(archive)
        (files / "tagger.tar.release.json").write_text(json.dumps(release))

        page = self.console()
        page.get_by_test_id("tab-presets").click()
        panel = page.get_by_test_id("mode-packages")
        expect(panel).to_contain_text("Pacotes de modos assinados")
        expect(page.get_by_test_id("packages-keys")).to_contain_text(KEY["key_id"])
        page.get_by_test_id("packages-archive").set_input_files(str(files / "tagger.tar"))
        page.get_by_test_id("packages-release").set_input_files(str(files / "tagger.tar.release.json"))
        page.get_by_test_id("packages-upload").click()
        signed = page.get_by_test_id("packages-signed-org.club.tagger")
        expect(signed).to_contain_text(KEY["key_id"])
        expect(signed).to_contain_text("não revisto pelo projeto")
        # The new mode is offered for presets and games at once (the stream's "modes").
        self.assertIn("org.club.tagger", [m["id"] for m in self.field.http.get("/api/v1/modes").json()])

        # From the index: a package signed by a trusted key installs; one signed by another does not.
        expect(page.get_by_test_id("packages-entry-org.club.foreign")).to_contain_text(
            "assinado com uma chave em que este controlador não confia")
        page.get_by_test_id("packages-install-org.club.second").click()
        expect(page.get_by_test_id("packages-entry-org.club.second")).to_contain_text("instalado")
        expect(page.get_by_test_id("packages-signed-org.club.second")).to_contain_text("revisto pelo projeto")
        page.get_by_test_id("lang").first.select_option("en")
        expect(page.get_by_test_id("packages-signed-org.club.tagger")).to_contain_text("not reviewed by the project")
        expect(page.get_by_test_id("packages-entry-org.club.second")).to_contain_text("installed")

        # A read token sees no such panel; a phone-width page fits.
        reader = self.console(token=READ, width=390, height=800)
        reader.get_by_test_id("tab-presets").click()
        expect(reader.get_by_test_id("mode-packages")).to_have_count(0)
        phone = self.console(width=390, height=800)
        phone.get_by_test_id("tab-presets").click()
        expect(phone.get_by_test_id("mode-packages")).to_be_visible()
        self.no_horizontal_scroll(phone)

    def test_send_missing_modes_from_the_invite_dialog(self):
        """Phase 5 plan phase 13a (protocol/mode-packages.md, "Fetching missing modes"): a box that
        lacks the game's signed mode answers "no mode"; next to it the dialog names the part and
        offers "Send missing modes"; the box, invited again with join key 16, fetches the package
        from the controller, checks it with the keys of its firmware, reports and says HELLO; the
        game waits for it meanwhile. The Boxes tab lists what the box keeps and marks it to forget
        them (join key 17). In pt-PT and English, and at phone width."""
        from test_mode_fetch import BUILTIN, TAGGER  # noqa: PLC0415
        from test_signed_modes import KEY  # noqa: PLC0415

        from atalaia_controller import mode_package as mp  # noqa: PLC0415

        box, device, hexid, deliver_invite = self.box_lacking_a_mode()
        page = self.console()
        page.get_by_test_id("game-name").fill("Domingo")
        page.get_by_test_id("game-source").select_option(f"mode:{TAGGER}")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("invite-dialog")).to_be_visible()
        self.field.host.transmitted_all()  # what the modem sent so far (the DISCOVER, TIME)
        page.get_by_test_id("invite-send").click()
        deliver_invite(1000)
        status = page.get_by_test_id(f"invite-status-{hexid}")
        expect(status).to_have_text("recusou: o modo não está na caixa")
        missing = page.get_by_test_id(f"invite-missing-{hexid}")
        expect(missing).to_contain_text("Modos que faltam a esta caixa")
        expect(page.get_by_test_id(f"invite-part-{hexid}-{TAGGER}")).to_have_text("Tagger 0.1.0: pode ser enviado")
        page.get_by_test_id(f"invite-fetch-{hexid}").click()
        deliver_invite(20_000)
        self.assertEqual((box.phase, box.fetching), ("joined", [TAGGER]))
        self.assertTrue(box.game["fetch_modes"])
        expect(status).to_have_text("a obter os modos em falta por Wi-Fi")
        expect(page.get_by_test_id("invite-fetch-wait")).to_contain_text("O jogo espera pelas caixas")
        # Until it says HELLO, the game waits for it.
        game = self.field.bundle.controller.game
        self.assertEqual(self.field.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True}).status_code,
                         409)

        # The box fetches (over HTTPS pinned to the field CA on a real box), checks, keeps, reports.
        text = httpx.get(f"{self.field.base}/api/v1/mode-packages/{TAGGER}/release")
        rel, _ = mp.box_check_release(text.content, TAGGER, [KEY["public_key_b64"]], "full", BUILTIN)
        got = httpx.get(f"{self.field.base}/api/v1/mode-packages/{TAGGER}/package")
        self.assertIn("node.lua", mp.box_check_archive(got.content, rel))
        box.fetched_part(TAGGER, rel.version)
        j = box.game
        body = mp.report_body(j["game_id"], j["node_id"], TAGGER, rel.version, "installed", box.fetched)
        r = httpx.post(f"{self.field.base}/api/v1/mode-packages/report", content=body,
                       headers={"X-Atalaia-Mac": mp.report_mac(j["game_key"], body)})
        self.assertEqual(r.json(), {"accepted": True})
        expect(status).to_have_text("modos instalados, a juntar-se")
        self.field.host.hear(node_packet(j["game_key"], j["game_id"], j["node_id"], 0, 1, "HELLO",
                                         self.fetching_hello(device), ack=True))
        expect(status).to_have_text("juntou-se")
        expect(page.get_by_test_id("invite-fetch-wait")).to_have_count(0)
        expect(page.get_by_test_id("invite-ready")).to_be_visible()
        page.get_by_test_id("invite-close").click()

        # The Boxes tab: what the box keeps, and "forget them at its next invite".
        page.get_by_test_id("lang").first.select_option("en")
        page.get_by_test_id("tab-nodes").click()
        kept = page.get_by_test_id(f"fetched-{hexid}")
        expect(kept).to_contain_text(f"{TAGGER} 0.1.0")
        expect(kept).to_contain_text(f"game {j['game_id']}, node {j['node_id']}")
        expect(page.get_by_test_id("fetched-keys")).to_contain_text(KEY["key_id"])
        page.get_by_test_id(f"fetched-forget-{hexid}").click()
        expect(kept).to_contain_text("Forgets them at its next invite")
        self.assertEqual(self.field.bundle.controller.mode_fetch.forget_marked(), [hexid])

        # At phone width: the dialog and the Boxes tab do not scroll sideways.
        phone = self.console(width=390, height=800)
        phone.get_by_test_id("tab-nodes").click()
        expect(phone.get_by_test_id("fetched-modes")).to_be_visible()
        self.no_horizontal_scroll(phone)
        phone.get_by_test_id("tab-game").click()
        phone.get_by_test_id("game-invite").click()
        expect(phone.get_by_test_id("invite-dialog")).to_be_visible()
        self.no_horizontal_scroll(phone)

    def test_a_fetch_that_failed_over_the_radio_after_its_hello(self):
        """Found on the bench (2026-10-23, decisions P5D-14 to P5D-17): a box invited with key 16
        that cannot reach the controller over HTTPS says HELLO in the game, then node.modes_failed
        over the radio, then leaves the join (P5E-8). The dialog does not show it joined: after its
        HELLO it says the box has not reported its modes, the game still waits; after the event, why
        the fetch failed, the game no longer waits, and once the box announces itself again the
        dialog offers "Send missing modes" again."""
        from test_mode_fetch import TAGGER  # noqa: PLC0415

        box, device, hexid, deliver_invite = self.box_lacking_a_mode()
        game = self.field.create_game("Domingo", mode_id=TAGGER)
        page = self.console()
        page.get_by_test_id("game-invite").click()
        expect(page.get_by_test_id("invite-dialog")).to_be_visible()
        self.field.host.transmitted_all()
        r = self.field.http.post(f"/api/v1/games/{game['id']}/invites",
                                 json={"boxes": [{"device_id": hexid, "role": "zone", "fetch_modes": True}]})
        self.assertEqual(r.status_code, 200, r.text)
        deliver_invite(1000)
        self.assertEqual((box.phase, box.fetching), ("joined", [TAGGER]))
        status = page.get_by_test_id(f"invite-status-{hexid}")
        expect(status).to_have_text("a obter os modos em falta por Wi-Fi")
        # Its HELLO, with no report: not joined; the game still waits for it.
        j = box.game
        self.field.host.hear(node_packet(j["game_key"], j["game_id"], j["node_id"], 0, 1, "HELLO",
                                         self.fetching_hello(device), ack=True))
        expect(status).to_have_text("disse HELLO sem relatório dos modos: à espera de notícias da caixa")
        expect(page.get_by_test_id("invite-fetch-wait")).to_be_visible()
        expect(page.get_by_test_id("invite-ready")).to_have_count(0)
        # node.modes_failed (unreachable), then it leaves the join.
        event = {"node": j["node_id"], "seq": 0, "t": 0, "type": "node.modes_failed",
                 "data": {"mode": TAGGER, "reason": "unreachable"}}
        self.field.host.hear(node_packet(j["game_key"], j["game_id"], j["node_id"], 1, 1, "EVENT",
                                         codec.encode_event(event), ack=True))
        expect(status).to_have_text("não conseguiu obter os modos: não chegou a este controlador por HTTPS")
        expect(status).to_have_class(re.compile(r"\berror\b"))
        expect(page.get_by_test_id("invite-fetch-wait")).to_have_count(0)
        expect(page.get_by_test_id("invite-ready")).to_have_count(0)
        fetch = self.field.http.get("/api/v1/mode-fetch").json()["fetches"][0]
        self.assertEqual((fetch["state"], fetch["reason"]), ("failed", "unreachable"))
        # Free again, it announces itself: "Send missing modes" is offered again.
        box.fetch_failed(30_000)
        self.field.host.hear(ff.encode(ff.field_key(JOIN_KEY), box._announce(), box.nonces.next()))
        expect(page.get_by_test_id(f"invite-fetch-{hexid}")).to_be_visible()
        expect(page.get_by_test_id(f"invite-box-{hexid}")).to_be_enabled()

    def fetching_hello(self, device: bytes) -> bytes:
        return hello_encode({"node_name": "Zona Norte", "platform": 1, "fw_version": "0.5.0", "core_version": "0.2.0",
                             "tier": 0, "capabilities": [0], "transports": 1, "epoch": 1, "device_id": device})

    def box_lacking_a_mode(self):
        """A controller offering the club's signed mode to boxes, and a box that played a game of
        Domination and is free again without that mode: (box, device id, its hex, deliver_invite)."""
        from test_mode_fetch import BUILTIN  # noqa: PLC0415
        from test_signed_modes import KEY, package, query  # noqa: PLC0415

        self.field.close()
        self.field = Field(cfg={"modes_keys": [KEY["public_key_b64"]], "modes_box_keys": [KEY["public_key_b64"]]})
        archive, release = package()
        r = self.field.http.post("/api/v1/mode-packages", params=query(release), content=archive,
                                 headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(r.status_code, 201, r.text)
        # A box that played a game of Domination, free again, without the club's mode.
        device = bytes.fromhex("5a17c0de0b0e1234")
        hexid = device.hex()
        key = ff.field_key(JOIN_KEY)
        first = self.field.create_game("Sábado", assignments={str(BOX): "zone"})
        self.field.box_hello(device=device)
        self.assertTrue(wait_for(lambda: self.field.bundle.controller.start_check()["ok"], 5))
        self.assertEqual(self.field.http.post(f"/api/v1/games/{first['id']}/start").status_code, 200)
        self.assertEqual(self.field.http.post(f"/api/v1/games/{first['id']}/end", json={}).status_code, 200)
        box = lobby.IdleBox(JOIN_KEY, "Zona Norte", device_id=device, rng=random.Random(2), installed=set(BUILTIN))
        box.last_game, box.last_role = first["id"], "zone"
        self.field.host.hear(ff.encode(key, box._announce(), box.nonces.next()))
        self.assertTrue(wait_for(lambda: hexid in self.field.bundle.controller.reinvite.inviter.boxes, 5))

        def deliver_invite(now_ms: int) -> None:
            """The invite's parts reach the box; its answer reaches the controller."""
            parts: list[bytes] = []

            def heard() -> bool:
                for f in self.field.host.transmitted_all(0.2):
                    if ff.is_frame(f) and ff.decode(key, f)["kind"] == "invite":
                        parts.append(f)
                return bool(parts) and len(parts) >= ff.decode(key, parts[0])["parts"]
            self.assertTrue(wait_for(heard, 5))
            for f in parts:
                box.on_frame(f, now_ms)
            for answer in box.tick(now_ms + 9_000):
                self.field.host.hear(answer)
        return box, device, hexid, deliver_invite

    def test_pod_settings_from_the_boxes_tab(self):
        """The I/O pod's settings over the radio (protocol/pod-config.md): the GM sets a phone's pod in
        the Boxes tab before the game starts; CMD pod (opcode 10) goes on the air to that phone's node
        id; the phone's node.setup_applied shows it taken, in both languages."""
        ctrl = self.field.bundle.controller
        game = self.field.create_game()
        self.field.box_hello("app-0.5.0", platform=3)  # a phone: only a phone has an I/O pod
        page = self.console()
        page.get_by_test_id("tab-nodes").click()
        expect(page.get_by_test_id("pod-config-panel")).to_contain_text("Definições dos módulos de E/S")
        expect(page.get_by_test_id("pod-config-nodes")).to_contain_text(str(BOX))
        send = page.get_by_test_id(f"pod-send-{BOX}")
        send.click()  # nothing chosen: refused on the page, nothing goes on the air
        expect(page.get_by_test_id("toast")).to_contain_text("Escolhe pelo menos uma definição")
        page.get_by_test_id(f"pod-setbtn-{BOX}").check()
        page.get_by_test_id(f"pod-btn-{BOX}-1").select_option("red")
        page.get_by_test_id(f"pod-btn-{BOX}-4").select_option("blue")
        page.get_by_test_id(f"pod-bright-{BOX}").fill("55")
        page.get_by_test_id(f"pod-tamper-{BOX}").select_option("off")
        key = ctrl.game_key(game["id"])
        epoch = ctrl.transport.epoch
        self.field.host.transmitted_all(0.3)
        send.click()
        state = page.get_by_test_id(f"pod-state-{BOX}")
        expect(state).to_contain_text("enviado (1), a aguardar")
        cmds = []

        def heard() -> bool:
            for pkt in self.field.host.transmitted_all(0.2):
                hdr, plain = packet_decrypt(pkt, epoch, key)
                if hdr.type == MESSAGE_TYPES["CMD"]:
                    cmds.append(cmd_decode(plain))
            return any(c["cmd"] == 10 and c["dest"] == BOX for c in cmds)
        self.assertTrue(wait_for(heard, 5), cmds)
        sent = next(c for c in cmds if c["cmd"] == 10)
        self.assertEqual(sent["params"]["btn"], ["red", "", "", "blue"])
        self.assertEqual((sent["params"]["v"], sent["params"]["bright"], sent["params"]["tamper"]), (1, 55, False))
        expect(page.get_by_test_id("pod-cancel")).to_be_visible()
        # The pod took it: its phone says so over the radio (node.setup_applied), the page follows.
        rev = sent["params"]["rev"]
        self.field.box("EVENT", codec.encode_event({
            "node": BOX, "seq": 2, "t": 0, "type": "node.setup_applied",
            "data": {"kind": "pod_config", "rev": rev}}), ack=True)
        expect(state).to_contain_text("aceite pelo módulo")
        expect(page.get_by_test_id("pod-cancel")).to_have_count(0)
        page.get_by_test_id("lang").first.select_option("en")
        expect(page.get_by_test_id("pod-config-panel")).to_contain_text("I/O pods' settings")
        expect(state).to_contain_text("taken by the pod")
        # Never during a game.
        self.assertEqual(self.field.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True}).status_code, 200)
        expect(page.get_by_test_id("pod-not-ready")).to_be_visible()
        expect(send).to_be_disabled()

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
        self.field.box_hello("0.3.0-dev.412+g8560d54.dirty")  # a development build (FV-2)
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
        expect(page.get_by_test_id("firmware-boxes")).to_contain_text("0.3.0-dev.412+g8560d54.dirty")
        # The page orders versions as the controller and the box do (protocol/vectors/firmware.json).
        versions = json.loads((CONTROLLER.parent / "protocol" / "vectors" / "firmware.json").read_text())["versions"]
        wrong = page.evaluate("""async (v) => {
            const { compareVersions } = await import('./components/firmware-panel.js');
            const wrong = [];
            for (const name of ['semver_order', 'semver_core_order', 'order']) {
                const l = v[name];
                for (let i = 0; i + 1 < l.length; i++) {
                    if (compareVersions(l[i], l[i + 1]) !== -1 || compareVersions(l[i + 1], l[i]) !== 1) {
                        wrong.push([l[i], l[i + 1]]);
                    }
                }
            }
            for (const [a, b] of v.equal) if (compareVersions(a, b) !== 0) wrong.push([a, b]);
            for (const x of v.valid.concat(v.build_metadata)) if (compareVersions(x, x) !== 0) wrong.push([x]);
            for (const x of v.invalid) if (compareVersions(x, '1.0.0') !== null) wrong.push([x]);
            return wrong;
        }""", versions)
        self.assertEqual(wrong, [])

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

    def test_money_factory_game_and_its_events(self):
        """A Money Factory game from the form (its parameters in Portuguese); a factory's join;
        money collected and banked read as words in the feed, in both languages."""
        page = self.console()
        page.get_by_test_id("game-name").fill("Fábrica")
        page.get_by_test_id("game-source").select_option("mode:org.atalaia.money_factory")
        expect(page.locator('label[for="game-carry_max"]')).to_contain_text("Máximo de dinheiro que cada pessoa leva")
        page.locator("#game-target").fill("100")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual((game["mode_id"], game["params"]["target"], game["params"]["carry_max"]),
                         ("org.atalaia.money_factory", 100, 20))

        page.get_by_test_id("tab-join").click()
        page.locator("#j-node").fill(str(BOX))
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual((j["mode_id"], j["role"]), ("org.atalaia.money_factory", "factory"))

        self.field.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True})
        self.field.host.transmitted_all(0.3)
        self.field.box_hello()
        for seq, type_ in ((1, "money.collected"), (2, "money.deposited")):
            self.field.box("EVENT", codec.encode_event({"node": BOX, "seq": seq, "t": 9000 * seq, "type": type_,
                                                        "team": 1, "data": {"player": "r1", "amount": 12}}),
                           ack=True)
        page.get_by_test_id("tab-feed").click()
        collected = page.locator('[data-testid=feed] [data-type="money.collected"]')
        deposited = page.locator('[data-testid=feed] [data-type="money.deposited"]')
        expect(collected).to_contain_text("r1 (red) recolheu 12 de dinheiro")
        expect(deposited).to_contain_text("r1 (red) depositou 12: 12 pontos")
        page.get_by_test_id("lang").first.select_option("en")
        expect(collected).to_contain_text("r1 (red) collected 12 money")
        expect(deposited).to_contain_text("r1 (red) banked 12: 12 points")

    def test_progressive_domination_game_and_its_events(self):
        """A Progressive Domination game from the form (its parameters in Portuguese); the
        activation and the completion of a box read as words in the feed, in both languages."""
        page = self.console()
        page.get_by_test_id("game-name").fill("Progressivo")
        page.get_by_test_id("game-source").select_option("mode:org.atalaia.progressive_domination")
        expect(page.locator('label[for="game-complete_min"]')).to_contain_text("Minutos que uma equipa mantém")
        page.locator("#game-complete_min").fill("5")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual((game["mode_id"], game["params"]["complete_min"], game["params"]["points_per_min"]),
                         ("org.atalaia.progressive_domination", 5, 6))
        self.field.http.post(f"/api/v1/games/{game['id']}/start", json={"force": True})
        self.field.host.transmitted_all(0.3)
        fc = self.field.bundle.controller.fc
        fc.controller_event("progressive.activated", {"zone": "Moinho", "step": 2}, team=None, prio="critical")
        fc.controller_event("progressive.completed", {"zone": "Moinho", "step": 2}, team="red", prio="critical")
        page.get_by_test_id("tab-feed").click()
        activated = page.locator('[data-testid=feed] [data-type="progressive.activated"]')
        completed = page.locator('[data-testid=feed] [data-type="progressive.completed"]')
        expect(activated).to_contain_text("A caixa Moinho está ativa (n.º 2)")
        expect(completed).to_contain_text("red completou a caixa Moinho (n.º 2)")
        page.get_by_test_id("lang").first.select_option("en")
        expect(activated).to_contain_text("Box Moinho is active now (number 2)")
        expect(completed).to_contain_text("red completed box Moinho (number 2)")

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
        # Wait for the new payload itself: the old result can already contain a "2" (its game id),
        # and reading the text field before it changes decoded the node's payload again.
        expect(page.get_by_test_id("join-text")).not_to_have_value(text)
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

    def test_german_and_english_for_what_it_lacks(self):
        """Plan phase 10 (P5H-2): German, and a key its table lacks (another change's new text)
        shown in English, never as the key; a German console's game gets German boxes."""
        page = self.page(service_workers="block")  # so that the route below sees the request
        de = json.loads((HERE.parent / "src" / "i18n" / "de.json").read_text(encoding="utf-8"))
        del de["tabs"]["presets"]
        page.route("**/i18n/de.json", lambda route: route.fulfill(
            status=200, content_type="application/json", body=json.dumps(de)))
        page.get_by_test_id("token").fill(GM)
        page.get_by_test_id("login").click()
        # The game view first: picked while the login was under way, the language went to the login
        # page's own picker, which the logged-in view replaced before its change event, unheard.
        expect(page.get_by_test_id("tab-game")).to_be_visible()
        page.get_by_test_id("lang").first.select_option("de")
        expect(page.get_by_test_id("tab-nodes")).to_have_text("Boxen")
        expect(page.get_by_test_id("tab-presets")).to_have_text("Presets")  # English's text
        self.assertEqual(page.evaluate("document.documentElement.lang"), "de")
        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-name").fill("Sonntag")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text(de["game"]["states"]["ready"])
        page.get_by_test_id("tab-join").click()
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual(j["lang"], "de")
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("box-language-game")).to_contain_text("Deutsch")

    def test_traditional_chinese(self):
        """Plan phase 11: Traditional Chinese (Taiwan) on a phone: its texts, <html lang>, a Han
        font of Taiwan's in the stack, a decimal point, no tab scrolling sideways, and a game
        whose boxes get "zh-tw" (join key 15)."""
        page = self.console(width=360, height=800)
        page.get_by_test_id("lang").first.select_option("zh-tw")
        expect(page.get_by_test_id("tab-nodes")).to_have_text("盒子")
        self.assertEqual(page.evaluate("document.documentElement.lang"), "zh-Hant-TW")
        self.assertIn("Noto Sans TC", page.evaluate("getComputedStyle(document.body).fontFamily"))
        for tab in ("game", "field", "nodes", "join", "presets", "feed", "controller", "checkin", "scenarios",
                    "adopt", "settings"):
            page.get_by_test_id(f"tab-{tab}").click()
            self.no_horizontal_scroll(page)
        expect(page.get_by_test_id("radio-channel")).to_have_text("869.525 MHz")  # a decimal point
        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-name").fill("週日場")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("就緒")
        self.no_horizontal_scroll(page)
        page.get_by_test_id("tab-join").click()
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual(j["lang"], "zh-tw")
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("box-language-game")).to_contain_text("繁體中文（台灣）")
        page.reload()
        expect(page.get_by_test_id("tab-nodes")).to_have_text("盒子")  # remembered

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

    def test_games_made_and_run_in_another_session_show_live(self):
        """A game the API (the bench, another GM's console) creates, starts, pauses, resumes and ends shows
        in every open console at once, without a reload: the GM's and a read token's, on the Game tab and
        with a second game after the first has ended (found on the bench, 2026-10-26)."""
        gm = self.console()
        ro = self.console(READ)
        for page in (gm, ro):
            expect(page.get_by_test_id("game-state")).to_have_count(0)
            page.evaluate("window.__sameDocument = 7")
        http = self.field.http
        first = self.field.create_game("Sessão B")
        for page in (gm, ro):
            expect(page.get_by_test_id("game-state")).to_have_text("pronto")
            expect(page.locator("main")).to_contain_text("Sessão B")
        self.assertEqual(http.post(f"/api/v1/games/{first['id']}/start", json={"force": True}).status_code, 200)
        for page in (gm, ro):
            expect(page.get_by_test_id("game-state")).to_have_text("a decorrer")
        for action, text in (("pause", "em pausa"), ("resume", "a decorrer")):
            self.assertEqual(http.post(f"/api/v1/games/{first['id']}/{action}", json={}).status_code, 200)
            for page in (gm, ro):
                expect(page.get_by_test_id("game-state")).to_have_text(text)
        self.assertEqual(http.post(f"/api/v1/games/{first['id']}/end", json={}).status_code, 200)
        for page in (gm, ro):
            expect(page.get_by_test_id("game-ended")).to_contain_text("Sessão B")
        second = self.field.create_game("Sessão C", start=True)
        for page in (gm, ro):
            expect(page.locator("main")).to_contain_text("Sessão C")
            expect(page.get_by_test_id("game-state")).to_have_text("a decorrer")
            self.assertEqual(page.evaluate("window.__sameDocument"), 7, "the page reloaded")
        self.assertNotEqual(first["id"], second["id"])

    def test_a_console_whose_stream_went_quiet_still_finds_the_live_game(self):
        """Decision CL-2: a stream that is open but gets nothing (a half-open connection) must not leave the
        console with no game for good: the 10 s refresh asks the controller which game is live."""
        page = self.console()
        hub = self.field.bundle.hub
        self.assertTrue(wait_for(lambda: hub.client_count == 1, 5))
        for queue in list(hub._clients):
            hub.unsubscribe(queue)  # still connected, never sent anything again
        self.field.create_game("Sessão D", start=True)
        expect(page.get_by_test_id("game-state")).to_have_text("a decorrer", timeout=15_000)
        expect(page.locator("main")).to_contain_text("Sessão D")

    def test_a_silent_stream_is_dropped_and_opened_again(self):
        """Decision CL-2: pings go out, and a connection that answers nothing for 20 s is replaced (the first
        connection's server messages are held back here, as a dead Wi-Fi would)."""
        opened = []
        muted = []

        def route(ws):
            server = ws.connect_to_server()
            opened.append(ws)
            mine = len(opened)
            ws.on_message(lambda m: server.send(m))
            server.on_message(lambda m: None if (mine == 1 and muted) else ws.send(m))

        page = self.page(setup=lambda p: p.route_web_socket("**/api/v1/stream**", route))
        page.get_by_test_id("token").fill(GM)
        page.get_by_test_id("login").click()
        expect(page.get_by_test_id("tab-game")).to_be_visible()
        page.wait_for_timeout(1500)  # the hello has come (Playwright's sync API runs the handlers while it waits)
        self.assertEqual(len(opened), 1)
        muted.append(True)
        for _ in range(160):
            if len(opened) == 2:
                break
            page.wait_for_timeout(250)
        self.assertEqual(len(opened), 2, "the silent stream was never replaced")
        self.field.create_game("Sessão E", start=True)
        expect(page.get_by_test_id("game-state")).to_have_text("a decorrer", timeout=15_000)

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

    # --- the token in the address and a controller that serves fewer areas (PE24-70) ---

    def test_token_in_the_fragment_is_kept_and_taken_out_of_the_address(self):
        requests: list[str] = []
        page = self.page(f"/console/#token={GM}&lang=en", setup=lambda p: p.on("request", lambda r: requests.append(r.url)))
        expect(page.get_by_test_id("tab-game")).to_have_text("Game")
        expect(page.get_by_test_id("tab-game")).to_have_attribute("aria-current", "page")
        self.assertEqual(page.evaluate("location.hash"), "")
        self.assertNotIn(GM, page.url)
        self.assertEqual(page.evaluate("localStorage.getItem('atalaia.token')"), GM)  # as a typed token
        self.assertEqual(page.evaluate("localStorage.getItem('atalaia.lang')"), "en")
        # Every area served by the Pi's controller: nothing explained as missing.
        page.get_by_test_id("tab-controller").click()
        expect(page.get_by_test_id("controller-status")).to_be_visible()
        expect(page.get_by_test_id("controller-missing")).to_have_count(0)
        # The token went in the Authorization header only (the stream's ?token= is a WebSocket,
        # not one of these requests), never in an address the page asked for.
        self.assertTrue(requests)
        self.assertEqual([u for u in requests if GM in u], [])
        # The address was replaced, not added to: back leads to the page before, forward to no token.
        page.go_back()
        self.assertEqual(page.url, "about:blank")
        page.go_forward()
        self.assertEqual(page.url, f"{self.field.base}/console/")
        expect(page.get_by_test_id("tab-game")).to_have_text("Game")  # kept, as a typed token
        page.reload()
        expect(page.get_by_test_id("tab-game")).to_have_text("Game")  # and across a reload
        # A tab in the same fragment stays; the token and language go.
        tab = self.page(f"/console/#field&token={GM}&lang=pt")
        expect(tab.get_by_test_id("tab-field")).to_have_attribute("aria-current", "page")
        expect(tab.get_by_test_id("tab-field")).to_have_text("Campo")
        self.assertEqual(tab.evaluate("location.hash"), "#field")
        # A wrong token: refused as a typed one, out of the address, not stored.
        bad = self.page("/console/#token=not-a-token")
        expect(bad.get_by_role("alert")).to_be_visible()
        expect(bad.get_by_test_id("token")).to_be_visible()
        self.assertEqual(bad.evaluate("location.hash"), "")
        self.assertIsNone(bad.evaluate("localStorage.getItem('atalaia.token')"))
        self.forget_refusal("/api/v1/whoami")

    # app/lib/controller/controller_api.dart (slice S7a added the radio and the field plan)
    PHONE_FEATURES = ["checkin", "join", "box_language", "positions", "radio", "field"]
    # The console's calls in the areas a phone controller does not serve yet.
    PHONE_HIDDEN = re.compile(r"/api/v1/(presets|team-presets|crests|field/branding|boxes|adopt|firmware|atak"
                              r"|scenarios|schedule|mode-packages|mode-fetch|controller/promote|controller/join"
                              r"|games/\d+/(invites|teams))")   # remote-gm is served: S7 slice, the Controller tab's log

    def phone_controller(self, page, requests: list) -> None:
        """whoami answers with the Android controller's features; every request is noted."""
        def whoami(route):
            resp = route.fetch()
            body = resp.json()
            body["features"] = self.PHONE_FEATURES
            route.fulfill(response=resp, json=body)
        page.route("**/api/v1/whoami", whoami)
        page.on("request", lambda r: requests.append(r.url))

    def test_a_phone_controller_hides_what_it_does_not_serve(self):
        game = self.field.create_game(name="Sábado")
        requests: list[str] = []
        page = self.page(f"/console/#token={GM}", width=390, height=844,
                         setup=lambda p: self.phone_controller(p, requests))
        expect(page.get_by_test_id("tab-game")).to_have_text("Jogo")
        expect(page.get_by_test_id("game-state")).to_be_visible()
        for tab in ("adopt", "presets", "scenarios"):
            expect(page.get_by_test_id(f"tab-{tab}")).to_have_count(0)
        expect(page.get_by_test_id("tab-field")).to_be_visible()  # slice S7a
        expect(page.get_by_test_id("game-actions")).to_be_visible()
        expect(page.get_by_test_id("game-invite")).to_have_count(0)  # boxes
        expect(page.get_by_test_id("teams-editor")).to_have_count(0)  # branding
        for tab in ("game", "checkin", "nodes", "join", "feed", "field", "controller", "settings"):
            page.get_by_test_id(f"tab-{tab}").click()
            page.wait_for_timeout(200)
            self.no_horizontal_scroll(page)
        expect(page.get_by_role("heading", name="Língua das caixas")).to_be_visible()
        expect(page.get_by_test_id("radio-current")).to_be_visible()  # slice S7a
        expect(page.get_by_test_id("branding-settings")).to_have_count(0)
        expect(page.get_by_test_id("team-presets")).to_have_count(0)
        page.get_by_test_id("tab-controller").click()
        missing = page.get_by_test_id("controller-missing")
        expect(missing).to_contain_text("Este controlador ainda não serve estas partes da consola")
        expect(missing).to_contain_text("adotar caixas")
        expect(missing).not_to_contain_text("o canal de rádio")
        expect(missing).not_to_contain_text("o mapa do campo")
        expect(missing).not_to_contain_text("check-in")
        expect(page.get_by_test_id("promote")).to_have_count(0)
        # No live game: the creation form without team names and crests, no standby join; the radio
        # reminder since slice S7a.
        self.field.http.post(f"/api/v1/games/{game['id']}/end", json={})
        page.get_by_test_id("tab-game").click()
        expect(page.get_by_test_id("game-ended")).to_be_visible()
        expect(page.get_by_test_id("game-team-branding")).to_have_count(0)
        expect(page.get_by_test_id("radio-first-setup")).to_be_visible()
        page.get_by_test_id("tab-join").click()
        expect(page.get_by_test_id("standby-form")).to_have_count(0)
        page.wait_for_timeout(300)
        self.assertTrue(any("/api/v1/whoami" in u for u in requests))
        self.assertEqual([u for u in requests if self.PHONE_HIDDEN.search(u)], [])
        # An #adopt address opens the game instead of a tab that is not there; #field opens the field.
        adopt = self.page(f"/console/#adopt&token={GM}", setup=lambda p: self.phone_controller(p, []))
        expect(adopt.get_by_test_id("tab-game")).to_have_attribute("aria-current", "page")
        expect(adopt.get_by_test_id("tab-adopt")).to_have_count(0)
        field = self.page(f"/console/#field&token={GM}", setup=lambda p: self.phone_controller(p, []))
        expect(field.get_by_test_id("tab-field")).to_have_attribute("aria-current", "page")

    def test_csv_and_printing_notice_in_androids_web_view(self):
        self.field.create_game()
        webview = ("Mozilla/5.0 (Linux; Android 14; Pixel 8 Build/AP1A.240505.005; wv) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Version/4.0 Chrome/124.0.6367.82 Mobile Safari/537.36")
        page = self.page(f"/console/#token={GM}", width=390, height=844, user_agent=webview)
        page.get_by_test_id("tab-checkin").click()  # often before the stream has told the page the game
        expect(page.get_by_test_id("checkin-csv")).to_be_visible()
        expect(page.get_by_test_id("checkin-webview")).to_contain_text("navegador de um computador")
        self.no_horizontal_scroll(page)
        page.get_by_test_id("lang").first.select_option("en")
        expect(page.get_by_test_id("checkin-webview")).to_contain_text("a computer's browser")
        browser = self.console()
        browser.get_by_test_id("tab-checkin").click()
        expect(browser.get_by_test_id("checkin-csv")).to_be_visible()
        expect(browser.get_by_test_id("checkin-webview")).to_have_count(0)

    def test_checkin_tab_follows_the_live_game(self):
        """Decision FL-1: the Check-in tab, open with no game, shows the game once it is made, and the next
        one's (empty) list after the first has ended, without leaving the tab."""
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id("checkin-no-game")).to_be_visible()
        first = self.field.create_game("Sábado")
        expect(page.get_by_test_id("checkin-open")).to_contain_text("Sábado")
        expect(page.get_by_test_id("checkin-csv")).to_be_visible()
        self.check_in(first["id"], "Coruja")
        expect(page.get_by_test_id("checkin-table")).to_contain_text("Coruja")
        self.field.http.post(f"/api/v1/games/{first['id']}/end", json={})
        expect(page.get_by_test_id("checkin-no-game")).to_be_visible()
        self.field.create_game("Domingo")
        expect(page.get_by_test_id("checkin-open")).to_contain_text("Domingo")
        expect(page.get_by_test_id("checkin-empty")).to_be_visible()

    def test_players_tags_signed_by_the_controller(self):
        """Players' NFC tags (decision TW-1) in the Check-in tab: the controller signs a tag for a checked-in
        player and a team with the game's key (the key is never on the page); without Web NFC the page shows
        the bytes, a download and the app that writes them; with Web NFC it writes the tag's record itself,
        and says when the writing fails; in every language."""
        from atalaia_sim import tag as tagfmt  # noqa: PLC0415

        game = self.field.create_game("Sábado")
        me = self.check_in(game["id"], "Coruja")
        key = self.field.bundle.controller.game_key(game["id"])
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        card = page.get_by_test_id("tags")
        expect(card).to_contain_text("Etiquetas de quem joga")
        expect(page.get_by_test_id("tags-game")).to_contain_text("Sábado")
        expect(page.get_by_test_id("tag-result")).to_have_count(0)

        # The checked-in players are offered, and a team is picked for the tag.
        self.assertEqual(page.locator("#tag-players option").first.get_attribute("value"), me["player_id"])
        page.get_by_test_id("tag-player").fill(me["player_id"])
        page.get_by_test_id("tag-team").select_option("blue")
        page.get_by_test_id("tag-make").click()
        expect(page.get_by_test_id("tag-for")).to_have_text(f"Etiqueta de {me['player_id']}, equipa blue")
        ndef = bytes.fromhex(page.get_by_test_id("tag-ndef").inner_text().strip())
        mime = tagfmt.NDEF_TYPE
        payload = ndef[3 + len(mime):]
        self.assertEqual(ndef[:3 + len(mime)], bytes([0xD2, len(mime), len(payload)]) + mime)  # MB ME SR, MIME
        self.assertEqual(tagfmt.decode(payload, game["id"], key, 2),
                         {"player": me["player_id"], "team": 2, "game_id": game["id"]})
        memory = bytes.fromhex(page.get_by_test_id("tag-memory").text_content().strip())
        self.assertEqual(tagfmt.from_ndef_tag(memory), payload)
        # The page never holds the game key, in what it shows or in its scripts' data.
        self.assertNotIn(key.hex(), page.content())

        # This browser has no Web NFC: the bytes, a file, and which app writes them.
        expect(page.get_by_test_id("tag-nfc-write")).to_have_count(0)
        expect(page.get_by_test_id("tag-nfc-unsupported")).to_contain_text("app Atalaia")
        with page.expect_download() as dl:
            page.get_by_test_id("tag-download").click()
        self.assertEqual(Path(dl.value.path()).read_bytes(), ndef)
        self.assertEqual(dl.value.suggested_filename, f"atalaia-tag-{me['player_id']}.ndef")

        # With Web NFC the page writes the one record itself.
        page.evaluate("""() => {
            window.__nfc = [];
            window.NDEFReader = class { async write(message, options) {
                window.__nfc.push({ message: { records: message.records.map((r) => ({ recordType: r.recordType,
                    mediaType: r.mediaType, data: Array.from(r.data) })) }, signal: !!(options && options.signal) });
            } };
        }""")
        page.get_by_test_id("tag-hide").click()
        expect(page.get_by_test_id("tag-result")).to_have_count(0)
        page.get_by_test_id("tag-team").select_option("")
        page.get_by_test_id("tag-make").click()
        expect(page.get_by_test_id("tag-for")).to_have_text(f"Etiqueta de {me['player_id']}, sem equipa")
        page.get_by_test_id("tag-nfc-write").click()
        expect(page.get_by_test_id("tag-nfc-done")).to_be_visible()
        written = page.evaluate("window.__nfc")
        self.assertEqual(len(written), 1)
        record = written[0]["message"]["records"][0]
        self.assertEqual((record["recordType"], record["mediaType"]), ("mime", "application/vnd.atalaia.tag"))
        self.assertEqual(tagfmt.decode(bytes(record["data"]), game["id"], key, 2),
                         {"player": me["player_id"], "team": 0, "game_id": game["id"]})
        expect(page.get_by_test_id("tag-nfc-unsupported")).to_have_count(0)

        # A tag that cannot be written is said, and the bytes stay.
        page.evaluate("""() => { window.NDEFReader = class { async write() {
            throw new DOMException('Not allowed', 'NotAllowedError'); } }; }""")
        page.get_by_test_id("tag-nfc-write").click()
        expect(page.get_by_test_id("tag-nfc-failed")).to_contain_text("Not allowed")
        expect(page.get_by_test_id("tag-ndef")).to_be_visible()

        # The controller refuses an id the form does not (a tag is 1 to 32 letters, digits, - _ .).
        r = httpx.post(self.field.base + f"/api/v1/games/{game['id']}/tags", json={"player": "no spaces"},
                       headers={"Authorization": f"Bearer {GM}"}, timeout=10)
        self.assertEqual(r.status_code, 400)

        for lang, title, make in (("en", "Players' tags", "Make the tag"), ("de", "Tags der Spielenden", "Tag erzeugen"),
                                  ("zh-tw", "玩家標籤", "產生標籤")):
            page.get_by_test_id("lang").first.select_option(lang)
            expect(card.locator("h2")).to_have_text(title)
            expect(page.get_by_test_id("tag-make")).to_have_text(make)
        page.get_by_test_id("lang").first.select_option("pt")

        # Gone with the game: nothing to sign with.
        self.field.http.post(f"/api/v1/games/{game['id']}/end", json={})
        expect(page.get_by_test_id("tags")).to_have_count(0)

        # The next game's card (no check-ins yet, so no table to widen the page) fits a phone.
        game2 = self.field.create_game("Domingo")
        expect(page.get_by_test_id("tags-game")).to_contain_text("Domingo")
        page.set_viewport_size({"width": 375, "height": 800})
        page.get_by_test_id("tag-player").fill("p-17")
        page.get_by_test_id("tag-make").click()
        expect(page.get_by_test_id("tag-ndef")).to_be_visible()
        self.no_horizontal_scroll(page)

        # A read token never sees the card (the controller refuses it too).
        read = self.console(READ)
        read.get_by_test_id("tab-checkin").click()
        expect(read.get_by_test_id("tags")).to_have_count(0)
        r = httpx.post(self.field.base + f"/api/v1/games/{game2['id']}/tags", json={"player": "p-1"},
                       headers={"Authorization": f"Bearer {READ}"}, timeout=10)
        self.assertEqual(r.status_code, 403)

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

    def test_a_channel_change_says_the_free_boxes_are_told_then_moved(self):
        """RFC 0001 Amendment 19, decision RB-13: while the MOVEs repeat on the old channel (about 5 s) the
        channel panel says the free boxes are being told, how many times it has been said, and then that
        the controller has moved, with what to do about a box that is still missing; four languages."""
        page = self.console()
        page.get_by_test_id("lang").first.select_option("en")
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("radio-move-telling")).to_have_count(0)
        page.get_by_test_id("radio-manual").select_option("869925000")
        page.get_by_test_id("radio-apply-manual").click()
        telling = page.get_by_test_id("radio-move-telling")
        expect(telling).to_contain_text("Telling the free boxes on the old channel (869.525 MHz)")
        expect(telling).to_contain_text("moving to 869.925 MHz")
        expect(telling).to_contain_text("of 3 times")
        expect(page.get_by_test_id("radio-channel")).to_have_text("869.925 MHz")
        moved = page.get_by_test_id("radio-move-moved")
        expect(moved).to_contain_text("The controller has moved to 869.925 MHz", timeout=20000)
        expect(moved).to_contain_text("adopted again")
        expect(telling).to_have_count(0)
        self.assertTrue(wait_for(lambda: (self.field.bundle.modem.status or {}).get("channel_hz")
                                 == 869_925_000, 8))
        move = self.field.http.get("/api/v1/radio").json()["move"]
        self.assertEqual((move["state"], move["sent"], move["repeats"], move["from_hz"], move["to_hz"]),
                         ("moved", 3, 3, 869_525_000, 869_925_000))
        for lang, text in (("pt", "O controlador já mudou para 869,925 MHz"),
                           ("de", "Der Controller ist auf 869,925 MHz gewechselt"),
                           ("zh-tw", "控制器已切換到 869.925 MHz")):
            page.get_by_test_id("lang").first.select_option(lang)
            expect(moved).to_contain_text(text)
        page.get_by_test_id("radio-move-dismiss").click()
        expect(moved).to_have_count(0)

    def test_find_boxes_names_the_swept_channels_and_counts_the_answers(self):
        """After "Look for boxes" (the Settings panel between games, the invite dialog in a game): which
        earlier channels were swept (boxes that were away when the field moved), how many boxes answered,
        and the help line for a box still missing; four languages."""
        self.assertEqual(self.field.http.put("/api/v1/radio/channel", json={"channel_hz": 869_925_000}).status_code,
                         200)
        self.assertTrue(wait_for(lambda: self.field.http.get("/api/v1/radio").json()["move"]["state"] == "moved",
                                 20))
        device = bytes.fromhex("5a17c0de0b0e1234")
        key = ff.field_key(JOIN_KEY)
        page = self.console()
        page.get_by_test_id("lang").first.select_option("en")
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("invite-discover-result")).to_have_count(0)
        page.get_by_test_id("radio-find-boxes").click()
        # (The controller's own DISCOVER after the move was a moment ago: it may say "asked a moment ago".)
        expect(page.get_by_test_id("invite-discover-sent")).to_have_text(
            re.compile("Asked the free boxes to announce themselves.|asked a moment ago"))
        expect(page.get_by_test_id("invite-discover-sweep")).to_contain_text(
            "Also looked on the earlier channels: 869.525 MHz.")
        expect(page.get_by_test_id("invite-discover-answered")).to_have_text("Boxes that answered: 0.")
        expect(page.get_by_test_id("invite-missing-help")).to_contain_text("must be adopted again")
        # A box that was away answers: counted.
        box = lobby.IdleBox(JOIN_KEY, "Zona Norte", device_id=device, rng=random.Random(2))
        self.field.host.hear(ff.encode(key, box._announce(), box.nonces.next()))
        expect(page.get_by_test_id("invite-discover-answered")).to_have_text("Boxes that answered: 1.")
        # Asking again within the minute is not swept again by the controller, yet the sweep stays named.
        self.assertEqual(self.field.http.post("/api/v1/boxes/discover").json()["sweep"], [])
        page.get_by_test_id("radio-find-boxes").click()
        expect(page.get_by_test_id("invite-discover-sweep")).to_contain_text("869.525 MHz")
        expect(page.get_by_test_id("invite-discover-answered")).to_have_text("Boxes that answered: 1.")
        page.get_by_test_id("lang").first.select_option("pt")
        expect(page.get_by_test_id("invite-discover-sweep")).to_contain_text(
            "Procurou-se também nos canais anteriores: 869,525 MHz.")
        expect(page.get_by_test_id("invite-missing-help")).to_contain_text("adotada de novo")
        page.get_by_test_id("lang").first.select_option("de")
        expect(page.get_by_test_id("invite-discover-answered")).to_have_text("Boxen, die geantwortet haben: 1.")
        page.get_by_test_id("lang").first.select_option("zh-tw")
        expect(page.get_by_test_id("invite-discover-answered")).to_have_text("已回應的盒子：1。")
        # In a game's invite dialog the same lines show (the controller sweeps only between games, but a
        # sweep from the last minute is still named).
        page.get_by_test_id("lang").first.select_option("en")
        self.field.create_game()
        page.get_by_test_id("tab-game").click()
        page.get_by_test_id("game-invite").click()
        expect(page.get_by_test_id("invite-dialog")).to_be_visible()
        expect(page.get_by_test_id("invite-discover-sent")).to_be_visible()
        expect(page.get_by_test_id("invite-discover-sweep")).to_contain_text("869.525 MHz")
        expect(page.get_by_test_id("invite-missing-help")).to_be_visible()

    def test_find_boxes_says_when_the_hourly_cap_refused_the_sweep(self):
        """RL-9: a sweep the controller's cap on air time refused is said, with the minutes to the next one
        (or that the sub-band never allows one), in four languages; never an empty sweep without a reason.
        The cap itself is the controller's (tests/test_reinvite.py, the contract case); here the console
        gets the answer."""
        capped = {"sent": True, "sweep": [], "sweep_refused": {
            "reason": "cap", "band": "g", "duty_pct": 1.0, "share_pct": 5.0, "limit_ms": 1800, "used_ms": 1478,
            "cost_ms": 370, "retry_after_s": 3356}}
        never = {"sent": True, "sweep": [], "sweep_refused": {
            "reason": "cap", "band": "g1", "duty_pct": 0.1, "share_pct": 5.0, "limit_ms": 180, "used_ms": 0,
            "cost_ms": 185, "retry_after_s": None}}
        answer = {"body": capped}
        page = self.console()
        page.route("**/api/v1/boxes/discover", lambda route: route.fulfill(json=answer["body"]))
        page.get_by_test_id("lang").first.select_option("en")
        page.get_by_test_id("tab-settings").click()
        page.get_by_test_id("radio-find-boxes").click()
        refused = page.get_by_test_id("invite-discover-capped")
        expect(refused).to_have_text(
            "No sweep of the earlier channels: on a 1% channel the radio may use only 5% of an hour's air time "
            "for sweeps, and that is used up for now. The next sweep is possible in 56 min.")
        expect(page.get_by_test_id("invite-discover-sweep")).to_have_count(0)
        page.get_by_test_id("lang").first.select_option("pt")
        expect(refused).to_contain_text("possível dentro de 56 min")
        expect(refused).to_contain_text("tempo de emissão")
        page.get_by_test_id("lang").first.select_option("de")
        expect(refused).to_contain_text("Der nächste Suchlauf ist in 56 Min. möglich.")
        page.get_by_test_id("lang").first.select_option("zh-tw")
        expect(refused).to_contain_text("下一次搜尋可在 56 分鐘後進行。")
        # A sub-band that never allows a sweep says that instead.
        answer["body"] = never
        page.get_by_test_id("lang").first.select_option("en")
        page.get_by_test_id("radio-find-boxes").click()
        expect(page.get_by_test_id("invite-discover-capped")).to_have_text(
            "No sweep of the earlier channels: a 0.1% channel has too little air time for a sweep.")
        page.get_by_test_id("lang").first.select_option("pt")
        expect(page.get_by_test_id("invite-discover-capped")).to_contain_text("um canal de 0,1%")

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

    # --- the field's radio region (RFC 0001 Amendment 12, RF-AS923) ----------------

    def test_region_changed_to_taiwan_after_a_confirmation(self):
        """The region shown with its band and LoRa settings; changing it asks first (No keeps it); Yes
        moves the field to Taiwan's default channel, unconfirmed, with its limits at the antenna port,
        its nine 500 kHz channels and its own explanation; this modem is an EU868 build: a warning."""
        page = self.console()
        page.get_by_test_id("lang").first.select_option("en")
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("radio-region")).to_have_text("Europe (EU868, 868 MHz)")
        expect(page.get_by_test_id("radio-region-lora")).to_have_text("868.000–870.000 MHz · LoRa SF7 at 125 kHz")
        expect(page.get_by_test_id("radio-region-source")).to_have_text("the controller's configuration")
        expect(page.get_by_test_id("radio-region-mismatch")).to_have_count(0)
        expect(page.get_by_test_id("radio-region-apply")).to_be_disabled()  # the same region
        page.get_by_test_id("radio-region-select").select_option("as923-tw")
        asked: list[str] = []

        def answer(dialog, yes: bool) -> None:
            asked.append(dialog.message)
            dialog.accept() if yes else dialog.dismiss()

        page.once("dialog", lambda d: answer(d, False))
        page.get_by_test_id("radio-region-apply").click()
        self.assertTrue(wait_for(lambda: len(asked) == 1, 5))
        self.assertIn("Taiwan (AS923, 920–925 MHz)", asked[0])
        self.assertIn("must be built for this region", asked[0])
        self.assertEqual(self.field.http.get("/api/v1/radio").json()["region"]["code"], "eu868")
        page.once("dialog", lambda d: answer(d, True))
        page.get_by_test_id("radio-region-apply").click()
        expect(page.get_by_test_id("radio-region")).to_have_text("Taiwan (AS923, 920–925 MHz)")
        expect(page.get_by_test_id("radio-region-lora")).to_have_text("920.000–925.000 MHz · LoRa SF9 at 500 kHz")
        expect(page.get_by_test_id("radio-region-source")).to_have_text("chosen in the console")
        expect(page.get_by_test_id("radio-channel")).to_have_text("921.500 MHz")
        expect(page.get_by_test_id("radio-limits")).to_have_text("10% of the time · 500 mW at the antenna port")
        expect(page.get_by_test_id("radio-source")).to_contain_text("not chosen yet")
        expect(page.get_by_test_id("radio-low-power")).to_have_count(0)
        expect(page.get_by_test_id("radio-region-mismatch")).to_contain_text(
            "The USB modem is built for Europe (EU868, 868 MHz), but the field is in Taiwan (AS923, 920–925 MHz)")
        expect(page.locator("[data-testid=radio-manual] option")).to_have_count(9)
        expect(page.locator('[data-testid=radio-manual] option[value="923000000"]')).to_contain_text(
            "LoRaWAN default, often busy")
        why = page.get_by_test_id("radio-why")
        why.locator("summary").click()
        expect(why).to_contain_text("NCC LP0002")
        expect(why).not_to_contain_text("869.4–869.65 MHz")
        settings = self.field.http.get("/api/v1/radio").json()
        self.assertEqual((settings["region"]["code"], settings["channel"]["channel_hz"], settings["confirmed"],
                          settings["region_mismatch"]), ("as923-tw", 921_500_000, False, True))
        # The first-setup reminder asks for the Taiwanese channel; back in the game tab it names it.
        page.get_by_test_id("tab-game").click()
        expect(page.get_by_test_id("radio-first-setup")).to_contain_text("921.500 MHz")
        # Back to Europe, from the stream of another change (the API), with no reload.
        page.get_by_test_id("tab-settings").click()
        self.assertEqual(self.field.http.put("/api/v1/radio/region", json={"region": "eu868"}).status_code, 200)
        expect(page.get_by_test_id("radio-region")).to_have_text("Europe (EU868, 868 MHz)")
        expect(page.get_by_test_id("radio-channel")).to_have_text("869.525 MHz")
        expect(page.get_by_test_id("radio-region-mismatch")).to_have_count(0)

    def test_a_taiwanese_field(self):
        """A controller configured for AS923-TW with a modem built for it: no warning, a noise scan over
        the nine 500 kHz channels whose suggestion is taken, a game and its join on that channel with
        the region (join key 18), the region locked while the game lives; in Traditional Chinese too."""
        self.field.close()
        self.field = Field("--region", "as923-tw", "--noise", "922000000:-112", "--noise-floor", "-100",
                           cfg={"region": "as923-tw", "channel_hz": 921_500_000})
        page = self.console()
        page.get_by_test_id("lang").first.select_option("en")
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("radio-region")).to_have_text("Taiwan (AS923, 920–925 MHz)")
        expect(page.get_by_test_id("radio-region-mismatch")).to_have_count(0)
        self.assertEqual(self.field.http.get("/api/v1/radio").json()["modem_region"], "as923-tw")
        page.get_by_test_id("radio-scan").click()
        expect(page.get_by_test_id("radio-suggestion")).to_contain_text(
            "Suggested: 922.000 MHz, the quietest full-power channel (10% of the time · 500 mW at the antenna port)",
            timeout=15000)
        rows = page.locator("[data-testid=radio-results] tbody tr")
        expect(rows).to_have_count(9)
        expect(rows.first).to_have_attribute("data-channel", "922000000")
        page.get_by_test_id("radio-accept-suggestion").click()
        expect(page.get_by_test_id("radio-channel")).to_have_text("922.000 MHz")
        self.assertTrue(wait_for(lambda: (self.field.bundle.modem.status or {}).get("channel_hz")
                                 == 922_000_000, 8))
        page.get_by_test_id("radio-random").click()
        expect(page.get_by_test_id("radio-random-result")).to_contain_text("9 of 9 candidate channels give 500 mW.")
        game = self.field.create_game()
        self.assertEqual(game["channel_hz"], 922_000_000)
        expect(page.get_by_test_id("radio-locked")).to_be_visible()
        expect(page.get_by_test_id("radio-region-select")).to_be_disabled()
        self.assertEqual(self.field.http.put("/api/v1/radio/region", json={"region": "eu868"}).status_code, 409)
        page.get_by_test_id("tab-join").click()
        page.get_by_test_id("join-generate").click()
        j = join.decode(join.from_text(page.get_by_test_id("join-text").input_value()), JOIN_KEY)
        self.assertEqual((j["region"], j["channel_hz"]), ("as923-tw", 922_000_000))
        page.get_by_test_id("lang").first.select_option("zh-tw")
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("radio-region")).to_have_text("台灣（AS923，920–925 MHz）")
        expect(page.get_by_test_id("radio-limits")).to_have_text("10% 的時間 · 天線端 500 mW")

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

    def test_standby_console_moves_the_markers_live_when_the_join_is_made_again(self):
        """BBC-30: a console open on a standby controller's plan sees a box move at once when the primary's
        join (key 22) is applied again, without a reload; a box whose place did not change is not touched. (The
        plan draws the boxes the standby has heard, so box 7 says HELLO to it; box 9 is only in the join.)"""
        game_key = bytes(range(16))

        def standby_text(places):
            return join.to_text(join.encode({
                "kind": "controller", "game_id": 77, "game_key": game_key, "node_id": 2, "controller_id": 1,
                "channel_hz": 869_525_000, "max_hops": 2, "teams": ["red", "blue"], "mode_id": DOMINATION,
                "role": "controller", "game_seed": 12345, "params": None, "box_places": places,
            }, JOIN_KEY))

        def apply(places):
            r = self.field.http.post("/api/v1/controller/join", json={"text": standby_text(places)})
            self.assertEqual(r.status_code, 201, r.text)

        apply([[BOX, 0, join.quantize(0.25), join.quantize(0.5)], [9, 0, 65535, 0]])
        self.field.box_hello()
        self.assertEqual(self.field.http.put("/api/v1/field/image", headers={"Content-Type": "image/png"},
                                             content=ICON.read_bytes()).status_code, 200)
        page = self.console()
        page.get_by_test_id("tab-field").click()
        moved = page.locator(f'[data-testid=field-area] .marker[data-node="{BOX}"]')
        expect(moved).to_have_attribute("style", re.compile(r"left: 25(\.\d+)?%"))
        page.evaluate("window.__sameDocument = 42")
        apply([[BOX, 0, join.quantize(0.75), join.quantize(0.2)], [9, 0, 65535, 0]])
        expect(moved).to_have_attribute("style", re.compile(r"left: 75(\.\d+)?%"))
        expect(moved).to_have_attribute("style", re.compile(r"top: 2[01](\.\d+)?%"))
        self.assertEqual(page.evaluate("window.__sameDocument"), 42, "the page reloaded")

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
        expect(page.get_by_test_id("georef-error")).to_contain_text("Um canto")
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
        # Any two opposite corners (GR-1, the maintainer's bench values): a south-west corner and a
        # north-east one are put at the bottom-left and top-right of the image, not mirrored.
        page.get_by_test_id("georef-top_left-input").fill("38.804476, -9.132643")
        page.get_by_test_id("georef-bottom_right-input").fill("38.804629, -9.132399")
        page.get_by_test_id("georef-save").click()
        expect(page.get_by_test_id("georef-top_right")).to_have_text("38.804629, -9.132399")
        expect(page.get_by_test_id("georef-error")).to_have_count(0)
        got = self.field.http.get("/api/v1/field/georef").json()["georef"]
        self.assertEqual(got["points"], [{"x": 0, "y": 1, "lat": 38.804476, "lon": -9.132643},
                                         {"x": 1, "y": 0, "lat": 38.804629, "lon": -9.132399}])
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
        page.get_by_test_id("levels-toggle").click()  # checked once the controller has the change
        expect(page.get_by_test_id("levels-toggle")).to_be_checked()
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
        page.get_by_test_id("levels-toggle").click()  # checked once the controller has the change
        expect(page.get_by_test_id("levels-toggle")).to_be_checked()
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
        expect(page.get_by_test_id("levels-confirm")).to_contain_text(
            "the plans of Floor 2 are deleted, with their map features")
        page.get_by_test_id("levels-confirm-yes").click()
        expect(page.get_by_test_id("level-tab-2")).to_have_count(0)
        expect(page.get_by_test_id("level-tab-0")).to_have_attribute("aria-selected", "true")
        levels = self.field.http.get("/api/v1/field/levels").json()
        self.assertEqual((levels["count"], levels["names"]), (2, ["Ground floor", "Mezzanine"]))
        self.assertIsNone(self.field.bundle.controller.store.field_image(2))

    # --- the field grid (decisions MF-81 to MF-93) -----------------------------------

    def test_field_grid_helpers(self):
        """MF-83, MF-90: row letters after Z, a place's cell and an area's span, square cells (field-grid.js)."""
        page = self.console()
        got = page.evaluate("""() => import('./components/field-grid.js').then((m) => {
            const g = { enabled: true, rows: 8, cols: 10 };
            return [[0, 1, 25, 26, 27, 51].map(m.rowLabel),
                    m.gridCell(g, 0, 0), m.gridCell(g, 0.35, 0.3), m.gridCell(g, 1, 1), m.gridCell(g, 0.0999, 0.125),
                    m.gridCell({ enabled: true, rows: 30, cols: 52 }, 0.999, 0.89),
                    m.gridCell({ ...g, enabled: false }, 0.5, 0.5), m.gridCell(g, 1.2, 0.5),
                    m.gridSpan(g, [{ x: 0.12, y: 0.2 }, { x: 0.38, y: 0.6 }, { x: 0.2, y: 0.4 }]),
                    m.gridSpan(g, [{ x: 0.31, y: 0.26 }, { x: 0.33, y: 0.3 }]),
                    m.suggestGrid(2), m.suggestGrid(0.5), m.suggestGrid(1), m.suggestGrid(20),
                    m.cellSize(g, { w: 400, h: 200 }), m.cellSize({ rows: 3, cols: 4 }, { w: 30, h: 20 })];
        })""")
        self.assertEqual(got, [["A", "B", "Z", "AA", "AB", "AZ"], "A1", "C4", "H10", "B1", "AA52", "", "",
                               "B2–E4", "C4", {"rows": 4, "cols": 8}, {"rows": 8, "cols": 4},
                               {"rows": 8, "cols": 8}, {"rows": 1, "cols": 8}, "40 × 25 m", "7.5 × 6.7 m"])

    def test_field_grid_over_the_plan(self):
        """The maintainer's request (MF-81): a grid over the field image, lettered rows on the left and numbered
        columns on the top; set by the GM, live on every console, hidden by any viewer in their own browser; the
        boxes and map features say their cell; legible over the image; at phone width with 52 columns."""
        game = self.field.create_game(start=True)
        self.field.box_hello()
        self.field.http.put("/api/v1/field/image", headers={"Content-Type": "image/png"}, content=ICON.read_bytes())
        # About 870 m across and 445 m down: cells about square are 4 rows by 8 columns (MF-86).
        self.field.http.put("/api/v1/field/georef", json={"points": [
            {"x": 0, "y": 0, "lat": 38.7240, "lon": -9.1420}, {"x": 1, "y": 1, "lat": 38.7200, "lon": -9.1320}]})
        self.field.http.put(f"/api/v1/games/{game['id']}/positions/{BOX}", json={"x": 0.35, "y": 0.3})
        r = self.field.http.post("/api/v1/field/features", json={"type": "first_aid", "shape": "point", "x": 0.9,
                                                                 "y": 0.95, "label": "Posto"})
        self.assertEqual(r.status_code, 201, r.text)
        page = self.console()
        page.get_by_test_id("tab-field").click()
        expect(page.locator("[data-testid=field-area] img")).to_be_visible()
        expect(page.get_by_test_id("field-grid")).to_have_count(0)  # off until the GM turns it on
        expect(page.get_by_test_id("grid-show")).to_have_count(0)
        viewer = self.console(READ)
        viewer.get_by_test_id("tab-field").click()
        expect(viewer.get_by_test_id("grid-settings")).to_have_count(0)  # the GM's alone

        page.get_by_test_id("grid-toggle").click()  # checked once the controller has it
        grid = page.get_by_test_id("field-grid")
        expect(grid).to_have_attribute("data-rows", "4")
        expect(grid).to_have_attribute("data-cols", "8")
        self.assertEqual(self.field.http.get("/api/v1/field/grid").json()["grid"], {"enabled": True, "rows": 4, "cols": 8})
        expect(page.get_by_test_id("grid-size")).to_have_text("Cada quadrado tem cerca de 108 × 111 m no terreno.")
        expect(page.locator("#grid-rows-note")).to_have_text("De A a D")
        expect(grid.locator(".fg-row")).to_have_text(["A", "B", "C", "D"])
        expect(grid.locator(".fg-col")).to_have_text([str(c) for c in range(1, 9)])
        # Live on the other console (the stream's field_grid), with the cells said: the box, and the feature.
        expect(viewer.get_by_test_id("field-grid")).to_have_attribute("data-cols", "8")
        marker = viewer.locator(f'[data-testid=field-area] .marker[data-node="{BOX}"]')
        expect(marker).to_have_attribute("aria-label", re.compile(r", quadrícula B3$"))
        fid = r.json()["id"]
        expect(viewer.get_by_test_id(f"mf-cell-{fid}")).to_have_text("quadrícula D8")
        # Legible on light and dark imagery: white labels and lines on a dark halo; nothing to press.
        style = page.locator(".fg-row").first.evaluate(
            "(e) => { const s = getComputedStyle(e); return [s.color, s.textShadow, s.pointerEvents]; }")
        self.assertEqual(style[0], "rgb(255, 255, 255)")
        self.assertIn("rgb(0, 0, 0)", style[1])
        self.assertEqual(style[2], "none")
        strokes = grid.locator("path").evaluate_all("(ps) => ps.map((p) => getComputedStyle(p).stroke)")
        self.assertEqual(strokes, ["rgba(0, 0, 0, 0.55)", "rgba(255, 255, 255, 0.9)"])
        # The GM's numbers: refused out of range in the page; saved; square cells keep the columns.
        page.get_by_test_id("grid-rows").fill("53")
        page.get_by_test_id("grid-save").click()
        expect(page.get_by_test_id("grid-error")).to_have_text("As linhas vão de 1 a 52 e as colunas de 1 a 52.")
        page.get_by_test_id("grid-rows").fill("6")
        page.get_by_test_id("grid-cols").fill("10")
        page.get_by_test_id("grid-save").click()
        expect(viewer.get_by_test_id("field-grid")).to_have_attribute("data-rows", "6")
        expect(viewer.get_by_test_id(f"mf-cell-{fid}")).to_have_text("quadrícula F10")
        self.assertEqual(self.field.http.get("/api/v1/field/grid").json()["grid"], {"enabled": True, "rows": 6, "cols": 10})
        page.get_by_test_id("grid-square").click()
        expect(page.get_by_test_id("grid-rows")).to_have_value("5")
        expect(page.get_by_test_id("grid-cols")).to_have_value("10")
        # The viewer hides it in their own browser (kept across a reload); the GM's console still shows it.
        expect(viewer.get_by_test_id("grid-show-label")).to_have_text(re.compile(r"Mostrar a quadrícula \(A–F, 1–10\)"))
        viewer.get_by_test_id("grid-show").uncheck()
        expect(viewer.get_by_test_id("field-grid")).to_have_count(0)
        viewer.reload()
        viewer.get_by_test_id("tab-field").click()
        expect(viewer.locator("[data-testid=field-area] img")).to_be_visible()
        expect(viewer.get_by_test_id("grid-show")).not_to_be_checked()
        expect(viewer.get_by_test_id("field-grid")).to_have_count(0)
        expect(page.get_by_test_id("field-grid")).to_have_count(1)
        # At phone width, in English, with 52 columns: the numbers are thinned out to fit, the page does not
        # scroll sideways; turned off, it is gone everywhere.
        self.field.http.put("/api/v1/field/grid", json={"enabled": True, "rows": 52, "cols": 52})
        phone = self.console(width=390, height=844)
        phone.get_by_test_id("lang").select_option("en")
        phone.get_by_test_id("tab-field").click()
        small = phone.get_by_test_id("field-grid")
        expect(small).to_have_attribute("data-cols", "52")
        expect(phone.get_by_test_id("grid-size")).to_have_text("Each square is about 17 × 8.6 m on the ground.")
        expect(phone.locator("[data-testid=field-area] img")).to_be_visible()
        # The numbers are thinned once the image is laid out; wait for that rather than read the first render.
        expect(small.locator(".fg-col").first).not_to_have_text("1")  # the corner is the row letter's
        cols = small.locator(".fg-col").count()
        self.assertLess(cols, 52)
        self.assertGreater(cols, 4)
        expect(small.locator(".fg-row").first).to_have_text("A")
        self.no_horizontal_scroll(phone)
        page.get_by_test_id("grid-toggle").click()
        expect(phone.get_by_test_id("field-grid")).to_have_count(0)
        expect(page.get_by_test_id("field-grid")).to_have_count(0)
        self.assertEqual(self.field.http.get("/api/v1/field/grid").json()["grid"],
                         {"enabled": False, "rows": 52, "cols": 52})

    def test_field_grid_map_prints(self):
        """PKE-2: the grid map is printable (a poster or a PDF through the browser's own dialog): a sheet with the
        field's name, the plan under its grid, and what is in which cell; nothing without a grid; the sheet is gone
        again after printing, and the console itself is hidden for print by a class on <html>."""
        game = self.field.create_game(start=True)
        self.field.box_hello()
        self.field.http.put("/api/v1/field/image", headers={"Content-Type": "image/png"}, content=ICON.read_bytes())
        self.field.http.put(f"/api/v1/games/{game['id']}/positions/{BOX}", json={"x": 0.35, "y": 0.3})
        r = self.field.http.post("/api/v1/field/features", json={"type": "first_aid", "shape": "point", "x": 0.9,
                                                                 "y": 0.95, "label": "Posto"})
        self.assertEqual(r.status_code, 201, r.text)
        self.field.http.put("/api/v1/field/grid", json={"enabled": True, "rows": 8, "cols": 10})
        page = self.console()
        # No dialog in a headless browser: window.print() is recorded, with what the page held at that moment.
        page.evaluate("""() => { window.__printed = [];
            window.print = () => { const s = document.querySelector('[data-testid=grid-print-sheet]');
                window.__printed.push({ html: document.documentElement.className,
                    title: s && s.querySelector('h1').textContent,
                    plan: !!(s && s.querySelector('[data-testid=grid-print-plan] img')),
                    layer: !!(s && s.querySelector('[data-testid=grid-print-layer]')),
                    rows: s ? s.querySelectorAll('.fg-row').length : 0,
                    entries: s ? Array.from(s.querySelectorAll('[data-testid=grid-print-entries] li'))
                        .map((l) => l.textContent.replace(/\\s+/g, ' ').trim()) : [] }); }; }""")
        page.get_by_test_id("tab-field").click()
        expect(page.locator("[data-testid=field-area] img")).to_be_visible()
        expect(page.get_by_test_id("grid-print")).to_be_visible()
        page.get_by_test_id("grid-print").click()
        self.assertTrue(wait_for(lambda: page.evaluate("window.__printed.length") == 1, 6))
        got = page.evaluate("window.__printed[0]")
        self.assertIn("print-grid-map", got["html"])
        self.assertTrue(got["title"].endswith(": mapa com quadrícula"), got)
        self.assertTrue(got["plan"] and got["layer"])
        self.assertEqual(got["rows"], 8)
        self.assertTrue(any(e.startswith("C4 ") and str(BOX) in e for e in got["entries"]), got["entries"])
        self.assertTrue(any(e.startswith("H10 ") and "Posto" in e for e in got["entries"]), got["entries"])
        # Gone again after printing: the sheet, its root and the class.
        self.assertTrue(wait_for(lambda: page.evaluate(
            "!document.getElementById('grid-print-root') && !document.documentElement.classList.contains('print-grid-map')"), 6))
        expect(page.get_by_test_id("grid-print")).to_be_enabled()
        # A level with no grid has nothing to print.
        self.field.http.put("/api/v1/field/grid", json={"enabled": False})
        expect(page.get_by_test_id("grid-print")).to_have_count(0)

    def test_field_map_grid_over_the_preview(self):
        """MF-87: a grid put over the drawn image on *Load the field from a map*, saved with the field in the same
        request, then shown on the console's plan; a level's grid comes back on the page."""
        page = self.console(service_workers="block")
        seen = self.map_routes(page)
        page.goto(self.field.base + "/console/field-map.html")
        expect(page.get_by_test_id("tm")).to_be_visible()
        self.type_outline(page)
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        expect(page.get_by_test_id("fm-grid-toggle")).not_to_be_checked()
        expect(page.get_by_test_id("fm-grid")).to_have_count(0)
        page.get_by_test_id("fm-grid-toggle").check()
        # Cells about square on this image (its pixels are square on the ground): 8 along the longer side.
        size = page.get_by_test_id("fm-image").evaluate("(i) => [i.naturalWidth, i.naturalHeight]")
        wide = size[0] >= size[1]
        expect(page.get_by_test_id("fm-grid-cols" if wide else "fm-grid-rows")).to_have_value("8")
        page.get_by_test_id("fm-grid-rows").fill("0")
        expect(page.get_by_test_id("fm-grid-error")).to_be_visible()
        page.get_by_test_id("fm-grid-rows").fill("5")
        page.get_by_test_id("fm-grid-cols").fill("7")
        expect(page.get_by_test_id("fm-grid")).to_have_attribute("data-rows", "5")
        expect(page.get_by_test_id("fm-grid").locator(".fg-col")).to_have_count(7)
        expect(page.get_by_test_id("fm-grid-size")).to_contain_text(" m no terreno.")
        expect(page.locator("#fm-preview-h")).to_be_in_viewport()
        self.no_horizontal_scroll(page)
        page.get_by_test_id("fm-upload").click()
        expect(page).to_have_url(re.compile(r"/console/#field$"))
        self.assertEqual(self.field.http.get("/api/v1/field/grid").json()["grid"], {"enabled": True, "rows": 5, "cols": 7})
        expect(page.get_by_test_id("field-grid")).to_have_attribute("data-cols", "7")
        self.check_loaded(0, seen["wms"][0])
        # Opened again, the page starts from the level's grid.
        page.goto(self.field.base + "/console/field-map.html")
        expect(page.get_by_test_id("tm")).to_be_visible()
        self.type_outline(page)
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-grid-toggle")).to_be_checked()
        expect(page.get_by_test_id("fm-grid-rows")).to_have_value("5")
        self.assertEqual(seen["other"], [])

    # --- map features (decisions MF-0 to MF-16) ------------------------------------

    def features(self) -> list:
        return self.field.http.get("/api/v1/field/features").json()["features"]

    def press_area(self, page, x: float, y: float, to: "tuple[float, float] | None" = None) -> None:
        """A press on the plan at (x, y) as fractions of it; with ``to``, dragged there before letting go."""
        page.get_by_test_id("field-area").scroll_into_view_if_needed()
        area = page.get_by_test_id("field-area").bounding_box()
        # A plan taller than the window (the console grew a panel below it): bring the target point into view.
        for fy in [y] + ([to[1]] if to is not None else []):
            top = area["y"] + area["height"] * fy
            height = page.viewport_size["height"]
            if not 0 <= top <= height - 1:
                page.evaluate("(dy) => window.scrollBy(0, dy)", top - height / 2)
                area = page.get_by_test_id("field-area").bounding_box()
        page.mouse.move(area["x"] + area["width"] * x, area["y"] + area["height"] * y)
        page.mouse.down()
        if to is not None:
            page.mouse.move(area["x"] + area["width"] * to[0], area["y"] + area["height"] * to[1], steps=6)
        page.mouse.up()

    def test_map_features_shape_chosen_before_the_type(self):
        """Found on the bench (MF-17): the GM chose an area, then the type; a safe zone's or a respawn's usual
        circle must not take the area's place."""
        self.field.http.put("/api/v1/field/image", headers={"Content-Type": "image/png"}, content=ICON.read_bytes())
        page = self.console()
        page.get_by_test_id("tab-field").click()
        page.get_by_test_id("mf-new-type").select_option("safe_zone")
        page.get_by_test_id("mf-add").click()
        expect(page.get_by_test_id("mf-shape-circle")).to_be_checked()
        page.locator("label", has=page.get_by_test_id("mf-shape-polygon")).click()
        page.get_by_test_id("mf-type").select_option("respawn")
        expect(page.get_by_test_id("mf-shape-polygon")).to_be_checked()
        expect(page.get_by_test_id("mf-radius")).to_have_count(0)
        for x, y in ((0.3, 0.5), (0.6, 0.5), (0.5, 0.8)):
            self.press_area(page, x, y)
        expect(page.get_by_test_id("mf-hint")).to_contain_text("3 até agora")
        page.get_by_test_id("mf-save").click()
        self.assertTrue(wait_for(lambda: len(self.features()) == 1, 5))
        got = self.features()[0]
        self.assertEqual((got["type"], got["shape"], len(got["points"])), ("respawn", "polygon", 3))

    def test_map_features_on_the_plan(self):
        """The maintainer's request (MF-0): a safe zone dragged to scale, a red respawn placed by keyboard, a car park
        traced corner by corner and made the organisers' own, a read-only phone that sees only what is for everyone,
        and a feature deleted after a confirmation; in pt-PT."""
        h = self.field.http
        h.put("/api/v1/field/image", headers={"Content-Type": "image/png"}, content=ICON.read_bytes())
        h.put("/api/v1/field/georef", json={"points": [{"x": 0, "y": 0, "lat": 38.7240, "lon": -9.1420},
                                                        {"x": 1, "y": 1, "lat": 38.7200, "lon": -9.1360}]})
        page = self.console()
        page.get_by_test_id("tab-field").click()
        expect(page.get_by_role("heading", name="Marcações no mapa")).to_be_visible()
        expect(page.get_by_test_id("mf-none")).to_be_visible()
        # A safe zone: a circle, pressed at its centre and dragged to its edge, to the plan's scale.
        page.get_by_test_id("mf-new-type").select_option("safe_zone")
        page.get_by_test_id("mf-add").click()
        expect(page.get_by_test_id("mf-shape-circle")).to_be_checked()
        expect(page.get_by_test_id("mf-hint")).to_contain_text("arrasta até à borda")
        expect(page.get_by_test_id("mf-no-scale")).to_have_count(0)
        self.press_area(page, 0.3, 0.3, to=(0.4, 0.3))
        radius = float(page.get_by_test_id("mf-radius").input_value())
        self.assertAlmostEqual(radius, 52, delta=4)  # a tenth of a plan about 520 m wide
        page.get_by_test_id("mf-label").fill("Zona A")
        page.get_by_test_id("mf-save").click()
        expect(page.get_by_test_id("mf-form")).to_have_count(0)
        self.assertTrue(wait_for(lambda: len(self.features()) == 1, 5))
        zone = self.features()[0]
        self.assertEqual((zone["type"], zone["shape"], zone["label"], zone["visibility"]),
                         ("safe_zone", "circle", "Zona A", "everyone"))
        self.assertAlmostEqual(zone["x"], 0.3, delta=0.02)
        self.assertEqual(zone["radius_m"], radius)
        expect(page.locator("[data-testid=mf-layer] ellipse")).to_have_count(1)
        expect(page.get_by_test_id(f"mf-pin-{zone['id']}")).to_have_attribute("aria-label", "Zona segura: Zona A")
        # A respawn is a team's: red by default, for red only; placed with the keyboard.
        page.get_by_test_id("mf-new-type").select_option("respawn")
        page.get_by_test_id("mf-add").click()
        expect(page.get_by_test_id("mf-team")).to_have_value("red")
        expect(page.get_by_test_id("mf-visibility")).to_have_value("team")
        page.get_by_test_id("mf-shape-point").check()
        page.get_by_test_id("mf-across").fill("70")
        page.get_by_test_id("mf-down").fill("20")
        page.get_by_test_id("mf-put").click()
        page.get_by_test_id("mf-save").click()
        self.assertTrue(wait_for(lambda: len(self.features()) == 2, 5))
        respawn = self.features()[1]
        self.assertEqual((respawn["type"], respawn["shape"], respawn["team"], respawn["visibility"]),
                         ("respawn", "point", "red", "team"))
        self.assertEqual((respawn["x"], respawn["y"]), (0.7, 0.2))
        expect(page.get_by_test_id(f"mf-item-{respawn['id']}")).to_contain_text("Só red")
        # The car park: an area traced corner by corner, a wrong corner taken back, the last one typed.
        page.get_by_test_id("mf-new-type").select_option("parking")
        page.get_by_test_id("mf-add").click()
        expect(page.get_by_test_id("mf-shape-polygon")).to_be_checked()
        for x, y in ((0.1, 0.6), (0.3, 0.6), (0.9, 0.1), (0.3, 0.9)):
            self.press_area(page, x, y)
        expect(page.get_by_test_id("mf-hint")).to_contain_text("4 até agora")
        page.get_by_test_id("mf-undo").click()
        page.get_by_test_id("mf-save").click()  # three corners, but the wrong one among them
        self.assertTrue(wait_for(lambda: len(self.features()) == 3, 5))
        car = self.features()[2]
        self.assertEqual(len(car["points"]), 3)
        page.get_by_test_id(f"mf-edit-{car['id']}").click()
        page.get_by_test_id("mf-place").click()
        page.locator("button", has_text="Recomeçar").click()  # with no corners there is no undo
        expect(page.get_by_test_id("mf-hint")).to_contain_text("0 até agora")
        for x, y in ((0.1, 0.6), (0.3, 0.6), (0.3, 0.9)):
            self.press_area(page, x, y)
        page.get_by_test_id("mf-across").fill("10")
        page.get_by_test_id("mf-down").fill("90")
        page.get_by_test_id("mf-put").click()
        page.get_by_test_id("mf-visibility").select_option("organisers")
        page.get_by_test_id("mf-save").click()
        self.assertTrue(wait_for(lambda: self.features()[2]["visibility"] == "organisers", 5))
        car = self.features()[2]
        self.assertEqual(len(car["points"]), 4)
        self.assertEqual(car["points"][3], {"x": 0.1, "y": 0.9})
        expect(page.locator("[data-testid=mf-layer] polygon")).to_have_count(1)
        self.no_horizontal_scroll(page)
        # A read-only phone sees only the safe zone: the respawn is red's, the car park the organisers'.
        viewer = self.console(READ, width=390, height=844)
        viewer.get_by_test_id("tab-field").click()
        expect(viewer.get_by_test_id(f"mf-pin-{zone['id']}")).to_be_visible()
        expect(viewer.locator(".mf-pin")).to_have_count(1)
        expect(viewer.locator("[data-testid=mf-layer] polygon")).to_have_count(0)
        expect(viewer.get_by_test_id("mf-add")).to_have_count(0)
        expect(viewer.get_by_test_id(f"mf-edit-{zone['id']}")).to_have_count(0)
        viewer.locator("[data-testid=mf-legend] summary").click()
        expect(viewer.get_by_test_id("mf-legend")).to_contain_text("Primeiros socorros")
        self.no_horizontal_scroll(viewer)
        # The car park for everyone again: the phone gets it through the live stream.
        page.get_by_test_id(f"mf-edit-{car['id']}").click()
        page.get_by_test_id("mf-visibility").select_option("everyone")
        page.get_by_test_id("mf-save").click()
        expect(viewer.locator("[data-testid=mf-layer] polygon")).to_have_count(1)
        # Deleted after a confirmation, on both pages.
        page.get_by_test_id(f"mf-delete-{zone['id']}").click()
        expect(page.get_by_role("group", name="Apagar Zona A do mapa?")).to_be_visible()
        page.get_by_test_id(f"mf-delete-{zone['id']}-yes").click()
        expect(page.get_by_test_id(f"mf-pin-{zone['id']}")).to_have_count(0)
        expect(viewer.get_by_test_id(f"mf-pin-{zone['id']}")).to_have_count(0)
        self.assertEqual([f["id"] for f in self.features()], [respawn["id"], car["id"]])
        # The editor at phone width.
        phone = self.console(width=390, height=844)
        phone.get_by_test_id("tab-field").click()
        phone.get_by_test_id("mf-add").click()
        expect(phone.get_by_test_id("mf-form")).to_be_visible()
        self.no_horizontal_scroll(phone)

    def beacons(self) -> list:
        return self.field.http.get("/api/v1/beacons").json()["beacons"]

    def test_beacons_registry_and_their_place_on_the_plan(self):
        """ADR-P3-6 (BLE-1 to BLE-9): the GM adds the building's iBeacons, one placed with a click on the plan, one
        with the keyboard, one not at all; a wrong UUID is refused before anything is sent; one is changed, one taken
        out after a confirmation; another console learns of it through the stream, and a read-only page has no
        panel; in pt-PT."""
        uuid = "FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F"
        self.field.http.put("/api/v1/field/image", headers={"Content-Type": "image/png"}, content=ICON.read_bytes())
        page = self.console()
        page.get_by_test_id("tab-field").click()
        expect(page.get_by_role("heading", name="Balizas interiores")).to_be_visible()
        expect(page.get_by_test_id("bc-none")).to_be_visible()
        # A first beacon: a wrong UUID is said so, then one placed by a click on the plan.
        page.get_by_test_id("bc-add").click()
        page.get_by_test_id("bc-uuid").fill("nope")
        page.get_by_test_id("bc-major").fill("1")
        page.get_by_test_id("bc-minor").fill("1")
        page.get_by_test_id("bc-room").fill("Átrio")
        page.get_by_test_id("bc-save").click()
        expect(page.get_by_test_id("bc-error")).to_contain_text("UUID")
        self.assertEqual(self.beacons(), [])
        page.get_by_test_id("bc-uuid").fill(uuid.lower())
        expect(page.get_by_test_id("bc-place-state")).to_have_text("Sem lugar na planta")
        page.get_by_test_id("bc-place").click()
        expect(page.get_by_test_id("bc-hint")).to_contain_text("Clica na planta")
        self.press_area(page, 0.25, 0.5)
        expect(page.get_by_test_id("bc-place-state")).to_have_text("Na planta")
        page.get_by_test_id("bc-save").click()
        expect(page.get_by_test_id("bc-form")).to_have_count(0)
        self.assertTrue(wait_for(lambda: len(self.beacons()) == 1, 5))
        first = self.beacons()[0]
        self.assertEqual((first["id"], first["uuid"], first["room"], first["level"]), ("1:1", uuid, "Átrio", 0))
        self.assertAlmostEqual(first["x"], 0.25, delta=0.02)
        self.assertAlmostEqual(first["y"], 0.5, delta=0.02)
        expect(page.get_by_test_id("bc-pin-1:1")).to_have_attribute("aria-label", "Baliza 1:1: Átrio")
        expect(page.get_by_test_id("bc-item-1:1")).to_contain_text("Na planta")
        # A second: the UUID is the last one's, a zone, placed with the keyboard.
        page.get_by_test_id("bc-add").click()
        expect(page.get_by_test_id("bc-uuid")).to_have_value(uuid)
        page.get_by_test_id("bc-major").fill("1")
        page.get_by_test_id("bc-minor").fill("2")
        page.get_by_test_id("bc-room").fill("Corredor A")
        page.get_by_test_id("bc-zone").fill("Piso 0")
        page.get_by_test_id("bc-place").click()
        page.get_by_test_id("bc-across").fill("60")
        page.get_by_test_id("bc-down").fill("40")
        page.get_by_test_id("bc-put").click()
        page.get_by_test_id("bc-save").click()
        self.assertTrue(wait_for(lambda: len(self.beacons()) == 2, 5))
        second = self.beacons()[1]
        self.assertEqual((second["id"], second["zone"], second["x"], second["y"]), ("1:2", "Piso 0", 0.6, 0.4))
        expect(page.get_by_test_id("bc-item-1:2")).to_contain_text("Corredor A (Piso 0)")
        # A third, not placed on the plan: in the list, with no pin.
        page.get_by_test_id("bc-add").click()
        page.get_by_test_id("bc-major").fill("1")
        page.get_by_test_id("bc-minor").fill("3")
        page.get_by_test_id("bc-room").fill("Cave")
        page.get_by_test_id("bc-save").click()
        self.assertTrue(wait_for(lambda: len(self.beacons()) == 3, 5))
        expect(page.get_by_test_id("bc-item-1:3")).to_contain_text("Sem lugar na planta")
        expect(page.locator(".bc-pin")).to_have_count(2)
        # The same major and minor again: the controller refuses (409) and the form stays.
        page.get_by_test_id("bc-add").click()
        page.get_by_test_id("bc-major").fill("1")
        page.get_by_test_id("bc-minor").fill("3")
        page.get_by_test_id("bc-room").fill("Outra")
        page.get_by_test_id("bc-save").click()
        # Wait for the refusal itself: the form was visible before the answer came.
        expect(page.get_by_test_id("toast")).to_contain_text("1:3")
        expect(page.get_by_test_id("bc-form")).to_be_visible()
        self.drop_errors("HTTP 409", "409 (Conflict)")
        page.get_by_test_id("bc-cancel").click()
        # Change one: the pair is fixed, the room is not.
        page.get_by_test_id("bc-edit-1:1").click()
        expect(page.get_by_test_id("bc-major")).to_be_disabled()
        page.get_by_test_id("bc-room").fill("Átrio principal")
        page.get_by_test_id("bc-save").click()
        self.assertTrue(wait_for(lambda: self.beacons()[0]["room"] == "Átrio principal", 5))
        expect(page.get_by_test_id("bc-pin-1:1")).to_have_attribute("aria-label", "Baliza 1:1: Átrio principal")
        # Another console follows the registry through the stream; a read-only page has no panel.
        other = self.console()
        other.get_by_test_id("tab-field").click()
        expect(other.get_by_test_id("bc-item-1:3")).to_be_visible()
        viewer = self.console(READ)
        viewer.get_by_test_id("tab-field").click()
        expect(viewer.get_by_test_id("field-area")).to_be_visible()
        expect(viewer.get_by_test_id("beacons")).to_have_count(0)
        expect(viewer.locator(".bc-pin")).to_have_count(0)
        # Taken out after a confirmation, on both consoles.
        page.get_by_test_id("bc-delete-1:3").click()
        expect(page.get_by_role("group", name="Remover a baliza de Cave? Os telemóveis deixam de a comunicar.")).to_be_visible()
        page.get_by_test_id("bc-delete-1:3-yes").click()
        expect(page.get_by_test_id("bc-item-1:3")).to_have_count(0)
        expect(other.get_by_test_id("bc-item-1:3")).to_have_count(0)
        self.assertEqual([b["id"] for b in self.beacons()], ["1:1", "1:2"])
        self.no_horizontal_scroll(page)
        # The editor at phone width.
        phone = self.console(width=390, height=844)
        phone.get_by_test_id("tab-field").click()
        phone.get_by_test_id("bc-add").click()
        expect(phone.get_by_test_id("bc-form")).to_be_visible()
        self.no_horizontal_scroll(phone)

    def test_field_boxes_are_beacons_too(self):
        """Decisions BBC-1 to BBC-12: the boxes of the live game the GM has placed are listed as Field Boxes under
        the beacons (no pin: the box's own marker is its place), registered by themselves; the GM disables one,
        gives it a room, turns the field's boxes off; a read-only page has no panel; in pt-PT."""
        game = self.field.create_game(start=True)
        self.field.box_hello()
        self.field.http.put("/api/v1/field/image", headers={"Content-Type": "image/png"}, content=ICON.read_bytes())
        page = self.console()
        page.get_by_test_id("tab-field").click()
        expect(page.get_by_role("heading", name="Caixas de campo como balizas")).to_be_visible()
        expect(page.get_by_test_id("bc-box-none")).to_be_visible()  # not placed on a plan: no level, no beacon
        self.field.http.put(f"/api/v1/games/{game['id']}/positions/{BOX}", json={"x": 0.35, "y": 0.3})
        item = page.get_by_test_id(f"bc-box-{BOX}")
        expect(item).to_be_visible()  # the stream told this console
        expect(item).to_contain_text("Caixa de campo")
        expect(item).to_contain_text(f"45253:{BOX}")
        expect(page.locator(".bc-pin")).to_have_count(0)  # a box is not a pin
        expect(page.get_by_test_id("bc-none")).to_be_visible()  # and not one of the building's own beacons
        boxes = [b for b in self.beacons() if b.get("kind") == "box"]
        self.assertEqual([(b["node_id"], b["enabled"]) for b in boxes], [(BOX, True)])
        # A room of the GM's.
        page.get_by_test_id(f"bc-box-room-{BOX}").click()
        page.get_by_test_id("bc-box-room-input").fill("Cave")
        page.get_by_test_id("bc-box-room-save").click()
        self.assertTrue(wait_for(lambda: [b for b in self.beacons() if b.get("kind") == "box"][0]["room"] == "Cave", 5))
        expect(item).to_contain_text("Cave")
        # Disabled, then enabled.
        page.get_by_test_id(f"bc-box-toggle-{BOX}").click()
        self.assertTrue(wait_for(lambda: not [b for b in self.beacons() if b.get("kind") == "box"][0]["enabled"], 5))
        expect(item).to_contain_text("desativada")
        page.get_by_test_id(f"bc-box-toggle-{BOX}").click()
        self.assertTrue(wait_for(lambda: [b for b in self.beacons() if b.get("kind") == "box"][0]["enabled"], 5))
        # The field's switch.
        switch = page.get_by_test_id("bc-box-switch")
        expect(switch).to_be_checked()
        switch.uncheck()
        self.assertTrue(wait_for(lambda: not self.field.http.get("/api/v1/beacons").json()["box_beacons"]["enabled"], 5))
        switch.check()
        self.assertTrue(wait_for(lambda: self.field.http.get("/api/v1/beacons").json()["box_beacons"]["enabled"], 5))
        # A read-only page has no panel.
        viewer = self.console(READ)
        viewer.get_by_test_id("tab-field").click()
        expect(viewer.get_by_test_id("field-area")).to_be_visible()
        expect(viewer.get_by_test_id("bc-boxes")).to_have_count(0)
        self.no_horizontal_scroll(page)
        phone = self.console(width=390, height=844)
        phone.get_by_test_id("tab-field").click()
        expect(phone.get_by_test_id(f"bc-box-{BOX}")).to_be_visible()
        self.no_horizontal_scroll(phone)

    def test_map_features_in_english_without_a_map_position(self):
        """English; a plan without a map position draws a circle at a set size and says so; a feature for the
        organisers only never reaches a read-only page."""
        page = self.console()
        page.get_by_test_id("lang").select_option("en")
        page.get_by_test_id("tab-field").click()
        viewer = self.console(READ)
        viewer.get_by_test_id("tab-field").click()
        expect(page.get_by_role("heading", name="Map features")).to_be_visible()
        page.get_by_test_id("mf-new-type").select_option("safe_zone")
        page.get_by_test_id("mf-add").click()
        expect(page.get_by_test_id("mf-no-scale")).to_contain_text("drawn at a set size")
        page.get_by_test_id("mf-radius").fill("40")
        page.get_by_test_id("mf-save").click()
        expect(page.get_by_test_id("mf-error")).to_have_text("Place it on the plan first.")
        page.get_by_test_id("mf-across").fill("50")
        page.get_by_test_id("mf-down").fill("150")
        page.get_by_test_id("mf-put").click()
        expect(page.get_by_test_id("mf-error")).to_have_text("Type two numbers from 0 to 100.")
        page.get_by_test_id("mf-down").fill("50")
        page.get_by_test_id("mf-put").click()
        page.get_by_test_id("mf-save").click()
        self.assertTrue(wait_for(lambda: len(self.features()) == 1, 5))
        self.assertEqual(self.features()[0]["radius_m"], 40.0)
        expect(page.locator("[data-testid=mf-layer] ellipse.no-scale")).to_have_count(1)
        expect(viewer.locator("[data-testid=mf-layer] ellipse")).to_have_count(1)  # live, for everyone
        # First aid for the organisers only, clicked on the grid.
        page.get_by_test_id("mf-new-type").select_option("first_aid")
        page.get_by_test_id("mf-add").click()
        expect(page.get_by_test_id("mf-hint")).to_have_text("Click the plan where it goes.")
        page.get_by_test_id("mf-visibility").select_option("organisers")
        page.get_by_test_id("mf-label").fill("Medic tent")
        self.press_area(page, 0.8, 0.8)
        page.get_by_test_id("mf-save").click()
        self.assertTrue(wait_for(lambda: len(self.features()) == 2, 5))
        tent = self.features()[1]
        self.assertEqual((tent["visibility"], tent["label"]), ("organisers", "Medic tent"))
        expect(page.get_by_test_id(f"mf-pin-{tent['id']}")).to_have_attribute("aria-label", "First aid: Medic tent")
        expect(page.get_by_test_id(f"mf-item-{tent['id']}")).to_contain_text("Organisers only")
        viewer.reload()
        viewer.get_by_test_id("tab-field").click()
        expect(viewer.locator(".mf-pin")).to_have_count(1)
        expect(viewer.get_by_test_id(f"mf-pin-{tent['id']}")).to_have_count(0)
        r = httpx.get(self.field.base + "/api/v1/field/features", headers={"Authorization": f"Bearer {READ}"})
        self.assertNotIn("Medic tent", r.text)
        # "Other" needs a name.
        page.get_by_test_id("mf-new-type").select_option("other")
        page.get_by_test_id("mf-add").click()
        self.press_area(page, 0.2, 0.2)
        page.get_by_test_id("mf-save").click()
        expect(page.get_by_test_id("mf-error")).to_have_text("Give it a name.")
        page.get_by_test_id("mf-cancel").click()
        expect(page.get_by_test_id("mf-form")).to_have_count(0)

    # --- the field loaded from a map (MF-18, built as MF-19 to MF-30) -------------------------

    OVERPASS_2 = "https://overpass.private.coffee/api/interpreter"

    def map_routes(self, page, wms: str = "orthophoto.png", overpass: "list | None" = None,
                   nominatim: "dict[str, int] | None" = None, fallbacks: "dict[str, list] | None" = None) -> dict:
        """Answers the field-map page's origins from fixtures; anything else outside the controller is
        refused and recorded (no real network in the tests). Nominatim answers fixtures/nominatim.json, an
        empty list for a q containing "nowhere", or the status nominatim maps a q to. Each Overpass instance
        answers its list in turn (the last one again and again): a status (with CORS), "nocors" (a 502 without
        Access-Control-Allow-Origin, as a busy proxy may send), "abort" (no answer) or "hang" (never
        answers); the main instance answers `overpass` (default 200), the other one `fallbacks` by URL
        (default "abort"). seen["hosts"] lists the instances asked, in order; seen["wms"] the orthophoto
        for the image (a GetMap in EPSG:4326, any of the four orthophotos' origins: they all answer `wms`),
        seen["wms_tiles"] the map's *Ortofoto* tiles (any other request to those origins)."""
        seen: dict = {"tiles": 0, "overpass": [], "hosts": [], "wms": [], "wms_tiles": [], "search": [],
                      "other": []}
        answers = {self.OVERPASS_2: ["abort"], **(fallbacks or {}),
                   "https://overpass-api.de/api/interpreter": list(overpass or [200])}
        answers = {url: list(v) for url, v in answers.items()}
        ctx = page.context

        def search(route):
            q ={k: v[0] for k, v in parse_qs(urlsplit(route.request.url).query).items()}
            seen["search"].append({"q": q, "referer": route.request.headers.get("referer")})
            status = (nominatim or {}).get(q.get("q", ""), 200)
            if status != 200:
                route.fulfill(status=status, content_type="text/plain", headers=CORS, body="no")
            elif "nowhere" in q.get("q", ""):
                route.fulfill(status=200, content_type="application/json", headers=CORS, body="[]")
            else:
                route.fulfill(status=200, content_type="application/json", headers=CORS,
                              body=(FIXTURES / "nominatim.json").read_text(encoding="utf-8"))

        def other(route):
            if route.request.url.startswith(self.field.base):
                route.continue_()
            else:
                seen["other"].append(route.request.url)
                route.abort()

        def tiles(route):
            seen["tiles"] += 1
            route.fulfill(status=200, content_type="image/png", headers=CORS, body=(FIXTURES / "tile.png").read_bytes())

        def overpass_api(route):
            url = route.request.url
            seen["hosts"].append(urlsplit(url).hostname)
            if url == "https://overpass-api.de/api/interpreter":
                seen["overpass"].append(route.request.post_data or "")
            todo = answers[url]
            status = todo.pop(0) if len(todo) > 1 else todo[0]
            if status == "hang":
                return  # never answered: the page's own time limit ends it
            if status == "abort":
                route.abort("connectionrefused")
            elif status == "nocors":
                route.fulfill(status=502, content_type="text/plain", body="This Overpass API server is currently "
                              "at capacity. Retry your request using exponential backoff.")
            elif status != 200:
                route.fulfill(status=status, content_type="text/plain", headers=CORS, body="busy")
            else:
                route.fulfill(status=200, content_type="application/json", headers=CORS,
                              body=(FIXTURES / "overpass.json").read_text(encoding="utf-8"))

        def orthophoto(route):
            url = route.request.url
            tile = not ("REQUEST=GetMap" in url and "EPSG%3A4326" in url)
            seen["wms_tiles" if tile else "wms"].append(url)
            body = (FIXTURES / ("orthophoto.png" if tile else wms)).read_bytes()
            route.fulfill(status=200, content_type="image/png", headers=CORS, body=body)

        # Playwright runs the last matching route first: the catch-all is registered first.
        ctx.route("**/*", other)
        ctx.route("https://tile.openstreetmap.org/**", tiles)
        ctx.route("https://overpass-api.de/api/interpreter", overpass_api)
        ctx.route(self.OVERPASS_2, overpass_api)
        for origin in ORTHO_ORIGINS:
            ctx.route(f"{origin}/**", orthophoto)
        ctx.route("https://nominatim.openstreetmap.org/**", search)
        return seen

    def type_outline(self, page) -> None:
        for lat, lon in OUTLINE:
            page.get_by_test_id("fm-corner").fill(f"{lat}, {lon}")
            page.get_by_test_id("fm-corner-add").click()

    def check_loaded(self, level: int, wms_url: "str | None", label: str = "") -> dict:
        """The controller's side after *Use as the field*: the plan, the map position from the image's edges
        and the boundary as the outline in the image's coordinates."""
        path = "/api/v1/field/georef" if level == 0 else f"/api/v1/field/levels/{level}/georef"
        geo = self.field.http.get(path).json()["georef"]
        self.assertEqual(geo["kind"], "corners")
        (tl, br) = geo["points"]
        self.assertEqual((tl["x"], tl["y"], br["x"], br["y"]), (0, 0, 1, 1))
        north, west, south, east = tl["lat"], tl["lon"], br["lat"], br["lon"]
        if wms_url is not None:
            # The orthophoto was asked for exactly the image's edges (EPSG:4326: south, west, north, east).
            q = dict(p.split("=", 1) for p in wms_url.split("?", 1)[1].split("&"))
            self.assertEqual((q["CRS"], q["REQUEST"]), ("EPSG%3A4326", "GetMap"))
            bbox = [float(v) for v in q["BBOX"].replace("%2C", ",").split(",")]
            self.assertEqual(bbox, [south, west, north, east])
        # The outline's box with its margin: the image covers every corner, a little more on each side.
        self.assertLess(north, 39.6020)
        self.assertGreater(north, max(lat for lat, _ in OUTLINE))
        self.assertLess(west, min(lon for _, lon in OUTLINE))
        boundary = [f for f in self.features() if f["type"] == "boundary"]
        self.assertEqual(len(boundary), 1)
        b = boundary[0]
        self.assertEqual((b["level"], b["shape"], b["visibility"], b["label"], len(b["points"])),
                         (level, "polygon", "everyone", label, len(OUTLINE)))
        for p, (lat, lon) in zip(b["points"], OUTLINE):
            self.assertAlmostEqual(p["x"], (lon - west) / (east - west), places=6)
            self.assertAlmostEqual(p["y"], (north - lat) / (north - south), places=6)
        return {"north": north, "south": south, "west": west, "east": east}

    def test_field_from_a_map_in_portugal(self):
        """The maintainer's idea (MF-18): find the field, trace its outline, draw the image over the DGT
        orthophoto with OSM's data, and load it as the field image with its map position and boundary."""
        self.field.http.put("/api/v1/field/image", headers={"Content-Type": "image/png"}, content=ICON.read_bytes())
        page = self.console(service_workers="block")
        seen = self.map_routes(page)
        page.get_by_test_id("tab-field").click()
        page.get_by_test_id("field-from-map").click()
        expect(page.get_by_role("heading", name="Carregar o campo de um mapa")).to_be_attached()
        expect(page.get_by_test_id("tm")).to_be_visible()
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"^https://tile\.openstreetmap\.org/6/"))
        expect(page.locator(".tm-credit")).to_have_text("© OpenStreetMap contributors")
        # Finding the field: a typed place.
        page.get_by_test_id("fm-go").fill("39.6, -8.401")
        page.get_by_test_id("fm-go-button").click()
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"/17/"))
        self.assertGreater(seen["tiles"], 0)
        # A press on the map marks a corner; undo takes it away.
        page.get_by_test_id("tm").click(position={"x": 60, "y": 60})
        expect(page.get_by_test_id("fm-count")).to_have_text("1 de no máximo 12 cantos (pelo menos 3).")
        expect(page.locator(".tm-corner")).to_have_count(1)
        page.get_by_test_id("fm-undo").click()
        expect(page.get_by_test_id("fm-count")).to_contain_text("0 de no máximo")
        # With the keyboard: the arrows move the map, the cross marks the corner at the map's centre.
        page.get_by_test_id("tm").focus()
        page.keyboard.press("ArrowRight")
        page.get_by_test_id("fm-centre").click()
        expect(page.get_by_test_id("fm-corners")).to_contain_text("39.600000, -8.40014")
        page.get_by_test_id("fm-clear").click()
        # A typed corner that is not "latitude, longitude" is refused; then the five corners.
        page.get_by_test_id("fm-corner").fill("39.6")
        page.get_by_test_id("fm-corner-add").click()
        expect(page.get_by_test_id("fm-error")).to_contain_text("latitude, longitude")
        self.type_outline(page)
        expect(page.locator(".tm-shape")).to_have_count(1)
        expect(page.get_by_test_id("fm-ortho")).to_be_checked()  # in Portugal: the orthophoto as the base
        page.get_by_test_id("fm-label").fill("Campo da Mata")
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        # MF-59: the preview comes into view with the focus on its heading; *Use as the field* is right under it,
        # and the banner at the top says the image is not saved yet.
        expect(page.locator("#fm-preview-h")).to_be_focused()
        expect(page.locator("#fm-preview-h")).to_be_in_viewport()
        expect(page.get_by_test_id("fm-upload")).to_be_in_viewport()
        expect(page.get_by_test_id("fm-banner")).to_contain_text("ainda não está guardada")
        expect(page.get_by_test_id("fm-preview-next")).to_contain_text("até lá, nada fica guardado")
        expect(page.get_by_test_id("fm-size")).to_contain_text("A ortofoto (DGT) com os caminhos")
        expect(page.get_by_test_id("fm-image-credit")).to_have_text(
            "Créditos na imagem: Ortofotomapas © DGT (CC BY 4.0) · © OpenStreetMap contributors")
        expect(page.get_by_test_id("fm-replaces")).to_contain_text("O campo já tem imagem")
        # One Overpass query for the area and one orthophoto, at the image's size; the image is drawn.
        self.assertEqual(len(seen["overpass"]), 1)
        self.assertIn("out geom", seen["overpass"][0].replace("+", " "))
        self.assertEqual(len(seen["wms"]), 1)
        q = dict(p.split("=", 1) for p in seen["wms"][0].split("?", 1)[1].split("&"))
        size = page.get_by_test_id("fm-image").evaluate("(i) => [i.naturalWidth, i.naturalHeight]")
        self.assertEqual(size, [int(q["WIDTH"]), int(q["HEIGHT"])])
        self.assertGreater(size[0], 600)  # about half a metre per pixel over some 500 m
        colours = page.get_by_test_id("fm-image").evaluate("""(i) => {
            const c = document.createElement('canvas'); c.width = 64; c.height = 64;
            const g = c.getContext('2d'); g.drawImage(i, 0, 0, 64, 64);
            const d = g.getImageData(0, 0, 64, 64).data; const s = new Set();
            for (let k = 0; k < d.length; k += 4) s.add(`${d[k]},${d[k + 1]},${d[k + 2]}`);
            return s.size; }""")
        self.assertGreater(colours, 20)
        # MF-60: leaving with the image not used asks first; "Cancel" stays.
        asked: list[str] = []

        def answer(d, accept: bool) -> None:
            asked.append(d.message)
            d.accept() if accept else d.dismiss()

        page.once("dialog", lambda d: answer(d, False))
        page.get_by_test_id("fm-back").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        self.assertEqual(asked, ["A imagem do campo desenhada ainda não foi guardada. Sair na mesma e perdê-la?"])
        self.no_horizontal_scroll(page)
        # MF-63: saved, the page goes back to the console's Field tab, which says so (a status, read aloud).
        page.get_by_test_id("fm-upload").click()
        expect(page).to_have_url(re.compile(r"/console/#field$"))
        expect(page.get_by_test_id("field-loaded")).to_have_text(
            "Campo carregado do mapa: a imagem, a sua posição no mapa (ATAK) e o limite do campo estão guardados.")
        expect(page.get_by_test_id("field-loaded")).to_have_attribute("role", "status")
        self.assertEqual(len(asked), 1)  # no question once saved
        self.assertIsNone(page.evaluate("sessionStorage.getItem('atalaia.fieldmap.loaded')"))  # said once
        info = self.field.http.get("/api/v1/field").json()["image"]
        self.assertEqual(info["content_type"], "image/jpeg")
        self.check_loaded(0, seen["wms"][0], label="Campo da Mata")
        self.assertEqual(seen["other"], [])
        self.assertEqual(seen["hosts"], ["overpass-api.de"])
        self.assertEqual(seen["wms_tiles"], [])  # the map stayed on *Mapa*
        # Back in the console: the field tab, the plan dimmed outside the boundary, one boundary per level.
        expect(page.get_by_test_id("field-area").locator("img")).to_be_visible()
        expect(page.get_by_test_id("mf-outside")).to_have_count(1)
        expect(page.get_by_test_id("mf-list")).to_contain_text("Campo da Mata")
        expect(page.get_by_test_id("mf-list")).to_contain_text("Limite do campo")
        expect(page.locator("[data-testid=mf-new-type] option[value=boundary]")).to_be_disabled()
        expect(page.get_by_test_id("georef-top_left")).to_be_visible()

    def test_field_from_a_map_osm_only_in_english_on_a_phone(self):
        """English at phone width, on a level of a building: the orthophoto has no picture (white) so the
        image is drawn from OSM alone; a busy Overpass and an outline too big are said in words; offline,
        the page says it needs internet; a read token cannot use it."""
        self.field.http.put("/api/v1/field/levels", json={"enabled": True, "count": 2})
        page = self.console(width=390, height=844, service_workers="block")
        page.get_by_test_id("lang").select_option("en")
        seen = self.map_routes(page, wms="orthophoto-white.png", overpass=[429],
                               fallbacks={self.OVERPASS_2: [200]})
        page.goto(self.field.base + "/console/field-map.html?level=1")
        expect(page.get_by_role("heading", name="Load the field from a map")).to_be_attached()
        expect(page.get_by_test_id("fm-level")).to_have_value("1")
        # Too big: 5 km across.
        for corner in ("39.60, -8.40", "39.60, -8.34", "39.58, -8.37"):
            page.get_by_test_id("fm-corner").fill(corner)
            page.get_by_test_id("fm-corner-add").click()
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-error")).to_contain_text("The outline is too big")
        self.assertEqual(seen["overpass"], [])
        page.get_by_test_id("fm-clear").click()
        self.type_outline(page)
        # The main Overpass instance refuses (429): the second instance is asked at once, and the page says so.
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        expect(page.locator("#fm-preview-h")).to_be_focused()
        expect(page.locator("#fm-preview-h")).to_be_in_viewport()
        self.assertEqual(seen["hosts"], ["overpass-api.de", "overpass.private.coffee"])
        self.drop_errors("429")
        expect(page.get_by_test_id("fm-notice")).to_contain_text(
            "OpenStreetMap's data came from overpass.private.coffee (the main server was busy); this server's data may be a few months old.")
        expect(page.get_by_test_id("fm-notice")).to_contain_text("has no picture of this area")
        expect(page.get_by_test_id("fm-size")).to_contain_text("Drawn from OpenStreetMap's data.")
        expect(page.get_by_test_id("fm-image-credit")).to_have_text("Credits on the image: © OpenStreetMap contributors")
        expect(page.get_by_test_id("fm-replaces")).to_have_count(0)
        self.no_horizontal_scroll(page)
        page.get_by_test_id("fm-upload").click()
        # Back on the console's Field tab, on the level just loaded (MF-63).
        expect(page.get_by_test_id("field-loaded")).to_contain_text("loaded from the map: the plan")
        expect(page.get_by_test_id("field-area")).to_have_attribute("data-level", "1")
        self.no_horizontal_scroll(page)
        self.assertEqual(self.field.http.get("/api/v1/field").json()["levels"]["levels"][1]["image"]["content_type"],
                         "image/png")
        self.assertIsNone(self.field.http.get("/api/v1/field/georef").json()["georef"])  # level 0 untouched
        self.check_loaded(1, None)
        self.assertEqual(seen["other"], [])
        # Offline, the page says so (the rest of the console needs no internet).
        page.goto(self.field.base + "/console/field-map.html?level=1")
        expect(page.get_by_test_id("tm")).to_be_visible()
        page.context.set_offline(True)
        expect(page.get_by_test_id("fm-offline")).to_contain_text("needs internet")
        page.context.set_offline(False)
        # The read token's console cannot load a field.
        viewer = self.console(READ, service_workers="block")
        self.map_routes(viewer)
        viewer.goto(self.field.base + "/console/field-map.html")
        expect(viewer.get_by_test_id("fm-login")).to_be_visible()
        viewer.goto(self.field.base + "/console/#field")
        expect(viewer.get_by_test_id("field-from-map")).to_have_count(0)

    def test_map_fetching_turned_off_in_settings_closes_the_map_page(self):
        """LEG-50: the GM turns map fetching off in Settings (Portuguese, then each language's message); the field-map
        page then says so, shows no map and asks no map service for anything; the Field tab says it too; turned on
        again, the map comes back."""
        page = self.console(service_workers="block")
        seen = self.map_routes(page)
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("map-fetching-settings")).to_contain_text("Obtenção de mapas")
        expect(page.get_by_test_id("map-fetching")).to_be_checked()
        page.get_by_test_id("map-fetching").uncheck()
        expect(page.get_by_test_id("map-fetching-settings")).to_contain_text("Guardado")
        self.assertIs(self.field.http.get("/api/v1/settings/map-fetching").json()["map_fetching"], False)
        page.get_by_test_id("tab-field").click()
        expect(page.get_by_test_id("field-map-off")).to_contain_text("desligada")
        for lang, tag, words in (("pt", "pt-PT", "desligada neste campo"), ("en", "en", "turned off for this field"),
                                 ("de", "de", "ausgeschaltet"), ("zh-tw", "zh-Hant-TW", "已關閉地圖擷取")):
            page.goto(self.field.base + "/console/")
            expect(page.get_by_test_id("tab-settings")).to_be_visible()
            page.get_by_test_id("lang").first.select_option(lang)
            expect(page.locator("html")).to_have_attribute("lang", tag)  # saved before the page is left
            page.goto(self.field.base + "/console/field-map.html")
            expect(page.get_by_test_id("fm-off")).to_contain_text(words)
            expect(page.get_by_test_id("tm")).to_have_count(0)
        self.assertEqual(seen["tiles"], 0)
        for what in ("overpass", "hosts", "wms", "wms_tiles", "search", "other"):
            self.assertEqual(seen[what], [], what)
        # On again: the map page is itself again.
        self.field.http.put("/api/v1/settings/map-fetching", json={"map_fetching": True})
        page.goto(self.field.base + "/console/field-map.html")
        expect(page.get_by_test_id("tm")).to_be_visible()

    def test_field_map_finds_a_place_by_name(self):
        """MF-44 to MF-46, as the maintainer asked (2026-10-23): a place's name goes to Nominatim (mocked)
        only when the GM presses Search, never per keystroke, at most once a second, the same question once,
        with the page's origin as the Referer and the page's language; typed coordinates send nothing; up
        to five results, chosen with the keyboard, fit the map to the place; at phone width."""
        page = self.console(width=390, height=844, service_workers="block")
        seen = self.map_routes(page, nominatim={"Campo Recusado": 429})
        # The browser's monotonic clock at the moment the page hands each Nominatim request to fetch (FL-2):
        # the route handler's time.monotonic() also counted how late Playwright got round to each request.
        page.add_init_script(self.SENT_AT_STUB)
        page.goto(self.field.base + "/console/field-map.html")
        expect(page.get_by_test_id("tm")).to_be_visible()
        # "latitude, longitude" goes straight there, without a request.
        page.get_by_test_id("fm-go").fill("39.6, -8.401")
        page.get_by_test_id("fm-go-button").click()
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"/17/"))
        # Typing is not searching: nothing is sent until Search (no search as you type).
        page.get_by_test_id("fm-go").fill("")
        page.get_by_test_id("fm-go").press_sequentially("Campo da Mata", delay=30)
        page.wait_for_timeout(400)
        self.assertEqual(seen["search"], [])
        page.get_by_test_id("fm-go").press("Enter")
        expect(page.get_by_test_id("fm-place")).to_have_count(3)  # the result without a position is left out
        expect(page.get_by_test_id("fm-place-status")).to_have_text(
            "Sítios encontrados: 3. Escolhe um para levar o mapa até lá.")
        expect(page.get_by_test_id("fm-search-credit")).to_contain_text("Nominatim")
        expect(page.get_by_test_id("fm-search-credit").locator("a")).to_have_attribute(
            "href", "https://www.openstreetmap.org/copyright")
        self.assertEqual(len(seen["search"]), 1)
        self.assertEqual(seen["search"][0]["q"], {"format": "jsonv2", "q": "Campo da Mata", "limit": "5",
                                                  "accept-language": "pt-PT,pt",
                                                  "email": "falecom@andersonleite.me"})
        self.assertEqual(seen["search"][0]["referer"], self.field.base + "/")  # the origin only
        self.no_horizontal_scroll(page)  # a long name wraps
        # With the keyboard: the result is a button; the map fits the place's box, and takes the focus.
        page.get_by_test_id("fm-place").first.focus()
        page.keyboard.press("Enter")
        expect(page.get_by_test_id("fm-places")).to_have_count(0)
        expect(page.get_by_test_id("fm-place-status")).to_have_text("No mapa: Campo da Mata, Vale Fictício, Portugal")
        expect(page.get_by_test_id("tm")).to_be_focused()
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"/16/"))  # 560 m across
        page.get_by_test_id("fm-centre").click()
        expect(page.get_by_test_id("fm-corners")).to_contain_text("39.600000, -8.401000")
        page.get_by_test_id("fm-clear").click()
        # The same question again: answered from the page's memory, not sent again.
        page.get_by_test_id("fm-go").fill("campo  da mata")
        page.get_by_test_id("fm-go-button").click()
        expect(page.get_by_test_id("fm-place")).to_have_count(3)
        self.assertEqual(len(seen["search"]), 1)
        # At most one request a second: a second search right after the first waits.
        page.get_by_test_id("fm-go").fill("Mata Grande")
        page.get_by_test_id("fm-go-button").click()
        expect(page.get_by_test_id("fm-place")).to_have_count(3)
        # A step of the wall clock does not shorten the second (FL-2): it is timed on the monotonic clock.
        page.evaluate("window.__clockStep = 900")
        page.get_by_test_id("fm-go").fill("nowhere at all")
        page.get_by_test_id("fm-go-button").click()
        expect(page.get_by_test_id("fm-place-status")).to_have_text(
            "Nenhum sítio encontrado para «nowhere at all». Experimenta outro nome, ou escreve «latitude, longitude».")
        expect(page.get_by_test_id("fm-search-credit")).to_be_visible()
        self.assertEqual(len(seen["search"]), 3)
        sent = page.evaluate("window.__nominatimSentAt")
        self.assertEqual(len(sent), 3)  # one fetch per request the route saw: nothing cached was sent
        self.assertGreaterEqual(sent[2] - sent[1], 1000 - 5)  # ms; the policy's 1 s (a timer's rounding aside)
        # Refused (a block or too many requests) is said in words; an empty search sends nothing.
        page.get_by_test_id("fm-go").fill("Campo Recusado")
        page.get_by_test_id("fm-go-button").click()
        expect(page.get_by_test_id("fm-error")).to_contain_text("recusou ou está ocupada (HTTP 429)")
        self.errors = [e for e in self.errors if "429" not in e]
        page.get_by_test_id("fm-go").fill("  ")
        page.get_by_test_id("fm-go-button").click()
        expect(page.get_by_test_id("fm-error")).to_have_text("Escreve o nome de um sítio, ou «latitude, longitude».")
        self.assertEqual(len(seen["search"]), 4)
        self.assertEqual((seen["other"], seen["overpass"], seen["wms"]), ([], [], []))
        self.no_horizontal_scroll(page)

    # Records when the page hands each Nominatim request to fetch, on the browser's monotonic clock, and lets a
    # test step the wall clock (Date.now) forward by window.__clockStep ms, as a time sync may.
    SENT_AT_STUB = """(() => {
        const real = window.fetch.bind(window);
        const dateNow = Date.now.bind(Date);
        window.__clockStep = 0;
        Date.now = () => dateNow() + window.__clockStep;
        window.__nominatimSentAt = [];
        window.fetch = (input, init) => {
            const url = typeof input === 'string' ? input : (input && input.url) || '';
            if (url.startsWith('https://nominatim.openstreetmap.org/')) window.__nominatimSentAt.push(performance.now());
            return real(input, init);
        };
    })();"""

    GEO_STUB = """(() => {
        const geo = navigator.geolocation;
        const real = geo.getCurrentPosition.bind(geo);
        geo.getCurrentPosition = (ok, err, o) => (window.__geoFail
            ? setTimeout(() => err({ code: window.__geoFail, message: 'test' }), 10) : real(ok, err, o));
        Object.defineProperty(window, 'isSecureContext', { configurable: true, get: () => !window.__insecure });
    })();"""

    def test_field_map_uses_the_gms_location(self):
        """MF-41 to MF-43, MF-47: already allowed, the page opens at the GM's location (a level's map position
        wins); *Use my location* asks again; only this page may ask; the position is sent nowhere."""
        here = {"latitude": 38.7071, "longitude": -9.1355, "accuracy": 25}
        page = self.console(service_workers="block", permissions=["geolocation"], geolocation=here)
        allows = "(document.permissionsPolicy || document.featurePolicy).allowsFeature('geolocation')"
        self.assertFalse(page.evaluate(allows))  # the console itself may not ask (geolocation=())
        seen = self.map_routes(page)
        sent: list[str] = []
        page.on("request", lambda r: sent.append(f"{r.url} {r.post_data or ''}"))
        page.goto(self.field.base + "/console/field-map.html")
        self.assertTrue(page.evaluate(allows))
        expect(page.get_by_test_id("fm-place-status")).to_have_text(
            "O mapa está na tua localização (precisão de cerca de 25 m).")
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"/17/"))
        page.get_by_test_id("fm-centre").click()
        expect(page.get_by_test_id("fm-corners")).to_contain_text("38.707100, -9.135500")
        page.get_by_test_id("fm-clear").click()
        # The button: elsewhere first, then a new fix.
        page.get_by_test_id("fm-go").fill("39.6, -8.401")
        page.get_by_test_id("fm-go-button").click()
        page.context.set_geolocation({"latitude": 39.5, "longitude": -8.2, "accuracy": 8})
        page.get_by_test_id("fm-locate").click()
        expect(page.get_by_test_id("fm-place-status")).to_have_text(
            "O mapa está na tua localização (precisão de cerca de 8 m).")
        page.get_by_test_id("fm-centre").click()
        expect(page.get_by_test_id("fm-corners")).to_contain_text("39.500000, -8.200000")
        page.get_by_test_id("fm-clear").click()
        # The positions went nowhere: not to the controller, not to any other origin.
        self.assertGreater(len(sent), 5)
        for s in sent:
            for coord in ("38.707", "9.135", "39.5", "-8.2"):
                self.assertNotIn(coord, s)
        self.assertEqual((seen["search"], seen["other"]), ([], []))
        # A level with a map position opens there, not at the GM's location.
        self.field.http.put("/api/v1/field/image", headers={"Content-Type": "image/png"}, content=ICON.read_bytes())
        r = self.field.http.put("/api/v1/field/georef", json={"points": [
            {"x": 0, "y": 0, "lat": 38.7240, "lon": -9.1420}, {"x": 1, "y": 1, "lat": 38.7200, "lon": -9.1360}]})
        self.assertEqual(r.status_code, 200, r.text)
        page.reload()
        expect(page.get_by_test_id("tm")).to_be_visible()
        page.wait_for_timeout(500)
        expect(page.get_by_test_id("fm-place-status")).to_have_count(0)
        page.get_by_test_id("fm-centre").click()
        expect(page.get_by_test_id("fm-corners")).to_contain_text("38.722000, -9.139000")

    def test_field_map_location_errors_in_english(self):
        """MF-41: without permission nothing is asked on open; a denial, a timeout, no position and a page
        that is not a secure context are said in words."""
        page = self.console(service_workers="block")
        page.get_by_test_id("lang").select_option("en")
        page.context.add_init_script(self.GEO_STUB)
        seen = self.map_routes(page)
        page.goto(self.field.base + "/console/field-map.html")
        expect(page.get_by_test_id("tm")).to_be_visible()
        page.wait_for_timeout(500)
        expect(page.get_by_test_id("fm-place-status")).to_have_count(0)  # not allowed yet: no prompt on open
        expect(page.get_by_test_id("fm-error")).to_have_count(0)
        page.get_by_test_id("fm-locate").click()
        expect(page.get_by_test_id("fm-error")).to_have_text(
            "This page is not allowed your location. You can allow it in the browser's settings for this address, "
            "or search for the place by name.")
        page.evaluate("window.__geoFail = 3")
        page.get_by_test_id("fm-locate").click()
        expect(page.get_by_test_id("fm-error")).to_contain_text("took too long")
        page.evaluate("window.__geoFail = 2")
        page.get_by_test_id("fm-locate").click()
        expect(page.get_by_test_id("fm-error")).to_contain_text("could not tell where it is")
        page.evaluate("window.__insecure = true")
        page.get_by_test_id("fm-locate").click()
        expect(page.get_by_test_id("fm-error")).to_contain_text("only to secure pages")
        expect(page.get_by_test_id("fm-error")).to_contain_text("127.0.0.1")
        self.assertEqual((seen["search"], seen["other"]), ([], []))

    # --- the field map in real use (2026-10-23): layout, a busy Overpass, the orthophoto layer (MF-50..MF-63)

    RETRY_JS = "(o) => import('./components/field-render.js').then((m) => { Object.assign(m.RETRY, o); })"

    def field_map(self, width: int = 1280, height: int = 900, lang: str = "", **routes):
        """The field-map page for the GM, its outside origins answered by map_routes(**routes)."""
        page = self.console(width=width, height=height, service_workers="block")
        if lang:
            page.get_by_test_id("lang").select_option(lang)
        seen = self.map_routes(page, **routes)
        page.goto(self.field.base + "/console/field-map.html")
        expect(page.get_by_test_id("tm")).to_be_visible()
        return page, seen

    def test_field_map_overpass_busy_retries_and_other_instances(self):
        """MF-50 to MF-52, after the maintainer met "This Overpass API server is currently at capacity" (502):
        the page waits with backoff and jitter, says it is retrying and when, asks the other public instances
        meanwhile, takes a 502 without CORS (a network error to the page) as busy too, and after the tries
        says the service is busy, in words."""
        page, seen = self.field_map(overpass=[502, 200])
        self.type_outline(page)
        page.get_by_test_id("fm-ortho").uncheck()  # OpenStreetMap alone: only Overpass is asked
        page.get_by_test_id("fm-draw").click()
        # The main instance said 502; the other did not answer; the main one is asked again after its
        # backoff, and the status line (and the banner at the top) count the seconds down.
        expect(page.get_by_test_id("fm-busy")).to_contain_text(
            re.compile(r"está ocupado: nova tentativa em \d+ s \(overpass-api\.de\)"))
        expect(page.get_by_test_id("fm-banner")).to_contain_text("nova tentativa em")
        expect(page.get_by_test_id("fm-cancel")).to_be_visible()
        expect(page.get_by_test_id("fm-preview")).to_be_visible(timeout=15000)
        self.assertEqual(seen["hosts"], ["overpass-api.de", "overpass.private.coffee", "overpass-api.de"])
        expect(page.get_by_test_id("fm-notice")).to_have_count(0)  # the main instance answered in the end
        # A 502 without Access-Control-Allow-Origin is a network error to the page: busy or unreachable, so
        # the next instance is asked, and the page says where the data came from.
        page.get_by_test_id("fm-redraw").click()
        seen = self.map_routes(page, overpass=["nocors"], fallbacks={self.OVERPASS_2: [200]})
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        self.assertEqual(seen["hosts"], ["overpass-api.de", "overpass.private.coffee"])
        expect(page.get_by_test_id("fm-notice")).to_have_text(
            "Os dados do OpenStreetMap vieram de overpass.private.coffee (o servidor principal estava ocupado); "
            "os deste servidor podem estar uns meses atrasados.")
        # Every instance busy (a 429 rests that instance 30 s): after the tries, within the time allowed (made
        # short here), the page says so; nothing is left running.
        page.get_by_test_id("fm-redraw").click()
        page.evaluate(self.RETRY_JS, {"baseMs": 200, "capMs": 400, "budgetMs": 2500})
        seen = self.map_routes(page, overpass=[503], fallbacks={self.OVERPASS_2: [429]})
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-error")).to_contain_text(
            "Os servidores de dados do OpenStreetMap estão ocupados (HTTP 50", timeout=10000)
        expect(page.get_by_test_id("fm-busy")).to_have_count(0)
        expect(page.get_by_test_id("fm-banner")).to_have_count(0)
        expect(page.get_by_test_id("fm-draw")).to_be_enabled()
        self.assertLessEqual(len(seen["hosts"]), 6)
        self.assertEqual(seen["hosts"][:3], ["overpass-api.de", "overpass.private.coffee", "overpass-api.de"])
        self.assertEqual(seen["hosts"].count("overpass.private.coffee"), 1)  # refused (429): not asked again so soon
        self.assertNotIn("maps.mail.ru", seen["hosts"])
        self.assertEqual(seen["other"], [])
        self.drop_errors("502", "503", "504", "429", "ERR_CONNECTION_REFUSED", "CORS", "Failed to fetch")

    def test_field_map_overpass_timeout_and_cancel(self):
        """The maintainer's page waited for ever on a stalled Overpass request: each request now has its own
        time limit (a little over the query's 25 s; made short here), after which the next instance is asked;
        the status line says which try and that it waits; *Cancel* ends a wait at once. In English."""
        page, seen = self.field_map(lang="en", width=390, height=844, overpass=["hang"],
                                    fallbacks={self.OVERPASS_2: ["hang", 200]})
        page.evaluate(self.RETRY_JS, {"requestMs": 1500})
        self.type_outline(page)
        page.get_by_test_id("fm-ortho").uncheck()
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-busy")).to_have_text("Fetching OpenStreetMap's data for the area…")
        expect(page.get_by_test_id("fm-busy")).to_have_text(
            "Fetching OpenStreetMap's data from overpass.private.coffee (try 2 of at most 6), waiting for the "
            "answer…", timeout=5000)
        expect(page.get_by_test_id("fm-preview")).to_be_visible(timeout=20000)
        self.assertEqual(seen["hosts"][:2], ["overpass-api.de", "overpass.private.coffee"])
        self.assertEqual(seen["hosts"][-1], "overpass.private.coffee")
        expect(page.get_by_test_id("fm-notice")).to_contain_text("came from overpass.private.coffee")
        self.no_horizontal_scroll(page)
        # Cancel: every instance silent; the GM stops waiting.
        page.get_by_test_id("fm-redraw").click()
        page.evaluate(self.RETRY_JS, {"requestMs": 35000})
        seen = self.map_routes(page, overpass=["hang"], fallbacks={self.OVERPASS_2: ["hang"]})
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-busy")).to_be_visible()
        expect(page.get_by_test_id("fm-banner")).to_have_attribute("aria-hidden", "true")  # said once, beside Draw
        page.get_by_test_id("fm-cancel").click()
        expect(page.get_by_test_id("fm-notice")).to_have_text(
            "Cancelled: nothing more is asked of OpenStreetMap. You can draw again whenever you like.")
        expect(page.get_by_test_id("fm-busy")).to_have_count(0)
        expect(page.get_by_test_id("fm-cancel")).to_have_count(0)
        expect(page.get_by_test_id("fm-draw")).to_be_enabled()
        expect(page.get_by_test_id("fm-error")).to_have_count(0)
        page.wait_for_timeout(500)
        self.assertEqual(seen["hosts"], ["overpass-api.de"])  # nothing asked after the cancel
        self.drop_errors("ERR_ABORTED", "ERR_FAILED", "ERR_CONNECTION_REFUSED", "Failed to fetch", "aborted")

    def test_field_map_outline_kept_across_a_reload(self):
        """MF-61: a page stuck waiting can be reloaded without tracing the outline again: the corners (only
        they) are kept for this tab, per level; MF-60: a reload with a drawn image not used asks first, and
        nothing is asked when no image is drawn."""
        page, seen = self.field_map()
        dialogs: list[str] = []

        def on_dialog(d) -> None:
            dialogs.append(d.type)
            d.accept()

        page.on("dialog", on_dialog)
        for lat, lon in OUTLINE[:2]:
            page.get_by_test_id("fm-corner").fill(f"{lat}, {lon}")
            page.get_by_test_id("fm-corner-add").click()
        page.reload()
        expect(page.get_by_test_id("fm-count")).to_have_text("2 de no máximo 12 cantos (pelo menos 3).")
        expect(page.get_by_test_id("fm-place-status")).to_have_text(
            "O limite que estavas a desenhar voltou (2 cantos): podes continuar.")
        expect(page.locator(".tm-corner")).to_have_count(2)
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"/1[6-7]/"))  # shown on the map
        self.assertEqual(dialogs, [])  # nothing drawn: no question
        page.get_by_test_id("fm-clear").click()
        self.type_outline(page)
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        page.reload()
        expect(page.get_by_test_id("fm-count")).to_contain_text("5 de no máximo")
        self.assertEqual(dialogs, ["beforeunload"])
        expect(page.get_by_test_id("fm-preview")).to_have_count(0)  # the image is not kept, only the corners
        expect(page.get_by_test_id("fm-corners")).to_contain_text("39.601500, -8.403000")
        # Kept for this tab only, and only the corners.
        kept = json.loads(page.evaluate("sessionStorage.getItem('atalaia.fieldmap.outline.0')"))
        self.assertEqual(kept, [{"lat": lat, "lon": lon} for lat, lon in OUTLINE])
        self.assertIsNone(page.evaluate("localStorage.getItem('atalaia.fieldmap.outline.0')"))
        # Start again empties it.
        page.get_by_test_id("fm-clear").click()
        self.assertIsNone(page.evaluate("sessionStorage.getItem('atalaia.fieldmap.outline.0')"))
        self.assertEqual(seen["other"], [])

    def test_field_map_layout_at_every_width(self):
        """The maintainer's desktop (about 1850 px wide) left the page's left part empty: one centred column on
        a phone, the map with the outline beside it from 64rem, centred and up to 100rem wide; no sideways
        scroll at 320, 390, 768, 1280 and 1850 px. Screenshots go to ATALAIA_SCREENSHOTS when set."""
        page, _ = self.field_map(width=1850)
        self.type_outline(page)
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        shots = os.environ.get("ATALAIA_SCREENSHOTS")
        for width in (320, 390, 768, 1280, 1850):
            page.set_viewport_size({"width": width, "height": 900})
            page.evaluate("window.dispatchEvent(new Event('resize'))")
            page.wait_for_timeout(150)
            self.no_horizontal_scroll(page)
            # All in one go, in page coordinates (a scroll between two measures would move them).
            main, card, side, preview = page.evaluate("""() => ['main', '.fm-find-card', '.fm-side',
                '[data-testid=fm-preview]'].map((s) => { const r = document.querySelector(s).getBoundingClientRect();
                return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height }; })""")
            left, right = main["x"], width - main["x"] - main["width"]
            self.assertAlmostEqual(left, right, delta=2, msg=f"{width} px: the page is centred")
            self.assertGreaterEqual(card["width"], min(width, 1600) * 0.55, f"{width} px: the map gets the width")
            if width >= 1024:  # 64rem: the outline beside the map, the preview across both
                self.assertGreaterEqual(side["x"], card["x"] + card["width"], f"{width} px")
                self.assertLess(abs(side["y"] - card["y"]), 2, f"{width} px")
                self.assertGreaterEqual(preview["width"], card["width"] + side["width"], f"{width} px")
            else:
                self.assertGreaterEqual(side["y"], card["y"] + card["height"], f"{width} px")
                self.assertAlmostEqual(side["width"], card["width"], delta=1, msg=f"{width} px")
            if width == 1850:
                self.assertGreaterEqual(main["width"], 1550)  # no empty half
                self.assertLessEqual(left, 130)
            self.assertLessEqual(page.get_by_test_id("fm-image").bounding_box()["height"], 900 * 0.7 + 1)
            png = page.screenshot(full_page=True)
            self.assertGreater(len(png), 1000)
            if shots:
                Path(shots).mkdir(parents=True, exist_ok=True)
                (Path(shots) / f"field-map-{width}.png").write_bytes(png)

    def test_field_map_orthophoto_layer(self):
        """MF-54 to MF-57: in mainland Portugal the map can show the DGT orthophoto (WMS GetMap per 256-pixel
        tile in EPSG:3857, only the tiles in view, each once), with its credit while shown; the choice is
        remembered in this browser; outside its coverage only the map is offered, and why is said."""
        page, seen = self.field_map()
        page.get_by_test_id("fm-go").fill("39.6, -8.401")
        page.get_by_test_id("fm-go-button").click()
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"^https://tile\.openstreetmap\.org/17/"))
        expect(page.get_by_test_id("fm-layer-map")).to_be_checked()  # the default stays *Mapa*
        self.assertEqual(seen["wms_tiles"], [])
        page.get_by_text("Ortofoto (DGT)", exact=True).click()
        expect(page.get_by_test_id("fm-layer-ortho")).to_be_checked()
        expect(page.locator(".tm-tile").first).to_have_attribute(
            "src", re.compile(r"^https://ortos\.dgterritorio\.gov\.pt/wms/ortosat2023\?"))
        expect(page.get_by_test_id("tm-credit")).to_have_text("Ortofotomapas © DGT (CC BY 4.0)")
        page.wait_for_function("[...document.querySelectorAll('.tm-tile')].every((i) => i.complete)")
        tiles = page.locator(".tm-tile").evaluate_all("(l) => l.map((i) => i.src)")
        # Only the tiles in view, each asked once, each a GetMap of exactly one zoom-17 tile.
        self.assertEqual(sorted(seen["wms_tiles"]), sorted(tiles))
        side = 2 * 20037508.342789244 / 2 ** 17
        for url in seen["wms_tiles"]:
            q = {k: v[0] for k, v in parse_qs(urlsplit(url).query, keep_blank_values=True).items()}
            self.assertEqual({k: v for k, v in q.items() if k != "BBOX"}, {
                "SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap", "LAYERS": "ortoSat2023-CorVerdadeira",
                "STYLES": "", "CRS": "EPSG:3857", "WIDTH": "256", "HEIGHT": "256", "FORMAT": "image/jpeg"})
            x0, y0, x1, y1 = (float(v) for v in q["BBOX"].split(","))
            self.assertAlmostEqual(x1 - x0, side, delta=0.02)
            self.assertAlmostEqual(y1 - y0, side, delta=0.02)
            frac = ((x0 + 20037508.342789244) / side) % 1
            self.assertLess(min(frac, 1 - frac), 1e-4)  # on the tile grid
        # Panning away and back asks only for the new tiles: the ones seen are kept.
        asked = len(seen["wms_tiles"])
        page.get_by_test_id("tm").focus()
        page.keyboard.press("ArrowRight")
        page.keyboard.press("ArrowLeft")
        page.wait_for_function("[...document.querySelectorAll('.tm-tile')].every((i) => i.complete)")
        self.assertLessEqual(len(seen["wms_tiles"]) - asked, 8)  # one column of new tiles at most
        self.assertEqual(len(set(seen["wms_tiles"])), len(seen["wms_tiles"]))
        # A corner pressed on the orthophoto is a corner as on the map.
        page.get_by_test_id("fm-centre").click()
        expect(page.get_by_test_id("fm-corners")).to_contain_text("39.600000, -8.401000")
        # Remembered in this browser.
        page.get_by_test_id("fm-clear").click()
        page.reload()
        expect(page.get_by_test_id("fm-layer-ortho")).to_be_checked()
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"^https://ortos\."))
        # Outside every orthophoto's coverage (Vienna): only the map, and why.
        page.get_by_test_id("fm-go").fill("48.2082, 16.3738")
        page.get_by_test_id("fm-go-button").click()
        expect(page.get_by_test_id("fm-layers")).to_have_count(0)
        expect(page.get_by_test_id("fm-layer-none")).to_have_text(
            "Aqui só há o mapa do OpenStreetMap: só há fotografia aérea aberta de alta resolução que se possa usar "
            "em Portugal continental, Espanha, França (com a Córsega e os territórios ultramarinos), nos Países "
            "Baixos, na Bélgica, no Luxemburgo, na Suíça e no Liechtenstein, na Polónia, na Chéquia e na Alemanha "
            "menos Baden-Württemberg, Baixa Saxónia, Hamburgo, Saxónia-Anhalt e Schleswig-Holstein.")
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"^https://tile\.openstreetmap\.org/"))
        for origin in ORTHO_ORIGINS:
            expect(page.locator(f".tm-tile[src^='{origin}']")).to_have_count(0)
        expect(page.get_by_test_id("tm-credit")).to_have_text("© OpenStreetMap contributors")
        # Back in Portugal, the orthophoto again (the choice was kept).
        page.get_by_test_id("fm-go").fill("38.6296, -9.1505")
        page.get_by_test_id("fm-go-button").click()
        expect(page.get_by_test_id("fm-layer-ortho")).to_be_checked()
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"^https://ortos\."))
        # Back to *Mapa*.
        page.get_by_test_id("fm-layer-map").check()
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile(r"^https://tile\.openstreetmap"))
        self.assertEqual(page.evaluate("localStorage.getItem('atalaia.fieldmap.layer')"), "map")
        self.assertEqual((seen["other"], seen["overpass"], seen["wms"]), ([], [], []))

    # --- open orthophotos outside Portugal (MF-65 to MF-72) ---

    SOURCES_JS = ("(pts) => import('./components/ortho-sources.js').then((m) => pts.map((p) => (p.length > 2"
                  " ? m.sourcesFor(p) : m.sourcesAt(p[0])).map((s) => s.id)))")

    @staticmethod
    def outline_at(lat: float, lon: float, scale: float = 1.0) -> list:
        """OUTLINE moved to (lat, lon) (its first corner's neighbourhood), optionally scaled."""
        return [(round(lat + (a - 39.6) * scale, 6), round(lon + (b + 8.4) * scale, 6)) for a, b in OUTLINE]

    def trace(self, page, corners: list) -> None:
        for lat, lon in corners:
            page.get_by_test_id("fm-corner").fill(f"{lat}, {lon}")
            page.get_by_test_id("fm-corner-add").click()

    def check_tiles(self, page, seen: dict, prefix: str, name: str, credit: str) -> None:
        """The *Ortofoto* layer in a country: its name on the switch, its tiles, its credit in the corner."""
        expect(page.get_by_test_id("fm-layers")).to_contain_text(name)
        page.get_by_test_id("fm-layer-ortho").check()
        expect(page.locator(".tm-tile").first).to_have_attribute("src", re.compile("^" + re.escape(prefix)))
        expect(page.get_by_test_id("tm-credit")).to_have_text(credit)
        page.wait_for_function("[...document.querySelectorAll('.tm-tile')].every((i) => i.complete)")
        tiles = page.locator(".tm-tile").evaluate_all("(l) => l.map((i) => i.src)")
        self.assertTrue(all(t.startswith(prefix) for t in tiles), tiles)
        # Only the tiles in view, each asked once.
        asked = [u for u in seen["wms_tiles"] if u.startswith(prefix)]
        self.assertEqual(sorted(asked), sorted(tiles))

    def test_field_map_orthophoto_chosen_by_country(self):
        """MF-66, MF-67: the orthophoto is the one of the country the point is in (the map's centre), or of
        the outline's centroid; by a border, both, the centroid's country first; none outside every
        coverage (the sea, the Azores, Madeira, the UK, Austria, Italy, Denmark, Andorra, and the German Länder
        left out by MF-80). MF-73 to MF-78: Belgium by region (Brussels before Flemish Brabant around it),
        Germany by Land (Berlin before Brandenburg around it), Switzerland with Liechtenstein, France's overseas
        departments and collectivities."""
        page, _ = self.field_map()
        points = {
            "dgt": [(38.7223, -9.1393), (38.881, -7.163), (37.0194, -7.9304)],
            "ign-es": [(38.878, -6.970), (40.4168, -3.7038), (39.5696, 2.6502), (28.1235, -15.4363)],
            "ign-fr": [(48.8566, 2.3522), (41.9192, 8.7386), (49.1193, 6.1757), (16.2411, -61.5331),
                       (14.6161, -61.0588), (4.9224, -52.3135), (-20.8823, 55.4504), (-12.7806, 45.2279),
                       (46.7811, -56.1764), (18.0708, -63.0501), (17.8962, -62.8498)],
            "pdok": [(52.3676, 4.9041), (53.0548, 4.7977), (50.8514, 5.6910)],
            "ngi": [(50.8467, 4.3525), (50.8503, 4.3517)],
            "vlaanderen": [(51.05, 3.72), (51.2194, 4.4025), (50.9307, 5.3378)],
            "spw": [(50.4669, 4.8675), (50.6326, 5.5797), (50.4542, 3.9567)],
            "act": [(49.6116, 6.1319), (49.9, 6.0)],
            "swisstopo": [(46.948, 7.447), (46.2044, 6.1432), (47.3769, 8.5417), (46.0037, 8.9511), (47.141, 9.521)],
            "de-be": [(52.52, 13.405), (52.477, 13.411)],
            "de-bb": [(52.3906, 13.0645), (52.607, 12.861)],
            "de-by": [(48.1351, 11.582), (49.4521, 11.0767)],
            "de-hb": [(53.0793, 8.8017), (53.5396, 8.5809)],
            "de-he": [(50.1109, 8.6821), (51.3127, 9.4797)],
            "de-mv": [(54.0924, 12.0991), (53.792, 12.17)],
            "de-nw": [(50.9375, 6.9603), (51.572, 8.111)],
            "de-rp": [(50.3569, 7.589), (49.752, 8.112)],
            "de-sl": [(49.35, 7.18), (49.472, 7.172)],
            "de-sn": [(51.0504, 13.7373), (51.3397, 12.3731)],
            "de-th": [(50.9848, 11.0299), (50.955, 11.105)],
            "gugik": [(52.2297, 21.0122), (50.0647, 19.945), (54.352, 18.6466)],
            "cuzk": [(50.0875, 14.4213), (49.1951, 16.6068)],
            "": [(51.5072, -0.1276), (37.7412, -25.6756), (32.65, -16.9083), (39.5, -11.5), (48.2082, 16.3738),
                 (47.2692, 11.4041), (41.9028, 12.4964), (55.6761, 12.5683), (42.5063, 1.5218), (48.7758, 9.1829),
                 (52.3759, 9.732), (53.5511, 9.9937), (52.1205, 11.6276), (54.3233, 10.1228)],
        }
        for want, pts in points.items():
            got = page.evaluate(self.SOURCES_JS, [[{"lat": a, "lon": b}] for a, b in pts])
            self.assertEqual([g[:1] for g in got], [[want] if want else []] * len(pts), want)
        # Two outlines across the border between Elvas and Badajoz: each has corners in both countries, and the
        # centroid decides; the other country comes second (asked when the first has no picture there).
        west = [{"lat": a, "lon": b} for a, b in ((38.885, -7.095), (38.885, -7.055), (38.875, -7.055),
                                                   (38.875, -7.095))]
        east = [{"lat": a, "lon": b} for a, b in ((38.885, -7.065), (38.885, -7.025), (38.875, -7.025),
                                                   (38.875, -7.065))]
        self.assertEqual(page.evaluate(self.SOURCES_JS, [west, east]), [["dgt", "ign-es"], ["ign-es", "dgt"]])

    def test_field_map_in_spain(self):
        """MF-68: in Spain the layer is IGN España's PNOA (its WMTS, Web Mercator tiles) with its credit, and
        the drawn image is over PNOA (one WMS GetMap in EPSG:4326 at the image's size) with IGN's wording for
        a derived work burned in."""
        page, seen = self.field_map()
        page.get_by_test_id("fm-go").fill("40.4168, -3.7038")
        page.get_by_test_id("fm-go-button").click()
        expect(page.get_by_test_id("fm-layer-map")).to_be_checked()
        expect(page.get_by_text("Ortofoto (IGN España)", exact=True)).to_be_visible()
        self.check_tiles(page, seen, "https://www.ign.es/wmts/pnoa-ma?", "Ortofoto (IGN España)",
                         "PNOA CC-BY 4.0 scne.es")
        q = {k: v[0] for k, v in parse_qs(urlsplit(seen["wms_tiles"][0]).query, keep_blank_values=True).items()}
        self.assertEqual({k: v for k, v in q.items() if k not in ("TILEROW", "TILECOL")}, {
            "SERVICE": "WMTS", "REQUEST": "GetTile", "VERSION": "1.0.0", "LAYER": "OI.OrthoimageCoverage",
            "STYLE": "default", "TILEMATRIXSET": "GoogleMapsCompatible", "TILEMATRIX": "17", "FORMAT": "image/jpeg"})
        self.trace(page, self.outline_at(40.4168, -3.7038))
        expect(page.get_by_test_id("fm-ortho")).to_be_checked()
        expect(page.locator("label.fm-ortho")).to_have_text("Ortofoto (IGN España) como base")
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        self.assertEqual(len(seen["wms"]), 1)
        self.assertTrue(seen["wms"][0].startswith("https://www.ign.es/wms-inspire/pnoa-ma?"), seen["wms"])
        q = {k: v[0] for k, v in parse_qs(urlsplit(seen["wms"][0]).query, keep_blank_values=True).items()}
        self.assertEqual((q["LAYERS"], q["CRS"], q["REQUEST"], q["FORMAT"]),
                         ("OI.OrthoimageCoverage", "EPSG:4326", "GetMap", "image/jpeg"))
        size = page.get_by_test_id("fm-image").evaluate("(i) => [i.naturalWidth, i.naturalHeight]")
        self.assertEqual(size, [int(q["WIDTH"]), int(q["HEIGHT"])])
        expect(page.get_by_test_id("fm-size")).to_contain_text("A ortofoto (IGN España) com os caminhos")
        expect(page.get_by_test_id("fm-image-credit")).to_have_text(
            "Créditos na imagem: Obra derivada de PNOA CC-BY 4.0 scne.es · © OpenStreetMap contributors")
        self.assertEqual(seen["other"], [])

    def test_field_map_in_france_and_the_netherlands(self):
        """MF-69, MF-70, in English: IGN France's orthophotos (Géoplateforme WMTS tiles, its WMS-R for the
        image) and PDOK's (WMTS tiles; its WMS draws at most 2500 pixels on a side, so a large area's picture
        is asked smaller, in proportion, and stretched to the image), each with its credit."""
        page, seen = self.field_map(lang="en")
        page.get_by_test_id("fm-go").fill("48.8566, 2.3522")
        page.get_by_test_id("fm-go-button").click()
        self.check_tiles(page, seen, "https://data.geopf.fr/wmts?", "Orthophoto (IGN France)",
                         "Orthophotos © IGN (Licence Ouverte 2.0)")
        q = {k: v[0] for k, v in parse_qs(urlsplit(seen["wms_tiles"][0]).query).items()}
        self.assertEqual((q["LAYER"], q["TILEMATRIXSET"], q["STYLE"], q["TILEMATRIX"]),
                         ("ORTHOIMAGERY.ORTHOPHOTOS", "PM_0_19", "normal", "17"))
        self.trace(page, self.outline_at(48.8566, 2.3522))
        expect(page.locator("label.fm-ortho")).to_have_text("Orthophoto (IGN France) as the base")
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        self.assertEqual(len(seen["wms"]), 1)
        self.assertTrue(seen["wms"][0].startswith("https://data.geopf.fr/wms-r?"), seen["wms"])
        self.assertIn("LAYERS=ORTHOIMAGERY.ORTHOPHOTOS", seen["wms"][0])
        expect(page.get_by_test_id("fm-image-credit")).to_have_text(
            "Credits on the image: Orthophotos © IGN (Licence Ouverte 2.0) · © OpenStreetMap contributors")
        # The Netherlands, a field about 3 km across: the image is 4096 pixels wide, PDOK's picture 2500.
        page.get_by_test_id("fm-clear").click()
        page.get_by_test_id("fm-go").fill("52.3676, 4.9041")
        page.get_by_test_id("fm-go-button").click()
        self.check_tiles(page, seen, "https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_ortho25/EPSG:3857/17/",
                         "Orthophoto (PDOK)", "Luchtfoto © Beeldmateriaal.nl / PDOK (CC BY 4.0)")
        self.trace(page, [(52.36, 4.88), (52.36, 4.92), (52.385, 4.92), (52.385, 4.88)])
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        self.assertEqual(len(seen["wms"]), 2)
        self.assertTrue(seen["wms"][1].startswith("https://service.pdok.nl/hwh/luchtfotorgb/wms/v1_0?"), seen["wms"])
        q = {k: v[0] for k, v in parse_qs(urlsplit(seen["wms"][1]).query).items()}
        self.assertEqual((q["LAYERS"], q["CRS"]), ("Actueel_ortho25", "EPSG:4326"))
        w, h = int(q["WIDTH"]), int(q["HEIGHT"])
        size = page.get_by_test_id("fm-image").evaluate("(i) => [i.naturalWidth, i.naturalHeight]")
        self.assertEqual(max(w, h), 2500)
        self.assertGreater(max(size), 2500)
        self.assertAlmostEqual(w / h, size[0] / size[1], delta=0.01)
        expect(page.get_by_test_id("fm-size")).to_contain_text("The orthophoto (PDOK) with OpenStreetMap's")
        expect(page.get_by_test_id("fm-image-credit")).to_have_text(
            "Credits on the image: Luchtfoto © Beeldmateriaal.nl / PDOK (CC BY 4.0) · © OpenStreetMap contributors")
        self.assertEqual(seen["other"], [])

    # MF-73 to MF-78: each new source, at a point inside it: its name, its tiles at zoom 17 (WMTS, or its WMS per
    # tile), the map's credit, its WMS for the drawn image and the image's credit.
    YEAR = time.localtime().tm_year
    NEW_SOURCES = (
        ("ign-fr", (-20.8823, 55.4504), "IGN France", "https://data.geopf.fr/wmts?",
         "Orthophotos © IGN (Licence Ouverte 2.0)", "Orthophotos © IGN (Licence Ouverte 2.0)",
         "https://data.geopf.fr/wms-r?"),
        ("ngi", (50.8467, 4.3525), "NGI-IGN", "https://wms.ngi.be/inspire/ortho/service?",
         "© NGI-IGN 2023, CC BY 4.0", "© NGI-IGN 2023, CC BY 4.0", "https://wms.ngi.be/inspire/ortho/service?"),
        ("vlaanderen", (51.05, 3.72), "Digitaal Vlaanderen", "https://geo.api.vlaanderen.be/OMWRGBMRVL/wmts?",
         "Bron: Luchtopnamen Digitaal Vlaanderen", "Bron: Luchtopnamen Digitaal Vlaanderen",
         "https://geo.api.vlaanderen.be/omwrgbmrvl/wms?"),
        ("spw", (50.4669, 4.8675), "SPW Wallonie",
         "https://geoservices.wallonie.be/arcgis/services/IMAGERIE/ORTHO_LAST/MapServer/WMSServer?",
         "Source : Service public de Wallonie (SPW) – Orthophotos (CC BY 4.0)",
         "Source : Service public de Wallonie (SPW) – Orthophotos (CC BY 4.0)",
         "https://geoservices.wallonie.be/arcgis/services/IMAGERIE/ORTHO_LAST/MapServer/WMSServer?"),
        ("act", (49.6116, 6.1319), "geoportail.lu",
         "https://wmts1.geoportail.lu/opendata/wmts/ortho_latest/GLOBAL_WEBMERCATOR_4_V3/17/",
         "Orthophoto © ACT Luxembourg (CC0)", "Orthophoto © ACT Luxembourg (CC0)",
         "https://wms.geoportail.lu/opendata/service?"),
        ("swisstopo", (47.141, 9.521), "swisstopo",
         "https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/17/",
         "© swisstopo", "© swisstopo", "https://wms.geo.admin.ch/?"),
        ("de-be", (52.477, 13.411), "Geoportal Berlin", "https://gdi.berlin.de/services/wms/truedop_2025_sommer?",
         "Geoportal Berlin / TrueDOP 2025 (dl-de/zero-2-0)", "Geoportal Berlin / TrueDOP 2025 (dl-de/zero-2-0)",
         "https://gdi.berlin.de/services/wms/truedop_2025_sommer?"),
        ("de-bb", (52.607, 12.861), "LGB Brandenburg", "https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms?",
         "© GeoBasis-DE/LGB, dl-de/by-2-0", "© GeoBasis-DE/LGB, dl-de/by-2-0 (Daten geändert)",
         "https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms?"),
        ("de-by", (48.1351, 11.582), "LDBV Bayern", "https://geoservices.bayern.de/od/wms/dop/v1/dop20?",
         "Bayerische Vermessungsverwaltung – www.geodaten.bayern.de (CC BY 4.0)",
         "Bayerische Vermessungsverwaltung – www.geodaten.bayern.de (CC BY 4.0, Daten geändert)",
         "https://geoservices.bayern.de/od/wms/dop/v1/dop20?"),
        ("de-hb", (53.5396, 8.5809), "GeoInformation Bremen", "https://geodienste.bremen.de/wms_dop_lb?",
         "© Landesamt GeoInformation Bremen (CC BY 4.0)", "© Landesamt GeoInformation Bremen (CC BY 4.0)",
         "https://geodienste.bremen.de/wms_dop_lb?"),
        ("de-he", (50.1109, 8.6821), "HVBG Hessen",
         "https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows?",
         "Geobasisdaten © Hessische Verwaltung für Bodenmanagement und Geoinformation",
         "Geobasisdaten © Hessische Verwaltung für Bodenmanagement und Geoinformation (Daten geändert)",
         "https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows?"),
        ("de-mv", (54.0924, 12.0991), "LAiV M-V", "https://www.geodaten-mv.de/dienste/adv_dop?",
         f"© GeoBasis-DE/M-V {YEAR} (CC BY 4.0)", f"© GeoBasis-DE/M-V {YEAR} (CC BY 4.0)",
         "https://www.geodaten-mv.de/dienste/adv_dop?"),
        ("de-nw", (50.9375, 6.9603), "Geobasis NRW",
         "https://www.wmts.nrw.de/geobasis/wmts_nw_dop/tiles/nw_dop/EPSG_3857_16/12/",
         "Luftbild: Geobasis NRW (dl-de/zero-2-0)", "Luftbild: Geobasis NRW (dl-de/zero-2-0)",
         "https://www.wms.nrw.de/geobasis/wms_nw_dop?"),
        ("de-rp", (50.3569, 7.589), "LVermGeo RLP", "https://geo4.service24.rlp.de/wms/rp_dop20.fcgi?",
         f"©GeoBasis-DE / LVermGeoRP ({YEAR}), dl-de/by-2-0, www.lvermgeo.rlp.de",
         f"©GeoBasis-DE / LVermGeoRP ({YEAR}), dl-de/by-2-0, www.lvermgeo.rlp.de [Daten bearbeitet]",
         "https://geo4.service24.rlp.de/wms/rp_dop20.fcgi?"),
        ("de-sl", (49.35, 7.18), "LVGL Saarland", "https://geoportal.saarland.de/freewms/dop2025?",
         "© GeoBasis DE/LVGL-SL 2025, dl-de/by-2-0", "© GeoBasis DE/LVGL-SL 2025, dl-de/by-2-0 (Daten geändert)",
         "https://geoportal.saarland.de/freewms/dop2025?"),
        ("de-sn", (51.0504, 13.7373), "GeoSN Sachsen", "https://geodienste.sachsen.de/wms_geosn_dop-rgb/guest?",
         "Quelle: GeoSN, dl-de/by-2-0", "Quelle: GeoSN, dl-de/by-2-0 (Daten geändert)",
         "https://geodienste.sachsen.de/wms_geosn_dop-rgb/guest?"),
        ("de-th", (50.9848, 11.0299), "GDI-Th", "https://www.geoproxy.geoportal-th.de/geoproxy/services/DOP?",
         "© GDI-Th (CC BY 4.0)", "© GDI-Th (CC BY 4.0)", "https://www.geoproxy.geoportal-th.de/geoproxy/services/DOP?"),
        ("gugik", (52.2297, 21.0122), "GUGiK",
         "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/StandardResolution?",
         "Ortofotomapa: GUGiK (geoportal.gov.pl)", "Ortofotomapa: GUGiK (geoportal.gov.pl)",
         "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution?"),
        ("cuzk", (50.0875, 14.4213), "ČÚZK", "https://ags.cuzk.gov.cz/arcgis1/rest/services/ORTOFOTO_WM/MapServer/tile/17/",
         f"Ortofoto: ČÚZK, {YEAR} (CC BY 4.0)", f"Ortofoto: ČÚZK, {YEAR} (CC BY 4.0)",
         "https://ags.cuzk.gov.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer?"),
    )

    def test_field_map_new_orthophotos(self):
        """MF-73 to MF-78, in English: in each new country, region or Land its own orthophoto is offered by name,
        its tiles come from its WMTS (or its WMS per tile) with its credit in the map's corner, and the drawn
        image is one GetMap of its WMS in EPSG:4326 with its credit burned in and said under the preview. The
        table's WMS, layers and size limits are the ones checked by hand (MF-73)."""
        page, seen = self.field_map(lang="en")
        table = page.evaluate("() => import('./components/ortho-sources.js').then((m) => m.ORTHO_SOURCES.map("
                              "(s) => [s.id, s.wms, s.layer, s.maxSide]))")
        self.assertEqual(table[4:], [
            ["ngi", "https://wms.ngi.be/inspire/ortho/service", "orthoimage_coverage", 4000],
            ["vlaanderen", "https://geo.api.vlaanderen.be/omwrgbmrvl/wms", "Ortho", 2048],
            ["spw", "https://geoservices.wallonie.be/arcgis/services/IMAGERIE/ORTHO_LAST/MapServer/WMSServer", "0",
             4096],
            ["act", "https://wms.geoportail.lu/opendata/service", "ortho_latest", 4096],
            ["swisstopo", "https://wms.geo.admin.ch/", "ch.swisstopo.swissimage", 2048],
            ["de-be", "https://gdi.berlin.de/services/wms/truedop_2025_sommer", "truedop_2025_sommer_rgb", 4096],
            ["de-bb", "https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms", "bebb_dop20c", 4096],
            ["de-by", "https://geoservices.bayern.de/od/wms/dop/v1/dop20", "by_dop20c", 4096],
            ["de-hb", "https://geodienste.bremen.de/wms_dop_lb", "dop10_2025_HB,dop10_2025_BHV", 4096],
            ["de-he", "https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows", "he_dop_rgb", 3000],
            ["de-mv", "https://www.geodaten-mv.de/dienste/adv_dop", "mv_dop", 4096],
            ["de-nw", "https://www.wms.nrw.de/geobasis/wms_nw_dop", "nw_dop_rgb", 4096],
            ["de-rp", "https://geo4.service24.rlp.de/wms/rp_dop20.fcgi", "rp_dop20", 4096],
            ["de-sl", "https://geoportal.saarland.de/freewms/dop2025", "sl_dop20_rgb", 4096],
            ["de-sn", "https://geodienste.sachsen.de/wms_geosn_dop-rgb/guest", "sn_dop_020", 4096],
            ["de-th", "https://www.geoproxy.geoportal-th.de/geoproxy/services/DOP", "th_dop", 4096],
            ["gugik", "https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution", "Raster", 4096],
            ["cuzk", "https://ags.cuzk.gov.cz/arcgis1/services/ORTOFOTO/MapServer/WMSServer", "0", 4096],
        ])
        for sid, (lat, lon), name, tiles, credit, image_credit, wms in self.NEW_SOURCES:
            with self.subTest(sid):
                page.get_by_test_id("fm-go").fill(f"{lat}, {lon}")
                page.get_by_test_id("fm-go-button").click()
                self.check_tiles(page, seen, tiles, f"Orthophoto ({name})", credit)
                self.trace(page, self.outline_at(lat, lon))
                expect(page.locator("label.fm-ortho")).to_have_text(f"Orthophoto ({name}) as the base")
                asked = len(seen["wms"])
                page.get_by_test_id("fm-draw").click()
                expect(page.get_by_test_id("fm-preview")).to_be_visible()
                self.assertEqual(len(seen["wms"]), asked + 1)
                self.assertTrue(seen["wms"][-1].startswith(wms), seen["wms"][-1])
                q = {k: v[0] for k, v in parse_qs(urlsplit(seen["wms"][-1]).query, keep_blank_values=True).items()}
                self.assertEqual((q["CRS"], q["REQUEST"], q["FORMAT"]), ("EPSG:4326", "GetMap", "image/jpeg"))
                expect(page.get_by_test_id("fm-image-credit")).to_have_text(
                    f"Credits on the image: {image_credit} · © OpenStreetMap contributors")
                page.get_by_test_id("fm-clear").click()
        # The WMTS whose levels are not the zooms: NRW's "00" is zoom 5, Poland's are "EPSG:3857:<zoom>", and
        # Flanders' are PNG; ČÚZK's (zooms 6 to 18) and NRW's (5 to 21) fall back to their WMS outside them.
        urls = page.evaluate("() => import('./components/ortho-sources.js').then((m) => Object.fromEntries("
                             "m.ORTHO_SOURCES.filter((s) => s.tile).map((s) => [s.id, [s.tile(17, 1, 2), "
                             "s.tile(4, 1, 2), s.tile(19, 1, 2)]])))")
        self.assertEqual(urls["de-nw"][0], "https://www.wmts.nrw.de/geobasis/wmts_nw_dop/tiles/nw_dop/EPSG_3857_16/12/1/2")
        self.assertTrue(urls["de-nw"][1].startswith("https://www.wms.nrw.de/geobasis/wms_nw_dop?"), urls["de-nw"])
        self.assertTrue(urls["cuzk"][2].startswith("https://ags.cuzk.gov.cz/arcgis1/services/ORTOFOTO/"), urls["cuzk"])
        self.assertIn("TILEMATRIX=EPSG%3A3857%3A17&TILEROW=2&TILECOL=1", urls["gugik"][0])
        self.assertIn("FORMAT=image%2Fpng", urls["vlaanderen"][0])
        self.assertEqual(seen["other"], [])

    def test_field_map_orthophoto_policy_matches_the_sources(self):
        """MF-79: the page's Content-Security-Policy names exactly the origins its sources use: every WMS as
        images and connections, a WMTS on an origin of its own as images only."""
        page, _ = self.field_map()
        csp = self.field.http.get("/console/field-map.html").headers["content-security-policy"]
        policy = dict(d.strip().split(" ", 1) for d in csp.split(";"))
        img = set(policy["img-src"].split()) - {"'self'", "blob:", "data:", "https://tile.openstreetmap.org"}
        connect = set(policy["connect-src"].split()) - {"'self'", "https://overpass-api.de",
                                                        "https://overpass.private.coffee",
                                                        "https://nominatim.openstreetmap.org"}
        got = page.evaluate("() => import('./components/ortho-sources.js').then((m) => [m.sourceOrigins(), "
                            "m.imageOrigins()])")
        self.assertEqual(set(got[0]), img)
        self.assertEqual(set(got[1]), connect)
        self.assertEqual(connect, set(ORTHO_WMS_ORIGINS))
        self.assertEqual(img - connect, set(ORTHO_TILE_ORIGINS))

    def test_field_map_orthophoto_at_a_border_and_outside(self):
        """MF-67: by the border between Elvas and Badajoz the centroid's country (Portugal) is asked first; a
        white picture (no photo there) asks the other country's once, and both white leave OpenStreetMap
        alone, said in words; so in Berlin (inside Brandenburg's outer ring, MF-76) Berlin's then Brandenburg's.
        Outside every coverage (Vienna) there is no orthophoto to tick and none is asked."""
        page, seen = self.field_map(wms="orthophoto-white.png")
        page.get_by_test_id("fm-go").fill("38.88, -7.075")
        page.get_by_test_id("fm-go-button").click()
        self.trace(page, [(38.885, -7.095), (38.885, -7.055), (38.875, -7.055), (38.875, -7.095)])
        expect(page.locator("label.fm-ortho")).to_have_text("Ortofoto (DGT) como base")
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        self.assertEqual([urlsplit(u).hostname for u in seen["wms"]], ["ortos.dgterritorio.gov.pt", "www.ign.es"])
        expect(page.get_by_test_id("fm-notice")).to_have_text(
            "A ortofoto (DGT) não tem imagem desta área: a imagem é desenhada só com o OpenStreetMap.")
        expect(page.get_by_test_id("fm-image-credit")).to_have_text("Créditos na imagem: © OpenStreetMap contributors")
        # Berlin: Berlin's TrueDOP first, then Brandenburg's (its mosaic takes in Berlin), both white here.
        page.get_by_test_id("fm-clear").click()
        page.get_by_test_id("fm-go").fill("52.52, 13.405")
        page.get_by_test_id("fm-go-button").click()
        self.trace(page, self.outline_at(52.52, 13.405))
        expect(page.locator("label.fm-ortho")).to_have_text("Ortofoto (Geoportal Berlin) como base")
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        self.assertEqual([urlsplit(u).hostname for u in seen["wms"][2:]], ["gdi.berlin.de", "isk.geobasis-bb.de"])
        expect(page.get_by_test_id("fm-notice")).to_have_text(
            "A ortofoto (Geoportal Berlin) não tem imagem desta área: a imagem é desenhada só com o OpenStreetMap.")
        # Vienna: no orthophoto, no switch, nothing asked.
        page.get_by_test_id("fm-clear").click()
        page.get_by_test_id("fm-go").fill("48.2082, 16.3738")
        page.get_by_test_id("fm-go-button").click()
        expect(page.get_by_test_id("fm-layers")).to_have_count(0)
        expect(page.get_by_test_id("fm-layer-none")).to_be_visible()
        self.trace(page, self.outline_at(48.2082, 16.3738))
        expect(page.get_by_test_id("fm-ortho")).to_have_count(0)
        page.get_by_test_id("fm-draw").click()
        expect(page.get_by_test_id("fm-preview")).to_be_visible()
        expect(page.get_by_test_id("fm-notice")).to_have_count(0)
        expect(page.get_by_test_id("fm-size")).to_contain_text("Desenhada a partir dos dados do OpenStreetMap.")
        self.assertEqual(len(seen["wms"]), 4)
        self.assertEqual(seen["wms_tiles"], [])
        self.assertEqual(seen["other"], [])

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
        cached = page.evaluate("caches.open('atalaia-console-v15').then((c) => c.keys())"
                               ".then((k) => k.map((r) => new URL(r.url).pathname))")
        for path in ("/console/app.js", "/console/lib/preact.module.js", "/console/i18n/en.json",
                     "/console/components/georef-panel.js", "/console/labels.js", "/console/qr-svg.js"):
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
        # Ticked from the controller's answer: a re-render before it (the page's clock, every second) shows the
        # stored value again, so Playwright's check() could find it unticked. Click, then wait for the tick.
        row.get_by_test_id("checkin-card-seen").click()
        expect(row.get_by_test_id("checkin-card-seen")).to_be_checked()
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

    def test_checkin_tab_imports_a_registration_list(self):
        """PKE-1 (decision F23): a CSV from another platform is checked (a dry run changes nothing), then imported
        as expected players, ticked by name at the desk; the same file again changes nothing, a bad file is
        refused with its reason in words."""
        game = self.field.create_game()
        csv_text = ("display_name,external_ref,team_preference,federation_number,replicas,email\r\n"
                    "Rita Falc\u00e3o,r-1,red,,aeg:rifle:Tokyo Marui M4,rita@example.pt\r\n"
                    "Z\u00e9 Coruja,r-2,verde,,,ze@example.pt\r\n")
        tmp = Path(tempfile.mkdtemp())
        good, bad = tmp / "inscricoes.csv", tmp / "mau.csv"
        good.write_text(csv_text, encoding="utf-8")
        bad.write_bytes(b"display_name\n\xe3\n")
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id("checkin-empty")).to_be_visible()
        page.get_by_test_id("import-open").click()
        expect(page.get_by_test_id("import-check")).to_be_disabled()
        page.get_by_test_id("import-file").set_input_files(str(bad))
        expect(page.get_by_test_id("import-error")).to_contain_text("UTF-8")
        page.get_by_test_id("import-file").set_input_files(str(good))
        page.get_by_test_id("import-source").fill("clube.exemplo")
        expect(page.get_by_test_id("import-run")).to_be_disabled()
        page.get_by_test_id("import-check").click()
        expect(page.get_by_test_id("import-result")).to_contain_text("Verificado, ainda nada importado")
        expect(page.get_by_test_id("import-result")).to_contain_text("1 nova")
        expect(page.get_by_test_id("import-result")).to_contain_text("1 recusada")
        expect(page.get_by_test_id("import-row-3")).to_contain_text("não é uma equipa deste jogo")
        expect(page.get_by_test_id("import-ignored")).to_contain_text("email")
        self.assertEqual(self.field.bundle.store.checkins(game["id"]), [])  # a dry run writes nothing
        expect(page.get_by_test_id("import-run")).to_be_disabled()  # the basis is not confirmed yet
        page.get_by_test_id("import-basis").check()
        page.get_by_test_id("import-run").click()
        row = page.get_by_test_id("checkin-table").locator("tr", has_text="Rita Falc\u00e3o")
        expect(row).to_contain_text("por chegar")
        expect(row.get_by_test_id("checkin-registered-badge")).to_be_visible()
        expect(row.get_by_test_id("checkin-replicas")).to_contain_text("1")
        self.assertEqual([r["display_name"] for r in self.field.bundle.store.checkins(game["id"])], ["Rita Falc\u00e3o"])
        row.get_by_test_id("checkin-arrived").click()  # ticked by name, as a registered player from a site
        expect(row).to_contain_text("com check-in")
        # The same file again: nothing is added twice, the arrived player is left alone.
        page.get_by_test_id("import-check").click()
        expect(page.get_by_test_id("import-result")).to_contain_text("1 ignorada")
        expect(page.get_by_test_id("import-row-2")).to_contain_text("já chegou")
        self.assertEqual(len(self.field.bundle.store.checkins(game["id"])), 1)
        # The read token never sees this tab's content.
        read = self.console(READ)
        read.get_by_test_id("tab-checkin").click()
        expect(read.locator("main.content")).not_to_contain_text("Rita")

    def test_checkin_tab_shows_the_apd_verdict_and_edits_the_rule(self):
        """APD membership (protocol/apd.md): the GM sets the rule in the settings (an own APD included), the table
        shows the declared APD, the expiry and a verdict, and a check-in the rule does not accept waits for a marshal."""
        game = self.field.create_game()
        self.field.http.put("/api/v1/checkin/settings", json={"country": "PT", "apd": {
            "checkin": True, "expiry": True, "accepted": ["x-clube"],
            "custom": [{"id": "x-clube", "name": "Clube Teste, APD", "short_name": "Clube", "website": None}]}})
        late = self.check_in(game["id"], "Atrasada", apd_id="x-clube", membership_number="12", membership_expires="2020-01-01")
        good = self.check_in(game["id"], "Pontual", apd_id="x-clube", membership_number="13", membership_expires="2099-01-01")
        self.assertEqual((late["status"], good["status"]), ("pending", "pending"))  # the card is not seen yet
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        row = page.get_by_test_id(f"checkin-row-{late['player_id']}")
        expect(row.get_by_test_id("checkin-apd-status")).to_have_text("caducada")
        expect(row.get_by_test_id("checkin-apd")).to_contain_text("Clube")
        expect(page.get_by_test_id(f"checkin-row-{good['player_id']}").get_by_test_id("checkin-apd-status")).to_have_text("válida")
        expect(row.get_by_test_id("checkin-confirm")).to_have_text("Admitir sem o cartão")
        row.get_by_test_id("checkin-confirm").click()
        expect(row.get_by_test_id("checkin-apd-override")).to_have_text("admitido sem o cartão")
        # "Card seen, matches": it lets the player in, shows who and when, erases the number, keeps the verdict.
        good_row = page.get_by_test_id(f"checkin-row-{good['player_id']}")
        expect(good_row.get_by_test_id("checkin-waits-card")).to_be_visible()
        good_row.get_by_test_id("checkin-card-seen").check()
        expect(good_row.get_by_test_id("checkin-card-by")).to_be_visible()
        expect(good_row.get_by_test_id("checkin-number-erased")).to_be_visible()
        expect(good_row.get_by_test_id("checkin-apd-status")).to_contain_text("válida em ")
        expect(good_row.get_by_test_id("checkin-card-seen")).to_be_disabled()
        stored = self.field.http.get(f"/api/v1/games/{game['id']}/checkins").json()["checkins"]
        mine = next(c for c in stored if c["player_id"] == good["player_id"])
        self.assertEqual((mine["status"], mine["federation_number"], mine["card_checked_by"], mine["apd_status"]),
                         ("checked_in", None, "gm", "valid"))
        # The rule's own entry is listed in the settings, ticked; add another and save.
        expect(page.get_by_test_id("checkin-apd-accept-x-clube")).to_be_checked()
        page.get_by_test_id("checkin-apd-custom").locator("summary").click()
        page.get_by_test_id("checkin-apd-name").fill("Outra Associação, APD")
        page.get_by_test_id("checkin-apd-short").fill("Outra")
        page.get_by_test_id("checkin-apd-add").click()
        expect(page.get_by_test_id("checkin-apd-accept-x-outra")).to_be_visible()
        expect(page.get_by_test_id("checkin-apd-accept-x-clube")).to_be_checked()  # what was ticked stays
        page.get_by_test_id("checkin-apd-accept-x-outra").check()
        page.locator("#cs-label").fill("N.º APD")
        # A player checks in before the GM saves: the stream draws the tab again, and nothing the GM ticked or
        # typed may be lost (both were, before the draft kept them).
        late2 = self.check_in(game["id"], "Tardia", apd_id="x-clube", membership_number="14", membership_expires="2099-01-01")
        expect(page.get_by_test_id(f"checkin-row-{late2['player_id']}")).to_be_visible()
        expect(page.get_by_test_id("checkin-apd-accept-x-outra")).to_be_checked()
        expect(page.get_by_test_id("checkin-apd-accept-x-clube")).to_be_checked()
        expect(page.locator("#cs-label")).to_have_value("N.º APD")
        page.get_by_test_id("checkin-settings-save").click()
        self.assertTrue(wait_for(lambda: self.field.http.get("/api/v1/checkin/settings").json()["apd"]["accepted"]
                                 == ["x-clube", "x-outra"], 10))
        self.assertEqual(self.field.http.get("/api/v1/checkin/settings").json()["federation_label"], "N.º APD")

    def test_checkin_poster_form_keeps_unsaved_edits_when_the_tab_is_drawn_again(self):
        """Audit CF-1 (the same loss as the check-in settings): the poster form drew its fields from the saved poster,
        so any new drawing of the tab (a player checking in) put the saved values back under the GM's typing."""
        game = self.field.create_game()
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id("poster-urls")).to_be_visible()
        page.get_by_test_id("poster-urls").fill("https://10.0.0.9:8443")
        page.locator("#cp-ssid").fill("CampoTeste")
        page.locator("input[name=pinned]").check()
        late = self.check_in(game["id"], "Chegada")
        expect(page.get_by_test_id(f"checkin-row-{late['player_id']}")).to_be_visible()
        page.wait_for_timeout(1500)   # and the console's own clock draws it again every second
        expect(page.get_by_test_id("poster-urls")).to_have_value("https://10.0.0.9:8443")
        expect(page.locator("#cp-ssid")).to_have_value("CampoTeste")
        expect(page.locator("input[name=pinned]")).to_be_checked()
        page.get_by_test_id("poster-save").click()
        self.assertTrue(wait_for(lambda: self.field.http.get("/api/v1/checkin/poster").json()["wifi_ssid"] == "CampoTeste", 10))
        saved = self.field.http.get("/api/v1/checkin/poster").json()
        self.assertEqual((saved["urls"], saved["game_id"]), (["https://10.0.0.9:8443"], game["id"]))

    def test_checkin_tab_says_association_membership_outside_portugal(self):
        """Decision MEM-2: the country is a setting of the field; PT keeps the APD texts, any other country (or none)
        says association membership and offers that country's list; the GM changes it in the settings."""
        game = self.field.create_game()
        self.field.http.put("/api/v1/checkin/settings", json={"country": "ES", "apd": {
            "checkin": True, "accepted": ["x-club"],
            "custom": [{"id": "x-club", "name": "Club de Prueba", "short_name": "Club", "website": None}]}})
        late = self.check_in(game["id"], "Atrasada", apd_id="x-club", membership_number="12")
        other = self.check_in(game["id"], "Outra", apd_id="apd-a", membership_number="13")
        self.assertEqual((late["status"], other["status"]), ("pending", "pending"))
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id("checkin-country")).to_have_value("ES")
        expect(page.get_by_test_id(f"checkin-row-{other['player_id']}").get_by_test_id("checkin-apd-status")) \
            .to_have_text("associação não aceite")
        expect(page.get_by_test_id("checkin-apd-settings").locator("legend")).to_have_text("Filiação numa associação")
        expect(page.get_by_test_id("checkin-apd-accept-ala")).to_have_count(0)  # Portugal's list is not Spain's
        expect(page.get_by_test_id("checkin-apd-accept-x-club")).to_be_checked()
        page.get_by_test_id("checkin-country").fill("pt")
        page.get_by_test_id("checkin-settings-save").click()
        self.assertTrue(wait_for(lambda: self.field.http.get("/api/v1/checkin/settings").json()["country"] == "PT", 5))
        expect(page.get_by_test_id("checkin-apd-settings").locator("legend")).to_have_text("Filiação numa APD")
        expect(page.get_by_test_id("checkin-apd-accept-ala")).to_be_visible()
        expect(page.get_by_test_id(f"checkin-row-{other['player_id']}").get_by_test_id("checkin-apd-status")) \
            .to_have_text("APD não aceite")

    def test_checkin_settings_set_how_long_chrono_and_game_data_are_kept(self):
        """Decisions RET-1 and RET-2: the field's chrono and game retention are settings of the check-in tab, chrono 365 and game data 90 days
        by default, saved with the others; the page labels them in the console's language."""
        self.field.create_game()
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id("checkin-game-retention")).to_have_value("90")
        expect(page.get_by_test_id("checkin-chrono-retention")).to_have_value("365")
        expect(page.locator("label[for=cs-game-days]")).to_have_text("Dados dos jogos guardados (dias)")
        page.get_by_test_id("checkin-game-retention").fill("120")
        page.get_by_test_id("checkin-chrono-retention").fill("180")
        page.get_by_test_id("checkin-settings-save").click()
        self.assertTrue(wait_for(lambda: self.field.http.get("/api/v1/checkin/settings").json()["game_retention_days"] == 120, 5))
        self.assertEqual(self.field.http.get("/api/v1/checkin/settings").json()["chrono_retention_days"], 180)

    def test_marshal_list_in_the_checkin_tab(self):
        """Decisions MR-1 to MR-14: the GM adds a checked-in player to the marshal list (the controller gives the
        id and the role), sees when the player's app has registered its key, renames and removes."""
        game = self.field.create_game()
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id("marshals")).to_be_visible()
        expect(page.get_by_test_id("marshals-empty")).to_be_visible()
        expect(page.get_by_test_id("marshal-add")).to_be_disabled()
        me = self.check_in(game["id"], "Coruja")
        other = self.check_in(game["id"], "Gaivota")
        add = page.get_by_test_id("marshal-add-player")
        expect(add.locator("option")).to_have_count(3)  # none, and the two who checked in
        add.select_option(label="Coruja")
        page.get_by_test_id("marshal-add").click()
        row = page.get_by_test_id("marshal-row-M-01")
        expect(row).to_be_visible()
        expect(row.get_by_test_id("marshal-id")).to_have_text("M-01")
        expect(row.get_by_test_id("marshal-name")).to_have_value("Coruja")  # the player's own name
        expect(row.get_by_test_id("marshal-key")).to_have_text("à espera da app")
        entry = self.field.bundle.store.roster_entry("M-01")
        self.assertEqual((entry["player_id"], entry["name"]), (me["player_id"], "Coruja"))
        # The role follows the list, in the check-in table, live.
        expect(page.get_by_test_id(f"checkin-row-{me['player_id']}").get_by_test_id("checkin-role")).to_have_value("marshal")
        # The one added is no longer offered as a new marshal.
        expect(page.get_by_test_id("marshal-add-player").locator("option")).to_have_count(2)
        # The player's app learns its id and registers its key; the list shows it without a reload.
        old = {"Authorization": f"Bearer {me['token']}"}
        mine = httpx.get(self.field.base + "/api/v1/checkin/me", headers=old, timeout=10).json()
        self.assertTrue(mine["stale_token"])  # made before the role: the app asks for a new one, as it does
        self.assertEqual(mine["marshal"]["marshal_id"], "M-01")
        fresh = httpx.post(self.field.base + "/api/v1/checkin/token", headers=old, timeout=10).json()["token"]
        r = httpx.put(self.field.base + "/api/v1/checkin/me/marshal-key", headers={"Authorization": f"Bearer {fresh}"},
                      json={"public_key": "A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg="}, timeout=10)
        self.assertEqual(r.status_code, 200, r.text)
        expect(row.get_by_test_id("marshal-key")).to_have_text("registada", timeout=15000)
        # A name only, no player yet (a marshal whose phone comes later), then tied to one.
        page.get_by_test_id("marshal-add-name").fill("Posto da entrada")
        page.get_by_test_id("marshal-add").click()
        row2 = page.get_by_test_id("marshal-row-M-02")
        expect(row2).to_be_visible()
        expect(row2.get_by_test_id("marshal-player")).to_have_value("")
        row2.get_by_test_id("marshal-player").select_option(label="Gaivota")
        self.assertTrue(wait_for(lambda: self.field.bundle.store.roster_entry("M-02")["player_id"] == other["player_id"], 5))
        # The list has been drawn again from the controller's answer (it would put back a name typed before).
        expect(row2.get_by_test_id("marshal-player")).to_have_value(other["player_id"])
        row2.get_by_test_id("marshal-name").fill("Gaivota (entrada)")
        # A slow GM: the list's refresh (every 5 s) comes while the name is being typed, and must not put
        # the old name back under the cursor.
        page.wait_for_timeout(6000)
        expect(row2.get_by_test_id("marshal-name")).to_have_value("Gaivota (entrada)")
        row2.get_by_test_id("marshal-name").press("Tab")
        self.assertTrue(wait_for(lambda: self.field.bundle.store.roster_entry("M-02")["name"] == "Gaivota (entrada)", 5))
        # Removing asks first, and revokes at once: the key stops, the role goes.
        page.once("dialog", lambda d: d.accept())
        row.get_by_test_id("marshal-remove").click()
        expect(page.get_by_test_id("marshal-row-M-01")).to_have_count(0)
        self.assertIsNone(self.field.bundle.store.roster_entry("M-01"))
        self.assertIsNone(self.field.bundle.store.marshal("M-01"))
        self.assertTrue(wait_for(lambda: self.field.bundle.store.checkin(game["id"], me["player_id"])["role"] == "player", 5))
        expect(page.get_by_test_id(f"checkin-row-{me['player_id']}").get_by_test_id("checkin-role")).to_have_value("player")
        # The read token has no list.
        read = self.console(READ)
        read.get_by_test_id("tab-checkin").click()
        expect(read.get_by_test_id("marshals")).to_have_count(0)

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

    def test_console_tabs_with_rows_fit_a_375_px_phone(self):
        """The check-in table (squads, federation numbers, replicas, a long name) and the marshal list stack
        into cards on a phone instead of scrolling the page sideways; every other tab with data fits too."""
        game = self.field.create_game("Sábado", squads=2)
        self.field.http.put("/api/v1/checkin/settings", json={"confirm": "staff", "federation": "optional"})
        replicas = [{"declaration_id": "6f1d2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b", "type": "aeg", "class": "rifle"},
                    {"declaration_id": "0a1b2c3d-4e5f-4a6b-9c7d-8e9f0a1b2c3d", "type": "bolt_action",
                     "class": "sniper", "make_model": "Well MB4402"}]
        me = self.check_in(game["id"], "Coruja Comprida Do Monte Alto", federation_number="FPA-77",
                           replicas=replicas)
        self.check_in(game["id"], "Gaivota")
        self.field.box_hello()
        page = self.console(width=375, height=800)
        page.get_by_test_id("tab-checkin").click()
        row = page.get_by_test_id(f"checkin-row-{me['player_id']}")
        expect(row).to_be_visible()
        def mine():
            body = self.field.http.get(f"/api/v1/games/{game['id']}/checkins").json()
            return next(r for r in body["checkins"] if r["player_id"] == me["player_id"])

        row.get_by_test_id("checkin-confirm").click()
        # The row is drawn again when the confirm comes back on the stream: change the team only after that,
        # or the select can be replaced under the change and the change never sent.
        self.assertTrue(wait_for(lambda: mine()["status"] == "checked_in", 5))
        expect(row.get_by_test_id("checkin-confirm")).to_have_count(0)
        row.get_by_test_id("checkin-team").select_option("blue")
        self.assertTrue(wait_for(lambda: mine().get("team") == "blue", 5))
        expect(row.get_by_test_id("checkin-squad")).to_be_visible()
        page.get_by_test_id("marshal-add-player").select_option(label="Gaivota")
        page.get_by_test_id("marshal-add").click()
        expect(page.get_by_test_id("marshal-row-M-01")).to_be_visible()
        self.no_horizontal_scroll(page)
        # Stacked: the table itself does not scroll, and the controls stay reachable by keyboard in order.
        for testid in ("checkin-table", "marshals-table"):
            box = page.get_by_test_id(testid).bounding_box()
            self.assertLessEqual(box["x"] + box["width"], 375.5, testid)
        self.assertEqual(page.get_by_test_id("checkin-table").get_attribute("role"), "table")
        self.assertEqual(page.get_by_test_id("checkin-table").locator("[role=columnheader]").count(), 7)
        for tab in page.locator("nav.tabs button").all():
            tab.click()
            self.no_horizontal_scroll(page)

    def test_who_of_a_squad_is_told_its_scenario_objectives(self):
        """SQ-3, SQ-4: a scenario with squads offers who of a squad gets its objectives (every member,
        or the squad leader only) when the game is made, and changes it for the live game; a game
        of another mode or without squads offers nothing."""
        text = (HERE.parents[1] / "tests" / "scenarios" / "squad_chains.yaml").read_text(encoding="utf-8")
        self.assertEqual(self.field.http.post("/api/v1/scenarios", json={"manifest": text}).status_code, 201)
        page = self.console()
        page.get_by_test_id("game-name").fill("Cadeias")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        page.get_by_test_id("game-squads").fill("2")
        expect(page.get_by_test_id("game-disclosure")).to_have_count(0)  # not a scenario
        page.get_by_test_id("game-source").select_option("mode:org.club.squad-chains")
        page.get_by_test_id("game-roles").locator('input[value="org.atalaia.objectives"]').check()
        page.get_by_test_id("game-squads").fill("0")
        expect(page.get_by_test_id("game-disclosure")).to_have_count(0)  # no squads
        page.get_by_test_id("game-squads").fill("2")
        select = page.get_by_test_id("game-disclosure")
        expect(select).to_be_visible()
        expect(select).to_have_value("")
        select.select_option("members")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        self.assertEqual(game["mode_id"], "org.club.squad-chains+org.atalaia.objectives")
        seen = self.field.http.get(f"/api/v1/games/{game['id']}").json()["scenario"]
        self.assertEqual((seen["disclosure"], seen["disclosure_default"], seen["reveal"]),
                         ("members", "leader", "active"))
        # The live game's own selector shows the choice and changes it.
        live = page.get_by_test_id("game-disclosure-select")
        expect(live).to_have_value("members")
        live.select_option("")
        self.assertTrue(wait_for(lambda: self.field.http.get(f"/api/v1/games/{game['id']}").json()
                                 ["scenario"]["disclosure"] == "leader", 5))
        expect(live).to_have_value("")
        expect(page.get_by_test_id("game-disclosure-live")).to_contain_text("Só o líder de squad")
        live.select_option("members")
        self.assertTrue(wait_for(lambda: self.field.http.get(f"/api/v1/games/{game['id']}").json()
                                 ["scenario"]["disclosure"] == "members", 5))

    def test_the_gm_chooses_whether_objectives_start_visible_or_hidden(self):
        """RVL-1: a scenario game offers when the objectives that say nothing about it become known;
        left alone a game with squads has only the active ones, the GM's choice is kept for the game
        and shown on its panel; another mode offers nothing."""
        text = (HERE.parents[1] / "tests" / "scenarios" / "squad_chains.yaml").read_text(encoding="utf-8")
        text = text.replace("id: org.club.squad-chains", "id: org.club.silent-chains").replace("reveal: active\n", "")
        self.assertNotIn("\nreveal:", text)
        self.assertEqual(self.field.http.post("/api/v1/scenarios", json={"manifest": text}).status_code, 201)
        page = self.console()
        page.get_by_test_id("game-name").fill("Silencioso")
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        expect(page.get_by_test_id("game-reveal")).to_have_count(0)  # not a scenario
        page.get_by_test_id("game-source").select_option("mode:org.club.silent-chains")
        page.get_by_test_id("game-roles").locator('input[value="org.atalaia.objectives"]').check()
        select = page.get_by_test_id("game-reveal")
        expect(select).to_be_visible()
        expect(select).to_have_value("")
        select.select_option("all")
        page.get_by_test_id("game-squads").fill("2")
        page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")
        game = self.field.bundle.controller.game
        seen = self.field.http.get(f"/api/v1/games/{game['id']}").json()["scenario"]
        self.assertEqual((seen["reveal"], seen["reveal_default"]), ("all", None))
        expect(page.get_by_test_id("game-reveal-live")).to_contain_text("todos visíveis desde o início")

    # --- the check-in poster suggestion after a game is created (check-R10 to check-R17) ---------------------

    def create_game_in_console(self, page, name: str = "Domingo", enter: bool = False) -> None:
        page.get_by_test_id("game-name").fill(name)
        page.get_by_test_id("game-source").select_option(f"mode:{DOMINATION}")
        if enter:
            page.get_by_test_id("game-name").press("Enter")  # the GM never left the field
        else:
            page.get_by_test_id("game-create").click()
        expect(page.get_by_test_id("game-state")).to_have_text("pronto")

    def end_game(self, page) -> None:
        self.field.http.post(f"/api/v1/games/{self.field.bundle.controller.game['id']}/end", json={})
        expect(page.get_by_test_id("game-create")).to_be_visible()
        self.drop_errors("409")  # the page asked for the ended game's positions and chrono list

    def test_poster_prompt_after_creating_a_game_counts_down_and_closes_itself(self):
        page = self.console(poster_prompt=True)
        t0 = time.monotonic()
        self.create_game_in_console(page, "Domingo de manhã")
        dialog = page.get_by_test_id("poster-prompt")
        expect(dialog).to_be_visible()
        expect(dialog).to_have_attribute("role", "dialog")
        expect(dialog).to_have_attribute("aria-modal", "true")
        expect(page.get_by_test_id("poster-prompt-body")).to_contain_text("Domingo de manhã")
        expect(page.get_by_test_id("poster-prompt-countdown")).to_contain_text("Fecha em")
        # The countdown is in sight, and a polite live region says it to a screen reader.
        expect(page.get_by_test_id("poster-prompt-countdown")).to_have_attribute("aria-hidden", "true")
        expect(page.get_by_test_id("poster-prompt-live")).to_have_attribute("aria-live", "polite")
        expect(page.get_by_test_id("poster-prompt-live")).to_contain_text("10 segundos")
        # Focus moved into it (onto the box, not onto a button).
        self.assertEqual(page.evaluate("document.activeElement.getAttribute('data-testid')"), "poster-prompt")
        expect(page.get_by_test_id("poster-prompt-countdown")).not_to_contain_text("10 s", timeout=4000)
        expect(page.get_by_test_id("poster-prompt-live")).to_contain_text("5 segundos", timeout=8000)
        # ... and it closes itself after ten seconds, the focus going back to the page's content.
        expect(dialog).to_be_hidden(timeout=12000)
        took = time.monotonic() - t0
        self.assertTrue(9.0 <= took <= 13.5, f"closed after {took:.1f} s")
        self.assertEqual(page.evaluate("document.activeElement.className"), "content")
        self.assertIsNone(page.evaluate("localStorage.getItem('atalaia.posterPrompt')"))  # nothing was chosen

    def test_poster_prompt_closes_early_with_the_button_and_with_esc(self):
        page = self.console(poster_prompt=True)
        self.create_game_in_console(page)
        dialog = page.get_by_test_id("poster-prompt")
        expect(dialog).to_be_visible()
        page.get_by_test_id("poster-prompt-close").click()
        expect(dialog).to_be_hidden(timeout=1500)
        self.assertEqual(page.evaluate("document.activeElement.className"), "content")
        # Another game: Esc closes it, from the keyboard alone (Tab stays inside while it is open).
        self.end_game(page)
        self.create_game_in_console(page, "Segundo")
        expect(dialog).to_be_visible()
        expect(page.get_by_test_id("poster-prompt-body")).to_contain_text("Segundo")
        for _ in range(5):
            page.keyboard.press("Tab")
            inside = page.evaluate("document.querySelector('[data-testid=poster-prompt]').contains(document.activeElement)")
            self.assertTrue(inside, "Tab left the dialog")
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden(timeout=1500)
        self.assertEqual(page.evaluate("document.activeElement.className"), "content")
        self.assertEqual(self.field.http.get("/api/v1/checkin/poster").json()["game_id"], None)  # nothing was pinned

    def test_poster_prompt_opens_the_poster_page(self):
        page = self.console(poster_prompt=True)
        self.create_game_in_console(page)
        expect(page.get_by_test_id("poster-prompt")).to_be_visible()
        with page.expect_popup() as popup:
            page.get_by_test_id("poster-prompt-open").click()
        poster = popup.value
        poster.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.assertTrue(poster.url.endswith("/console/poster.html"), poster.url)
        expect(poster.get_by_test_id("poster-qr")).to_be_visible()
        expect(page.get_by_test_id("poster-prompt")).to_be_hidden(timeout=1500)

    def test_poster_prompt_not_for_a_read_token_nor_without_a_poster(self):
        game = self.field.create_game("Domingo")
        reader = self.console(READ, poster_prompt=True)
        expect(reader.get_by_test_id("header-game")).to_contain_text("Domingo")
        expect(reader.get_by_test_id("game-create")).to_have_count(0)  # a read token creates nothing
        self.field.http.post(f"/api/v1/games/{game['id']}/end", json={})
        self.field.create_game("Segundo")  # a game made elsewhere does not ask this console either
        expect(reader.get_by_test_id("header-game")).to_contain_text("Segundo")
        reader.wait_for_timeout(1500)
        expect(reader.get_by_test_id("poster-prompt")).to_have_count(0)
        # HTTPS off: there is no poster to print, so nothing to suggest.
        reader.context.close()
        self.field.close()
        self.drop_errors("409")
        self.field = Field(cfg={"tls_port": 0})
        page = self.console(poster_prompt=True)
        self.create_game_in_console(page)
        page.wait_for_timeout(1500)
        expect(page.get_by_test_id("poster-prompt")).to_have_count(0)

    def test_poster_prompt_leaves_focus_alone_while_the_gm_types(self):
        page = self.console(poster_prompt=True)
        self.create_game_in_console(page, enter=True)  # Enter in the name field: the GM is typing
        dialog = page.get_by_test_id("poster-prompt")
        expect(dialog).to_be_visible()
        expect(dialog).to_have_attribute("aria-modal", "false")
        expect(dialog).to_have_attribute("data-modal", "false")
        self.assertFalse(page.evaluate("document.querySelector('[data-testid=poster-prompt]').contains(document.activeElement)"))
        # No backdrop: the page stays usable, and a field typed into keeps what is typed.
        page.get_by_test_id("tab-feed").click()
        expect(page.get_by_test_id("tab-feed")).to_have_class("active")
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden(timeout=1500)

    def test_poster_prompt_dont_show_again_is_kept_in_this_browser(self):
        page = self.console(poster_prompt=True)
        self.create_game_in_console(page)
        page.get_by_test_id("poster-prompt-never").check()
        page.get_by_test_id("poster-prompt-close").click()
        expect(page.get_by_test_id("poster-prompt")).to_be_hidden(timeout=1500)
        self.assertEqual(page.evaluate("localStorage.getItem('atalaia.posterPrompt')"), "off")
        self.end_game(page)
        self.create_game_in_console(page, "Segundo")
        page.wait_for_timeout(1500)
        expect(page.get_by_test_id("poster-prompt")).to_have_count(0)
        # Settings brings it back.
        page.get_by_test_id("tab-settings").click()
        setting = page.get_by_test_id("poster-prompt-setting")
        expect(setting).not_to_be_checked()
        setting.check()
        self.assertIsNone(page.evaluate("localStorage.getItem('atalaia.posterPrompt')"))
        page.reload()
        expect(page.get_by_test_id("tab-game")).to_be_visible()
        self.end_game(page)
        self.create_game_in_console(page, "Terceiro")
        expect(page.get_by_test_id("poster-prompt")).to_be_visible()

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

    def test_labels_page_prints_a_qr_label_for_each_declared_replica(self):
        """The replica labels page: one 30 x 30 mm label per declared replica, for one player or for everyone
        checked in, whose QR reads back (zbarimg) as the text the marshal's app registers and scans, and holds
        nothing about the player."""
        if not ZBARIMG:
            self.skipTest("zbarimg is not installed")
        game = self.field.create_game()
        self.field.http.put("/api/v1/checkin/settings", json={"confirm": "staff"})
        d1, d2, d3 = ("6f1d2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b", "0a1b2c3d-4e5f-4a6b-9c7d-8e9f0a1b2c3d",
                      "9e8d7c6b-5a49-4382-a1b0-c9d8e7f6a5b4")
        me = self.check_in(game["id"], "Coruja", replicas=[
            {"declaration_id": d1, "type": "aeg", "class": "rifle"},
            {"declaration_id": d2, "type": "bolt_action", "class": "sniper", "make_model": "Well MB4402"}])
        other = self.check_in(game["id"], "Gaivota", replicas=[{"declaration_id": d3, "type": "gbb", "class": "cqb"}])
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        row = page.get_by_test_id(f"checkin-row-{me['player_id']}")
        row.get_by_test_id("checkin-confirm").click()
        expect(row).to_contain_text("com check-in")
        expect(page.get_by_test_id(f"checkin-row-{other['player_id']}").get_by_test_id("checkin-labels")).to_be_visible()
        expected = ["ATL-6F1D2A3B", "ATL-0A1B2C3D"]

        def read_labels(popup, count):
            popup.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
            expect(popup.get_by_test_id("label")).to_have_count(count)
            texts = []
            with tempfile.TemporaryDirectory() as tmp:
                for i in range(count):
                    shot = os.path.join(tmp, f"label{i}.png")
                    popup.get_by_test_id("label-qr").nth(i).screenshot(path=shot)
                    out = read_qr(shot)
                    self.assertEqual(out.returncode, 0, out.stderr)
                    texts.append(out.stdout)
            return texts

        # One player's labels.
        with page.expect_popup() as popup:
            row.get_by_test_id("checkin-labels").click()
        labels = popup.value
        self.assertEqual(read_labels(labels, 2), expected)
        expect(labels.get_by_test_id("label-code")).to_have_text(expected)
        expect(labels.get_by_test_id("labels-count")).to_have_text("2 etiquetas")
        for text in expected:
            # What the marshal's scanner accepts: printable ASCII of 1-64 characters that is no other Atalaia code,
            # and nothing about the player.
            self.assertRegex(text, r"^[\x21-\x7e]{1,64}$")
            self.assertFalse(text.startswith("atalaia:"))
            for private in (me["player_id"], "Coruja", "Well"):
                self.assertNotIn(private, text)
        self.assertEqual(self.field.http.get("/api/v1/games/%d/chrono-list" % game["id"]).status_code, 200)
        # 30 x 30 mm on paper (96 dpi: 113.4 px), the player's name and replica only on the screen.
        expect(labels.get_by_test_id("label").first).to_contain_text("Coruja")
        labels.emulate_media(media="print")
        expect(labels.get_by_test_id("labels-print")).to_be_hidden()
        box = labels.get_by_test_id("label").first.bounding_box()
        self.assertAlmostEqual(box["width"], 30 * 96 / 25.4, delta=2)
        self.assertAlmostEqual(box["height"], 30 * 96 / 25.4, delta=2)
        self.assertNotIn("Coruja", labels.get_by_test_id("label").first.inner_text())
        labels.emulate_media(media="screen")
        labels.set_viewport_size({"width": 390, "height": 844})
        self.no_horizontal_scroll(labels)

        # Everyone checked in: the player still waiting for confirmation has no labels yet.
        with page.expect_popup() as popup:
            page.get_by_test_id("checkin-labels-all").click()
        self.assertEqual(read_labels(popup.value, 2), expected)
        other_row = page.get_by_test_id(f"checkin-row-{other['player_id']}")
        other_row.get_by_test_id("checkin-confirm").click()
        expect(other_row).to_contain_text("com check-in")
        with page.expect_popup() as popup:
            page.get_by_test_id("checkin-labels-all").click()
        self.assertEqual(read_labels(popup.value, 3), expected + ["ATL-9E8D7C6B"])

        # The language of the console.
        page.get_by_test_id("lang").select_option("en")
        with page.expect_popup() as popup:
            row.get_by_test_id("checkin-labels").click()
        read_labels(popup.value, 2)
        expect(popup.value.get_by_test_id("labels-count")).to_have_text("2 labels")

    # --- the remote GM's log (decision S19-11) -------------------------------------------

    def add_remote_command(self, **entry) -> None:
        store = self.field.bundle.store
        store.add_remote_command({"received_at": time.time(), **entry})

    def test_remote_gm_log_panel_in_the_controller_tab(self):
        """S19-11: the Controller tab lists what the remote GM sent, from GET /api/v1/remote-gm, in the
        console's language; the GM token only."""
        game = self.field.create_game()
        self.add_remote_command(command_id="00000000-0000-4000-8000-000000000001", user_id="u1", username="ana",
                                command="pause", params={"reason": "chuva"}, game_id=game["id"], game_seed=1,
                                result="done", detail=None)
        self.add_remote_command(command_id="00000000-0000-4000-8000-000000000002", user_id="u1", username="ana",
                                command="message", params={"text": "Fim em 5 min"}, game_id=game["id"], game_seed=1,
                                result="not_live", detail="game 9 (seed 1) is not this controller's live game")
        page = self.console()
        page.get_by_test_id("tab-controller").click()
        expect(page.get_by_test_id("remote-gm")).to_be_visible()
        expect(page.get_by_test_id("remote-gm-off")).to_contain_text("GM remoto está desligado")  # [sync] remote_gm off
        rows = page.get_by_test_id("remote-gm-row")
        expect(rows).to_have_count(2)
        newest = rows.nth(0)                                      # the latest command first
        expect(newest).to_contain_text("ana")
        expect(newest).to_contain_text("mensagem para todas as caixas")
        expect(newest).to_contain_text("Fim em 5 min")
        expect(newest).to_contain_text("recusado: não é o jogo em curso")
        expect(rows.nth(1)).to_contain_text("pausa")
        expect(rows.nth(1)).to_contain_text("chuva")
        expect(rows.nth(1)).to_contain_text("cumprido")
        # Another language; a command that arrives later shows without leaving the tab (it asks every 10 s,
        # and "Refresh" asks now).
        page.get_by_test_id("lang").select_option("en")
        expect(page.get_by_test_id("remote-gm-off")).to_contain_text("The remote GM is off")
        self.add_remote_command(command_id="00000000-0000-4000-8000-000000000003", user_id="u2", username="rui",
                                command="end", params={}, game_id=game["id"], game_seed=1, result="done", detail=None)
        page.get_by_test_id("remote-gm-refresh").click()
        expect(rows).to_have_count(3)
        expect(rows.nth(0)).to_contain_text("rui")
        expect(rows.nth(0)).to_contain_text("done")
        expect(rows.nth(1)).to_contain_text("refused: not the live game")
        self.no_horizontal_scroll(page)
        # The read token never sees it (the API refuses it too).
        read = self.console(READ)
        read.get_by_test_id("tab-controller").click()
        expect(read.get_by_test_id("controller-status")).to_be_visible()
        expect(read.get_by_test_id("remote-gm")).to_have_count(0)
        refused = httpx.get(self.field.base + "/api/v1/remote-gm", headers={"Authorization": f"Bearer {READ}"})
        self.assertEqual(refused.status_code, 403)

    # --- "the poster changed" (decision check-R8) ---------------------------------------

    def test_console_says_the_poster_changed_and_suggests_printing_it_again(self):
        """The poster's addresses are worked out again at every start: when they differ from the poster last
        printed, the console says so (an alert and a notice in the Check-in tab); printing it again quiets it."""
        poster = self.field.http.get("/api/v1/checkin/poster").json()
        self.assertEqual((poster["printed"], poster["changed"]), (None, None))   # never printed: nothing to compare
        page = self.console()
        page.get_by_test_id("tab-checkin").click()
        expect(page.get_by_test_id("poster-ca")).to_be_visible()
        expect(page.get_by_test_id("poster-changed")).to_have_count(0)
        # The poster that was printed had another address (a DHCP lease that moved).
        self.field.bundle.store.set_setting("checkin.poster_printed", json.dumps(
            {"urls": ["https://10.42.0.7:8443"], "ca_sha256": poster["ca_sha256"], "at": 1.0}))
        page = self.console()          # a new start of the console: the alert
        page.get_by_test_id("tab-checkin").click()
        notice = page.get_by_test_id("poster-changed")
        expect(notice).to_be_visible()
        expect(notice).to_contain_text("O cartaz mudou.")
        expect(notice).to_contain_text("https://10.42.0.1:8443")
        expect(notice).to_contain_text("já não chega a ele")
        page.get_by_test_id("tab-feed").click()
        expect(page.get_by_test_id("alerts")).to_contain_text("O cartaz de check-in mudou: imprime-o de novo.")
        # Printing it (the poster page's button) keeps these addresses as the printed ones.
        sheet = page.context.new_page()
        sheet.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        sheet.goto(self.field.base + "/console/poster.html")
        expect(sheet.get_by_test_id("poster-qr")).to_be_visible()
        sheet.evaluate("window.print = () => {}")                    # headless: no print dialog
        sheet.get_by_test_id("poster-print").click()
        self.assertTrue(wait_for(lambda: self.field.http.get("/api/v1/checkin/poster").json()["changed"] is None, 5))
        printed = self.field.http.get("/api/v1/checkin/poster").json()["printed"]
        self.assertEqual(printed["urls"], poster["urls"])
        self.assertEqual(printed["ca_sha256"], poster["ca_sha256"])
        # Back in the console, the notice goes (the tab asks again when its window is focused).
        page.get_by_test_id("tab-checkin").click()
        page.evaluate("window.dispatchEvent(new Event('focus'))")
        expect(page.get_by_test_id("poster-changed")).to_have_count(0)
        # The same console in English; a changed certificate says printed posters no longer work.
        self.field.bundle.store.set_setting("checkin.poster_printed", json.dumps(
            {"urls": poster["urls"], "ca_sha256": "ab" * 32, "at": 1.0}))
        page.get_by_test_id("lang").select_option("en")
        page.evaluate("window.dispatchEvent(new Event('focus'))")
        expect(page.get_by_test_id("poster-changed")).to_contain_text("printed posters no longer work")
        # Not for the read token (it has no poster).
        self.assertEqual(httpx.post(self.field.base + "/api/v1/checkin/poster/printed",
                                    headers={"Authorization": f"Bearer {READ}"}).status_code, 403)

    # --- "Print the poster?" can be paused (WCAG 2.2.1, decision check-R15) -------------------

    def test_poster_prompt_countdown_can_be_paused_and_waits_for_the_pointer_and_focus(self):
        page = self.console(poster_prompt=True)
        self.create_game_in_console(page, "Domingo")
        dialog = page.get_by_test_id("poster-prompt")
        expect(dialog).to_be_visible()
        countdown = page.get_by_test_id("poster-prompt-countdown")
        pause = page.get_by_test_id("poster-prompt-pause")
        expect(pause).to_have_attribute("aria-pressed", "false")
        expect(pause).to_contain_text("Pausar a contagem")
        # The pointer over the dialog holds the countdown; leaving it lets it run again.
        dialog.hover()
        held = countdown.text_content()
        page.wait_for_timeout(2500)
        self.assertEqual(countdown.text_content(), held, "the countdown ran under the pointer")
        page.mouse.move(2, 2)
        expect(countdown).not_to_have_text(held, timeout=4000)
        # The button stops it until it is pressed again: the dialog then stays.
        pause.click()
        expect(pause).to_have_attribute("aria-pressed", "true")
        expect(countdown).to_contain_text("Em pausa")
        expect(page.get_by_test_id("poster-prompt-live")).to_contain_text("Contagem em pausa")
        page.mouse.move(2, 2)
        page.wait_for_timeout(12000)                      # longer than the ten seconds
        expect(dialog).to_be_visible()
        expect(countdown).to_contain_text("Em pausa")
        pause.click()
        expect(pause).to_have_attribute("aria-pressed", "false")
        expect(page.get_by_test_id("poster-prompt-live")).to_contain_text("Contagem retomada")
        page.mouse.move(2, 2)                             # the pointer left over the button would hold it
        # Running again, with the seconds that were left: it closes itself (the default is kept).
        expect(dialog).to_be_hidden(timeout=12000)

    def test_poster_prompt_waits_while_a_control_has_keyboard_focus(self):
        page = self.console(poster_prompt=True)
        self.create_game_in_console(page, "Domingo")
        dialog = page.get_by_test_id("poster-prompt")
        expect(dialog).to_be_visible()
        page.mouse.move(2, 2)
        page.keyboard.press("Tab")                        # onto the first control, inside the dialog
        self.assertTrue(page.evaluate("document.querySelector('[data-testid=poster-prompt]').contains(document.activeElement)"
                                      " && document.activeElement !== document.querySelector('[data-testid=poster-prompt]')"))
        page.wait_for_timeout(13000)
        expect(dialog).to_be_visible()                    # held while the control has focus
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden(timeout=1500)

    # --- "share with players": the scoreboard's QR code (decision PD13) -------------------

    def test_scoreboard_qr_code_is_the_scoreboard_address_the_app_follows(self):
        if not ZBARIMG:
            self.skipTest("zbarimg is not installed")
        self.field.create_game()
        page = self.console()
        box = page.get_by_test_id("scoreboard-share")
        expect(box).to_be_visible()
        expect(page.get_by_test_id("scoreboard-qr")).to_have_count(0)             # the code is asked for, not shown
        page.get_by_test_id("scoreboard-show").click()
        expect(page.get_by_test_id("scoreboard-qr")).to_be_visible()
        # The address the app takes (FieldLink.parse): http://host:port/scoreboard#token=<read code>, the host one
        # the poster lists (this field's is configured), the port the controller's API.
        want = f"http://10.42.0.1:{self.field.port}/scoreboard#token={READ}"
        expect(page.get_by_test_id("scoreboard-link")).to_have_text(want)
        with tempfile.TemporaryDirectory() as tmp:
            shot = os.path.join(tmp, "scoreboard.png")
            page.get_by_test_id("scoreboard-qr").screenshot(path=shot)
            out = read_qr(shot)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, want)
        parts = urlsplit(out.stdout)
        self.assertEqual((parts.scheme, parts.hostname, parts.port, parts.path), ("http", "10.42.0.1", self.field.port, "/scoreboard"))
        self.assertEqual(parse_qs(parts.fragment), {"token": [READ]})
        expect(page.get_by_test_id("scoreboard-warning")).to_contain_text("quem o tiver pode acompanhar")
        # The same address opens the scoreboard page (here at this machine's own address) with the read code.
        board = self.page(f"/scoreboard#token={READ}")
        expect(board.get_by_test_id("board-state")).to_be_visible()
        page.get_by_test_id("scoreboard-hide").click()
        expect(page.get_by_test_id("scoreboard-qr")).to_have_count(0)
        # The GM token only: the read token gets neither the panel nor the address.
        read = self.console(READ)
        expect(read.get_by_test_id("scoreboard-share")).to_have_count(0)
        self.assertEqual(httpx.get(self.field.base + "/api/v1/scoreboard-link",
                                   headers={"Authorization": f"Bearer {READ}"}).status_code, 403)
        link = self.field.http.get("/api/v1/scoreboard-link")
        # Then the https address of the poster with the field CA's fingerprint (`ca`, in the fragment, never sent to
        # the server): what the app fetches from /api/v1/controller/ca, checks and pins.
        ca = self.field.bundle.tls.ca_sha256.hex()
        want_tls = f"https://10.42.0.1:8443/scoreboard#token={READ}&ca={ca}"
        self.assertEqual(link.json(), {"links": [want, want_tls]})
        self.assertEqual(link.headers["cache-control"], "no-store")
        page.get_by_test_id("scoreboard-show").click()
        page.get_by_test_id("scoreboard-address").select_option(index=1)
        expect(page.get_by_test_id("scoreboard-link")).to_have_text(want_tls)
        with tempfile.TemporaryDirectory() as tmp:
            shot = os.path.join(tmp, "scoreboard-tls.png")
            page.get_by_test_id("scoreboard-qr").screenshot(path=shot)
            out = read_qr(shot)
        self.assertEqual(out.stdout, want_tls)
        parts = urlsplit(out.stdout)
        self.assertEqual((parts.scheme, parts.port), ("https", 8443))
        self.assertEqual(parse_qs(parts.fragment), {"token": [READ], "ca": [ca]})

    # --- the log's words for every event (E) -----------------------------------------------

    def test_the_log_has_words_for_every_event_the_built_in_modes_emit(self):
        emitted = set()
        for lua in (CONTROLLER.parent / "modes").glob("*/*.lua"):
            emitted |= set(re.findall(r"""(?:emit|event)[a-z_]*\(\s*["']([a-z_]+\.[a-z_.]+)["']""",
                                      lua.read_text(encoding="utf-8")))
        core = {"game.start", "game.pause", "game.resume", "game.end", "score.delta", "gm.message", "team.eliminated"}
        types = sorted(emitted | core)
        self.assertGreaterEqual(len(types), 25, types)
        page = self.page()
        for lang in ("pt", "en", "de", "zh-tw"):
            words = page.evaluate("""async ([lang, types]) => {
                const m = await import('/console/ui.js');
                await m.loadLanguage(lang);
                return types.map((type) => [type, m.eventWords({ type, team: 'red', node: 3, data: {} })]);
            }""", [lang, types])
            for typ, text in words:
                self.assertNotEqual(text, "", f"{lang}: no words for {typ}")
                self.assertNotIn("feed.events", text)
        # Placeholders are filled from the event's data.
        one = page.evaluate("""async () => {
            const m = await import('/console/ui.js');
            await m.loadLanguage('en');
            return [m.eventWords({ type: 'zone.captured', team: 'red', node: 3, data: { zone: 'Alpha' } }),
                    m.eventWords({ type: 'player.respawn', node: 3, data: { player: 'P1', lives_left: 2 } }),
                    m.eventWords({ type: 'bomb.armed', team: 'blue', node: 4, data: { fuse_s: 30 } }),
                    m.eventWords({ type: 'game.end', node: 0, data: { reason: 'win', by_node: 5, by_name: 'Gate' } }),
                    m.eventWords({ type: 'game.end', node: 0, data: { by_node: 5 } }),
                    m.eventWords({ type: 'game.end', node: 0, data: { reason: 'time' } })];
        }""")
        self.assertEqual(one, ["red captured Alpha", "P1 is back in (2 lives)", "Bomb armed by blue (30 s)",
                               "The game ended: ended by box Gate", "The game ended: ended by box 5",
                               "The game ended"])
        # "ended by box <name or node id>" in every language (GE-5).
        for lang in ("pt", "de", "zh-tw"):
            text = page.evaluate("""async (lang) => {
                const m = await import('/console/ui.js');
                await m.loadLanguage(lang);
                return m.eventWords({ type: 'game.end', node: 0, data: { by_node: 5, by_name: 'Gate' } });
            }""", lang)
            self.assertIn("Gate", text, lang)
            self.assertNotIn("feed.events", text)

    # --- field and team branding (decisions BR1-BR24) -------------------------------

    def loaded(self, locator) -> None:
        """The image is shown and the browser decoded it."""
        expect(locator).to_be_visible()
        self.assertTrue(wait_for(lambda: locator.evaluate("img => img.complete && img.naturalWidth > 0"), 5),
                        "the image did not decode")

    def forget_refusal(self, path: str) -> None:
        """A refusal the test asked for is not a page error."""
        self.errors = [e for e in self.errors if path not in e and "status of 4" not in e]

    def test_branding_from_the_site_server_is_labelled_and_read_only(self):
        """PKE-4 (S18-11): with [sync] branding = "site" the Settings tab says the field's name, accent and images come
        from the site server and offers no form for them; the site's saved teams are a list of their own with a badge
        and no delete button, the console's own presets below them as before."""
        from atalaia_controller import sync_format
        self.field.close()
        self.field = Field(cfg={"sync_url": "https://site.example.org", "sync_enabled": True, "sync_branding": "site"})
        answer = sync_format.check_field({"sync_version": 1, "field": {
            "field_name": "Campo do Sul", "accent": "#1e6b3a", "logo": None, "wallpaper": None},
            "teams": [{"team_id": "0e000000-0000-4000-8000-000000000001", "name": "Lobos", "colour": "red",
                       "crest": None, "club": {"slug": "lobos", "name": "Clube Lobos"}}]})
        self.field.bundle.controller.branding.apply_site(answer)
        page = self.console()
        page.get_by_test_id("tab-settings").click()
        expect(page.get_by_test_id("branding-from-site")).to_contain_text("servidor do campo")
        expect(page.get_by_test_id("branding-site-name")).to_have_text("Campo do Sul")
        expect(page.get_by_test_id("branding-form")).to_have_count(0)
        expect(page.get_by_test_id("branding-logo-upload")).to_have_count(0)
        expect(page.get_by_test_id("branding-rights")).to_have_count(0)
        site = page.get_by_test_id("site-teams")
        expect(site).to_contain_text("Lobos")
        expect(site.get_by_test_id("team-preset-site-badge")).to_be_visible()
        expect(site.locator("[data-testid^=team-preset-delete-]")).to_have_count(0)
        page.get_by_test_id("team-preset-name").fill("Corvos")
        page.get_by_test_id("team-preset-add").click()
        local = page.locator("[data-testid=team-presets] ul").nth(1)
        expect(local).to_contain_text("Corvos")
        expect(local.locator("[data-testid^=team-preset-delete-]")).to_have_count(1)
        presets = {p["name"]: p for p in self.field.http.get("/api/v1/team-presets").json()}
        self.assertEqual((presets["Lobos"]["source"], "source" in presets["Corvos"]), ("site", False))

    def test_names_the_box_cannot_draw_are_warned_about(self):
        """PKE-3 (follow-up of P5K-5): a team, preset or field name with a letter the box's fonts lack is warned
        about where it is typed, with the letters; Portuguese and German letters, and Chinese ones the box's texts
        have, pass; the name is still accepted."""
        page = self.console()
        got = page.evaluate("""() => import('./components/box-glyphs.js').then(async (m) => {
            const g = await m.loadGlyphs();
            return [m.glyphProblems('Águias ção Größe 123 -', g), m.glyphProblems('紅隊', g),
                    m.glyphProblems('Łódź Привет', g), m.glyphProblems('', g), m.glyphProblems('x', null)];
        })""")
        self.assertEqual(got[0], {"none": [], "some": []})
        self.assertEqual(got[1]["none"], ["紅"])  # 隊 is in the box's texts, 紅 is not (P5K-14)
        self.assertEqual(sorted(got[2]["none"]), sorted(["Ł", "ź", "П", "р", "и", "в", "е", "т"]))
        self.assertEqual(got[3:], [{"none": [], "some": []}, {"none": [], "some": []}])
        page.get_by_test_id("tab-game").click()
        expect(page.get_by_test_id("glyph-teams")).to_have_count(0)
        page.get_by_test_id("game-teams").fill("Lobos, 紅隊")
        expect(page.get_by_test_id("glyph-teams")).to_contain_text("紅")
        expect(page.get_by_test_id("glyph-teams")).to_contain_text("?")
        expect(page.get_by_test_id("glyph-none")).to_have_count(1)
        page.get_by_test_id("game-teams").fill("Lobos, Águias")
        expect(page.get_by_test_id("glyph-teams")).to_have_count(0)
        page.get_by_test_id("tab-settings").click()
        page.get_by_test_id("branding-name").fill("Campo 北")
        expect(page.get_by_test_id("glyph-field-name")).to_contain_text("北")
        page.get_by_test_id("branding-name").fill("Campo Norte")
        expect(page.get_by_test_id("glyph-field-name")).to_have_count(0)
        page.get_by_test_id("team-preset-name").fill("Яблоко")
        expect(page.get_by_test_id("glyph-team-preset")).to_be_visible()

    def test_game_scenario_and_team_display_names_the_box_cannot_draw_are_warned_about(self):
        """GLY-1: the game's name, a team's display name (the game form's team branding) and a scenario's and
        its objectives' names (also the Portuguese ones) are warned about like the other names (PKE-3), with the
        same wording; the name is still accepted (the scenario is checked, the game is made)."""
        page = self.console()
        page.get_by_test_id("tab-game").click()
        expect(page.get_by_test_id("glyph-game-name")).to_have_count(0)
        page.get_by_test_id("game-name").fill("Jogo 紅")
        expect(page.get_by_test_id("glyph-game-name")).to_contain_text("紅")
        expect(page.get_by_test_id("glyph-game-name")).to_contain_text("?")
        page.get_by_test_id("game-name").fill("Jogo Águias")
        expect(page.get_by_test_id("glyph-game-name")).to_have_count(0)
        page.get_by_test_id("game-team-branding").locator("summary").click()
        team = page.get_by_test_id("game-team-name-red")
        expect(page.get_by_test_id("game-glyph-team-name-red")).to_have_count(0)
        team.fill("Яблоко")
        expect(page.get_by_test_id("game-glyph-team-name-red")).to_contain_text("Я")
        expect(page.get_by_test_id("game-glyph-team-name-blue")).to_have_count(0)
        team.fill("Lobos")
        expect(page.get_by_test_id("game-glyph-team-name-red")).to_have_count(0)
        page.get_by_test_id("tab-scenarios").click()
        page.get_by_test_id("scenario-example").click()
        expect(page.get_by_test_id("scenario-ok")).to_be_visible()
        expect(page.get_by_test_id("glyph-scenario")).to_have_count(0)
        editor = page.get_by_test_id("scenario-text")
        example = editor.input_value()
        self.assertIn("\nname:", example)
        editor.fill(example.replace("\nname:", "\nname: 紅 ", 1))
        expect(page.get_by_test_id("glyph-scenario")).to_contain_text("紅")
        expect(page.get_by_test_id("scenario-ok")).to_be_visible()  # a warning only
        editor.fill(example.replace("    name:", "    name: Ł ", 1))
        expect(page.get_by_test_id("glyph-scenario")).to_contain_text("Ł")
        expect(page.get_by_test_id("scenario-install")).to_be_enabled()
        editor.fill(example)
        expect(page.get_by_test_id("glyph-scenario")).to_have_count(0)

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


class ConsoleTextsTests(unittest.TestCase):
    """The console's texts (no browser): nothing internal for the GM to read, and the Portuguese as the app
    and the site write it (tu, no gendered or formal forms, the glossary's words)."""

    I18N = CONTROLLER / "console" / "src" / "i18n"

    @staticmethod
    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                yield from ConsoleTextsTests.walk(v, f"{path}.{k}" if path else k)
        else:
            yield path, node

    def texts(self, lang: str):
        return list(self.walk(json.loads((self.I18N / f"{lang}.json").read_text(encoding="utf-8"))))

    def test_no_internal_ids_in_any_language(self):
        internal = re.compile(r"\bADR-|\b(?:check|PE24|PD|MF|BR|CL|FL|GM|RJ|SQ|MR|OT|S19|FU\d?)-\d+|\bP[0-9][A-Z]-?\d+")
        for lang in ("en", "pt", "de", "zh-tw"):
            for key, text in self.texts(lang):
                self.assertIsNone(internal.search(text), f"{lang} {key}: {text}")

    def test_portuguese_is_tu_and_the_glossary_words(self):
        formal = re.compile(r"\b(?:Convide|comece|[Tt]ermine|[Cc]rie|[Jj]unte|[Rr]einicie|[Aa]tualize|[Cc]arregue|[Ee]scolha|"
                            r"[Mm]arque|[Cc]onfigure|[Ii]mprima|[Pp]ode fechar|[Vv]oc[eê]s?|[Ii]ntroduza|[Cc]lique|[Dd]igite)\b")
        for key, text in self.texts("pt"):
            self.assertIsNone(formal.search(text), f"pt {key}: {text}")
            self.assertNotIn("jogadores", text.lower(), f"pt {key}: gendered plural")
            self.assertNotIn("servidor do clube", text.lower(), f"pt {key}: the glossary says servidor do site")
        pt = dict(self.texts("pt"))
        self.assertNotIn("red, blue", pt["game.teams_hint"])
        self.assertIn("«PRONTA»", pt["invites.empty"])                     # the pt box shows PRONTA
        self.assertIn("código de acesso", pt["poster.login"])              # as the login says
        self.assertIn("código de acesso", pt["fieldmap.login"])


if __name__ == "__main__":
    unittest.main()
