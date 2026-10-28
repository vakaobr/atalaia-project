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
    GET  /api/v1/sync/chrono?scheduled_game_id= other fields' chrono records of that roster's players, only
                               with the person's consent for both fields (S14-5)
    GET  /api/v1/sync/claims                   accounts' claims of player ids, waiting for this field's verdict
    GET  /api/v1/sync/field                    the field's branding and saved teams, images by SHA-256 (plan phase 18);
                               with ?settings=1 also its check-in settings and limit template (BR24)
    GET  /api/v1/sync/images/{sha256}          one of those images, as stored (checked, metadata stripped)
    GET  /api/v1/sync/presets                  the field's scenario library (id, revision, SHA-256) and game
                                               presets (plan phase 20), the same for every controller of the field
    GET  /api/v1/sync/scenarios/{scenario_id}  one scenario's current manifest
    WS   /api/v1/sync/stream   the POST bodies on one socket the controller keeps open; with the
                               controller's [sync] remote_gm on, also its hello, live view and
                               command results, and the remote GM's commands the other way (plan phase 19);
                               with its [atak] remote on, its CoT events for the remote ATAK relay
                               (``cot``, Phase 4 follow-up FU5, ``atak_relay.py``); to every controller
                               connected, a ``field.changed`` note when the field's branding, saved teams or
                               settings change (BR24; ``services/branding.announce``)

The controller opens every connection (P4R12); nothing here connects to it.
Bodies are checked by ``atalaia_controller.sync_format``, the code the
controller's client uses (plain Python, no pydantic), and stored by
``atalaia_server.sync``. Every request with a valid key marks the key used and
the controller seen.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from atalaia_controller import sync_format
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from .. import chrono_registry, quotas, remote_gm, sync, tenancy, tenant_watch
from ..audit import record
from ..auth import UNAUTHORISED, bearer
from ..models import FieldApiKey
from ..services import branding, library, registration

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
            await _quota_note(request.app.state, exc)
            return JSONResponse(exc.body(), status_code=exc.status, headers=NO_STORE)
    return JSONResponse(answer, headers=NO_STORE)


async def _quota_note(state: Any, exc: sync.SyncProblem) -> None:
    """A refusal for a quota is left as a note for the hub operator (``quotas.report``)."""
    if exc.detail == quotas.CODE and exc.extra:
        await quotas.report(state, str(exc.extra["quota"]), int(exc.extra["limit"]))


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
        # FU7-6: when this key's controller last pulled the game's roster (the staff roster page shows it).
        await registration.record_roster_pull(db, caller.key_id, wanted, datetime.now(timezone.utc),
                                              request.headers.get("user-agent"))
        return answer
    return await _pull(request, build)


@router.get("/chrono")
async def shared_chrono(request: Request) -> JSONResponse:
    try:
        wanted = uuid.UUID(request.query_params.get("scheduled_game_id", ""))
    except ValueError:
        return JSONResponse({"detail": "invalid_query", "error": "not_a_uuid", "path": "scheduled_game_id"},
                            status_code=400, headers=NO_STORE)

    async def build(db: Any, caller: sync.Caller) -> Any:
        players = await registration.roster_players(db, caller.field_id, wanted)
        if players is None:
            raise sync.SyncProblem(404, "scheduled_game_not_found")
        found = await chrono_registry.shared_for_players(db, caller.field_id, players)
        if found:
            # As the staff's lookup is logged: that a controller pulled and how much, not whose.
            record(db, "chrono_shared_pull", request, resource="field", resource_id=caller.field_id,
                   details={"players": len(found), "readings": sum(len(p["readings"]) for p in found)})
        return {"sync_version": sync_format.SYNC_VERSION, "scheduled_game_id": str(wanted), "players": found}
    return await _pull(request, build)


@router.get("/claims")
async def pending_claims(request: Request) -> JSONResponse:
    async def build(db: Any, caller: sync.Caller) -> Any:
        return await registration.pending_claims(db, caller.field_id)
    return await _pull(request, build)


@router.get("/field")
async def field_branding(request: Request) -> JSONResponse:
    """The field's branding and saved teams; with ``?settings=1`` (a controller of BR24 onwards; an older one
    does not send it and gets the old shape, which it checks strictly) also its check-in settings."""
    settings = request.query_params.get("settings") == "1"

    async def build(db: Any, caller: sync.Caller) -> Any:
        return await branding.field_answer(db, caller.field_id, settings=settings)
    return await _pull(request, build)


