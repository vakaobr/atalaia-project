# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Money Factory (modes/money_factory) on the controller, through the real engine and core: the
mode's field.lua tells the bank boxes what they are and every player's money (CMD opcode 8,
"bank" and "wallet"), takes a deposit off the wallet, keeps the money each team banked in the
field state, and ends the game when a team banks the target (decision A1's blocker, MF-A1 on).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import tempfile
import unittest

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from test_engine import ev
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import join
from atalaia_sim.field_controller import CMD_MODE
from atalaia_sim.packet import cmd_decode
from atalaia_sim.protocol import MESSAGE_TYPES

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
MONEY = "org.atalaia.money_factory"
JOIN_KEY = bytes(range(32))
RED = 1
FACTORY, EAST, WEST = 4, 5, 6


@unittest.skipIf(CORE is None, "the shared core library is not built")
class MoneyFactoryControllerTests(unittest.TestCase):
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
            "name": "Sunday", "mode_id": MONEY, "teams": ["red", "blue"],
            "assignments": {str(FACTORY): "factory", str(EAST): "bank", str(WEST): "bank"},
            "params": {"target": 20}})
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

    def test_the_catalogue_and_the_joins(self):
        modes = {m["id"]: m for m in self.client.get("/api/v1/modes", headers=READ).json()}
        self.assertEqual(list(modes[MONEY]["roles"]), ["factory", "bank"])
        self.assertEqual(modes[MONEY]["i18n"]["pt"]["name"], "Fábrica de Dinheiro")
        for role in ("factory", "bank"):
            r = self.client.post("/api/v1/join", headers=GM, json={"role": role})
            self.assertEqual(r.status_code, 200, r.text)
            j = join.decode(bytes.fromhex(r.json()["payload_hex"]), JOIN_KEY)
            # Both roles run the one script with the game's parameters; field.lua tells the banks.
            self.assertEqual((j["mode_id"], j["role"], j["params"]["target"]), (MONEY, role, 20))

    def test_wallets_deposits_and_the_target(self):
        gid = self.game["id"]
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True}).status_code, 200)
        # The start tells both banks what they are; the factory is told nothing.
        self.assertEqual(sorted(d for d, p in self.mode_cmds() if p == {"name": "bank"}), [EAST, WEST])
        self.modem.sent.clear()
        # r1 collects 12 at the factory: both banks, and the factory (carrying has a limit), are told.
        self.rx(FACTORY, 1, "EVENT", ev(FACTORY, 1, 30_000, "money.collected", team=RED, player="r1", amount=12))
        told = [(d, p["player"], p["amount"], p["n"]) for d, p in self.mode_cmds() if p["name"] == "wallet"]
        self.assertEqual(sorted(told), [(FACTORY, "r1", 12, 1), (EAST, "r1", 12, 1), (WEST, "r1", 12, 1)])
        # r1 banks 12 at the east bank: the wallet is empty again, everywhere.
        self.modem.sent.clear()
        self.rx(EAST, 1, "EVENT", ev(EAST, 1, 60_000, "money.deposited", team=RED, player="r1", amount=12))
        told = [(d, p["amount"], p["n"]) for d, p in self.mode_cmds() if p["name"] == "wallet"]
        self.assertEqual(sorted(told), [(FACTORY, 0, 2), (EAST, 0, 2), (WEST, 0, 2)])
        self.assertTrue(any(m["type"] == "field_state" and m["key"] == "banked" and m["value"] == {"red": 12}
                            for m in self.messages), self.messages)
        logged = [(e["node"], e["team"], e["data"]) for e in self.ctrl.log(gid) if e["type"].startswith("money.")]
        self.assertEqual(logged, [(FACTORY, "red", {"player": "r1", "amount": 12}),
                                  (EAST, "red", {"player": "r1", "amount": 12})])
        self.assertEqual(self.client.get(f"/api/v1/games/{gid}", headers=GM).json()["state"], "running")
        # Another 10 banked at the west bank: 22 of the target's 20, and red wins.
        self.rx(FACTORY, 2, "EVENT", ev(FACTORY, 2, 70_000, "money.collected", team=RED, player="r2", amount=10))
        self.rx(WEST, 1, "EVENT", ev(WEST, 1, 90_000, "money.deposited", team=RED, player="r2", amount=10))
        # field.lua's end asked for in the radio receive path waits for the controller's tick.
        self.assertEqual(self.client.get(f"/api/v1/games/{gid}", headers=GM).json()["state"], "running")
        self.ctrl.tick()
        self.assertEqual(self.client.get(f"/api/v1/games/{gid}", headers=GM).json()["state"], "ended")
        end = [e for e in self.ctrl.log(gid) if e["type"] == "game.end"]
        self.assertEqual(end[-1]["data"].get("winner"), "red")


if __name__ == "__main__":
    unittest.main()
