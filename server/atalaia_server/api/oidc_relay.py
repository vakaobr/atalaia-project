# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hub-level social login callback of hosted mode (decision LG-14, ADR-P4-13).

    GET /api/v1/auth/oidc/callback      on the hub's own host only, when ATALAIA_OIDC_RELAY=on

Google, Microsoft and Apple each need every redirect address registered exactly, so a hub with a hundred fields
(and custom host names) would mean a hundred registrations per provider. With the relay on, every field sends the
provider the hub's one address, and the provider's answer comes here first. The hub:

1. checks the ``state`` it signed when the field started the login (HMAC with its own key; the field's slug, the
   provider and an expiry are inside; ten minutes);
2. looks the slug up in the **tenant registry** (one row of ``public.atalaia_tenants``, no field data, no field's
   database role) and refuses a field that does not exist or is suspended;
3. answers ``303`` to the field's own callback, on a host read from that registry row: ``<slug>.<hub domain>``, or
   the field's custom host name when the login started there and the name is still on. No part of the target comes
   from the query, so the relay cannot be made an open redirect; only ``code`` (or ``error=denied``) and ``state``
   go on.

The relay holds no state and sees no token: the code is single use at the provider and bound to the PKCE verifier
only the field has; the field's own callback (unchanged) checks the browser's binding cookie, deletes the login row
(single use), exchanges the code and validates the ID token and nonce. The field also re-reads the state's
signature and refuses one made for another field. Every refusal here is the same plain 400 page, so the relay does
not tell a prober which fields exist.
"""

from __future__ import annotations

from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .. import tenancy
from ..oidc import OidcError, read_relay_state
from .auth import NO_STORE

router = APIRouter(prefix="/api/v1", tags=["login methods"])

RELAY_PATH = "/api/v1/auth/oidc/callback"
HEADERS = {**NO_STORE, "Referrer-Policy": "no-referrer"}
REFUSED = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Atalaia</title></head>
<body><h1>Atalaia</h1>
<p lang="en">This sign-in link has expired or is not valid. Go back to the page you came from and start again.</p>
<p lang="pt-PT">Este link de entrada expirou ou não é válido. Volta à página de onde vieste e começa de novo.</p>
<p lang="de">Dieser Anmeldelink ist abgelaufen oder ungültig. Gehe zurück zu der Seite, von der du kamst, und beginne von vorn.</p>
<p lang="zh-TW">此登入連結已過期或無效。請回到你來的頁面，重新開始。</p>
</body></html>
"""


def _refused() -> Response:
    return HTMLResponse(REFUSED, status_code=400, headers=HEADERS)


@router.get("/auth/oidc/callback")
async def relay_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None,
                         error: Optional[str] = None) -> Response:
    settings = request.app.state.settings
    # Off, or reached by a field's host: not here (a field's own callback is per provider).
    if not (settings.hosted and settings.oidc_relay) or tenancy.current() is not None:
        return HTMLResponse("", status_code=404, headers=HEADERS)
    if not state:
        return _refused()
    try:
        routing = read_relay_state(request.app.state.keys.oidc_relay, state, request.app.state.clock())
    except OidcError:
        return _refused()
    if routing.provider not in request.app.state.oidc.clients:
        return _refused()
    try:
        tenant = await tenancy.lookup(request.app.state.engine, routing.slug)
    except Exception:  # noqa: BLE001  (the registry cannot be read: nothing is forwarded)
        return _refused()
    if tenant is None or tenant.status != "active":
        return _refused()
    host = tenant.host(settings.hosted_domain)
    if routing.custom and tenant.custom_host and tenant.custom_host_status == "active":
        host = tenant.custom_host
    query = {"state": state}
    if code and not error and len(code) <= 2048:
        query["code"] = code
    else:
        query["error"] = "denied"     # the provider's own words are never passed on
    return RedirectResponse(f"https://{host}/api/v1/auth/oidc/{routing.provider}/callback?{urlencode(query)}",
                            status_code=303, headers=HEADERS)
