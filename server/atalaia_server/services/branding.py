# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Club profiles, field branding and saved teams (P4R19; plan phase 18).

Images are checked with the field controller's own ``images.py`` (imported, the same limits: a logo
1 MiB and 16-2048 px, a wallpaper 4 MiB and 320-4096 px, a crest 512 KiB and 16-1024 px; PNG, JPEG or
WebP only; metadata stripped) and stored once in ``branding_images`` by the SHA-256 of the checked
bytes, the name controllers fetch them by. Every upload is answered with the rights reminder
(``RIGHTS_NOTICE``) and needs ``rights_confirmed=true`` (decision S18-4).

A field's saved team is a club's team (the club's short name and crest, unless the team sets its own)
or one of its own; ``field_answer`` is what ``GET /api/v1/sync/field`` sends the field's controllers,
checked by ``sync_format.check_field`` in the tests.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from atalaia_controller import images, sync_format
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import BrandingImage, Club, ClubMember, Field, FieldTeam
from . import registration

RIGHTS_NOTICE = {
    "pt": "Carregue apenas imagens que tem o direito de usar: quem as carrega é responsável por elas.",
    "en": "Upload only images you have the right to use: the uploader is responsible for them.",
}
IMAGE_GRACE = timedelta(days=1)  # an image nothing uses is kept a day after its upload, then purged
ACCENT = re.compile(r"#[0-9a-f]{6}")
CLUB_SLUG = sync_format.CLUB_SLUG
CLUB_NAME_MAX = 128
CLUB_DESCRIPTION_MAX = 4000
TEAM_NAME_MAX = sync_format.TEAM_DISPLAY_MAX  # 32: a controller's team display name
TEAM_COLOUR_MAX = sync_format.TEAM_MAX        # 23 bytes: a team name as the boxes know it
FIELD_NAME_MAX = sync_format.FIELD_NAME_MAX   # 48: the controller's poster name
MAX_TEAMS = sync_format.MAX_SYNC_TEAMS        # a field's saved teams


class BrandingError(ValueError):
    """A refused change: ``code`` is the API's ``detail``, ``status`` its HTTP status."""

    def __init__(self, code: str, status: int = 400) -> None:
        super().__init__(code)
        self.code, self.status = code, status


def accent(value: Optional[str], name: str = "accent") -> Optional[str]:
    """``#rrggbb`` (stored lower-case), or None for none."""
    if value is None or value == "":
        return None
    value = value.strip().lower()
    if not ACCENT.fullmatch(value):
        raise BrandingError(f"{name}_invalid")
    return value


def one_line(value: Optional[str], name: str, limit: int, required: bool = False) -> Optional[str]:
    """Trimmed text on one line, no control characters, within ``limit`` characters; None when empty."""
    text = (value or "").strip()
    if not text:
        if required:
            raise BrandingError(f"{name}_invalid")
        return None
    if len(text) > limit or any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F or 0xD800 <= ord(c) <= 0xDFFF
                                for c in text):
        raise BrandingError(f"{name}_invalid")
    return text


def team_colour(value: Optional[str]) -> Optional[str]:
    """The colour a team usually plays, as a game names teams (red, blue...): 1-23 bytes, no spaces."""
    if value is None or value.strip() == "":
        return None
    value = value.strip()
    if len(value.encode("utf-8")) > TEAM_COLOUR_MAX or any(ord(c) < 0x21 or 0x7F <= ord(c) <= 0x9F for c in value):
        raise BrandingError("colour_invalid")
    return value


# --- images ----------------------------------------------------------------------------

async def store_image(db: AsyncSession, data: bytes, content_type: str, kind: str) -> BrandingImage:
    """Checks an upload with the controller's ``images.check`` (``ImageError`` with its 413, 415 or 422) and
    stores the checked bytes once; returns the row."""
    checked = images.check(data, content_type, images.KINDS[kind])
    sha = hashlib.sha256(checked.data).hexdigest()
    await db.execute(insert(BrandingImage).values(
        sha256=sha, content_type=checked.content_type, width=checked.width, height=checked.height,
        bytes=len(checked.data), data=checked.data).on_conflict_do_nothing(index_elements=["sha256"]))
    row = await db.get(BrandingImage, sha)
    assert row is not None
    return row


