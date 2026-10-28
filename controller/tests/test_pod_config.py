# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The I/O pod's settings over the radio (protocol/pod-config.md, decision PODC).

The shared vectors (protocol/vectors/pod_config.json, which the pod's C and the Android controller
check too) against this controller's validation and the reference model; then the service and API
in-process over the real engine with a fake modem: the push as CMD pod (opcode 10) to the phone's
node id, the pod's answer as node.setup_applied, the resends, the end of the tries, and what is
refused (a game being played, a node that is not a phone, a bad body, the read token).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from atalaia_controller import pod_config as pc
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.pod_config import PodConfig, PodSettingsModel, check_params
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import codec
from atalaia_sim.packet import cmd_decode, cmd_encode, hello_encode

REPO = Path(__file__).resolve().parents[2]
VECTORS = json.loads((REPO / "protocol" / "vectors" / "pod_config.json").read_text(encoding="utf-8"))
GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
DOMINATION = "org.atalaia.domination"


class VectorTests(unittest.TestCase):
    def test_steps(self) -> None:
        model = PodSettingsModel()
        self.assertGreaterEqual(len(VECTORS["steps"]), 15)
        for step in VECTORS["steps"]:
            with self.subTest(step["name"]):
                self.assertEqual(model.handle(step["params"]), step["result"])
                self.assertEqual(model.stored(), step["stored"])
                self.assertEqual(cmd_encode({"cmd": VECTORS["opcode"], "params": step["params"],
                                             "dest": VECTORS["dest"]}).hex(), step["cmd_cbor"])
                self.assertEqual(cmd_decode(bytes.fromhex(step["cmd_cbor"]))["params"], step["params"])
                # The controller refuses what the pod would refuse, and sends only what it takes.
                if step["result"] == "refused":
                    with self.assertRaises(pc.ControllerError):
                        check_params(step["params"])
                else:
                    check_params(step["params"])

    def test_the_longest_fits_a_cmd(self) -> None:
        longest = VECTORS["steps"][-1]["params"]
        self.assertLessEqual(len(json.dumps(longest, separators=(",", ":"))), pc.CMD_PARAMS_MAX)

    def test_body_to_params(self) -> None:
        self.assertEqual(pc.params_from_body({"bright": 5}, 77), {"v": 1, "rev": 77, "bright": 5})
        self.assertEqual(pc.params_from_body({"bright": 5, "rev": 9}, 77)["rev"], 9)
        for bad in ({}, {"rev": 3}, {"led": 3}, {"bright": 101}, {"btn": ["red"]}, [], {"btn": ["red", "x", "", ""]},
                    {"tamper": "yes"}, {"vol": True}):
            with self.subTest(bad=bad), self.assertRaises(pc.ControllerError):
                pc.params_from_body(bad, 77)


class Clock:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


class PodConfigCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        cfg = config(self.tmp.name)
        self.store = Store(cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(cfg, self.store, modem=self.modem, core=CORE)
        self.clock = Clock()
        self.pc = PodConfig(self.ctrl, clock=self.clock)
        self.messages: list[dict] = []
        self.ctrl.add_listener(self.messages.append)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(cfg.gm_token, cfg.read_token)))

    def tearDown(self) -> None:
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def new_game(self) -> dict:
        r = self.client.post("/api/v1/games", json={"name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"],
                                                     "assignments": {"4": "zone", "5": "zone", "6": "zone"}},
                             headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def hello(self, game: dict, node: int, platform: int, seq: int = 0) -> None:
        self.modem.rx(node, seq, "HELLO", hello_encode({
            "node_name": f"n-{node}", "platform": platform, "fw_version": "0.3.0", "core_version": "0.3.0",
            "tier": 0, "capabilities": [0], "transports": 1, "battery_pct": 80, "epoch": 1}),
            game_id=game["id"], epoch=1)

    def pod_cmds(self) -> list[dict]:
        return [d for d in (cmd_decode(p) for _, p in self.modem.of("CMD")) if d["cmd"] == 10]

    def applied_event(self, game: dict, node: int, rev: int, seq: int, kind: str = "pod_config") -> None:
        """node.setup_applied, as the phone sends it when its pod says it took the settings."""
        self.modem.rx(node, seq, "EVENT", codec.encode_event({
            "node": node, "seq": seq, "t": 0, "type": "node.setup_applied",
            "data": {"kind": kind, "rev": rev}}), game_id=game["id"], epoch=1, ack=True)

    def push(self, node: int, body: dict):
        return self.client.post(f"/api/v1/pod-config/{node}", json=body, headers=GM)


