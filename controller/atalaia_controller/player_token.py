# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Player tokens (ADR-P3-9, protocol/player-token.md): issue and verify.

    apt1.<base64url(payload)>.<base64url(HMAC-SHA256(key, "apt1." + base64url(payload)))>

payload is canonical JSON (sorted keys, no spaces) with exp, game_id,
player_id, role, squad and team. The Dart side is app/lib/security/
player_token.dart; both check protocol/vectors/player_token.json.

Not wired into the API yet: issuing tokens at join and checking them on
the position and chrono endpoints is plan phase E.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Any

PREFIX = "apt1"
MAC_SIZE = 32
KEY_MIN, KEY_MAX = 16, 64
TOKEN_MAX = 512
ROLES = ("player", "squad_leader", "vip", "marshal", "gm", "spectator")
FIELDS = ("exp", "game_id", "player_id", "role", "squad", "team")
INTS = {"exp": (1, 0xFFFFFFFF), "game_id": (1, 0xFFFE), "squad": (0, 255), "team": (0, 8)}
PLAYER_RE = re.compile(r"[A-Za-z0-9._-]{1,32}")
B64URL_RE = re.compile(r"[A-Za-z0-9_-]+")
VERSION_RE = re.compile(r"apt[0-9]{1,3}")


class TokenError(ValueError):
    """A token that is refused. ``reason``: format, version, mac, game, team or expired."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    if not B64URL_RE.fullmatch(text) or len(text) % 4 == 1:
        raise TokenError("format", "not base64url")
    raw = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    if _b64(raw) != text:
        raise TokenError("format", "not canonical base64url")
    return raw


def _key(key: bytes) -> bytes:
    if not KEY_MIN <= len(key) <= KEY_MAX:
        raise ValueError(f"the token key is {KEY_MIN}-{KEY_MAX} bytes")
    return key


def check_claims(claims: Any) -> dict[str, Any]:
    if not isinstance(claims, dict) or set(claims) != set(FIELDS):
        raise TokenError("format", f"the payload has exactly the fields {FIELDS}")
    for name, (lo, hi) in INTS.items():
        v = claims[name]
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise TokenError("format", f"{name} is an integer {lo}-{hi}")
    if not isinstance(claims["player_id"], str) or not PLAYER_RE.fullmatch(claims["player_id"]):
        raise TokenError("format", "player_id is 1-32 letters, digits, '.', '_' or '-'")
    if claims["role"] not in ROLES:
        raise TokenError("format", f"role is one of {ROLES}")
    return dict(claims)


def payload_bytes(claims: dict[str, Any]) -> bytes:
    return json.dumps(check_claims(claims), sort_keys=True, separators=(",", ":")).encode("ascii")


def _mac(key: bytes, signed: str) -> bytes:
    return hmac.new(key, signed.encode("ascii"), hashlib.sha256).digest()


def issue(claims: dict[str, Any], key: bytes) -> str:
    signed = PREFIX + "." + _b64(payload_bytes(claims))
    return signed + "." + _b64(_mac(_key(key), signed))


def verify(token: Any, key: bytes, *, game_id: int, team_count: int, now: int) -> dict[str, Any]:
    """The token's claims, checked for the game at time now (Unix seconds); raises TokenError."""
    _key(key)
    if not isinstance(token, str) or not token.isascii() or not 0 < len(token) <= TOKEN_MAX:
        raise TokenError("format", "a token is 1-512 ASCII characters")
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("format", "a token has three parts")
    if parts[0] != PREFIX:
        if VERSION_RE.fullmatch(parts[0]):
            raise TokenError("version", f"unknown token version {parts[0]}")
        raise TokenError("format", "not a player token")
    payload = _unb64(parts[1])
    mac = _unb64(parts[2])
    if len(mac) != MAC_SIZE:
        raise TokenError("format", "the MAC is 32 bytes")
    if not hmac.compare_digest(_mac(key, parts[0] + "." + parts[1]), mac):
        raise TokenError("mac", "the token's MAC does not match")
    try:
        claims = check_claims(json.loads(payload.decode("utf-8")))
    except (ValueError, UnicodeDecodeError) as exc:
        if isinstance(exc, TokenError):
            raise
        raise TokenError("format", "the payload is not JSON") from None
    if payload_bytes(claims) != payload:
        raise TokenError("format", "the payload is not canonical JSON")
    if claims["game_id"] != game_id:
        raise TokenError("game", f"the token is for game {claims['game_id']}, not {game_id}")
    if claims["team"] > team_count:
        raise TokenError("team", f"team {claims['team']} is not one of the game's {team_count}")
    if now >= claims["exp"]:
        raise TokenError("expired", "the token has expired")
    return claims
