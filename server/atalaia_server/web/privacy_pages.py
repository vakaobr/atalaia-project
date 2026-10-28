# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The privacy notice as a public page (decisions CONS-1 to CONS-6).

    GET /privacy       the operator's notice for ``ATALAIA_PRIVACY_NOTICE_VERSION`` in the language asked for
                       (``?lang=``, else ``Accept-Language``), as the field pages are: no script, nothing from
                       elsewhere; 404 when the operator has put no file there (``privacy_notice.py``)

The text is the operator's Markdown rendered by the server (every character escaped); only the page around it (title,
version, a line when the language asked for does not exist, footer) is in the project's four languages.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .. import privacy_notice
from . import i18n
from .consent_i18n import PUBLIC
from .field_pages import GET_HEAD, STARTED, Page, esc

router = APIRouter(include_in_schema=False)
assert set(PUBLIC) == set(i18n.LANGUAGES)


@router.api_route("/privacy", methods=GET_HEAD)
async def privacy_page(request: Request) -> Response:
    settings = request.app.state.settings
    page = Page(request)
    t = PUBLIC[page.lang]
    notice = privacy_notice.load(settings.privacy_notice_dir, settings.privacy_notice_version, page.lang,
                                 settings.default_lang)
    if notice is None:
        content = f"<h1>{esc(t['privacy_none_title'])}</h1>\n<p>{esc(t['privacy_none'])}</p>\n"
        response = page.render(request, t["privacy_none_title"], content, None, status_code=404,
                               footer=t["privacy_footer"])
        response.headers["Cache-Control"] = "no-store"
        return response
    names = i18n.LANGUAGE_NAMES
    shown = ""
    if notice.lang != page.lang:
        text = t["privacy_lang_fallback"].format(requested=names[page.lang], shown=names[notice.lang])
        shown = f'<p class="notice">{esc(text)}</p>\n'
    content = (shown + f'<p class="address">{esc(t["privacy_version"].format(version=notice.version))}</p>\n'
               f'<article class="privacy" lang="{i18n.TAGS[notice.lang]}">\n{privacy_notice.render(notice.markdown)}\n'
               "</article>\n")
    # The page's own language for its frame, the notice's for its text; modified: when the process started.
    return page.render(request, f"{t['privacy_title']} · {notice.version}", content, STARTED,
                       footer=t["privacy_footer"])
