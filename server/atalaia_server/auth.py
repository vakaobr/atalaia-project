# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Who is calling, and what they may do (ADR-P4-2's role checks).

``current_principal`` reads the ``Authorization: Bearer`` access token, then
the database: the session must exist, belong to the token's user, be neither
revoked nor expired, and the roles are the user's rows in
``user_field_roles`` now, not the token's ``roles`` claim. A logout, a revoked
session or a removed role therefore counts at the next request.

Roles are per field. ``admin``, ``gm`` and ``marshal`` need TOTP (granting
them to an account without TOTP fails) and count only in a session that
passed the TOTP step (``sessions.mfa``); so does the server administrator.
Per-game roles come with the ``games`` table (plan phase 13; decision S11-6).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session
from .models import PRIVILEGED_ROLES, ROLE_BY_ID, User, UserFieldRole, UserSession
from .tokens import TokenError, read_access_token

UNAUTHORISED = {"WWW-Authenticate": "Bearer"}


@dataclass
class Principal:
    user: User
    session: UserSession
    roles: dict[uuid.UUID, set[str]] = field(default_factory=dict)

    @property
    def mfa(self) -> bool:
        return self.session.mfa

    @property
    def is_server_admin(self) -> bool:
        return self.user.server_admin and self.session.mfa

    def field_roles(self, field_id: uuid.UUID) -> set[str]:
        """The roles that count in this session: privileged ones only after the TOTP step."""
        roles = self.roles.get(field_id, set())
        return roles if self.session.mfa else roles - PRIVILEGED_ROLES

    def has_field_role(self, field_id: uuid.UUID, wanted: Iterable[str]) -> bool:
        return bool(self.field_roles(field_id) & set(wanted))

    def roles_claim(self) -> dict[str, list[str]]:
        return {str(f): sorted(r) for f, r in self.roles.items()}


def bearer(request: Request) -> Optional[str]:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not value.strip():
        return None
    return value.strip()


async def load_roles(db: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, set[str]]:
    rows = await db.execute(select(UserFieldRole.field_id, UserFieldRole.role_id)
                            .where(UserFieldRole.user_id == user_id))
    roles: dict[uuid.UUID, set[str]] = {}
    for field_id, role_id in rows:
        roles.setdefault(field_id, set()).add(ROLE_BY_ID[role_id])
    return roles


async def principal_from_token(request: Request, db: AsyncSession, token: str) -> Optional[Principal]:
    """The principal for a valid access token whose session is live, else None."""
    try:
        claims = read_access_token(request.app.state.keys, token)
    except TokenError:
        return None
    row = (await db.execute(
        select(UserSession, User).join(User, User.id == UserSession.user_id)
        .where(UserSession.id == claims.session_id, UserSession.user_id == claims.user_id))).first()
    if row is None:
        return None
    session, user = row
    if session.revoked_at is not None or session.expires_at <= datetime.now(timezone.utc):
        return None
    return Principal(user=user, session=session, roles=await load_roles(db, user.id))


async def current_principal(request: Request, db: AsyncSession = Depends(get_session)) -> Principal:
    token = bearer(request)
    principal = await principal_from_token(request, db, token) if token else None
    if principal is None:
        raise HTTPException(401, "not_authenticated", headers=UNAUTHORISED)
    return principal


async def server_admin(principal: Principal = Depends(current_principal)) -> Principal:
    if not principal.is_server_admin:
        raise HTTPException(403, "server_admin_required")
    return principal


def require_field_role(principal: Principal, field_id: uuid.UUID, *wanted: str) -> None:
    """403 unless the principal holds one of these roles on the field (a server administrator
    counts as the field's ``admin``)."""
    if principal.is_server_admin and "admin" in wanted:
        return
    if not principal.has_field_role(field_id, wanted):
        raise HTTPException(403, "role_required")
