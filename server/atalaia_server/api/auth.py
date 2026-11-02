# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accounts and sessions: register, login, the TOTP step, refresh, logout, TOTP enrolment (ADR-P4-2).

    POST /api/v1/auth/register        {username, password, email?, notice_seen, age_confirmed, notice_version?}
    POST /api/v1/auth/login           {username, password}
    POST /api/v1/auth/login/totp      {totp_session, code}
    POST /api/v1/auth/refresh         the refresh cookie + header X-Atalaia-Refresh: 1
    POST /api/v1/auth/logout          Bearer
    GET  /api/v1/me                   Bearer
    POST /api/v1/auth/totp/enrol      Bearer, {password}
    POST /api/v1/auth/totp/confirm    Bearer, {code}
    POST /api/v1/auth/totp/disable    Bearer, {password, code}

A login answers ``{access_token, token_type, expires_in, user}`` and sets the
refresh token as a cookie: ``__Secure-atalaia_refresh``, HttpOnly, Secure,
SameSite=Strict, Path=/api/v1/auth/refresh, so the browser sends it to the
refresh endpoint only and scripts never see it. The access token travels in
``Authorization: Bearer``, never in a cookie, so the API needs no CSRF token;
the refresh endpoint, the one place a cookie is read, also wants the header
``X-Atalaia-Refresh: 1``, which a cross-site form cannot send and a
cross-site script cannot send without a CORS preflight the server never
grants. Errors are ``{"detail": "<code>"}`` with a code a client translates.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import passwords, personal_data, privacy_notice, quotas, tenancy, totp
from ..audit import record, request_ip
from ..auth import Principal, current_principal, load_roles
from ..db import get_session
from ..models import (PRIVILEGED_ROLES, ROLE_NAMES, Passkey, RefreshToken, User, UserFieldRole, UserGameRole,
                      UserSession)
from ..ratelimit import login_key
from ..tokens import (ACCESS_TTL_S, REFRESH_TTL_S, SESSION_MAX_S, TokenError, make_access_token,
                      make_totp_step_token, new_refresh_token, read_totp_step_token, refresh_token_hash)

router = APIRouter(prefix="/api/v1", tags=["auth"])

