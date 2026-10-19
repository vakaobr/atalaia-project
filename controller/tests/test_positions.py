# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Player positions (ADR-P3-6, constraint 9): reported with a player token, kept for the running
game only, and sent only to those who may see them, on REST and on the stream.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from p3support import GM, READ, P3Case, bearer


def gps(lat: float = 38.72, lon: float = -9.14, t: int = 1000) -> dict:
    return {"lat": lat, "lon": lon, "accuracy_m": 5.0, "source": "gps", "t": t}


class PositionTests(P3Case):
    def setUp(self):
        super().setUp()
        self.game = self.new_game(teams=["red", "blue"], params={}, squads=2)
        self.gid = self.game["id"]
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM)
        self.people = {}
        for name, team, squad, role in (("red1", "red", 1, "player"), ("red2", "red", 1, "player"),
                                        ("red3", "red", 2, "player"), ("lead", "red", 1, "squad_leader"),
                                        ("vip", "red", 0, "vip"), ("blue1", "blue", 1, "player"),
                                        ("marshal", None, 0, "marshal"), ("watch", None, 0, "spectator")):
            me = self.check_in(self.gid, name=name)
            self.svc.rate.allow = lambda key: True
            self.gm_patch(self.gid, me["player_id"], team=team, squad=squad, role=role)
            tok = self.client.post("/api/v1/checkin/token", headers=bearer(me["token"])).json()["token"]
            self.people[name] = (me["player_id"], tok)
        for name in ("red1", "red2", "red3", "lead", "vip", "blue1"):
            r = self.client.post("/api/v1/positions", headers=bearer(self.people[name][1]), json=gps())
            self.assertEqual(r.status_code, 200, r.text)

    def seen_by(self, name: str) -> set[str]:
        ids = {pid: n for n, (pid, _) in self.people.items()}
        r = self.client.get("/api/v1/positions", headers=bearer(self.people[name][1]))
        self.assertEqual(r.status_code, 200, r.text)
        return {ids[p["player_id"]] for p in r.json()["positions"]}

    def test_visibility_table(self):
        self.assertEqual(self.seen_by("red1"), {"red1"})
        self.assertEqual(self.seen_by("lead"), {"lead", "red1", "red2"})  # the squad
        self.assertEqual(self.seen_by("vip"), {"vip", "red1", "red2", "red3", "lead"})  # the team
        self.assertEqual(self.seen_by("blue1"), {"blue1"})
        self.assertEqual(len(self.seen_by("marshal")), 6)
        self.assertEqual(self.seen_by("watch"), set())
        self.assertEqual(len(self.client.get("/api/v1/positions", headers=GM).json()["positions"]), 6)
        self.assertEqual(self.client.get("/api/v1/positions", headers=READ).json()["positions"], [])

    def test_squad_visible_parameter(self):
        self.ctrl.store._exec("UPDATE games SET params_json = ? WHERE id = ?", ('{"squad_visible": true}', self.gid))
        self.assertEqual(self.seen_by("red1"), {"red1", "red2", "lead"})

    def test_temporary_visibility(self):
        fc = self.ctrl.fc
        fc.controller_event("visibility.granted", {"see_team": "blue", "duration_s": 30, "text": "uav"}, team="red")
        self.assertEqual(self.seen_by("red1"), {"red1", "blue1"})
        self.assertEqual(self.seen_by("blue1"), {"blue1"})  # one way only
        self.now += 31
        with self.ctrl._lock:
            self.ctrl.positions.tick()
        self.assertEqual(self.seen_by("red1"), {"red1"})
        expired = self.events(self.gid, "visibility.expired")
        self.assertEqual((expired[0]["team"], expired[0]["data"]["see_team"]), ("red", "blue"))

    def test_stream_sends_only_what_each_may_see(self):
        with self.client.websocket_connect(f"/api/v1/stream?token={self.people['red1'][1]}") as red, \
                self.client.websocket_connect("/api/v1/stream?token=read-secret") as read:
            hello = red.receive_json()
            self.assertEqual([p["player_id"] for p in hello["positions"]], [self.people["red1"][0]])
            read.receive_json()
            self.client.post("/api/v1/positions", headers=bearer(self.people["blue1"][1]), json=gps(t=2000))
            self.client.post("/api/v1/positions", headers=bearer(self.people["red1"][1]), json=gps(t=3000))
            self.ctrl._emit({"type": "pong", "sentinel": True})
            got_red, got_read = [], []
            for ws, got in ((red, got_red), (read, got_read)):
                while True:
                    m = ws.receive_json()
                    if m.get("sentinel"):
                        break
                    got.append(m)
        mine = [m["position"]["player_id"] for m in got_red if m["type"] == "player_position"]
        self.assertEqual(mine, [self.people["red1"][0]])
        self.assertFalse([m for m in got_read if m["type"] == "player_position"])

    def test_reports_are_checked_and_deleted_with_the_game(self):
        tok = self.people["red1"][1]
        for bad in ({"lat": 91, "lon": 0}, {"source": "ble"}, {"source": "ble", "beacon_id": "1:70000"},
                    {"reports": [gps()] * 6}, {**gps(), "player_id": self.people["red2"][0]}, {**gps(), "x": 1}):
            with self.subTest(bad):
                self.assertEqual(self.client.post("/api/v1/positions", headers=bearer(tok), json=bad).status_code, 400)
        r = self.client.post("/api/v1/positions", headers=bearer(tok),
                             json={"reports": [gps(t=1), {"source": "ble", "beacon_id": "1:2", "t": 5}]})
        self.assertEqual(r.json(), {"stored": 2, "interval_s": 10})
        mine = self.ctrl.store.player_positions(self.gid)[self.people["red1"][0]]
        self.assertEqual((mine["source"], mine["beacon_id"]), ("ble", "1:2"))  # the latest
        self.assertEqual(self.client.post("/api/v1/positions", headers=READ, json=gps()).status_code, 403)
        self.client.post(f"/api/v1/games/{self.gid}/end", json={}, headers=GM)
        self.assertEqual(self.ctrl.store.player_positions(self.gid), {})
        self.assertEqual(self.client.post("/api/v1/positions", headers=bearer(tok), json=gps()).status_code, 409)


if __name__ == "__main__":
    unittest.main()
