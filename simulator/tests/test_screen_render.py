# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Screens drawn in the web view (decisions SIMS-1 to SIMS-8): the render model the page lays out,
built from the core's own parse of the template and its own evaluation of every expression, as
the Field Box's LVGL renderer (firmware/esp32/main/screen_template.c) builds it.

Every built-in mode's screens are drawn with the data its scripts really send, in its own tests
(modes/*/tests), in every box language; no expression may fail on that data, and the model must
be one the page can draw.
"""

from __future__ import annotations

import ctypes
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterator

import yaml

from atalaia_sim import testing
from atalaia_sim.core import Core, find_library
from atalaia_sim.live import LiveGame
from atalaia_sim.mode import compose, find_modes, load_mode
from atalaia_sim.screens import (FONT_SIZES, LANGS, ScreenError, box_data, find_screen,
                                 nearest_font, render_screen, screen_files)
from atalaia_sim.sim import Simulation

ROOT = Path(__file__).resolve().parents[2]
MODES = ROOT / "modes"
TEAMS = ["red", "blue"]
HEX = re.compile(r"^#[0-9a-f]{6}$")
TYPES = {"label", "progress_bar", "icon", "qr_code", "spacer", "row", "column"}
_LOG = ctypes.CFUNCTYPE(None, ctypes.c_char_p)


def walk(widgets: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for w in widgets:
        yield w
        yield from walk(w.get("children", []))


def yaml_widgets(node: Any) -> int:
    """The widgets a template's YAML has (rows and columns with their children)."""
    if isinstance(node, list):
        return sum(yaml_widgets(n) for n in node)
    if isinstance(node, dict) and "type" in node:
        return 1 + yaml_widgets(node.get("children", []))
    return 0


def texts(model: dict[str, Any]) -> list[str]:
    return [w["text"] for w in walk(model["widgets"]) if w["visible"] and "text" in w]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core = Core(find_library())
        # Expressions that fail while rendering (the box shows "?" for them and logs one line).
        cls.failed: list[str] = []
        cls._log = _LOG(lambda message: cls.failed.append(message.decode(errors="replace")))
        cls.core.lib.atalaia_tpl_set_log.argtypes = [_LOG]
        cls.core.lib.atalaia_tpl_set_log.restype = None
        cls.core.lib.atalaia_tpl_set_log(cls._log)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.core.lib.atalaia_tpl_set_log(_LOG())

    def render(self, source: str, data: dict[str, Any] | None = None,
               params: dict[str, Any] | None = None) -> dict[str, Any]:
        return render_screen(self.core, source.encode(), data or {}, params or {})

    def check_model(self, model: dict[str, Any], source: bytes, where: str) -> None:
        """A model the page can draw: known widgets, colours as #rrggbb, the box's fonts, bar
        values in 0-100, every widget of the YAML once."""
        self.assertEqual((model["width"], model["height"]), (320, 240), where)
        self.assertRegex(model["background"], HEX, where)
        widgets = list(walk(model["widgets"]))
        self.assertEqual(len(widgets), yaml_widgets(yaml.safe_load(source)["layout"]), where)
        for w in widgets:
            self.assertIn(w["type"], TYPES, where)
            self.assertIsInstance(w["visible"], bool, where)
            self.assertIn(w["align"], ("left", "center", "right"), where)
            self.assertEqual(len(w["padding"]), 4, where)
            for side in ("width", "height"):
                self.assertTrue(w[side] is None or w[side] == "fill"
                                or (isinstance(w[side], int) and 0 <= w[side] <= 1000), where)
            if w["background"] is not None:
                self.assertRegex(w["background"], HEX, where)
            if w["type"] in ("label", "icon", "qr_code"):
                self.assertIn(w["font"], FONT_SIZES, where)
                self.assertRegex(w["color"], HEX, where)
            if w["type"] in ("label", "qr_code"):
                self.assertIsInstance(w["text"], str, where)
                self.assertLess(len(w["text"].encode()), 160, where)  # ATALAIA_TPL_TEXT_MAX
            if w["type"] == "progress_bar":
                self.assertTrue(0 <= w["value"] <= 100, where)
                self.assertRegex(w["color"], HEX, where)
                self.assertIsInstance(w["width"], (int, str), where)
            if w["type"] in ("row", "column"):
                self.assertIsInstance(w["children"], list, where)


class _Recording(Simulation):
    """A Simulation that keeps the screens its nodes showed when it closes."""

    shown: list[tuple[Any, str, dict[str, Any], dict[str, Any], int]] = []

    def close(self) -> None:
        for vnode in self.nodes.values():
            for cmd in vnode.commands:
                if cmd.target == "ui" and cmd.method == "screen" and cmd.args:
                    data = cmd.args[1] if len(cmd.args) > 1 and isinstance(cmd.args[1], dict) else {}
                    _Recording.shown.append((self.mode, cmd.args[0], data, dict(self.params),
                                             cmd.t_ms // 1000))
        super().close()


class BuiltInModeScreens(Base):
    """Each built-in mode's screens, drawn with the data its own tests make its scripts send."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        _Recording.shown = []
        real = testing.Simulation
        testing.Simulation = _Recording
        try:
            for path in find_modes([MODES]):
                mode = load_mode(path)
                for test in mode.tests:
                    testing.run_test(cls.core, mode, test)
        finally:
            testing.Simulation = real
        cls.shown = list(_Recording.shown)

    def test_every_screen_a_mode_shows_draws_without_a_failed_expression(self) -> None:
        drawn: dict[str, set[str]] = {}
        for mode, name, data, params, game_s in self.shown:
            path = find_screen(mode.screen_folders, name)
            if path is None:
                continue  # a built-in C screen of the Field Box (code_entry, final_score, ...)
            source = path.read_bytes()
            drawn.setdefault(path.parent.parent.parent.name, set()).add(name)
            for lang in ("", *LANGS):
                where = f"{mode.id} / {name} / lang {lang or 'not set'} / {data}"
                self.failed.clear()
                model = render_screen(self.core, source, box_data(data, lang, game_s), params)
                self.assertEqual(self.failed, [], where)
                self.assertEqual(model["template"], name, where)
                self.check_model(model, source, where)
                self.assertTrue(any(w["visible"] for w in walk(model["widgets"])), where)
        # Every built-in mode with templates had them drawn by its tests.
        with_screens = {p.name for p in find_modes([MODES]) if screen_files(p)}
        self.assertEqual(with_screens - set(drawn), set())
        self.assertIn("countdown", drawn["bomb"])

    def test_every_template_draws_with_no_data(self) -> None:
        """A screen before its data is in (or with a key missing) still draws: a missing name is
        empty, so no template may fail on an empty data."""
        for path in find_modes([MODES]):
            for file in screen_files(path):
                for lang in ("", *LANGS):
                    with self.subTest(mode=path.name, screen=file.stem, lang=lang):
                        self.failed.clear()
                        model = render_screen(self.core, file.read_bytes(), box_data({}, lang), {})
                        self.check_model(model, file.read_bytes(), f"{path.name}/{file.stem}")
                        self.assertEqual(self.failed, [])

    def test_each_language_draws_its_own_texts(self) -> None:
        """The templates' language chains: the countdown's header in the box's language."""
        source = (MODES / "bomb" / "assets" / "screens" / "countdown.yaml").read_bytes()
        headers = {}
        for lang in ("", *LANGS):
            model = render_screen(self.core, source, box_data({"left": 30}, lang), {"fuse_s": 60})
            headers[lang] = model["widgets"][0]["children"][0]["text"]
        self.assertEqual(headers, {"": "ARMED", "en": "ARMED", "pt": "ARMADA", "de": "SCHARF",
                                   "zh-tw": "已啟動"})


class RenderModel(Base):
    """The rules of the Field Box's renderer, one by one."""

    def test_bomb_countdown_with_the_data_bomb_sends(self) -> None:
        mode = load_mode(MODES / "bomb")
        params = mode.resolve_params({"fuse_s": 60}, TEAMS)
        sim = Simulation(self.core, mode, {"bomb": "bomb"}, TEAMS, params)
        self.addCleanup(sim.close)
        sim.start()
        sim.hold("bomb", "red", 5)
        sim.wait(10)
        name, data = sim.node("bomb").last_command("ui", "screen").args
        source = find_screen(mode.screen_folders, name).read_bytes()
        model = render_screen(self.core, source, box_data(data), params)
        header, spacer, left, until, fuse, defusing, defuse, *_ = model["widgets"]
        self.assertEqual((header["type"], header["width"], header["height"], header["background"]),
                         ("row", "fill", 44, "#e53935"))  # danger
        self.assertEqual(header["children"][0]["text"], "ARMED")
        self.assertEqual((spacer["type"], spacer["height"]), ("spacer", "fill"))
        self.assertEqual((left["id"], left["text"], left["font"], left["color"]),
                         ("time_left", "0:50", 48, "#ffffff"))
        self.assertEqual((until["text"], until["color"]), ("until detonation", "#9aa5b1"))  # muted
        self.assertEqual((fuse["value"], fuse["width"], fuse["height"]), (83, 240, 10))
        self.assertFalse(defusing["visible"])
        self.assertFalse(defuse["visible"])
        # The last ten seconds in red, and a defenders' hold fills the defuse bar.
        model = render_screen(self.core, source, {**data, "left": 9, "defuse": 0.25}, params)
        self.assertEqual(model["widgets"][2]["color"], "#e53935")
        self.assertTrue(model["widgets"][5]["visible"])
        self.assertEqual((model["widgets"][6]["visible"], model["widgets"][6]["value"]), (True, 25))

    def test_defaults_are_the_boxs(self) -> None:
        model = self.render("template: t\nlayout:\n  - type: label\n    text: hi\n"
                            "  - type: progress_bar\n    value: 0.5\n"
                            "  - type: spacer\n    height: 8\n"
                            "  - type: qr_code\n    data: \"x{n}\"\n", {"n": 3})
        label, bar, spacer, qr = model["widgets"]
        self.assertEqual(model["background"], "#101418")
        self.assertEqual((label["color"], label["font"], label["background"], label["align"]),
                         ("#ffffff", 20, None, "center"))
        self.assertEqual((label["width"], label["height"]), (None, None))
        self.assertEqual((bar["width"], bar["height"], bar["color"], bar["track"], bar["value"]),
                         (200, 12, "#ffb300", "#222b35", 50))
        self.assertEqual((spacer["width"], spacer["height"]), (1, 8))
        self.assertEqual((qr["text"], qr["font"]), ("x3", 14))  # drawn as its text, as on the box

    def test_fonts_pick_the_nearest_of_the_box(self) -> None:
        self.assertEqual([nearest_font(s) for s in (0, 6, 16, 17, 24, 25, 38, 39, 200)],
                         [20, 14, 14, 20, 20, 28, 28, 48, 48])

    def test_colours(self) -> None:
        source = ("template: t\nstyle: { background: \"{bg}\" }\nlayout:\n"
                  "  - type: label\n    text: a\n    style: { color: team }\n"
                  "  - type: label\n    text: b\n    style: { color: contrast }\n"
                  "  - type: row\n    style: { background: yellow }\n    children:\n"
                  "      - type: label\n        text: c\n        style: { color: contrast }\n"
                  "  - type: label\n    text: d\n    style: { color: \"{c}\" }\n"
                  "  - type: progress_bar\n    value: 1\n    style: { color: team, background: red }\n")
        model = self.render(source, {"team": "blue", "bg": "white", "c": "#12AB34"})
        a, b, row, d, bar = model["widgets"]
        self.assertEqual(model["background"], "#ffffff")
        self.assertEqual(a["color"], "#1e88e5")  # the data's team
        self.assertEqual(b["color"], "#101418")  # dark on the white screen
        self.assertEqual(row["background"], "#fdd835")
        self.assertEqual(row["children"][0]["color"], "#101418")  # dark on yellow
        self.assertEqual(d["color"], "#12ab34")
        self.assertEqual((bar["color"], bar["background"]), ("#1e88e5", None))  # a bar has no background
        # A team without a colour is grey; no team leaves the default; contrast on dark is white.
        model = self.render(source, {"team": "wolves", "bg": "panel"})
        self.assertEqual(model["widgets"][0]["color"], "#78909c")
        self.assertEqual(model["widgets"][1]["color"], "#ffffff")
        self.assertEqual(model["widgets"][3]["color"], "#ffffff")  # "{c}" empty: not set
        self.assertEqual(self.render(source, {})["widgets"][0]["color"], "#ffffff")

    def test_layout_properties(self) -> None:
        source = ("template: t\nlayout:\n  - type: column\n    style:\n      width: fill\n"
                  "      height: fill\n      padding: { top: 2, left: 5 }\n    children:\n"
                  "      - type: label\n        id: big\n        text: \"{n|int}\"\n"
                  "        style: { font_size: 40, align: right, padding: 3, visible: \"{n > 1}\" }\n"
                  "      - type: icon\n        icon: warning\n        style: { font_size: 28 }\n"
                  "  - type: label\n    text: never\n    style: { visible: false }\n")
        model = self.render(source, {"n": 2.6})
        column, never = model["widgets"]
        self.assertEqual((column["width"], column["height"], column["padding"]),
                         ("fill", "fill", [2, 0, 0, 5]))
        big, icon = column["children"]
        self.assertEqual((big["id"], big["text"], big["font"], big["align"], big["padding"], big["visible"]),
                         ("big", "2", 48, "right", [3, 3, 3, 3], True))
        self.assertEqual((icon["icon"], icon["font"]), ("warning", 28))
        self.assertFalse(never["visible"])
        self.assertFalse(self.render(source, {"n": 1})["widgets"][0]["children"][0]["visible"])

    def test_bar_values_are_clamped_and_rounded_as_the_box_does(self) -> None:
        source = "template: t\nlayout:\n  - type: progress_bar\n    value: \"{v}\"\n"
        values = [self.render(source, {"v": v})["widgets"][0]["value"]
                  for v in (-1, 0, 0.004, 0.005, 0.5, 2, "x")]
        self.assertEqual(values, [0, 0, 0, 1, 50, 100, 0])

    def test_a_refused_template_is_an_error(self) -> None:
        with self.assertRaises(ScreenError):
            self.render("template: t\nlayout:\n  - type: dial\n")

    def test_box_data(self) -> None:
        """screen_renderer.c add_extras: the box's language unless the mode sets one, and the
        live held time from the data's since."""
        self.assertEqual(box_data({"a": 1}), {"a": 1})
        self.assertEqual(box_data({"a": 1}, "pt"), {"lang": "pt", "a": 1})
        self.assertEqual(box_data({"lang": "de"}, "pt"), {"lang": "de"})
        self.assertEqual(box_data({"since": 10}, "", 75), {"since": 10, "held": 65, "age": 65, "live": 1})
        self.assertEqual(box_data({"since": 10, "held": 3}, "", 75),
                         {"since": 10, "held": 3, "age": 65, "live": 1})
        self.assertEqual(box_data({"since": 90}, "", 75)["age"], 0)
        self.assertEqual(box_data({"since": "10"}, "", 75), {"since": "10"})

    def test_find_screen_looks_in_the_parts_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a", Path(tmp) / "b"
            for folder, names in ((a, ["one"]), (b, ["one", "two"])):
                (folder / "assets" / "screens").mkdir(parents=True)
                for n in names:
                    (folder / "assets" / "screens" / f"{n}.yaml").write_text("x")
            self.assertEqual(find_screen([a, b], "one"), a / "assets" / "screens" / "one.yaml")
            self.assertEqual(find_screen([a, b], "two"), b / "assets" / "screens" / "two.yaml")
            self.assertIsNone(find_screen([a, b], "three"))
            self.assertIsNone(find_screen([a, b], "../a/assets/screens/one"))
        # A scenario's game (org.club.chain+org.atalaia.objectives): the scenario's folder first,
        # then the objectives package's, which has the screens.
        objectives = load_mode(MODES / "objectives")
        game = compose(load_mode(MODES / "objectives" / "tests" / "fixtures" / "chain"), [objectives])
        self.assertEqual(game.screen_folders[-1], objectives.path)
        self.assertEqual(find_screen(game.screen_folders, "obj_status"),
                         objectives.path / "assets" / "screens" / "obj_status.yaml")
        self.assertEqual(objectives.screen_folders, (objectives.path,))


class WebViewState(Base):
    """What GET /api/state gives the page for a node's screen."""

    def live(self, name: str = "bomb", nodes: dict[str, str] | None = None) -> LiveGame:
        mode = load_mode(MODES / name)
        params = mode.resolve_params({}, TEAMS)
        game = LiveGame(lambda: Simulation(self.core, mode, nodes or {name: name}, TEAMS, params))
        self.addCleanup(game.close)
        return game

    def test_the_drawn_screen_follows_the_box_language(self) -> None:
        game = self.live()
        game.act("start", {})
        node = game.snapshot()["nodes"][0]
        self.assertEqual(node["screen"]["args"][0], "standby")
        self.assertEqual(node["drawn"]["template"], "standby")
        english = texts(node["drawn"])
        portuguese = texts(game.snapshot(lang="pt")["nodes"][0]["drawn"])
        self.assertNotEqual(english, portuguese)
        self.assertEqual(texts(game.snapshot(lang="xx")["nodes"][0]["drawn"]), english)
        # The outputs (expansion port, increment 4) are still there beside it.
        self.assertEqual([o["capability"] for o in node["switched"]], ["smoke", "siren"])

    def test_a_screen_without_a_template_is_not_drawn(self) -> None:
        """The Field Box's built-in C screens (code_entry, final_score): the page shows their
        name and data, as before."""
        game = self.live()
        self.assertIsNone(game._drawn({"args": ["code_entry", {"digits": 4}]}, ""))
        self.assertIsNone(game._drawn({"args": []}, ""))
        self.assertIsNone(game._drawn(None, ""))

    def test_a_template_the_core_refuses_says_why(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "m"
            (folder / "assets" / "screens").mkdir(parents=True)
            (folder / "assets" / "screens" / "bad.yaml").write_text("template: bad\nlayout:\n  - type: dial\n")
            game = self.live()
            game.sim.mode.part_paths = (folder,)
            drawn = game._drawn({"args": ["bad", {}]}, "")
            self.assertEqual(drawn["template"], "bad")
            self.assertIn("dial", drawn["error"])


if __name__ == "__main__":
    unittest.main()
