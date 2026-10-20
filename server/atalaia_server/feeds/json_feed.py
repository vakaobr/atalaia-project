# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The JSON feed of a field's games (ADR-P4-12, decision F19): ``atalaia.games`` version 1.

    GET /f/<slug>/games.json

The format is the JSON Schema ``server/schemas/games-feed-v1.schema.json`` and is described
in ``server/docs/feeds.md``. Times are RFC 3339 in UTC with a ``Z``, to the second. Version 1
may gain optional members; anything a reader of version 1 could misread gets a new
``version`` and a new path. Plain Python (no third-party import).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from . import FeedField, FeedGame

FORMAT = "atalaia.games"
VERSION = 1
MEDIA_TYPE = "application/json"


def rfc3339(value: Optional[datetime]) -> Optional[str]:
    """``2026-11-08T09:00:00Z`` (RFC 3339, UTC, whole seconds), or None."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("a time zone-aware datetime is needed")
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def game_json(game: FeedGame, f: FeedField) -> dict[str, Any]:
    return {
        "id": str(game.id),
        "title": game.title,
        "description": game.description,
        "starts_at": rfc3339(game.starts_at),
        "ends_at": rfc3339(game.ends_at),
        "status": game.status,
        "cancelled_reason": game.cancelled_reason if game.status == "cancelled" else None,
        "mode": game.mode_id,
        "teams": list(game.teams),
        "location": game.location,
        "registration": {
            "opens_at": rfc3339(game.registration_opens_at),
            "closes_at": rfc3339(game.registration_closes_at),
            "open": game.registration_open,
            "max_players": game.max_players,
            "places_left": game.places_left,
        },
        "requirements": {
            "federation": game.federation,
            "federation_label": f.federation_label if game.federation != "off" else None,
        },
        "url": game.page_url(f),
        "ics": game.ics_url(f),
        "updated_at": rfc3339(game.updated_at),
    }


def feed(f: FeedField, games: Iterable[FeedGame]) -> dict[str, Any]:
    return {
        "format": FORMAT,
        "version": VERSION,
        "field": {"slug": f.slug, "name": f.name, "timezone": f.timezone, "url": f.page_url,
                  "description": f.description, "address": f.address},
        "games": [game_json(g, f) for g in games],
    }


def dumps(document: dict[str, Any]) -> str:
    """The feed's bytes: UTF-8 JSON, keys in a fixed order, so the same games give the same ETag."""
    return json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
