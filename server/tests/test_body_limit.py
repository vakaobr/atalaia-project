# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The request body cap (SRV-2): no database, a plain ASGI application behind the middleware."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atalaia_server import body_limit  # noqa: E402
from atalaia_server.body_limit import BodyLimitMiddleware, limit_for  # noqa: E402


async def echo_length(scope: dict[str, Any], receive: Any, send: Any) -> None:
    """Reads the whole body, answers its length (what a handler that trusts nothing does)."""
    size = 0
    while True:
        message = await receive()
        if message["type"] == "http.disconnect":
            raise RuntimeError("the client went away")
        size += len(message.get("body", b""))
        if not message.get("more_body"):
            break
    body = json.dumps({"size": size}).encode()
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": body})


async def call(app: Any, method: str, path: str, chunks: list[bytes],
               headers: list[tuple[bytes, bytes]]) -> tuple[int, bytes, int]:
    """(status, body, times the application asked for a message) of one request."""
    queue = list(chunks)
    asked = 0
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        nonlocal asked
        asked += 1
        if not queue:
            return {"type": "http.disconnect"}
        body = queue.pop(0)
        return {"type": "http.request", "body": body, "more_body": bool(queue)}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {"type": "http", "method": method, "path": path, "headers": headers}
    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"), asked


class LimitTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app = BodyLimitMiddleware(echo_length)

    async def test_a_body_under_the_limit_passes(self) -> None:
        status, body, _ = await call(self.app, "POST", "/api/v1/x", [b"a" * 1000], [(b"content-length", b"1000")])
        self.assertEqual((status, json.loads(body)), (200, {"size": 1000}))

    async def test_a_declared_length_over_the_limit_is_refused_unread(self) -> None:
        status, body, asked = await call(self.app, "POST", "/api/v1/x", [b"a"],
                                         [(b"content-length", str(body_limit.DEFAULT_LIMIT + 1).encode())])
        self.assertEqual((status, json.loads(body), asked), (413, {"detail": "body_too_large"}, 0))

    async def test_a_lying_or_missing_length_is_counted_as_it_arrives(self) -> None:
        chunk = b"a" * 65536
        chunks = [chunk] * (body_limit.DEFAULT_LIMIT // len(chunk) + 4)
        for headers in ([], [(b"content-length", b"10")], [(b"transfer-encoding", b"chunked")]):
            with self.subTest(headers=headers):
                status, body, asked = await call(self.app, "PUT", "/api/v1/x", list(chunks), headers)
                self.assertEqual((status, json.loads(body)), (413, {"detail": "body_too_large"}))
                self.assertLess(asked, len(chunks))  # stopped at the limit, not after the whole body

    async def test_a_length_that_is_not_a_number_is_refused(self) -> None:
        for value in (b"-5", b"lots"):
            with self.subTest(value=value):
                status, _, _ = await call(self.app, "POST", "/api/v1/x", [b""], [(b"content-length", value)])
                self.assertEqual(status, 413)

    async def test_reads_and_other_scopes_pass_untouched(self) -> None:
        status, _, _ = await call(self.app, "GET", "/api/v1/x", [b""], [])
        self.assertEqual(status, 200)
        seen = []

        async def other_scope(scope: Any, receive: Any, send: Any) -> None:
            seen.append(scope["type"])

        await BodyLimitMiddleware(other_scope)({"type": "websocket", "path": "/api/v1/sync/stream"}, None, None)
        self.assertEqual(seen, ["websocket"])

    async def test_the_upload_routes_have_the_larger_limit(self) -> None:
        for method, path in (("PUT", "/api/v1/fields/abc/branding/wallpaper"),
                             ("PUT", "/api/v1/fields/abc/teams/def/crest"),
                             ("PUT", "/api/v1/clubs/abc/images/logo"),
                             ("POST", "/api/v1/fields/abc/scheduled-games/def/registrations/import")):
            with self.subTest(path=path):
                self.assertEqual(limit_for(method, path), body_limit.UPLOAD_LIMIT)
        for method, path in (("POST", "/api/v1/auth/login"), ("POST", "/api/v1/sync/field"),
                             ("PUT", "/api/v1/fields/abc/roles"), ("POST", "/api/v1/fields/abc/branding/logo/x")):
            with self.subTest(path=path):
                self.assertEqual(limit_for(method, path), body_limit.DEFAULT_LIMIT)
        size = 3 * 1024 * 1024
        status, _, _ = await call(self.app, "PUT", "/api/v1/fields/abc/branding/wallpaper", [b"a" * size],
                                  [(b"content-length", str(size).encode())])
        self.assertEqual(status, 200)
        chunk = b"a" * (1024 * 1024)
        status, _, _ = await call(self.app, "PUT", "/api/v1/fields/abc/branding/wallpaper", [chunk] * 5, [])
        self.assertEqual(status, 413)

    def test_the_caddyfiles_cap_bodies_above_the_largest_upload(self) -> None:
        server = Path(__file__).resolve().parents[1]
        for name in ("Caddyfile", "Caddyfile.hosted"):
            if not (server / name).exists():  # the test image holds no deployment files: the deploy test has them
                continue
            text = (server / name).read_text(encoding="utf-8")
            self.assertIn(f"max_size {body_limit.CADDY_MAX}", text, name)
        self.assertGreater(int(body_limit.CADDY_MAX[:-2]) * 1000 * 1000, body_limit.UPLOAD_LIMIT)


if __name__ == "__main__":
    unittest.main()
