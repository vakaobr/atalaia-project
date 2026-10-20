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
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import yaml
from atalaia_controller import REPO_ROOT, checkin_ticket, sync_format
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (Field, FieldPlayerId, Game, GameRegistration, PlayerIdClaim, RegistrationReplica, Replica,
                      ScheduledGame)
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


def _federation(game: ScheduledGame, value: Any) -> Optional[str]:
    number = clean_name(value, "federation_number", FEDERATION_MAX)
    if game.federation == "off":
        return None
    if game.federation == "required" and number is None:
        raise RegistrationError("federation_number_required")
    return number


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
    name = clean_name(body.get("display_name"), "display_name", NAME_MAX) or username[:NAME_MAX]
    team = _team(game, body.get("team_preference"))
    federation = _federation(game, body.get("federation_number"))
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
    reg.display_name, reg.team_preference, reg.federation_number = name, team, federation
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
    if "federation_number" in body:
        number = _federation(game, body["federation_number"])
        if number != reg.federation_number:
            reg.federation_number = number
            changed.append("federation_number")
    if "replicas" in body:
        await _put_replicas(db, reg, await check_declarations(db, field, game, reg.player_id, body["replicas"]))
        changed.append("replicas")
    if changed:
        reg.updated_at = now
    return changed


def cancel(game: ScheduledGame, reg: GameRegistration, now: datetime, staff: bool) -> None:
    if reg.status != "registered":
        raise RegistrationError("not_registered", 409)
    if staff:
        if game.status != "published" or game.starts_at <= now:
            raise RegistrationError("game_started", 409)
    elif not is_open(game, now):
        raise RegistrationError("registration_closed", 409)
    reg.status, reg.cancelled_at, reg.updated_at, reg.ticket_hash = "cancelled", now, now, None


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


def registration_json(reg: GameRegistration, replicas: list[RegistrationReplica],
                      game: Optional[ScheduledGame] = None, field: Optional[Field] = None) -> dict[str, Any]:
    """A registration as its player or the field's staff see it: never the ticket's hash."""
    out: dict[str, Any] = {
        "id": str(reg.id), "scheduled_game_id": str(reg.scheduled_game), "field_id": str(reg.field_id),
        "player_id": reg.player_id, "display_name": reg.display_name, "team_preference": reg.team_preference,
        "federation_number": reg.federation_number, "status": reg.status, "source": reg.source,
        "external_ref": reg.external_ref,
        "has_ticket": reg.ticket_hash is not None, "replicas": [replica_json(r) for r in replicas],
        "created_at": _iso(reg.created_at), "updated_at": _iso(reg.updated_at),
        "cancelled_at": _iso(reg.cancelled_at), "outcome_at": _iso(reg.outcome_at),
    }
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
    out = []
    for r in regs:
        entry: dict[str, Any] = {"registration_id": str(r.id), "player_id": r.player_id,
                                 "display_name": r.display_name, "replicas": []}
        if r.team_preference:
            entry["team_preference"] = r.team_preference
        if r.federation_number and game.federation != "off":
            entry["federation_number"] = r.federation_number
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
    return {"sync_version": sync_format.SYNC_VERSION, "scheduled_game_id": str(game.id), "status": game.status,
            "federation": game.federation, "registrations": out}


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