class PushTests(PodConfigCase):
    def test_the_whole_way(self) -> None:
        game = self.new_game()
        self.hello(game, 4, 3)  # a phone
        self.hello(game, 5, 1)  # a box
        status = self.client.get("/api/v1/pod-config", headers=GM).json()
        self.assertEqual([n["node_id"] for n in status["nodes"]], [4])
        self.assertEqual((status["colours"], status["buttons"], status["pushes"]), (list(pc.COLOURS), 4, []))
        r = self.push(4, {"btn": ["red", "", "", "blue"], "bright": 60})
        self.assertEqual(r.status_code, 200, r.text)
        push = r.json()
        self.assertEqual((push["node_id"], push["state"], push["tries"]), (4, "sent", 1))
        self.assertEqual(push["rev"], 1_000_000)  # seconds since 1970: a pod keeps the last rev in its flash
        # CMD pod (opcode 10) to the phone's node id alone, with the version, the rev and the settings.
        self.assertEqual(self.pod_cmds(), [{"cmd": 10, "dest": 4, "params": {
            "v": 1, "rev": 1_000_000, "btn": ["red", "", "", "blue"], "bright": 60}}])
        # The pod took it: the phone says so over the radio, the controller shows it.
        self.applied_event(game, 4, 1_000_000, seq=1)
        self.assertEqual(self.client.get("/api/v1/pod-config", headers=GM).json()["pushes"][0]["state"], "applied")
        self.assertTrue(any(m.get("type") == "pod_config" for m in self.messages))
        # The next push goes above the last rev even in the same second.
        r = self.push(4, {"vol": 30})
        self.assertEqual(r.json()["rev"], 1_000_001)
        # An answer for another rev, another kind or another node changes nothing.
        self.applied_event(game, 4, 5, seq=2)
        self.applied_event(game, 4, 1_000_001, seq=3, kind="mode")
        self.assertEqual(self.pc.pushes[4]["state"], "sent")
        self.applied_event(game, 4, 1_000_001, seq=4)
        self.assertEqual(self.pc.pushes[4]["state"], "applied")

    def test_resends_then_no_answer(self) -> None:
        game = self.new_game()
        self.hello(game, 4, 3)
        self.assertEqual(self.push(4, {"vol": 30}).status_code, 200)
        self.pc.tick()
        self.assertEqual(len(self.pod_cmds()), 1)  # too soon
        waits = [8, 16, 32, 64, 128]
        for n, wait in enumerate(waits, start=2):
            self.clock.t += wait
            self.pc.tick()
            self.assertEqual(len(self.pod_cmds()), n, n)
            self.assertEqual(self.pc.pushes[4]["state"], "sent")
        # Each repeat carries the same rev and settings.
        self.assertEqual(len({json.dumps(c, sort_keys=True) for c in self.pod_cmds()}), 1)
        self.clock.t += 128
        self.pc.tick()
        self.assertEqual((len(self.pod_cmds()), self.pc.pushes[4]["state"]), (6, "no_answer"))
        # A late answer is still taken, and a push starts the tries again.
        self.applied_event(game, 4, self.pc.pushes[4]["rev"], seq=1)
        self.assertEqual(self.pc.pushes[4]["state"], "applied")

    def test_an_answer_stops_the_resends(self) -> None:
        game = self.new_game()
        self.hello(game, 4, 3)
        rev = self.push(4, {"vol": 30}).json()["rev"]
        self.applied_event(game, 4, rev, seq=1)
        self.clock.t += 500
        self.pc.tick()
        self.assertEqual(len(self.pod_cmds()), 1)

    def test_cancel(self) -> None:
        game = self.new_game()
        self.hello(game, 4, 3)
        self.push(4, {"vol": 30})
        self.assertEqual(self.client.delete("/api/v1/pod-config", headers=GM).json(), {"cancelled": [4]})
        self.clock.t += 500
        self.pc.tick()
        self.assertEqual((len(self.pod_cmds()), self.pc.pushes[4]["state"]), (1, "cancelled"))

    def test_the_radio_is_down(self) -> None:
        game = self.new_game()
        self.hello(game, 4, 3)
        self.push(4, {"vol": 30})
        self.modem.state = "down"
        self.clock.t += 8
        self.pc.tick()  # not sent, not lost: tried again at the next wait
        self.assertEqual(len(self.pod_cmds()), 1)
        self.assertEqual(self.pc.pushes[4]["state"], "sent")

    def test_refusals(self) -> None:
        r = self.push(4, {"vol": 30})
        self.assertEqual(r.status_code, 409)  # no live game
        game = self.new_game()
        self.hello(game, 4, 3)
        self.hello(game, 5, 1)
        for name, node, body, code in [
            ("a box is not a phone", 5, {"vol": 30}, 404),
            ("an unknown node", 9, {"vol": 30}, 404),
            ("never broadcast", 65535, {"vol": 30}, 400),
            ("nothing to set", 4, {}, 400),
            ("a bad colour", 4, {"btn": ["red", "pink-ish", "", ""]}, 400),
            ("out of range", 4, {"bright": 200}, 400),
            ("unknown setting", 4, {"leds": 12}, 400),
        ]:
            with self.subTest(name):
                self.assertEqual(self.push(node, body).status_code, code)
        self.assertEqual(self.pod_cmds(), [])
        # The GM's alone.
        self.assertEqual(self.client.post("/api/v1/pod-config/4", json={"vol": 3}, headers=READ).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/pod-config", headers=READ).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/pod-config/4", json={"vol": 3}).status_code, 401)

    def test_not_during_a_game(self) -> None:
        game = self.new_game()
        self.hello(game, 4, 3)
        self.assertEqual(self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM,
                                          json={"force": True}).status_code, 200)
        r = self.push(4, {"vol": 30})
        self.assertEqual(r.status_code, 409)
        self.assertIn("before a game starts", r.json()["detail"])
        self.assertEqual(self.pod_cmds(), [])

    def test_a_mode_script_cannot_send_it(self) -> None:
        game = self.new_game()
        self.hello(game, 4, 3)
        self.assertEqual(self.client.post("/api/v1/nodes/4/cmd", headers=GM,
                                          json={"cmd": "pod", "params": {"v": 1, "rev": 5, "vol": 1}}).status_code, 400)
        self.assertEqual(self.pod_cmds(), [])


if __name__ == "__main__":
    unittest.main()
