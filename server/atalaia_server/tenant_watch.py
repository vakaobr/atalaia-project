# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Closing the open sockets of a field that was deleted or suspended, at once (S21-12; hosted mode only).

The operator's ``hosted delete`` and ``hosted suspend`` run in another process (the ``hub`` container, with the
owner role) and cannot reach the server's memory. The server therefore looks at the registry
(``public.atalaia_tenants``, which its role may read) every ``ATALAIA_HOSTED_WATCH_S`` seconds (2 by default) while
any socket or link is open, and closes what belongs to a field that is no longer there:

- a field **deleted** (no registry row, or a row with another field id: the slug was made again): its controllers'
  ``/api/v1/sync/stream`` sockets close with 4404, its remote-GM links are dropped (a command waiting for an
  answer fails ``controller_offline``) and its remote ATAK relay connections close;
- a field **suspended**: the same, with 4403 (a suspended field serves nothing, so nothing stays open on it).

A socket that is not watched (a request that ended) costs nothing; with nothing open the registry is not read.
The sweep's cost is one query on a table of at most about a thousand rows. A socket also still fails at its next
message for any other reason (a revoked key, a dropped schema), so this only makes the end prompt: a deleted
field's controller sees its stream close within the interval instead of at its next message.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from . import tenancy

log = logging.getLogger("atalaia.server.watch")

CLOSE_SUSPENDED = 4403
CLOSE_GONE = 4404

_REGISTRY = text("SELECT schema_name, field_id, status FROM public.atalaia_tenants")


@dataclass(eq=False)
class Watched:
    """One open socket of a tenant's field."""

    schema: str
    field_id: uuid.UUID
    close: Callable[[int], Awaitable[None]]     # closes the socket with this code and wakes its handler
    closed: bool = False


@dataclass
class TenantWatch:
    """The open sockets of hosted mode, and the sweep that closes those of a field that is gone."""

    sockets: set[Watched] = field(default_factory=set)
    sweeps: int = 0

    def add(self, tenant: tenancy.Tenant, field_id: uuid.UUID, close: Callable[[int], Awaitable[None]]) -> Watched:
        item = Watched(tenant.schema, field_id, close)
        self.sockets.add(item)
        return item

    def remove(self, item: Watched) -> None:
        self.sockets.discard(item)

    def count(self, schema: Optional[str], field_id: uuid.UUID) -> int:
        """Open sockets of one field (for the stream quota)."""
        return sum(1 for s in self.sockets if s.schema == schema and s.field_id == field_id and not s.closed)

    async def sweep(self, engine: AsyncEngine, hub: Any = None, relay: Any = None) -> int:
        """One look at the registry; returns how many sockets, links and relay connections were closed."""
        schemas = {s.schema for s in self.sockets}
        if hub is not None:
            schemas |= hub.tenants()
        if relay is not None:
            schemas |= relay.tenants()
        if not schemas:
            return 0
        async with engine.connect() as conn:
            rows = (await conn.execute(_REGISTRY)).all()
        registry = {r[0]: (r[1], r[2]) for r in rows}
        closed = 0
        for schema in schemas:
            entry = registry.get(schema)
            if entry is None:
                code, keep = CLOSE_GONE, None
            elif entry[1] != "active":
                code, keep = CLOSE_SUSPENDED, None
            else:
                code, keep = CLOSE_GONE, entry[0]  # active: only what belongs to another field id (slug made again)
            for item in list(self.sockets):
                if item.schema == schema and not item.closed and (keep is None or item.field_id != keep):
                    item.closed = True
                    closed += 1
                    with contextlib.suppress(Exception):
                        await item.close(code)
            if hub is not None:
                closed += hub.drop_tenant(schema, keep)
            if relay is not None:
                closed += relay.drop_tenant(schema, keep)
        self.sweeps += 1
        return closed

    async def run(self, engine: AsyncEngine, interval_s: float, hub: Any = None, get_relay: Any = None) -> None:
        """The background task: sweep every ``interval_s`` until cancelled; a failed look is logged and tried again."""
        while True:
            await asyncio.sleep(interval_s)
            try:
                n = await self.sweep(engine, hub, get_relay() if get_relay else None)
                if n:
                    log.info("closed %d socket(s) or link(s) of fields that were deleted or suspended", n)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001  (the database was away: the next sweep looks again)
                log.warning("tenant watch: could not read the registry", exc_info=True)
