# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two ASGI guards in front of the whole API (security review FLD-9 and FLD-4).

``BodyLimit``: no request body is read past its route's limit. The limit is judged first from
``Content-Length`` (answered 413 before anything is read, before the token and before any rate limit),
then again while the body streams in (chunked bodies have no length). 64 KB for JSON; the routes that
carry an upload have their own, larger limit (``BODY_LIMITS``).

``TokenTransport``: with HTTPS on, the GM token and the players' tokens are never accepted over plain
HTTP from another machine (they would cross the field's Wi-Fi in clear). The read token, which the
scoreboard needs on HTTP (decision PE3), is accepted there for reading only. Requests with no token,
the check-in poster flow and the CA fetch among them, are not touched. The Pi's own loopback address
is trusted (a browser on the controller itself). Refused with 403 and ``https_port`` in the body, which
the console turns into a link to the HTTPS address.

``Hsts``: ``Strict-Transport-Security`` on answers served over TLS, never on the plain-HTTP listener (the
field's local HTTP flows must keep working: a browser that saw the header would refuse them afterwards).

Behind a reverse proxy that ends TLS (a Cloudflare Tunnel in front of the demo image) ``[api] trusted_proxy``
makes all three read ``X-Forwarded-Proto`` instead of the socket's scheme. Off by default: a field's Wi-Fi and
the phone controller have no proxy, and the header would be the client's to forge. When on, a proxied request
that says ``http`` is treated as plain HTTP: tokens refused as above (the loopback exemption does not apply: the
proxy is the peer), and a page (not the API) redirected with 308 to the same address over https.
"""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any, Awaitable, Callable, Optional

from . import images
from .firmware_updates import SLOT_SIZE
from .mode_package import MAX_PACKAGE_BYTES
from .store import FIELD_IMAGE_MAX
from .stream_auth import stream_token

JSON_LIMIT = 64 * 1024
FROM_MAP_LIMIT = 6 << 20  # the plan's image in base64 (about 5.6 MB) and its settings
UPLOAD_JSON_LIMIT = 2 << 20  # a mode (its files as JSON text), a scenario's manifest, a registration CSV

_IMAGE_MAX = max(images.LOGO.max_bytes, images.WALLPAPER.max_bytes)

# (method, path regex, limit in bytes), first match wins; anything else gets JSON_LIMIT.
BODY_LIMITS: list[tuple[str, "re.Pattern[str]", int]] = [
    (m, re.compile(p), n) for m, p, n in (
        ("PUT", r"/api/v1/field/image", FIELD_IMAGE_MAX),
        ("PUT", r"/api/v1/field/levels/\d+/image", FIELD_IMAGE_MAX),
        ("POST", r"/api/v1/field/levels/\d+/from-map", FROM_MAP_LIMIT),
        ("PUT", r"/api/v1/field/branding/[a-z]+", _IMAGE_MAX),
        ("POST", r"/api/v1/crests", images.CREST.max_bytes),
        ("POST", r"/api/v1/mode-packages", MAX_PACKAGE_BYTES),
        ("POST", r"/api/v1/firmware", SLOT_SIZE),
        ("POST", r"/api/v1/modes", UPLOAD_JSON_LIMIT),
        ("POST", r"/api/v1/scenarios(/check)?", UPLOAD_JSON_LIMIT),
        ("POST", r"/api/v1/games/\d+/checkins/import", UPLOAD_JSON_LIMIT),
    )]

# One WebSocket message (the stream's pings, a prop's frames): far under uvicorn's 16 MB default.
WS_MAX_MESSAGE = 256 * 1024

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


def body_limit(method: str, path: str) -> int:
    for m, pattern, limit in BODY_LIMITS:
        if m == method and pattern.fullmatch(path):
            return limit
    return JSON_LIMIT


async def _json(send: Send, status: int, body: dict[str, Any]) -> None:
    data = json.dumps(body).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(data)).encode()),
                            (b"cache-control", b"no-store"), (b"connection", b"close")]})
    await send({"type": "http.response.body", "body": data})


class BodyLimit:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS", "DELETE"):
            await self.app(scope, receive, send)
            return
        limit = body_limit(scope["method"], scope["path"])
        detail = {"detail": f"the request body is over {limit} bytes"}
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            if not declared.isdigit() or int(declared) > limit:
                await _json(send, 413, detail)
                return
        seen = 0
        refused = False

        async def counted() -> dict[str, Any]:
            nonlocal seen, refused
            msg = await receive()
            if msg["type"] == "http.request":
                seen += len(msg.get("body", b""))
                if seen > limit and not refused:
                    refused = True
                    await _json(send, 413, detail)
                    return {"type": "http.disconnect"}
            return msg

        async def guarded(msg: dict[str, Any]) -> None:
            if not refused:  # the app's own answer to the cut-off body is dropped
                await send(msg)

        await self.app(scope, counted, guarded)


def forwarded_proto(scope: Scope, trusted_proxy: bool) -> Optional[str]:
    """``X-Forwarded-Proto``'s first value, lower case, when a trusted proxy sets it."""
    if not trusted_proxy:
        return None
    value = dict(scope["headers"]).get(b"x-forwarded-proto", b"").decode("latin-1").split(",")[0].strip().lower()
    return value if value in ("http", "https") else None


def is_secure(scope: Scope, trusted_proxy: bool) -> bool:
    via = forwarded_proto(scope, trusted_proxy)
    return via == "https" if via else scope.get("scheme") in ("https", "wss")


class Hsts:
    VALUE = b"max-age=31536000"

    def __init__(self, app: Any, trusted_proxy: bool = False) -> None:
        self.app = app
        self.trusted_proxy = trusted_proxy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_secure(scope, self.trusted_proxy):
            await self.app(scope, receive, send)
            return

        async def with_header(msg: dict[str, Any]) -> None:
            if msg["type"] == "http.response.start":
                msg = {**msg, "headers": [*msg.get("headers", []), (b"strict-transport-security", self.VALUE)]}
            await send(msg)

        await self.app(scope, receive, with_header)


def _loopback(host: Optional[str]) -> bool:
    try:
        return host is not None and ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


class TokenTransport:
    """``auth``: an Auth (its ``role`` tells the GM and read tokens apart); ``https_port``: 0 = HTTPS off,
    nothing is refused (the controller would be unusable)."""

    def __init__(self, app: Any, auth: Any, https_port: int, trusted_proxy: bool = False) -> None:
        self.app = app
        self.auth = auth
        self.https_port = https_port
        self.trusted_proxy = trusted_proxy

    def plain(self, scope: Scope) -> bool:
        if not (self.https_port or self.trusted_proxy):
            return False
        return not is_secure(scope, self.trusted_proxy)

    def refused(self, scope: Scope) -> bool:
        if not self.plain(scope):
            return False
        proxied = forwarded_proto(scope, self.trusted_proxy) is not None
        if not proxied and _loopback((scope.get("client") or (None, 0))[0]):
            return False
        token = None
        header = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
        if scope["type"] == "websocket" and not token:
            token = stream_token(scope)
        if not token:
            return False
        if self.auth.role(token) == "read":  # reading only: the scoreboard's page and its stream
            if scope["type"] == "websocket":
                return scope["path"] != "/api/v1/stream"
            return scope["method"] not in ("GET", "HEAD", "OPTIONS")
        return True  # the GM token, a player's token or anything else sent in clear

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (scope["type"] == "http" and forwarded_proto(scope, self.trusted_proxy) == "http"
                and scope["method"] in ("GET", "HEAD") and not scope["path"].startswith(("/api/", "/healthz"))):
            host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")
            query = scope.get("query_string", b"").decode("latin-1")
            where = f"https://{host}{scope['path']}" + (f"?{query}" if query else "")
            await send({"type": "http.response.start", "status": 308,
                        "headers": [(b"location", where.encode("latin-1")), (b"content-length", b"0")]})
            await send({"type": "http.response.body", "body": b""})
            return
        if scope["type"] in ("http", "websocket") and self.refused(scope):
            if scope["type"] == "websocket":
                await receive()  # websocket.connect
                await send({"type": "websocket.close", "code": 4403})
                return
            where = f"on port {self.https_port}" if self.https_port else ""
            await _json(send, 403, {
                "detail": f"this token is not accepted over plain HTTP: use https {where}".rstrip(),
                "https_port": self.https_port})
            return
        await self.app(scope, receive, send)
