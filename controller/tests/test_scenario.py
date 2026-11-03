# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scenario packages on the controller (decision P4R7), through the real engine and core: the
example scenario (modes/objectives/tests/fixtures/foxhound, kind: scenario) is uploaded, never
built in; a game is the scenario over org.atalaia.objectives; every node's join names only the
objectives package; the scenario's field.lua sets the nodes up with the mode command "setup"
(CMD opcode 8) over the radio, scores, reveals and logs the scenario events, and sets a node up
again after node.rebooted; which objective an event is about stays the staff's (M6-5). A compiled
scenario's triggers (draft RFC "The expansion port", EXP-25) switch the boxes' outputs with CMD 12.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from test_engine import Clock, ev
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.modes import ModeRegistry, parse_package
from atalaia_controller.scenarios import compile_scenario, load
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import join
from atalaia_sim.field_controller import CMD_END, CMD_MODE, CMD_OUTPUT
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
        self.assertEqual(self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True}).status_code, 200)

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
        # The vault's code went to its box only: never in the log or the stream. Only what an entry carries
        # is searched: its received_at once read ...47.11... (about one run in twelve) and failed this test.
        self.assertFalse(any("4711" in repr((e["type"], e["team"], e["data"])) for e in self.ctrl.log(self.gid)))

        # Box 7 reboots: the scenario sets it up again.
        self.modem.sent.clear()
        self.rx(7, 0, "EVENT", ev(7, 0, 40_000, "node.rebooted", reason="power"), epoch=2)
        self.assertEqual([d for d, p in self.setups()], [7])

        # A crash is logged as one: the box's reset reason (panic, watchdog) reaches the log and the
        # API as it said it, never turned into "power" (bench 2026-10-31); the setup goes again.
        for i, reason in enumerate(("panic", "watchdog")):
            self.modem.sent.clear()
            self.rx(7, 0, "EVENT", ev(7, 0, 50_000 + i * 1000, "node.rebooted", reason=reason), epoch=3 + i)
            self.assertEqual([d for d, p in self.setups()], [7])
        reasons = [e["data"]["reason"] for e in self.client.get(f"/api/v1/games/{self.gid}/log", headers=GM).json()
                   if e["type"] == "node.rebooted" and e["node"] == 7]
        self.assertEqual(reasons, ["power", "panic", "watchdog"])

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


SIRENS = """\
id: org.club.sirens
version: 1
name: Sirens
nodes:
  sat_a: { role: objective }
  sat_b: { role: objective }
  master: { role: objective }
objectives:
  - { id: sat_a, name: A, type: capture_and_hold, target: sat_a }
  - { id: sat_b, name: B, type: capture_and_hold, target: sat_b, depends_on: [sat_a], effect: { win: true } }
triggers:
  - when: { game: start }
    output: { node: master, capability: horn, act: "on", seconds: 2 }
  - when: { any_completed: [sat_a, sat_b] }
    output: { node: master, capability: strobe, act: pattern, seconds: 30, on_ms: 500, off_ms: 1500 }
  - when: { completed: [sat_a, sat_b] }
    output: { node: master, capability: siren, act: pulse, seconds: 10 }
  - when: { game: end }
    output: { node: sat_a, capability: horn, act: pulse, seconds: 5 }
"""
SIREN_NAMES = {4: "sat_a", 5: "sat_b", 6: "master"}


