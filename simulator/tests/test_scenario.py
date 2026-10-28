# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Scenario packages (kind: scenario) and the objectives role package (modes/objectives) in the
simulator (decision P4R7): the composition rules against protocol/vectors/composition.yaml,
which the app's Dart runner reads too; the example scenario (modes/objectives/tests/fixtures/
foxhound) over the objectives package; a node's join never names the scenario; a field
script's command too large for a box is a problem; the objectives script fits a Reduced box.

    cd simulator && python -m unittest discover -s tests
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import yaml

from atalaia_sim.core import Core, find_library
from atalaia_sim.mode import Mode, ModeError, check_files, check_manifest, compose, load_mode, split_id
from atalaia_sim.sim import CONTROLLER, Simulation

REPO = Path(__file__).resolve().parents[2]
MODES = REPO / "modes"
FOXHOUND = MODES / "objectives" / "tests" / "fixtures" / "foxhound"
# A compiled scenario (not hand-written) with a chain: `second` depends on `first` and says nothing about its
# visibility (it follows the game's reveal setting, RVL-1); `third` depends on `first` and says `visibility: team`.
CHAIN = MODES / "objectives" / "tests" / "fixtures" / "chain"
VECTORS = yaml.safe_load((REPO / "protocol" / "vectors" / "composition.yaml").read_text(encoding="utf-8"))
TEAMS = ["red", "blue"]
NODES = {"alpha": "objective", "bravo": "objective", "charlie": "objective", "site": "bomb_site"}


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and CORE is None:
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the shared core library is not built")


def vector_package(mode_id: str, spec: dict) -> Mode:
    """A package of the vectors, as load_mode would make it (the scripts name the package)."""
    kind = spec.get("kind", "mode")
    manifest = {"id": mode_id, "version": "1", "kind": kind,
                "roles": {r: {} for r in spec.get("roles", [])},
                "params": {p: {"type": "int", "default": 1} for p in spec.get("params", [])}}
    check_manifest(manifest, mode_id)
    check_files(kind, bool(spec.get("node_lua")), bool(spec.get("field_lua")), mode_id)
    return Mode(path=Path(mode_id), id=mode_id, name=mode_id, version="1", roles=manifest["roles"],
                params=manifest["params"],
                node_script=f"-- node {mode_id}\n" if spec.get("node_lua") else "",
                field_script=f"-- field {mode_id}\n" if spec.get("field_lua") else None, kind=kind)


def compose_id(mode_id: str) -> Mode:
    packages = {k: vector_package(k, v) for k, v in VECTORS["packages"].items()}
    parts = [packages[name] for name in split_id(mode_id)]
    return compose(parts[0], parts[1:])


class CompositionVectorTests(unittest.TestCase):
    def test_valid(self):
        for case in VECTORS["valid"]:
            with self.subTest(case["name"]):
                game = compose_id(case["id"])
                self.assertEqual(game.id, case["id"])
                self.assertEqual(list(game.roles), case["roles"])
                if "main_id" in case:
                    self.assertEqual(game.main_id, case["main_id"])
                params = game.resolve_params({}, TEAMS)
                for role, (node_mode_id, names) in case["joins"].items():
                    self.assertEqual(game.node_mode_id(role), node_mode_id)
                    self.assertEqual(sorted(game.params_for(role, params)), sorted(names))
                    self.assertNotIn("scenario", node_mode_id)
                found = [line.split()[2] for line in (game.field_script or "").splitlines()
                         if line.startswith("-- field ")]
                self.assertEqual(found, case["fields"])

    def test_invalid(self):
        for case in VECTORS["invalid"]:
            with self.subTest(case["name"]):
                with self.assertRaises(ModeError) as cm:
                    compose_id(case["id"])
                self.assertIn(case["error"], str(cm.exception))

    def test_packages_invalid(self):
        for case in VECTORS["packages_invalid"]:
            with self.subTest(case["name"]):
                with self.assertRaises(ModeError) as cm:
                    vector_package("org.t.bad", case["package"])
                self.assertIn(case["error"], str(cm.exception))


