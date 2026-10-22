# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the interactive game (live.py) and the web view's server (web.py).

They need the shared core library and are skipped without it.
"""

from __future__ import annotations

import http.client
import json
import threading
import unittest
from pathlib import Path

from atalaia_sim.core import Core, find_library
from atalaia_sim.live import LiveError, LiveGame, ReloadError
from atalaia_sim.mode import load_mode
from atalaia_sim.sim import Simulation
from atalaia_sim.web import make_server

REPO = Path(__file__).resolve().parents[2]


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()


def live(mode: str, **params) -> LiveGame:
    m = load_mode(REPO / "modes" / mode)
    resolved = m.resolve_params(params, ["red", "blue"])
    role = next(iter(m.roles))
    return LiveGame(lambda: Simulation(CORE, m, {role: role}, ["red", "blue"], resolved))


def events(game: LiveGame, type_: str) -> list:
    return [e for e in game.sim.arrivals if e.type == type_]


@unittest.skipIf(CORE is None, "the shared core library is not built")
class LiveGameTests(unittest.TestCase):
    def test_holding_captures_exactly_on_time(self):
        game = live("domination", capture_hold_ms=3000)
        game.act("start", {})
        game.act("step", {"seconds": 1})
        game.act("hold", {"node": "zone", "team": "blue"})
        game.act("step", {"seconds": 2.9})
        self.assertEqual(events(game, "zone.captured"), [])
        game.act("step", {"seconds": 0.1})
        [captured] = events(game, "zone.captured")
        self.assertEqual((captured.t_ms, captured.team), (4000, "blue"))
        self.assertEqual(game.snapshot()["nodes"][0]["hold"], {"team": "blue", "ms": 3000})
        game.act("release", {"node": "zone"})
        self.assertIsNone(game.snapshot()["nodes"][0]["hold"])

    def test_bomb_arms_and_explodes(self):
        game = live("bomb", fuse_s=60)
        game.act("start", {})
        game.act("hold", {"node": "bomb", "team": "red"})
        game.act("step", {"seconds": 5})
        game.act("release", {"node": "bomb"})
        self.assertEqual([e.t_ms for e in events(game, "bomb.armed")], [5000])
        game.act("step", {"seconds": 60})
        self.assertEqual([e.t_ms for e in events(game, "bomb.exploded")], [65000])
        screen = game.snapshot()["nodes"][0]["screen"]
        self.assertEqual(screen["args"], ["exploded", {"team": "red"}])
        self.assertTrue(all(e.wire_bytes for e in game.sim.arrivals))

    def test_clock_follows_real_time_at_its_speed(self):
        game = live("domination")
        game.act("start", {})
        game.act("clock", {"speed": 10})
        game.tick(100.0)
        game.tick(100.25)
        self.assertEqual(game.sim.time_ms, 2500)
        game.tick(200.0)  # a long gap catches up at most MAX_CATCH_UP_S
        self.assertEqual(game.sim.time_ms, 7500)
        game.act("clock", {"running": False})
        game.tick(201.0)
        self.assertEqual(game.sim.time_ms, 7500)

    def test_pause_stops_time_and_releases_holds(self):
        game = live("domination")
        game.act("start", {})
        game.act("hold", {"node": "zone", "team": "red"})
        game.act("pause", {})
        self.assertEqual(game.holds, {})
        self.assertEqual(len(events(game, "game.pause")), 1)
        with self.assertRaises(LiveError):
            game.act("step", {"seconds": 1})
        game.tick(0.0)
        game.tick(0.3)
        self.assertEqual(game.sim.time_ms, 0)
        game.act("resume", {})
        game.act("step", {"seconds": 1})
        self.assertEqual(game.sim.time_ms, 1000)

    def test_end_and_reset(self):
        game = live("domination")
        game.act("start", {})
        game.act("end", {})
        state = game.snapshot()
        self.assertTrue(state["game"]["ended"])
        self.assertEqual(state["nodes"][0]["status"], "ended")
        generation = state["generation"]
        game.act("reset", {})
        state = game.snapshot()
        self.assertEqual(state["generation"], generation + 1)
        self.assertEqual((state["events_total"], state["game"]["started"]), (0, False))

    def test_bad_actions(self):
        game = live("domination")
        for action, args in (("press", {"node": "zone", "team": "red"}), ("pause", {}),
                             ("step", {"seconds": 1}), ("nope", {})):
            with self.subTest(action):
                with self.assertRaises(LiveError):
                    game.act(action, args)
        game.act("start", {})
        for action, args in (("start", {}), ("hold", {"node": "nowhere", "team": "red"}),
                             ("hold", {"node": "zone", "team": "green"}), ("press", {"node": "zone"}),
                             ("clock", {"speed": 7})):
            with self.subTest(action):
                with self.assertRaises(LiveError):
                    game.act(action, args)

    def test_last_input_shows_presses_the_mode_ignores(self):
        game = live("domination")
        game.act("start", {})
        game.act("press", {"node": "zone", "team": "red"})
        state = game.snapshot()
        self.assertEqual(state["nodes"][0]["input"],
                         {"t": 0, "type": "team_input.press", "data": {"team": "red"}, "accepted": True})
        self.assertEqual(state["events_total"], 1)  # domination reacts only to holds

    def test_snapshot_sends_only_new_events(self):
        game = live("domination")
        game.act("start", {})
        first = game.snapshot()
        self.assertEqual(first["events_total"], 1)
        game.act("press", {"node": "zone", "team": "red"})
        game.act("end", {})
        later = game.snapshot(since=first["events_total"])
        self.assertEqual(later["events_from"], 1)
        self.assertEqual([e["type"] for e in later["events"]], ["game.end"])
        self.assertEqual(game.snapshot(since=99)["events_from"], 0)  # stale index: start over


def mode_files(mode: str) -> dict:
    """A mode folder's files as the mode editor sends them to POST /api/reload."""
    folder = REPO / "modes" / mode
    field = folder / "field.lua"
    return {"mode_yaml": (folder / "mode.yaml").read_text(encoding="utf-8"),
            "node_lua": (folder / "node.lua").read_text(encoding="utf-8"),
            "field_lua": field.read_text(encoding="utf-8") if field.exists() else None}


