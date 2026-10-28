# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The live demo's read-only proxy: the only thing of the demo field that is reachable from outside its container.

It stands in front of the field controller and lets through only what a visitor may do:

- **Reading only.** GET and HEAD, nothing else: any other method is refused with 405 before anything is forwarded.
  Nothing a visitor sends can start, pause, end or change a game, make a join card, register a box or a mode.
- **Only the public read token.** The token every visitor uses is published on the "Try the demo" page; the proxy
  forwards a request only if it carries exactly that token (header or ``?token=`` on the stream), and always
  replaces whatever it was given with it. The controller's GM token is never accepted and never seen here.
- **Only listed paths.** The console's static files, the scoreboard page and a list of the controller's read
  endpoints (``API_READ``); everything else, join cards, adoption, firmware, check-in lists of other people, the
  marshal list, is a 404 here, whatever the controller would have said.
- **The stream is one-way.** The WebSocket the console and the scoreboard follow is relayed controller to visitor;
  what the visitor sends on it is dropped.
- **The player's view** (``/player/``) shows what one checked-in demo player's phone shows, read with that player's
  own token, which the proxy holds (a file only it can read) and the visitor never receives.

Everything in the demo is invented (callsigns, scores, the field); there is no personal data to protect, and the
list above is what keeps it that way if a later version of the controller grows an endpoint that has some.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response

READ_TOKEN = os.environ.get("DEMO_READ_TOKEN", "atalaia-demo")
CONTROLLER = os.environ.get("DEMO_CONTROLLER", "http://127.0.0.1:8080").rstrip("/")
DATA = Path(os.environ.get("DEMO_DATA", "/data"))
HERE = Path(__file__).resolve().parent
MAX_STREAMS = 60
SITE_URL = os.environ.get("DEMO_SITE_URL", "").rstrip("/")
SITE_SLUG = os.environ.get("DEMO_SITE_SLUG", "demo-ao-vivo")

# What a visitor with the read token may read from the controller's REST API. Anchored, GET only (see below).
API_READ = [re.compile(p) for p in (
    r"/api/v1/whoami",
    r"/api/v1/nodes",
    r"/api/v1/presets",
    r"/api/v1/modes",
    r"/api/v1/scenarios",
    r"/api/v1/schedule",
    r"/api/v1/controller",
    r"/api/v1/radio",
    r"/api/v1/atak",
    r"/api/v1/team-presets",
    r"/api/v1/settings/box-language",
    r"/api/v1/beacons",
    r"/api/v1/positions",
    r"/api/v1/games",
    r"/api/v1/games/[0-9]{1,9}",
    r"/api/v1/games/[0-9]{1,9}/(score|log|teams|start-check|positions|checkins|chrono-list)",
    r"/api/v1/field",
    r"/api/v1/field/(image|georef|levels|grid|features|branding)",
    r"/api/v1/field/levels/[0-9]/(image|georef|grid)",
    r"/api/v1/field/branding/[a-z_]{1,32}",
    r"/api/v1/crests/[A-Za-z0-9_-]{1,64}",
)]
STATIC = re.compile(r"/(console(/[A-Za-z0-9_.-]+)*/?|scoreboard)")
SAFE_PATH = re.compile(r"/[A-Za-z0-9_./-]*")
PASS_REQUEST = ("accept", "accept-language", "if-none-match", "if-modified-since")
DROP_RESPONSE = {"server", "date", "connection", "keep-alive", "transfer-encoding", "content-length",
                 "content-encoding"}

app = FastAPI(title="Atalaia demo (read-only)", docs_url=None, redoc_url=None, openapi_url=None)
client = httpx.AsyncClient(base_url=CONTROLLER, timeout=15.0, follow_redirects=False)
streams = 0


def token_ok(request: Request) -> bool:
    """The request carries the public read token (and nothing else is accepted)."""
    header = request.headers.get("authorization", "")
    return header == f"Bearer {READ_TOKEN}"


