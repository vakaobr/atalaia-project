# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The phase 2 mode pack on the controller: the built-in field.lua scripts
(Hold-All Domination, Last Stand) run through the real engine and core, and
modifiers composed with a main mode.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from support import CORE
from test_engine import EngineCase, ev, state
from atalaia_sim.mode import ModeError

HOLDALL = "org.atalaia.holdall"
LASTSTAND = "org.atalaia.laststand"
CODES = "org.atalaia.codes"
RED, BLUE = 1, 2


@unittest.skipIf(CORE is None, "the shared core library is not built")
class ModePackEngineTests(EngineCase):
    def log(self, gid: int, type_: str) -> list[dict]:
        return [e for e in self.ctrl.log(gid) if e["type"] == type_]

    def step(self, seconds: float, ticks: int = 1) -> None:
        for _ in range(ticks):
            self.clock.advance(seconds / ticks)
            self.ctrl.tick()

    def owners(self, *teams: int, epoch: int = 1, seq: int = 0) -> None:
        for node, team in zip((4, 5, 6), teams):
            self.rx(node, seq, "STATE", state(team, {}), epoch=epoch)

    def test_catalogue_lists_kinds_and_translations(self):
        modes = {m["id"]: m for m in (p.to_api() for p in self.ctrl.modes.all())}
        self.assertEqual(modes[CODES]["kind"], "modifier")
        self.assertEqual(modes[HOLDALL]["kind"], "mode")
        self.assertTrue(modes[HOLDALL]["field_script"])
        self.assertTrue(modes[LASTSTAND]["field_script"])
        self.assertFalse(modes["org.atalaia.bomb"]["field_script"])
        self.assertEqual(modes[HOLDALL]["i18n"]["pt"]["name"], "Domínio Total")
        self.assertIn("team_codes", modes["org.atalaia.bomb"]["params"])

    def test_holdall_scores_on_the_controller_and_survives_a_restart(self):
        self.reopen(persist_game_key=True)
        gid = self.create(mode_id=HOLDALL, params={"tick_s": 5, "points_per_tick": 2})["id"]
        self.ctrl.start_game(gid, force=True)
        self.owners(RED, BLUE)
        self.rx(4, 1, "EVENT", ev(4, 1, 100, "zone.captured", team=RED))
        self.step(2, 4)
        self.assertEqual(self.log(gid, "holdall.scoring_start"), [])
        self.owners(RED, RED, seq=2)
        self.step(1)
        [start] = self.log(gid, "holdall.scoring_start")
        self.assertEqual((start["node"], start["team"]), (0, "red"))
        self.step(10, 20)                       # two ticks of the script's 5 s timer
        self.assertEqual(self.ctrl.score(gid)["teams"], {"red": 4, "blue": 0})
        self.assertEqual(self.ctrl.field.score_key, "field-1")

        # A controller restart: the earlier points stay, and field.lua runs again
        # (a second run, whose points add to the first run's).
        self.reopen(persist_game_key=True)
        self.assertEqual(self.ctrl.score(gid)["teams"]["red"], 4)
        self.assertIsNotNone(self.ctrl.field)
        self.assertEqual(self.ctrl.field.score_key, "field-2")
        self.owners(RED, RED, epoch=2)
        self.step(6, 12)
        self.assertEqual(self.ctrl.score(gid)["teams"]["red"], 6)
        self.assertEqual(self.ctrl.end_game(gid)["state"], "ended")
        [end] = self.log(gid, "game.end")
        self.assertEqual(end["data"].get("winner"), "red")

    def test_last_stand_defeat_ends_the_game_with_the_attackers_winning(self):
        gid = self.create(mode_id=LASTSTAND, params={"countdown_s": 10},
                          assignments={"4": "zone", "5": "zone", "6": "zone"})["id"]
        self.ctrl.start_game(gid, force=True)
        self.owners(BLUE, BLUE, BLUE)
        self.step(2, 4)
        self.owners(RED, RED, BLUE, seq=2)
        self.step(1, 2)
        [start] = self.log(gid, "laststand.countdown_start")
        self.assertEqual((start["team"], start["data"]["duration_s"]), ("blue", 10))
        self.step(12, 24)
        [defeat] = self.log(gid, "laststand.defeated")
        self.assertEqual(defeat["team"], "blue")
        [end] = self.log(gid, "game.end")
        self.assertEqual((end["data"]["reason"], end["data"]["winner"]), ("win", "red"))  # red has no points
        self.assertEqual(self.ctrl.get_game(gid)["state"], "ended")
        self.assertIsNone(self.ctrl.field)

    def test_takeover_starts_the_field_script(self):
        gid = self.create(mode_id=HOLDALL)["id"]
        self.ctrl.start_game(gid, force=True)
        self.ctrl.field.close()
        self.ctrl.field = None
        self.ctrl._on_role("leader", 2)
        self.assertEqual(self.ctrl.field.score_key, "field-2")

    def test_modifiers_compose_with_a_main_mode(self):
        game = self.create(modifiers=[CODES], params={"codes": "4711:hint", "tick_s": 5})
        self.assertEqual(game["mode_id"], f"org.atalaia.domination+{CODES}")
        self.assertEqual(game["params"]["codes"], "4711:hint")
        pkg = self.ctrl.modes.get(game["mode_id"])
        self.assertEqual(pkg.to_api()["parts"], ["org.atalaia.domination", CODES])
        self.assertIn("do\n", pkg.mode.node_script)
        self.ctrl.start_game(game["id"], force=True)
        self.rx(4, 1, "EVENT", ev(4, 1, 100, "code.used", team=RED, code="1", kind="hint", holder="red"))
        [used] = self.log(game["id"], "code.used")
        self.assertEqual(used["data"], {"code": "1", "kind": "hint", "holder": "red"})
        self.ctrl.end_game(game["id"])
        with self.assertRaisesRegex(ModeError, "is a modifier"):
            self.create(mode_id=CODES + "+org.atalaia.domination")
        with self.assertRaisesRegex(ModeError, "not a modifier"):
            self.create(modifiers=["org.atalaia.bomb"])


if __name__ == "__main__":
    unittest.main()
