# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live demo's own code: the read-only proxy against a stand-in controller, the plan and its georeference, the
made-up callsigns. Run in the demo's image:  python3 tools/docker_server.py preview-demo-unit
(or:  python3 -m unittest discover -s /app/demo  inside it).

The stand-in controller records everything it is asked, so the tests can say what reached it: nothing a visitor
sends may change anything, and no credential but the public read token (and the demo player's own token, for its
own few paths) may ever be forwarded.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, Response
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

READ = "test-read-token"
GM = "gm-token-nobody-knows"
PLAYER = "apt-the-demo-players-own-token"
TMP = tempfile.mkdtemp(prefix="demo-test-")

seen: list[tuple[str, str, str]] = []          # (method, path, authorization) of every request the controller got
ws_received: list[str] = []                    # what reached the controller's stream from a visitor
stub = FastAPI()


@stub.middleware("http")
async def record(request: Request, call_next):
    seen.append((request.method, request.url.path, request.headers.get("authorization", "")))
    return await call_next(request)


@stub.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@stub.get("/api/v1/games")
def games() -> list:
    return [{"id": 7, "name": "Demonstração 10:00 (Domínio)", "state": "running", "created_at": 5.0, "teams": ["red", "blue"]}]


@stub.post("/api/v1/games")
def make_game() -> dict:
    return {"id": 99}


@stub.get("/api/v1/boxes")
def boxes() -> list:
    return [{"device_id": "secret"}]


@stub.get("/console/")
def console() -> HTMLResponse:
    return HTMLResponse("<html>console</html>", headers={"Content-Security-Policy": "default-src 'self'"})


@stub.get("/scoreboard")
def scoreboard() -> HTMLResponse:
    return HTMLResponse("<html>board</html>")


@stub.get("/api/v1/field/image")
def image() -> Response:
    return Response(b"\x89PNG-stand-in", media_type="image/png")


@stub.get("/api/v1/checkin/me")
def me() -> dict:
    return {"display_name": "Falcão", "team": "red", "role": "vip", "status": "checked_in", "squad": 1,
            "player_id": "p-abc", "game_id": 7, "email": "must-not-pass@example.org",
            "declarations": [{"class": "rifle", "type": "aeg", "state": "passed", "make_model": "secret model"}]}


@stub.get("/api/v1/games/{gid}")
def one(gid: int) -> dict:
    return {"id": gid, "name": "Demonstração", "state": "running", "teams": ["red", "blue"], "game_time_ms": 1000}


@stub.get("/api/v1/games/{gid}/score")
def score(gid: int) -> dict:
    return {"game": gid, "teams": {"red": 3, "blue": 2}}


@stub.get("/api/v1/games/{gid}/log")
def log(gid: int) -> list:
    return [{"t": i, "type": "zone.captured", "node": 1, "team": "red", "data": {}} for i in range(20)]


@stub.get("/api/v1/games/{gid}/positions")
def box_positions(gid: int) -> dict:
    return {"1": {"x": 0.2, "y": 0.3, "level": 0}}


@stub.get("/api/v1/positions")
def positions() -> dict:
    return {"positions": [{"player_id": "p-abc", "team": "red", "lat": 0.001, "lon": 0.001}]}


@stub.get("/api/v1/nodes")
def nodes() -> list:
    return [{"node_id": 1, "name": "alpha", "owner": "red", "link": "online", "device_id": "private"}]


@stub.get("/api/v1/field/georef")
def georef() -> dict:
    return {"georef": None}


