# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scenario packages on the controller (decision P4R7), through the real engine and core: the
example scenario (modes/objectives/tests/fixtures/foxhound, kind: scenario) is uploaded, never
built in; a game is the scenario over org.atalaia.objectives; every node's join names only the
objectives package; the scenario's field.lua sets the nodes up with the mode command "setup"
(CMD opcode 8) over the radio, scores, reveals and logs the scenario events, and sets a node up
again after node.rebooted; which objective an event is about stays the staff's (M6-5).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from test_engine import ev
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.modes import ModeRegistry, parse_package
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import join
from atalaia_sim.field_controller import CMD_MODE
from atalaia_sim.mode import ModeError
from atalaia_sim.packet import cmd_decode, hello_encode
from atalaia_sim.protocol import MESSAGE_TYPES

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
JOIN_KEY = bytes(range(32))
FOXHOUND_DIR = Path(__file__).resolve().parents[2] / "modes" / "objectives" / "tests" / "fixtures" / "foxhound"
FOXHOUND = "org.club.foxhound"
OBJECTIVES = "org.atalaia.objectives"
RED = 1
NAMES = {4: "alpha", 5: "bravo", 6: "charlie", 7: "site"}


def scenario_files() -> dict[str, str]:
    return {name: (FOXHOUND_DIR / name).read_text(encoding="utf-8") for name in ("mode.yaml", "field.lua")}


class ScenarioPackageTests(unittest.TestCase):
    def test_parse(self):
        pkg = parse_package(scenario_files())
        self.assertEqual((pkg.id, pkg.kind, pkg.mode.roles, pkg.mode.node_script), (FOXHOUND, "scenario", {}, ""))
        api = pkg.to_api()
        self.assertEqual((api["kind"], api["roles"], api["field_script"], api["files"]),
                         ("scenario", {}, True, ["field.lua", "mode.yaml"]))
        for files, why in [
            ({**scenario_files(), "node.lua": "-- no"}, "a scenario has no node.lua"),
            ({"mode.yaml": scenario_files()["mode.yaml"]}, "a scenario needs a field.lua"),
            ({**scenario_files(), "mode.yaml": "id: org.club.x\nversion: 1\nkind: scenario\nroles: { a: {} }\n"},
             "a scenario has no roles"),
            ({"mode.yaml": "id: org.club.x\nversion: 1\nroles: { a: {} }\n", "field.lua": "-- x"},
             "the package has no node.lua"),
        ]:
            with self.subTest(why), self.assertRaisesRegex(ModeError, why):
                parse_package(files)

    def test_a_scenario_is_never_built_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(str(Path(tmp) / "c.db"))
            self.addCleanup(store.close)
            with self.assertRaisesRegex(ModeError, "a scenario is uploaded, not built in"):
                ModeRegistry(store, [str(FOXHOUND_DIR)], CORE)


