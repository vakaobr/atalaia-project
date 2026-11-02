# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The privacy notice the operator published (decisions CONS-1 to CONS-6; S17-16).

    GET /api/v1/privacy-notice?lang=   public: ``{version, lang, requested_lang, available, markdown, html, url}``

The text is the operator's Markdown file for ``ATALAIA_PRIVACY_NOTICE_VERSION`` in the language asked for (``lang``,
else ``Accept-Language``, else the default), else in another language the version has (``lang`` says which, so a
client can tell); ``html`` is the same text rendered by the server (everything escaped), ``url`` the public page. 404
``privacy_notice_not_published`` when no file exists for the current version. The app shows it before an account is
made (``POST /api/v1/auth/register`` takes ``notice_version`` so a notice that changed in between is refused with 409
``notice_version_changed``), and again to an account that was last shown another version (``GET /api/v1/me``,
``POST /api/v1/me/notice``). An account rests on the contract, not on consent (LEG-*): the notice is information
(GDPR Art. 13), and what the server records is which version was shown.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from .. import privacy_notice
from ..web import i18n
from ..web.field_pages import base_url

router = APIRouter(prefix="/api/v1", tags=["privacy notice"])
CACHE = "public, max-age=60"


@router.get("/privacy-notice")
async def get_privacy_notice(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    wanted, _, _ = i18n.for_request(request, auto=i18n.choose)
    notice = privacy_notice.load(settings.privacy_notice_dir, settings.privacy_notice_version, wanted,
                                 settings.default_lang)
    if notice is None:
        raise HTTPException(404, "privacy_notice_not_published")
    return JSONResponse({
        "version": notice.version, "lang": notice.lang, "requested_lang": wanted, "available": list(notice.available),
        "markdown": notice.markdown, "html": privacy_notice.render(notice.markdown),
        "url": f"{base_url(request)}/privacy?lang={notice.lang}",
    }, headers={"Cache-Control": CACHE, "Vary": "Accept-Language"})
