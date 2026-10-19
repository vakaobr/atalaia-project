# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Security headers on every HTTP response (ADR-P4-10).

A plain ASGI middleware, not Starlette's BaseHTTPMiddleware, so it adds the
headers to every response (errors and 404s included) without buffering
bodies, and lets WebSocket connections (plan phase 13) pass untouched. The
site server is served over HTTPS behind Caddy (plan phase 22); HSTS is sent
regardless, since browsers ignore it over plain HTTP.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

Scope = dict[str, Any]
Message = dict[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

HEADERS: tuple[tuple[str, str], ...] = (
    ("strict-transport-security", "max-age=63072000; includeSubDomains"),
    ("x-content-type-options", "nosniff"),
    ("x-frame-options", "DENY"),
    ("content-security-policy",
     "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
     "connect-src 'self' wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"),
    ("referrer-policy", "strict-origin-when-cross-origin"),
)
_RAW = [(name.encode("latin-1"), value.encode("latin-1")) for name, value in HEADERS]
_NAMES = {name for name, _ in _RAW}


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in _NAMES]
                message = {**message, "headers": kept + _RAW}
            await send(message)

        await self.app(scope, receive, send_with_headers)
