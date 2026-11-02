# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chrono sharing across the tenants of a hosted hub (SVX-2; ADR-P4-4's amendment of 2026-10-28).

Single-field mode shares chrono records between fields by the one account that holds a player id at both
(``chrono_registry.shared_history``). In hosted mode each field is a schema of its own with its own accounts
(S21-2), and the server's role may read nothing outside it, so the sharing goes through the hub's three tables in
``public`` (``atalaia_share_members``, ``atalaia_share_records``, ``atalaia_share_codes``; made by ``hosted init`` /
``hosted migrate``, see ``hosted.SHARE_DDL``):

- **Link.** A person who has an account at two hosted fields says so: at the first field they ask for a link code
  (``new_code``: 16 random bytes shown once, kept only as a SHA-256, 15 minutes, once), at the second they give it
  back (``redeem``). Both accounts then hold the same random ``person_id`` (``hub_share_links``). Nothing is matched
  by e-mail address or user name.
- **Publish.** A field publishes the signed records (exactly as stored, with the marshal's public key) of a linked
  person's player ids at that field, and only while the link is *active*: the person's live ``chrono_sharing``
  consent for this field, and the field's ``chrono_sharing_enabled``. ``sync_user`` makes the hub's rows say what
  this field's rows say now; it runs wherever one of those changes (consent, the field's switch, a link, an adopted
  player id, an erasure) and ``publish`` adds each new reading as it arrives; the retention purge runs ``sync_all``.
  A tenant can only touch its own rows there (row-level security on ``tenant``).
- **Read.** ``shared_history`` calls ``public.atalaia_share_read``, a SECURITY DEFINER function that takes the
  caller's tenant from ``atalaia.tenant`` and returns another field's records of the person only when both fields
  are active members for that person and the other field is active in the registry. It reads hub tables only.

None of it runs in a single-field server (``available()`` is False): the sharing there is the old one.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import (Boolean, Column, DateTime, LargeBinary, MetaData, String, Table, Text, bindparam, delete, func,
                        select, text)
from sqlalchemy.dialects.postgresql import ARRAY, UUID, insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import sharing_terms, tenancy
from .models import ChronoReading, Consent, Field, FieldPlayerId, HubShareLink, MarshalKey

SHARING = "chrono_sharing"
CODE_TTL_S = 900
CODE_BYTES = 16
MAX_PUBLISHED = 2000        # the newest records of one person a field publishes
MAX_READ = 500              # the newest records of one person a field reads from the hub

_hub = MetaData()
members = Table("atalaia_share_members", _hub, Column("person_id", UUID(as_uuid=True), primary_key=True),
                Column("tenant", String, primary_key=True), Column("active", Boolean),
                Column("field_name", String), Column("updated_at", DateTime(timezone=True)), schema="public")
records = Table("atalaia_share_records", _hub, Column("tenant", String, primary_key=True),
                Column("person_id", UUID(as_uuid=True)), Column("reading_id", UUID(as_uuid=True), primary_key=True),
                Column("taken_at", DateTime(timezone=True)), Column("record_json", Text),
                Column("public_key", String), schema="public")
codes = Table("atalaia_share_codes", _hub, Column("code_hash", LargeBinary, primary_key=True),
              Column("person_id", UUID(as_uuid=True)), Column("tenant", String),
              Column("expires_at", DateTime(timezone=True)), schema="public")

_READ = text("SELECT person_id, field_name, reading_id, taken_at, record_json, public_key "
             "FROM public.atalaia_share_read(:persons, :n)").bindparams(
    bindparam("persons", type_=ARRAY(UUID(as_uuid=True))))


