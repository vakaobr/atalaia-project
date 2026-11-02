# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A cap on request bodies (security review SRV-2).

The server runs one worker process (ADR-P4-2): a few huge POSTs could take it down. This plain ASGI middleware
refuses a body over its route's limit with ``413 body_too_large``. A declared ``Content-Length`` over the limit is
refused before anything is read; the bytes that arrive are counted too, so a chunked body, or a lie in the header,
is stopped at the limit as well (the handler then sees the client go away, and the 413 is sent instead of its
answer). Caddy has its own ``request_body max_size`` in front (``CADDY_MAX``, above the biggest upload's limit).

Limits: ``DEFAULT_LIMIT`` (1 MiB plus a margin for the JSON around the biggest legitimate body, a sync batch of
``sync_format.MAX_BODY`` = 1 MiB) everywhere; ``UPLOAD_LIMIT`` on the routes that take a file: a field's and a club's
images (the wallpaper is 4 MiB), a team's crest and the registration import (the handler keeps its own, finer limit).
"""

from __future__ import annotations

import re
from typing import Any

DEFAULT_LIMIT = 1024 * 1024 + 64 * 1024
UPLOAD_LIMIT = 4 * 1024 * 1024 + 64 * 1024   # the largest image (wallpaper) plus a margin
CADDY_MAX = "5MB"                            # the Caddyfiles' request_body max_size: above UPLOAD_LIMIT

_UPLOAD_ROUTES = re.compile(
    r"^/api/v1/(?:"
    r"fields/[^/]+/branding/[^/]+"
    r"|fields/[^/]+/teams/[^/]+/crest"
    r"|clubs/[^/]+/images/[^/]+"
    r"|fields/[^/]+/scheduled-games/[^/]+/registrations/import"
    r")/?$")
_BODY_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def limit_for(method: str, path: str) -> int:
    """The body limit of this request: the upload routes' larger one, else the default."""
    if method in ("PUT", "POST") and _UPLOAD_ROUTES.match(path):
        return UPLOAD_LIMIT
    return DEFAULT_LIMIT


_BODY = b'{"detail":"body_too_large"}'
_HEADERS = [(b"content-type", b"application/json"), (b"content-length", str(len(_BODY)).encode()),
            (b"cache-control", b"no-store")]


class BodyLimitMiddleware:
    """A plain ASGI middleware: 413 ``body_too_large`` once a request body passes its route's limit."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("method", "GET") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return
        limit = limit_for(scope["method"], scope.get("path", ""))
        for name, value in scope.get("headers", ()):
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = -1
                if declared < 0 or declared > limit:  # not a number: nothing honest sends it
                    await self._refuse(send)
                    return
        state = {"seen": 0, "over": False, "started": False}

        async def counted_receive() -> Any:
            if state["over"]:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                state["seen"] += len(message.get("body", b""))
                if state["seen"] > limit:
                    state["over"] = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Any) -> None:
            if state["over"]:
                return  # the handler's answer to a body that was cut off is not sent
            if message["type"] == "http.response.start":
                state["started"] = True
            await send(message)

        try:
            await self.app(scope, counted_receive, guarded_send)
        except Exception:
            if not state["over"]:
                raise
        if state["over"] and not state["started"]:
            await self._refuse(send)

    @staticmethod
    async def _refuse(send: Any) -> None:
        await send({"type": "http.response.start", "status": 413, "headers": _HEADERS})
        await send({"type": "http.response.body", "body": _BODY})