COOKIE = "__Secure-atalaia_refresh"
COOKIE_PATH = "/api/v1/auth/refresh"
REFRESH_HEADER = "x-atalaia-refresh"
USERNAME = re.compile(r"[a-z0-9][a-z0-9_.-]{2,63}")
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+")
NO_STORE = {"Cache-Control": "no-store"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterIn(Strict):
    username: str = Field(max_length=64)
    password: str = Field(max_length=4096)
    email: Optional[str] = Field(default=None, max_length=320)
    # The account rests on the contract (LEG-*), so these are not consents: the person was shown the privacy notice
    # (``notice_seen``; the version is recorded) and confirms being 16 or older (``age_confirmed``; no date of
    # birth is asked). Younger players use the field's check-in without an account.
    notice_seen: bool = False
    age_confirmed: bool = False
    # The version of the privacy notice the person was shown (GET /api/v1/privacy-notice); when given and not the
    # current one, 409 notice_version_changed (CONS-4).
    notice_version: Optional[str] = Field(default=None, max_length=64)


class LoginIn(Strict):
    username: str = Field(max_length=320)
    password: str = Field(max_length=4096)


class TotpLoginIn(Strict):
    totp_session: str = Field(max_length=2048)
    code: str = Field(max_length=16)


class PasswordIn(Strict):
    # Empty for an account with no password: it confirms with a recent login instead (LG-6).
    password: str = Field(default="", max_length=4096)


class CodeIn(Strict):
    code: str = Field(max_length=16)


class DisableIn(Strict):
    password: str = Field(default="", max_length=4096)
    code: str = Field(max_length=16)


def username_problem(username: str) -> Optional[str]:
    """None when a (lower-cased) username may be used, else the error code."""
    if not USERNAME.fullmatch(username):
        return "username_invalid"
    if username.startswith(personal_data.ERASED_PREFIX):
        return "username_reserved"  # the names erased accounts get (ADR-P4-8)
    return None


def normalise_email(email: Optional[str]) -> Optional[str]:
    return email.strip().lower() if email and email.strip() else None


def email_problem(email: Optional[str]) -> Optional[str]:
    if email is not None and (len(email) > 320 or not EMAIL.fullmatch(email)):
        return "email_invalid"
    return None


async def passkey_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return await db.scalar(select(func.count()).select_from(Passkey).where(Passkey.user_id == user_id)) or 0


async def has_second_factor(db: AsyncSession, user: User) -> bool:
    """TOTP on, or a passkey: what a role that needs a second factor asks of an account (LG-4)."""
    return user.totp_enabled or await passkey_count(db, user.id) > 0


async def is_staff(db: AsyncSession, user: User) -> bool:
    """A server administrator, or ``admin``/``gm``/``marshal`` on a field or a game: a role that needs a second
    factor (LG-4)."""
    if user.server_admin:
        return True
    privileged = [ROLE_NAMES[r] for r in PRIVILEGED_ROLES]
    for table in (UserFieldRole, UserGameRole):
        if await db.scalar(select(func.count()).select_from(table).where(table.user_id == user.id,
                                                                         table.role_id.in_(privileged))):
            return True
    return False


async def step_up_needed(db: AsyncSession, user: User) -> bool:
    """True when changing how this account logs in must come from a session that passed a second factor (SR-1).

    An account with a TOTP or a passkey already has one, so a social login or a bare password session (``mfa``
    false) must not be able to add, swap or remove the means of getting in. A staff account with no second
    factor yet and a password is let through (the password is the proof; it is how it gets its first one:
    SR-2). A passwordless staff account with none cannot: nothing could prove it, an operator sets a password
    first. An account with no staff role and no second factor (a player adding a first passkey) keeps the
    confirmation it always had (password, or a recent login)."""
    if await has_second_factor(db, user):
        return True
    return user.password_hash is None and await is_staff(db, user)


# The confirmations (the ``where`` of ``_check_password``) that change how the account logs in or who it is
# merged with: the passkeys, TOTP, the password, the social links and the merge.
STEP_UP_ACTIONS = frozenset({"passkey_add", "passkey_remove", "totp_enrol", "totp_disable", "password_change",
                             "password_remove", "identity_link", "identity_unlink", "account_merge"})


async def require_step_up(db: AsyncSession, request: Request, user: User) -> None:
    """403 ``mfa_required`` for an account that ``step_up_needed`` unless this session passed a second factor."""
    principal = getattr(request.state, "principal", None)
    if principal is not None and principal.user.id == user.id and principal.mfa:
        return
    if await step_up_needed(db, user):
        record(db, "step_up_refused", request, user_id=user.id, resource="user", resource_id=user.id)
        await db.commit()
        raise HTTPException(403, "mfa_required")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ip_key(request: Request) -> str:
    return request_ip(request) or "unknown"


def _too_many(retry_after: int) -> HTTPException:
    return HTTPException(429, "too_many_attempts", headers={"Retry-After": str(retry_after)})


def user_json(user: User, roles: dict[uuid.UUID, set[str]]) -> dict[str, Any]:
    return {"id": str(user.id), "username": user.username, "email": user.email,
            "totp_enabled": user.totp_enabled, "has_password": user.password_hash is not None,
            "server_admin": user.server_admin,
            "roles": {str(f): sorted(r) for f, r in roles.items()},
            "created_at": user.created_at.isoformat() if user.created_at else None}


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=REFRESH_TTL_S, path=COOKIE_PATH, secure=True, httponly=True,
                        samesite="strict")


def _clear_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path=COOKIE_PATH, secure=True, httponly=True, samesite="strict")