class HubShareProblem(Exception):
    """A refusal to answer with ``status`` and ``detail``."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status, self.detail = status, detail


def available() -> bool:
    """True in hosted mode, within a tenant's request: the only place the hub's tables apply."""
    return tenancy.current() is not None


def _tenant() -> str:
    schema = tenancy.current_schema()
    if schema is None:
        raise HubShareProblem(404, "not_hosted")
    return schema


def normalise(code: Any) -> str:
    return "".join(c for c in str(code).upper() if c.isalnum()) if isinstance(code, str) else ""


def code_hash(code: str) -> bytes:
    return hashlib.sha256(normalise(code).encode("ascii", "ignore")).digest()


def pretty(raw: bytes) -> str:
    text_ = base64.b32encode(raw).decode("ascii").rstrip("=")
    return "-".join(text_[i:i + 4] for i in range(0, len(text_), 4))


async def _field(db: AsyncSession) -> Field:
    field = await db.scalar(select(Field).limit(1))  # a tenant has exactly one field (S21-2)
    if field is None:
        raise HubShareProblem(404, "field_not_found")
    return field


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# What this field publishes -----------------------------------------------------------------------

async def is_active(db: AsyncSession, user_id: uuid.UUID, field: Field) -> bool:
    live = await db.scalar(select(Consent.id).where(
        Consent.user_id == user_id, Consent.purpose == SHARING, Consent.field_id == field.id,
        Consent.withdrawn_at.is_(None)))
    return live is not None and sharing_terms.is_live(field)


async def sync_user(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Makes the hub's rows for one linked account say what this field's rows say now (the caller commits)."""
    if not available():
        return
    link = await db.get(HubShareLink, user_id)
    if link is None:
        return
    field, tenant = await _field(db), _tenant()
    active = await is_active(db, user_id, field)
    stmt = insert(members).values(person_id=link.person_id, tenant=tenant, active=active, field_name=field.name,
                                  updated_at=func.now())
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["person_id", "tenant"],
        set_={"active": stmt.excluded.active, "field_name": stmt.excluded.field_name,
              "updated_at": stmt.excluded.updated_at}))
    if not active:
        await db.execute(delete(records).where(records.c.person_id == link.person_id))
        return
    wanted = (await db.execute(
        select(ChronoReading.reading_id, ChronoReading.timestamp, ChronoReading.record_json, MarshalKey.public_key)
        .join(MarshalKey, MarshalKey.id == ChronoReading.marshal_key)
        .where(ChronoReading.field_id == field.id, ChronoReading.player_id.in_(
            select(FieldPlayerId.player_id).where(FieldPlayerId.user_id == user_id,
                                                  FieldPlayerId.field_id == field.id)))
        .order_by(ChronoReading.timestamp.desc(), ChronoReading.reading_id.desc()).limit(MAX_PUBLISHED))).all()
    have = set(await db.scalars(select(records.c.reading_id).where(records.c.person_id == link.person_id)))
    keep = {r.reading_id for r in wanted}
    gone = list(have - keep)
    if gone:
        await db.execute(delete(records).where(records.c.person_id == link.person_id,
                                               records.c.reading_id.in_(gone)))
    fresh = [{"tenant": tenant, "person_id": link.person_id, "reading_id": r.reading_id, "taken_at": r.timestamp,
              "record_json": r.record_json, "public_key": base64.b64encode(bytes(r.public_key)).decode("ascii")}
             for r in wanted if r.reading_id not in have]
    if fresh:
        await db.execute(insert(records).on_conflict_do_nothing(), fresh)


async def sync_all(db: AsyncSession) -> int:
    """Every linked account again (the field's switch, the retention purge); returns how many."""
    if not available():
        return 0
    users = list(await db.scalars(select(HubShareLink.user_id)))
    for user_id in users:
        await sync_user(db, user_id)
    await db.execute(delete(codes).where(codes.c.expires_at < func.now()))
    return len(users)


async def publish(db: AsyncSession, field_id: uuid.UUID,
                  new: list[dict[str, Any]]) -> None:
    """Newly stored readings (``player_id``, ``reading_id``, ``taken_at``, ``record_json``, ``public_key`` as
    base64) of players whose account is linked and active are added to the hub's rows."""
    if not new or not available():
        return
    tenant = _tenant()
    owner = dict((await db.execute(
        select(FieldPlayerId.player_id, HubShareLink.person_id)
        .join(HubShareLink, HubShareLink.user_id == FieldPlayerId.user_id)
        .where(FieldPlayerId.field_id == field_id, FieldPlayerId.player_id.in_({r["player_id"] for r in new})))).all())
    if not owner:
        return
    active = set(await db.scalars(select(members.c.person_id).where(
        members.c.tenant == tenant, members.c.active.is_(True), members.c.person_id.in_(set(owner.values())))))
    rows = [{"tenant": tenant, "person_id": owner[r["player_id"]], "reading_id": r["reading_id"],
             "taken_at": r["taken_at"], "record_json": r["record_json"], "public_key": r["public_key"]}
            for r in new if owner.get(r["player_id"]) in active]
    if rows:
        await db.execute(insert(records).on_conflict_do_nothing(), rows)


async def forget_player(db: AsyncSession, field_id: uuid.UUID, player_id: str) -> None:
    """A player's erasure at the field: what the hub holds of their records goes too (``sync_user`` would do it
    on the next run; this does it now)."""
    if not available():
        return
    user_id = await db.scalar(select(FieldPlayerId.user_id).where(FieldPlayerId.field_id == field_id,
                                                                  FieldPlayerId.player_id == player_id))
    if user_id is None:
        return
    mine = select(ChronoReading.reading_id).where(ChronoReading.field_id == field_id,
                                                  ChronoReading.player_id == player_id)
    await db.execute(delete(records).where(records.c.reading_id.in_(mine)))


# Linking -------------------------------------------------------------------------------------------

_PEERS = text("SELECT field_name, active, updated_at FROM public.atalaia_share_peers(:person)")


