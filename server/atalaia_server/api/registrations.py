# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registrations for scheduled games and the player's ids at fields (ADR-P4-11; plan phase 16, decisions S16-*).

    POST   /api/v1/fields/{field_id}/scheduled-games/{id}/registrations   any account: register; the
                                                                        ticket is in this answer only
    GET    /api/v1/fields/{field_id}/scheduled-games/{id}/registrations   admin or gm: the list with names
    PATCH  /api/v1/fields/{field_id}/scheduled-games/{id}/registrations/{reg}  admin or gm: change it
    DELETE /api/v1/fields/{field_id}/scheduled-games/{id}/registrations/{reg}  admin or gm: cancel it
    GET    /api/v1/me/registrations                     the account's registrations
    PATCH  /api/v1/me/registrations/{reg}               change them while the window is open
    DELETE /api/v1/me/registrations/{reg}               cancel while the window is open
    POST   /api/v1/me/registrations/{reg}/ticket        a new ticket (shown once), until the game starts
    GET    /api/v1/fields-by-slug/{slug}                any account: the field and its games that can be
                                                        registered for, for the app (plan phase 17, S17-9)
    GET    /api/v1/me/player-ids                        the account's player ids and its claims
    POST   /api/v1/me/player-ids                        {field_id, player_id, player_secret}: claim the
                                                        id a phone already has at that field; the field's
                                                        controller confirms it (202, pending)

Registering needs only an account (F14); the field's staff roles count only in a TOTP session. The
rules are in ``services/registration.py``. Changes are in the audit log without names or numbers.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import Field, FieldPlayerId, GameRegistration, PlayerIdClaim, ScheduledGame
from ..services import registration as svc
from ..services import scheduling
from .fields import NO_STORE, SLUG

router = APIRouter(prefix="/api/v1", tags=["registrations"])