def _session_body(request: Request, user: User, session: UserSession,
                  roles: dict[uuid.UUID, set[str]]) -> dict[str, Any]:
    token, _ = make_access_token(request.app.state.keys, user.id, session.id, user.username,
                                 {str(f): sorted(r) for f, r in roles.items()})
    return {"access_token": token, "token_type": "bearer", "expires_in": ACCESS_TTL_S, "mfa": session.mfa,
            "user": user_json(user, roles)}


async def _start_session(db: AsyncSession, request: Request, user: User, mfa: bool, method: str = "password",
                         provider: Optional[str] = None, extra: Optional[dict[str, Any]] = None) -> JSONResponse:
    """A new session and its refresh token. ``method`` (password, passkey, oidc) goes in the audit entry; a
    passkey login counts as both factors (``mfa``), a password login only when the TOTP step passed, a social
    login never (LG-4)."""
    now = _now()
    session = UserSession(user_id=user.id, user_agent=(request.headers.get("user-agent") or "")[:512] or None,
                          ip_address=request_ip(request), expires_at=now + timedelta(seconds=REFRESH_TTL_S),
                          mfa=mfa, last_used_at=now, confirmed_at=now)
    db.add(session)
    await db.flush()
    refresh = new_refresh_token()
    db.add(RefreshToken(session_id=session.id, token_hash=refresh_token_hash(refresh)))
    user.last_login_at = now
    record(db, "login", request, user_id=user.id, resource="session", resource_id=session.id,
           details={"mfa": mfa, "method": method, **({"provider": provider} if provider else {})})
    await db.commit()
    roles = await load_roles(db, user.id)
    response = JSONResponse({**_session_body(request, user, session, roles), **(extra or {})}, headers=NO_STORE)
    _set_cookie(response, refresh)
    return response


async def _check_password(db: AsyncSession, request: Request, user: Optional[User], password: str,
                          where: str, username: Optional[str] = None) -> None:
    """Verifies the password under the lockouts; 429 when locked, raises on a mismatch.

    Two lockouts count each failure (decisions S11-12, S12-1): one per (address, username),
    ``username`` being what was typed at login (the account's own name elsewhere), and a much
    higher one per address against spraying many usernames from one place."""
    if user is not None and where in STEP_UP_ACTIONS:
        await require_step_up(db, request, user)
    if user is not None and user.password_hash is None and where != "login":
        _recently_confirmed(request, user)  # an account with no password: a recent proof instead (LG-6)
        return
    limits = request.app.state.limits
    address = _ip_key(request)
    key = login_key(address, username if username is not None else (user.username if user else ""),
                    tenancy.current_schema())
    wait = max(limits.login.retry_after(key), limits.login_address.retry_after(address))
    if wait:
        raise _too_many(wait)
    if await passwords.verify_password(user.password_hash if user else None, password):
        if user is not None and passwords.needs_rehash(user.password_hash):
            user.password_hash = await passwords.hash_password(password)
        limits.login.clear(key)
        return
    locked = limits.login.fail(key)
    address_locked = limits.login_address.fail(address)
    record(db, "login_failed", request, user_id=user.id if user else None, details={"where": where})
    if locked or address_locked:
        record(db, "login_locked", request, user_id=user.id if user and locked else None,
               details={"where": where, "scope": "address" if address_locked else "username_address"})
    await db.commit()
    if where == "login":
        raise HTTPException(401, "invalid_credentials")
    raise HTTPException(403, "invalid_password")


RECENT_CONFIRM_S = 600


def _recently_confirmed(request: Request, user: User) -> None:
    """403 ``confirmation_required`` unless this session proved the account is there in the last ten minutes
    (a login, a TOTP or passkey step-up, a social re-login): what a password confirms for an account that has one."""
    principal = getattr(request.state, "principal", None)
    confirmed = principal.session.confirmed_at if principal is not None and principal.user.id == user.id else None
    if confirmed is None or (_now() - confirmed).total_seconds() > RECENT_CONFIRM_S:
        raise HTTPException(403, "confirmation_required")


