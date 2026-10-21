# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hosted hub's ``ask`` endpoint for Caddy's on-demand TLS (Phase 4 follow-up; decisions FU4-*).

In hosted mode Caddy serves ``*.<ATALAIA_HOSTED_DOMAIN>`` and gets each
field's certificate when the first client asks for that name (on-demand TLS,
server/Caddyfile.hosted). Before it asks a certificate authority, Caddy asks
this service ``GET /check?domain=<name>``: 200 lets it go on, anything else
stops it, so nobody can make the hub request certificates for names that are
not an active field's (the CA's rate limits, and the hub's, would be theirs
to spend). It runs as a separate container (``tls-ask`` in
server/docker-compose.hosted.yml) on the internal networks only: Caddy never
proxies to it, so it cannot be reached from outside.

    uvicorn --factory atalaia_server.tls_ask:create_app --host 0.0.0.0 --port 8001 --workers 1

- 200 ``yes`` only for ``<slug>.<domain>`` (case and one trailing dot
  ignored) where the slug is in the registry (``public.atalaia_tenants``) and
  ``active``; a suspended field, any other name, the hub's own name and a
  name under a field's (``x.<slug>.<domain>``) get 404;
- every check is counted against one token bucket (``RATE`` a second, bursts
  of ``BURST``): past it, 429 without touching the database, so a flood of
  TLS handshakes with made-up names cannot flood PostgreSQL;
- 503 when the database cannot be read (Caddy then gets no certificate,
  which is the safe side); ``GET /health`` answers 200 without the database.

Settings: ATALAIA_DATABASE_URL (the server's role: it only needs to read the
registry, which that role may) and ATALAIA_HOSTED_DOMAIN.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Awaitable, Callable, Mapping, Optional
from urllib.parse import parse_qs

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from . import tenancy
from .config import HOSTED_DOMAIN, ConfigError, database_url_from_env

RATE = 5.0      # checks a second, sustained
BURST = 20      # checks at once
MAX_NAME = 253  # a DNS name's length
log = logging.getLogger("atalaia.tls_ask")

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
Lookup = Callable[[str], Awaitable[Optional[tenancy.Tenant]]]


class TokenBucket:
    """``rate`` tokens a second up to ``burst``; ``take`` is False when none is left."""

    def __init__(self, rate: float, burst: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.rate, self.burst, self.clock = rate, float(burst), clock
        self._tokens, self._at = float(burst), clock()
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            now = self.clock()
            self._tokens = min(self.burst, self._tokens + (now - self._at) * self.rate)
            self._at = now
            if self._tokens < 1.0:
                return False
            self._tokens -= 1.0
            return True


def check_domain(value: str) -> str:
    domain = (value or "").strip().lower()
    if not HOSTED_DOMAIN.fullmatch(domain):
        raise ConfigError("ATALAIA_HOSTED_DOMAIN must be a domain name such as hub.example.pt "
                          "(no scheme, port or path)")
    return domain


def slug_for(name: str, domain: str) -> Optional[str]:
    """The slug of ``<slug>.<domain>``, else None (another name, the hub's own, a deeper one, a port)."""
    if not name or len(name) > MAX_NAME + 1:
        return None
    name = name.lower()
    if name.endswith("."):
        name = name[:-1]
    suffix = "." + domain
    if not name.endswith(suffix):
        return None
    label = name[:-len(suffix)]
    return label if tenancy.TENANT_SLUG.fullmatch(label) else None


class AskApp:
    """The ASGI app: ``GET /check?domain=NAME`` and ``GET /health``."""

    def __init__(self, domain: str, lookup: Lookup, bucket: Optional[TokenBucket] = None,
                 close: Optional[Callable[[], Awaitable[None]]] = None) -> None:
        self.domain = check_domain(domain)
        self.lookup = lookup
        self.bucket = bucket or TokenBucket(RATE, BURST)
        self._close = close

    async def close(self) -> None:
        """Closes the database connections (at shutdown)."""
        if self._close is not None:
            await self._close()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        if scope["type"] != "http":
            return
        status, body = await self.answer(scope)
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                (b"content-length", str(len(body)).encode()), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": body})

    async def answer(self, scope: Scope) -> tuple[int, bytes]:
        path, method = scope.get("path"), scope.get("method")
        if path == "/health":
            return (200, b"ok\n") if method in ("GET", "HEAD") else (405, b"method not allowed\n")
        if path != "/check":
            return 404, b"not found\n"
        if method != "GET":
            return 405, b"method not allowed\n"
        if not self.bucket.take():
            return 429, b"too many checks\n"
        try:
            query = parse_qs(scope.get("query_string", b"").decode("ascii"), strict_parsing=True,
                             max_num_fields=4)
        except (UnicodeDecodeError, ValueError):
            return 400, b"bad query\n"
        names = query.get("domain", [])
        if len(names) != 1:
            return 400, b"one domain, please\n"
        slug = slug_for(names[0], self.domain)
        if slug is None:
            return 404, b"no\n"
        try:
            tenant = await self.lookup(slug)
        except Exception:  # noqa: BLE001  (the database is down: no certificate, the safe side)
            log.warning("tls-ask: the registry cannot be read")
            return 503, b"registry unavailable\n"
        if tenant is None or tenant.status != "active":
            return 404, b"no\n"
        return 200, b"yes\n"

    async def _lifespan(self, receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await self.close()
                await send({"type": "lifespan.shutdown.complete"})
                return


def create_app(env: Optional[Mapping[str, str]] = None) -> AskApp:
    """uvicorn's factory: the registry read through the server's role, connections with no schema on the path."""
    env = os.environ if env is None else env
    domain = check_domain(env.get("ATALAIA_HOSTED_DOMAIN", ""))
    engine: AsyncEngine = create_async_engine(database_url_from_env(env), pool_size=2, max_overflow=2,
                                              pool_pre_ping=True, pool_timeout=5,
                                              connect_args={"timeout": 5, **tenancy.engine_options()})

    async def lookup(slug: str) -> Optional[tenancy.Tenant]:
        return await tenancy.lookup(engine, slug)

    return AskApp(domain, lookup, close=engine.dispose)


__all__ = ["AskApp", "TokenBucket", "create_app", "slug_for"]
