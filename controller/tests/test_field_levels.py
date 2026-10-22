# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Field levels: a multi-story building with a floor plan per level (decisions ML-0 to ML-12).

The store's upgrade of a schema 8 file (its one image becomes level 0's plan), the levels' API
(on and off, their number and names, a plan per level, the old single-image endpoints as level 0),
boxes' positions with a level, players' reports with a level, a level's georeference (its own or
level 0's), the ATAK remarks that name the level, and a scenario box's level.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from typing import Any

from p3support import GM, READ, bearer
from support import wait_for
from test_atak import BR, PNG, TL, AtakCase, split_stream

from atalaia_controller import atak, field_levels, georef
from atalaia_controller.scenarios import compile_scenario, load, validate
from atalaia_controller.store import SCHEMA_VERSION, Store

JPG = b"\xff\xd8\xff\xe0" + b"\1" * 40


class StoreUpgradeTests(unittest.TestCase):
    def test_a_schema_8_file_keeps_its_image_as_level_0(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "old.db")
            db = sqlite3.connect(path)
            db.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            db.execute("INSERT INTO settings VALUES ('schema_version', '8')")
            db.execute("CREATE TABLE field_image (id INTEGER PRIMARY KEY CHECK (id = 1), content_type TEXT NOT NULL, "
                       "data BLOB NOT NULL, updated_at REAL NOT NULL)")
            db.execute("INSERT INTO field_image VALUES (1, 'image/png', ?, 12.5)", (PNG,))
            db.execute("CREATE TABLE positions (game_id INTEGER NOT NULL, node_id INTEGER NOT NULL, x REAL NOT NULL, "
                       "y REAL NOT NULL, PRIMARY KEY (game_id, node_id))")
            db.execute("INSERT INTO positions VALUES (1, 4, 0.25, 0.75)")
            db.commit()
            db.close()
            store = Store(path)
            self.assertEqual(store.field_image(), ("image/png", PNG, 12.5))
            self.assertEqual(store.field_image(0), store.field_image())
            self.assertEqual(store.positions(1), {4: {"x": 0.25, "y": 0.75, "level": 0}})
            self.assertEqual(store.get_setting("schema_version"), str(SCHEMA_VERSION))  # 9 or later
            self.assertEqual(field_levels.load(store), {"enabled": False, "count": 1, "names": [""]})
            store.close()
            # The old table is gone, and opening again changes nothing.
            names = {r[0] for r in sqlite3.connect(path).execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("field_image", names)
            store = Store(path)
            self.assertEqual(store.field_images(), {0: ("image/png", len(PNG), 12.5)})
            store.close()

    def test_a_new_file_without_an_image(self) -> None:
        store = Store(":memory:")
        self.assertIsNone(store.field_image())
        self.assertEqual(store.set_position(1, 4, 0.5, 0.5), 0)
        self.assertEqual(store.set_position(1, 4, 0.5, 0.5, 3), 3)
        self.assertEqual(store.set_position(1, 4, 0.1, 0.2), 3)  # None keeps the level
        self.assertEqual(store.move_positions_to_level0(3), 1)
        self.assertEqual(store.positions(1)[4], {"x": 0.1, "y": 0.2, "level": 0})
        with self.assertRaises(ValueError):
            store.set_field_image("image/png", PNG, 10)
        store.close()


class LevelsApiTests(AtakCase):
    def levels(self, body: dict[str, Any], expect: int = 200) -> dict[str, Any]:
        r = self.client.put("/api/v1/field/levels", headers=GM, json=body)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def plan(self, level: int, data: bytes = PNG, ctype: str = "image/png", expect: int = 200) -> Any:
        r = self.client.put(f"/api/v1/field/levels/{level}/image", headers={**GM, "Content-Type": ctype},
                            content=data)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def test_off_by_default_and_the_old_endpoints_are_level_0(self) -> None:
        c = self.client
        got = c.get("/api/v1/field/levels", headers=READ).json()
        self.assertEqual((got["enabled"], got["count"], got["in_use"]), (False, 1, 1))
        c.put("/api/v1/field/image", headers={**GM, "Content-Type": "image/png"}, content=PNG)
        self.assertEqual(c.get("/api/v1/field/levels/0/image", headers=READ).content, PNG)
        self.assertEqual(c.get("/api/v1/field", headers=READ).json()["levels"]["levels"][0]["image"]["bytes"], len(PNG))
        # Levels are off: level 1 is not in use.
        self.assertEqual(c.get("/api/v1/field/levels/1/image", headers=READ).status_code, 404)
        self.plan(1, expect=400)
        r = c.put(f"/api/v1/games/{self.new_game()['id']}/positions/4", headers=GM, json={"x": 0.5, "y": 0.5, "level": 1})
        self.assertEqual(r.status_code, 400, r.text)

    def test_three_levels_a_plan_each_and_names(self) -> None:
        c = self.client
        self.assertEqual(c.put("/api/v1/field/levels", headers=READ, json={"enabled": True}).status_code, 403)
        out = self.levels({"enabled": True, "count": 3, "names": ["Cave", "R/C", "1.º andar"]})
        self.assertEqual((out["in_use"], out["names"], out["removed"]), (3, ["Cave", "R/C", "1.º andar"], []))
        self.plan(0)
        self.plan(1, JPG, "image/jpeg")
        self.plan(2, PNG + b"2")
        self.plan(3, expect=400)                     # only 3 levels
        self.plan(1, b"text", "text/plain", expect=415)
        self.assertEqual(c.get("/api/v1/field/levels/1/image", headers=READ).content, JPG)
        self.assertEqual(c.get("/api/v1/field/levels/1/image", headers=READ).headers["content-type"], "image/jpeg")
        self.assertEqual(c.get("/api/v1/field/levels/1/image", headers=READ).headers["cache-control"], "no-store")
        view = c.get("/api/v1/field/levels", headers=READ).json()
        self.assertEqual([lv["image"]["bytes"] for lv in view["levels"]], [len(PNG), len(JPG), len(PNG) + 1])
        self.assertEqual(c.put("/api/v1/field/levels/1/image", headers={**READ, "Content-Type": "image/png"},
                               content=PNG).status_code, 403)
        # Refused: a count out of range, a name too long or on two lines, unknown fields.
        for bad in ({"enabled": True, "count": 1}, {"enabled": True, "count": 11}, {"enabled": "yes"},
                    {"enabled": True, "names": ["x" * 33]}, {"enabled": True, "names": ["a\nb"]},
                    {"enabled": True, "count": 2, "names": ["a", "b", "c"]}, {"enabled": True, "floors": 2}):
            self.levels(bad, expect=400)
        # A name is trimmed; names not given are kept.
        out = self.levels({"enabled": True, "names": ["  Cave  -1 "]})
        self.assertEqual(out["names"], ["Cave -1", "R/C", "1.º andar"])
        # Deleting a level's plan.
        self.assertTrue(c.delete("/api/v1/field/levels/2/image", headers=GM).json()["deleted"])
        self.assertEqual(c.get("/api/v1/field/levels/2/image", headers=READ).status_code, 404)

    def test_turning_off_keeps_everything_and_on_brings_it_back(self) -> None:
        gid = self.new_game()["id"]
        self.levels({"enabled": True, "count": 3})
        self.plan(2)
        self.place_on(gid, 4, 0.3, 0.4, 2)
        out = self.levels({"enabled": False})
        self.assertEqual((out["enabled"], out["count"], out["in_use"], out["removed"]), (False, 3, 1, []))
        self.assertEqual(self.client.get("/api/v1/field/levels/2/image", headers=READ).status_code, 404)
        self.assertEqual(self.ctrl.store.field_image(2)[1], PNG)        # kept
        self.assertEqual(self.positions(gid)["4"]["level"], 2)          # kept; shown on level 0 by clients
        self.assertEqual(field_levels.shown(field_levels.load(self.ctrl.store), 2), 0)
        # Moved while off, without a level: it keeps level 2.
        self.place_on(gid, 4, 0.6, 0.6)
        self.assertEqual(self.positions(gid)["4"]["level"], 2)
        out = self.levels({"enabled": True})
        self.assertEqual((out["count"], out["in_use"]), (3, 3))
        self.assertEqual(self.client.get("/api/v1/field/levels/2/image", headers=READ).content, PNG)

    def test_fewer_levels_delete_their_plans_and_move_their_boxes(self) -> None:
        gid = self.new_game()["id"]
        self.levels({"enabled": True, "count": 4})
        self.plan(2)
        self.plan(3)
        self.client.put("/api/v1/field/levels/3/georef", headers=GM, json={"points": [TL, BR]})
        self.place_on(gid, 4, 0.3, 0.4, 3)
        out = self.levels({"enabled": True, "count": 2})
        self.assertEqual(out["removed"], [2, 3])
        self.assertIsNone(self.ctrl.store.field_image(3))
        self.assertIsNone(georef.load(self.ctrl.store, 3))
        self.assertEqual(self.positions(gid)["4"], {"x": 0.3, "y": 0.4, "level": 0})

    def test_positions_carry_their_level_on_the_stream(self) -> None:
        gid = self.new_game()["id"]
        self.levels({"enabled": True, "count": 3})
        with self.client.websocket_connect("/api/v1/stream?token=read-secret") as ws:
            ws.receive_json()
            self.place_on(gid, 4, 0.5, 0.25, 2)
            for _ in range(20):
                msg = ws.receive_json()
                if msg["type"] == "position":
                    break
            self.assertEqual(msg, {"type": "position", "game": gid, "node_id": 4, "x": 0.5, "y": 0.25, "level": 2})
        for bad in (True, "1", 1.0, -1, 3):
            r = self.client.put(f"/api/v1/games/{gid}/positions/4", headers=GM, json={"x": 0.5, "y": 0.5, "level": bad})
            self.assertEqual(r.status_code, 400, (bad, r.text))
        self.assertEqual(self.positions(gid)["4"]["level"], 2)

    def test_a_level_shares_level_0s_georeference_unless_it_has_its_own(self) -> None:
        c = self.client
        self.levels({"enabled": True, "count": 2})
        self.put_image_and_corners()
        got = c.get("/api/v1/field/levels/1/georef", headers=READ).json()
        self.assertFalse(got["own"])
        self.assertEqual(got["georef"]["points"], [TL, BR])
        self.assertEqual(c.put("/api/v1/field/levels/1/georef", headers=GM, json={"points": [TL, BR]}).status_code,
                         409)  # no plan on level 1 yet
        self.plan(1)
        own = [{**TL, "lat": 38.7250}, {**BR, "lat": 38.7210}]
        r = c.put("/api/v1/field/levels/1/georef", headers=GM, json={"points": own})
        self.assertEqual(r.status_code, 200, r.text)
        got = c.get("/api/v1/field/levels/1/georef", headers=READ).json()
        self.assertEqual((got["own"], got["georef"]["points"][0]["lat"]), (True, 38.725))
        self.assertTrue(c.get("/api/v1/field/levels", headers=READ).json()["levels"][1]["own_georef"])
        # A new plan on level 1 clears its own points only.
        self.assertTrue(self.plan(1, PNG + b"x")["georef_cleared"])
        self.assertFalse(c.get("/api/v1/field/levels/1/georef", headers=READ).json()["own"])
        self.assertIsNotNone(c.get("/api/v1/field/georef", headers=READ).json()["georef"])

    def test_atak_places_a_box_by_its_levels_georeference_and_names_the_level(self) -> None:
        self.levels({"enabled": True, "count": 2, "names": ["R/C", "1.º andar"]})
        self.put_image_and_corners()
        self.plan(1)
        gid = self.running_game()
        self.place_on(gid, 4, 0.5, 0.5, 0)
        self.place_on(gid, 5, 0.0, 1.0, 1)
        self.udp.drain(0.05)
        self.emitter.cycle(full=True)
        got = self.events_by_uid(self.udp.drain())
        self.assertEqual(got["atalaia.field.node.4"].find("detail/remarks").text, "Atalaia: -, R/C")
        self.assertEqual(got["atalaia.field.node.5"].find("detail/remarks").text, "Atalaia: -, 1.º andar")
        self.assertAlmostEqual(float(got["atalaia.field.node.5"].find("point").get("lat")), BR["lat"], places=6)
        self.assertEqual(got["atalaia.field.node.5"].find("point").get("hae"), "9999999.0")  # ML-7: no height
        # Level 1 gets its own points: box 5 moves on the map with them.
        own = [{**TL, "lat": 38.7340}, {**BR, "lat": 38.7300}]
        self.client.put("/api/v1/field/levels/1/georef", headers=GM, json={"points": own})
        self.emitter.cycle(full=True)
        got = self.events_by_uid(self.udp.drain())
        self.assertAlmostEqual(float(got["atalaia.field.node.5"].find("point").get("lat")), 38.73, places=6)
        # Levels off: no level in the remarks, every box by level 0's points.
        self.levels({"enabled": False})
        self.emitter.cycle(full=True)
        got = self.events_by_uid(self.udp.drain())
        self.assertEqual(got["atalaia.field.node.5"].find("detail/remarks").text, "Atalaia: -")
        self.assertAlmostEqual(float(got["atalaia.field.node.5"].find("point").get("lat")), BR["lat"], places=6)

    # --- helpers ---------------------------------------------------------------------

    def place_on(self, gid: int, node: int, x: float, y: float, level: Any = None) -> None:
        body = {"x": x, "y": y} if level is None else {"x": x, "y": y, "level": level}
        r = self.client.put(f"/api/v1/games/{gid}/positions/{node}", headers=GM, json=body)
        self.assertEqual(r.status_code, 200, r.text)

    def positions(self, gid: int) -> dict[str, Any]:
        return self.client.get(f"/api/v1/games/{gid}/positions", headers=READ).json()


class PlayerLevelTests(AtakCase):
    players = True
    staff = True

    def report(self, tok: str, expect: int = 200, **extra: Any) -> None:
        body = {"lat": 38.7221, "lon": -9.1391, "accuracy_m": 6.0, "source": "gps", "t": 2, **extra}
        r = self.client.post("/api/v1/positions", headers=bearer(tok), json=body)
        self.assertEqual(r.status_code, expect, r.text)

    def mine(self, gid: int, pid: str) -> dict[str, Any]:
        return self.ctrl.store.player_positions(gid)[pid]

    def test_a_players_level_is_kept_until_they_change_it(self) -> None:
        self.client.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 3,
                                                                    "names": ["R/C", "1.º andar", "2.º andar"]})
        self.put_image_and_corners()
        gid = self.running_game()
        pid, tok = self.player(gid, "Falcão", "red")
        self.assertNotIn("level", self.mine(gid, pid))           # never said: not known (ML-5)
        self.report(tok, level=2)
        self.assertEqual(self.mine(gid, pid)["level"], 2)
        self.report(tok)                                          # no level: the last one stays
        self.assertEqual(self.mine(gid, pid)["level"], 2)
        self.emitter.cycle(full=True)  # the staff's ATAK: the level the phone gave, by its name (ML-7)
        self.assertTrue(wait_for(lambda: "Atalaia: red, player, 2.º andar" in self.player_remarks(), 3),
                        self.player_remarks())
        self.report(tok, level=None)                              # null: not known any more
        self.assertNotIn("level", self.mine(gid, pid))
        for bad in (10, -1, True, "1", 1.5):
            self.report(tok, expect=400, level=bad)
        # The level reaches the player's own view of positions.
        got = self.client.get("/api/v1/positions", headers=bearer(tok)).json()["positions"]
        self.assertEqual([p.get("level") for p in got], [None])

    def player_remarks(self) -> list[str]:
        events = (self.check_event(e) for e in split_stream(b"".join(self.tcp.connections)))
        return [r.find("detail/remarks").text for r in events if r.get("type") == atak.TYPE_PLAYER]


class ScenarioLevelTests(unittest.TestCase):
    MANIFEST = """
id: org.club.tower
version: 1
name: Tower
teams: [red, blue]
nodes:
  roof: { role: objective, level: 3 }
  hall: { role: objective }
objectives:
  - { id: roof, name: Take the roof, type: capture_and_hold, target: roof, params: { hold_ms: 3000 } }
"""

    def test_a_box_may_say_its_level(self) -> None:
        m = load(self.MANIFEST)
        self.assertEqual([p for p in validate(m) if p.level == "error"], [])
        package = compile_scenario(m)
        self.assertIn("level: 3", package.files["mode.yaml"])

    def test_a_bad_level_is_an_error(self) -> None:
        for bad in ("10", "-1", "true", "'2'", "1.5"):
            m = load(self.MANIFEST.replace("level: 3", f"level: {bad}"))
            self.assertIn("bad_level", [p.code for p in validate(m)], bad)
        m = load(self.MANIFEST.replace("hall: { role: objective }", "vip: { player: true, role: vip, level: 1 }"))
        self.assertIn("bad_level", [p.code for p in validate(m)])


if __name__ == "__main__":
    unittest.main()
