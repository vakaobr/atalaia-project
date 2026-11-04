# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Game history shared across the fields of a hosted hub, by each field's opt-in (decisions HUBH-1 to HUBH-14; the
maintainer's decision of 2026-11-04: "fields can choose to share their games or not, should be an opt-in").

Each field's history is its own (S20-8, S21-2): a field's schema is readable by that field's database role only
(S2113-1). So, as with the chrono sharing (``hub_share.py``, SVX-2), what a field shares goes through the hub's tables
in ``public`` (``atalaia_hub_history_members``, ``atalaia_hub_games``; made by ``hosted init`` / ``hosted migrate``,
``hosted.HISTORY_DDL``), where a field can only touch its own rows (row-level security on the field's database role):

- **Opt in.** ``fields.history_sharing_enabled`` (migration 0031), off by default; the field's admin turns it on
  (``api/hub_history.py``). While it is on the field has a member row and publishes its ended games; ``sync_field``
  makes the hub's rows say what the field holds now (the switch, the retention purge) and ``after_sync`` adds or
  updates one game as the field's controller sends it (``sync.apply``).
- **Opt out.** Turning it off deletes the member row, and every game the field shared goes with it (ON DELETE CASCADE):
  off withdraws what was shared, not only what comes next (HUBH-3).
- **What is shared** (HUBH-7): per ended game, the mode, when it started and ended, each team's key and final score,
  the winner, and the field's name. Never a player id, an event, a member list, a squad, or the free text a field
  types (a game's or a team's display name), which could name people. The copy never outlives the field's own: a game
  leaves the hub when the field no longer holds it or its team results (``personal_data.RESULTS_RETENTION``, 365 days
  after the game ended), and the hub's function shows nothing older than that whatever is left.
- **Read** (HUBH-5, reciprocity): ``public.atalaia_hub_history_read`` and ``atalaia_hub_history_fields``, SECURITY
  DEFINER functions over hub tables only, answer a field only while it shares itself, and list only active fields that
  share. A field that has not opted in reads nothing and has nothing there to read.

None of it runs in a single-field server (``available()`` is False): there is no other field.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import Column, DateTime, MetaData, String, Table, delete, func, select, text
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import tenancy
from .models import Field, Game, GameResult
from .services import history

KEEP = timedelta(days=365)   # as personal_data.RESULTS_RETENTION and hosted.HISTORY_KEEP_DAYS
MAX_LIMIT = 200
SYNC_KINDS = frozenset({"games", "events", "scores"})  # the sync bodies that can end a game or change its totals

_hub = MetaData()
members = Table("atalaia_hub_history_members", _hub, Column("tenant", String, primary_key=True),
                Column("field_name", String), Column("since", DateTime(timezone=True)),
                Column("updated_at", DateTime(timezone=True)), schema="public")
games = Table("atalaia_hub_games", _hub, Column("tenant", String, primary_key=True),
              Column("game_ref", String, primary_key=True), Column("mode_id", String),
              Column("started_at", DateTime(timezone=True)), Column("ended_at", DateTime(timezone=True)),
              Column("teams", JSONB), Column("winner", String), Column("published_at", DateTime(timezone=True)),
              schema="public")

_READ = text("SELECT field_name, own, mode_id, started_at, ended_at, teams, winner "
             "FROM public.atalaia_hub_history_read(:before, :mode, :n)")
_FIELDS = text("SELECT field_name, own, since, games FROM public.atalaia_hub_history_fields()")


class HistoryShareProblem(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


def available() -> bool:
    """True in hosted mode, within a field's request or command: the only place the hub's tables apply."""
    return tenancy.current() is not None


def _tenant() -> str:
    schema = tenancy.current_schema()
    if schema is None:
        raise HistoryShareProblem(404, "not_hosted")
    return schema


def game_ref(field_id: uuid.UUID, game_id: int, game_seed: int) -> str:
    """The shared row's key: opaque (the game's id and radio seed stay the field's), the same for a game and the team
    results the purge writes of it, so a game that turns into its results keeps one row."""
    return hashlib.sha256(f"{field_id}:{game_id}:{game_seed}".encode()).hexdigest()[:32]


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _teams(team_keys: list[str], totals: dict[str, Any]) -> list[dict[str, Any]]:
    """Each team's key and final score: no display name (free text a field types), no squad, no player."""
    out = []
    for team in team_keys:
        score = totals.get(team, 0) if isinstance(totals, dict) else 0
        out.append({"team": str(team)[:32], "score": int(score) if isinstance(score, int) else 0})
    return out


async def _field(db: AsyncSession) -> Field:
    field = await db.scalar(select(Field).limit(1))  # a tenant has exactly one field (S21-2)
    if field is None:
        raise HistoryShareProblem(404, "field_not_found")
    return field


def _row(tenant: str, ref: str, mode_id: str, started: Optional[datetime], ended: datetime, teams: list[dict[str, Any]],
         winner: Optional[str]) -> dict[str, Any]:
    return {"tenant": tenant, "game_ref": ref, "mode_id": mode_id[:128], "started_at": started, "ended_at": ended,
            "teams": teams, "winner": winner if winner is None else str(winner)[:32]}


async def _game_row(db: AsyncSession, tenant: str, game: Game) -> dict[str, Any]:
    totals = await history.totals_until(db, game, None)
    ended = game.ended_at or game.updated_at or game.controller_created_at
    return _row(tenant, game_ref(game.field_id, game.game_id, game.game_seed), game.mode_id, game.started_at, ended,
                _teams(list(game.teams), totals), history.winner(totals))


async def _upsert(db: AsyncSession, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    stmt = insert(games).values(rows)
    ex = stmt.excluded
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["tenant", "game_ref"],
        set_={"mode_id": ex.mode_id, "started_at": ex.started_at, "ended_at": ex.ended_at, "teams": ex.teams,
              "winner": ex.winner, "published_at": func.now()}))


async def sync_field(db: AsyncSession, now: Optional[datetime] = None) -> int:
    """Makes the hub's rows say what this field shares now (the caller commits): nothing at all while the switch is
    off (the member row and, with it, every game go), else the member row and one row per ended game the field holds
    or whose team results it keeps, none older than ``KEEP``. Returns how many games are shared."""
    if not available():
        return 0
    tenant, field = _tenant(), await _field(db)
    if not field.history_sharing_enabled:
        await db.execute(delete(members).where(members.c.tenant == tenant))  # its games cascade
        return 0
    now = now or datetime.now(timezone.utc)
    since = field.history_shared_since or now
    stmt = insert(members).values(tenant=tenant, field_name=field.name, since=since, updated_at=func.now())
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["tenant"], set_={"field_name": stmt.excluded.field_name, "since": stmt.excluded.since,
                                         "updated_at": stmt.excluded.updated_at}))
    oldest = now - KEEP
    ended = func.coalesce(Game.ended_at, Game.updated_at)
    wanted: dict[str, dict[str, Any]] = {}
    for result in await db.scalars(select(GameResult).where(
            GameResult.field_id == field.id, GameResult.state == "ended", GameResult.ended_at > oldest)):
        ref = game_ref(result.field_id, result.game_id, result.game_seed)
        wanted[ref] = _row(tenant, ref, result.mode_id, result.started_at, result.ended_at,
                           _teams(list(result.teams), result.team_totals or {}), result.winner)
    for game in list(await db.scalars(select(Game).where(Game.field_id == field.id, Game.state == "ended",
                                                         ended > oldest))):
        row = await _game_row(db, tenant, game)
        wanted[row["game_ref"]] = row  # the game itself, while the field still has it, over its results
    have = set(await db.scalars(select(games.c.game_ref).where(games.c.tenant == tenant)))
    gone = list(have - set(wanted))
    if gone:
        await db.execute(delete(games).where(games.c.tenant == tenant, games.c.game_ref.in_(gone)))
    await _upsert(db, list(wanted.values()))
    return len(wanted)


