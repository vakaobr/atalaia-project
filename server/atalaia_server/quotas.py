# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-field quotas in hosted mode (S21-12's "per-field quotas"; decisions in docs/review/decisions-to-review.md, Q-rows).

One field of a hosted hub must not be able to fill the database for the others, by a mistake of its own
(an import loop, a controller that makes a game per second) or on purpose. Each resource has a limit per
field, from ``config.QUOTA_DEFAULTS`` or ``ATALAIA_QUOTA_<NAME>`` (a number, or ``off`` for none):

| Name | What it counts | Where it is checked |
| --- | --- | --- |
| ``accounts`` | the field's user accounts | ``POST /api/v1/auth/register`` |
| ``scheduled_games`` | the schedule, any status | ``POST /api/v1/fields/{id}/scheduled-games`` |
| ``registrations`` | game registrations, imported ones too | a player's registration; the import refuses the rows past it |
| ``games`` | games synced from controllers | the sync (a new game only; an update of a stored one never counts) |
| ``atak_certs`` | live ATAK certificates (not revoked, not expired) | enrolment |
| ``streams`` | open WebSocket streams of the field's controllers | ``WS /api/v1/sync/stream``, closed 4429 |
| ``stored_mb`` | what the field's schema takes in the database, in MiB (tables, indexes, TOAST) | the sync, an image, a scenario, a registration import |

The limits are the hub's (``ATALAIA_QUOTA_<NAME>``) with the operator's own for one field over them (``hosted quota``,
kept in the registry; decision PKC-5). The stored bytes are read from the catalogue (``pg_total_relation_size`` over
the field's schema) at most once every ``STORED_CACHE_S`` seconds, so a field can pass its limit by what one burst
adds; a request that adds a known number of bytes (an image) counts them. When a field is refused, ``report`` leaves a
note for the hub operator in the registry's inbox (``public.atalaia_quota_hits``, which the server may only add to),
at most one per field and quota every ``REPORT_EVERY_S`` seconds; ``hosted quota-hits`` moves them into the hub's
audit log and shows them (``hosted list`` and ``hosted check`` say how many wait).

Scenarios and presets have their own fixed caps (``services/library.py``). Past a limit the request is
refused with **409** and ``{"detail": "quota_exceeded", "quota": NAME, "limit": N}`` (the sync answers the same
body; a stream is closed with 4429 before it is accepted); what exists is never deleted, and the retention purge
(ADR-P4-8) makes room again. Single-field mode has no quotas: the limits are read from a context variable the
tenant middleware sets, so nothing else needs to know the mode. Counts are taken just before the insert in the
request's own transaction; two requests racing at the limit may both pass (the limit is a guard against
runaway growth, not a billing meter).
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from . import tenancy
from .atak_models import AtakCert
from .config import QUOTA_DEFAULTS
from .models import Game, GameRegistration, ScheduledGame, User

CODE = "quota_exceeded"
STREAM_CLOSE = 4429
MIB = 1024 * 1024
STORED_CACHE_S = 30.0
REPORT_EVERY_S = 600.0
log = logging.getLogger("atalaia.quotas")

QUOTA_NAMES = tuple(QUOTA_DEFAULTS)

_limits: ContextVar[Optional[Mapping[str, int]]] = ContextVar("atalaia_quotas", default=None)


class QuotaExceeded(HTTPException):
    """409 ``quota_exceeded``; the app's handler adds ``quota`` and ``limit`` to the body."""

    def __init__(self, name: str, limit: int) -> None:
        super().__init__(409, CODE)
        self.name = name
        self.limit = limit

    def body(self) -> dict[str, Any]:
        return {"detail": CODE, "quota": self.name, "limit": self.limit}


@contextmanager
def use(limits: Optional[Mapping[str, int]]) -> Iterator[None]:
    """Enforce ``limits`` (a name -> number map, 0 for none) inside the block; None: no quotas."""
    token = _limits.set(limits)
    try:
        yield
    finally:
        _limits.reset(token)


def limit(name: str) -> int:
    """The current limit of a quota; 0 when there is none (single-field mode, or ``off``)."""
    limits = _limits.get()
    return int(limits.get(name, 0)) if limits else 0


