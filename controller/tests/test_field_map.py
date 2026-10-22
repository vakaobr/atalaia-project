# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field boundary and the field loaded from a map (decision MF-18, built as MF-19 to MF-30).

The boundary type (an area, one per level, no team, for everyone by default), the API refusing a second
boundary on a level, ATAK's closed shape without a fill, and POST /api/v1/field/levels/{n}/from-map: the
image, its map position from its edges and the boundary in the image's coordinates written together, or
nothing at all when any part is wrong or the write fails.
"""

from __future__ import annotations

import base64
import json
import math
from typing import Any
from unittest import mock

from p3support import GM, READ
from support import wait_for
from test_atak import AtakCase, split_stream

from atalaia_controller import atak, field_map, georef
from atalaia_controller import map_features as mapmod
from atalaia_controller.engine import ControllerError
from atalaia_controller.store import FIELD_IMAGE_MAX

OFF = {"enabled": False, "count": 1, "names": [""]}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 64
# A field near Tomar: the image's edges and an outline of five corners inside them.
BOUNDS = {"north": 39.6020, "south": 39.5980, "west": -8.4040, "east": -8.3980}
OUTLINE = [{"lat": 39.6015, "lon": -8.4030}, {"lat": 39.6012, "lon": -8.3990}, {"lat": 39.5990, "lon": -8.3985},
           {"lat": 39.5984, "lon": -8.4010}, {"lat": 39.5995, "lon": -8.4035}]
SQUARE = [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}, {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}]


def boundary(**kw: Any) -> dict[str, Any]:
    return {"type": "boundary", "shape": "polygon", "points": SQUARE, **kw}


def from_map(**kw: Any) -> dict[str, Any]:
    return {"content_type": "image/png", "image": base64.b64encode(PNG).decode(), "bounds": BOUNDS,
            "outline": OUTLINE, **kw}


class BoundaryModelTests(AtakCase):
    def test_an_area_for_everyone_and_no_team(self) -> None:
        got = mapmod.check(boundary(), OFF)
        self.assertEqual((got["type"], got["shape"], got["team"], got["visibility"]),
                         ("boundary", "polygon", None, "everyone"))
        self.assertEqual(mapmod.check(boundary(visibility="organisers"), OFF)["visibility"], "organisers")
        for bad in (boundary(shape="circle", x=0.5, y=0.5, radius_m=40, points=None),
                    {"type": "boundary", "shape": "point", "x": 0.5, "y": 0.5},
                    boundary(team="red"), boundary(team="red", visibility="team"), boundary(visibility="team")):
            bad = {k: v for k, v in bad.items() if v is not None}
            with self.subTest(body=bad), self.assertRaises(ControllerError):
                mapmod.check(bad, OFF)

    def test_one_per_level(self) -> None:
        c = self.client
        c.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 2})
        first = c.post("/api/v1/field/features", headers=GM, json=boundary())
        self.assertEqual(first.status_code, 201, first.text)
        self.assertEqual(c.post("/api/v1/field/features", headers=GM, json=boundary()).status_code, 409)
        self.assertEqual(c.post("/api/v1/field/features", headers=GM, json=boundary(level=1)).status_code, 201)
        other = c.post("/api/v1/field/features", headers=GM, json={"type": "parking", "shape": "polygon",
                                                                   "points": SQUARE}).json()
        # Changing the boundary itself is fine; turning another area into a second one is not.
        fid = first.json()["id"]
        r = c.put(f"/api/v1/field/features/{fid}", headers=GM, json=boundary(label="Perímetro"))
        self.assertEqual((r.status_code, r.json()["label"]), (200, "Perímetro"))
        self.assertEqual(c.put(f"/api/v1/field/features/{other['id']}", headers=GM, json=boundary()).status_code,
                         409)
        self.assertEqual(mapmod.boundary_id(self.ctrl.store, 0), fid)
        # Everyone sees it (the read token's console too).
        seen = c.get("/api/v1/field/features", headers=READ).json()["features"]
        self.assertIn("boundary", {f["type"] for f in seen})


class AtakBoundaryTests(AtakCase):
    staff = True

    def test_a_closed_shape_without_a_fill(self) -> None:
        self.put_image_and_corners()
        self.running_game()
        fid = self.client.post("/api/v1/field/features", headers=GM, json=boundary()).json()["id"]
        self.udp.drain(0.05)
        self.emitter.cycle(full=True)
        udp = self.events_by_uid(self.udp.drain())
        ev = udp[f"atalaia.field.feature.{fid}"]
        self.assertEqual(ev.get("type"), "u-d-f")
        links = [lk.get("point") for lk in ev.findall("detail/link")]
        self.assertEqual((len(links), links[0]), (len(SQUARE) + 1, links[-1]))  # closed: the first again
        self.assertEqual(ev.find("detail/contact").get("callsign"), "Field boundary")
        self.assertEqual(int(ev.find("detail/strokeColor").get("value")),
                         atak.argb_of(atak.FEATURE_COLOURS["boundary"]))
        self.assertEqual(int(ev.find("detail/fillColor").get("value")) & 0xFF000000, 0)  # transparent fill
        self.assertTrue(wait_for(lambda: len(self.tcp.connections) > 0, 3))
        staff = self.events_by_uid(split_stream(self.tcp.connections[0]))
        self.assertIn(f"atalaia.field.feature.{fid}", staff)


class FromMapTests(AtakCase):
    def post(self, body: Any, level: int = 0, headers: Any = GM, expect: int = 200) -> dict[str, Any]:
        r = self.client.post(f"/api/v1/field/levels/{level}/from-map", headers=headers, json=body)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def test_image_corners_and_boundary_at_once(self) -> None:
        self.assertEqual(self.client.post("/api/v1/field/levels/0/from-map", json=from_map()).status_code, 401)
        self.post(from_map(), headers=READ, expect=403)
        with self.client.websocket_connect("/api/v1/stream?token=gm-secret") as ws:
            ws.receive_json()  # the hello
            out = self.post(from_map(label="Campo da Mata"))
            kinds = set()
            for _ in range(10):
                kinds.add(ws.receive_json()["type"])
                if {"field_image", "field_georef", "map_features"} <= kinds:
                    break
            self.assertLessEqual({"field_image", "field_georef", "map_features"}, kinds)
        self.assertEqual(self.ctrl.store.field_image(0)[:2], ("image/png", PNG))
        # The map position: the image's edges as its two corners, exactly (MF-24).
        geo = self.client.get("/api/v1/field/georef", headers=GM).json()["georef"]
        self.assertEqual(geo["kind"], "corners")
        self.assertEqual(geo["points"], [{"x": 0, "y": 0, "lat": BOUNDS["north"], "lon": BOUNDS["west"]},
                                         {"x": 1, "y": 1, "lat": BOUNDS["south"], "lon": BOUNDS["east"]}])
        self.assertEqual(out["georef"], geo)
        # The boundary: the outline in the image's coordinates; back through the map position it is the
        # outline again (to a millimetre).
        b = out["boundary"]
        self.assertEqual((b["type"], b["shape"], b["label"], b["visibility"], b["level"]),
                         ("boundary", "polygon", "Campo da Mata", "everyone", 0))
        self.assertTrue(out["boundary_new"])
        g = georef.load(self.ctrl.store)
        for p, want in zip(b["points"], OUTLINE):
            lat, lon = g.to_latlon(p["x"], p["y"])
            north_m = (lat - want["lat"]) * georef.EARTH_RADIUS_M * math.pi / 180
            east_m = (lon - want["lon"]) * georef.EARTH_RADIUS_M * math.pi / 180 * math.cos(math.radians(lat))
            self.assertLess(math.hypot(north_m, east_m), 0.001)
        self.assertAlmostEqual(b["points"][0]["x"], (OUTLINE[0]["lon"] - BOUNDS["west"]) / 0.006, places=6)
        self.assertAlmostEqual(b["points"][0]["y"], (BOUNDS["north"] - OUTLINE[0]["lat"]) / 0.004, places=6)
        # Again (a better image): the same boundary is changed, not a second one added.
        again = self.post(from_map(content_type="image/jpeg", image=base64.b64encode(JPEG).decode()))
        self.assertEqual((again["boundary"]["id"], again["boundary_new"]), (b["id"], False))
        self.assertEqual(self.ctrl.store.field_image(0)[0], "image/jpeg")
        self.assertEqual([f["type"] for f in mapmod.every(self.ctrl.store)], ["boundary"])

    def test_a_level_gets_its_own_map_position(self) -> None:
        self.client.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 2})
        self.post(from_map(), level=1)
        self.assertIsNone(georef.load(self.ctrl.store, 0))
        self.assertEqual(georef.load(self.ctrl.store, 1).points[0].lat, BOUNDS["north"])
        self.assertEqual(mapmod.every(self.ctrl.store)[0]["level"], 1)
        self.post(from_map(), level=2, expect=400)  # not a level in use

    def test_refused_and_nothing_written(self) -> None:
        big = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * FIELD_IMAGE_MAX).decode()
        bad = [
            "not an object", from_map(extra=1), from_map(content_type="image/webp"), from_map(image="%%%"),
            from_map(image=base64.b64encode(JPEG).decode()),  # says PNG, is a JPEG
            from_map(image=big), from_map(bounds={**BOUNDS, "north": BOUNDS["south"] - 0.001}),
            from_map(bounds={"north": 39.6}), from_map(bounds={**BOUNDS, "east": 200}),
            from_map(bounds={**BOUNDS, "west": -9.5, "east": -8.0}),  # over 20 km: georef.py refuses
            from_map(outline=OUTLINE[:2]), from_map(outline=OUTLINE * 3),
            from_map(outline=[*OUTLINE[:2], {"lat": 39.70, "lon": -8.40}]),  # a corner outside the image
            from_map(outline=[{"lat": 39.60, "lon": -8.40}] * 3),  # no area
            from_map(outline=[[39.6, -8.4]] * 3), from_map(label="x" * 49),
        ]
        for body in bad:
            with self.subTest(body=str(body)[:80]):
                self.post(body, expect=400)
        self.assertIsNone(self.ctrl.store.field_image(0))
        self.assertIsNone(georef.load(self.ctrl.store))
        self.assertEqual(mapmod.every(self.ctrl.store), [])

    def test_a_failed_write_leaves_the_old_field(self) -> None:
        self.post(from_map())
        before = (self.ctrl.store.field_image(0), self.ctrl.store.get_setting("field.georef"),
                  mapmod.every(self.ctrl.store))
        moved = [{"x": 0, "y": 0, "lat": 39.6030, "lon": -8.4040}, {"x": 1, "y": 1, "lat": 39.5970, "lon": -8.3980}]
        real = self.ctrl.store._db

        def execute(sql: str, *args: Any) -> Any:
            if sql.startswith("UPDATE map_features"):
                raise RuntimeError("disk full")  # after the image and the map position were written
            return real.execute(sql, *args)

        with mock.patch.object(self.ctrl.store, "_db", wraps=real) as db:
            db.execute.side_effect = execute
            with self.assertRaises(RuntimeError):
                self.ctrl.store.set_field_from_map(0, "image/jpeg", JPEG, "field.georef", json.dumps(moved),
                                                   {"type": "boundary", "shape": "polygon", "points": SQUARE})
        after = (self.ctrl.store.field_image(0), self.ctrl.store.get_setting("field.georef"),
                 mapmod.every(self.ctrl.store))
        self.assertEqual(after, before)

    def test_a_full_field_refuses_a_new_boundary_but_not_a_replaced_one(self) -> None:
        with mock.patch.object(mapmod, "FEATURES_MAX", 1):
            self.client.post("/api/v1/field/features", headers=GM,
                             json={"type": "first_aid", "shape": "point", "x": 0.5, "y": 0.5})
            self.post(from_map(), expect=409)
            self.assertIsNone(self.ctrl.store.field_image(0))

    def test_the_check_alone(self) -> None:
        got = field_map.check(from_map(), OFF, 0)
        self.assertEqual((got["content_type"], got["data"], got["georef"].kind), ("image/png", PNG, "corners"))
        self.assertEqual(len(got["boundary"]["points"]), len(OUTLINE))
