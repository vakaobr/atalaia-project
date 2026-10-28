# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What lets the phone's app and this site trust each other (decision PKA-1).

    GET /.well-known/assetlinks.json              Android's Digital Asset Links: the app may open this site's links
                                                  and use its passkeys (ATALAIA_APP_ANDROID_PACKAGE and _SHA256)
    GET /.well-known/apple-app-site-association   iOS: the same for the iOS app (ATALAIA_APP_IOS_APP_IDS)
    GET /app/oidc                                 where a social login that the app began returns to; the phone
                                                  opens it in the app, so a browser only ever sees this short page

Each file is ``404`` until its settings are given: a server with no app of its own says nothing about one. They
are public by nature (the phone fetches them without credentials) and say nothing a published app does not.
The ``/app/oidc`` page carries no script and reads nothing: the ticket after ``#`` stays in the browser's address.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .auth import NO_STORE
from .login_methods import APP_RETURN

router = APIRouter(tags=["app links"])

CACHE = {"Cache-Control": "public, max-age=3600"}
APP_PATHS = "/app/*"

RETURN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Atalaia</title></head>
<body>
<h1>Atalaia</h1>
<p>This link finishes a sign-in that began in the Atalaia app. Open it on the phone that has the app, and it
opens there on its own.</p>
<p>Este link conclui um início de sessão feito na app Atalaia. Abre-o no telemóvel que tem a app e abre-se lá
sozinho.</p>
</body></html>
"""


@router.get("/.well-known/assetlinks.json")
async def assetlinks(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    if settings.app_android_package is None:
        raise HTTPException(404, "not_found")
    return JSONResponse([{
        "relation": ["delegate_permission/common.handle_all_urls", "delegate_permission/common.get_login_creds"],
        "target": {"namespace": "android_app", "package_name": settings.app_android_package,
                   "sha256_cert_fingerprints": list(settings.app_android_sha256)},
    }], headers=CACHE)


@router.get("/.well-known/apple-app-site-association")
async def apple_app_site_association(request: Request) -> JSONResponse:
    ids = request.app.state.settings.app_ios_app_ids
    if not ids:
        raise HTTPException(404, "not_found")
    body: dict[str, Any] = {
        "applinks": {"details": [{"appIDs": list(ids), "components": [{"/": APP_PATHS}]}]},
        "webcredentials": {"apps": list(ids)},
    }
    return JSONResponse(body, headers=CACHE)


@router.get(APP_RETURN)
async def app_oidc_return() -> HTMLResponse:
    return HTMLResponse(RETURN_PAGE, headers={**NO_STORE, "Referrer-Policy": "no-referrer"})
