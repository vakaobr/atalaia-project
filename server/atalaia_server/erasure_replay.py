# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Erases again, after a restore, what the erasure ledger says was erased (PRIV-4; ``erasure_ledger.py``).

``python -m atalaia_server erasure-ledger apply`` (``restore.sh`` runs it once the restored server is healthy): reads the
ledger, and for each field's database (every active field of a hosted hub, one by one under its own role; the one
database of a single-field server) erases again the accounts and the players' records whose hash is in it, with the code
of the person's own erasure (``personal_data.erase``, ``chrono_registry.erase_player`` and ``erase_identity``). An entry
whose account or player the restored database does not hold (it was made after the entry, or the retention purge removed
the row) does nothing; running it again does nothing. Accounts are matched by hashing the ids of the accounts that are not
anonymised yet, players by hashing the ids the field holds in its chrono tables, claims and links: nothing is looked up by
a name, and the ledger by itself leads to no row.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional, TextIO

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import chrono_registry, erasure_ledger, personal_data, tenancy
from .audit import record
from .config import Settings
from .db import make_engine, make_sessionmaker
from .models import ChronoReading, ChronoReject, Field, FieldPlayerId, PlayerIdClaim, Replica, User

REASON = "restore_replay"


async def _player_ids(db: AsyncSession, field_id: uuid.UUID) -> set[str]:
    """Every player id the restored database holds for the field, in any table an erasure reaches."""
    found: set[str] = set()
    for column, where in ((ChronoReading.player_id, ChronoReading.field_id), (ChronoReject.player_id, ChronoReject.field_id),
                          (Replica.owner_player_id, Replica.field_id), (FieldPlayerId.player_id, FieldPlayerId.field_id),
                          (PlayerIdClaim.player_id, PlayerIdClaim.field_id)):
        found.update(p for p in await db.scalars(select(column).where(where == field_id).distinct()) if p)
    return found


async def apply_entries(db: AsyncSession, entries: list[dict[str, Any]]) -> dict[str, int]:
    """The entries of one database, applied in the caller's transaction (the caller commits); returns what was done."""
    done = {"accounts": 0, "players": 0, "chrono_readings": 0, "chrono_rejects": 0, "replicas": 0, "identities": 0,
            "claims": 0}
    accounts = {e["hash"] for e in entries if e["kind"] == "account"}
    if accounts:
        for user_id in list(await db.scalars(select(User.id).where(~User.username.startswith(personal_data.ERASED_PREFIX,
                                                                                            autoescape=True)))):
            if erasure_ledger.hash_account(user_id) in accounts:
                await personal_data.erase(db, user_id, reason=REASON)
                done["accounts"] += 1
    by_field: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        if e["kind"] == "player":
            by_field.setdefault(e["field"], []).append(e)
    known = set(map(str, await db.scalars(select(Field.id)))) if by_field else set()
    for field_text, wanted in by_field.items():
        if field_text not in known:
            continue
        field_id = uuid.UUID(field_text)
        for pid in sorted(await _player_ids(db, field_id)):
            digest = erasure_ledger.hash_player(field_id, pid)
            hit = [e for e in wanted if e["hash"] == digest]
            if not hit:
                continue
            counts: dict[str, int] = {}
            if any(e["chrono"] for e in hit):
                counts.update(await chrono_registry.erase_player(db, field_id, pid))
            if any(e["identity"] for e in hit):
                counts.update(await chrono_registry.erase_identity(db, field_id, pid))
            done["players"] += 1
            for key, n in counts.items():
                done[key] += n
    if done["players"]:
        record(db, "chrono_player_erasure", resource="field", details={**done, "by": REASON})
    return done


async def apply_ledger(settings: Settings, out: TextIO, path: Optional[str] = None) -> dict[str, int]:
    """Every database the settings reach (a hub's active fields, or the one), each in its own transaction."""
    path = path or settings.erasure_ledger
    if not path:
        raise ValueError("ATALAIA_ERASURE_LEDGER is not set: there is no ledger to apply")
    entries, bad = erasure_ledger.read(path)
    print(f"Erasure ledger {path}: {len(entries)} entries" + (f", {bad} line(s) not valid left out" if bad else ""),
          file=out)
    total: dict[str, int] = {}
    engine = make_engine(settings)
    try:
        maker = make_sessionmaker(engine, hosted=settings.hosted)
        tenants: list[Optional[tenancy.Tenant]] = (list(await tenancy.active_tenants(engine)) if settings.hosted
                                                   else [None])
        for tenant in tenants:
            slug = tenant.slug if tenant is not None else None
            mine = [e for e in entries if e.get("tenant") == slug]
            if not mine:
                continue
            with tenancy.use(tenant):
                async with maker() as db:
                    done = await apply_entries(db, mine)
                    await db.commit()
            where = f" ({slug})" if slug else ""
            print(f"Erased again{where}: " + ", ".join(f"{n} {what.replace('_', ' ')}" for what, n in done.items() if n)
                  if any(done.values()) else f"Nothing to erase again{where}", file=out)
            for what, n in done.items():
                total[what] = total.get(what, 0) + n
    finally:
        await engine.dispose()
    return total