class ScenarioPackageTests(unittest.TestCase):
    def setUp(self):
        self.foxhound = load_mode(FOXHOUND)
        self.objectives = load_mode(MODES / "objectives")

    def test_the_example_is_a_scenario(self):
        self.assertEqual((self.foxhound.kind, self.foxhound.roles, self.foxhound.node_script),
                         ("scenario", {}, ""))
        self.assertIn("scenario.started", self.foxhound.field_script)
        self.assertEqual(self.objectives.kind, "role")
        self.assertEqual(list(self.objectives.roles), ["objective", "bomb_site"])
        self.assertEqual(self.objectives.params, {})
        self.assertIsNone(self.objectives.field_script)

    def test_composed(self):
        game = compose(self.foxhound, [self.objectives])
        self.assertEqual(game.id, "org.club.foxhound+org.atalaia.objectives")
        self.assertEqual(game.i18n["pt"]["name"], "Foxhound + Objetivos")
        self.assertEqual(game.field_script, self.foxhound.field_script)
        params = game.resolve_params({}, TEAMS)
        self.assertEqual(params, {"vault_points": 100})
        for role in ("objective", "bomb_site"):
            self.assertEqual(game.node_mode_id(role), "org.atalaia.objectives")
            self.assertEqual(game.node_script_for(role), self.objectives.node_script)
            # The scenario's parameters are its field.lua's: no join carries them.
            self.assertEqual(game.params_for(role, params), {})

    def test_load_refuses_a_scenario_with_a_node_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad"
            path.mkdir()
            (path / "mode.yaml").write_text("id: org.t.bad\nversion: 1\nkind: scenario\n", encoding="utf-8")
            with self.assertRaisesRegex(ModeError, "a scenario needs a field.lua"):
                load_mode(path)
            (path / "field.lua").write_text("-- ok\n", encoding="utf-8")
            self.assertEqual(load_mode(path).kind, "scenario")
            (path / "node.lua").write_text("-- no\n", encoding="utf-8")
            with self.assertRaisesRegex(ModeError, "a scenario has no node.lua"):
                load_mode(path)
            (path / "node.lua").unlink()
            (path / "mode.yaml").write_text("id: org.t.bad\nversion: 1\nkind: scenario\n"
                                            "commands: { go: { roles: [x], label: Go } }\n", encoding="utf-8")
            with self.assertRaisesRegex(ModeError, "a scenario has no commands"):
                load_mode(path)


@unittest.skipIf(CORE is None, "the shared core library is not built")
class ScenarioRunTests(unittest.TestCase):
    def game(self, nodes=None, **overrides) -> Simulation:
        game = compose(load_mode(FOXHOUND), [load_mode(MODES / "objectives")])
        sim = Simulation(CORE, game, nodes or NODES, TEAMS, game.resolve_params(overrides, TEAMS))
        self.addCleanup(sim.close)
        return sim

    def setups(self, sim: Simulation) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for _, node, cmd, params in sim.field_commands:
            if cmd == "mode" and params.get("name") == "setup":
                out.setdefault(node, []).append(params)
        return out

    def test_the_start_sets_up_every_node(self):
        sim = self.game()
        sim.start()
        setups = self.setups(sim)
        self.assertEqual(setups["alpha"], [{"name": "setup", "kind": "capture", "team": "red", "hold_ms": 3000,
                                            "label": "Ponte"}])
        self.assertEqual(setups["charlie"], [{"name": "setup", "kind": "off", "label": "Cofre"}])
        self.assertEqual(setups["site"][0]["kind"], "bomb")
        # The vault's code goes to its node only, never into an event or state.field.
        self.assertFalse(any("4711" in str(e.data) for e in sim.events))
        self.assertEqual(sim.problems, [])

    def test_set_up_once_and_again_after_a_reboot(self):
        sim = self.game({"alpha": "objective"})
        sim.start()
        self.assertEqual(len(self.setups(sim)["alpha"]), 1)
        sim.wait(5)  # every second the scenario sets up only what it has not set up yet
        self.assertEqual(len(self.setups(sim)["alpha"]), 1)
        sim.reboot("alpha")
        self.assertEqual(len(self.setups(sim)["alpha"]), 2)
        self.assertEqual(sim.node("alpha").last_command("ui", "screen").args[0], "obj_capture")
        self.assertEqual([e.type for e in sim.events if e.node == "alpha"],
                         ["node.setup_applied", "node.rebooted", "node.setup_applied"])
        self.assertEqual(sim.problems, [])

    def test_a_box_that_took_its_setup_says_so_and_is_not_sent_it_again(self):
        """PKB-3: the objectives package confirms each setup (node.setup_applied, with its kind), and the
        scenario stops repeating it when it hears that."""
        sim = self.game({"alpha": "objective"})
        sim.start()
        confirmed = [e for e in sim.events if e.node == "alpha" and e.type == "node.setup_applied"]
        self.assertEqual([e.data for e in confirmed], [{"kind": "capture"}])
        sim.wait(600)  # well past every wait of the repeats
        self.assertEqual(len(self.setups(sim)["alpha"]), 1)
        self.assertEqual(sim.problems, [])

    def test_a_lost_setup_is_sent_again_until_the_box_confirms(self):
        sim = self.game({"alpha": "objective"})
        sim.set_reachable("alpha", False)  # the controller's commands to it are lost
        sim.start()
        self.assertEqual(len(self.setups(sim)["alpha"]), 1)
        sim.wait(9)  # the first repeat, 8 s later (the runtime's every-second tick)
        self.assertEqual(len(self.setups(sim)["alpha"]), 2)
        sim.set_reachable("alpha", True)
        sim.wait(20)  # the next repeat, 16 s after that one, reaches it
        self.assertEqual(len(self.setups(sim)["alpha"]), 3)
        self.assertEqual(sim.node("alpha").last_command("ui", "screen").args[0], "obj_capture")
        sim.wait(600)  # and it confirmed: no more
        self.assertEqual(len(self.setups(sim)["alpha"]), 3)
        self.assertEqual(sim.problems, [])

    def test_a_box_that_never_confirms_gets_a_bounded_number_of_repeats(self):
        """An older firmware never says node.setup_applied: five repeats (8, 16, 32, 64 and 128 s), then none."""
        sim = self.game({"alpha": "objective"})
        sim.set_reachable("alpha", False)
        sim.start()
        sim.wait(1000)
        self.assertEqual(len(self.setups(sim)["alpha"]), 1 + 5)
        sim.wait(1000)
        self.assertEqual(len(self.setups(sim)["alpha"]), 1 + 5)

    def test_a_repeat_never_takes_back_what_happened_since(self):
        """The objective moved on while the first setup was lost: the repeats say what is true now."""
        sim = self.game({"alpha": "objective"})
        sim.set_reachable("alpha", False)
        sim.start()
        sim.wait(9)
        sim.set_reachable("alpha", True)
        sim.wait(20)  # the second repeat reaches it
        sim.hold("alpha", "red", 3)  # the bridge is taken: the scenario sets the box up as done
        sim.wait(600)
        kinds = [p["kind"] for p in self.setups(sim)["alpha"]]
        self.assertEqual(kinds[-1], "done")
        self.assertNotIn("capture", kinds[kinds.index("done"):])
        self.assertEqual(sim.problems, [])

    def test_a_reboot_keeps_the_holder(self):
        sim = self.game()
        sim.start()
        sim.hold("alpha", "red", 3)
        sim.reboot("alpha")  # completed: set up as done
        self.assertEqual(self.setups(sim)["alpha"][-1], {"name": "setup", "kind": "done", "team": "red",
                                                         "label": "Ponte"})

    def test_a_command_too_large_for_a_box_is_a_problem(self):
        sim = self.game({"alpha": "objective"})
        sim.start()
        alpha = sim.node("alpha").runtime.node_id
        self.assertFalse(sim._field_send(alpha, "mode", {"name": "setup", "label": "x" * 120}))
        self.assertEqual(len(sim.problems), 1)
        self.assertIn("at most 127 fit in a CMD", sim.problems[0])

    def test_scores_come_from_the_scenario_only(self):
        sim = self.game()
        sim.start()
        sim.hold("alpha", "red", 3)
        self.assertEqual(sim.score("red", CONTROLLER), 50)
        self.assertEqual(sum(sim.score("red", n) for n in NODES), 0)

    def test_the_objectives_script_fits_a_reduced_box(self):
        """A role package runs alone on its node: the objectives script in a Reduced box's 64 KB
        Lua heap (decision M4-8's bound), through a setup of every kind."""
        objectives = load_mode(MODES / "objectives")
        self.assertLess(len(objectives.node_script.encode()), 16 * 1024 - 2048)
        sim = Simulation(CORE, objectives, {"a": "objective"}, TEAMS, {}, mem_limit=64 * 1024)
        self.addCleanup(sim.close)
        # About 40 KB once loaded (before a collection), under the 56 KB bound of M4-8.
        self.assertLess(sim.node("a").runtime.mem_used, 56 * 1024)
        sim.start()
        for setup in ({"kind": "capture"}, {"kind": "code", "code": "12"}, {"kind": "tags", "count": 3},
                      {"kind": "bomb", "fuse_s": 10}, {"kind": "done", "team": "red"}):
            sim.input("a", "cmd.mode", {"name": "setup", **setup})
            sim.hold("a", "red", 4)
            sim.keys("a", "12#")
            sim.wait(12)
        runtime = sim.node("a").runtime
        self.assertEqual(runtime.status, "running", runtime.last_error)
        self.assertEqual([e for e in sim.events if e.type == "script.error"], [])
        self.assertEqual(sim.problems, [])


