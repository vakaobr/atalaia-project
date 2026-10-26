# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The server administrators' side of a preview server's feedback form (decisions PV-*).

    GET    /api/v1/admin/feedback              the feedback, newest first (?status=new|seen|done|all, default new;
                                               ?limit=1-500, default 200), with the counts per status
    PATCH  /api/v1/admin/feedback/{id}         {"status": "new" | "seen" | "done"}
    DELETE /api/v1/admin/feedback/{id}         delete one (spam, or a request to erase)

Only a server administrator in a TOTP session, as for the club reports; only registered on a server started
with ``ATALAIA_PREVIEW=on``. The form itself is in ``web/preview.py``.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..auth import Principal, server_admin
from ..db import get_session
from ..preview_models import FEEDBACK_STATUSES, PreviewFeedback

router = APIRouter(prefix="/api/v1/admin", tags=["feedback"])
NO_STORE = {"Cache-Control": "no-store"}


class FeedbackPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


def feedback_json(row: PreviewFeedback) -> dict[str, Any]:
    return {"id": str(row.id), "kind": row.kind, "who": row.who, "message": row.message, "contact": row.contact,
            "page": row.page, "lang": row.lang, "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None}


async def list_feedback(db: AsyncSession, status: str = "new", limit: int = 200) -> dict[str, Any]:
    """The feedback with this status (``all``: every one), newest first, and the count of each status."""
    if status != "all" and status not in FEEDBACK_STATUSES:
        raise HTTPException(400, "status_invalid")
    query = select(PreviewFeedback)
    if status != "all":
        query = query.where(PreviewFeedback.status == status)
    rows = await db.scalars(query.order_by(PreviewFeedback.created_at.desc(), PreviewFeedback.id.desc())
                            .limit(max(1, min(limit, 500))))
    counts = {s: 0 for s in FEEDBACK_STATUSES}
    for s, n in await db.execute(select(PreviewFeedback.status, func.count()).group_by(PreviewFeedback.status)):
        counts[s] = int(n)
    return {"counts": counts, "feedback": [feedback_json(r) for r in rows]}


@router.get("/feedback")
async def get_feedback(request: Request, principal: Principal = Depends(server_admin),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    try:
        limit = int(request.query_params.get("limit", "200"))
    except ValueError:
        raise HTTPException(400, "limit_invalid") from None
    return JSONResponse(await list_feedback(db, request.query_params.get("status", "new"), limit), headers=NO_STORE)


@router.patch("/feedback/{feedback_id}")
async def patch_feedback(feedback_id: uuid.UUID, body: FeedbackPatch, request: Request,
                         principal: Principal = Depends(server_admin),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if body.status not in FEEDBACK_STATUSES:
        raise HTTPException(400, "status_invalid")
    row = await db.get(PreviewFeedback, feedback_id)
    if row is None:
        raise HTTPException(404, "feedback_not_found")
    row.status = body.status
    record(db, "preview_feedback_status", request, user_id=principal.user.id, resource="preview_feedback",
           resource_id=row.id, details={"status": body.status})
    await db.commit()
    await db.refresh(row)
    return JSONResponse(feedback_json(row), headers=NO_STORE)


@router.delete("/feedback/{feedback_id}")
async def delete_feedback(feedback_id: uuid.UUID, request: Request, principal: Principal = Depends(server_admin),
                          db: AsyncSession = Depends(get_session)) -> Response:
    gone = await db.execute(delete(PreviewFeedback).where(PreviewFeedback.id == feedback_id))
    if not gone.rowcount:
        raise HTTPException(404, "feedback_not_found")
    record(db, "preview_feedback_delete", request, user_id=principal.user.id, resource="preview_feedback",
           resource_id=feedback_id)
    await db.commit()
    return Response(status_code=204, headers=NO_STORE)
