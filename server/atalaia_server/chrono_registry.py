# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chrono registry on the site server (ADR-P4-5 as amended; plan phase 14, P4R14, P4R15).

The field controller pushes, after its games (``protocol/sync.md``):

- ``marshals``: each marshal's Ed25519 public keys with their periods. Upserted
  per (field, marshal, key); a key's period starts at its earliest registration
  and ends when the controller says it was replaced. Never a private key: the
  marshals' phones make and keep them (P4R14).
- ``replicas``: the field's replica registry, upserted by the app's ``replica_id``.
- ``chrono``: signed readings with the controller's series and outcome. Each
  record is verified with ``chrono_verify`` (the controller's ``chrono.py``)
  against its marshal's key valid when the controller received it, and stored
  exactly as sent (``record_json``); one that fails is kept apart in
  ``chrono_rejects`` with its reason and named in the answer, never silently
  dropped; one kept apart for want of its marshal's key (``marshal``) is
  checked again when that marshal's keys arrive. A reading sent again is a duplicate; another record under a stored
  reading id is a ``conflict``, kept apart. A spot check that failed or warned
  becomes a ``chrono_violations`` row for its series, pointing at the series'
  highest-energy reading.

Reading the registry (``api/chrono.py``, ``api/me.py``): the field's staff see
its readings, rejects, violations, keys and replicas; a person sees the
readings of the player ids their account holds at each field
(``field_player_ids``); another field sees them only when both fields share
and the person consented for both (``shared_history``), with each record's
marshal key so the record can be checked there without trusting this server.
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from atalaia_controller import sync_format
from sqlalchemy import and_, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from . import hub_share, sharing_terms
from .audit import record
from .chrono_verify import Key, same_record, verify_reading
from .models import (ChronoCopyRevocation, ChronoReading, ChronoReject, ChronoViolation, Consent, Field, FieldPlayerId, Game, MarshalKey,
                     PlayerIdClaim, Replica)

SHARING = "chrono_sharing"
DEFAULT_BAN_DAYS = 365  # a ban lasts 12 months unless the field sets another length (PRIV-2)


def _time(value: Optional[float]) -> Optional[datetime]:
    return datetime.fromtimestamp(value, tz=timezone.utc) if value is not None else None


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def record_time(text: str) -> datetime:
    """A record's ``timestamp`` (``YYYY-MM-DDTHH:MM:SSZ``) as an aware time."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def key_fingerprint(public_key: bytes) -> str:
    """The first 16 hex digits of the key's SHA-256, for staff to compare keys at a glance."""
    return hashlib.sha256(public_key).hexdigest()[:16]


# --- the sync bodies ---------------------------------------------------------------------

async def apply_marshals(db: AsyncSession, field_id: uuid.UUID, body: dict[str, Any]) -> dict[str, Any]:
    rows = [{"field_id": field_id, "marshal_id": m["marshal_id"], "name": m["name"],
             "public_key": base64.b64decode(m["public_key"]), "player_id": m["player_id"], "source": "controller",
             "valid_from": _time(m["registered_at"]), "valid_until": _time(m["replaced_at"])}
            for m in body["marshals"]]
    stmt = insert(MarshalKey).values(rows)
    ex = stmt.excluded
    stmt = stmt.on_conflict_do_update(
        index_elements=["field_id", "marshal_id", "public_key"],
        set_={"name": ex.name, "player_id": ex.player_id, "valid_until": ex.valid_until,
              "valid_from": func.least(MarshalKey.valid_from, ex.valid_from), "updated_at": func.now()},
    ).returning(MarshalKey.id, text("(xmax = 0) AS created"))
    result = (await db.execute(stmt)).all()
    resolved = await _retry(db, field_id, {m["marshal_id"] for m in body["marshals"]})
    return {"marshals": len(result), "added": sum(1 for row in result if row[1]), "resolved": resolved}


async def _retry(db: AsyncSession, field_id: uuid.UUID, marshal_ids: set[str]) -> int:
    """Readings kept apart because no key of their marshal was valid then (``marshal``) are checked again
    when that marshal's keys arrive; the ones that verify now are stored and leave the rejects."""
    rejects = (await db.scalars(select(ChronoReject).where(
        ChronoReject.field_id == field_id, ChronoReject.reason == "marshal",
        ChronoReject.marshal_id.in_(sorted(marshal_ids)), ChronoReject.received_at.is_not(None)))).all()
    if not rejects:
        return 0
    keys = await _keys(db, field_id, marshal_ids)
    resolved = 0
    for reject in rejects:
        entry = {"record": reject.record_text, "series_id": str(reject.series_id), "outcome": reject.outcome,
                 "received_at": reject.received_at.timestamp(), "game_seed": None}
        verdict = verify_reading(reject.record_text, entry["received_at"], lambda mid: keys.get(mid, []))
        if not verdict.ok:
            continue
        stored = await db.scalar(select(ChronoReading.record_json).where(
            ChronoReading.field_id == field_id, ChronoReading.reading_id == uuid.UUID(verdict.fields["reading_id"])))
        if stored is None:
            await _store(db, field_id, reject.controller, entry, verdict)
        elif not same_record(stored, reject.record_text):
            continue  # another record holds the id: this one stays apart
        await db.delete(reject)
        resolved += 1
    return resolved


async def apply_replicas(db: AsyncSession, field_id: uuid.UUID, body: dict[str, Any]) -> dict[str, Any]:
    rows = [{"field_id": field_id, "replica_id": uuid.UUID(r["replica_id"]), "owner_player_id": r["owner_player_id"],
             "replica_type": r["type"], "replica_class": r["class"], "make_model": r["make_model"],
             "tag_type": r["tag_type"], "tag_uid": r["tag_uid"],
             "registered_at": record_time(r["registered_at"]) if r["registered_at"] else None}
            for r in body["replicas"]]
    stmt = insert(Replica).values(rows)
    ex = stmt.excluded
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["field_id", "replica_id"],
        set_={"owner_player_id": ex.owner_player_id, "replica_type": ex.replica_type,
              "replica_class": ex.replica_class, "make_model": ex.make_model, "tag_type": ex.tag_type,
              "tag_uid": ex.tag_uid, "registered_at": ex.registered_at, "updated_at": func.now()}))
    return {"replicas": len(rows)}


