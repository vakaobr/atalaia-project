# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Field Boxes as iBeacons (decisions BBC-1 to BBC-12, protocol/box-beacon.md): the UUID and the
advertisement bytes against the shared vectors; a box's beacon registered by itself from its place (and
following it when the GM moves the box or changes its level); the room (the box's name, or the GM's); a box
disabled, and the field's setting off (the join says so, the registry stops listing the boxes); what staff and
what everyone else read; a phone that hears a box is placed exactly as with a tag; tags and boxes together,
with the box's major reserved.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from p3support import GM, READ, P3Case, bearer

from atalaia_controller import beacons as beaconsmod
from atalaia_controller import box_beacons as bb
from atalaia_sim import join as joinfmt

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "box_beacon.json")
                     .read_text(encoding="utf-8"))
TAG_UUID = "FDA50693-A4E2-4FB1-AFCF-C28847DC5D9F"


class VectorTests(unittest.TestCase):
    def test_the_uuid_is_the_vectors(self) -> None:
        for v in VECTORS["uuids"]:
            with self.subTest(v["join_key"][:8]):
                self.assertEqual(bb.derive_uuid(bytes.fromhex(v["join_key"])), v["uuid_text"])

    def test_the_advertisement_is_the_vectors(self) -> None:
        self.assertEqual(VECTORS["major"], bb.MAJOR)
        self.assertEqual(VECTORS["label"].encode(), bb.LABEL)
        for v in VECTORS["adv"]:
            with self.subTest(v["id"]):
                key = bytes.fromhex(v["join_key"])
                self.assertEqual(bb.adv_bytes(key, v["node_id"], v["measured_power"]).hex(), v["adv"])
                self.assertEqual(bb.box_id(v["node_id"]), v["id"])

    def test_a_box_id_is_never_a_tags(self) -> None:
        with self.assertRaises(Exception) as cm:
            beaconsmod.check({"uuid": TAG_UUID, "major": bb.MAJOR, "minor": 1, "room": "x"},
                             {"enabled": False, "count": 1, "names": [""]})
        self.assertIn("Field Boxes", str(cm.exception))


