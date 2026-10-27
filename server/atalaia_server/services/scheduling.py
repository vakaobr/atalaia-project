# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scheduled games: the rules of ADR-P4-11 that the API, the field pages and the feeds share.

Statuses (stored): ``draft`` (staff only), ``published`` (on the field page and the feeds),
``in_progress`` and ``completed`` (from the controller, plan phase 16), ``cancelled`` (kept
visible with its reason). ``registering`` is not stored: it is ``published`` with the window
open (``registration_state``). A draft can be edited, published or deleted; a published game
can be edited or cancelled, never deleted or turned back into a draft (calendars that
subscribed must see it change, decision S15-4).

**iCalendar ``SEQUENCE``** (``ical_sequence``, ADR-P4-12): raised by one when a published game's
start, end or place changes, when it is cancelled, and when the field's address changes for a
game that shows it (``bump_for_field_address``). Publishing does not raise it: subscribers have
not seen the game before.

**The feeds' window** (decision S15-5): every non-draft game of the field that ended less than
30 days ago or has not ended, cancelled ones included, so calendars keep a just-played or
just-cancelled game for a while; the field page lists only games that have not ended.

**Registration** (plan phase 16, ``services/registration.py``): ``places_left`` is ``max_players``
less the live registrations, and ``registration.open`` in the feeds is true while the window is open
and places are left (decision S15-7 as amended by S16-9).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional
from urllib.parse import urlsplit

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..feeds import FeedField, FeedGame
from ..models import FEDERATION_RULES, Field, ScheduledGame

# Online registration (plan phase 16): on.
ONLINE_REGISTRATION = True

FEED_PAST = timedelta(days=30)        # games stay in the feeds this long after their end
MAX_DURATION = timedelta(days=14)     # a weekend milsim fits easily
TITLE_MAX = 256
DESCRIPTION_MAX = 8000
LOCATION_MAX = 512
REASON_MAX = 512
TEAMS_MAX = 16
TEAM_MAX = 32
MAX_PLAYERS = 10000
MODE_ID = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
FIELD_DESCRIPTION_MAX = 4000
FEDERATION_LABEL_MAX = 16  # the controller's [checkin] federation_label
# What changes a published game for a calendar that already has it.
SEQUENCE_KEYS = frozenset({"starts_at", "ends_at", "location_text"})
EDITABLE = ("draft", "published")


class ScheduleError(ValueError):
    """A refused change: ``code`` is the API's ``detail``, ``status`` its HTTP status."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


def aware(value: Optional[datetime], name: str) -> Optional[datetime]:
    """A time with its offset, in UTC; a time without one is refused (it would be read in the
    server's zone, not the field's)."""
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScheduleError(f"{name}_needs_offset")
    return value.astimezone(timezone.utc)


def clean_text(value: Optional[str], name: str, limit: int, required: bool = False) -> Optional[str]:
    """Trimmed text within ``limit`` characters, None when empty (refused if ``required``); no
    control characters but line breaks and tabs."""
    text = (value or "").replace("\r\n", "\n").strip()
    if not text:
        if required:
            raise ScheduleError(f"{name}_invalid")
        return None
    if len(text) > limit or any(ord(c) < 0x20 and c not in "\n\t" for c in text) or "\x7f" in text:
        raise ScheduleError(f"{name}_invalid")
    return text


def clean_line(value: Optional[str], name: str, limit: int, required: bool = False) -> Optional[str]:
    """``clean_text`` on one line (a title, a place, a reason)."""
    text = clean_text(value, name, limit, required)
    if text is not None and ("\n" in text or "\t" in text):
        raise ScheduleError(f"{name}_invalid")
    return text


def clean_teams(teams: Iterable[str]) -> list[str]:
    out: list[str] = []
    for team in teams:
        name = clean_line(team, "teams", TEAM_MAX, required=True)
        assert name is not None
        if name in out:
            raise ScheduleError("teams_invalid")
        out.append(name)
    if len(out) > TEAMS_MAX:
        raise ScheduleError("teams_invalid")
    return out


def check(game: ScheduledGame) -> None:
    """The rules between a game's values (each value was checked on its own already)."""
    if game.ends_at <= game.starts_at or game.ends_at - game.starts_at > MAX_DURATION:
        raise ScheduleError("times_invalid")
    opens, closes = game.registration_opens_at, game.registration_closes_at
    if opens is not None and closes is not None and closes <= opens:
        raise ScheduleError("registration_window_invalid")
    if closes is not None and closes > game.starts_at:
        raise ScheduleError("registration_window_invalid")
    if opens is not None and opens >= game.starts_at:
        raise ScheduleError("registration_window_invalid")
    if game.federation not in FEDERATION_RULES:
        raise ScheduleError("federation_invalid")
    if game.max_players is not None and not 1 <= game.max_players <= MAX_PLAYERS:
        raise ScheduleError("max_players_invalid")
    if game.mode_id is not None and not MODE_ID.fullmatch(game.mode_id):
        raise ScheduleError("mode_id_invalid")


