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
import os
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
from . import apd as apdfmt
from . import checkin_poster as posterfmt
from .addresses import FieldAddresses, saved_poster_urls, warn_dropped
from . import checkin_ticket as ticketfmt
from . import import_format as importfmt
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
# What a check-in forgets of the card check (leaving, removal, retention): protocol/apd.md "The card check".
ERASED_CARD = {"apd_verdict": None, "apd_verdict_on": None, "card_checked_by": None, "card_checked_at": None}
FEDERATION_MAX = 32
SERIES_MAX = 50
MARSHAL_VALID_FOR_S = 2 * 3600  # how long a phone may act as a marshal offline after the controller said yes (MR-4)
RANK = {"spectator": 0, "player": 1, "squad_leader": 2, "vip": 2, "marshal": 3, "gm": 4}
STAFF_ROLES = ("marshal", "gm")
LIMIT_TEMPLATES = REPO_ROOT / "app" / "lib" / "chrono" / "limit_templates"
NOTICES = Path(__file__).resolve().parent.parent / "templates"
TOKEN_GRACE_S = 2 * 3600
TOKEN_MIN_S = 60
IDENTITY_DAYS = 365
CHRONO_RETENTION_DAYS = 365  # the default of ``chrono_retention_days`` (the field's setting, 30-3653)
GAME_RETENTION_DAYS = 365    # the default of ``game_retention_days`` (decision RET-1)
RETENTION_KEYS = ("chrono_retention_days", "game_retention_days")
RETENTION_MIN, RETENTION_MAX = 30, 3653
PLAYER_HIDDEN = ("max_players", *RETENTION_KEYS)  # settings the player's app is not told
SITE_LIMITS_SETTING = "checkin.site_limits"  # the limit template the site server sent (BR24), as it sent it
SETTINGS_KEYS = ("confirm", "federation", "federation_label", "max_replicas", "max_players",
                 "chrono_valid_for", "apd", "country", *RETENTION_KEYS)
RETENTION_SITE_SETTING = "checkin.retention_site"  # the retention days the site server sent (JSON: key to days)
APD_SITE_SETTING = "checkin.apd_site"  # the field's APD rule from the site server's settings (branding = "site")
COUNTRY_SITE_SETTING = "checkin.country_site"  # ... and its country (JSON: a code or null; empty: the site sent none)
IMPORT_NS = uuid.UUID("6f1b5f0e-3c1d-5a7e-9b44-0a7a1a1a0001")  # registration ids of an imported list (uuid5 of source + ref)
IMPORT_LISTED = 100  # external refs listed as missing in an import's answer


class Unauthorized(ControllerError):
    status = 401


class Forbidden(ControllerError):
    status = 403


class TooMany(ControllerError):
    status = 429


class ImportRefused(ControllerError):
    """A registration list refused whole (``import_format.FileError``): the message is its code."""

    @property
    def status(self) -> int:  # type: ignore[override]
        return 413 if str(self) in ("too_large", "too_many_rows") else 400

    def __init__(self, code: str, line: Optional[int] = None) -> None:
        super().__init__(code)
        self.code, self.line = code, line


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


