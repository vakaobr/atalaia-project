# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote GM (plan phase 19; P4R12; decisions S19-1 to S19-4, S19-8 to S19-10).

    GET  /api/v1/fields/{field_id}/remote-gm            the field's gm: its connected controllers, each with
                                                        whether it takes remote commands and its live view
    POST /api/v1/fields/{field_id}/remote-gm/commands   the field's gm: {game: {game_id, game_seed}, command,
                                                        params?, controller_id?}: one command, sent on the
                                                        controller's own socket; answers the controller's result
    GET  /api/v1/fields/{field_id}/remote-gm/log        the field's admin or gm: the audit log's remote GM rows

Who may: a user with the ``gm`` role on that field, in a session that passed
the TOTP step (``gm`` counts only then, ADR-P4-2); not the field's admin, not a
per-game gm and not a server administrator unless they also hold ``gm`` on the
field. What: only ``sync_format.REMOTE_COMMANDS`` (start, pause, resume, end,
a GM message, a declared mode command), each checked here with the same
function the controller checks it with again. Where: only to a controller that
opened its stream with ``[sync] remote_gm = true``; the site server never
connects to a controller. At most 30 commands a minute per account. Every
attempt is in the audit log: ``remote_gm_command`` (sent: the command, its
parameters, the controller and its result) or ``remote_gm_denied`` (not sent,
and why); the controller logs each command it gets on its side too.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Optional

from atalaia_controller import sync_format
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..ids import uuid7
from ..models import AuditLog, FieldApiKey, User
from ..remote_gm import RemoteHub, RemoteProblem

router = APIRouter(prefix="/api/v1/fields/{field_id}/remote-gm", tags=["remote gm"])
NO_STORE = {"Cache-Control": "no-store"}
ACTIONS = ("remote_gm_command", "remote_gm_denied")
MAX_BODY = 4096


def _hub(request: Request) -> RemoteHub:
    return request.app.state.remote_hub


def _is_gm(principal: Principal, field_id: uuid.UUID) -> bool:
    return "gm" in principal.field_roles(field_id)  # privileged: only in a TOTP session


@router.get("")
async def remote_view(field_id: uuid.UUID, request: Request,
                      principal: Principal = Depends(current_principal)) -> JSONResponse:
    if not _is_gm(principal, field_id):
        raise HTTPException(403, "role_required")
    return JSONResponse({"controllers": [link.json() for link in _hub(request).links(field_id)],
                         "commands": list(sync_format.REMOTE_COMMANDS)}, headers=NO_STORE)


def _deny(db: AsyncSession, request: Request, principal: Principal, field_id: uuid.UUID, reason: str,
          **details: Any) -> None:
    record(db, "remote_gm_denied", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"reason": reason, **{k: v for k, v in details.items() if v is not None}})


@router.post("/commands")
async def remote_command(field_id: uuid.UUID, request: Request, principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    wait = request.app.state.limits.remote_commands.hit(str(principal.user.id))
    if wait:
        return JSONResponse({"detail": "too_many_requests"}, status_code=429, headers={"Retry-After": str(wait)})
    raw = await request.body()
    try:
        body = json.loads(raw) if len(raw) <= MAX_BODY else None
    except ValueError:
        body = None
    wanted = body.get("command") if isinstance(body, dict) and isinstance(body.get("command"), str) else None
    named = wanted if wanted in sync_format.REMOTE_COMMANDS else None
    if not _is_gm(principal, field_id):
        _deny(db, request, principal, field_id, "role_required", command=named)
        await db.commit()
        raise HTTPException(403, "role_required")
    if not isinstance(body, dict) or set(body) - {"game", "command", "params", "controller_id"}:
        _deny(db, request, principal, field_id, "invalid_command", command=named)
        await db.commit()
        return JSONResponse({"detail": "invalid_command", "error": "bad_body", "path": ""}, status_code=400)
    controller_id = body.get("controller_id")
    command = {"id": str(uuid7()), "game": body.get("game"), "command": body.get("command"),
               "params": body.get("params", {}),
               "user": {"id": str(principal.user.id), "username": principal.user.username}, "sent_at": time.time()}
    try:
        if controller_id is not None and not isinstance(controller_id, str):
            raise sync_format.SyncFormatError("not_a_text", "controller_id")
        command = sync_format.check_command(command)
    except sync_format.SyncFormatError as exc:
        _deny(db, request, principal, field_id, "invalid_command", command=named, error=exc.code, path=exc.path)
        await db.commit()
        return JSONResponse({"detail": "invalid_command", "error": exc.code, "path": exc.path}, status_code=400)
    what = {"command": command["command"], "params": command["params"], "game_id": command["game"]["game_id"],
            "game_seed": command["game"]["game_seed"]}
    hub = _hub(request)
    try:
        link = hub.pick(field_id, controller_id)
        key = await db.get(FieldApiKey, link.key_id)
        if key is None or key.revoked_at is not None:
            hub.detach(link)
            raise RemoteProblem(409, "controller_offline")
        if not link.remote_gm:
            raise RemoteProblem(409, "remote_gm_off")
    except RemoteProblem as exc:
        _deny(db, request, principal, field_id, exc.detail, controller_id=controller_id, **what)
        await db.commit()
        return JSONResponse({"detail": exc.detail}, status_code=exc.status, headers=NO_STORE)
    await db.commit()  # nothing held open while the controller answers
    answer: Optional[dict[str, Any]] = None
    try:
        answer = await hub.command(link, command)
        code, message = answer["code"], answer["detail"]
    except RemoteProblem as exc:  # the controller went away or did not answer in time
        code, message, problem = exc.detail, None, exc
    record(db, "remote_gm_command", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"id": command["id"], "controller_id": link.controller_id, **what, "result": code,
                    **({"message": message} if message else {})})
    await db.commit()
    out = {"id": command["id"], "controller_id": link.controller_id, "code": code, "message": message}
    if answer is None:
        return JSONResponse({**out, "detail": problem.detail}, status_code=problem.status, headers=NO_STORE)
    if code != "done":
        return JSONResponse({**out, "detail": "refused_by_controller"}, status_code=409, headers=NO_STORE)
    return JSONResponse(out, headers=NO_STORE)


@router.get("/log")
async def remote_log(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    rows = await db.execute(
        select(AuditLog, User.username).outerjoin(User, User.id == AuditLog.user_id)
        .where(AuditLog.resource == "field", AuditLog.resource_id == field_id, AuditLog.action.in_(ACTIONS))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(200))
    return JSONResponse([{"action": a.action, "at": a.created_at.isoformat(), "user_id": str(a.user_id)
                          if a.user_id else None, "username": username, "details": a.details}
                         for a, username in rows], headers=NO_STORE)