@router.get("/images/{sha256}")
async def field_image(sha256: str, request: Request) -> Response:
    """An image the field's branding or saved teams use, by its SHA-256 (immutable: cached for a year)."""
    async with request.app.state.sessionmaker() as db:
        caller = await sync.authenticate(db, bearer(request))
        if caller is None:
            return JSONResponse({"detail": "invalid_api_key"}, status_code=401, headers=UNAUTHORISED)
        image = await branding.field_image(db, caller.field_id, sha256)
        await db.commit()  # the key's last use
        if image is None:
            return JSONResponse({"detail": "image_not_found"}, status_code=404, headers=NO_STORE)
        return Response(image.data, media_type=image.content_type, headers={
            "ETag": f'"{image.sha256}"', "Cache-Control": "private, max-age=31536000, immutable",
            "Content-Disposition": "inline"})


@router.get("/presets")
async def library_presets(request: Request) -> JSONResponse:
    async def build(db: Any, caller: sync.Caller) -> Any:
        return await library.sync_answer(db, caller.field_id)
    return await _pull(request, build)


@router.get("/scenarios/{scenario_id}")
async def library_scenario(scenario_id: str, request: Request) -> JSONResponse:
    async def build(db: Any, caller: sync.Caller) -> Any:
        answer = await library.sync_scenario(db, caller.field_id, scenario_id)
        if answer is None:
            raise sync.SyncProblem(404, "scenario_not_found")
        return answer
    return await _pull(request, build)


# The remote GM's messages from the controller (plan phase 19) and its CoT for the remote ATAK relay (FU5);
# ``command`` goes the other way only.
STREAM_IN = ("hello", "live", "command.result", "cot", "positions")


class _Session:
    """One socket's state: its sends serialised (a remote command is sent from another request's task)
    and, after ``hello``, its remote GM link."""

    def __init__(self, ws: WebSocket, caller: sync.Caller) -> None:
        self.ws = ws
        self.caller = caller
        self.lock = asyncio.Lock()
        self.link: Optional[remote_gm.Link] = None
        self.rx: Optional[asyncio.Future[str]] = None  # the pending receive (see _receive)
        self.closed = asyncio.Event()  # set when the server closes the socket (a deleted or suspended field)

    async def send(self, msg: dict[str, Any]) -> None:
        async with self.lock:
            await self.ws.send_json(msg)

    async def release(self) -> None:
        """Ends the pending receive, if any, and waits for it so no cancellation or error is left over."""
        rx, self.rx = self.rx, None
        if rx is not None:
            if not rx.done():
                rx.cancel()
            await asyncio.gather(rx, return_exceptions=True)

    async def close(self, code: int) -> None:
        """Closes the socket from outside its own handler (tenant_watch.py) and wakes the handler."""
        self.closed.set()
        try:
            await self.ws.close(code=code)
        except RuntimeError:  # already closed
            pass


