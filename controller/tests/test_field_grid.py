# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field grid (decisions MF-81 to MF-93): lettered rows and numbered columns over a level's plan.

The labels (A..Z, AA..), a place's cell ("C4"), the check of the GM's settings, the API on both paths (level
0 and a level of a building), who may read and change it, the live stream, a restart, fewer levels, and
the grid sent with the field loaded from a map (all or nothing).
"""

from __future__ import annotations

import base64
import json
import unittest
from typing import Any
from unittest import mock

from p3support import GM, READ, P3Case

from atalaia_controller import field_grid
from atalaia_controller.engine import ControllerError

OFF = {"enabled": False, "rows": 8, "cols": 8}
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 64
BOUNDS = {"north": 39.6020, "south": 39.5980, "west": -8.4040, "east": -8.3980}
OUTLINE = [{"lat": 39.6015, "lon": -8.4030}, {"lat": 39.6012, "lon": -8.3990}, {"lat": 39.5990, "lon": -8.3985}]


def from_map(**kw: Any) -> dict[str, Any]:
    return {"content_type": "image/png", "image": base64.b64encode(PNG).decode(), "bounds": BOUNDS,
            "outline": OUTLINE, **kw}


class GridModelTests(unittest.TestCase):
    def test_row_labels_go_on_after_z(self) -> None:
        self.assertEqual([field_grid.row_label(i) for i in (0, 1, 2, 25, 26, 27, 51)],
                         ["A", "B", "C", "Z", "AA", "AB", "AZ"])
        self.assertEqual(field_grid.row_label(52), "BA")
        self.assertEqual(field_grid.row_label(26 + 26 * 26), "AAA")

    def test_a_places_cell(self) -> None:
        grid = {"enabled": True, "rows": 8, "cols": 10}
        self.assertEqual(field_grid.cell(grid, 0, 0), "A1")
        self.assertEqual(field_grid.cell(grid, 0.35, 0.3), "C4")  # 0.35 x 10 = 3.5: column 4; 0.3 x 8 = 2.4: C
        self.assertEqual(field_grid.cell(grid, 1, 1), "H10")       # the far edges are in the last cell
        self.assertEqual(field_grid.cell(grid, 0.0999, 0.125), "B1")  # a line belongs to the cell after it
        wide = {"enabled": True, "rows": 30, "cols": 52}
        self.assertEqual(field_grid.cell(wide, 0.999, 0.89), "AA52")  # 26.7: row 26
        self.assertIsNone(field_grid.cell({**grid, "enabled": False}, 0.5, 0.5))
        self.assertIsNone(field_grid.cell(grid, 1.2, 0.5))

    def test_the_check(self) -> None:
        self.assertEqual(field_grid.check({"enabled": True}, OFF), {"enabled": True, "rows": 8, "cols": 8})
        self.assertEqual(field_grid.check({"enabled": True, "rows": 52, "cols": 1}, OFF),
                         {"enabled": True, "rows": 52, "cols": 1})
        self.assertEqual(field_grid.check({"enabled": False}, {"enabled": True, "rows": 3, "cols": 4}),
                         {"enabled": False, "rows": 3, "cols": 4})  # off keeps the numbers for next time
        for bad in (None, [], {}, {"enabled": "yes"}, {"enabled": True, "rows": 0}, {"enabled": True, "rows": 53},
                    {"enabled": True, "cols": 2.5}, {"enabled": True, "cols": True}, {"enabled": True, "cols": "4"},
                    {"enabled": True, "size": 4}):
            with self.subTest(body=bad), self.assertRaises(ControllerError):
                field_grid.check(bad, OFF)


class GridApiTests(P3Case):
    def test_off_until_the_gm_sets_it_and_kept_across_a_restart(self) -> None:
        c = self.client
        self.assertEqual(c.get("/api/v1/field/grid", headers=READ).json(), {"level": 0, "grid": OFF})
        self.assertEqual(c.get("/api/v1/field", headers=READ).json()["levels"]["levels"][0]["grid"], OFF)
        self.assertEqual(c.get("/api/v1/field/grid").status_code, 401)
        self.assertEqual(c.put("/api/v1/field/grid", headers=READ, json={"enabled": True}).status_code, 403)
        r = c.put("/api/v1/field/grid", headers=GM, json={"enabled": True, "rows": 6, "cols": 9})
        self.assertEqual((r.status_code, r.json()), (200, {"level": 0, "grid": {"enabled": True, "rows": 6, "cols": 9}}))
        r = c.put("/api/v1/field/grid", headers=GM, json={"enabled": True, "rows": 27, "colour": "red"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("unknown fields", r.text)
        self.assertEqual(c.put("/api/v1/field/grid", headers=GM, json={"enabled": True, "rows": 53}).status_code, 400)
        self.restart()
        c = self.client
        want = {"enabled": True, "rows": 6, "cols": 9}
        self.assertEqual(c.get("/api/v1/field/grid", headers=READ).json()["grid"], want)
        self.assertEqual(c.get("/api/v1/field/levels/0/grid", headers=READ).json()["grid"], want)
        self.assertEqual(c.get("/api/v1/field/levels", headers=READ).json()["levels"][0]["grid"], want)
        # Off keeps the rows and columns; a new plan keeps the grid (it is not places on the image).
        r = c.put("/api/v1/field/levels/0/grid", headers=GM, json={"enabled": False})
        self.assertEqual(r.json()["grid"], {**want, "enabled": False})
        c.put("/api/v1/field/grid", headers=GM, json={"enabled": True})
        c.put("/api/v1/field/image", headers={**GM, "Content-Type": "image/png"}, content=PNG)
        self.assertEqual(c.get("/api/v1/field/grid", headers=READ).json()["grid"], want)

    def test_a_grid_per_level_and_fewer_levels(self) -> None:
        c = self.client
        self.assertEqual(c.get("/api/v1/field/levels/1/grid", headers=READ).status_code, 404)
        self.assertEqual(c.put("/api/v1/field/levels/1/grid", headers=GM, json={"enabled": True}).status_code, 400)
        c.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 3})
        r = c.put("/api/v1/field/levels/2/grid", headers=GM, json={"enabled": True, "rows": 4, "cols": 5})
        self.assertEqual(r.status_code, 200, r.text)
        levels = c.get("/api/v1/field/levels", headers=READ).json()["levels"]
        self.assertEqual([lv["grid"] for lv in levels], [OFF, OFF, {"enabled": True, "rows": 4, "cols": 5}])
        self.assertEqual(c.put("/api/v1/field/levels/10/grid", headers=GM, json={"enabled": True}).status_code, 400)
        # Fewer levels: the grid of the level that went goes with it; coming back, it is off again.
        c.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 2})
        self.assertIsNone(self.ctrl.store.get_setting("field.grid.2"))
        c.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 3})
        self.assertEqual(c.get("/api/v1/field/levels/2/grid", headers=READ).json()["grid"], OFF)

    def test_the_stream_says_when_it_changes(self) -> None:
        with self.client.websocket_connect("/api/v1/stream?token=read-secret") as ws:
            ws.receive_json()  # hello
            self.client.put("/api/v1/field/grid", headers=GM, json={"enabled": True, "rows": 3, "cols": 4})
            msg = ws.receive_json()
            self.assertEqual(msg, {"type": "field_grid", "level": 0,
                                   "grid": {"enabled": True, "rows": 3, "cols": 4}})

    def test_sent_with_the_field_from_a_map(self) -> None:
        c = self.client
        r = c.post("/api/v1/field/levels/0/from-map", headers=GM,
                   json=from_map(grid={"enabled": True, "rows": 5, "cols": 7}))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["grid"], {"enabled": True, "rows": 5, "cols": 7})
        self.assertEqual(c.get("/api/v1/field/grid", headers=READ).json()["grid"],
                         {"enabled": True, "rows": 5, "cols": 7})
        # Without a grid, the level's stays as it was.
        r = c.post("/api/v1/field/levels/0/from-map", headers=GM, json=from_map())
        self.assertEqual(r.json()["grid"], {"enabled": True, "rows": 5, "cols": 7})
        # A wrong grid refuses the whole request: nothing is written.
        before = (self.ctrl.store.field_image(0), self.ctrl.store.get_setting("field.georef"))
        r = c.post("/api/v1/field/levels/0/from-map", headers=GM,
                   json=from_map(bounds={**BOUNDS, "north": 39.6030}, grid={"enabled": True, "rows": 99}))
        self.assertEqual(r.status_code, 400)
        self.assertIn("grid: rows", r.text)
        self.assertEqual((self.ctrl.store.field_image(0), self.ctrl.store.get_setting("field.georef")), before)

    def test_from_a_map_all_or_nothing_with_the_grid(self) -> None:
        """A write failing after the grid was written leaves the grid as it was (one transaction)."""
        c = self.client
        c.put("/api/v1/field/grid", headers=GM, json={"enabled": True, "rows": 2, "cols": 2})
        real = self.ctrl.store._db

        def execute(sql: str, *args: Any) -> Any:
            if sql.startswith("INSERT INTO map_features"):
                raise RuntimeError("disk full")
            return real.execute(sql, *args)

        with mock.patch.object(self.ctrl.store, "_db", wraps=real) as db:
            db.execute.side_effect = execute
            with self.assertRaises(RuntimeError):
                self.ctrl.store.set_field_from_map(
                    0, "image/png", PNG, "field.georef", json.dumps([]), {"type": "boundary"},
                    (("field.grid", field_grid.dump({"enabled": True, "rows": 9, "cols": 9})),))
        self.assertEqual(field_grid.load(self.ctrl.store), {"enabled": True, "rows": 2, "cols": 2})


if __name__ == "__main__":
    unittest.main()
