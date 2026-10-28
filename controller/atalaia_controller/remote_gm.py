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
  game's declared mode commands) exist; ``start`` takes an optional ``force``
  (the console's "Start anyway", decision RG-1); the controller checks each with the
  shared ``sync_format.check_command``, refuses one for another game than its
  live one, one sent more than 60 s ago (by the site server's clock), one it
  already had (by its id), and any command when ``remote_gm`` is off, and carries
  out the rest through the engine exactly as the console's GM token would
  (a standby controller refuses, a paused game does not pause again).
- ``command.result`` back: ``done`` or why not. A ``start`` refused because roles
  of the game have no joined node comes back as ``conflict`` with those roles in
  ``missing``, so the site server's page can ask "Start anyway?" and send it
  again with ``force`` (decision RG-1; the guard itself is RJ-1).

The same stream carries the remote ATAK relay (Phase 4 follow-up, decisions
FU5-*): with ``[atak] remote = true`` the controller opens it even with
``remote_gm`` off, says ``atak: true`` in its ``hello``, and once the site
server's ``hello.ack`` says ``atak_relay: true`` pushes the CoT events its
emitter makes (``atak.py``: the boxes and the extraction zone; player
positions only with ``[atak] remote_players = true``) as ``cot`` messages. The
site server relays them to the field's enrolled ATAK devices; it never connects
to the controller. With ``remote_gm`` off no ``live`` view is sent and every
command is refused, as before.

With ``[sync] branding = "site"`` or ``[sync] library`` on (the default; PKD-1) the controller opens the
stream too (BR24), even with both of those off: it then sends only ``hello`` (``remote_gm: false``) and
pings, and the site server sends a ``field.changed`` note whenever the field's branding, saved teams or
check-in settings change (no ``what``), or its scenario library (``what: ["library"]``) or schedule
(``["schedule"]``) do, on which the sync client pulls them at once instead of at its next cycle. A site
server that never sends it (an older one) leaves the pull to the cycle, as before.

Every command, carried out or refused, is in the store's ``remote_commands``
(store schema 8): who sent it (the site server's account id and username),
what it asked for, the game and the result; ``GET /api/v1/remote-gm`` shows
them to the GM. The site server logs the same in its audit log.

The client reconnects after a failure, waiting 5 s and doubling up to 5 min
(5 min at once when the API key is refused). Without a key, or with the sync
off, nothing starts.
"""

from __future__ import annotations

import collections
import copy
import json
import logging
import threading
import time
from typing import Any, Callable, Optional
from urllib.parse import urlsplit, urlunsplit

from . import __version__
from .engine import Conflict, ControllerError, NotFound, StartBlocked, Unavailable
from .sync_format import (MAX_COT_EVENTS, MAX_LIVE_EVENTS, MISSING_MAX, NODE_INFO, ROLE_MAX, STALE_S, SYNC_VERSION, SyncFormatError,
                          check_command, check_event, check_field_changed, check_live, check_nodes, check_positions)
from .positions import Positions
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
POSITIONS_MIN_S = 5.0     # changed positions go at most this often (PKD-5)
POSITIONS_EVERY_S = 30.0  # and, while there are any, at least this often (their ages are fresh)
COT_QUEUE_MAX = 500  # CoT events waiting for the stream; older ones go first (the next full cycle resends)


def _positions_digest(body: dict[str, Any]) -> str:
    """What changed in a ``positions`` body, without the ages (they change every second)."""
    rows = [{k: v for k, v in item.items() if k != "age_s"} for item in body["positions"]]
    return json.dumps([body["game"], rows], sort_keys=True)


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
        self._pos_dirty = threading.Event()
        self._pos_digest: Optional[str] = None  # what the site server has of the positions (never logged)
        self.positions_sent = 0
        self._thread: Optional[threading.Thread] = None
        self.connected = False
        self.connected_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.commands = 0  # commands received (carried out or not)
        self.lives = 0
        # The remote ATAK relay (FU5): events waiting to go, whether the site server takes them on this socket,
        # and the emitter's hook to send its whole picture again on a new socket.
        self._cot: collections.deque[str] = collections.deque(maxlen=COT_QUEUE_MAX)
        self.atak_relay = False
        self.on_relay_open: Optional[Callable[[], None]] = None
        # The site server's ``field.changed`` (BR24, PKD-1): the sync client pulls what changed at once.
        self.on_field_changed: Optional[Callable[[Optional[list[str]]], None]] = None
        self.cot_sent = 0

    # --- the thread ------------------------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="remote-gm", daemon=True)
        self._thread.start()
        if self.cfg.sync_remote_gm:
            log.warning("remote GM is on: users with the gm role on this field at %s may act on the live game",
                        self.cfg.sync_url)
        if not self.cfg.sync_remote_gm and not self.cfg.atak_remote:
            log.info("stream open for the site server's notes on the field's branding, library and schedule "
                     "(nothing of the game leaves)")
        if self.cfg.atak_remote:
            log.warning("remote ATAK is on: this field's CoT events go to %s for its enrolled ATAK devices%s",
                        self.cfg.sync_url, ", player positions included"
                        if self.cfg.atak_remote_players else "")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.cfg.sync_timeout_s + 2)
            self._thread = None

    def on_controller_message(self, msg: dict[str, Any]) -> None:
        """The engine's listener: something the live view shows changed."""
        if msg.get("type") in ("game", "event", "nodes", "node", "score") and not msg.get("tick"):
            self._dirty.set()  # (a projected-score tick, decision BSC-2, is not in the site's live view)
        if msg.get("type") in ("player_position", "positions", "game"):
            self._pos_dirty.set()

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
                self.atak_relay = False
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
        """One open stream: hello, then commands as they come, the live view as it changes (remote GM on) and
        the CoT events as the emitter makes them (remote ATAK on and taken by the site server)."""
        hello = {**self.envelope(), "remote_gm": bool(self.cfg.sync_remote_gm)}
        if self.cfg.atak_remote:
            hello["atak"] = True  # only then: an older site server refuses a hello with a field it does not know
        self._send(ws, "hello", hello)
        self.atak_relay = False
        self._cot.clear()
        last_live = last_ping = last_pos = 0.0
        self._dirty.set()
        self._pos_dirty.set()
        self._pos_digest = None
        while not self._stop.is_set():
            raw = ws.recv(RECV_S)
            if raw is not None:
                self._on_message(ws, raw)
            self._send_cot(ws)
            now = time.monotonic()
            due = (self._dirty.is_set() and now - last_live >= LIVE_MIN_S) or now - last_live >= LIVE_EVERY_S
            if due and self.cfg.sync_remote_gm:  # no live view leaves the field without the remote GM
                self._dirty.clear()
                body = self.live_body()
                if body is not None:
                    self._send(ws, "live", body)
                    self.lives += 1
                last_live = now
            if self.cfg.sync_remote_gm:
                last_pos = self._send_positions(ws, now, last_pos)
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
        if kind == "hello.ack":
            wanted = bool(self.cfg.atak_remote)
            self.atak_relay = wanted and msg.get("atak_relay") is True
            if wanted and not self.atak_relay:
                log.warning("remote ATAK: the site server does not relay CoT (its ATAK relay is off): nothing sent")
            elif self.atak_relay and self.on_relay_open is not None:
                self.on_relay_open()  # the emitter sends its whole picture again
        elif kind == "field.changed":
            try:
                check_field_changed(msg)
            except SyncFormatError:
                log.warning("remote GM stream: a field.changed note in a form this controller does not know")
            else:
                if self.on_field_changed is not None:
                    self.on_field_changed(msg.get("what"))
        elif kind == "command":
            result = self.handle_command(msg)
            self._send(ws, "command.result", {**self.envelope(), **result})
            self._dirty.set()
        elif kind == "error":
            log.warning("remote GM stream: the site server refused a message (%s %s at %s)", msg.get("detail"),
                        msg.get("error", ""), msg.get("path", ""))

    # --- the remote ATAK relay (FU5) ---------------------------------------------------------

    def push_cot(self, events: list[bytes]) -> int:
        """The emitter's events for the relay: queued while the site server takes them, else dropped (the
        emitter's next full cycle sends everything again). Returns how many were queued."""
        if not self.connected or not self.atak_relay:
            return 0
        for data in events:
            self._cot.append(data.decode("utf-8"))
        return len(events)

    def _send_cot(self, ws: Any) -> None:
        while self._cot and self.atak_relay:
            batch: list[str] = []
            while self._cot and len(batch) < MAX_COT_EVENTS:
                batch.append(self._cot.popleft())
            self._send(ws, "cot", {**self.envelope(), "events": batch})
            self.cot_sent += len(batch)

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
            missing = None
        elif abs(received - cmd["sent_at"]) > STALE_S:
            code, detail = "stale", f"sent {received - cmd['sent_at']:.0f} s ago by the site server's clock"
            missing = None
        else:
            code, detail, missing = self._carry_out(cmd)
        row = self.store.add_remote_command({**entry, "result": code, "detail": detail})
        log.warning("remote GM %s (%s): %s %s on game %d: %s%s", cmd["user"]["username"], cmd["user"]["id"],
                    cmd["command"], json.dumps(cmd["params"], ensure_ascii=False), cmd["game"]["game_id"], code,
                    f" ({detail})" if detail and code != "done" else "")
        out = {"id": cmd["id"], "code": row["result"], "detail": row["detail"]}
        if missing:
            out["missing"] = missing
        return out

    def _carry_out(self, cmd: dict[str, Any]) -> tuple[str, Optional[str], Optional[list[str]]]:
        """``(code, detail, missing)``: ``missing`` names the roles without a joined node when a start was
        refused for that (the console's ``start_check``), else None."""
        ctrl = self.controller
        gid, seed = cmd["game"]["game_id"], cmd["game"]["game_seed"]
        game = ctrl.game
        if game is None or int(game["id"]) != gid or int(game["game_seed"]) != seed:
            return "not_live", f"game {gid} (seed {seed}) is not this controller's live game", None
        params = cmd["params"]
        forced: list[str] = []
        try:
            what = cmd["command"]
            if what == "start":
                force = params.get("force") is True
                if force:
                    forced = list(ctrl.start_check()["missing"])
                out = ctrl.start_game(gid, force=force)
            elif what == "pause":
                out = ctrl.pause_game(gid, params.get("reason", ""))
            elif what == "resume":
                out = ctrl.resume_game(gid)
            elif what == "end":
                out = ctrl.end_game(gid, params.get("reason", ""))
            elif what == "message":
                sent = ctrl.send_node_cmd(BROADCAST, "message", {"text": params["text"]})
                return "done", f"sent to every node (seq {sent['seq']})", None
            else:
                sent = ctrl.send_node_cmd(params["node"], "mode", {"name": params["name"]})
                return "done", f"sent to node {sent['node']} (seq {sent['seq']})", None
        except NotFound as exc:
            return "not_found", str(exc)[:200], None
        except StartBlocked as exc:
            missing = [str(r)[:ROLE_MAX] for r in exc.check.get("missing", [])][:MISSING_MAX]
            return "conflict", str(exc)[:200], missing or None
        except Conflict as exc:
            return "conflict", str(exc)[:200], None
        except Unavailable as exc:
            return "unavailable", str(exc)[:200], None
        except ControllerError as exc:
            return "invalid", str(exc)[:200], None
        except Exception:  # noqa: BLE001
            log.exception("remote GM: %s failed", cmd["command"])
            return "failed", "the controller could not carry it out (see its log)", None
        if forced:  # the console's "Start anyway", by a remote GM: also in this command's log entry
            return "done", f"game {gid} is {out.get('state')}, started anyway without nodes for: {', '.join(forced)}"[:200], None
        return "done", f"game {gid} is {out.get('state')}", None

    # --- the live view ---------------------------------------------------------------------

    def live_body(self) -> Optional[dict[str, Any]]:
        """The ``live`` message, checked; None (nothing sent) if it does not pass the shared check."""
        body = {**self.envelope(), "live": self.live()}
        try:
            return check_live(body)
        except SyncFormatError as exc:
            log.warning("remote GM: the live view is not in protocol/sync.md's form (%s): not sent", exc)
            return None

    def _send_positions(self, ws: Any, now: float, last: float) -> float:
        """The live game's player positions for the remote GM (PKD-5), when they changed (at most every 5 s) or,
        while there are any, every 30 s so their ages stay fresh; an empty list once when the last one is gone
        or the game ends. Returns the time of the last send. Never logged."""
        if not ((self._pos_dirty.is_set() and now - last >= POSITIONS_MIN_S) or now - last >= POSITIONS_EVERY_S):
            return last
        self._pos_dirty.clear()
        body = self.positions_body()
        if body is None:
            return now
        same = self._pos_digest == _positions_digest(body)
        if same and not body["positions"]:
            return now  # nothing then, nothing now
        if same and now - last < POSITIONS_EVERY_S:
            return last
        self._pos_digest = _positions_digest(body)
        self._send(ws, "positions", body)
        self.positions_sent += 1
        return now

    def positions_body(self) -> Optional[dict[str, Any]]:
        """The ``positions`` message, checked; None (nothing sent) if it does not pass the shared check."""
        body = {**self.envelope(), **self.positions()}
        try:
            return check_positions(body)
        except SyncFormatError as exc:
            log.warning("remote GM: the positions are not in protocol/sync.md's form (%s): not sent", exc.code)
            return None

    def positions(self) -> dict[str, Any]:
        """``{game, positions}``: the live game's positions the GM sees (a GM sees everyone's, positions.py), the
        latest of each player, none older than three reporting intervals; ``game`` null when none is live."""
        ctrl = self.controller
        game = ctrl.game
        if game is None or game["state"] not in ("running", "paused"):
            return {"game": None, "positions": []}
        now = self._wall()
        teams = list(game.get("teams") or [])
        stale = 3 * Positions.interval(game)
        items: list[dict[str, Any]] = []
        for pid, pos in ctrl.store.player_positions(int(game["id"])).items():
            age = max(0.0, now - float(pos.get("received_at") or now))
            if age > stale:
                continue
            item: dict[str, Any] = {"player_id": pid, "source": pos.get("source"), "age_s": round(age, 1)}
            team_id = pos.get("team")
            if isinstance(team_id, int) and 1 <= team_id <= len(teams):
                item["team"] = teams[team_id - 1]
            if isinstance(pos.get("squad"), int) and pos["squad"] > 0:
                item["squad"] = pos["squad"]
            role = (ctrl.store.checkin(int(game["id"]), pid) or {}).get("role")
            if isinstance(role, str) and role:
                item["role"] = role
            if isinstance(pos.get("level"), int):
                item["level"] = pos["level"]
            if pos.get("source") == "gps":
                item.update({k: pos[k] for k in ("lat", "lon") if pos.get(k) is not None})
                if pos.get("accuracy_m") is not None:
                    item["accuracy_m"] = pos["accuracy_m"]
            else:
                for key in ("room", "zone", "x", "y"):
                    if pos.get(key) is not None:
                        item[key] = pos[key]
            items.append(item)
        return {"game": {"game_id": int(game["id"]), "game_seed": int(game["game_seed"])}, "positions": items}

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
            info = {k: node[k] for k in NODE_INFO if node.get(k) is not None}
            if isinstance(info.get("capabilities"), list):  # integer ids as texts (decision PE24-121)
                info["capabilities"] = [str(c) for c in info["capabilities"]]
            entry = {"node_id": node["node_id"], "name": node.get("name") or f"node-{node['node_id']}",
                     "role": node.get("role") or "-", "last_seen": seen, "info": info}
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
                "connected_at": self.connected_at, "last_error": self.last_error, "commands": self.commands,
                "atak": {"enabled": bool(self.cfg.atak_remote), "relay": self.atak_relay,
                         "sent": self.cot_sent}}
