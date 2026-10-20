# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""VIP / Payload on the controller (plan phase 5, decision P4R6), and what only staff may read
(decision M5-1).

- A VIP's position report (POST /api/v1/positions) reaches the game's field.lua as position.fix
  and nothing else: inside the extraction zone it ends the game; a player who is not the VIP does
  nothing; no event, no stream message other than the phase 3 player_position (to those who may see
  it), and no MQTT topic carries a coordinate.
- gm_only data (protocol/schema/events.yaml) and parameters (mode.yaml): a Hacking Terminal's
  revealed code and its reveal_code, a Bomb's team codes, reach the GM token and marshals only, never
  a player's connection, the read token or MQTT.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import re
import unittest
from typing import Any

from p3support import GM, READ, P3Case, bearer

from atalaia_controller.mqtt import MqttBridge


_JSON_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def leaked(secret: str, text: str) -> list[str]:
    """The JSON strings in text that carry secret: a code leaks in a value or a message, never in a
    number (a timestamp such as 941.4711146 is not a leak) or a UUID (ids are random hex)."""
    return [s for s in _JSON_STRING.findall(text) if secret in s and not _UUID.fullmatch(s)]


VIP = "org.atalaia.vip_payload"
HACK = "org.atalaia.hacking_terminal"
ZONE = "38.722345,-9.139312"
# The players' positions: 100 m north of the zone's centre, and 7 m north-east of it (inside).
# The zone itself is a game parameter, which everyone may know (the defenders guard it).
OUTSIDE = {"lat": 38.723244, "lon": -9.13925, "accuracy_m": 5.0, "source": "gps"}
INSIDE = {"lat": 38.722390, "lon": -9.13925, "accuracy_m": 5.0, "source": "gps"}
COORDS = ("38.723244", "38.72239", "-9.13925")


class Recorder:
    """An MQTT bridge whose publishes are recorded instead of sent (no broker needed)."""

    def __init__(self, cfg, ctrl) -> None:
        self.bridge = MqttBridge(cfg, ctrl)
        self.sent: list[tuple[str, Any]] = []
        self.bridge._publish = lambda topic, data, retain=False: self.sent.append((topic, data))  # type: ignore[method-assign]

    def text(self) -> str:
        return json.dumps(self.sent)


class Case(P3Case):
    def person(self, gid: int, name: str, team: Any, role: str) -> tuple[str, str]:
        me = self.check_in(gid, name=name)
        self.svc.rate.allow = lambda key: True
        self.gm_patch(gid, me["player_id"], team=team, squad=0, role=role)
        tok = self.client.post("/api/v1/checkin/token", headers=bearer(me["token"])).json()["token"]
        return me["player_id"], tok

    def drain(self, *sockets) -> list[list[dict[str, Any]]]:
        """Everything each socket got until a sentinel message reached all of them."""
        self.ctrl._emit({"type": "pong", "sentinel": True})
        out = []
        for ws in sockets:
            got = []
            while True:
                m = ws.receive_json()
                if m.get("sentinel"):
                    break
                got.append(m)
            out.append(got)
        return out


