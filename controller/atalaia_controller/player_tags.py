# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed player tags for the GM console and the marshal's app (decision TW-1, protocol/nfc-tag.md).

``POST /api/v1/games/{id}/tags`` with ``{"player": "p-17", "team": "blue"}`` answers the bytes of
one player tag, signed with the live game's key, ready for whoever writes the NFC tag: the console
(Web NFC, or a download for a phone app), the phone controller's own screen, or the marshal's app
(which no longer needs the field join key for it). The game key never leaves the controller: only
the tag's own MAC, which is what the box checks, goes out.
"""

from __future__ import annotations

from typing import Any

from atalaia_sim import join as joinfmt
from atalaia_sim import tag as tagfmt

from .checkin import Forbidden, Viewer
from .engine import Conflict, Controller, ControllerError

_FIELDS = {"player", "team"}


def issue(ctrl: Controller, viewer: Viewer, game_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """The tag for ``body`` in game ``game_id``: staff only (the GM token, or a marshal's for this game)."""
    if not viewer.is_staff:
        raise Forbidden("staff only: the GM token or a marshal's token")
    if viewer.kind == "player" and viewer.game_id != game_id:
        raise Forbidden("this token is for another game")
    game = ctrl.get_game(game_id)  # 404 for a game that does not exist
    unknown = sorted(set(body) - _FIELDS)
    if unknown:
        raise ControllerError(f"unknown fields {unknown}")
    player = body.get("player")
    if not tagfmt.player_ok(player):
        raise ControllerError("player: 1-32 letters, digits, '-', '_' or '.'")
    teams = game["teams"]
    name = body.get("team")
    if name in (None, ""):
        team = 0
        name = None
    elif isinstance(name, str) and name in teams:
        team = teams.index(name) + 1
    else:
        raise ControllerError(f"team: one of {teams}, or none")
    if not 0 < game_id <= 0xFFFF:
        raise Conflict(f"game {game_id}: a tag holds a 16-bit game id")
    key = ctrl.game_key(game_id)  # 409 when the game is not live here (or its key was lost)
    payload = tagfmt.encode({"player": player, "team": team, "game_id": game_id}, key)
    message = joinfmt.ndef_record(payload, tagfmt.NDEF_TYPE)
    return {"game_id": game_id, "player": player, "team": name, "team_id": team,
            "mime": tagfmt.NDEF_TYPE.decode(), "payload": payload.hex(), "ndef": message.hex(),
            "memory": tagfmt.to_ndef_tag(payload).hex()}
