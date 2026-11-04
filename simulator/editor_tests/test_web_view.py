# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Browser tests of the simulator's web view: a box's screen drawn from its template (decisions
SIMS-1 to SIMS-8), next to its outputs (draft RFC "The expansion port", increment 4).

The page, served by the simulator's real web server, runs in headless Chromium (Playwright), as
the mode editor's tests do (run.sh, python tools/docker_editor.py, CI's editor job). With
ATALAIA_REQUIRE_BROWSER=1 a missing Playwright or core is an error, never a skip.
"""

from __future__ import annotations

import os
import re
import threading
import unittest
from pathlib import Path

from atalaia_sim.core import Core, find_library
from atalaia_sim.live import LiveGame
from atalaia_sim.mode import load_mode
from atalaia_sim.sim import Simulation
from atalaia_sim.web import make_server

REPO = Path(__file__).resolve().parents[2]
REQUIRE = os.environ.get("ATALAIA_REQUIRE_BROWSER") == "1"
TEAMS = ["red", "blue"]

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover - the test image has it
    if REQUIRE:
        raise
    sync_playwright = None


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        if REQUIRE:
            raise
        return None


CORE = _core() if sync_playwright else None


@unittest.skipIf(CORE is None, "Playwright or the core library is missing")
class WebViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mode = load_mode(REPO / "modes" / "bomb")
        params = mode.resolve_params({"fuse_s": 60, "smoke_s": 3}, TEAMS)
        cls.game = LiveGame(lambda: Simulation(CORE, mode, {"bomb": "bomb"}, TEAMS, params))
        cls.server = make_server(cls.game, "127.0.0.1", 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.game.close()

    def setUp(self):
        self.game.act("reset", {})

    def open(self, width=1280):
        context = self.browser.new_context(viewport={"width": width, "height": 900})
        self.addCleanup(context.close)
        page = context.new_page()
        self.errors, self.outside = [], []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        origin = self.server.url.rstrip("/")
        page.on("request", lambda r: r.url.startswith(origin) or self.outside.append(r.url))
        page.on("dialog", lambda d: d.accept())
        page.goto(self.server.url)
        return page

    def tearDown(self):
        self.assertEqual(getattr(self, "errors", []), [])
        self.assertEqual(getattr(self, "outside", []), [])  # the page works offline

    def test_the_screen_is_drawn_from_its_template(self):
        page = self.open()
        node = page.locator(".node").first
        self.game.act("start", {})
        lcd = node.locator(".lcd")
        expect(lcd).to_have_attribute("data-template", "standby")
        box = lcd.bounding_box()
        self.assertEqual((round(box["width"]), round(box["height"])), (320, 240))
        self.assertEqual(lcd.evaluate("e => getComputedStyle(e).backgroundColor"), "rgb(16, 20, 24)")
        # Red arms the bomb: the countdown, its header on the danger colour, the fuse bar.
        self.game.act("hold", {"node": "bomb", "team": "red"})
        self.game.act("step", {"seconds": 5})
        self.game.act("release", {"node": "bomb"})
        self.game.act("step", {"seconds": 10})
        expect(lcd).to_have_attribute("data-template", "countdown")
        expect(lcd.locator("[data-id=time_left]")).to_have_text("0:50")
        expect(lcd).to_contain_text("ARMED")
        header = lcd.locator(".w-row").first
        self.assertEqual(header.evaluate("e => getComputedStyle(e).backgroundColor"), "rgb(229, 57, 53)")
        self.assertEqual(round(header.bounding_box()["width"]), 320)  # width: fill
        self.assertEqual(round(header.bounding_box()["height"]), 44)
        fuse = lcd.locator("[data-id=fuse_bar]")
        expect(fuse).to_have_attribute("aria-valuenow", "83")
        self.assertEqual(round(fuse.bounding_box()["width"]), 240)
        fill = fuse.locator(".w-fill").bounding_box()["width"]
        self.assertAlmostEqual(fill, 0.83 * 240, delta=1)
        # The defuse bar and its text are hidden until the defenders hold.
        expect(lcd.locator("[data-id=defuse_bar]")).to_be_hidden()
        font = lcd.locator("[data-id=time_left]").evaluate("e => getComputedStyle(e).fontSize")
        self.assertEqual(font, "48px")
        # The box language: the same screen in Portuguese.
        page.select_option("#box-lang", "pt")
        expect(lcd).to_contain_text("ARMADA")
        expect(lcd).to_contain_text("até à explosão")
        # The template's name and data are still there, under it.
        expect(node.locator(".template")).to_have_text("countdown")
        expect(node.locator(".screen-data")).to_contain_text("left")

    def test_the_outputs_are_drawn_beside_the_screen(self):
        """Increment 4 of the expansion port: the explosion fires the smoke output."""
        page = self.open()
        node = page.locator(".node").first
        self.game.act("start", {})
        switched = node.locator(".switched li")
        expect(switched).to_have_count(2)
        expect(switched.first).to_have_text(re.compile("^smoke: off"))
        self.game.act("hold", {"node": "bomb", "team": "red"})
        self.game.act("step", {"seconds": 5})
        self.game.act("release", {"node": "bomb"})
        for _ in range(90):  # to the explosion, a second at a time: the smoke is on for 3 s
            self.game.act("step", {"seconds": 1})
            if self.game.sim.node("bomb").last_command("ui", "screen").args[0] == "exploded":
                break
        expect(node.locator(".lcd")).to_have_attribute("data-template", "exploded")
        expect(switched.first).to_have_text(re.compile("^smoke: on"))
        expect(switched.first).to_have_class("on")

    def test_a_narrow_card_scales_the_screen_down(self):
        page = self.open(width=340)
        self.game.act("start", {})
        frame = page.locator(".node .lcd-frame").first
        expect(frame.locator(".lcd")).to_have_attribute("data-template", "standby")
        box = frame.bounding_box()
        self.assertLess(box["width"], 320)
        self.assertAlmostEqual(box["height"], box["width"] * 0.75, delta=1.5)
        node = page.locator(".node").first.bounding_box()
        self.assertLessEqual(node["x"] + node["width"], 340)  # the card fits the phone's width


if __name__ == "__main__":
    unittest.main()
