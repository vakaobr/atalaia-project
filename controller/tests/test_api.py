# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""REST and WebSocket API v1 (plan AC-5): every endpoint through the real FastAPI app.

    cd controller && python -m unittest discover -s tests

The app runs in-process (Starlette's TestClient) over the real engine and
store; the radio is a recording modem, so commands and beacons are checked
as the packets they become.
"""

from __future__ import annotations

import tempfile
import unittest

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import codec
from atalaia_sim.packet import cmd_decode, state_encode

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
DOMINATION = "org.atalaia.domination"


class ApiCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = config(self.tmp.name)
        self.store = Store(cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(cfg, self.store, modem=self.modem, core=CORE)
        self.hub = Hub()
        self.app = create_app(self.ctrl, self.hub, Auth(cfg.gm_token, cfg.read_token))
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def new_game(self, **spec):
        body = {"name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"],
                "assignments": {"4": "zone"}, **spec}
        r = self.client.post("/api/v1/games", json=body, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()


class EndpointTests(ApiCase):
    def test_every_endpoint(self):
        c = self.client
        # GET/POST modes
        r = c.get("/api/v1/modes", headers=READ)
        self.assertEqual(r.status_code, 200)
        ids = {m["id"]: m for m in r.json()}
        self.assertTrue(ids[DOMINATION]["builtin"])
        self.assertEqual(ids[DOMINATION]["params"]["tick_s"]["default"], 10)
        upload = {"files": {"mode.yaml": "id: org.test.up\nversion: 1.0\nroles: { zone: {} }\n",
                            "node.lua": "local x = 1\n"}}
        r = c.post("/api/v1/modes", json=upload, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["id"], "org.test.up")
        # GET/POST presets
        r = c.post("/api/v1/presets", json={"name": "fast", "mode_id": DOMINATION,
                                            "params": {"tick_s": 5}}, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        preset = r.json()
        self.assertEqual(c.get("/api/v1/presets", headers=READ).json(), [preset])
        # POST games (from the preset), GET games, GET game
        game = self.new_game(preset_id=preset["id"], mode_id=None, duration_ms=900_000)
        gid = game["id"]
        self.assertEqual(game["params"]["tick_s"], 5)
        self.assertEqual(c.get("/api/v1/games", headers=READ).json()[0]["id"], gid)
        self.assertEqual(c.get(f"/api/v1/games/{gid}", headers=READ).json()["state"], "ready")
        # lifecycle
        self.assertEqual(c.post(f"/api/v1/games/{gid}/start", headers=GM).json()["state"], "running")
        self.assertEqual(c.post(f"/api/v1/games/{gid}/pause", json={"reason": "medic"}, headers=GM)
                         .json()["state"], "paused")
        self.assertEqual(c.post(f"/api/v1/games/{gid}/resume", headers=GM).json()["state"], "running")
        # nodes (fed by the radio)
        self.modem.rx(4, 0, "STATE", state_encode({"owner_team": 1, "phase": 1, "game_time_ms": 10,
                                                   "counters": {1: 7}, "epoch": 1}), game_id=gid, epoch=1)
        self.modem.rx(4, 1, "EVENT", codec.encode_event({"node": 4, "seq": 1, "t": 50, "type": "zone.captured",
                                                         "team": 1}), game_id=gid, epoch=1)
        nodes = c.get("/api/v1/nodes", headers=READ).json()
        self.assertEqual((nodes[0]["node_id"], nodes[0]["owner"]), (4, "red"))
        self.assertEqual(c.get(f"/api/v1/nodes?game={gid}", headers=READ).json()[0]["node_id"], 4)
        # score
        self.assertEqual(c.get(f"/api/v1/games/{gid}/score", headers=READ).json(),
                         {"game": gid, "teams": {"red": 7, "blue": 0}})
        r = c.post(f"/api/v1/games/{gid}/score", json={"team": "blue", "amount": 3, "reason": "bonus"},
                   headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["score"]["teams"], {"red": 7, "blue": 3})
        # node command
        r = c.post("/api/v1/nodes/4/cmd", json={"cmd": "message", "params": {"text": "go"}}, headers=GM)
        self.assertEqual(r.status_code, 202, r.text)
        self.assertEqual(cmd_decode(self.modem.of("CMD")[-1][1]), {"cmd": 5, "params": {"text": "go"}, "dest": 4})
        # controller status and promote (already the controller: 409)
        status = c.get("/api/v1/controller", headers=READ).json()
        self.assertEqual((status["role"], status["live_game"], status["radio"]), ("leader", gid, "up"))
        self.assertEqual(c.post("/api/v1/controller/promote", headers=GM).status_code, 409)
        # end and log
        self.assertEqual(c.post(f"/api/v1/games/{gid}/end", json={"reason": "time"}, headers=GM)
                         .json()["state"], "ended")
        log = c.get(f"/api/v1/games/{gid}/log", headers=READ).json()
        self.assertEqual(log[0]["type"], "game.start")
        self.assertEqual({e["type"] for e in log},
                         {"game.start", "game.pause", "game.resume", "zone.captured", "score.delta", "game.end"})
        self.assertEqual([e for e in log if e["type"] == "game.end"][0]["data"], {"reason": "time", "winner": "red"})
        self.assertEqual([e["t"] for e in log], sorted(e["t"] for e in log))  # in game-time order
        self.assertEqual(c.get(f"/api/v1/games/{gid}/score", headers=READ).json()["teams"],
                         {"red": 7, "blue": 3})
        self.assertTrue(c.get("/healthz").json()["ok"])

    def test_tokens(self):
        c = self.client
        self.assertEqual(c.get("/api/v1/games").status_code, 401)
        self.assertEqual(c.get("/api/v1/games", headers={"Authorization": "Bearer nope"}).status_code, 401)
        self.assertEqual(c.get("/api/v1/games", headers=GM).status_code, 200)
        r = c.post("/api/v1/games", json={"name": "x", "mode_id": DOMINATION}, headers=READ)
        self.assertEqual(r.status_code, 403)
        self.assertEqual(c.post("/api/v1/games", json={"name": "x", "mode_id": DOMINATION}).status_code, 401)
        for path in ("/api/v1/modes", "/api/v1/presets", "/api/v1/nodes/1/cmd", "/api/v1/games/1/start",
                     "/api/v1/games/1/pause", "/api/v1/games/1/resume", "/api/v1/games/1/end",
                     "/api/v1/games/1/score", "/api/v1/controller/promote"):
            with self.subTest(path):
                self.assertEqual(c.post(path, json={}, headers=READ).status_code, 403)
        self.assertEqual(self.store.games(), [])

    def test_errors(self):
        c = self.client
        self.assertEqual(c.get("/api/v1/games/999", headers=READ).status_code, 404)
        self.assertEqual(c.get("/api/v1/games/999/log", headers=READ).status_code, 404)
        self.assertEqual(c.post("/api/v1/games/999/start", headers=GM).status_code, 404)
        r = c.post("/api/v1/games", json={"name": "x", "mode_id": "org.no.such"}, headers=GM)
        self.assertEqual(r.status_code, 400)
        self.assertIn("unknown mode", r.json()["detail"])
        self.assertEqual(c.post("/api/v1/games", json=[1, 2], headers=GM).status_code, 400)
        self.assertEqual(c.post("/api/v1/presets", json={"name": "p", "mode_id": DOMINATION,
                                                         "params": {"tick_s": 9999}}, headers=GM).status_code, 400)
        self.assertEqual(c.post("/api/v1/modes", json={"files": {"node.lua": "x"}}, headers=GM).status_code, 400)
        self.assertEqual(c.post("/api/v1/nodes/4/cmd", json={"cmd": "message"}, headers=GM).status_code, 409)
        gid = self.new_game()["id"]
        self.assertEqual(c.post("/api/v1/games", json={"name": "y", "mode_id": DOMINATION},
                                headers=GM).status_code, 409)
        self.assertEqual(c.post(f"/api/v1/games/{gid}/resume", headers=GM).status_code, 409)
        c.post(f"/api/v1/games/{gid}/start", headers=GM)
        self.assertEqual(c.post("/api/v1/nodes/4/cmd", json={"cmd": "start"}, headers=GM).status_code, 400)
        self.assertEqual(c.post(f"/api/v1/games/{gid}/score", json={"team": "green", "amount": 1},
                                headers=GM).status_code, 400)
        self.assertEqual(c.post(f"/api/v1/games/{gid}/pause", json={"reason": 5}, headers=GM).status_code, 400)
        self.modem.state = "down"
        self.assertEqual(c.post("/api/v1/nodes/4/cmd", json={"cmd": "message"}, headers=GM).status_code, 503)
        self.assertEqual(c.get("/api/v1/games/abc", headers=READ).status_code, 422)


class StreamTests(ApiCase):
    def test_snapshot_then_live_messages(self):
        gid = self.new_game()["id"]
        with self.client.websocket_connect("/api/v1/stream?token=read-secret") as ws:
            hello = ws.receive_json()
            self.assertEqual(hello["type"], "hello")
            self.assertEqual(hello["game"]["id"], gid)
            self.assertEqual(hello["score"]["teams"], {"red": 0, "blue": 0})
            ws.send_json({"type": "ping"})
            self.assertEqual(ws.receive_json(), {"type": "pong"})
            self.client.post(f"/api/v1/games/{gid}/start", headers=GM)
            self.modem.rx(4, 0, "EVENT", codec.encode_event({"node": 4, "seq": 1, "t": 5, "type": "zone.captured",
                                                             "team": 2}), game_id=gid, epoch=1)
            seen = []
            while not any(m["type"] == "event" and m["event"]["type"] == "zone.captured" for m in seen):
                seen.append(ws.receive_json())
            kinds = [m["type"] for m in seen]
            self.assertIn("game", kinds)
            captured = [m for m in seen if m["type"] == "event" and m["event"]["type"] == "zone.captured"][0]
            self.assertEqual(captured["event"]["team"], "blue")
            self.modem.on_state("down")
            while True:
                msg = ws.receive_json()
                if msg["type"] == "system":
                    break
            self.assertEqual(msg["kind"], "radio.down")

    def test_stream_needs_a_token(self):
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect) as ctx:
            with self.client.websocket_connect("/api/v1/stream") as ws:
                ws.receive_json()
        self.assertEqual(ctx.exception.code, 4401)
        with self.client.websocket_connect("/api/v1/stream", headers=GM) as ws:
            self.assertEqual(ws.receive_json()["type"], "hello")

    def test_slow_client_is_dropped(self):
        self.hub.max_queue = 2
        with self.client.websocket_connect("/api/v1/stream?token=read-secret") as ws:
            ws.receive_json()
            for i in range(50):
                self.ctrl._emit({"type": "system", "kind": "test", "i": i})
            got = []
            from starlette.websockets import WebSocketDisconnect
            try:
                while True:
                    got.append(ws.receive_json())
            except WebSocketDisconnect as exc:
                self.assertEqual(exc.code, 4408)
            self.assertLess(len(got), 50)
        self.assertGreaterEqual(self.hub.dropped_clients, 1)


if __name__ == "__main__":
    unittest.main()