async def _receive(session: _Session) -> Optional[str]:
    """The next text message, or None when the server closed the socket meanwhile. One receive task lives
    as long as a message is awaited and is kept across calls (never cancelled mid-wait, which could lose
    a message or leak a cancellation into the transport); ``session.release()`` ends it."""
    if session.closed.is_set():
        return None
    if session.rx is None:
        session.rx = asyncio.ensure_future(session.ws.receive_text())
    closed = asyncio.ensure_future(session.closed.wait())
    try:
        await asyncio.wait({session.rx, closed}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        closed.cancel()
    if session.rx.done():
        rx, session.rx = session.rx, None
        return rx.result()
    return None


@router.websocket("/stream")
async def stream(ws: WebSocket) -> None:
    """One socket per controller: ``{"type": kind, ...body}`` in, ``{"type": kind + ".ack", ...}`` out;
    the remote GM's ``hello``, ``live`` and ``command.result`` in (only ``hello`` is answered), its
    ``command`` out. Closed by the server with 4401 (no valid key), 4429 (the field's stream quota, hosted
    mode) and, in hosted mode, 4404 or 4403 when the field is deleted or suspended while it is open."""
    scheme, _, value = ws.headers.get("authorization", "").partition(" ")
    key = value.strip() if scheme.lower() == "bearer" else None
    async with ws.app.state.sessionmaker() as db:
        caller = await sync.authenticate(db, key)
        await db.commit()
    if caller is None:
        await ws.close(code=WS_UNAUTHORISED)
        return
    watch: tenant_watch.TenantWatch = ws.app.state.tenant_watch
    tenant = tenancy.current()
    if tenant is not None and quotas.streams_full(watch.count(tenant.schema, caller.field_id)):
        await quotas.report(ws.app.state, "streams", quotas.limit("streams"))
        await ws.close(code=quotas.STREAM_CLOSE)
        return
    session = _Session(ws, caller)
    # Counted before the accept: no await between the quota's check and the registration.
    watched = watch.add(tenant, caller.field_id, session.close) if tenant is not None else None
    hub: remote_gm.RemoteHub = ws.app.state.remote_hub
    try:
        await ws.accept()
        while True:
            raw = await _receive(session)
            if raw is None:
                return
            answer = await _message(ws, caller, raw, session)
            if answer is not None:
                await session.send(answer)
    except WebSocketDisconnect:
        return
    finally:
        await session.release()
        if watched is not None:
            watch.remove(watched)
        if session.link is not None:
            hub.detach(session.link)


async def _message(ws: WebSocket, caller: sync.Caller, raw: str,
                   session: Optional[_Session] = None) -> Optional[dict[str, Any]]:
    """One message's answer, or None (a ``live`` or ``command.result`` gets none). Without a ``session`` (no
    socket of its own) only the sync bodies and ``ping`` are taken."""
    if len(raw.encode("utf-8")) > sync_format.MAX_BODY:
        return {"type": "error", "detail": "body_too_large"}
    try:
        msg = json.loads(raw)
    except ValueError:
        return {"type": "error", **sync.SyncProblem(400, "invalid_body", "not_json", "").body()}
    if not isinstance(msg, dict) or msg.get("type") not in (*sync_format.CHECKS, *STREAM_IN, "ping"):
        return {"type": "error", **sync.SyncProblem(400, "invalid_body", "bad_type", "type").body()}
    kind = msg.pop("type")
    if kind == "ping":
        return {"type": "pong"}
    async with ws.app.state.sessionmaker() as db:
        try:
            # The key may have been revoked since the socket opened.
            if not await _still_live(db, caller):
                if session is not None and session.link is not None:
                    ws.app.state.remote_hub.detach(session.link)
                    session.link = None
                await ws.close(code=WS_UNAUTHORISED)
                raise WebSocketDisconnect(WS_UNAUTHORISED)
            if kind in STREAM_IN:
                if session is None:
                    raise sync.SyncProblem(400, "invalid_body", "bad_type", "type")
                return await _remote(session, db, kind, msg)
            answer = await sync.apply(db, caller, kind, sync.check(kind, msg))
        except sync.SyncProblem as exc:
            await db.rollback()
            await _quota_note(ws.app.state, exc)
            return {"type": "error", **exc.body()}
    return {"type": f"{kind}.ack", **answer}


async def _remote(session: _Session, db: Any, kind: str, msg: dict[str, Any]) -> Optional[dict[str, Any]]:
    """The remote GM's messages (plan phase 19): ``hello`` registers the link (and is answered), ``live``
    replaces its live view, ``positions`` the players' positions it relays to the remote GM page (PKD-5),
    ``command.result`` answers a waiting command, ``cot`` goes to the remote ATAK relay (FU5); the last four get
    no answer."""
    try:
        body = sync_format.STREAM[kind](msg)
    except sync_format.SyncFormatError as exc:
        raise sync.SyncProblem(400, "invalid_body", exc.code, exc.path) from None
    hub: remote_gm.RemoteHub = session.ws.app.state.remote_hub
    relay = session.ws.app.state.atak_relay
    if kind == "hello":
        await sync.seen(db, session.caller, body)
        await db.commit()
        if session.link is not None:
            hub.detach(session.link)
        session.link = remote_gm.Link(
            field_id=session.caller.field_id, key_id=session.caller.key_id, controller_id=body["controller"]["id"],
            controller_row=session.caller.controller, version=body["controller"]["version"],
            remote_gm=body["remote_gm"], send=session.send, atak=bool(body["atak"] and relay is not None))
        hub.attach(session.link)
        return {"type": "hello.ack", "remote_gm": body["remote_gm"], "atak_relay": session.link.atak}
    link = session.link
    if link is None:
        raise sync.SyncProblem(409, "hello_first")
    if body["controller"]["id"] != link.controller_id:
        raise sync.SyncProblem(400, "invalid_body", "not_this_controller", "controller.id")
    if kind == "live":
        hub.set_live(link, body["live"])
    elif kind == "positions":
        hub.set_positions(link, body)  # relayed in memory to the field's remote GM page: never stored, never logged
    elif kind == "cot":
        if link.atak and relay is not None:  # else dropped: the hello.ack said the relay does not take them
            # At most ``atak_cot`` messages a minute per field, whatever its streams (FU5-15).
            if session.ws.app.state.limits.atak_cot.hit(f"{tenancy.current_schema()}:{session.caller.field_id}"):
                raise sync.SyncProblem(429, "too_many_requests")
            relay.publish(session.caller.field_id, [sync_format.cot_event(e) for e in body["events"]])
    else:
        hub.result(link, body)
    return None


async def _still_live(db: Any, caller: sync.Caller) -> bool:
    key = await db.get(FieldApiKey, caller.key_id)
    return key is not None and key.revoked_at is None
