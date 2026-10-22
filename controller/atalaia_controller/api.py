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
    POST /api/v1/scenarios/check           a scenario manifest's problems {"manifest": text} (GM or read token)
    GET|POST /api/v1/scenarios             installed scenarios / GM: compile and install {"manifest": text}
    GET  /api/v1/scenarios/{id}            GM: its manifest and generated package (mode.yaml, field.lua)
    GET  /api/v1/presets                   saved presets
    POST /api/v1/presets                   save a preset {"name", "mode_id", "params"}
    GET  /api/v1/games                     every game
    POST /api/v1/games                     create a game from a mode or preset
    GET  /api/v1/games/{id}                one game
    POST /api/v1/games/{id}/start|pause|resume|end   (start: {"force": true} starts without a node for
                                           every role the game needs; refused with start_check otherwise)
    GET  /api/v1/games/{id}/start-check    the roles the game needs, those joined, missing, warnings
    GET  /api/v1/boxes                     GM: free boxes heard over the radio (protocol/field-frames.md)
    POST /api/v1/boxes/discover            GM: ask the free boxes to announce themselves now
    GET|POST /api/v1/games/{id}/invites    GM: invites into the live game / invite boxes
                                           {"boxes": [{"device_id", "role"?, "name"?}]}
    GET  /api/v1/games/{id}/score          current totals
    POST /api/v1/games/{id}/score          GM adjustment, logged as score.delta
    POST /api/v1/nodes/{id}/cmd            a command to one node (65535: all)
    GET  /api/v1/games/{id}/log            the merged event log
    WS   /api/v1/stream                    live events, scores, nodes and alerts
    GET  /api/v1/controller                controller and radio status
    POST /api/v1/controller/promote        manual failover: stand for election
    GET  /api/v1/remote-gm                 GM: the remote GM's state and log of commands (plan phase 19)
    POST /api/v1/join                      a join payload for a box or a standby controller
    POST /api/v1/nodes/{id}/join           the same, for node id {id} ({"name"}: a scenario's box)
    POST /api/v1/controller/join           this controller takes a game as standby
    GET  /api/v1/field                     whether a field image is uploaded
    GET|PUT|DELETE /api/v1/field/image     the field image (map or floor plan) of the console
    GET|PUT|DELETE /api/v1/field/georef    its georeference: 2-8 control points {x, y, lat, lon} (PUT, DELETE: GM)
    GET  /api/v1/atak                      the ATAK / CoT feed's settings and counters (GM or read token)
    GET  /api/v1/field/branding            the field's name, logo, wallpaper and accent (no token, ETag)
    PUT  /api/v1/field/branding            GM: {"field_name"?, "accent"?}
    GET|PUT|DELETE /api/v1/field/branding/{logo|wallpaper}  the images (GET: no token, ETag)
    POST /api/v1/crests                    GM: upload a team crest (raw PNG, JPEG or WebP)
    GET  /api/v1/crests/{id}               a crest (no token, immutable)
    GET|POST /api/v1/team-presets          saved teams: display name, colour, crest
    PUT|DELETE /api/v1/team-presets/{id}   GM
    GET  /api/v1/games/{id}/teams          a game's team colours, display names and crests (no token)
    PUT  /api/v1/games/{id}/teams/{team}   GM: {"display_name"?, "crest_id"?, "team_preset_id"?}
    GET|PUT /api/v1/settings/box-language  the boxes' screen language: "auto" (the console's), "pt", "en"
    GET  /api/v1/radio                     the field's radio channel, its limits, candidates, last scan
    PUT  /api/v1/radio/channel             set it {"channel_hz", "source"} (no live game)
    POST /api/v1/radio/scan                find a quiet channel: noise scan with the modem {"dwell_s"?}
    GET  /api/v1/radio/scan                the scan's progress and results
    DELETE /api/v1/radio/scan              cancel the scan
    POST /api/v1/radio/random              a random legal channel, as a suggestion
    GET  /api/v1/games/{id}/positions      where the nodes are on the field image
    PUT  /api/v1/games/{id}/positions/{n}  move a node on it
    GET  /api/v1/controller/ca             the field CA's certificate (PEM), no token (ADR-P3-9)
    GET|POST /api/v1/firmware              GM: firmware releases and updates / upload a signed release
                                           (raw image; ?platform=&version=&signature=)
    DELETE /api/v1/firmware/{id}           GM: delete a release
    POST /api/v1/firmware/{id}/install     GM: update boxes of the live game before it starts {"nodes": [..] | "all"}
    DELETE /api/v1/firmware/updates        GM: stop tracking the updates on their way
    GET  /api/v1/firmware/{id}/release     a box: the signed release text, no token (protocol/firmware-update.md)
    GET  /api/v1/firmware/{id}/image       a box: the image, no token
    POST /api/v1/firmware/report           a box: how its update went, with the game key's MAC
    GET  /api/v1/adopt                     GM: the field's fingerprint and name, the adoption records
    POST /api/v1/adopt/card                GM: the NFC field card's bytes (the field join key; protocol/adoption.md)
    POST /api/v1/adopt/usb/scan            GM: the Field Boxes plugged into this controller by USB
    POST /api/v1/adopt/usb                 GM: adopt one {"port", "mac" (as confirmed), "pin"?}
    GET  /api/v1/adopt/pair                GM: boxes offering a pairing code over the radio, the run
    POST /api/v1/adopt/pair/listen         GM: keep the modem on 869.525 MHz for 5 minutes (no live game)
    POST /api/v1/adopt/pair                GM: pair {"pair_id", "code"} (CPace with the box's code)
    GET  /api/v1/checkin                   field check-in: field, notice, settings, open games (no token)
    POST /api/v1/checkin                   check in with a field identity: a player token
    POST /api/v1/checkin/token             a new player token (player token)
    GET|DELETE /api/v1/checkin/me          the player's own check-in / leave the game
    PUT  /api/v1/checkin/me/replicas       the player's declaration (replicas for this game)
    PUT  /api/v1/checkin/me/marshal-key    a marshal registers the Ed25519 key that signs readings
    GET|POST /api/v1/games/{id}/checkins   staff: the list with names / a manual check-in
    GET  /api/v1/games/{id}/checkins.csv   GM: the list as CSV
    PATCH|DELETE /api/v1/games/{id}/checkins/{player}  staff changes / GM removal
    GET  /api/v1/games/{id}/chrono-list    staff: the "replicas to chrono" list
    POST /api/v1/games/{id}/checkin/open|close  GM
    POST /api/v1/chrono/readings           a marshal's signed series of readings
    GET|POST /api/v1/marshals              GM: marshals' public keys
    GET|PUT /api/v1/checkin/settings       GM: confirm, federation, limits
    GET|PUT /api/v1/checkin/poster         GM: the check-in poster's text and fields
    POST /api/v1/games/{id}/checkins/ticket  staff: a registered player's printed ticket, scanned
    GET  /api/v1/schedule                  the site server's schedule as last pulled (plan phase 16)
    POST /api/v1/schedule/{id}/game        GM: a game made from a scheduled game, linked to it
    GET|DELETE /api/v1/players/{player}    GM (or the player): their data / erase it (?chrono=1: readings too)
    GET|POST /api/v1/positions             player positions: the ones the caller may see / report (player token)
    WS   /api/v1/prop                      an Android prop's Wi-Fi link (prop_link.py)
    GET  /healthz                          liveness, no token
    GET  /console/                         the GM console (static files, no token)
    GET  /scoreboard                       the read-only scoreboard page (/console/scoreboard.html)

Join answers carry the game key inside the payload: GM token only, never cached.

Player tokens (protocol/player-token.md, issued at check-in) read what the
read token reads about games, and their own check-in; their role, team and
squad are checked against the check-in on every request (checkin.py). They
cannot read modes, presets, the controller's or the radio's state.
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
from . import checkin as checkinmod
from . import schedule as schedulemod
from . import georef as georefmod
from . import images, visibility
from . import scenario_service as scenarios
from .branding import SLOTS, Branding, etag
from .checkin import Viewer
from .engine import Controller, ControllerError, StartBlocked
from .modes import resolve_params
from .store import FIELD_IMAGE_MAX
from .ws import PLAYER_TYPES, Hub, default_route, public

CONSOLE_DIR = Path(__file__).resolve().parent.parent / "console" / "src"
IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}
NO_STORE = {"Cache-Control": "no-store"}
# Served images: never sniffed as anything else, and inert if opened as a page (decision BR9).
IMAGE_HEADERS = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "default-src 'none'; sandbox",
                 "Content-Disposition": "inline"}


