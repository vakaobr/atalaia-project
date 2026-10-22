# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Map features: safe zones, respawns, HQs, the car park, first aid, objectives on the field's plan
(the maintainer's request of 2026-10-22, decisions MF-0 to MF-16).

The model's checks and defaults, the store's upgrade of a schema 10 file, the API (GM writes, reads
filtered by who asks), the live stream filtered per connection, the features of levels that go or are
not in use, and the ATAK feed: shapes as CoT drawn shapes, only the features for everyone on the field's
Wi-Fi, all of them to the staff's devices, points and circles for everyone to the remote relay in its
shared narrow form, and drops when a feature goes.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from p3support import GM, READ, bearer
from support import wait_for
from test_atak import BR, PNG, TL, AtakCase, FakeRelay, split_stream

from atalaia_controller import atak, field_levels, sync_format
from atalaia_controller import map_features as mapmod
from atalaia_controller.engine import ControllerError
from atalaia_controller.store import SCHEMA_VERSION, Store

COT = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "cot.json").read_text("utf-8"))
OFF = {"enabled": False, "count": 1, "names": [""]}
SQUARE = [{"x": 0.1, "y": 0.1}, {"x": 0.4, "y": 0.1}, {"x": 0.4, "y": 0.4}, {"x": 0.1, "y": 0.4}]


def point(**kw: Any) -> dict[str, Any]:
    return {"type": "first_aid", "shape": "point", "x": 0.5, "y": 0.5, **kw}


def circle(**kw: Any) -> dict[str, Any]:
    return {"type": "safe_zone", "shape": "circle", "x": 0.25, "y": 0.75, "radius_m": 30, **kw}


def polygon(**kw: Any) -> dict[str, Any]:
    return {"type": "parking", "shape": "polygon", "points": SQUARE, **kw}