def note_change(game: ScheduledGame, changed: Iterable[str]) -> None:
    """Raises ``SEQUENCE`` when a change matters to calendars that already have the game."""
    if game.status != "draft" and SEQUENCE_KEYS & set(changed):
        game.ical_sequence += 1


def publish(game: ScheduledGame, now: datetime) -> None:
    if game.status != "draft":
        raise ScheduleError("not_a_draft", 409)
    if game.ends_at <= now:
        raise ScheduleError("game_in_the_past", 409)
    game.status, game.published_at = "published", now


def cancel(game: ScheduledGame, reason: Optional[str], now: datetime) -> None:
    if game.status != "published":
        raise ScheduleError("not_published", 409)
    game.status, game.cancelled_at = "cancelled", now
    game.cancelled_reason = clean_line(reason, "reason", REASON_MAX, required=True)
    game.ical_sequence += 1


async def bump_for_field_address(db: AsyncSession, field_id: uuid.UUID, now: datetime) -> int:
    """The field's address changed: a published game that shows it (no place of its own) and has
    not ended is changed for calendars. Returns how many."""
    result = await db.execute(update(ScheduledGame).where(
        ScheduledGame.field_id == field_id, ScheduledGame.status == "published",
        ScheduledGame.location_text.is_(None), ScheduledGame.ends_at > now,
    ).values(ical_sequence=ScheduledGame.ical_sequence + 1).execution_options(synchronize_session=False))
    return result.rowcount or 0


# --- what the public sees -------------------------------------------------------------------

def registration_state(game: ScheduledGame, now: datetime) -> Optional[str]:
    """``None`` (no window set), ``not_yet``, ``open``, ``closed`` (the window, as published; a
    window with no start opens at publication, one with no end closes at the start)."""
    opens, closes = game.registration_opens_at, game.registration_closes_at
    if opens is None and closes is None:
        return None
    if game.status != "published":
        return "closed"
    if opens is not None and now < opens:
        return "not_yet"
    if now >= (closes or game.starts_at):
        return "closed"
    return "open"


def places_left(game: ScheduledGame, registered: int = 0) -> Optional[int]:
    """``max_players`` less the live registrations (``registered``), or None for no limit."""
    if game.max_players is None:
        return None
    return max(game.max_players - registered, 0)


def can_register(game: ScheduledGame, now: datetime, registered: int = 0) -> bool:
    """Whether the public may register now: online registration on, the window open, places left."""
    left = places_left(game, registered)
    return ONLINE_REGISTRATION and registration_state(game, now) == "open" and (left is None or left > 0)


def location(game: ScheduledGame, field: Field) -> Optional[str]:
    return game.location_text or field.address_text