class Auth:
    def __init__(self, gm_token: str, read_token: str) -> None:
        if not gm_token or not read_token:
            raise ValueError("both tokens must be set")
        self.gm_token = gm_token
        self.read_token = read_token
        self.checkin: Optional[checkinmod.Checkin] = None  # set by create_app

    def role(self, token: Optional[str]) -> Optional[str]:
        if not token:
            return None
        if hmac.compare_digest(token.encode(), self.gm_token.encode()):
            return "gm"
        if hmac.compare_digest(token.encode(), self.read_token.encode()):
            return "read"
        return None

    def viewer(self, token: Optional[str]) -> Optional[Viewer]:
        """Who a token is: the GM or read token, or a valid player token (None: refused)."""
        role = self.role(token)
        if role is not None:
            return Viewer(role)
        if token and token.startswith("apt") and self.checkin is not None:
            try:
                return self.checkin.resolve(token)
            except checkinmod.Unauthorized:
                return None
        return None


def _token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


def create_app(controller: Controller, hub: Hub, auth: Auth,
               on_start: Optional[Callable[[], None]] = None,
               on_stop: Optional[Callable[[], None]] = None,
               ca_pem: Optional[bytes] = None) -> FastAPI:
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
    checkin = controller.checkin
    players = controller.positions  # player positions (positions.py)
    auth.checkin = checkin
    if hub.route is default_route:
        hub.route = make_route(controller)  # who gets what, gm_only data included (M5-1)
    controller.add_listener(hub.publish)
    branding = controller.branding if controller.branding is not None else Branding(controller)

    def viewer(request: Request) -> Viewer:
        v = auth.viewer(_token(request))
        if v is None:
            raise HTTPException(401, "a GM, read or player token is needed", {"WWW-Authenticate": "Bearer"})
        return v

    def require_read(request: Request) -> Viewer:
        """The GM, read or a player token: the game's public data."""
        return viewer(request)

    def require_console(request: Request) -> str:
        """The GM or read token (the console's views of the controller itself)."""
        role = auth.role(_token(request))
        if role is None:
            raise HTTPException(401, "a read or GM token is needed", {"WWW-Authenticate": "Bearer"})
        return role

    def require_player(request: Request) -> Viewer:
        v = viewer(request)
        if v.kind != "player":
            raise HTTPException(403, "this needs a player token (check in first)")
        return v

    def need_checkin() -> checkinmod.Checkin:
        if checkin is None:
            raise HTTPException(503, "field check-in is not set up on this controller")
        return checkin

    def client_of(request: Request) -> str:
        return request.client.host if request.client else "?"

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

    @app.exception_handler(StartBlocked)
    async def start_blocked(request: Request, exc: StartBlocked):
        # The console shows the missing roles and offers "Start anyway" (decision RJ-1).
        return JSONResponse({"detail": str(exc), "start_check": exc.check}, status_code=exc.status)

    @app.exception_handler(checkinmod.Refused)
    async def refused(request: Request, exc: checkinmod.Refused):
        return JSONResponse({"detail": str(exc), "reasons": exc.reasons}, status_code=exc.status)

    @app.exception_handler(ModeError)
    async def mode_error(request: Request, exc: ModeError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(scenarios.Refused)
    async def scenario_refused(request: Request, exc: scenarios.Refused):
        return JSONResponse({"detail": str(exc), "problems": [p.to_dict() for p in exc.problems]},
                            status_code=exc.status)

    @app.exception_handler(images.ImageError)
    async def image_error(request: Request, exc: images.ImageError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

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
    def whoami(v: Viewer = Depends(require_read)) -> dict[str, Any]:
        """Which token this is ("gm", "read" or "player"): the console hides GM controls for "read"."""
        out: dict[str, Any] = {"role": v.kind, "version": __version__}
        if v.kind == "player":
            out.update({"player_role": v.role, "player_id": v.player_id, "game_id": v.game_id,
                        "team": v.team, "squad": v.squad, "stale": v.stale})
        return out

    @app.get("/api/v1/nodes", dependencies=[Depends(require_read)])
    def nodes(game: Optional[int] = None) -> list[dict[str, Any]]:
        return controller.nodes(game)

    @app.get("/api/v1/modes", dependencies=[Depends(require_console)])
    def modes() -> list[dict[str, Any]]:
        return [m.to_api() for m in controller.modes.all()]

    @app.post("/api/v1/modes", status_code=201, dependencies=[Depends(require_gm)])
    def upload_mode(body: Any = Body(None)) -> dict[str, Any]:
        files = body_map(body).get("files")
        return controller.modes.install(files).to_api()

    # --- scenarios (plan phase 8, scenario_service.py) ----------------------------------

    @app.post("/api/v1/scenarios/check", dependencies=[Depends(require_console)])
    def scenario_check(body: Any = Body(None)) -> dict[str, Any]:
        return scenarios.check(controller, scenarios.manifest_text(body))

    @app.get("/api/v1/scenarios", dependencies=[Depends(require_console)])
    def scenario_list() -> list[dict[str, Any]]:
        return scenarios.listing(controller)

    @app.post("/api/v1/scenarios", status_code=201, dependencies=[Depends(require_gm)])
    def scenario_install(body: Any = Body(None)) -> dict[str, Any]:
        out = scenarios.install(controller, scenarios.manifest_text(body))
        controller._emit({"type": "modes"})
        return out

    @app.get("/api/v1/scenarios/{scenario_id}", dependencies=[Depends(require_gm)])
    def scenario_read(scenario_id: str) -> JSONResponse:
        return JSONResponse(scenarios.read(controller, scenario_id), headers=NO_STORE)

    @app.get("/api/v1/presets")
    def presets(role: str = Depends(require_console)) -> list[dict[str, Any]]:
        out = controller.store.presets()
        if role == "gm":
            return out
        # The read token's console: without the gm_only parameters (decision M5-1).
        return [{**p, "params": visibility.public_params(_mode_of(controller, p.get("mode_id")),
                                                         p.get("params"))} for p in out]

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

    @app.get("/api/v1/games")
    def games(v: Viewer = Depends(require_read)) -> list[dict[str, Any]]:
        return [g if visibility.is_staff(v, g["id"]) else controller.players_game(g, v)
                for g in controller.list_games()]

    @app.post("/api/v1/games", status_code=201, dependencies=[Depends(require_gm)])
    def create_game(body: Any = Body(None)) -> dict[str, Any]:
        return controller.create_game(body_map(body))

    @app.get("/api/v1/games/{game_id}")
    def game(game_id: int, v: Viewer = Depends(require_read)) -> dict[str, Any]:
        out = controller.get_game(game_id)
        return out if visibility.is_staff(v, game_id) else controller.players_game(out, v)

    @app.post("/api/v1/games/{game_id}/start", dependencies=[Depends(require_gm)])
    def start(game_id: int, body: Any = Body(None)) -> dict[str, Any]:
        force = body_map(body).get("force", False)
        if not isinstance(force, bool):
            raise ControllerError("force: true or false")
        out = controller.start_game(game_id, force=force)
        if checkin is not None:
            # ADR-P3-13: a warning, not a block; the console asks before it starts.
            out = {**out, "pending_declarations": checkin.pending_count(game_id)}
        return out

    @app.get("/api/v1/games/{game_id}/start-check", dependencies=[Depends(require_console)])
    def start_check(game_id: int) -> dict[str, Any]:
        game = controller.game
        if game is None or game["id"] != game_id:
            raise ControllerError(f"game {game_id} is not the live game")
        return controller.start_check()

    # --- re-inviting boxes over the radio (reinvite.py, protocol/field-frames.md) ----------

    def need_reinvite() -> Any:
        if controller.reinvite is None:
            raise ControllerError("no field join key: boxes cannot be invited over the radio")
        return controller.reinvite

    @app.get("/api/v1/boxes", dependencies=[Depends(require_gm)])
    def boxes() -> dict[str, Any]:
        return need_reinvite().boxes()

    @app.post("/api/v1/boxes/discover", dependencies=[Depends(require_gm)])
    def boxes_discover() -> dict[str, Any]:
        return need_reinvite().discover()

    @app.get("/api/v1/games/{game_id}/invites", dependencies=[Depends(require_gm)])
    def invites(game_id: int) -> dict[str, Any]:
        return {"invites": need_reinvite().invites(game_id)}

    @app.post("/api/v1/games/{game_id}/invites", dependencies=[Depends(require_gm)])
    def invite(game_id: int, body: Any = Body(None)) -> dict[str, Any]:
        return need_reinvite().invite(game_id, body_map(body).get("boxes"))

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

    @app.get("/api/v1/games/{game_id}/log")
    def game_log(game_id: int, since_ms: Optional[int] = None,
                 v: Viewer = Depends(require_read)) -> list[dict[str, Any]]:
        out = controller.log(game_id, since_ms)
        return out if visibility.is_staff(v, game_id) else [controller.event_for(v, game_id, e) for e in out]

    @app.get("/api/v1/controller", dependencies=[Depends(require_console)])
    def status() -> dict[str, Any]:
        return controller.status()

    @app.get("/api/v1/remote-gm", dependencies=[Depends(require_gm)])
    def remote_gm_log(limit: int = 200) -> dict[str, Any]:
        """The remote GM (plan phase 19): whether it is on, its stream, and every command it got."""
        remote = getattr(controller.sync, "remote", None) if controller.sync is not None else None
        return {"enabled": bool(controller.cfg.sync_remote_gm), "stream": remote.status() if remote else None,
                "log": controller.store.remote_commands(max(1, min(int(limit), 1000)))}

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

    # --- the boxes' screen language (join key 15, RFC 0001 Amendment 10) ------

    @app.get("/api/v1/settings/box-language", dependencies=[Depends(require_console)])
    def box_language() -> dict[str, Any]:
        return controller.box_language()

    @app.put("/api/v1/settings/box-language", dependencies=[Depends(require_gm)])
    def put_box_language(body: Any = Body(None)) -> dict[str, Any]:
        return controller.set_box_language(body_map(body).get("box_language"))

    # --- the field's radio channel (channels.py, RFC 0001 Amendment 3) -------

    @app.get("/api/v1/radio", dependencies=[Depends(require_console)])
    def radio() -> dict[str, Any]:
        return controller.radio_settings()

    @app.put("/api/v1/radio/channel", dependencies=[Depends(require_gm)])
    def put_channel(body: Any = Body(None)) -> dict[str, Any]:
        spec = body_map(body)
        return controller.set_field_channel(spec.get("channel_hz"), spec.get("source", "manual"))

    @app.post("/api/v1/radio/scan", status_code=202, dependencies=[Depends(require_gm)])
    def start_scan(body: Any = Body(None)) -> dict[str, Any]:
        return controller.start_scan(body_map(body).get("dwell_s"))

    @app.get("/api/v1/radio/scan", dependencies=[Depends(require_console)])
    def scan_status() -> dict[str, Any]:
        return {"scan": controller.scan_status()}

    @app.delete("/api/v1/radio/scan", dependencies=[Depends(require_gm)])
    def cancel_scan() -> dict[str, Any]:
        return controller.cancel_scan()

    @app.post("/api/v1/radio/random", dependencies=[Depends(require_gm)])
    def random_channel() -> dict[str, Any]:
        return {"suggestion": controller.random_channel()}

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
        # The control points were places on the old image (decision M9-4).
        dropped = georefmod.clear(controller.store)
        controller._emit({"type": "field_image"})
        if dropped:
            controller._emit({"type": "field_georef", "georef": None})
        return {"content_type": ctype, "bytes": len(data), "georef_cleared": dropped}

    @app.delete("/api/v1/field/image", dependencies=[Depends(require_gm)])
    def delete_field_image() -> dict[str, Any]:
        deleted = controller.store.delete_field_image()
        dropped = georefmod.clear(controller.store)
        if deleted:
            controller._emit({"type": "field_image"})
        if dropped:
            controller._emit({"type": "field_georef", "georef": None})
        return {"deleted": deleted}

    @app.get("/api/v1/field/georef", dependencies=[Depends(require_read)])
    def get_georef() -> dict[str, Any]:
        geo = georefmod.load(controller.store)
        return {"georef": geo.to_api() if geo else None}

    @app.put("/api/v1/field/georef", dependencies=[Depends(require_gm)])
    def put_georef(body: Any = Body(None)) -> dict[str, Any]:
        """Control points: two opposite corners of a north-up image, or 3-8 points (georef.py)."""
        if controller.store.field_image() is None:
            raise HTTPException(409, "upload the field image first: the points are places on it")
        spec = body_map(body)
        if set(spec) != {"points"}:
            raise ControllerError("the body is {\"points\": [{\"x\", \"y\", \"lat\", \"lon\"}, ...]}")
        try:
            geo = georefmod.Georef(georefmod.check_points(spec["points"]))
        except georefmod.GeorefError as exc:
            raise ControllerError(str(exc)) from None
        georefmod.save(controller.store, geo)
        out = geo.to_api()
        controller._emit({"type": "field_georef", "georef": out})
        return {"georef": out}

    @app.delete("/api/v1/field/georef", dependencies=[Depends(require_gm)])
    def delete_georef() -> dict[str, Any]:
        deleted = georefmod.clear(controller.store)
        if deleted:
            controller._emit({"type": "field_georef", "georef": None})
        return {"deleted": deleted}

    @app.get("/api/v1/atak", dependencies=[Depends(require_console)])
    def atak_status() -> dict[str, Any]:
        if controller.atak is None:
            return {"enabled": False}
        return controller.atak.status()

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

    # --- field and team branding (branding.py, decisions BR1-BR24) ----------------

    def public_read(request: Request) -> None:
        if not branding.rate.allow(client_of(request)):
            raise HTTPException(429, "too many requests from this address; wait a minute")

    def not_modified(request: Request, tag: str) -> bool:
        wanted = request.headers.get("if-none-match")
        if not wanted:
            return False
        return wanted.strip() == "*" or any(t.strip().removeprefix("W/") == tag for t in wanted.split(","))

    def image_response(request: Request, img: dict[str, Any], cache: str) -> Response:
        tag = etag(img["id"])
        headers = {"ETag": tag, "Cache-Control": cache, **IMAGE_HEADERS}
        if not_modified(request, tag):
            return Response(status_code=304, headers=headers)
        return Response(img["data"], media_type=img["content_type"], headers=headers)

    async def read_upload(request: Request, limit: int, what: str) -> tuple[bytes, str]:
        ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
        declared = request.headers.get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            raise HTTPException(413, f"the {what} is over {limit} bytes")
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > limit:
                raise HTTPException(413, f"the {what} is over {limit} bytes")
        return bytes(data), ctype

    def slot_of(slot: str) -> images.Limits:
        if slot not in SLOTS:
            raise HTTPException(404, "the field's branding images are 'logo' and 'wallpaper'")
        return SLOTS[slot]

    @app.get("/api/v1/field/branding")
    def field_branding(request: Request) -> Response:
        """No token: anyone who can reach the field's API (players before or right after check-in)."""
        public_read(request)
        view = branding.view()
        headers = {"ETag": view["etag"], "Cache-Control": "no-cache"}
        if not_modified(request, view["etag"]):
            return Response(status_code=304, headers=headers)
        return JSONResponse(view, headers=headers)

    @app.put("/api/v1/field/branding", dependencies=[Depends(require_gm)])
    def put_field_branding(body: Any = Body(None)) -> dict[str, Any]:
        return branding.set_field(body_map(body))

    @app.get("/api/v1/field/branding/{slot}")
    def field_branding_image(slot: str, request: Request) -> Response:
        slot_of(slot)
        public_read(request)
        img = branding.image(slot)
        if img is None:
            raise HTTPException(404, f"no {slot} uploaded")
        return image_response(request, img, "no-cache")

    @app.put("/api/v1/field/branding/{slot}", dependencies=[Depends(require_gm)])
    async def put_field_branding_image(slot: str, request: Request) -> dict[str, Any]:
        limits = slot_of(slot)
        data, ctype = await read_upload(request, limits.max_bytes, slot)
        return branding.put_image(slot, data, ctype)

    @app.delete("/api/v1/field/branding/{slot}", dependencies=[Depends(require_gm)])
    def delete_field_branding_image(slot: str) -> dict[str, Any]:
        slot_of(slot)
        return branding.delete_image(slot)

    @app.post("/api/v1/crests", dependencies=[Depends(require_gm)])
    async def post_crest(request: Request) -> JSONResponse:
        data, ctype = await read_upload(request, images.CREST.max_bytes, "crest")
        out, created = branding.add_crest(data, ctype)
        return JSONResponse(out, status_code=201 if created else 200)

    @app.get("/api/v1/crests/{crest_id}")
    def get_crest(crest_id: str, request: Request) -> Response:
        public_read(request)
        img = branding.crest(crest_id)
        if img is None:
            raise HTTPException(404, "no such crest")
        # A crest's id is its content's hash: the same URL never shows another image.
        return image_response(request, img, "public, max-age=31536000, immutable")

    @app.get("/api/v1/team-presets", dependencies=[Depends(require_console)])
    def team_presets() -> list[dict[str, Any]]:
        return branding.team_presets()

    @app.post("/api/v1/team-presets", status_code=201, dependencies=[Depends(require_gm)])
    def team_preset_add(body: Any = Body(None)) -> dict[str, Any]:
        return branding.save_team_preset(body_map(body))

    @app.put("/api/v1/team-presets/{preset_id}", dependencies=[Depends(require_gm)])
    def team_preset_put(preset_id: int, body: Any = Body(None)) -> dict[str, Any]:
        return branding.save_team_preset(body_map(body), preset_id)

    @app.delete("/api/v1/team-presets/{preset_id}", dependencies=[Depends(require_gm)])
    def team_preset_delete(preset_id: int) -> dict[str, Any]:
        return branding.delete_team_preset(preset_id)

    @app.get("/api/v1/games/{game_id}/teams")
    def game_teams(game_id: int, request: Request) -> dict[str, Any]:
        public_read(request)
        return branding.game_teams(game_id)

    @app.put("/api/v1/games/{game_id}/teams/{team}", dependencies=[Depends(require_gm)])
    def game_team_put(game_id: int, team: str, body: Any = Body(None)) -> dict[str, Any]:
        return controller.set_team_info(game_id, team, body_map(body))

    # --- the field CA (ADR-P3-9, P3-8) -------------------------------------------

    @app.get("/api/v1/controller/ca")
    def field_ca() -> Response:
        """The field CA's certificate, no token: phones check it against the poster's or the join
        payload's fingerprint and pin it (protocol/checkin.md)."""
        if ca_pem is None:
            raise HTTPException(404, "HTTPS is off on this controller ([api] tls_port = 0)")
        import hashlib  # noqa: PLC0415

        from cryptography import x509  # noqa: PLC0415
        from cryptography.hazmat.primitives import serialization  # noqa: PLC0415

        der = x509.load_pem_x509_certificate(ca_pem).public_bytes(serialization.Encoding.DER)
        return Response(ca_pem, media_type="application/x-pem-file",
                        headers={"X-Atalaia-CA-SHA256": hashlib.sha256(der).hexdigest(),
                                 "Cache-Control": "no-cache"})

    # --- firmware updates (firmware_updates.py, protocol/firmware-update.md) -----------

    def firmware() -> Any:
        if controller.firmware is None:
            raise HTTPException(503, "firmware updates are not set up on this controller")
        return controller.firmware

    @app.get("/api/v1/firmware", dependencies=[Depends(require_gm)])
    def firmware_status() -> dict[str, Any]:
        return firmware().status()

    @app.post("/api/v1/firmware", status_code=201, dependencies=[Depends(require_gm)])
    async def firmware_upload(request: Request, platform: str = "", version: str = "",
                              signature: str = "") -> dict[str, Any]:
        from .firmware_updates import SLOT_SIZE  # noqa: PLC0415

        data, _ = await read_upload(request, SLOT_SIZE, "firmware image")
        return firmware().add(data, platform, version, signature)

    @app.delete("/api/v1/firmware/updates", dependencies=[Depends(require_gm)])
    def firmware_cancel() -> dict[str, Any]:
        return {"cancelled": firmware().cancel()}

    @app.delete("/api/v1/firmware/{release_id}", dependencies=[Depends(require_gm)])
    def firmware_delete(release_id: str) -> dict[str, Any]:
        firmware().remove(release_id)
        return {"deleted": release_id}

    @app.post("/api/v1/firmware/{release_id}/install", dependencies=[Depends(require_gm)])
    def firmware_install(release_id: str, body: Any = Body(None)) -> dict[str, Any]:
        return firmware().install(release_id, body_map(body).get("nodes"))

    @app.get("/api/v1/firmware/{release_id}/release")
    def firmware_release_text(release_id: str) -> Response:
        """For the boxes, no token: the release's manifest and signature, which the box verifies."""
        return Response(firmware().release_text(release_id), media_type="text/plain; charset=utf-8",
                        headers={"Cache-Control": "no-store"})

    @app.get("/api/v1/firmware/{release_id}/image")
    def firmware_image(release_id: str) -> Response:
        from fastapi.responses import FileResponse  # noqa: PLC0415

        return FileResponse(firmware().image_path(release_id), media_type="application/octet-stream",
                            headers={"Cache-Control": "no-store"})

    @app.post("/api/v1/firmware/report")
    async def firmware_report(request: Request) -> dict[str, Any]:
        """A box's report on its update: no token, the live game's key signs it (an HMAC)."""
        from .firmware_updates import REPORT_MAX  # noqa: PLC0415

        data, _ = await read_upload(request, REPORT_MAX, "report")
        return firmware().report(data, request.headers.get("x-atalaia-mac"))

    # --- adopting boxes (protocol/adoption.md): GM only, never cached --------------------

    def adoption() -> Any:
        if controller.adoption is None:
            raise HTTPException(503, "adoption is not set up on this controller")
        return controller.adoption

    @app.get("/api/v1/adopt", dependencies=[Depends(require_gm)])
    def adopt_info() -> JSONResponse:
        return JSONResponse(adoption().info(), headers=NO_STORE)

    @app.post("/api/v1/adopt/card", dependencies=[Depends(require_gm)])
    def adopt_card() -> JSONResponse:
        """The NFC field card's bytes: the field join key, the field's master secret."""
        return JSONResponse(adoption().field_card(), headers=NO_STORE)

    @app.post("/api/v1/adopt/usb/scan", dependencies=[Depends(require_gm)])
    def adopt_usb_scan() -> JSONResponse:
        return JSONResponse(adoption().scan(), headers=NO_STORE)

    @app.post("/api/v1/adopt/usb", dependencies=[Depends(require_gm)])
    def adopt_usb(body: Any = Body(None)) -> JSONResponse:
        b = body_map(body)
        return JSONResponse(adoption().adopt_usb(b.get("port"), b.get("mac"), b.get("pin")), headers=NO_STORE)

    def pairing() -> Any:
        if controller.pairing is None:
            raise HTTPException(503, "pairing needs the field join key")
        return controller.pairing

    @app.get("/api/v1/adopt/pair", dependencies=[Depends(require_gm)])
    def adopt_pair_status() -> JSONResponse:
        return JSONResponse(pairing().status(), headers=NO_STORE)

    @app.post("/api/v1/adopt/pair/listen", dependencies=[Depends(require_gm)])
    def adopt_pair_listen() -> JSONResponse:
        return JSONResponse(pairing().listen(), headers=NO_STORE)

    @app.post("/api/v1/adopt/pair", dependencies=[Depends(require_gm)])
    def adopt_pair(body: Any = Body(None)) -> JSONResponse:
        b = body_map(body)
        return JSONResponse(pairing().pair(b.get("pair_id"), b.get("code")), headers=NO_STORE)

    # --- field check-in (ADR-P3-13, protocol/checkin.md) ------------------------------

    @app.get("/api/v1/checkin")
    def checkin_info(request: Request) -> JSONResponse:
        svc = need_checkin()
        if not svc.info_rate.allow(client_of(request)):
            raise HTTPException(429, "too many requests from this address; wait a minute")
        return JSONResponse(svc.info(), headers=NO_STORE)

    @app.post("/api/v1/checkin")
    def checkin_post(request: Request, body: Any = Body(None)) -> JSONResponse:
        out, created = need_checkin().check_in(body_map(body), client_of(request))
        return JSONResponse(out, status_code=201 if created else 200, headers=NO_STORE)

    @app.post("/api/v1/checkin/token")
    def checkin_token(v: Viewer = Depends(require_player)) -> JSONResponse:
        return JSONResponse(need_checkin().refresh_token(v), headers=NO_STORE)

    @app.get("/api/v1/checkin/me")
    def checkin_me(v: Viewer = Depends(require_player)) -> JSONResponse:
        return JSONResponse(need_checkin().me(v), headers=NO_STORE)

    @app.delete("/api/v1/checkin/me")
    def checkin_leave(v: Viewer = Depends(require_player)) -> dict[str, Any]:
        return need_checkin().leave(v)

    @app.put("/api/v1/checkin/me/replicas")
    def checkin_replicas(v: Viewer = Depends(require_player), body: Any = Body(None)) -> dict[str, Any]:
        return need_checkin().put_my_replicas(v, body_map(body))

    @app.put("/api/v1/checkin/me/marshal-key")
    def checkin_marshal_key(v: Viewer = Depends(require_player), body: Any = Body(None)) -> dict[str, Any]:
        if v.role != "marshal":
            raise HTTPException(403, "only a marshal registers a signing key (the GM gives the role)")
        return need_checkin().register_marshal(body_map(body), player_id=v.player_id)

    @app.get("/api/v1/games/{game_id}/checkins")
    def checkins_list(game_id: int, v: Viewer = Depends(require_read)) -> JSONResponse:
        return JSONResponse(need_checkin().list_checkins(v, game_id), headers=NO_STORE)

    @app.get("/api/v1/games/{game_id}/checkins.csv", dependencies=[Depends(require_gm)])
    def checkins_csv(game_id: int) -> Response:
        text = need_checkin().csv_export(game_id)
        return Response(text.encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                        headers={**NO_STORE,
                                 "Content-Disposition": f'attachment; filename="checkins-{game_id}.csv"'})

    @app.post("/api/v1/games/{game_id}/checkins", status_code=201)
    def checkins_manual(game_id: int, v: Viewer = Depends(require_read), body: Any = Body(None)) -> dict[str, Any]:
        return need_checkin().manual_checkin(v, game_id, body_map(body))

    @app.patch("/api/v1/games/{game_id}/checkins/{player_id}")
    def checkins_patch(game_id: int, player_id: str, v: Viewer = Depends(require_read),
                       body: Any = Body(None)) -> dict[str, Any]:
        return need_checkin().patch_checkin(v, game_id, player_id, body_map(body))

    @app.delete("/api/v1/games/{game_id}/checkins/{player_id}")
    def checkins_remove(game_id: int, player_id: str, v: Viewer = Depends(require_read)) -> dict[str, Any]:
        return need_checkin().remove_checkin(v, game_id, player_id)

    @app.post("/api/v1/games/{game_id}/checkins/ticket")
    def checkins_ticket(game_id: int, v: Viewer = Depends(require_read), body: Any = Body(None)) -> dict[str, Any]:
        return need_checkin().ticket_checkin(v, game_id, body_map(body))

    # --- the site server's schedule (plan phase 16, schedule.py) ------------------------------

    @app.get("/api/v1/schedule", dependencies=[Depends(require_console)])
    def schedule_list() -> JSONResponse:
        return JSONResponse(schedulemod.schedule(controller), headers=NO_STORE)

    @app.post("/api/v1/schedule/{scheduled_game_id}/game", status_code=201, dependencies=[Depends(require_gm)])
    def schedule_game(scheduled_game_id: str, body: Any = Body(None)) -> dict[str, Any]:
        return schedulemod.create_game(controller, scheduled_game_id, body if body is not None else {})

    @app.get("/api/v1/games/{game_id}/chrono-list")
    def chrono_list(game_id: int, v: Viewer = Depends(require_read)) -> JSONResponse:
        return JSONResponse(need_checkin().chrono_list(v, game_id), headers=NO_STORE)

    @app.post("/api/v1/games/{game_id}/checkin/open", dependencies=[Depends(require_gm)])
    def checkin_open(game_id: int) -> dict[str, Any]:
        return need_checkin().set_open(game_id, True)

    @app.post("/api/v1/games/{game_id}/checkin/close", dependencies=[Depends(require_gm)])
    def checkin_close(game_id: int) -> dict[str, Any]:
        return need_checkin().set_open(game_id, False)

    @app.post("/api/v1/chrono/readings")
    def chrono_readings(v: Viewer = Depends(require_read), body: Any = Body(None)) -> dict[str, Any]:
        return need_checkin().upload_readings(v, body_map(body))

    @app.get("/api/v1/marshals", dependencies=[Depends(require_gm)])
    def marshals() -> list[dict[str, Any]]:
        return need_checkin().marshals()

    @app.post("/api/v1/marshals", status_code=201, dependencies=[Depends(require_gm)])
    def marshal_add(body: Any = Body(None)) -> dict[str, Any]:
        return need_checkin().register_marshal(body_map(body))

    @app.get("/api/v1/checkin/settings", dependencies=[Depends(require_gm)])
    def checkin_settings() -> dict[str, Any]:
        return need_checkin().settings()

    @app.put("/api/v1/checkin/settings", dependencies=[Depends(require_gm)])
    def checkin_settings_put(body: Any = Body(None)) -> dict[str, Any]:
        return need_checkin().set_settings(body_map(body))

    @app.get("/api/v1/checkin/poster", dependencies=[Depends(require_gm)])
    def checkin_poster() -> dict[str, Any]:
        return need_checkin().poster()

    @app.put("/api/v1/checkin/poster", dependencies=[Depends(require_gm)])
    def checkin_poster_put(body: Any = Body(None)) -> dict[str, Any]:
        return need_checkin().set_poster(body_map(body))

    def own_or_gm(v: Viewer, player_id: str) -> None:
        if not (v.is_gm_token or (v.kind == "player" and v.player_id == player_id)):
            raise HTTPException(403, "the GM token, or the player's own token")

    @app.get("/api/v1/players/{player_id}/chrono")
    def player_chrono(player_id: str, v: Viewer = Depends(require_read)) -> JSONResponse:
        own_or_gm(v, player_id)
        return JSONResponse({"player_id": player_id, "readings": need_checkin().player_readings(player_id)},
                            headers=NO_STORE)

    @app.delete("/api/v1/players/{player_id}/chrono")
    def player_chrono_erase(player_id: str, v: Viewer = Depends(require_read)) -> dict[str, Any]:
        own_or_gm(v, player_id)
        svc = need_checkin()
        return {"player_id": player_id, "readings_deleted": svc.store.delete_readings(player_id=player_id)}

    @app.delete("/api/v1/players/{player_id}", dependencies=[Depends(require_gm)])
    def player_erase(player_id: str, chrono: bool = False) -> dict[str, Any]:
        return need_checkin().erase_player(player_id, chrono_too=chrono)

    # --- player positions (ADR-P3-6) -------------------------------------------------

    @app.post("/api/v1/positions")
    def positions_post(v: Viewer = Depends(require_player), body: Any = Body(None)) -> dict[str, Any]:
        if players is None:
            raise HTTPException(503, "positions are not set up on this controller")
        return players.report(v, body)

    @app.get("/api/v1/positions")
    def positions_get(v: Viewer = Depends(require_read)) -> JSONResponse:
        if players is None:
            raise HTTPException(503, "positions are not set up on this controller")
        return JSONResponse({"positions": players.visible(v)}, headers=NO_STORE)

    # --- Android props on Wi-Fi (prop_link.py) ----------------------------------------

    @app.websocket("/api/v1/prop")
    async def prop_link(ws: WebSocket) -> None:
        links = controller.prop_links
        if links is None:
            await ws.close(code=4404)
            return
        await links.serve(ws)

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
        v = auth.viewer(token)
        if v is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        queue = hub.subscribe(v)
        try:
            await ws.send_json(_snapshot(controller, v))

            async def sender() -> None:
                while True:
                    msg = await queue.get()
                    if msg is None:
                        await ws.close(code=4408)  # too slow: reconnect for a fresh snapshot
                        return
                    if isinstance(msg, tuple):  # ("close", code): e.g. 4409, fetch a new token
                        await ws.close(code=msg[1])
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


HELLO_EVENTS = 100


def _snapshot(controller: Controller, viewer: Optional[Viewer] = None) -> dict[str, Any]:
    """The first message on the stream: the live game, its score, nodes and its latest events,
    so a client that connects mid-game shows what already happened (item 4 of plan phase E).
    A player's connection also gets its own check-in and the positions it may see."""
    status = controller.status()
    game_id = status["live_game"]
    events = []
    staff = visibility.is_staff(viewer, game_id)
    if game_id:
        events = [{k: e.get(k) for k in ("node", "seq", "t", "type", "team", "squad", "prio", "data")}
                  for e in controller.store.events(game_id)[-HELLO_EVENTS:]]
        if not staff:
            events = [controller.event_for(viewer, game_id, e) for e in events]
    game = controller.get_game(game_id) if game_id else None
    out: dict[str, Any] = {
        "type": "hello",
        "game": game if game is None or staff else controller.players_game(game, viewer),
        "score": controller.score(game_id) if game_id else None,
        "nodes": controller.nodes(game_id) if game_id else [],
        "events": events,
    }
    if controller.branding is not None:
        out["branding"] = controller.branding.view()  # public: the field's name, images, accent
    if viewer is None or viewer.kind != "player":
        out["status"] = status
        return out
    out["status"] = {"live_game": game_id}
    svc = controller.checkin
    if svc is not None and viewer.game_id is not None:
        game = controller.store.game(viewer.game_id)
        row = controller.store.checkin(viewer.game_id, viewer.player_id)
        if game is not None and row is not None:
            out["me"] = {**svc.row_view(game, row), "stale_token": viewer.stale}
    if controller.positions is not None:
        out["positions"] = controller.positions.visible(viewer)
    return out


def make_route(controller: Controller) -> Callable[[Any, dict[str, Any]], Any]:
    """Who gets which stream message (decision PE6; ws.py)."""

    def route(v: Optional[Viewer], msg: dict[str, Any]) -> Any:
        if v is None:
            return None
        if msg.get("_staff") or "_player" in msg:
            game = msg.get("game")
            staff = v.is_staff and (v.kind != "player" or v.game_id == game)
            own = v.kind == "player" and v.player_id is not None and v.player_id == msg.get("_player") \
                and v.game_id == game
            if not staff and not own:
                return None
            out = public(msg)
            if own and msg.get("_assignment"):
                # The GM changed this player's team, squad or role: fetch a new token and reconnect.
                return [out, ("close", 4409)]
            return out
        if msg.get("_position"):
            pos = controller.positions
            return public(msg) if pos is not None and pos.can_see(v, msg["position"]) else None
        if msg.get("_positions_refresh"):
            pos = controller.positions
            if pos is None or v.kind == "read":
                return None
            return {"type": "positions", "game": msg.get("game"), "positions": pos.visible(v, msg.get("game"))}
        if v.kind == "player" and msg.get("type") not in PLAYER_TYPES:
            return None
        out = public(msg)
        # Decision M5-1: gm_only event data and game parameters to staff only; a scenario's
        # objectives to the players they are for (P4R24).
        if out.get("type") == "event" and isinstance(out.get("event"), dict) \
                and not visibility.is_staff(v, out.get("game")):
            out["event"] = controller.event_for(v, out.get("game"), out["event"])
        elif out.get("type") == "game" and isinstance(out.get("game"), dict) \
                and not visibility.is_staff(v, out["game"].get("id")):
            out["game"] = controller.players_game(out["game"], v)
        return out

    return route


def _mode_of(controller: Controller, mode_id: Any) -> Any:
    pkg = controller.modes.get(mode_id) if isinstance(mode_id, str) else None
    return pkg.mode if pkg else None
