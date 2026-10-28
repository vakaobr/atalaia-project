# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chrono registry's views for a field's staff (ADR-P4-5 as amended; plan phase 14).

    GET    /api/v1/fields/{field}/chrono/readings?player_id=&replica_id=&series_id=&marshal_id=&after=&limit=
                                                      admin, gm, marshal: the signed readings, each with its
                                                      record as received and the key that verified it
    GET    /api/v1/fields/{field}/chrono/rejects     admin, gm: readings that did not verify, with the reason
    GET    /api/v1/fields/{field}/chrono/violations?open=
                                                      admin, gm, marshal: failed and warned spot checks
    PATCH  /api/v1/fields/{field}/chrono/violations/{id}  admin, gm: {outcome: warning|pulled|ban}
    GET    /api/v1/fields/{field}/chrono/players/{player_id}
                                                      admin, gm, marshal: one player's readings here, and
                                                      (``shared``) other fields' with the person's consent
    DELETE /api/v1/fields/{field}/chrono/players/{player_id}
                                                      admin: erase that player's chrono data here (readings,
                                                      refused readings, violations, replicas), as the
                                                      controller's DELETE /api/v1/players/{player}/chrono does
    GET    /api/v1/fields/{field}/replicas?owner_player_id=   admin, gm, marshal: the replica registry
    GET    /api/v1/fields/{field}/marshal-keys        admin, gm, marshal: every key with its period
    POST   /api/v1/fields/{field}/marshal-keys        a marshal: {marshal_id, name, public_key}, the key made on
                                                      their phone, linked to their account
    DELETE /api/v1/fields/{field}/marshal-keys/{key}  admin: revoked as compromised (the row stays)

All of these need a role on the field in a TOTP session (admin, gm and marshal are TOTP roles). A
per-game role does not open the field's registry. The site server never holds a marshal's private key
(P4R14): a key comes from the controller (``POST /api/v1/sync/marshals``) or from the marshal's own
account here; a lost phone means a new key, and the old one keeps its period so its records still
verify. Revoking a key (a stolen phone) refuses what reaches the server signed with it afterwards;
what was stored before stays, as it was verified then.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime, timezone
from typing import Optional

from atalaia_controller import chrono
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field as PydanticField
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import chrono_registry
from ..audit import record
from ..auth import Principal, current_principal, require_field_role
from ..db import get_session
from ..models import VIOLATION_OUTCOMES, ChronoReading, ChronoReject, ChronoViolation, Field, MarshalKey, Replica

router = APIRouter(prefix="/api/v1/fields/{field_id}", tags=["chrono"])
NO_STORE = {"Cache-Control": "no-store"}
STAFF = ("admin", "gm", "marshal")


class MarshalKeyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    marshal_id: str = PydanticField(max_length=64)
    name: str = PydanticField(max_length=64)
    public_key: str = PydanticField(max_length=88)


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str = PydanticField(max_length=16)


async def _field(db: AsyncSession, field_id: uuid.UUID) -> Field:
    field = await db.get(Field, field_id)
    if field is None:
        raise HTTPException(404, "field_not_found")
    return field