async def status(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """Where the account's link stands. ``linked``, ``linked_at`` and ``sharing`` are the app's (APF-4); the rest is
    for the staff page (HLC-2): ``field`` (this field's id and name, the field's own switch and terms, and whether
    the account's consent for it is live) and ``others``, the other fields the person is linked at (name, whether
    sharing is on there, since when; never what they hold)."""
    _tenant()
    field = await _field(db)
    consent = await db.scalar(select(Consent.id).where(
        Consent.user_id == user_id, Consent.purpose == SHARING, Consent.field_id == field.id,
        Consent.withdrawn_at.is_(None))) is not None
    out: dict[str, Any] = {
        "linked": False, "linked_at": None, "sharing": False,
        "field": {"id": str(field.id), "name": field.name, "enabled": bool(field.chrono_sharing_enabled),
                  "live": sharing_terms.is_live(field)},
        "consent": consent, "others": []}
    link = await db.get(HubShareLink, user_id)
    if link is None:
        return out
    out["linked"], out["linked_at"] = True, link.linked_at.isoformat()
    out["sharing"] = consent and sharing_terms.is_live(field)
    out["others"] = [{"field_name": r.field_name, "sharing": bool(r.active), "since": _iso(r.updated_at)}
                     for r in (await db.execute(_PEERS, {"person": link.person_id})).all()]
    return out


async def new_code(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    """A link code for the account's person (made now if the account has none yet); shown once."""
    tenant = _tenant()
    link = await db.get(HubShareLink, user_id)
    if link is None:
        link = HubShareLink(user_id=user_id, person_id=uuid.uuid4())
        db.add(link)
        await db.flush()
    await sync_user(db, user_id)
    await db.execute(delete(codes).where(codes.c.expires_at < func.now()))
    raw = secrets.token_bytes(CODE_BYTES)
    expires = datetime.now(timezone.utc) + timedelta(seconds=CODE_TTL_S)
    await db.execute(insert(codes).values(code_hash=hashlib.sha256(normalise(pretty(raw)).encode()).digest(),
                                          person_id=link.person_id, tenant=tenant, expires_at=expires))
    return {"code": pretty(raw), "expires_at": expires.isoformat(), "expires_in": CODE_TTL_S}


async def redeem(db: AsyncSession, user_id: uuid.UUID, code: Any) -> dict[str, Any]:
    """Links the account to the person a code from another field names. The caller commits on success; a refusal
    raises before anything is committed, so the code is not used up."""
    tenant = _tenant()
    if not normalise(code):
        raise HubShareProblem(400, "invalid_code")
    person = await db.scalar(text("SELECT public.atalaia_share_redeem(:h)").bindparams(
        bindparam("h", type_=LargeBinary)), {"h": code_hash(code)})
    if person is None:
        raise HubShareProblem(400, "invalid_code")
    mine = await db.get(HubShareLink, user_id)
    if mine is not None:
        if mine.person_id == person:
            return await status(db, user_id)
        raise HubShareProblem(409, "already_linked")
    if await db.scalar(select(HubShareLink.user_id).where(HubShareLink.person_id == person)) is not None:
        raise HubShareProblem(409, "person_already_linked_here")
    if await db.scalar(select(members.c.person_id).where(members.c.person_id == person,
                                                          members.c.tenant == tenant)) is not None:
        raise HubShareProblem(409, "person_already_linked_here")
    db.add(HubShareLink(user_id=user_id, person_id=person))
    await db.flush()
    await sync_user(db, user_id)
    return await status(db, user_id)


async def unlink(db: AsyncSession, user_id: uuid.UUID) -> bool:
    """The account leaves the person's link; this field's rows in the hub go (the caller commits)."""
    if not available():
        return False
    link = await db.get(HubShareLink, user_id)
    if link is None:
        return False
    await db.execute(delete(members).where(members.c.person_id == link.person_id,
                                           members.c.tenant == _tenant()))  # its records go with it
    await db.execute(delete(codes).where(codes.c.person_id == link.person_id))
    await db.delete(link)
    await db.flush()
    return True


# What other fields published ---------------------------------------------------------------------------

async def shared_history(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Other hosted fields' records of the person behind this account (newest ``MAX_READ``), in the shape of
    ``chrono_registry.reading_json``: only what the hub's function returns, which is only what both fields are
    active for."""
    if not available():
        return []
    link = await db.get(HubShareLink, user_id)
    if link is None:
        return []
    rows = (await db.execute(_READ, {"persons": [link.person_id], "n": MAX_READ})).all()
    out = []
    for r in rows:
        try:
            parsed = json.loads(r.record_json)
        except ValueError:
            continue
        if not isinstance(parsed, dict):
            continue
        out.append({"field": r.field_name, "field_id": None, "reading_id": str(r.reading_id),
                    "record_json": r.record_json, "record": parsed, "public_key": r.public_key,
                    "timestamp": _iso(r.taken_at), "type": parsed.get("type"),
                    "velocity_mps": parsed.get("velocity_mps"), "bb_weight_g": parsed.get("bb_weight_g"),
                    "energy_j": parsed.get("energy_j"), "marshal_id": parsed.get("marshal_id"), "hub": True})
    return out