class BoxBeaconCase(P3Case):
    def setUp(self) -> None:
        super().setUp()
        self.game = self.new_game(teams=["red", "blue"], params={}, assignments={"4": "zone", "5": "zone"})
        self.gid = self.game["id"]
        self.uuid = bb.derive_uuid(self.ctrl.join_key)

    def place(self, node: int, x: float = 0.25, y: float = 0.5, **extra: Any) -> Any:
        r = self.client.put(f"/api/v1/games/{self.gid}/positions/{node}", headers=GM,
                            json={"x": x, "y": y, **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def listing(self, headers: dict[str, str] = GM) -> dict[str, Any]:
        r = self.client.get("/api/v1/beacons", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def boxes(self, headers: dict[str, str] = GM) -> list[dict[str, Any]]:
        return [b for b in self.listing(headers)["beacons"] if b["id"].startswith(f"{bb.MAJOR}:")]


class AutoRegistrationTests(BoxBeaconCase):
    def test_a_box_is_registered_from_its_place_and_follows_it(self) -> None:
        self.assertEqual(self.boxes(), [])  # not placed: no level, no place, no beacon
        self.place(4, 0.25, 0.5)
        (box,) = self.boxes()
        self.assertEqual((box["id"], box["uuid"], box["kind"], box["major"], box["minor"]),
                         (f"{bb.MAJOR}:4", self.uuid, "box", bb.MAJOR, 4))
        self.assertEqual((box["node_id"], box["room"], box["level"], box["x"], box["y"], box["enabled"]),
                         (4, "node-4", 0, 0.25, 0.5, True))
        # Moved on the plan: the beacon moves.
        self.place(4, 0.8, 0.1)
        (box,) = self.boxes()
        self.assertEqual((box["x"], box["y"]), (0.8, 0.1))
        # A second box, and the staff list has both, by node.
        self.place(5, 0.4, 0.4)
        self.assertEqual([b["minor"] for b in self.boxes()], [4, 5])

    def test_a_level_change_moves_the_beacon_to_that_level(self) -> None:
        self.client.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 3})
        self.place(4, 0.3, 0.3, level=2)
        self.assertEqual(self.boxes()[0]["level"], 2)
        self.place(4, 0.3, 0.3, level=1)
        self.assertEqual(self.boxes()[0]["level"], 1)
        # Levels off: a box is shown on level 0 (ML-4), and so is its beacon; the level it had comes back.
        self.client.put("/api/v1/field/levels", headers=GM, json={"enabled": False, "count": 3})
        self.assertEqual(self.boxes()[0]["level"], 0)

    def test_the_room_is_the_boxs_name_or_the_gms(self) -> None:
        self.place(4)
        self.assertEqual(self.boxes()[0]["room"], "node-4")
        self.ctrl.scenario_names[4] = "Roof tank"  # the GM's name for it in a scenario (Join tab)
        self.assertEqual(self.boxes()[0]["room"], "Roof tank")
        r = self.client.put("/api/v1/box-beacons/4", headers=GM, json={"room": "  Server   room "})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["room"], r.json()["room_given"]), ("Server room", True))
        self.assertEqual(self.boxes()[0]["name"], "Roof tank")
        r = self.client.put("/api/v1/box-beacons/4", headers=GM, json={"room": None})
        self.assertEqual((r.json()["room"], r.json()["room_given"]), ("Roof tank", False))
        for bad in ({"room": "x" * 49}, {"room": 5}, {"room": "a\tb"}, {"colour": 1}, {}, {"enabled": "yes"}):
            with self.subTest(bad):
                self.assertEqual(self.client.put("/api/v1/box-beacons/4", headers=GM, json=bad).status_code, 400)
        self.assertEqual(self.client.put("/api/v1/box-beacons/99", headers=GM, json={"room": "x"}).status_code, 400)

    def test_everyone_else_is_given_the_id_and_uuid_of_each_enabled_box(self) -> None:
        self.place(4)
        self.place(5)
        short = [{"id": f"{bb.MAJOR}:4", "uuid": self.uuid}, {"id": f"{bb.MAJOR}:5", "uuid": self.uuid}]
        self.assertEqual(self.listing(READ)["beacons"], short)
        self.assertEqual(self.client.get("/api/v1/beacons", headers={}).status_code, 401)
        self.assertNotIn("box_beacons", self.listing(READ))
        staff = self.listing()
        self.assertEqual(staff["box_beacons"], {"enabled": True, "major": bb.MAJOR, "uuid": self.uuid})

    def test_a_box_not_of_this_game_is_not_listed_and_the_game_ending_ends_it(self) -> None:
        self.place(4)
        self.assertEqual(len(self.boxes()), 1)
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
        self.assertEqual(len(self.boxes()), 1)
        self.client.post(f"/api/v1/games/{self.gid}/end", headers=GM, json={})
        self.assertEqual(self.boxes(), [])  # the boxes' game is over: they stop advertising


class DisableTests(BoxBeaconCase):
    def test_a_box_can_be_disabled_and_enabled(self) -> None:
        self.place(4)
        self.place(5)
        r = self.client.put("/api/v1/box-beacons/4", headers=GM, json={"enabled": False})
        self.assertEqual((r.status_code, r.json()["enabled"]), (200, False))
        by = {b["minor"]: b for b in self.boxes()}
        self.assertEqual((by[4]["enabled"], by[5]["enabled"]), (False, True))  # staff still see it
        self.assertEqual([b["id"] for b in self.listing(READ)["beacons"]], [f"{bb.MAJOR}:5"])
        self.client.put("/api/v1/box-beacons/4", headers=GM, json={"enabled": True})
        self.assertEqual(len(self.listing(READ)["beacons"]), 2)
        self.assertEqual(self.client.put("/api/v1/box-beacons/4", headers=READ, json={"enabled": False}).status_code,
                         403)

    def test_the_field_setting_turns_every_box_off_and_the_join_says_so(self) -> None:
        self.place(4)

        def join_flag() -> bool:
            r = self.client.post("/api/v1/join", headers=GM, json={"role": "zone"})
            self.assertEqual(r.status_code, 200, r.text)
            got = joinfmt.decode(joinfmt.from_text(r.json()["text"]), self.ctrl.join_key)
            return got["box_beacon"]

        self.assertTrue(join_flag())  # on by default
        r = self.client.put("/api/v1/box-beacons", headers=GM, json={"enabled": False})
        self.assertEqual((r.status_code, r.json()["enabled"]), (200, False))
        self.assertEqual(self.listing(READ)["beacons"], [])  # a phone listens for no box
        self.assertTrue(self.boxes()[0]["enabled"])  # the box itself is not disabled: the field's switch is off
        self.assertFalse(self.listing()["box_beacons"]["enabled"])
        self.assertFalse(join_flag())  # key 19: the boxes do not advertise
        self.client.put("/api/v1/box-beacons", headers=GM, json={"enabled": True})
        self.assertTrue(join_flag())
        self.assertEqual(len(self.listing(READ)["beacons"]), 1)
        for bad in ({}, {"enabled": 1}, {"enabled": True, "x": 1}, [True]):
            with self.subTest(bad):
                self.assertEqual(self.client.put("/api/v1/box-beacons", headers=GM, json=bad).status_code, 400)
        self.assertEqual(self.client.put("/api/v1/box-beacons", headers=READ, json={"enabled": False}).status_code,
                         403)


