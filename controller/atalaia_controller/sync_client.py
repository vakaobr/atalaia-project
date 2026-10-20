# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The site server sync: the controller pushes its games (ADR-P4-3 as amended, protocol/sync.md).

The controller opens every connection (it usually sits behind a phone's 4G
link and carrier-grade NAT, decision P4R12): this client sends HTTPS
requests to the site server's ``/api/v1/sync/*`` with the field's API key
in ``Authorization: Bearer``. The site server never connects to the
controller and holds none of its tokens.

**Offline first.** The client runs in its own thread and only reads the
SQLite store (it never takes the engine's lock), so a game runs the same
whether the site server is reachable or not. Every event is already in the
store (ADR-P2-9); the client sends, per game and in ``events.id`` order,
the events above the last id the site server acknowledged (``sync_state``,
store schema 5, decision P4R11), then the game's score counters per source
and its nodes when they changed. A cycle runs every ``interval_game_s``
(30 s) while a game runs and every ``interval_idle_s`` (5 min) between
games; a failure doubles the wait, up to ``interval_idle_s``; a ``Retry-After``
from the server is respected. A game's start, pause or end wakes the
client at once (unless it is backing off).

**Conflict-free.** Replays are harmless: the site server's unique key on
events is the controller's own, ``(game, node, seq, game time, type)``,
so a batch sent twice (a lost answer, a restart before the cursor was
saved, a standby controller's copy of the same events) is counted as
duplicates and nothing is doubled. Score counters merge by maximum per
(source, team); GM adjustments are ``score.delta`` events and may be
negative (P4R10).

**The field's chrono registry** (plan phase 14; ADR-P4-5 as amended, P4R14,
P4R15) goes after the games in every cycle: the marshals' public keys with
their periods (the current one and the earlier ones of ``marshal_key_history``,
store schema 6), then the replica registry, then the signed readings with
their series and outcomes, each reading's record as the text the controller
stored. ``sync_items`` keeps what was sent (each key's and replica's hash,
each reading's id), so a cycle sends only what is new or changed. Keys go
before readings, so the site server can verify every reading it gets; one it
cannot verify is kept apart there and named in the answer, never silently
dropped, and logged here. Private keys never leave the marshals' phones.

**Never sent:** positions (P4R25), check-in names and federation numbers,
tokens, the game, join and token keys, private keys. The bodies carry the fields listed in
protocol/sync.md only; a node's info goes through a list of allowed keys, and
every event is checked with ``sync_format.check_event`` before it is sent
(one that fails is skipped and counted, so it never stalls the queue).

The API key comes from ``[sync] api_key`` or ``ATALAIA_SYNC_API_KEY``, or is
kept in the store (mode 0600, like the tokens) by ``python3 -m
atalaia_controller sync-key``. The site server's certificate is checked
against the system's CAs, or against ``[sync] ca_file``; ``http://`` is
allowed only to this machine (tests, a local trial). Redirects are refused,
so the key is never sent to another address.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import logging
import re
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

from . import __version__
from .sync_format import (MAX_EVENTS, MAX_MARSHALS, MAX_READINGS, MAX_REPLICAS, SYNC_VERSION, SyncFormatError,
                          check_event, check_marshal, check_nodes, check_reading, check_replica)

log = logging.getLogger("atalaia.sync")

API_KEY = re.compile(r"[A-Za-z0-9_-]{43}")
KEY_SETTING = "sync.api_key"
ID_SETTING = "sync.controller_id"
BATCHES_PER_GAME = 20   # events batches per game and cycle (10,000 events), so one game cannot hold the rest
BATCHES_PER_KIND = 20   # chrono registry batches per kind and cycle
FIELD_RUN = re.compile(r"field-(\d{1,6})")
LIVE = ("running", "paused")


def api_key_ok(key: str) -> bool:
    """A key as the site server makes them: 32 random bytes, base64url without padding."""
    return isinstance(key, str) and API_KEY.fullmatch(key) is not None


def key_fingerprint(key: str) -> str:
    """The first 8 hex digits of the key's SHA-256: the site server lists keys by the same."""
    return hashlib.sha256(key.encode("ascii")).hexdigest()[:8]


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def url_problem(url: str) -> Optional[str]:
    """Why the site server's address is not usable, or None."""
    try:
        parts = urlsplit(url)
        parts.port  # noqa: B018  (raises ValueError for a bad port)
    except ValueError:
        return "not a valid URL"
    if parts.scheme not in ("https", "http") or not parts.hostname:
        return "an https:// address such as https://site.example.org"
    if parts.username or parts.password or parts.query or parts.fragment:
        return "no user, password, query or fragment in the address"
    if parts.scheme == "http" and not _loopback(parts.hostname):
        return "https:// is required (http:// only to this machine)"
    return None


def resolve_api_key(cfg: Any, store: Any) -> tuple[Optional[str], Optional[str]]:
    """The key and where it came from: the settings (TOML or ATALAIA_SYNC_API_KEY) or the store."""
    if cfg.sync_api_key:
        return cfg.sync_api_key, "config"
    stored = store.get_setting(KEY_SETTING)
    if stored and api_key_ok(stored):
        return stored, "stored"
    return None, None


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


class SyncError(Exception):
    """A request did not go through: ``code`` says why; ``retry_after`` (s) when the server said."""

    def __init__(self, code: str, status: Optional[int] = None, retry_after: Optional[float] = None,
                 detail: Any = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.retry_after = retry_after
        self.detail = detail


def _refusal(exc: SyncError) -> tuple[str, str]:
    """A 400's format error and where it is (protocol/sync.md's error body)."""
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    return str(detail.get("error") or exc.code), str(detail.get("path") or "the body")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None  # the redirect comes back as an HTTPError; the key never goes elsewhere


class HttpTransport:
    """JSON POSTs to the site server with urllib (no dependency beyond the standard library)."""

    def __init__(self, base_url: str, api_key: str, *, ca_file: str = "", timeout_s: float = 15.0,
                 user_agent: str = f"atalaia-controller/{__version__}") -> None:
        self.base_url = base_url.rstrip("/")
        self._auth = f"Bearer {api_key}"
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        context = ssl.create_default_context(cafile=ca_file or None)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        self._opener = urllib.request.build_opener(_NoRedirect, urllib.request.HTTPSHandler(context=context))

    def post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, method="POST", headers={
            "Authorization": self._auth, "Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": self.user_agent})
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                raw = resp.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read(64 * 1024) or b"{}")
            except ValueError:
                detail = {}
            retry = exc.headers.get("Retry-After") if exc.headers else None
            code = detail.get("detail") if isinstance(detail, dict) and isinstance(detail.get("detail"), str) \
                else f"http_{exc.code}"
            raise SyncError(code, exc.code, float(retry) if retry and retry.isdigit() else None,
                            detail) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as exc:
            raise SyncError("unreachable", detail=str(getattr(exc, "reason", exc))) from None
        try:
            answer = json.loads(raw)
        except ValueError:
            raise SyncError("bad_answer") from None
        if not isinstance(answer, dict):
            raise SyncError("bad_answer")
        return answer


class SyncClient:
    """Pushes the store's games to the site server; ``start`` runs it in a thread."""

    def __init__(self, cfg: Any, store: Any, *, api_key: Optional[str] = None,
                 transport: Optional[Any] = None, wall: Callable[[], float] = time.time) -> None:
        self.cfg = cfg
        self.store = store
        key, source = (api_key, "given") if api_key else resolve_api_key(cfg, store)
        self.key_source = source
        self.key_fingerprint = key_fingerprint(key) if key else None
        self.transport = transport or (HttpTransport(cfg.sync_url, key, ca_file=cfg.sync_ca_file,
                                                     timeout_s=cfg.sync_timeout_s) if key else None)
        self._wall = wall
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()  # one cycle at a time (the thread, a test's run_once)
        self.failures = 0
        self.retry_after: Optional[float] = None
        self.last_ok_at: Optional[float] = None
        self.last_attempt_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self.registry_error: Optional[str] = None  # the last refusal of a chrono registry body
        self.refused_readings = 0  # readings the site server kept apart (it could not verify them)
        self.requests = 0

    # --- identity ---------------------------------------------------------------------

    @property
    def controller_id(self) -> str:
        """This controller's id on the site server: random, made once, kept in the store."""
        cid = self.store.get_setting(ID_SETTING)
        if not cid:
            cid = str(uuid.uuid4())
            self.store.set_setting(ID_SETTING, cid)
        return cid

    def _envelope(self, game: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """The common part of a body; without a game for the field's chrono registry."""
        env: dict[str, Any] = {"sync_version": SYNC_VERSION,
                               "controller": {"id": self.controller_id, "version": __version__}}
        if game is not None:
            env["game"] = {"game_id": int(game["id"]), "game_seed": int(game["game_seed"])}
        return env

    # --- the thread ---------------------------------------------------------------------

    def start(self) -> None:
        if self.transport is None:
            log.error("sync is on but there is no API key: set [sync] api_key or ATALAIA_SYNC_API_KEY, "
                      "or store one with: python3 -m atalaia_controller sync-key")
            self.last_error = "no_api_key"
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="site-sync", daemon=True)
        self._thread.start()
        log.info("syncing with %s (key %s, %s)", self.cfg.sync_url, self.key_fingerprint, self.key_source)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=self.cfg.sync_timeout_s + 2)
            self._thread = None

    def kick(self) -> None:
        """Sync soon (a game started, paused or ended), unless the client is backing off."""
        if self.failures == 0:
            self._wake.set()

    def on_controller_message(self, msg: dict[str, Any]) -> None:
        """The engine's listener: a game's state changed, or a chrono series was judged."""
        if msg.get("type") in ("game", "chrono_list"):
            self.kick()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_once()
            except Exception:  # noqa: BLE001  (never let the thread die: the next cycle tries again)
                log.exception("sync cycle failed")
                self.failures += 1
            self._wake.wait(self.next_delay())
            self._wake.clear()

    def next_delay(self) -> float:
        game = self.store.live_game()
        base = self.cfg.sync_interval_game_s if game and game["state"] in LIVE else self.cfg.sync_interval_idle_s
        delay = base if self.failures == 0 else min(base * 2 ** self.failures, self.cfg.sync_interval_idle_s)
        delay = max(delay, base)
        if self.retry_after:
            delay = max(delay, min(self.retry_after, 3600.0))
        return delay

    # --- one cycle ----------------------------------------------------------------------

    def run_once(self) -> bool:
        """One pass over every game; True when everything that was due went through."""
        if self.transport is None:
            return False
        with self._lock:
            self.last_attempt_at = self._wall()
            try:
                for game in self.store.games():
                    self._sync_game(game)
                self._sync_registry()
            except SyncError as exc:
                self.failures += 1
                self.retry_after = exc.retry_after
                if exc.code != self.last_error:
                    if exc.status in (401, 403):
                        log.error("the site server refused the API key (%s): check [sync] api_key", exc.code)
                    else:
                        log.warning("sync failed (%s); retrying in %.0f s", exc.code, self.next_delay())
                self.last_error = exc.code
                return False
            if self.failures:
                log.info("sync works again after %d failed attempts", self.failures)
            self.failures = 0
            self.retry_after = None
            self.last_error = None
            self.last_ok_at = self._wall()
            return True

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        self.requests += 1
        return self.transport.post(path, body)

    def _bound(self, game: dict[str, Any], path: str, body: dict[str, Any]) -> dict[str, Any]:
        """A request about a game the site server may not have (yet, or any more): the game's
        metadata goes first, then the request again."""
        try:
            return self._post(path, body)
        except SyncError as exc:
            if exc.code != "game_not_found":
                raise
        self._post("/api/v1/sync/games", {**self._envelope(game), "meta": self.meta(game)})
        self.store.save_sync_state(game["id"], game["game_seed"], meta_sha=digest(self.meta(game)))
        return self._post(path, body)

    def _sync_game(self, game: dict[str, Any]) -> None:
        gid, seed = game["id"], game["game_seed"]
        state = self.store.sync_state(gid, seed)
        if state["final"]:
            return
        env = self._envelope(game)
        refused = sent = False  # a refused body is kept as sent: it goes again only once it changes
        meta = self.meta(game)
        if digest(meta) != state["meta_sha"]:
            refused |= self._rejected(gid, seed, "/api/v1/sync/games", {**env, "meta": meta})
            self.store.save_sync_state(gid, seed, meta_sha=digest(meta))
            sent = True
        acked = self._push_events(game, env, state)
        sent |= acked is not None and acked != state["acked_id"]
        counters = self.counters(game)
        if counters and digest(counters) != state["scores_sha"]:
            refused |= self._rejected(gid, seed, "/api/v1/sync/scores", {**env, "counters": counters}, game)
            self.store.save_sync_state(gid, seed, scores_sha=digest(counters))
            sent = True
        nodes = self.nodes(game)
        if nodes and digest(nodes) != state["nodes_sha"]:
            refused |= self._rejected(gid, seed, "/api/v1/sync/nodes", {**env, "nodes": nodes}, game)
            self.store.save_sync_state(gid, seed, nodes_sha=digest(nodes))
            sent = True
        if acked is None:
            refused = True
        # An ended game with everything through is not looked at again (until sync-key --resend).
        final = (not refused and game["state"] == "ended" and acked is not None
                 and self.store.count_events_after(gid, acked) == 0)
        changes: dict[str, Any] = {"final": final, "last_ok_at": self._wall()}
        if sent and not refused:
            changes["last_error"] = None
        self.store.save_sync_state(gid, seed, **changes)

    def _rejected(self, gid: int, seed: int, path: str, body: dict[str, Any],
                  game: Optional[dict[str, Any]] = None) -> bool:
        """Sends one body; a 400 (it does not follow protocol/sync.md) is logged and kept in the game's
        ``last_error``. The caller keeps it as sent, so it goes again only once it changes and never
        blocks the rest. True when it was refused."""
        try:
            if game is None:
                self._post(path, body)
            else:
                self._bound(game, path, body)
            return False
        except SyncError as exc:
            if exc.status != 400:
                raise
            code, where = _refusal(exc)
            log.error("the site server refused %s for game %d (%s at %s)", path, gid, code, where)
            self.store.save_sync_state(gid, seed, last_error=f"{path}: {code} at {where}")
            return True

    def _push_events(self, game: dict[str, Any], env: dict[str, Any], state: dict[str, Any]) -> Optional[int]:
        """Sends the events above the cursor; returns the new cursor (None: refused, retried later)."""
        gid, seed = game["id"], game["game_seed"]
        acked, skipped = state["acked_id"], state["skipped"]
        for _ in range(BATCHES_PER_GAME):
            rows = self.store.events_after(gid, acked, MAX_EVENTS)
            if not rows:
                break
            batch = []
            for row in rows:
                try:
                    batch.append(check_event(dict(row), "event"))
                except SyncFormatError as exc:
                    skipped += 1
                    log.warning("game %d: event %d (%s) not sent: %s", gid, row["id"], row.get("type"), exc)
            if batch:
                body = {**env, "after_id": acked, "events": batch}
                try:
                    answer = self._bound(game, "/api/v1/sync/events", body)
                except SyncError as exc:
                    if exc.status != 400:
                        raise
                    code, where = _refusal(exc)
                    log.error("the site server refused events of game %d (%s at %s)", gid, code, where)
                    self.store.save_sync_state(gid, seed, last_error=f"/api/v1/sync/events: {code} at {where}")
                    return None
                if answer.get("acked_id") != batch[-1]["id"]:
                    raise SyncError("bad_answer", detail=answer)
            acked = rows[-1]["id"]
            self.store.save_sync_state(gid, seed, acked_id=acked, skipped=skipped)
            if len(rows) < MAX_EVENTS:
                break
        return acked

    # --- the field's chrono registry (plan phase 14) ----------------------------------------

    def _sync_registry(self) -> None:
        """Marshal keys, then replicas, then readings: what is new or changed since the last cycle."""
        env = self._envelope()
        self._push_items("marshal", "/api/v1/sync/marshals", "marshals", self.marshal_entries(), MAX_MARSHALS, env)
        self._push_items("replica", "/api/v1/sync/replicas", "replicas", self.replica_entries(), MAX_REPLICAS, env)
        self._push_readings(env)

    def _registry_refused(self, path: str, exc: SyncError) -> None:
        """A 400 for a registry body: logged and kept; the body counts as sent, so it never blocks the rest."""
        if exc.status != 400:
            raise exc
        code, where = _refusal(exc)
        log.error("the site server refused %s (%s at %s)", path, code, where)
        self.registry_error = f"{path}: {code} at {where}"

    def _push_items(self, kind: str, path: str, field: str, entries: dict[str, dict[str, Any]], limit: int,
                    env: dict[str, Any]) -> None:
        sent = self.store.sync_items(kind)
        due = {item: entry for item, entry in entries.items() if digest(entry) != sent.get(item)}
        items = list(due.items())
        for start in range(0, min(len(items), limit * BATCHES_PER_KIND), limit):
            chunk = dict(items[start:start + limit])
            try:
                self._post(path, {**env, field: list(chunk.values())})
            except SyncError as exc:
                self._registry_refused(path, exc)
            self.store.mark_synced(kind, {item: digest(entry) for item, entry in chunk.items()})

    def _push_readings(self, env: dict[str, Any]) -> None:
        for _ in range(BATCHES_PER_KIND):
            rows = self.store.readings_unsynced(MAX_READINGS)
            if not rows:
                return
            batch = []
            for row in rows:
                entry = {"record": row["record_json"], "series_id": row["series_id"], "outcome": row["outcome"],
                         "received_at": row["received_at"]}
                seed = self._game_seed(row["game_id"])
                if seed is not None:
                    entry["game_seed"] = seed
                try:
                    batch.append(check_reading(entry))
                except SyncFormatError as exc:
                    log.warning("chrono reading %s not sent: %s", row["reading_id"], exc)
            if batch:
                try:
                    answer = self._post("/api/v1/sync/chrono", {**env, "readings": batch})
                except SyncError as exc:
                    self._registry_refused("/api/v1/sync/chrono", exc)
                    answer = {}
                refused = answer.get("refused") if isinstance(answer.get("refused"), list) else []
                for item in refused:
                    if isinstance(item, dict):
                        log.error("the site server could not verify chrono reading %s (%s): it keeps it apart",
                                  item.get("reading_id"), item.get("reason"))
                self.refused_readings += len(refused)
            self.store.mark_synced("reading", {r["reading_id"]: r["reading_id"] for r in rows})
            if len(rows) < MAX_READINGS:
                return

    def _game_seed(self, game_id: Optional[str]) -> Optional[int]:
        """The seed of the reading's game in this store (the site server links the reading to it)."""
        if not game_id or not game_id.isdigit() or int(game_id) > 0xFFFF:
            return None
        game = self.store.game(int(game_id))
        return int(game["game_seed"]) if game and game.get("game_seed") is not None else None

    def marshal_entries(self) -> dict[str, dict[str, Any]]:
        """Each marshal key once, by (marshal, key): its first registration and, for an earlier key,
        when it was last replaced. Public keys only: the private keys are on the marshals' phones."""
        import base64  # noqa: PLC0415

        out: dict[str, dict[str, Any]] = {}
        rows = [{**h, "current": False} for h in self.store.marshal_key_history()]
        rows += [{**m, "current": True, "replaced_at": None} for m in self.store.marshals()]
        for row in rows:  # oldest first, the current keys last
            key = base64.b64encode(row["public_key"]).decode("ascii")
            item = f"{row['marshal_id']}:{key}"
            entry = out.get(item)
            if entry is None:
                entry = {"marshal_id": row["marshal_id"], "public_key": key, "registered_at": row["registered_at"],
                         "replaced_at": None}
                out[item] = entry
            entry["name"] = row["name"]
            entry["player_id"] = row["player_id"]
            entry["registered_at"] = min(entry["registered_at"], row["registered_at"])
            if row["current"]:
                entry["replaced_at"] = None
            else:
                entry["replaced_at"] = max(entry["replaced_at"] or 0, row["replaced_at"])
        for item, entry in list(out.items()):
            try:
                check_marshal(dict(entry), "marshal")
            except SyncFormatError as exc:
                log.warning("marshal key %s not sent: %s", entry["marshal_id"], exc)
                del out[item]
        return out

    def replica_entries(self) -> dict[str, dict[str, Any]]:
        """The replica registry as protocol/sync.md lists it; a replica out of that form is not sent."""
        out: dict[str, dict[str, Any]] = {}
        for rep in self.store.replicas():
            entry = {k: rep[k] for k in ("replica_id", "owner_player_id", "type", "class", "make_model",
                                         "registered_at", "tag_type", "tag_uid") if rep.get(k) is not None}
            try:
                out[entry["replica_id"]] = check_replica(dict(entry))
            except (SyncFormatError, KeyError) as exc:
                log.warning("replica %s not sent: %s", rep.get("replica_id"), exc)
        return out

    # --- what is sent -------------------------------------------------------------------

    def meta(self, game: dict[str, Any]) -> dict[str, Any]:
        """A game's metadata: never its key, assignments or check-ins."""
        info = {}
        for team, entry in (game.get("team_info") or {}).items():
            if team in game["teams"] and isinstance(entry, dict):
                kept = {k: entry[k] for k in ("display_name", "crest_id") if entry.get(k) is not None}
                if kept:
                    info[team] = kept
        return {"name": game["name"], "mode_id": game["mode_id"], "teams": list(game["teams"]),
                "team_info": info, "params": game.get("params") or {}, "squads": int(game.get("squads") or 0),
                "duration_ms": int(game.get("duration_ms") or 0), "state": game["state"],
                "node_id": game.get("node_id"), "joined": bool(game.get("joined")),
                "created_at": game["created_at"], "started_at": game.get("started_at"),
                "ended_at": game.get("ended_at")}

    def counters(self, game: dict[str, Any]) -> dict[str, dict[str, int]]:
        """The game's score counters per source, as the controller merges them (P4R10): each node's
        counters as it last reported them, and each run of this controller's field script, qualified
        by this controller's node id in the game (decision S13-3)."""
        teams = set(game["teams"])

        def positive(values: Any) -> dict[str, int]:
            if not isinstance(values, dict):
                return {}
            return {t: v for t, v in values.items() if t in teams and isinstance(v, int)
                    and not isinstance(v, bool) and 0 < v < 2**31}

        out: dict[str, dict[str, int]] = {}
        for node in self.store.nodes(game["id"]):
            values = positive(node.get("score"))
            if values:
                out[f"node-{node['node_id']}"] = values
        me = game.get("node_id")
        me = self.cfg.node_id if me is None else int(me)
        try:
            runs = json.loads(self.store.get_setting(f"field_scores:{game['id']}") or "{}")
        except ValueError:
            runs = {}
        for key, values in (runs.items() if isinstance(runs, dict) else ()):
            values = positive(values)
            if FIELD_RUN.fullmatch(str(key)) and values:
                out[f"{key}@{me}"] = values
        return out

    def nodes(self, game: dict[str, Any]) -> list[dict[str, Any]]:
        """The game's nodes: name, role, last seen and the health fields of protocol/sync.md only."""
        from .sync_format import NODE_INFO  # noqa: PLC0415

        out = []
        for node in self.store.nodes(game["id"]):
            entry = {"node_id": node["node_id"], "name": node["name"], "role": node["role"],
                     "last_seen": node["last_seen"], "info": {k: node[k] for k in NODE_INFO if k in node}}
            try:
                check_nodes({**self._envelope(game), "nodes": [entry]})
            except SyncFormatError as exc:
                log.warning("game %d: node %s not sent: %s", game["id"], node["node_id"], exc)
                continue
            out.append(entry)
        return out

    # --- status ------------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        pending = 0
        for game in self.store.games():
            state = self.store.sync_state(game["id"], game["game_seed"])
            if not state["final"]:
                pending += self.store.count_events_after(game["id"], state["acked_id"])
        return {"enabled": True, "url": self.cfg.sync_url, "key": self.key_source,
                "key_fingerprint": self.key_fingerprint, "controller_id": self.controller_id,
                "last_ok_at": self.last_ok_at, "last_attempt_at": self.last_attempt_at,
                "last_error": self.last_error, "failures": self.failures, "pending_events": pending,
                "pending_readings": self.store.count_readings_unsynced(), "registry_error": self.registry_error,
                "refused_readings": self.refused_readings}