def feed_field(field: Field, base_url: str) -> FeedField:
    """The field for the feeds; ``base_url`` is the site's origin (iCalendar UIDs take its host name)."""
    return FeedField(slug=field.slug, name=field.name, timezone=field.timezone, base_url=base_url.rstrip("/"),
                     host=urlsplit(base_url).hostname or "localhost", description=field.description,
                     address=field.address_text,
                     federation_label=field.federation_label)


def feed_game(game: ScheduledGame, field: Field, now: datetime, registered: int = 0) -> FeedGame:
    return FeedGame(
        id=game.id, title=game.title, starts_at=game.starts_at, ends_at=game.ends_at, status=game.status,
        updated_at=game.updated_at, sequence=game.ical_sequence, description=game.description,
        location=location(game, field), mode_id=game.mode_id, teams=tuple(game.teams or ()),
        max_players=game.max_players, places_left=places_left(game, registered),
        registration_opens_at=game.registration_opens_at, registration_closes_at=game.registration_closes_at,
        registration_open=can_register(game, now, registered),
        federation=game.federation, cancelled_reason=game.cancelled_reason)


async def public_field(db: AsyncSession, slug: str) -> Optional[Field]:
    """The field with this slug, if its public page is on (otherwise, for the public, it is not there)."""
    return await db.scalar(select(Field).where(Field.slug == slug, Field.public_page.is_(True)))


async def public_games(db: AsyncSession, field_id: uuid.UUID, now: datetime,
                       upcoming_only: bool = False) -> list[ScheduledGame]:
    """The field's games the public may see, by start: never drafts; for the feeds, those that ended
    less than ``FEED_PAST`` ago too."""
    since = now if upcoming_only else now - FEED_PAST
    rows = await db.scalars(select(ScheduledGame).where(
        ScheduledGame.field_id == field_id, ScheduledGame.status != "draft", ScheduledGame.ends_at > since,
    ).order_by(ScheduledGame.starts_at, ScheduledGame.id))
    return list(rows)


async def public_game(db: AsyncSession, field_id: uuid.UUID, game_id: uuid.UUID) -> Optional[ScheduledGame]:
    """One game of the field the public may see (not a draft), whenever it was."""
    return await db.scalar(select(ScheduledGame).where(
        ScheduledGame.id == game_id, ScheduledGame.field_id == field_id, ScheduledGame.status != "draft"))


def last_modified(field: Field, games: Iterable[ScheduledGame]) -> datetime:
    """The latest change among the field's public details and these games (the feeds'
    ``Last-Modified``)."""
    return max([field.updated_at, *(g.updated_at for g in games)])


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def staff_json(game: ScheduledGame, field: Field, now: datetime, registered: int = 0) -> dict[str, Any]:
    """A scheduled game as its field's staff see it in the API."""
    return {
        "id": str(game.id), "field_id": str(game.field_id), "title": game.title, "description": game.description,
        "starts_at": _iso(game.starts_at), "ends_at": _iso(game.ends_at), "location_text": game.location_text,
        "location": location(game, field), "mode_id": game.mode_id, "teams": list(game.teams or ()),
        "max_players": game.max_players, "places_left": places_left(game, registered), "registered": registered,
        "registration_opens_at": _iso(game.registration_opens_at),
        "registration_closes_at": _iso(game.registration_closes_at),
        "registration_state": registration_state(game, now), "federation": game.federation,
        "predeclare_replicas": game.predeclare_replicas, "status": game.status,
        "published_at": _iso(game.published_at), "cancelled_at": _iso(game.cancelled_at),
        "cancelled_reason": game.cancelled_reason, "ical_sequence": game.ical_sequence,
        "created_by": str(game.created_by) if game.created_by else None,
        "controller_game": str(game.controller_game) if game.controller_game else None, "walkins": game.walkins,
        "roster_pull": None if game.roster_pulled_at is None else {
            "at": _iso(game.roster_pulled_at), "key_label": game.roster_key_label,
            "key_fingerprint": game.roster_key_fingerprint, "agent": game.roster_agent},
        "created_at": _iso(game.created_at), "updated_at": _iso(game.updated_at),
    }
