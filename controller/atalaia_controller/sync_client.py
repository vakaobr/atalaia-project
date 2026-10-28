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

**Game day** (plan phase 16; ADR-P4-11): after the pushes, the client pulls
the field's schedule of the coming days (``GET /api/v1/sync/schedule``, kept in
the store for the GM's *Create from the schedule*), the roster of each
scheduled game a game here was made from while that game has not started
(``GET /api/v1/sync/roster``, applied by ``Checkin.apply_roster`` as expected
check-ins; with it, other fields' signed chrono records of those players that
their person consented to share, ``GET /api/v1/sync/chrono``, kept apart from the
field's own readings by ``Checkin.apply_shared_chrono`` and shown marked as from
another field, never judged and never sent back: decision S14-5), and accounts' claims of this field's player ids (``GET
/api/v1/sync/claims``), which it answers by comparing the claimed secret's
hash with its own (``POST /api/v1/sync/claims``: the hashes never leave the
controller). Once a linked game has ended, its registrations' outcomes go back
(``POST /api/v1/sync/checkins``), again only when they change. A site server
without these endpoints (an older one) is skipped quietly. The site server
never sends anything into a running game: a roster pulled after the start is
not applied.

**Branding** (plan phase 18; P4R19): with ``[sync] branding = "site"`` the
client then pulls the field's branding and saved teams (``GET
/api/v1/sync/field``) and each image the store does not have yet by its
SHA-256 (``GET /api/v1/sync/images/{sha256}``). An image must hash to the
SHA-256 it was asked for and pass ``images.check`` with the same limits as
an upload to the console, stripped bytes unchanged; then ``Branding.apply_site``
makes the field's branding and the site's team presets match the answer.
With ``"local"`` (the default) nothing is pulled and the console's branding
stays the controller's own. A site server without these endpoints is
skipped quietly, as for game day. The pull asks for ``?settings=1`` (BR24):
a site server that knows it adds the field's check-in settings (``max_replicas``,
the federation label, the limit template whole), which ``Checkin.apply_site_settings``
makes this controller's; an older one ignores the query and the settings stay
the controller's own. The site server's ``field.changed`` note on the stream
(``remote_gm.py``) calls ``field_changed``, which runs the cycle at once.
A standby controller has its own sync and does all this by itself.

**The scenario library** (plan phase 20; ADR-P4-6 as amended, P4R9): with
``[sync] library = true`` (the default) the client then pulls the field's
library (``GET /api/v1/sync/presets``): each scenario by id, revision and the
SHA-256 of its manifest, and the field's game presets. A scenario whose
manifest this controller has not installed from the site yet is fetched
(``GET /api/v1/sync/scenarios/{id}``, its SHA-256 checked) and installed with
``scenario_service.install``, which compiles it and loads its ``field.lua`` in
the core again: the controller stays the authority. Every controller with the
field's key does this, a standby too, so a standby has the scenario a join
names (decision M8-3). A refused manifest is not fetched again until the site
changes it; one the live game runs waits for the game to end. Presets are
saved by name once their mode is installed here and their parameters fit it.
A scenario the site archived and a preset it deleted are removed on the next
pull (decision S20-8; the answer is the field's whole library, so what it no
longer lists is gone): only what this controller installed from the site, and
a scenario neither a game that is not ended runs, nor a scheduled game names,
nor the GM replaced with a manifest of their own, which stay.

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

from atalaia_sim.mode import ModeError

from . import __version__, images
from .modes import resolve_params
from .sync_format import (ANSWERS, MAX_EVENTS, MAX_MARSHALS, MAX_READINGS, MAX_REPLICAS, MAX_ROSTER, SYNC_VERSION,
                          SyncFormatError, check_checkins, check_claims, check_event, check_marshal, check_nodes,
                          check_reading, check_replica, library_removals)

log = logging.getLogger("atalaia.sync")

