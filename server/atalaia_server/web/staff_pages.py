# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field staff's pages (Phase 4 follow-up, decisions FU2-1 to FU2-12): pages for the APIs that had none.

    GET /staff/                                        the fields the account has a role on
    GET /staff/login                                   log in: password (then the TOTP code), a passkey, or Google,
                                                       Microsoft or Apple (decisions LG-*; what the server offers
                                                       comes from GET /api/v1/auth/methods); a session that logged
                                                       in with no second factor is offered the TOTP or passkey
                                                       step-up on every page (static/staff/stepup.js)
    GET /staff/account                                 the logged-in account's own login methods: link or unlink
                                                       Google, Microsoft or Apple, add, rename and remove passkeys,
                                                       set, change or remove the password, turn TOTP on or off,
                                                       and the confirmation those ask for (decisions ACC-*); linked
                                                       from every page's header
    GET /staff/fields/<field>/history                  the field's games, filters, the history settings
    GET /staff/fields/<field>/games/<game>             one game: its score timeline, its event log, its boxes
    GET /staff/fields/<field>/schedule                 the field's scheduled games: create, edit, publish, cancel,
                                                       delete a draft (Phase 4 follow-up FU6)
    GET /staff/fields/<field>/schedule/<id>/registrations   who registered for a game: change a name, a team, a
                                                       federation number or the replicas, move, withdraw or
                                                       restore a registration, note who paid, mark a no-show
                                                       after the game, the list's import and CSV export (FU7)
    GET /staff/fields/<field>/schedule/<id>/roster     the game-day roster as the controller pulls it, printable,
                                                       and when a controller last pulled it
    GET /staff/fields/<field>/scenarios                the scenario library (archived ones on request)
    GET /staff/fields/<field>/scenarios/new            a new manifest: check (every problem shown), save
    GET /staff/fields/<field>/scenarios/<id>           one scenario: manifest, package, revisions, edit, archive
    GET /staff/fields/<field>/presets                  the field's game presets: add, change, delete
    GET /staff/fields/<field>/devices                  the field's boxes with their health flags
    GET /staff/fields/<field>/remote-gm                the remote GM: each controller's live view, the
                                                       commands, the remote GM log
    GET /staff/fields/<field>/atak                     the remote ATAK relay (Phase 4 follow-up FU5): issue a
                                                       device's certificate (its TAK data package, made in the
                                                       page from the API's answer), the field's certificates,
                                                       revoking one, the devices connected now, the log
    GET /staff/fields/<field>/roles                    who holds which role at the field: grant, revoke (FU9)
    GET /staff/fields/<field>/games/<game>/roles       the roles held in one game only
    GET /staff/fields/<field>/sync-keys                the controllers' API keys: labelled, fingerprint shown,
                                                       made and revoked (the key is shown once)
    GET /staff/fields/<field>/branding                 the field's name, accent colour, logo and wallpaper, and its
                                                       saved teams with their crests
    GET /staff/fields/<field>/platforms                the links to third-party platforms: on or off, configured
    GET /staff/fields/<field>/data                     the field's data export (a ZIP, with its SHA-256) and what it
                                                       uses of each hosted-mode limit (PKC-1)
    GET /staff/clubs, /staff/clubs/<club>              the account's clubs and invitations; one club, its images
                                                       and members (and a server administrator's moderation)
    GET /staff/firmware                                the firmware catalogue (add and withdraw: server administrator)
    GET /staff/admin                                   server administration: fields, the reports of clubs' pages
    GET /static/staff/<file>                           the pages' scripts and style sheet

How they work (FU2-1, FU2-2): each page is rendered here, in the field pages' languages (pt-PT, English,
German, Traditional Chinese for Taiwan) and chosen as they are (``?lang=``, else ``Accept-Language``),
with every text escaped, and holds **no data**: its script
(``static/staff/``, same-origin modules, which the content security policy's ``script-src 'self'``
already allows: no inline script, nothing from elsewhere) asks the API for it, with the access token in
``Authorization: Bearer`` as the app does. So every page has exactly its API's role rules (the field's
admin or gm, TOTP sessions only for the privileged roles; the remote GM's commands for the field's gm),
nothing here can drift from them, and a state-changing request can only come from a script on this
origin: no cookie authorises one, so there is nothing for a cross-site request to forge (FU2-3). The
refresh token stays the HttpOnly, SameSite=Strict cookie on ``/api/v1/auth/refresh``, which the script
calls with ``X-Atalaia-Refresh: 1``; the access token lives in the tab's ``sessionStorage`` (FU2-4). The
script writes every value with ``textContent`` and DOM nodes, never as HTML (FU2-5).

