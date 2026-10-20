# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registration import and the list's CSV export (ADR-P4-12; plan phase 17, decisions F20, S17-*).

    POST /api/v1/fields/{field_id}/scheduled-games/{id}/registrations/import?source=&dry_run=&basis_confirmed=
         admin or gm: a CSV (``text/csv``) or JSON (``application/json``) list, at most 1 MiB and 5,000
         rows; ``dry_run=true`` previews and writes nothing; a real import needs ``basis_confirmed=true``
         (the field is the data controller of what it imports and must have its own basis for having that
         list). The answer lists every row as created, updated, unchanged, skipped or refused (with a code).
    GET  /api/v1/fields/{field_id}/scheduled-games/{id}/registrations.csv
         admin or gm: the game's registrations as CSV, in the import's columns first, every cell safe
         from spreadsheet formulas.

The roles count only in a TOTP session. A real import is in the audit log (``registration_import``: the
source, the counts and the names of the columns not imported, never a value); an export too
(``registration_export``). Format and rules: ``import_format.py``, ``services/registration_import.py``,
``server/docs/integrations.md``.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import import_format as fmt
from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import Field, ScheduledGame
from ..services import registration as reg_svc
from ..services import registration_import as svc
from .fields import NO_STORE

router = APIRouter(prefix="/api/v1", tags=["registrations"])

MEDIA = {"text/csv": "csv", "application/json": "json"}


async def read_capped(request: Request, limit: int = fmt.MAX_BYTES) -> bytes:
    """The request body, refused with 413 once it passes ``limit`` bytes (before it is all read)."""
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise HTTPException(413, "too_large")
        except ValueError:
            raise HTTPException(400, "content_length_invalid") from None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, "too_large")
        chunks.append(chunk)
    return b"".join(chunks)


def media_format(request: Request) -> str:
    """``csv`` or ``json`` from the Content-Type (a charset other than UTF-8 is refused)."""
    value = request.headers.get("content-type", "")
    kind, _, params = value.partition(";")
    found = MEDIA.get(kind.strip().lower())
    if found is None:
        raise HTTPException(415, "unsupported_media_type")
    for param in params.split(";"):
        key, _, val = param.strip().partition("=")
        if key.strip().lower() == "charset" and val.strip().strip('"').lower() not in ("utf-8", "utf8"):
            raise HTTPException(415, "charset_not_utf8")
    return found


def file_error(exc: fmt.FileError) -> JSONResponse:
    status = 413 if exc.code in ("too_large", "too_many_rows") else 400
    body: dict[str, object] = {"detail": exc.code}
    if exc.line is not None:
        body["line"] = exc.line
    return JSONResponse(body, status_code=status, headers=NO_STORE)


async def _field(db: AsyncSession, field_id: uuid.UUID) -> Field:
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    return field


@router.post("/fields/{field_id}/scheduled-games/{game_id}/registrations/import")
async def import_registrations(field_id: uuid.UUID, game_id: uuid.UUID, request: Request,
                               source: str = Query(..., max_length=64), dry_run: bool = False,
                               basis_confirmed: bool = False, principal: Principal = Depends(current_principal),
                               db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    try:
        label = fmt.check_source(source)
    except fmt.FileError as exc:
        return file_error(exc)
    if not dry_run and not basis_confirmed:
        raise HTTPException(400, "basis_not_confirmed")
    kind = media_format(request)
    data = await read_capped(request)
    try:
        parsed = fmt.parse(data, kind)
    except fmt.FileError as exc:
        return file_error(exc)
    field = await _field(db, field_id)
    try:
        game = await reg_svc.lock_game(db, field_id, game_id)
        outcome = await svc.run(db, field, game, parsed, label, dry_run, reg_svc.now_utc())
    except reg_svc.RegistrationError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.code) from None
    if dry_run:
        await db.rollback()
    else:
        record(db, "registration_import", request, user_id=principal.user.id, resource="scheduled_game",
               resource_id=game_id, details={"field_id": str(field_id), "source": label, "format": kind,
                                             "counts": outcome.counts,
                                             "not_imported_columns": parsed.ignored})
        await db.commit()
    return JSONResponse(outcome.answer, headers=NO_STORE)


@router.get("/fields/{field_id}/scheduled-games/{game_id}/registrations.csv")
async def export_registrations(field_id: uuid.UUID, game_id: uuid.UUID, request: Request,
                               principal: Principal = Depends(current_principal),
                               db: AsyncSession = Depends(get_session)) -> Response:
    require_field_role(principal, field_id, "admin", "gm")
    game = await db.scalar(select(ScheduledGame).where(ScheduledGame.id == game_id, ScheduledGame.field_id == field_id))
    if game is None:
        raise HTTPException(404, "scheduled_game_not_found")
    text = fmt.export_csv(await svc.export_rows(db, game))
    record(db, "registration_export", request, user_id=principal.user.id, resource="scheduled_game",
           resource_id=game_id, details={"field_id": str(field_id)})
    await db.commit()
    # With a byte order mark, as the controller's check-in export, so spreadsheets read it as UTF-8.
    return Response(text.encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={**NO_STORE, "Content-Disposition": f'attachment; filename="registrations-{game_id}.csv"'})