API_KEY = re.compile(r"[A-Za-z0-9_-]{43}")
KEY_SETTING = "sync.api_key"
ID_SETTING = "sync.controller_id"
BATCHES_PER_GAME = 20   # events batches per game and cycle (10,000 events), so one game cannot hold the rest
BATCHES_PER_KIND = 20   # chrono registry batches per kind and cycle
FIELD_RUN = re.compile(r"field-(\d{1,6})")
LIVE = ("running", "paused")
SCHEDULE_DAYS = 14
UNSUPPORTED = (404, 405, 501)  # an older site server without the game-day endpoints
UNSUPPORTED_CODES = ("Not Found", "Method Not Allowed", "http_404", "http_405", "http_501")
IMAGES_PER_CYCLE = 50  # branding images fetched in one cycle; the rest in the next ones
LIBRARY_SETTING = "sync.site_library"  # what was installed from the site's library: {scenarios, refused, presets}


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
        return self._send(req)

    def get(self, path: str) -> dict[str, Any]:
        """A pull (plan phase 16): the same key, no body."""
        req = urllib.request.Request(self.base_url + path, method="GET", headers={
            "Authorization": self._auth, "Accept": "application/json", "User-Agent": self.user_agent})
        return self._send(req)

    def get_bytes(self, path: str, limit: int) -> bytes:
        """A raw download (a branding image, plan phase 18), at most ``limit`` bytes (more: ``too_large``)."""
        req = urllib.request.Request(self.base_url + path, method="GET", headers={
            "Authorization": self._auth, "User-Agent": self.user_agent})
        raw = self._send(req, raw_limit=limit)
        assert isinstance(raw, bytes)
        return raw

    def _send(self, req: urllib.request.Request, raw_limit: Optional[int] = None) -> Any:
        try:
            with self._opener.open(req, timeout=self.timeout_s) as resp:
                raw = resp.read((raw_limit + 1) if raw_limit is not None else 1024 * 1024)
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
        if raw_limit is not None:
            if len(raw) > raw_limit:
                raise SyncError("too_large")
            return raw
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
                 transport: Optional[Any] = None, wall: Callable[[], float] = time.time,
                 checkin: Optional[Any] = None, branding: Optional[Any] = None,
                 controller: Optional[Any] = None) -> None:
        self.cfg = cfg
        self.store = store
        self.checkin = checkin  # checkin.Checkin: applies rosters and makes outcomes (plan phase 16)
        # branding.Branding: applies the site's branding (plan phase 18); a Branding made later sets it itself.
        self.branding = branding
        self.controller = controller  # engine.Controller: installs the site's scenarios and presets (plan phase 20)
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
        self.requests = 0  # POSTs (what was pushed)
        self.pulls = 0  # GETs (plan phase 16)
        self.game_day_error: Optional[str] = None
        self.game_day_supported = True
        self.schedule_pulled_at: Optional[float] = None
        self.claims_answered = 0
        self.shared_chrono_supported = True  # S14-5: GET /api/v1/sync/chrono
        self.shared_chrono_stored = 0  # records kept at the last pull
        self.branding_supported = True
        self.branding_pulled_at: Optional[float] = None
        self.branding_error: Optional[str] = None
        self.images_fetched = 0
        self.settings_from_site = False  # the last answer carried the field's check-in settings (BR24)
        self.settings_applied = 0        # settings (and limit templates) changed by them
        self.field_changes = 0           # stream notes that the field's branding changed (BR24)
        self.remote: Optional[Any] = None  # remote_gm.RemoteGm, with [sync] remote_gm = true (plan phase 19)
        self.library_supported = True
        self.library_pulled_at: Optional[float] = None
        self.library_error: Optional[str] = None
        self.scenarios_installed = 0
        self.scenarios_removed = 0
        self.presets_removed = 0

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

    def field_changed(self) -> None:
        """The site server's note on the stream that the field's branding, teams or settings changed
        (``field.changed``): pull them at once, unless this controller keeps its own branding or is
        backing off."""
        if getattr(self.cfg, "sync_branding", "local") == "site":
            self.field_changes += 1
            self.kick()

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
                self._game_day()
                self._site_branding()
                self._site_library()
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

    # --- game day (plan phase 16) -------------------------------------------------------

    def _get(self, path: str, kind: str) -> Optional[dict[str, Any]]:
        """A pull, its answer checked with the shared format; None when the server has no such endpoint."""
        self.pulls += 1
        try:
            answer = self.transport.get(path)
        except SyncError as exc:
            if exc.status in UNSUPPORTED and exc.code in ("Not Found", "Method Not Allowed", "http_404",
                                                          "http_405", "http_501"):
                if self.game_day_supported:
                    log.info("the site server has no game-day sync (%s): skipped", path)
                self.game_day_supported = False
                return None
            raise
        self.game_day_supported = True
        try:
            return ANSWERS[kind](answer)
        except SyncFormatError as exc:
            raise SyncError("bad_answer", detail=str(exc)) from None

    def _game_day(self) -> None:
        if not hasattr(self.transport, "get"):
            return
        self.game_day_error = None
        schedule = self._get(f"/api/v1/sync/schedule?days={SCHEDULE_DAYS}", "schedule")
        if schedule is None:
            return
        now = self._wall()
        self.store.set_schedule(schedule["games"], now)
        self.schedule_pulled_at = now
        self._pull_rosters()
        self._answer_claims()
        self._push_checkins()

    def _linked(self) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        out = []
        for link in self.store.schedule_links():
            game = self.store.game(link["game_id"])
            if game is not None and int(game["game_seed"]) == int(link["game_seed"]):
                out.append((link, game))
        return out

    def _pull_rosters(self) -> None:
        """Each linked game's roster until the game starts; after the start the controller's list is the
        authority and nothing from the site server changes it (ADR-P4-11)."""
        if self.checkin is None:
            return
        for link, game in self._linked():
            if game["state"] != "ready":
                continue
            path = f"/api/v1/sync/roster?scheduled_game_id={link['scheduled_game_id']}"
            try:
                roster = self._get(path, "roster")
            except SyncError as exc:
                if exc.status != 404:
                    raise
                self.store.roster_pulled(game["id"], game["game_seed"], self._wall(), None, exc.code)
                continue  # the scheduled game is gone or another field's: the game goes on as it is
            if roster is None:
                return
            if roster["scheduled_game_id"] != link["scheduled_game_id"]:
                raise SyncError("bad_answer", detail="the roster of another game")
            result = self.checkin.apply_roster(game["id"], roster)
            self.store.roster_pulled(game["id"], game["game_seed"], self._wall(), len(roster["registrations"]),
                                     None)
            if result.get("conflicts") or result.get("dropped_declarations"):
                log.warning("roster of game %d: %d conflicts, %d declarations dropped", game["id"],
                            result["conflicts"], result["dropped_declarations"])
            self._pull_shared_chrono(game, link, [r["player_id"] for r in roster["registrations"]])

    def _pull_shared_chrono(self, game: dict[str, Any], link: dict[str, Any], players: list[str]) -> None:
        """Other fields' chrono records of the roster's players (``GET /api/v1/sync/chrono``, decision S14-5),
        the same game, the same time as the roster. The site server decides what may be shared (the person's
        consent for both fields, both fields sharing); ``Checkin.apply_shared_chrono`` keeps only the roster's
        players and the records it can verify. A server without the endpoint is skipped quietly."""
        if not players:
            return
        self.pulls += 1
        try:
            answer = self.transport.get(f"/api/v1/sync/chrono?scheduled_game_id={link['scheduled_game_id']}")
        except SyncError as exc:
            if exc.status in UNSUPPORTED and exc.code in UNSUPPORTED_CODES:
                if self.shared_chrono_supported:
                    log.info("the site server has no shared chrono pull: skipped")
                self.shared_chrono_supported = False
                return
            if exc.status == 404:
                return  # the scheduled game went since the roster: nothing to show
            raise
        self.shared_chrono_supported = True
        try:
            answer = ANSWERS["shared_chrono"](answer)
        except SyncFormatError as exc:
            raise SyncError("bad_answer", detail=str(exc)) from None
        if answer["scheduled_game_id"] != link["scheduled_game_id"]:
            raise SyncError("bad_answer", detail="the shared chrono of another game")
        result = self.checkin.apply_shared_chrono(game["id"], players, answer)
        self.shared_chrono_stored = result["stored"]
        if result["dropped"]:
            log.warning("shared chrono of game %d: %d records dropped (not on the roster, not verified, "
                        "too old or already a local reading)", game["id"], result["dropped"])

    def _answer_claims(self) -> None:
        """Accounts that claim a player id of this field: confirmed when this controller knows the id with
        the same secret's hash (compared in constant time), refused when it knows it with another or with
        none (a hand check-in), unknown otherwise. The hashes themselves never leave the controller."""
        import hmac  # noqa: PLC0415

        claims = self._get("/api/v1/sync/claims", "claims")
        if not claims or not claims["claims"]:
            return
        results = []
        for c in claims["claims"]:
            known = self.store.field_player(c["player_id"])
            if known is None:
                result = "unknown"
            elif known["secret_sha256"] is None:
                result = "refused"
            else:
                result = "confirmed" if hmac.compare_digest(known["secret_sha256"].hex(), c["secret_sha256"]) \
                    else "refused"
            results.append({"claim_id": c["claim_id"], "result": result})
        body = check_claims({**self._envelope(), "results": results})
        try:
            self._post("/api/v1/sync/claims", body)
        except SyncError as exc:
            self._registry_refused("/api/v1/sync/claims", exc)
        self.claims_answered += sum(1 for r in results if r["result"] != "unknown")

    def _push_checkins(self) -> None:
        """Once a linked game has ended: its registrations' outcomes, again only when they change."""
        if self.checkin is None:
            return
        sent = self.store.sync_items("checkins")
        for link, game in self._linked():
            if game["state"] != "ended":
                continue
            out = self.checkin.outcomes(game["id"])
            item = f"{game['id']}:{game['game_seed']}"
            sha = digest(out)  # before the check below fills in its defaults
            if sha == sent.get(item):
                continue
            env = self._envelope(game)
            regs = out["registrations"]
            for start in range(0, max(len(regs), 1), MAX_ROSTER):
                body = {**env, "scheduled_game_id": link["scheduled_game_id"], "walkins": out["walkins"],
                        "registrations": json.loads(json.dumps(regs[start:start + MAX_ROSTER]))}
                try:
                    self._bound(game, "/api/v1/sync/checkins", check_checkins(body))
                except SyncFormatError as exc:
                    log.error("game %d: the check-in outcomes are not in protocol/sync.md's form: %s", game["id"], exc)
                except SyncError as exc:
                    if exc.status != 400:
                        raise
                    code, where = _refusal(exc)
                    log.error("the site server refused the check-in outcomes of game %d (%s at %s)", game["id"],
                              code, where)
            self.store.mark_synced("checkins", {item: sha})

    # --- branding and saved teams (plan phase 18) ------------------------------------------

    def _site_branding(self) -> None:
        """With ``[sync] branding = "site"``: the field's branding and saved teams, then the images missing here.
        With ``[sync] apd = "site"`` the same answer carries the field's APD rule (protocol/apd.md)."""
        branding_on = getattr(self.cfg, "sync_branding", "local") == "site" and self.branding is not None
        apd_on = getattr(self.cfg, "sync_apd", "local") == "site" \
            and self.checkin is not None
        if not (branding_on or apd_on) or not hasattr(self.transport, "get"):
            return
        self.pulls += 1
        try:
            # ``settings=1``: an older site server ignores it; one that knows it adds the field's check-in
            # settings (BR24). Without it the answer is the old one, which an older controller checks strictly.
            answer = self.transport.get("/api/v1/sync/field?settings=1")
        except SyncError as exc:
            if exc.status in UNSUPPORTED and exc.code in UNSUPPORTED_CODES:
                if self.branding_supported:
                    log.info("the site server has no branding sync: skipped")
                self.branding_supported = False
                return
            raise
        self.branding_supported = True
        try:
            answer = ANSWERS["field"](answer)
        except SyncFormatError as exc:
            raise SyncError("bad_answer", detail=str(exc)) from None
        if apd_on:
            self.checkin.set_site_apd(answer["field"].get("apd"))
        if not branding_on:
            return
        wanted: dict[str, tuple[str, dict[str, Any]]] = {}  # sha256 -> (kind, ref)
        for slot in ("logo", "wallpaper"):
            if answer["field"][slot] is not None:
                wanted.setdefault(answer["field"][slot]["sha256"], (slot, answer["field"][slot]))
        for team in answer["teams"]:
            if team["crest"] is not None:
                wanted.setdefault(team["crest"]["sha256"], ("crest", team["crest"]))
        missing = [sha for sha in wanted if self.store.image(sha, with_data=False) is None]
        failed = set()
        for sha in missing[:IMAGES_PER_CYCLE]:
            kind, ref = wanted[sha]
            if not self._fetch_image(sha, kind, ref):
                failed.add(sha)
        failed |= set(missing[IMAGES_PER_CYCLE:])
        self.branding_error = f"{len(failed)} images not fetched yet" if failed else None
        self.branding.apply_site(answer, unavailable=failed)
        if answer.get("settings") is not None and self.checkin is not None:
            self.settings_applied += self.checkin.apply_site_settings(answer["settings"])
        self.settings_from_site = answer.get("settings") is not None
        self.branding_pulled_at = self._wall()

    def _fetch_image(self, sha: str, kind: str, ref: dict[str, Any]) -> bool:
        """One image by its SHA-256: it must hash to it and pass ``images.check`` unchanged (the site server
        stores images as checked, so checking them again strips nothing)."""
        self.pulls += 1
        limits = images.KINDS[kind]
        try:
            data = self.transport.get_bytes(f"/api/v1/sync/images/{sha}", limits.max_bytes)
        except SyncError as exc:
            if exc.status == 404 or exc.code == "too_large":
                log.warning("branding image %s (%s) not fetched: %s", sha[:12], kind, exc.code)
                return False
            raise
        problem = None
        if hashlib.sha256(data).hexdigest() != sha:
            problem = "its SHA-256 differs"
        else:
            try:
                checked = images.check(data, ref["content_type"], limits)
                if checked.data != data:
                    problem = "it was not stripped as the controller strips it"
            except images.ImageError as exc:
                problem = str(exc)
        if problem:
            log.error("branding image %s (%s) from the site server refused: %s", sha[:12], kind, problem)
            return False
        self.store.put_image(sha, kind, checked.content_type, checked.width, checked.height, checked.data)
        self.images_fetched += 1
        return True

    # --- the scenario library and presets (plan phase 20) ------------------------------------

    def _library_state(self) -> dict[str, dict[str, str]]:
        try:
            state = json.loads(self.store.get_setting(LIBRARY_SETTING) or "{}")
        except ValueError:
            state = {}
        return {k: dict(state.get(k) or {}) for k in ("scenarios", "refused", "presets")}

    def _site_library(self) -> None:
        """With ``[sync] library = true``: the field's scenarios not installed from the site yet, then its presets."""
        if not getattr(self.cfg, "sync_library", True) or self.controller is None \
                or not hasattr(self.transport, "get"):
            return
        self.pulls += 1
        try:
            answer = self.transport.get("/api/v1/sync/presets")
        except SyncError as exc:
            if exc.status in UNSUPPORTED and exc.code in UNSUPPORTED_CODES:
                if self.library_supported:
                    log.info("the site server has no scenario library: skipped")
                self.library_supported = False
                return
            raise
        self.library_supported = True
        try:
            answer = ANSWERS["presets"](answer)
        except SyncFormatError as exc:
            raise SyncError("bad_answer", detail=str(exc)) from None
        state = self._library_state()
        problems: list[str] = []
        try:
            for ref in answer["scenarios"]:
                sid, sha = ref["scenario_id"], ref["sha256"]
                if sha not in (state["scenarios"].get(sid), state["refused"].get(sid)):
                    problem = self._install_scenario(sid, sha, state)
                    if problem:
                        problems.append(f"{sid}: {problem}")
            for preset in answer["presets"]:
                sha = digest({k: preset[k] for k in ("name", "mode_id", "params")})
                if state["presets"].get(preset["name"]) != sha:
                    problem = self._save_preset(preset)
                    if problem:
                        problems.append(f"preset {preset['name']}: {problem}")
                    else:
                        state["presets"][preset["name"]] = sha
            self._remove_gone(answer, state)
        finally:
            self.store.set_setting(LIBRARY_SETTING, json.dumps(state, sort_keys=True))
        self.library_error = "; ".join(problems)[:500] or None
        self.library_pulled_at = self._wall()

    def _remove_gone(self, answer: dict[str, Any], state: dict[str, dict[str, str]]) -> None:
        """Removes what the site no longer lists (decision S20-8): the scenarios and presets this controller
        installed from it. A scenario stays (and is tried again next cycle) while a game that is not ended runs it
        or a scheduled game names it; one the GM replaced with another manifest is theirs, so only the site's claim
        on it is dropped."""
        from . import scenario_service  # noqa: PLC0415 (it imports the engine's modules)
        from .engine import Conflict  # noqa: PLC0415

        gone = library_removals(state, answer)
        listed = {s["scenario_id"] for s in answer["scenarios"]}
        for sid in [s for s in state["refused"] if s not in listed]:
            del state["refused"][sid]  # refused, then archived: nothing to fetch any more
        ctrl = self.controller
        scheduled = {part for g in self.store.schedule() for part in str(g.get("mode_id") or "").split("+")}
        for sid in gone["scenarios"]:
            kept = self.store.get_setting(scenario_service.MANIFEST_KEY + sid)
            if kept is None or hashlib.sha256(kept.encode("utf-8")).hexdigest() != state["scenarios"][sid]:
                del state["scenarios"][sid]  # the GM's own manifest now (or the package is gone already)
                continue
            if sid in scheduled:
                log.info("scenario %s archived on the site server: kept, a scheduled game names it", sid)
                continue
            try:
                with ctrl._lock:
                    scenario_service.uninstall(ctrl, sid)
            except Conflict as exc:
                log.info("scenario %s archived on the site server: kept, %s", sid, exc)
                continue
            del state["scenarios"][sid]
            self.scenarios_removed += 1
            ctrl._emit({"type": "modes"})
            log.info("scenario %s removed: archived on the site server", sid)
        for name in gone["presets"]:
            self.store.delete_preset(name)
            del state["presets"][name]
            self.presets_removed += 1
            log.info("preset %s removed: deleted on the site server", name)

    def _install_scenario(self, sid: str, sha: str, state: dict[str, dict[str, str]]) -> Optional[str]:
        """Fetches one manifest and installs it (compiled and loaded in the core here); a problem, or None."""
        from . import scenario_service  # noqa: PLC0415 (it imports the engine's modules)
        from .engine import Conflict  # noqa: PLC0415

        self.pulls += 1
        try:
            body = self.transport.get(f"/api/v1/sync/scenarios/{sid}")
        except SyncError as exc:
            if exc.status == 404:
                return "gone from the site server"
            raise
        try:
            body = ANSWERS["scenario"](body)
        except SyncFormatError as exc:
            raise SyncError("bad_answer", detail=str(exc)) from None
        if body["scenario_id"] != sid or body["sha256"] != sha:
            return "changed on the site server while fetched; next cycle"
        ctrl = self.controller
        try:
            with ctrl._lock:  # not while a game starts with it (the console's install runs the same checks)
                scenario_service.install(ctrl, body["manifest"])
        except (scenario_service.Refused, ModeError) as exc:
            state["refused"][sid] = sha
            log.error("scenario %s from the site server refused: %s", sid, exc)
            return f"refused: {exc}"
        except Conflict as exc:
            if not scenario_service._uses(ctrl.game, sid):
                state["refused"][sid] = sha  # another kind of package has this id here
            log.warning("scenario %s from the site server not installed: %s", sid, exc)
            return str(exc)
        state["scenarios"][sid] = sha
        state["refused"].pop(sid, None)
        self.scenarios_installed += 1
        ctrl._emit({"type": "modes"})
        log.info("scenario %s installed from the site server (revision %d)", sid, body["revision"])
        return None

    def _save_preset(self, preset: dict[str, Any]) -> Optional[str]:
        """A site preset saved by its name once its mode is installed here and its parameters fit it."""
        ctrl = self.controller
        try:
            pkg = ctrl.modes.get(preset["mode_id"])
            if pkg is None:
                return f"mode {preset['mode_id']} is not installed here"
            resolve_params(pkg.mode, preset["params"], None)
        except ModeError as exc:
            return str(exc)
        self.store.save_preset(preset["name"], pkg.id, preset["params"])
        return None

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
                "ended_at": game.get("ended_at"), "scheduled_game_id": self._scheduled(game)}

    def _scheduled(self, game: dict[str, Any]) -> Optional[str]:
        """The site server's scheduled game this game was made from (plan phase 16), or None."""
        link = self.store.schedule_link(int(game["id"]), int(game["game_seed"]))
        return link["scheduled_game_id"] if link else None

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
            info = {k: node[k] for k in NODE_INFO if k in node}
            if isinstance(info.get("capabilities"), list):
                # A HELLO's capabilities are integer ids, the format's texts: as their decimal text, or
                # every box that said HELLO was left out (decision PE24-121).
                info["capabilities"] = [str(c) for c in info["capabilities"]]
            entry = {"node_id": node["node_id"], "name": node["name"], "role": node["role"],
                     "last_seen": node["last_seen"], "info": info}
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
                "refused_readings": self.refused_readings,
                "game_day": {"supported": self.game_day_supported, "schedule_pulled_at": self.schedule_pulled_at,
                             "linked_games": len(self.store.schedule_links()),
                             "claims_answered": self.claims_answered,
                             "shared_chrono": {"supported": self.shared_chrono_supported,
                                               "stored": self.shared_chrono_stored}},
                "branding": {"source": getattr(self.cfg, "sync_branding", "local"),
                             "supported": self.branding_supported, "pulled_at": self.branding_pulled_at,
                             "error": self.branding_error, "images_fetched": self.images_fetched,
                             "settings": self.settings_from_site, "settings_applied": self.settings_applied,
                             "field_changes": self.field_changes},
                "remote_gm": self.remote.status() if self.remote is not None else {"enabled": False},
                "library": {"enabled": bool(getattr(self.cfg, "sync_library", True)),
                            "supported": self.library_supported, "pulled_at": self.library_pulled_at,
                            "error": self.library_error, "scenarios_installed": self.scenarios_installed,
                            "scenarios_removed": self.scenarios_removed, "presets_removed": self.presets_removed,
                            "from_site": {k: sorted(v) for k, v in self._library_state().items()}}}
