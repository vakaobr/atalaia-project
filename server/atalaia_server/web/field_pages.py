# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The public field page, its game pages and the open feeds (ADR-P4-11, ADR-P4-12; plan phase 15).

    GET /f/<slug>/                     the field page: its description, address and upcoming games
    GET /f/<slug>/games/<id>           one game: details, places, requirements, schema.org JSON-LD, and a
                                       *Register* button while registration is open and places are left
    GET /f/<slug>/games/<id>/register  how to register for it (with an account, plan phase 16)
    GET /f/<slug>/games.ics            iCalendar (RFC 5545) of the field's games
    GET /f/<slug>/games/<id>.ics       iCalendar of one game
    GET /f/<slug>/games.json           the JSON feed (``atalaia.games`` version 1)
    GET /static/field.css              the pages' one style sheet

Only a field with ``public_page`` on has them; any other slug, a draft, or a game of another
field is a 404, the same as a page that never existed. Rendered on the server from
``templates/`` (``string.Template``, every value escaped), no JavaScript, nothing loaded from
elsewhere, so the security headers' content security policy holds as it is (the JSON-LD block
is data, which the policy does not run). pt-PT or English: ``?lang=pt|en``, else
``Accept-Language``, else pt. No registrant's name or count: only the places left.

Every answer has an ``ETag`` (SHA-256 of the body) and ``Last-Modified``, and a matching
``If-None-Match`` (or, without it, ``If-Modified-Since``) gets 304, so calendars can poll
cheaply. ``HEAD`` is answered like ``GET`` without the body (the same headers, the GET's
``Content-Length``), as calendar clients use it (decision S16-10). The feeds send ``Access-Control-Allow-Origin: *`` (read-only, no cookies). Links use
``ATALAIA_PUBLIC_URL``, or the request's own address when it is not set.
"""

from __future__ import annotations

import hashlib
import html
import json
import uuid
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from string import Template
from typing import Any, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..feeds import FeedField, ical, json_feed
from ..models import Field, ScheduledGame
from ..services import registration, scheduling as svc
from ..api.fields import SLUG
from . import i18n

router = APIRouter(include_in_schema=False)

HERE = Path(__file__).resolve().parent
CACHE_PAGE = "public, max-age=60"
CACHE_FEED = "public, max-age=300"
HTML_TYPE = "text/html; charset=utf-8"


def _load(name: str) -> Template:
    lines = (HERE / "templates" / name).read_text(encoding="utf-8").splitlines(keepends=True)
    return Template("".join(line for line in lines if not line.startswith("<!-- SPDX-")))


TEMPLATES = {name: _load(f"{name}.html") for name in ("page", "field", "game", "register", "not_found")}
GET_HEAD = ["GET", "HEAD"]
CSS = (HERE / "static" / "field.css").read_bytes()
STARTED = datetime.now(timezone.utc)  # the style sheet's Last-Modified: it changes only with the server


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def paragraphs(text: Optional[str], css: str = "") -> str:
    """Plain text as HTML paragraphs (blank lines) with line breaks, every character escaped."""
    if not text:
        return ""
    cls = f' class="{css}"' if css else ""
    blocks = [b.strip() for b in text.replace("\r\n", "\n").split("\n\n") if b.strip()]
    return "".join(f"<p{cls}>" + "<br>\n".join(esc(line) for line in b.split("\n")) + "</p>\n" for b in blocks)


def json_ld(document: dict[str, Any]) -> str:
    """A ``<script type="application/ld+json">`` block that no text inside can close or break."""
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
    text = text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return f'<script type="application/ld+json">{text}</script>\n'


def base_url(request: Request) -> str:
    configured = request.app.state.settings.public_url
    return configured or str(request.base_url).rstrip("/")


def _http_date(value: datetime) -> str:
    return format_datetime(value.astimezone(timezone.utc).replace(microsecond=0), usegmt=True)


def _not_modified(request: Request, etag: str, modified: datetime) -> bool:
    match = request.headers.get("if-none-match")
    if match is not None:
        tags = {t.strip() for t in match.split(",")}
        return "*" in tags or etag in tags or f"W/{etag}" in tags
    since = request.headers.get("if-modified-since")
    if since:
        try:
            when = parsedate_to_datetime(since)
        except (TypeError, ValueError):
            return False
        if when.tzinfo is None:
            return False
        return modified.replace(microsecond=0) <= when
    return False


def answer(request: Request, body: str, media_type: str, modified: datetime, cache: str,
           extra: Optional[dict[str, str]] = None, status_code: int = 200) -> Response:
    data = body.encode("utf-8")
    etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
    headers = {"ETag": etag, "Last-Modified": _http_date(modified), "Cache-Control": cache, **(extra or {})}
    if status_code == 200 and _not_modified(request, etag, modified):
        return Response(status_code=304, headers=headers)
    if request.method == "HEAD":  # the GET's headers, its length, no body (RFC 9110 section 9.3.2)
        return Response(media_type=media_type, status_code=status_code,
                        headers={**headers, "Content-Length": str(len(data))})
    return Response(content=data, media_type=media_type, headers=headers, status_code=status_code)


def no_feed() -> Response:
    """A feed that is not there: 404, not cached (the same for HEAD: no body either way)."""
    return Response(status_code=404, headers={"Cache-Control": "no-store"})


class Page:
    """One rendering: the language and how links keep it."""

    def __init__(self, request: Request) -> None:
        self.lang, self.explicit = i18n.choose(request.query_params.get("lang"),
                                               request.headers.get("accept-language"))
        self.t = i18n.STRINGS[self.lang]
        self.path = request.url.path

    def link(self, path: str) -> str:
        return f"{path}?lang={self.lang}" if self.explicit else path

    def languages(self) -> str:
        out = []
        for lang in i18n.LANGUAGES:
            name = esc(i18n.LANGUAGE_NAMES[lang])
            if lang == self.lang:
                out.append(f'<span lang="{lang}" aria-current="true">{name}</span>')
            else:
                out.append(f'<a lang="{lang}" hreflang="{lang}" href="{esc(self.path)}?lang={lang}">{name}</a>')
        return " ".join(out)

    def render(self, request: Request, title: str, content: str, modified: datetime, head: str = "",
               status_code: int = 200) -> Response:
        body = TEMPLATES["page"].substitute(
            lang=self.lang, title=esc(title), head=head, language_label=esc(self.t["language"]),
            languages=self.languages(), content=content, footer=esc(self.t["footer"]))
        return answer(request, body, HTML_TYPE, modified, CACHE_PAGE, status_code=status_code,
                      extra={"Content-Language": self.lang, "Vary": "Accept-Language"})

    def not_found(self, request: Request) -> Response:
        content = TEMPLATES["not_found"].substitute(heading=esc(self.t["not_found_title"]),
                                                    text=esc(self.t["not_found"]))
        response = self.render(request, self.t["not_found_title"], content, datetime.now(timezone.utc),
                               status_code=404)
        response.headers["Cache-Control"] = "no-store"
        return response


def _game_line(page: Page, game: ScheduledGame, field: Field) -> str:
    when = i18n.span(game.starts_at, game.ends_at, field.timezone, page.lang)
    badge = f' <span class="badge">{esc(page.t["cancelled"])}</span>' if game.status == "cancelled" else ""
    href = page.link(f"/f/{field.slug}/games/{game.id}")
    return (f'<li><span class="when">{esc(when)}</span><a class="title" href="{esc(href)}">{esc(game.title)}</a>'
            f"{badge}</li>\n")


def _details(page: Page, game: ScheduledGame, field: Field, now: datetime, registered: int) -> str:
    t, zone = page.t, field.timezone
    rows: list[tuple[str, str]] = [
        (t["when"], esc(i18n.span(game.starts_at, game.ends_at, zone, page.lang)) + " <small>("
         + esc(t["local_time"].format(zone=zone)) + ")</small>")]
    place = svc.location(game, field)
    if place:
        rows.append((t["where"], esc(place)))
    rows.append((t["mode"], f"<code>{esc(game.mode_id)}</code>" if game.mode_id else esc(t["mode_later"])))
    if game.teams:
        rows.append((t["teams"], esc(", ".join(game.teams))))
    left = svc.places_left(game, registered)
    rows.append((t["places"], (esc(left) if left else esc(t["full"])) if left is not None else esc(t["places_open"])))
    state = svc.registration_state(game, now)
    if state == "not_yet":
        assert game.registration_opens_at is not None
        rows.append((t["registration"], esc(t["reg_not_yet"].format(
            opens=i18n.moment(game.registration_opens_at, zone, page.lang)))))
    elif state == "open":
        rows.append((t["registration"], esc(t["reg_open"].format(
            closes=i18n.moment(game.registration_closes_at or game.starts_at, zone, page.lang)))))
    elif state == "closed":
        rows.append((t["registration"], esc(t["reg_closed"])))
    if game.federation != "off":
        label = t["federation"] + (f" ({field.federation_label})" if field.federation_label else "")
        rows.append((label, esc(t["fed_required" if game.federation == "required" else "fed_optional"])))
    return "".join(f"<dt>{esc(k)}</dt><dd>{v}</dd>\n" for k, v in rows)


def _event_ld(game: ScheduledGame, field: Field, f: FeedField) -> dict[str, Any]:
    """schema.org ``Event`` (decision F19): times with the field's offset."""
    zone = ZoneInfo(field.timezone)
    place: dict[str, Any] = {"@type": "Place", "name": field.name}
    if svc.location(game, field):
        place["address"] = svc.location(game, field)
    doc: dict[str, Any] = {
        "@context": "https://schema.org", "@type": "Event", "name": game.title,
        "startDate": game.starts_at.astimezone(zone).replace(microsecond=0).isoformat(),
        "endDate": game.ends_at.astimezone(zone).replace(microsecond=0).isoformat(),
        "eventStatus": "https://schema.org/EventCancelled" if game.status == "cancelled"
        else "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": place, "url": f"{f.base_url}/f/{field.slug}/games/{game.id}",
        "organizer": {"@type": "Organization", "name": field.name, "url": f.page_url},
    }
    if game.description:
        doc["description"] = game.description
    if game.max_players is not None:
        doc["maximumAttendeeCapacity"] = game.max_players
    return doc


