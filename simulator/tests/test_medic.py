# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Medic Kit (modes/medic) and role packages in the simulator: a role package's
nodes run it alone, joins name what a node runs, kits share a player's limit through
the controller's field.lua, and a kit out of the controller's reach uses its own count.

    cd simulator && python -m unittest discover -s tests
"""

from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

from atalaia_sim import tag as player_tag
from atalaia_sim.core import Core, find_library
from atalaia_sim.mode import ModeError, compose, load_mode
from atalaia_sim.sim import CONTROLLER, Simulation

MODES = Path(__file__).resolve().parents[2] / "modes"
TEAMS = ["red", "blue"]


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and CORE is None:
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the shared core library is not built")


class RolePackageComposeTests(unittest.TestCase):
    def setUp(self):
        self.dom, self.codes, self.medic = (load_mode(MODES / n) for n in ("domination", "codes", "medic"))

    def test_the_medic_kit_is_a_role_package(self):
        self.assertEqual(self.medic.kind, "role")
        self.assertEqual(list(self.medic.roles), ["medic"])
        self.assertEqual(self.medic.commands, {"refill": {"roles": ["medic"], "label": "Refill the kit"}})
        self.assertEqual(self.medic.i18n["pt"]["name"], "Ligaduras")
        self.assertEqual(self.medic.i18n["pt"]["commands"], {"refill": "Repor as ligaduras"})
        self.assertEqual(self.medic.resolve_params({}, TEAMS), {
            "heal_hold_s": 10, "charges": 5, "max_heals_per_player": 2, "cooldown_s": 0, "lang": "pt"})

    def test_each_role_runs_its_own_part(self):
        game = compose(self.dom, [self.codes, self.medic])
        self.assertEqual(game.id, "org.atalaia.domination+org.atalaia.codes+org.atalaia.medic")
        self.assertEqual(list(game.roles), ["zone", "medic"])
        # The zone box runs Domination and Codes; the kit runs the Medic Kit alone.
        self.assertEqual(game.node_mode_id("zone"), "org.atalaia.domination+org.atalaia.codes")
        self.assertEqual(game.node_mode_id("medic"), "org.atalaia.medic")
        self.assertIn("do\n", game.node_script_for("zone"))
        self.assertIn(self.codes.node_script, game.node_script_for("zone"))
        self.assertNotIn(self.medic.node_script, game.node_script_for("zone"))
        self.assertEqual(game.node_script_for("medic"), self.medic.node_script)
        self.assertEqual(game.chunk_name_for("medic"), "@medic/node.lua")
        # Each node gets its part's parameters, as in its join (200 bytes of JSON at most).
        params = game.resolve_params({"codes": "1:hint"}, TEAMS)
        self.assertEqual(set(game.params_for("medic", params)),
                         {"heal_hold_s", "charges", "max_heals_per_player", "cooldown_s", "lang"})
        self.assertEqual(set(game.params_for("zone", params)),
                         {"capture_hold_ms", "tick_s", "points_per_tick", "codes"})
        # The controller runs every part's field.lua; the console offers the kit's refill.
        self.assertEqual(game.field_script, self.medic.field_script)
        self.assertEqual(set(game.commands), {"refill"})
        self.assertEqual(game.i18n["pt"]["name"], "Domínio + Códigos + Ligaduras")
        self.assertEqual(game.i18n["pt"]["commands"], {"refill": "Repor as ligaduras"})

    def test_a_game_without_role_packages_is_unchanged(self):
        both = compose(self.dom, [self.codes])
        self.assertEqual(both.node_mode_id("zone"), both.id)
        self.assertEqual(both.node_script_for("zone"), both.node_script)
        self.assertEqual(both.params_for("zone", {"a": 1}), {"a": 1})

    def test_bad_combinations_are_refused(self):
        with self.assertRaisesRegex(ModeError, "is a role; a game needs a main mode first"):
            compose(self.medic, [self.codes])
        with self.assertRaisesRegex(ModeError, "named twice"):
            compose(self.dom, [self.medic, self.medic])
        clash = load_mode(MODES / "medic")
        clash.id, clash.params = "org.test.zones", {}
        clash.roles, clash.commands = {"zone": {}}, {}
        with self.assertRaisesRegex(ModeError, r"both have the role\(s\) \['zone'\]"):
            compose(self.dom, [clash])
        other = load_mode(MODES / "medic")
        other.id, other.params, other.roles = "org.test.other", {}, {"other": {}}
        with self.assertRaisesRegex(ModeError, r"both have the command\(s\) \['refill'\]"):
            compose(self.dom, [self.medic, other])

    def test_manifest_commands_are_checked(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "node.lua").write_text("local x = 1\n")
            for manifest, message in [
                ("commands: [a]", "commands must map"),
                ("commands: { Refill: { roles: [a], label: x } }", "1-24 of a-z"),
                ("commands: { refill: { roles: [b], label: x } }", "list of the mode's roles"),
                ("commands: { refill: { roles: [a] } }", "needs a label"),
                ("commands: { refill: { roles: [a], label: x, extra: 1 } }", "needs a label"),
                ("i18n: { pt: { commands: { refill: 1 } } }", "maps command names"),
            ]:
                (path / "mode.yaml").write_text(f"id: org.t.m\nversion: 1\nroles: {{ a: {{}} }}\n{manifest}\n")
                with self.subTest(manifest), self.assertRaisesRegex(ModeError, message):
                    load_mode(path)


@unittest.skipIf(CORE is None, "the shared core library is not built")
class MedicKitSimTests(unittest.TestCase):
    def sim(self, nodes, params=None, main=None) -> Simulation:
        medic = load_mode(MODES / "medic")
        mode = compose(load_mode(MODES / main), [medic]) if main else medic
        sim = Simulation(CORE, mode, nodes, TEAMS, mode.resolve_params(params or {}, TEAMS))
        self.addCleanup(sim.close)
        sim.start()
        return sim

    def scan(self, sim: Simulation, node: str, player: str, team: str) -> None:
        payload = player_tag.encode({"player": player, "team": TEAMS.index(team) + 1,
                                     "game_id": sim.game_id}, sim.game_key)
        uid = b"\x04" + hashlib.sha256(player.encode()).digest()[:6]
        sim.scan(node, uid, payload)

    def heal(self, sim: Simulation, node: str, player: str, team: str, s: float = 2) -> None:
        self.scan(sim, node, player, team)
        sim.hold(node, team, s)

    def heals(self, sim: Simulation, node=None):
        return [(e.node, e.data["player"], e.data["player_heals_used"], e.data["remaining"])
                for e in sim.events if e.type == "medic.heal" and (node is None or e.node == node)]

    def screen(self, sim: Simulation, node: str):
        cmd = sim.node(node).last_command("ui", "screen")
        return cmd.args[0], cmd.args[1]

    def test_two_kits_share_the_limit_through_the_controller(self):
        sim = self.sim({"north": "medic", "south": "medic"}, {"heal_hold_s": 2})
        self.heal(sim, "north", "b1", "blue")
        # field.lua told the south kit only (north knew its own heal).
        self.assertEqual([(c[1], c[3]["name"], c[3]["player"], c[3]["used"]) for c in sim.field_commands],
                         [("south", "heals", "b1", 1)])
        sim.wait(5)
        self.heal(sim, "south", "b1", "blue")
        sim.wait(5)
        self.scan(sim, "north", "b1", "blue")
        self.assertEqual(self.screen(sim, "north")[1]["reason"], "limit")
        self.scan(sim, "south", "b1", "blue")
        self.assertEqual(self.screen(sim, "south")[1]["reason"], "limit")
        self.assertEqual(self.heals(sim), [("north", "b1", 1, 4), ("south", "b1", 2, 4)])
        self.assertEqual(sim.problems, [])

    def test_a_kit_out_of_reach_uses_its_own_count(self):
        sim = self.sim({"north": "medic", "south": "medic"}, {"heal_hold_s": 2})
        sim.set_reachable("south", False)
        self.heal(sim, "north", "b1", "blue")      # the controller's word to south is lost
        sim.wait(5)
        # South only knows its own heals: b1 is healed a second time there, and a third.
        self.heal(sim, "south", "b1", "blue")
        sim.wait(5)
        self.assertEqual(self.heals(sim, "south"), [("south", "b1", 1, 4)])
        self.scan(sim, "south", "b1", "blue")       # by its own count, b1 has had 1 of 2
        sim.hold("south", "blue", 2)
        self.assertEqual(self.heals(sim, "south"), [("south", "b1", 1, 4), ("south", "b1", 2, 3)])
        sim.wait(5)
        self.scan(sim, "south", "b1", "blue")       # now its own count is at the limit
        self.assertEqual(self.screen(sim, "south")[1]["reason"], "limit")
        # Nothing of south's has reached the controller, which still counts one heal.
        self.assertEqual([c[1] for c in sim.field_commands], ["south"])
        # Back in reach, south's heals arrive (as resent) and the controller adds them up:
        # three heals for b1 in the game, and both kits are told.
        sim.set_reachable("south", True)
        told = [(c[1], c[3]["used"]) for c in sim.field_commands[1:]]
        self.assertEqual(told, [("north", 2), ("south", 2), ("north", 3), ("south", 3)])
        self.scan(sim, "north", "b1", "blue")
        self.assertEqual(self.screen(sim, "north")[1], {
            "reason": "limit", "message": "Chegaste ao limite de tratamentos", "player": "b1",
            "team": "blue", "used": 3, "max": 2, "remaining": 4})
        self.assertEqual(sim.problems, [])

    def test_a_rebooted_kit_is_told_every_count_again(self):
        sim = self.sim({"north": "medic", "south": "medic"}, {"heal_hold_s": 2})
        self.heal(sim, "north", "b1", "blue")
        sim.wait(1)
        self.heal(sim, "north", "r1", "red")
        before = len(sim.field_commands)
        assert sim.field is not None
        sim.field.input("node.rebooted", {"node": sim.node("south").runtime.node_id, "reason": "power"})
        sim._pump()
        told = sorted((c[1], c[3]["player"], c[3]["used"]) for c in sim.field_commands[before:])
        self.assertEqual(told, [("south", "b1", 1), ("south", "r1", 1)])
        # A reboot of something that is not a kit changes nothing.
        sim.field.input("node.rebooted", {"node": 99})
        self.assertEqual(len(sim.field_commands), before + 2)

    def test_the_kit_runs_alone_next_to_domination(self):
        sim = self.sim({"zone": "zone", "kit": "medic"}, {"heal_hold_s": 2, "capture_hold_ms": 1000},
                       main="domination")
        # The kit's node has only the kit's parameters, as its join gives them.
        self.assertNotIn("tick_s", sim.node("kit").params)
        self.assertNotIn("charges", sim.node("zone").params)
        sim.hold("kit", "red", 2)
        self.assertEqual([e.type for e in sim.events if e.node == "kit"], [])
        self.heal(sim, "kit", "r1", "red")
        sim.hold("zone", "blue", 1)
        types = [(e.node, e.type) for e in sim.events if e.node != CONTROLLER]
        self.assertEqual(types, [("kit", "medic.heal"), ("zone", "zone.captured")])
        self.assertEqual(sim.problems, [])

    def test_mode_commands_must_name_themselves(self):
        sim = self.sim({"kit": "medic"})
        assert sim.field is not None
        ops = sim._field_send
        node_id = sim.node("kit").runtime.node_id
        self.assertFalse(ops(node_id, "mode", {}))
        self.assertFalse(ops(node_id, "mode", {"name": "Refill"}))
        self.assertFalse(ops(node_id, "mode", {"name": "x" * 25}))
        self.assertTrue(ops(node_id, "mode", {"name": "refill"}))
        sim._pump()
        self.assertEqual(self.screen(sim, "kit")[0], "medic_idle")


if __name__ == "__main__":
    unittest.main()
