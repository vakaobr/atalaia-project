# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The data subject's rights on their own account (ADR-P4-8, plan phase 12).

    GET    /api/v1/me/data       Bearer                       access (GDPR Art. 15): JSON
    GET    /api/v1/me/export     Bearer                       portability (Art. 20): a ZIP of JSON files
    PATCH  /api/v1/me            Bearer, {password, username?, email?}
                                                              rectification (Art. 16)
    POST   /api/v1/me/password   Bearer, {password, new_password}
                                                              a new password; other sessions end
    DELETE /api/v1/me            Bearer, {password, code?}    erasure (Art. 17): anonymised

``GET /api/v1/me`` itself is in ``api/auth.py``. Changing or erasing the
account needs the current password (and a TOTP code to erase an account that
has TOTP), under the same lockouts as a login, so a stolen 15-minute access
token cannot rename, lock out or delete its owner (decision S12-3).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import passwords, personal_data
from ..audit import record
from ..auth import Principal, current_principal, load_roles
from ..db import get_session
from ..models import UserSession
from .auth import (NO_STORE, Strict, _check_code, _check_password, _clear_cookie, _secret, _user_for_update,
                   email_problem, normalise_email, user_json, username_problem)

router = APIRouter(prefix="/api/v1", tags=["personal data"])


class ProfileIn(Strict):
    password: str = Field(max_length=4096)
    username: Optional[str] = Field(default=None, max_length=64)
    email: Optional[str] = Field(default=None, max_length=320)


class NewPasswordIn(Strict):
    password: str = Field(max_length=4096)
    new_password: str = Field(max_length=4096)


class EraseIn(Strict):
    password: str = Field(max_length=4096)
    code: Optional[str] = Field(default=None, max_length=16)


@router.get("/me/data")
async def my_data(principal: Principal = Depends(current_principal),
                  db: AsyncSession = Depends(get_session)) -> JSONResponse:
    data = await personal_data.collect(db, principal.user, principal.session.id)
    return JSONResponse(data, headers=NO_STORE)


@router.get("/me/export")
async def my_export(principal: Principal = Depends(current_principal),
                    db: AsyncSession = Depends(get_session)) -> Response:
    data = await personal_data.collect(db, principal.user, principal.session.id)
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    return Response(personal_data.export_zip(data), media_type="application/zip", headers={
        **NO_STORE, "Content-Disposition": f'attachment; filename="atalaia-export-{principal.user.username}-{day}.zip"'})


@router.patch("/me")
async def update_me(body: ProfileIn, request: Request, principal: Principal = Depends(current_principal),
                    db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """Rectification: a new username and/or email (``email: null`` or ``""`` removes it)."""
    user = await _user_for_update(db, principal)
    changes: dict[str, Optional[str]] = {}
    if body.username is not None:
        username = body.username.strip().lower()
        problem = username_problem(username)
        if problem:
            raise HTTPException(400, problem)
        if username != user.username:
            changes["username"] = username
    if "email" in body.model_fields_set:
        email = normalise_email(body.email)
        problem = email_problem(email)
        if problem:
            raise HTTPException(400, problem)
        if email != user.email:
            changes["email"] = email
    await _check_password(db, request, user, body.password, "profile_update")
    if "username" in changes and passwords.normalise(body.password).casefold() == changes["username"].casefold():
        await db.commit()  # a rehash, if any
        raise HTTPException(400, "password_is_username")
    if changes:
        for name, value in changes.items():
            setattr(user, name, value)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(409, "username_or_email_taken") from None
        # Which fields changed, never their values (decision S12-3).
        record(db, "profile_update", request, user_id=user.id, resource="user", resource_id=user.id,
               details={"fields": sorted(changes)})
    await db.commit()
    return JSONResponse(user_json(user, await load_roles(db, user.id)), headers=NO_STORE)


@router.post("/me/password", status_code=204)
async def change_password(body: NewPasswordIn, request: Request, principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_session)) -> Response:
    """A new password; every other session of the account ends (this one stays)."""
    user = await _user_for_update(db, principal)
    await _check_password(db, request, user, body.password, "password_change")
    problem = passwords.policy_problem(body.new_password, user.username)
    if problem:
        await db.commit()  # a rehash, if any
        raise HTTPException(400, problem)
    user.password_hash = await passwords.hash_password(body.new_password)
    ended = await db.execute(update(UserSession).where(
        UserSession.user_id == user.id, UserSession.id != principal.session.id,
        UserSession.revoked_at.is_(None)).values(revoked_at=datetime.now(timezone.utc)))
    record(db, "password_change", request, user_id=user.id, resource="user", resource_id=user.id,
           details={"sessions_ended": ended.rowcount or 0})
    await db.commit()
    return Response(status_code=204)


@router.delete("/me", status_code=204)
async def erase_me(body: EraseIn, request: Request, principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> Response:
    """Erasure: the account is anonymised (ADR-P4-8), every session ends, the cookie is cleared."""
    user = await _user_for_update(db, principal)
    await _check_password(db, request, user, body.password, "erasure")
    if user.totp_enabled:
        if not body.code:
            await db.commit()  # a rehash, if any
            raise HTTPException(400, "code_required")
        await _check_code(db, request, user, _secret(request, user), body.code, "erasure")
    if user.server_admin and not await personal_data.live_server_admins(db, user.id):
        await db.rollback()
        raise HTTPException(409, "last_server_admin")
    await personal_data.erase(db, user.id)
    await db.commit()
    response = Response(status_code=204)
    _clear_cookie(response)
    return response
