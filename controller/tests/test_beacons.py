# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The indoor BLE beacon registry (ADR-P3-6, decisions BLE-1 to BLE-9): the model, the store (schema 14), the
API (GM writes; staff read all, everyone else ids and UUIDs), the stream, the position reports that name a
beacon (only a registered one is accepted; the room, zone, level and plan place come from the registry) and
the ATAK feed's marker for an indoor position.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from typing import Any

from p3support import GM, READ, P3Case, bearer
from support import wait_for
from test_atak import BR, PNG, TL, AtakCase, split_stream

from atalaia_controller import atak
from atalaia_controller import beacons as beaconsmod
from atalaia_controller.engine import ControllerError
from atalaia_controller.store import SCHEMA_VERSION, Store

UUID = "FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F"
OFF = {"enabled": False, "count": 1, "names": [""]}
ON3 = {"enabled": True, "count": 3, "names": ["", "", ""]}


def beacon(major: int = 1, minor: int = 1, **kw: Any) -> dict[str, Any]:
    return {"uuid": UUID, "major": major, "minor": minor, "room": "Lobby", **kw}


class ModelTests(unittest.TestCase):
    def test_a_beacon_checked(self) -> None:
        out = beaconsmod.check(beacon(uuid=UUID.lower(), room="  Main   hall ", zone="Ground", x=0.25, y=0.5), OFF)
        self.assertEqual(out, {"major": 1, "minor": 1, "uuid": UUID, "room": "Main hall", "zone": "Ground",
                               "level": 0, "x": 0.25, "y": 0.5})
        self.assertEqual(beaconsmod.check(beacon(), OFF)["x"], None)  # not placed yet
        self.assertEqual(beaconsmod.check({**beacon(), "major": 0, "minor": 65535}, OFF)["minor"], 65535)

    def test_refused(self) -> None:
        for bad in ({"uuid": "nope"}, {"uuid": None}, {"major": 65536}, {"minor": -1}, {"major": True},
                    {"major": "1"}, {"room": ""}, {"room": "x" * 49}, {"room": "a\tb"}, {"room": 4},
                    {"zone": "x" * 49}, {"level": 1}, {"level": True}, {"x": 0.5}, {"y": 0.5, "x": None},
                    {"x": 1.5, "y": 0.5}, {"x": True, "y": 0.5}, {"x": float("nan"), "y": 0.5}, {"colour": "red"}):
            with self.subTest(bad), self.assertRaises(ControllerError):
                beaconsmod.check({**beacon(), **bad}, OFF)
        with self.assertRaises(ControllerError):
            beaconsmod.check([], OFF)
        with self.assertRaises(ControllerError):
            beaconsmod.check({k: v for k, v in beacon().items() if k != "room"}, OFF)
        # With levels on, a level in use only; a PUT cannot change the pair.
        self.assertEqual(beaconsmod.check(beacon(level=2), ON3)["level"], 2)
        with self.assertRaises(ControllerError):
            beaconsmod.check(beacon(level=3), ON3)
        self.assertEqual(beaconsmod.check({"uuid": UUID, "room": "A"}, OFF, "7:8")["minor"], 8)
        with self.assertRaises(ControllerError):
            beaconsmod.check(beacon(minor=2), OFF, "1:1")

    def test_ids(self) -> None:
        self.assertEqual(beaconsmod.parse_id("12:65535"), (12, 65535))
        for bad in ("1", "1:2:3", "a:b", "65536:1", "", None, 5):
            with self.subTest(bad), self.assertRaises(ControllerError):
                beaconsmod.parse_id(bad)

    def test_the_interval_is_the_games_within_the_adr_range(self) -> None:
        self.assertEqual(beaconsmod.interval(None), 5)
        self.assertEqual(beaconsmod.interval({"params": {"ble_interval_s": 3}}), 3)
        self.assertEqual(beaconsmod.interval({"params": {"ble_interval_s": 30}}), 30)
        for bad in (2, 31, "9", True, 4.5):
            self.assertEqual(beaconsmod.interval({"params": {"ble_interval_s": bad}}), 5)