@unittest.skipIf(CORE is None, "the shared core library is not built")
class ScenarioControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name)
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=JOIN_KEY)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))
        r = self.client.post("/api/v1/modes", headers=GM, json={"files": scenario_files()})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["kind"], r.json()["builtin"]), ("scenario", False))
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "Foxhound", "mode_id": FOXHOUND, "modifiers": [OBJECTIVES], "teams": ["red", "blue"],
            "assignments": {"4": "objective", "5": "objective", "6": "objective", "7": "bomb_site"}})
        self.assertEqual(r.status_code, 201, r.text)
        self.game = r.json()
        self.gid = self.game["id"]

    def tearDown(self):
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def rx(self, *args, **kw):
        kw.setdefault("game_id", self.gid)
        self.modem.rx(*args, **kw)

    def hello(self, node_id: int) -> None:
        self.rx(node_id, 0, "HELLO", hello_encode({"node_name": NAMES[node_id], "platform": 1, "fw_version": "0.2.0",
                                                   "core_version": "0.2.0", "tier": 0, "capabilities": [0],
                                                   "transports": 1, "battery_pct": 90, "epoch": 1}), epoch=1)

    def setups(self) -> list[tuple[int, dict]]:
        out = []
        for header, payload in self.modem.sent:
            if header.type == MESSAGE_TYPES["CMD"]:
                c = cmd_decode(payload)
                if c["cmd"] == CMD_MODE and c["params"].get("name") == "setup":
                    out.append((c.get("dest"), c["params"]))
        return out

    def start(self) -> None:
        for node_id in NAMES:
            self.hello(node_id)
        self.assertEqual(self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM).status_code, 200)

    def test_the_game_and_the_catalogue(self):
        self.assertEqual(self.game["mode_id"], f"{FOXHOUND}+{OBJECTIVES}")
        self.assertEqual(self.game["params"], {"vault_points": 100})
        modes = {m["id"]: m for m in self.client.get("/api/v1/modes", headers=READ).json()}
        self.assertEqual((modes[OBJECTIVES]["kind"], modes[OBJECTIVES]["builtin"]), ("role", True))
        self.assertEqual(list(modes[OBJECTIVES]["roles"]), ["objective", "bomb_site"])
        self.assertEqual(modes[OBJECTIVES]["i18n"]["pt"]["name"], "Objetivos")
        self.assertEqual(modes[FOXHOUND]["kind"], "scenario")
        # A scenario alone, or after another part, is no game.
        self.ctrl.end_game(self.gid)
        for mode_id, why in [(FOXHOUND, "it needs a role package after it"),
                             (f"{OBJECTIVES}+{FOXHOUND}", "a game needs a main mode first"),
                             (f"org.atalaia.domination+{FOXHOUND}+{OBJECTIVES}", "a scenario leads")]:
            with self.subTest(mode_id), self.assertRaisesRegex(ModeError, why):
                self.ctrl.create_game({"name": "x", "mode_id": mode_id})

    def test_joins_name_the_objectives_package_only(self):
        def joined(**spec):
            r = self.client.post("/api/v1/join", headers=GM, json=spec)
            self.assertEqual(r.status_code, 200, r.text)
            return join.decode(bytes.fromhex(r.json()["payload_hex"]), JOIN_KEY)

        for role in ("objective", "bomb_site"):
            j = joined(role=role)
            # What the box runs: the objectives package, with none of the scenario's parameters.
            self.assertEqual((j["mode_id"], j["role"], j.get("params") or {}), (OBJECTIVES, role, {}))
        standby = joined(kind="controller")  # a standby controller takes the whole game
        self.assertEqual((standby["mode_id"], standby["params"]), (f"{FOXHOUND}+{OBJECTIVES}", {"vault_points": 100}))

    def test_the_scenario_sets_up_the_nodes_and_plays(self):
        self.start()
        setups = dict(self.setups())
        self.assertEqual(setups[4], {"name": "setup", "kind": "capture", "team": "red", "hold_ms": 3000,
                                     "label": "Ponte"})
        self.assertEqual(setups[6], {"name": "setup", "kind": "off", "label": "Cofre"})
        self.assertEqual((setups[5]["kind"], setups[7]["kind"]), ("tags", "bomb"))
        log = self.ctrl.log(self.gid)
        controller = [(e["type"], e["team"], e["data"]) for e in log if e["node"] == self.cfg.node_id
                      and e["type"].startswith("scenario.")]
        self.assertEqual(controller[:2], [("scenario.started", None, {"scenario": FOXHOUND}),
                                          ("scenario.objective.revealed", "red",
                                           {"objective": "bridge", "team": "red"})])
        self.assertEqual(len(controller), 4)  # bridge, intel and site_a are revealed; the vault is hidden

        # Red captures the bridge (box 4): completed, 50 points, the vault set up for red.
        self.modem.sent.clear()
        self.rx(4, 1, "EVENT", ev(4, 1, 30_000, "zone.captured", team=RED), epoch=1)
        log = self.ctrl.log(self.gid)
        done = [e for e in log if e["type"] == "scenario.objective.completed"]
        self.assertEqual([(e["team"], e["data"]["objective"]) for e in done], [("red", "bridge")])
        self.assertEqual(self.ctrl.score(self.gid)["teams"]["red"], 50)
        setups = dict(self.setups())
        self.assertEqual(setups[4], {"name": "setup", "kind": "done", "team": "red", "label": "Ponte"})
        self.assertEqual(setups[6], {"name": "setup", "kind": "code", "code": "4711", "team": "red",
                                     "label": "Cofre"})
        # The vault's code went to its box only: never in the log or the stream.
        self.assertFalse(any("4711" in str(e) for e in self.ctrl.log(self.gid)))

        # Box 7 reboots: the scenario sets it up again.
        self.modem.sent.clear()
        self.rx(7, 0, "EVENT", ev(7, 0, 40_000, "node.rebooted", reason="power"), epoch=2)
        self.assertEqual([d for d, p in self.setups()], [7])

    def test_which_objective_is_for_staff_only(self):
        self.start()
        self.rx(4, 1, "EVENT", ev(4, 1, 30_000, "zone.captured", team=RED), epoch=1)
        gm = [e for e in self.client.get(f"/api/v1/games/{self.gid}/log", headers=GM).json()
              if e["type"] == "scenario.objective.completed"]
        self.assertEqual(gm[0]["data"], {"objective": "bridge", "team": "red"})
        # The read token's scoreboards (and players, and MQTT) learn that red completed an
        # objective, not which one, until the player view routes them per team (P4R24).
        public = [e for e in self.client.get(f"/api/v1/games/{self.gid}/log", headers=READ).json()
                  if e["type"].startswith("scenario.")]
        self.assertEqual([e["data"] for e in public if e["type"] == "scenario.started"], [{"scenario": FOXHOUND}])
        self.assertTrue(all("objective" not in e["data"] for e in public if e["type"] != "scenario.started"))
        self.assertIn({"team": "red"}, [e["data"] for e in public if e["type"] == "scenario.objective.completed"])


if __name__ == "__main__":
    unittest.main()
