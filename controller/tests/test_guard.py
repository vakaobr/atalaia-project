# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The body limit (FLD-9) and the token transport rule (FLD-4), through the real app."""

from __future__ import annotations

import tempfile
import unittest

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.guard import JSON_LIMIT, body_limit
from atalaia_controller.store import FIELD_IMAGE_MAX, Store
from atalaia_controller.stream_auth import encode_subprotocol
from atalaia_controller.ws import Hub

def from_address(app, host, base_url="http://testserver"):
    """A TestClient whose requests come from ``host`` (this Starlette's TestClient has no ``client`` option)."""
    async def shim(scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            scope = {**scope, "client": (host, 5000)}
        await app(scope, receive, send)
    return TestClient(shim, base_url=base_url)


GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
PLAYER = {"Authorization": "Bearer apt-not-a-real-token"}


class GuardCase(unittest.TestCase):
    https_port = 8443

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = config(self.tmp.name)
        self.store = Store(cfg.db_path)
        self.ctrl = Controller(cfg, self.store, modem=FakeModem(), core=CORE)
        self.app = create_app(self.ctrl, Hub(), Auth(cfg.gm_token, cfg.read_token), https_port=self.https_port)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()


class BodyLimitTests(GuardCase):
    def test_limits_by_route(self):
        self.assertEqual(body_limit("POST", "/api/v1/checkin"), JSON_LIMIT)
        self.assertEqual(body_limit("POST", "/api/v1/games"), JSON_LIMIT)
        self.assertEqual(body_limit("PUT", "/api/v1/field/image"), FIELD_IMAGE_MAX)
        self.assertEqual(body_limit("PUT", "/api/v1/field/levels/2/image"), FIELD_IMAGE_MAX)
        self.assertGreater(body_limit("POST", "/api/v1/mode-packages"), JSON_LIMIT)
        self.assertGreater(body_limit("POST", "/api/v1/firmware"), 1 << 20)
        self.assertGreater(body_limit("POST", "/api/v1/crests"), JSON_LIMIT)
        self.assertEqual(body_limit("POST", "/api/v1/checkin/token"), JSON_LIMIT)

    def test_checkin_over_the_limit_is_refused_before_it_is_parsed(self):
        big = b'{"name": "' + b"a" * (JSON_LIMIT + 1) + b'"}'
        r = self.client.post("/api/v1/checkin", content=big, headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)
        self.assertIn("bytes", r.json()["detail"])

    def test_declared_length_alone_is_enough(self):
        r = self.client.post("/api/v1/checkin", content=b"{}",
                             headers={"Content-Length": str(10 << 20), "Content-Type": "application/json"})
        self.assertIn(r.status_code, (413, 400))  # the server may notice the short body first

    def test_chunked_body_without_a_length(self):
        def chunks():
            for _ in range(JSON_LIMIT // 1024 + 2):
                yield b"a" * 1024
        r = self.client.post("/api/v1/checkin", content=chunks(), headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)

    def test_a_body_inside_the_limit_still_works(self):
        r = self.client.post("/api/v1/checkin", json={"name": "x"})
        self.assertNotEqual(r.status_code, 413)

    def test_upload_route_takes_more_than_json(self):
        body = b"x" * (JSON_LIMIT * 4)
        r = self.client.put("/api/v1/field/image", content=body, headers={**GM, "Content-Type": "image/png"})
        self.assertNotEqual(r.status_code, 413)  # refused later, as no image, not as too big
        r = self.client.put("/api/v1/field/image", content=b"x" * (FIELD_IMAGE_MAX + 1),
                            headers={**GM, "Content-Type": "image/png"})
        self.assertEqual(r.status_code, 413)

    def test_too_big_before_the_token_is_checked(self):
        r = self.client.post("/api/v1/games", content=b"x" * (JSON_LIMIT + 1),
                             headers={"Content-Type": "application/json"})
        self.assertEqual(r.status_code, 413)  # not 401: nothing was read, not even to find the token


class TokenTransportTests(GuardCase):
    def over_http_from_the_field(self):
        return from_address(self.app, "10.42.0.7")

    def test_gm_token_refused_over_plain_http(self):
        with self.over_http_from_the_field() as c:
            r = c.get("/api/v1/whoami", headers=GM)
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.json()["https_port"], 8443)
            self.assertEqual(c.post("/api/v1/games", json={}, headers=GM).status_code, 403)

    def test_player_token_refused_over_plain_http(self):
        with self.over_http_from_the_field() as c:
            self.assertEqual(c.get("/api/v1/checkin/me", headers=PLAYER).status_code, 403)

    def test_read_token_may_read_but_not_write_over_http(self):
        with self.over_http_from_the_field() as c:
            self.assertEqual(c.get("/api/v1/whoami", headers=READ).status_code, 200)
            self.assertEqual(c.post("/api/v1/games/1/checkins", json={}, headers=READ).status_code, 403)

    def test_websocket_token_in_the_query_is_refused(self):
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415
        with self.over_http_from_the_field() as c:
            with self.assertRaises(WebSocketDisconnect):
                with c.websocket_connect("/api/v1/stream?token=gm-secret"):
                    pass
            with c.websocket_connect("/api/v1/stream?token=read-secret") as ws:
                self.assertEqual(ws.receive_json()["type"], "hello")

    def test_websocket_token_in_the_subprotocol_follows_the_same_rules(self):
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415
        with self.over_http_from_the_field() as c:
            with self.assertRaises(WebSocketDisconnect):  # the GM token is never accepted in clear
                with c.websocket_connect("/api/v1/stream", subprotocols=["atalaia.v1", encode_subprotocol("gm-secret")]):
                    pass
            with c.websocket_connect("/api/v1/stream",
                                     subprotocols=["atalaia.v1", encode_subprotocol("read-secret")]) as ws:
                self.assertEqual(ws.receive_json()["type"], "hello")

    def test_what_has_no_token_stays_on_http(self):
        with self.over_http_from_the_field() as c:
            self.assertEqual(c.get("/healthz").status_code, 200)
            self.assertEqual(c.get("/api/v1/controller/ca").status_code, 404)  # no CA here, but not refused as HTTP
            self.assertNotEqual(c.get("/api/v1/checkin").status_code, 403)
            self.assertEqual(c.get("/console/").status_code, 200)

    def test_the_controllers_own_loopback_is_trusted(self):
        with from_address(self.app, "127.0.0.1") as c:
            self.assertEqual(c.get("/api/v1/whoami", headers=GM).status_code, 200)

    def test_https_requests_are_untouched(self):
        with from_address(self.app, "10.42.0.7", "https://10.42.0.1:8443") as c:
            self.assertEqual(c.get("/api/v1/whoami", headers=GM).status_code, 200)


class HttpsOffTests(GuardCase):
    https_port = 0

    def test_nothing_is_refused_when_https_is_off(self):
        with from_address(self.app, "10.42.0.7") as c:
            self.assertEqual(c.get("/api/v1/whoami", headers=GM).status_code, 200)



class HstsAndProxyTests(GuardCase):
    https_port = 8443

    def proxied(self):
        app = create_app(self.ctrl, Hub(), Auth("gm-secret", "read-secret"), https_port=0, trusted_proxy=True)
        return from_address(app, "10.0.0.2")

    def test_hsts_on_tls_only(self):
        with from_address(self.app, "10.42.0.7", "https://10.42.0.1:8443") as c:
            self.assertIn("max-age=", c.get("/healthz").headers["strict-transport-security"])
            r = c.post("/api/v1/checkin", content=b"x" * 70000)
            self.assertEqual(r.status_code, 413)
            self.assertIn("strict-transport-security", r.headers)
        with from_address(self.app, "10.42.0.7") as c:  # the field's plain HTTP listener
            self.assertNotIn("strict-transport-security", c.get("/healthz").headers)
            self.assertNotIn("strict-transport-security", c.get("/console/").headers)

    def test_behind_a_trusted_proxy(self):
        with self.proxied() as c:
            r = c.get("/healthz", headers={"X-Forwarded-Proto": "https"})
            self.assertIn("strict-transport-security", r.headers)
            self.assertEqual(c.get("/api/v1/whoami", headers={**GM, "X-Forwarded-Proto": "https"}).status_code, 200)
            r = c.get("/healthz", headers={"X-Forwarded-Proto": "http"})
            self.assertNotIn("strict-transport-security", r.headers)
            self.assertEqual(c.get("/api/v1/whoami", headers={**GM, "X-Forwarded-Proto": "http"}).status_code, 403)
            r = c.get("/console/?lang=en", headers={"X-Forwarded-Proto": "http", "Host": "demo.example"},
                      follow_redirects=False)
            self.assertEqual((r.status_code, r.headers["location"]), (308, "https://demo.example/console/?lang=en"))

    def test_the_header_means_nothing_without_a_trusted_proxy(self):
        with from_address(self.app, "10.42.0.7") as c:
            r = c.get("/healthz", headers={"X-Forwarded-Proto": "https"})
            self.assertNotIn("strict-transport-security", r.headers)
            self.assertEqual(c.get("/api/v1/whoami", headers={**GM, "X-Forwarded-Proto": "https"}).status_code, 403)


if __name__ == "__main__":
    unittest.main()
