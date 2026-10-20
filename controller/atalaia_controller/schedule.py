# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Games made from the site server's schedule (ADR-P4-11; phase 4, plan phase 16).

With sync on, the sync client pulls the field's published games of the coming days
(``GET /api/v1/sync/schedule``) into the store (``schedule_games``, store schema 7). The GM
picks one in the console (*Create from the schedule*): the controller game takes its
title, mode and teams unless the GM gives others, and the store links the two
(``schedule_links``). From then on the sync client pulls that scheduled game's roster
until the game starts (``Checkin.apply_roster``), the game's metadata names the
scheduled game (so the site server shows it in progress, then completed), and after the
game its registrations' outcomes go back (``Checkin.outcomes``).

The schedule never drives the controller: nothing here runs unless the GM asks, a game
made from the schedule is an ordinary game, and the GM can change everything about it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from .engine import Conflict, ControllerError, NotFound

if TYPE_CHECKING:
    from .engine import Controller

TEAM_MAX = 23  # bytes: the radio's team names (the core's ATALAIA_TEAM_NAME_MAX - 1)
NAME_MAX = 64
USABLE = ("published", "in_progress")


def schedule(ctrl: "Controller") -> dict[str, Any]:
    """GET /api/v1/schedule: the scheduled games as last pulled, each with the controller games made from it."""
    links: dict[str, list[int]] = {}
    for link in ctrl.store.schedule_links():
        game = ctrl.store.game(link["game_id"])
        if game is not None and int(game["game_seed"]) == int(link["game_seed"]):
            links.setdefault(link["scheduled_game_id"], []).append(link["game_id"])
    games = [{**g, "games": links.get(g["scheduled_game_id"], [])} for g in ctrl.store.schedule()]
    pulled = max((g["pulled_at"] for g in games), default=None)
    sync = getattr(ctrl, "sync", None)
    return {"enabled": sync is not None, "pulled_at": pulled, "games": games}


def _teams(scheduled: dict[str, Any]) -> list[str]:
    teams = [t for t in scheduled.get("teams") or [] if isinstance(t, str)]
    if teams and (len(teams) > 8 or any(not 0 < len(t.encode("utf-8")) <= TEAM_MAX for t in teams)):
        raise ControllerError("the scheduled game's teams do not fit the radio (1-8 names of up to "
                              f"{TEAM_MAX} bytes): give the teams")
    return teams


def create_game(ctrl: "Controller", scheduled_game_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """POST /api/v1/schedule/{id}/game: a controller game made from a scheduled game, linked to it.
    ``spec`` is what POST /api/v1/games takes; what it leaves out comes from the scheduled game (its
    title as the name, its mode, its teams, its length)."""
    scheduled = ctrl.store.schedule_game(scheduled_game_id)
    if scheduled is None:
        raise NotFound("no such scheduled game in the last schedule pulled")
    if scheduled["status"] not in USABLE:
        raise Conflict(f"the scheduled game is {scheduled['status']}")
    if not isinstance(spec, dict):
        raise ControllerError("a game's settings are an object")
    body = dict(spec)
    body.setdefault("name", scheduled["title"].strip()[:NAME_MAX].strip() or "Jogo")
    if not body.get("mode_id") and not body.get("preset_id") and scheduled.get("mode_id"):
        body["mode_id"] = scheduled["mode_id"]
    if "teams" not in body:
        teams = _teams(scheduled)
        if teams:
            body["teams"] = teams
    if "duration_ms" not in body:
        body["duration_ms"] = int(max(0, min(scheduled["ends_at"] - scheduled["starts_at"], 0xFFFFFFFF // 1000)) * 1000)
    game = ctrl.create_game(body)
    ctrl.store.link_schedule(game["id"], int(game["game_seed"]), scheduled_game_id, time.time())
    sync = getattr(ctrl, "sync", None)
    if sync is not None:
        sync.kick()  # the roster comes at once
    return {**game, "scheduled_game_id": scheduled_game_id}
