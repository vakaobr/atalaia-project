# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Money Factory (modes/money_factory) beyond its YAML tests: the controller's field.lua keeps
what each player carries and tells the banks (and, with a carrying limit, the factories), an
older or repeated word is ignored, a bank out of reach goes on with what it knows, the banks
are reminded what they are, and the mode's commands fit a CMD (decision A1's blocker,
MF-A1 to MF-A12).

    cd simulator && python -m unittest discover -s tests
"""

from __future__ import annotations

import hashlib
import os
import unittest
from pathlib import Path

from atalaia_sim import tag as player_tag
from atalaia_sim.core import Core, find_library
from atalaia_sim.mode import load_mode
from atalaia_sim.protocol import EVENTS
from atalaia_sim.sim import Simulation

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


class ManifestTests(unittest.TestCase):
    def test_events_and_manifest(self):
        self.assertEqual((EVENTS["money.collected"].id, EVENTS["money.collected"].data), (33, ("player", "amount")))
        self.assertEqual((EVENTS["money.deposited"].id, EVENTS["money.deposited"].data), (34, ("player", "amount")))
        mode = load_mode(MODES / "money_factory")
        self.assertEqual(mode.id, "org.atalaia.money_factory")
        self.assertEqual(mode.kind, "mode")
        self.assertEqual(list(mode.roles), ["factory", "bank"])
        self.assertEqual(mode.i18n["pt"]["name"], "Fábrica de Dinheiro")
        self.assertEqual(set(mode.i18n["pt"]["params"]), set(mode.params))
        self.assertEqual(mode.resolve_params({}, TEAMS), {
            "production": 1, "tick_s": 10, "capacity": 50, "carry_max": 20, "capture": True,
            "capture_hold_ms": 3000, "target": 0, "drop_on_heal": True})


@unittest.skipIf(CORE is None, "the shared core library is not built")
class MoneyFactorySimTests(unittest.TestCase):
    def sim(self, nodes, params=None) -> Simulation:
        mode = load_mode(MODES / "money_factory")
        defaults = {"production": 5, "tick_s": 10, "capture_hold_ms": 1000}
        sim = Simulation(CORE, mode, nodes, TEAMS, mode.resolve_params({**defaults, **(params or {})}, TEAMS))
        self.addCleanup(sim.close)
        sim.start()
        return sim

    def scan(self, sim: Simulation, node: str, player: str, team: str) -> None:
        payload = player_tag.encode({"player": player, "team": TEAMS.index(team) + 1,
                                     "game_id": sim.game_id}, sim.game_key)
        uid = b"\x04" + hashlib.sha256(player.encode()).digest()[:6]
        sim.scan(node, uid, payload)

    def screen(self, sim: Simulation, node: str):
        cmd = sim.node(node).last_command("ui", "screen")
        return cmd.args[0], cmd.args[1]

    def wallets(self, sim: Simulation, since: int = 0):
        return [(c[1], c[3]["player"], c[3]["amount"], c[3]["n"])
                for c in sim.field_commands[since:] if c[2] == "mode" and c[3]["name"] == "wallet"]

    def money(self, sim: Simulation, type_: str):
        return [(e.node, e.data["player"], e.data["amount"]) for e in sim.events if e.type == type_]

    def test_banks_are_told_at_the_start_and_reminded(self):
        sim = self.sim({"plant": "factory", "east": "bank", "west": "bank"})
        told = [(c[0], c[1]) for c in sim.field_commands if c[3]["name"] == "bank"]
        self.assertEqual(told, [(0, "east"), (0, "west")])
        self.assertEqual(self.screen(sim, "east")[0], "bank")
        self.assertEqual(self.screen(sim, "plant")[0], "neutral")
        sim.wait(31)
        told = [(c[0], c[1]) for c in sim.field_commands if c[3]["name"] == "bank"]
        self.assertEqual(told[2:], [(30_000, "east"), (30_000, "west")])
        # Being told again changes nothing on a bank.
        self.assertEqual(self.screen(sim, "east"), ("bank", {"total": 0, "counts": ""}))

    def test_wallets_go_to_banks_and_to_factories_only_with_a_limit(self):
        sim = self.sim({"plant": "factory", "vault": "bank"})
        sim.hold("plant", "red", 1)
        sim.wait(9)
        self.scan(sim, "plant", "r1", "red")
        self.assertEqual(self.wallets(sim), [("vault", "r1", 5, 1), ("plant", "r1", 5, 1)])
        self.scan(sim, "vault", "r1", "red")
        self.assertEqual(self.wallets(sim)[2:], [("vault", "r1", 0, 2), ("plant", "r1", 0, 2)])

        sim = self.sim({"plant": "factory", "vault": "bank"}, {"carry_max": 0})
        sim.hold("plant", "red", 1)
        sim.wait(9)
        self.scan(sim, "plant", "r1", "red")
        self.assertEqual(self.wallets(sim), [("vault", "r1", 5, 1)])
        self.assertEqual(sim.problems, [])

    def test_an_older_or_repeated_word_is_ignored(self):
        sim = self.sim({"plant": "factory", "vault": "bank"})
        vault = sim.node("vault").runtime
        vault.input("cmd.mode", {"name": "wallet", "player": "r1", "amount": 7, "n": 3})
        vault.input("cmd.mode", {"name": "wallet", "player": "r1", "amount": 9, "n": 2})   # older
        self.scan(sim, "vault", "r1", "red")
        self.assertEqual(self.money(sim, "money.deposited"), [("vault", "r1", 7)])
        # The bank's own deposit emptied the wallet; the same word again does not fill it.
        vault.input("cmd.mode", {"name": "wallet", "player": "r1", "amount": 7, "n": 3})
        self.scan(sim, "vault", "r1", "red")
        self.assertEqual(self.screen(sim, "vault")[1]["reason"], "nothing")
        # Malformed words are ignored.
        vault.input("cmd.mode", {"name": "wallet", "amount": 5, "n": 9})
        vault.input("cmd.mode", {"name": "wallet", "player": "r1", "amount": "lots", "n": 9})
        self.scan(sim, "vault", "r1", "red")
        self.assertEqual(self.screen(sim, "vault")[1]["reason"], "nothing")
        self.assertEqual(len(self.money(sim, "money.deposited")), 1)
        self.assertEqual(vault.status, "running", vault.last_error)

    def test_a_bank_out_of_reach_goes_on_with_what_it_knows(self):
        sim = self.sim({"plant": "factory", "east": "bank", "west": "bank"}, {"carry_max": 0})
        sim.hold("plant", "red", 1)
        sim.wait(9)
        self.scan(sim, "plant", "r1", "red")                  # 5, told to both banks
        sim.set_reachable("east", False)
        self.scan(sim, "east", "r1", "red")                   # banked; the controller does not know
        self.assertEqual(self.money(sim, "money.deposited"), [("east", "r1", 5)])
        sim.wait(10)
        self.scan(sim, "plant", "r1", "red")                  # 5 more: the controller counts 10
        before = len(sim.field_commands)
        # West was told 10; east, out of reach, heard nothing and still knows 0.
        self.assertEqual([(w[0], w[2]) for w in self.wallets(sim)][-1:], [("west", 10)])
        self.scan(sim, "east", "r1", "red")
        self.assertEqual(self.screen(sim, "east")[1]["reason"], "nothing")
        # Back in reach, east's deposit arrives: the controller takes it off and tells both banks.
        sim.set_reachable("east", True)
        self.assertEqual([(w[0], w[2]) for w in self.wallets(sim, before)], [("east", 5), ("west", 5)])
        self.scan(sim, "west", "r1", "red")
        self.assertEqual(self.money(sim, "money.deposited"), [("east", "r1", 5), ("west", "r1", 5)])
        self.assertEqual(sim.score("red"), 10)
        self.assertEqual(sim.problems, [])

    def test_the_longest_player_id_fits_a_command(self):
        sim = self.sim({"plant": "factory", "vault": "bank"}, {"production": 1000, "capacity": 10000,
                                                               "carry_max": 10000})
        player = "p" * 32
        sim.hold("plant", "blue", 1)
        sim.wait(99)
        self.scan(sim, "plant", player, "blue")
        self.assertEqual(self.money(sim, "money.collected"), [("plant", player, 10000)])
        self.assertEqual(self.wallets(sim)[0][1:3], (player, 10000))
        self.scan(sim, "vault", player, "blue")
        self.assertEqual(sim.score("blue"), 10000)
        self.assertEqual(sim.problems, [])

    def test_the_bar_fills_while_a_team_holds(self):
        sim = self.sim({"plant": "factory"}, {"capture_hold_ms": 2000})
        sim.input("plant", "team_input.hold", {"team": "blue", "ms": 500})
        self.assertEqual(self.screen(sim, "plant"), ("neutral", {"stock": 0, "taker": "blue", "progress": 0.25}))
        sim.input("plant", "team_input.release", {"team": "blue", "ms": 500})
        self.assertEqual(self.screen(sim, "plant"), ("neutral", {"stock": 0}))
        sim.hold("plant", "red", 2)
        sim.input("plant", "team_input.hold", {"team": "blue", "ms": 1000})
        name, data = self.screen(sim, "plant")
        self.assertEqual((name, data["team"], data["taker"], data["progress"]), ("captured", "red", "blue", 0.5))
        # A result on the screen is not cut short by the bar or the ticks.
        self.scan(sim, "plant", "b1", "blue")
        sim.input("plant", "team_input.hold", {"team": "blue", "ms": 1250})
        self.assertEqual(self.screen(sim, "plant")[0], "refused")
        sim.wait(4)
        self.assertEqual(self.screen(sim, "plant")[1]["progress"], 0.62)


if __name__ == "__main__":
    unittest.main()