async def _keys(db: AsyncSession, field_id: uuid.UUID, marshal_ids: set[str]) -> dict[str, list[Key]]:
    out: dict[str, list[Key]] = {}
    if not marshal_ids:
        return out
    rows = await db.scalars(select(MarshalKey).where(MarshalKey.field_id == field_id,
                                                     MarshalKey.marshal_id.in_(sorted(marshal_ids))))
    for k in rows:
        out.setdefault(k.marshal_id, []).append(Key(
            id=k.id, public_key=bytes(k.public_key), valid_from=k.valid_from.timestamp(),
            valid_until=k.valid_until.timestamp() if k.valid_until else None,
            revoked_at=k.revoked_at.timestamp() if k.revoked_at else None))
    return out


def _marshal_of(text: str) -> Optional[str]:
    import json  # noqa: PLC0415

    try:
        record = json.loads(text)
    except ValueError:
        return None
    mid = record.get("marshal_id") if isinstance(record, dict) else None
    return mid if isinstance(mid, str) else None


async def _game(db: AsyncSession, field_id: uuid.UUID, record_game: Optional[str],
                seed: Optional[int]) -> Optional[uuid.UUID]:
    if seed is None or not record_game or not record_game.isdigit() or int(record_game) > 0xFFFF:
        return None
    return await db.scalar(select(Game.id).where(Game.field_id == field_id, Game.game_id == int(record_game),
                                                 Game.game_seed == seed))


