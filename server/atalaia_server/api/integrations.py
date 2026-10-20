# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Platform adapters per field (ADR-P4-12; plan phase 17, decisions F21, F22, S17-*).

    GET    /api/v1/integrations/adapters                       any account: the adapters this server offers
    GET    /api/v1/fields/{field_id}/integrations              admin: the field's links
    PUT    /api/v1/fields/{field_id}/integrations/{adapter}    admin: {enabled?, config?}; off by default
    DELETE /api/v1/fields/{field_id}/integrations/{adapter}    admin: the link and its configuration
    GET    /api/v1/fields/{field_id}/scheduled-games/{id}/integrations             admin or gm: the game's
                                                               references on the platforms
    POST   /api/v1/fields/{field_id}/scheduled-games/{id}/integrations/{adapter}/push   admin: publish the
                                                               game there, update it, or cancel it
    POST   /api/v1/fields/{field_id}/scheduled-games/{id}/integrations/{adapter}/registrations?dry_run=
                                                               admin or gm: the platform's registrations,
                                                               through the import's rules

Rules: an adapter only uses a platform's documented API or a written agreement (``integrations/base.py``);
a link is off until the field's admin turns it on; its configuration is stored encrypted and never shown
again (only which names are set); every call goes out from the site server only, and every call is in the
audit log (``integration_call``: the adapter, the operation, ``ok`` or the error's code); a failing or
slow platform (``CALL_TIMEOUT_S``) fails that call only, never scheduling, publication or check-in, which
call no adapter at all. The roles count only in a TOTP session.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import import_format as fmt
from .. import integrations
from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..integrations.base import AdapterError, ImportedRegistration, PlatformAdapter, PublishedGame
from ..models import ExternalGameLink, Field, PlatformLink, ScheduledGame
from ..services import registration as reg_svc
from ..services import registration_import as import_svc
from ..services import scheduling
from ..web.field_pages import base_url
from .fields import NO_STORE

router = APIRouter(prefix="/api/v1", tags=["integrations"])
log = logging.getLogger("atalaia.server.integrations")
T = TypeVar("T")


class LinkIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Optional[bool] = None
    config: Optional[dict[str, Any]] = None


def _registry(request: Request) -> integrations.Registry:
    return request.app.state.adapters


def _box(request: Request) -> integrations.ConfigBox:
    return request.app.state.config_box


def _adapter(request: Request, adapter_id: str) -> PlatformAdapter:
    adapter = _registry(request).get(adapter_id)
    if adapter is None:
        raise HTTPException(404, "adapter_unknown")
    return adapter


def adapter_json(a: PlatformAdapter) -> dict[str, Any]:
    return {"id": a.id, "name": a.name, "capabilities": sorted(a.capabilities), "basis": a.basis,
            "config_keys": list(a.config_keys), "secret_keys": sorted(a.secret_keys)}


def _link_json(request: Request, link: PlatformLink) -> dict[str, Any]:
    adapter = _registry(request).get(link.adapter_id)
    config = _box(request).open(link.field_id, link.adapter_id, link.config_enc) if link.config_enc else None
    shown: dict[str, Any] = {}
    if config is not None and adapter is not None:  # the names set, and the values that are not secret
        shown = {k: ("set" if k in adapter.secret_keys else config.get(k)) for k in adapter.config_keys if k in config}
    return {"adapter_id": link.adapter_id, "name": adapter.name if adapter else None, "available": adapter is not None,
            "enabled": link.enabled, "configured": config is not None,
            "config_unreadable": link.config_enc is not None and config is None, "config": shown,
            "created_at": link.created_at.isoformat(), "updated_at": link.updated_at.isoformat()}


async def _field(db: AsyncSession, field_id: uuid.UUID) -> Field:
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    return field


async def _link(db: AsyncSession, field_id: uuid.UUID, adapter_id: str, lock: bool = False) -> Optional[PlatformLink]:
    query = select(PlatformLink).where(PlatformLink.field_id == field_id, PlatformLink.adapter_id == adapter_id)
    return await db.scalar(query.with_for_update() if lock else query)


@router.get("/integrations/adapters")
async def list_adapters(request: Request, principal: Principal = Depends(current_principal)) -> JSONResponse:
    return JSONResponse([adapter_json(a) for a in _registry(request).all()], headers=NO_STORE)


@router.get("/fields/{field_id}/integrations")
async def list_links(field_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    await _field(db, field_id)
    rows = await db.scalars(select(PlatformLink).where(PlatformLink.field_id == field_id)
                            .order_by(PlatformLink.adapter_id))
    return JSONResponse([_link_json(request, r) for r in rows], headers=NO_STORE)


@router.put("/fields/{field_id}/integrations/{adapter_id}")
async def put_link(field_id: uuid.UUID, adapter_id: str, body: LinkIn, request: Request,
                   principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin")
    await _field(db, field_id)
    adapter = _adapter(request, adapter_id)
    link = await _link(db, field_id, adapter_id, lock=True)
    if link is None:
        link = PlatformLink(field_id=field_id, adapter_id=adapter_id, enabled=False)
        db.add(link)
    details: dict[str, Any] = {"adapter": adapter_id}
    if body.config is not None:
        try:
            config = adapter.check_config(body.config)
        except AdapterError as exc:
            raise HTTPException(400, exc.code) from None
        link.config_enc = _box(request).seal(field_id, adapter_id, config)
        details["config"] = "set"  # never the values
    if body.enabled is not None:
        if body.enabled and _box(request).open(field_id, adapter_id, link.config_enc) is None and adapter.config_keys:
            raise HTTPException(409, "config_missing")
        link.enabled = body.enabled
        details["enabled"] = body.enabled
    record(db, "integration_update", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details=details)
    await db.commit()
    await db.refresh(link)
    return JSONResponse(_link_json(request, link), headers=NO_STORE)


@router.delete("/fields/{field_id}/integrations/{adapter_id}", status_code=204)
async def delete_link(field_id: uuid.UUID, adapter_id: str, request: Request,
                      principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> Response:
    require_field_role(principal, field_id, "admin")
    link = await _link(db, field_id, adapter_id, lock=True)
    if link is None:
        raise HTTPException(404, "integration_not_found")
    await db.delete(link)
    record(db, "integration_delete", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"adapter": adapter_id})
    await db.commit()
    return Response(status_code=204)


# --- calls ----------------------------------------------------------------------------------

def published_game(request: Request, game: ScheduledGame, field: Field, now: datetime, registered: int) -> PublishedGame:
    """What the adapter is given: the JSON feed's view of the game, no person in it."""
    return PublishedGame(
        id=str(game.id), field_slug=field.slug, field_name=field.name, title=game.title,
        description=game.description, starts_at=game.starts_at, ends_at=game.ends_at, status=game.status,
        location=scheduling.location(game, field), mode_id=game.mode_id, teams=tuple(game.teams or ()),
        max_players=game.max_players, places_left=scheduling.places_left(game, registered),
        registration_opens_at=game.registration_opens_at, registration_closes_at=game.registration_closes_at,
        registration_open=scheduling.can_register(game, now, registered), federation=game.federation,
        url=f"{base_url(request)}/f/{field.slug}/games/{game.id}", cancelled_reason=game.cancelled_reason)


async def call(db: AsyncSession, request: Request, principal: Principal, field_id: uuid.UUID, game_id: uuid.UUID,
               adapter_id: str, operation: str, fn: Callable[[], Awaitable[T]]) -> tuple[Optional[T], Optional[str]]:
    """Runs one call to the platform with a time limit; returns (result, None) or (None, error code). The
    call is in the audit log either way; an exception of the adapter's own is logged by its type only."""
    try:
        result = await asyncio.wait_for(fn(), timeout=integrations.CALL_TIMEOUT_S)
        error = None
    except AdapterError as exc:
        result, error = None, exc.code
    except asyncio.TimeoutError:
        result, error = None, "timeout"
    except Exception as exc:  # noqa: BLE001  (a broken adapter fails its call, not the server)
        log.warning("adapter %s %s failed: %s", adapter_id, operation, type(exc).__name__)
        result, error = None, "adapter_failed"
    record(db, "integration_call", request, user_id=principal.user.id, resource="scheduled_game",
           resource_id=game_id, details={"field_id": str(field_id), "adapter": adapter_id, "operation": operation,
                                         "result": error or "ok"})
    return result, error


async def _ready(db: AsyncSession, request: Request, field_id: uuid.UUID, game_id: uuid.UUID, adapter_id: str,
                 capability: str) -> tuple[Field, ScheduledGame, PlatformAdapter, dict[str, str]]:
    field = await _field(db, field_id)
    adapter = _adapter(request, adapter_id)
    link = await _link(db, field_id, adapter_id)
    if link is None or not link.enabled:
        raise HTTPException(409, "integration_disabled")
    config = _box(request).open(field_id, adapter_id, link.config_enc)
    if config is None and adapter.config_keys:
        raise HTTPException(409, "config_unreadable")
    if capability not in adapter.capabilities:
        raise HTTPException(409, "capability_missing")
    game = await db.scalar(select(ScheduledGame).where(ScheduledGame.id == game_id, ScheduledGame.field_id == field_id)
                           .with_for_update())
    if game is None:
        raise HTTPException(404, "scheduled_game_not_found")
    return field, game, adapter, config or {}


async def _game_link(db: AsyncSession, game_id: uuid.UUID, adapter_id: str) -> Optional[ExternalGameLink]:
    return await db.scalar(select(ExternalGameLink).where(ExternalGameLink.scheduled_game_id == game_id,
                                                          ExternalGameLink.adapter_id == adapter_id).with_for_update())


def _game_link_json(g: ExternalGameLink) -> dict[str, Any]:
    return {"adapter_id": g.adapter_id, "external_ref": g.external_ref, "cancelled": g.cancelled,
            "last_synced_at": g.last_synced_at.isoformat() if g.last_synced_at else None,
            "last_error": g.last_error}


@router.get("/fields/{field_id}/scheduled-games/{game_id}/integrations")
async def game_links(field_id: uuid.UUID, game_id: uuid.UUID, principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    game = await db.scalar(select(ScheduledGame).where(ScheduledGame.id == game_id, ScheduledGame.field_id == field_id))
    if game is None:
        raise HTTPException(404, "scheduled_game_not_found")
    rows = await db.scalars(select(ExternalGameLink).where(ExternalGameLink.scheduled_game_id == game_id)
                            .order_by(ExternalGameLink.adapter_id))
    return JSONResponse([_game_link_json(g) for g in rows], headers=NO_STORE)


@router.post("/fields/{field_id}/scheduled-games/{game_id}/integrations/{adapter_id}/push")
async def push(field_id: uuid.UUID, game_id: uuid.UUID, adapter_id: str, request: Request,
               principal: Principal = Depends(current_principal),
               db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """Publishes the game on the platform the first time, updates it after, cancels it once it is cancelled
    here. Drafts never leave the site server."""
    require_field_role(principal, field_id, "admin")
    field, game, adapter, config = await _ready(db, request, field_id, game_id, adapter_id, "publish")
    if game.status == "draft":
        raise HTTPException(409, "game_not_published")
    link = await _game_link(db, game_id, adapter_id)
    now = reg_svc.now_utc()
    registered = (await reg_svc.counts(db, [game.id])).get(game.id, 0)
    view = published_game(request, game, field, now, registered)
    if link is None:
        link = ExternalGameLink(scheduled_game_id=game_id, adapter_id=adapter_id)
        db.add(link)
    if link.external_ref is None:
        if game.status == "cancelled":
            raise HTTPException(409, "game_cancelled")
        operation = "publish"
        ref, error = await call(db, request, principal, field_id, game_id, adapter_id, operation,
                                lambda: adapter.publish(view, config))
        if error is None:
            if not isinstance(ref, str) or not 1 <= len(ref) <= 256:
                ref, error = None, "adapter_failed"
            else:
                link.external_ref = ref
    elif game.status == "cancelled":
        if link.cancelled:
            raise HTTPException(409, "already_cancelled")
        if "cancel" not in adapter.capabilities:
            raise HTTPException(409, "capability_missing")
        operation = "cancel"
        _, error = await call(db, request, principal, field_id, game_id, adapter_id, operation,
                              lambda: adapter.cancel(link.external_ref, config))
        if error is None:
            link.cancelled = True
    else:
        if "update" not in adapter.capabilities:
            raise HTTPException(409, "capability_missing")
        operation = "update"
        _, error = await call(db, request, principal, field_id, game_id, adapter_id, operation,
                              lambda: adapter.update(link.external_ref, view, config))
    link.last_error = error
    if error is None:
        link.last_synced_at = now
    await db.commit()
    await db.refresh(link)
    return JSONResponse({"operation": operation, **_game_link_json(link)}, status_code=502 if error else 200,
                        headers=NO_STORE)


def _raw_rows(items: list[ImportedRegistration]) -> list[fmt.RawRow]:
    """A platform's registrations as import rows: the same columns, the same checks (F21)."""
    rows = []
    for number, item in enumerate(items, start=1):
        if not isinstance(item, ImportedRegistration):
            rows.append(fmt.RawRow(number, {}, "row_not_object"))
            continue
        rows.append(fmt.RawRow(number, {
            "display_name": item.display_name, "external_ref": item.external_ref,
            "team_preference": item.team_preference, "federation_number": item.federation_number,
            "replicas": [{"type": r.type, "class": r.cls, "make_model": r.make_model} for r in item.replicas]}))
    return rows


@router.post("/fields/{field_id}/scheduled-games/{game_id}/integrations/{adapter_id}/registrations")
async def fetch_registrations(field_id: uuid.UUID, game_id: uuid.UUID, adapter_id: str, request: Request,
                              dry_run: bool = False, basis_confirmed: bool = False,
                              principal: Principal = Depends(current_principal),
                              db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    if not dry_run and not basis_confirmed:
        raise HTTPException(400, "basis_not_confirmed")
    field, game, adapter, config = await _ready(db, request, field_id, game_id, adapter_id, "registrations")
    try:
        import_svc.check_game(game, reg_svc.now_utc())  # before the platform is asked anything
    except reg_svc.RegistrationError as exc:
        raise HTTPException(exc.status, exc.code) from None
    link = await _game_link(db, game_id, adapter_id)
    if link is None or link.external_ref is None:
        raise HTTPException(409, "not_published_there")
    ref = link.external_ref
    items, error = await call(db, request, principal, field_id, game_id, adapter_id, "registrations",
                              lambda: adapter.fetch_registrations(ref, config))
    if error is None and (not isinstance(items, list) or len(items) > fmt.MAX_ROWS):
        items, error = None, "too_many_rows" if isinstance(items, list) else "adapter_failed"
    link.last_error = error
    if error is not None:
        await db.commit()
        return JSONResponse({"detail": error}, status_code=502, headers=NO_STORE)
    assert items is not None
    parsed = fmt.Parsed("adapter", fmt.COLUMNS, [], 0, _raw_rows(items))
    try:
        game = await reg_svc.lock_game(db, field_id, game_id)
        outcome = await import_svc.run(db, field, game, parsed, adapter_id, dry_run, reg_svc.now_utc())
    except reg_svc.RegistrationError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.code) from None
    if not dry_run:  # a dry run wrote nothing; the call itself is logged either way
        link.last_synced_at = reg_svc.now_utc()
        record(db, "registration_import", request, user_id=principal.user.id, resource="scheduled_game",
               resource_id=game_id, details={"field_id": str(field_id), "source": adapter_id, "format": "adapter",
                                             "counts": outcome.counts, "not_imported_columns": []})
    await db.commit()
    return JSONResponse(outcome.answer, headers=NO_STORE)
