# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Field check-in and the "replicas to chrono" list (ADR-P3-13, protocol/checkin.md).

A player scans the field's check-in poster, the app calls POST
/api/v1/checkin with its field identity (a player id and a secret, made on
the phone once per field), and gets a player token (protocol/player-token.md)
keyed with the game's own token key (decision B8). The player then declares
the replicas they will use; each declaration is ``pending`` until a signed
chrono check-in series for that replica arrives from a marshal's phone
(POST /api/v1/chrono/readings), verified with the marshal's registered
Ed25519 key, which makes it ``passed`` or ``refused``.

Personal data is a short list (a display name, an optional federation
number that nothing ever checks, a team preference) and stays here: events
carry only the player id, the stream sends names to staff connections only,
and the retention purge erases them 30 days after the game.

The controller is the authority: a token's role, team and squad are checked
against the player's current check-in on every request, so a demotion, a
team change or a removal takes effect at once.

**Registrations** (phase 4, plan phase 16; ADR-P4-11): with a site server, the
sync client pulls the roster of a scheduled game the GM made this game from,
until the game starts. Each registration becomes an **expected** check-in
(``apply_roster``) with its pre-declared replicas already ``pending`` in the
"replicas to chrono" list; a cancelled one that has not arrived goes. The
player arrives with the app (the check-in carries ``registration_id`` and the
ticket, whose SHA-256 the roster holds), shows a printed ``atalaia:ticket:``
code to a marshal (``ticket_checkin``), or is ticked by name. Without a roster
the app's registration id and ticket are kept with the walk-in, so the site
server can match them later. What goes back after the game (``outcomes``) is
each registration's outcome and declarations' states, never a name.
"""

from __future__ import annotations

import base64
import binascii
import collections
import csv
import datetime
import hashlib
import hmac
import io
import json
import logging
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

import yaml

from . import REPO_ROOT, chrono, player_token
from . import checkin_poster as posterfmt
from . import checkin_ticket as ticketfmt
from .engine import Conflict, ControllerError, NotFound

if TYPE_CHECKING:
    from .engine import Controller

log = logging.getLogger("atalaia.checkin")

PLAYER_ID_RE = re.compile(r"p-[a-z2-7]{12}")
SECRET_RE = re.compile(r"[A-Za-z0-9_-]{43}")
UUID_RE = chrono.UUID_RE
CLASS_RE = re.compile(r"[a-z0-9_]{1,32}")
MARSHAL_ID_RE = chrono.ID_RE
REPLICA_TYPES = ("aeg", "gbb", "hpa", "bolt_action", "dmr", "sniper", "pistol", "shotgun")
STATUSES = ("expected", "pending", "checked_in", "left", "removed")
ARRIVED = ("pending", "checked_in", "left")  # at the field (a registration's outcome: checked_in)
STATES = ("pending", "passed", "refused", "withdrawn")
NAME_MAX = 32
FEDERATION_MAX = 32
SERIES_MAX = 50
RANK = {"spectator": 0, "player": 1, "squad_leader": 2, "vip": 2, "marshal": 3, "gm": 4}
STAFF_ROLES = ("marshal", "gm")
LIMIT_TEMPLATES = REPO_ROOT / "app" / "lib" / "chrono" / "limit_templates"
NOTICES = Path(__file__).resolve().parent.parent / "templates"
TOKEN_GRACE_S = 2 * 3600
TOKEN_MIN_S = 60
IDENTITY_DAYS = 365
CHRONO_RETENTION_DAYS = 365
SETTINGS_KEYS = ("confirm", "federation", "federation_label", "max_replicas", "max_players",
                 "chrono_valid_for")


class Unauthorized(ControllerError):
    status = 401


class Forbidden(ControllerError):
    status = 403


class TooMany(ControllerError):
    status = 429


class Refused(ControllerError):
    """A request whose content cannot be accepted (422), with per-item reasons."""

    status = 422

    def __init__(self, message: str, reasons: Optional[list[dict[str, Any]]] = None) -> None:
        super().__init__(message)
        self.reasons = reasons or []


# --- who is calling ----------------------------------------------------------


@dataclass
class Viewer:
    """Who a request or a stream connection belongs to.

    kind: "gm" (the GM token), "read" (the read token) or "player" (a player
    token, its claims already checked against the player's check-in row).
    """

    kind: str
    claims: dict[str, Any] = field(default_factory=dict)
    stale: bool = False  # the token's role, team or squad no longer match the row

    @property
    def role(self) -> str:
        if self.kind == "player":
            return self.claims["role"]
        return "gm" if self.kind == "gm" else "spectator"

    @property
    def player_id(self) -> Optional[str]:
        return self.claims.get("player_id") if self.kind == "player" else None

    @property
    def game_id(self) -> Optional[int]:
        return self.claims.get("game_id") if self.kind == "player" else None

    @property
    def team(self) -> int:
        return int(self.claims.get("team", 0)) if self.kind == "player" else 0

    @property
    def squad(self) -> int:
        return int(self.claims.get("squad", 0)) if self.kind == "player" else 0

    @property
    def is_gm_token(self) -> bool:
        return self.kind == "gm"

    @property
    def is_staff(self) -> bool:
        """The GM token, or a marshal or gm player token: sees names and the chrono list."""
        return self.kind == "gm" or (self.kind == "player" and self.role in STAFF_ROLES)


def effective_role(token_role: str, row_role: str) -> str:
    """What an older token may still do: its own role if the row still says it, else the lesser."""
    if token_role == row_role:
        return token_role
    a, b = RANK[token_role], RANK[row_role]
    if a == b:
        return "player"  # squad_leader and vip are not above one another
    return token_role if a < b else row_role


# --- checks ------------------------------------------------------------------


def _printable(value: str) -> bool:
    return all(not (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or 0xD800 <= ord(c) <= 0xDFFF) for c in value)


def _text(name: str, value: Any, max_chars: int, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ControllerError(f"{name}: text")
    value = value.strip()
    if not 1 <= len(value) <= max_chars or not _printable(value):
        raise ControllerError(f"{name}: 1-{max_chars} characters without control characters")
    return value


def player_id_ok(value: Any) -> bool:
    return isinstance(value, str) and PLAYER_ID_RE.fullmatch(value) is not None


def secret_bytes(value: Any) -> bytes:
    """The 32-byte player secret from its canonical base64url form (43 characters, no padding)."""
    if not isinstance(value, str) or not SECRET_RE.fullmatch(value):
        raise ControllerError("player_secret: 32 bytes in base64url without padding (43 characters)")
    raw = base64.urlsafe_b64decode(value + "=")
    if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != value:
        raise ControllerError("player_secret: not canonical base64url")
    return raw


def new_player_id() -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz234567"
    return "p-" + "".join(secrets.choice(alphabet) for _ in range(12))


def validate_declaration(item: Any) -> dict[str, Any]:
    """One declared replica as the app or staff send it (protocol/checkin.md); raises ControllerError."""
    if not isinstance(item, dict):
        raise ControllerError("a declaration is an object")
    allowed = {"declaration_id", "replica_id", "type", "class", "make_model"}
    unknown = set(item) - allowed
    if unknown:
        raise ControllerError(f"declaration: unknown fields {sorted(unknown)} (the state is the controller's)")
    did = item.get("declaration_id")
    if not isinstance(did, str) or not UUID_RE.fullmatch(did):
        raise ControllerError("declaration_id: a lowercase UUID")
    rid = item.get("replica_id")
    if rid is not None and (not isinstance(rid, str) or not UUID_RE.fullmatch(rid)):
        raise ControllerError("replica_id: a lowercase UUID")
    rtype = item.get("type")
    if rtype not in REPLICA_TYPES:
        raise ControllerError(f"type: one of {', '.join(REPLICA_TYPES)}")
    rclass = item.get("class")
    if not isinstance(rclass, str) or not CLASS_RE.fullmatch(rclass):
        raise ControllerError("class: 1-32 of a-z 0-9 _ (a class of the field's limits)")
    mm = item.get("make_model")
    if mm is not None:
        if not isinstance(mm, str) or not 1 <= len(mm) <= 64 or not _printable(mm):
            raise ControllerError("make_model: 1-64 characters without control characters")
    return {"declaration_id": did, "replica_id": rid, "type": rtype, "class": rclass, "make_model": mm}


def load_limits(template: str) -> dict[str, Any]:
    """A limit template's classes ({class: {max_energy_j, ...}}), from app/lib/chrono/limit_templates."""
    path = LIMIT_TEMPLATES / f"{template}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"limit template {template!r}: {exc}") from None
    classes = data.get("classes") if isinstance(data, dict) else None
    if not isinstance(classes, dict) or not classes:
        raise ValueError(f"limit template {template!r} has no classes")
    out = {}
    for name, spec in classes.items():
        if not isinstance(spec, dict) or not isinstance(spec.get("max_energy_j"), (int, float)):
            raise ValueError(f"limit template {template!r}: class {name} has no max_energy_j")
        out[str(name)] = {"max_energy_j": float(spec["max_energy_j"]), "med_m": spec.get("med_m"),
                          "fire_mode": spec.get("fire_mode")}
    return {"id": data.get("id", template), "name": data.get("name", template),
            "status": data.get("status"), "classes": out}


class RateLimit:
    """At most ``per_minute`` calls per key in any 60 s."""

    def __init__(self, per_minute: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.per_minute = per_minute
        self._clock = clock
        self._calls: dict[str, collections.deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            q = self._calls.setdefault(key, collections.deque())
            while q and now - q[0] >= 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            if len(self._calls) > 10_000:  # forget idle clients
                for k in [k for k, v in self._calls.items() if not v]:
                    del self._calls[k]
            return True


# --- the service -------------------------------------------------------------


class Checkin:
    def __init__(self, controller: "Controller", *, ca_sha256: Optional[bytes] = None,
                 default_urls: Optional[list[str]] = None, wall: Callable[[], float] = time.time,
                 tz: Optional[datetime.tzinfo] = None) -> None:
        self.ctrl = controller
        self.cfg = controller.cfg
        self.store = controller.store
        self.ca_sha256 = ca_sha256
        self.default_urls = list(default_urls or [])
        self._wall = wall
        self._tz = tz  # None: the controller's local time zone
        self._lock = threading.RLock()
        self.limits = load_limits(self.cfg.limit_template)
        self.rate = RateLimit(self.cfg.rate_per_minute)
        self.info_rate = RateLimit(max(60, self.cfg.rate_per_minute * 6))
        self._last_purge = 0.0
        controller.checkin = self

    # --- settings and the poster -----------------------------------------------

    def settings(self) -> dict[str, Any]:
        out = {"confirm": self.cfg.checkin_confirm, "federation": self.cfg.federation,
               "federation_label": self.cfg.federation_label, "max_replicas": self.cfg.max_replicas,
               "max_players": self.cfg.max_players, "chrono_valid_for": self.cfg.chrono_valid_for}
        saved = self.store.get_setting("checkin.settings")
        if saved:
            try:
                out.update({k: v for k, v in json.loads(saved).items() if k in SETTINGS_KEYS})
            except ValueError:
                pass
        return out

    def set_settings(self, spec: dict[str, Any]) -> dict[str, Any]:
        unknown = set(spec) - set(SETTINGS_KEYS)
        if unknown:
            raise ControllerError(f"unknown check-in settings {sorted(unknown)}")
        cur = self.settings()
        choices = {"confirm": ("auto", "staff"), "federation": ("off", "optional", "required"),
                   "chrono_valid_for": ("day", "game")}
        for k, v in spec.items():
            if k in choices and v not in choices[k]:
                raise ControllerError(f"{k}: one of {', '.join(choices[k])}")
            if k == "federation_label":
                _text(k, v, 16)
            if k == "max_replicas" and (isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 20):
                raise ControllerError("max_replicas: 1-20")
            if k == "max_players" and (isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5000):
                raise ControllerError("max_players: 1-5000")
            cur[k] = v.strip() if isinstance(v, str) else v
        self.store.set_setting("checkin.settings", json.dumps({k: cur[k] for k in SETTINGS_KEYS}))
        self.ctrl._emit({"type": "checkin_settings", "settings": cur, "_staff": True})
        return cur

    def poster_fields(self) -> dict[str, Any]:
        saved = {}
        raw = self.store.get_setting("checkin.poster")
        if raw:
            try:
                saved = json.loads(raw)
            except ValueError:
                saved = {}
        urls = saved.get("urls") or self.cfg.checkin_urls or self.default_urls
        return {"field_id": self.cfg.field_id, "field_name": saved.get("field_name") or self.cfg.field_name,
                "urls": list(urls)[:3], "ca_sha256": self.ca_sha256,
                "wifi_ssid": saved.get("wifi_ssid", self.cfg.wifi_ssid or None) or None,
                "game_id": saved.get("game_id")}

    def poster(self) -> dict[str, Any]:
        p = self.poster_fields()
        out = {k: v for k, v in p.items() if k != "ca_sha256"}
        out["ca_sha256"] = p["ca_sha256"].hex() if p["ca_sha256"] else None
        out["ca_short"] = posterfmt.short_fingerprint(p["ca_sha256"]) if p["ca_sha256"] else None
        # problem: the text in English (for logs and scripts); problem_code: what the console translates.
        if p["ca_sha256"] is None:
            out["text"] = None
            out["problem_code"] = "https_off"
            out["problem"] = "HTTPS is off ([api] tls_port = 0): the poster needs the field's CA"
        elif not p["urls"]:
            out["text"] = None
            out["problem_code"] = "no_address"
            out["problem"] = "no https address for the poster: set [checkin] urls or [api] tls_names"
        else:
            try:
                out["text"] = posterfmt.make(p)
                out["problem"] = out["problem_code"] = None
            except posterfmt.PosterError as exc:
                out["text"] = None
                out["problem_code"] = "too_long" if exc.reason == "length" else "invalid"
                out["problem"] = str(exc)
        return out

    def set_poster(self, spec: dict[str, Any]) -> dict[str, Any]:
        unknown = set(spec) - {"urls", "wifi_ssid", "game_id", "field_name"}
        if unknown:
            raise ControllerError(f"unknown poster fields {sorted(unknown)}")
        trial = {**self.poster_fields(), **{k: v for k, v in spec.items()}}
        if trial.get("wifi_ssid") == "":
            trial["wifi_ssid"] = None
        if not trial.get("urls"):
            trial["urls"] = self.cfg.checkin_urls or self.default_urls
        # No address yet (a container without [api] tls_names, OT-10) or no field CA (HTTPS off): the
        # rest is still checked and kept, with a placeholder for what is missing; GET says what is
        # missing (problem_code no_address, https_off). Unchecked, a bad game_id was kept and every
        # check-in then refused as "for another game" (decision PE24-58).
        checked = trial if trial.get("urls") else {**trial, "urls": ["https://a.invalid"]}
        if checked["ca_sha256"] is None:
            checked = {**checked, "ca_sha256": bytes(32)}
        try:
            posterfmt.encode(checked)
        except posterfmt.PosterError as exc:
            raise ControllerError(str(exc)) from None
        saved = {k: trial.get(k) for k in ("urls", "wifi_ssid", "game_id", "field_name")}
        if "urls" not in spec:
            saved.pop("urls")
        self.store.set_setting("checkin.poster", json.dumps(saved))
        return self.poster()

    def notice(self) -> dict[str, Any]:
        texts = {}
        for lang, configured in (("pt", self.cfg.notice_pt), ("en", self.cfg.notice_en)):
            path = Path(configured) if configured else NOTICES / f"checkin-notice-{lang}.md"
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                text = ""
            # The licence header of the default files is not part of the notice.
            text = re.sub(r"\A<!--.*?-->\s*", "", text, flags=re.S)
            operator = self.cfg.operator or self.poster_fields()["field_name"]
            texts[lang] = text.replace("{operator}", operator).replace(
                "{retention_days}", str(self.cfg.retention_days))
        return {"version": self.cfg.notice_version, **texts}

    # --- games open for check-in ---------------------------------------------

    def is_open(self, game_id: int) -> bool:
        game = self.store.game(game_id)
        if game is None or game["state"] == "ended" or game.get("joined"):
            return False
        return self.store.get_setting(f"checkin.open:{game_id}") != "0"

    def set_open(self, game_id: int, is_open: bool) -> dict[str, Any]:
        game = self.ctrl.get_game(game_id)
        if game["state"] == "ended":
            raise Conflict(f"game {game_id} has ended")
        self.store.set_setting(f"checkin.open:{game_id}", "1" if is_open else "0")
        out = {"game_id": game_id, "open": self.is_open(game_id)}
        self.ctrl._emit({"type": "checkin_open", "game": game_id, "open": out["open"]})
        return out

    def open_games(self) -> list[dict[str, Any]]:
        out = []
        for g in self.store.games():
            if g["state"] != "ended" and self.is_open(g["id"]):
                out.append({"game_id": g["id"], "name": g["name"], "state": g["state"], "teams": g["teams"],
                            "squads": int(g.get("squads") or 0)})
        pinned = self.poster_fields().get("game_id")
        if pinned:
            out = [g for g in out if g["game_id"] == pinned]
        return out

    def info(self) -> dict[str, Any]:
        """GET /api/v1/checkin: what a player's app needs before checking in. No names."""
        p = self.poster_fields()
        return {
            "version": 1,
            "field": {"id": self.cfg.field_id, "name": p["field_name"], "operator": self.cfg.operator or None},
            "notice": self.notice(),
            "settings": {k: v for k, v in self.settings().items() if k != "max_players"},
            "limits": {"id": self.limits["id"], "name": self.limits["name"],
                       "status": self.limits["status"], "classes": sorted(self.limits["classes"])},
            "replica_types": list(REPLICA_TYPES),
            "games": self.open_games(),
        }

    # --- tokens ----------------------------------------------------------------

    def _local_day_end(self, now: float) -> float:
        tz = self._tz
        dt = datetime.datetime.fromtimestamp(now, tz) if tz else datetime.datetime.fromtimestamp(now)
        nxt = (dt + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return nxt.timestamp()

    def local_day(self, ts: float) -> datetime.date:
        tz = self._tz
        return (datetime.datetime.fromtimestamp(ts, tz) if tz else datetime.datetime.fromtimestamp(ts)).date()

    def token_exp(self, game: dict[str, Any], now: float) -> int:
        """The game's planned end plus 2 hours, or the end of the field's day, whichever is first."""
        exp = self._local_day_end(now)
        if game.get("duration_ms") and game.get("started_at"):
            exp = min(exp, game["started_at"] + game["duration_ms"] / 1000 + TOKEN_GRACE_S)
        return int(max(exp, now + TOKEN_MIN_S))

    def issue_token(self, game: dict[str, Any], row: dict[str, Any]) -> tuple[str, int]:
        key = self.store.token_key(game["id"], create=True)
        assert key is not None
        exp = self.token_exp(game, self._wall())
        claims = {"exp": exp, "game_id": game["id"], "player_id": row["player_id"], "role": row["role"],
                  "squad": int(row["squad"]), "team": int(row["team"])}
        return player_token.issue(claims, key), exp

    def resolve(self, token: str) -> Viewer:
        """A player token's viewer, its claims checked against the check-in row; raises Unauthorized."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                raise ValueError
            raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
            game_id = json.loads(raw.decode("utf-8")).get("game_id")
            if isinstance(game_id, bool) or not isinstance(game_id, int):
                raise ValueError
        except (ValueError, binascii.Error, UnicodeDecodeError, AttributeError):
            raise Unauthorized("not a valid token") from None
        key = self.store.token_key(game_id)
        game = self.store.game(game_id)
        if key is None or game is None:
            raise Unauthorized("not a valid token")
        try:
            claims = player_token.verify(token, key, game_id=game_id, team_count=len(game["teams"]),
                                         now=int(self._wall()))
        except player_token.TokenError as exc:
            raise Unauthorized(f"player token refused ({exc.reason})") from None
        row = self.store.checkin(game_id, claims["player_id"])
        if row is None or row["status"] in ("left", "removed"):
            raise Unauthorized("this check-in is no longer valid; check in again")
        eff = dict(claims)
        eff["role"] = effective_role(claims["role"], row["role"])
        eff["team"] = int(row["team"])
        eff["squad"] = int(row["squad"])
        stale = (claims["role"], claims["team"], claims["squad"]) != (row["role"], row["team"], row["squad"])
        return Viewer("player", eff, stale=stale)

    # --- checking in -------------------------------------------------------------

    def _team_id(self, game: dict[str, Any], team: Any, name: str = "team") -> int:
        if team is None or team == 0 or team == "":
            return 0
        if isinstance(team, str):
            if team not in game["teams"]:
                raise ControllerError(f"{name}: one of {game['teams']}")
            return game["teams"].index(team) + 1
        if isinstance(team, bool) or not isinstance(team, int) or not 0 <= team <= len(game["teams"]):
            raise ControllerError(f"{name}: a team of the game")
        return team

    def _team_name(self, game: dict[str, Any], team_id: int) -> Optional[str]:
        return game["teams"][team_id - 1] if 1 <= team_id <= len(game["teams"]) else None

    def check_in(self, body: dict[str, Any], client: str) -> tuple[dict[str, Any], bool]:
        """POST /api/v1/checkin. Answers (result, created)."""
        if not self.rate.allow(client):
            raise TooMany("too many check-ins from this address; wait a minute")
        allowed = {"game_id", "player_id", "player_secret", "display_name", "federation_number",
                   "team_preference", "notice_version", "replicas", "registration_id", "ticket"}
        unknown = set(body) - allowed
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        game_id = body.get("game_id")
        if isinstance(game_id, bool) or not isinstance(game_id, int):
            raise ControllerError("game_id: the game's id")
        game = self.store.game(game_id)
        if game is None:
            raise NotFound(f"no game {game_id}")
        if not self.is_open(game_id):
            raise Forbidden(f"check-in for game {game_id} is closed")
        pinned = self.poster_fields().get("game_id")
        if pinned and pinned != game_id:
            raise Forbidden("this field's check-in is for another game")
        pid = body.get("player_id")
        if not player_id_ok(pid):
            raise ControllerError("player_id: p- and 12 of a-z 2-7")
        secret = secret_bytes(body.get("player_secret"))
        reg_id, ticket_hex = self._registration_proof(body)
        st = self.settings()
        name = _text("display_name", body.get("display_name"), NAME_MAX)
        fed_in = _text("federation_number", body.get("federation_number") or None, FEDERATION_MAX, optional=True)
        pref = body.get("team_preference")
        if pref is not None:
            self._team_id(game, pref, "team_preference")
        notice = body.get("notice_version")
        if notice != self.cfg.notice_version:
            raise Conflict("the privacy notice changed: read it again (GET /api/v1/checkin)")
        replicas = body.get("replicas")
        decls = None
        if replicas is not None:
            decls = self._check_declarations(replicas, st)
        now = self._wall()
        digest = hashlib.sha256(secret).digest()
        with self._lock:
            known = self.store.field_player(pid)
            row = self.store.checkin(game_id, pid)
            expected = self._expected_match(game_id, pid, row, known, reg_id, ticket_hex)
            if known is not None:
                if known["secret_sha256"] is None or not hmac.compare_digest(known["secret_sha256"], digest):
                    raise Conflict("this player id is someone else's at this field")
                self.store.touch_field_player(pid, now)
            if row is not None and row["status"] == "removed":
                raise Forbidden("staff removed this check-in; ask at the desk")
            # A registered player's roster entry fills in what the app did not send.
            fed = fed_in if fed_in is not None or expected is None else expected["federation_number"]
            if pref is None and expected is not None and expected["team_preference"] in game["teams"]:
                pref = expected["team_preference"]
            if st["federation"] == "off":
                fed = None
            elif st["federation"] == "required" and fed is None:
                raise ControllerError(f"federation_number: this field asks for your {st['federation_label']} number")
            created = row is None or row["status"] == "expected"  # an expected player arriving is a new check-in
            emit = False
            if created:
                if self.store.count_checkins(game_id) >= st["max_players"]:
                    raise Forbidden(f"game {game_id} is full ({st['max_players']} players)")
                if known is None:
                    self.store.add_field_player(pid, digest, now)
                status = "checked_in" if st["confirm"] == "auto" else "pending"
                fields = {"status": status, "display_name": name, "federation_number": fed,
                          "team_preference": pref, "notice_version": notice,
                          "checked_in_at": now if status == "checked_in" else None}
                if row is None:
                    if reg_id is not None:  # no roster here: kept, so the site server can match it later
                        fields.update(registration_id=reg_id, ticket_sha256=ticket_hex)
                    self.store.add_checkin(game_id, pid, fields, now)
                else:
                    self.store.update_checkin(game_id, pid, **fields, updated_at=now)
                emit = status == "checked_in"
            else:
                status = row["status"]
                if status == "left":
                    status = "checked_in" if st["confirm"] == "auto" else "pending"
                    emit = status == "checked_in"
                fields = {"status": status, "display_name": name, "team_preference": pref,
                          "notice_version": notice, "updated_at": now}
                if fed != row["federation_number"]:
                    fields["federation_number"] = fed
                    fields["federation_seen"] = False
                if emit:
                    fields["checked_in_at"] = now
                if reg_id is not None and row["registration_id"] is None:
                    fields.update(registration_id=reg_id, ticket_sha256=ticket_hex)
                self.store.update_checkin(game_id, pid, **fields)
            if decls is not None:
                self._replace_declarations(game, pid, decls, staff=False, now=now)
            row = self.store.checkin(game_id, pid)
            assert row is not None
            token, exp = self.issue_token(game, row)
        if emit:
            self._emit_checkin_event(game, row)
        self._notify(game_id, pid)
        log.info("check-in: game %d, %s (%s)", game_id, pid, row["status"])  # never the name
        return self._token_answer(game, row, token, exp), created

    def _token_answer(self, game: dict[str, Any], row: dict[str, Any], token: str, exp: int) -> dict[str, Any]:
        return {"game_id": game["id"], "player_id": row["player_id"], "token": token, "exp": exp,
                "status": row["status"], "team": self._team_name(game, row["team"]), "team_id": row["team"],
                "squad": row["squad"], "role": row["role"]}

    def _registration_proof(self, body: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        """``registration_id`` and ``ticket`` (both or neither): the id and the SHA-256 (hex) of the ticket."""
        reg_id, ticket = body.get("registration_id"), body.get("ticket")
        if reg_id is None and ticket is None:
            return None, None
        if reg_id is None or ticket is None:
            raise ControllerError("registration_id and ticket go together")
        if not isinstance(reg_id, str) or not UUID_RE.fullmatch(reg_id):
            raise ControllerError("registration_id: a lowercase UUID")
        try:
            return reg_id, ticketfmt.secret_sha256(ticketfmt.secret_from_text(ticket))
        except ticketfmt.TicketError:
            raise ControllerError("ticket: 32 bytes in base64url without padding (43 characters)") from None

    def _expected_match(self, game_id: int, pid: str, row: Optional[dict[str, Any]],
                        known: Optional[dict[str, Any]], reg_id: Optional[str],
                        ticket_hex: Optional[str]) -> Optional[dict[str, Any]]:
        """The roster's check-in this arrival is, checked against its ticket; None for a walk-in.
        A player id the roster brought and this controller never saw needs the registration's ticket:
        the site server made that id, so no phone has proved it here yet."""
        if reg_id is not None:
            match = self.store.checkin_by_registration(game_id, reg_id)
            if match is not None and match["from_roster"]:
                if match["player_id"] != pid:
                    raise Conflict("this registration is for another player id at this field")
                if not match["ticket_sha256"] or not hmac.compare_digest(match["ticket_sha256"], ticket_hex or ""):
                    raise Forbidden("this ticket is not this registration's (was a newer one made?)")
                return match
        if row is not None and row["from_roster"] and known is None:
            raise Forbidden("this player id is registered for the game: check in with the registration's ticket")
        return row if row is not None and row["from_roster"] else None

    def refresh_token(self, viewer: Viewer) -> dict[str, Any]:
        game = self.store.game(viewer.game_id)
        row = self.store.checkin(viewer.game_id, viewer.player_id)
        if game is None or row is None:
            raise Unauthorized("this check-in is no longer valid")
        if game["state"] == "ended":
            raise Conflict("the game has ended")
        token, exp = self.issue_token(game, row)
        return self._token_answer(game, row, token, exp)

    def _emit_checkin_event(self, game: dict[str, Any], row: dict[str, Any]) -> None:
        """player.checkin (15) as the controller's node: the player id only, never the name."""
        fc = self.ctrl.fc
        if fc is None or self.ctrl.game is None or self.ctrl.game["id"] != game["id"]:
            log.info("check-in of %s not logged as an event: game %d is not on the radio here",
                     row["player_id"], game["id"])
            return
        with self.ctrl._lock:
            fc.controller_event("player.checkin", {"player": row["player_id"]},
                                team=self._team_name(game, row["team"]))

    # --- the player's own check-in ----------------------------------------------

    def _decl_view(self, d: dict[str, Any], refused_today: bool = False) -> dict[str, Any]:
        out = {k: d[k] for k in ("declaration_id", "replica_id", "type", "class", "make_model", "state",
                                 "reading_id")}
        if refused_today:
            out["refused_today"] = True
        return out

    def _decl_views(self, game_id: int, player_id: str) -> list[dict[str, Any]]:
        return [self._decl_view(d, self._refused_today(d)) for d in self.store.declarations(game_id, player_id)]

    def row_view(self, game: dict[str, Any], row: dict[str, Any], *, names: bool = True,
                 declarations: bool = True) -> dict[str, Any]:
        out = {"game_id": game["id"], "player_id": row["player_id"], "status": row["status"],
               "team": self._team_name(game, row["team"]), "team_id": row["team"], "squad": row["squad"],
               "role": row["role"], "manual": row["manual"], "checked_in_at": row["checked_in_at"],
               "seq": row["seq"], "registration_id": row.get("registration_id"),
               "registered": bool(row.get("registration_id"))}
        if names:
            out.update({"display_name": row["display_name"], "federation_number": row["federation_number"],
                        "federation_seen": row["federation_seen"], "team_preference": row["team_preference"]})
        if declarations:
            out["declarations"] = self._decl_views(game["id"], row["player_id"])
        return out

    def me(self, viewer: Viewer) -> dict[str, Any]:
        game = self.store.game(viewer.game_id)
        row = self.store.checkin(viewer.game_id, viewer.player_id)
        if game is None or row is None:
            raise NotFound("no check-in")
        out = self.row_view(game, row)
        out["stale_token"] = viewer.stale
        out["settings"] = {k: v for k, v in self.settings().items() if k != "max_players"}
        return out

    def _check_declarations(self, items: Any, st: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(items, list):
            raise ControllerError("replicas: a list of declarations")
        if len(items) > st["max_replicas"]:
            raise ControllerError(f"at most {st['max_replicas']} replicas per player and game")
        out = [validate_declaration(i) for i in items]
        ids = [d["declaration_id"] for d in out]
        if len(set(ids)) != len(ids):
            raise ControllerError("each declaration_id once")
        rids = [d["replica_id"] for d in out if d["replica_id"]]
        if len(set(rids)) != len(rids):
            raise ControllerError("each replica once")
        for d in out:
            if d["class"] not in self.limits["classes"]:
                raise ControllerError(f"class {d['class']!r} is not one of the field's "
                                      f"{sorted(self.limits['classes'])}")
        return out

    def _replace_declarations(self, game: dict[str, Any], pid: str, items: list[dict[str, Any]], *,
                              staff: bool, now: float) -> None:
        gid = game["id"]
        existing = {d["declaration_id"]: d for d in self.store.declarations(gid, pid)}
        new_ids = {d["declaration_id"] for d in items}
        for d in items:
            other = self.store.declaration(d["declaration_id"])
            if other is not None and (other["game_id"] != gid or other["player_id"] != pid):
                raise Conflict(f"declaration {d['declaration_id']} belongs to someone else")
        if not staff:
            for did, d in existing.items():
                if d["state"] in ("passed", "refused"):
                    kept = next((i for i in items if i["declaration_id"] == did), None)
                    if kept is None or any(kept[k] != d[k] for k in ("replica_id", "type", "class")):
                        raise Conflict("a chronographed replica stays declared; ask a marshal to change it")
        for pos, d in enumerate(items):
            old = existing.get(d["declaration_id"])
            row = {**d, "game_id": gid, "player_id": pid, "position": pos}
            if old is not None and old["state"] != "withdrawn" and old["replica_id"] == d["replica_id"]:
                row["state"], row["reading_id"] = old["state"], old["reading_id"]
            else:
                row["state"], row["reading_id"] = "pending", None
                if d["replica_id"]:
                    passed = self._passed_earlier(d["replica_id"], pid, gid, now)
                    if passed is not None:
                        row["state"], row["reading_id"] = "passed", passed
            self.store.put_declaration(row, now)
        for did, d in existing.items():
            if did not in new_ids and d["state"] != "withdrawn":
                self.store.put_declaration({**d, "state": "withdrawn"}, now)

    def put_my_replicas(self, viewer: Viewer, body: dict[str, Any]) -> dict[str, Any]:
        game = self.store.game(viewer.game_id)
        assert game is not None
        if game["state"] == "ended":
            raise Conflict("the game has ended")
        decls = self._check_declarations(body.get("replicas"), self.settings())
        with self._lock:
            self._replace_declarations(game, viewer.player_id, decls, staff=False, now=self._wall())
        self._notify(game["id"], viewer.player_id)
        return {"declarations": self._decl_views(game["id"], viewer.player_id)}

    def leave(self, viewer: Viewer) -> dict[str, Any]:
        """DELETE /api/v1/checkin/me: the player leaves the game; the personal fields are erased."""
        gid, pid = viewer.game_id, viewer.player_id
        now = self._wall()
        with self._lock:
            self.store.update_checkin(gid, pid, status="left", display_name=None, federation_number=None,
                                      federation_seen=False, team_preference=None, updated_at=now,
                                      erased_at=now)
            for d in self.store.declarations(gid, pid):
                if d["state"] == "pending":
                    self.store.put_declaration({**d, "state": "withdrawn"}, now)
        self._notify(gid, pid)
        return {"game_id": gid, "player_id": pid, "status": "left"}

    # --- staff ---------------------------------------------------------------------

    def _staff(self, viewer: Viewer, game_id: int) -> dict[str, Any]:
        if not viewer.is_staff:
            raise Forbidden("staff only: the GM token or a marshal's token")
        if viewer.kind == "player" and viewer.game_id != game_id:
            raise Forbidden("this token is for another game")
        return self.ctrl.get_game(game_id)

    def list_checkins(self, viewer: Viewer, game_id: int) -> dict[str, Any]:
        game = self._staff(viewer, game_id)
        rows = [self.row_view(game, r) for r in self.store.checkins(game_id)]
        counts = collections.Counter(r["status"] for r in rows)
        arrived = [r for r in rows if r["status"] in ("pending", "checked_in")]
        return {"game_id": game_id, "open": self.is_open(game_id), "settings": self.settings(),
                "squads": int(game.get("squads") or 0),
                "counts": {s: counts.get(s, 0) for s in STATUSES}, "checkins": rows,
                # Plan phase 16: registered players expected and arrived, and walk-ins (not registered).
                "registrations": {"expected": counts.get("expected", 0),
                                  "arrived": sum(1 for r in arrived if r["registered"]),
                                  "walkins": sum(1 for r in arrived if not r["registered"])}}

    def manual_checkin(self, viewer: Viewer, game_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """A player without the app, checked in by a marshal or the GM (ADR-P3-13)."""
        game = self._staff(viewer, game_id)
        if game["state"] == "ended":
            raise Conflict("the game has ended")
        unknown = set(body) - {"display_name", "federation_number", "team_preference", "replicas"}
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        st = self.settings()
        name = _text("display_name", body.get("display_name"), NAME_MAX)
        fed = _text("federation_number", body.get("federation_number") or None, FEDERATION_MAX, optional=True)
        if st["federation"] == "off":
            fed = None
        elif st["federation"] == "required" and fed is None:
            raise ControllerError(f"federation_number: this field asks for the {st['federation_label']} number")
        pref = body.get("team_preference")
        if pref is not None:
            self._team_id(game, pref, "team_preference")
        decls = self._check_declarations(body.get("replicas") or [], st)
        now = self._wall()
        with self._lock:
            if self.store.count_checkins(game_id) >= st["max_players"]:
                raise Forbidden(f"game {game_id} is full ({st['max_players']} players)")
            pid = new_player_id()
            while self.store.field_player(pid) is not None:
                pid = new_player_id()
            self.store.add_field_player(pid, None, now)
            self.store.add_checkin(game_id, pid, {
                "status": "checked_in", "display_name": name, "federation_number": fed,
                "federation_seen": fed is not None, "team_preference": pref, "manual": 1,
                "checked_in_at": now}, now)
            self._replace_declarations(game, pid, decls, staff=True, now=now)
            row = self.store.checkin(game_id, pid)
            assert row is not None
        self._emit_checkin_event(game, row)
        self._notify(game_id, pid)
        return self.row_view(game, row)

    def patch_checkin(self, viewer: Viewer, game_id: int, pid: str, body: dict[str, Any]) -> dict[str, Any]:
        game = self._staff(viewer, game_id)
        row = self.store.checkin(game_id, pid)
        if row is None:
            raise NotFound(f"{pid} is not checked in to game {game_id}")
        gm_fields = {"team", "squad", "role"}
        marshal_fields = {"status", "federation_seen", "replicas"}
        unknown = set(body) - gm_fields - marshal_fields
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        if gm_fields & set(body) and not viewer.is_gm_token:
            raise Forbidden("team, squad and role: the GM token only")
        if row["status"] in ("left", "removed"):
            raise Conflict(f"this check-in is {row['status']}")
        now = self._wall()
        fields: dict[str, Any] = {"updated_at": now}
        emit = False
        assignment = False
        if "team" in body:
            fields["team"] = self._team_id(game, body["team"])
        squads = int(game.get("squads") or 0)
        if "squad" in body:
            sq = body["squad"]
            if isinstance(sq, bool) or not isinstance(sq, int) or not 0 <= sq <= squads:
                raise ControllerError("squad: this game has no squads" if not squads
                                      else f"squad: 0 (none) to {squads}")
            fields["squad"] = sq
        if "role" in body:
            if body["role"] not in player_token.ROLES:
                raise ControllerError(f"role: one of {', '.join(player_token.ROLES)}")
            if body["role"] == "squad_leader" and not squads:
                raise ControllerError("role: this game has no squads, so no squad leaders")
            fields["role"] = body["role"]
        if fields.get("squad", row["squad"]) and not fields.get("team", row["team"]):
            raise ControllerError("squad: a squad is inside a team; give the team first")
        if any(k in fields and fields[k] != row[k] for k in ("team", "squad", "role")):
            assignment = True
        if "status" in body:
            if body["status"] != "checked_in":
                raise ControllerError("status: only \"checked_in\" (confirm); remove with DELETE")
            if row["status"] in ("pending", "expected"):  # a confirmation, or a registered player ticked by name
                fields["status"] = "checked_in"
                fields["checked_in_at"] = now
                emit = True
        if "federation_seen" in body:
            if not isinstance(body["federation_seen"], bool):
                raise ControllerError("federation_seen: true or false")
            fields["federation_seen"] = body["federation_seen"]
        with self._lock:
            if "replicas" in body:
                decls = self._check_declarations(body["replicas"], self.settings())
                self._replace_declarations(game, pid, decls, staff=True, now=now)
            self.store.update_checkin(game_id, pid, **fields)
            row = self.store.checkin(game_id, pid)
            assert row is not None
        if emit:
            self._emit_checkin_event(game, row)
        self._notify(game_id, pid, assignment=assignment)
        return self.row_view(game, row)

    def remove_checkin(self, viewer: Viewer, game_id: int, pid: str) -> dict[str, Any]:
        game = self._staff(viewer, game_id)
        if not viewer.is_gm_token:
            raise Forbidden("removing a check-in: the GM token only")
        row = self.store.checkin(game_id, pid)
        if row is None:
            raise NotFound(f"{pid} is not checked in to game {game_id}")
        now = self._wall()
        with self._lock:
            self.store.update_checkin(game_id, pid, status="removed", display_name=None,
                                      federation_number=None, federation_seen=False, team_preference=None,
                                      updated_at=now, erased_at=now)
            for d in self.store.declarations(game_id, pid):
                if d["state"] == "pending":
                    self.store.put_declaration({**d, "state": "withdrawn"}, now)
        self._notify(game_id, pid, assignment=True)
        return {"game_id": game["id"], "player_id": pid, "status": "removed"}

    # --- registrations from a site server (plan phase 16) -----------------------------------

    def ticket_checkin(self, viewer: Viewer, game_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """POST /api/v1/games/{id}/checkins/ticket: a marshal scans a registered player's printed
        ``atalaia:ticket:`` code. The registration must be in this game's roster and the ticket its own;
        the player is checked in at once (staff saw them). Scanning it again changes nothing."""
        game = self._staff(viewer, game_id)
        if game["state"] == "ended":
            raise Conflict("the game has ended")
        if set(body) - {"ticket"}:
            raise ControllerError(f"unknown fields {sorted(set(body) - {'ticket'})}")
        try:
            ticket = ticketfmt.parse(body.get("ticket"))
        except ticketfmt.TicketError as exc:
            raise ControllerError(f"ticket: {exc}") from None
        digest = ticketfmt.secret_sha256(ticket["secret"])
        now = self._wall()
        with self._lock:
            row = self.store.checkin_by_registration(game_id, ticket["registration_id"])
            if row is None or not row["from_roster"]:
                raise NotFound("this ticket's registration is not on this game's roster")
            if row["player_id"] != ticket["player_id"] or not row["ticket_sha256"] \
                    or not hmac.compare_digest(row["ticket_sha256"], digest):
                raise Forbidden("this ticket is not this registration's (was a newer one made?)")
            if row["status"] == "removed":
                raise Forbidden("staff removed this check-in")
            emit = row["status"] == "expected"
            if emit:
                st = self.settings()
                if self.store.count_checkins(game_id) >= st["max_players"]:
                    raise Forbidden(f"game {game_id} is full ({st['max_players']} players)")
                self.store.update_checkin(game_id, row["player_id"], status="checked_in", checked_in_at=now,
                                          updated_at=now)
            row = self.store.checkin(game_id, row["player_id"])
            assert row is not None
        if emit:
            self._emit_checkin_event(game, row)
        self._notify(game_id, row["player_id"])
        return self.row_view(game, row)

    def apply_roster(self, game_id: int, roster: dict[str, Any]) -> dict[str, Any]:
        """A roster pulled from the site server (checked by ``sync_format.check_roster``) becomes this
        game's expected check-ins, until the game starts (ADR-P4-11): new registrations are added with
        their declarations ``pending``, an expected one takes the roster's latest data, a cancelled one
        that has not arrived goes, and anyone already at the field stays as the controller has them.
        A declaration this field's check-in would refuse (a class of another limit template, a declaration
        id another player holds, more than ``max_replicas``) is dropped and counted."""
        out = {"added": 0, "updated": 0, "removed": 0, "kept": 0, "conflicts": 0, "dropped_declarations": 0,
               "frozen": False}
        game = self.store.game(game_id)
        if game is None or game["state"] != "ready":
            out["frozen"] = True  # started (or gone): the controller's list is the authority now
            return out
        st = self.settings()
        now = self._wall()
        listed: set[str] = set()
        with self._lock:
            for reg in roster["registrations"]:
                pid, rid = reg["player_id"], reg["registration_id"]
                listed.add(rid)
                by_reg = self.store.checkin_by_registration(game_id, rid)
                row = self.store.checkin(game_id, pid)
                if (by_reg is not None and by_reg["player_id"] != pid) or (
                        row is not None and row["registration_id"] not in (None, rid)):
                    out["conflicts"] += 1
                    continue
                try:
                    name = _text("display_name", reg["display_name"], NAME_MAX)
                except ControllerError:
                    out["conflicts"] += 1
                    continue
                fed = reg.get("federation_number") if st["federation"] != "off" else None
                pref = reg.get("team_preference") if reg.get("team_preference") in game["teams"] else None
                decls = self._roster_declarations(game_id, pid, reg["replicas"], st, out)
                fields = {"display_name": name, "federation_number": fed, "team_preference": pref,
                          "registration_id": rid, "ticket_sha256": reg.get("ticket_sha256"), "from_roster": 1}
                if row is None:
                    self.store.add_checkin(game_id, pid, {"status": "expected", **fields}, now)
                    self._replace_declarations(game, pid, decls, staff=True, now=now)
                    out["added"] += 1
                elif row["status"] == "expected":
                    self.store.update_checkin(game_id, pid, **fields, updated_at=now)
                    self._replace_declarations(game, pid, decls, staff=True, now=now)
                    out["updated"] += 1
                else:
                    if row["registration_id"] is None:  # a walk-in who turns out to be registered
                        self.store.update_checkin(game_id, pid, registration_id=rid, from_roster=1,
                                                  ticket_sha256=reg.get("ticket_sha256"), updated_at=now)
                    out["kept"] += 1
            for row in self.store.checkins(game_id):
                if row["status"] == "expected" and row["registration_id"] not in listed:
                    self.store.delete_checkin(game_id, row["player_id"])
                    out["removed"] += 1
        if any(out[k] for k in ("added", "updated", "removed")):
            self.ctrl._emit({"type": "roster", "game": game_id, "counts": dict(out), "_staff": True})
            log.info("roster for game %d: %s", game_id, out)  # ids and counts only, never a name
        return out

    def _roster_declarations(self, game_id: int, pid: str, items: list[dict[str, Any]], st: dict[str, Any],
                             out: dict[str, Any]) -> list[dict[str, Any]]:
        decls = []
        for item in items:
            try:
                d = validate_declaration(item)
            except ControllerError:
                out["dropped_declarations"] += 1
                continue
            other = self.store.declaration(d["declaration_id"])
            if d["class"] not in self.limits["classes"] or len(decls) >= st["max_replicas"] or (
                    other is not None and (other["game_id"] != game_id or other["player_id"] != pid)):
                out["dropped_declarations"] += 1
                continue
            decls.append(d)
        return decls

    def outcomes(self, game_id: int) -> dict[str, Any]:
        """What goes back to the site server after the game (POST /api/v1/sync/checkins): per registration
        its outcome (``checked_in``: the player came; ``no_show``) and its declarations' final states, and
        the walk-ins as a count. No names, no federation numbers. A registration this controller had only
        from the app (no roster) carries its ticket's hash, which the site server checks."""
        regs, walkins = [], 0
        for r in self.store.checkins(game_id):
            arrived = r["status"] in ARRIVED or (r["status"] == "removed" and r["checked_in_at"] is not None)
            if not r["registration_id"]:
                walkins += arrived
                continue
            if not r["from_roster"] and not r["ticket_sha256"]:
                continue
            entry: dict[str, Any] = {
                "registration_id": r["registration_id"], "player_id": r["player_id"],
                "outcome": "checked_in" if arrived else "no_show",
                "declarations": [{"declaration_id": d["declaration_id"], "state": d["state"],
                                  "reading_id": d["reading_id"]}
                                 for d in self.store.declarations(game_id, r["player_id"])][:20]}
            if not r["from_roster"]:
                entry["ticket_sha256"] = r["ticket_sha256"]
            regs.append(entry)
        return {"registrations": regs, "walkins": int(walkins)}

    def csv_export(self, game_id: int) -> str:
        game = self.ctrl.get_game(game_id)
        out = io.StringIO()
        w = csv.writer(out, lineterminator="\r\n")
        w.writerow(["player_id", "display_name", "status", "team", "squad", "role", "federation_number",
                    "card_seen", "manual", "checked_in_at", "declaration_id", "replica_id", "type", "class",
                    "make_model", "chrono"])
        for r in self.store.checkins(game_id):
            base = [r["player_id"], _csv_safe(r["display_name"]), r["status"],
                    self._team_name(game, r["team"]) or "", r["squad"] or "", r["role"],
                    _csv_safe(r["federation_number"]), "yes" if r["federation_seen"] else "",
                    "yes" if r["manual"] else "",
                    _iso(r["checked_in_at"])]
            decls = self.store.declarations(game_id, r["player_id"]) or [None]
            for d in decls:
                if d is None:
                    w.writerow(base + [""] * 6)
                else:
                    w.writerow(base + [d["declaration_id"], d["replica_id"] or "", d["type"], d["class"],
                                       _csv_safe(d["make_model"]), d["state"]])
        return out.getvalue()

    # --- the "replicas to chrono" list -------------------------------------------------

    def _refused_today(self, d: dict[str, Any]) -> bool:
        if d["state"] != "pending" or not d["replica_id"]:
            return False
        today = self.local_day(self._wall())
        for r in self.store.readings(replica_id=d["replica_id"], player_id=d["player_id"]):
            if r["type"] != "spotcheck" and r["outcome"] == "fail" and self._reading_day(r) == today:
                return True
        return False

    def _reading_day(self, r: dict[str, Any]) -> datetime.date:
        ts = datetime.datetime.strptime(r["timestamp"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=datetime.timezone.utc).timestamp()
        return self.local_day(ts)

    def _passed_earlier(self, replica_id: str, pid: str, game_id: int, now: float) -> Optional[str]:
        """With chrono_valid_for = "day": the deciding reading of a passing check-in series for this
        replica earlier on the field's day (in any game), if its latest series passed."""
        if self.settings()["chrono_valid_for"] != "day":
            return None
        today = self.local_day(now)
        series: dict[str, list[dict[str, Any]]] = {}
        for r in self.store.readings(replica_id=replica_id, player_id=pid):
            if r["type"] != "spotcheck" and r["outcome"] in ("pass", "fail") and self._reading_day(r) == today:
                series.setdefault(r["series_id"], []).append(r)
        if not series:
            return None
        latest = max(series.values(), key=lambda rs: max(x["received_at"] for x in rs))
        if latest[0]["outcome"] != "pass":
            return None
        return max(latest, key=lambda x: (x["record"]["energy_j"], x["reading_id"]))["reading_id"]

    def chrono_list(self, viewer: Viewer, game_id: int) -> dict[str, Any]:
        game = self._staff(viewer, game_id)
        return self._chrono_list(game)

    def _chrono_list(self, game: dict[str, Any]) -> dict[str, Any]:
        gid = game["id"]
        players = []
        counts = collections.Counter()
        for r in self.store.checkins(gid):
            if r["status"] in ("left", "removed"):
                continue
            decls = [self._decl_view(d, self._refused_today(d)) for d in self.store.declarations(gid, r["player_id"])
                     if d["state"] != "withdrawn"]
            for d in decls:
                counts[d["state"]] += 1
            if not decls:
                continue
            players.append({"player_id": r["player_id"], "display_name": r["display_name"],
                            "status": r["status"], "team": self._team_name(game, r["team"]),
                            "squad": r["squad"], "seq": r["seq"],
                            "pending": sum(1 for d in decls if d["state"] == "pending"),
                            "declarations": decls})
        players.sort(key=lambda p: (p["pending"] == 0, p["seq"]))
        return {"game_id": gid, "squads": int(game.get("squads") or 0),
                "counts": {s: counts.get(s, 0) for s in ("pending", "passed", "refused")},
                "chrono_valid_for": self.settings()["chrono_valid_for"], "players": players}

    def pending_count(self, game_id: int) -> int:
        """Pending declarations of the players at the field (not of registered players who never came)."""
        game = self.store.game(game_id)
        if game is None:
            return 0
        return sum(p["pending"] for p in self._chrono_list(game)["players"] if p["status"] != "expected")

    # --- marshals and readings -------------------------------------------------------

    def _public_key(self, value: Any) -> bytes:
        if not isinstance(value, str):
            raise ControllerError("public_key: the Ed25519 public key, 32 bytes in base64 or hex")
        raw = None
        if re.fullmatch(r"[0-9a-fA-F]{64}", value):
            raw = bytes.fromhex(value)
        else:
            try:
                raw = base64.b64decode(value, validate=True)
            except binascii.Error:
                raw = None
        if raw is None or len(raw) != 32:
            raise ControllerError("public_key: the Ed25519 public key, 32 bytes in base64 or hex")
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: PLC0415

        try:
            Ed25519PublicKey.from_public_bytes(raw)
        except ValueError:
            raise ControllerError("public_key: not an Ed25519 public key") from None
        return raw

    def register_marshal(self, body: dict[str, Any], player_id: Optional[str] = None) -> dict[str, Any]:
        unknown = set(body) - {"marshal_id", "name", "public_key", "player_id"}
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        mid = body.get("marshal_id")
        if not isinstance(mid, str) or not MARSHAL_ID_RE.fullmatch(mid):
            raise ControllerError("marshal_id: 1-64 of A-Z a-z 0-9 . _ : -")
        name = _text("name", body.get("name"), 64)
        key = self._public_key(body.get("public_key"))
        pid = player_id if player_id is not None else body.get("player_id")
        if pid is not None and not isinstance(pid, str):
            raise ControllerError("player_id: text")
        with self._lock:
            existing = self.store.marshal(mid)
            if existing is not None and player_id is not None and existing["player_id"] not in (None, player_id):
                raise Conflict(f"marshal id {mid} is someone else's")
            self.store.put_marshal(mid, name, key, pid, self._wall())
        log.info("marshal key registered: %s", mid)
        return {"marshal_id": mid, "name": name, "public_key": base64.b64encode(key).decode("ascii"),
                "player_id": pid}

    def marshals(self) -> list[dict[str, Any]]:
        return [{"marshal_id": m["marshal_id"], "name": m["name"], "player_id": m["player_id"],
                 "public_key": base64.b64encode(m["public_key"]).decode("ascii"),
                 "registered_at": m["registered_at"]} for m in self.store.marshals()]

    def upload_readings(self, viewer: Viewer, body: dict[str, Any]) -> dict[str, Any]:
        """POST /api/v1/chrono/readings: one series of signed readings (protocol/checkin.md)."""
        if not (viewer.is_gm_token or (viewer.kind == "player" and viewer.role in STAFF_ROLES)):
            raise Forbidden("chrono readings come from a marshal's token")
        unknown = set(body) - {"readings", "declaration_id", "replica"}
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        items = body.get("readings")
        if not isinstance(items, list) or not 1 <= len(items) <= SERIES_MAX:
            raise ControllerError(f"readings: 1 to {SERIES_MAX} signed records of one series")
        reasons = []
        checked = []
        for i, rec in enumerate(items):
            try:
                fields = chrono.check(rec)
                m = self.store.marshal(fields["marshal_id"])
                if "signature" not in rec:
                    raise chrono.ChronoError("unsigned", "the record has no signature")
                if m is None:
                    raise chrono.ChronoError("marshal", f"marshal {fields['marshal_id']} is not registered here")
                fields = chrono.verify(rec, m["public_key"])
                if fields["field_id"] != self.cfg.field_id:
                    raise chrono.ChronoError("field", f"the record is for field {fields['field_id']}")
                checked.append((rec, fields))
            except chrono.ChronoError as exc:
                reasons.append({"index": i, "reading_id": rec.get("reading_id") if isinstance(rec, dict) else None,
                                "reason": exc.reason, "detail": str(exc)})
        if reasons:
            raise Refused("readings refused: nothing was stored", reasons)
        first = checked[0][1]
        for _, f in checked:
            if (f["replica_id"], f["player_id"], f["type"]) != (first["replica_id"], first["player_id"],
                                                                 first["type"]):
                raise ControllerError("one series per request: the same replica, player and type")
        ids = [f["reading_id"] for _, f in checked]
        if len(set(ids)) != len(ids):
            raise ControllerError("each reading once")
        game = self._reading_game(first)
        with self._lock:
            stored = self.store.readings(reading_ids=ids)
            if stored:
                if len(stored) == len(ids):  # a resend: nothing changes
                    out = {"series_id": stored[0]["series_id"], "outcome": stored[0]["outcome"],
                           "duplicate": True, "stored": 0}
                    if game:
                        out["declarations"] = self._decl_views(game["id"], first["player_id"])
                    return out
                raise Conflict("some of these readings were stored with another series")
            self._link(first, body, game)
            rclass = self._class_for(first, game)
            judged = self._judge(first["type"], [f for _, f in checked], rclass, first)
            series_id = str(uuid.uuid4())
            now = self._wall()
            for rec, _ in checked:
                self.store.add_reading(rec, series_id, judged["outcome"], now)
            changed = []
            if game is not None and first["type"] != "spotcheck" and judged["outcome"] in ("pass", "fail"):
                changed = self._apply(game, first, judged, now)
        self._chrono_events(game, first, judged)
        if game is not None:
            self._notify(game["id"], first["player_id"])
        out = {"series_id": series_id, "outcome": judged["outcome"], "stored": len(checked),
               "highest_energy_j": judged["highest"]["energy_j"], "limit_j": judged["limit_j"],
               "class": rclass, "duplicate": False, "changed": changed}
        if game is not None:
            out["declarations"] = self._decl_views(game["id"], first["player_id"])
        return out

    def _reading_game(self, f: dict[str, Any]) -> Optional[dict[str, Any]]:
        gid = f.get("game_id")
        if gid is not None:
            if not gid.isdigit():
                return None
            return self.store.game(int(gid))
        live = self.ctrl.game
        return self.store.game(live["id"]) if live else None

    def _link(self, f: dict[str, Any], body: dict[str, Any], game: Optional[dict[str, Any]]) -> None:
        """Registers the replica (if sent) and links a declaration that had no replica id yet."""
        rep = body.get("replica")
        if rep is not None:
            if not isinstance(rep, dict) or rep.get("replica_id") != f["replica_id"] \
                    or rep.get("owner_player_id") != f["player_id"]:
                raise ControllerError("replica: the registry record of the readings' replica and player")
            rc = rep.get("class")
            if not isinstance(rc, str) or not CLASS_RE.fullmatch(rc) or rep.get("type") not in REPLICA_TYPES:
                raise ControllerError("replica: a type and a class are required")
            self.store.put_replica({k: rep[k] for k in rep if k in (
                "replica_id", "owner_player_id", "type", "class", "make_model", "registered_at", "tag_type",
                "tag_uid")}, self._wall())
        did = body.get("declaration_id")
        if did is None:
            return
        d = self.store.declaration(did) if isinstance(did, str) else None
        if d is None:
            raise NotFound("no such declaration")
        if d["player_id"] != f["player_id"] or (game is not None and d["game_id"] != game["id"]):
            raise Conflict("that declaration is another player's or another game's")
        if d["replica_id"] not in (None, f["replica_id"]):
            raise Conflict("that declaration is for another replica")
        if d["replica_id"] is None:
            self.store.put_declaration({**d, "replica_id": f["replica_id"]}, self._wall())

    def _class_for(self, f: dict[str, Any], game: Optional[dict[str, Any]]) -> Optional[str]:
        if game is not None:
            for d in self.store.declarations(game["id"], f["player_id"]):
                if d["replica_id"] == f["replica_id"] and d["state"] != "withdrawn":
                    return d["class"]
        rep = self.store.replica(f["replica_id"])
        if rep is not None:
            return rep.get("class")
        for d in reversed(self.store.declarations_for_replica(f["replica_id"], f["player_id"])):
            return d["class"]
        return None

    def _judge(self, rtype: str, fields: list[dict[str, Any]], rclass: Optional[str],
               first: dict[str, Any]) -> dict[str, Any]:
        """ADR-P3-7 and decision B11: the series' highest energy against the class limit; a spot check
        also against the replica's last passing check-in plus the tolerance."""
        highest = max(fields, key=lambda f: (f["energy_j"], f["reading_id"]))
        limit = self.limits["classes"].get(rclass) if rclass else None
        out = {"highest": highest, "limit_j": limit["max_energy_j"] if limit else None, "outcome": None,
               "tolerance_pct": None, "checkin_j": None}
        if limit is None:
            out["outcome"] = "unjudged"  # no class known: stored, the list does not change
            return out
        if rtype != "spotcheck":
            out["outcome"] = "pass" if highest["energy_j"] <= limit["max_energy_j"] else "fail"
            return out
        tol = 5.0
        out["tolerance_pct"] = tol
        last = self._last_pass(first["replica_id"], first["player_id"])
        out["checkin_j"] = last
        if highest["energy_j"] > limit["max_energy_j"]:
            out["outcome"] = "fail"
        elif last is not None and highest["energy_j"] > last * (1 + tol / 100):
            out["outcome"] = "warn"
        else:
            out["outcome"] = "pass"
        return out

    def _last_pass(self, replica_id: str, pid: str) -> Optional[float]:
        series: dict[str, list[dict[str, Any]]] = {}
        for r in self.store.readings(replica_id=replica_id, player_id=pid):
            if r["type"] != "spotcheck" and r["outcome"] == "pass":
                series.setdefault(r["series_id"], []).append(r)
        if not series:
            return None
        latest = max(series.values(), key=lambda rs: max(x["received_at"] for x in rs))
        return max(x["record"]["energy_j"] for x in latest)

    def _apply(self, game: dict[str, Any], f: dict[str, Any], judged: dict[str, Any], now: float) -> list[str]:
        state = "passed" if judged["outcome"] == "pass" else "refused"
        changed = []
        for d in self.store.declarations(game["id"], f["player_id"]):
            if d["replica_id"] == f["replica_id"] and d["state"] != "withdrawn":
                self.store.put_declaration({**d, "state": state, "reading_id": judged["highest"]["reading_id"]},
                                           now)
                changed.append(d["declaration_id"])
        return changed

    def _chrono_events(self, game: Optional[dict[str, Any]], f: dict[str, Any], judged: dict[str, Any]) -> None:
        """chrono.checkin (35) once per passing series; spot checks: chrono.spotcheck (36), and
        chrono.violation (17) on WARN or FAIL. A refusal adds no event (it is in the list)."""
        ctrl = self.ctrl
        if game is None or ctrl.fc is None or ctrl.game is None or ctrl.game["id"] != game["id"]:
            return
        h = judged["highest"]
        base = {"replica": f["replica_id"], "player": f["player_id"], "reading_mps": h["velocity_mps"],
                "bb_g": h["bb_weight_g"]}
        with ctrl._lock:
            if f["type"] != "spotcheck":
                if judged["outcome"] == "pass":
                    ctrl.fc.controller_event("chrono.checkin", base)
                return
            if judged["outcome"] in ("pass", "warn", "fail"):
                ctrl.fc.controller_event("chrono.spotcheck", {**base, "tolerance_pct": judged["tolerance_pct"]})
            if judged["outcome"] in ("warn", "fail"):
                ctrl.fc.controller_event("chrono.violation", {
                    "replica": f["replica_id"], "reading_mps": h["velocity_mps"], "bb_g": h["bb_weight_g"],
                    "limit_j": judged["limit_j"]}, prio="critical")

    def player_readings(self, pid: str) -> list[dict[str, Any]]:
        return [r["record"] for r in self.store.readings(player_id=pid)]

    def erase_player(self, pid: str, chrono_too: bool = False) -> dict[str, Any]:
        with self._lock:
            games = {r["game_id"] for g in self.store.games() for r in [self.store.checkin(g["id"], pid)] if r}
            self.store.erase_player(pid)
            readings = self.store.delete_readings(player_id=pid) if chrono_too else 0
        for gid in games:
            self.ctrl._emit({"type": "checkin", "game": gid, "player_id": pid, "erased": True, "_staff": True})
        return {"player_id": pid, "erased": True, "readings_deleted": readings}

    # --- retention -----------------------------------------------------------------

    def purge(self, force: bool = False) -> Optional[dict[str, Any]]:
        now = self._wall()
        if not force and now - self._last_purge < 600:
            return None
        self._last_purge = now
        out = self.store.purge_checkins(now - self.cfg.retention_days * 86400, now - IDENTITY_DAYS * 86400,
                                        now)
        cutoff = datetime.datetime.fromtimestamp(now - CHRONO_RETENTION_DAYS * 86400, datetime.timezone.utc)
        out["readings"] = self.store.delete_readings(before=cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"))
        # A marshal's earlier keys outlive what they signed by the same period (schema 6).
        out["marshal_keys"] = self.store.delete_marshal_history(now - CHRONO_RETENTION_DAYS * 86400)
        if any(out.values()):
            log.info("retention purge: %s", out)
        return out

    # --- the stream ----------------------------------------------------------------

    def _notify(self, game_id: int, pid: str, assignment: bool = False) -> None:
        """Tells staff connections (names included) and the player's own connections what changed."""
        game = self.store.game(game_id)
        row = self.store.checkin(game_id, pid)
        if game is None or row is None:
            return
        view = self.row_view(game, row)
        self.ctrl._emit({"type": "checkin", "game": game_id, "checkin": view, "assignment": assignment,
                         "_staff": True, "_player": pid, "_assignment": assignment})
        self.ctrl._emit({"type": "chrono_list", "game": game_id, "player_id": pid,
                         "declarations": [d for d in view["declarations"] if d["state"] != "withdrawn"],
                         "counts": self._chrono_list(game)["counts"], "_staff": True, "_player": pid})


def _iso(ts: Optional[float]) -> str:
    if not ts:
        return ""
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _csv_safe(value: Optional[str]) -> str:
    """No formula injection when the CSV is opened in a spreadsheet."""
    if not value:
        return ""
    return "'" + value if value[0] in "=+-@\t\r" else value