def _alternates(page: Page, field: Field) -> str:
    return (f'<link rel="alternate" type="text/calendar" href="/f/{esc(field.slug)}/games.ics">\n'
            f'<link rel="alternate" type="application/json" href="/f/{esc(field.slug)}/games.json">\n')


@router.api_route("/static/field.css", methods=GET_HEAD)
async def stylesheet(request: Request) -> Response:
    return answer(request, CSS.decode("utf-8"), "text/css; charset=utf-8", STARTED, "public, max-age=3600")


@router.api_route("/f/{slug}", methods=GET_HEAD)
async def field_redirect(slug: str, request: Request) -> Response:
    if not SLUG.fullmatch(slug):
        return Page(request).not_found(request)
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/f/{slug}/{query}", status_code=308)


@router.api_route("/f/{slug}/", methods=GET_HEAD)
async def field_page(slug: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    page = Page(request)
    field = await svc.public_field(db, slug)
    if field is None:
        return page.not_found(request)
    now = datetime.now(timezone.utc)
    games = await svc.public_games(db, field.id, now, upcoming_only=True)
    items = "".join(_game_line(page, g, field) for g in games)
    listing = f'<ul class="list">\n{items}</ul>\n' if games else f"<p>{esc(page.t['no_games'])}</p>\n"
    address = f'<p class="address">{esc(field.address_text)}</p>\n' if field.address_text else ""
    content = TEMPLATES["field"].substitute(
        name=esc(field.name), description=paragraphs(field.description), address=address,
        upcoming=esc(page.t["upcoming"]), games=listing, calendar=esc(page.t["calendar"]),
        feeds_text=esc(page.t["feeds_text"]), ics_url=esc(f"/f/{field.slug}/games.ics"),
        json_url=esc(f"/f/{field.slug}/games.json"), feed_ics=esc(page.t["feed_ics"]),
        feed_json=esc(page.t["feed_json"]))
    return page.render(request, field.name, content, svc.last_modified(field, games), head=_alternates(page, field))


def _feed_headers() -> dict[str, str]:
    return {"Access-Control-Allow-Origin": "*"}


async def _feed_games(db: AsyncSession, field: Field, now: datetime) -> tuple[datetime, list[Any]]:
    """The feed's games and its Last-Modified: the places left change with the registrations."""
    from sqlalchemy import func, select  # noqa: PLC0415

    from ..models import GameRegistration  # noqa: PLC0415

    games = await svc.public_games(db, field.id, now)
    n = await registration.counts(db, [g.id for g in games])
    modified = svc.last_modified(field, games)
    if games:
        last = await db.scalar(select(func.max(GameRegistration.updated_at)).where(
            GameRegistration.scheduled_game.in_([g.id for g in games])))
        modified = max(modified, last) if last is not None else modified
    return modified, [svc.feed_game(g, field, now, n.get(g.id, 0)) for g in games]


@router.api_route("/f/{slug}/games.ics", methods=GET_HEAD)
async def field_calendar(slug: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    field = await svc.public_field(db, slug)
    if field is None:
        return no_feed()
    now = datetime.now(timezone.utc)
    modified, feed = await _feed_games(db, field, now)
    f = svc.feed_field(field, base_url(request))
    body = ical.calendar(f, feed)
    return answer(request, body, ical.MEDIA_TYPE, modified, CACHE_FEED, _feed_headers())


@router.api_route("/f/{slug}/games.json", methods=GET_HEAD)
async def field_json(slug: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    field = await svc.public_field(db, slug)
    if field is None:
        return no_feed()
    now = datetime.now(timezone.utc)
    modified, feed = await _feed_games(db, field, now)
    f = svc.feed_field(field, base_url(request))
    body = json_feed.dumps(json_feed.feed(f, feed))
    return answer(request, body, json_feed.MEDIA_TYPE, modified, CACHE_FEED, _feed_headers())


def _game_id(text: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(text) if len(text) == 36 else None
    except ValueError:
        return None


@router.api_route("/f/{slug}/games/{name}", methods=GET_HEAD)
async def game_page(slug: str, name: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    """One game's page, or its ``.ics`` (``<id>.ics``)."""
    page = Page(request)
    want_ics = name.endswith(".ics")
    game_id = _game_id(name[:-4] if want_ics else name)
    field = await svc.public_field(db, slug)
    game = await svc.public_game(db, field.id, game_id) if field is not None and game_id is not None else None
    if field is None or game is None:
        if want_ics:
            return no_feed()
        return page.not_found(request)
    now = datetime.now(timezone.utc)
    f = svc.feed_field(field, base_url(request))
    registered = (await registration.counts(db, [game.id])).get(game.id, 0)
    # The places left change with every registration: the page and its feed change with them.
    modified = max(svc.last_modified(field, [game]), await _last_registration(db, game))
    if want_ics:
        body = ical.calendar(f, [svc.feed_game(game, field, now, registered)], name=f"{field.name}: {game.title}")
        return answer(request, body, ical.MEDIA_TYPE, modified, CACHE_FEED, _feed_headers())
    notice = ""
    if game.status == "cancelled":
        reason = (f" {esc(page.t['reason'])}: {esc(game.cancelled_reason)}" if game.cancelled_reason else "")
        notice = f'<p class="notice">{esc(page.t["cancelled_notice"])}{reason}</p>\n'
    elif game.ends_at <= now:
        notice = f'<p class="notice">{esc(page.t["past"])}</p>\n'
    register = ""
    if svc.can_register(game, now, registered):  # only while it is open and places are left
        href = page.link(f"/f/{field.slug}/games/{game.id}/register")
        register = f'<p class="register"><a class="button" href="{esc(href)}">{esc(page.t["register"])}</a></p>\n'
    content = TEMPLATES["game"].substitute(
        field_url=esc(page.link(f"/f/{field.slug}/")), back=esc(page.t["back"].format(field=field.name)),
        title=esc(game.title), notice=notice, details=_details(page, game, field, now, registered),
        register=register,
        description=paragraphs(game.description), ics_url=esc(f"/f/{field.slug}/games/{game.id}.ics"),
        add_to_calendar=esc(page.t["add_to_calendar"]))
    head = json_ld(_event_ld(game, field, f)) + _alternates(page, field)
    return page.render(request, f"{game.title} · {field.name}", content, modified, head=head)



async def _last_registration(db: AsyncSession, game: ScheduledGame) -> datetime:
    """When the game's registrations last changed (its own ``updated_at`` if never)."""
    from sqlalchemy import func, select  # noqa: PLC0415

    from ..models import GameRegistration  # noqa: PLC0415

    when = await db.scalar(select(func.max(GameRegistration.updated_at)).where(
        GameRegistration.scheduled_game == game.id))
    return max(when, game.updated_at) if when is not None else game.updated_at


@router.api_route("/f/{slug}/games/{name}/register", methods=GET_HEAD)
async def register_page(slug: str, name: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    """How to register: with an account on this site, in the Atalaia app (no form here: the pages have no
    JavaScript and no login, decision S16-9). Only while registration is open."""
    page = Page(request)
    game_id = _game_id(name)
    field = await svc.public_field(db, slug)
    game = await svc.public_game(db, field.id, game_id) if field is not None and game_id is not None else None
    if field is None or game is None:
        return page.not_found(request)
    now = datetime.now(timezone.utc)
    registered = (await registration.counts(db, [game.id])).get(game.id, 0)
    t = page.t
    if svc.can_register(game, now, registered):
        steps = "".join(f"<li>{esc(t[k])}</li>\n" for k in ("reg_step_account", "reg_step_app", "reg_step_ticket"))
        text = f'<p>{esc(t["reg_intro"])}</p>\n<ol class="steps">\n{steps}</ol>\n<p class="address">{esc(t["reg_data"])}</p>\n'
    else:
        text = f'<p class="notice">{esc(t["reg_unavailable"])}</p>\n'
    content = TEMPLATES["register"].substitute(
        game_url=esc(page.link(f"/f/{field.slug}/games/{game.id}")), back=esc(t["back_game"].format(game=game.title)),
        heading=esc(t["register_title"].format(game=game.title)), text=text)
    modified = max(svc.last_modified(field, [game]), await _last_registration(db, game))
    return page.render(request, f"{t['register']} · {game.title}", content, modified)
