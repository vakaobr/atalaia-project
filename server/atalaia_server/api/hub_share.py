# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Linking a person's accounts at the fields of a hosted hub, for chrono sharing across tenants
(SVX-2; ADR-P4-4's amendment of 2026-10-28; ``hub_share.py``). Hosted mode only: a single-field server
answers 404 ``not_hosted``.

    GET    /api/v1/me/hub-share         Bearer                 {linked, linked_at, sharing, field: {id, name, enabled,
                                                               live}, consent, others: [{field_name, sharing, since}]}
                                                               (the app reads the first three; the staff page
                                                               /staff/account/hub-share reads all, HLC-*)
    POST   /api/v1/me/hub-share/code    Bearer                 a link code for another field of the hub (shown once,
                                                               15 minutes, used once): {code, expires_at, expires_in}
    POST   /api/v1/me/hub-share/link    Bearer, {code}         link this account to the person the code names
    DELETE /api/v1/me/hub-share         Bearer                 unlink; this field's records leave the hub's view

What is shared is the same as in single-field mode and needs the same consent: the person's
``PUT /api/v1/me/consents/chrono-sharing/{field_id}`` at each field and the field's own switch. At most 10 codes
or links an hour per account. Linking is audited (``hub_share_code``, ``hub_share_linked``, ``hub_share_unlinked``)
without the code.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from .. import hub_share
from ..audit import record
from ..auth import Principal, current_principal
from ..db import get_session
from .auth import NO_STORE, Strict

router = APIRouter(prefix="/api/v1", tags=["chrono sharing"])


class LinkIn(Strict):
    code: str = Field(max_length=64)


def _limited(request: Request, principal: Principal) -> None:
    wait = request.app.state.limits.hub_share.hit(str(principal.user.id))
    if wait:
        raise HTTPException(429, "too_many_requests", headers={"Retry-After": str(wait)})


@router.get("/me/hub-share")
async def state(principal: Principal = Depends(current_principal),
                db: AsyncSession = Depends(get_session)) -> JSONResponse:
    try:
        return JSONResponse(await hub_share.status(db, principal.user.id), headers=NO_STORE)
    except hub_share.HubShareProblem as e:
        raise HTTPException(e.status, e.detail) from None


@router.post("/me/hub-share/code", status_code=201)
async def make_code(request: Request, principal: Principal = Depends(current_principal),
                    db: AsyncSession = Depends(get_session)) -> JSONResponse:
    _limited(request, principal)
    try:
        out = await hub_share.new_code(db, principal.user.id)
    except hub_share.HubShareProblem as e:
        raise HTTPException(e.status, e.detail) from None
    record(db, "hub_share_code", request, user_id=principal.user.id, resource="user", resource_id=principal.user.id)
    await db.commit()
    return JSONResponse(out, status_code=201, headers=NO_STORE)


@router.post("/me/hub-share/link")
async def link(body: LinkIn, request: Request, principal: Principal = Depends(current_principal),
               db: AsyncSession = Depends(get_session)) -> JSONResponse:
    _limited(request, principal)
    try:
        out = await hub_share.redeem(db, principal.user.id, body.code)
    except hub_share.HubShareProblem as e:
        await db.rollback()  # a refused code is not used up
        raise HTTPException(e.status, e.detail) from None
    record(db, "hub_share_linked", request, user_id=principal.user.id, resource="user", resource_id=principal.user.id)
    await db.commit()
    return JSONResponse(out, headers=NO_STORE)


@router.delete("/me/hub-share", status_code=204)
async def unlink(request: Request, principal: Principal = Depends(current_principal),
                 db: AsyncSession = Depends(get_session)) -> Response:
    if not hub_share.available():
        raise HTTPException(404, "not_hosted")
    if not await hub_share.unlink(db, principal.user.id):
        raise HTTPException(404, "not_linked")
    record(db, "hub_share_unlinked", request, user_id=principal.user.id, resource="user", resource_id=principal.user.id)
    await db.commit()
    return Response(status_code=204)