@router.get("/chrono/readings")
async def readings(field_id: uuid.UUID, player_id: Optional[str] = Query(None, max_length=64),
                   replica_id: Optional[uuid.UUID] = None, series_id: Optional[uuid.UUID] = None,
                   marshal_id: Optional[str] = Query(None, max_length=64), after: Optional[uuid.UUID] = None,
                   limit: int = Query(500, ge=1, le=1000), principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    await _field(db, field_id)
    query = (select(ChronoReading, MarshalKey).join(MarshalKey, MarshalKey.id == ChronoReading.marshal_key)
             .where(ChronoReading.field_id == field_id))
    for column, value in ((ChronoReading.player_id, player_id), (ChronoReading.replica_id, replica_id),
                          (ChronoReading.series_id, series_id), (ChronoReading.marshal_id, marshal_id)):
        if value is not None:
            query = query.where(column == value)
    if after is not None:
        query = query.where(ChronoReading.id > after)
    rows = (await db.execute(query.order_by(ChronoReading.id).limit(limit))).all()
    out = [chrono_registry.reading_json(r, k) for r, k in rows]
    return JSONResponse({"readings": out, "next": out[-1]["id"] if len(out) == limit else None}, headers=NO_STORE)


@router.get("/chrono/rejects")
async def rejects(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                  db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    await _field(db, field_id)
    rows = await db.scalars(select(ChronoReject).where(ChronoReject.field_id == field_id)
                            .order_by(ChronoReject.last_seen_at.desc()).limit(1000))
    return JSONResponse([chrono_registry.reject_json(r) for r in rows], headers=NO_STORE)


@router.get("/chrono/violations")
async def violations(field_id: uuid.UUID, open_only: bool = Query(False, alias="open"),
                     principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    await _field(db, field_id)
    query = select(ChronoViolation).where(ChronoViolation.field_id == field_id)
    if open_only:
        query = query.where(ChronoViolation.resolved_at.is_(None))
    rows = await db.scalars(query.order_by(ChronoViolation.created_at.desc()).limit(1000))
    return JSONResponse([chrono_registry.violation_json(v) for v in rows], headers=NO_STORE)


@router.patch("/chrono/violations/{violation_id}")
async def resolve(field_id: uuid.UUID, violation_id: uuid.UUID, body: ResolveIn, request: Request,
                  principal: Principal = Depends(current_principal),
                  db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, "admin", "gm")
    if body.outcome not in VIOLATION_OUTCOMES:
        raise HTTPException(400, "outcome_invalid")
    v = await db.get(ChronoViolation, violation_id)
    if v is None or v.field_id != field_id:
        raise HTTPException(404, "violation_not_found")
    v.outcome = body.outcome
    v.resolved_by = principal.user.id
    v.resolved_at = datetime.now(timezone.utc)
    record(db, "chrono_violation_resolve", request, user_id=principal.user.id, resource="field",
           resource_id=field_id, details={"violation": str(v.id), "outcome": body.outcome})
    await db.commit()
    await db.refresh(v)
    return JSONResponse(chrono_registry.violation_json(v), headers=NO_STORE)


@router.get("/chrono/players/{player_id}")
async def player(field_id: uuid.UUID, player_id: str, request: Request,
                 principal: Principal = Depends(current_principal),
                 db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    await _field(db, field_id)
    if not chrono.ID_RE.fullmatch(player_id):
        raise HTTPException(400, "player_id_invalid")
    here = await chrono_registry.readings_with_keys(db, ChronoReading.field_id == field_id,
                                                    ChronoReading.player_id == player_id)
    shared = await chrono_registry.shared_history(db, field_id, player_id)
    if shared:
        # Who looked, at which field, how much: not the player (the log outlives the records).
        record(db, "chrono_shared_lookup", request, user_id=principal.user.id, resource="field",
               resource_id=field_id, details={"readings": len(shared)})
        await db.commit()
    return JSONResponse({"player_id": player_id, "readings": here, "shared": shared}, headers=NO_STORE)


@router.delete("/chrono/players/{player_id}")
async def erase_player(field_id: uuid.UUID, player_id: str, request: Request,
                       principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A player's erasure request at the field (ADR-P3-7): the field's copy here goes too. A controller's own
    erasure reaches the site server by itself (``POST /api/v1/sync/erasures``, decision RET-4); this is for a
    request made to the field's admin here."""
    require_field_role(principal, field_id, "admin")
    await _field(db, field_id)
    if not chrono.ID_RE.fullmatch(player_id):
        raise HTTPException(400, "player_id_invalid")
    counts = await chrono_registry.erase_player(db, field_id, player_id)
    # The log keeps that it happened and how much, not whose (the player id is gone with the data).
    record(db, "chrono_player_erasure", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details=counts)
    await db.commit()
    return JSONResponse(counts, headers=NO_STORE)


@router.get("/replicas")
async def replicas(field_id: uuid.UUID, owner_player_id: Optional[str] = Query(None, max_length=64),
                   principal: Principal = Depends(current_principal),
                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    await _field(db, field_id)
    query = select(Replica).where(Replica.field_id == field_id)
    if owner_player_id is not None:
        query = query.where(Replica.owner_player_id == owner_player_id)
    rows = await db.scalars(query.order_by(Replica.created_at).limit(5000))
    return JSONResponse([chrono_registry.replica_json(r) for r in rows], headers=NO_STORE)


@router.get("/marshal-keys")
async def marshal_keys(field_id: uuid.UUID, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    require_field_role(principal, field_id, *STAFF)
    await _field(db, field_id)
    rows = await db.scalars(select(MarshalKey).where(MarshalKey.field_id == field_id)
                            .order_by(MarshalKey.marshal_id, MarshalKey.valid_from))
    return JSONResponse([chrono_registry.key_json(k) for k in rows], headers=NO_STORE)


def _public_key(value: str) -> bytes:
    """32 bytes in standard base64 (as the controller's PUT /api/v1/checkin/me/marshal-key takes it), a real
    Ed25519 public key."""
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError):
        raise HTTPException(400, "public_key_invalid") from None
    if len(raw) != 32:
        raise HTTPException(400, "public_key_invalid")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: PLC0415

    try:
        Ed25519PublicKey.from_public_bytes(raw)
    except ValueError:
        raise HTTPException(400, "public_key_invalid") from None
    return raw


@router.post("/marshal-keys", status_code=201)
async def register_key(field_id: uuid.UUID, body: MarshalKeyIn, request: Request,
                       principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A marshal registers the public key their phone made; it is linked to their account. The same key
    already sent by the field's controller is claimed; a marshal id another account holds is refused."""
    require_field_role(principal, field_id, "marshal")
    await _field(db, field_id)
    if not chrono.ID_RE.fullmatch(body.marshal_id):
        raise HTTPException(400, "marshal_id_invalid")
    name = body.name.strip()
    if not 1 <= len(name) <= chrono.NAME_MAX or not chrono._text_ok(name):
        raise HTTPException(400, "name_invalid")
    raw = _public_key(body.public_key)
    await db.execute(select(Field.id).where(Field.id == field_id).with_for_update())
    keys = (await db.scalars(select(MarshalKey).where(MarshalKey.field_id == field_id,
                                                      MarshalKey.marshal_id == body.marshal_id))).all()
    if any(k.user_id is not None and k.user_id != principal.user.id for k in keys):
        raise HTTPException(409, "marshal_id_taken")
    now = datetime.now(timezone.utc)
    same = next((k for k in keys if bytes(k.public_key) == raw), None)
    if same is not None and same.revoked_at is not None:
        raise HTTPException(409, "key_revoked")
    created = same is None
    if same is None:
        # A new key: this account's earlier current keys for the id end now (a rotation).
        for k in keys:
            if k.valid_until is None and k.revoked_at is None:
                k.valid_until = now
        same = MarshalKey(field_id=field_id, marshal_id=body.marshal_id, name=name, public_key=raw,
                          user_id=principal.user.id, source="account", valid_from=now)
        db.add(same)
    else:
        same.user_id = principal.user.id
        same.name = name
    await db.flush()
    record(db, "marshal_key_register", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"marshal_id": body.marshal_id, "key": str(same.id),
                    "fingerprint": chrono_registry.key_fingerprint(raw), "claimed": not created})
    await db.commit()
    await db.refresh(same)
    return JSONResponse(chrono_registry.key_json(same), status_code=201 if created else 200, headers=NO_STORE)


@router.delete("/marshal-keys/{key_id}", status_code=204)
async def revoke_key(field_id: uuid.UUID, key_id: uuid.UUID, request: Request,
                     principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> Response:
    require_field_role(principal, field_id, "admin")
    key = await db.get(MarshalKey, key_id)
    if key is None or key.field_id != field_id or key.revoked_at is not None:
        raise HTTPException(404, "key_not_found")
    key.revoked_at = datetime.now(timezone.utc)
    key.revoked_by = principal.user.id
    record(db, "marshal_key_revoke", request, user_id=principal.user.id, resource="field", resource_id=field_id,
           details={"marshal_id": key.marshal_id, "key": str(key.id),
                    "fingerprint": chrono_registry.key_fingerprint(bytes(key.public_key))})
    await db.commit()
    return Response(status_code=204)
