# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The open feeds of a field's published games (ADR-P4-12): iCalendar (``ical.py``) and JSON
(``json_feed.py``), documented in ``server/docs/feeds.md``.

Plain Python with no third-party import and no database (decision P4R17), so their tests also
run in the atalaia-dev image (tools/check.sh). They take the games as the plain values below;
``services/scheduling.py`` makes them from the database. Nothing here carries personal data:
no registrant, no count beyond the places left, no account (ADR-P4-12).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class FeedField:
    """The field as the feeds show it. ``base_url`` is the site's public origin
    (``https://campo.example.pt``, no trailing slash); ``host`` its host name, for iCalendar UIDs."""

    slug: str
    name: str
    timezone: str
    base_url: str
    host: str
    description: Optional[str] = None
    address: Optional[str] = None
    federation_label: Optional[str] = None

    @property
    def page_url(self) -> str:
        return f"{self.base_url}/f/{self.slug}/"


@dataclass(frozen=True)
class FeedGame:
    """A published (or later) game, as the feeds show it. ``location`` is already resolved (the
    game's own place, else the field's address); ``status`` is the stored one (never ``draft``);
    ``registration_open`` and ``places_left`` are computed by the caller."""

    id: uuid.UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    status: str
    updated_at: datetime
    sequence: int = 0
    description: Optional[str] = None
    location: Optional[str] = None
    mode_id: Optional[str] = None
    teams: tuple[str, ...] = field(default_factory=tuple)
    max_players: Optional[int] = None
    places_left: Optional[int] = None
    registration_opens_at: Optional[datetime] = None
    registration_closes_at: Optional[datetime] = None
    registration_open: bool = False
    federation: str = "off"
    cancelled_reason: Optional[str] = None

    def page_url(self, f: FeedField) -> str:
        return f"{f.base_url}/f/{f.slug}/games/{self.id}"

    def ics_url(self, f: FeedField) -> str:
        return f"{f.base_url}/f/{f.slug}/games/{self.id}.ics"