async def _check_code(db: AsyncSession, request: Request, user: User, secret: Optional[str], code: str,
                      where: str) -> int:
    """Verifies a TOTP code under the per-account lockout and spends its step; returns the step."""
    tenant = tenancy.current_schema()  # hosted mode: per field, as the login lockouts (plan phase 21)
    key = f"{tenant}#{user.id}" if tenant is not None else str(user.id)
    wait = request.app.state.limits.totp.retry_after(key)
    if wait:
        raise _too_many(wait)
    step = totp.verify(secret, code, request.app.state.clock(), user.totp_last_step) if secret else None
    if step is not None:
        # Spend the step atomically: two requests with the same code cannot both pass.
        spent = await db.scalar(
            update(User).where(User.id == user.id,
                               (User.totp_last_step.is_(None)) | (User.totp_last_step < step))
            .values(totp_last_step=step).returning(User.id).execution_options(synchronize_session=False))
        if spent is not None:
            user.totp_last_step = step
            request.app.state.limits.totp.clear(key)
            return step
    locked = request.app.state.limits.totp.fail(key)
    record(db, "totp_failed", request, user_id=user.id, details={"where": where})
    if locked:
        record(db, "totp_locked", request, user_id=user.id, details={"where": where})
    await db.commit()
    raise HTTPException(401 if where == "login" else 403, "invalid_code")


def _secret(request: Request, user: User) -> Optional[str]:
    if user.totp_secret_enc is None:
        return None
    return request.app.state.seed_box.open(user.totp_secret_enc)


