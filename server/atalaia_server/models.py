# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ORM models (ADR-P4-1; migrations 0001_base, 0002_accounts and 0003_personal_data).

Fields, users, roles, per-field roles, sessions and the audit log, as
ADR-P4-1 defines them, with plan phase 11's additions for accounts: the
server administrator flag and the last TOTP step on ``users``, the second
factor on ``sessions``, and ``refresh_tokens`` (only hashes); plan phase 12's
``consents`` (ADR-P4-8). A table that holds personal data must also be added to
``personal_data.py`` (access, export, erasure, the purge) in the same plan
phase. Every later plan phase adds its own tables here and in
its own Alembic migration; ``tests.test_migrations`` checks that the
migrations build exactly these models. User-facing keys are UUIDv7
(``ids.uuid7``) with ``gen_random_uuid()`` as the database's fallback;
``created_at`` and ``updated_at`` are ``TIMESTAMPTZ`` set by the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, MetaData,
                        SmallInteger, String, UniqueConstraint, func, text)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .ids import uuid7

# Constraint names Alembic can find again in a downgrade.
NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

# The roles table's rows (ADR-P4-1), seeded by migration 0001_base.
ROLES: tuple[tuple[int, str], ...] = (
    (1, "player"), (2, "squad_leader"), (3, "vip"), (4, "marshal"), (5, "gm"), (6, "spectator"), (7, "admin"),
)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7,
                         server_default=text("gen_random_uuid()"))


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Field(Base):
    __tablename__ = "fields"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    field_type: Mapped[str] = mapped_column(String(32), nullable=False, server_default="outdoor")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, server_default="Europe/Lisbon")
    default_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="365")
    chrono_sharing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    public_scoreboard: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# Roles that need TOTP (ADR-P4-2): granting one to an account without TOTP fails, and they
# count only in a session that passed the TOTP step.
PRIVILEGED_ROLES = frozenset({"admin", "gm", "marshal"})
ROLE_NAMES = {name: role_id for role_id, name in ROLES}
ROLE_BY_ID = {role_id: name for role_id, name in ROLES}


class User(Base):
    """An account. Usernames are stored lower-case (a check constraint), so they are unique
    whatever the case typed. ``server_admin`` (plan phase 11) is the site server's own
    administrator, made by ``python -m atalaia_server create-admin``: it manages fields and
    roles everywhere and reads the metrics, and always has TOTP."""

    __tablename__ = "users"
    __table_args__ = (CheckConstraint("username = lower(username)", name="username_lower"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    totp_secret_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # The time step of the last TOTP code accepted: a code is used once (RFC 6238 section 5.2).
    totp_last_step: Mapped[Optional[int]] = mapped_column(BigInteger)
    server_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    gdpr_consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    data_retention_days: Mapped[Optional[int]] = mapped_column(Integer)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)


class UserFieldRole(Base):
    __tablename__ = "user_field_roles"
    __table_args__ = (UniqueConstraint("user_id", "field_id", "role_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("roles.id"), nullable=False)
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class UserSession(Base):
    """One login (ADR-P4-2). ``mfa`` says the login passed the TOTP step; ``expires_at`` moves
    on at each refresh (7 days) but never past 30 days from ``created_at``. Its refresh tokens
    are in ``refresh_tokens``."""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_user", "user_id"),
        Index("idx_sessions_expires", "expires_at", postgresql_where=text("revoked_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    user_agent: Mapped[Optional[str]] = mapped_column(String(512))
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    mfa: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class RefreshToken(Base):
    """Every refresh token a session was given, as its SHA-256 (the token itself is never stored).

    Rotation marks the presented token ``used_at`` and issues a new one; a token presented
    again after that is a replay, and the whole session is revoked (ADR-P4-2)."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("idx_refresh_tokens_session", "session_id"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _created()
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_log_user", "user_id"),
        Index("idx_audit_log_action", "action"),
        Index("idx_audit_log_created", "created_at"),
        Index("idx_audit_log_resource", "resource_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource: Mapped[Optional[str]] = mapped_column(String(64))
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    created_at: Mapped[datetime] = _created()


class Consent(Base):
    """A consent given (ADR-P4-8, plan phase 12): its purpose, the version of the privacy notice
    the person was shown, when, and when it was withdrawn. At most one live consent per purpose.
    ``users.gdpr_consent_at`` keeps the account consent's time, as ADR-P4-1 has it; this table is
    the record that shows what was consented to (GDPR Art. 7(1)). Purposes: ``account`` now;
    ``chrono_sharing`` comes with the chrono registry (plan phase 14)."""

    __tablename__ = "consents"
    __table_args__ = (
        Index("idx_consents_user", "user_id"),
        Index("uq_consents_live", "user_id", "purpose", unique=True, postgresql_where=text("withdrawn_at IS NULL")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    notice_version: Mapped[str] = mapped_column(String(64), nullable=False)
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