async def after_sync(db: AsyncSession, field_id: uuid.UUID, body: dict[str, Any]) -> None:
    """After a controller's ``games``, ``events`` or ``scores`` body is stored (``sync.apply``, before its commit): when
    the field shares and the game has ended, its shared row is added or brought up to date (the final scores often come
    after the end). A no-op in a single-field server and for a field that does not share."""
    if not available():
        return
    sharing = await db.scalar(select(Field.history_sharing_enabled).where(Field.id == field_id))
    if not sharing:
        return
    game_key = body.get("game") if isinstance(body, dict) else None
    if not isinstance(game_key, dict):
        return
    game = await db.scalar(select(Game).where(Game.field_id == field_id, Game.game_id == game_key.get("game_id"),
                                              Game.game_seed == game_key.get("game_seed")))
    if game is None:
        return
    await db.refresh(game)  # the state the handler just wrote (an UPDATE that bypassed the session)
    if game.state != "ended":
        return
    tenant = _tenant()
    if await db.scalar(select(members.c.tenant).where(members.c.tenant == tenant)) is None:
        await sync_field(db)  # the member row went missing (a restore, say): put everything back
        return
    await _upsert(db, [await _game_row(db, tenant, game)])


# The staff's view ---------------------------------------------------------------------------------------------