async def _keep_apart(db: AsyncSession, field_id: uuid.UUID, controller: Optional[uuid.UUID],
                      entry: dict[str, Any], reason: str, detail: str, verdict: Any) -> None:
    text = entry["record"]
    stmt = insert(ChronoReject).values(
        field_id=field_id, record_text=text, record_sha256=_sha(text), reason=reason, detail=detail[:256], reading_id=verdict.reading_id,
        player_id=verdict.text_field("player_id"), marshal_id=verdict.text_field("marshal_id"),
        series_id=uuid.UUID(entry["series_id"]), outcome=entry["outcome"], controller=controller,
        received_at=_time(entry["received_at"]))
    ex = stmt.excluded
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["field_id", "record_sha256"],
        set_={"times": ChronoReject.times + 1, "last_seen_at": func.now(), "reason": ex.reason, "detail": ex.detail,
              "controller": ex.controller}))


async def _store(db: AsyncSession, field_id: uuid.UUID, controller: Optional[uuid.UUID], entry: dict[str, Any],
                 verdict: Any) -> bool:
    """A verified reading, stored once (False: a concurrent request stored it first)."""
    f = verdict.fields
    inserted = await db.scalar(insert(ChronoReading).values(
        field_id=field_id, reading_id=uuid.UUID(f["reading_id"]), record_json=entry["record"],
        replica_id=uuid.UUID(f["replica_id"]), player_id=f["player_id"], type=f["type"],
        velocity_mps=f["velocity_mps"], bb_weight_g=f["bb_weight_g"], energy_j=f["energy_j"],
        chrono_id=f["chrono_id"], marshal_id=f["marshal_id"], record_field_id=f["field_id"],
        record_game_id=f.get("game_id"), timestamp=record_time(f["timestamp"]),
        ref_reading_id=uuid.UUID(f["ref_reading_id"]) if f.get("ref_reading_id") else None,
        series_id=uuid.UUID(entry["series_id"]), outcome=entry["outcome"], marshal_key=verdict.key.id,
        game=await _game(db, field_id, f.get("game_id"), entry.get("game_seed")), controller=controller,
        received_at=_time(entry["received_at"]),
    ).on_conflict_do_nothing(index_elements=["field_id", "reading_id"]).returning(ChronoReading.id))
    if inserted is None:
        return False
    if f["type"] == "spotcheck" and entry["outcome"] in ("fail", "warn"):
        await _violation(db, field_id, uuid.UUID(entry["series_id"]), entry.get("limit_j"))
    return True


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogatepass")).hexdigest()


async def apply_chrono(db: AsyncSession, field_id: uuid.UUID, controller: Optional[uuid.UUID],
                       body: dict[str, Any]) -> dict[str, Any]:
    """Verifies and stores a batch of readings; the answer names every one kept apart."""
    readings = body["readings"]
    keys = await _keys(db, field_id, {m for m in (_marshal_of(e["record"]) for e in readings) if m})
    accepted = duplicates = 0
    refused: list[dict[str, Any]] = []
    flagged: set[uuid.UUID] = set()
    published: list[dict[str, Any]] = []  # for the hub's shared view (SVX-2), when the player's person shares
    for index, entry in enumerate(readings):
        verdict = verify_reading(entry["record"], entry["received_at"], lambda mid: keys.get(mid, []))
        reason, detail = verdict.reason, verdict.detail
        if verdict.ok:
            f = verdict.fields
            stored = await db.scalar(select(ChronoReading.record_json).where(
                ChronoReading.field_id == field_id, ChronoReading.reading_id == uuid.UUID(f["reading_id"])))
            if stored is None and await _store(db, field_id, controller, entry, verdict):
                # The same record kept apart earlier for want of its marshal's key is settled now.
                await db.execute(delete(ChronoReject).where(
                    ChronoReject.field_id == field_id, ChronoReject.reason == "marshal",
                    ChronoReject.record_sha256 == _sha(entry["record"])))
                accepted += 1
                published.append({"player_id": f["player_id"], "reading_id": uuid.UUID(f["reading_id"]),
                                  "taken_at": record_time(f["timestamp"]), "record_json": entry["record"],
                                  "public_key": base64.b64encode(bytes(verdict.key.public_key)).decode("ascii")})
                if f["type"] == "spotcheck" and entry["outcome"] in ("fail", "warn"):
                    flagged.add(uuid.UUID(entry["series_id"]))
                continue
            if stored is None or same_record(stored, entry["record"]):
                duplicates += 1  # sent again (or stored by a concurrent request a moment ago)
                continue
            reason, detail = "conflict", f"another record is stored under reading_id {f['reading_id']}"
        await _keep_apart(db, field_id, controller, entry, reason or "format", detail, verdict)
        refused.append({"index": index, "reading_id": verdict.reading_id, "reason": reason, "detail": detail})
    await hub_share.publish(db, field_id, published)
    return {"accepted": accepted, "duplicates": duplicates, "refused": refused, "violations": len(flagged)}


