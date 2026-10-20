# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller sync, on the site server's side (ADR-P4-3 as amended, protocol/sync.md).

The routes (``api/sync.py``) and the WebSocket check a body with the
controller's own ``sync_format`` (shared, plain Python) and hand it here:

- ``authenticate``: the ``Authorization: Bearer`` API key, looked up by its
  SHA-256 and compared in constant time; a revoked key is refused (P4R13).
- ``apply``: one checked body in the caller's transaction. Games are upserted
  on ``(field, game_id, game_seed)`` with the state only moving forward;
  events are inserted with ``ON CONFLICT DO NOTHING`` on the controller's own
  key, so replays, duplicates and out-of-order batches change nothing;
  counters are merged with ``GREATEST`` per (game, source, team); nodes keep the
  entry with the latest ``last_seen``.
- The field's chrono registry (``marshals``, ``replicas``, ``chrono``; plan phase 14)
  is handed on to ``chrono_registry``, which verifies every reading.
- Registration and game day (plan phase 16): a game's ``meta.scheduled_game_id`` links
  it to the scheduled game it was made from (whose status then follows it);
  ``checkins`` (registrations' outcomes) and ``claims`` (the controller's verdicts on
  accounts' claims of player ids) go to ``services.registration``, which also builds
  the answers of the GET endpoints the controller pulls.
- ``totals``: a game's totals, derived as the controller derives them (P4R10):
  the counters' sum per team plus every ``score.delta`` amount, negative ones
  included. Totals are never stored, so they can never be merged wrongly.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from atalaia_controller import sync_format
from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import chrono_registry
from .models import Controller, FieldApiKey, Game, GameEvent, GameNode, GameNodeScore
from .services import registration

MAX_LIVE_KEYS = 2  # a field's live API keys: the old one and the new one during a rotation


class SyncProblem(Exception):
    """An answer other than 200: status, ``detail`` code and, for a 400, the format error."""

    def __init__(self, status: int, detail: str, error: Optional[str] = None, path: Optional[str] = None) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.error = error
        self.path = path

    def body(self) -> dict[str, Any]:
        out: dict[str, Any] = {"detail": self.detail}
        if self.error is not None:
            out["error"] = self.error
            out["path"] = self.path or ""
        return out


@dataclass
class Caller:
    field_id: uuid.UUID
    key_id: uuid.UUID
    controller: Optional[uuid.UUID] = None  # the site server's row of the sending controller, once seen


def new_key() -> str:
    """A new API key: 32 random bytes, base64url without padding (43 characters)."""
    return secrets.token_urlsafe(32)


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def fingerprint(key_sha256: str) -> str:
    """What both sides show of a key (protocol/sync.md): the first 8 hex digits of its SHA-256."""
    return key_sha256[:8]


async def authenticate(db: AsyncSession, presented: Optional[str]) -> Optional[Caller]:
    """The field whose live key this is, or None. Marks the key used."""
    if not presented or len(presented) > 256:
        return None
    wanted = key_hash(presented)
    row = await db.scalar(select(FieldApiKey).where(FieldApiKey.key_sha256 == wanted))
    if row is None or row.revoked_at is not None or not hmac.compare_digest(row.key_sha256, wanted):
        return None
    await db.execute(update(FieldApiKey).where(FieldApiKey.id == row.id).values(last_used_at=func.now()))
    return Caller(field_id=row.field_id, key_id=row.id)


def parse(kind: str, raw: bytes) -> dict[str, Any]:
    try:
        return sync_format.parse(kind, raw)
    except sync_format.SyncFormatError as exc:
        if exc.code == "too_large" and exc.path == "":
            raise SyncProblem(413, "body_too_large") from None
        raise SyncProblem(400, "invalid_body", exc.code, exc.path) from None


def check(kind: str, body: Any) -> dict[str, Any]:
    try:
        return sync_format.CHECKS[kind](body)
    except sync_format.SyncFormatError as exc:
        raise SyncProblem(400, "invalid_body", exc.code, exc.path) from None


def _time(value: Optional[float]) -> Optional[datetime]:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value is not None else None


async def seen(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> None:
    """Marks the body's controller seen (version, the key it used, now) and sets ``caller.controller``."""
    await _seen(db, caller, body)


async def _seen(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> None:
    ctrl = body["controller"]
    stmt = insert(Controller).values(field_id=caller.field_id, controller_id=uuid.UUID(ctrl["id"]),
                                     version=ctrl["version"], api_key_id=caller.key_id)
    caller.controller = await db.scalar(stmt.on_conflict_do_update(
        index_elements=["field_id", "controller_id"],
        set_={"version": stmt.excluded.version, "api_key_id": stmt.excluded.api_key_id, "last_seen_at": func.now()},
    ).returning(Controller.id))


async def find_game(db: AsyncSession, field_id: uuid.UUID, body: dict[str, Any]) -> Game:
    game_id, seed = sync_format.game_key(body)
    game = await db.scalar(select(Game).where(Game.field_id == field_id, Game.game_id == game_id,
                                              Game.game_seed == seed))
    if game is None:
        raise SyncProblem(404, "game_not_found")
    return game


# The state only moves forward: ready < running = paused < ended (protocol/sync.md).
_STATE_MERGE = text(
    "CASE WHEN games.state = 'ended' OR excluded.state = 'ended' THEN 'ended' "
    "WHEN excluded.state = 'ready' THEN games.state ELSE excluded.state END")


async def _games(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    game_id, seed = sync_format.game_key(body)
    meta = body["meta"]
    state, ended_at = meta["state"], meta["ended_at"]
    if meta["joined"] and state == "ended":
        # A standby controller's "ended" may only mean it left the game: the game ends with the
        # game.end event of whichever controller ended it (decision S13-5).
        state, ended_at = ("running" if meta["started_at"] is not None else "ready"), None
    values = {"name": meta["name"], "mode_id": meta["mode_id"], "teams": meta["teams"],
              "team_info": meta["team_info"], "params": meta["params"], "squads": meta["squads"],
              "duration_ms": meta["duration_ms"], "state": state,
              "controller_created_at": _time(meta["created_at"]), "started_at": _time(meta["started_at"]),
              "ended_at": _time(ended_at)}
    stmt = insert(Game).values(field_id=caller.field_id, game_id=game_id, game_seed=seed, **values)
    ex = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=["field_id", "game_id", "game_seed"],
        set_={"name": ex.name, "mode_id": ex.mode_id, "teams": ex.teams, "team_info": ex.team_info,
              "params": ex.params, "squads": ex.squads, "duration_ms": ex.duration_ms, "state": _STATE_MERGE,
              "controller_created_at": func.least(Game.controller_created_at, ex.controller_created_at),
              "started_at": func.least(Game.started_at, ex.started_at),
              "ended_at": func.greatest(Game.ended_at, ex.ended_at), "updated_at": func.now()},
    ).returning(Game.id, Game.state, text("(xmax = 0) AS created"))
    row = (await db.execute(stmt)).one()
    answer = {"game": str(row[0]), "created": bool(row[2]), "state": row[1]}
    if meta["scheduled_game_id"] is not None:
        answer["scheduled"] = await registration.link_game(db, caller.field_id, meta["scheduled_game_id"], row[0],
                                                          row[1])
    return answer


async def _events(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    game = await find_game(db, caller.field_id, body)
    rows = [{"game": game.id, "node_id": e["node"], "seq": e["seq"], "game_time_ms": e["t"], "event_type": e["type"],
             "team": e["team"], "squad": e["squad"], "priority": e["prio"], "data": e["data"], "epoch": e["epoch"],
             "pkt_seq": e["pkt_seq"]} for e in body["events"]]
    # Two copies of one event in the same batch (a standby's log merged into this one): one row.
    unique = {(r["node_id"], r["seq"], r["game_time_ms"], r["event_type"]): r for r in rows}
    stmt = insert(GameEvent).values(list(unique.values())).on_conflict_do_nothing(
        index_elements=["game", "node_id", "seq", "game_time_ms", "event_type"]).returning(GameEvent.id)
    inserted = len((await db.execute(stmt)).all())
    if any(e["type"] == "game.end" for e in body["events"]) and game.state != "ended":
        await db.execute(update(Game).where(Game.id == game.id).values(state="ended", updated_at=func.now()))
    return {"acked_id": body["events"][-1]["id"], "inserted": inserted, "duplicates": len(rows) - inserted}


def _unknown_teams(game: Game, counters: dict[str, dict[str, int]]) -> None:
    for source, teams in counters.items():
        for team in teams:
            if team not in game.teams:
                raise SyncProblem(400, "invalid_body", "unknown_team", f"counters.{source}.{team}")


async def _scores(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    game = await find_game(db, caller.field_id, body)
    _unknown_teams(game, body["counters"])
    rows = [{"game": game.id, "source": source, "team": team, "value": value}
            for source, teams in body["counters"].items() for team, value in teams.items()]
    updated = 0
    if rows:
        stmt = insert(GameNodeScore).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=["game", "source", "team"],
            set_={"value": func.greatest(GameNodeScore.value, stmt.excluded.value), "updated_at": func.now()},
            where=stmt.excluded.value > GameNodeScore.value).returning(GameNodeScore.source)
        updated = len((await db.execute(stmt)).all())
    return {"totals": await totals(db, game), "updated": updated}


async def _nodes(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    game = await find_game(db, caller.field_id, body)
    rows = [{"game": game.id, "node_id": n["node_id"], "name": n["name"], "role": n["role"], "info": n["info"],
             "last_seen_at": _time(n["last_seen"])} for n in body["nodes"]]
    if rows:
        stmt = insert(GameNode).values(rows)
        ex = stmt.excluded
        await db.execute(stmt.on_conflict_do_update(
            index_elements=["game", "node_id"],
            set_={"name": ex.name, "role": ex.role, "info": ex.info, "last_seen_at": ex.last_seen_at},
            where=ex.last_seen_at >= GameNode.last_seen_at))
    return {"nodes": len(rows)}


async def _marshals(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    return await chrono_registry.apply_marshals(db, caller.field_id, body)


async def _replicas(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    return await chrono_registry.apply_replicas(db, caller.field_id, body)


async def _chrono(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    return await chrono_registry.apply_chrono(db, caller.field_id, caller.controller, body)


async def _checkins(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    game = await find_game(db, caller.field_id, body)
    return await registration.apply_checkins(db, caller.field_id, game, body, datetime.now(timezone.utc))


async def _claims(db: AsyncSession, caller: Caller, body: dict[str, Any]) -> dict[str, Any]:
    return await registration.apply_claims(db, caller.field_id, body, datetime.now(timezone.utc))


HANDLERS = {"games": _games, "events": _events, "scores": _scores, "nodes": _nodes,
            "marshals": _marshals, "replicas": _replicas, "chrono": _chrono, "checkins": _checkins,
            "claims": _claims}


async def apply(db: AsyncSession, caller: Caller, kind: str, body: dict[str, Any]) -> dict[str, Any]:
    """Stores one checked body and commits; the answer of protocol/sync.md."""
    await _seen(db, caller, body)
    answer = await HANDLERS[kind](db, caller, body)
    await db.commit()
    return answer


async def counters(db: AsyncSession, game: Game) -> dict[str, dict[str, int]]:
    rows = await db.execute(select(GameNodeScore.source, GameNodeScore.team, GameNodeScore.value)
                            .where(GameNodeScore.game == game.id))
    out: dict[str, dict[str, int]] = {}
    for source, team, value in rows:
        out.setdefault(source, {})[team] = int(value)
    return out


async def totals(db: AsyncSession, game: Game) -> dict[str, int]:
    """The game's totals (P4R10): the counters' sum per team plus every score.delta amount."""
    deltas = await db.execute(select(GameEvent.team, GameEvent.data).where(
        GameEvent.game == game.id, GameEvent.event_type == "score.delta"))
    adjustments = []
    for team, data in deltas:
        team = data.get("team", team) if isinstance(data, dict) else team
        amount = data.get("amount") if isinstance(data, dict) else None
        if isinstance(team, str) and isinstance(amount, int) and not isinstance(amount, bool):
            adjustments.append((team, amount))
    return sync_format.totals(list(game.teams), await counters(db, game), adjustments)


async def live_keys(db: AsyncSession, field_id: uuid.UUID) -> int:
    return int(await db.scalar(select(func.count()).select_from(FieldApiKey).where(
        FieldApiKey.field_id == field_id, FieldApiKey.revoked_at.is_(None))) or 0)
