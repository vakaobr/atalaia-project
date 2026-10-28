# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A field's data export for its administrator (S21-12; ``field_export.py`` has the format and what is left out).

    GET /api/v1/fields/{field_id}/export     the field's ``admin`` in a TOTP session (a server administrator counts
                                             as one): the field's own data as a ZIP of JSON Lines files
    GET /api/v1/fields/{field_id}/quotas     the same caller: what the field uses of each hosted-mode limit
                                             (``{"hosted": bool, "quotas": [{name, used, limit}]}``; ``limit`` is
                                             null when there is none, ``used`` null when it is not counted; a
                                             single-field server has no quotas: ``hosted`` false and no rows)

Answers ``200`` with ``application/zip`` (``Content-Disposition: attachment``, ``Cache-Control: no-store``,
``X-Content-SHA256`` of the file, also in the audit log's ``field_export`` row), or:

- ``401`` / ``403 role_required`` / ``404 field_not_found`` as every field endpoint;
- ``409 export_running``: another export of this field is being built (one at a time per field);
- ``429 too_many_requests`` with ``Retry-After``: one export per ``ATALAIA_EXPORT_MIN_INTERVAL_S`` (300 s) per field,
  so that nobody turns the database into a download service;
- ``413 export_too_large``: the archive would pass ``ATALAIA_EXPORT_MAX_MB`` (512): the operator's
  ``hosted export`` or the database backup is the way for a field that big.

The archive is built before the answer starts, in a repeatable-read read-only transaction, and the audit row is made in
its own transaction once it is ready (so the log says "prepared and sent", never "started"). In memory the server
keeps up to 16 MB of it; more goes to a temporary file the server deletes when the download ends.
"""

from __future__ import annotations

import math
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .. import field_export, quotas, tenancy
from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import Field

router = APIRouter(prefix="/api/v1", tags=["fields"])

CHUNK = 256 * 1024
NO_STORE = {"Cache-Control": "no-store"}


def _chunks(built: field_export.Built) -> Iterator[bytes]:
    try:
        while block := built.file.read(CHUNK):
            yield block
    finally:
        built.file.close()


@router.get("/fields/{field_id}/quotas")
async def field_quotas(field_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """What the field uses of each quota, for its administrator (decision PKC-1)."""
    require_field_role(principal, field_id, "admin")
    if await db.get(Field, field_id) is None:
        raise HTTPException(404, "field_not_found")
    tenant = tenancy.current()
    if tenant is None:
        return JSONResponse({"hosted": False, "quotas": []}, headers=NO_STORE)
    watch = request.app.state.tenant_watch
    rows = await quotas.usage(db, field_id, watch.count(tenant.schema, field_id))
    return JSONResponse({"hosted": True, "quotas": rows}, headers=NO_STORE)


@router.get("/fields/{field_id}/export")
async def export_field(field_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> Any:
    require_field_role(principal, field_id, "admin")
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    settings = request.app.state.settings
    state: dict[tuple[Any, uuid.UUID], dict[str, Any]] = request.app.state.export_state
    key = (tenancy.current_schema(), field_id)
    entry = state.setdefault(key, {"running": False, "last": None})
    if entry["running"]:
        raise HTTPException(409, "export_running")
    wait = 0
    if entry["last"] is not None:
        remaining = entry["last"] + settings.export_min_interval_s - time.monotonic()
        wait = math.ceil(remaining) if remaining > 0 else 0
    if wait > 0:
        return JSONResponse({"detail": "too_many_requests"}, status_code=429, headers={"Retry-After": str(wait),
                                                                                       "Cache-Control": "no-store"})
    entry["running"] = True
    built = None
    try:
        # The principal's reads are done: the export starts its own transaction (and reads plain values: the ORM
        # object would be expired by the rollback).
        info = SimpleNamespace(id=field.id, slug=field.slug, name=field.name)
        user_id = principal.user.id
        await db.rollback()
        async with request.app.state.sessionmaker() as export_db:
            try:
                built = await field_export.build(export_db, info, hosted=settings.hosted,
                                                 max_bytes=settings.export_max_mb * 1024 * 1024)
            except field_export.ExportTooLarge:
                raise HTTPException(413, "export_too_large") from None
            finally:
                await export_db.rollback()
        rows = {d["name"]: d["rows"] for d in built.manifest["datasets"]}
        async with request.app.state.sessionmaker() as audit_db:
            record(audit_db, "field_export", request, user_id=user_id, resource="field", resource_id=field_id,
                   details={"format": field_export.FORMAT, "version": field_export.VERSION, "sha256": built.sha256,
                            "bytes": built.size, "rows": rows})
            await audit_db.commit()
    except BaseException:
        if built is not None:
            built.file.close()
        raise
    finally:
        entry["running"] = False
        entry["last"] = time.monotonic()  # a refused (too large) or failed attempt waits too: it was the costly part
    name = f"atalaia-{info.slug}-{datetime.now(timezone.utc):%Y%m%d}.zip"
    return StreamingResponse(_chunks(built), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}"',
                                      "Content-Length": str(built.size), "Cache-Control": "no-store",
                                      "X-Content-SHA256": built.sha256})
