# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Synced games and per-game roles (ADR-P4-1's ``games`` and ``user_game_roles``; plan phase 13).

    GET    /api/v1/fields/{field_id}/games                anyone with a role on the field: its games
    GET    /api/v1/games/{game}                           a role on the field or on the game: the game,
                                                          its totals, counters and nodes
    GET    /api/v1/games/{game}/events?after=&limit=      the field's admin, gm or marshal, or the game's
                                                          gm or marshal: the log, in arrival order
    GET    /api/v1/games/{game}/roles                     the field's admin or gm
    PUT    /api/v1/games/{game}/roles                     {username, role}: grant on this game
    DELETE /api/v1/games/{game}/roles/{user_id}/{role}    revoke

``{game}`` is the site server's id of the game (the ``game`` of
``POST /api/v1/sync/games``'s answer). Totals are derived, never stored
(P4R10). A game's ``params`` (a Bomb's arming codes, say) are shown only to
the field's admin and gm. Per-game roles follow the per-field rules
(``api/fields.py``): the field's admin grants any role, its gm the player,
squad leader, VIP and spectator roles; admin, gm and marshal need TOTP on the
account and count only in a TOTP session. The game history views are plan
phase 20.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from .. import sync
from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import (PRIVILEGED_ROLES, ROLE_BY_ID, ROLE_NAMES, Game, GameEvent, GameNode, User, UserGameRole)
from ..services.history import STAFF_FIELD_ROLES, STAFF_GAME_ROLES
from .auth import has_second_factor
from .fields import GM_GRANTS, NO_STORE, GrantIn

router = APIRouter(prefix="/api/v1", tags=["games"])


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if value is not None else None


def game_json(g: Game, staff: bool = False) -> dict[str, Any]:
    """A game's public face. ``game_seed`` is the game's identity towards its controller, not a
    secret, but only staff (who send remote commands naming it) have any use for it (LIVE2-2)."""
    seed = {"game_seed": g.game_seed} if staff else {}
    return {"id": str(g.id), "field_id": str(g.field_id), "game_id": g.game_id, **seed,
            "name": g.name, "mode_id": g.mode_id, "teams": g.teams, "team_info": g.team_info, "squads": g.squads,
            "duration_ms": g.duration_ms, "state": g.state, "created_at": _iso(g.controller_created_at),
            "started_at": _iso(g.started_at), "ended_at": _iso(g.ended_at), "synced_at": _iso(g.updated_at)}


async def game_roles(db: AsyncSession, principal: Principal, game_id: uuid.UUID) -> set[str]:
    """The caller's roles on one game that count in this session (privileged ones after TOTP)."""
    rows = await db.scalars(select(UserGameRole.role_id).where(UserGameRole.user_id == principal.user.id,
                                                               UserGameRole.game == game_id))
    roles = {ROLE_BY_ID[r] for r in rows}
    return roles if principal.mfa else roles - PRIVILEGED_ROLES


async def _game(db: AsyncSession, game_id: uuid.UUID) -> Game:
    game = await db.get(Game, game_id)
    if game is None:
        raise HTTPException(404, "game_not_found")
    return game


async def _may_see(db: AsyncSession, principal: Principal, game: Game, *wanted: str) -> set[str]:
    """403 unless the caller holds one of the roles (any role, when none are named) on the game's
    field or on the game itself; returns the field roles."""
    field_roles = principal.field_roles(game.field_id)
    if principal.is_server_admin:
        field_roles = field_roles | {"admin"}
    mine = field_roles | await game_roles(db, principal, game.id)
    if not mine or (wanted and not mine & set(wanted)):
        raise HTTPException(403, "role_required")
    return field_roles


