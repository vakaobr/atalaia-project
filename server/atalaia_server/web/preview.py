# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A preview server's own pages (decisions PV-*): only with ``ATALAIA_PREVIEW=on``.

    GET  /                  the landing page: what the preview is, what to look at, how to leave feedback
    GET  /feedback          the feedback form (pt-PT, English, German, Traditional Chinese; ``?lang=``, else
                            ``Accept-Language``); ``?from=/some/path`` remembers the page the visitor came from
    POST /feedback          a visitor's feedback (form-encoded; no account, no cookie); 303 back to the form
    GET  /robots.txt        ``Disallow: /``
    GET  /staff/feedback    the server administrators' list of the feedback (a staff page: its script asks
                            ``GET /api/v1/admin/feedback``)

Every response of a preview server also carries ``X-Robots-Tag: noindex, nofollow, noarchive``
(``PreviewHeadersMiddleware``) and every HTML page the banner (``preview_texts.banner``).

The form is anonymous, so there is no session for a forged request to ride on; it is still guarded (PV-8):

- **A signed, timed token** in a hidden field (``HMAC-SHA256`` under a key derived from the secret key, with the
  time it was issued): refused when it is missing, forged, older than two hours or younger than three seconds,
  so a script that posts without reading the form first gets nothing.
- **Same-origin only:** a request with an ``Origin`` that is not this site's, or ``Sec-Fetch-Site`` ``cross-site``
  or ``same-site``, is refused (the content security policy's ``form-action 'self'`` already stops a form on this
  site from posting elsewhere).
- **A honeypot** field (hidden, ``website``): filled, the answer is the same "thank you" and nothing is stored.
- **Limits:** 5 messages an hour from one address and 300 a day in all (``Limits.feedback``), a body of at most
  16 KB, a message of at most 2000 characters, a contact of at most 200, no control characters, only the known
  kinds and roles.
- **Privacy:** the address is used for the limit in memory only; nothing about the visitor is stored but what
  they typed (``preview_models.py``).
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import parse_qs, quote, urlsplit

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__, demo_data
from ..audit import record
from ..db import get_session
from ..preview_models import (CONTACT_MAX, CONTACT_RETENTION, FEEDBACK_KINDS, FEEDBACK_WHO, MESSAGE_MAX,
                              PreviewFeedback)
from ..ratelimit import client_ip
from ..services.scheduling import ScheduleError, clean_line, clean_text
from . import i18n, preview_texts as pt, staff_pages
from .field_pages import GET_HEAD, Page, _load, esc

router = APIRouter(include_in_schema=False)

FORM_MAX = 16384          # bytes of a feedback form (2000 characters of Chinese are 6000 bytes)
TOKEN_MIN_AGE_S = 3
TOKEN_MAX_AGE_S = 2 * 3600
ROBOTS = "User-agent: *\nDisallow: /\n"
TEMPLATES = {name: _load(f"{name}.html") for name in ("preview_landing", "preview_feedback")}


# --- the headers ---------------------------------------------------------------------------------------------