@stub.websocket("/api/v1/stream")
async def stream(ws: WebSocket) -> None:
    await ws.accept()
    await ws.send_json({"type": "hello", "token": ws.query_params.get("token")})
    try:
        while True:
            ws_received.append(await ws.receive_text())
    except Exception:  # noqa: BLE001
        return


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        port = free_port()
        cls.server = uvicorn.Server(uvicorn.Config(stub, host="127.0.0.1", port=port, log_level="error"))
        cls.thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.thread.start()
        end = time.monotonic() + 10
        while not cls.server.started and time.monotonic() < end:
            time.sleep(0.05)
        os.environ.update({"DEMO_CONTROLLER": f"http://127.0.0.1:{port}", "DEMO_READ_TOKEN": READ, "DEMO_DATA": TMP,
                           "DEMO_SITE_URL": "https://site.example.org/"})
        import proxy  # noqa: PLC0415  (reads the environment when imported)

        cls.proxy = proxy
        cls.client = TestClient(proxy.app)
        cls.client.__enter__()   # one event loop for every request, as the proxy has in service

    @classmethod
    def tearDownClass(cls) -> None:
        cls.client.__exit__(None, None, None)
        cls.server.should_exit = True
        cls.thread.join(timeout=5)

    def setUp(self) -> None:
        seen.clear()
        ws_received.clear()
        (Path(TMP) / "player.json").unlink(missing_ok=True)

    def reached(self, method: str, path: str) -> bool:
        return any(m == method and p == path for m, p, _ in seen)

    # --- nothing can be changed ---

    def test_every_method_but_get_is_refused_before_anything_is_forwarded(self) -> None:
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"):
            for path in ("/api/v1/games", "/api/v1/games/7/end", "/console/", "/scoreboard", "/", "/player/", "/nothing"):
                r = self.client.request(method, path, headers={"Authorization": f"Bearer {READ}"}, content=b"{}")
                self.assertEqual(r.status_code, 405, (method, path))
                self.assertEqual(r.headers["allow"], "GET, HEAD")
        self.assertEqual(seen, [])

    def test_the_gm_token_is_never_accepted_and_never_forwarded(self) -> None:
        for token in (GM, "", "wrong", PLAYER):
            r = self.client.get("/api/v1/games", headers={"Authorization": f"Bearer {token}"} if token else {})
            self.assertEqual(r.status_code, 401, token)
        self.assertEqual(self.client.get("/api/v1/games?token=" + READ).status_code, 401)  # the query is not a credential here
        self.assertEqual(seen, [])

    def test_the_read_token_reads_and_is_all_that_is_sent_on(self) -> None:
        r = self.client.get("/api/v1/games", headers={"Authorization": f"Bearer {READ}", "Cookie": "a=b",
                                                     "X-Forwarded-For": "1.2.3.4", "X-Anything": "x"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["x-atalaia-demo"], "read-only")
        self.assertEqual(seen, [("GET", "/api/v1/games", f"Bearer {READ}")])

    def test_only_listed_paths_are_served(self) -> None:
        for path in ("/api/v1/boxes", "/api/v1/join", "/api/v1/adopt", "/api/v1/firmware", "/api/v1/marshals",
                     "/api/v1/checkin", "/api/v1/checkin/settings", "/api/v1/checkin/me", "/api/v1/mode-packages",
                     "/api/v1/remote-gm", "/api/v1/games/7/checkins.csv", "/api/v1/games/7/invites",
                     "/api/v1/games/7/tags", "/api/v1/scoreboard-link", "/api/v1/controller/ca", "/api/v1/players/x/chrono",
                     "/api/v1/games/x", "/api/v1/games/7/end", "/healthz", "/openapi.json", "/docs", "/console/../api/v1/boxes",
                     "/api/v1/stream", "/data/player.json", "/../etc/passwd"):
            r = self.client.get(path, headers={"Authorization": f"Bearer {READ}"})
            self.assertIn(r.status_code, (404, 426), path)
        self.assertFalse(self.reached("GET", "/api/v1/boxes"))
        self.assertEqual([p for _, p, _ in seen if p != "/console/"], [])

    def raw_get(self, path: str) -> int:
        """A GET with the path exactly as written (an HTTP client would tidy dot segments away; an attacker's does not)."""
        status: list[int] = []
        sent = []

        async def receive() -> dict:
            if not sent:
                sent.append(1)
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                status.append(message["status"])

        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
                 "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                 "headers": [(b"host", b"demo"), (b"authorization", f"Bearer {READ}".encode())],
                 "client": ("127.0.0.1", 1), "server": ("demo", 80)}
        self.client.portal.call(self.proxy.app, scope, receive, send)
        return status[0]

    def test_dot_segments_and_odd_paths_never_reach_the_controller(self) -> None:
        for path in ("/console/../api/v1/boxes", "/console/./../api/v1/boxes", "/console/..", "/console//x", "/console/x/../../api/v1/join",
                     "/scoreboard/../api/v1/boxes", "/console/%2e%2e/api/v1/boxes", "/console/..\\api", "/console/a b",
                     "/api/v1/games/../boxes", "/api/v1/games/7/../../boxes"):
            self.assertEqual(self.raw_get(path), 404, path)
        self.assertEqual(seen, [])
        self.assertEqual(self.raw_get("/console/"), 200)
        self.assertEqual(seen[-1][1], "/console/")
        self.assertEqual(self.raw_get("/console/app.js"), 404)  # a plain file name is forwarded; the stand-in has no such file
        self.assertEqual(seen[-1][1], "/console/app.js")

    def test_the_console_and_the_scoreboard_pages_need_no_token(self) -> None:
        self.assertEqual(self.client.get("/console/").status_code, 200)
        self.assertEqual(self.client.get("/scoreboard").status_code, 200)
        self.assertTrue(all(a == f"Bearer {READ}" for _, _, a in seen))

    def test_a_controller_that_is_down_is_a_retry_later(self) -> None:
        port = free_port()
        import httpx  # noqa: PLC0415

        old = self.proxy.client
        self.proxy.client = httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=2.0)
        try:
            r = self.client.get("/api/v1/games", headers={"Authorization": f"Bearer {READ}"})
            self.assertEqual((r.status_code, r.headers["retry-after"]), (503, "30"))
        finally:
            self.proxy.client = old

    # --- the stream is one way ---

    def test_the_stream_relays_to_the_visitor_and_drops_what_the_visitor_sends(self) -> None:
        with self.client.websocket_connect(f"/api/v1/stream?token={READ}") as ws:
            hello = ws.receive_json()
            self.assertEqual(hello, {"type": "hello", "token": READ})
            ws.send_text('{"cmd":"end"}')
            ws.send_text("x")
            time.sleep(0.5)
        self.assertEqual(ws_received, [])

    def test_the_stream_refuses_any_other_token(self) -> None:
        for query in ("", "?token=" + GM, "?token=wrong", "?token=" + PLAYER):
            with self.assertRaises(WebSocketDisconnect, msg=query):
                with self.client.websocket_connect("/api/v1/stream" + query) as ws:
                    ws.receive_json()
        self.assertEqual(seen, [])

    # --- the player's view ---

    def test_the_players_view_without_a_game(self) -> None:
        self.assertEqual(self.client.get("/player/data.json").status_code, 503)

    def test_the_players_view_uses_the_players_token_and_shows_only_the_phones_screen(self) -> None:
        (Path(TMP) / "player.json").write_text(json.dumps({"game_id": 7, "player_id": "p-abc", "token": PLAYER,
                                                           "name": "Falcão", "team": "red"}))
        r = self.client.get("/player/data.json")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["me"]["display_name"], "Falcão")
        self.assertEqual(body["me"]["replicas"], [{"class": "rifle", "type": "aeg", "state": "passed"}])
        self.assertEqual(len(body["log"]), 12)
        self.assertNotIn(PLAYER, r.text)
        self.assertNotIn("must-not-pass", r.text)        # the e-mail the stand-in leaked is cut
        self.assertNotIn("secret model", r.text)
        self.assertNotIn("private", r.text)              # the box's device id is cut
        tokens = {a for _, _, a in seen}
        self.assertEqual(tokens <= {f"Bearer {PLAYER}", f"Bearer {READ}"}, True)
        self.assertFalse(any(m != "GET" for m, _, _ in seen))
        self.assertEqual(self.client.get("/player/field.png").status_code, 200)

    # --- the proxy's own pages ---

    def test_the_home_page_and_its_facts(self) -> None:
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("script-src 'self'", r.headers["content-security-policy"])
        self.assertEqual(r.headers["x-content-type-options"], "nosniff")
        self.assertIn("noindex", r.headers["x-robots-tag"])
        cfg = self.client.get("/demo/config.json").json()
        self.assertEqual(cfg, {"read_token": READ, "site_url": "https://site.example.org", "site_slug": "demo-ao-vivo"})
        state = self.client.get("/demo/state.json").json()
        self.assertEqual(state["state"], "running")
        self.assertEqual(self.client.get("/demo/health").status_code, 200)
        self.assertIn("Disallow: /", self.client.get("/robots.txt").text)
        for page in ("/player/", "/player/player.js", "/player/player.css", "/home/home.js", "/home/home.css"):
            self.assertEqual(self.client.get(page).status_code, 200, page)
        self.assertEqual(self.client.get("/home/..%2fproxy.py").status_code, 404)
        self.assertEqual(self.client.get("/player/proxy.py").status_code, 404)


