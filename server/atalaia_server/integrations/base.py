# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The interface between the site server and an external platform (ADR-P4-12; plan phase 17, decisions F21,
F22, S17-*).

An adapter connects one field's site server to one external platform **through that platform's own
documented API, or an interface the platform agreed to in writing**. No scraping of web pages, no
automated form posting, no use of a person's login beyond what the platform's API offers: an adapter
that does any of these is not accepted. Each adapter names that basis (``basis``: the API
documentation's address or the agreement's reference), and ``registry.register`` refuses one without it.

What an adapter is given is what the public JSON feed already shows (``PublishedGame``: no person at all);
what it brings back is a list of ``ImportedRegistration`` with only the import's columns, which then go
through the registration import's rules (``import_format.check_row``), the same as a CSV file.

Plain Python (no web stack), so the interface's own tests also run in tools/check.sh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Optional, Protocol, runtime_checkable

CAPABILITIES = frozenset({"publish", "update", "cancel", "registrations"})

ExternalRef = str
AdapterConfig = Mapping[str, str]


class AdapterError(Exception):
    """A refused or failed call: ``code`` is a short reason (``config_invalid``, ``platform_unavailable``,
    ``not_found``...) that goes in the audit log and ``external_game_links.last_error``; never a credential."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code[:64]


@dataclass(frozen=True)
class PublishedGame:
    """A scheduled game as the public JSON feed shows it (``feeds/json_feed.py``): no personal data."""

    id: str
    field_slug: str
    field_name: str
    title: str
    description: Optional[str]
    starts_at: datetime
    ends_at: datetime
    status: str                       # published, in_progress, completed, cancelled
    location: Optional[str]
    mode_id: Optional[str]
    teams: tuple[str, ...]
    max_players: Optional[int]
    places_left: Optional[int]
    registration_opens_at: Optional[datetime]
    registration_closes_at: Optional[datetime]
    registration_open: bool
    federation: str
    url: str
    cancelled_reason: Optional[str] = None


@dataclass(frozen=True)
class ImportedReplica:
    type: str
    cls: str
    make_model: Optional[str] = None


@dataclass(frozen=True)
class ImportedRegistration:
    """One registration as a platform gives it, with only the import's columns (F20)."""

    display_name: str
    external_ref: Optional[str] = None
    team_preference: Optional[str] = None
    federation_number: Optional[str] = None
    replicas: tuple[ImportedReplica, ...] = field(default_factory=tuple)


@runtime_checkable
class PlatformAdapter(Protocol):
    id: str                           # stable, a-z 0-9 . _ - (also the imports' source)
    name: str
    capabilities: frozenset[str]      # a subset of CAPABILITIES
    basis: str                        # the documented API or the written agreement it uses
    config_keys: tuple[str, ...]      # the configuration's names, in order
    secret_keys: frozenset[str]       # those never shown again once set

    def check_config(self, config: Mapping[str, object]) -> dict[str, str]:
        """The configuration as stored, or ``AdapterError("config_invalid")``."""
        ...

    async def publish(self, game: PublishedGame, cfg: AdapterConfig) -> ExternalRef: ...

    async def update(self, ref: ExternalRef, game: PublishedGame, cfg: AdapterConfig) -> None: ...

    async def cancel(self, ref: ExternalRef, cfg: AdapterConfig) -> None: ...

    async def fetch_registrations(self, ref: ExternalRef, cfg: AdapterConfig) -> list[ImportedRegistration]: ...
