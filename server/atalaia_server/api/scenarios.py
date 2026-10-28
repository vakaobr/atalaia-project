# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's scenario library and game presets (plan phase 20; ``services/library.py``).

    POST   /api/v1/fields/{field_id}/scenarios/check          {"manifest": text}: its problems (validator, then
                                                              the core's load check), nothing stored
    GET    /api/v1/fields/{field_id}/scenarios?archived=      the library: id, revision, version, name
    POST   /api/v1/fields/{field_id}/scenarios                {"manifest": text}: save it as the scenario's
                                                              next revision (201 for a new scenario)
    GET    /api/v1/fields/{field_id}/scenarios/{id}           the current manifest, the package it compiles to
                                                              and the revisions
    GET    /api/v1/fields/{field_id}/scenarios/{id}/revisions/{n}   one revision's manifest
    DELETE /api/v1/fields/{field_id}/scenarios/{id}           archive: no longer pushed (saving it again
                                                              restores it)
    GET    /api/v1/fields/{field_id}/presets                  the field's game presets
    POST   /api/v1/fields/{field_id}/presets                  {name, mode_id, params}
    PUT    /api/v1/fields/{field_id}/presets/{preset_id}      the same, replacing it
    DELETE /api/v1/fields/{field_id}/presets/{preset_id}

All of them for the field's admin and gm in a TOTP session (a manifest and a preset's parameters hold the
game's codes and destinations, as the controller's ``GET /api/v1/scenarios/{id}`` is for its GM token only).
Every change is in the audit log (scenario id and revision, preset name; never a manifest or parameters).
The field's controllers pull the library with ``GET /api/v1/sync/presets`` (``api/sync.py``).
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import quotas
from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..history_models import FieldPreset, FieldScenarioRevision
from ..models import Field
from ..services import branding, library
from .fields import NO_STORE

router = APIRouter(prefix="/api/v1/fields/{field_id}", tags=["scenarios"])


def core_holder(request: Request) -> library.CoreHolder:
    """The app's core (loaded on first use; a test may set its own holder)."""
    holder = getattr(request.app.state, "core_holder", None)
    if holder is None:
        holder = request.app.state.core_holder = library.CoreHolder()
    return holder


async def _staff(principal: Principal, db: AsyncSession, field_id: uuid.UUID) -> None:
    require_field_role(principal, field_id, "admin", "gm")
    if await db.get(Field, field_id) is None:
        raise HTTPException(404, "field_not_found")


def _text(body: Any) -> str:
    text = body.get("manifest") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        raise library.LibraryProblem(400, "scenario_refused", [{
            "path": "", "code": "bad_manifest", "level": "error",
            "message": 'the request body is {"manifest": "<the scenario\'s YAML>"}'}])
    return text


def _problem(exc: library.LibraryProblem) -> JSONResponse:
    return JSONResponse(exc.body(), status_code=exc.status, headers=NO_STORE)


