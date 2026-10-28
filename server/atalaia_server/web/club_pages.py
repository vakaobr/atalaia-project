# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The public club pages (P4R19; plan phase 18).

    GET  /c/<slug>/                 the club: its colour, crest, logo, name, short name, description and the fields
                                    with a public page where it plays (from the teams those fields saved for it)
    GET  /c/<slug>/logo, /crest     its images, as stored (checked, metadata stripped)
    GET  /c/<slug>/report           the report button's form
    POST /c/<slug>/report           a report (reason and text; form-encoded, no JavaScript, no login)

Only a club with ``public_page`` on that no server administrator hid has them; anything else is a 404,
the same as a club that never existed (decision S18-8). Rendered like the field pages (``field_pages``:
``string.Template`` with every value escaped, in their languages, ETags, no script); no member is ever named.
A report keeps no address; the reports per address are limited (5 an hour, ``Limits.reports``).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..models import REPORT_REASONS, BrandingImage, Club
from ..services import branding as svc
from .field_pages import GET_HEAD, Page, _load, esc, paragraphs

router = APIRouter(include_in_schema=False)
TEMPLATES = {name: _load(f"{name}.html") for name in ("club", "club_report")}
FORM_MAX = 8192  # bytes of a report form


async def public_club(db: AsyncSession, slug: str) -> Optional[Club]:
    if not svc.CLUB_SLUG.fullmatch(slug):
        return None
    club = await db.scalar(select(Club).where(Club.slug == slug))
    return club if club is not None and svc.club_visible(club) else None


def _footer(page: Page) -> str:
    return page.t["club_footer"]


@router.api_route("/c/{slug}", methods=GET_HEAD)
async def club_redirect(slug: str, request: Request) -> Response:
    if not svc.CLUB_SLUG.fullmatch(slug):
        return Page(request).not_found(request)
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/c/{slug}/{query}", status_code=308)


@router.api_route("/c/{slug}/", methods=GET_HEAD)
async def club_page(slug: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    page = Page(request)
    club = await public_club(db, slug)
    if club is None:
        return page.not_found(request)
    band = f'<div class="club-band" style="background: {esc(club.colour)}"></div>\n' if club.colour else ""
    imgs = []
    for slot, label in (("crest", "club_crest"), ("logo", "club_logo")):
        sha = getattr(club, f"{slot}_sha256")
        if sha:
            imgs.append(f'<img src="/c/{esc(club.slug)}/{slot}?v={esc(sha[:16])}" '
                        f'alt="{esc(page.t[label].format(club=club.name))}">')
    images = f'<p class="club-images">{"".join(imgs)}</p>\n' if imgs else ""
    short = f'<p class="short-name">{esc(club.short_name)}</p>\n' if club.short_name != club.name else ""
    played = await svc.club_fields(db, club, True)  # only fields with a public page are named (PKC-3)
    fields = ""
    if played:
        links = "".join(f'<li><a href="{esc(page.link("/f/" + f["slug"] + "/"))}">{esc(f["name"])}</a></li>\n'
                        for f in played)
        fields = (f'<section class="club-fields">\n<h2>{esc(page.t["club_fields"])}</h2>\n<ul>\n{links}</ul>\n'
                  '</section>\n')
    content = TEMPLATES["club"].substitute(
        band=band, images=images, fields=fields, name=esc(club.name), short_name=short,
        description=paragraphs(club.description),
        report_url=esc(page.link(f"/c/{club.slug}/report")), report=esc(page.t["report"]))
    return page.render(request, club.name, content, club.updated_at, footer=_footer(page))


@router.api_route("/c/{slug}/{slot}", methods=GET_HEAD)
async def club_image(slug: str, slot: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    if slot == "report":
        return await report_form(slug, request, db)
    club = await public_club(db, slug) if slot in ("logo", "crest") else None
    sha = getattr(club, f"{slot}_sha256") if club is not None else None
    image = await db.get(BrandingImage, sha) if sha else None
    if image is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    etag = f'"{image.sha256}"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=300", "Content-Disposition": "inline"}
    if etag in {t.strip() for t in request.headers.get("if-none-match", "").split(",")}:
        return Response(status_code=304, headers=headers)
    if request.method == "HEAD":
        return Response(media_type=image.content_type, headers={**headers, "Content-Length": str(image.bytes)})
    return Response(image.data, media_type=image.content_type, headers=headers)


def _form(page: Page, club: Club, chosen: str = "", text: str = "") -> str:
    t = page.t
    options = "".join(
        f'<label><input type="radio" name="reason" value="{r}" required{" checked" if r == chosen else ""}> '
        f'{esc(t["reason_" + r])}</label>\n' for r in REPORT_REASONS)
    return (f'<p>{esc(t["report_intro"])}</p>\n'
            f'<form class="report" method="post" action="{esc(page.link(f"/c/{club.slug}/report"))}">\n'
            f'<fieldset>\n<legend>{esc(t["report_reason"])}</legend>\n{options}</fieldset>\n'
            f'<label for="text">{esc(t["report_text"])}</label>\n'
            f'<textarea id="text" name="text" maxlength="1000">{esc(text)}</textarea>\n'
            f'<button type="submit">{esc(t["report_send"])}</button>\n</form>\n'
            f'<p class="address">{esc(t["report_privacy"])}</p>\n')


def _report_page(request: Request, page: Page, club: Club, notice: str, form: str, status_code: int = 200) -> Response:
    t = page.t
    content = TEMPLATES["club_report"].substitute(
        club_url=esc(page.link(f"/c/{club.slug}/")), back=esc(t["back_club"].format(club=club.name)),
        heading=esc(t["report_title"].format(club=club.name)), notice=notice, form=form)
    response = page.render(request, t["report_title"].format(club=club.name), content, datetime.now(timezone.utc),
                           status_code=status_code, footer=_footer(page))
    response.headers["Cache-Control"] = "no-store"
    return response


async def report_form(slug: str, request: Request, db: AsyncSession) -> Response:
    page = Page(request)
    club = await public_club(db, slug)
    if club is None:
        return page.not_found(request)
    return _report_page(request, page, club, "", _form(page, club))


@router.post("/c/{slug}/report")
async def report(slug: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    from ..api.clubs import file_report  # noqa: PLC0415

    page = Page(request)
    club = await public_club(db, slug)
    if club is None:
        return page.not_found(request)
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > FORM_MAX:
            break
    form = parse_qs(bytes(raw[:FORM_MAX]).decode("utf-8", "replace"), max_num_fields=8)
    reason = (form.get("reason") or [""])[0]
    text = (form.get("text") or [""])[0]
    notice_cls = '<p class="notice">{}</p>\n'
    try:
        done = await file_report(db, request, club.slug, reason, text, None) if len(raw) <= FORM_MAX else None
        if len(raw) > FORM_MAX:
            raise HTTPException(400, "too_large")
    except HTTPException as exc:
        if exc.status_code == 429:
            return _report_page(request, page, club, notice_cls.format(esc(page.t["report_too_many"])), "",
                                status_code=429)
        return _report_page(request, page, club, notice_cls.format(esc(page.t["report_invalid"])),
                            _form(page, club, reason, text[:1000]), status_code=400)
    if done is None:
        return page.not_found(request)
    return _report_page(request, page, club, f'<p>{esc(page.t["report_done"])}</p>\n', "")
