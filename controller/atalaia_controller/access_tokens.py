# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Short-lived, scoped, revocable access tokens (maintainer decision of 2026-11-01).

Until now the controller had two tokens that never expire: the GM token and the read token. A referee's
phone for one game day, a visiting GM, an automated test run or a spectator screen should not be given
those. The GM (the main GM token only; a made token can never make another) makes a token with a label, a
scope, an expiry and, optionally, one game:

* ``read``: what the read token does (the game's public data, no GM actions).
* ``gm``: what the GM token does, except managing these tokens.
* ``marshals``: the read token's view plus listing, adding, editing and removing marshals (the roster and
  their keys) and nothing else: the narrow scope an automated run needs to add and remove a test marshal.

``game_id`` (scopes ``read`` and ``gm``) limits the token to one game: a route that names a game
(``/games/{game_id}/...``) refuses another one, and a route that names none refuses everything but reads.
Reads that are the same for every viewer (the list of games, the stream) still show every game; the limit
bounds what the token can *change*, not what the read token can see.

A token is ``atk_<id>.<secret>``: ``id`` is 8 hex digits (public, how the token is found, listed and
revoked), ``secret`` is 256 random bits. Only the SHA-256 of the secret is stored (a 256-bit secret needs no
slow hash), and the comparison is constant time. The token is shown once, when it is made.

Where the rules are enforced: ``api.create_app`` puts ``gate`` in front of every route (HTTP and the stream's
WebSocket). It is the one place that resolves the token, refuses a scope's or game's violation and says what
role the token has on this route; the routes' own ``require_*`` checks then read that answer, so a new route
is covered with no change here (the test builds its list of routes from the router).

