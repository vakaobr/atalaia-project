# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registering for a game on the field's public pages, in a browser, without the app (decisions WREG-*, S16-9).

    GET /f/<slug>/games/<id>/register/web   log in (social login, a passkey, or the password when the server takes
                                            them), or make the account with a social login after the privacy notice
                                            and the 16-or-older box; then the registration form, the ticket (a QR code
                                            and its text, shown once, printable), and later the registration's state,
                                            changing or cancelling it, a new ticket, the way into the app
    GET /static/player/<file>               the page's script, its style sheet and the vendored QR code generator

The page is the staff pages' kind (FU2-1 to FU2-5), not the public pages' kind: rendered here in the field pages'
languages with every text escaped and **no data**, ``no-store`` and ``noindex``; its script (``static/player/``,
same-origin modules, so the content security policy's ``script-src 'self'`` holds: no inline script, nothing from
elsewhere) does everything through the API the app uses, with the access token in ``Authorization: Bearer``:

- the login is the staff login's (``/api/v1/auth/*``, the social login's binding cookie and fragment ticket, passkeys);
  a new account comes from a social login with ``notice_seen``, ``notice_version`` and ``age_confirmed``, checked by
  the server as for the app (LEG-*, CONS-4), and the account's notice record is the server's;
- the registration is ``POST /api/v1/fields/<field>/scheduled-games/<game>/registrations`` and the ``/me/registrations``
  routes: the same checks (window, places, the field's membership rule, the replicas' classes), the same records
  (``source`` ``site``, the audit entries) and the same ticket, whose secret only the answer holds;
- a notice that changed since the account last saw it is shown again (``static/staff/consent.js``, ``POST
  /api/v1/me/notice``), as on the staff pages.

So no request is authorised by a cookie alone and there is nothing for a cross-site request to forge (FU2-3, WREG-4):
the refresh cookie is HttpOnly, SameSite=Strict, sent only to ``/api/v1/auth/refresh`` with ``X-Atalaia-Refresh: 1``.
The page works only while the field's public page is on and the game is public (else the public pages' 404); whether
registration is open is the API's to say. The texts are in ``player_i18n.py`` plus the staff texts in ``SHARED``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..services import registration, scheduling as svc
from . import i18n, preview_texts
from .consent_i18n import STAFF as CONSENT
from .field_pages import (GET_HEAD, HERE, HTML_TYPE, STARTED, Page, answer, base_url, esc, notice_published,
                          privacy_link, switcher, _game_id)
from .player_i18n import STRINGS as OWN
from .staff_i18n import STRINGS as STAFF

router = APIRouter(include_in_schema=False)

STATIC = HERE / "static" / "player"
TEMPLATE_DIR = HERE / "templates" / "player"
NO_STORE = "no-store"
HTML_LANG = {**i18n.TAGS, "pt": "pt-PT"}
# The staff texts the page shares (the login, the refusals, the membership verdicts, the notice panel).
SHARED_PREFIXES = ("err_", "e_", "oidc_err_", "passkey_", "login_", "apd_", "reg_status_", "totp_")
SHARED_KEYS = ("loading", "username", "password", "or", "none", "logged_out")
# Only these files are served, read once (a vendored file keeps its upstream name: static/player/README.md).
STATIC_TYPES = {"register.js": "text/javascript; charset=utf-8", "player.css": "text/css; charset=utf-8",
                "qrcode.module.js": "text/javascript; charset=utf-8"}
FILES = {name: (STATIC / name).read_bytes() for name in STATIC_TYPES}
assert set(OWN) == set(i18n.LANGUAGES)


def _template(path: Path) -> Template:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return Template("".join(line for line in lines if not line.startswith("<!-- SPDX-")))


TEMPLATES = {p.stem: _template(p) for p in sorted(TEMPLATE_DIR.glob("*.html"))}


def strings_for(lang: str) -> dict[str, str]:
    """The page's texts: the shared staff ones, the notice panel's, then its own (which win)."""
    staff = STAFF[lang]
    shared = {k: v for k, v in staff.items() if k.startswith(SHARED_PREFIXES) or k in SHARED_KEYS}
    return {**shared, **CONSENT[lang], **OWN[lang]}


