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

Scenarios and presets have their own fixed caps (``services/library.py``). Past a limit the request is
refused with **409** and ``{"detail": "quota_exceeded", "quota": NAME, "limit": N}`` (the sync answers the same
body; a stream is closed with 4429 before it is accepted); what exists is never deleted, and the retention purge
(ADR-P4-8) makes room again. Single-field mode has no quotas: the limits are read from a context variable the
tenant middleware sets, so nothing else needs to know the mode. Counts are taken just before the insert in the
request's own transaction; two requests racing at the limit may both pass (the limit is a guard against
runaway growth, not a billing meter).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .atak_models import AtakCert
from .models import Game, GameRegistration, ScheduledGame, User

CODE = "quota_exceeded"
STREAM_CLOSE = 4429

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


__all__ = ["CODE", "STREAM_CLOSE", "QuotaExceeded", "check", "limit", "room", "streams_full", "use"]