def _days_ok(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and RETENTION_MIN <= value <= RETENTION_MAX


def _share_choice(body: dict[str, Any]) -> Optional[bool]:
    """The player's own choice to share their position during the game (``share_position``, an unticked box
    on the form): None when the body does not say, so an older client changes nothing."""
    v = body.get("share_position")
    if v is not None and not isinstance(v, bool):
        raise ControllerError("share_position: true or false")
    return v


def _text(name: str, value: Any, max_chars: int, optional: bool = False) -> Optional[str]:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise ControllerError(f"{name}: text")
    value = value.strip()
    if not 1 <= len(value) <= max_chars or not _printable(value):
        raise ControllerError(f"{name}: 1-{max_chars} characters without control characters")
    return value


def declared_membership(body: dict[str, Any]) -> dict[str, Optional[str]]:
    """The membership a body declares: ``apd_id``, ``membership_number`` (or the old ``federation_number``, the
    same value: both must agree) and ``membership_expires``; missing and null are None (protocol/apd.md)."""
    number = _text("membership_number", body.get("membership_number") or None, FEDERATION_MAX, optional=True)
    old = _text("federation_number", body.get("federation_number") or None, FEDERATION_MAX, optional=True)
    if number is not None and old is not None and number != old:
        raise ControllerError("membership_number and federation_number are the same value: send one")
    value = {"apd": body.get("apd_id"), "number": number if number is not None else old,
             "expires": body.get("membership_expires")}
    if value["apd"] == "":
        value["apd"] = None
    if value["expires"] == "":
        value["expires"] = None
    try:
        return apdfmt.check_membership(value)
    except apdfmt.ApdError as exc:
        raise ControllerError(f"apd_id, membership_number, membership_expires: {exc}") from None


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


def site_limits(template: dict[str, Any]) -> dict[str, Any]:
    """A limit template as the site server sends it (``sync_format.check_field_settings``), in the shape
    ``load_limits`` returns."""
    return {"id": template["id"], "name": template["name"], "status": template.get("status"),
            "classes": {str(n): {"max_energy_j": float(c["max_energy_j"]), "med_m": c.get("med_m"),
                                 "fire_mode": c.get("fire_mode")} for n, c in template["classes"].items()}}


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


# --- what changed since the poster was last printed (decision check-R8) ---------


def poster_change(printed: Optional[dict[str, Any]], urls: list[str],
                  ca_hex: Optional[str]) -> Optional[dict[str, Any]]:
    """How the poster now differs from the one last printed: None when nothing was printed yet, there is no
    poster to compare, or its addresses and CA are the same (in any order). Otherwise ``added`` and
    ``removed`` addresses, ``ca_changed`` and ``still_works``: whether a printed poster still reaches the
    controller (the CA is the same and at least one of its addresses is still listed). The same on the
    phone controller (controller_checkin.dart); shared cases ``poster_change`` in protocol/vectors/checkin.json."""
    if not printed or not urls or not ca_hex:
        return None
    old_urls = [u for u in printed.get("urls") or [] if isinstance(u, str)]
    added = [u for u in urls if u not in old_urls]
    removed = [u for u in old_urls if u not in urls]
    ca_changed = bool(printed.get("ca_sha256")) and printed.get("ca_sha256") != ca_hex
    if not added and not removed and not ca_changed:
        return None
    return {"added": added, "removed": removed, "ca_changed": ca_changed,
            "still_works": not ca_changed and any(u in urls for u in old_urls)}


# --- the service -------------------------------------------------------------


class Checkin:
    def __init__(self, controller: "Controller", *, ca_sha256: Optional[bytes] = None,
                 default_urls: Optional[list[str]] = None, wall: Callable[[], float] = time.time,
                 tz: Optional[datetime.tzinfo] = None, addresses: Optional[FieldAddresses] = None) -> None:
        self.ctrl = controller
        self.cfg = controller.cfg
        self.store = controller.store
        self.ca_sha256 = ca_sha256
        self.default_urls = list(default_urls or [])
        # With the host's addresses (main.build), a saved poster's or [checkin] urls' address that is not
        # on an interface now is left out, warned about and dropped from the saved poster at start
        # (check-R8); without, the lists are used as given (tests).
        self.addresses = addresses
        self.explicit_urls: list[str] = []
        if addresses is not None:
            self._rederive()
        self._wall = wall
        self._tz = tz  # None: the controller's local time zone
        self._lock = threading.RLock()
        self.limits = load_limits(self.cfg.limit_template)
        self._use_site_limits()
        self.rate = RateLimit(self.cfg.rate_per_minute)
        self.info_rate = RateLimit(max(60, self.cfg.rate_per_minute * 6))
        self._last_purge = 0.0
        controller.checkin = self

    # --- settings and the poster -----------------------------------------------

    def _use_site_limits(self) -> None:
        """With ``[sync] branding = "site"``: the limit template the site server sent last, kept in the store,
        instead of the configured one (so a controller that restarts offline keeps the field's rules)."""
        if getattr(self.cfg, "sync_branding", "local") != "site":
            return
        try:
            saved = json.loads(self.store.get_setting(SITE_LIMITS_SETTING) or "null")
            if isinstance(saved, dict):
                self.limits = site_limits(saved)
        except (ValueError, KeyError, TypeError):
            log.warning("the limit template saved from the site server is unreadable: the configured one is used")

    def apply_site_settings(self, site: dict[str, Any]) -> int:
        """The field's check-in settings from the site server (``GET /api/v1/sync/field``, with ``[sync] branding
        = "site"``; checked by ``sync_format.check_field_settings``): its federation label (when it has one),
        ``max_replicas`` and limit template replace this controller's, so a registration the site server accepted
        is one this controller accepts (decision S16-6, BR24). Returns how many of the three changed."""
        changed = 0
        cur = self.settings()
        spec: dict[str, Any] = {"max_replicas": site["max_replicas"]}
        if site["federation_label"] is not None:
            spec["federation_label"] = site["federation_label"]
        spec = {k: v for k, v in spec.items() if cur[k] != v}
        if spec:
            self.set_settings(spec)
            changed += len(spec)
        if "apd" in site and self.store.get_setting(APD_SITE_SETTING) != json.dumps(site["apd"], sort_keys=True):
            self.set_site_apd(site["apd"])  # the field's APD rule (protocol/apd.md); an older site server sends none
            changed += 1
            if not spec:
                self.ctrl._emit({"type": "checkin_settings", "settings": self.settings(), "_staff": True})
        if "country" in site and self.store.get_setting(COUNTRY_SITE_SETTING) != json.dumps(site["country"]):
            self.store.set_setting(COUNTRY_SITE_SETTING, json.dumps(site["country"]))  # an older site sends none
            changed += 1
            if not spec:
                self.ctrl._emit({"type": "checkin_settings", "settings": self.settings(), "_staff": True})
        sent = {k: site[k] for k in RETENTION_KEYS if k in site}  # an older site server sends none
        if sent:
            try:
                before = json.loads(self.store.get_setting(RETENTION_SITE_SETTING) or "{}")
            except ValueError:
                before = {}
            merged = {**(before if isinstance(before, dict) else {}), **sent}
            if merged != before:
                self.store.set_setting(RETENTION_SITE_SETTING, json.dumps(merged, sort_keys=True))
                changed += 1
                if not spec:
                    self.ctrl._emit({"type": "checkin_settings", "settings": self.settings(), "_staff": True})
        template = site["limit_template"]
        if self.store.get_setting(SITE_LIMITS_SETTING) != json.dumps(template, sort_keys=True):
            self.limits = site_limits(template)
            self.store.set_setting(SITE_LIMITS_SETTING, json.dumps(template, sort_keys=True))
            changed += 1
            if not spec:  # set_settings told the console about the others
                self.ctrl._emit({"type": "checkin_settings", "settings": self.settings(), "_staff": True})
        return changed

    def settings(self) -> dict[str, Any]:
        out = {"confirm": self.cfg.checkin_confirm, "federation": self.cfg.federation,
               "federation_label": self.cfg.federation_label, "max_replicas": self.cfg.max_replicas,
               "max_players": self.cfg.max_players, "chrono_valid_for": self.cfg.chrono_valid_for,
               "chrono_retention_days": self.cfg.chrono_retention_days,
               "game_retention_days": self.cfg.game_retention_days}
        out["apd"] = self._local_apd()
        out["country"] = self._local_country()
        saved = self.store.get_setting("checkin.settings")
        if saved:
            try:
                out.update({k: v for k, v in json.loads(saved).items() if k in SETTINGS_KEYS and k not in ("apd", "country")})
            except ValueError:
                pass
        for key, days in self._site_retention().items():
            out[key] = days
        if getattr(self.cfg, "sync_branding", "local") == "site":
            site_country = self.store.get_setting(COUNTRY_SITE_SETTING)
            if site_country:
                try:
                    out["country"] = apdfmt.check_country(json.loads(site_country))
                except (ValueError, apdfmt.ApdError):
                    pass
            raw = self.store.get_setting(APD_SITE_SETTING)
            if raw:
                try:
                    out["apd"] = apdfmt.check_rule(json.loads(raw))
                except (ValueError, apdfmt.ApdError):
                    pass
        return out

    def _site_retention(self) -> dict[str, int]:
        """The retention days the site server sent (the field's own, decision RET-2), when ``[sync] branding =
        "site"``; empty otherwise or while it has sent none."""
        if getattr(self.cfg, "sync_branding", "local") != "site":
            return {}
        try:
            raw = json.loads(self.store.get_setting(RETENTION_SITE_SETTING) or "{}")
        except ValueError:
            return {}
        return {k: v for k, v in raw.items() if k in RETENTION_KEYS and _days_ok(v)} if isinstance(raw, dict) else {}

    def _local_retention(self, key: str) -> int:
        """The console's saved value of a retention key, else the configured one."""
        try:
            value = json.loads(self.store.get_setting("checkin.settings") or "{}").get(key)
        except (ValueError, AttributeError):
            value = None
        return value if _days_ok(value) else getattr(self.cfg, key)

    def retention_days(self, key: str) -> int:
        """``chrono_retention_days`` or ``game_retention_days`` as the field has them now."""
        return int(self.settings()[key])

    def _local_apd(self) -> dict[str, Any]:
        """The APD rule of [checkin] apd_* and the console's saved one (the site's is laid over it)."""
        rule = apdfmt.check_rule({"accepted": list(self.cfg.apd_accepted) or None, "checkin": self.cfg.apd_checkin,
                                  "expiry": self.cfg.apd_expiry})
        saved = self.store.get_setting("checkin.settings")
        if saved:
            try:
                rule = apdfmt.check_rule(json.loads(saved).get("apd", rule))
            except (ValueError, apdfmt.ApdError, AttributeError):
                pass
        return rule

    def _zone_name(self) -> Optional[str]:
        """The IANA name of the controller's time zone: the one it was given, else ``TZ``, ``/etc/timezone`` or
        the ``/etc/localtime`` link; None when none is known."""
        key = getattr(self._tz, "key", None)
        if isinstance(key, str):
            return key
        if os.environ.get("TZ"):
            return os.environ["TZ"].lstrip(":")
        try:
            return Path("/etc/timezone").read_text(encoding="utf-8").strip() or None
        except OSError:
            pass
        try:
            return os.path.realpath("/etc/localtime").split("zoneinfo/", 1)[1]
        except (OSError, IndexError):
            return None

    def _local_country(self) -> Optional[str]:
        """The field's country: the console's saved one, else ``[checkin] country``, else PT where the time zone is
        Portugal's (decision MEM-2); None is unset. The site server's is laid over it."""
        saved = self.store.get_setting("checkin.settings")
        if saved:
            try:
                value = json.loads(saved).get("country")
                if isinstance(value, str) and apdfmt.COUNTRY_RE.fullmatch(value):
                    return value
            except (ValueError, AttributeError):
                pass
        return self._config_country()

    def _config_country(self) -> Optional[str]:
        return self.cfg.country or apdfmt.default_country(self._zone_name())

    def set_site_apd(self, rule: Optional[dict[str, Any]]) -> None:
        """The field's APD rule from the site server (None: it sent none)."""
        self.store.set_setting(APD_SITE_SETTING, json.dumps(rule, sort_keys=True) if rule is not None else "")

    def _verdict(self, st: dict[str, Any], apd: Optional[str], number: Optional[str], expires: Optional[str],
                 now: float) -> Optional[str]:
        """The membership's verdict, or None when the rule does not check at check-in."""
        rule = st["apd"]
        if not rule["checkin"]:
            return None
        return apdfmt.status(rule, apd, number, expires, self.local_day(now).isoformat())

    def _row_verdict(self, st: dict[str, Any], row: dict[str, Any], now: float) -> Optional[str]:
        """What staff see: the verdict stored when the card was checked, else the one worked out now."""
        if row.get("apd_verdict"):
            return row["apd_verdict"]
        return self._verdict(st, row.get("apd_id"), row["federation_number"], row.get("membership_expires"), now)

    def _card_fields(self, st: dict[str, Any], apd: Optional[str], number: Optional[str], expires: Optional[str],
                     staff: str, now: float) -> dict[str, Any]:
        """The columns of a confirmed card check (protocol/apd.md "The card check"): who and when, the verdict
        as it stood that day, and the number gone (association, expiry and the verdict stay)."""
        day = self.local_day(now).isoformat()
        return {"federation_seen": True, "card_checked_by": staff, "card_checked_at": now,
                "apd_verdict": apdfmt.status(st["apd"], apd, number, expires, day), "apd_verdict_on": day,
                "federation_number": None}

    @staticmethod
    def _share_fields(share: Optional[bool], notice: Any, now: float) -> dict[str, Any]:
        """The position-sharing choice with its time and the notice version it was made under."""
        return {"position_share": bool(share), "position_share_at": now, "position_share_notice": notice}

    def set_settings(self, spec: dict[str, Any]) -> dict[str, Any]:
        unknown = set(spec) - set(SETTINGS_KEYS)
        if unknown:
            raise ControllerError(f"unknown check-in settings {sorted(unknown)}")
        if "apd" in spec and getattr(self.cfg, "sync_branding", "local") == "site" \
                and self.store.get_setting(APD_SITE_SETTING):
            raise Conflict("the APD rule is the site server's ([sync] branding = \"site\"): change it there")
        if "country" in spec and getattr(self.cfg, "sync_branding", "local") == "site" \
                and self.store.get_setting(COUNTRY_SITE_SETTING):
            raise Conflict("the country is the site server's ([sync] branding = \"site\"): change it there")
        if getattr(self.cfg, "sync_branding", "local") == "site":
            held = set(spec) & set(self._site_retention())
            if held:
                raise Conflict(f"{sorted(held)[0]} is the site server's ([sync] branding = \"site\"): change it there")
        cur = self.settings()
        local_apd = self._local_apd()
        saved_country = None  # the console's own choice; None: the configured or default one
        if (blob := self.store.get_setting("checkin.settings")):
            try:
                saved_country = json.loads(blob).get("country")
            except (ValueError, AttributeError):
                pass
        choices = {"confirm": ("auto", "staff"), "federation": ("off", "optional", "required"),
                   "chrono_valid_for": ("day", "game")}
        for k, v in spec.items():
            if k in choices and v not in choices[k]:
                raise ControllerError(f"{k}: one of {', '.join(choices[k])}")
            if k == "federation_label":
                _text(k, v, 16)
            if k == "apd":
                try:
                    v = local_apd = apdfmt.check_rule(v)
                except apdfmt.ApdError as exc:
                    raise ControllerError(f"apd: {exc}") from None
            if k == "country":
                code = v.strip().upper() if isinstance(v, str) else v
                try:
                    saved_country = apdfmt.check_country(code or None)
                except apdfmt.ApdError:
                    raise ControllerError("country: two letters (ISO 3166-1 alpha-2, e.g. PT) or empty") from None
                v = saved_country or self._config_country()
            if k == "max_replicas" and (isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 20):
                raise ControllerError("max_replicas: 1-20")
            if k in RETENTION_KEYS and not _days_ok(v):
                raise ControllerError(f"{k}: {RETENTION_MIN}-{RETENTION_MAX}")
            if k == "max_players" and (isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= 5000):
                raise ControllerError("max_players: 1-5000")
            cur[k] = v.strip() if isinstance(v, str) else v
        saved = {k: cur[k] for k in SETTINGS_KEYS}
        saved["apd"] = local_apd
        saved["country"] = saved_country
        for k in RETENTION_KEYS:  # the console's own choice, not the site server's value laid over it
            saved[k] = spec[k] if k in spec else self._local_retention(k)
        self.store.set_setting("checkin.settings", json.dumps(saved))
        self.ctrl._emit({"type": "checkin_settings", "settings": cur, "_staff": True})
        return cur

    def _rederive(self) -> None:
        """The GM's addresses that are still current: the saved poster's, else [checkin] urls. Stale ones
        are dropped from the saved poster (it keeps its other fields)."""
        assert self.addresses is not None
        had = saved_poster_urls(self.store)
        plan = self.addresses.plan(had, self.cfg.checkin_urls)
        kept, _ = self.addresses.keep(had)
        if kept != had:
            try:
                doc = json.loads(self.store.get_setting("checkin.poster") or "{}")
            except ValueError:
                doc = {}
            if kept:
                doc["urls"] = kept
            else:
                doc.pop("urls", None)
            self.store.set_setting("checkin.poster", json.dumps(doc))
        self.explicit_urls = plan.explicit

    def poster_fields(self) -> dict[str, Any]:
        saved = {}
        raw = self.store.get_setting("checkin.poster")
        if raw:
            try:
                saved = json.loads(raw)
            except ValueError:
                saved = {}
        if self.addresses is not None:
            urls = self.explicit_urls or self.default_urls
        else:
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
        printed = self.printed_poster()
        out["printed"] = printed
        out["changed"] = poster_change(printed, p["urls"], out["ca_sha256"])
        return out

    def printed_poster(self) -> Optional[dict[str, Any]]:
        """The poster the GM last printed: ``urls``, ``ca_sha256`` (hex) and ``at`` (seconds), or None."""
        try:
            doc = json.loads(self.store.get_setting("checkin.poster_printed") or "null")
        except ValueError:
            return None
        return doc if isinstance(doc, dict) and isinstance(doc.get("urls"), list) else None

    def mark_poster_printed(self) -> dict[str, Any]:
        """The GM printed (or showed) the poster as it is now: later changes are measured from here."""
        p = self.poster_fields()
        if p["ca_sha256"] is None or not p["urls"]:
            raise ControllerError("there is no poster to print yet")
        self.store.set_setting("checkin.poster_printed", json.dumps(
            {"urls": list(p["urls"]), "ca_sha256": p["ca_sha256"].hex(), "at": self._wall()}))
        return self.poster()

    def set_poster(self, spec: dict[str, Any]) -> dict[str, Any]:
        unknown = set(spec) - {"urls", "wifi_ssid", "game_id", "field_name"}
        if unknown:
            raise ControllerError(f"unknown poster fields {sorted(unknown)}")
        if self.addresses is not None and isinstance(spec.get("urls"), list):
            # An address typed now that is on no interface is left out, as at start.
            kept, dropped = self.addresses.keep(spec["urls"])
            warn_dropped(dropped, "check-in poster")
            spec = {**spec, "urls": kept}
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
        if "urls" not in spec or (self.addresses is not None and not spec["urls"]):
            saved.pop("urls")
        self.store.set_setting("checkin.poster", json.dumps(saved))
        if self.addresses is not None:
            self._rederive()
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
            st = self.settings()
            texts[lang] = (text.replace("{operator}", operator)
                           .replace("{retention_days}", str(self.cfg.retention_days))
                           .replace("{chrono_retention_days}", str(st["chrono_retention_days"]))
                           .replace("{game_retention_days}", str(st["game_retention_days"])))
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
        st = self.settings()
        return {
            "version": 1,
            "field": {"id": self.cfg.field_id, "name": p["field_name"], "operator": self.cfg.operator or None},
            "notice": self.notice(),
            "settings": {k: v for k, v in st.items() if k not in PLAYER_HIDDEN},
            "limits": {"id": self.limits["id"], "name": self.limits["name"],
                       "status": self.limits["status"], "classes": sorted(self.limits["classes"])},
            "replica_types": list(REPLICA_TYPES),
            "apds": apdfmt.choices(st["apd"], st["country"]),
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
                   "team_preference", "notice_version", "replicas", "registration_id", "ticket", "apd_id",
                   "membership_number", "membership_expires", "share_position"}
        unknown = set(body) - allowed
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        share = _share_choice(body)
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
        decl_m = declared_membership(body)
        fed_in, apd_in, exp_in = decl_m["number"], decl_m["apd"], decl_m["expires"]
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
            if expected is None or any(v is not None for v in (fed_in, apd_in, exp_in)):
                fed, apd_id, exp = fed_in, apd_in, exp_in
            else:
                fed, apd_id, exp = expected["federation_number"], expected.get("apd_id"), \
                    expected.get("membership_expires")
            if pref is None and expected is not None and expected["team_preference"] in game["teams"]:
                pref = expected["team_preference"]
            if st["federation"] == "off" and not st["apd"]["checkin"]:
                fed = apd_id = exp = None
            elif st["federation"] == "required" and fed is None:
                raise ControllerError(f"federation_number: this field asks for your {st['federation_label']} number")
            # A membership the rule does not accept waits for a marshal, who decides (protocol/apd.md).
            verdict = self._verdict(st, apd_id, fed, exp, now)
            # With a rule that checks at check-in, only a marshal or the GM ticking "card seen, matches" lets a
            # player in, whatever the verdict (protocol/apd.md, "The card check").
            auto_ok = verdict in (None, "valid") and not st["apd"]["checkin"]
            created = row is None or row["status"] == "expected"  # an expected player arriving is a new check-in
            emit = False
            if created:
                if self.store.count_checkins(game_id) >= st["max_players"]:
                    raise Forbidden(f"game {game_id} is full ({st['max_players']} players)")
                if known is None:
                    self.store.add_field_player(pid, digest, now)
                status = "checked_in" if st["confirm"] == "auto" and auto_ok else "pending"
                fields = {"status": status, "display_name": name, "federation_number": fed,
                          "apd_id": apd_id, "membership_expires": exp, "team_preference": pref, "notice_version": notice,
                          "checked_in_at": now if status == "checked_in" else None,
                          **self._share_fields(share, notice, now)}
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
                    status = "checked_in" if st["confirm"] == "auto" and auto_ok else "pending"
                    emit = status == "checked_in"
                fields = {"status": status, "display_name": name, "team_preference": pref,
                          "notice_version": notice, "updated_at": now}
                # Once a marshal checked the card, the number is gone and the stored verdict stands: the player's
                # app cannot put the number back or reset the check.
                if row.get("card_checked_at") is None and (fed, apd_id, exp) != (
                        row["federation_number"], row.get("apd_id"), row.get("membership_expires")):
                    fields.update(federation_number=fed, apd_id=apd_id, membership_expires=exp,
                                  federation_seen=False)
                if share is not None:
                    fields.update(self._share_fields(share, notice, now))
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
                "squad": row["squad"], "role": row["role"], "position_share": bool(row.get("position_share"))}

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
               "registered": bool(row.get("registration_id")),
               "position_share": bool(row.get("position_share")),
               "position_share_at": row.get("position_share_at"),
               "position_share_notice": row.get("position_share_notice")}
        if names:
            st = self.settings()
            out.update({"display_name": row["display_name"], "federation_number": row["federation_number"],
                        "federation_seen": row["federation_seen"], "team_preference": row["team_preference"],
                        "membership_number": row["federation_number"], "apd_id": row.get("apd_id"),
                        "membership_expires": row.get("membership_expires"),
                        "apd_override": bool(row.get("apd_override")),
                        "apd_status": self._row_verdict(st, row, self._wall()),
                        "apd_verdict_on": row.get("apd_verdict_on"),
                        "card_checked_by": row.get("card_checked_by"),
                        "card_checked_at": row.get("card_checked_at"),
                        "country": st["country"]})  # the words of the verdict: protocol/apd.md
        if declarations:
            out["declarations"] = self._decl_views(game["id"], row["player_id"])
            if names:
                shared = self.shared_view(row["player_id"])
                if shared:
                    out["shared_readings"] = shared
        return out

    def me(self, viewer: Viewer) -> dict[str, Any]:
        game = self.store.game(viewer.game_id)
        row = self.store.checkin(viewer.game_id, viewer.player_id)
        if game is None or row is None:
            raise NotFound("no check-in")
        out = self.row_view(game, row)
        out["stale_token"] = viewer.stale
        if row["role"] == "marshal":
            out["marshal"] = self.my_marshal(viewer)
        out["settings"] = {k: v for k, v in self.settings().items() if k not in PLAYER_HIDDEN}
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
                                      apd_id=None, membership_expires=None, apd_override=False,
                                      federation_seen=False, team_preference=None, updated_at=now,
                                      erased_at=now, **ERASED_CARD, position_share=False,
                                      position_share_at=now)
            self.store.delete_player_position(gid, pid)
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

    @staticmethod
    def _staff_id(viewer: Viewer) -> str:
        """Who ticked the card: the marshal's player id, or "gm" for the GM token (no membership number ever)."""
        return viewer.player_id or "gm"

    def set_position_sharing(self, viewer: Viewer, body: dict[str, Any]) -> dict[str, Any]:
        """PUT /api/v1/checkin/me/position-sharing: the player turns sharing their position with the game on or
        off, at any time. Off drops the stored position at once. Recorded with the time and notice version."""
        if set(body) - {"share_position"} or not isinstance(body.get("share_position"), bool):
            raise ControllerError("share_position: true or false, nothing else")
        gid, pid = viewer.game_id, viewer.player_id
        game = self.store.game(gid)
        if game is None or game["state"] == "ended":
            raise Conflict("the game has ended")
        now, on = self._wall(), body["share_position"]
        with self._lock:
            row = self.store.checkin(gid, pid)
            if row is None or row["status"] in ("left", "removed"):
                raise Conflict("this check-in is over")
            self.store.update_checkin(gid, pid, updated_at=now, **self._share_fields(on, self.cfg.notice_version, now))
            if not on:
                self.store.delete_player_position(gid, pid)
            row = self.store.checkin(gid, pid)
            assert row is not None
        if not on:
            self.ctrl._emit({"type": "positions", "game": gid, "_positions_refresh": True})
        self._notify(gid, pid)
        return self.row_view(game, row, names=False, declarations=False)

    def list_checkins(self, viewer: Viewer, game_id: int) -> dict[str, Any]:
        game = self._staff(viewer, game_id)
        rows = [self.row_view(game, r) for r in self.store.checkins(game_id)]
        counts = collections.Counter(r["status"] for r in rows)
        arrived = [r for r in rows if r["status"] in ("pending", "checked_in")]
        st = self.settings()
        return {"game_id": game_id, "open": self.is_open(game_id), "settings": st,
                "apds": apdfmt.choices(st["apd"], st["country"]), "squads": int(game.get("squads") or 0),
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
        unknown = set(body) - {"display_name", "federation_number", "team_preference", "replicas", "apd_id",
                               "membership_number", "membership_expires", "federation_seen", "share_position"}
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        share = _share_choice(body)
        seen = body.get("federation_seen")
        if seen is not None and not isinstance(seen, bool):
            raise ControllerError("federation_seen: true or false")
        st = self.settings()
        name = _text("display_name", body.get("display_name"), NAME_MAX)
        decl_m = declared_membership(body)
        fed, apd_id, exp = decl_m["number"], decl_m["apd"], decl_m["expires"]
        if st["federation"] == "off" and not st["apd"]["checkin"]:
            fed = apd_id = exp = None
        elif st["federation"] == "required" and fed is None:
            raise ControllerError(f"federation_number: this field asks for the {st['federation_label']} number")
        pref = body.get("team_preference")
        if pref is not None:
            self._team_id(game, pref, "team_preference")
        decls = self._check_declarations(body.get("replicas") or [], st)
        now = self._wall()
        verdict = self._verdict(st, apd_id, fed, exp, now)
        carded = bool(st["apd"]["checkin"]) and seen is True  # the card in hand, matching what was typed
        # Never refused: a marshal decides. A verdict other than valid, or a rule that checks the card with no
        # card seen, is an override, logged with the reason (never the number).
        reason = "no_card" if st["apd"]["checkin"] and not carded else (
            verdict if verdict not in (None, "valid") else None)
        override = reason is not None
        extra = self._card_fields(st, apd_id, fed, exp, self._staff_id(viewer), now) if carded else {}
        with self._lock:
            if self.store.count_checkins(game_id) >= st["max_players"]:
                raise Forbidden(f"game {game_id} is full ({st['max_players']} players)")
            pid = new_player_id()
            while self.store.field_player(pid) is not None:
                pid = new_player_id()
            self.store.add_field_player(pid, None, now)
            self.store.add_checkin(game_id, pid, {
                "status": "checked_in", "display_name": name, "federation_number": fed,
                "apd_id": apd_id, "membership_expires": exp, "apd_override": override,
                "federation_seen": carded if st["apd"]["checkin"] else fed is not None, "team_preference": pref, "manual": 1,
                "checked_in_at": now, **self._share_fields(share, self.cfg.notice_version, now),
                **extra}, now)
            if carded:
                log.info("card check: game %d, %s by %s, verdict %s", game_id, pid, extra["card_checked_by"],
                         extra["apd_verdict"])
            if override:
                log.info("apd override: game %d, %s checked in by staff, reason %s, verdict %s", game_id, pid, reason, verdict)
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
        marshal_fields = {"status", "federation_seen", "replicas", "apd_id", "membership_number",
                          "membership_expires", "federation_number"}
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
        st = self.settings()
        seen = body.get("federation_seen")
        if "federation_seen" in body and not isinstance(seen, bool):
            raise ControllerError("federation_seen: true or false")
        if "federation_seen" in body:
            fields["federation_seen"] = seen
        redone = False
        if {"apd_id", "membership_number", "membership_expires", "federation_number"} & set(body):
            m = declared_membership(body)  # what a marshal sends replaces the three; null clears
            if (m["number"], m["apd"], m["expires"]) != (row["federation_number"], row.get("apd_id"),
                                                          row.get("membership_expires")):
                # New data: an earlier card check no longer covers it.
                fields.update(federation_number=m["number"], apd_id=m["apd"], membership_expires=m["expires"],
                              federation_seen=False, **ERASED_CARD)
                redone = True
                if "federation_seen" in body:
                    fields["federation_seen"] = seen
        card_rule = bool(st["apd"]["checkin"])
        card_done = row.get("card_checked_at") is not None and not redone
        if card_rule and seen is False and card_done:
            raise Conflict("the card check is recorded and the number erased; send the number again to redo it")
        carded = card_rule and seen is True and not card_done
        if carded:  # "card seen, matches": records who and when, stores the verdict, erases the number
            number = fields.get("federation_number", row["federation_number"])
            fields.update(self._card_fields(st, fields.get("apd_id", row.get("apd_id")), number,
                                            fields.get("membership_expires", row.get("membership_expires")),
                                            self._staff_id(viewer), now))
            if row["status"] in ("pending", "expected") and "status" not in fields:
                fields["status"] = "checked_in"  # the tick is the confirmation the rule waits for
                fields["checked_in_at"] = now
                emit = True
            log.info("card check: game %d, %s by %s, verdict %s", game_id, pid, fields["card_checked_by"],
                     fields["apd_verdict"])
        if emit:  # a confirmation over a verdict other than valid, or with no card seen, is the marshal's call
            if carded:
                verdict = fields["apd_verdict"]
            elif card_done:
                verdict = row.get("apd_verdict")
            else:
                verdict = self._verdict(st, fields.get("apd_id", row.get("apd_id")),
                                        fields.get("federation_number", row["federation_number"]),
                                        fields.get("membership_expires", row.get("membership_expires")), now)
            reason = "no_card" if card_rule and not (carded or card_done) else (
                verdict if verdict not in (None, "valid") else None)
            if reason is not None:
                fields["apd_override"] = True
                log.info("apd override: game %d, %s confirmed by staff, reason %s, verdict %s", game_id, pid, reason, verdict)
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
                                      federation_number=None, apd_id=None, membership_expires=None,
                                      apd_override=False, federation_seen=False, team_preference=None,
                                      updated_at=now, erased_at=now, **ERASED_CARD, position_share=False,
                                      position_share_at=now)
            self.store.delete_player_position(game_id, pid)
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
            arriving = row["status"] == "expected"
            emit = False
            if arriving:
                st = self.settings()
                if self.store.count_checkins(game_id) >= st["max_players"]:
                    raise Forbidden(f"game {game_id} is full ({st['max_players']} players)")
                if st["apd"]["checkin"]:  # the ticket is not the card: pending until "card seen, matches"
                    self.store.update_checkin(game_id, row["player_id"], status="pending", updated_at=now)
                else:
                    emit = True
                    self.store.update_checkin(game_id, row["player_id"], status="checked_in", checked_in_at=now,
                                              updated_at=now)
            row = self.store.checkin(game_id, row["player_id"])
            assert row is not None
        if emit:
            self._emit_checkin_event(game, row)
        self._notify(game_id, row["player_id"])
        return self.row_view(game, row)

    def apply_shared_chrono(self, game_id: int, roster_players: list[str], answer: dict[str, Any]) -> dict[str, Any]:
        """Other fields' records of the game's roster players, from ``GET /api/v1/sync/chrono`` (S14-5,
        checked by ``sync_format.check_shared_chrono``). The site server decided what may be shared
        (consent for both fields); this keeps only what it can check: players on this roster, a record the
        marshal's key given with it signed (``chrono.parse``), one younger than the retention period, and none
        whose id is a measurement of this field (a local reading is never replaced). The records go in
        ``shared_readings``: never judged, counted for the list's states or sent back. A roster player the
        answer leaves out has none kept (a consent withdrawn). Returns ``{players, stored, dropped}``."""
        now = self._wall()
        cutoff = datetime.datetime.fromtimestamp(now - self.retention_days("chrono_retention_days") * 86400,
                                                 datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        on = set(roster_players)
        rows: dict[str, list[dict[str, Any]]] = {pid: [] for pid in roster_players}
        dropped = 0
        for entry in answer["players"]:
            if entry["player_id"] not in on:
                dropped += len(entry["readings"])
                continue
            for item in entry["readings"]:
                try:
                    record = chrono.parse(item["record"], base64.b64decode(item["public_key"]))
                except chrono.ChronoError:
                    dropped += 1
                    continue
                if record["timestamp"] < cutoff or self.store.has_reading(record["reading_id"]):
                    dropped += 1
                    continue
                rows[entry["player_id"]].append({"reading_id": record["reading_id"], "field_name": item["field"],
                                                 "timestamp": record["timestamp"], "record_json": item["record"],
                                                 "public_key": base64.b64decode(item["public_key"])})
        changed = []
        with self._lock:
            for pid, mine in rows.items():
                if {r["reading_id"] for r in self.store.shared_readings(pid)} != {r["reading_id"] for r in mine}:
                    changed.append(pid)
                self.store.set_shared_readings(pid, mine, now)
        stored = sum(len(v) for v in rows.values())
        for pid in changed:
            if self.store.checkin(game_id, pid) is not None:
                self._notify(game_id, pid)
        return {"players": sum(1 for v in rows.values() if v), "stored": stored, "dropped": dropped}

    def shared_view(self, pid: str) -> list[dict[str, Any]]:
        """A player's records from other fields as the lists show them: marked as from another field (with
        its name) and never part of the field's own readings or judgements."""
        return [{"reading_id": r["reading_id"], "field": r["field"], "from_other_field": True,
                 "type": r["record"]["type"], "timestamp": r["timestamp"],
                 "velocity_mps": r["record"]["velocity_mps"], "bb_weight_g": r["record"]["bb_weight_g"],
                 "energy_j": r["record"]["energy_j"], "marshal_name": r["record"]["marshal_name"]}
                for r in self.store.shared_readings(pid)]

    # --- a registration list imported by the GM (PKE-1) -------------------------------------

    def import_rules(self, game: dict[str, Any]) -> importfmt.Rules:
        st = self.settings()
        # A field whose APD rule asks at check-in keeps the number an import carries even when the
        # federation setting asks for none (never required by an import: protocol/apd.md).
        federation = "optional" if st["federation"] == "off" and st["apd"]["checkin"] else st["federation"]
        return importfmt.Rules(teams=tuple(game["teams"]), federation=federation, predeclare_replicas=True,
                               classes=tuple(self.limits["classes"]), max_replicas=st["max_replicas"])

    def import_registrations(self, game_id: int, body: dict[str, Any]) -> dict[str, Any]:
        """``POST /api/v1/games/{id}/checkins/import``: a CSV or JSON list of registrations (the site
        server's import format, ``import_format.py``) becomes this game's expected check-ins, for a field
        with no site server. Body: ``format`` (csv or json), ``data`` (the file's text), ``source`` (the
        other platform's name; rows upsert by source + ``external_ref``), ``dry_run`` and, for a real
        import, ``basis_confirmed`` (the field is the data controller of the list it imports). A row the
        field's rules refuse is listed with a code and the others still go in. An imported registration
        has no ticket and no app identity: a marshal ticks it by name (``patch_checkin``), as a registered
        player from the site. A player who has arrived is never changed; a registration the file no
        longer lists is reported (``missing``), never removed."""
        unknown = set(body) - {"format", "data", "source", "dry_run", "basis_confirmed"}
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        game = self.store.game(game_id)
        if game is None:
            raise NotFound(f"no game {game_id}")
        if game["state"] == "ended":
            raise Conflict("game_ended")
        dry_run, confirmed = body.get("dry_run", False), body.get("basis_confirmed", False)
        if not isinstance(dry_run, bool) or not isinstance(confirmed, bool):
            raise ControllerError("dry_run and basis_confirmed: true or false")
        try:
            source = importfmt.check_source(body.get("source", "csv"))
            data = body.get("data")
            if not isinstance(data, str):
                raise importfmt.FileError("empty")
            if not dry_run and not confirmed:
                raise ControllerError("basis_not_confirmed")
            try:
                raw_bytes = data.encode("utf-8")
            except UnicodeEncodeError:
                raise importfmt.FileError("encoding_invalid") from None
            parsed = importfmt.parse(raw_bytes, body.get("format"))
        except importfmt.FileError as exc:
            raise ImportRefused(exc.code, exc.line) from None
        rules, now = self.import_rules(game), self._wall()
        st = self.settings()
        asked = st["federation"] != "off" or st["apd"]["checkin"]
        counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "refused": 0}
        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        with self._lock:
            by_ref = {r["registration_id"]: r for r in self.store.checkins(game_id)
                      if r.get("registration_id") and not r["from_roster"] and not r["ticket_sha256"]}
            for raw in parsed.rows:
                entry: dict[str, Any] = {"row": raw.number}
                try:
                    row = importfmt.check_row(raw, rules)
                except importfmt.RowError as exc:
                    entry.update(result="refused", code=exc.code)
                    counts["refused"] += 1
                    results.append(entry)
                    continue
                entry.update(external_ref=row.external_ref, display_name=row.display_name,
                             warnings=list(row.warnings))
                rid = None
                if row.external_ref is not None:
                    rid = str(uuid.uuid5(IMPORT_NS, f"{source}\0{row.external_ref}"))
                    if rid in seen:
                        entry.update(result="refused", code="external_ref_twice")
                        counts["refused"] += 1
                        results.append(entry)
                        continue
                    seen.add(rid)
                existing = by_ref.get(rid) if rid else None
                if existing is None:
                    entry["result"] = "created"
                    if not dry_run:
                        self._import_new(game, st, row, str(uuid.uuid4()) if rid is None else rid, now, asked)
                elif existing["status"] != "expected":
                    entry.update(result="skipped", code="removed" if existing["status"] == "removed"
                                 else "already_arrived")
                else:
                    changed = self._import_changes(game_id, existing, row, asked)
                    entry["result"] = "updated" if changed else "unchanged"
                    if changed:
                        entry["changed"] = changed
                        if not dry_run:
                            self._import_update(game, st, existing, row, now, asked)
                counts[entry["result"]] += 1
                results.append(entry)
            ours = {rid for rid, r in by_ref.items() if r["status"] == "expected"}
            missing = sorted(by_ref[r]["player_id"] for r in ours - seen)
        if not dry_run and (counts["created"] or counts["updated"]):
            self.ctrl._emit({"type": "roster", "game": game_id, "counts": dict(counts), "_staff": True})
            log.info("registration import for game %d: %s (source %s)", game_id, counts, source)  # never a name
        return {"dry_run": dry_run, "format": parsed.format, "source": source, "game_id": game_id,
                "columns": list(parsed.columns), "not_imported_columns": parsed.ignored,
                "not_imported_more": parsed.ignored_more, "rows": len(parsed.rows), "counts": counts,
                "missing": {"count": len(missing), "player_ids": missing[:IMPORT_LISTED]}, "results": results}

    def _import_new(self, game: dict[str, Any], st: dict[str, Any], row: importfmt.Row, rid: str, now: float,
                    asked: bool) -> None:
        pid = new_player_id()
        while self.store.field_player(pid) is not None:
            pid = new_player_id()
        pref = row.team_preference if row.team_preference in game["teams"] else None
        self.store.add_field_player(pid, None, now)
        self.store.add_checkin(game["id"], pid, {
            "status": "expected", "display_name": row.display_name,
            "federation_number": row.federation_number if asked else None,
            "apd_id": row.apd_id if asked else None, "membership_expires": row.membership_expires if asked else None,
            "team_preference": pref, "registration_id": rid, "from_roster": 0}, now)
        self._replace_declarations(game, pid, self._import_declarations(rid, row), staff=True, now=now)

    def _import_update(self, game: dict[str, Any], st: dict[str, Any], existing: dict[str, Any], row: importfmt.Row,
                       now: float, asked: bool) -> None:
        fields: dict[str, Any] = {"updated_at": now}
        if "display_name" in row.present:
            fields["display_name"] = row.display_name
        if "team_preference" in row.present:
            fields["team_preference"] = row.team_preference
        # Once the card was checked the number is gone for good: an import never puts it (or a changed
        # membership) back over the stored verdict.
        carded = existing.get("card_checked_at") is not None
        if "federation_number" in row.present and not carded:
            fields["federation_number"] = row.federation_number if asked else None
        for name in ("apd_id", "membership_expires"):
            if name in row.present and not carded:
                fields[name] = getattr(row, name) if asked else None
        self.store.update_checkin(game["id"], existing["player_id"], **fields)
        if row.replicas is not None:
            self._replace_declarations(game, existing["player_id"],
                                       self._import_declarations(existing["registration_id"], row), staff=True,
                                       now=now)

    @staticmethod
    def _import_declarations(rid: str, row: importfmt.Row) -> list[dict[str, Any]]:
        base = uuid.UUID(rid)
        return [{"declaration_id": str(uuid.uuid5(base, f"declaration-{i}")), "replica_id": None,
                 "type": r["type"], "class": r["class"], "make_model": r["make_model"]}
                for i, r in enumerate(row.replicas or [])]

    def _import_changes(self, game_id: int, existing: dict[str, Any], row: importfmt.Row,
                        asked: bool) -> list[str]:
        """The names of what the row changes, among the columns the file has."""
        changed = []
        if "display_name" in row.present and row.display_name != existing["display_name"]:
            changed.append("display_name")
        if "team_preference" in row.present and row.team_preference != existing["team_preference"]:
            changed.append("team_preference")
        wanted = row.federation_number if asked else None
        carded = existing.get("card_checked_at") is not None  # see _import_update
        if "federation_number" in row.present and wanted != existing["federation_number"] and not carded:
            changed.append("federation_number")
        for name in ("apd_id", "membership_expires"):
            if name in row.present and not carded and (getattr(row, name) if asked else None) != existing.get(name):
                changed.append(name)
        if row.replicas is not None:
            old = [(d["type"], d["class"], d["make_model"]) for d in self.store.declarations(game_id, existing["player_id"])
                   if d["state"] != "withdrawn"]
            if old != [(r["type"], r["class"], r["make_model"]) for r in row.replicas]:
                changed.append("replicas")
        return changed

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
                asked = st["federation"] != "off" or st["apd"]["checkin"]
                fed = reg.get("federation_number") if asked else None
                apd_id = reg.get("apd_id") if asked else None
                exp = reg.get("membership_expires") if asked else None
                pref = reg.get("team_preference") if reg.get("team_preference") in game["teams"] else None
                decls = self._roster_declarations(game_id, pid, reg["replicas"], st, out)
                fields = {"display_name": name, "federation_number": fed, "apd_id": apd_id,
                          "membership_expires": exp, "team_preference": pref, "registration_id": rid, "ticket_sha256": reg.get("ticket_sha256"), "from_roster": 1}
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
                if row["status"] == "expected" and row["from_roster"] and row["registration_id"] not in listed:
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
                    "apd_id", "membership_expires", "apd_status", "card_seen", "card_checked_by", "card_checked_at", "manual", "checked_in_at", "declaration_id", "replica_id", "type", "class",
                    "make_model", "chrono"])
        st, now = self.settings(), self._wall()
        for r in self.store.checkins(game_id):
            base = [r["player_id"], _csv_safe(r["display_name"]), r["status"],
                    self._team_name(game, r["team"]) or "", r["squad"] or "", r["role"],
                    _csv_safe(r["federation_number"]), r.get("apd_id") or "", r.get("membership_expires") or "",
                    self._row_verdict(st, r, now) or "",
                    "yes" if r["federation_seen"] else "",
                    r.get("card_checked_by") or "", _iso(r.get("card_checked_at")),
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
        st, now = self.settings(), self._wall()
        for r in self.store.checkins(gid):
            if r["status"] in ("left", "removed"):
                continue
            decls = [self._decl_view(d, self._refused_today(d)) for d in self.store.declarations(gid, r["player_id"])
                     if d["state"] != "withdrawn"]
            for d in decls:
                counts[d["state"]] += 1
            if not decls and r["status"] != "pending":
                continue  # a player with no replica is listed only while a marshal has to let them in
            players.append({"player_id": r["player_id"], "display_name": r["display_name"],
                            "status": r["status"], "team": self._team_name(game, r["team"]),
                            "squad": r["squad"], "seq": r["seq"],
                            "pending": sum(1 for d in decls if d["state"] == "pending"),
                            "apd_id": r.get("apd_id"), "membership_number": r["federation_number"],
                            "membership_expires": r.get("membership_expires"),
                            "apd_override": bool(r.get("apd_override")),
                            "apd_status": self._row_verdict(st, r, now),
                            "declarations": decls, "shared_readings": self.shared_view(r["player_id"])})
        players.sort(key=lambda p: (p["pending"] == 0, p["seq"]))
        return {"game_id": gid, "squads": int(game.get("squads") or 0),
                "counts": {s: counts.get(s, 0) for s in ("pending", "passed", "refused")},
                "chrono_valid_for": st["chrono_valid_for"], "country": st["country"],
                "players": players}

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

    # The GM's marshal list (MR-1 to MR-14): a marshal exists only on it. The GM adds a checked-in
    # player (the controller gives the id, M-01, M-02...), the player's phone learns its id from
    # GET /api/v1/checkin/me and registers its signing key for that id and no other.

    def _marshal_view(self, entry: dict[str, Any]) -> dict[str, Any]:
        key = self.store.marshal(entry["marshal_id"])
        return {"marshal_id": entry["marshal_id"], "name": entry["name"], "player_id": entry["player_id"],
                "public_key": base64.b64encode(key["public_key"]).decode("ascii") if key else None,
                "key_registered": key is not None, "registered_at": key["registered_at"] if key else None,
                "created_at": entry["created_at"]}

    def _follow_role(self, pid: str, to: str) -> None:
        """A player added to the list is a marshal in every check-in that still counts; one taken off it
        is a player again (MR-9). A gm-role player keeps their role."""
        now = self._wall()
        for row in self.store.active_checkins_of(pid):
            if to == "marshal" and row["role"] in ("marshal", "gm"):
                continue
            if to != "marshal" and row["role"] != "marshal":
                continue
            self.store.update_checkin(row["game_id"], pid, role=to, updated_at=now)
            self._notify(row["game_id"], pid, assignment=True)

    def _free_marshal_id(self) -> str:
        taken = {e["marshal_id"] for e in self.store.roster()}
        n = 1
        while f"M-{n:02d}" in taken:
            n += 1
        return f"M-{n:02d}"

    def _name_of(self, pid: str) -> Optional[str]:
        for row in reversed(self.store.active_checkins_of(pid)):
            if row.get("display_name"):
                return row["display_name"]
        return None

    def _check_player(self, pid: Any) -> str:
        if not player_id_ok(pid):
            raise ControllerError("player_id: a player's field id (p-...)")
        if self.store.field_player(pid) is None:
            raise NotFound(f"{pid} has not checked in here")
        return pid

    def add_marshal(self, body: dict[str, Any]) -> dict[str, Any]:
        """POST /api/v1/marshals (GM): adds a marshal to the list, or changes the id's name, player or
        key. ``player_id`` binds the id to a player who has checked in here (who then gets the marshal
        role); ``marshal_id`` is made when not given; ``public_key`` is optional (the phone registers it)."""
        unknown = set(body) - {"marshal_id", "name", "public_key", "player_id"}
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        mid = body.get("marshal_id")
        if mid is not None and (not isinstance(mid, str) or not MARSHAL_ID_RE.fullmatch(mid)):
            raise ControllerError("marshal_id: 1-64 of A-Z a-z 0-9 . _ : -")
        key = self._public_key(body["public_key"]) if body.get("public_key") is not None else None
        with self._lock:
            pid = self._check_player(body["player_id"]) if body.get("player_id") is not None else None
            before = self.store.roster_entry(mid) if mid is not None else None
            name = body.get("name")
            if name is None:
                name = before["name"] if before is not None else (self._name_of(pid) if pid else None)
            name = _text("name", name, 64)
            if pid is not None:
                other = self.store.roster_of_player(pid)
                if other is not None and mid is not None and other["marshal_id"] != mid:
                    raise Conflict(f"{pid} is already marshal {other['marshal_id']}")
                if other is not None and mid is None:
                    mid, before = other["marshal_id"], other
            if mid is None:
                mid = self._free_marshal_id()
            now = self._wall()
            self.store.put_roster(mid, name, pid, now)
            if before is not None and before["player_id"] != pid:
                self.store.retire_marshal_key_only(mid, now)  # another phone's key does not carry over (MR-6)
                if before["player_id"] is not None:
                    self._follow_role(before["player_id"], "player")
            if key is not None:
                self.store.put_marshal(mid, name, key, pid, now)
            elif self.store.marshal(mid) is not None:
                self.store.put_marshal(mid, name, self.store.marshal(mid)["public_key"], pid, now)
            if pid is not None:
                self._follow_role(pid, "marshal")
            entry = self.store.roster_entry(mid)
        log.info("marshal listed: %s", mid)
        return self._marshal_view(entry)

    def patch_marshal(self, mid: str, body: dict[str, Any]) -> dict[str, Any]:
        """PATCH /api/v1/marshals/{id} (GM): the name, or the player the id is bound to (null unbinds)."""
        unknown = set(body) - {"name", "player_id"}
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        with self._lock:
            entry = self.store.roster_entry(mid)
            if entry is None:
                raise NotFound(f"{mid} is not on the marshal list")
            name = _text("name", body["name"], 64) if "name" in body else entry["name"]
            pid = entry["player_id"]
            if "player_id" in body:
                pid = self._check_player(body["player_id"]) if body["player_id"] is not None else None
                other = self.store.roster_of_player(pid) if pid else None
                if other is not None and other["marshal_id"] != mid:
                    raise Conflict(f"{pid} is already marshal {other['marshal_id']}")
            now = self._wall()
            self.store.put_roster(mid, name, pid, now)
            if pid != entry["player_id"]:
                self.store.retire_marshal_key_only(mid, now)  # the new phone registers its own key (MR-6)
                if entry["player_id"] is not None:
                    self._follow_role(entry["player_id"], "player")
                if pid is not None:
                    self._follow_role(pid, "marshal")
            elif self.store.marshal(mid) is not None:
                self.store.put_marshal(mid, name, self.store.marshal(mid)["public_key"], pid, now)
            out = self._marshal_view(self.store.roster_entry(mid))
        return out

    def remove_marshal(self, mid: str) -> dict[str, Any]:
        """DELETE /api/v1/marshals/{id} (GM): the marshal is revoked at once (MR-8, MR-9)."""
        with self._lock:
            entry = self.store.roster_entry(mid)
            if entry is None:
                raise NotFound(f"{mid} is not on the marshal list")
            self.store.retire_marshal(mid, self._wall())
            if entry["player_id"] is not None:
                self._follow_role(entry["player_id"], "player")
        log.info("marshal removed from the list: %s", mid)
        return {"marshal_id": mid, "removed": True}

    def my_marshal(self, viewer: Viewer) -> Optional[dict[str, Any]]:
        """What GET /api/v1/checkin/me says to a marshal's phone (MR-2): the id the GM gave this
        player, and the key the controller holds for it, or null when the player is not on the list."""
        entry = self.store.roster_of_player(viewer.player_id) if viewer.player_id else None
        if entry is None:
            return None
        view = self._marshal_view(entry)
        return {"marshal_id": view["marshal_id"], "name": view["name"], "public_key": view["public_key"],
                "valid_for_s": MARSHAL_VALID_FOR_S}

    def register_my_key(self, viewer: Viewer, body: dict[str, Any]) -> dict[str, Any]:
        """PUT /api/v1/checkin/me/marshal-key: the marshal's phone registers the key that signs its
        readings, for the id the GM's list gave this player (MR-2, MR-5)."""
        unknown = set(body) - {"marshal_id", "name", "public_key"}
        if unknown:
            raise ControllerError(f"unknown fields {sorted(unknown)}")
        with self._lock:
            entry = self.store.roster_of_player(viewer.player_id) if viewer.player_id else None
            if entry is None:
                raise Forbidden("you are not on the field's marshal list: ask the GM to add you as a marshal")
            mid = body.get("marshal_id")
            if mid is not None and mid != entry["marshal_id"]:
                raise Conflict(f"your marshal id is {entry['marshal_id']}, not {mid}")
            key = self._public_key(body.get("public_key"))
            self.store.put_marshal(entry["marshal_id"], entry["name"], key, viewer.player_id, self._wall())
        log.info("marshal key registered: %s", entry["marshal_id"])
        return {"marshal_id": entry["marshal_id"], "name": entry["name"],
                "public_key": base64.b64encode(key).decode("ascii"), "player_id": viewer.player_id}

    def marshals(self) -> list[dict[str, Any]]:
        return [self._marshal_view(e) for e in self.store.roster()]

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
                    raise chrono.ChronoError("marshal", f"marshal {fields['marshal_id']} is not on this field's "
                                                         "marshal list (never added, or removed by the GM)")
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
                self.store.add_reading(rec, series_id, judged["outcome"], now, limit_j=judged["limit_j"])
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
            self._record_erasure(pid, chrono=chrono_too, identity=True)
        for gid in games:
            self.ctrl._emit({"type": "checkin", "game": gid, "player_id": pid, "erased": True, "_staff": True})
        return {"player_id": pid, "erased": True, "readings_deleted": readings}

    def erase_chrono(self, pid: str) -> dict[str, Any]:
        """DELETE /api/v1/players/{player}/chrono: the player's readings, and other fields' copies of them (S14-5)."""
        with self._lock:
            self.store.delete_shared_readings(player_id=pid)
            readings = self.store.delete_readings(player_id=pid)
            self._record_erasure(pid, chrono=True, identity=False)
        return {"player_id": pid, "readings_deleted": readings}

    def _record_erasure(self, pid: str, *, chrono: bool, identity: bool) -> None:
        """With the site sync on, keeps that this player's data was erased until the site server has it (S14-10,
        decision RET-4): the next sync sends ``POST /api/v1/sync/erasures``. Nothing is kept without a sync."""
        if getattr(self.cfg, "sync_enabled", False):
            self.store.record_erasure(pid, chrono=chrono, identity=identity, now=self._wall())

    # --- retention -----------------------------------------------------------------

    def purge(self, force: bool = False) -> Optional[dict[str, Any]]:
        now = self._wall()
        if not force and now - self._last_purge < 600:
            return None
        self._last_purge = now
        out = self.store.purge_checkins(now - self.cfg.retention_days * 86400, now - IDENTITY_DAYS * 86400,
                                        now)
        chrono_days = self.retention_days("chrono_retention_days")
        cutoff = datetime.datetime.fromtimestamp(now - chrono_days * 86400, datetime.timezone.utc)
        out["readings"] = self.store.delete_readings(before=cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"))
        # Other fields' records pulled from the site server (S14-5) go with the same retention.
        out["shared_readings"] = self.store.delete_shared_readings(before=cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"))
        # A marshal's earlier keys outlive what they signed by the same period (schema 6).
        out["marshal_keys"] = self.store.delete_marshal_history(now - chrono_days * 86400)
        out.update(self._purge_games(now))
        out["erasure_records"] = self.store.purge_erasures(now - chrono_days * 86400)
        if any(out.values()):
            log.info("retention purge: %s", out)
        return out

    def _purge_games(self, now: float) -> dict[str, int]:
        """Ended games older than ``game_retention_days`` go whole: events, scores, nodes, positions, their
        check-in rows and token key and sync bookkeeping (decision RET-1). With the site sync on, a game the site
        server has not confirmed (``sync_state.final``: ended and every event acknowledged) is never purged
        (decision RET-3): the field's only copy would go. Without a sync, age alone decides."""
        days = self.retention_days("game_retention_days")
        confirmed = self.sync_confirmed if getattr(self.cfg, "sync_enabled", False) else None
        done = self.store.purge_games(now - days * 86400, confirmed_only=confirmed)
        return {"games": done["games"], "game_events": done["events"], "games_unsynced_kept": done["kept"]}

    def sync_confirmed(self, game: dict[str, Any]) -> bool:
        return bool(self.store.sync_state(game["id"], game["game_seed"])["final"])

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
