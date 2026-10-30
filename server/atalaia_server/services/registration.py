# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registration for scheduled games and the game-day sync's data (ADR-P4-11; plan phase 16, decisions S16-*).

**Registering.** A logged-in account registers for a published game while its window is open
(``scheduling.registration_state``: a game with no window takes no online registration) and places
are left (``max_players``; no waiting list, F17): a display name for that game (the username by
default, 1-32 characters), a team preference among the game's teams, the federation number when the
game asks for one (never verified), and, when the game wants them (``predeclare_replicas``), up to the
field's ``max_replicas`` pre-declared replicas: one of the person's replicas in the field's registry
(``replica_id``; its type and class are the registry's) or a new one (type, a class of the field's
limit template, make and model). Each becomes a declaration with its own ``declaration_id``. The
player may change it or cancel until the window closes; the field's staff at any time before the game
starts.

**What staff do beyond that** (Phase 4 follow-up FU7, decisions FU7-1 to FU7-8): note a registration paid (``mark_paid``:
who and when, no payment), mark a registered player a no-show after the game (``mark_no_show``: the controller's
outcomes win), bring a withdrawn registration back before the start while a place is left (``restore``: no ticket),
move one to another published game of the field that has not started (``move``: the ticket stays, it is the
registration's), and note when a controller pulled a roster (``record_roster_pull``).

**The player's id at the field** (``field_player_ids``) is made on the first registration there (``p-``
and 12 base32 characters, the phase 3 form), unless the account adopted a phone's id first: the phone
sends its id and secret once, the site server keeps the secret's SHA-256 in a claim, and the field's
controller, the only one that holds the hash it was given at the phone's first check-in, confirms or
refuses it over its sync (``claims``; decision S16-4).

**The ticket.** Each registration gets a random 32-byte ticket secret, shown once to the player (and
as the ``atalaia:ticket:`` text of a printable QR code, ``checkin_ticket.py``); only its SHA-256 is kept
and sent in the roster. A new one replaces it (``POST .../ticket``).

**Game day.** The controller pulls the schedule and, for each scheduled game it made a game from, the
roster (``roster``) until that game starts; after the game it pushes each registration's outcome and its
declarations' final states (``apply_checkins``). The controller stays the authority: the site server
never sends anything into a running game, and nothing it holds changes the controller's list.
"""

from __future__ import annotations

import functools
import hashlib
import hmac
import json
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml
from atalaia_controller import REPO_ROOT, apd as apd_core, checkin_ticket, sync_format
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import hub_share, quotas
from ..models import (Field, FieldApiKey, FieldPlayerId, Game, GameRegistration, PlayerIdClaim,
                      RegistrationReplica, Replica, ScheduledGame, User)
from . import scheduling

LIMIT_TEMPLATES = REPO_ROOT / "app" / "lib" / "chrono" / "limit_templates"
TEMPLATE_NAME = re.compile(r"[a-z0-9_]{1,32}")
REPLICA_TYPES = sync_format.REPLICA_TYPES
NAME_MAX = 32
FEDERATION_MAX = 32
MAKE_MODEL_MAX = 64
MAX_REPLICAS = 20               # the controller's bound for [checkin] max_replicas
ACTIVE = ("registered", "checked_in")
SCHEDULE_DAYS = 14              # GET /api/v1/sync/schedule's default horizon
SCHEDULE_DAYS_MAX = 60
CLAIM_RETENTION = timedelta(days=30)  # a claim, decided or still waiting, then goes
FEDERATION_RETENTION = timedelta(days=30)  # a registration's federation number after the game (ADR-P4-11)
ALPHABET = "abcdefghijklmnopqrstuvwxyz234567"


class RegistrationError(ValueError):
    """A refused request: ``code`` is the API's ``detail``, ``status`` its HTTP status."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


# --- the field's limit templates (the controller's, app/lib/chrono/limit_templates) ----------