@router.get("/fields/{field_id}/games")
async def list_games(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if not principal.is_server_admin and not principal.field_roles(field_id):
        raise HTTPException(403, "role_required")
    rows = await db.scalars(select(Game).where(Game.field_id == field_id)
                            .order_by(Game.controller_created_at.desc()).limit(500))
    roles = principal.field_roles(field_id) | ({"admin"} if principal.is_server_admin else set())
    staff = bool(roles & STAFF_FIELD_ROLES)
    return JSONResponse([game_json(g, staff) for g in rows], headers=NO_STORE)


@router.get("/games/{game_id}")
async def get_game(game_id: uuid.UUID, principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    game = await _game(db, game_id)
    field_roles = await _may_see(db, principal, game)
    nodes = await db.scalars(select(GameNode).where(GameNode.game == game.id).order_by(GameNode.node_id))
    staff = bool(field_roles & STAFF_FIELD_ROLES) or bool(await game_roles(db, principal, game.id) & STAFF_GAME_ROLES)
    body = {**game_json(game, staff), "totals": await sync.totals(db, game), "counters": await sync.counters(db, game),
            "nodes": [{"node_id": n.node_id, "name": n.name, "role": n.role, "info": n.info,
                       "last_seen_at": _iso(n.last_seen_at)} for n in nodes]}
    if field_roles & {"admin", "gm"}:
        body["params"] = game.params
    return JSONResponse(body, headers=NO_STORE)


@router.get("/games/{game_id}/events")
async def game_events(game_id: uuid.UUID, after: int = Query(0, ge=0), limit: int = Query(500, ge=1, le=1000),
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    game = await _game(db, game_id)
    await _may_see(db, principal, game, "admin", "gm", "marshal")
    rows = (await db.scalars(select(GameEvent).where(GameEvent.game == game.id, GameEvent.id > after)
                             .order_by(GameEvent.id).limit(limit))).all()
    return JSONResponse({"events": [{"id": e.id, "node": e.node_id, "seq": e.seq, "t": e.game_time_ms,
                                     "type": e.event_type, "team": e.team, "squad": e.squad, "prio": e.priority,
                                     "data": e.data, "epoch": e.epoch, "pkt_seq": e.pkt_seq,
                                     "received_at": _iso(e.received_at)} for e in rows],
                         "next": rows[-1].id if len(rows) == limit else None}, headers=NO_STORE)


def _may_manage(principal: Principal, game: Game, role: str) -> None:
    if role in GM_GRANTS:
        require_field_role(principal, game.field_id, "admin", "gm")
    else:
        require_field_role(principal, game.field_id, "admin")


@router.get("/games/{game_id}/roles")
async def list_game_roles(game_id: uuid.UUID, principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_session)) -> JSONResponse:
    game = await _game(db, game_id)
    require_field_role(principal, game.field_id, "admin", "gm")
    rows = await db.execute(
        select(UserGameRole, User.username).join(User, User.id == UserGameRole.user_id)
        .where(UserGameRole.game == game.id).order_by(User.username, UserGameRole.role_id))
    return JSONResponse([{"user_id": str(r.user_id), "username": username, "role": ROLE_BY_ID[r.role_id],
                          "granted_at": _iso(r.granted_at)} for r, username in rows], headers=NO_STORE)


@router.put("/games/{game_id}/roles")
async def grant_game_role(game_id: uuid.UUID, body: GrantIn, request: Request,
                          principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if body.role not in ROLE_NAMES:
        raise HTTPException(400, "role_invalid")
    game = await _game(db, game_id)
    _may_manage(principal, game, body.role)
    target = await db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if body.role in PRIVILEGED_ROLES and (target is None or not await has_second_factor(db, target)):
        raise HTTPException(409, "totp_required")  # one answer for "no such account" and "no second factor" (SRV-4)
    if target is None:
        raise HTTPException(404, "user_not_found")
    inserted = await db.scalar(
        insert(UserGameRole).values(user_id=target.id, game=game.id, role_id=ROLE_NAMES[body.role],
                                    granted_by=principal.user.id)
        .on_conflict_do_nothing(index_elements=["user_id", "game", "role_id"]).returning(UserGameRole.id))
    if inserted is not None:
        record(db, "game_role_grant", request, user_id=principal.user.id, resource="user", resource_id=target.id,
               details={"game": str(game.id), "role": body.role})
    await db.commit()
    return JSONResponse({"user_id": str(target.id), "username": target.username, "role": body.role,
                         "game": str(game.id)}, status_code=201 if inserted is not None else 200)


@router.delete("/games/{game_id}/roles/{user_id}/{role}", status_code=204)
async def revoke_game_role(game_id: uuid.UUID, user_id: uuid.UUID, role: str, request: Request,
                           principal: Principal = Depends(current_principal),
                           db: AsyncSession = Depends(get_session)) -> Response:
    if role not in ROLE_NAMES:
        raise HTTPException(400, "role_invalid")
    game = await _game(db, game_id)
    _may_manage(principal, game, role)
    gone = await db.scalar(delete(UserGameRole).where(
        UserGameRole.game == game.id, UserGameRole.user_id == user_id,
        UserGameRole.role_id == ROLE_NAMES[role]).returning(UserGameRole.id))
    if gone is None:
        raise HTTPException(404, "role_not_found")
    record(db, "game_role_revoke", request, user_id=principal.user.id, resource="user", resource_id=user_id,
           details={"game": str(game.id), "role": role})
    await db.commit()
    return Response(status_code=204)