def clean_headers(upstream: httpx.Response) -> dict[str, str]:
    out = {k: v for k, v in upstream.headers.items() if k.lower() not in DROP_RESPONSE}
    out["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    out["X-Atalaia-Demo"] = "read-only"
    return out


@app.middleware("http")
async def read_only(request: Request, call_next):
    if request.method not in ("GET", "HEAD"):
        return PlainTextResponse("This is a read-only demo: nothing can be changed here.\n", status_code=405,
                                 headers={"Allow": "GET, HEAD", "X-Robots-Tag": "noindex"})
    response = await call_next(request)
    h = response.headers
    h.setdefault("X-Robots-Tag", "noindex, nofollow, noarchive")
    # The proxy's own pages (the controller's carry their own policy): no script or style but our own files.
    h.setdefault("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; "
                 "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; "
                 "frame-ancestors 'none'")
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.get("/demo/health", include_in_schema=False)
async def health() -> Response:
    try:
        r = await client.get("/healthz")
        return PlainTextResponse("ok\n" if r.status_code == 200 else "controller not ready\n",
                                 status_code=200 if r.status_code == 200 else 503)
    except httpx.HTTPError:
        return PlainTextResponse("controller not ready\n", status_code=503)


@app.get("/demo/config.json", include_in_schema=False)
async def config() -> Response:
    """What the home page needs: the public read token and where the site server's pages of this game are."""
    return JSONResponse({"read_token": READ_TOKEN, "site_url": SITE_URL, "site_slug": SITE_SLUG},
                        headers={"Cache-Control": "no-cache"})


@app.get("/demo/state.json", include_in_schema=False)
async def state() -> Response:
    """The newest game's name and state, for the home page's "now" line."""
    r = await player_get("/api/v1/games", READ_TOKEN)
    games = r.json() if r is not None else []
    if not games:
        return JSONResponse(None, headers={"Cache-Control": "no-store"})
    g = max(games, key=lambda x: x.get("created_at", 0))
    return JSONResponse({"name": g["name"], "state": g["state"]}, headers={"Cache-Control": "no-store"})


@app.get("/robots.txt", include_in_schema=False)
async def robots() -> Response:
    return PlainTextResponse("User-agent: *\nDisallow: /\n")


@app.get("/", include_in_schema=False)
async def home() -> Response:
    return FileResponse(HERE / "home" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/home/{name}", include_in_schema=False)
async def home_files(name: str) -> Response:
    if not re.fullmatch(r"[a-z0-9._-]{1,40}", name) or not (HERE / "home" / name).is_file():
        return PlainTextResponse("not found\n", status_code=404)
    return FileResponse(HERE / "home" / name, headers={"Cache-Control": "no-cache"})


# --- the player's view -------------------------------------------------------------------------------------------

def player_file() -> Optional[dict[str, Any]]:
    try:
        return json.loads((DATA / "player.json").read_text())
    except (OSError, ValueError):
        return None


@app.get("/player", include_in_schema=False)
async def player_redirect() -> Response:
    return RedirectResponse("/player/")


@app.get("/player/", include_in_schema=False)
async def player_page() -> Response:
    return FileResponse(HERE / "player" / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/player/{name}", include_in_schema=False)
async def player_files(name: str) -> Response:
    if name in ("data.json", "field.png"):
        return await player_data(name)
    if not re.fullmatch(r"[a-z0-9._-]{1,40}", name) or not (HERE / "player" / name).is_file():
        return PlainTextResponse("not found\n", status_code=404)
    return FileResponse(HERE / "player" / name, headers={"Cache-Control": "no-cache"})


async def player_get(path: str, token: str) -> Optional[httpx.Response]:
    try:
        r = await client.get(path, headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return None
    return r if r.status_code == 200 else None


async def player_data(name: str) -> Response:
    who = player_file()
    if who is None:
        return JSONResponse({"waiting": True}, status_code=503, headers={"Cache-Control": "no-store"})
    token, gid = who["token"], who["game_id"]
    if name == "field.png":
        r = await player_get("/api/v1/field/image", READ_TOKEN)
        if r is None:
            return PlainTextResponse("not found\n", status_code=404)
        return Response(r.content, media_type=r.headers.get("content-type", "image/png"),
                        headers={"Cache-Control": "max-age=300"})
    me, game, score, pos, log, geo, nodes, boxes = await asyncio.gather(
        player_get("/api/v1/checkin/me", token), player_get(f"/api/v1/games/{gid}", token),
        player_get(f"/api/v1/games/{gid}/score", token), player_get("/api/v1/positions", token),
        player_get(f"/api/v1/games/{gid}/log", token), player_get("/api/v1/field/georef", token),
        player_get("/api/v1/nodes", token), player_get(f"/api/v1/games/{gid}/positions", token))
    if me is None or game is None:
        return JSONResponse({"waiting": True}, status_code=503, headers={"Cache-Control": "no-store"})
    me_j = me.json()
    # Only what the phone's own screen shows: the callsign, team, role and state of this one check-in.
    keep = ("display_name", "team", "team_name", "role", "status", "squad", "player_id", "game_id")
    body = {
        "me": {**{k: me_j[k] for k in keep if k in me_j},
               "replicas": [{"class": d.get("class"), "type": d.get("type"), "state": d.get("state")}
                            for d in me_j.get("declarations", [])]},
        "game": game.json(),
        "score": score.json() if score else None,
        "positions": (pos.json() if pos else {}).get("positions", []),
        "log": (log.json() if log else [])[-12:],
        "georef": geo.json() if geo else None,
        "nodes": [{k: n.get(k) for k in ("node_id", "name", "owner", "link")} for n in (nodes.json() if nodes else [])],
        "boxes": boxes.json() if boxes else {},
        "you": who["player_id"],
    }
    return JSONResponse(body, headers={"Cache-Control": "no-store"})


# --- the controller's console, scoreboard and read endpoints ---------------------------------------------------------

async def forward(request: Request, token: str) -> Response:
    headers = {k: v for k, v in request.headers.items() if k.lower() in PASS_REQUEST}
    headers["Authorization"] = f"Bearer {token}"
    try:
        upstream = await client.request(request.method, request.url.path, params=dict(request.query_params),
                                        headers=headers)
    except httpx.HTTPError:
        return PlainTextResponse("the demo field is restarting; try again in a minute\n", status_code=503,
                                 headers={"Retry-After": "30"})
    body = b"" if request.method == "HEAD" else upstream.content
    return Response(body, status_code=upstream.status_code, headers=clean_headers(upstream))


@app.get("/api/v1/stream", include_in_schema=False)
async def stream_needs_websocket() -> Response:
    return PlainTextResponse("a WebSocket endpoint\n", status_code=426)


@app.get("/{path:path}", include_in_schema=False)
async def get_any(path: str, request: Request) -> Response:
    full = "/" + path
    # A path is only ever what it says: no dot segments, no empty segments, no odd characters (so that
    # /console/../api/v1/boxes can never pass for a console file and slip the list below).
    segments = full.split("/")[1:]
    if (not SAFE_PATH.fullmatch(full) or any(seg in ("", ".", "..") for seg in segments[:-1])
            or segments[-1] in (".", "..")):
        return PlainTextResponse("not found\n", status_code=404)
    if STATIC.fullmatch(full):
        return await forward(request, READ_TOKEN)
    if any(p.fullmatch(full) for p in API_READ):
        if not token_ok(request):
            return JSONResponse({"detail": "the demo's read token is needed (it is on the demo's home page)"},
                                status_code=401, headers={"WWW-Authenticate": "Bearer"})
        return await forward(request, READ_TOKEN)
    return PlainTextResponse("not found\n", status_code=404)


@app.websocket("/api/v1/stream")
async def stream(ws: WebSocket) -> None:
    global streams
    import websockets

    if ws.query_params.get("token") != READ_TOKEN:
        await ws.close(code=4401)
        return
    if streams >= MAX_STREAMS:
        await ws.close(code=4429)
        return
    await ws.accept()
    streams += 1
    try:
        url = CONTROLLER.replace("http", "ws", 1) + f"/api/v1/stream?token={READ_TOKEN}"
        async with websockets.connect(url, open_timeout=10, ping_interval=20) as upstream:
            async def down() -> None:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await ws.send_bytes(message)
                    else:
                        await ws.send_text(message)

            async def drain() -> None:
                # What a visitor sends is read and thrown away: the stream is one way.
                while (await ws.receive())["type"] != "websocket.disconnect":
                    pass

            tasks = [asyncio.ensure_future(down()), asyncio.ensure_future(drain())]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except Exception:  # noqa: BLE001  (a dropped stream is the client's to reconnect)
        pass
    finally:
        streams -= 1
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass
