# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Progressive Domination (modes/progressive_domination) on the controller, through the real
engine and core: field.lua activates the first box at the start and tells every box its phase (the
mode command "pd"), follows the active box's own zone.captured and zone.neutralized, pays each full
minute of a hold, completes the box and announces the next one in the log, and the state it
publishes names the active box (decisions PD-MODE-1 to PD-MODE-20).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from test_engine import EngineCase, ev
from atalaia_sim.field_controller import CMD_MODE
from atalaia_sim.packet import cmd_decode, hello_encode
from atalaia_sim.protocol import MESSAGE_TYPES
from support import CORE

PD = "org.atalaia.progressive_domination"
RED, BLUE = 1, 2
ALPHA, BRAVO, CHARLIE = 4, 5, 6


def hello(name: str) -> bytes:
    return hello_encode({"node_name": name, "platform": 1, "fw_version": "0.2.0", "core_version": "0.2.0",
                         "tier": 0, "capabilities": [0, 3], "transports": 1, "battery_pct": 90, "epoch": 1})


@unittest.skipIf(CORE is None, "the shared core library is not built")
class ProgressiveControllerTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.gid = self.create(mode_id=PD, assignments={str(ALPHA): "zone", str(BRAVO): "zone", str(CHARLIE): "zone"},
                               params={"complete_min": 1, "points_per_min": 3})["id"]
        for node, name in ((ALPHA, "Church"), (BRAVO, "Bridge"), (CHARLIE, "Mill")):
            self.rx(node, 0, "HELLO", hello(name))

    def pd_words(self):
        out = []
        for header, payload in self.modem.sent:
            if header.type == MESSAGE_TYPES["CMD"]:
                c = cmd_decode(payload)
                if c["cmd"] == CMD_MODE and (c.get("params") or {}).get("name") == "pd":
                    out.append((c["dest"], c["params"]))
        return out

    def logged(self, type_):
        return [(e["node"], e["team"], e["data"]) for e in self.ctrl.log(self.gid) if e["type"] == type_]

    def test_the_first_box_is_announced_and_every_box_told(self):
        self.ctrl.start_game(self.gid, force=True)
        self.assertEqual(self.logged("progressive.activated"), [(0, None, {"zone": "Church", "step": 1})])
        words = {dest: p for dest, p in self.pd_words()}
        self.assertEqual({d: p["phase"] for d, p in words.items()}, {ALPHA: "active", BRAVO: "wait", CHARLIE: "wait"})
        self.assertTrue(all(p["of"] == 3 and p["n"] == 1 for p in words.values()))
        state = [m for m in self.messages if m["type"] == "field_state" and m["key"] == "active"]
        self.assertEqual(state[-1]["value"], "Church")

    def test_a_held_box_pays_each_minute_completes_and_the_next_is_announced(self):
        self.ctrl.start_game(self.gid, force=True)
        self.modem.sent.clear()
        self.clock.advance(5)
        self.ctrl.tick()
        self.rx(BRAVO, 1, "EVENT", ev(BRAVO, 1, 5_000, "zone.captured", team=BLUE))   # not the active box
        self.rx(ALPHA, 1, "EVENT", ev(ALPHA, 1, 5_000, "zone.captured", team=RED))
        self.clock.advance(59)
        self.ctrl.tick()
        self.assertEqual(self.ctrl.score(self.gid)["teams"], {"red": 0, "blue": 0})
        self.clock.advance(1)
        self.ctrl.tick()
        self.assertEqual(self.ctrl.score(self.gid)["teams"], {"red": 3, "blue": 0})
        self.assertEqual(self.logged("progressive.completed"), [(0, "red", {"zone": "Church", "step": 1, "team": "red"})])
        self.assertEqual([d["zone"] for _, _, d in self.logged("progressive.activated")], ["Church", "Bridge"])
        done = {dest: p for dest, p in self.pd_words()}
        self.assertEqual({d: p["phase"] for d, p in done.items()}, {ALPHA: "done", BRAVO: "active", CHARLIE: "wait"})
        self.assertEqual((done[ALPHA]["team"], done[ALPHA]["done"], done[BRAVO]["n"]), ("red", 1, 2))

    def test_the_last_box_ends_the_game_with_a_winner(self):
        self.ctrl.start_game(self.gid, force=True)
        for i, node in enumerate((ALPHA, BRAVO, CHARLIE)):
            self.clock.advance(1)
            self.ctrl.tick()
            self.rx(node, 1, "EVENT", ev(node, 1, 1_000 + i, "zone.captured", team=RED))
            self.clock.advance(60)
            self.ctrl.tick()
        self.assertEqual(self.logged("progressive.completed")[-1][2], {"zone": "Mill", "step": 3, "team": "red"})
        self.assertEqual(self.store.game(self.gid)["state"], "ended")
        end = [e for e in self.ctrl.log(self.gid) if e["type"] == "game.end"]
        self.assertEqual(end[-1]["data"].get("winner"), "red")


if __name__ == "__main__":
    unittest.main()
