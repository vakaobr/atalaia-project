# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ways to log in besides a password: social login, passkeys, and the staff second factor (decisions LG-*).

    GET    /api/v1/auth/methods                        what this server offers (the login pages' buttons)
    POST   /api/v1/auth/oidc/{provider}/start          {purpose, consent?, notice_version?, return_to?, password?}: the provider's URL
    GET    /api/v1/auth/oidc/{provider}/browser        the app's browser starts here (PKA-1): sets the binding cookie
    GET    /api/v1/auth/oidc/{provider}/callback       where the provider sends the browser back (a field's own address)
    GET    /api/v1/auth/oidc/callback                  hosted hub only, ATALAIA_OIDC_RELAY=on: the hub's one address, see oidc_relay.py
    POST   /api/v1/auth/oidc/complete                  {ticket}: a finished social login becomes a session
    POST   /api/v1/auth/passkey/login/options          a passkey login needs no username
    POST   /api/v1/auth/passkey/login                  {challenge_token, credential}: a session with both factors
    POST   /api/v1/auth/stepup/totp                    Bearer, {code}: this session now counts as having a second factor
    POST   /api/v1/auth/stepup/passkey/options         Bearer
    POST   /api/v1/auth/stepup/passkey                 Bearer, {challenge_token, credential}
    GET    /api/v1/me/login-methods                    Bearer: the password, the social logins, the passkeys
    DELETE /api/v1/me/identities/{provider}            Bearer, {password?}: unlink a social login
    POST   /api/v1/me/passkeys/options                 Bearer, {password?}
    POST   /api/v1/me/passkeys                         Bearer, {challenge_token, credential, name?}
    PATCH  /api/v1/me/passkeys/{id}                    Bearer, {name}
    DELETE /api/v1/me/passkeys/{id}                    Bearer, {password?}
    DELETE /api/v1/me/password                         Bearer, {password?}: log in without one

**Social login** (OpenID Connect, ``oidc.py``) is a redirect dance, so its state is kept on the server: one row
in ``oidc_logins`` per attempt (state, nonce, PKCE verifier; ten minutes; deleted by the callback, so one use
even with several workers), and a short-lived cookie in the browser, ``__Secure-atalaia_oidc`` (HttpOnly,
Secure, **SameSite=Lax**, only on ``/api/v1/auth/oidc``), whose hash the row holds. Lax is the one place the
server needs it: the provider's redirect back is a cross-site navigation, which a Strict cookie would not
accompany; Lax cookies go with top-level GET navigations only, and the callback is such a GET that changes
nothing without a state the attacker does not have. The cookie is what stops a login-CSRF: a callback URL made by
an attacker (their own code, their own state) is useless in a victim's browser, which has no cookie for that
state. A signed cookie holding the verifier would have needed the same cookie and left the single use to one
process's memory; the row is the simpler and the stronger choice. The callback finishes with a redirect to the
page that began the login, carrying a one-minute single-use signed ticket in the URL fragment (never sent to
a server or a referrer); the page sends it to ``/auth/oidc/complete``, a same-site call that makes the session
and sets the refresh cookie as every other login does, with the access token in the answer and no token ever in
a URL or a cookie the API reads.

A social login never sets ``sessions.mfa``: the roles that need a second factor count only after a TOTP or
passkey step-up (``/auth/stepup/*``). A passkey login sets it: it is something you have and something you are
or know in one gesture (user verification is required).

Accounts with no password (made by a social login, or after removing the password) confirm a sensitive change
with a proof from the last ten minutes: the session's ``confirmed_at``, set by every login and by a step-up
(TOTP, passkey) or a social re-login (``purpose: reauth``) (``api/auth._check_password``).
"""

from __future__ import annotations

import hashlib
import hmac
import html
import re
import secrets
import uuid
from datetime import timedelta
from typing import Any, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import passkeys, personal_data, quotas, tenancy
from ..audit import record
from ..auth import Principal, bearer, current_principal, principal_from_token
from ..db import get_session
from ..models import PRIVILEGED_ROLES, ROLE_NAMES, AuditLog, OidcLogin, Passkey, User, UserFieldRole, UserIdentity, UserSession
from ..oidc import (MAX_STATE, NAME_PROVIDERS, PROVIDER_LABELS, OidcError, make_relay_state, new_verifier, read_relay_state,
                    pkce_challenge, username_from_name)
from ..tokens import (TokenError, WebauthnChallenge, make_merge_ticket, make_oidc_ticket, make_webauthn_challenge, read_oidc_ticket,
                      read_webauthn_challenge)
from .auth import (NO_STORE, Strict, username_problem, _check_code, _check_password, _ip_key, _now, _secret, _start_session, _too_many,
                   _user_for_update, passkey_count)

router = APIRouter(prefix="/api/v1", tags=["login methods"])

BINDING_COOKIE = "__Secure-atalaia_oidc"
BINDING_PATH = "/api/v1/auth/oidc"
STATE_TTL_S = 600
DEFAULT_RETURN = "/staff/login"
RETURN_TO = re.compile(r"/staff/[A-Za-z0-9/_.?=&%-]{0,380}")
APP_RETURN = "/app/oidc"      # the app's own path on this host: an Android App Link or an iOS Universal Link
APP_RETURN_TO = re.compile(r"/app/oidc(?:\?[A-Za-z0-9_.=&%-]{0,380})?")


# Bodies ---------------------------------------------------------------------------------------------


class StartIn(Strict):
    purpose: Literal["login", "link", "reauth", "name"] = "login"
    consent: bool = False
    notice_version: Optional[str] = Field(default=None, max_length=64)  # the privacy notice the person was shown
    return_to: str = Field(default=DEFAULT_RETURN, max_length=400)
    password: str = Field(default="", max_length=4096)


class TicketIn(Strict):
    ticket: str = Field(max_length=2048)


class ConfirmIn(Strict):
    password: str = Field(default="", max_length=4096)


class ChallengeIn(Strict):
    challenge_token: str = Field(max_length=2048)
    credential: dict[str, Any]


class AddPasskeyIn(ChallengeIn):
    name: Optional[str] = Field(default=None, max_length=64)


class NameIn(Strict):
    name: str = Field(max_length=64)


class CodeIn(Strict):
    code: str = Field(max_length=16)


# Helpers --------------------------------------------------------------------------------------------


def site_origin(request: Request) -> str:
    """The address this site's pages are served from: ATALAIA_PUBLIC_URL, a hosted field's own host name (its custom
    one when the request came by it), else what the request says (a trial on this computer). It is the WebAuthn origin
    and the OpenID redirect URI's base, so ATALAIA_PUBLIC_URL should be set behind a proxy."""
    settings = request.app.state.settings
    if settings.public_url:
        return settings.public_url
    tenant = tenancy.current()
    if settings.hosted and tenant is not None:
        return f"https://{tenant.serving_host(settings.hosted_domain, request.headers.get('host', ''))}"
    return f"{request.url.scheme}://{request.url.netloc}"


def callback_url(request: Request, provider: str) -> str:
    """The redirect address the provider is given: the field's own, or (hosted mode with the relay on, LG-14) the
    hub's one, ``https://<hub domain>/api/v1/auth/oidc/callback``, the same for every field and provider."""
    settings = request.app.state.settings
    if relay_on(request):
        return f"https://{settings.hosted_domain}{BINDING_PATH}/callback"
    return f"{site_origin(request)}{BINDING_PATH}/{provider}/callback"


def relay_on(request: Request) -> bool:
    settings = request.app.state.settings
    return settings.hosted and settings.oidc_relay and tenancy.current() is not None


def new_state(request: Request, provider: str) -> str:
    """A random state; with the relay on, one the hub signed that names this field (and whether the login began at
    its custom host name), so the hub's callback can send the browser back here and nowhere else."""
    tenant = tenancy.current()
    if not relay_on(request) or tenant is None:
        return secrets.token_urlsafe(32)
    settings = request.app.state.settings
    custom = tenant.serving_host(settings.hosted_domain, request.headers.get("host", "")) != tenant.host(settings.hosted_domain)
    return make_relay_state(request.app.state.keys.oidc_relay, tenant.slug, provider, custom,
                            int(request.app.state.clock()) + STATE_TTL_S)


def safe_return_to(text: str, origin: Optional[str] = None) -> str:
    """A path on the staff pages (with its query), or the app's named path ``/app/oidc`` (PKA-1: the app asks
    for it as a link on this very host, which the phone opens in the app; ``origin`` is this site's address,
    so the full address of that link is read as its path), else the staff login: nothing else is a place to
    send a browser after a login (no other host, no protocol-relative address)."""
    if origin and text.startswith(f"{origin}{APP_RETURN}"):
        text = text[len(origin):]
    parts = urlsplit(text)
    if parts.scheme or parts.netloc or parts.fragment or "//" in text or "\\" in text \
            or not (RETURN_TO.fullmatch(text) or APP_RETURN_TO.fullmatch(text)):
        return DEFAULT_RETURN
    return text


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _provider(request: Request, name: str) -> str:
    if name not in PROVIDER_LABELS or name not in request.app.state.oidc.clients:
        raise HTTPException(404, "provider_not_configured")
    return name


async def optional_principal(request: Request, db: AsyncSession = Depends(get_session)) -> Optional[Principal]:
    token = bearer(request)
    principal = await principal_from_token(request, db, token) if token else None
    if principal is not None:
        request.state.principal = principal
    return principal


async def login_method_count(db: AsyncSession, request: Request, user: User, *, without_password: bool = False,
                             without_provider: Optional[str] = None,
                             without_passkey: Optional[uuid.UUID] = None) -> int:
    """How many ways the account can log in now: the password (when password login is on), each social login
    whose provider this server has configured, each passkey made for this host name."""
    settings = request.app.state.settings
    count = 1 if user.password_hash is not None and settings.password_login and not without_password else 0
    configured = [p for p in request.app.state.oidc.providers() if p != without_provider]
    if configured:
        count += await db.scalar(select(func.count()).select_from(UserIdentity).where(
            UserIdentity.user_id == user.id, UserIdentity.provider.in_(configured))) or 0
    rp = passkeys.rp_id_of(site_origin(request))
    keys = select(func.count()).select_from(Passkey).where(Passkey.user_id == user.id, Passkey.rp_id == rp)
    if without_passkey is not None:
        keys = keys.where(Passkey.id != without_passkey)
    return count + (await db.scalar(keys) or 0)


async def _needs_second_factor(db: AsyncSession, user: User) -> bool:
    """True for an account a role makes need a second factor (a server administrator, admin, gm, marshal)."""
    if user.server_admin:
        return True
    return bool(await db.scalar(select(func.count()).select_from(UserFieldRole).where(
        UserFieldRole.user_id == user.id, UserFieldRole.role_id.in_([ROLE_NAMES[r] for r in PRIVILEGED_ROLES]))))


def passkey_json(k: Passkey) -> dict[str, Any]:
    return {"id": str(k.id), "name": k.name, "backed_up": k.backed_up,
            "created_at": k.created_at.isoformat() if k.created_at else None,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}


def _back(return_to: str, *, ok: Optional[str] = None, error: Optional[str] = None,
          ticket: Optional[str] = None, fragment: Optional[dict[str, str]] = None) -> RedirectResponse:
    """The redirect to the page that began the login: ``?oidc=linked|reauth`` or ``?oidc_error=<code>`` in the query,
    a login's ticket (or a merge ticket, or the proposed username of the "use my name" round) in the fragment. The binding cookie is cleared: it is for one attempt."""
    parts = urlsplit(safe_return_to(return_to))
    query = [(k, v) for k, v in parse_qsl(parts.query) if k not in ("oidc", "oidc_error")]
    if ok:
        query.append(("oidc", ok))
    if error:
        query.append(("oidc_error", error))
    if ticket:
        fragment = {"oidc": ticket}
    url = urlunsplit(("", "", parts.path, urlencode(query), urlencode(fragment) if fragment else ""))
    response = RedirectResponse(url, status_code=303, headers={**NO_STORE, "Referrer-Policy": "no-referrer"})
    response.delete_cookie(BINDING_COOKIE, path=BINDING_PATH, secure=True, httponly=True, samesite="lax")
    return response


# What the server offers -----------------------------------------------------------------------------


@router.get("/auth/methods")
async def methods(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    return JSONResponse({"password_login": settings.password_login, "passkeys": True,
                         "oidc": [{"provider": p, "label": PROVIDER_LABELS[p]}
                                  for p in request.app.state.oidc.providers()]}, headers=NO_STORE)


@router.get("/me/login-methods")
async def my_methods(request: Request, principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    user = principal.user
    identities_list = list(await db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id)
                                            .order_by(UserIdentity.created_at)))
    identities = identities_list
    keys = await db.scalars(select(Passkey).where(Passkey.user_id == user.id).order_by(Passkey.created_at))
    settings = request.app.state.settings
    signed_up = await signup_provider(db, user.id)
    linked = {i.provider for i in identities_list}
    name_provider = ({"provider": signed_up, "label": PROVIDER_LABELS[signed_up]}
                     if signed_up in NAME_PROVIDERS and signed_up in linked
                     and signed_up in request.app.state.oidc.providers() else None)
    return JSONResponse({
        "username": user.username,
        "name_provider": name_provider,
        "password": {"set": user.password_hash is not None, "login_enabled": settings.password_login},
        "identities": [{"provider": i.provider, "label": PROVIDER_LABELS.get(i.provider, i.provider),
                        "linked_at": i.created_at.isoformat(),
                        "last_login_at": i.last_login_at.isoformat() if i.last_login_at else None}
                       for i in identities],
        "passkeys": [passkey_json(k) for k in keys],
        "totp_enabled": user.totp_enabled,
        "available_providers": [{"provider": p, "label": PROVIDER_LABELS[p]}
                                for p in request.app.state.oidc.providers()],
        "mfa": principal.mfa,
    }, headers=NO_STORE)


# Social login ---------------------------------------------------------------------------------------


@router.post("/auth/oidc/{provider}/start")
async def oidc_start(provider: str, body: StartIn, request: Request,
                     principal: Optional[Principal] = Depends(optional_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """The URL to send the browser to. ``login`` needs nothing; ``link`` (add this provider to the account) and
    ``reauth`` (prove it is you again, for an account with no password) need the bearer token, and ``link`` the
    account's confirmation as every sensitive change does."""
    _provider(request, provider)
    current = request.app.state.settings.privacy_notice_version
    if body.consent and body.notice_version is not None and body.notice_version != current:
        return JSONResponse({"detail": "notice_version_changed", "current_version": current}, status_code=409,
                            headers=NO_STORE)
    user_id: Optional[uuid.UUID] = None
    session_id: Optional[uuid.UUID] = None
    if body.purpose != "login":
        if principal is None:
            raise HTTPException(401, "not_authenticated", headers={"WWW-Authenticate": "Bearer"})
        user_id, session_id = principal.user.id, principal.session.id
        if body.purpose == "link":
            user = await _user_for_update(db, principal)
            await _check_password(db, request, user, body.password, "identity_link")
        if body.purpose == "name":
            await _check_name_round(db, request, principal, provider, body.return_to)
    now = _now()
    await db.execute(delete(OidcLogin).where(OidcLogin.expires_at < now))  # the ones never finished
    state, binding = new_state(request, provider), secrets.token_urlsafe(32)
    nonce, verifier = secrets.token_urlsafe(24), new_verifier()
    redirect_uri = callback_url(request, provider)
    db.add(OidcLogin(state_hash=_hash(state), binding_hash=_hash(binding), provider=provider, purpose=body.purpose,
                     user_id=user_id, session_id=session_id, nonce=nonce, code_verifier=verifier,
                     redirect_uri=redirect_uri, return_to=safe_return_to(body.return_to, site_origin(request)),
                     consent=body.consent, notice_version=body.notice_version if body.consent else None,
                     expires_at=now + timedelta(seconds=STATE_TTL_S)))
    await db.commit()
    url = request.app.state.oidc.authorization_url(provider, redirect_uri, state, nonce,
                                                   pkce_challenge(verifier), profile=body.purpose == "name")
    if APP_RETURN_TO.fullmatch(safe_return_to(body.return_to, site_origin(request))):
        # The app calls this itself, so the binding cookie would land in the app, not in the browser that goes
        # to the provider: the app opens this address in the browser, which sets the cookie there (PKA-1).
        query = urlencode({"x": binding, "s": state})
        return JSONResponse({"authorization_url": url,
                             "browser_url": f"{site_origin(request)}{BINDING_PATH}/{provider}/browser?{query}"},
                            headers=NO_STORE)
    response = JSONResponse({"authorization_url": url}, headers=NO_STORE)
    response.set_cookie(BINDING_COOKIE, binding, max_age=STATE_TTL_S, path=BINDING_PATH, secure=True, httponly=True,
                        samesite="lax")
    return response


async def signup_provider(db: AsyncSession, user_id: uuid.UUID) -> Optional[str]:
    """The provider whose login made the account, when a social login did (the ``register`` audit entry names it)."""
    details = await db.scalar(select(AuditLog.details).where(AuditLog.user_id == user_id, AuditLog.action == "register")
                              .order_by(AuditLog.id).limit(1))
    if isinstance(details, dict) and details.get("method") == "oidc" and details.get("provider") in PROVIDER_LABELS:
        return str(details["provider"])
    return None


async def _check_name_round(db: AsyncSession, request: Request, principal: Principal, provider: str,
                            return_to: str) -> None:
    """The "use my name" round (LG-10) is offered for the provider the account signed up with, never Apple, and
    only to the staff pages (the app has no such step)."""
    if provider not in NAME_PROVIDERS or await signup_provider(db, principal.user.id) != provider \
            or APP_RETURN_TO.fullmatch(safe_return_to(return_to, site_origin(request))):
        raise HTTPException(409, "name_not_offered")


BROWSER_GONE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Atalaia</title></head>
<body><h1>Atalaia</h1>
<p>This sign-in link has expired or is not valid. Go back to the Atalaia app and start again.</p>
<p>Este link de entrada expirou ou não é válido. Voltar à app Atalaia e começar de novo.</p>
</body></html>
"""
BROWSER_CONFIRM = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Atalaia</title></head>
<body><h1>Atalaia</h1>
<p>{en}</p>
<p>{pt}</p>
<p><a href="{href}">{provider} &rarr;</a></p>
</body></html>
"""


@router.get("/auth/oidc/{provider}/browser")
async def oidc_browser(provider: str, request: Request, x: str = "", s: str = "", go: str = "",
                       db: AsyncSession = Depends(get_session)) -> Response:
    """The app's way into a social login (PKA-1): its browser opens this address (from ``browser_url``, which only
    the app that started the login holds), and gets the binding cookie that ``start`` could not set in a browser;
    then it is sent on to the provider. A login goes straight on. A link or a reauth first says whose account
    it is for, and goes on only on a tap: an address made by someone else for their own account must not link
    the account of whoever opens it without their knowing."""
    gone = HTMLResponse(BROWSER_GONE, status_code=400, headers={**NO_STORE, "Referrer-Policy": "no-referrer"})
    if provider not in PROVIDER_LABELS or provider not in request.app.state.oidc.clients \
            or not s or len(s) > MAX_STATE or not x or len(x) > 128:
        return gone
    row = await db.scalar(select(OidcLogin).where(OidcLogin.state_hash == _hash(s), OidcLogin.provider == provider))
    if row is None or row.expires_at <= _now() or not hmac.compare_digest(_hash(x), row.binding_hash) \
            or not APP_RETURN_TO.fullmatch(row.return_to):
        return gone
    if row.purpose != "login" and go != "1":
        user = await db.get(User, row.user_id) if row.user_id else None
        if user is None:
            return gone
        who = html.escape(user.username)
        label = PROVIDER_LABELS[provider]
        what = {"link": (f"Link {label} to the account {who}, started in the Atalaia app?",
                         f"Ligar {label} à conta {who}, iniciado na app Atalaia?"),
                "reauth": (f"Confirm with {label} that you are the account {who}, started in the Atalaia app?",
                           f"Confirmar com {label} que és a conta {who}, iniciado na app Atalaia?")}[row.purpose]
        href = html.escape(f"?{urlencode({'x': x, 's': s, 'go': '1'})}")
        return HTMLResponse(BROWSER_CONFIRM.format(en=what[0], pt=what[1], href=href, provider=html.escape(label)),
                            headers={**NO_STORE, "Referrer-Policy": "no-referrer"})
    url = request.app.state.oidc.authorization_url(provider, row.redirect_uri, s, row.nonce,
                                                   pkce_challenge(row.code_verifier), profile=row.purpose == "name")
    response = RedirectResponse(url, status_code=303, headers={**NO_STORE, "Referrer-Policy": "no-referrer"})
    response.set_cookie(BINDING_COOKIE, x, max_age=STATE_TTL_S, path=BINDING_PATH, secure=True, httponly=True,
                        samesite="lax")
    return response


def _relay_state_is_ours(request: Request, provider: str, state: str) -> bool:
    """A state the hub signed (LG-14) is accepted only at the field and for the provider it names, and before its
    expiry: a result relayed for another field is refused here even if its login row somehow existed."""
    tenant = tenancy.current()
    try:
        routing = read_relay_state(request.app.state.keys.oidc_relay, state, request.app.state.clock())
    except OidcError:
        return False
    return tenant is not None and routing.slug == tenant.slug and routing.provider == provider


@router.get("/auth/oidc/{provider}/callback")
async def oidc_callback(provider: str, request: Request, code: Optional[str] = None, state: Optional[str] = None,
                        error: Optional[str] = None, db: AsyncSession = Depends(get_session)) -> RedirectResponse:
    if provider not in PROVIDER_LABELS or provider not in request.app.state.oidc.clients or not state \
            or len(state) > MAX_STATE:
        return _back(DEFAULT_RETURN, error="state_invalid")
    if state.startswith("r1.") and not _relay_state_is_ours(request, provider, state):
        return _back(DEFAULT_RETURN, error="state_invalid")
    row = (await db.execute(delete(OidcLogin).where(OidcLogin.state_hash == _hash(state),
                                                    OidcLogin.provider == provider).returning(OidcLogin)
                            .execution_options(synchronize_session=False))).scalar_one_or_none()
    await db.commit()  # the state is spent whatever happens next
    if row is None or row.expires_at <= _now():
        return _back(DEFAULT_RETURN, error="state_invalid")
    binding = request.cookies.get(BINDING_COOKIE, "")
    if not binding or len(binding) > 128 or not hmac.compare_digest(_hash(binding), row.binding_hash):
        return _back(row.return_to, error="state_invalid")
    if error or not code or len(code) > 2048:
        return _back(row.return_to, error="denied")
    oidc = request.app.state.oidc
    try:
        token = await oidc.exchange(provider, code, row.redirect_uri, row.code_verifier)
        claims = await oidc.validate_claims(provider, token, row.nonce)
        subject = claims["sub"]
    except OidcError as e:
        record(db, "oidc_failed", request, user_id=row.user_id, details={"provider": provider, "reason": e.code})
        await db.commit()
        return _back(row.return_to, error=e.code)
    if row.purpose == "name":
        return await _oidc_name(db, request, row, provider, subject, claims)
    handler = {"login": _oidc_login, "link": _oidc_link, "reauth": _oidc_reauth}[row.purpose]
    return await handler(db, request, row, provider, subject)


async def _oidc_login(db: AsyncSession, request: Request, row: OidcLogin, provider: str,
                      subject: str) -> RedirectResponse:
    identity = await db.scalar(select(UserIdentity).where(UserIdentity.provider == provider,
                                                          UserIdentity.subject == subject).with_for_update())
    now = _now()
    if identity is not None:
        user = await db.get(User, identity.user_id)
        if user is None:
            return _back(row.return_to, error="state_invalid")
        identity.last_login_at = now
        await db.commit()
        return _back(row.return_to, ticket=make_oidc_ticket(request.app.state.keys, user.id, provider))
    # An unknown subject makes an account, under the same rules as registering: consent given, the per-address
    # registration limit. Never matched to an existing account by email (the server never asks for one).
    if not row.consent:
        return _back(row.return_to, error="consent_required")
    current = request.app.state.settings.privacy_notice_version
    if row.notice_version is not None and row.notice_version != current:  # the notice changed during the round trip
        return _back(row.return_to, error="notice_version_changed")
    try:
        await quotas.check(db, "accounts", None)  # hosted mode: the field's account quota, as for registering
    except quotas.QuotaExceeded:
        return _back(row.return_to, error="quota_exceeded")
    limits, address = request.app.state.limits, _ip_key(request)
    if limits.register.retry_after(address):
        return _back(row.return_to, error="too_many_attempts")
    limits.register.fail(address)
    user = User(username=f"user-{secrets.token_hex(6)}", email=None, password_hash=None, gdpr_consent_at=now)
    db.add(user)
    try:
        await db.flush()
        db.add(UserIdentity(user_id=user.id, provider=provider, subject=subject, last_login_at=now))
        await db.flush()
    except IntegrityError:  # the same subject finished twice at once: the other one won
        await db.rollback()
        return _back(row.return_to, error="try_again")
    personal_data.give_consent(db, user.id, personal_data.ACCOUNT, row.notice_version or current, now)
    record(db, "register", request, user_id=user.id, resource="user", resource_id=user.id,
           details={"method": "oidc", "provider": provider})
    await db.commit()
    return _back(row.return_to, ticket=make_oidc_ticket(request.app.state.keys, user.id, provider, new_account=True))


async def _oidc_link(db: AsyncSession, request: Request, row: OidcLogin, provider: str,
                     subject: str) -> RedirectResponse:
    user = await db.scalar(select(User).where(User.id == row.user_id).with_for_update()) if row.user_id else None
    if user is None:
        return _back(row.return_to, error="state_invalid")
    existing = await db.scalar(select(UserIdentity).where(UserIdentity.provider == provider,
                                                          UserIdentity.subject == subject))
    if existing is not None and existing.user_id == user.id:
        return _back(row.return_to, error="already_linked")
    if await db.scalar(select(UserIdentity.id).where(UserIdentity.user_id == user.id,
                                                     UserIdentity.provider == provider)):
        return _back(row.return_to, error="provider_already_linked")
    if existing is not None:
        if APP_RETURN_TO.fullmatch(row.return_to):
            return _back(row.return_to, error="identity_taken")
        # The login belongs to another account: this round proved control of it, so the Account page may offer to
        # merge that account into this one (account_merge.py). Nothing changes until the person confirms there.
        ticket = make_merge_ticket(request.app.state.keys, user.id, existing.user_id, provider)
        record(db, "identity_link_taken", request, user_id=user.id, resource="user", resource_id=user.id,
               details={"provider": provider})
        await db.commit()
        return _back(row.return_to, ok="merge", fragment={"merge": ticket})
    db.add(UserIdentity(user_id=user.id, provider=provider, subject=subject))
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return _back(row.return_to, error="identity_taken")
    record(db, "identity_link", request, user_id=user.id, resource="user", resource_id=user.id,
           details={"provider": provider})
    await db.commit()
    return _back(row.return_to, ok="linked")


async def _oidc_reauth(db: AsyncSession, request: Request, row: OidcLogin, provider: str,
                       subject: str) -> RedirectResponse:
    mine = await db.scalar(select(UserIdentity.id).where(UserIdentity.provider == provider,
                                                         UserIdentity.subject == subject,
                                                         UserIdentity.user_id == row.user_id))
    if mine is None or row.session_id is None:
        return _back(row.return_to, error="identity_mismatch")
    await db.execute(update(UserSession).where(UserSession.id == row.session_id, UserSession.revoked_at.is_(None))
                     .values(confirmed_at=_now()))
    record(db, "stepup", request, user_id=row.user_id, resource="session", resource_id=row.session_id,
           details={"method": "oidc", "provider": provider, "mfa": False})
    await db.commit()
    return _back(row.return_to, ok="reauth")


async def _oidc_name(db: AsyncSession, request: Request, row: OidcLogin, provider: str, subject: str,
                     claims: dict[str, Any]) -> RedirectResponse:
    """The "use my name" round (LG-10): proves it is the account's own login (as a reauth does) and hands the browser
    a username proposed from the name claim, in the address fragment. The name is read here and kept nowhere: not in
    the users row, not in the audit entry, not in the log."""
    mine = await db.scalar(select(UserIdentity.id).where(UserIdentity.provider == provider,
                                                         UserIdentity.subject == subject,
                                                         UserIdentity.user_id == row.user_id))
    if mine is None or row.session_id is None:
        return _back(row.return_to, error="identity_mismatch")
    suggestion = username_from_name(claims)
    if suggestion is None or username_problem(suggestion):
        record(db, "oidc_name_read", request, user_id=row.user_id, details={"provider": provider, "usable": False})
        await db.commit()
        return _back(row.return_to, error="name_unusable")
    await db.execute(update(UserSession).where(UserSession.id == row.session_id, UserSession.revoked_at.is_(None))
                     .values(confirmed_at=_now()))
    record(db, "oidc_name_read", request, user_id=row.user_id, details={"provider": provider, "usable": True})
    await db.commit()
    return _back(row.return_to, ok="name", fragment={"username": suggestion})


@router.post("/auth/oidc/complete")
async def oidc_complete(body: TicketIn, request: Request, db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A finished social login becomes a session (``mfa`` false: see the module's text)."""
    try:
        user_id, provider, jti, expires_at, new_account = read_oidc_ticket(request.app.state.keys, body.ticket)
    except TokenError:
        raise HTTPException(401, "invalid_ticket") from None
    used = request.app.state.used_challenges
    if used.spent(jti) or not used.spend(jti, expires_at):
        raise HTTPException(401, "invalid_ticket")
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "invalid_ticket")
    return await _start_session(db, request, user, mfa=False, method="oidc", provider=provider,
                                extra={"new_account": True, "provider": provider} if new_account else None)


@router.delete("/me/identities/{provider}", status_code=204)
async def unlink_identity(provider: str, body: ConfirmIn, request: Request,
                          principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_session)) -> Response:
    user = await _user_for_update(db, principal)
    identity = await db.scalar(select(UserIdentity).where(UserIdentity.user_id == user.id,
                                                          UserIdentity.provider == provider))
    if identity is None:
        raise HTTPException(404, "identity_not_found")
    await _check_password(db, request, user, body.password, "identity_unlink")
    if await login_method_count(db, request, user, without_provider=provider) < 1:
        await db.rollback()
        raise HTTPException(409, "last_login_method")
    await db.delete(identity)
    record(db, "identity_unlink", request, user_id=user.id, resource="user", resource_id=user.id,
           details={"provider": provider})
    await db.commit()
    return Response(status_code=204)


@router.delete("/me/password", status_code=204)
async def remove_password(body: ConfirmIn, request: Request, principal: Principal = Depends(current_principal),
                          db: AsyncSession = Depends(get_session)) -> Response:
    """Log in without a password from now on; refused when it would leave no way to log in."""
    user = await _user_for_update(db, principal)
    if user.password_hash is None:
        raise HTTPException(409, "no_password")
    await _check_password(db, request, user, body.password, "password_remove")
    if await login_method_count(db, request, user, without_password=True) < 1:
        await db.rollback()
        raise HTTPException(409, "last_login_method")
    user.password_hash = None
    record(db, "password_remove", request, user_id=user.id, resource="user", resource_id=user.id)
    await db.commit()
    return Response(status_code=204)


# Passkeys -------------------------------------------------------------------------------------------


def _challenge(request: Request, token: str, purpose: str) -> WebauthnChallenge:
    """The challenge a browser answered, if its token is ours, of this purpose and not spent yet."""
    try:
        challenge = read_webauthn_challenge(request.app.state.keys, token)
    except TokenError:
        raise HTTPException(400, "invalid_challenge") from None
    used = request.app.state.used_challenges
    if challenge.purpose != purpose or used.spent(challenge.jti) or not used.spend(challenge.jti,
                                                                                  challenge.expires_at):
        raise HTTPException(400, "invalid_challenge")
    return challenge


@router.post("/me/passkeys/options")
async def passkey_register_options(body: ConfirmIn, request: Request,
                                   principal: Principal = Depends(current_principal),
                                   db: AsyncSession = Depends(get_session)) -> JSONResponse:
    user = await _user_for_update(db, principal)
    await _check_password(db, request, user, body.password, "passkey_add")
    existing = list(await db.scalars(select(Passkey.credential_id).where(Passkey.user_id == user.id)))
    if len(existing) >= passkeys.MAX_PER_ACCOUNT:
        await db.commit()
        raise HTTPException(409, "too_many_passkeys")
    options, challenge = passkeys.registration_options(site_origin(request), user.id.bytes, user.username,
                                                       [bytes(c) for c in existing])
    token = make_webauthn_challenge(request.app.state.keys, "register", challenge, user.id)
    await db.commit()  # a rehash, if any
    return JSONResponse({"options": options, "challenge_token": token}, headers=NO_STORE)


@router.post("/me/passkeys", status_code=201)
async def passkey_register(body: AddPasskeyIn, request: Request, principal: Principal = Depends(current_principal),
                           db: AsyncSession = Depends(get_session)) -> JSONResponse:
    challenge = _challenge(request, body.challenge_token, "register")
    if challenge.user_id != principal.user.id:
        raise HTTPException(400, "invalid_challenge")
    user = await _user_for_update(db, principal)
    try:
        verified = passkeys.verify_registration(body.credential, challenge.challenge, site_origin(request),
                                                request.app.state.settings.app_origins)
    except passkeys.PasskeyError:
        raise HTTPException(400, "passkey_invalid") from None
    count = await passkey_count(db, user.id)
    if count >= passkeys.MAX_PER_ACCOUNT:
        raise HTTPException(409, "too_many_passkeys")
    name = (body.name or "").strip() or f"Passkey {count + 1}"
    if not name.isprintable():
        raise HTTPException(400, "name_invalid")
    transports = body.credential.get("response", {}).get("transports") if isinstance(
        body.credential.get("response"), dict) else None
    transports_text = ",".join(t for t in transports if isinstance(t, str) and re.fullmatch(r"[a-z-]{1,16}", t))[:128] \
        if isinstance(transports, list) else None
    key = Passkey(user_id=user.id, credential_id=verified.credential_id, public_key=verified.credential_public_key,
                  sign_count=verified.sign_count, name=name, rp_id=passkeys.rp_id_of(site_origin(request)),
                  transports=transports_text or None, backed_up=bool(verified.credential_backed_up))
    db.add(key)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "passkey_exists") from None
    record(db, "passkey_add", request, user_id=user.id, resource="passkey", resource_id=key.id,
           details={"backed_up": key.backed_up})
    await db.commit()
    await db.refresh(key)
    return JSONResponse(passkey_json(key), status_code=201, headers=NO_STORE)


@router.patch("/me/passkeys/{passkey_id}")
async def passkey_rename(passkey_id: uuid.UUID, body: NameIn, request: Request,
                         principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    name = body.name.strip()
    if not name or not name.isprintable():
        raise HTTPException(400, "name_invalid")
    key = await db.scalar(select(Passkey).where(Passkey.id == passkey_id, Passkey.user_id == principal.user.id))
    if key is None:
        raise HTTPException(404, "passkey_not_found")
    key.name = name
    record(db, "passkey_rename", request, user_id=principal.user.id, resource="passkey", resource_id=key.id)
    await db.commit()
    await db.refresh(key)
    return JSONResponse(passkey_json(key), headers=NO_STORE)


@router.delete("/me/passkeys/{passkey_id}", status_code=204)
async def passkey_remove(passkey_id: uuid.UUID, body: ConfirmIn, request: Request,
                         principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> Response:
    user = await _user_for_update(db, principal)
    key = await db.scalar(select(Passkey).where(Passkey.id == passkey_id, Passkey.user_id == user.id))
    if key is None:
        raise HTTPException(404, "passkey_not_found")
    await _check_password(db, request, user, body.password, "passkey_remove")
    if await login_method_count(db, request, user, without_passkey=key.id) < 1:
        await db.rollback()
        raise HTTPException(409, "last_login_method")
    # A role that needs a second factor keeps one: TOTP, or another passkey (LG-4).
    if not user.totp_enabled and await passkey_count(db, user.id) <= 1 and await _needs_second_factor(db, user):
        await db.rollback()
        raise HTTPException(409, "second_factor_required_by_role")
    await db.delete(key)
    record(db, "passkey_remove", request, user_id=user.id, resource="passkey", resource_id=key.id)
    await db.commit()
    return Response(status_code=204)


async def _verify_assertion(db: AsyncSession, request: Request, token: str, credential: dict[str, Any],
                            purpose: str, user: Optional[User], session_id: Optional[uuid.UUID], where: str
                            ) -> tuple[User, Passkey, Any]:
    """The passkey login's and the step-up's shared check; failures count against the address's login lockout."""
    limits, address = request.app.state.limits, _ip_key(request)
    wait = limits.login_address.retry_after(address)
    if wait:
        raise _too_many(wait)
    challenge = _challenge(request, token, purpose)
    if challenge.user_id != (user.id if user else None) or challenge.session_id != session_id:
        raise HTTPException(400, "invalid_challenge")
    origin = site_origin(request)
    key: Optional[Passkey] = None
    try:
        cid = passkeys.credential_id_of(credential)
        key = await db.scalar(select(Passkey).where(Passkey.credential_id == cid,
                                                    Passkey.rp_id == passkeys.rp_id_of(origin)))
        handle = passkeys.user_handle_of(credential)
        if key is None or (user is not None and key.user_id != user.id) or (
                handle is not None and handle != key.user_id.bytes):
            raise passkeys.PasskeyError("unknown credential")
        verified = passkeys.verify_authentication(credential, challenge.challenge, origin, bytes(key.public_key),
                                                  int(key.sign_count), request.app.state.settings.app_origins)
    except passkeys.PasskeyError:
        locked = limits.login_address.fail(address)
        record(db, "login_failed", request, user_id=key.user_id if key is not None else None,
               details={"where": where, "method": "passkey"})
        if locked:
            record(db, "login_locked", request, details={"where": where, "scope": "address"})
        await db.commit()
        raise HTTPException(401, "invalid_passkey") from None
    owner = user or await db.get(User, key.user_id)
    if owner is None:
        raise HTTPException(401, "invalid_passkey")
    key.sign_count = verified.new_sign_count
    key.last_used_at = _now()
    key.backed_up = bool(verified.credential_backed_up)
    return owner, key, verified


@router.post("/auth/passkey/login/options")
async def passkey_login_options(request: Request) -> JSONResponse:
    wait = request.app.state.limits.login_address.retry_after(_ip_key(request))
    if wait:
        raise _too_many(wait)
    options, challenge = passkeys.authentication_options(site_origin(request))
    token = make_webauthn_challenge(request.app.state.keys, "login", challenge)
    return JSONResponse({"options": options, "challenge_token": token}, headers=NO_STORE)


@router.post("/auth/passkey/login")
async def passkey_login(body: ChallengeIn, request: Request, db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A passkey is both factors: the session has ``mfa`` (user verification was required)."""
    user, key, _ = await _verify_assertion(db, request, body.challenge_token, body.credential, "login", None, None,
                                           "login")
    return await _start_session(db, request, user, mfa=True, method="passkey")


# The second factor of an account that logged in without one ----------------------------------------------


@router.post("/auth/stepup/totp")
async def stepup_totp(body: CodeIn, request: Request, principal: Principal = Depends(current_principal),
                      db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """A TOTP code for this session: it now counts as having a second factor (and as recently confirmed)."""
    user = await _user_for_update(db, principal)
    if not user.totp_enabled:
        raise HTTPException(409, "totp_not_enabled")
    await _check_code(db, request, user, _secret(request, user), body.code, "stepup")
    await db.execute(update(UserSession).where(UserSession.id == principal.session.id)
                     .values(mfa=True, confirmed_at=_now()))
    record(db, "stepup", request, user_id=user.id, resource="session", resource_id=principal.session.id,
           details={"method": "totp", "mfa": True})
    await db.commit()
    return JSONResponse({"mfa": True}, headers=NO_STORE)


@router.post("/auth/stepup/passkey/options")
async def stepup_passkey_options(request: Request, principal: Principal = Depends(current_principal),
                                 db: AsyncSession = Depends(get_session)) -> JSONResponse:
    rp = passkeys.rp_id_of(site_origin(request))
    ids = [bytes(c) for c in await db.scalars(select(Passkey.credential_id).where(
        Passkey.user_id == principal.user.id, Passkey.rp_id == rp))]
    if not ids:
        raise HTTPException(409, "no_passkey")
    options, challenge = passkeys.authentication_options(site_origin(request), ids)
    token = make_webauthn_challenge(request.app.state.keys, "stepup", challenge, principal.user.id,
                                    principal.session.id)
    return JSONResponse({"options": options, "challenge_token": token}, headers=NO_STORE)


@router.post("/auth/stepup/passkey")
async def stepup_passkey(body: ChallengeIn, request: Request, principal: Principal = Depends(current_principal),
                         db: AsyncSession = Depends(get_session)) -> JSONResponse:
    await _verify_assertion(db, request, body.challenge_token, body.credential, "stepup", principal.user,
                            principal.session.id, "stepup")
    await db.execute(update(UserSession).where(UserSession.id == principal.session.id)
                     .values(mfa=True, confirmed_at=_now()))
    record(db, "stepup", request, user_id=principal.user.id, resource="session", resource_id=principal.session.id,
           details={"method": "passkey", "mfa": True})
    await db.commit()
    return JSONResponse({"mfa": True}, headers=NO_STORE)