class PreviewHeadersMiddleware:
    """``X-Robots-Tag: noindex`` on every HTTP response of a preview server (PV-3): a search engine that finds the
    address anyway still does not list it. It also adds the headers production's Caddy adds (``Caddyfile``), since a
    preview is served by a Cloudflare Tunnel straight to the server, with no Caddy (PV-5)."""

    HEADER = (b"x-robots-tag", b"noindex, nofollow, noarchive")
    EXTRA = ((b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"),
             (b"cross-origin-opener-policy", b"same-origin"), (b"x-permitted-cross-domain-policies", b"none"))

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_header(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                mine = {self.HEADER[0], *(k for k, _ in self.EXTRA)}
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in mine]
                message = {**message, "headers": kept + [self.HEADER, *self.EXTRA]}
            await send(message)

        await self.app(scope, receive, send_with_header)


# --- the form's token ----------------------------------------------------------------------------------------


def make_token(request: Request) -> str:
    issued = int(request.app.state.clock())
    mac = hmac.new(request.app.state.keys.feedback_form, f"feedback|{issued}".encode(), hashlib.sha256)
    return f"{issued}.{mac.hexdigest()[:32]}"


def token_state(request: Request, token: str) -> str:
    """``ok``, or why not: ``missing``, ``forged``, ``early`` (younger than 3 s) or ``old`` (older than 2 h)."""
    stamp, _, mac = token.partition(".")
    if not stamp.isdigit() or len(stamp) > 12 or not mac:
        return "missing" if not token else "forged"
    expected = hmac.new(request.app.state.keys.feedback_form, f"feedback|{int(stamp)}".encode(), hashlib.sha256)
    if not hmac.compare_digest(expected.hexdigest()[:32], mac):
        return "forged"
    age = request.app.state.clock() - int(stamp)
    if age < TOKEN_MIN_AGE_S:
        return "early"
    return "old" if age > TOKEN_MAX_AGE_S else "ok"


def same_origin(request: Request) -> bool:
    """False for a request a browser says came from another site (``Sec-Fetch-Site``) or whose ``Origin`` is
    neither this host nor the configured public address. Clients that send neither header (curl, tests) pass: the
    token is what they need."""
    site = request.headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        return False
    origin = request.headers.get("origin")
    if origin is None:
        return True
    host = urlsplit(origin).netloc.lower()
    allowed = {request.headers.get("host", "").lower()}
    public = request.app.state.settings.public_url
    if public:
        allowed.add(urlsplit(public).netloc.lower())
    return bool(host) and host in allowed


# --- pages ---------------------------------------------------------------------------------------------------


class PreviewPage(Page):
    """A page in the preview's four languages (the field pages have two)."""

    def __init__(self, request: Request) -> None:
        self.lang, self.explicit, self.remember = i18n.for_request(request, pt.LANGUAGES, pt.choose)
        self.t = pt.STRINGS[self.lang]
        self.path = request.url.path

    def languages(self) -> str:
        out = []
        extra = f"&from={quote(self.came_from, safe='/')}" if getattr(self, "came_from", "") else ""
        for lang in pt.LANGUAGES:
            name = esc(pt.LANGUAGE_NAMES[lang])
            if lang == self.lang:
                out.append(f'<span lang="{pt.HTML_LANG[lang]}" aria-current="true">{name}</span>')
            else:
                out.append(f'<a lang="{pt.HTML_LANG[lang]}" hreflang="{pt.HTML_LANG[lang]}" '
                           f'href="{esc(self.path)}?lang={lang}{esc(extra)}">{name}</a>')
        return " ".join(out)

    def site_link(self, path: str) -> str:
        """A link to a page with pt-PT and English only: the visitor's language if it has it, else English."""
        return f"{path}?lang={pt.page_language(self.lang)}"

    def render_page(self, request: Request, title: str, content: str, status_code: int = 200,
                    no_store: bool = False) -> Response:
        response = self.render(request, title, content, STARTED, status_code=status_code)
        if no_store:
            response.headers["Cache-Control"] = "no-store"
        return response


STARTED = datetime.now(timezone.utc)


def _from_path(value: Optional[str]) -> Optional[str]:
    return value if value and pt.FROM_PATH.fullmatch(value) else None


@router.api_route("/robots.txt", methods=GET_HEAD)
async def robots(request: Request) -> Response:
    return PlainTextResponse(ROBOTS, headers={"Cache-Control": "public, max-age=3600"})


@router.api_route("/", methods=GET_HEAD)
async def landing(request: Request) -> Response:
    page = PreviewPage(request)
    t = page.t
    field = f"/f/{demo_data.FIELD_SLUG}/"
    items = [
        (page.site_link(field), "li_field", "li_field_d"),
        (page.site_link(f"/f/{demo_data.FIELD_SLUG}/scoreboard"), "li_scoreboard", "li_scoreboard_d"),
        (page.site_link(f"/c/{demo_data.CLUB_SLUG}/"), "li_club", "li_club_d"),
        (f"/staff/login?lang={pt.page_language(page.lang)}", "li_staff", "li_staff_d"),
        (f"/feedback?lang={page.lang}", "li_feedback", "li_feedback_d"),
    ]
    rows = "".join(f'<li><a href="{esc(href)}">{esc(t[name])}</a>: {esc(t[desc])}</li>\n'
                   for href, name, desc in items)
    content = TEMPLATES["preview_landing"].substitute(
        heading=esc(t["landing_title"]), intro=esc(t["landing_intro"]), what=esc(t["what_title"]), items=rows,
        not_here=esc(t["not_here_title"]), not_here_text=esc(t["not_here_text"]), demo_note=esc(t["demo_note"]),
        project_url="https://atalaia-project.link/")
    return page.render_page(request, t["landing_title"], content)


def _form(page: PreviewPage, token: str, values: dict[str, str], notice: str = "") -> str:
    t = page.t
    kinds = "".join(
        f'<label><input type="radio" name="kind" value="{k}" required{" checked" if values.get("kind") == k else ""}> '
        f'{esc(t["kind_" + k])}</label>\n' for k in FEEDBACK_KINDS)
    who = '<option value="">' + esc(t["who_none"]) + "</option>" + "".join(
        f'<option value="{w}"{" selected" if values.get("who") == w else ""}>{esc(t["who_" + w])}</option>'
        for w in FEEDBACK_WHO)
    hint = t["fb_message_hint"].format(max=MESSAGE_MAX)
    contact_hint = t["fb_contact_hint"].format(days=CONTACT_RETENTION.days)
    return TEMPLATES["preview_feedback"].substitute(
        heading=esc(t["fb_title"]), intro=esc(t["fb_intro"]), notice=notice, action="/feedback",
        token=esc(token), lang=esc(page.lang), came_from=esc(values.get("page", "")),
        kind_legend=esc(t["fb_kind"]), kinds=kinds, who_label=esc(t["fb_who"]), who_options=who,
        message_label=esc(t["fb_message"]), message_hint=esc(hint), message_max=str(MESSAGE_MAX),
        message=esc(values.get("message", "")), contact_label=esc(t["fb_contact"]),
        contact_hint=esc(contact_hint), contact_max=str(CONTACT_MAX), contact=esc(values.get("contact", "")),
        honeypot=esc(t["fb_honeypot"]), send=esc(t["fb_send"]), privacy=esc(t["fb_privacy"]))


def _back(page: PreviewPage, came_from: Optional[str]) -> str:
    if not came_from:
        return ""
    href = f"{came_from}?lang={pt.page_language(page.lang)}" if came_from != "/" else f"/?lang={page.lang}"
    return f'<p><a href="{esc(href)}">{esc(page.t["fb_back"])}</a></p>\n'


@router.api_route("/feedback", methods=GET_HEAD)
async def feedback_form(request: Request) -> Response:
    page = PreviewPage(request)
    came_from = _from_path(request.query_params.get("from"))
    page.came_from = came_from or ""  # type: ignore[attr-defined]
    t = page.t
    if request.query_params.get("sent") == "1":
        again = f"/feedback?lang={page.lang}" + (f"&from={quote(came_from, safe='/')}" if came_from else "")
        content = (f'<h1>{esc(t["fb_title"])}</h1>\n<p class="notice" role="status">{esc(t["fb_done"])}</p>\n'
                   f'<p><a href="{esc(again)}">{esc(t["fb_again"])}</a></p>\n' + _back(page, came_from))
        return page.render_page(request, t["fb_title"], content, no_store=True)
    content = _form(page, make_token(request), {"page": came_from or ""}) + _back(page, came_from)
    return page.render_page(request, t["fb_title"], content, no_store=True)


async def _read_form(request: Request) -> Optional[dict[str, str]]:
    """The form's fields (first value of each), or None when the body is too large."""
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > FORM_MAX:
            return None
    parsed = parse_qs(bytes(raw).decode("utf-8", "replace"), keep_blank_values=True, max_num_fields=16)
    return {k: v[0] for k, v in parsed.items() if v}


def _notice(text: str) -> str:
    return f'<p class="notice" role="alert">{esc(text)}</p>\n'


@router.post("/feedback")
async def feedback_post(request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    page = PreviewPage(request)
    t = page.t
    if not same_origin(request) or not request.headers.get("content-type", "").startswith(
            "application/x-www-form-urlencoded"):
        return page.render_page(request, t["fb_title"], f'<h1>{esc(t["fb_title"])}</h1>\n{_notice(t["fb_refused"])}',
                                status_code=403, no_store=True)
    fields = await _read_form(request)
    if fields is None:
        return page.render_page(request, t["fb_title"], f'<h1>{esc(t["fb_title"])}</h1>\n{_notice(t["fb_invalid"].format(max=MESSAGE_MAX))}',
                                status_code=413, no_store=True)
    lang = fields.get("lang", "")
    if lang in pt.LANGUAGES:
        page.lang, page.t = lang, pt.STRINGS[lang]
        t = page.t
    came_from = _from_path(fields.get("from"))
    values = {"kind": fields.get("kind", ""), "who": fields.get("who", ""), "message": fields.get("message", "")[:MESSAGE_MAX * 2],
              "contact": fields.get("contact", "")[:CONTACT_MAX * 2], "page": came_from or ""}
    state = token_state(request, fields.get("t", ""))
    if state != "ok":
        # A real visitor gets a new form with their text kept; "early" is the bot's tell, but a fast typist
        # after a reload is possible, so all of them are told to send again.
        content = _form(page, make_token(request), values, _notice(t["fb_expired"]))
        return page.render_page(request, t["fb_title"], content, status_code=400, no_store=True)
    sent = f"/feedback?lang={page.lang}&sent=1" + (f"&from={quote(came_from, safe='/')}" if came_from else "")
    if fields.get("website", "") != "":  # the honeypot: a person never sees this field
        return Response(status_code=303, headers={"Location": sent, "Cache-Control": "no-store"})
    try:
        kind = values["kind"] if values["kind"] in FEEDBACK_KINDS else None
        who = values["who"] or None
        if who is not None and who not in FEEDBACK_WHO:
            kind = None
        message = clean_text(values["message"], "message", MESSAGE_MAX, required=True)
        contact = clean_line(values["contact"], "contact", CONTACT_MAX)
        if kind is None or message is None:
            raise ScheduleError("message_invalid")
    except ScheduleError:
        content = _form(page, make_token(request), values, _notice(t["fb_invalid"].format(max=MESSAGE_MAX)))
        return page.render_page(request, t["fb_title"], content, status_code=400, no_store=True)
    limits = request.app.state.limits
    wait = limits.feedback.hit(client_ip(request.scope)) or limits.feedback_total.hit("all")
    if wait:
        response = page.render_page(request, t["fb_title"], f'<h1>{esc(t["fb_title"])}</h1>\n{_notice(t["fb_too_many"])}',
                                    status_code=429, no_store=True)
        response.headers["Retry-After"] = str(wait)
        return response
    row = PreviewFeedback(kind=kind, who=who, message=message, contact=contact, page=came_from, lang=page.lang)
    db.add(row)
    await db.flush()
    record(db, "preview_feedback", None, resource="preview_feedback", resource_id=row.id,
           details={"kind": kind, "server": __version__})
    await db.commit()
    return Response(status_code=303, headers={"Location": sent, "Cache-Control": "no-store"})


@router.api_route("/staff/feedback", methods=GET_HEAD)
async def staff_feedback(request: Request) -> Response:
    p = staff_pages.StaffPage(request)
    content = staff_pages.TEMPLATES["feedback"].substitute(p.texts())
    return p.render(request, "feedback", p.t["feedback_title"], content, section="fields")


__all__ = ["PreviewHeadersMiddleware", "PreviewPage", "router"]