async def _count(db: AsyncSession, name: str, field_id: Optional[uuid.UUID]) -> int:
    if name == "accounts":
        # A tenant's accounts are all its own; a single-field server has no quotas, so the count is the schema's.
        q = select(func.count()).select_from(User)
    elif name == "scheduled_games":
        q = select(func.count()).select_from(ScheduledGame).where(ScheduledGame.field_id == field_id)
    elif name == "registrations":
        q = select(func.count()).select_from(GameRegistration).where(GameRegistration.field_id == field_id)
    elif name == "games":
        q = select(func.count()).select_from(Game).where(Game.field_id == field_id)
    elif name == "atak_certs":
        q = select(func.count()).select_from(AtakCert).where(
            AtakCert.field_id == field_id, AtakCert.revoked_at.is_(None),
            AtakCert.not_after > datetime.now(timezone.utc))
    else:
        raise KeyError(name)
    return int(await db.scalar(q) or 0)


_stored: dict[str, tuple[float, int]] = {}      # schema -> (when read, bytes)
_reported: dict[tuple[str, str], float] = {}    # (schema, quota) -> when it was last reported
_SIZE = text("SELECT coalesce(sum(pg_total_relation_size(c.oid)), 0) FROM pg_class c "
             "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = :schema AND c.relkind IN ('r', 'm', 't')")


async def stored_bytes(db: AsyncSession, fresh: bool = False) -> Optional[int]:
    """What the tenant's schema takes (None in single-field mode: the schema is the whole database's); cached."""
    schema = tenancy.current_schema()
    if schema is None:
        return None
    now = time.monotonic()
    cached = _stored.get(schema)
    if cached is not None and not fresh and now - cached[0] < STORED_CACHE_S:
        return cached[1]
    size = int(await db.scalar(_SIZE, {"schema": schema}) or 0)
    _stored[schema] = (now, size)
    return size


async def check_stored(db: AsyncSession, adding: int = 0) -> None:
    """Raises ``QuotaExceeded`` for ``stored_mb`` when the field's data already take its limit, or would with
    ``adding`` more bytes."""
    cap = limit("stored_mb")
    if not cap:
        return
    used = await stored_bytes(db)
    if used is not None and used + adding > cap * MIB:
        raise QuotaExceeded("stored_mb", cap)


async def usage(db: AsyncSession, field_id: uuid.UUID, open_streams: Optional[int]) -> list[dict[str, Any]]:
    """Every quota with what the field uses and its limit (None for no limit), for the field's administrator."""
    out = []
    for name in QUOTA_NAMES:
        if name == "streams":
            used: Optional[int] = open_streams
        elif name == "stored_mb":
            size = await stored_bytes(db, fresh=True)
            used = None if size is None else -(-size // MIB)
        else:
            used = await _count(db, name, field_id)
        out.append({"name": name, "used": used, "limit": limit(name) or None})
    return out


async def report(state: Any, name: str, cap: int) -> None:
    """Tells the hub operator that this field was refused for ``name`` (see the module's note); never raises."""
    tenant = tenancy.current()
    if tenant is None:
        return
    key, now = (tenant.schema, name), time.monotonic()
    last = _reported.get(key)
    if last is not None and now - last < REPORT_EVERY_S:
        return
    _reported[key] = now
    try:
        async with state.engine.begin() as conn:
            await conn.execute(text("INSERT INTO public.atalaia_quota_hits (slug, quota, limit_value) "
                                    "VALUES (:slug, :quota, :cap)"), {"slug": tenant.slug, "quota": name, "cap": cap})
    except Exception:  # noqa: BLE001  (a note that cannot be left never turns a refusal into a failure)
        log.warning("quota hit of %s (%s) could not be recorded", tenant.slug, name)


async def room(db: AsyncSession, name: str, field_id: Optional[uuid.UUID]) -> Optional[int]:
    """How many more of ``name`` the field may have (0 when full); None when there is no limit."""
    cap = limit(name)
    if not cap:
        return None
    return max(0, cap - await _count(db, name, field_id))


async def check(db: AsyncSession, name: str, field_id: Optional[uuid.UUID], adding: int = 1) -> None:
    """Raises ``QuotaExceeded`` when ``adding`` more of ``name`` would pass the field's limit."""
    free = await room(db, name, field_id)
    if free is not None and free < adding:
        raise QuotaExceeded(name, limit(name))


def streams_full(open_streams: int) -> bool:
    """True when a field already has as many open streams as its limit allows."""
    cap = limit("streams")
    return bool(cap) and open_streams >= cap


__all__ = ["CODE", "QUOTA_NAMES", "STREAM_CLOSE", "QuotaExceeded", "check", "check_stored", "limit", "report", "room",
           "streams_full", "usage", "use"]