@unittest.skipIf(CORE is None, "the shared core library is not built")
class ScenarioTriggerTests(unittest.TestCase):
    """A compiled scenario's triggers (EXP-25) through the engine: CMD 12 with src field, once each;
    an output the controller's 2 s rate limit holds back goes a second later; the outputs of the win
    that ends the game, and of its game: end trigger, go after the end's CMD (in the boxes' grace)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = config(self.tmp.name)
        self.store = Store(self.cfg.db_path)
        self.addCleanup(self.store.close)
        self.modem = FakeModem()
        self.clock = Clock()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=JOIN_KEY, clock=self.clock)
        self.addCleanup(self.ctrl.stop)
        pkg = compile_scenario(load(SIRENS))
        self.ctrl.modes.install({"mode.yaml": pkg.mode_yaml, "field.lua": pkg.field_lua})
        self.gid = self.ctrl.create_game({"name": "Sirens", "mode_id": "org.club.sirens", "modifiers": [OBJECTIVES],
                                          "teams": ["red", "blue"],
                                          "assignments": {str(n): "objective" for n in SIREN_NAMES}})["id"]

    def rx(self, *args, **kw):
        self.modem.rx(*args, game_id=self.gid, **kw)

    def cmds(self) -> list[dict]:
        out = [cmd_decode(p) for _, p in self.modem.of("CMD")]
        return [c for c in out if c["cmd"] in (CMD_OUTPUT, CMD_END)]

    def start(self) -> None:
        for node_id, name in SIREN_NAMES.items():
            self.rx(node_id, 0, "HELLO", hello_encode({"node_name": name, "platform": 1, "fw_version": "0.2.0",
                                                       "core_version": "0.2.0", "tier": 0, "capabilities": [0],
                                                       "transports": 1, "battery_pct": 90, "epoch": 1}), epoch=1)
        self.modem.sent.clear()
        self.ctrl.start_game(self.gid, force=True)

    def test_triggers_switch_outputs(self):
        self.start()
        self.assertEqual(self.cmds(), [{"cmd": CMD_OUTPUT, "dest": 6, "params": {
            "capability": "horn", "act": "on", "ms": 2000, "src": "field"}}])

        # Satellite A: the strobe, held back by the 2 s since the horn, goes on the next tick.
        self.modem.sent.clear()
        self.rx(4, 1, "EVENT", ev(4, 1, 500, "zone.captured", team=RED), epoch=1)
        self.assertEqual(self.cmds(), [])
        self.clock.advance(2.5)
        self.ctrl.tick()
        self.assertEqual(self.cmds(), [{"cmd": CMD_OUTPUT, "dest": 6, "params": {
            "capability": "strobe", "act": "pattern", "ms": 30000, "on_ms": 500, "off_ms": 1500, "src": "field"}}])

        # Satellite B wins the game: the end's CMD first, then the siren and the end's horn.
        self.clock.advance(5)
        self.ctrl.tick()
        self.modem.sent.clear()
        self.rx(5, 1, "EVENT", ev(5, 1, 8000, "zone.captured", team=RED), epoch=1)
        self.assertEqual(self.cmds(), [])  # the script's outputs wait for the end (FieldScript.held_outputs)
        self.ctrl.tick()  # the end a box's event brought about comes on the tick
        got = self.cmds()
        self.assertEqual(got[0]["cmd"], CMD_END)
        self.assertEqual(got[1:], [
            {"cmd": CMD_OUTPUT, "dest": 6, "params": {"capability": "siren", "act": "pulse", "ms": 10000,
                                                      "src": "field"}},
            {"cmd": CMD_OUTPUT, "dest": 4, "params": {"capability": "horn", "act": "pulse", "ms": 5000,
                                                      "src": "field"}},
        ])
        self.assertEqual(self.store.game(self.gid)["state"], "ended")

    def test_a_pause_drops_what_waits_and_the_gm_s_end_sounds_the_horn(self):
        self.start()
        self.rx(4, 1, "EVENT", ev(4, 1, 500, "zone.captured", team=RED), epoch=1)  # the strobe waits
        self.ctrl.pause_game(self.gid)
        self.clock.advance(3)
        self.ctrl.tick()
        self.ctrl.resume_game(self.gid)
        for _ in range(12):
            self.clock.advance(1)
            self.ctrl.tick()
        self.modem.sent.clear()
        self.ctrl.end_game(self.gid)
        got = self.cmds()
        self.assertEqual(got, [got[0], {"cmd": CMD_OUTPUT, "dest": 4, "params": {
            "capability": "horn", "act": "pulse", "ms": 5000, "src": "field"}}])
        self.assertEqual(got[0]["cmd"], CMD_END)


if __name__ == "__main__":
    unittest.main()
