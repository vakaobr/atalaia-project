# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote GM: a site-server user acts on this controller's live game (plan phase 19; P4R12).

Off by default. Only with ``[sync] remote_gm = true`` (and the sync on) does
the controller open ``WS /api/v1/sync/stream`` to its site server and keep it
open: the controller opens the connection, as for every other request, so a
controller behind a phone's 4G link and carrier-grade NAT never has to be
reachable, and the site server never holds the controller's GM token. The
socket carries, as protocol/sync.md describes:

- ``hello`` once (``remote_gm: true``), then ``live``: the live game as the
  console sees it (state, totals, the nodes' health, the latest events, the
  game's declared mode commands), at most every 2 s when something changed and
  every 30 s anyway. Never a position, a token, a key or a check-in.
- ``command`` from the site server, for a user it authenticated with the ``gm``
  role on this field (in a TOTP session). Only ``start``, ``pause``, ``resume``,
  ``end``, ``message`` (a GM message to every node) and ``mode`` (one of the
  game's declared mode commands) exist; the controller checks each with the
  shared ``sync_format.check_command``, refuses one for another game than its
  live one, one sent more than 60 s ago (by the site server's clock), one it
  already had (by its id), and any command when ``remote_gm`` is off, and carries
  out the rest through the engine exactly as the console's GM token would
  (a standby controller refuses, a paused game does not pause again).
- ``command.result`` back: ``done`` or why not.

Every command, carried out or refused, is in the store's ``remote_commands``
(store schema 8): who sent it (the site server's account id and username),
what it asked for, the game and the result; ``GET /api/v1/remote-gm`` shows
them to the GM. The site server logs the same in its audit log.

The client reconnects after a failure, waiting 5 s and doubling up to 5 min
(5 min at once when the API key is refused). Without a key, or with the sync
off, nothing starts.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from typing import Any, Callable, Optional
from urllib.parse import urlsplit, urlunsplit

from . import __version__
from .engine import Conflict, ControllerError, NotFound, Unavailable
from .sync_format import (MAX_LIVE_EVENTS, NODE_INFO, STALE_S, SYNC_VERSION, SyncFormatError, check_command,
                          check_event, check_live, check_nodes)
from .ws_client import WebSocket, WsError

log = logging.getLogger("atalaia.remote_gm")

STREAM_PATH = "/api/v1/sync/stream"
LIVE_MIN_S = 2.0     # a changed live view goes at most this often
LIVE_EVERY_S = 30.0  # and at least this often (the site server shows when it last heard)
PING_S = 30.0
RECV_S = 0.5
BACKOFF_MIN_S = 5.0
BACKOFF_MAX_S = 300.0
AUTH_REFUSED = 4401
BROADCAST = 0xFFFF   # every node (atalaia_sim.field_controller.BROADCAST)


def stream_url(sync_url: str) -> str:
    """The stream's address from the sync's: https -> wss, http (this machine only) -> ws."""
    parts = urlsplit(sync_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    return urlunsplit((scheme, parts.netloc, parts.path.rstrip("/") + STREAM_PATH, "", ""))


class RemoteGm:
    """The stream's thread: ``start``/``stop``; ``handle_command`` and ``live`` are what it sends and does."""

    def __init__(self, cfg: Any, store: Any, controller: Any, *, api_key: str, controller_id: Callable[[], str],
                 connect: Optional[Callable[[], Any]] = None, wall: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.store = store
        self.controller = controller
        self._controller_id = controller_id
        self._key = api_key
        self._connect = connect or self._open
        self._wall = wall
        self._stop = threading.Event()
        self._dirty = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.connected = False
        self.connected_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.commands = 0  # commands received (carried out or not)
        self.lives = 0

    # --- the thread ------------------------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="remote-gm", daemon=True)
        self._thread.start()
        log.warning("remote GM is on: users with the gm role on this field at %s may act on the live game",
                    self.cfg.sync_url)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.cfg.sync_timeout_s + 2)
            self._thread = None

    def on_controller_message(self, msg: dict[str, Any]) -> None:
        """The engine's listener: something the live view shows changed."""
        if msg.get("type") in ("game", "event", "nodes", "node", "score"):
            self._dirty.set()

    def _open(self) -> Any:
        return WebSocket.connect(stream_url(self.cfg.sync_url), {
            "Authorization": f"Bearer {self._key}", "User-Agent": f"atalaia-controller/{__version__}"},
            ca_file=self.cfg.sync_ca_file, timeout_s=self.cfg.sync_timeout_s)

    def _run(self) -> None:
        delay = BACKOFF_MIN_S
        while not self._stop.is_set():
            began = time.monotonic()
            refused = False
            ws = None
            try:
                ws = self._connect()
                self.connected, self.connected_at = True, self._wall()
                if self.last_error:
                    log.info("remote GM stream open again")
                self.last_error = None
                self.session(ws)
            except WsError as exc:
                refused = exc.code == AUTH_REFUSED or exc.status in (401, 403)
                why = "the site server refused the API key" if refused else str(exc)
                if why != self.last_error:
                    log.warning("remote GM stream: %s", why)
                self.last_error = why
            except Exception:  # noqa: BLE001  (never let the thread die)
                log.exception("remote GM stream failed")
                self.last_error = "failed"
            finally:
                self.connected = False
                if ws is not None:
                    ws.close()
            if refused:
                delay = BACKOFF_MAX_S
            elif time.monotonic() - began > 60:  # it worked for a while: start again from the shortest wait
                delay = BACKOFF_MIN_S
            if self._stop.wait(delay):
                break
            delay = min(delay * 2, BACKOFF_MAX_S)

    def envelope(self) -> dict[str, Any]:
        return {"sync_version": SYNC_VERSION, "controller": {"id": self._controller_id(), "version": __version__}}

    def _send(self, ws: Any, kind: str, body: dict[str, Any]) -> None:
        ws.send_text(json.dumps({"type": kind, **body}, separators=(",", ":"), ensure_ascii=False))

    def session(self, ws: Any) -> None:
        """One open stream: hello, then commands as they come and the live view as it changes."""
        self._send(ws, "hello", {**self.envelope(), "remote_gm": bool(self.cfg.sync_remote_gm)})
        last_live = last_ping = 0.0
        self._dirty.set()
        while not self._stop.is_set():
            raw = ws.recv(RECV_S)
            if raw is not None:
                self._on_message(ws, raw)
            now = time.monotonic()
            if (self._dirty.is_set() and now - last_live >= LIVE_MIN_S) or now - last_live >= LIVE_EVERY_S:
                self._dirty.clear()
                body = self.live_body()
                if body is not None:
                    self._send(ws, "live", body)
                    self.lives += 1
                last_live = now
            if now - last_ping >= PING_S:
                self._send(ws, "ping", {})
                last_ping = now

    def _on_message(self, ws: Any, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except ValueError:
            log.warning("remote GM stream: a message that is not JSON")
            return
        if not isinstance(msg, dict):
            return
        kind = msg.pop("type", None)
        if kind == "command":
            result = self.handle_command(msg)
            self._send(ws, "command.result", {**self.envelope(), **result})
            self._dirty.set()
        elif kind == "error":
            log.warning("remote GM stream: the site server refused a message (%s %s at %s)", msg.get("detail"),
                        msg.get("error", ""), msg.get("path", ""))

    # --- commands --------------------------------------------------------------------------

    def handle_command(self, body: Any) -> dict[str, Any]:
        """Checks and carries out one command; logs it in the store whatever came of it. Returns
        ``{"id", "code", "detail"}`` for ``command.result``."""
        self.commands += 1
        received = self._wall()
        cid = body.get("id") if isinstance(body, dict) else None
        try:
            cmd = check_command(copy.deepcopy(body))
        except SyncFormatError as exc:
            entry = {"command_id": None, "result": "invalid", "detail": str(exc)[:200]}
            if isinstance(body, dict):
                entry["command"] = body.get("command") if isinstance(body.get("command"), str) else None
            log.warning("remote GM: a command not in protocol/sync.md's form refused (%s)", exc)
            self.store.add_remote_command({**entry, "received_at": received})
            return {"id": cid if isinstance(cid, str) and len(cid) == 36 else "00000000-0000-0000-0000-000000000000",
                    "code": "invalid", "detail": entry["detail"]}
        prior = self.store.remote_command(cmd["id"])
        if prior is not None:  # never twice
            return {"id": cmd["id"], "code": prior["result"], "detail": prior["detail"]}
        entry = {"command_id": cmd["id"], "received_at": received, "user_id": cmd["user"]["id"],
                 "username": cmd["user"]["username"], "command": cmd["command"], "params": cmd["params"],
                 "game_id": cmd["game"]["game_id"], "game_seed": cmd["game"]["game_seed"]}
        if not self.cfg.sync_remote_gm:
            code, detail = "remote_gm_off", "[sync] remote_gm is off on this controller"
        elif abs(received - cmd["sent_at"]) > STALE_S:
            code, detail = "stale", f"sent {received - cmd['sent_at']:.0f} s ago by the site server's clock"
        else:
            code, detail = self._carry_out(cmd)
        row = self.store.add_remote_command({**entry, "result": code, "detail": detail})
        log.warning("remote GM %s (%s): %s %s on game %d: %s%s", cmd["user"]["username"], cmd["user"]["id"],
                    cmd["command"], json.dumps(cmd["params"], ensure_ascii=False), cmd["game"]["game_id"], code,
                    f" ({detail})" if detail and code != "done" else "")
        return {"id": cmd["id"], "code": row["result"], "detail": row["detail"]}

    def _carry_out(self, cmd: dict[str, Any]) -> tuple[str, Optional[str]]:
        ctrl = self.controller
        gid, seed = cmd["game"]["game_id"], cmd["game"]["game_seed"]
        game = ctrl.game
        if game is None or int(game["id"]) != gid or int(game["game_seed"]) != seed:
            return "not_live", f"game {gid} (seed {seed}) is not this controller's live game"
        params = cmd["params"]
        try:
            what = cmd["command"]
            if what == "start":
                out = ctrl.start_game(gid)
            elif what == "pause":
                out = ctrl.pause_game(gid, params.get("reason", ""))
            elif what == "resume":
                out = ctrl.resume_game(gid)
            elif what == "end":
                out = ctrl.end_game(gid, params.get("reason", ""))
            elif what == "message":
                sent = ctrl.send_node_cmd(BROADCAST, "message", {"text": params["text"]})
                return "done", f"sent to every node (seq {sent['seq']})"
            else:
                sent = ctrl.send_node_cmd(params["node"], "mode", {"name": params["name"]})
                return "done", f"sent to node {sent['node']} (seq {sent['seq']})"
        except NotFound as exc:
            return "not_found", str(exc)[:200]
        except Conflict as exc:
            return "conflict", str(exc)[:200]
        except Unavailable as exc:
            return "unavailable", str(exc)[:200]
        except ControllerError as exc:
            return "invalid", str(exc)[:200]
        except Exception:  # noqa: BLE001
            log.exception("remote GM: %s failed", cmd["command"])
            return "failed", "the controller could not carry it out (see its log)"
        return "done", f"game {gid} is {out.get('state')}"

    # --- the live view ---------------------------------------------------------------------

    def live_body(self) -> Optional[dict[str, Any]]:
        """The ``live`` message, checked; None (nothing sent) if it does not pass the shared check."""
        body = {**self.envelope(), "live": self.live()}
        try:
            return check_live(body)
        except SyncFormatError as exc:
            log.warning("remote GM: the live view is not in protocol/sync.md's form (%s): not sent", exc)
            return None

    def live(self) -> Optional[dict[str, Any]]:
        ctrl = self.controller
        game = ctrl.game
        if game is None:
            return None
        gid = int(game["id"])
        try:
            pub = ctrl.get_game(gid)
            totals = ctrl.score(gid)["teams"]
            nodes = ctrl.nodes(gid)
        except ControllerError:
            return None
        now = self._wall()
        env = {**self.envelope(), "game": {"game_id": gid, "game_seed": int(game["game_seed"])}}
        out_nodes = []
        for node in nodes:
            seen = node.get("last_seen")
            if seen is None:
                ago = node.get("seen_ms_ago")
                seen = now - ago / 1000 if isinstance(ago, (int, float)) else now
            entry = {"node_id": node["node_id"], "name": node.get("name") or f"node-{node['node_id']}",
                     "role": node.get("role") or "-", "last_seen": seen,
                     "info": {k: node[k] for k in NODE_INFO if node.get(k) is not None}}
            try:
                check_nodes({**env, "nodes": [entry]})
            except SyncFormatError:
                continue
            out_nodes.append(entry)
        events = []
        for ev in self.store.last_events(gid, MAX_LIVE_EVENTS):
            try:
                events.append(check_event(ev, "event"))
            except SyncFormatError:
                continue
        pkg = ctrl.modes.get(game["mode_id"])
        commands = pkg.mode.commands if pkg is not None else {}
        fc = ctrl.fc
        in_charge = bool(fc is not None and fc.is_controller and not ctrl.key_lost)
        return {"game": env["game"], "name": pub["name"], "mode_id": pub["mode_id"], "teams": list(pub["teams"]),
                "state": pub["state"], "in_charge": in_charge,
                "totals": {t: int(totals.get(t, 0)) for t in pub["teams"]},
                "game_time_ms": pub.get("game_time_ms"), "duration_ms": int(pub.get("duration_ms") or 0),
                "nodes": out_nodes, "events": events,
                "mode_commands": [{"name": n, "roles": list(spec.get("roles") or [])}
                                  for n, spec in sorted(commands.items())]}

    def status(self) -> dict[str, Any]:
        return {"enabled": bool(self.cfg.sync_remote_gm), "connected": self.connected,
                "connected_at": self.connected_at, "last_error": self.last_error, "commands": self.commands}
