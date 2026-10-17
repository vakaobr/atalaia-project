# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The simulator's web view: python -m atalaia_sim serve MODE.

A small local web server (standard library only) around a LiveGame. The
page in web/ polls GET /api/state and sends actions to POST /api/action.

It is a development tool for one person's machine: it listens on localhost
by default, answers only requests addressed to a local host name (so a web
page elsewhere cannot reach it through DNS rebinding), and accepts actions
only as JSON (so another site's form cannot send one).
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

from .live import LiveError, LiveGame

WEB = Path(__file__).resolve().parent / "web"
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MAX_BODY = 16 * 1024
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

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; frame-ancestors 'none'; form-action 'none'")
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
        if url.path == "/api/state":
            try:
                since = int(parse_qs(url.query).get("since", ["0"])[0])
            except ValueError:
                since = 0
            return self._json(HTTPStatus.OK, self.server.game.snapshot(since))
        self._error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self) -> None:
        if not self._host_allowed():
            return self._error(HTTPStatus.FORBIDDEN, "unknown host")
        if urlsplit(self.path).path != "/api/action":
            return self._error(HTTPStatus.NOT_FOUND, "not found")
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            return self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "send JSON")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if not 0 < length <= MAX_BODY:
            return self._error(HTTPStatus.BAD_REQUEST, "bad request body")
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or not isinstance(body.get("action"), str):
                raise ValueError
        except ValueError:
            return self._error(HTTPStatus.BAD_REQUEST, "expected {\"action\": ...}")
        action = body.pop("action")
        try:
            self.server.game.act(action, body)
        except LiveError as exc:
            return self._error(HTTPStatus.CONFLICT, str(exc))
        self._json(HTTPStatus.OK, {"ok": True})


def make_server(game: LiveGame, host: str = "127.0.0.1", port: int = 8000,
                allow_hosts: Optional[list[str]] = None) -> WebServer:
    allowed = set(LOCAL_HOSTS) | {h.lower() for h in allow_hosts or []}
    if host not in ("0.0.0.0", "::", ""):
        allowed.add(host.lower())
    return WebServer(game, host, port, allowed)