SMALL_MODE = """id: org.test.small
version: 0.1.0
roles:
  zone: {}
params:
  points: { type: int, min: 1, max: 9, default: 1 }
"""


@unittest.skipIf(CORE is None, "the shared core library is not built")
class FieldScriptAndReloadTests(unittest.TestCase):
    """The web view's controller (field.lua) and POST /api/reload's game side (phase 5 plan phase 2)."""

    def test_holdall_plays_live_with_its_field_script(self):
        m = load_mode(REPO / "modes" / "holdall")
        params = m.resolve_params({"tick_s": 5}, ["red", "blue"])
        game = LiveGame(lambda: Simulation(CORE, m, {"alpha": "zone", "bravo": "zone"}, ["red", "blue"], params))
        self.addCleanup(game.close)
        game.act("start", {})
        for node in ("alpha", "bravo"):
            game.act("hold", {"node": node, "team": "red"})
            game.act("step", {"seconds": 3})
            game.act("release", {"node": node})
        game.act("step", {"seconds": 10})
        state = game.snapshot()
        controller = state["controller"]
        self.assertEqual(controller["status"], "running")
        self.assertGreater(controller["scores"]["red"], 0)
        self.assertEqual(state["scores"]["red"], controller["scores"]["red"])
        self.assertIn("holdall.scoring_start", [e["type"] for e in state["events"] if e["node"] == "controller"])
        self.assertIsNone(live("domination").snapshot()["controller"])  # no field.lua, no controller

    def test_reload_swaps_the_mode_and_starts_it(self):
        game = live("domination")
        self.addCleanup(game.close)
        generation = game.generation
        errors = game.reload(**mode_files("holdall"), nodes={"zone1": "zone", "zone2": "zone"},
                             params={"tick_s": 5})
        self.assertEqual(errors, [])
        state = game.snapshot()
        self.assertEqual((state["mode"]["id"], state["reloads"]), ("org.atalaia.holdall", 1))
        self.assertEqual(state["generation"], generation + 1)
        self.assertEqual([n["name"] for n in state["nodes"]], ["zone1", "zone2"])
        self.assertEqual(state["params"]["tick_s"], 5)
        self.assertTrue(state["game"]["started"] and state["clock"]["running"])
        self.assertEqual(state["controller"]["status"], "running")
        # A reset starts the reloaded mode again, not the one the server began with.
        game.act("reset", {})
        self.assertEqual(game.snapshot()["mode"]["id"], "org.atalaia.holdall")

    def test_reload_keeps_the_boxes_whose_role_the_mode_has(self):
        game = live("domination")
        self.addCleanup(game.close)
        game.reload(SMALL_MODE, 'on("game.start", function() score.add("red", params.points) end)\n')
        self.assertEqual(list(game.sim.nodes), ["zone"])
        self.assertEqual(game.sim.score("red"), 1)
        game.reload(SMALL_MODE.replace("zone", "post"), "log('hi')\n")
        self.assertEqual(game.sim.nodes["post"].role, "post")  # none fits: one box of its first role

    def test_a_mode_that_does_not_load_leaves_the_game_running(self):
        game = live("domination")
        self.addCleanup(game.close)
        game.act("start", {})
        game.act("step", {"seconds": 2})
        cases = [
            ({"mode_yaml": SMALL_MODE, "node_lua": "-- line 1\nlocal = 2\n"}, "node", 2),
            ({"mode_yaml": SMALL_MODE, "node_lua": "log('ok')\n",
              "field_lua": "local x = 1\nlocal y = nil + x\n"}, "field", 2),
            ({"mode_yaml": "id: [unclosed", "node_lua": "x = 1\n"}, "mode", None),
            ({"mode_yaml": SMALL_MODE.replace("org.test.small", "Not An Id"), "node_lua": "x = 1\n"}, "mode", None),
            ({"mode_yaml": SMALL_MODE + "kind: modifier\n", "node_lua": "x = 1\n"}, "mode", None),
            ({"mode_yaml": SMALL_MODE, "node_lua": ""}, "mode", None),
            ({"mode_yaml": SMALL_MODE, "node_lua": "x = 1\n", "params": {"points": 99}}, "mode", None),
            ({"mode_yaml": SMALL_MODE, "node_lua": "x = 1\n", "nodes": {"a": "nope"}}, "mode", None),
            ({"mode_yaml": SMALL_MODE, "node_lua": "x = 1\n", "nodes": {"controller": "zone"}}, "mode", None),
        ]
        messages = []
        for body, script, line in cases:
            with self.subTest(body=body):
                with self.assertRaises(ReloadError) as caught:
                    game.reload(**body)
                [error] = caught.exception.errors
                messages.append(error["message"])
                self.assertEqual((error["script"], error["line"]), (script, line), error["message"])
        self.assertIn("org.test.small/node.lua:2:", messages[0])  # the chunk is named after the mode
        state = game.snapshot()
        self.assertEqual((state["mode"]["id"], state["reloads"], state["time_ms"]), ("org.atalaia.domination", 0, 2000))
        game.act("step", {"seconds": 1})  # still playable

    def test_errors_on_game_start_come_back_with_their_line(self):
        game = live("domination")
        self.addCleanup(game.close)
        errors = game.reload(SMALL_MODE, 'local s = state.node {}\n\non("game.start", function()\n'
                                         '  log("a" + 1)\nend)\n')
        [error] = errors
        self.assertEqual((error["script"], error["line"], error["node"], error["type"]),
                         ("node", 4, "zone", "script.error"))
        self.assertEqual(game.snapshot()["script_errors"], errors)