class VipPositionTests(Case):
    def setUp(self):
        super().setUp()
        self.mqtt = Recorder(self.cfg, self.ctrl)
        self.game = self.new_game(mode_id=VIP, assignments={"4": "checkpoint"},
                                  params={"extraction": ZONE, "vip_points": 50})
        self.gid = self.game["id"]
        r = self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.vip = self.person(self.gid, "Escoltada", "red", "vip")
        self.red = self.person(self.gid, "Ana", "red", "player")
        self.blue_vip = self.person(self.gid, "Rui", "blue", "vip")

    def post(self, who, report) -> None:
        r = self.client.post("/api/v1/positions", headers=bearer(who[1]), json={**report, "t": 1000})
        self.assertEqual(r.status_code, 200, r.text)

    def test_the_vip_in_the_zone_ends_the_game(self):
        with self.client.websocket_connect(f"/api/v1/stream?token={self.red[1]}") as red, \
                self.client.websocket_connect("/api/v1/stream?token=read-secret") as read, \
                self.client.websocket_connect("/api/v1/stream?token=gm-secret") as gm:
            for ws in (red, read, gm):
                ws.receive_json()
            self.post(self.vip, OUTSIDE)
            self.post(self.red, INSIDE)        # not the VIP
            self.post(self.blue_vip, INSIDE)   # not the escorting team's VIP
            self.assertEqual(self.events(self.gid, "vip.extracted"), [])
            self.assertEqual(self.client.get(f"/api/v1/games/{self.gid}", headers=GM).json()["state"], "running")
            self.post(self.vip, INSIDE)
            got_red, got_read, got_gm = self.drain(red, read, gm)
        game = self.client.get(f"/api/v1/games/{self.gid}", headers=GM).json()
        self.assertEqual(game["state"], "ended")
        extracted = self.events(self.gid, "vip.extracted")
        self.assertEqual([(e["team"], e["data"]) for e in extracted], [("red", {"team": "red", "player": self.vip[0]})])
        end = self.events(self.gid, "game.end")
        self.assertEqual(end[-1]["data"].get("winner"), "red")
        self.assertEqual(self.client.get(f"/api/v1/games/{self.gid}/score", headers=GM).json()["teams"].get("red"), 50)
        # Coordinates: only in player_position messages, and only to those who may see them (the red
        # player sees nobody's but their own, the read token nobody's; the GM everyone's).
        for name, got in (("red", got_red), ("read", got_read), ("gm", got_gm)):
            others = json.dumps([m for m in got if m["type"] != "player_position"])
            for c in COORDS:
                self.assertNotIn(c, others, name)
            self.assertTrue(any(m["type"] == "event" and m["event"]["type"] == "vip.extracted" for m in got), name)
        self.assertEqual({m["position"]["player_id"] for m in got_red if m["type"] == "player_position"},
                         {self.red[0]})
        self.assertFalse([m for m in got_read if m["type"] == "player_position"])
        # Nothing on MQTT or in the log, nothing the read token can fetch, and positions are gone.
        self.assertTrue(any(t.endswith("/events/vip.extracted") for t, _ in self.mqtt.sent))
        for text in (self.mqtt.text(), json.dumps(self.events(self.gid)), self.everything_public(self.gid)):
            for c in COORDS:
                self.assertNotIn(c, text)
        self.assertEqual(self.ctrl.store.player_positions(self.gid), {})

    def test_a_vip_without_a_zone_or_a_field_script_extracts_nothing(self):
        self.ctrl.end_game(self.gid, "test")
        game = self.new_game(mode_id=VIP, assignments={"4": "checkpoint"})  # no extraction zone
        self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM)
        vip = self.person(game["id"], "Escoltada", "red", "vip")
        self.post(vip, INSIDE)
        self.assertEqual(self.events(game["id"], "vip.extracted"), [])
        self.ctrl.end_game(game["id"], "test")
        dom = self.new_game()  # Domination: no field.lua; the report is only a position
        self.client.post(f"/api/v1/games/{dom['id']}/start", headers=GM)
        vip = self.person(dom["id"], "Escoltada", "red", "vip")
        self.post(vip, INSIDE)
        self.assertEqual(self.events(dom["id"], "vip.extracted"), [])

    def test_a_malformed_zone_refuses_to_start(self):
        self.ctrl.end_game(self.gid, "test")
        game = self.new_game(mode_id=VIP, assignments={"4": "checkpoint"}, params={"extraction": "38.7;-9.1"})
        r = self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("extraction: latitude,longitude", r.text)