FU9 added the pages for the APIs that still had none (roles, sync keys, branding and clubs, platform links, the
firmware catalogue, server administration; decisions FU9-1 to FU9-7) by the same rules, and the remote GM's view is
pushed to the browser (server-sent events, ``GET .../remote-gm/stream``) with the polling kept as the fallback.

The pages are ``no-store`` and ``noindex``; a page whose path names no valid field, game or scenario id
is a 404. The texts are in ``staff_i18n.py``.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from .. import firmware, sync
from ..api import fields as fields_api
from ..history_models import DEFAULT_RETENTION_DAYS, MAX_DELAY_S, MIN_RETENTION_DAYS
from ..services import branding as branding_svc
from ..services import devices
from . import i18n, preview_texts
from .field_pages import GET_HEAD, HERE, HTML_TYPE, STARTED, answer, esc, switcher
from .staff_i18n import STRINGS

router = APIRouter(include_in_schema=False)

STATIC = HERE / "static" / "staff"
TEMPLATE_DIR = HERE / "templates" / "staff"
NO_STORE = "no-store"
SCENARIO_ID = re.compile(r"[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+")
STATIC_NAME = re.compile(r"[a-z][a-z0-9_]*\.(js|css)")
STATIC_TYPES = {"js": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8"}
REMOTE_POLL_S = 5
DEVICE_DAYS = (7, 30, 90, 365, devices.MAX_DEVICE_DAYS)
HTML_LANG = {**i18n.TAGS, "pt": "pt-PT"}
assert set(STRINGS) == set(i18n.LANGUAGES)


def _template(path: Path) -> Template:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return Template("".join(line for line in lines if not line.startswith("<!-- SPDX-")))


TEMPLATES = {p.stem: _template(p) for p in sorted(TEMPLATE_DIR.glob("*.html"))}
# The scripts and the style sheet, read once: only these names are served.
FILES = {p.name: p.read_bytes() for p in sorted(STATIC.iterdir()) if STATIC_NAME.fullmatch(p.name)}


def strings_block(strings: dict[str, str]) -> str:
    """The texts as JSON inside ``<script type="application/json">``, which no text can close or break (it is
    data: the content security policy runs no inline script, and this is not one)."""
    text = json.dumps(strings, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


class StaffPage:
    """One staff page: its language, its texts, its links."""

    def __init__(self, request: Request) -> None:
        self.lang, self.explicit, self.remember = i18n.for_request(request)
        self.t = STRINGS[self.lang]
        self.path = request.url.path

    def link(self, path: str) -> str:
        return f"{path}?lang={self.lang}" if self.explicit else path

    def languages(self) -> str:
        return switcher(self.lang, self.path)

    def sections(self, field: Optional[uuid.UUID], current: str) -> str:
        """The navigation: every field, and on a field's pages that field's sections (the script hides those
        the account's roles do not reach; the API refuses them anyway)."""
        items = [("fields", "/staff/", "nav_fields")]
        if field is not None:
            base = f"/staff/fields/{field}"
            items += [("history", f"{base}/history", "nav_history"), ("schedule", f"{base}/schedule", "nav_schedule"),
                      ("scenarios", f"{base}/scenarios", "nav_scenarios"),
                      ("presets", f"{base}/presets", "nav_presets"), ("devices", f"{base}/devices", "nav_devices"),
                      ("remote", f"{base}/remote-gm", "nav_remote"), ("atak", f"{base}/atak", "nav_atak"),
                      ("roles", f"{base}/roles", "nav_roles"), ("synckeys", f"{base}/sync-keys", "nav_synckeys"),
                      ("branding", f"{base}/branding", "nav_branding"),
                      ("platforms", f"{base}/platforms", "nav_platforms"), ("data", f"{base}/data", "nav_data")]
        # Not of one field: any account's clubs, the firmware list, the server administrator's page.
        items += [("clubs", "/staff/clubs", "nav_clubs"), ("firmware", "/staff/firmware", "nav_firmware"),
                  ("admin", "/staff/admin", "nav_admin")]
        out = []
        for name, href, label in items:
            here = ' aria-current="page"' if name == current else ""
            out.append(f'<li data-section="{name}"><a href="{esc(self.link(href))}"{here}>{esc(self.t[label])}</a></li>')
        return "<ul>" + "".join(out) + "</ul>"

    def texts(self, **extra: str) -> dict[str, str]:
        """Every text, escaped, for a template's ``$name``; ``extra`` values are HTML already."""
        return {**{k: esc(v) for k, v in self.t.items()}, **extra}

    def render(self, request: Request, page: str, title: str, content: str, *, field: Optional[uuid.UUID] = None,
               section: str = "", data: Optional[dict[str, str]] = None, status_code: int = 200) -> Response:
        attrs = {"page": page, "lang": self.lang, "explicit": "1" if self.explicit else "", **(data or {})}
        if field is not None:
            attrs["field"] = str(field)
        body = TEMPLATES["staff"].substitute(
            self.texts(),
            html_lang=HTML_LANG[self.lang], title=esc(f"{title} · {self.t['site']}"), script=esc(f"{page}.js"),
            data_attrs=" ".join(f'data-{k}="{esc(v)}"' for k, v in attrs.items()),
            home=esc(self.link("/staff/")), account_href=esc(self.link("/staff/account")),
            sections=self.sections(field, section),
            language_label=esc(i18n.STRINGS[self.lang]["language"]), languages=self.languages(),
            content=content, strings=strings_block(self.t))
        body = preview_texts.inject_banner(request, body, self.lang)  # a preview server's banner (PV-3)
        response = answer(request, body, HTML_TYPE, datetime.now(timezone.utc), NO_STORE, status_code=status_code,
                          extra={"Content-Language": i18n.TAGS[self.lang], "Vary": "Accept-Language, Cookie",
                                 "X-Robots-Tag": "noindex"})
        if self.remember:  # the visitor chose a language: keep it while they browse (decision PV-9)
            i18n.remember(response, self.lang)
        return response

    def not_found(self, request: Request) -> Response:
        content = f'<h1>{esc(self.t["err_not_found"])}</h1>\n'
        return self.render(request, "notfound", self.t["err_not_found"], content, status_code=404)


def _uuid(text: str) -> Optional[uuid.UUID]:
    try:
        return uuid.UUID(text)
    except ValueError:
        return None


def _field_page(request: Request, field_text: str, page: str, section: str, title_key: str,
                data: Optional[dict[str, str]] = None, **values: str) -> Response:
    p = StaffPage(request)
    field = _uuid(field_text)
    if field is None:
        return p.not_found(request)
    base = f"/staff/fields/{field}"
    links = {"history_href": esc(p.link(f"{base}/history")), "scenarios_href": esc(p.link(f"{base}/scenarios")),
             "new_href": esc(p.link(f"{base}/scenarios/new")), "schedule_href": esc(p.link(f"{base}/schedule"))}
    if data and "game" in data:
        links["game_roles_href"] = esc(p.link(f"{base}/games/{data['game']}/roles"))
    content = TEMPLATES[page].substitute(p.texts(**links, **values))
    return p.render(request, page, p.t[title_key], content, field=field, section=section, data=data)


@router.api_route("/static/staff/{name}", methods=GET_HEAD)
async def static_file(name: str, request: Request) -> Response:
    data = FILES.get(name)
    if data is None:
        return Response(status_code=404, headers={"Cache-Control": NO_STORE})
    media = STATIC_TYPES[name.rsplit(".", 1)[1]]
    # Revalidated each time (ETag, 304): a new server's scripts are never mixed with an old page.
    return answer(request, data.decode("utf-8"), media, STARTED, "no-cache")


@router.api_route("/staff", methods=GET_HEAD)
async def staff_redirect(request: Request) -> Response:
    query = f"?{request.url.query}" if request.url.query else ""
    return RedirectResponse(f"/staff/{query}", status_code=308)


@router.api_route("/staff/", methods=GET_HEAD)
async def home(request: Request) -> Response:
    p = StaffPage(request)
    content = TEMPLATES["home"].substitute(p.texts())
    preview = {"preview": "1"} if request.app.state.settings.preview else None  # the feedback link (PV-8)
    return p.render(request, "home", p.t["home_title"], content, section="fields", data=preview)


@router.api_route("/staff/login", methods=GET_HEAD)
async def login(request: Request) -> Response:
    p = StaffPage(request)
    content = TEMPLATES["login"].substitute(p.texts())
    return p.render(request, "login", p.t["login_title"], content)


@router.api_route("/staff/account", methods=GET_HEAD)
async def account(request: Request) -> Response:
    p = StaffPage(request)
    content = TEMPLATES["account"].substitute(p.texts())
    return p.render(request, "account", p.t["acct_title"], content, section="account")


@router.api_route("/staff/fields/{field}/history", methods=GET_HEAD)
async def history(field: str, request: Request) -> Response:
    t = STRINGS[StaffPage(request).lang]
    return _field_page(request, field, "history", "history", "history_title",
                       spectator_delay_label=esc(t["spectator_delay"].format(max=MAX_DELAY_S)),
                       retention_label=esc(t["retention_days"].format(min=MIN_RETENTION_DAYS,
                                                                      max=DEFAULT_RETENTION_DAYS)),
                       max_delay=str(MAX_DELAY_S), min_retention=str(MIN_RETENTION_DAYS),
                       max_retention=str(DEFAULT_RETENTION_DAYS))


@router.api_route("/staff/fields/{field}/games/{game}", methods=GET_HEAD)
async def game(field: str, game: str, request: Request) -> Response:
    game_id = _uuid(game)
    if game_id is None:
        return StaffPage(request).not_found(request)
    return _field_page(request, field, "game", "history", "game_title", data={"game": str(game_id)})


@router.api_route("/staff/fields/{field}/schedule", methods=GET_HEAD)
async def schedule(field: str, request: Request) -> Response:
    return _field_page(request, field, "schedule", "schedule", "schedule_title")


@router.api_route("/staff/fields/{field}/schedule/{game}/registrations", methods=GET_HEAD)
async def registrations(field: str, game: str, request: Request) -> Response:
    game_id = _uuid(game)
    if game_id is None:
        return StaffPage(request).not_found(request)
    return _field_page(request, field, "registrations", "schedule", "regs_title", data={"game": str(game_id)})


@router.api_route("/staff/fields/{field}/schedule/{game}/roster", methods=GET_HEAD)
async def roster(field: str, game: str, request: Request) -> Response:
    game_id = _uuid(game)
    if game_id is None:
        return StaffPage(request).not_found(request)
    return _field_page(request, field, "roster", "schedule", "roster_title", data={"game": str(game_id)})


@router.api_route("/staff/fields/{field}/scenarios", methods=GET_HEAD)
async def scenarios(field: str, request: Request) -> Response:
    return _field_page(request, field, "scenarios", "scenarios", "scenarios_title")


@router.api_route("/staff/fields/{field}/scenarios/new", methods=GET_HEAD)
async def scenario_new(field: str, request: Request) -> Response:
    t = STRINGS[StaffPage(request).lang]
    return _field_page(request, field, "scenario", "scenarios", "new_scenario", data={"scenario": ""},
                       heading=esc(t["new_scenario"]))


@router.api_route("/staff/fields/{field}/scenarios/{scenario}", methods=GET_HEAD)
async def scenario(field: str, scenario: str, request: Request) -> Response:
    if len(scenario) > 40 or not SCENARIO_ID.fullmatch(scenario):
        return StaffPage(request).not_found(request)
    return _field_page(request, field, "scenario", "scenarios", "scenario_title", data={"scenario": scenario},
                       heading=esc(scenario))


@router.api_route("/staff/fields/{field}/presets", methods=GET_HEAD)
async def presets(field: str, request: Request) -> Response:
    return _field_page(request, field, "presets", "presets", "presets_title")


@router.api_route("/staff/fields/{field}/devices", methods=GET_HEAD)
async def field_devices(field: str, request: Request) -> Response:
    t = STRINGS[StaffPage(request).lang]
    options = "".join(f'<option value="{d}"{" selected" if d == devices.DEVICE_DAYS else ""}>'
                      f'{esc(t["days_n"].format(n=d))}</option>' for d in DEVICE_DAYS)
    intro = t["devices_intro"].format(pct=devices.BATTERY_LOW_PCT, s=devices.SILENT_S)
    return _field_page(request, field, "devices", "devices", "devices_title", day_options=options,
                       devices_intro_text=esc(intro))


@router.api_route("/staff/fields/{field}/remote-gm", methods=GET_HEAD)
async def remote_gm(field: str, request: Request) -> Response:
    t = STRINGS[StaffPage(request).lang]
    return _field_page(request, field, "remote", "remote", "remote_title", data={"poll": str(REMOTE_POLL_S)},
                       remote_intro_text=esc(t["remote_intro"].format(s=REMOTE_POLL_S)))


@router.api_route("/staff/fields/{field}/atak", methods=GET_HEAD)
async def atak(field: str, request: Request) -> Response:
    return _field_page(request, field, "atak", "atak", "atak_title")


@router.api_route("/staff/fields/{field}/games/{game}/roles", methods=GET_HEAD)
async def game_roles(field: str, game: str, request: Request) -> Response:
    game_id = _uuid(game)
    field_id = _uuid(field)
    if game_id is None or field_id is None:
        return StaffPage(request).not_found(request)
    href = esc(StaffPage(request).link(f"/staff/fields/{field_id}/games/{game_id}"))
    return _field_page(request, field, "gameroles", "history", "gameroles_title", data={"game": str(game_id)},
                       game_href=href)


@router.api_route("/staff/fields/{field}/roles", methods=GET_HEAD)
async def roles(field: str, request: Request) -> Response:
    return _field_page(request, field, "roles", "roles", "roles_title")


@router.api_route("/staff/fields/{field}/sync-keys", methods=GET_HEAD)
async def sync_keys(field: str, request: Request) -> Response:
    t = STRINGS[StaffPage(request).lang]
    return _field_page(request, field, "synckeys", "synckeys", "keys_title",
                       keys_intro_text=esc(t["keys_intro"].format(n=sync.MAX_LIVE_KEYS)),
                       label_max=str(fields_api.SYNC_LABEL_MAX))


@router.api_route("/staff/fields/{field}/branding", methods=GET_HEAD)
async def branding(field: str, request: Request) -> Response:
    return _field_page(request, field, "branding", "branding", "branding_title",
                       field_name_max=str(branding_svc.FIELD_NAME_MAX), team_name_max=str(branding_svc.TEAM_NAME_MAX),
                       team_colour_max=str(branding_svc.TEAM_COLOUR_MAX))


@router.api_route("/staff/fields/{field}/platforms", methods=GET_HEAD)
async def platforms(field: str, request: Request) -> Response:
    return _field_page(request, field, "platforms", "platforms", "platforms_title")


@router.api_route("/staff/fields/{field}/data", methods=GET_HEAD)
async def data(field: str, request: Request) -> Response:
    return _field_page(request, field, "data", "data", "data_title")


def _page(request: Request, page: str, section: str, title_key: str, data: Optional[dict[str, str]] = None,
          **values: str) -> Response:
    """A page that is not one field's (clubs, firmware, server administration)."""
    p = StaffPage(request)
    content = TEMPLATES[page].substitute(p.texts(**values))
    return p.render(request, page, p.t[title_key], content, section=section, data=data)


def _club_limits() -> dict[str, str]:
    return {"club_name_max": str(branding_svc.CLUB_NAME_MAX), "team_name_max": str(branding_svc.TEAM_NAME_MAX),
            "club_description_max": str(branding_svc.CLUB_DESCRIPTION_MAX)}


@router.api_route("/staff/clubs", methods=GET_HEAD)
async def clubs(request: Request) -> Response:
    return _page(request, "clubs", "clubs", "clubs_title", **_club_limits())


@router.api_route("/staff/clubs/{club}", methods=GET_HEAD)
async def club(club: str, request: Request) -> Response:
    club_id = _uuid(club)
    if club_id is None:
        return StaffPage(request).not_found(request)
    p = StaffPage(request)
    return _page(request, "club", "clubs", "club_title", data={"club": str(club_id)},
                 clubs_href=esc(p.link("/staff/clubs")), **_club_limits())


@router.api_route("/staff/firmware", methods=GET_HEAD)
async def firmware_page(request: Request) -> Response:
    options = "".join(f'<option value="{esc(name)}">{esc(name)}</option>' for name in firmware.PLATFORM_NAMES)
    return _page(request, "firmware", "firmware", "fw_title", platform_options=options)


@router.api_route("/staff/admin", methods=GET_HEAD)
async def admin(request: Request) -> Response:
    options = "".join(f'<option value="{esc(name)}">{esc(StaffPage(request).t["field_type_" + name])}</option>'
                      for name in fields_api.FIELD_TYPES)
    zone = fields_api.FieldIn.model_fields["timezone"].default
    return _page(request, "admin", "admin", "admin_title", type_options=options, default_zone=esc(zone))


def page_names() -> list[str]:
    """The pages that have a script (for the tests)."""
    return [name for name in TEMPLATES if name != "staff"]


__all__ = ["FILES", "STRINGS", "TEMPLATES", "page_names", "router", "strings_block"]