@unittest.skipIf(CORE is None, "the shared core library is not built")
class WebServerTests(unittest.TestCase):
    def setUp(self):
        self.game = live("bomb")
        self.server = make_server(self.game, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.game.close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=body, headers={"Host": f"localhost:{self.port}", **(headers or {})})
        res = conn.getresponse()
        data = res.read()
        conn.close()
        return res, data

    def post(self, value, content_type="application/json"):
        return self.request("POST", "/api/action", json.dumps(value).encode(), {"Content-Type": content_type})

    def test_page_and_assets(self):
        for path, kind in (("/", "text/html"), ("/app.js", "text/javascript"), ("/style.css", "text/css")):
            res, body = self.request("GET", path)
            self.assertEqual(res.status, 200, path)
            self.assertTrue(res.getheader("Content-Type").startswith(kind))
            self.assertIn("default-src 'self'", res.getheader("Content-Security-Policy"))
            self.assertIn(b"SPDX-License-Identifier", body)
        res, _ = self.request("GET", "/missing")
        self.assertEqual(res.status, 404)

    def test_actions_and_state(self):
        res, _ = self.post({"action": "start"})
        self.assertEqual(res.status, 200)
        self.post({"action": "hold", "node": "bomb", "team": "red"})
        self.post({"action": "step", "seconds": 5})
        res, body = self.request("GET", "/api/state")
        state = json.loads(body)
        self.assertTrue(state["game"]["started"])
        self.assertIn("bomb.armed", [e["type"] for e in state["events"]])
        res, body = self.post({"action": "start"})
        self.assertEqual(res.status, 409)
        self.assertIn("already started", json.loads(body)["error"])

    def test_refuses_foreign_hosts_and_non_json(self):
        res, _ = self.request("GET", "/api/state", headers={"Host": "evil.example"})
        self.assertEqual(res.status, 403)
        res, _ = self.request("POST", "/api/action", b"action=start",
                              {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(res.status, 415)
        res, _ = self.post(["start"])
        self.assertEqual(res.status, 400)
        self.assertFalse(self.game.started)

    def reload(self, value, **headers):
        return self.request("POST", "/api/reload", json.dumps(value).encode(),
                            {"Content-Type": "application/json", **headers})

    def test_reload(self):
        res, body = self.reload({**mode_files("holdall"), "nodes": {"a": "zone", "b": "zone"}})
        self.assertEqual(res.status, 200)
        answer = json.loads(body)
        self.assertEqual((answer["status"], answer["errors"], answer["reloads"], answer["nodes"]),
                         ("ok", [], 1, ["a", "b"]))
        self.assertEqual(answer["mode"]["id"], "org.atalaia.holdall")
        state = json.loads(self.request("GET", "/api/state")[1])
        self.assertEqual(state["controller"]["status"], "running")
        # A script that does not load: a 200 with its errors, and the game goes on.
        res, body = self.reload({"mode_yaml": SMALL_MODE, "node_lua": "local = 1\n"})
        self.assertEqual(res.status, 200)
        answer = json.loads(body)
        self.assertEqual(answer["status"], "error")
        self.assertEqual((answer["errors"][0]["script"], answer["errors"][0]["line"]), ("node", 1))
        self.assertEqual(json.loads(self.request("GET", "/api/state")[1])["mode"]["id"], "org.atalaia.holdall")

    def test_reload_keeps_the_servers_rules(self):
        files = mode_files("domination")
        res, _ = self.reload(files, Host="evil.example")
        self.assertEqual(res.status, 403)
        res, _ = self.request("POST", "/api/reload", json.dumps(files).encode(), {"Content-Type": "text/plain"})
        self.assertEqual(res.status, 415)
        for bad in (["x"], {"mode_yaml": 1, "node_lua": ""}, {**files, "extra": 1},
                    {**files, "nodes": ["a"]}, {**files, "params": 3}):
            with self.subTest(body=bad):
                self.assertEqual(self.reload(bad)[0].status, 400)
        res, _ = self.reload({**files, "node_lua": "-" * 1_000_001})
        self.assertEqual(res.status, 413)
        res, _ = self.request("GET", "/api/reload")
        self.assertEqual(res.status, 404)
        self.assertEqual(self.game.reloads, 0)


if __name__ == "__main__":
    unittest.main()