class GmOnlyTests(Case):
    """Decision M5-1: the code a terminal reveals, and the codes in the game's parameters."""

    def setUp(self):
        super().setUp()
        self.mqtt = Recorder(self.cfg, self.ctrl)
        self.game = self.new_game(mode_id=HACK, assignments={"4": "terminal"},
                                  params={"reveal_code": "4711", "puzzle": "wires"})
        self.gid = self.game["id"]
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM)
        self.player = self.person(self.gid, "Ana", "red", "player")
        self.marshal = self.person(self.gid, "Rita", None, "marshal")

    def solve(self) -> None:
        self.ctrl.fc.controller_event("hacking.solved", {"puzzle": "wires", "code": "4711"}, team="red",
                                      prio="critical")

    def test_a_player_never_sees_the_code(self):
        with self.client.websocket_connect(f"/api/v1/stream?token={self.player[1]}") as player, \
                self.client.websocket_connect("/api/v1/stream?token=read-secret") as read, \
                self.client.websocket_connect(f"/api/v1/stream?token={self.marshal[1]}") as marshal, \
                self.client.websocket_connect("/api/v1/stream?token=gm-secret") as gm:
            hellos = [ws.receive_json() for ws in (player, read, marshal, gm)]
            self.assertEqual(leaked("4711", json.dumps(hellos[:2])), [])      # the game's reveal_code
            self.assertEqual(hellos[2]["game"]["params"]["reveal_code"], "4711")
            self.assertEqual(hellos[3]["game"]["params"]["reveal_code"], "4711")
            self.solve()
            self.client.post(f"/api/v1/games/{self.gid}/pause", headers=GM)  # a "game" message
            got = self.drain(player, read, marshal, gm)
        for name, msgs in zip(("player", "read"), got[:2]):
            solved = [m["event"] for m in msgs if m["type"] == "event" and m["event"]["type"] == "hacking.solved"]
            self.assertEqual([e["data"] for e in solved], [{"puzzle": "wires"}], name)
            self.assertTrue([m for m in msgs if m["type"] == "game"], name)
            self.assertEqual(leaked("4711", json.dumps(msgs)), [], name)
        for name, msgs in zip(("marshal", "gm"), got[2:]):
            solved = [m["event"] for m in msgs if m["type"] == "event" and m["event"]["type"] == "hacking.solved"]
            self.assertEqual(solved[0]["data"]["code"], "4711", name)
            game = [m["game"] for m in msgs if m["type"] == "game"][-1]
            self.assertEqual(game["params"]["reveal_code"], "4711", name)
        # A later connection's hello: its latest events.
        with self.client.websocket_connect(f"/api/v1/stream?token={self.player[1]}") as player:
            self.assertEqual(leaked("4711", json.dumps(player.receive_json())), [])
        with self.client.websocket_connect(f"/api/v1/stream?token={self.marshal[1]}") as marshal:
            hello = marshal.receive_json()
            self.assertIn("4711", json.dumps([e for e in hello["events"] if e["type"] == "hacking.solved"]))

    def test_rest_and_mqtt(self):
        self.solve()
        for headers in (bearer(self.player[1]), READ):
            text = json.dumps([self.client.get(p, headers=headers).json() for p in (
                f"/api/v1/games/{self.gid}/log", f"/api/v1/games/{self.gid}", "/api/v1/games")])
            self.assertEqual(leaked("4711", text), [])
            self.assertIn("hacking.solved", text)
            self.assertIn('"puzzle": "wires"', text)
        for headers in (GM, bearer(self.marshal[1])):
            log = self.client.get(f"/api/v1/games/{self.gid}/log", headers=headers).json()
            self.assertEqual([e["data"]["code"] for e in log if e["type"] == "hacking.solved"], ["4711"])
            game = self.client.get(f"/api/v1/games/{self.gid}", headers=headers).json()
            self.assertEqual(game["params"]["reveal_code"], "4711")
        self.assertEqual(json.loads(self.client.get("/api/v1/games", headers=GM).text)[0]["params"]["reveal_code"],
                         "4711")
        sent = [d for t, d in self.mqtt.sent if t.endswith("/events/hacking.solved")]
        self.assertEqual([d["data"] for d in sent], [{"puzzle": "wires"}])
        self.assertEqual(leaked("4711", self.mqtt.text()), [])

    def test_presets_for_the_read_token(self):
        r = self.client.post("/api/v1/presets", headers=GM, json={
            "name": "Bomba com códigos", "mode_id": "org.atalaia.bomb", "params": {"team_codes": "red=1234,blue=5678"}})
        self.assertEqual(r.status_code, 201, r.text)
        mine = [p for p in self.client.get("/api/v1/presets", headers=READ).json() if p["name"] == "Bomba com códigos"]
        self.assertEqual(mine[0]["params"], {})
        mine = [p for p in self.client.get("/api/v1/presets", headers=GM).json() if p["name"] == "Bomba com códigos"]
        self.assertEqual(mine[0]["params"], {"team_codes": "red=1234,blue=5678"})

    def test_a_marshal_of_another_game_is_not_staff_here(self):
        from atalaia_controller import visibility
        from atalaia_controller.checkin import Viewer

        marshal = Viewer("player", {"role": "marshal", "game_id": self.gid + 1, "player_id": "p-x"})
        self.assertFalse(visibility.is_staff(marshal, self.gid))
        self.assertTrue(visibility.is_staff(Viewer("gm"), self.gid))
        self.assertFalse(visibility.is_staff(Viewer("read"), self.gid))


if __name__ == "__main__":
    unittest.main()