Time: expiry is judged by the controller's own wall clock, ``Controller._wall`` (the same clock as a game's
created_at), in ``AccessTokens.live`` and nowhere else. A token made when the clock was ahead of what it is
now (a clock set back) is refused: ``live`` fails closed.
"""

from __future__ import annotations

import collections
import hashlib
import hmac
import logging
import re
import secrets
import threading
import time
from typing import Any, Callable, Optional

from .store import Store

log = logging.getLogger("atalaia")

PREFIX = "atk_"
TOKEN_RE = re.compile(r"atk_([0-9a-f]{8})\.([A-Za-z0-9_-]{43})")
SCOPES = ("read", "gm", "marshals")
GAME_SCOPES = ("read", "gm")  # the scopes a single game can limit
BASE_ROLE = {"read": "read", "gm": "gm", "marshals": "read"}
# The extra routes a narrow scope may use as the GM would, as (method, route template).
GRANTS: dict[str, frozenset[tuple[str, str]]] = {
    "marshals": frozenset({("GET", "/api/v1/marshals"), ("POST", "/api/v1/marshals"),
                           ("PATCH", "/api/v1/marshals/{marshal_id}"), ("DELETE", "/api/v1/marshals/{marshal_id}")}),
}
MANAGE_PREFIX = "/api/v1/tokens"  # this API: only the main GM token
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

DEFAULT_TTL_S = 8 * 3600
MAX_TTL_S = 7 * 86400
MIN_TTL_S = 60
MAX_ACTIVE = 50
LABEL_MAX = 60
SKEW_S = 60               # a token "from the future" by more than this (the clock was set back) is refused
FAILS_PER_MINUTE = 60     # unknown or wrong tokens per address; then 429 until the minute is over
USE_LOG_EVERY_S = 600     # one "used" audit line per token per 10 minutes
TOUCH_EVERY_S = 10        # last_used_at is written at most this often per token
PURGE_EVERY_S = 600
STREAM_RECHECK_S = 5      # an open stream asks again whether its token is still valid this often
PURGE_GRACE_S = 3600      # an expired token stays listed (as expired) this long


class TokenError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class TooManyFailures(Exception):
    pass


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def effective_role(scope: str, method: str, route_path: str) -> str:
    """The role a token of ``scope`` has on one route."""
    if (method.upper(), route_path) in GRANTS.get(scope, ()):
        return "gm"
    return BASE_ROLE[scope]


def ceiling_role(scope: str) -> str:
    """The most a token of ``scope`` can ever be (what the plain-HTTP guard judges it by)."""
    return "gm" if scope == "gm" or scope in GRANTS else "read"


def denial(rec: dict[str, Any], method: str, route_path: str, params: dict[str, Any]) -> Optional[str]:
    """Why a valid token may not make this request (a 403), or None."""
    if route_path.startswith(MANAGE_PREFIX):
        return "access tokens are made and revoked with the main GM token only"
    game = rec.get("game_id")
    if game is not None:
        asked = params.get("game_id")
        if asked is not None:
            if str(asked) != str(game):
                return f"this token is limited to game {game}"
        elif method.upper() not in SAFE_METHODS:
            return f"this token is limited to game {game}: it changes nothing outside it"
    return None


def clean_label(label: Any) -> str:
    if not isinstance(label, str):
        raise TokenError("label: a text")
    label = " ".join(label.split())  # also folds newlines and tabs: a label goes in logs and audit lines
    if not label or len(label) > LABEL_MAX or not label.isprintable():
        raise TokenError(f"label: 1 to {LABEL_MAX} printable characters")
    return label


class AccessTokens:
    def __init__(self, store: Store, wall: Callable[[], float]) -> None:
        self.store = store
        self._wall = wall  # the controller's wall clock: the only time source here
        self._lock = threading.Lock()
        self._fails: dict[str, collections.deque] = {}
        self._noted: dict[tuple[str, str], float] = {}
        self._touched: dict[str, float] = {}
        self._last_purge = 0.0

    # --- time: the one place expiry is judged ------------------------------------------------

    def live(self, row: dict[str, Any], now: Optional[float] = None) -> bool:
        now = self._wall() if now is None else now
        return row["revoked_at"] is None and row["created_at"] - SKEW_S <= now < row["expires_at"]

    # --- making, listing, revoking ------------------------------------------------------------

    def create(self, body: dict[str, Any], by: str = "GM") -> dict[str, Any]:
        unknown = set(body) - {"label", "scope", "ttl_s", "game_id"}
        if unknown:
            raise TokenError(f"unknown field: {sorted(unknown)[0]}")
        label = clean_label(body.get("label"))
        scope = body.get("scope")
        if scope not in SCOPES:
            raise TokenError(f"scope: one of {', '.join(SCOPES)}")
        ttl = body.get("ttl_s", DEFAULT_TTL_S)
        if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not MIN_TTL_S <= ttl <= MAX_TTL_S:
            raise TokenError(f"ttl_s: {MIN_TTL_S} to {MAX_TTL_S} seconds (at most 7 days; default {DEFAULT_TTL_S})")
        game = body.get("game_id")
        if game is not None:
            if scope not in GAME_SCOPES:
                raise TokenError("game_id: only for the read and gm scopes")
            if isinstance(game, bool) or not isinstance(game, int) or game < 1:
                raise TokenError("game_id: a game's number")
            if self.store.game(game) is None:
                raise TokenError(f"game_id: no game {game}", 404)
        now = self._wall()
        with self._lock:
            active = [r for r in self.store.access_tokens() if self.live(r, now)]
            if len(active) >= MAX_ACTIVE:
                raise TokenError(f"already {MAX_ACTIVE} active tokens: revoke some first", 409)
            secret = secrets.token_urlsafe(32)  # 43 characters, 256 bits
            while True:
                token_id = secrets.token_hex(4)
                if self.store.access_token(token_id) is None:
                    break
            row = {"id": token_id, "label": label, "scope": scope, "game_id": game,
                   "secret_hash": hash_secret(secret), "created_at": now, "expires_at": now + float(ttl),
                   "revoked_at": None}
            self.store.add_access_token(row)
        self.store.add_token_audit(now, "created", token_id, label, scope,
                                   f"by {by}; expires in {int(ttl)} s" + (f"; game {game}" if game else ""))
        log.warning("access token %s (%s, %s) made by %s, expires in %d s", token_id, label, scope, by, int(ttl))
        return {**self.public(row, now), "token": f"{PREFIX}{token_id}.{secret}"}

    def public(self, row: dict[str, Any], now: Optional[float] = None) -> dict[str, Any]:
        now = self._wall() if now is None else now
        status = "revoked" if row["revoked_at"] is not None else "expired" if now >= row["expires_at"] else "active"
        return {"id": row["id"], "label": row["label"], "scope": row["scope"], "game_id": row["game_id"],
                "created_at": row["created_at"], "expires_at": row["expires_at"],
                "last_used_at": row.get("last_used_at"), "last_used_from": row.get("last_used_from"),
                "revoked_at": row["revoked_at"], "status": status}

    def list(self) -> list[dict[str, Any]]:
        now = self._wall()
        return [self.public(r, now) for r in self.store.access_tokens()]

    def revoke(self, token_id: str, by: str = "GM") -> dict[str, Any]:
        row = self.store.access_token(token_id)
        if row is None:
            raise TokenError("no such token", 404)
        now = self._wall()
        if self.store.revoke_access_token(token_id, now):
            self.store.add_token_audit(now, "revoked", token_id, row["label"], row["scope"], f"by {by}")
            log.warning("access token %s (%s) revoked by %s", token_id, row["label"], by)
        return self.public(self.store.access_token(token_id) or row, now)

    def audit(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.store.token_audit(max(1, min(limit, 1000)))

    def purge(self, force: bool = False) -> int:
        now = self._wall()
        if not force and abs(now - self._last_purge) < PURGE_EVERY_S:
            return 0
        self._last_purge = now
        return self.store.purge_access_tokens(now - PURGE_GRACE_S)

    # --- using ---------------------------------------------------------------------------------

    def _blocked(self, client: str) -> bool:
        q = self._fails.get(client)
        return bool(q) and len(q) >= FAILS_PER_MINUTE and self._mono() - q[0] < 60

    @staticmethod
    def _mono() -> float:
        return time.monotonic()  # a spacing between failures, not a date: not the wall clock

    def _failed(self, client: str) -> None:
        now = self._mono()
        with self._lock:
            q = self._fails.setdefault(client, collections.deque())
            q.append(now)
            while q and now - q[0] >= 60 or len(q) > FAILS_PER_MINUTE:
                q.popleft()
            if len(self._fails) > 10_000:
                for k in [k for k, v in self._fails.items() if not v or now - v[-1] >= 60]:
                    del self._fails[k]

    def verify(self, token: Optional[str], client: Optional[str] = None) -> Optional[dict[str, Any]]:
        """The stored row of a valid token, or None. ``client``: the address, for the failure limit
        (None: a look-up that counts nothing, such as the plain-HTTP guard's). Raises TooManyFailures
        when this address has sent too many unknown or wrong tokens."""
        if not token or not token.startswith(PREFIX):
            return None
        if client is not None and self._blocked(client):
            raise TooManyFailures
        m = TOKEN_RE.fullmatch(token)
        row = self.store.access_token(m.group(1)) if m else None
        # A wrong id costs the same comparison as a wrong secret.
        expected = row["secret_hash"] if row else hash_secret("x")
        given = hash_secret(m.group(2)) if m else hash_secret("y")
        if not hmac.compare_digest(expected.encode(), given.encode()) or row is None:
            if client is not None:
                self._failed(client)
            return None
        return row if self.live(row) else None

    def note_use(self, row: dict[str, Any], source: str) -> None:
        """Last-used time and the rate-limited "used" audit line."""
        now = self._wall()
        tid = row["id"]
        with self._lock:
            touch = now - self._touched.get(tid, 0.0) >= TOUCH_EVERY_S or now < self._touched.get(tid, 0.0)
            if touch:
                self._touched[tid] = now
            log_it = self._rate_ok((tid, "used"), now, USE_LOG_EVERY_S)
        if touch:
            self.store.touch_access_token(tid, now, source)
        if log_it:
            self.store.add_token_audit(now, "used", tid, row["label"], row["scope"], f"from {source}")

    def note_refused(self, row: dict[str, Any], why: str, source: str) -> None:
        now = self._wall()
        with self._lock:
            log_it = self._rate_ok((row["id"], "refused"), now, USE_LOG_EVERY_S)
        if log_it:
            self.store.add_token_audit(now, "refused", row["id"], row["label"], row["scope"], f"{why}; from {source}")
            log.warning("access token %s (%s) refused: %s", row["id"], row["label"], why)

    def _rate_ok(self, key: tuple[str, str], now: float, every: float) -> bool:
        last = self._noted.get(key)
        if last is not None and 0 <= now - last < every:
            return False
        if len(self._noted) > 5000:
            self._noted.clear()
        self._noted[key] = now
        return True