@unittest.skipIf(CORE is None, "the shared core library is not built")
class ScenarioRevealTests(unittest.TestCase):
    """What the game's ``scenario_reveal`` setting (the controller's, RVL-1) does to the runtime: an
    objective that depends on others and says nothing about its visibility is known at the start
    ("all") or only when it opens ("active"); an explicit visibility always wins."""

    def revealed(self, params: dict, capture_first: bool = False) -> list[str]:
        game = compose(load_mode(CHAIN), [load_mode(MODES / "objectives")])
        sim = Simulation(CORE, game, {"alpha": "objective", "bravo": "objective", "charlie": "objective"},
                         TEAMS, params)
        self.addCleanup(sim.close)
        sim.start()
        if capture_first:
            sim.hold("alpha", "red", 3)
        self.assertEqual(sim.problems, [])
        return [e.data["objective"] for e in sim.events if e.type == "scenario.objective.revealed"]

    def test_all_shows_every_objective_from_the_start(self):
        self.assertEqual(self.revealed({"scenario_reveal": "all"}), ["first", "second", "third"])

    def test_active_reveals_a_followed_objective_only_when_it_opens(self):
        self.assertEqual(self.revealed({"scenario_reveal": "active"}), ["first", "third"])
        self.assertEqual(self.revealed({"scenario_reveal": "active"}, True), ["first", "third", "second"])

    def test_without_the_setting_every_objective_shows(self):
        self.assertEqual(self.revealed({}), ["first", "second", "third"])


if __name__ == "__main__":
    unittest.main()
