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
from atalaia_sim.screens import check_screen, check_screens, screen_files
from atalaia_sim.sim import Simulation

MODES = Path(__file__).resolve().parents[2] / "modes"
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
        self.assertEqual(found["domination"], ["captured", "final_score", "standby"])
        self.assertEqual(found["kill_confirmed"], ["tags"])
        self.assertEqual(found["respawn"], ["respawn"])
        self.assertEqual(found["player_checkin"], ["checkin"])

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