class ModelTests(unittest.TestCase):
    def test_shapes_and_defaults(self) -> None:
        got = mapmod.check(point(label="  Posto  médico "), OFF)
        self.assertEqual(got, {"level": 0, "type": "first_aid", "label": "Posto médico", "shape": "point",
                               "x": 0.5, "y": 0.5, "team": None, "visibility": "everyone", "note": ""})
        got = mapmod.check(circle(radius_m=12.345), OFF)
        self.assertEqual((got["radius_m"], got["visibility"]), (12.3, "everyone"))
        got = mapmod.check(polygon(note="Só carros da organização"), OFF)
        self.assertEqual(got["points"], SQUARE)
        self.assertNotIn("x", got)
        # MF-4: a team's respawn or HQ is for that team unless the GM says otherwise.
        self.assertEqual(mapmod.check(circle(type="respawn", team="red"), OFF)["visibility"], "team")
        self.assertEqual(mapmod.check(point(type="hq", team="blue"), OFF)["visibility"], "team")
        self.assertEqual(mapmod.check(point(type="hq", team="blue", visibility="everyone"), OFF)["visibility"],
                         "everyone")
        self.assertEqual(mapmod.check(point(type="objective"), OFF)["visibility"], "everyone")
        self.assertEqual(mapmod.check(point(type="respawn"), OFF)["visibility"], "everyone")  # a shared respawn
        self.assertEqual(mapmod.check(point(visibility="organisers"), OFF)["visibility"], "organisers")
        self.assertEqual(mapmod.check(point(type="other", label="Bar"), OFF)["label"], "Bar")

    def test_refused(self) -> None:
        levels = {"enabled": True, "count": 3, "names": ["", "", ""]}
        bad = [
            "not an object", point(type="toilet"), point(shape="square"), point(type="other"),
            point(colour="red"), point(x=1.5), point(y=-0.1), point(x=True), point(x=float("nan")), {"type": "hq"},
            point(radius_m=10), point(points=SQUARE), circle(radius_m=0.5), circle(radius_m=2001),
            circle(radius_m="30"), polygon(x=0.1), polygon(points=SQUARE[:2]),
            polygon(points=[{"x": i / 20, "y": (i % 2) / 2} for i in range(mapmod.POLYGON_MAX + 1)]),
            polygon(points=[{"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}, {"x": 0.3, "y": 0.3}]),  # on one line
            polygon(points=[{"x": 0.1, "y": 0.1}] * 3), polygon(points=[[0.1, 0.1], [0.2, 0.1], [0.2, 0.2]]),
            polygon(points=[{"x": 0.1, "y": 0.1, "z": 0}, {"x": 0.2, "y": 0.1}, {"x": 0.2, "y": 0.2}]),
            point(visibility="squad"), point(visibility="team"), point(team=""), point(team="x" * 24),
            point(team=" red"), point(team=7), point(label="x" * 49), point(label="a\nb"), point(note="n\tb"),
            point(note="x" * 201), point(level=3), point(level=-1), point(level="1"), point(level=True),
        ]
        for body in bad:
            with self.subTest(body=body), self.assertRaises(ControllerError):
                mapmod.check(body, levels)
        with self.assertRaises(ControllerError):
            mapmod.check(point(level=1), OFF)  # levels off: only level 0
        self.assertEqual(mapmod.check(point(level=2), levels)["level"], 2)

    def test_who_sees_what(self) -> None:
        class V:
            def __init__(self, kind: str, role: str = "player", team: int = 0) -> None:
                self.kind, self.claims = kind, {"role": role, "team": team, "game_id": 1}
                self.is_staff = kind == "gm" or (kind == "player" and role in ("marshal", "gm"))
                self.team, self.game_id = team, 1

        feats = {vis: {"visibility": vis, "team": "red" if vis == "team" else None}
                 for vis in mapmod.VISIBILITIES}
        cases = {(V("gm"), None): {"everyone", "team", "organisers"},
                 (V("read"), None): {"everyone"},
                 (V("player", team=1), "red"): {"everyone", "team"},
                 (V("player", team=2), "blue"): {"everyone"},
                 (V("player", role="marshal", team=2), "blue"): {"everyone", "team", "organisers"},
                 (V("player", role="gm"), None): {"everyone", "team", "organisers"}}
        for (viewer, team), want in cases.items():
            self.assertEqual({k for k, f in feats.items() if mapmod.can_see(viewer, f, team)}, want)
        self.assertFalse(mapmod.can_see(None, feats["everyone"], None))


class StoreUpgradeTests(unittest.TestCase):
    def test_a_schema_10_file_gets_the_table_and_keeps_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            store = Store(path)
            store.set_field_image("image/png", PNG)
            store.close()
            db = sqlite3.connect(path)  # back to schema 10: no map_features table
            db.execute("DROP TABLE map_features")
            db.execute("UPDATE settings SET value = '10' WHERE key = 'schema_version'")
            db.commit()
            db.close()
            store = Store(path)
            self.assertEqual(SCHEMA_VERSION, 11)
            self.assertEqual(store.get_setting("schema_version"), "11")
            self.assertEqual(store.map_features(), [])
            self.assertEqual(store.field_image()[1], PNG)
            fid = store.add_map_feature(0, {"type": "hq", "shape": "point", "x": 0.1, "y": 0.2})
            store.close()
            store = Store(path)  # opening again changes nothing
            self.assertEqual([(f["id"], f["level"], f["data"]["type"]) for f in store.map_features()], [(fid, 0, "hq")])
            self.assertTrue(store.put_map_feature(fid, 0, {"type": "hq", "shape": "point", "x": 0.3, "y": 0.2}))
            self.assertEqual(store.map_feature(fid)["data"]["x"], 0.3)
            self.assertTrue(store.delete_map_feature(fid))
            self.assertFalse(store.delete_map_feature(fid))
            self.assertIsNone(store.map_feature(fid))
            store.close()


class ApiTests(AtakCase):
    def add(self, body: dict[str, Any], expect: int = 201, headers: Any = GM) -> dict[str, Any]:
        r = self.client.post("/api/v1/field/features", headers=headers, json=body)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def seen(self, headers: Any) -> dict[str, str]:
        r = self.client.get("/api/v1/field/features", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        return {f["label"]: f["visibility"] for f in r.json()["features"]}

    def three(self) -> dict[str, int]:
        return {"Hospital": self.add(point(label="Hospital"))["id"],
                "Red respawn": self.add(circle(type="respawn", team="red", label="Red respawn"))["id"],
                "Staff car park": self.add(polygon(label="Staff car park", visibility="organisers"))["id"]}

    def test_gm_writes_and_everyone_reads_what_they_may(self) -> None:
        c = self.client
        self.assertEqual(c.get("/api/v1/field/features").status_code, 401)
        self.assertEqual(c.get("/api/v1/field/features", headers=GM).json(), {"features": []})
        self.add(point(), expect=403, headers=READ)
        self.add(point(type="toilet"), expect=400)
        ids = self.three()
        got = c.get("/api/v1/field/features", headers=GM).json()["features"]
        self.assertEqual([f["id"] for f in got], list(ids.values()))
        respawn = got[1]
        self.assertEqual({k: respawn[k] for k in ("level", "type", "shape", "x", "y", "radius_m", "team", "visibility")},
                         {"level": 0, "type": "respawn", "shape": "circle", "x": 0.25, "y": 0.75, "radius_m": 30.0,
                          "team": "red", "visibility": "team"})
        self.assertIn("updated_at", respawn)
        self.assertEqual(set(self.seen(GM)), set(ids))
        self.assertEqual(self.seen(READ), {"Hospital": "everyone"})
        # Players: a red player sees the red respawn, a blue one does not; a marshal sees everything.
        gid = self.running_game()
        _, red = self.player(gid, "Falcão", "red")
        _, blue = self.player(gid, "Mocho", "blue")
        _, marshal = self.player(gid, "Ana", "blue", role="marshal")
        self.assertEqual(set(self.seen(bearer(red))), {"Hospital", "Red respawn"})
        self.assertEqual(set(self.seen(bearer(blue))), {"Hospital"})
        self.assertEqual(set(self.seen(bearer(marshal))), set(ids))
        # Changed by the GM: the car park for everyone, the respawn to blue.
        r = c.put(f"/api/v1/field/features/{ids['Staff car park']}", headers=GM,
                  json=polygon(label="Staff car park", visibility="everyone"))
        self.assertEqual(r.status_code, 200, r.text)
        c.put(f"/api/v1/field/features/{ids['Red respawn']}", headers=GM,
              json=circle(type="respawn", team="blue", label="Red respawn"))
        self.assertEqual(set(self.seen(bearer(red))), {"Hospital", "Staff car park"})
        self.assertEqual(set(self.seen(bearer(blue))), {"Hospital", "Staff car park", "Red respawn"})
        self.assertEqual(c.put(f"/api/v1/field/features/{ids['Hospital']}", headers=READ, json=point()).status_code, 403)
        self.assertEqual(c.put(f"/api/v1/field/features/{ids['Hospital']}", headers=GM,
                               json=point(shape="circle")).status_code, 400)
        self.assertEqual(c.put("/api/v1/field/features/999", headers=GM, json=point()).status_code, 404)
        # Deleted.
        self.assertEqual(c.delete(f"/api/v1/field/features/{ids['Hospital']}", headers=READ).status_code, 403)
        self.assertEqual(c.delete(f"/api/v1/field/features/{ids['Hospital']}", headers=GM).json(), {"deleted": True})
        self.assertEqual(c.delete(f"/api/v1/field/features/{ids['Hospital']}", headers=GM).status_code, 404)
        self.assertNotIn("Hospital", self.seen(GM))

    def test_a_field_has_at_most_features_max(self) -> None:
        with mock.patch.object(mapmod, "FEATURES_MAX", 2):
            self.add(point())
            self.add(point())
            self.add(point(), expect=409)

    def test_the_stream_gives_each_connection_what_it_may_see(self) -> None:
        gid = self.running_game()
        _, red = self.player(gid, "Falcão", "red")
        _, blue = self.player(gid, "Mocho", "blue")

        def next_features(ws: Any) -> list[dict[str, Any]]:
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "map_features":
                    self.assertEqual(set(msg), {"type", "features"})  # no routing marks
                    return msg["features"]
            self.fail("no map_features message")

        with self.client.websocket_connect("/api/v1/stream?token=gm-secret") as gm, \
                self.client.websocket_connect("/api/v1/stream?token=read-secret") as read, \
                self.client.websocket_connect(f"/api/v1/stream?token={red}") as rws, \
                self.client.websocket_connect(f"/api/v1/stream?token={blue}") as bws:
            for ws in (gm, read, rws, bws):
                self.assertNotIn("map_features", ws.receive_json())  # the hello is unchanged (MF-15)
            self.add(circle(type="respawn", team="red", label="Red respawn"))
            self.assertEqual([f["label"] for f in next_features(gm)], ["Red respawn"])
            self.assertEqual([f["label"] for f in next_features(rws)], ["Red respawn"])
            self.assertEqual(next_features(read), [])
            self.assertEqual(next_features(bws), [])
            self.add(polygon(label="Staff", visibility="organisers"))
            self.assertEqual(len(next_features(gm)), 2)
            self.assertEqual([f["label"] for f in next_features(rws)], ["Red respawn"])
            self.assertEqual(next_features(read), [])
            self.assertEqual(next_features(bws), [])

    def test_levels_that_go_take_their_features_and_levels_off_hide_them(self) -> None:
        c = self.client
        c.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 3})
        self.add(point(label="Ground"))
        self.add(point(label="Roof", level=2))
        self.add(point(label="First", level=1))
        self.assertEqual(set(self.seen(READ)), {"Ground", "Roof", "First"})
        self.add(point(level=3), expect=400)
        # Off: kept, but shown nowhere (MF-8); on again: back.
        c.put("/api/v1/field/levels", headers=GM, json={"enabled": False})
        self.assertEqual(set(self.seen(GM)), {"Ground"})
        self.add(point(level=1), expect=400)
        c.put("/api/v1/field/levels", headers=GM, json={"enabled": True})
        self.assertEqual(set(self.seen(GM)), {"Ground", "Roof", "First"})
        # Fewer levels: level 2's features go with its plan.
        out = c.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 2}).json()
        self.assertEqual(out["removed"], [2])
        self.assertEqual(set(self.seen(GM)), {"Ground", "First"})
        self.assertEqual(len(self.ctrl.store.map_features()), 2)
        self.assertEqual(field_levels.load(self.ctrl.store)["count"], 2)


