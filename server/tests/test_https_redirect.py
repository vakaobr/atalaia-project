# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The HTTP to HTTPS redirect behind a TLS-ending proxy (LIVE-1): no database, a plain ASGI application."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atalaia_server.https_redirect import HttpsRedirectMiddleware  # noqa: E402


async def ok(scope: dict[str, Any], receive: Any, send: Any) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def get(path: str, *, host: str, proto: Optional[str], scheme: str = "http", query: bytes = b"",
              public: Optional[str] = None) -> tuple[int, dict[bytes, bytes]]:
    app = HttpsRedirectMiddleware(ok, get_public_url=lambda: public)
    headers = [(b"host", host.encode())] + ([(b"x-forwarded-proto", proto.encode())] if proto else [])
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    await app({"type": "http", "scheme": scheme, "method": "GET", "path": path, "query_string": query,
               "headers": headers}, receive, send)
    return sent[0]["status"], dict(sent[0]["headers"])


async def websocket(app: Any, path: str, *, host: str, proto: Optional[str], scheme: str = "ws",
                    public: Optional[str] = None) -> list[dict[str, Any]]:
    """Runs a websocket scope through the middleware; returns what was sent to the client."""
    middleware = HttpsRedirectMiddleware(app, get_public_url=lambda: public)
    headers = [(b"host", host.encode())] + ([(b"x-forwarded-proto", proto.encode())] if proto else [])
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "websocket.connect"}

    await middleware({"type": "websocket", "scheme": scheme, "path": path, "query_string": b"",
                      "headers": headers}, receive, send)
    return sent


class RedirectTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_request_the_proxy_says_was_plain_http_goes_to_https(self) -> None:
        status, headers = await get("/staff/login", host="tests.example.org", proto="http", query=b"x=1&y=2")
        self.assertEqual((status, headers[b"location"]), (308, b"https://tests.example.org/staff/login?x=1&y=2"))

    async def test_the_configured_address_is_the_target_not_the_host_header(self) -> None:
        status, headers = await get("/staff/login", host="evil.example", proto="http", public="https://campo.example.pt")
        self.assertEqual((status, headers[b"location"]), (308, b"https://campo.example.pt/staff/login"))

    async def test_what_is_left_alone(self) -> None:
        for name, kwargs in (("https through the proxy", dict(host="a.example.org", proto="https", scheme="https")),
                             ("no proxy header (containers, health checks)", dict(host="server:8000", proto=None)),
                             ("localhost", dict(host="localhost:8000", proto="http")),
                             ("loopback", dict(host="127.0.0.1:8000", proto="http")),
                             ("loopback v6", dict(host="[::1]:8000", proto="http"))):
            with self.subTest(name):
                self.assertEqual((await get("/staff/login", **kwargs))[0], 200)
        self.assertEqual((await get("/api/v1/health", host="a.example.org", proto="http"))[0], 200)

    async def test_an_odd_host_is_not_made_a_redirect_target(self) -> None:
        self.assertEqual((await get("/x", host="a.example.org/evil", proto="http"))[0], 200)

    async def test_a_websocket_over_plain_http_is_refused_with_1008(self) -> None:
        """Nothing to redirect on an upgrade: it is closed with 1008 (policy violation) and never reaches the app."""
        reached: list[str] = []

        async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
            reached.append(scope["type"])

        for name, kwargs in (("proxy says http", dict(host="tests.example.org", proto="http")),
                             ("public address set", dict(host="evil.example", proto="http",
                                                         public="https://campo.example.pt"))):
            with self.subTest(name):
                sent = await websocket(inner, "/api/v1/stream", **kwargs)
                self.assertEqual(sent, [{"type": "websocket.close", "code": 1008}])
        self.assertEqual(reached, [])

    async def test_a_websocket_that_is_not_plain_http_goes_through(self) -> None:
        for name, kwargs in (("wss through the proxy", dict(host="a.example.org", proto="https", scheme="wss")),
                             ("no proxy header", dict(host="server:8000", proto=None)),
                             ("loopback", dict(host="127.0.0.1:8000", proto="http"))):
            reached: list[str] = []

            async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
                reached.append(scope["type"])

            with self.subTest(name):
                sent = await websocket(inner, "/api/v1/stream", **kwargs)
                self.assertEqual((sent, reached), ([], ["websocket"]))


if __name__ == "__main__":
    unittest.main()
