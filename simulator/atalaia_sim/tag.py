# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Player tags (ADR-P3-9, protocol/nfc-tag.md): Python side of core/src/tag.c.

    version (1, = 1) | player (1-32 bytes) | team (1) | game_id (2, BE) | mac (16)

mac is HMAC-SHA256 over everything before it, keyed with the game's 16-byte
key and truncated to 16 bytes. A tag is a dict:

    {"player": "p-17", "team": 2, "game_id": 4242}

team is the 1-based team id in the game (0: no team). Both codecs check
protocol/vectors/tag.json.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Optional

from . import join

VERSION = 1
MAC_SIZE = 16
KEY_SIZE = 16
PLAYER_MAX = 32
MIN_LEN = 1 + 1 + 1 + 2 + MAC_SIZE
MAX_LEN = 1 + PLAYER_MAX + 1 + 2 + MAC_SIZE
NDEF_TYPE = b"application/vnd.atalaia.tag"
_PLAYER = re.compile(r"^[A-Za-z0-9._-]{1,32}$")


class TagError(ValueError):
    """A tag that cannot be used. ``reason`` is one of format, version, game, mac, team."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def player_ok(player: Any) -> bool:
    return isinstance(player, str) and _PLAYER.fullmatch(player) is not None


def _mac(game_key: bytes, msg: bytes) -> bytes:
    return hmac.new(game_key, msg, hashlib.sha256).digest()[:MAC_SIZE]


def encode(tag: dict[str, Any], game_key: bytes) -> bytes:
    if len(game_key) != KEY_SIZE:
        raise ValueError("the game key is 16 bytes")
    if not player_ok(tag["player"]):
        raise ValueError(f"player id {tag['player']!r}: 1-32 letters, digits, '-', '_' or '.'")
    team, game_id = int(tag["team"]), int(tag["game_id"])
    if not 0 <= team <= 255 or not 0 <= game_id <= 0xFFFF:
        raise ValueError("team is 0-255 and game_id 0-65535")
    body = bytes([VERSION]) + tag["player"].encode() + bytes([team]) + game_id.to_bytes(2, "big")
    return body + _mac(game_key, body)


def decode(data: bytes, game_id: int, game_key: bytes, team_count: int) -> dict[str, Any]:
    """The tag in data, checked for the game; raises TagError (same checks and order as C)."""
    if not MIN_LEN <= len(data) <= MAX_LEN:
        raise TagError("format", f"a tag is {MIN_LEN} to {MAX_LEN} bytes, not {len(data)}")
    if data[0] != VERSION:
        raise TagError("version", f"unknown tag version {data[0]}")
    body, mac = data[:-MAC_SIZE], data[-MAC_SIZE:]
    gid = int.from_bytes(body[-2:], "big")
    if gid != game_id:
        raise TagError("game", f"the tag is for game {gid}, not {game_id}")
    if not hmac.compare_digest(_mac(game_key, body), mac):
        raise TagError("mac", "the signature does not match")
    raw_player = body[1:-3]
    try:
        player = raw_player.decode("ascii")
    except UnicodeDecodeError:
        player = ""
    if not player_ok(player):
        raise TagError("format", "malformed player id")
    team = body[-3]
    if team > team_count:
        raise TagError("team", f"team {team} is not one of the game's {team_count}")
    return {"player": player, "team": team, "game_id": gid}


def to_ndef_tag(payload: bytes) -> bytes:
    """A Type 2 tag's user memory (page 4 on) holding the tag's NDEF record."""
    return join.to_ndef_tag(payload, NDEF_TYPE)


def from_ndef_tag(mem: bytes) -> Optional[bytes]:
    return join.from_ndef_tag(mem, NDEF_TYPE)


def event_data(uid: bytes, payload: Optional[bytes], game_id: int, game_key: Optional[bytes],
               teams: list[str]) -> dict[str, Any]:
    """The data of the nfc.tag input event, as atalaia_tag_event_json writes it."""
    data: dict[str, Any] = {"uid": uid[:10].hex(), "valid": False}
    if payload is None:
        data["reason"] = "unsigned"
        return data
    if game_key is None:
        data["reason"] = "no_game"
        return data
    try:
        tag = decode(payload, game_id, game_key, len(teams))
    except TagError as exc:
        data["reason"] = exc.reason
        return data
    data["valid"] = True
    data["player"] = tag["player"]
    if tag["team"]:
        data["team"] = teams[tag["team"] - 1]
    return data
