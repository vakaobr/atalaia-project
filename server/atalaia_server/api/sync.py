# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller sync's endpoints (ADR-P4-3 as amended, protocol/sync.md), all with a field's API key.

    POST /api/v1/sync/games    a game's metadata: create or update
    POST /api/v1/sync/events   a batch of a game's events: {after_id, events}, answers acked_id
    POST /api/v1/sync/scores   a game's score counters per source, merged by maximum; answers the totals
    POST /api/v1/sync/nodes    a game's nodes (name, role, health)
    POST /api/v1/sync/marshals the field's marshal public keys with their periods (plan phase 14)
    POST /api/v1/sync/replicas the field's replica registry
    POST /api/v1/sync/chrono   signed chrono readings with the controller's series and outcomes: each
                               verified, the ones that fail kept apart and named in the answer
    POST /api/v1/sync/checkins after a game made from a scheduled game: each registration's outcome and
                               its declarations' final states, the walk-ins as a count (plan phase 16)
    POST /api/v1/sync/claims   the controller's verdicts on accounts' claims of its player ids
    GET  /api/v1/sync/schedule?days=14         the field's published games of the coming days
    GET  /api/v1/sync/roster?scheduled_game_id= one scheduled game's live registrations
    GET  /api/v1/sync/claims                   accounts' claims of player ids, waiting for this field's verdict
    WS   /api/v1/sync/stream   the POST bodies on one socket the controller keeps open

The controller opens every connection (P4R12); nothing here connects to it.
Bodies are checked by ``atalaia_controller.sync_format``, the code the
controller's client uses (plain Python, no pydantic), and stored by
``atalaia_server.sync``. Every request with a valid key marks the key used and
the controller seen.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from atalaia_controller import sync_format
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .. import sync
from ..auth import UNAUTHORISED, bearer
from ..models import FieldApiKey
from ..services import registration

router = APIRouter(prefix="/api/v1/sync", tags=["sync"])
NO_STORE = {"Cache-Control": "no-store"}
WS_UNAUTHORISED = 4401


async def _handle(request: Request, kind: str) -> JSONResponse:
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    async with request.app.state.sessionmaker() as db:
        caller = await sync.authenticate(db, bearer(request))
        if caller is None:
            return JSONResponse({"detail": "invalid_api_key"}, status_code=401, headers=UNAUTHORISED)
        await db.commit()  # the key's last use counts even if the body is refused
        try:
            if length > sync_format.MAX_BODY:
                raise sync.SyncProblem(413, "body_too_large")
            body = sync.parse(kind, await request.body())
            answer = await sync.apply(db, caller, kind, body)
        except sync.SyncProblem as exc:
            await db.rollback()
            return JSONResponse(exc.body(), status_code=exc.status, headers=NO_STORE)
    return JSONResponse(answer, headers=NO_STORE)


@router.post("/games")
async def games(request: Request) -> JSONResponse:
    return await _handle(request, "games")


@router.post("/events")
async def events(request: Request) -> JSONResponse:
    return await _handle(request, "events")


@router.post("/scores")
async def scores(request: Request) -> JSONResponse:
    return await _handle(request, "scores")


@router.post("/nodes")
async def nodes(request: Request) -> JSONResponse:
    return await _handle(request, "nodes")


@router.post("/marshals")
async def marshals(request: Request) -> JSONResponse:
    return await _handle(request, "marshals")


@router.post("/replicas")
async def replicas(request: Request) -> JSONResponse:
    return await _handle(request, "replicas")


@router.post("/chrono")
async def chrono(request: Request) -> JSONResponse:
    return await _handle(request, "chrono")


@router.post("/checkins")
async def checkins(request: Request) -> JSONResponse:
    return await _handle(request, "checkins")


@router.post("/claims")
async def claims(request: Request) -> JSONResponse:
    return await _handle(request, "claims")