async def image_ref(db: AsyncSession, sha: Optional[str]) -> Optional[dict[str, Any]]:
    """An image as the APIs and the sync name it, without its bytes."""
    if sha is None:
        return None
    row = (await db.execute(select(BrandingImage.sha256, BrandingImage.content_type, BrandingImage.width,
                                   BrandingImage.height, BrandingImage.bytes)
                            .where(BrandingImage.sha256 == sha))).first()
    if row is None:
        return None
    return {"sha256": row[0], "content_type": row[1], "width": row[2], "height": row[3], "bytes": row[4]}


def referenced() -> Any:
    """A condition: the image is used by a club, a field or a saved team."""
    sha = BrandingImage.sha256
    return or_(select(Club.id).where(or_(Club.logo_sha256 == sha, Club.crest_sha256 == sha)).exists(),
               select(Field.id).where(or_(Field.logo_sha256 == sha, Field.wallpaper_sha256 == sha)).exists(),
               select(FieldTeam.id).where(FieldTeam.crest_sha256 == sha).exists())


async def purge_images(db: AsyncSession, now: datetime) -> int:
    """Deletes the images nothing uses, a day after their upload (called by the daily purge)."""
    from sqlalchemy import delete  # noqa: PLC0415

    result = await db.execute(delete(BrandingImage).where(BrandingImage.created_at < now - IMAGE_GRACE,
                                                          ~referenced()))
    return result.rowcount or 0


# --- clubs ----------------------------------------------------------------------------------

async def club_role(db: AsyncSession, club_id: uuid.UUID, user_id: uuid.UUID) -> Optional[str]:
    """The account's club role, once it accepted the invitation; else None."""
    return await db.scalar(select(ClubMember.role).where(ClubMember.club_id == club_id, ClubMember.user_id == user_id,
                                                         ClubMember.accepted_at.is_not(None)))


def club_visible(club: Club) -> bool:
    """The club's public page is on and no administrator hid it."""
    return club.public_page and club.hidden_at is None


async def club_json(db: AsyncSession, club: Club, my_role: Optional[str] = None) -> dict[str, Any]:
    out = {"id": str(club.id), "name": club.name, "short_name": club.short_name, "slug": club.slug,
           "description": club.description, "colour": club.colour,
           "logo": await image_ref(db, club.logo_sha256), "crest": await image_ref(db, club.crest_sha256),
           "public_page": club.public_page, "hidden": club.hidden_at is not None,
           "hidden_reason": club.hidden_reason,
           "created_at": club.created_at.isoformat() if club.created_at else None}
    if my_role is not None:
        out["my_role"] = my_role
    return out


async def club_fields(db: AsyncSession, club: Club, public_only: bool) -> list[dict[str, Any]]:
    """The fields where a club plays, from the teams those fields saved for it (``field_teams``): id, name and slug,
    by name. ``public_only``: only fields with a public page (what anyone may be told); a member sees them all."""
    stmt = select(Field).join(FieldTeam, FieldTeam.field_id == Field.id).where(FieldTeam.club_id == club.id)
    if public_only:
        stmt = stmt.where(Field.public_page.is_(True))
    fields = (await db.scalars(stmt.distinct().order_by(Field.name, Field.id))).all()
    return [{"id": str(f.id), "name": f.name, "slug": f.slug, "public_page": bool(f.public_page)} for f in fields]


# --- a field's branding and saved teams -------------------------------------------------------

async def field_teams(db: AsyncSession, field_id: uuid.UUID) -> list[tuple[FieldTeam, Optional[Club]]]:
    rows = await db.execute(select(FieldTeam, Club).outerjoin(Club, Club.id == FieldTeam.club_id)
                            .where(FieldTeam.field_id == field_id).order_by(FieldTeam.created_at, FieldTeam.id))
    return [(t, c) for t, c in rows]


def team_name(team: FieldTeam, club: Optional[Club]) -> str:
    """The name a team carries on controllers: its own, else its club's short name."""
    if team.name:
        return team.name
    assert club is not None
    return club.short_name


def team_crest(team: FieldTeam, club: Optional[Club]) -> Optional[str]:
    return team.crest_sha256 or (club.crest_sha256 if club is not None else None)