async def _violation(db: AsyncSession, field_id: uuid.UUID, series: uuid.UUID, limit_j: Optional[float] = None) -> None:
    """The series' violation, at its highest-energy reading (as the controller judges a series). ``limit_j``, the
    class limit the controller judged against (PKD-3), gives ``delta_j`` (the excess over it); a series
    that arrives without one keeps the limit an earlier reading of it gave."""
    top = (await db.execute(select(ChronoReading).where(
        ChronoReading.field_id == field_id, ChronoReading.series_id == series)
        .order_by(ChronoReading.energy_j.desc(), ChronoReading.reading_id.desc()).limit(1))).scalar_one()
    vtype = "over_limit" if top.outcome == "fail" else "over_tolerance"
    stmt = insert(ChronoViolation).values(field_id=field_id, series_id=series, reading=top.id, player_id=top.player_id,
                                          replica_id=top.replica_id, violation_type=vtype, energy_j=top.energy_j,
                                          game=top.game, limit_j=limit_j,
                                          delta_j=top.energy_j - limit_j if limit_j is not None else None)
    ex = stmt.excluded
    await db.execute(stmt.on_conflict_do_update(
        index_elements=["field_id", "series_id"],
        set_={"reading": ex.reading, "energy_j": ex.energy_j, "violation_type": ex.violation_type,
              "limit_j": func.coalesce(ex.limit_j, ChronoViolation.limit_j),
              "delta_j": ex.energy_j - func.coalesce(ex.limit_j, ChronoViolation.limit_j)}))
    await _flag_repeats(db, field_id, top.player_id)


def counts_for_repeat(violation_type: str, outcome: Optional[str]) -> bool:
    """Whether an earlier violation makes a later one of the same player a repeat (PRIV-2). **A plain warning never
    does** (a fixed rule, approved with the lawyer's brief on 2026-10-30): neither a spot check the controller only
    warned about (``over_tolerance``) nor one staff resolved with the outcome ``warning``. Anything else counts."""
    return violation_type == "over_limit" and outcome != "warning"


async def _flag_repeats(db: AsyncSession, field_id: uuid.UUID, player_id: str) -> None:
    """A player's violations at the field, oldest deciding reading first: one after an earlier violation that counts
    (``counts_for_repeat``) is flagged ``repeat_offender``. A flag for a person's attention, not a verdict (the staff
    page words it that way): worked out again whenever a violation arrives or is resolved, so a late arrival of an older one puts the flags right."""
    rows = (await db.execute(
        select(ChronoViolation.id, ChronoViolation.repeat_offender, ChronoViolation.violation_type,
               ChronoViolation.outcome)
        .join(ChronoReading, ChronoReading.id == ChronoViolation.reading)
        .where(ChronoViolation.field_id == field_id, ChronoViolation.player_id == player_id)
        .order_by(ChronoReading.timestamp, ChronoReading.reading_id))).all()
    earlier = False
    for vid, flag, vtype, outcome in rows:
        if flag != earlier:
            await db.execute(update(ChronoViolation).where(ChronoViolation.id == vid).values(repeat_offender=earlier))
        earlier = earlier or counts_for_repeat(vtype, outcome)


async def refresh_player_flags(db: AsyncSession, field_id: uuid.UUID, player_id: str) -> None:
    """One player's flags again (a violation of theirs was resolved: its outcome may change who is a repeat)."""
    await _flag_repeats(db, field_id, player_id)


