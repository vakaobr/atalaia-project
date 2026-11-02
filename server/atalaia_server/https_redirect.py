# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A request that came to the proxy over plain HTTP is sent to HTTPS (LIVE-1, defence in depth).

Behind a tunnel that ends TLS (Cloudflare) the site may also be reachable as ``http://``: the staff login would then
be served in the clear, and browsers ignore HSTS over HTTP. The proxy says how the client came in with
``X-Forwarded-Proto``; this middleware answers ``308`` to the same address with ``https`` when that is ``http``.

Whom to trust: uvicorn's ``--proxy-headers`` (``FORWARDED_ALLOW_IPS`` names the proxies) is what turns the header into
the request's scheme, and only for those proxies. This middleware does not look at the header on its own for a
decision about anyone else's traffic: it redirects when the scheme is ``http`` and the header says ``http`` too, so a
request with no header (the containers talking to each other, a health check on 127.0.0.1) is never touched, and a
forged header from an untrusted client only redirects that client's own request. Not redirected: a ``localhost`` or
loopback host and ``/api/v1/health`` (a monitor that cannot follow redirects must still see the status). The target
host is ``ATALAIA_PUBLIC_URL``'s when set (never a made-up ``Host``), else the request's own, when it is a plain name.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

HEALTH_PATH = "/api/v1/health"
LOOPBACK = frozenset({"localhost", "127.0.0.1", "[::1]", "::1"})
PLAIN_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}(?::[0-9]{1,5})?$")


def _host_name(host: str) -> str:
    """The host without its port (``[::1]:8000`` is ``[::1]``)."""
    return host[:host.index("]") + 1] if host.startswith("[") and "]" in host else host.split(":")[0]


class HttpsRedirectMiddleware:
    """A plain ASGI middleware: 308 to ``https://`` for a request the proxy says came over HTTP."""

    def __init__(self, app: Any, get_public_url: Callable[[], Optional[str]] = lambda: None) -> None:
        self.app = app
        self._public_url = get_public_url

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket") or scope.get("scheme") not in ("http", "ws") \
                or scope.get("path") == HEALTH_PATH:
            await self.app(scope, receive, send)
            return
        headers = {k: v for k, v in scope.get("headers", ())}
        if headers.get(b"x-forwarded-proto", b"").split(b",")[0].strip().lower() != b"http":
            await self.app(scope, receive, send)
            return
        host = headers.get(b"host", b"").decode("latin-1")
        if _host_name(host).lower() in LOOPBACK or not host:
            await self.app(scope, receive, send)
            return
        public = self._public_url()
        if public:
            target_host = public.split("://", 1)[1]
        elif PLAIN_HOST.fullmatch(host):
            target_host = host
        else:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":  # nothing to redirect: refuse the upgrade
            await receive()
            await send({"type": "websocket.close", "code": 1008})
            return
        path = (scope.get("raw_path") or scope["path"].encode("utf-8")).decode("latin-1").split("?")[0]
        query = scope.get("query_string", b"").decode("latin-1")
        location = f"https://{target_host}{path}" + (f"?{query}" if query else "")
        await send({"type": "http.response.start", "status": 308, "headers": [
            (b"location", location.encode("latin-1")), (b"content-length", b"0"), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": b""})