async def team_json(db: AsyncSession, team: FieldTeam, club: Optional[Club], sync: bool = False) -> dict[str, Any]:
    """A saved team as the field's staff see it, or (``sync``) as its controllers get it."""
    out: dict[str, Any] = {"team_id": str(team.id), "name": team_name(team, club), "colour": team.colour,
                           "crest": await image_ref(db, team_crest(team, club)),
                           "club": {"slug": club.slug, "name": club.name} if club is not None else None}
    if not sync:
        out["own_name"] = team.name
        out["own_crest"] = team.crest_sha256 is not None
    return out


async def check_team_names(db: AsyncSession, field_id: uuid.UUID) -> None:
    """Two saved teams of a field never carry the same name (a controller's presets are unique by name)."""
    seen: set[str] = set()
    for team, club in await field_teams(db, field_id):
        name = team_name(team, club)
        if name in seen:
            raise BrandingError("team_name_taken", 409)
        seen.add(name)


async def field_branding(db: AsyncSession, field: Field) -> dict[str, Any]:
    return {"field_name": field.branding_name, "accent": field.accent,
            "logo": await image_ref(db, field.logo_sha256), "wallpaper": await image_ref(db, field.wallpaper_sha256)}


def field_settings(field: Field) -> Optional[dict[str, Any]]:
    """The field's check-in rules a controller takes over (decision S16-6, BR24): its federation label (null
    when it has none), ``max_replicas``, limit template whole, APD membership rule and country (protocol/apd.md),
    and how many days it keeps chrono records and ended games' data (decisions RET-1, RET-2); None when the
    template's file is gone."""
    template = registration.limit_template_body(field.limit_template)
    if template is None:
        return None
    return {"federation_label": field.federation_label, "max_replicas": field.max_replicas,
            "limit_template": template, "apd": registration.field_rule(field), "country": field.country,
            "chrono_retention_days": field.default_retention_days, "game_retention_days": field.game_retention_days}


async def field_answer(db: AsyncSession, field_id: uuid.UUID, settings: bool = False) -> dict[str, Any]:
    """``GET /api/v1/sync/field``: the field's branding and saved teams (protocol/sync.md, plan phase 18) and,
    only for a controller that asked (``?settings=1``: an older controller checks the answer strictly and
    would refuse a key it does not know), the field's check-in ``settings``."""
    field = await db.get(Field, field_id)
    assert field is not None
    teams, names = [], set()
    for t, c in await field_teams(db, field_id):
        name = team_name(t, c)
        if name in names:
            continue  # a club renamed to another saved team's name: the first one keeps it (decision S18-7)
        names.add(name)
        teams.append(await team_json(db, t, c, sync=True))
    out = {"sync_version": sync_format.SYNC_VERSION, "field": await field_branding(db, field), "teams": teams}
    if settings and (st := field_settings(field)) is not None:
        out["settings"] = st
    return out


async def fields_of_club(db: AsyncSession, club_id: uuid.UUID) -> list[uuid.UUID]:
    """The fields that have a saved team of the club (a change of the club's name or crest reaches them)."""
    return list(await db.scalars(select(FieldTeam.field_id).where(FieldTeam.club_id == club_id).distinct()))


def announce(request: Any, field_ids: Any, what: Optional[tuple[str, ...]] = None) -> None:
    """Tells the controllers of these fields that are connected on the stream that their branding, saved teams
    or settings changed (``field.changed``; they pull ``GET /api/v1/sync/field`` at once). Call it after the
    change is committed; it never fails a request and never waits for a socket. ``what``: ``("library",)`` or
    ``("schedule",)`` for the scenario library and the schedule (PKD-1); none for the branding and settings."""
    hub = getattr(request.app.state, "remote_hub", None)
    if hub is not None:
        for field_id in set(field_ids):
            hub.announce_field(field_id, what)


async def field_image(db: AsyncSession, field_id: uuid.UUID, sha: str) -> Optional[BrandingImage]:
    """An image the field's branding or one of its saved teams uses (another one is not the field's to fetch)."""
    if not sync_format.SHA256_HEX.fullmatch(sha):
        return None
    field = await db.get(Field, field_id)
    if field is None:
        return None
    used = sha in (field.logo_sha256, field.wallpaper_sha256)
    if not used:
        used = any(team_crest(t, c) == sha for t, c in await field_teams(db, field_id))
    return await db.get(BrandingImage, sha) if used else None