class FieldMapTests(unittest.TestCase):
    def test_the_plan_is_a_png_the_controller_accepts(self) -> None:
        import fieldmap
        from atalaia_controller import images

        checked = images.check(fieldmap.plan_png(), "image/png", images.Limits("field", 4 << 20, 16, 4096, 8.0))
        self.assertEqual((checked.width, checked.height), (fieldmap.WIDTH, fieldmap.HEIGHT))

    def test_the_georeference_round_trips_and_the_field_is_in_the_open_sea(self) -> None:
        import fieldmap

        pts = fieldmap.georef_points()
        self.assertEqual((pts[0]["x"], pts[0]["y"], pts[1]["x"], pts[1]["y"]), (0.0, 0.0, 1.0, 1.0))
        for x, y in ((0.0, 0.0), (0.5, 0.5), (0.24, 0.3), (1.0, 1.0)):
            lat, lon = fieldmap.to_latlon(x, y)
            bx, by = fieldmap.to_plan(lat, lon)
            self.assertAlmostEqual(bx, x, places=3)
            self.assertAlmostEqual(by, y, places=3)
        # Latitude and longitude within a third of a degree of 0, 0: no land, no road, no building of anyone's.
        for p in pts:
            self.assertLess(abs(p["lat"]), 0.01)
            self.assertLess(abs(p["lon"]), 0.01)

    def test_boxes_and_bases_are_on_the_plan(self) -> None:
        import fieldmap

        for fx, fy in [*fieldmap.ZONES.values(), *fieldmap.BASES.values()]:
            self.assertTrue(0.05 < fx < 0.95 and 0.05 < fy < 0.95)