async def state(db: AsyncSession) -> dict[str, Any]:
    """This field's switch, since when, and whether the hub has it as a member (the page's first look)."""
    tenant, field = _tenant(), await _field(db)
    member = await db.scalar(select(members.c.tenant).where(members.c.tenant == tenant)) is not None
    shared = int(await db.scalar(select(func.count()).select_from(games).where(games.c.tenant == tenant)) or 0)
    return {"hosted": True, "field": {"id": str(field.id), "name": field.name},
            "enabled": bool(field.history_sharing_enabled), "since": _iso(field.history_shared_since),
            "member": member, "shared_games": shared}


async def set_enabled(db: AsyncSession, enabled: bool) -> bool:
    """Turns the field's sharing on or off and makes the hub's rows follow (the caller commits); True if it changed."""
    _tenant()
    field = await _field(db)
    changed = bool(field.history_sharing_enabled) != enabled
    field.history_sharing_enabled = enabled
    if changed:
        field.history_shared_since = datetime.now(timezone.utc) if enabled else None
    await db.flush()
    await sync_field(db)
    return changed


async def shared_history(db: AsyncSession, before: Optional[datetime], mode: Optional[str],
                         limit: int) -> dict[str, Any]:
    """The hub's shared games, newest first, and the fields that share: only for a field that shares itself
    (403 ``history_sharing_off`` otherwise, HUBH-5)."""
    tenant, field = _tenant(), await _field(db)
    if not field.history_sharing_enabled \
            or await db.scalar(select(members.c.tenant).where(members.c.tenant == tenant)) is None:
        raise HistoryShareProblem(403, "history_sharing_off")
    limit = max(1, min(limit, MAX_LIMIT))
    rows = (await db.execute(_READ, {"before": before, "mode": mode or None, "n": limit})).all()
    fields = [{"field_name": r.field_name, "own": bool(r.own), "since": _iso(r.since), "games": int(r.games)}
              for r in (await db.execute(_FIELDS)).all()]
    out = [{"field_name": r.field_name, "own": bool(r.own), "mode_id": r.mode_id, "started_at": _iso(r.started_at),
            "ended_at": _iso(r.ended_at), "teams": r.teams if isinstance(r.teams, list) else [],
            "winner": r.winner} for r in rows]
    nxt = out[-1]["ended_at"] if len(out) == limit else None
    return {"fields": fields, "games": out, "next_before": nxt}