class StoreTests(unittest.TestCase):
    def test_a_schema_13_file_gets_the_table_and_keeps_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            first = Store(path)
            first.set_setting("keep", "me")
            first.close()
            db = sqlite3.connect(path)
            db.execute("DROP TABLE beacons")
            db.execute("UPDATE settings SET value = '13' WHERE key = 'schema_version'")
            db.commit()
            db.close()
            store = Store(path)
            self.assertGreaterEqual(SCHEMA_VERSION, 14)
            self.assertEqual(store.get_setting("schema_version"), str(SCHEMA_VERSION))
            self.assertEqual(store.get_setting("keep"), "me")
            self.assertEqual(store.beacons(), [])
            store.close()

    def test_rows(self) -> None:
        store = Store(":memory:")
        self.assertTrue(store.add_beacon(1, 2, 0, {"uuid": UUID, "room": "A", "zone": "", "x": None, "y": None}))
        self.assertFalse(store.add_beacon(1, 2, 1, {"uuid": UUID, "room": "B"}))  # the pair is taken
        self.assertTrue(store.add_beacon(1, 1, 2, {"uuid": UUID, "room": "C", "zone": "", "x": 0.5, "y": 0.5}))
        self.assertEqual([(b["major"], b["minor"]) for b in store.beacons()], [(1, 1), (1, 2)])
        self.assertEqual(store.count_beacons(), 2)
        self.assertEqual(store.move_beacons_to_level0(1), 1)  # (1, 1) was on level 2
        moved = store.beacon(1, 1)
        self.assertEqual((moved["level"], moved["data"]["x"], moved["data"]["room"]), (0, None, "C"))
        self.assertTrue(store.delete_beacon(1, 1))
        self.assertFalse(store.delete_beacon(1, 1))
        self.assertIsNone(store.beacon(1, 1))
        store.close()


