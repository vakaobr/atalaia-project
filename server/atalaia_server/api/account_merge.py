# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Merging two accounts of the same person (decision LG-11).

    POST /api/v1/me/merge/preview   Bearer, {ticket}            whose account the ticket is for, and whether it may be merged
    POST /api/v1/me/merge           Bearer, {ticket, password?} moves the other account into this one

A person who signed up with Google (account A) and later signed in with Microsoft, ticking the box for a new
account, has two accounts (B is the second). Linking Microsoft from A's Account page used to end at "already linked
to another account". Now the provider round A has just completed (``purpose: link``, which proves control of B's
Microsoft login) hands the page a five-minute, single-use **merge ticket** (``tokens.make_merge_ticket``) naming A, B
and the provider, and the page offers the merge. Nothing happens until A confirms it, as every sensitive change is
confirmed (the password, or for an account with none a login from the last ten minutes); a login with B's identity
while A is open is just a login to B, never a merge.

What moves from B into A: every row that points at B's account (``Base.metadata`` is read, so a table added later is
included without touching this file): linked logins, passkeys, roles, game roles, registrations, consents, club
memberships, player ids and claims, the chrono sharing link, ATAK certificates and the "who did it" columns of the
rest. Where both accounts hold the same thing (the same role on a field, the same game, the same club, the same
consent) A's stays and B's duplicate is dropped; a registration of B's for a game A is registered for is cancelled and
unlinked from B (as an erasure does). A's password, TOTP and username stay; B's password, TOTP and email go (a
password is never carried over silently: an account with none stays without one, and the answer says so). B itself is
kept as an anonymised row (the audit log's rows point at it): a username ``deleted-...``, no password, no logins, its
sessions revoked; both accounts get an audit entry, with counts and no names.

What refuses it (409): a B with a staff role (server administrator, or ``admin``/``gm``/``marshal`` on a field or a
game): a role that needs a second factor is not something a social login round may take over, and the decision is
to keep that out of this feature (``merge_staff_account``); a provider both accounts already have a login for
(``merge_provider_conflict``: dropping one would be silent loss of a way in); more passkeys together than an account
may hold (``merge_too_many_passkeys``); a B with passkeys into an A with a staff role
(``merge_passkeys_into_staff``: a passkey counts as both factors, so one the merge carried in would hand a staff
account a way to log in with ``mfa`` that only a social round proved; B's person removes them first, or keeps the
accounts apart). Confirming a merge, like linking the provider that starts it, also needs a session that passed a
second factor when the account has one or a staff role (``mfa_required``, ``api/auth.step_up_needed``).

Accounts are per field in hosted mode, and a merge runs in one request, so inside one field's schema and database
role; no statement here reaches another field.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import Column, Table, delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import hub_share, passkeys, personal_data
from ..audit import record
from ..auth import Principal, current_principal
from ..db import get_session
from ..models import (Base, Consent, GameRegistration, HubShareLink, Passkey, User, UserFieldRole, UserGameRole,
                      UserIdentity, UserSession)
from ..oidc import PROVIDER_LABELS
from ..tokens import TokenError, read_merge_ticket
from .auth import NO_STORE, Strict, _check_password, is_staff

router = APIRouter(prefix="/api/v1", tags=["login methods"])

# Tables whose rows are not moved: the audit log keeps what happened to B under B's id; B's sessions end; a social
# login in progress of B's is of no use any more.
NOT_MOVED = frozenset({"audit_log", "sessions", "oidc_logins", "users"})


class MergeIn(Strict):
    ticket: str = Field(max_length=2048)
    password: str = Field(default="", max_length=4096)


def user_columns() -> list[tuple[Table, Column[Any]]]:
    """Every column of every table that is a foreign key to ``users.id``."""
    found = []
    for table in Base.metadata.sorted_tables:
        if table.name in NOT_MOVED:
            continue
        for column in table.columns:
            if any(fk.column.table.name == "users" and fk.column.name == "id" for fk in column.foreign_keys):
                found.append((table, column))
    return found


async def blocked_by(db: AsyncSession, a: User, b: User) -> Optional[str]:
    """The reason these two accounts may not be merged (the error code), else None."""
    if await is_staff(db, b):
        return "merge_staff_account"
    if await is_staff(db, a) and await db.scalar(select(func.count()).select_from(Passkey).where(Passkey.user_id == b.id)):
        return "merge_passkeys_into_staff"  # a passkey is a login that counts as two factors: never carried in (SR-3)
    mine = set(await db.scalars(select(UserIdentity.provider).where(UserIdentity.user_id == a.id)))
    theirs = set(await db.scalars(select(UserIdentity.provider).where(UserIdentity.user_id == b.id)))
    if mine & theirs:
        return "merge_provider_conflict"
    keys = await db.scalar(select(func.count()).select_from(Passkey).where(Passkey.user_id.in_([a.id, b.id]))) or 0
    if keys > passkeys.MAX_PER_ACCOUNT:
        return "merge_too_many_passkeys"
    return None


async def _open(db: AsyncSession, request: Request, principal: Principal, ticket: str) -> tuple[User, User, str, str, int]:
    """The ticket's two accounts, locked in id order (two merges the other way round cannot deadlock)."""
    try:
        a_id, b_id, provider, jti, exp = read_merge_ticket(request.app.state.keys, ticket)
    except TokenError:
        raise HTTPException(400, "merge_ticket_invalid") from None
    if a_id != principal.user.id or a_id == b_id or request.app.state.used_challenges.spent(jti):
        raise HTTPException(400, "merge_ticket_invalid")
    rows = list(await db.scalars(select(User).where(User.id.in_([a_id, b_id])).order_by(User.id).with_for_update()))
    by_id = {u.id: u for u in rows}
    if a_id not in by_id or b_id not in by_id:
        raise HTTPException(409, "merge_ticket_invalid")
    b = by_id[b_id]
    if b.password_hash == personal_data.ERASED_PASSWORD or not await db.scalar(
            select(UserIdentity.id).where(UserIdentity.user_id == b_id, UserIdentity.provider == provider)):
        raise HTTPException(409, "merge_ticket_invalid")  # B is gone, or no longer holds that login
    return by_id[a_id], b, provider, jti, exp


@router.post("/me/merge/preview")
async def merge_preview(body: MergeIn, request: Request, principal: Principal = Depends(current_principal),
                        db: AsyncSession = Depends(get_session)) -> JSONResponse:
    a, b, provider, _, _ = await _open(db, request, principal, body.ticket)
    logins = list(await db.scalars(select(UserIdentity.provider).where(UserIdentity.user_id == b.id)
                                   .order_by(UserIdentity.created_at)))
    keys = await db.scalar(select(func.count()).select_from(Passkey).where(Passkey.user_id == b.id)) or 0
    reason = await blocked_by(db, a, b)
    answer = {"username": b.username, "provider": provider, "label": PROVIDER_LABELS.get(provider, provider),
              "logins": [PROVIDER_LABELS.get(p, p) for p in logins], "passkeys": keys,
              "other_has_password": b.password_hash is not None, "has_password": a.password_hash is not None,
              "blocked": reason}
    await db.rollback()  # nothing is changed: the locks go
    return JSONResponse(answer, headers=NO_STORE)


@router.post("/me/merge")
async def merge(body: MergeIn, request: Request, principal: Principal = Depends(current_principal),
                db: AsyncSession = Depends(get_session)) -> JSONResponse:
    a, b, provider, jti, exp = await _open(db, request, principal, body.ticket)
    await _check_password(db, request, a, body.password, "account_merge")
    reason = await blocked_by(db, a, b)
    if reason:
        await db.rollback()
        raise HTTPException(409, reason)
    used = request.app.state.used_challenges
    if not used.spend(jti, exp):
        await db.rollback()
        raise HTTPException(400, "merge_ticket_invalid")
    password_dropped = b.password_hash is not None and b.password_hash != personal_data.ERASED_PASSWORD
    moved = await merge_into(db, a, b)
    record(db, "account_merge", request, user_id=a.id, resource="user", resource_id=a.id,
           details={"from": str(b.id), "provider": provider, "moved": moved, "password_dropped": password_dropped})
    record(db, "account_merged_into", request, user_id=b.id, resource="user", resource_id=b.id,
           details={"into": str(a.id), "provider": provider})
    await db.commit()
    return JSONResponse({"merged": True, "moved": moved, "password_dropped": password_dropped,
                         "has_password": a.password_hash is not None}, headers=NO_STORE)


async def merge_into(db: AsyncSession, a: User, b: User) -> dict[str, int]:
    """Moves everything of ``b`` into ``a`` and retires ``b`` (the caller holds both rows locked and commits).
    Returns how many rows moved per table, only the tables where some did."""
    dedupe_roles = select(UserFieldRole.field_id, UserFieldRole.role_id).where(UserFieldRole.user_id == a.id)
    await db.execute(delete(UserFieldRole).where(UserFieldRole.user_id == b.id).where(
        tuple_(UserFieldRole.field_id, UserFieldRole.role_id).in_(dedupe_roles)))
    dedupe_games = select(UserGameRole.game, UserGameRole.role_id).where(UserGameRole.user_id == a.id)
    await db.execute(delete(UserGameRole).where(UserGameRole.user_id == b.id).where(
        tuple_(UserGameRole.game, UserGameRole.role_id).in_(dedupe_games)))
    clubs = Base.metadata.tables["club_members"]
    await db.execute(delete(clubs).where(clubs.c.user_id == b.id, clubs.c.club_id.in_(
        select(clubs.c.club_id).where(clubs.c.user_id == a.id))))
    mine = {(c.purpose, c.field_id) for c in await db.scalars(select(Consent).where(
        Consent.user_id == a.id, Consent.withdrawn_at.is_(None)))}
    for consent in await db.scalars(select(Consent).where(Consent.user_id == b.id, Consent.withdrawn_at.is_(None))):
        if (consent.purpose, consent.field_id) in mine:
            await db.delete(consent)
    await db.flush()
    # A registration of B's for a game A is already registered for: A's stays, B's is cancelled and unlinked.
    now = datetime.now(timezone.utc)
    same_game = select(GameRegistration.scheduled_game).where(GameRegistration.user_id == a.id)
    await db.execute(update(GameRegistration).where(
        GameRegistration.user_id == b.id, GameRegistration.scheduled_game.in_(same_game),
        GameRegistration.status == "registered").values(status="cancelled", cancelled_at=now)
        .execution_options(synchronize_session=False))
    await db.execute(update(GameRegistration).where(
        GameRegistration.user_id == b.id, GameRegistration.scheduled_game.in_(same_game)).values(
        user_id=None, display_name=None, team_preference=None, federation_number=None, apd_id=None,
        membership_expires=None, ticket_hash=None, updated_at=now).execution_options(synchronize_session=False))
    # The chrono sharing link is one per account.
    if await db.get(HubShareLink, a.id) is not None:
        await hub_share.unlink(db, b.id)
        await db.execute(delete(HubShareLink).where(HubShareLink.user_id == b.id))
    moved: dict[str, int] = {}
    for table, column in user_columns():
        result = await db.execute(update(table).where(column == b.id).values({column.name: a.id})
                                  .execution_options(synchronize_session=False))
        if result.rowcount:
            key = table.name if column.name == "user_id" else f"{table.name}.{column.name}"
            moved[key] = result.rowcount
    await db.execute(delete(Base.metadata.tables["oidc_logins"]).where(
        Base.metadata.tables["oidc_logins"].c.user_id == b.id))
    await db.execute(update(UserSession).where(UserSession.user_id == b.id, UserSession.revoked_at.is_(None))
                     .values(revoked_at=now))  # its refresh tokens go with the session
    await db.execute(update(User).where(User.id == b.id).values(
        username=personal_data.ERASED_PREFIX + secrets.token_hex(8), email=None,
        password_hash=personal_data.ERASED_PASSWORD, totp_secret_enc=None, totp_enabled=False, totp_last_step=None,
        server_admin=False, gdpr_consent_at=None, last_login_at=None).execution_options(synchronize_session=False))
    await db.flush()
    return moved