@functools.lru_cache(maxsize=1)
def limit_templates() -> dict[str, tuple[str, ...]]:
    """Each limit template's classes, read once from the same YAML files the controller and the app use."""
    out: dict[str, tuple[str, ...]] = {}
    for path in sorted(Path(LIMIT_TEMPLATES).glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        classes = data.get("classes") if isinstance(data, dict) else None
        if isinstance(classes, dict) and classes and TEMPLATE_NAME.fullmatch(path.stem):
            out[path.stem] = tuple(sorted(str(c) for c in classes))
    return out


def classes(template: str) -> tuple[str, ...]:
    return limit_templates().get(template, ())


def limit_template_body(template: str) -> Optional[dict[str, Any]]:
    """A limit template whole, as ``GET /api/v1/sync/field`` sends it to the field's controllers (checked by
    ``sync_format.check_field_settings``): its id (the file's name), name, status and each class's energy
    limit, minimum engagement distance and fire mode. None when the file is gone or unreadable."""
    if not TEMPLATE_NAME.fullmatch(template):
        return None
    try:
        data = yaml.safe_load((Path(LIMIT_TEMPLATES) / f"{template}.yaml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    raw = data.get("classes") if isinstance(data, dict) else None
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, Any] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict) or isinstance(spec.get("max_energy_j"), bool) \
                or not isinstance(spec.get("max_energy_j"), (int, float)):
            return None
        out[str(name)] = {"max_energy_j": float(spec["max_energy_j"]), "med_m": spec.get("med_m"),
                          "fire_mode": spec.get("fire_mode")}
    status, verified = data.get("status"), data.get("verified_date")
    body = {"id": template, "name": str(data.get("name") or template),
            "status": status if isinstance(status, str) else None,
            "verified_date": verified.isoformat() if hasattr(verified, "isoformat") else
            (verified if isinstance(verified, str) else None), "classes": out}
    try:  # what a controller would refuse is not sent: it keeps its own template
        sync_format.check_field_settings({"federation_label": None, "max_replicas": 1, "limit_template": body})
    except sync_format.SyncFormatError:
        return None
    return body


# --- checks ----------------------------------------------------------------------------------

def _printable(value: str) -> bool:
    return all(not (ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or 0xD800 <= ord(c) <= 0xDFFF) for c in value)


def clean_name(value: Any, name: str, limit: int, required: bool = False) -> Optional[str]:
    """One line of 1..limit characters (trimmed) without control characters, as the controller's check-in."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise RegistrationError(f"{name}_invalid")
        return None
    if not isinstance(value, str):
        raise RegistrationError(f"{name}_invalid")
    text = value.strip()
    if len(text) > limit or not _printable(text):
        raise RegistrationError(f"{name}_invalid")
    return text


def new_player_id() -> str:
    return "p-" + "".join(secrets.choice(ALPHABET) for _ in range(12))


def new_ticket() -> tuple[bytes, str]:
    secret = secrets.token_bytes(checkin_ticket.SECRET_LEN)
    return secret, checkin_ticket.secret_sha256(secret)


def ticket_answer(reg: GameRegistration, secret: bytes) -> dict[str, str]:
    """What the player gets once: the secret as the app sends it, and the printable ticket's text."""
    return {"ticket": checkin_ticket.secret_text(secret),
            "ticket_text": checkin_ticket.make({"registration_id": str(reg.id), "player_id": reg.player_id,
                                                "secret": secret})}


def is_open(game: ScheduledGame, now: datetime) -> bool:
    return game.status == "published" and scheduling.registration_state(game, now) == "open"


async def counts(db: AsyncSession, game_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Live registrations (registered or checked in) per scheduled game."""
    ids = list(game_ids)
    if not ids:
        return {}
    rows = await db.execute(select(GameRegistration.scheduled_game, func.count()).where(
        GameRegistration.scheduled_game.in_(ids), GameRegistration.status.in_(ACTIVE))
        .group_by(GameRegistration.scheduled_game))
    return {gid: int(n) for gid, n in rows}


async def player_id_for(db: AsyncSession, user_id: uuid.UUID, field_id: uuid.UUID, create: bool = True) -> Optional[str]:
    """The account's player id at the field, made now if it has none (and ``create``)."""
    pid = await db.scalar(select(FieldPlayerId.player_id).where(FieldPlayerId.user_id == user_id,
                                                                FieldPlayerId.field_id == field_id))
    if pid is not None or not create:
        return pid
    for _ in range(5):
        candidate = new_player_id()
        try:
            async with db.begin_nested():
                db.add(FieldPlayerId(field_id=field_id, player_id=candidate, user_id=user_id))
                await db.flush()
            return candidate
        except IntegrityError:
            continue  # 60 random bits: another account's id by chance, try again
    raise RegistrationError("player_id_unavailable", 503)


async def check_declarations(db: AsyncSession, field: Field, game: ScheduledGame, player_id: str,
                             items: Any) -> list[dict[str, Any]]:
    """The pre-declared replicas as the controller's check-in would take them (protocol/checkin.md):
    a type and a class of the field's limit template, at most the field's ``max_replicas``; a replica of
    the person's in the field's registry brings its own type, class and make."""
    if items is None:
        return []
    if not isinstance(items, list):
        raise RegistrationError("replicas_invalid")
    if items and not game.predeclare_replicas:
        raise RegistrationError("replicas_not_asked")
    if len(items) > min(field.max_replicas, MAX_REPLICAS):
        raise RegistrationError("too_many_replicas")
    allowed = classes(field.limit_template)
    out: list[dict[str, Any]] = []
    seen: set[uuid.UUID] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) - {"replica_id", "type", "class", "make_model"}:
            raise RegistrationError("replicas_invalid")
        decl: dict[str, Any] = {"declaration_id": uuid.uuid4(), "replica_id": None}
        if item.get("replica_id") is not None:
            try:
                rid = uuid.UUID(str(item["replica_id"]))
            except ValueError:
                raise RegistrationError("replicas_invalid") from None
            rep = await db.scalar(select(Replica).where(Replica.field_id == field.id, Replica.replica_id == rid,
                                                        Replica.owner_player_id == player_id))
            if rep is None:
                raise RegistrationError("replica_unknown")
            if rid in seen:
                raise RegistrationError("replica_twice")
            seen.add(rid)
            decl.update(replica_id=rid, type=rep.replica_type, cls=rep.replica_class, make_model=rep.make_model)
        else:
            decl.update(type=item.get("type"), cls=item.get("class"),
                        make_model=clean_name(item.get("make_model"), "make_model", MAKE_MODEL_MAX))
        if decl["type"] not in REPLICA_TYPES:
            raise RegistrationError("replica_type_invalid")
        if decl["cls"] not in allowed:
            raise RegistrationError("replica_class_invalid")
        out.append(decl)
    return out


def _team(game: ScheduledGame, value: Any) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or value not in (game.teams or []):
        raise RegistrationError("team_preference_invalid")
    return value


APDS_FILE = Path(__file__).resolve().parents[1] / "data" / "apds.json"


@functools.lru_cache(maxsize=1)
def project_apds() -> list[dict[str, Any]]:
    """The project's list of APDs (``data/apds.json``, a copy of ``registry/apds/apds.json``), without each
    entry's ``source``."""
    doc = json.loads(APDS_FILE.read_text(encoding="utf-8"))
    return [{k: v for k, v in e.items() if k != "source"} for e in doc["apds"]]


def field_rule(field: Optional[Field]) -> dict[str, Any]:
    """The field's APD rule, normalised (the default when none is set or it cannot be read: a rule stored by an
    older build must never lock a registration out)."""
    try:
        return apd_core.check_rule(field.apd_rule if field is not None else None)
    except apd_core.ApdError:
        return apd_core.default_rule()


def field_country(field: Optional[Field]) -> Optional[str]:
    """The field's country (null: unset), which picks the wording and the list it offers (decisions MEM-2, MEM-3)."""
    return field.country if field is not None else None


def country_apds(country: Optional[str]) -> list[dict[str, Any]]:
    """The project's entries of ``country`` (none for a field without one): what a field of it offers besides
    the entries in its own rule (``custom``)."""
    return [e for e in project_apds() if country is not None and e.get("country") == country]


def asks_membership(game: ScheduledGame, rule: dict[str, Any]) -> bool:
    """Whether the game or the field's rule has a use for the membership number (protocol/apd.md): otherwise it
    is dropped, as the federation number always was."""
    return game.federation != "off" or rule["register"] or rule["checkin"]


def game_day(game: ScheduledGame, field: Optional[Field]) -> str:
    """The local date (``YYYY-MM-DD``) the game is played on, in the field's time zone."""
    try:
        tz = ZoneInfo(field.timezone) if field is not None else timezone.utc
    except (KeyError, ValueError):
        tz = timezone.utc
    return game.starts_at.astimezone(tz).date().isoformat()


def declared_membership(body: dict[str, Any]) -> dict[str, Any]:
    """What a request body says about the membership, only for the keys it has: ``number`` (``membership_number``,
    or the old ``federation_number``: both given must agree), ``apd`` and ``expires`` (a date)."""
    out: dict[str, Any] = {}
    names = [k for k in ("membership_number", "federation_number") if k in body]
    if names:
        values = [clean_name(body[k], "federation_number", FEDERATION_MAX) for k in names]
        if len(set(values)) > 1:
            raise RegistrationError("membership_number_conflict")
        out["number"] = values[0]
    if "apd_id" in body:
        v = body["apd_id"]
        if v is not None and v != "":
            if not isinstance(v, str) or not apd_core.ID_RE.fullmatch(v):
                raise RegistrationError("apd_id_invalid")
        out["apd"] = v or None
    if "membership_expires" in body:
        v = body["membership_expires"]
        if v is not None and v != "":
            try:
                apd_core.check_membership({"expires": v})
            except apd_core.ApdError:
                raise RegistrationError("membership_expires_invalid") from None
            out["expires"] = date.fromisoformat(v)
        else:
            out["expires"] = None
    return out


def membership_for(game: ScheduledGame, field: Optional[Field], cur: tuple[Optional[str], Optional[str], Optional[date]],
                   declared: dict[str, Any], enforce: bool) -> tuple[Optional[str], Optional[str], Optional[date]]:
    """The registration's ``(number, apd_id, expires)`` after ``declared`` is put over ``cur`` and the game's and
    the field's rules are applied: all of it is dropped when neither asks for a membership; the number is needed
    when the game requires one; with ``enforce`` (a player registering or changing) a field rule with ``register``
    refuses a missing number, an APD it does not accept and an expired membership (protocol/apd.md)."""
    number = declared["number"] if "number" in declared else cur[0]
    apd = declared["apd"] if "apd" in declared else cur[1]
    expires = declared["expires"] if "expires" in declared else cur[2]
    rule = field_rule(field)
    if not asks_membership(game, rule):
        return None, None, None
    if game.federation == "required" and number is None:
        raise RegistrationError("federation_number_required")
    if enforce and rule["register"]:
        verdict = apd_core.status(rule, apd, number, expires.isoformat() if expires else None,
                                  game_day(game, field))
        if verdict != "valid":
            raise RegistrationError({"missing": "membership_missing", "not_accepted": "apd_not_accepted",
                                     "expired": "membership_expired"}[verdict])
    return number, apd, expires


def membership_status(game: Optional[ScheduledGame], field: Optional[Field], reg: GameRegistration,
                      now: Optional[datetime] = None) -> Optional[str]:
    """The verdict shown to staff (null when no rule of the field asks at registration or check-in)."""
    rule = field_rule(field)
    if not (rule["register"] or rule["checkin"]):
        return None
    on = game_day(game, field) if game is not None else (now or datetime.now(timezone.utc)).date().isoformat()
    return apd_core.status(rule, reg.apd_id, reg.federation_number,
                           reg.membership_expires.isoformat() if reg.membership_expires else None, on)


async def replicas_of(db: AsyncSession, reg_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[RegistrationReplica]]:
    ids = list(reg_ids)
    out: dict[uuid.UUID, list[RegistrationReplica]] = {i: [] for i in ids}
    if ids:
        rows = await db.scalars(select(RegistrationReplica).where(RegistrationReplica.registration.in_(ids))
                                .order_by(RegistrationReplica.registration, RegistrationReplica.position))
        for r in rows:
            out[r.registration].append(r)
    return out


async def _put_replicas(db: AsyncSession, reg: GameRegistration, decls: list[dict[str, Any]]) -> None:
    await db.execute(RegistrationReplica.__table__.delete().where(RegistrationReplica.registration == reg.id))
    for pos, d in enumerate(decls):
        db.add(RegistrationReplica(registration=reg.id, declaration_id=d["declaration_id"], replica_id=d["replica_id"],
                                   replica_type=d["type"], replica_class=d["cls"], make_model=d["make_model"],
                                   position=pos))


async def lock_game(db: AsyncSession, field_id: uuid.UUID, game_id: uuid.UUID) -> ScheduledGame:
    """The scheduled game, its row locked: two registrations at once cannot both take the last place."""
    game = await db.scalar(select(ScheduledGame).where(ScheduledGame.id == game_id, ScheduledGame.field_id == field_id)
                           .with_for_update())
    if game is None or game.status == "draft":
        raise RegistrationError("scheduled_game_not_found", 404)
    return game


async def register(db: AsyncSession, field: Field, game: ScheduledGame, user_id: uuid.UUID, username: str,
                   body: dict[str, Any], now: datetime) -> tuple[GameRegistration, bytes]:
    """A new registration (or a cancelled one made live again) in the caller's transaction, ``game``
    locked by ``lock_game``. Returns it and its ticket secret (shown once)."""
    if not is_open(game, now):
        raise RegistrationError("registration_closed", 409)
    existing = await db.scalar(select(GameRegistration).where(GameRegistration.scheduled_game == game.id,
                                                             GameRegistration.user_id == user_id))
    if existing is not None and existing.status != "cancelled":
        raise RegistrationError("already_registered", 409)
    if game.max_players is not None and (await counts(db, [game.id])).get(game.id, 0) >= game.max_players:
        raise RegistrationError("game_full", 409)
    if existing is None:
        await quotas.check(db, "registrations", field.id)
    name = clean_name(body.get("display_name"), "display_name", NAME_MAX) or username[:NAME_MAX]
    team = _team(game, body.get("team_preference"))
    number, apd_id, expires = membership_for(game, field, (None, None, None), declared_membership(body), True)
    pid = await player_id_for(db, user_id, field.id)
    assert pid is not None
    decls = await check_declarations(db, field, game, pid, body.get("replicas"))
    secret, digest = new_ticket()
    if existing is None:
        reg = GameRegistration(scheduled_game=game.id, field_id=field.id, user_id=user_id, player_id=pid,
                               source="site")
        db.add(reg)
    else:
        reg = existing
        reg.player_id, reg.cancelled_at, reg.outcome_at = pid, None, None
    reg.display_name, reg.team_preference, reg.federation_number = name, team, number
    reg.apd_id, reg.membership_expires = apd_id, expires
    reg.status, reg.ticket_hash, reg.updated_at = "registered", digest, now
    await db.flush()
    await _put_replicas(db, reg, decls)
    return reg, secret


async def change(db: AsyncSession, field: Field, game: ScheduledGame, reg: GameRegistration, body: dict[str, Any],
                 now: datetime, staff: bool) -> list[str]:
    """Changes what was sent (display name, team preference, federation number, replicas). The player
    while the window is open, staff until the game starts. Returns the names of what changed."""
    if reg.status != "registered":
        raise RegistrationError("not_registered", 409)
    if staff:
        if game.status != "published" or game.starts_at <= now:
            raise RegistrationError("game_started", 409)
    elif not is_open(game, now):
        raise RegistrationError("registration_closed", 409)
    changed = []
    if "display_name" in body:
        name = clean_name(body["display_name"], "display_name", NAME_MAX, required=True)
        if name != reg.display_name:
            reg.display_name = name
            changed.append("display_name")
    if "team_preference" in body:
        team = _team(game, body["team_preference"])
        if team != reg.team_preference:
            reg.team_preference = team
            changed.append("team_preference")
    if any(k in body for k in ("federation_number", "membership_number", "apd_id", "membership_expires")):
        number, apd_id, expires = membership_for(game, field, (reg.federation_number, reg.apd_id, reg.membership_expires),
                                                 declared_membership(body), enforce=not staff)
        for name, new in (("federation_number", number), ("apd_id", apd_id), ("membership_expires", expires)):
            if new != getattr(reg, name):
                setattr(reg, name, new)
                changed.append(name)
    if "replicas" in body:
        decls = await check_declarations(db, field, game, reg.player_id, body["replicas"])
        if await _replace_replicas(db, reg, decls):
            changed.append("replicas")
    if changed:
        reg.updated_at = now
    return changed


def _replica_key(replica_id: Optional[uuid.UUID], kind: str, cls: str, make_model: Optional[str]) -> tuple[Any, ...]:
    return (replica_id, kind, cls, make_model)


async def _replace_replicas(db: AsyncSession, reg: GameRegistration, decls: list[dict[str, Any]]) -> bool:
    """Puts the declarations in place of the registration's, and says whether they differed. A declaration
    that is the same as one already there keeps its ``declaration_id`` (the controller's roster follows it), so
    saving the form with nothing changed, or adding one replica, does not renew the others."""
    old = (await replicas_of(db, [reg.id]))[reg.id]
    if [_replica_key(r.replica_id, r.replica_type, r.replica_class, r.make_model) for r in old] == \
            [_replica_key(d["replica_id"], d["type"], d["cls"], d["make_model"]) for d in decls]:
        return False
    pool: dict[tuple[Any, ...], list[uuid.UUID]] = {}
    for r in old:
        pool.setdefault(_replica_key(r.replica_id, r.replica_type, r.replica_class, r.make_model), []).append(
            r.declaration_id)
    for d in decls:
        ids = pool.get(_replica_key(d["replica_id"], d["type"], d["cls"], d["make_model"]))
        if ids:
            d["declaration_id"] = ids.pop(0)
    await _put_replicas(db, reg, decls)
    return True


def cancel(game: ScheduledGame, reg: GameRegistration, now: datetime, staff: bool) -> None:
    if reg.status != "registered":
        raise RegistrationError("not_registered", 409)
    if staff:
        if game.status != "published" or game.starts_at <= now:
            raise RegistrationError("game_started", 409)
    elif not is_open(game, now):
        raise RegistrationError("registration_closed", 409)
    reg.status, reg.cancelled_at, reg.updated_at, reg.ticket_hash = "cancelled", now, now, None


def _staff_window(game: ScheduledGame, now: datetime) -> None:
    """What staff may change in a registration: a published game that has not started."""
    if game.status != "published" or game.starts_at <= now:
        raise RegistrationError("game_started", 409)


def mark_paid(game: ScheduledGame, reg: GameRegistration, paid: bool, user_id: uuid.UUID, now: datetime) -> bool:
    """Staff's note that the registration is paid (or not): when and who. No payment is processed. A withdrawn
    registration or a cancelled game cannot be marked paid (the note can still be cleared). False when
    nothing changed."""
    if paid:
        if reg.status == "cancelled":
            raise RegistrationError("registration_withdrawn", 409)
        if game.status == "cancelled":
            raise RegistrationError("game_cancelled", 409)
        if reg.paid_at is not None:
            return False
        reg.paid_at, reg.paid_by = now, user_id
    else:
        if reg.paid_at is None:
            return False
        reg.paid_at = reg.paid_by = None
    reg.updated_at = now
    return True


def mark_no_show(game: ScheduledGame, reg: GameRegistration, no_show: bool, user_id: uuid.UUID,
                 now: datetime) -> bool:
    """Staff's mark that a registered player did not come, once the game is over. Check-in stays the
    controller's: only an active registration (one the controller reported nothing about) is marked, and a
    controller's outcome overwrites the mark at its next push. Staff undo only a mark staff made. False
    when nothing changed."""
    if no_show:
        if reg.status == "no_show":
            return False
        if reg.status != "registered":
            raise RegistrationError("not_registered", 409)
        if game.status == "cancelled":
            raise RegistrationError("game_cancelled", 409)
        if game.status != "completed" and game.ends_at > now:
            raise RegistrationError("game_not_over", 409)
        reg.status, reg.outcome_at, reg.outcome_by = "no_show", now, user_id
    else:
        if reg.status != "no_show":
            return False
        if reg.outcome_by is None:
            raise RegistrationError("outcome_from_controller", 409)
        reg.status, reg.outcome_at, reg.outcome_by = "registered", None, None
    reg.updated_at = now
    return True


def _fit(game: ScheduledGame, field: Optional[Field], reg: GameRegistration) -> list[str]:
    """What the game's and the field's rules do to the registration's team and membership: the number is needed
    when the game requires one (refused without) and dropped when nothing asks for one; a team the game lacks is
    cleared. Staff's moves never enforce the field's ``register`` rule."""
    changed = []
    number, apd_id, expires = membership_for(game, field, (reg.federation_number, reg.apd_id, reg.membership_expires),
                                             {}, enforce=False)
    for name, new in (("federation_number", number), ("apd_id", apd_id), ("membership_expires", expires)):
        if new != getattr(reg, name):
            setattr(reg, name, new)
            changed.append(name)
    if reg.team_preference is not None and reg.team_preference not in (game.teams or []):
        reg.team_preference = None
        changed.append("team_preference")
    return changed


async def restore(db: AsyncSession, game: ScheduledGame, reg: GameRegistration, now: datetime) -> list[str]:
    """Brings a withdrawn registration back while the game has not started (staff; the window does not apply
    but the places and the federation rule do). It has no ticket: the player asks for a new one in the app
    (or the marshal ticks the name). Returns what the game's rules changed."""
    if reg.status != "cancelled":
        raise RegistrationError("not_withdrawn", 409)
    _staff_window(game, now)
    if reg.display_name is None:
        raise RegistrationError("registration_erased", 409)  # its person's data is gone: nothing to bring back
    if game.max_players is not None and (await counts(db, [game.id])).get(game.id, 0) >= game.max_players:
        raise RegistrationError("game_full", 409)
    changed = _fit(game, await db.get(Field, reg.field_id), reg)
    reg.status, reg.cancelled_at, reg.updated_at = "registered", None, now
    return changed


async def move(db: AsyncSession, source: ScheduledGame, target: ScheduledGame, reg: GameRegistration,
               now: datetime) -> list[str]:
    """Moves an active registration to another published game of the field that has not started, both games
    locked by the caller (``lock_game``, in id order). The person, the player id, the registration id, the
    ticket and the replicas stay (the ticket is the registration's, not the game's: it holds the registration
    id, the player id and a secret, and the roster carries its hash); the registration window does not apply
    (staff) but the places, the federation rule and the target's one registration per person do. Returns
    what the target's rules changed (team, federation number, replicas)."""
    if reg.status != "registered":
        raise RegistrationError("not_registered", 409)
    _staff_window(source, now)
    if target.id == source.id:
        raise RegistrationError("same_game", 400)
    if target.status == "cancelled":
        raise RegistrationError("game_cancelled", 409)
    if target.status != "published" or target.starts_at <= now:
        raise RegistrationError("target_started", 409)
    clash = [GameRegistration.player_id == reg.player_id]
    if reg.user_id is not None:
        clash.append(GameRegistration.user_id == reg.user_id)
    if reg.external_ref is not None:
        clash.append((GameRegistration.source == reg.source) & (GameRegistration.external_ref == reg.external_ref))
    if await db.scalar(select(GameRegistration.id).where(GameRegistration.scheduled_game == target.id, or_(*clash))):
        raise RegistrationError("already_registered_there", 409)
    if target.max_players is not None and (await counts(db, [target.id])).get(target.id, 0) >= target.max_players:
        raise RegistrationError("game_full", 409)
    changed = _fit(target, await db.get(Field, reg.field_id), reg)
    if not target.predeclare_replicas and (await replicas_of(db, [reg.id]))[reg.id]:
        await _put_replicas(db, reg, [])
        changed.append("replicas")
    reg.scheduled_game, reg.updated_at = target.id, now
    return changed


def renew_ticket(game: ScheduledGame, reg: GameRegistration, now: datetime) -> bytes:
    """A new ticket (the old one lost): the old one stops matching at the controller's next roster pull."""
    if reg.status != "registered" or game.status != "published" or game.starts_at <= now:
        raise RegistrationError("not_registered", 409)
    secret, reg.ticket_hash = new_ticket()
    reg.updated_at = now
    return secret


# --- views -----------------------------------------------------------------------------------

def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def replica_json(r: RegistrationReplica) -> dict[str, Any]:
    return {"declaration_id": str(r.declaration_id), "replica_id": str(r.replica_id) if r.replica_id else None,
            "type": r.replica_type, "class": r.replica_class, "make_model": r.make_model, "state": r.state,
            "reading_id": str(r.reading_id) if r.reading_id else None}


async def staff_names(db: AsyncSession, regs: Iterable[GameRegistration]) -> dict[uuid.UUID, str]:
    """The usernames of the staff accounts that marked these registrations paid (staff see them, a player not)."""
    ids = {r.paid_by for r in regs if r.paid_by is not None}
    if not ids:
        return {}
    return {i: name for i, name in await db.execute(select(User.id, User.username).where(User.id.in_(ids)))}


def registration_json(reg: GameRegistration, replicas: list[RegistrationReplica],
                      game: Optional[ScheduledGame] = None, field: Optional[Field] = None,
                      names: Optional[dict[uuid.UUID, str]] = None,
                      verdict_for: Optional[tuple[ScheduledGame, Field]] = None) -> dict[str, Any]:
    """A registration as its player or the field's staff see it: never the ticket's hash. ``names`` (the
    staff views) adds who marked it paid."""
    out: dict[str, Any] = {
        "id": str(reg.id), "scheduled_game_id": str(reg.scheduled_game), "field_id": str(reg.field_id),
        "player_id": reg.player_id, "display_name": reg.display_name, "team_preference": reg.team_preference,
        "federation_number": reg.federation_number, "membership_number": reg.federation_number,
        "apd_id": reg.apd_id, "membership_expires": reg.membership_expires.isoformat()
        if reg.membership_expires else None, "apd_status": membership_status(*(verdict_for or (game, field)), reg),
        "status": reg.status, "source": reg.source,
        "external_ref": reg.external_ref,
        "has_ticket": reg.ticket_hash is not None, "replicas": [replica_json(r) for r in replicas],
        "created_at": _iso(reg.created_at), "updated_at": _iso(reg.updated_at),
        "cancelled_at": _iso(reg.cancelled_at), "outcome_at": _iso(reg.outcome_at),
        "paid": reg.paid_at is not None, "paid_at": _iso(reg.paid_at),
        "no_show_by_staff": reg.status == "no_show" and reg.outcome_by is not None,
    }
    if names is not None:
        out["paid_by"] = names.get(reg.paid_by) if reg.paid_by is not None else None
    if game is not None:
        out["game"] = {"title": game.title, "starts_at": _iso(game.starts_at), "ends_at": _iso(game.ends_at),
                       "status": game.status}
    if field is not None:
        out["field"] = {"name": field.name, "slug": field.slug}
    return out


# --- the game-day sync (protocol/sync.md) ------------------------------------------------------

def _ts(value: datetime) -> float:
    return value.timestamp()


async def schedule(db: AsyncSession, field_id: uuid.UUID, now: datetime, days: int) -> dict[str, Any]:
    """GET /api/v1/sync/schedule: the field's published (and running) games that have not ended and start
    within ``days``."""
    rows = list(await db.scalars(select(ScheduledGame).where(
        ScheduledGame.field_id == field_id, ScheduledGame.status.in_(("published", "in_progress")),
        ScheduledGame.ends_at > now, ScheduledGame.starts_at < now + timedelta(days=days))
        .order_by(ScheduledGame.starts_at, ScheduledGame.id).limit(sync_format.MAX_SCHEDULE)))
    field = await db.get(Field, field_id)
    n = await counts(db, [g.id for g in rows])
    games = []
    for g in rows:
        entry: dict[str, Any] = {
            "scheduled_game_id": str(g.id), "title": g.title, "starts_at": _ts(g.starts_at), "ends_at": _ts(g.ends_at),
            "status": g.status, "teams": list(g.teams or ()), "federation": g.federation,
            "predeclare_replicas": g.predeclare_replicas, "registered": n.get(g.id, 0)}
        if g.mode_id and sync_format.MODE_ID.fullmatch(g.mode_id):
            entry["mode_id"] = g.mode_id
        if g.max_players is not None:
            entry["max_players"] = g.max_players
        place = scheduling.location(g, field) if field is not None else g.location_text
        if place:
            entry["location"] = place
        games.append(entry)
    return {"sync_version": sync_format.SYNC_VERSION, "games": games}


async def roster(db: AsyncSession, field_id: uuid.UUID, game_id: uuid.UUID) -> Optional[dict[str, Any]]:
    """GET /api/v1/sync/roster: a scheduled game's live registrations, with only what ADR-P3-13's check-in
    holds (the federation number only when the game asks for one), or None for no such game here."""
    game = await db.scalar(select(ScheduledGame).where(ScheduledGame.id == game_id, ScheduledGame.field_id == field_id,
                                                       ScheduledGame.status != "draft"))
    if game is None:
        return None
    regs = list(await db.scalars(select(GameRegistration).where(
        GameRegistration.scheduled_game == game.id, GameRegistration.status == "registered",
        GameRegistration.display_name.is_not(None)).order_by(GameRegistration.created_at, GameRegistration.id)
        .limit(sync_format.MAX_ROSTER)))
    reps = await replicas_of(db, [r.id for r in regs])
    rule = field_rule(await db.get(Field, field_id))
    asks = asks_membership(game, rule)
    out = []
    for r in regs:
        entry: dict[str, Any] = {"registration_id": str(r.id), "player_id": r.player_id,
                                 "display_name": r.display_name, "replicas": []}
        if r.team_preference:
            entry["team_preference"] = r.team_preference
        if asks and r.federation_number:
            entry["federation_number"] = r.federation_number
            if r.apd_id:
                entry["apd_id"] = r.apd_id
            if r.membership_expires:
                entry["membership_expires"] = r.membership_expires.isoformat()
        if r.ticket_hash:
            entry["ticket_sha256"] = r.ticket_hash
        for d in reps[r.id]:
            decl: dict[str, Any] = {"declaration_id": str(d.declaration_id), "type": d.replica_type,
                                    "class": d.replica_class}
            if d.replica_id:
                decl["replica_id"] = str(d.replica_id)
            if d.make_model:
                decl["make_model"] = d.make_model
            entry["replicas"].append(decl)
        out.append(entry)
    answer = {"sync_version": sync_format.SYNC_VERSION, "scheduled_game_id": str(game.id), "status": game.status,
              "federation": game.federation, "registrations": out}
    if rule["register"] or rule["checkin"]:
        answer["apd"] = rule  # protocol/apd.md: the controller shows the verdict with the field's rule
    return answer


async def roster_players(db: AsyncSession, field_id: uuid.UUID, game_id: uuid.UUID) -> Optional[list[str]]:
    """The player ids of ``roster``'s registrations, in its order (None for no such game here): the
    players other fields' chrono records may be pulled for (S14-5)."""
    game = await db.scalar(select(ScheduledGame).where(ScheduledGame.id == game_id, ScheduledGame.field_id == field_id,
                                                       ScheduledGame.status != "draft"))
    if game is None:
        return None
    return list(await db.scalars(select(GameRegistration.player_id).where(
        GameRegistration.scheduled_game == game.id, GameRegistration.status == "registered",
        GameRegistration.display_name.is_not(None)).order_by(GameRegistration.created_at, GameRegistration.id)
        .limit(sync_format.MAX_ROSTER)))


def _agent(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()[:64]
    return text if text and _printable(text) else None


async def record_roster_pull(db: AsyncSession, key_id: uuid.UUID, game_id: uuid.UUID, now: datetime,
                             user_agent: Optional[str]) -> None:
    """Notes that a controller pulled the game's roster: when, the key it used (its label and fingerprint now)
    and its User-Agent. A pull carries nothing else of the controller. ``updated_at`` is kept: the public pages'
    and feeds' ``Last-Modified`` follows what the game shows, not a pull."""
    key = await db.get(FieldApiKey, key_id)
    await db.execute(update(ScheduledGame).where(ScheduledGame.id == game_id).values(
        roster_pulled_at=now, roster_key_label=key.label[:64] if key is not None and key.label else None,
        roster_key_fingerprint=key.key_sha256[:8] if key is not None else None, roster_agent=_agent(user_agent),
        updated_at=ScheduledGame.updated_at).execution_options(synchronize_session=False))


# The scheduled game follows its controller game: published -> in_progress -> completed, never back.
_FORWARD = {"running": "in_progress", "paused": "in_progress", "ended": "completed"}


async def link_game(db: AsyncSession, field_id: uuid.UUID, scheduled_id: Optional[str], game_id: uuid.UUID,
                    state: str) -> bool:
    """POST /api/v1/sync/games named the scheduled game the controller's game was made from: link them
    and move the scheduled game's status on with the game. False when there is no such game here (it is
    not an error: the controller may have an old schedule)."""
    if scheduled_id is None:
        return False
    game = await db.scalar(select(ScheduledGame).where(ScheduledGame.id == uuid.UUID(scheduled_id),
                                                       ScheduledGame.field_id == field_id).with_for_update())
    if game is None or game.status not in ("published", "in_progress", "completed"):
        return False
    game.controller_game = game_id  # the last game made from it wins (the GM may have made it again)
    target = _FORWARD.get(state)
    order = ("published", "in_progress", "completed")
    if target is not None and order.index(target) > order.index(game.status):
        game.status = target
    return True


async def erase_numbers(db: AsyncSession, game_id: uuid.UUID) -> int:
    """The membership number of every registration of the scheduled game that was made into this game, when the
    game ends (protocol/apd.md, "The card check"): the card was compared at the field, so the number is not
    kept for the 30 days the APD and expiry stay. Returns how many were cleared."""
    sched = select(ScheduledGame.id).where(ScheduledGame.controller_game == game_id).scalar_subquery()
    result = await db.execute(update(GameRegistration).where(
        GameRegistration.scheduled_game.in_(sched), GameRegistration.federation_number.is_not(None))
        .values(federation_number=None).execution_options(synchronize_session=False))
    return result.rowcount or 0


async def apply_checkins(db: AsyncSession, field_id: uuid.UUID, game: Game, body: dict[str, Any],
                         now: datetime) -> dict[str, Any]:
    """POST /api/v1/sync/checkins: each registration's outcome and its declarations' final states. A
    registration the controller had in a roster is matched by its id and player id; one it had not (the
    app sent its registration id and ticket at check-in, ``ticket_sha256``) only if that ticket is the
    registration's. Anything else is ignored and counted."""
    sched = await db.scalar(select(ScheduledGame).where(ScheduledGame.id == uuid.UUID(body["scheduled_game_id"]),
                                                        ScheduledGame.field_id == field_id).with_for_update())
    if sched is None:
        return {"linked": False, "applied": 0, "ignored": len(body["registrations"])}
    if sched.controller_game is None:
        sched.controller_game = game.id
    sched.walkins = body["walkins"]
    applied = ignored = declarations = 0
    for item in body["registrations"]:
        reg = await db.scalar(select(GameRegistration).where(
            GameRegistration.id == uuid.UUID(item["registration_id"]), GameRegistration.scheduled_game == sched.id))
        proof = item["ticket_sha256"]
        if reg is None or (proof is None and reg.player_id != item["player_id"]) or (
                proof is not None and not (reg.ticket_hash and hmac.compare_digest(reg.ticket_hash, proof))):
            ignored += 1
            continue
        if reg.status == "cancelled" and item["outcome"] == "no_show":
            ignored += 1  # cancelled and did not come: nothing to record
            continue
        reg.status, reg.outcome_at, reg.updated_at = item["outcome"], now, now
        reg.outcome_by = None  # the controller's word replaces a mark staff made
        reg.federation_number = None  # the card was checked at the field: the number has done its job (LEG-5)
        applied += 1
        for d in item["declarations"]:
            result = await db.execute(update(RegistrationReplica).where(
                RegistrationReplica.registration == reg.id,
                RegistrationReplica.declaration_id == uuid.UUID(d["declaration_id"])).values(
                state=d["state"], reading_id=uuid.UUID(d["reading_id"]) if d["reading_id"] else None))
            declarations += result.rowcount or 0
    return {"linked": True, "applied": applied, "ignored": ignored, "declarations": declarations}


# --- claims of a phone's player id (decision S16-4) -------------------------------------------

def secret_hash(player_secret: Any) -> str:
    """The SHA-256 (hex) of a phone's field secret, checked as the controller checks it (43 characters of
    canonical base64url, 32 bytes). The secret itself is not kept."""
    try:
        raw = checkin_ticket.secret_from_text(player_secret)
    except checkin_ticket.TicketError:
        raise RegistrationError("player_secret_invalid") from None
    return hashlib.sha256(raw).hexdigest()


async def claim(db: AsyncSession, user_id: uuid.UUID, field_id: uuid.UUID, player_id: Any,
                player_secret: Any) -> PlayerIdClaim:
    if not isinstance(player_id, str) or not sync_format.PLAYER_ID.fullmatch(player_id):
        raise RegistrationError("player_id_invalid")
    digest = secret_hash(player_secret)
    if await player_id_for(db, user_id, field_id, create=False) is not None:
        raise RegistrationError("player_id_exists", 409)
    taken = await db.scalar(select(FieldPlayerId.id).where(FieldPlayerId.field_id == field_id,
                                                           FieldPlayerId.player_id == player_id))
    if taken is not None:
        raise RegistrationError("player_id_taken", 409)
    await db.execute(PlayerIdClaim.__table__.delete().where(
        PlayerIdClaim.user_id == user_id, PlayerIdClaim.field_id == field_id, PlayerIdClaim.status == "pending"))
    row = PlayerIdClaim(user_id=user_id, field_id=field_id, player_id=player_id, secret_sha256=digest)
    db.add(row)
    await db.flush()
    return row


async def pending_claims(db: AsyncSession, field_id: uuid.UUID) -> dict[str, Any]:
    rows = await db.scalars(select(PlayerIdClaim).where(PlayerIdClaim.field_id == field_id,
                                                        PlayerIdClaim.status == "pending")
                            .order_by(PlayerIdClaim.created_at, PlayerIdClaim.id).limit(sync_format.MAX_CLAIMS))
    return {"sync_version": sync_format.SYNC_VERSION,
            "claims": [{"claim_id": str(c.id), "player_id": c.player_id, "secret_sha256": c.secret_sha256}
                       for c in rows]}


async def apply_claims(db: AsyncSession, field_id: uuid.UUID, body: dict[str, Any], now: datetime) -> dict[str, int]:
    """POST /api/v1/sync/claims: a confirmed claim links the player id to the account, unless another account
    took it meanwhile or the account got an id of its own here (then it is refused)."""
    out = {"confirmed": 0, "refused": 0, "pending": 0}
    for item in body["results"]:
        c = await db.scalar(select(PlayerIdClaim).where(PlayerIdClaim.id == uuid.UUID(item["claim_id"]),
                                                        PlayerIdClaim.field_id == field_id,
                                                        PlayerIdClaim.status == "pending").with_for_update())
        if c is None or item["result"] == "unknown":
            out["pending"] += c is not None
            continue
        status = "refused"
        if item["result"] == "confirmed":
            free = await db.scalar(select(FieldPlayerId.id).where(FieldPlayerId.field_id == field_id,
                                                                  FieldPlayerId.player_id == c.player_id)) is None
            if free and await player_id_for(db, c.user_id, field_id, create=False) is None:
                db.add(FieldPlayerId(field_id=field_id, player_id=c.player_id, user_id=c.user_id))
                await hub_share.sync_user(db, c.user_id)  # its readings join a hosted hub's shared view (SVX-2)
                status = "confirmed"
        c.status, c.decided_at = status, now
        out[status] += 1
    await db.flush()
    return out


def claim_json(c: PlayerIdClaim) -> dict[str, Any]:
    return {"id": str(c.id), "field_id": str(c.field_id), "player_id": c.player_id, "status": c.status,
            "created_at": _iso(c.created_at), "decided_at": _iso(c.decided_at)}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