async def _pull(request: Request, build: Callable[[Any, sync.Caller], Awaitable[Any]]) -> JSONResponse:
    """A GET the controller makes: the same key, the answer checked by the shared format's ``ANSWERS``."""
    async with request.app.state.sessionmaker() as db:
        caller = await sync.authenticate(db, bearer(request))
        if caller is None:
            return JSONResponse({"detail": "invalid_api_key"}, status_code=401, headers=UNAUTHORISED)
        try:
            answer = await build(db, caller)
        except sync.SyncProblem as exc:
            await db.rollback()
            return JSONResponse(exc.body(), status_code=exc.status, headers=NO_STORE)
        await db.commit()  # the key's last use
    return JSONResponse(answer, headers=NO_STORE)


@router.get("/schedule")
async def schedule(request: Request) -> JSONResponse:
    raw = request.query_params.get("days", str(registration.SCHEDULE_DAYS))
    if not raw.isdigit() or not 1 <= int(raw) <= registration.SCHEDULE_DAYS_MAX:
        return JSONResponse({"detail": "invalid_query", "error": "out_of_range", "path": "days"}, status_code=400,
                            headers=NO_STORE)

    async def build(db: Any, caller: sync.Caller) -> Any:
        return await registration.schedule(db, caller.field_id, datetime.now(timezone.utc), int(raw))
    return await _pull(request, build)


@router.get("/roster")
async def roster(request: Request) -> JSONResponse:
    try:
        wanted = uuid.UUID(request.query_params.get("scheduled_game_id", ""))
    except ValueError:
        return JSONResponse({"detail": "invalid_query", "error": "not_a_uuid", "path": "scheduled_game_id"},
                            status_code=400, headers=NO_STORE)

    async def build(db: Any, caller: sync.Caller) -> Any:
        answer = await registration.roster(db, caller.field_id, wanted)
        if answer is None:
            raise sync.SyncProblem(404, "scheduled_game_not_found")
        return answer
    return await _pull(request, build)


@router.get("/claims")
async def pending_claims(request: Request) -> JSONResponse:
    async def build(db: Any, caller: sync.Caller) -> Any:
        return await registration.pending_claims(db, caller.field_id)
    return await _pull(request, build)


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    """One socket per controller: ``{"type": kind, ...body}`` in, ``{"type": kind + ".ack", ...}`` out."""
    scheme, _, value = ws.headers.get("authorization", "").partition(" ")
    key = value.strip() if scheme.lower() == "bearer" else None
    async with ws.app.state.sessionmaker() as db:
        caller = await sync.authenticate(db, key)
        await db.commit()
    if caller is None:
        await ws.close(code=WS_UNAUTHORISED)
        return
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            await ws.send_json(await _message(ws, caller, raw))
    except WebSocketDisconnect:
        return


async def _message(ws: WebSocket, caller: sync.Caller, raw: str) -> dict[str, Any]:
    if len(raw.encode("utf-8")) > sync_format.MAX_BODY:
        return {"type": "error", "detail": "body_too_large"}
    try:
        msg = json.loads(raw)
    except ValueError:
        return {"type": "error", **sync.SyncProblem(400, "invalid_body", "not_json", "").body()}
    if not isinstance(msg, dict) or msg.get("type") not in (*sync_format.CHECKS, "ping"):
        return {"type": "error", **sync.SyncProblem(400, "invalid_body", "bad_type", "type").body()}
    kind = msg.pop("type")
    if kind == "ping":
        return {"type": "pong"}
    async with ws.app.state.sessionmaker() as db:
        try:
            # The key may have been revoked since the socket opened.
            if not await _still_live(db, caller):
                await ws.close(code=WS_UNAUTHORISED)
                raise WebSocketDisconnect(WS_UNAUTHORISED)
            answer = await sync.apply(db, caller, kind, sync.check(kind, msg))
        except sync.SyncProblem as exc:
            await db.rollback()
            return {"type": "error", **exc.body()}
    return {"type": f"{kind}.ack", **answer}


async def _still_live(db: Any, caller: sync.Caller) -> bool:
    key = await db.get(FieldApiKey, caller.key_id)
    return key is not None and key.revoked_at is None
