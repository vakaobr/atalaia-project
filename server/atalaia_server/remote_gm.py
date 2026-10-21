# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote GM relay (plan phase 19; ADR-P4-3's amendment, P4R12; decisions S19-*).

A field controller with ``[sync] remote_gm = true`` keeps ``WS
/api/v1/sync/stream`` open (it opened it, with the field's API key; the site
server never connects to a controller and holds none of its tokens). On it the
controller says ``hello`` (whether it takes remote commands), sends ``live``
(its live game as its console sees it) and answers commands with
``command.result``. This module keeps, in memory, one ``Link`` per connected
controller: its last live view and the commands waiting for their answers.
``api/remote_gm.py`` lets a user with the ``gm`` role on the field (in a TOTP
session) read the live views and send a command, from the list in
``sync_format.REMOTE_COMMANDS``, to one controller; the answer comes back on
the same socket, or the request ends after ``timeout_s`` (10 s) with
``controller_timeout``.

Nothing here is stored: live views stay in memory (they hold no position:
``sync_format.check_live`` refuses one) and the commands are in the audit log.
The links live in the server's one worker process (ADR-P4-2; decision S19-4):
a server with several workers would need a shared channel, which the
deployment (plan phase 22) does not have. In hosted mode (plan phase 21) a link
belongs to the tenant whose address the controller connected to, and only that
tenant's requests see it.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from . import tenancy

COMMAND_TIMEOUT_S = 10.0


class RemoteProblem(Exception):
    """A command that cannot be sent: HTTP status and ``detail`` code."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass
class Link:
    """One controller's open stream."""

    field_id: uuid.UUID
    key_id: uuid.UUID
    controller_id: str                       # the controller's own id (protocol/sync.md)
    controller_row: Optional[uuid.UUID]      # the site server's ``controllers`` row
    version: str
    remote_gm: bool
    send: Callable[[dict[str, Any]], Awaitable[None]]
    atak: bool = False                       # it pushes CoT for the remote ATAK relay (FU5) and the relay is on
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    live: Optional[dict[str, Any]] = None
    live_at: Optional[datetime] = None
    pending: dict[str, "asyncio.Future[dict[str, Any]]"] = field(default_factory=dict)
    tenant: Optional[str] = field(default_factory=tenancy.current_schema)  # hosted mode's schema, else None

    @property
    def key(self) -> tuple[Optional[str], uuid.UUID, str]:
        return (self.tenant, self.field_id, self.controller_id)

    def json(self) -> dict[str, Any]:
        return {"controller_id": self.controller_id, "controller": str(self.controller_row) if self.controller_row
                else None, "version": self.version, "remote_gm": self.remote_gm,
                "atak": self.atak, "connected_at": self.connected_at.isoformat(),
                "live_at": self.live_at.isoformat() if self.live_at else None, "live": self.live}


class RemoteHub:
    """The open links, by (tenant, field, controller id); one per controller (a new socket replaces the old).
    Every lookup is in the current tenant (``tenancy.current_schema()``; None in single-field mode)."""

    def __init__(self, timeout_s: float = COMMAND_TIMEOUT_S) -> None:
        self.timeout_s = timeout_s
        self._links: dict[tuple[Optional[str], uuid.UUID, str], Link] = {}

    def attach(self, link: Link) -> None:
        old = self._links.get(link.key)
        self._links[link.key] = link
        if old is not None and old is not link:
            self._fail_pending(old, "controller_offline")

    def detach(self, link: Link) -> None:
        if self._links.get(link.key) is link:
            del self._links[link.key]
        self._fail_pending(link, "controller_offline")

    def detach_key(self, key_id: uuid.UUID) -> None:
        """A revoked API key: its links can no longer take commands."""
        tenant = tenancy.current_schema()
        for link in [lk for lk in self._links.values() if lk.key_id == key_id and lk.tenant == tenant]:
            self.detach(link)

    def links(self, field_id: uuid.UUID) -> list[Link]:
        tenant = tenancy.current_schema()
        return sorted((lk for (t, f, _), lk in self._links.items() if t == tenant and f == field_id),
                      key=lambda lk: lk.controller_id)

    def pick(self, field_id: uuid.UUID, controller_id: Optional[str]) -> Link:
        """The link a command goes to: the one named, or the only one that takes commands and is in charge
        of its live game."""
        links = self.links(field_id)
        if controller_id is not None:
            for link in links:
                if link.controller_id == controller_id:
                    return link
            raise RemoteProblem(409, "controller_offline")
        if not links:
            raise RemoteProblem(409, "controller_offline")
        able = [lk for lk in links if lk.remote_gm]
        if not able:
            raise RemoteProblem(409, "remote_gm_off")
        in_charge = [lk for lk in able if lk.live and lk.live.get("in_charge")]
        if len(in_charge) == 1:
            return in_charge[0]
        if len(able) == 1:
            return able[0]
        raise RemoteProblem(409, "controller_required")

    async def command(self, link: Link, command: dict[str, Any]) -> dict[str, Any]:
        """Sends a checked command and waits for its result (``command.result``'s body)."""
        if not link.remote_gm:
            raise RemoteProblem(409, "remote_gm_off")
        if self._links.get(link.key) is not link or link.tenant != tenancy.current_schema():
            raise RemoteProblem(409, "controller_offline")
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        link.pending[command["id"]] = future
        try:
            try:
                await link.send({"type": "command", **command})
            except Exception:  # noqa: BLE001  (the socket went away under us)
                raise RemoteProblem(409, "controller_offline") from None
            try:
                return await asyncio.wait_for(future, self.timeout_s)
            except asyncio.TimeoutError:
                raise RemoteProblem(504, "controller_timeout") from None
        finally:
            link.pending.pop(command["id"], None)

    def result(self, link: Link, body: dict[str, Any]) -> bool:
        """A ``command.result`` from the link: True if a command was waiting for it."""
        future = link.pending.get(body["id"])
        if future is None or future.done():
            return False
        future.set_result(body)
        return True

    @staticmethod
    def _fail_pending(link: Link, detail: str) -> None:
        for future in list(link.pending.values()):
            if not future.done():
                with contextlib.suppress(asyncio.InvalidStateError):
                    future.set_exception(RemoteProblem(409, detail))
