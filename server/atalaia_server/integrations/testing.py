# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The test adapter: an in-memory stand-in for a platform (ADR-P4-12's "a test adapter"; decision S17-6).

It talks to no network and to no real platform. It exists so the adapter interface, the per-field
configuration, the audit log and the import of a platform's registrations can be tested and tried
end to end. A server offers it only with ``ATALAIA_TEST_ADAPTER=on``. Its configuration is an
``account`` and a ``token`` (a secret, never shown again); the platform's state lives in
``TestPlatform`` (one per process) for the tests to look at, fill with registrations and make fail.
"""

from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from .base import AdapterConfig, AdapterError, ExternalRef, ImportedRegistration, PublishedGame

TEXT_MAX = 128


@dataclass
class TestPlatform:
    """What the stand-in platform holds: its events by reference, the registrations it would give back,
    and the operations that should fail (``fail``) or hang (``hang``) for the next calls."""

    __test__ = False  # not a unittest case

    events: dict[str, dict[str, Any]] = field(default_factory=dict)
    registrations: dict[str, list[ImportedRegistration]] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)  # (operation, account)
    fail: set[str] = field(default_factory=set)
    hang: set[str] = field(default_factory=set)
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    def reset(self) -> None:
        self.events.clear()
        self.registrations.clear()
        self.calls.clear()
        self.fail.clear()
        self.hang.clear()
        self._ids = itertools.count(1)

    async def _enter(self, operation: str, cfg: AdapterConfig) -> None:
        self.calls.append((operation, cfg.get("account", "")))
        if operation in self.hang:
            await asyncio.sleep(3600)
        if operation in self.fail:
            raise AdapterError("platform_unavailable")


class TestAdapter:
    __test__ = False

    id = "test"
    name = "Test platform (in memory)"
    capabilities = frozenset({"publish", "update", "cancel", "registrations"})
    basis = "No platform: an in-memory stand-in for the tests and trials (decision S17-6)."
    config_keys = ("account", "token")
    secret_keys = frozenset({"token"})

    def __init__(self, platform: Optional[TestPlatform] = None) -> None:
        self.platform = platform or TestPlatform()

    def check_config(self, config: Mapping[str, object]) -> dict[str, str]:
        if set(config) != set(self.config_keys):
            raise AdapterError("config_invalid")
        out = {}
        for key in self.config_keys:
            value = config[key]
            if not isinstance(value, str) or not 1 <= len(value) <= TEXT_MAX or not value.isprintable():
                raise AdapterError("config_invalid")
            out[key] = value
        return out

    def _event(self, ref: ExternalRef) -> dict[str, Any]:
        event = self.platform.events.get(ref)
        if event is None:
            raise AdapterError("not_found")
        return event

    async def publish(self, game: PublishedGame, cfg: AdapterConfig) -> ExternalRef:
        await self.platform._enter("publish", cfg)
        ref = f"test-{next(self.platform._ids)}"
        self.platform.events[ref] = {"game": game, "cancelled": False, "account": cfg["account"]}
        return ref

    async def update(self, ref: ExternalRef, game: PublishedGame, cfg: AdapterConfig) -> None:
        await self.platform._enter("update", cfg)
        self._event(ref)["game"] = game

    async def cancel(self, ref: ExternalRef, cfg: AdapterConfig) -> None:
        await self.platform._enter("cancel", cfg)
        self._event(ref)["cancelled"] = True

    async def fetch_registrations(self, ref: ExternalRef, cfg: AdapterConfig) -> list[ImportedRegistration]:
        await self.platform._enter("registrations", cfg)
        self._event(ref)
        return list(self.platform.registrations.get(ref, []))
