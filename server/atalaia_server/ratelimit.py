# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rate limits and lockouts, in memory (ADR-P4-2).

- 5 failed logins from one IP address in 15 minutes lock that address out of
  logging in for 15 minutes (``Lockout``).
- 5 failed TOTP codes for one account in 15 minutes lock that account's TOTP
  checks for 15 minutes.
- 10 registrations from one IP address an hour.
- 100 API requests a minute from one IP address (``RequestLimitMiddleware``);
  the health check is not counted, so an uptime monitor never trips it.

The state is a dict per limit in the server's one worker process, as ADR-P4-2
chooses for single-site servers (a restart clears it). Each limit keeps at
most ``max_keys`` addresses or accounts; past that, entries that have expired
are dropped first, then the oldest, so a flood of addresses cannot grow the
memory without bound. Behind a reverse proxy the client address must come
from the proxy (uvicorn's ``--proxy-headers``, plan phase 22), or every
client would share the proxy's address.
"""

from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
from typing import Any, Callable

Clock = Callable[[], float]


class Lockout:
    """``limit`` failures within ``window_s`` lock the key for ``lock_s``."""

    def __init__(self, limit: int, window_s: float, lock_s: float, clock: Clock = time.monotonic,
                 max_keys: int = 100_000) -> None:
        self.limit, self.window_s, self.lock_s, self.max_keys = limit, window_s, lock_s, max_keys
        self.clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._locked: dict[str, float] = {}
        self._lock = threading.Lock()

    def retry_after(self, key: str) -> int:
        """Seconds until the key may try again; 0 if it is not locked."""
        with self._lock:
            until = self._locked.get(key)
            if until is None:
                return 0
            left = until - self.clock()
            if left <= 0:
                del self._locked[key]
                return 0
            return max(1, math.ceil(left))

    def fail(self, key: str) -> bool:
        """Counts a failure; True if this one locked the key."""
        with self._lock:
            now = self.clock()
            times = self._failures.pop(key, None) or deque()
            while times and times[0] <= now - self.window_s:
                times.popleft()
            times.append(now)
            if len(times) >= self.limit:
                self._locked[key] = now + self.lock_s
                self._prune(self._locked, now, lambda until: until <= now)
                return True
            self._failures[key] = times  # re-inserted: the dict stays in order of last use
            self._prune(self._failures, now, lambda t: not t or t[-1] <= now - self.window_s)
            return False

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked.pop(key, None)

    def _prune(self, table: dict[str, Any], now: float, expired: Callable[[Any], bool]) -> None:
        if len(table) <= self.max_keys:
            return
        for key in [k for k, v in table.items() if expired(v)]:
            del table[key]
        while len(table) > self.max_keys:
            del table[next(iter(table))]


class RequestLimit:
    """At most ``limit`` requests per key in any ``window_s`` (a sliding log)."""

    def __init__(self, limit: int, window_s: float, clock: Clock = time.monotonic, max_keys: int = 100_000) -> None:
        self.limit, self.window_s, self.max_keys = limit, window_s, max_keys
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str) -> int:
        """Counts a request; returns 0 if it is allowed, else the seconds to wait (it is not counted)."""
        with self._lock:
            now = self.clock()
            times = self._hits.pop(key, None) or deque()
            while times and times[0] <= now - self.window_s:
                times.popleft()
            if len(times) >= self.limit:
                self._hits[key] = times
                return max(1, math.ceil(times[0] + self.window_s - now))
            times.append(now)
            self._hits[key] = times
            if len(self._hits) > self.max_keys:
                for k in [k for k, t in self._hits.items() if t[-1] <= now - self.window_s]:
                    del self._hits[k]
                while len(self._hits) > self.max_keys:
                    del self._hits[next(iter(self._hits))]
            return 0


class Limits:
    """The limits of one application (``app.state.limits``)."""

    def __init__(self, clock: Clock = time.monotonic) -> None:
        self.login = Lockout(5, 15 * 60, 15 * 60, clock)          # per IP address
        self.totp = Lockout(5, 15 * 60, 15 * 60, clock)           # per account
        self.register = Lockout(10, 3600, 3600, clock)            # per IP address (each one counts)
        self.requests = RequestLimit(100, 60, clock)              # per IP address


UNLIMITED_PATHS = ("/api/v1/health",)


def client_ip(scope: dict[str, Any]) -> str:
    client = scope.get("client")
    return client[0] if client else "unknown"


def too_many(retry_after: int) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    body = json.dumps({"detail": "too_many_requests"}).encode()
    headers = [(b"content-type", b"application/json"), (b"retry-after", str(retry_after).encode()),
               (b"content-length", str(len(body)).encode())]
    return 429, headers, body


class RequestLimitMiddleware:
    """A plain ASGI middleware: 429 with Retry-After past the per-address request limit."""

    def __init__(self, app: Any, get_limits: Callable[[], Limits]) -> None:
        self.app = app
        self._get = get_limits  # read per request, so a test can swap the app's limits

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api/") or scope["path"] in UNLIMITED_PATHS:
            await self.app(scope, receive, send)
            return
        wait = self._get().requests.hit(client_ip(scope))
        if not wait:
            await self.app(scope, receive, send)
            return
        status, headers, body = too_many(wait)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