class DirectorTests(unittest.TestCase):
    def test_callsigns_are_made_up_and_enough(self) -> None:
        import director

        self.assertEqual(len(set(director.CALLSIGNS)), len(director.CALLSIGNS))
        self.assertGreaterEqual(len(director.CALLSIGNS), 12)
        for name in director.CALLSIGNS:
            self.assertRegex(name, r"^[A-ZÁÉÍÓÚÂÊÔÃÕÇ][a-záéíóúâêôãõç]+$")   # one word, no surname, no digits
        self.assertNotRegex(director.MARSHAL_NAME, r"\d")

    def test_a_player_walks_towards_a_target_and_stays_on_the_plan(self) -> None:
        import random

        import director

        rng = random.Random(3)
        p = director.Player("Falcão", "red", (0.09, 0.86), rng)
        p.target = (0.9, 0.1)
        for _ in range(2000):
            p.step(1.0, rng)
        self.assertTrue(0.02 <= p.x <= 0.98 and 0.02 <= p.y <= 0.98)
        self.assertLess(((p.x - 0.9) ** 2 + (p.y - 0.1) ** 2) ** 0.5, 0.06)

    def test_the_pace_comes_from_the_environment(self) -> None:
        import director

        os.environ["DEMO_GAME_S"] = "12"
        os.environ["DEMO_RESTART_AFTER_GAMES"] = "3"
        try:
            d = director.Director.__new__(director.Director)
            self.assertEqual(director.env_float("DEMO_GAME_S", 240), 12.0)
            self.assertEqual(director.env_float("DEMO_NOT_SET", 60), 60.0)
        finally:
            del os.environ["DEMO_GAME_S"], os.environ["DEMO_RESTART_AFTER_GAMES"]


if __name__ == "__main__":
    unittest.main()
