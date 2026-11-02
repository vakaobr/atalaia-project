# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Screen templates (ADR-P3-4): every shipped template passes the core's parser, the checks
catch broken ones, and the screens the modes draw have the data their templates read."""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path

from atalaia_sim.core import Core, find_library
from atalaia_sim.mode import load_mode
from atalaia_sim.screens import (LITERALS_MAX, LITERALS_WARN, check_screen, check_screens,
                                 literal_budget, screen_files, screen_warnings)
from atalaia_sim.sim import Simulation

ROOT = Path(__file__).resolve().parents[2]
MODES = ROOT / "modes"
REGISTRY_EXAMPLES = ROOT / "registry" / "examples"
TEAMS = ["red", "blue"]


class ScreenTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core = Core(find_library())

    def test_shipped_templates(self) -> None:
        found = {}
        for mode_dir in sorted(p.parent for p in MODES.glob("*/mode.yaml")):
            files = screen_files(mode_dir)
            found[mode_dir.name] = sorted(p.stem for p in files)
            with self.subTest(mode_dir.name):
                self.assertEqual(check_screens(self.core, mode_dir), [])
        # Plan phase A: Domination and Bomb migrated; the phase 3 modes ship their own.
        self.assertEqual(found["bomb"], ["countdown", "defused", "exploded", "standby"])
        # Its neutral screen was "standby", the Bomb's word, until decision BN-11.
        self.assertEqual(found["domination"], ["captured", "final_score", "neutral"])
        self.assertEqual(found["kill_confirmed"], ["tags"])
        self.assertEqual(found["respawn"], ["respawn"])
        self.assertEqual(found["player_checkin"], ["checkin"])

    def _template(self, tmp: str, name: str, text: str) -> Path:
        path = Path(tmp) / f"{name}.yaml"
        path.write_text(f'template: {path.stem}\nlayout:\n  - type: spacer\n    height: 4\n'
                        f'  - type: label\n    text: "{text}"\n', encoding="utf-8")
        return path

    def test_literals_over_the_limit_are_refused_with_a_clear_message(self) -> None:
        """Decision TPL-1: the evaluator gives one expression's 'text' literals 256 bytes (each
        its length + 1, every branch of && and || counted) and used to render an empty text over
        it. The check says which mode, screen and widget, and how many bytes."""
        def expr(sizes: list[int]) -> str:
            return "{" + " || ".join(f"lang == 'x' && '{'a' * n}'" for n in sizes) + "}"

        with tempfile.TemporaryDirectory() as tmp:
            # Each branch: 'x' takes 2 and the long text n + 1, so 3 * (n + 3) bytes: 255 fit.
            fits = self._template(tmp, "fits", expr([82, 82, 82]))
            self.assertEqual(check_screen(self.core, fits, "demo"), [])
            exact = literal_budget(self.core, fits)[0][2]
            self.assertLessEqual(exact, LITERALS_MAX)
            over = self._template(tmp, "over", expr([100, 100, 100]))
            problems = check_screen(self.core, over, "demo")
            self.assertEqual(len(problems), 1, problems)
            for word in ("demo / over / layout[1] label text", "309 bytes", f"limit is {LITERALS_MAX}"):
                self.assertIn(word, problems[0])
            # Without the Python scan the core refuses it just as well, with its own words.
            self.assertIn("need 309 bytes of 256", self.core.check_screen(over.read_bytes()))
            # The exact edge: 256 bytes fit, 257 do not.
            edge = {n: self._template(tmp, f"edge{n}", "{'" + "a" * (n - 1) + "'}") for n in (256, 257)}
            self.assertEqual(check_screen(self.core, edge[256], "demo"), [])
            self.assertEqual(len(check_screen(self.core, edge[257], "demo")), 1)

    def test_near_the_limit_warns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mode = Path(tmp) / "demo"
            (mode / "assets" / "screens").mkdir(parents=True)
            self._template(str(mode / "assets" / "screens"), "near", "{'" + "a" * (LITERALS_WARN) + "'}")
            self._template(str(mode / "assets" / "screens"), "small", "{'abc'}")
            warnings = screen_warnings(self.core, mode)
            self.assertEqual(len(warnings), 1, warnings)
            self.assertIn("demo / near / layout[1] label text", warnings[0])
            self.assertIn(f"{LITERALS_WARN + 1} of {LITERALS_MAX}", warnings[0])

    def test_every_builtin_mode_and_registry_example_fits_the_literal_limit(self) -> None:
        """No shipped template has an expression over the limit (so none can go blank on a box),
        in the built-in modes or the registry's examples. The report is the biggest of each."""
        folders = sorted(p.parent for root in (MODES, REGISTRY_EXAMPLES) for p in root.glob("*/mode.yaml"))
        self.assertGreater(len(folders), 15)
        screens = 0
        for mode_dir in folders:
            for path in screen_files(mode_dir):
                screens += 1
                with self.subTest(f"{mode_dir.name}/{path.stem}"):
                    self.assertEqual(check_screen(self.core, path, mode_dir.name), [])
                    for where, expr, size in literal_budget(self.core, path):
                        self.assertLessEqual(size, LITERALS_MAX, (where, expr))
        self.assertGreater(screens, 30)

    def test_broken_templates_are_reported(self) -> None:
        cases = {
            "wrong_name.yaml": ("template: other\nlayout:\n  - { type: spacer, height: 1 }\n",
                                "must be 'wrong_name'"),
            "slider.yaml": ("template: slider\nlayout:\n  - type: slider\n", "unknown widget type"),
            "bad_yaml.yaml": ("template: bad_yaml\nlayout: [1]\n", "flow sequences"),
            "bad_expr.yaml": ("template: bad_expr\nlayout:\n  - type: label\n    text: \"{a +}\"\n",
                              "{a +}"),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (source, why) in cases.items():
                path = Path(tmp) / name
                path.write_text(source, encoding="utf-8")
                with self.subTest(name):
                    problems = check_screen(self.core, path)
                    self.assertEqual(len(problems), 1, problems)
                    self.assertIn(why, problems[0])

    def test_expressions_through_the_core(self) -> None:
        data = {"left": 7, "team": "red"}
        params = {"fuse_s": 300}
        self.assertEqual(self.core.screen_text("{left|clock}", data, params), "0:07")
        self.assertEqual(self.core.screen_text("{left / params.fuse_s * 300}", data, params), "7")
        self.assertEqual(self.core.screen_text("Armed by {team|upper}", data, params), "Armed by RED")

    def test_screens_drawn_by_the_modes_have_templates(self) -> None:
        """Every ui.screen() a migrated mode's script calls has a template, or is one of the
        Field Box's built-in screens (code_entry, paused) that stay in C."""
        builtin = {"code_entry", "paused"}
        for name in ("bomb", "domination", "kill_confirmed", "respawn", "player_checkin"):
            mode = load_mode(MODES / name)
            called = set(re.findall(r'ui\.screen\("([a-z_]+)"', mode.node_script))
            have = {p.stem for p in screen_files(MODES / name)}
            with self.subTest(name):
                self.assertTrue(called)
                self.assertEqual(called - have - builtin, set())

    def test_bomb_countdown_reads_its_data(self) -> None:
        """The countdown template's expressions over the data Bomb really sends."""
        mode = load_mode(MODES / "bomb")
        params = mode.resolve_params({"fuse_s": 60}, TEAMS)
        sim = Simulation(self.core, mode, {"bomb": "bomb"}, TEAMS, params)
        self.addCleanup(sim.close)
        sim.start()
        sim.hold("bomb", "red", 5)
        sim.wait(10)
        cmd = sim.node("bomb").last_command("ui", "screen")
        self.assertEqual(cmd.args[0], "countdown")
        self.assertEqual(self.core.screen_text("{left|clock}", cmd.args[1], params), "0:50")
        self.assertEqual(self.core.screen_text("{left / params.fuse_s}", cmd.args[1], params), "0.83")


if __name__ == "__main__":
    unittest.main()