class ReportTests(BoxBeaconCase):
    def setUp(self) -> None:
        super().setUp()
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
        me = self.check_in(self.gid, name="red1")
        self.svc.rate.allow = lambda key: True
        self.gm_patch(self.gid, me["player_id"], team="red", squad=0, role="player")
        self.tok = self.client.post("/api/v1/checkin/token", headers=bearer(me["token"])).json()["token"]

    def report(self, bid: str, expect: int = 200, t: int = 10) -> Any:
        r = self.client.post("/api/v1/positions", headers=bearer(self.tok),
                             json={"source": "ble", "beacon_id": bid, "t": t})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def mine(self) -> dict[str, Any]:
        return self.client.get("/api/v1/positions", headers=bearer(self.tok)).json()["positions"][0]

    def test_a_phone_that_hears_a_box_is_placed_as_with_a_tag(self) -> None:
        self.client.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 2})
        self.place(4, 0.25, 0.75, level=1)
        self.client.put("/api/v1/box-beacons/4", headers=GM, json={"room": "Upstairs office"})
        self.report(f"{bb.MAJOR}:4")
        pos = self.mine()
        self.assertEqual((pos["source"], pos["beacon_id"], pos["room"], pos["level"], pos["x"], pos["y"]),
                         ("ble", f"{bb.MAJOR}:4", "Upstairs office", 1, 0.25, 0.75))
        # The box is moved: the next report puts the player where the box is now.
        self.place(4, 0.5, 0.5, level=0)
        self.report(f"{bb.MAJOR}:4", t=11)
        pos = self.mine()
        self.assertEqual((pos["level"], pos["x"], pos["y"]), (0, 0.5, 0.5))

    def test_a_box_not_placed_disabled_or_off_is_refused(self) -> None:
        self.report(f"{bb.MAJOR}:4", expect=400)  # not placed
        self.place(4)
        self.report(f"{bb.MAJOR}:5", expect=400)  # a box of the game, not placed
        self.report(f"{bb.MAJOR}:77", expect=400)  # no such box
        self.client.put("/api/v1/box-beacons/4", headers=GM, json={"enabled": False})
        self.report(f"{bb.MAJOR}:4", expect=400)
        self.client.put("/api/v1/box-beacons/4", headers=GM, json={"enabled": True})
        self.report(f"{bb.MAJOR}:4")
        self.client.put("/api/v1/box-beacons", headers=GM, json={"enabled": False})
        self.report(f"{bb.MAJOR}:4", expect=400, t=12)

    def test_tags_and_boxes_coexist(self) -> None:
        self.place(4, 0.1, 0.2)
        self.client.post("/api/v1/beacons", headers=GM,
                         json={"uuid": TAG_UUID, "major": 1, "minor": 1, "room": "Lobby", "x": 0.9, "y": 0.9})
        self.assertEqual(self.client.post("/api/v1/beacons", headers=GM, json={
            "uuid": TAG_UUID, "major": bb.MAJOR, "minor": 4, "room": "Clash"}).status_code, 400)
        ids = [b["id"] for b in self.listing(READ)["beacons"]]
        self.assertEqual(sorted(ids), sorted(["1:1", f"{bb.MAJOR}:4"]))
        self.report("1:1", t=20)
        self.assertEqual(self.mine()["room"], "Lobby")
        self.report(f"{bb.MAJOR}:4", t=21)  # the most recent report wins, whatever it heard
        self.assertEqual(self.mine()["room"], "node-4")
        self.report("1:1", t=22)
        self.assertEqual(self.mine()["room"], "Lobby")

    def test_everyone_is_told_when_a_box_moves_with_no_data(self) -> None:
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
                self.client.websocket_connect(f"/api/v1/stream?token={self.tok}") as player:
            gm.receive_json()
            player.receive_json()
            self.place(4)
            self.assertEqual(beacon_messages(gm), [{"type": "beacons"}])
            self.assertEqual(beacon_messages(player), [{"type": "beacons"}])  # bare, for the phone's scan (BLE-20)


if __name__ == "__main__":
    unittest.main()
