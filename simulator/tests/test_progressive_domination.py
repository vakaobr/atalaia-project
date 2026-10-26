# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Progressive Domination (modes/progressive_domination) beyond its YAML tests: the manifest and
its events, the order (listed, by box id, shuffled by the game's seed) and what field.lua tells the boxes
(the mode command "pd": its size, reminders, an older word ignored, a word lost and said again;
decisions PD-MODE-1 to PD-MODE-20).

    cd simulator && python -m unittest discover -s tests
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from atalaia_sim.core import Core, find_library
from atalaia_sim.mode import load_mode
from atalaia_sim.protocol import EVENTS
from atalaia_sim.sim import CMD_PARAMS_MAX, Simulation

MODES = Path(__file__).resolve().parents[2] / "modes"
TEAMS = ["red", "blue"]
BOXES = {"alpha": "zone", "bravo": "zone", "charlie": "zone", "delta": "zone", "echo": "zone"}


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and CORE is None:
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the shared core library is not built")


class ManifestTests(unittest.TestCase):
    def test_events_and_manifest(self):
        self.assertEqual((EVENTS["progressive.activated"].id, EVENTS["progressive.activated"].data), (54, ("zone", "step")))
        self.assertEqual((EVENTS["progressive.completed"].id, EVENTS["progressive.completed"].data), (55, ("zone", "step")))
        mode = load_mode(MODES / "progressive_domination")
        self.assertEqual(mode.id, "org.atalaia.progressive_domination")
        self.assertEqual(mode.kind, "mode")
        self.assertEqual(list(mode.roles), ["zone"])
        self.assertEqual(mode.i18n["pt"]["name"], "Domínio Progressivo")
        self.assertEqual(mode.i18n["zh-tw"]["name"], "漸進佔點")
        for lang in ("pt", "de", "zh-tw"):
            self.assertEqual(set(mode.i18n[lang]["params"]), set(mode.params), lang)
        self.assertEqual(mode.resolve_params({}, TEAMS), {
            "capture_hold_ms": 3000, "complete_min": 10, "points_per_min": 6, "complete_bonus": 0,
            "random_order": False, "order": "", "target_score": 0})


@unittest.skipIf(CORE is None, "the shared core library is not built")
class ProgressiveSimTests(unittest.TestCase):
    def sim(self, nodes=None, params=None, teams=None, seed=1) -> Simulation:
        mode = load_mode(MODES / "progressive_domination")
        defaults = {"complete_min": 1, "points_per_min": 2, "capture_hold_ms": 1000}
        teams = teams or TEAMS
        sim = Simulation(CORE, mode, nodes or BOXES, teams,
                         mode.resolve_params({**defaults, **(params or {})}, teams), seed=seed)
        self.addCleanup(sim.close)
        sim.start()
        return sim

    def words(self, sim: Simulation, node=None, since: int = 0):
        return [(c[0], c[1], c[3]) for c in sim.field_commands[since:]
                if c[2] == "mode" and c[3]["name"] == "pd" and (node is None or c[1] == node)]

    def activations(self, sim: Simulation):
        return [e.data["zone"] for e in sim.events if e.type == "progressive.activated"]

    def screen(self, sim: Simulation, node: str):
        cmd = sim.node(node).last_command("ui", "screen")
        return cmd.args[0], cmd.args[1]

    def test_every_box_is_told_at_the_start_and_reminded_with_the_same_word(self):
        sim = self.sim()
        first = self.words(sim)
        self.assertEqual([w[1] for w in first], list(BOXES))
        self.assertEqual([w[2]["phase"] for w in first], ["active", "wait", "wait", "wait", "wait"])
        self.assertTrue(all(w[2]["n"] == 1 and w[2]["of"] == 5 for w in first))
        sim.wait(10.5)
        again = self.words(sim, since=len(sim.field_commands) - 5)
        self.assertEqual([(w[0], w[1]) for w in again], [(10_000, b) for b in BOXES])
        self.assertEqual([w[2] for w in again], [w[2] for w in first])  # said again, not new: same n

    def test_a_word_lost_on_the_radio_reaches_the_box_at_the_next_reminder(self):
        sim = self.sim()
        sim.set_reachable("bravo", False)
        sim.hold("alpha", "red", 1)
        sim.wait(61)                                         # alpha is completed; bravo hears nothing
        self.assertEqual(self.screen(sim, "bravo")[0], "inactive")
        self.assertEqual(self.screen(sim, "bravo")[1], {"done": 0, "of": 5})
        sim.set_reachable("bravo", True)
        sim.hold("bravo", "blue", 1)                         # still deaf to buttons: not told yet
        self.assertEqual([e for e in sim.events if e.type == "zone.captured" and e.node == sim.node("bravo").runtime.node_id], [])
        sim.wait(10)
        self.assertEqual(self.screen(sim, "bravo")[0], "neutral")
        self.assertEqual(self.screen(sim, "bravo")[1]["step"], 2)
        self.assertEqual(sim.problems, [])

    def test_an_older_or_malformed_word_is_ignored(self):
        sim = self.sim()
        box = sim.node("alpha").runtime
        box.input("cmd.mode", {"name": "pd", "n": 1, "phase": "done", "team": "blue", "step": 1, "of": 5, "done": 1})
        self.assertEqual(self.screen(sim, "alpha")[0], "neutral")      # n 1 is not newer than n 1
        box.input("cmd.mode", {"name": "pd", "n": 9, "phase": "bogus"})
        box.input("cmd.mode", {"name": "pd", "phase": "wait"})
        self.assertEqual(self.screen(sim, "alpha")[0], "neutral")
        box.input("cmd.mode", {"name": "other", "n": 9, "phase": "wait"})
        self.assertEqual(self.screen(sim, "alpha")[0], "neutral")
        box.input("cmd.mode", {"name": "pd", "n": 9, "phase": "wait", "step": 1, "of": 5, "done": 0})
        self.assertEqual(self.screen(sim, "alpha")[0], "inactive")
        self.assertEqual(box.status, "running", box.last_error)

    def test_the_longest_team_name_fits_a_command(self):
        team = "t" * 23
        sim = self.sim(params={"order": ""}, teams=[team, "blue"])
        sim.hold("alpha", team, 1)
        sim.wait(61)
        self.assertEqual(sim.problems, [])
        done = [w for w in self.words(sim) if w[2]["phase"] == "done"]
        self.assertEqual(done[0][2]["team"], team)
        biggest = max(len(__import__("json").dumps(w[2], separators=(",", ":"), ensure_ascii=False)) for w in self.words(sim))
        self.assertLessEqual(biggest, CMD_PARAMS_MAX)

    def test_the_order_by_box_id_listed_or_shuffled_by_the_seed(self):
        self.assertEqual(self.activations(self.sim()), ["alpha"])
        listed = self.sim(params={"order": "echo,nobody, charlie ,echo"})
        self.assertEqual(self.activations(listed), ["echo"])
        words = {w[1]: w[2]["step"] for w in self.words(listed)}
        self.assertEqual(words, {"echo": 1, "charlie": 2, "alpha": 3, "bravo": 4, "delta": 5})

        def shuffled(seed):
            sim = self.sim(params={"random_order": True}, seed=seed)
            return {w[1]: w[2]["step"] for w in self.words(sim)}

        orders = [shuffled(seed) for seed in range(1, 8)]
        self.assertEqual(shuffled(3), orders[2])                         # a replay picks the same
        for steps in orders:
            self.assertEqual(sorted(steps.values()), [1, 2, 3, 4, 5])  # a permutation, every box once
        self.assertGreater(len({tuple(sorted(o.items())) for o in orders}), 1)  # and the seed matters
        # The named boxes keep their places in front of the shuffled rest.
        mixed = self.sim(params={"random_order": True, "order": "delta"}, seed=4)
        self.assertEqual(self.activations(mixed), ["delta"])

    def test_a_single_box_game_completes_and_ends(self):
        sim = self.sim({"only": "zone"})
        self.assertEqual(self.activations(sim), ["only"])
        self.assertEqual(self.screen(sim, "only")[1]["final"], True)
        sim.hold("only", "blue", 1)
        sim.wait(61)
        self.assertEqual([e.type for e in sim.events if e.type in ("progressive.completed", "game.end")],
                         ["progressive.completed", "game.end"])
        self.assertEqual(sim.node("only").runtime.status, "ended")
        self.assertEqual(sim.score("blue"), 2)
        self.assertEqual(sim.problems, [])


if __name__ == "__main__":
    unittest.main()