class RegistryApiTests(P3Case):
    def add(self, body: dict[str, Any], expect: int = 201, headers: dict[str, str] = GM) -> Any:
        r = self.client.post("/api/v1/beacons", headers=headers, json=body)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def test_gm_writes_and_everyone_reads_what_they_may(self) -> None:
        c = self.client
        empty = c.get("/api/v1/beacons", headers=GM).json()
        self.assertEqual((empty["beacons"], empty["ble_interval_s"]), ([], 5))
        self.assertTrue(empty["box_beacons"]["enabled"])  # staff also read the boxes' switch (box_beacons.py)
        self.assertEqual(c.get("/api/v1/beacons", headers=READ).json(), {"beacons": [], "ble_interval_s": 5})
        made = self.add(beacon(zone="Ground floor", x=0.2, y=0.4))
        self.assertEqual((made["id"], made["room"], made["zone"], made["level"]), ("1:1", "Lobby", "Ground floor", 0))
        self.add(beacon(minor=2, room="Corridor A"))
        self.add(beacon(), expect=409)  # the pair is taken
        self.add(beacon(minor=3, room=""), expect=400)
        self.add({}, expect=400)
        self.add(beacon(minor=9), expect=403, headers=READ)
        self.add(beacon(minor=9), expect=401, headers={})
        staff = c.get("/api/v1/beacons", headers=GM).json()["beacons"]
        self.assertEqual([b["id"] for b in staff], ["1:1", "1:2"])
        self.assertEqual(staff[0]["x"], 0.2)
        # The read token and a player: each beacon's id and uuid, nothing about the building.
        short = [{"id": "1:1", "uuid": UUID}, {"id": "1:2", "uuid": UUID}]
        self.assertEqual(c.get("/api/v1/beacons", headers=READ).json()["beacons"], short)
        self.assertEqual(c.get("/api/v1/beacons", headers={}).status_code, 401)
        # Change one: the pair stays.
        put = c.put("/api/v1/beacons/1:2", headers=GM, json={"uuid": UUID, "room": "Corridor B", "x": 0.7, "y": 0.1})
        self.assertEqual((put.status_code, put.json()["room"], put.json()["x"]), (200, "Corridor B", 0.7))
        self.assertEqual(c.put("/api/v1/beacons/1:2", headers=GM, json={**beacon(minor=5)}).status_code, 400)
        self.assertEqual(c.put("/api/v1/beacons/1:9", headers=GM, json=beacon(minor=9)).status_code, 404)
        self.assertEqual(c.put("/api/v1/beacons/x", headers=GM, json=beacon()).status_code, 404)
        self.assertEqual(c.put("/api/v1/beacons/1:2", headers=READ, json=beacon(minor=2)).status_code, 403)
        self.assertEqual(c.delete("/api/v1/beacons/1:1", headers=READ).status_code, 403)
        self.assertEqual(c.delete("/api/v1/beacons/1:1", headers=GM).json(), {"deleted": True})
        self.assertEqual(c.delete("/api/v1/beacons/1:1", headers=GM).status_code, 404)
        self.assertEqual([b["id"] for b in c.get("/api/v1/beacons", headers=GM).json()["beacons"]], ["1:2"])

    def test_a_field_has_at_most_beacons_max(self) -> None:
        for i in range(beaconsmod.BEACONS_MAX):
            self.ctrl.store.add_beacon(2, i, 0, {"uuid": UUID, "room": "r", "zone": "", "x": None, "y": None})
        self.add(beacon(), expect=409)

    def test_levels_that_go_take_their_beacons_to_level_0(self) -> None:
        c = self.client
        c.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 3})
        self.add(beacon(room="Roof", level=2, x=0.5, y=0.5))
        self.add(beacon(minor=2, room="Hall"))
        self.add(beacon(minor=3, level=3), expect=400)
        c.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 2})
        by = {b["room"]: b for b in c.get("/api/v1/beacons", headers=GM).json()["beacons"]}
        self.assertEqual((by["Roof"]["level"], by["Roof"]["x"]), (0, None))  # still there, to place again
        self.assertEqual(by["Hall"]["level"], 0)

    def test_the_interval_is_the_default_without_a_game_setting(self) -> None:
        # (A mode declares ble_interval_s as it does position_interval_s; none does yet, so the ADR's 5 s.)
        game = self.new_game(teams=["red", "blue"], params={})
        self.client.post(f"/api/v1/games/{game['id']}/start", headers=GM, json={"force": True})
        self.assertEqual(self.client.get("/api/v1/beacons", headers=GM).json()["ble_interval_s"], 5)

    def test_staff_are_told_when_it_changes_and_nobody_else(self) -> None:
        game = self.new_game(teams=["red", "blue"], params={})
        gid = game["id"]
        self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True})
        me = self.check_in(gid, name="red1")
        self.svc.rate.allow = lambda key: True
        self.gm_patch(gid, me["player_id"], team="red", squad=0, role="player")
        tok = self.client.post("/api/v1/checkin/token", headers=bearer(me["token"])).json()["token"]

        def beacon_messages(ws: Any) -> list[dict[str, Any]]:
            self.ctrl._emit({"type": "pong", "sentinel": True})
            got = []
            while True:
                m = ws.receive_json()
                if m.get("sentinel"):
                    return got
                if m["type"] == "beacons":
                    got.append(m)

        with self.client.websocket_connect("/api/v1/stream?token=gm-secret") as gm, \
                self.client.websocket_connect(f"/api/v1/stream?token={tok}") as player:
            gm.receive_json()
            player.receive_json()
            self.add(beacon())
            self.assertEqual(beacon_messages(gm), [{"type": "beacons"}])  # no routing marks
            self.assertEqual(beacon_messages(player), [])