async def ban_expiry(db: AsyncSession, field: Field, violation: ChronoViolation, now: datetime) -> datetime:
    """When a "ban" recorded ``now`` ends (PRIV-2): the field's ban length (``chrono_ban_days``, else 12 months) from
    now, never longer than the field's chrono retention and never later than the violation's own record goes (its reading's time plus the field's chrono
    retention: the violation is deleted with it, and the ban with it)."""
    reading = await db.get(ChronoReading, violation.reading)
    days = min(field.chrono_ban_days or DEFAULT_BAN_DAYS, field.default_retention_days)
    end = now + timedelta(days=days)
    if reading is not None:
        end = min(end, reading.timestamp + timedelta(days=field.default_retention_days))
    return end


async def revoke_copies(db: AsyncSession, user_id: uuid.UUID, reason: str, *,
                        source_field: Optional[uuid.UUID] = None) -> int:
    """PRIV-5: tells the controllers of every field where the account holds a player id (but ``source_field``'s: the
    copies of a field's own records are not at that field) to drop the copies of other fields' chrono records they
    pulled for it (``chrono_copy_revocations``, carried in the schedule answer). ``erasure``: the account is erased;
    ``withdrawn``: the person withdrew ``source_field``'s chrono-sharing consent. The caller commits."""
    query = select(FieldPlayerId.field_id, FieldPlayerId.player_id).where(FieldPlayerId.user_id == user_id)
    if source_field is not None:
        query = query.where(FieldPlayerId.field_id != source_field)
    rows = [{"field_id": f, "player_id": p, "reason": reason} for f, p in (await db.execute(query)).all()]
    if not rows:
        return 0
    stmt = insert(ChronoCopyRevocation).values(rows)
    await db.execute(stmt.on_conflict_do_update(index_elements=["field_id", "player_id", "reason"],
                                                set_={"created_at": func.now()}))
    return len(rows)


async def restore_copies(db: AsyncSession, user_id: uuid.UUID) -> None:
    """The person gave a chrono-sharing consent again: the ``withdrawn`` revocations of their player ids go, so the
    copies pulled from now on are not dropped again. (Already-dropped copies stay dropped.) The caller commits."""
    mine = select(FieldPlayerId.player_id).where(FieldPlayerId.user_id == user_id,
                                                 FieldPlayerId.field_id == ChronoCopyRevocation.field_id)
    await db.execute(delete(ChronoCopyRevocation).where(ChronoCopyRevocation.reason == "withdrawn",
                                                        ChronoCopyRevocation.player_id.in_(mine))
                     .execution_options(synchronize_session=False))


async def copies_revoked(db: AsyncSession, field_id: uuid.UUID, now: datetime) -> list[dict[str, Any]]:
    """The schedule answer's ``copies_revoked`` (PRIV-5): this field's players whose pulled copies its controllers drop,
    those of the field's chrono retention period (a copy cannot outlive it on a controller), the newest
    ``sync_format.MAX_REVOKED``."""
    days = await db.scalar(select(Field.default_retention_days).where(Field.id == field_id))
    rows = await db.execute(
        select(ChronoCopyRevocation.player_id, ChronoCopyRevocation.reason, ChronoCopyRevocation.created_at)
        .where(ChronoCopyRevocation.field_id == field_id,
               ChronoCopyRevocation.created_at > now - timedelta(days=days or 365))
        .order_by(ChronoCopyRevocation.created_at.desc(), ChronoCopyRevocation.player_id)
        .limit(sync_format.MAX_REVOKED))
    return [{"player_id": p, "reason": r, "at": int(at.timestamp())} for p, r, at in rows]


# --- reading the registry ----------------------------------------------------------------

