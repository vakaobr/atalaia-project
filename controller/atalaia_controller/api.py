# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""REST and WebSocket API v1 (spec section 11), served by FastAPI.

Reading needs the read token or the GM token; anything that changes a game
or a node needs the GM token (spec section 11: "Publishing commands needs a
GM token"). Tokens go in ``Authorization: Bearer <token>``; the WebSocket,
which browsers cannot give headers, also takes ``?token=``.

    GET  /api/v1/whoami                    which token this is: gm or read
    GET  /api/v1/nodes                     nodes, capabilities, health (live game, or ?game=)
    GET  /api/v1/modes                     installed mode packages and their parameters
    POST /api/v1/modes                     upload a mode package {"files": {name: text}}
    GET  /api/v1/presets                   saved presets
    POST /api/v1/presets                   save a preset {"name", "mode_id", "params"}
    GET  /api/v1/games                     every game
    POST /api/v1/games                     create a game from a mode or preset
    GET  /api/v1/games/{id}                one game
    POST /api/v1/games/{id}/start|pause|resume|end
    GET  /api/v1/games/{id}/score          current totals
    POST /api/v1/games/{id}/score          GM adjustment, logged as score.delta
    POST /api/v1/nodes/{id}/cmd            a command to one node (65535: all)
    GET  /api/v1/games/{id}/log            the merged event log
    WS   /api/v1/stream                    live events, scores, nodes and alerts
    GET  /api/v1/controller                controller and radio status
    POST /api/v1/controller/promote        manual failover: stand for election
    POST /api/v1/join                      a join payload for a box or a standby controller
    POST /api/v1/nodes/{id}/join           the same, for node id {id}
    POST /api/v1/controller/join           this controller takes a game as standby
    GET  /api/v1/field                     whether a field image is uploaded
    GET|PUT|DELETE /api/v1/field/image     the field image (map or floor plan) of the console
    GET  /api/v1/games/{id}/positions      where the nodes are on the field image
    PUT  /api/v1/games/{id}/positions/{n}  move a node on it
    GET  /healthz                          liveness, no token
    GET  /console/                         the GM console (static files, no token)
    GET  /scoreboard                       the read-only scoreboard page (/console/scoreboard.html)

Join answers carry the game key inside the payload: GM token only, never cached.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import math
from pathlib import Path
from typing import Any, Callable, Optional

from atalaia_sim.mode import ModeError
from fastapi import Body, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__
from .engine import Controller, ControllerError
from .modes import resolve_params
from .store import FIELD_IMAGE_MAX
from .ws import Hub

CONSOLE_DIR = Path(__file__).resolve().parent.parent / "console" / "src"
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
NO_STORE = {"Cache-Control": "no-store"}


class Auth:
    def __init__(self, gm_token: str, read_token: str) -> None:
        if not gm_token or not read_token:
            raise ValueError("both tokens must be set")
        self.gm_token = gm_token
        self.read_token = read_token

    def role(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        if hmac.compare_digest(token.encode(), self.gm_token.encode()):
            return "gm"
        if hmac.compare_digest(token.encode(), self.read_token.encode()):
            return "read"
        return None


def _token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def create_app(controller: Controller, hub: Hub, auth: Auth,
               on_start: Optional[Callable[[], None]] = None,
               on_stop: Optional[Callable[[], None]] = None) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if on_start:
            on_start()
        try:
            yield
        finally:
            if on_stop:
                on_stop()

    app = FastAPI(title="Atalaia field controller", version=__version__, lifespan=lifespan)
    controller.add_listener(hub.publish)

    def require_read(request: Request) -> str:
        role = auth.role(_token(request))
        if role is None:
            raise HTTPException(401, "a read or GM token is needed", {"WWW-Authenticate": "Bearer"})
        return role

    def require_gm(request: Request) -> str:
        role = auth.role(_token(request))
        if role is None:
            raise HTTPException(401, "the GM token is needed", {"WWW-Authenticate": "Bearer"})
        if role != "gm":
            raise HTTPException(403, "the read token cannot change the game; use the GM token")
        return role

    @app.exception_handler(ControllerError)
    async def controller_error(request: Request, exc: ControllerError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    @app.exception_handler(ModeError)
    async def mode_error(request: Request, exc: ModeError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    def body_map(body: Any) -> dict[str, Any]:
        if body is None:
            return {}
        if not isinstance(body, dict):
            raise ControllerError("the request body must be a JSON object")
        return body

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"ok": True, "version": __version__, "radio": controller.radio_state}

    @app.get("/api/v1/whoami")
    def whoami(role: str = Depends(require_read)) -> dict[str, Any]:
        """Which token this is ("gm" or "read"): the console hides GM controls for "read"."""
        return {"role": role, "version": __version__}

    @app.get("/api/v1/nodes", dependencies=[Depends(require_read)])
    def nodes(game: Optional[int] = None) -> list[dict[str, Any]]:
        return controller.nodes(game)

    @app.get("/api/v1/modes", dependencies=[Depends(require_read)])
    def modes() -> list[dict[str, Any]]:
        return [m.to_api() for m in controller.modes.all()]

    @app.post("/api/v1/modes", status_code=201, dependencies=[Depends(require_gm)])
    def upload_mode(body: Any = Body(None)) -> dict[str, Any]:
        files = body_map(body).get("files")
        return controller.modes.install(files).to_api()

    @app.get("/api/v1/presets", dependencies=[Depends(require_read)])
    def presets() -> list[dict[str, Any]]:
        return controller.store.presets()

    @app.post("/api/v1/presets", status_code=201, dependencies=[Depends(require_gm)])
    def save_preset(body: Any = Body(None)) -> dict[str, Any]:
        spec = body_map(body)
        name = spec.get("name")
        if not isinstance(name, str) or not 1 <= len(name) <= 64:
            raise ControllerError("name: 1 to 64 characters")
        pkg = controller.modes.get(spec.get("mode_id")) if isinstance(spec.get("mode_id"), str) else None
        if pkg is None:
            raise ControllerError(f"unknown mode {spec.get('mode_id')!r}")
        params = spec.get("params", {})
        resolve_params(pkg.mode, params, None)  # raises ModeError -> 400
        return controller.store.save_preset(name, pkg.id, params)

    @app.get("/api/v1/games", dependencies=[Depends(require_read)])
    def games() -> list[dict[str, Any]]:
        return controller.list_games()

    @app.post("/api/v1/games", status_code=201, dependencies=[Depends(require_gm)])
    def create_game(body: Any = Body(None)) -> dict[str, Any]:
        return controller.create_game(body_map(body))

    @app.get("/api/v1/games/{game_id}", dependencies=[Depends(require_read)])
    def game(game_id: int) -> dict[str, Any]:
        return controller.get_game(game_id)

    @app.post("/api/v1/games/{game_id}/start", dependencies=[Depends(require_gm)])
    def start(game_id: int) -> dict[str, Any]:
        return controller.start_game(game_id)

    @app.post("/api/v1/games/{game_id}/pause", dependencies=[Depends(require_gm)])
    def pause(game_id: int, body: Any = Body(None)) -> dict[str, Any]:
        return controller.pause_game(game_id, _reason(body_map(body)))

    @app.post("/api/v1/games/{game_id}/resume", dependencies=[Depends(require_gm)])
    def resume(game_id: int) -> dict[str, Any]:
        return controller.resume_game(game_id)

    @app.post("/api/v1/games/{game_id}/end", dependencies=[Depends(require_gm)])
    def end(game_id: int, body: Any = Body(None)) -> dict[str, Any]:
        return controller.end_game(game_id, _reason(body_map(body)))

    @app.get("/api/v1/games/{game_id}/score", dependencies=[Depends(require_read)])
    def score(game_id: int) -> dict[str, Any]:
        return controller.score(game_id)

    @app.post("/api/v1/games/{game_id}/score", dependencies=[Depends(require_gm)])
    def adjust(game_id: int, body: Any = Body(None)) -> dict[str, Any]:
        spec = body_map(body)
        return controller.adjust_score(game_id, spec.get("team"), spec.get("amount"),
                                       spec.get("reason", ""))

    @app.post("/api/v1/nodes/{node_id}/cmd", status_code=202, dependencies=[Depends(require_gm)])
    def node_cmd(node_id: int, body: Any = Body(None)) -> dict[str, Any]:
        spec = body_map(body)
        return controller.send_node_cmd(node_id, spec.get("cmd"), spec.get("params"))

    @app.get("/api/v1/games/{game_id}/log", dependencies=[Depends(require_read)])
    def game_log(game_id: int, since_ms: Optional[int] = None) -> list[dict[str, Any]]:
        return controller.log(game_id, since_ms)

    @app.get("/api/v1/controller", dependencies=[Depends(require_read)])
    def status() -> dict[str, Any]:
        return controller.status()

    @app.post("/api/v1/controller/promote", dependencies=[Depends(require_gm)])
    def promote() -> dict[str, Any]:
        return controller.promote()

    # --- join flow (ADR-P2-12, protocol/join.md) ------------------------------

    @app.post("/api/v1/join", dependencies=[Depends(require_gm)])
    def join(body: Any = Body(None)) -> JSONResponse:
        return JSONResponse(controller.issue_join(body_map(body)), headers=NO_STORE)

    @app.post("/api/v1/nodes/{node_id}/join", dependencies=[Depends(require_gm)])
    def join_node(node_id: int, body: Any = Body(None)) -> JSONResponse:
        return JSONResponse(controller.issue_join(body_map(body), node_id=node_id), headers=NO_STORE)

    @app.post("/api/v1/controller/join", status_code=201, dependencies=[Depends(require_gm)])
    def join_standby(body: Any = Body(None)) -> dict[str, Any]:
        return controller.join_as_standby(body_map(body).get("text"))

    # --- field image and node positions (console field view) ------------------

    @app.get("/api/v1/field", dependencies=[Depends(require_read)])
    def field_info() -> dict[str, Any]:
        """Whether a field image is uploaded (the console asks before fetching it)."""
        image = controller.store.field_image()
        if image is None:
            return {"image": None}
        return {"image": {"content_type": image[0], "bytes": len(image[1]), "updated_at": image[2]}}

    @app.get("/api/v1/field/image", dependencies=[Depends(require_read)])
    def field_image() -> Response:
        image = controller.store.field_image()
        if image is None:
            raise HTTPException(404, "no field image uploaded")
        return Response(image[1], media_type=image[0], headers=NO_STORE)

    @app.put("/api/v1/field/image", dependencies=[Depends(require_gm)])
    async def put_field_image(request: Request) -> dict[str, Any]:
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype not in IMAGE_TYPES:
            raise HTTPException(415, f"the field image must be one of {sorted(IMAGE_TYPES)}")
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > FIELD_IMAGE_MAX:
            raise HTTPException(413, f"the field image is over {FIELD_IMAGE_MAX} bytes")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > FIELD_IMAGE_MAX:
                raise HTTPException(413, f"the field image is over {FIELD_IMAGE_MAX} bytes")
        if not data:
            raise HTTPException(400, "empty image")
        controller.store.set_field_image(ctype, bytes(data))
        controller._emit({"type": "field_image"})
        return {"content_type": ctype, "bytes": len(data)}

    @app.delete("/api/v1/field/image", dependencies=[Depends(require_gm)])
    def delete_field_image() -> dict[str, Any]:
        deleted = controller.store.delete_field_image()
        if deleted:
            controller._emit({"type": "field_image"})
        return {"deleted": deleted}

    @app.get("/api/v1/games/{game_id}/positions", dependencies=[Depends(require_read)])
    def positions(game_id: int) -> dict[str, Any]:
        controller.get_game(game_id)  # 404 for an unknown game
        return {str(k): v for k, v in controller.store.positions(game_id).items()}

    @app.put("/api/v1/games/{game_id}/positions/{node_id}", dependencies=[Depends(require_gm)])
    def put_position(game_id: int, node_id: int, body: Any = Body(None)) -> dict[str, Any]:
        controller.get_game(game_id)
        spec = body_map(body)
        if not 0 <= node_id <= 0xFFFE:
            raise ControllerError("node id: 0-65534")
        xy = []
        for name in ("x", "y"):
            v = spec.get(name)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) \
                    or not 0.0 <= v <= 1.0:
                raise ControllerError(f"{name}: a number from 0 to 1 (fraction of the image)")
            xy.append(float(v))
        controller.store.set_position(game_id, node_id, xy[0], xy[1])
        msg = {"type": "position", "game": game_id, "node_id": node_id, "x": xy[0], "y": xy[1]}
        controller._emit(msg)
        return msg

    # --- the GM console and the scoreboard: static files, no build step -------

    if CONSOLE_DIR.is_dir():
        @app.get("/", include_in_schema=False)
        def root() -> RedirectResponse:
            return RedirectResponse("/console/")

        @app.get("/console", include_in_schema=False)
        def console_slash() -> RedirectResponse:
            return RedirectResponse("/console/")

        @app.get("/scoreboard", include_in_schema=False)
        def scoreboard() -> RedirectResponse:
            return RedirectResponse("/console/scoreboard.html")

        app.mount("/console", StaticFiles(directory=CONSOLE_DIR, html=True), name="console")

        @app.middleware("http")
        async def security_headers(request: Request, call_next):
            response = await call_next(request)
            if request.url.path.startswith("/console"):
                for k, v in SECURITY_HEADERS.items():
                    response.headers.setdefault(k, v)
            return response

    @app.websocket("/api/v1/stream")
    async def stream(ws: WebSocket) -> None:
        token = ws.query_params.get("token")
        header = ws.headers.get("authorization", "")
        if not token and header.lower().startswith("bearer "):
            token = header[7:].strip()
        if auth.role(token) is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        queue = hub.subscribe()
        try:
            await ws.send_json(_snapshot(controller))

            async def sender() -> None:
                while True:
                    msg = await queue.get()
                    if msg is None:
                        await ws.close(code=4408)  # too slow: reconnect for a fresh snapshot
                        return
                    await ws.send_json(msg)

            async def receiver() -> None:
                while True:
                    msg = await ws.receive_json()
                    if isinstance(msg, dict) and msg.get("type") == "ping":
                        await ws.send_json({"type": "pong"})

            tasks = [asyncio.ensure_future(sender()), asyncio.ensure_future(receiver())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            pass
        finally:
            hub.unsubscribe(queue)

    return app


# Same-origin only: no inline scripts or styles, nothing from other hosts
# (OpenStreetMap tiles are not used in phase 2), images from blob: URLs.
SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self'; "
                                "img-src 'self' blob: data:; connect-src 'self'; "
                                "manifest-src 'self'; worker-src 'self'; frame-ancestors 'none'; "
                                "base-uri 'none'; form-action 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def _reason(spec: dict[str, Any]) -> str:
    reason = spec.get("reason", "")
    if not isinstance(reason, str) or len(reason) > 64:
        raise ControllerError("reason: text up to 64 characters")
    return reason


def _snapshot(controller: Controller) -> dict[str, Any]:
    status = controller.status()
    game_id = status["live_game"]
    return {
        "type": "hello",
        "status": status,
        "game": controller.get_game(game_id) if game_id else None,
        "score": controller.score(game_id) if game_id else None,
        "nodes": controller.nodes(game_id) if game_id else [],
    }