class ReportTests(P3Case):
    def setUp(self) -> None:
        super().setUp()
        self.game = self.new_game(teams=["red", "blue"], params={}, squads=2)
        self.gid = self.game["id"]
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
        me = self.check_in(self.gid, name="red1")
        self.svc.rate.allow = lambda key: True
        self.gm_patch(self.gid, me["player_id"], team="red", squad=1, role="player")
        self.pid = me["player_id"]
        self.tok = self.client.post("/api/v1/checkin/token", headers=bearer(me["token"])).json()["token"]

    def post(self, body: dict[str, Any], expect: int = 200) -> Any:
        r = self.client.post("/api/v1/positions", headers=bearer(self.tok), json=body)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def mine(self) -> dict[str, Any]:
        r = self.client.get("/api/v1/positions", headers=bearer(self.tok))
        self.assertEqual(r.status_code, 200)
        return r.json()["positions"][0]

    def test_only_a_registered_beacon_is_accepted_and_it_gives_the_room(self) -> None:
        self.post({"source": "ble", "beacon_id": "1:2", "t": 10}, expect=400)  # not in the registry
        self.assertEqual(self.ctrl.store.player_positions(self.gid), {})
        self.client.post("/api/v1/beacons", headers=GM, json=beacon(minor=2, room="Corridor A", zone="Ground"))
        out = self.post({"source": "ble", "beacon_id": "1:2", "t": 10, "level": 4})
        self.assertEqual(out, {"stored": 1, "interval_s": 10, "ble_interval_s": 5})
        pos = self.mine()
        self.assertEqual((pos["source"], pos["beacon_id"], pos["room"], pos["zone"], pos["level"]),
                         ("ble", "1:2", "Corridor A", "Ground", 0))  # the beacon's level, not the report's
        self.assertNotIn("x", pos)  # not placed on a plan
        self.assertNotIn("lat", pos)
        # A batch with one unknown beacon is refused whole.
        self.post({"reports": [{"source": "ble", "beacon_id": "1:2", "t": 11},
                               {"source": "ble", "beacon_id": "9:9", "t": 12}]}, expect=400)
        self.assertEqual(self.mine()["t"], 10)

    def test_a_placed_beacon_gives_its_plan_place_and_gps_replaces_it_outdoors(self) -> None:
        self.client.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 2})
        self.client.post("/api/v1/beacons", headers=GM, json=beacon(room="Upstairs", level=1, x=0.25, y=0.75))
        self.post({"source": "ble", "beacon_id": "1:1", "t": 1})
        pos = self.mine()
        self.assertEqual((pos["room"], pos["level"], pos["x"], pos["y"]), ("Upstairs", 1, 0.25, 0.75))
        self.post({"source": "gps", "lat": 38.72, "lon": -9.14, "accuracy_m": 5, "t": 2})
        pos = self.mine()
        self.assertEqual((pos["source"], pos["lat"]), ("gps", 38.72))
        self.assertNotIn("room", pos)

    def test_a_removed_beacon_is_refused_but_the_last_position_keeps_its_room(self) -> None:
        self.client.post("/api/v1/beacons", headers=GM, json=beacon())
        self.post({"source": "ble", "beacon_id": "1:1", "t": 1})
        self.client.delete("/api/v1/beacons/1:1", headers=GM)
        self.assertEqual(self.mine()["room"], "Lobby")
        self.post({"source": "ble", "beacon_id": "1:1", "t": 2}, expect=400)


class AtakBeaconTests(AtakCase):
    players = True
    staff = True

    def test_an_indoor_position_is_the_beacon_on_the_plan_with_the_room_in_the_remarks(self) -> None:
        self.put_image_and_corners()
        gid = self.running_game()
        red, tok = self.player(gid, "Falcão", "red")
        blue, tok_b = self.player(gid, "Mocho", "blue")
        self.client.post("/api/v1/beacons", headers=GM, json=beacon(room="Lobby", zone="Ground", x=0.5, y=0.5))
        self.client.post("/api/v1/beacons", headers=GM, json=beacon(minor=2, room="Cellar"))  # not placed
        for who, bid in ((tok, "1:1"), (tok_b, "1:2")):
            r = self.client.post("/api/v1/positions", headers=bearer(who),
                                 json={"source": "ble", "beacon_id": bid, "t": 5})
            self.assertEqual(r.status_code, 200, r.text)
        self.emitter.cycle(full=True)
        self.assertTrue(wait_for(lambda: len(self.tcp.connections) == 1, 3))
        events = self.events_by_uid(split_stream(self.tcp.connections[0]))
        self.assertIn(f"atalaia.field.player.{red}", events)
        self.assertNotIn(f"atalaia.field.player.{blue}", events)  # a beacon nowhere on the map: no marker
        p = events[f"atalaia.field.player.{red}"]
        self.assertEqual(p.get("how"), "h-e")  # from the image, not a GPS fix
        lat, lon = float(p.find("point").get("lat")), float(p.find("point").get("lon"))
        self.assertAlmostEqual(lat, (TL["lat"] + BR["lat"]) / 2, places=4)
        self.assertAlmostEqual(lon, (TL["lon"] + BR["lon"]) / 2, places=4)
        self.assertEqual(p.find("detail/remarks").text, "Atalaia: red, player, Lobby (Ground)")
        self.assertFalse([r for r in self.events_by_uid(self.udp.drain()).values()
                          if r.get("type") == atak.TYPE_PLAYER])  # never on the multicast


if __name__ == "__main__":
    unittest.main()
