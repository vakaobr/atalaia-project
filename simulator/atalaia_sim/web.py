# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The simulator's web view: python -m atalaia_sim serve MODE.

A small local web server (standard library only) around a LiveGame. The
page in web/ polls GET /api/state and sends actions to POST /api/action.
The mode editor (editor/, phase 5 plan phase 1) is served at /editor/: a
static page with its own vendored Blockly, which needs no network. Its
"Test" button sends the mode it is editing to POST /api/reload (plan phase
2), which makes it the game the web view shows.

It is a development tool for one person's machine: it listens on localhost
by default, answers only requests addressed to a local host name (so a web
page elsewhere cannot reach it through DNS rebinding), and accepts actions
and reloads only as JSON (so another site's form cannot send one, and a
script elsewhere cannot without a CORS preflight, which it never grants).
A reloaded mode's scripts run in the core's sandbox, as every mode's do.
"""

from __future__ import annotations

import json
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from .live import LiveError, LiveGame, ReloadError

WEB = Path(__file__).resolve().parent / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
EDITOR = Path(__file__).resolve().parent / "editor"
# The editor's files by suffix; anything else under editor/ is not served.
EDITOR_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".gif": "image/gif",
    ".cur": "image/x-icon",
    ".mp3": "audio/mpeg",
}
# Blockly writes its stylesheet into the page and draws with inline styles, so the editor's
# pages allow inline styles (never inline scripts) and data: images.
EDITOR_CSP = ("default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
              "frame-ancestors 'none'; form-action 'none'")
DEFAULT_CSP = "default-src 'self'; frame-ancestors 'none'; form-action 'none'"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MAX_BODY = 16 * 1024
# A reload carries a mode's files: at most what the field controller takes as a mode package
# (MAX_PACKAGE_BYTES in controller/atalaia_controller/modes.py, decision P5-6).
MAX_RELOAD_BODY = 1_000_000
POST_LIMITS = {"/api/action": MAX_BODY, "/api/reload": MAX_RELOAD_BODY}
TICK_S = 0.05


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, game: LiveGame, host: str, port: int, allowed_hosts: set[str]):
        self.game = game
        self.allowed_hosts = allowed_hosts
        self.verbose = False
        self._stop = threading.Event()
        super().__init__((host, port), _Handler)
        self._ticker = threading.Thread(target=self._tick, name="atalaia-clock", daemon=True)
        self._ticker.start()

    def _tick(self) -> None:
        while not self._stop.wait(TICK_S):
            try:
                self.game.tick()
            except Exception as exc:  # keep the clock alive; show the error in the log
                print(f"clock: {exc}")

    @property
    def url(self) -> str:
        host, port = self.server_address[:2]
        shown = "localhost" if host in ("0.0.0.0", "::", "127.0.0.1") else host
        return f"http://{shown}:{port}/"

    def server_close(self) -> None:
        self._stop.set()
        super().server_close()


class _Handler(BaseHTTPRequestHandler):
    server: WebServer
    server_version = "atalaia-sim"

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.server.verbose:
            super().log_message(fmt, *args)

    # -- responses --

    def _send(self, status: int, body: bytes, content_type: str, csp: str = DEFAULT_CSP) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send(status, json.dumps(value).encode(), "application/json")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _host_allowed(self) -> bool:
        host = self.headers.get("Host", "")
        name = host[1:host.find("]")] if host.startswith("[") else host.rsplit(":", 1)[0]
        return name.lower() in self.server.allowed_hosts

    # -- requests --

    def do_GET(self) -> None:
        if not self._host_allowed():
            return self._error(HTTPStatus.FORBIDDEN, "unknown host")
        url = urlsplit(self.path)
        if url.path in STATIC:
            name, content_type = STATIC[url.path]
            return self._send(HTTPStatus.OK, (WEB / name).read_bytes(), content_type)
        if url.path == "/editor":
            self.send_response(HTTPStatus.MOVED_PERMANENTLY)
            self.send_header("Location", "/editor/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        if url.path.startswith("/editor/"):
            return self._editor_file(url.path[len("/editor/"):] or "index.html")
        if url.path == "/api/state":
            try:
                since = int(parse_qs(url.query).get("since", ["0"])[0])
            except ValueError:
                since = 0
            return self._json(HTTPStatus.OK, self.server.game.snapshot(since))
        if url.path in ("/api/log.json", "/api/log.csv"):
            return self._download(url.path.rsplit(".", 1)[1])
        self._error(HTTPStatus.NOT_FOUND, "not found")

    def _download(self, kind: str) -> None:
        """The game's events as a file to save: JSON (with the mode, teams and parameters) or CSV."""
        game = self.server.game
        name = re.sub(r"[^A-Za-z0-9._-]", "_", game.sim.mode.id)
        if kind == "json":
            body, content_type = json.dumps(game.export_json(), indent=2).encode(), "application/json"
        else:
            body, content_type = game.export_csv().encode(), "text/csv; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'attachment; filename="atalaia-{name}-events.{kind}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", DEFAULT_CSP)
        self.end_headers()
        self.wfile.write(body)

    def _editor_file(self, name: str) -> None:
        """A file of editor/: plain names only, no dot files, a known suffix, inside the folder."""
        parts = name.split("/")
        path = EDITOR.joinpath(*parts)
        if (any(not p or p.startswith(".") for p in parts) or path.suffix not in EDITOR_TYPES
                or not path.resolve().is_relative_to(EDITOR) or not path.is_file()):
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        self._send(HTTPStatus.OK, path.read_bytes(), EDITOR_TYPES[path.suffix], EDITOR_CSP)

    def do_POST(self) -> None:
        if not self._host_allowed():
            return self._error(HTTPStatus.FORBIDDEN, "unknown host")
        path = urlsplit(self.path).path
        if path not in POST_LIMITS:
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "send JSON")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length > POST_LIMITS[path]:
            return self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                               f"at most {POST_LIMITS[path]} bytes")
        if length <= 0:
            return self._error(HTTPStatus.BAD_REQUEST, "bad request body")
        try:
            body = json.loads(self.rfile.read(length))
        except ValueError:
            body = None
        if path == "/api/reload":
            return self._reload(body)
        if not isinstance(body, dict) or not isinstance(body.get("action"), str):
            return self._error(HTTPStatus.BAD_REQUEST, "expected {\"action\": ...}")
        action = body.pop("action")
        try:
            self.server.game.act(action, body)
        except LiveError as exc:
            return self._error(HTTPStatus.CONFLICT, str(exc))
        self._json(HTTPStatus.OK, {"ok": True})

    def _reload(self, body: Any) -> None:
        """POST /api/reload (ADR-P5-2): the mode editor's files become the game. A body of the
        wrong shape is a 400; a mode that does not load is a 200 with status "error" and its
        errors (the game that was running goes on), so the editor can show them on its blocks."""
        texts = ("mode_yaml", "node_lua", "field_lua")
        if (not isinstance(body, dict) or set(body) - {*texts, "params", "nodes"}
                or not isinstance(body.get("mode_yaml"), str) or not isinstance(body.get("node_lua"), str)
                or not isinstance(body.get("field_lua") or "", str)
                or not isinstance(body.get("params") or {}, dict)
                or not isinstance(body.get("nodes") or {}, dict)):
            return self._error(HTTPStatus.BAD_REQUEST, "expected {\"mode_yaml\": ..., \"node_lua\": ..., "
                               "\"field_lua\": ..., \"params\": {...}, \"nodes\": {...}}")
        game = self.server.game
        try:
            errors = game.reload(body["mode_yaml"], body["node_lua"], body.get("field_lua"),
                                 body.get("params"), body.get("nodes") or None)
        except ReloadError as exc:
            return self._json(HTTPStatus.OK, {"status": "error", "errors": exc.errors})
        mode = game.sim.mode
        self._json(HTTPStatus.OK, {"status": "ok", "errors": errors, "reloads": game.reloads,
                                   "generation": game.generation,
                                   "mode": {"id": mode.id, "name": mode.name, "version": mode.version},
                                   "nodes": list(game.sim.nodes)})


def make_server(game: LiveGame, host: str = "127.0.0.1", port: int = 8000,
                allow_hosts: Optional[list[str]] = None) -> WebServer:
    allowed = set(LOCAL_HOSTS) | {h.lower() for h in allow_hosts or []}
    if host not in ("0.0.0.0", "::", ""):
        allowed.add(host.lower())
    return WebServer(game, host, port, allowed)