def reading_json(r: ChronoReading, key: Optional[MarshalKey] = None) -> dict[str, Any]:
    import json  # noqa: PLC0415

    out = {"id": str(r.id), "reading_id": str(r.reading_id), "record_json": r.record_json,
           "record": json.loads(r.record_json), "replica_id": str(r.replica_id), "player_id": r.player_id,
           "type": r.type, "velocity_mps": r.velocity_mps, "bb_weight_g": r.bb_weight_g, "energy_j": r.energy_j,
           "marshal_id": r.marshal_id, "timestamp": _iso(r.timestamp), "series_id": str(r.series_id),
           "outcome": r.outcome, "game": str(r.game) if r.game else None, "received_at": _iso(r.received_at),
           "verified_at": _iso(r.verified_at), "marshal_key": str(r.marshal_key)}
    if key is not None:
        out["public_key"] = base64.b64encode(bytes(key.public_key)).decode("ascii")
    return out


def key_json(k: MarshalKey) -> dict[str, Any]:
    return {"id": str(k.id), "marshal_id": k.marshal_id, "name": k.name,
            "public_key": base64.b64encode(bytes(k.public_key)).decode("ascii"),
            "fingerprint": key_fingerprint(bytes(k.public_key)), "player_id": k.player_id,
            "linked_account": k.user_id is not None, "source": k.source, "valid_from": _iso(k.valid_from),
            "valid_until": _iso(k.valid_until), "revoked_at": _iso(k.revoked_at)}


def replica_json(r: Replica) -> dict[str, Any]:
    return {"replica_id": str(r.replica_id), "owner_player_id": r.owner_player_id, "type": r.replica_type,
            "class": r.replica_class, "make_model": r.make_model, "tag_type": r.tag_type, "tag_uid": r.tag_uid,
            "registered_at": _iso(r.registered_at), "updated_at": _iso(r.updated_at)}


def violation_json(v: ChronoViolation) -> dict[str, Any]:
    return {"id": str(v.id), "series_id": str(v.series_id), "reading": str(v.reading), "player_id": v.player_id,
            "replica_id": str(v.replica_id), "violation_type": v.violation_type, "energy_j": v.energy_j,
            "limit_j": v.limit_j, "delta_j": v.delta_j, "repeat_offender": v.repeat_offender,
            "game": str(v.game) if v.game else None, "outcome": v.outcome, "resolved_at": _iso(v.resolved_at),
            "ban_expires_at": _iso(v.ban_expires_at), "ban_active": ban_active(v),
            "created_at": _iso(v.created_at)}


def ban_active(v: ChronoViolation, now: Optional[datetime] = None) -> bool:
    """A "ban" outcome that has not ended (PRIV-2): one with no recorded end (made before ``ban_expires_at`` existed and
    not given one by the migration) lasts as long as the violation does, which the chrono retention bounds."""
    if v.outcome != "ban":
        return False
    return v.ban_expires_at is None or v.ban_expires_at > (now or datetime.now(timezone.utc))


def reject_json(r: ChronoReject) -> dict[str, Any]:
    return {"id": str(r.id), "reason": r.reason, "detail": r.detail, "reading_id": r.reading_id,
            "player_id": r.player_id, "marshal_id": r.marshal_id, "record_text": r.record_text,
            "series_id": str(r.series_id) if r.series_id else None, "outcome": r.outcome, "times": r.times,
            "received_at": _iso(r.received_at), "first_seen_at": _iso(r.first_seen_at),
            "last_seen_at": _iso(r.last_seen_at)}


async def readings_with_keys(db: AsyncSession, *where: Any, limit: int = 1000) -> list[dict[str, Any]]:
    rows = await db.execute(select(ChronoReading, MarshalKey).join(MarshalKey, MarshalKey.id == ChronoReading.marshal_key)
                            .where(*where).order_by(ChronoReading.timestamp, ChronoReading.reading_id).limit(limit))
    return [reading_json(r, k) for r, k in rows]


async def linked_user(db: AsyncSession, field_id: uuid.UUID, player_id: str) -> Optional[uuid.UUID]:
    return await db.scalar(select(FieldPlayerId.user_id).where(FieldPlayerId.field_id == field_id,
                                                              FieldPlayerId.player_id == player_id))


