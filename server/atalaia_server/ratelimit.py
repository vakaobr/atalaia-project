# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rate limits and lockouts, in memory (ADR-P4-2).

- 5 failed logins for one username from one IP address in 15 minutes lock
  that username out of logging in from that address for 15 minutes
  (``Lockout``, key ``login_key(address, username)``), and 50 failed logins
  from one address in 15 minutes, whatever the usernames, lock the whole
  address for 15 minutes (against password spraying). Players at a field
  share one 4G/NAT address, so one player's typos must not lock everyone out
  (decisions S11-12, S12-1). The typed username is kept only as a truncated
  SHA-256 inside the key, never as text.
- 5 failed TOTP codes for one account in 15 minutes lock that account's TOTP
  checks for 15 minutes.
- 10 registrations from one IP address an hour.
- 5 reports of club pages from one IP address an hour (plan phase 18).
- 5 feedback forms from one IP address an hour, and 300 a day in all (a preview server's form, decision PV-8).
- 30 remote GM commands a minute from one account (plan phase 19).
- 20 ATAK certificates an hour from one account, and 30 new connections a
  minute (16 open at once) from one address to the ATAK relay (Phase 4
  follow-up FU5; the relay keeps its own, ``atak_relay.py``), and 120 ``cot``
  messages a minute from one field's controller (FU5-15).
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

import hashlib
import json
import math
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

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


def login_key(address: str, username: str, tenant: Optional[str] = None) -> str:
    """The per (address, username) lockout key; the username only as a truncated hash, so a
    password typed into the username box never sits in memory as text."""
    digest = hashlib.sha256(username.strip().lower().encode("utf-8", "surrogatepass")).hexdigest()[:32]
    if tenant is not None:  # hosted mode: one field's "ana" is not another's (plan phase 21)
        return f"{address}#{tenant}#{digest}"
    return f"{address}#{digest}"


class Limits:
    """The limits of one application (``app.state.limits``)."""

    def __init__(self, clock: Clock = time.monotonic) -> None:
        self.login = Lockout(5, 15 * 60, 15 * 60, clock)          # per (IP address, username): login_key()
        self.login_address = Lockout(50, 15 * 60, 15 * 60, clock)  # per IP address, any username
        self.totp = Lockout(5, 15 * 60, 15 * 60, clock)           # per account
        self.register = Lockout(10, 3600, 3600, clock)            # per IP address (each one counts)
        self.requests = RequestLimit(100, 60, clock)              # per IP address
        self.reports = RequestLimit(5, 3600, clock)               # club page reports per IP address (plan phase 18)
        self.feedback = RequestLimit(5, 3600, clock)              # preview feedback forms per IP address (PV-8)
        self.feedback_total = RequestLimit(300, 86400, clock)     # ... and all together, so the table cannot be flooded
        self.remote_commands = RequestLimit(30, 60, clock)        # remote GM commands per account (plan phase 19)
        self.atak_issue = RequestLimit(20, 3600, clock)           # ATAK certificates per account (FU5)
        self.hub_share = RequestLimit(10, 3600, clock)            # link codes and links per account (SVX-2)
        self.atak_cot = RequestLimit(120, 60, clock)              # a controller's cot messages per field (FU5-15)


UNLIMITED_PATHS = ("/api/v1/health",)
# The API, the public field pages and feeds (plan phase 15), the club pages (plan phase 18), the staff pages
# (decision FU2-9) and a preview server's feedback form (PV-8) share the per-address limit.
LIMITED_PREFIXES = ("/api/", "/f/", "/c/", "/staff", "/feedback")


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
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith(LIMITED_PREFIXES) or path in UNLIMITED_PATHS:
            await self.app(scope, receive, send)
            return
        wait = self._get().requests.hit(client_ip(scope))
        if not wait:
            await self.app(scope, receive, send)
            return
        status, headers, body = too_many(wait)
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