class AtakFeatureTests(AtakCase):
    staff = True

    def add(self, body: dict[str, Any]) -> int:
        r = self.client.post("/api/v1/field/features", headers=GM, json=body)
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def staff_events(self, before: int = 0) -> dict[str, Any]:
        self.assertTrue(wait_for(lambda: len(self.tcp.connections) > before, 3))
        return self.events_by_uid(split_stream(self.tcp.connections[before]))

    def test_shapes_on_the_map_and_who_gets_them(self) -> None:
        self.put_image_and_corners()
        gid = self.running_game()
        self.place(gid, 4, 0.5, 0.5)
        hospital = self.add(point(label="Hospital", note="Bring the green kit"))
        safe = self.add(circle(label="Safe zone A"))
        car = self.add(polygon())
        red = self.add(circle(type="respawn", team="red", label="Red respawn"))
        staff = self.add(point(type="hq", label="Control", visibility="organisers"))
        self.udp.drain(0.05)
        self.emitter.cycle(full=True)
        udp = self.events_by_uid(self.udp.drain())
        uid = {n: f"atalaia.field.feature.{i}" for n, i in
               (("hospital", hospital), ("safe", safe), ("car", car), ("red", red), ("staff", staff))}
        # MF-12: the field's Wi-Fi gets only the features for everyone; the staff's devices all of them.
        self.assertEqual(set(udp), {"atalaia.field.node.4", uid["hospital"], uid["safe"], uid["car"]})
        tcp = self.staff_events()
        self.assertEqual(set(tcp), {"atalaia.field.node.4", *uid.values()})
        self.assertEqual(self.emitter.status()["features"], 5)
        # A point: a spot marker in the type's colour, its note in the remarks.
        h = udp[uid["hospital"]]
        self.assertEqual((h.get("type"), h.get("how")), ("b-m-p-s-m", "h-e"))
        self.assertEqual(h.find("detail/contact").get("callsign"), "Hospital")
        self.assertEqual(h.find("detail/remarks").text, "Atalaia: First aid. Bring the green kit")
        self.assertEqual(int(h.find("detail/color").get("argb")), atak.argb_of(atak.FEATURE_COLOURS["first_aid"]))
        self.assertAlmostEqual(float(h.find("point").get("lat")), (TL["lat"] + BR["lat"]) / 2, places=6)
        # A circle: ATAK's drawn circle, the radius as the ellipse's axes (cot.json u-d-c-c).
        s = udp[uid["safe"]]
        self.assertEqual(s.get("type"), "u-d-c-c")
        self.assertEqual(s.find("detail/shape/ellipse").attrib, {"major": "30.0", "minor": "30.0", "angle": "360"})
        link = s.find("detail/shape/link")
        self.assertEqual(link.attrib, {"uid": f"{uid['safe']}.Style", "type": "b-x-KmlStyle", "relation": "p-c"})
        self.assertEqual(link.find("Style/LineStyle/color").text, "ffa6b814")  # aabbggrr of 0x14B8A6
        self.assertEqual(s.find("detail/remarks").text, "Atalaia: Safe zone, 30 m")
        self.assertEqual(s.find("detail/labels_on").get("value"), "true")
        self.assertEqual(int(s.find("detail/fillColor").get("value")) & 0xFFFFFFFF,
                         (atak.FILL_ALPHA << 24) | atak.FEATURE_COLOURS["safe_zone"])
        lat = TL["lat"] + (BR["lat"] - TL["lat"]) * 0.75
        self.assertAlmostEqual(float(s.find("point").get("lat")), lat, places=6)
        # A polygon: a closed drawn shape, its first corner again at the end (cot.json u-d-f).
        p = udp[uid["car"]]
        self.assertEqual(p.get("type"), "u-d-f")
        links = [lk.get("point") for lk in p.findall("detail/link")]
        self.assertEqual(len(links), len(SQUARE) + 1)
        self.assertEqual(links[0], links[-1])
        la, lo = (float(v) for v in links[2].split(","))
        self.assertAlmostEqual(la, TL["lat"] + (BR["lat"] - TL["lat"]) * 0.4, places=6)
        self.assertAlmostEqual(lo, TL["lon"] + (BR["lon"] - TL["lon"]) * 0.4, places=6)
        self.assertEqual(p.find("detail/contact").get("callsign"), "Parking")  # no label: the type's name
        # The red respawn and the organisers' HQ: the staff's devices only, said so in the remarks.
        r = tcp[uid["red"]]
        self.assertEqual(int(r.find("detail/strokeColor").get("value")), atak.team_colour("red", ["red", "blue"]))
        self.assertEqual(r.find("detail/remarks").text, "Atalaia: Respawn, red, team only, 30 m")
        self.assertEqual(tcp[uid["staff"]].find("detail/remarks").text, "Atalaia: HQ, organisers only")
        self.assertEqual(tcp[uid["staff"]].find("detail/__group"), None)  # no team: no ATAK team

        # The car park becomes the organisers' and the hospital is deleted: dropped on the Wi-Fi at once.
        before = len(self.tcp.connections)
        self.client.put(f"/api/v1/field/features/{car}", headers=GM, json=polygon(visibility="organisers"))
        self.client.delete(f"/api/v1/field/features/{hospital}", headers=GM)
        self.emitter.cycle(full=False)  # the map_features message asked for everything again
        udp = self.events_by_uid(self.udp.drain())
        for gone in (uid["car"], uid["hospital"]):
            self.assertLess(udp[gone].get("stale"), udp[gone].get("start"))  # drop track
        self.assertGreater(udp[uid["safe"]].get("stale"), udp[uid["safe"]].get("start"))
        tcp = self.staff_events(before)
        self.assertLess(tcp[uid["hospital"]].get("stale"), tcp[uid["hospital"]].get("start"))
        self.assertGreater(tcp[uid["car"]].get("stale"), tcp[uid["car"]].get("start"))  # still the staff's

        # The game ends: every feature is dropped with the boxes.
        self.client.post(f"/api/v1/games/{gid}/end", headers=GM)
        self.emitter.cycle(full=False)
        udp = self.events_by_uid(self.udp.drain())
        self.assertIn(uid["safe"], udp)
        self.assertLess(udp[uid["safe"]].get("stale"), udp[uid["safe"]].get("start"))

    def test_without_a_map_position_nothing_goes(self) -> None:
        self.client.put("/api/v1/field/image", headers={**GM, "Content-Type": "image/png"}, content=PNG)
        self.running_game()
        self.add(point())
        self.udp.drain(0.05)
        sent = self.emitter.cycle(full=True)
        self.assertEqual(sent["udp"], 0)
        self.assertTrue(self.emitter.status()["no_georef"])

    def test_the_largest_events_fit_one_datagram(self) -> None:
        self.put_image_and_corners()
        self.running_game(team_info={"red": {"display_name": "é" * 32}})
        many = [{"x": round(0.5 + 0.45 * math.cos(i * 0.39), 3), "y": round(0.5 + 0.45 * math.sin(i * 0.39), 3)}
                for i in range(mapmod.POLYGON_MAX)]
        long = "\"&<" * 16
        self.add(polygon(points=many, label=long, note="&" * 200, team="red", visibility="everyone"))
        self.add(circle(label=long, note="\"" * 200, team="red", visibility="everyone"))
        self.add(point(label=long, note="'" * 200, team="red", visibility="everyone"))
        self.udp.drain(0.05)
        self.emitter.cycle(full=True)
        got = self.udp.drain()
        self.assertEqual(len(got), 3)
        for data in got:
            self.check_event(data)  # under atak.DATAGRAM_MAX, and cot.json's rules

    def test_the_remote_relay_gets_points_and_circles_for_everyone_in_its_form(self) -> None:
        self.put_image_and_corners()
        self.running_game()
        self.cfg.atak_remote = True
        fake = FakeRelay()
        self.emitter.remote = fake
        pin = self.add(point(type="objective", label="Bridge"))
        ring = self.add(circle())
        self.add(polygon())
        self.add(circle(type="respawn", team="red"))
        self.add(point(visibility="organisers"))
        self.emitter.cycle(full=True)
        got = {}
        for data in fake.events:
            ev = sync_format.cot_event(data.decode("utf-8"))  # the site server's own check
            self.assertTrue(ev["map"])
            got[ev["uid"]] = ev
        self.assertEqual(set(got), {f"atalaia.field.feature.{pin}", f"atalaia.field.feature.{ring}"})
        circle_ev = got[f"atalaia.field.feature.{ring}"]
        self.assertEqual(circle_ev["type"], "b-m-p-s-m")  # the extraction zone's form: the radius as ce
        self.assertIn("ce=\"30.0\"", circle_ev["xml"])
        fake.events.clear()
        self.client.delete(f"/api/v1/field/features/{ring}", headers=GM)
        self.emitter.cycle(full=False)
        drops = [sync_format.cot_event(d.decode("utf-8")) for d in fake.events]
        self.assertEqual([(d["uid"], d["stale"] < d["start"]) for d in drops if d["uid"].endswith(f".{ring}")],
                         [(f"atalaia.field.feature.{ring}", True)])

    def test_cot_vectors_name_the_shape_types(self) -> None:
        for name in (atak.TYPE_CIRCLE, atak.TYPE_POLYGON):
            self.assertIn(name, COT["types"])
            self.assertIn(name, COT["types"][name]["source"])
        for tag in ("shape", "link", "strokeColor", "strokeWeight", "fillColor", "labels_on"):
            self.assertIn(tag, COT["details"])
        self.assertEqual(atak.kml_colour(-1), "ffffffff")              # the circle example's LineStyle
        self.assertEqual(atak.kml_colour(-1761607681), "96ffffff")     # its fillColor and PolyStyle
        self.assertEqual(atak.argb_of(0xFFFFFF, 0x96), -1761607681)
        self.assertEqual(set(atak.FEATURE_NAMES), set(mapmod.TYPES))
        self.assertEqual(set(atak.FEATURE_COLOURS), set(mapmod.TYPES))