async def sharing_fields(db: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """The fields the person consented to share chrono records with (a live consent each) that share."""
    rows = await db.scalars(select(Consent.field_id).join(Field, Field.id == Consent.field_id).where(
        Consent.user_id == user_id, Consent.purpose == SHARING, Consent.withdrawn_at.is_(None),
        sharing_terms.live_clause()))
    return {f for f in rows if f is not None}


async def shared_history(db: AsyncSession, field_id: uuid.UUID, player_id: str) -> list[dict[str, Any]]:
    """Other fields' readings of the person behind this field's player id (ADR-P4-5's sharing): only
    through an account that holds the id here, only when this field and the other share chrono
    records, and only with the person's live consent for both. Per-field ids are never matched."""
    user_id = await linked_user(db, field_id, player_id)
    if user_id is None:
        return []
    # A hosted hub's other fields (SVX-2): the hub's function answers only while both are active for the person.
    hub = await hub_share.shared_history(db, user_id)
    fields = await sharing_fields(db, user_id)
    if field_id not in fields:
        return []
    others = fields - {field_id}
    if not others:
        return hub
    links = (await db.execute(select(FieldPlayerId.field_id, FieldPlayerId.player_id, Field.name)
                              .join(Field, Field.id == FieldPlayerId.field_id)
                              .where(FieldPlayerId.user_id == user_id, FieldPlayerId.field_id.in_(others)))).all()
    out = []
    for other, pid, name in links:
        for reading in await readings_with_keys(db, ChronoReading.field_id == other, ChronoReading.player_id == pid):
            out.append({"field": name, "field_id": str(other), **reading})
    return out + hub


SHARED_PER_PLAYER = sync_format.MAX_SHARED  # the newest records of other fields one player's pull carries


async def shared_for_players(db: AsyncSession, field_id: uuid.UUID, player_ids: list[str]) -> list[dict[str, Any]]:
    """What ``GET /api/v1/sync/chrono`` answers for a roster (S14-5): per player id of this field that
    has records to show, the other fields' signed records ``shared_history`` allows (the account that
    holds the id here, both fields sharing, the person's live consent for each), the newest
    ``SHARED_PER_PLAYER`` of them, each as the text that was signed with its field's name and the marshal's
    public key. A player with nothing to show is left out."""
    if not player_ids or not await db.scalar(select(Field.id).where(Field.id == field_id, sharing_terms.live_clause())):
        return []
    linked = set(await db.scalars(select(FieldPlayerId.player_id).where(
        FieldPlayerId.field_id == field_id, FieldPlayerId.player_id.in_(player_ids),
        FieldPlayerId.user_id.is_not(None))))
    out = []
    for pid in player_ids:
        if pid not in linked:
            continue
        shared = await shared_history(db, field_id, pid)
        shared.sort(key=lambda r: (r["timestamp"] or "", r["reading_id"]))
        if shared:
            out.append({"player_id": pid, "readings": [
                {"field": r["field"], "record": r["record_json"], "public_key": r["public_key"]}
                for r in shared[-SHARED_PER_PLAYER:]]})
    return out


async def my_history(db: AsyncSession, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """The person's own chrono history: per field where the account holds a player id, its readings,
    replicas and violations."""
    links = (await db.execute(select(FieldPlayerId.field_id, FieldPlayerId.player_id, Field.name)
                              .join(Field, Field.id == FieldPlayerId.field_id)
                              .where(FieldPlayerId.user_id == user_id).order_by(Field.name))).all()
    out = []
    for field_id, pid, name in links:
        replicas = await db.scalars(select(Replica).where(Replica.field_id == field_id,
                                                          Replica.owner_player_id == pid).order_by(Replica.created_at))
        violations = await db.scalars(select(ChronoViolation).where(
            ChronoViolation.field_id == field_id, ChronoViolation.player_id == pid).order_by(ChronoViolation.created_at))
        rejects = await db.scalars(select(ChronoReject).where(
            ChronoReject.field_id == field_id, ChronoReject.player_id == pid).order_by(ChronoReject.first_seen_at))
        out.append({"field_id": str(field_id), "field": name, "player_id": pid,
                    "readings": await readings_with_keys(db, ChronoReading.field_id == field_id,
                                                         ChronoReading.player_id == pid, limit=100_000),
                    "replicas": [replica_json(r) for r in replicas],
                    "violations": [violation_json(v) for v in violations],
                    "refused_readings": [{k: v for k, v in reject_json(r).items() if k != "record_text"}
                                         for r in rejects]})
    return out


def owned_by(user_id: uuid.UUID, player_column: Any, field_column: Any) -> Any:
    """``player_column`` at ``field_column`` is one of the account's player ids (an EXISTS clause)."""
    return select(FieldPlayerId.id).where(and_(FieldPlayerId.user_id == user_id,
                                               FieldPlayerId.field_id == field_column,
                                               FieldPlayerId.player_id == player_column)).exists()


async def erase_player(db: AsyncSession, field_id: uuid.UUID, player_id: str) -> dict[str, int]:
    """Everything of one player id at a field (their readings with their violations, the refused
    readings naming them, their replicas): a field's erasure, not an account's (an account's keeps
    the signed records and drops the link, ``personal_data.erase``). The caller commits."""
    await hub_share.forget_player(db, field_id, player_id)  # a hosted hub's shared copies (SVX-2)
    holder = await linked_user(db, field_id, player_id)
    if holder is not None:  # PRIV-5: the copies of this field's records of them, at the other fields' controllers
        await revoke_copies(db, holder, "erasure", source_field=field_id)
    readings = await db.execute(delete(ChronoReading).where(ChronoReading.field_id == field_id,
                                                            ChronoReading.player_id == player_id))
    rejects = await db.execute(delete(ChronoReject).where(ChronoReject.field_id == field_id,
                                                          ChronoReject.player_id == player_id))
    replicas = await db.execute(delete(Replica).where(Replica.field_id == field_id,
                                                      Replica.owner_player_id == player_id))
    return {"chrono_readings": readings.rowcount or 0, "chrono_rejects": rejects.rowcount or 0,
            "replicas": replicas.rowcount or 0}


async def erase_identity(db: AsyncSession, field_id: uuid.UUID, player_id: str) -> dict[str, int]:
    """What links an account to one player id at a field: the link itself (``field_player_ids``, the only way the
    game history's events name a person) and the claims of that id. The signed records are a chrono erasure's
    (``erase_player``). The caller commits."""
    links = await db.execute(delete(FieldPlayerId).where(FieldPlayerId.field_id == field_id,
                                                         FieldPlayerId.player_id == player_id))
    claims = await db.execute(delete(PlayerIdClaim).where(PlayerIdClaim.field_id == field_id,
                                                          PlayerIdClaim.player_id == player_id))
    return {"identities": links.rowcount or 0, "claims": claims.rowcount or 0}


async def apply_erasures(db: AsyncSession, field_id: uuid.UUID, body: dict[str, Any]) -> dict[str, int]:
    """``POST /api/v1/sync/erasures`` (decision RET-4, S14-10): the players whose data the field's controller erased
    on request. ``chrono`` erases their readings, refused readings and replicas here (``erase_player``);
    ``identity`` the links of the player id to an account (``erase_identity``). Idempotent: a player the server
    has nothing of counts nothing, so a controller that sends again after a lost answer does no harm. The log
    keeps how much, never whose."""
    totals = {"players": 0, "chrono_readings": 0, "chrono_rejects": 0, "replicas": 0, "identities": 0, "claims": 0}
    for entry in body["erasures"]:
        totals["players"] += 1
        counts: dict[str, int] = {}
        if entry["chrono"]:
            counts.update(await erase_player(db, field_id, entry["player_id"]))
        if entry["identity"]:
            counts.update(await erase_identity(db, field_id, entry["player_id"]))
        for key, n in counts.items():
            totals[key] += n
    record(db, "chrono_player_erasure", resource="field", resource_id=field_id, details={**totals, "by": "controller"})
    return totals