@router.post("/scenarios/check")
async def check_scenario(field_id: uuid.UUID, request: Request, body: Any = Body(None),
                         principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _staff(principal, db, field_id)
    try:
        text = _text(body)
    except library.LibraryProblem as exc:
        return _problem(exc)
    checked = library.check(core_holder(request), text)
    out = {"ok": checked.ok and checked.checked_in_core, "problems": [p.to_dict() for p in checked.problems],
           **library.summary(checked.manifest), "checked_in_core": checked.checked_in_core}
    current = await library.find(db, field_id, out["scenario_id"]) if out["scenario_id"] else None
    out["saved_revision"] = current.revision if current is not None and current.archived_at is None else None
    return JSONResponse(out, headers=NO_STORE)


@router.get("/scenarios")
async def list_scenarios(field_id: uuid.UUID, archived: bool = False,
                         principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _staff(principal, db, field_id)
    return JSONResponse(await library.listing(db, field_id, archived=archived), headers=NO_STORE)


@router.post("/scenarios")
async def save_scenario(field_id: uuid.UUID, request: Request, body: Any = Body(None),
                        principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _staff(principal, db, field_id)
    await quotas.check_stored(db)  # hosted mode: the field's stored-bytes quota (409 quota_exceeded)
    try:
        saved, outcome = await library.save(db, core_holder(request), field_id, _text(body))
    except library.LibraryProblem as exc:
        await db.rollback()
        return _problem(exc)
    except IntegrityError:  # the same new scenario saved twice at once: this one lost
        await db.rollback()
        return JSONResponse({"detail": "conflict_retry"}, status_code=409, headers=NO_STORE)
    if outcome != "unchanged":
        record(db, f"scenario_{outcome}", request, user_id=principal.user.id, resource="field", resource_id=field_id,
               details={"scenario": saved["scenario_id"], "revision": saved["revision"]})
    await db.commit()
    if outcome != "unchanged":
        branding.announce(request, [field_id], ("library",))  # the controllers pull it at once (PKD-1)
    return JSONResponse({**saved, "outcome": outcome}, status_code=201 if outcome == "created" else 200,
                        headers=NO_STORE)


async def _scenario(db: AsyncSession, field_id: uuid.UUID, scenario_id: str) -> Any:
    scenario = await library.find(db, field_id, scenario_id)
    if scenario is None:
        raise HTTPException(404, "scenario_not_found")
    return scenario


@router.get("/scenarios/{scenario_id}")
async def read_scenario(field_id: uuid.UUID, scenario_id: str, principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _staff(principal, db, field_id)
    scenario = await _scenario(db, field_id, scenario_id)
    rev = await library.current(db, scenario)
    return JSONResponse({**library.scenario_json(scenario, rev), "manifest": rev.manifest, "warnings": rev.warnings,
                         "files": library.package_files(rev.manifest),
                         "revisions": await library.revisions(db, scenario)}, headers=NO_STORE)


@router.get("/scenarios/{scenario_id}/revisions/{revision}")
async def read_revision(field_id: uuid.UUID, scenario_id: str, revision: int,
                        principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _staff(principal, db, field_id)
    scenario = await _scenario(db, field_id, scenario_id)
    rev = await db.scalar(select(FieldScenarioRevision).where(FieldScenarioRevision.scenario == scenario.id,
                                                              FieldScenarioRevision.revision == revision))
    if rev is None:
        raise HTTPException(404, "revision_not_found")
    return JSONResponse({"scenario_id": scenario.scenario_id, "revision": rev.revision, "version": rev.version,
                         "name": rev.name, "sha256": rev.manifest_sha256, "manifest": rev.manifest,
                         "warnings": rev.warnings, "created_at": rev.created_at.isoformat()}, headers=NO_STORE)


@router.delete("/scenarios/{scenario_id}", status_code=204)
async def archive_scenario(field_id: uuid.UUID, scenario_id: str, request: Request,
                           principal: Principal = Depends(current_principal),
                           db: AsyncSession = Depends(get_session)) -> Response:
    await _staff(principal, db, field_id)
    scenario = await _scenario(db, field_id, scenario_id)
    changed = scenario.archived_at is None
    if changed:
        scenario.archived_at = func.now()
        record(db, "scenario_archived", request, user_id=principal.user.id, resource="field", resource_id=field_id,
               details={"scenario": scenario.scenario_id, "revision": scenario.revision})
    await db.commit()
    if changed:
        branding.announce(request, [field_id], ("library",))
    return Response(status_code=204)


# --- presets ---------------------------------------------------------------------------------


@router.get("/presets")
async def list_presets(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _staff(principal, db, field_id)
    return JSONResponse([library.preset_json(p) for p in await library.presets(db, field_id)], headers=NO_STORE)


async def _store_preset(db: AsyncSession, preset: FieldPreset) -> None:
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "preset_name_taken") from None
    await db.refresh(preset)


@router.post("/presets", status_code=201)
async def create_preset(field_id: uuid.UUID, request: Request, body: Any = Body(None),
                        principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _staff(principal, db, field_id)
    try:
        spec = library.check_preset(body)
    except library.LibraryProblem as exc:
        return _problem(exc)
    count = await db.scalar(select(func.count()).select_from(FieldPreset).where(FieldPreset.field_id == field_id))
    if (count or 0) >= library.MAX_PRESETS:
        raise HTTPException(409, "too_many_presets")
    preset = FieldPreset(field_id=field_id, **spec)
    db.add(preset)
    await _store_preset(db, preset)
    record(db, "preset_create", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"preset": preset.name, "mode_id": preset.mode_id})
    await db.commit()
    branding.announce(request, [field_id], ("library",))
    return JSONResponse(library.preset_json(preset), status_code=201, headers=NO_STORE)


async def _preset(db: AsyncSession, field_id: uuid.UUID, preset_id: uuid.UUID) -> FieldPreset:
    preset = await db.get(FieldPreset, preset_id)
    if preset is None or preset.field_id != field_id:
        raise HTTPException(404, "preset_not_found")
    return preset


@router.put("/presets/{preset_id}")
async def replace_preset(field_id: uuid.UUID, preset_id: uuid.UUID, request: Request, body: Any = Body(None),
                         principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _staff(principal, db, field_id)
    try:
        spec = library.check_preset(body)
    except library.LibraryProblem as exc:
        return _problem(exc)
    preset = await _preset(db, field_id, preset_id)
    preset.name, preset.mode_id, preset.params = spec["name"], spec["mode_id"], spec["params"]
    await _store_preset(db, preset)
    record(db, "preset_update", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"preset": preset.name, "mode_id": preset.mode_id})
    await db.commit()
    branding.announce(request, [field_id], ("library",))
    return JSONResponse(library.preset_json(preset), headers=NO_STORE)


@router.delete("/presets/{preset_id}", status_code=204)
async def delete_preset(field_id: uuid.UUID, preset_id: uuid.UUID, request: Request,
                        principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> Response:
    await _staff(principal, db, field_id)
    preset = await _preset(db, field_id, preset_id)
    await db.delete(preset)
    record(db, "preset_delete", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"preset": preset.name})
    await db.commit()
    branding.announce(request, [field_id], ("library",))
    return Response(status_code=204)
