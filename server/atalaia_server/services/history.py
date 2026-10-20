# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Game history: the views of the synced games (plan phase 20; ADR-P4-3, P4R10, P4R25).

- **The score timeline** is derived from the per-node counters: every rise of a counter the site server
  receives is kept (``game_score_samples``, written by ``record_samples`` when ``POST /api/v1/sync/scores``
  raises a counter), and the totals at each moment are the controller's rule (``sync_format.totals``: the
  counters' sum per team plus every ``score.delta`` received by then, negative ones included). Its times are
  when the site server received them (the controller syncs every 30 s during a game), counted from the game's
  start (decision S20-3).
- **Who sees what.** Staff (the field's admin, gm and marshal, the game's gm and marshal) see everything as
  it is. Anyone else with a role on the field or the game (players, spectators) sees a live game's log, totals
  and timeline ``spectator_delay_s`` behind (the field's setting, 60 s by default), and a log without the
  ``gm_only`` data (``visibility.public_event``, the controller's rule), without telemetry and without the
  players' pseudonymous ids (decision S20-5). Once the game has ended there is no delay.
- **The public scoreboard** (``fields.public_scoreboard``, off by default) shows the field's live or last
  game's name, teams and delayed totals to anyone: no events, no players, no parameters.
- **Retention** (ADR-P4-8: game history 24 months, per field): ``retention_days`` (30-730) per field; the
  daily purge deletes a game, with everything that hangs off it, that many days after it ended.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from atalaia_controller import sync_format, visibility
from sqlalchemy import DateTime, func, literal, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..history_models import DEFAULT_DELAY_S, DEFAULT_RETENTION_DAYS, FieldHistorySettings, GameScoreSample
from ..models import Field, Game, GameEvent

LIVE = ("running", "paused")
STAFF_FIELD_ROLES = frozenset({"admin", "gm", "marshal"})
STAFF_GAME_ROLES = frozenset({"gm", "marshal"})
# Event data that names a person (the field's pseudonymous ids) or their replica: never shown to non-staff.
PERSONAL_KEYS = frozenset({"player", "owner", "holder", "replica"})
MAX_POINTS = 1000  # a timeline's points; a longer one keeps evenly spaced ones and the last
RECENT = timedelta(hours=12)  # the public scoreboard shows an ended game this long after its end


async def settings(db: AsyncSession, field_id: uuid.UUID) -> dict[str, Any]:
    row = await db.get(FieldHistorySettings, field_id)
    return {"spectator_delay_s": row.spectator_delay_s if row else DEFAULT_DELAY_S,
            "retention_days": row.retention_days if row else DEFAULT_RETENTION_DAYS}


async def record_samples(db: AsyncSession, game_id: uuid.UUID, rows: list[tuple[str, str, int]]) -> None:
    """The counters ``POST /api/v1/sync/scores`` raised (source, team, new value), for the timeline."""
    if rows:
        db.add_all([GameScoreSample(game=game_id, source=s, team=t, value=int(v)) for s, t, v in rows])
        await db.flush()


def is_staff(field_roles: set[str], game_roles: set[str]) -> bool:
    return bool(field_roles & STAFF_FIELD_ROLES or game_roles & STAFF_GAME_ROLES)


def cutoff(game: Game, delay_s: int, staff: bool, now: Optional[datetime] = None) -> Optional[datetime]:
    """What a viewer may see up to: None for everything (staff, or a game that has ended)."""
    if staff or game.state not in LIVE or delay_s <= 0:
        return None
    return (now or datetime.now(timezone.utc)) - timedelta(seconds=delay_s)


def _adjustment(team: Optional[str], data: Any) -> Optional[tuple[str, int]]:
    """A score.delta's (team, amount), as sync.totals reads it."""
    team = data.get("team", team) if isinstance(data, dict) else team
    amount = data.get("amount") if isinstance(data, dict) else None
    if isinstance(team, str) and isinstance(amount, int) and not isinstance(amount, bool):
        return team, amount
    return None


async def timeline(db: AsyncSession, game: Game, until: Optional[datetime]) -> list[dict[str, Any]]:
    """The totals after each batch of changes the site server received, up to ``until`` (None: all)."""
    samples = select(GameScoreSample.received_at, GameScoreSample.id, GameScoreSample.source, GameScoreSample.team,
                     GameScoreSample.value).where(GameScoreSample.game == game.id)
    deltas = select(GameEvent.received_at, GameEvent.id, GameEvent.team, GameEvent.data).where(
        GameEvent.game == game.id, GameEvent.event_type == "score.delta")
    if until is not None:
        samples = samples.where(GameScoreSample.received_at <= until)
        deltas = deltas.where(GameEvent.received_at <= until)
    changes: list[tuple[datetime, int, int, Any]] = []
    for at, sid, source, team, value in await db.execute(samples):
        changes.append((at, 0, sid, ("counter", source, team, int(value))))
    for at, eid, team, data in await db.execute(deltas):
        adj = _adjustment(team, data)
        if adj is not None:
            changes.append((at, 1, eid, ("delta", *adj)))
    changes.sort(key=lambda c: (c[0], c[1], c[2]))
    teams = list(game.teams)
    start = game.started_at or (changes[0][0] if changes else game.controller_created_at)
    points = [{"t": 0, "at": start.isoformat(), "totals": {t: 0 for t in teams}}]
    counters: dict[str, dict[str, int]] = {}
    adjustments: list[tuple[str, int]] = []
    for i, (at, _, _, change) in enumerate(changes):
        if change[0] == "counter":
            _, source, team, value = change
            row = counters.setdefault(source, {})
            row[team] = max(row.get(team, 0), value)
        else:
            adjustments.append((change[1], change[2]))
        if i + 1 < len(changes) and changes[i + 1][0] == at:
            continue  # one point per arrival
        points.append({"t": max(0, round((at - start).total_seconds())), "at": at.isoformat(),
                       "totals": sync_format.totals(teams, counters, adjustments)})
    if len(points) > MAX_POINTS:
        step = len(points) / (MAX_POINTS - 1)
        points = [points[int(i * step)] for i in range(MAX_POINTS - 1)] + [points[-1]]
    return points


async def totals_until(db: AsyncSession, game: Game, until: Optional[datetime]) -> dict[str, int]:
    """The totals as a viewer may know them: now (staff) or as they were at ``until``."""
    if until is None:
        from .. import sync  # noqa: PLC0415 (sync imports this module)

        return await sync.totals(db, game)
    return (await timeline(db, game, until))[-1]["totals"]


def winner(totals: dict[str, int]) -> Optional[str]:
    """The team with the most points, None on a tie or with no points at all."""
    if not totals:
        return None
    best = max(totals.values())
    leaders = [t for t, v in totals.items() if v == best]
    return leaders[0] if len(leaders) == 1 and best > 0 else None


def event_json(e: GameEvent, staff: bool) -> Optional[dict[str, Any]]:
    """One log entry as the viewer may see it; None for one a non-staff viewer does not get at all."""
    out = {"id": e.id, "node": e.node_id, "seq": e.seq, "t": e.game_time_ms, "type": e.event_type, "team": e.team,
           "squad": e.squad, "prio": e.priority, "data": e.data, "received_at": e.received_at.isoformat()}
    if staff:
        return {**out, "epoch": e.epoch, "pkt_seq": e.pkt_seq}
    if e.priority == "telemetry":
        return None
    out = visibility.public_event(out)
    data = out["data"] if isinstance(out["data"], dict) else {}
    return {**out, "data": {k: v for k, v in data.items() if k not in PERSONAL_KEYS}}


def game_summary(game: Game, totals: dict[str, int]) -> dict[str, Any]:
    names = {t: (game.team_info or {}).get(t, {}).get("display_name") for t in game.teams}
    return {"id": str(game.id), "name": game.name, "mode_id": game.mode_id, "state": game.state,
            "teams": [{"team": t, "display_name": names[t], "score": totals.get(t, 0)} for t in game.teams],
            "winner": winner(totals) if game.state == "ended" else None,
            "started_at": game.started_at.isoformat() if game.started_at else None,
            "ended_at": game.ended_at.isoformat() if game.ended_at else None}


async def public_game(db: AsyncSession, field_id: uuid.UUID, now: datetime) -> Optional[Game]:
    """The game a public scoreboard shows: the live one started last, else one that ended in the last 12 hours."""
    live = await db.scalar(select(Game).where(Game.field_id == field_id, Game.state.in_(LIVE))
                           .order_by(Game.started_at.desc().nulls_last(), Game.controller_created_at.desc()).limit(1))
    if live is not None:
        return live
    # A game.end event ends a game without an end time from the controller's metadata: then its last update.
    ended = func.coalesce(Game.ended_at, Game.updated_at)
    return await db.scalar(select(Game).where(Game.field_id == field_id, Game.state == "ended", ended >= now - RECENT)
                           .order_by(ended.desc()).limit(1))


def past_retention(now: datetime) -> Any:
    """The games whose history retention has run out: their field's ``retention_days`` (730 without a row)
    after they ended (or were made, if they never ended). For ``personal_data.purge``."""
    days = (select(FieldHistorySettings.retention_days).where(FieldHistorySettings.field_id == Game.field_id)
            .scalar_subquery())
    cutoff_at = (literal(now, DateTime(timezone=True))
                 - literal_column("interval '1 day'") * func.coalesce(days, DEFAULT_RETENTION_DAYS))
    return func.coalesce(Game.ended_at, Game.controller_created_at) < cutoff_at


async def public_field(db: AsyncSession, slug: str) -> Optional[Field]:
    return await db.scalar(select(Field).where(Field.slug == slug, Field.public_scoreboard.is_(True)))


# --- the person's game history (ADR-P4-8: access and export) --------------------------------------------


async def player_history(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """The games the person played, by the player ids their account holds at each field (``field_player_ids``):
    the games whose events name one of them (as ``player``, ``owner`` or ``holder``), with those events, and
    the games their registrations were checked in to. Erasure deletes the player ids, so nothing leads here
    any more (the events keep only the field's pseudonymous ids)."""
    from ..models import FieldPlayerId, GameRegistration, ScheduledGame  # noqa: PLC0415

    ids = list(await db.execute(select(FieldPlayerId.field_id, FieldPlayerId.player_id)
                                .where(FieldPlayerId.user_id == user_id)))
    games: dict[uuid.UUID, dict[str, Any]] = {}

    def entry(game: Game, field_name: str, player_id: Optional[str]) -> dict[str, Any]:
        out = games.setdefault(game.id, {"game": str(game.id), "field": field_name, "name": game.name,
                                         "mode_id": game.mode_id, "teams": list(game.teams), "state": game.state,
                                         "started_at": game.started_at.isoformat() if game.started_at else None,
                                         "ended_at": game.ended_at.isoformat() if game.ended_at else None,
                                         "player_ids": [], "registered": False, "events": [], "_game": game})
        if player_id is not None and player_id not in out["player_ids"]:
            out["player_ids"].append(player_id)
        return out

    for field_id, pid in ids:
        named = (GameEvent.data["player"].astext == pid) | (GameEvent.data["owner"].astext == pid) \
            | (GameEvent.data["holder"].astext == pid)
        rows = await db.execute(select(GameEvent, Game, Field.name).join(Game, Game.id == GameEvent.game)
                                .join(Field, Field.id == Game.field_id)
                                .where(Game.field_id == field_id, named).order_by(Game.controller_created_at,
                                                                                  GameEvent.id))
        for e, game, field_name in rows:
            entry(game, field_name, pid)["events"].append(
                {"t": e.game_time_ms, "type": e.event_type, "team": e.team, "squad": e.squad, "data": e.data,
                 "received_at": e.received_at.isoformat()})
    regs = await db.execute(select(GameRegistration.player_id, Game, Field.name)
                            .join(ScheduledGame, ScheduledGame.id == GameRegistration.scheduled_game)
                            .join(Game, Game.id == ScheduledGame.controller_game)
                            .join(Field, Field.id == Game.field_id)
                            .where(GameRegistration.user_id == user_id, GameRegistration.status == "checked_in"))
    for pid, game, field_name in regs:
        entry(game, field_name, pid)["registered"] = True
    out = []
    for item in games.values():
        game = item.pop("_game")
        item["totals"] = await totals_until(db, game, None)
        out.append(item)
    return sorted(out, key=lambda g: (g["started_at"] or "", g["game"]))