def strings_block(strings: dict[str, str]) -> str:
    """The texts as JSON in ``<script type="application/json">``: data, which the policy runs nothing of, and which no
    text can close (``<``, ``>`` and ``&`` escaped)."""
    text = json.dumps(strings, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


@router.api_route("/static/player/{name}", methods=GET_HEAD)
async def static_file(name: str, request: Request) -> Response:
    data = FILES.get(name)
    if data is None:
        return Response(status_code=404, headers={"Cache-Control": NO_STORE})
    # Revalidated each time (ETag, 304): a new server's script is never mixed with an old page.
    return answer(request, data.decode("utf-8"), STATIC_TYPES[name], STARTED, "no-cache")


@router.api_route("/f/{slug}/games/{name}/register/web", methods=GET_HEAD)
async def register_web(slug: str, name: str, request: Request, db: AsyncSession = Depends(get_session)) -> Response:
    public = Page(request)
    game_id = _game_id(name)
    field = await svc.public_field(db, slug)
    game = await svc.public_game(db, field.id, game_id) if field is not None and game_id is not None else None
    if field is None or game is None:
        response = public.not_found(request)
        response.headers["X-Robots-Tag"] = "noindex"
        return response
    lang, explicit, remember = public.lang, public.explicit, public.remember
    t = OWN[lang]
    texts = {k: esc(v) for k, v in strings_for(lang).items()}
    link = public.link
    site = base_url(request)
    app_link = "atalaia://register?" + urlencode({"site": site, "field": field.slug, "game": str(game.id)})
    notice = ""
    if notice_published(request):
        href = f"/privacy?lang={lang}" if explicit else "/privacy"
        notice = (f'<a id="notice-link" href="{esc(href)}" target="_blank" rel="noopener">'
                  f'{esc(t["w_notice_open"])}</a>')
    zone = field.timezone
    when = i18n.span(game.starts_at, game.ends_at, zone, lang) + i18n.paren(zone, lang)
    content = TEMPLATES["register_web"].substitute(
        texts, heading=esc(t["w_title"].format(game=game.title)), when=esc(when),
        game_url=esc(link(f"/f/{field.slug}/games/{game.id}")),
        back=esc(i18n.STRINGS[lang]["back_game"].format(game=game.title)),
        field_url=esc(link(f"/f/{field.slug}/")), app_link=esc(app_link),
        account_href=esc(f"/staff/account?lang={lang}" if explicit else "/staff/account"),
        notice_link=notice, name_max=str(registration.NAME_MAX), fed_max=str(registration.FEDERATION_MAX))
    attrs = {"page": "register_web", "lang": lang, "explicit": "1" if explicit else "", "slug": field.slug,
             "game": str(game.id), "field": str(field.id), "notice": "1" if notice else ""}
    body = TEMPLATES["player"].substitute(
        html_lang=HTML_LANG[lang], title=esc(f"{t['w_title'].format(game=game.title)} · {field.name}"),
        data_attrs=" ".join(f'data-{k}="{esc(v)}"' for k, v in attrs.items()),
        skip=esc(STAFF[lang]["skip"]), field_name=esc(field.name), field_url=esc(link(f"/f/{field.slug}/")),
        language_label=esc(i18n.STRINGS[lang]["language"]), languages=switcher(lang, request.url.path),
        noscript=esc(t["w_noscript"]), content=content, strings=strings_block(strings_for(lang)),
        footer=esc(i18n.STRINGS[lang]["footer"]) + privacy_link(request, lang, explicit))
    body = preview_texts.inject_banner(request, body, lang)  # a preview server's banner (PV-3)
    response = answer(request, body, HTML_TYPE, datetime.now(timezone.utc), NO_STORE,
                      extra={"Content-Language": i18n.TAGS[lang], "Vary": "Accept-Language, Cookie",
                             "X-Robots-Tag": "noindex"})
    if remember:  # the visitor chose a language: keep it while they browse (decision PV-9)
        i18n.remember(response, lang)
    return response


__all__ = ["FILES", "TEMPLATES", "router", "strings_for"]
