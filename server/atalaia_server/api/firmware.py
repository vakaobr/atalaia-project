# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The firmware catalogue (plan phase 19; RESEARCH section 8; decisions S19-5, S19-6).

    GET    /api/v1/firmware              any account: every release, each checked again against today's release
                                         keys (``verified``), the latest verified stable one per platform, the
                                         keys' ids
    POST   /api/v1/firmware              a server administrator: {platform, version, size, sha256, signature,
                                         notes?, released_at?}: added only if a trusted release key signed it
    DELETE /api/v1/firmware/{id}?reason= a server administrator: withdraw a release (it stays, marked)

A list only (``firmware.py``): no image is stored, served or sent anywhere
until OTA is built; a box will verify an image itself before installing it.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import firmware
from ..audit import record
from ..auth import Principal, current_principal, server_admin
from ..db import get_session
from ..models import FirmwareRelease
from ..services import devices

router = APIRouter(prefix="/api/v1", tags=["firmware"])
NO_STORE = {"Cache-Control": "no-store"}
FIELDS = ("platform", "version", "size", "sha256", "signature", "notes", "released_at")


class _Bad(Exception):
    def __init__(self, code: str, path: str) -> None:
        super().__init__(code)
        self.code, self.path = code, path


def _bad(code: str, path: str) -> "_Bad":
    return _Bad(code, path)


@router.get("/firmware")
async def list_firmware(request: Request, principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    keys = request.app.state.settings.firmware_keys
    releases, latest = await devices.catalogue(db, keys)
    return JSONResponse({"releases": releases, "latest": latest, "keys": [firmware.key_id(k) for k in keys]},
                        headers=NO_STORE)


def _released_at(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        when = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        when = None
    if when is None or when.tzinfo is None:
        raise _bad("bad_time", "released_at")
    return when


@router.post("/firmware", status_code=201)
async def add_firmware(request: Request, principal: Principal = Depends(server_admin),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    try:
        return await _add(request, principal, db)
    except _Bad as exc:
        return JSONResponse({"detail": "invalid_release", "error": exc.code, "path": exc.path}, status_code=400)


async def _add(request: Request, principal: Principal, db: AsyncSession) -> JSONResponse:
    keys = request.app.state.settings.firmware_keys
    if not keys:
        raise HTTPException(409, "no_release_keys")
    try:
        body = json.loads(await request.body())
    except ValueError:
        raise _bad("not_json", "") from None
    if not isinstance(body, dict):
        raise _bad("not_an_object", "")
    unknown = sorted(set(body) - set(FIELDS))
    if unknown:
        raise _bad("unknown_field", unknown[0])
    try:
        firmware.check_entry(body)
    except firmware.FirmwareError as exc:
        raise _bad(exc.code, exc.field) from None
    notes = body.get("notes")
    if notes is not None and (not isinstance(notes, str) or len(notes) > 2000):
        raise _bad("bad_text", "notes")
    released_at = _released_at(body.get("released_at"))
    key = firmware.signer(keys, body["platform"], body["version"], body["size"], body["sha256"], body["signature"])
    if key is None:
        record(db, "firmware_refused", request, user_id=principal.user.id, resource="firmware",
               details={"platform": body["platform"], "version": body["version"], "sha256": body["sha256"]})
        await db.commit()
        raise _bad("signature_not_verified", "signature")
    exists = await db.scalar(select(FirmwareRelease.id).where(FirmwareRelease.platform == body["platform"],
                                                              FirmwareRelease.version == body["version"]))
    if exists is not None:
        raise HTTPException(409, "release_exists")
    row = FirmwareRelease(platform=body["platform"], version=body["version"], size=body["size"],
                          sha256=body["sha256"], signature=body["signature"], key_id=key, notes=notes,
                          released_at=released_at, added_by=principal.user.id)
    db.add(row)
    await db.flush()
    record(db, "firmware_add", request, user_id=principal.user.id, resource="firmware", resource_id=row.id,
           details={"platform": row.platform, "version": row.version, "sha256": row.sha256, "key_id": key})
    await db.commit()
    await db.refresh(row)
    return JSONResponse(devices.release_json(row, True), status_code=201)


@router.delete("/firmware/{release_id}")
async def yank_firmware(release_id: uuid.UUID, request: Request, reason: str = Query("", max_length=200),
                        principal: Principal = Depends(server_admin),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    row = await db.get(FirmwareRelease, release_id)
    if row is None:
        raise HTTPException(404, "release_not_found")
    if row.yanked_at is None:
        row.yanked_at = datetime.now(timezone.utc)
        row.yank_reason = reason.strip() or None
        record(db, "firmware_yank", request, user_id=principal.user.id, resource="firmware", resource_id=row.id,
               details={"platform": row.platform, "version": row.version, "reason": row.yank_reason})
        await db.commit()
        await db.refresh(row)
    keys = request.app.state.settings.firmware_keys
    ok = firmware.signer(keys, row.platform, row.version, row.size, row.sha256, row.signature) is not None
    return JSONResponse(devices.release_json(row, ok))