class ReplicaIn(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    replica_id: Optional[str] = PydanticField(default=None, max_length=36)
    type: Optional[str] = PydanticField(default=None, max_length=16)
    cls: Optional[str] = PydanticField(default=None, alias="class", max_length=32)
    make_model: Optional[str] = PydanticField(default=None, max_length=256)


class RegistrationIn(BaseModel):
    """Only the members sent count (a PATCH changes only those)."""

    model_config = ConfigDict(extra="forbid")
    display_name: Optional[str] = PydanticField(default=None, max_length=256)
    team_preference: Optional[str] = PydanticField(default=None, max_length=64)
    federation_number: Optional[str] = PydanticField(default=None, max_length=256)
    replicas: Optional[list[ReplicaIn]] = PydanticField(default=None, max_length=svc.MAX_REPLICAS + 1)


class ClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field_id: uuid.UUID
    player_id: str = PydanticField(max_length=64)
    player_secret: str = PydanticField(max_length=64)


def _body(body: RegistrationIn) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in body.model_fields_set:
        value = getattr(body, name)
        if name == "replicas" and value is not None:
            value = [r.model_dump(by_alias=True, exclude_unset=True) for r in value]
        out[name] = value
    return out


def _error(exc: svc.RegistrationError) -> HTTPException:
    return HTTPException(exc.status, exc.code)


async def _field(db: AsyncSession, field_id: uuid.UUID) -> Field:
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    return field


async def _game(db: AsyncSession, field_id: uuid.UUID, game_id: uuid.UUID) -> ScheduledGame:
    try:
        return await svc.lock_game(db, field_id, game_id)
    except svc.RegistrationError as exc:
        raise _error(exc) from None


async def _answer(db: AsyncSession, reg: GameRegistration, status_code: int = 200,
                  extra: Optional[dict[str, Any]] = None) -> JSONResponse:
    await db.refresh(reg)
    game = await db.get(ScheduledGame, reg.scheduled_game)
    field = await db.get(Field, reg.field_id)
    reps = await svc.replicas_of(db, [reg.id])
    body = {**svc.registration_json(reg, reps[reg.id], game, field), **(extra or {})}
    return JSONResponse(body, status_code=status_code, headers=NO_STORE)


@router.post("/fields/{field_id}/scheduled-games/{game_id}/registrations", status_code=201)
async def register(field_id: uuid.UUID, game_id: uuid.UUID, body: RegistrationIn, request: Request,
                   principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """Registers the account; the answer holds the ticket (``ticket``, ``ticket_text``), shown this once."""
    field = await _field(db, field_id)
    game = await _game(db, field_id, game_id)
    try:
        reg, secret = await svc.register(db, field, game, principal.user.id, principal.user.username, _body(body),
                                         svc.now_utc())
    except svc.RegistrationError as exc:
        await db.rollback()
        raise _error(exc) from None
    record(db, "registration_create", request, user_id=principal.user.id, resource="registration",
           resource_id=reg.id, details={"field_id": str(field_id), "scheduled_game": str(game_id)})
    await db.commit()
    return await _answer(db, reg, 201, svc.ticket_answer(reg, secret))


@router.get("/fields/{field_id}/scheduled-games/{game_id}/registrations")
async def list_registrations(field_id: uuid.UUID, game_id: uuid.UUID, principal: Principal = Depends(current_principal),
                             db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    game = await db.scalar(select(ScheduledGame).where(ScheduledGame.id == game_id, ScheduledGame.field_id == field_id))
    if game is None:
        raise HTTPException(404, "scheduled_game_not_found")
    regs = list(await db.scalars(select(GameRegistration).where(GameRegistration.scheduled_game == game_id)
                                 .order_by(GameRegistration.created_at, GameRegistration.id)))
    reps = await svc.replicas_of(db, [r.id for r in regs])
    counts: dict[str, int] = {}
    for r in regs:
        counts[r.status] = counts.get(r.status, 0) + 1
    return JSONResponse({"scheduled_game_id": str(game_id), "max_players": game.max_players,
                         "walkins": game.walkins, "counts": counts,
                         "registrations": [svc.registration_json(r, reps[r.id]) for r in regs]}, headers=NO_STORE)


async def _staff_registration(db: AsyncSession, field_id: uuid.UUID, game_id: uuid.UUID,
                              reg_id: uuid.UUID) -> tuple[Field, ScheduledGame, GameRegistration]:
    field = await _field(db, field_id)
    game = await _game(db, field_id, game_id)
    reg = await db.scalar(select(GameRegistration).where(GameRegistration.id == reg_id,
                                                         GameRegistration.scheduled_game == game_id).with_for_update())
    if reg is None:
        raise HTTPException(404, "registration_not_found")
    return field, game, reg


@router.patch("/fields/{field_id}/scheduled-games/{game_id}/registrations/{reg_id}")
async def staff_change(field_id: uuid.UUID, game_id: uuid.UUID, reg_id: uuid.UUID, body: RegistrationIn,
                       request: Request, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    field, game, reg = await _staff_registration(db, field_id, game_id, reg_id)
    try:
        changed = await svc.change(db, field, game, reg, _body(body), svc.now_utc(), staff=True)
    except svc.RegistrationError as exc:
        await db.rollback()
        raise _error(exc) from None
    if changed:
        record(db, "registration_update", request, user_id=principal.user.id, resource="registration",
               resource_id=reg.id, details={"field_id": str(field_id), "changed": changed, "by": "staff"})
    await db.commit()
    return await _answer(db, reg)


@router.delete("/fields/{field_id}/scheduled-games/{game_id}/registrations/{reg_id}", status_code=204)
async def staff_cancel(field_id: uuid.UUID, game_id: uuid.UUID, reg_id: uuid.UUID, request: Request,
                       principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> Response:
    require_field_role(principal, field_id, "admin", "gm")
    _, game, reg = await _staff_registration(db, field_id, game_id, reg_id)
    try:
        svc.cancel(game, reg, svc.now_utc(), staff=True)
    except svc.RegistrationError as exc:
        raise _error(exc) from None
    record(db, "registration_cancel", request, user_id=principal.user.id, resource="registration",
           resource_id=reg.id, details={"field_id": str(field_id), "by": "staff"})
    await db.commit()
    return Response(status_code=204)


# --- the field's games for the app (decisions S16-13, S17-9) -------------------------------

@router.get("/fields-by-slug/{slug}")
async def field_games(slug: str, principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A field by its slug (as the public register page's link names it) with its published games that have
    not ended, and what registering needs: the teams, the federation number, the replicas' classes. Any
    logged-in account; drafts never; no person (only the places left)."""
    if not SLUG.fullmatch(slug):
        raise HTTPException(404, "field_not_found")
    field = await db.scalar(select(Field).where(Field.slug == slug))
    if field is None:
        raise HTTPException(404, "field_not_found")
    now = svc.now_utc()
    games = list(await db.scalars(select(ScheduledGame).where(
        ScheduledGame.field_id == field.id, ScheduledGame.status != "draft", ScheduledGame.ends_at > now)
        .order_by(ScheduledGame.starts_at, ScheduledGame.id).limit(200)))
    n = await svc.counts(db, [g.id for g in games])
    out = []
    for g in games:
        registered = n.get(g.id, 0)
        out.append({
            "id": str(g.id), "title": g.title, "description": g.description,
            "starts_at": g.starts_at.isoformat(), "ends_at": g.ends_at.isoformat(),
            "location": scheduling.location(g, field), "mode_id": g.mode_id, "teams": list(g.teams or ()),
            "max_players": g.max_players, "places_left": scheduling.places_left(g, registered),
            "registration_opens_at": g.registration_opens_at.isoformat() if g.registration_opens_at else None,
            "registration_closes_at": g.registration_closes_at.isoformat() if g.registration_closes_at else None,
            "registration_state": scheduling.registration_state(g, now),
            "registration_open": scheduling.can_register(g, now, registered), "federation": g.federation,
            "predeclare_replicas": g.predeclare_replicas, "status": g.status, "cancelled_reason": g.cancelled_reason})
    return JSONResponse({"field": {"id": str(field.id), "slug": field.slug, "name": field.name,
                                   "timezone": field.timezone, "federation_label": field.federation_label,
                                   "limit_template": field.limit_template,
                                   "classes": list(svc.classes(field.limit_template)),
                                   "max_replicas": field.max_replicas},
                         "games": out}, headers=NO_STORE)


# --- the account's own ----------------------------------------------------------------------

@router.get("/me/registrations")
async def my_registrations(principal: Principal = Depends(current_principal),
                           db: AsyncSession = Depends(get_session)) -> JSONResponse:
    rows = await db.execute(select(GameRegistration, ScheduledGame, Field)
                            .join(ScheduledGame, ScheduledGame.id == GameRegistration.scheduled_game)
                            .join(Field, Field.id == GameRegistration.field_id)
                            .where(GameRegistration.user_id == principal.user.id)
                            .order_by(ScheduledGame.starts_at, GameRegistration.id))
    rows = list(rows)
    reps = await svc.replicas_of(db, [r.id for r, _, _ in rows])
    return JSONResponse([svc.registration_json(r, reps[r.id], g, f) for r, g, f in rows], headers=NO_STORE)


async def _mine(db: AsyncSession, principal: Principal, reg_id: uuid.UUID) -> tuple[Field, ScheduledGame,
                                                                                    GameRegistration]:
    reg = await db.scalar(select(GameRegistration).where(GameRegistration.id == reg_id,
                                                         GameRegistration.user_id == principal.user.id))
    if reg is None:
        raise HTTPException(404, "registration_not_found")
    return await _staff_registration(db, reg.field_id, reg.scheduled_game, reg.id)


@router.patch("/me/registrations/{reg_id}")
async def change_mine(reg_id: uuid.UUID, body: RegistrationIn, request: Request,
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    field, game, reg = await _mine(db, principal, reg_id)
    try:
        changed = await svc.change(db, field, game, reg, _body(body), svc.now_utc(), staff=False)
    except svc.RegistrationError as exc:
        await db.rollback()
        raise _error(exc) from None
    if changed:
        record(db, "registration_update", request, user_id=principal.user.id, resource="registration",
               resource_id=reg.id, details={"field_id": str(field.id), "changed": changed})
    await db.commit()
    return await _answer(db, reg)


@router.delete("/me/registrations/{reg_id}", status_code=204)
async def cancel_mine(reg_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> Response:
    field, game, reg = await _mine(db, principal, reg_id)
    try:
        svc.cancel(game, reg, svc.now_utc(), staff=False)
    except svc.RegistrationError as exc:
        raise _error(exc) from None
    record(db, "registration_cancel", request, user_id=principal.user.id, resource="registration",
           resource_id=reg.id, details={"field_id": str(field.id)})
    await db.commit()
    return Response(status_code=204)


@router.post("/me/registrations/{reg_id}/ticket")
async def new_ticket(reg_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    field, game, reg = await _mine(db, principal, reg_id)
    try:
        secret = svc.renew_ticket(game, reg, svc.now_utc())
    except svc.RegistrationError as exc:
        raise _error(exc) from None
    record(db, "registration_ticket", request, user_id=principal.user.id, resource="registration",
           resource_id=reg.id, details={"field_id": str(field.id)})
    await db.commit()
    return await _answer(db, reg, 200, svc.ticket_answer(reg, secret))


@router.get("/me/player-ids")
async def my_player_ids(principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    links = await db.execute(select(FieldPlayerId.field_id, FieldPlayerId.player_id, FieldPlayerId.created_at)
                             .where(FieldPlayerId.user_id == principal.user.id).order_by(FieldPlayerId.created_at))
    claims = await db.scalars(select(PlayerIdClaim).where(PlayerIdClaim.user_id == principal.user.id)
                              .order_by(PlayerIdClaim.created_at))
    return JSONResponse({"player_ids": [{"field_id": str(f), "player_id": p, "linked_at": t.isoformat()}
                                        for f, p, t in links],
                         "claims": [svc.claim_json(c) for c in claims]}, headers=NO_STORE)


@router.post("/me/player-ids", status_code=202)
async def claim_player_id(body: ClaimIn, request: Request, principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """The phone's field identity (its id and secret, sent once): pending until the field's controller,
    which holds the secret's hash, confirms it at its next sync. The secret itself is not kept."""
    await _field(db, body.field_id)
    try:
        row = await svc.claim(db, principal.user.id, body.field_id, body.player_id, body.player_secret)
    except svc.RegistrationError as exc:
        await db.rollback()
        raise _error(exc) from None
    record(db, "player_id_claim", request, user_id=principal.user.id, resource="field", resource_id=body.field_id)
    await db.commit()
    await db.refresh(row)
    return JSONResponse(svc.claim_json(row), status_code=202, headers=NO_STORE)