@router.post("/auth/register", status_code=201)
async def register(body: RegisterIn, request: Request, db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if not request.app.state.settings.password_login:
        raise HTTPException(403, "password_login_disabled")
    if privacy_notice.signup_blocked(request.app.state.settings):  # LIVE-2: a consent is to a published text
        raise HTTPException(409, "privacy_notice_unpublished")
    username = body.username.strip().lower()
    email = normalise_email(body.email)
    problem = username_problem(username) or email_problem(email)
    if problem:
        raise HTTPException(400, problem)
    if not body.age_confirmed:
        raise HTTPException(400, "age_confirmation_required")
    if not body.notice_seen:
        raise HTTPException(400, "notice_required")
    current = request.app.state.settings.privacy_notice_version
    if body.notice_version is not None and body.notice_version != current:
        return JSONResponse({"detail": "notice_version_changed", "current_version": current}, status_code=409,
                            headers=NO_STORE)
    problem = passwords.policy_problem(body.password, username)
    if problem:
        raise HTTPException(400, problem)
    await quotas.check(db, "accounts", None)  # hosted mode: the field's account quota (409 quota_exceeded)
    limits = request.app.state.limits
    wait = limits.register.retry_after(_ip_key(request))
    if wait:
        raise _too_many(wait)
    limits.register.fail(_ip_key(request))  # every registration counts towards the hourly limit
    user = User(username=username, email=email, password_hash=await passwords.hash_password(body.password),
                gdpr_consent_at=_now())
    db.add(user)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(409, "username_or_email_taken") from None
    personal_data.record_notice(db, user.id, current, personal_data.NOTICE_SIGNUP, user.gdpr_consent_at,
                                age_confirmed=True)
    record(db, "register", request, user_id=user.id, resource="user", resource_id=user.id)
    await db.commit()
    return JSONResponse(user_json(user, {}), status_code=201, headers=NO_STORE)


@router.post("/auth/login")
async def login(body: LoginIn, request: Request, db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if not request.app.state.settings.password_login:
        raise HTTPException(403, "password_login_disabled")
    username = body.username.strip().lower()
    user = await db.scalar(select(User).where(User.username == username)) if username else None
    await _check_password(db, request, user, body.password, "login", username)
    assert user is not None
    if user.totp_enabled:
        await db.commit()  # a rehash, if any
        token, _ = make_totp_step_token(request.app.state.keys, user.id)
        return JSONResponse({"totp_required": True, "totp_session": token}, headers=NO_STORE)
    return await _start_session(db, request, user, mfa=False)


@router.post("/auth/login/totp")
async def login_totp(body: TotpLoginIn, request: Request, db: AsyncSession = Depends(get_session)) -> JSONResponse:
    used = request.app.state.used_totp_steps
    try:
        user_id, jti, expires_at = read_totp_step_token(request.app.state.keys, body.totp_session)
    except TokenError:
        raise HTTPException(401, "invalid_totp_session") from None
    if used.spent(jti):
        raise HTTPException(401, "invalid_totp_session")
    user = await db.get(User, user_id)
    if user is None or not user.totp_enabled:
        raise HTTPException(401, "invalid_totp_session")
    await _check_code(db, request, user, _secret(request, user), body.code, "login")
    if not used.spend(jti, expires_at):
        await db.rollback()
        raise HTTPException(401, "invalid_totp_session")
    return await _start_session(db, request, user, mfa=True)


@router.post("/auth/refresh")
async def refresh(request: Request, db: AsyncSession = Depends(get_session)) -> JSONResponse:
    if request.headers.get(REFRESH_HEADER) != "1":
        raise HTTPException(403, "refresh_header_required")

    def refused(code: str = "invalid_refresh_token") -> JSONResponse:
        response = JSONResponse({"detail": code}, status_code=401, headers=NO_STORE)
        _clear_cookie(response)
        return response

    presented = request.cookies.get(COOKIE)
    if not presented or len(presented) > 256:
        return refused()
    row = (await db.execute(
        select(RefreshToken, UserSession, User)
        .join(UserSession, UserSession.id == RefreshToken.session_id)
        .join(User, User.id == UserSession.user_id)
        .where(RefreshToken.token_hash == refresh_token_hash(presented))
        .with_for_update(of=[RefreshToken, UserSession]))).first()
    if row is None:
        return refused()
    token, session, user = row
    now = _now()
    if token.used_at is not None:
        # A rotated token came back: someone else has a copy. End the session for both (ADR-P4-2).
        if session.revoked_at is None:
            session.revoked_at = now
        record(db, "refresh_replay", request, user_id=user.id, resource="session", resource_id=session.id)
        await db.commit()
        return refused()
    deadline = session.created_at + timedelta(seconds=SESSION_MAX_S)
    if session.revoked_at is not None or session.expires_at <= now or deadline <= now:
        await db.rollback()
        return refused()
    token.used_at = now
    fresh = new_refresh_token()
    db.add(RefreshToken(session_id=session.id, token_hash=refresh_token_hash(fresh)))
    session.expires_at = min(now + timedelta(seconds=REFRESH_TTL_S), deadline)
    session.last_used_at = now
    await db.commit()
    roles = await load_roles(db, user.id)
    response = JSONResponse(_session_body(request, user, session, roles), headers=NO_STORE)
    _set_cookie(response, fresh)
    return response


@router.post("/auth/logout", status_code=204)
async def logout(request: Request, principal: Principal = Depends(current_principal),
                 db: AsyncSession = Depends(get_session)) -> Response:
    await db.execute(update(UserSession).where(UserSession.id == principal.session.id,
                                               UserSession.revoked_at.is_(None)).values(revoked_at=func.now()))
    record(db, "logout", request, user_id=principal.user.id, resource="session", resource_id=principal.session.id)
    await db.commit()
    response = Response(status_code=204)
    _clear_cookie(response)
    return response


@router.get("/me")
async def me(request: Request, principal: Principal = Depends(current_principal),
             db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """The account, its roles and which privacy notice it was last shown (CONS-2, LEG-*): ``notice.status`` is
    ``current``, ``outdated`` (another version: show it again and ``POST /api/v1/me/notice``) or ``missing``;
    ``notice.notice_published`` says whether ``GET /api/v1/privacy-notice`` has a text to show. ``inactivity`` is
    null, or (PRIV-7) when the retention purge warned that the account, inactive for a long time, would be
    anonymised (``warned_at``) and when it would have been (``anonymise_after``): the client says so, and that the
    account stays because the person is here (the purge clears the warning at its next run)."""
    settings = request.app.state.settings
    notice = await personal_data.notice_state(db, principal.user.id, settings.privacy_notice_version)
    notice["notice_published"] = bool(privacy_notice.available(settings.privacy_notice_dir,
                                                               settings.privacy_notice_version))
    warned = principal.user.inactivity_warned_at
    inactivity = None
    if warned is not None and settings.retention.inactive_months is not None:
        inactivity = {"warned_at": warned.isoformat(),
                      "anonymise_after": (warned + timedelta(days=settings.retention.inactive_grace_days)).isoformat()}
    return JSONResponse({**user_json(principal.user, principal.roles), "mfa": principal.mfa, "notice": notice,
                         "inactivity": inactivity}, headers=NO_STORE)


async def _user_for_update(db: AsyncSession, principal: Principal) -> User:
    """The caller's row, locked, in the request's own database session."""
    user = await db.scalar(select(User).where(User.id == principal.user.id).with_for_update())
    if user is None:
        raise HTTPException(401, "not_authenticated")
    return user


@router.post("/auth/totp/enrol")
async def totp_enrol(body: PasswordIn, request: Request, principal: Principal = Depends(current_principal),
                     db: AsyncSession = Depends(get_session)) -> JSONResponse:
    """Starts enrolment: a new secret, shown once; TOTP is on after ``confirm``."""
    user = await _user_for_update(db, principal)
    if user.totp_enabled:
        raise HTTPException(409, "totp_already_enabled")
    await _check_password(db, request, user, body.password, "totp_enrol")
    secret = totp.new_secret()
    user.totp_secret_enc = request.app.state.seed_box.seal(secret)
    user.totp_last_step = None
    await db.commit()
    return JSONResponse({"secret": secret, "otpauth_uri": totp.provisioning_uri(secret, user.username),
                         "digits": totp.DIGITS, "period_s": totp.PERIOD_S}, headers=NO_STORE)


@router.post("/auth/totp/confirm", status_code=204)
async def totp_confirm(body: CodeIn, request: Request, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> Response:
    """A code from the new secret turns TOTP on; this session counts as having passed it."""
    user = await _user_for_update(db, principal)
    if user.totp_enabled or user.totp_secret_enc is None:
        raise HTTPException(409, "totp_not_pending")
    await _check_code(db, request, user, _secret(request, user), body.code, "totp_confirm")
    user.totp_enabled = True
    await db.execute(update(UserSession).where(UserSession.id == principal.session.id).values(mfa=True))
    record(db, "totp_enabled", request, user_id=user.id, resource="user", resource_id=user.id)
    await db.commit()
    return Response(status_code=204)


@router.post("/auth/totp/disable", status_code=204)
async def totp_disable(body: DisableIn, request: Request, principal: Principal = Depends(current_principal),
                       db: AsyncSession = Depends(get_session)) -> Response:
    """Turns TOTP off, with the password and a current code; refused while a role needs it."""
    user = await _user_for_update(db, principal)
    if not user.totp_enabled:
        raise HTTPException(409, "totp_not_enabled")
    privileged = await db.scalar(select(func.count()).select_from(UserFieldRole).where(
        UserFieldRole.user_id == user.id,
        UserFieldRole.role_id.in_([ROLE_NAMES[r] for r in PRIVILEGED_ROLES])))
    if (user.server_admin or privileged) and not await passkey_count(db, user.id):
        raise HTTPException(409, "totp_required_by_role")  # a passkey is the other second factor (LG-4)
    await _check_password(db, request, user, body.password, "totp_disable")
    await _check_code(db, request, user, _secret(request, user), body.code, "totp_disable")
    user.totp_enabled = False
    user.totp_secret_enc = None
    user.totp_last_step = None
    await db.execute(update(UserSession).where(UserSession.user_id == user.id).values(mfa=False))
    record(db, "totp_disabled", request, user_id=user.id, resource="user", resource_id=user.id)
    await db.commit()
    return Response(status_code=204)
