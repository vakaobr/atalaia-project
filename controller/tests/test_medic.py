# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Medic Kit (modes/medic, a role package) on the controller, through the real
engine and core: a kit's join names the kit alone, the medic field.lua tells the other
kits a player's heals (CMD opcode 8, "heals"), and the GM refills a kit through the API.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import tempfile
import unittest

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from test_engine import ev
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller, ControllerError
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import join
from atalaia_sim.field_controller import CMD_MODE
from atalaia_sim.mode import ModeError
from atalaia_sim.packet import cmd_decode
from atalaia_sim.protocol import MESSAGE_TYPES

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
DOMINATION = "org.atalaia.domination"
MEDIC = "org.atalaia.medic"
JOIN_KEY = bytes(range(32))
BLUE = 2


@unittest.skipIf(CORE is None, "the shared core library is not built")
class MedicKitControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name)
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=JOIN_KEY)
        self.messages: list[dict] = []
        self.ctrl.add_listener(self.messages.append)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "Sunday", "mode_id": DOMINATION, "modifiers": [MEDIC], "teams": ["red", "blue"],
            "assignments": {"4": "zone", "5": "medic", "6": "medic"},
            "params": {"tick_s": 5, "max_heals_per_player": 2, "team": "blue"}})
        self.assertEqual(r.status_code, 201, r.text)
        self.game = r.json()

    def tearDown(self):
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def rx(self, *args, **kw):
        kw.setdefault("game_id", self.game["id"])
        self.modem.rx(*args, **kw)

    def mode_cmds(self) -> list[tuple[int, dict]]:
        out = []
        for header, payload in self.modem.sent:
            if header.type == MESSAGE_TYPES["CMD"]:
                c = cmd_decode(payload)
                if c["cmd"] == CMD_MODE:
                    out.append((c.get("dest"), c.get("params")))
        return out

    def test_the_game_and_the_catalogue(self):
        self.assertEqual(self.game["mode_id"], f"{DOMINATION}+{MEDIC}")
        self.assertEqual(self.game["params"]["charges"], 5)
        modes = {m["id"]: m for m in self.client.get("/api/v1/modes", headers=READ).json()}
        self.assertEqual(modes[MEDIC]["kind"], "role")
        self.assertEqual(modes[MEDIC]["commands"], {"refill": {"roles": ["medic"], "label": "Refill the kit"}})
        self.assertEqual(modes[MEDIC]["i18n"]["pt"]["name"], "Ligaduras")
        # A role package cannot lead a game with other parts.
        self.ctrl.end_game(self.game["id"])
        with self.assertRaisesRegex(ModeError, "is a role; a game needs a main mode first"):
            self.ctrl.create_game({"name": "x", "mode_id": f"{MEDIC}+org.atalaia.codes"})
        alone = self.ctrl.create_game({"name": "kits", "mode_id": MEDIC, "assignments": {"7": "medic"}})
        self.assertEqual(alone["mode_id"], MEDIC)

    def test_a_kit_is_joined_with_the_kit_alone(self):
        def joined(**spec):
            r = self.client.post("/api/v1/join", headers=GM, json=spec)
            self.assertEqual(r.status_code, 200, r.text)
            return join.decode(bytes.fromhex(r.json()["payload_hex"]), JOIN_KEY)

        kit = joined(role="medic")
        self.assertEqual((kit["mode_id"], kit["role"]), (MEDIC, "medic"))
        self.assertEqual(kit["params"], {"heal_hold_s": 10, "charges": 5, "max_heals_per_player": 2,
                                         "cooldown_s": 0, "team": "blue", "lang": "pt"})
        zone = joined(role="zone")
        self.assertEqual((zone["mode_id"], zone["params"]),
                         (DOMINATION, {"capture_hold_ms": 3000, "tick_s": 5, "points_per_tick": 1}))
        standby = joined(kind="controller")
        self.assertEqual(standby["mode_id"], f"{DOMINATION}+{MEDIC}")
        self.assertEqual(standby["params"], self.game["params"])

    def test_kits_share_the_count_and_the_gm_refills(self):
        gid = self.game["id"]
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).status_code, 200)
        # Kit 5 heals b1: field.lua tells kit 6 (kit 5 knows its own heal).
        self.rx(5, 1, "EVENT", ev(5, 1, 30_000, "medic.heal", team=BLUE, player="b1", remaining=4,
                                  player_heals_used=1))
        heals = [e for e in self.ctrl.log(gid) if e["type"] == "medic.heal"]
        self.assertEqual([(e["node"], e["team"], e["data"]) for e in heals],
                         [(5, "blue", {"player": "b1", "remaining": 4, "player_heals_used": 1})])
        self.assertTrue(any(m["type"] == "event" and m["event"]["type"] == "medic.heal" for m in self.messages))
        [(dest, params)] = self.mode_cmds()
        self.assertEqual(dest, 6)
        self.assertEqual({k: params[k] for k in ("name", "player", "used")}, {"name": "heals", "player": "b1",
                                                                          "used": 1})
        self.assertIsInstance(params["at"], int)
        # Kit 6 was out of reach and healed b1 by its own count (1): the controller now counts
        # two heals and tells both kits.
        self.modem.sent.clear()
        self.rx(6, 1, "EVENT", ev(6, 1, 40_000, "medic.heal", team=BLUE, player="b1", remaining=4,
                                  player_heals_used=1))
        self.assertEqual([(d, p["used"]) for d, p in self.mode_cmds()], [(5, 2), (6, 2)])
        # The GM refills kit 6 from the console: a mode command for the medic role only.
        self.modem.sent.clear()
        r = self.client.post("/api/v1/nodes/6/cmd", headers=GM, json={"cmd": "mode", "params": {"name": "refill"}})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual((r.json()["cmd"], r.json()["opcode"]), ("mode", 8))
        self.assertEqual(self.mode_cmds(), [(6, {"name": "refill"})])
        for node, params, why in [
            (4, {"name": "refill"}, "for medic nodes; node 4 is a zone"),
            (6, {"name": "reboot"}, r"one of the game's mode commands \(refill\)"),
            (6, {}, "one of the game's mode commands"),
        ]:
            with self.subTest(params), self.assertRaisesRegex(ControllerError, why):
                self.ctrl.send_node_cmd(node, "mode", params)
        self.assertEqual(self.client.post("/api/v1/nodes/6/cmd", headers=READ,
                                          json={"cmd": "mode", "params": {"name": "refill"}}).status_code, 403)
        # medic.empty is logged like any event.
        self.rx(5, 2, "EVENT", ev(5, 2, 50_000, "medic.empty", team=BLUE))
        self.assertEqual([e["team"] for e in self.ctrl.log(gid) if e["type"] == "medic.empty"], ["blue"])


@unittest.skipIf(CORE is None, "the shared core library is not built")
class ModeCommandsWithoutDeclarationsTests(unittest.TestCase):
    def test_a_game_without_mode_commands_refuses_them(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = config(tmp.name)
        store = Store(cfg.db_path)
        ctrl = Controller(cfg, store, modem=FakeModem(), core=CORE)
        self.addCleanup(store.close)
        self.addCleanup(ctrl.stop)
        ctrl.create_game({"name": "x", "mode_id": DOMINATION, "assignments": {"4": "zone"}})
        with self.assertRaisesRegex(ControllerError, "none in this game"):
            ctrl.send_node_cmd(4, "mode", {"name": "refill"})


if __name__ == "__main__":
    unittest.main()
