# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ORM models (ADR-P4-1; migrations 0001_base, 0002_accounts, 0003_personal_data, 0004_sync, 0005_chrono,
0006_scheduling, 0007_registration, 0008_integrations, 0009_clubs, 0010_firmware; 0011_history in
``history_models``; 0012_atak in ``atak_models``; 0013_preview_feedback in ``preview_models``; 0015_login_methods: ``user_identities``,
``passkeys``, ``oidc_logins``, ``sessions.confirmed_at`` and a nullable ``users.password_hash``).

Fields, users, roles, per-field roles, sessions and the audit log, as
ADR-P4-1 defines them, with plan phase 11's additions for accounts: the
server administrator flag and the last TOTP step on ``users``, the second
factor on ``sessions``, and ``refresh_tokens`` (only hashes); plan phase 12's
``consents`` (ADR-P4-8); plan phase 13's controller sync (ADR-P4-3 as amended):
``field_api_keys``, ``controllers``, ``games``, ``game_events``,
``game_node_scores``, ``game_nodes`` and the per-game roles,
``user_game_roles``; plan phase 14's chrono registry (ADR-P4-5 as amended):
``marshal_keys``, ``replicas``, ``chrono_readings``, ``chrono_rejects``,
``chrono_violations`` and ``field_player_ids``, with ``consents.field_id``
for the per-field ``chrono_sharing`` consent; plan phase 15's ``scheduled_games`` (ADR-P4-11) and
the field page's columns on ``fields`` (``public_page``, ``description``, ``address_text``,
``federation_label``); plan phase 16's registrations (migration 0007_registration):
``game_registrations``, ``registration_replicas``, ``player_id_claims``, the link from a scheduled
game to the controller's game (``scheduled_games.controller_game``, ``walkins``) and the field's
check-in rules for registering (``fields.limit_template``, ``max_replicas``); plan phase 17's platform
adapters (migration 0008_integrations): ``platform_links`` and ``external_game_links``; plan phase 18's
clubs and branding (migration 0009_clubs, P4R19): ``branding_images``, ``clubs``, ``club_members``,
``club_reports``, ``field_teams`` and the field's branding columns on ``fields``; plan phase 19's firmware
catalogue (migration 0010_firmware): ``firmware_releases``; the remote ATAK relay's certificates (migration
0012_atak, Phase 4 follow-up FU5) in ``atak_models``. A table that holds personal data must also be added to
``personal_data.py`` (access, export, erasure, the purge) in the same plan
phase. Every later plan phase adds its own tables here and in
its own Alembic migration; ``tests.test_migrations`` checks that the
migrations build exactly these models. User-facing keys are UUIDv7
(``ids.uuid7``) with ``gen_random_uuid()`` as the database's fallback;
``created_at`` and ``updated_at`` are ``TIMESTAMPTZ`` set by the database.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, LargeBinary,
                        MetaData, PrimaryKeyConstraint, SmallInteger, String, Text, UniqueConstraint, func, text)
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
    # How long the field's controllers keep chrono records (and this server its registry, migration 0022, decision
    # RET-2) and an ended game's events, scores and nodes (decision RET-1): 30-3653 days, 365 by default.
    default_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="365")
    game_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="365")
    chrono_sharing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    public_scoreboard: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # The public field page and its feeds (ADR-P4-11, ADR-P4-12; plan phase 15): off by default.
    public_page: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    description: Mapped[Optional[str]] = mapped_column(Text)
    address_text: Mapped[Optional[str]] = mapped_column(String(512))
    federation_label: Mapped[Optional[str]] = mapped_column(String(16))
    # APD membership rule (migration 0016, protocol/apd.md): null is the default rule (any APD, nothing asked).
    apd_rule: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    # The field's country (migration 0019): ISO 3166-1 alpha-2, null is unset. It picks the wording of the
    # membership texts ("APD" for PT, "association membership" otherwise) and the shipped list's entries offered.
    country: Mapped[Optional[str]] = mapped_column(String(2))
    # Registration's replica rules (plan phase 16): the controller's [checkin] limit_template and
    # max_replicas, so a pre-declared replica is one the field's check-in accepts.
    limit_template: Mapped[str] = mapped_column(String(32), nullable=False, server_default="portugal")
    max_replicas: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="5")
    # The field's branding (plan phase 18, P4R19): what its controllers show with [sync] branding = "site".
    branding_name: Mapped[Optional[str]] = mapped_column(String(48))
    accent: Mapped[Optional[str]] = mapped_column(String(7))
    logo_sha256: Mapped[Optional[str]] = mapped_column(ForeignKey("branding_images.sha256"))
    wallpaper_sha256: Mapped[Optional[str]] = mapped_column(ForeignKey("branding_images.sha256"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    __table_args__ = (CheckConstraint("accent IS NULL OR accent ~ '^#[0-9a-f]{6}$'", name="accent"),
                      CheckConstraint("country IS NULL OR country ~ '^[A-Z]{2}$'", name="country"),
                      CheckConstraint("default_retention_days BETWEEN 30 AND 3653", name="default_retention_days"),
                      CheckConstraint("game_retention_days BETWEEN 30 AND 3653", name="game_retention_days"))


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
    # NULL: no password (the account signs in with a passkey or a social login, plan "login methods", LG-3).
    password_hash: Mapped[Optional[str]] = mapped_column(String(256))
    totp_secret_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # The time step of the last TOTP code accepted: a code is used once (RFC 6238 section 5.2).
    totp_last_step: Mapped[Optional[int]] = mapped_column(BigInteger)
    server_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    gdpr_consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
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
    # The last time the account proved it is there (a login, a TOTP or passkey step-up, a social re-login): an
    # account with no password confirms a sensitive change with a proof this recent (LG-6).
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class UserIdentity(Base):
    """A social login linked to an account (OpenID Connect, LG-1): the provider and the subject the provider
    gave, nothing of the profile. One per provider per account; a subject belongs to one account."""

    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("provider", "subject"), UniqueConstraint("user_id", "provider"),
                      CheckConstraint("provider IN ('google', 'microsoft', 'apple')", name="provider"))

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = _created()
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Passkey(Base):
    """A WebAuthn credential of an account (LG-2). ``rp_id`` is the host name it was made for."""

    __tablename__ = "passkeys"
    __table_args__ = (Index("idx_passkeys_user", "user_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    credential_id: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    rp_id: Mapped[str] = mapped_column(String(255), nullable=False)
    transports: Mapped[Optional[str]] = mapped_column(String(128))
    backed_up: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class OidcLogin(Base):
    """A social login in progress (LG-1): the state, nonce and PKCE verifier of one authorization request, for
    ten minutes and one use (the callback deletes the row). ``binding_hash`` is the hash of the random value in
    the browser's short-lived cookie, so a callback can only be finished by the browser that began it."""

    __tablename__ = "oidc_logins"
    __table_args__ = (Index("idx_oidc_logins_expires", "expires_at"),
                      CheckConstraint("purpose IN ('login', 'link', 'reauth')", name="purpose"))

    id: Mapped[uuid.UUID] = _uuid_pk()
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    binding_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(8), nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("sessions.id", ondelete="CASCADE"))
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    code_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    return_to: Mapped[str] = mapped_column(String(512), nullable=False)
    consent: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
    the record that shows what was consented to (GDPR Art. 7(1)). Purposes: ``account``, and
    ``chrono_sharing`` (plan phase 14) with the field whose chrono records the person lets other
    sharing fields see (``field_id``; one live consent per field)."""

    __tablename__ = "consents"
    __table_args__ = (
        Index("idx_consents_user", "user_id"),
        Index("uq_consents_live", "user_id", "purpose", unique=True,
              postgresql_where=text("withdrawn_at IS NULL AND field_id IS NULL")),
        Index("uq_consents_live_field", "user_id", "purpose", "field_id", unique=True,
              postgresql_where=text("withdrawn_at IS NULL AND field_id IS NOT NULL")),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    field_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"))
    notice_version: Mapped[str] = mapped_column(String(64), nullable=False)
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    withdrawn_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# --- the controller sync (plan phase 13, migration 0004_sync) -----------------------------

GAME_STATES = ("ready", "running", "paused", "ended")


class FieldApiKey(Base):
    """A field's API key for its controllers (P4R13): only its SHA-256 (hex) is kept; the key is
    shown once when it is made. At most two live keys per field (a rotation), checked when one is
    made; a revoked key stays listed."""

    __tablename__ = "field_api_keys"
    __table_args__ = (Index("idx_field_api_keys_field", "field_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    key_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    label: Mapped[Optional[str]] = mapped_column(String(64))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Controller(Base):
    """A field controller that synced (its own random id, protocol/sync.md): version, first and
    last seen, the key it used last. A standby controller is a row of its own."""

    __tablename__ = "controllers"
    __table_args__ = (UniqueConstraint("field_id", "controller_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    controller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    api_key_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("field_api_keys.id", ondelete="SET NULL"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Game(Base):
    """A controller's game: ``(field_id, game_id, game_seed)`` (P4R11), ``game_id`` being the 16-bit
    id on the radio. The controller's own times are ``controller_created_at``, ``started_at`` and
    ``ended_at``; ``created_at`` and ``updated_at`` are the site server's."""

    __tablename__ = "games"
    __table_args__ = (
        UniqueConstraint("field_id", "game_id", "game_seed"),
        CheckConstraint("state IN ('ready', 'running', 'paused', 'ended')", name="state"),
        CheckConstraint("game_id BETWEEN 0 AND 65535 AND game_seed BETWEEN 0 AND 4294967295", name="radio_id"),
        Index("idx_games_field_created", "field_id", "controller_created_at"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    game_id: Mapped[int] = mapped_column(Integer, nullable=False)
    game_seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    mode_id: Mapped[str] = mapped_column(String(128), nullable=False)
    teams: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    team_info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    squads: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    controller_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class GameEvent(Base):
    """One event of a game's log, append-only; unique on the controller's own key (P4R11)."""

    __tablename__ = "game_events"
    __table_args__ = (
        UniqueConstraint("game", "node_id", "seq", "game_time_ms", "event_type"),
        Index("idx_game_events_game_time", "game", "game_time_ms"),
        Index("idx_game_events_type", "game", "event_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    game: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    game_time_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    team: Mapped[Optional[str]] = mapped_column(String(32))
    squad: Mapped[Optional[int]] = mapped_column(SmallInteger)
    priority: Mapped[str] = mapped_column(String(16), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    epoch: Mapped[Optional[int]] = mapped_column(Integer)
    pkt_seq: Mapped[Optional[int]] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GameNodeScore(Base):
    """A score counter per (game, source, team), merged by ``GREATEST`` (P4R10). A source is a node
    (``node-3``) or one run of a controller's field script (``field-1@0``, decision S13-3)."""

    __tablename__ = "game_node_scores"
    __table_args__ = (PrimaryKeyConstraint("game", "source", "team"),
                      CheckConstraint("value >= 0", name="value"))

    game: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    team: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class GameNode(Base):
    """A game's node: name, role, health (the allowed ``info`` keys of protocol/sync.md)."""

    __tablename__ = "game_nodes"
    __table_args__ = (PrimaryKeyConstraint("game", "node_id"),)

    game: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    node_id: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class UserGameRole(Base):
    """A role on one game (ADR-P4-1's ``user_game_roles``; decision S11-6): the same roles and the
    same TOTP rule as per field."""

    __tablename__ = "user_game_roles"
    __table_args__ = (UniqueConstraint("user_id", "game", "role_id"),
                      Index("idx_user_game_roles_game", "game"))

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    game: Mapped[uuid.UUID] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), nullable=False)
    role_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("roles.id"), nullable=False)
    granted_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


# --- the chrono registry (plan phase 14, migration 0005_chrono) ---------------------------

KEY_SOURCES = ("controller", "account")
READING_TYPES = ("checkin", "spotcheck", "retest")
OUTCOMES = ("pass", "fail", "warn", "unjudged")
REJECT_REASONS = ("format", "unsigned", "signature", "marshal", "conflict")
VIOLATION_TYPES = ("over_limit", "over_tolerance")
VIOLATION_OUTCOMES = ("warning", "pulled", "ban")


class FieldPlayerId(Base):
    """An account's pseudonymous player id at one field (ADR-P4-11's ``field_player_ids``, the phase 3
    form ``p-`` + 12 base32). Made here for the chrono registry's own history, erasure and sharing
    (decision S14-3); an account adopts a phone's id with its secret in plan phase 16."""

    __tablename__ = "field_player_ids"
    __table_args__ = (UniqueConstraint("field_id", "player_id"), Index("idx_field_player_ids_user", "user_id"))

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = _created()


class HubShareLink(Base):
    """Hosted mode only (SVX-2, ADR-P4-4's 2026-10-28 amendment): this account is one person's account at this
    field, and ``person_id`` is the random id the person's accounts at the hub's other fields hold too. Made
    when the person asks for a link code or gives one (``hub_share.py``); never derived from an e-mail
    address or a user name. A single-field server never has a row."""

    __tablename__ = "hub_share_links"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, unique=True)
    linked_at: Mapped[datetime] = _created()


class MarshalKey(Base):
    """A marshal's Ed25519 public key at a field, with the period it was the marshal's key in
    (P4R14): from its first registration until it was replaced (``valid_until``, NULL while
    current) or revoked as compromised. Never a private key. Old keys stay, so old records still
    verify. ``user_id`` links the key to a marshal's account when the account registered it."""

    __tablename__ = "marshal_keys"
    __table_args__ = (
        UniqueConstraint("field_id", "marshal_id", "public_key"),
        CheckConstraint("octet_length(public_key) = 32", name="public_key"),
        CheckConstraint("source IN ('controller', 'account')", name="source"),
        Index("idx_marshal_keys_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    marshal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    player_id: Mapped[Optional[str]] = mapped_column(String(64))
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Replica(Base):
    """A replica of a field's registry (ADR-P4-1's amendment): the app's ``replica_id`` per field,
    its owner by the field's pseudonymous player id, type (``sniper`` included), class."""

    __tablename__ = "replicas"
    __table_args__ = (UniqueConstraint("field_id", "replica_id"), Index("idx_replicas_owner", "field_id",
                                                                        "owner_player_id"))

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    replica_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    owner_player_id: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_type: Mapped[str] = mapped_column(String(16), nullable=False)
    replica_class: Mapped[str] = mapped_column(String(32), nullable=False)
    make_model: Mapped[Optional[str]] = mapped_column(String(64))
    tag_type: Mapped[Optional[str]] = mapped_column(String(8))
    tag_uid: Mapped[Optional[str]] = mapped_column(String(64))
    registered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ChronoReading(Base):
    """One signed chrono reading (P4R15): ``record_json`` exactly as the controller sent it, verified on
    arrival with ``atalaia_controller.chrono`` and the marshal's key valid then (``marshal_key``); the
    record's fields as columns for queries; the controller's series and its outcome."""

    __tablename__ = "chrono_readings"
    __table_args__ = (
        UniqueConstraint("field_id", "reading_id"),
        CheckConstraint("type IN ('checkin', 'spotcheck', 'retest')", name="type"),
        CheckConstraint("outcome IS NULL OR outcome IN ('pass', 'fail', 'warn', 'unjudged')", name="outcome"),
        Index("idx_chrono_readings_player", "field_id", "player_id"),
        Index("idx_chrono_readings_replica", "field_id", "replica_id"),
        Index("idx_chrono_readings_series", "field_id", "series_id"),
        Index("idx_chrono_readings_time", "field_id", "timestamp"),
        Index("idx_chrono_readings_key", "marshal_key"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    reading_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    record_json: Mapped[str] = mapped_column(Text, nullable=False)
    replica_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    player_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    velocity_mps: Mapped[float] = mapped_column(Float, nullable=False)
    bb_weight_g: Mapped[float] = mapped_column(Float, nullable=False)
    energy_j: Mapped[float] = mapped_column(Float, nullable=False)
    chrono_id: Mapped[str] = mapped_column(String(64), nullable=False)
    marshal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    record_field_id: Mapped[str] = mapped_column(String(64), nullable=False)
    record_game_id: Mapped[Optional[str]] = mapped_column(String(64))
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ref_reading_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    series_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    outcome: Mapped[Optional[str]] = mapped_column(String(16))
    marshal_key: Mapped[uuid.UUID] = mapped_column(ForeignKey("marshal_keys.id"), nullable=False)
    game: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    controller: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("controllers.id", ondelete="SET NULL"))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ChronoReject(Base):
    """A reading the site server could not verify, kept apart with its reason (``format``,
    ``unsigned``, ``signature``, ``marshal``: no key of the marshal valid when the controller got it,
    ``conflict``: another record under a stored reading id), never silently dropped. Once by its
    text's SHA-256; ``times`` counts the arrivals."""

    __tablename__ = "chrono_rejects"
    __table_args__ = (
        UniqueConstraint("field_id", "record_sha256"),
        CheckConstraint("reason IN ('format', 'unsigned', 'signature', 'marshal', 'conflict')", name="reason"),
        Index("idx_chrono_rejects_player", "field_id", "player_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    record_text: Mapped[str] = mapped_column(Text, nullable=False)
    record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[str] = mapped_column(String(256), nullable=False)
    reading_id: Mapped[Optional[str]] = mapped_column(String(64))
    player_id: Mapped[Optional[str]] = mapped_column(String(64))
    marshal_id: Mapped[Optional[str]] = mapped_column(String(64))
    series_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    outcome: Mapped[Optional[str]] = mapped_column(String(16))
    controller: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("controllers.id", ondelete="SET NULL"))
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    times: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ChronoViolation(Base):
    """A spot check that failed (``over_limit``) or warned (``over_tolerance``), one per series, with
    the series' deciding (highest energy) reading; staff record what was done (``outcome``)."""

    __tablename__ = "chrono_violations"
    __table_args__ = (
        UniqueConstraint("field_id", "series_id"),
        CheckConstraint("violation_type IN ('over_limit', 'over_tolerance')", name="violation_type"),
        CheckConstraint("outcome IS NULL OR outcome IN ('warning', 'pulled', 'ban')", name="outcome"),
        Index("idx_chrono_violations_reading", "reading"),
        Index("idx_chrono_violations_player", "field_id", "player_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    series_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reading: Mapped[uuid.UUID] = mapped_column(ForeignKey("chrono_readings.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(64), nullable=False)
    replica_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    violation_type: Mapped[str] = mapped_column(String(32), nullable=False)
    energy_j: Mapped[float] = mapped_column(Float, nullable=False)
    # PKD-3: the class limit the controller judged against, the excess over it, and whether the player had an
    # earlier violation at the field (limit_j and delta_j are null when the controller did not send the limit).
    limit_j: Mapped[Optional[float]] = mapped_column(Float)
    delta_j: Mapped[Optional[float]] = mapped_column(Float)
    repeat_offender: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    game: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    outcome: Mapped[Optional[str]] = mapped_column(String(16))
    resolved_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


# --- scheduling (plan phase 15, migration 0006_scheduling) -------------------------------

# Stored statuses (ADR-P4-11): ``registering`` is not one, it is computed from the window.
SCHEDULED_STATUSES = ("draft", "published", "in_progress", "completed", "cancelled")
FEDERATION_RULES = ("off", "optional", "required")


class ScheduledGame(Base):
    """A game a field announces (ADR-P4-1's ``scheduled_games`` with ADR-P4-11's columns): times in UTC
    (shown in ``fields.timezone``), the mode if already chosen, the registration window and its rules.
    ``draft`` is seen by staff only; ``published`` and later are on the field page and the feeds;
    ``cancelled`` stays visible with its reason. ``ical_sequence`` is the iCalendar ``SEQUENCE``, raised
    when the time, the place or the status of a published game changes (ADR-P4-12). Its registrations
    (``game_registrations``) and the controller's game made from it (``controller_game``) are plan phase
    16's; ``in_progress`` and ``completed`` follow that game's state. Presets and scenarios: plan phase 20."""

    __tablename__ = "scheduled_games"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'in_progress', 'completed', 'cancelled')", name="status"),
        CheckConstraint("federation IN ('off', 'optional', 'required')", name="federation"),
        CheckConstraint("ends_at > starts_at", name="times"),
        CheckConstraint("registration_closes_at IS NULL OR registration_opens_at IS NULL "
                        "OR registration_closes_at > registration_opens_at", name="window"),
        CheckConstraint("max_players IS NULL OR max_players BETWEEN 1 AND 10000", name="max_players"),
        CheckConstraint("ical_sequence >= 0", name="ical_sequence"),
        CheckConstraint("walkins IS NULL OR walkins >= 0", name="walkins"),
        Index("idx_scheduled_games_field_starts", "field_id", "starts_at"),
        Index("idx_scheduled_games_created_by", "created_by"),
        Index("idx_scheduled_games_controller_game", "controller_game"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location_text: Mapped[Optional[str]] = mapped_column(String(512))
    mode_id: Mapped[Optional[str]] = mapped_column(String(128))
    teams: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    max_players: Mapped[Optional[int]] = mapped_column(Integer)
    registration_opens_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    registration_closes_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    federation: Mapped[str] = mapped_column(String(16), nullable=False, server_default="off")
    predeclare_replicas: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cancelled_reason: Mapped[Optional[str]] = mapped_column(String(512))
    ical_sequence: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # Plan phase 16: the controller's game made from this one (ADR-P4-11's controller_game_id; a
    # games.id, not the radio's 16-bit game_id, decision S13-6) and how many walked in (a count only).
    controller_game: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("games.id", ondelete="SET NULL"))
    walkins: Mapped[Optional[int]] = mapped_column(Integer)
    # Phase 4 follow-up FU7 (migration 0014): the last roster pull (a controller's GET carries only its key
    # and User-Agent, so those are what is kept: the key's label and fingerprint as they were then).
    roster_pulled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    roster_key_label: Mapped[Optional[str]] = mapped_column(String(64))
    roster_key_fingerprint: Mapped[Optional[str]] = mapped_column(String(8))
    roster_agent: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# --- registration (plan phase 16, migration 0007_registration) ---------------------------

REGISTRATION_STATUSES = ("registered", "cancelled", "checked_in", "no_show")
CLAIM_STATUSES = ("pending", "confirmed", "refused")


class GameRegistration(Base):
    """A registration for a scheduled game (ADR-P4-11): the player's id at the field, a display name for
    that game, a team preference, the federation number when the game asks for one, and the SHA-256 of
    the check-in ticket (the secret is shown once to the player and never stored). ``user_id`` is the
    account (null once erased, and for plan phase 17's imports). The outcome (``checked_in``,
    ``no_show``) comes from the controller after the game; the controller is the authority on the day."""

    __tablename__ = "game_registrations"
    __table_args__ = (
        UniqueConstraint("scheduled_game", "player_id"),
        UniqueConstraint("scheduled_game", "user_id"),
        UniqueConstraint("scheduled_game", "source", "external_ref"),
        CheckConstraint("status IN ('registered', 'cancelled', 'checked_in', 'no_show')", name="status"),
        CheckConstraint("paid_by IS NULL OR paid_at IS NOT NULL", name="paid"),
        CheckConstraint("apd_id IS NULL OR apd_id ~ '^[a-z0-9][a-z0-9-]{0,31}$'", name="apd_id"),
        Index("idx_game_registrations_paid_by", "paid_by"),
        Index("idx_game_registrations_outcome_by", "outcome_by"),
        Index("idx_game_registrations_user", "user_id"),
        Index("idx_game_registrations_field_player", "field_id", "player_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    scheduled_game: Mapped[uuid.UUID] = mapped_column(ForeignKey("scheduled_games.id", ondelete="CASCADE"),
                                                      nullable=False)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    player_id: Mapped[str] = mapped_column(String(14), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(32))
    team_preference: Mapped[Optional[str]] = mapped_column(String(32))
    # The membership number (migration 0016: ``federation_number`` is it; ``apd_id`` null is "APD unknown"),
    # the APD the player declared and the expiry. Personal data, erased together (protocol/apd.md).
    federation_number: Mapped[Optional[str]] = mapped_column(String(32))
    apd_id: Mapped[Optional[str]] = mapped_column(String(32))
    membership_expires: Mapped[Optional[date]] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="registered")
    ticket_hash: Mapped[Optional[str]] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="site")
    external_ref: Mapped[Optional[str]] = mapped_column(String(128))
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    outcome_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Phase 4 follow-up FU7 (migration 0014): what staff record. ``paid_at`` (with who marked it) is only a
    # note, no payment is processed; ``outcome_by`` is the staff account that marked a no-show by hand (null
    # for an outcome the controller reported).
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    paid_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    outcome_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class RegistrationReplica(Base):
    """A pre-declared replica: it becomes a declaration (``declaration_id``) in the controller's
    "replicas to chrono" list. ``state`` and ``reading_id`` are the controller's final ones, after the game."""

    __tablename__ = "registration_replicas"
    __table_args__ = (
        UniqueConstraint("declaration_id"),
        CheckConstraint("state IS NULL OR state IN ('pending', 'passed', 'refused', 'withdrawn')", name="state"),
        Index("idx_registration_replicas_registration", "registration"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    registration: Mapped[uuid.UUID] = mapped_column(ForeignKey("game_registrations.id", ondelete="CASCADE"),
                                                    nullable=False)
    declaration_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    replica_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))
    replica_type: Mapped[str] = mapped_column(String(16), nullable=False)
    replica_class: Mapped[str] = mapped_column(String(32), nullable=False)
    make_model: Mapped[Optional[str]] = mapped_column(String(64))
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    state: Mapped[Optional[str]] = mapped_column(String(16))
    reading_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True))


class PlayerIdClaim(Base):
    """An account's claim to a player id its phone already has at a field (a phase 3 field identity made
    without an account), with the SHA-256 of the phone's secret. The site server never had that secret's
    hash: the field's controller does, and confirms or refuses the claim over its sync (decision S16-4).
    Only a confirmed claim becomes a ``field_player_ids`` link."""

    __tablename__ = "player_id_claims"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'confirmed', 'refused')", name="status"),
        Index("idx_player_id_claims_field_status", "field_id", "status"),
        Index("idx_player_id_claims_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[str] = mapped_column(String(14), nullable=False)
    secret_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = _created()
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class PlatformLink(Base):
    """A field's link to an external platform through one adapter (ADR-P4-12; plan phase 17): off until
    the field's admin turns it on, its configuration (credentials included) encrypted with Fernet under a
    key derived from ATALAIA_SECRET_KEY (``integrations.ConfigBox``)."""

    __tablename__ = "platform_links"
    __table_args__ = (UniqueConstraint("field_id", "adapter_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(32), nullable=False)
    config_enc: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ExternalGameLink(Base):
    """A scheduled game as it is known on an external platform: the platform's reference, when it was
    last sent and the last error (a failing platform never blocks scheduling, publication or check-in)."""

    __tablename__ = "external_game_links"
    __table_args__ = (UniqueConstraint("scheduled_game_id", "adapter_id"),)

    id: Mapped[uuid.UUID] = _uuid_pk()
    scheduled_game_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scheduled_games.id", ondelete="CASCADE"),
                                                         nullable=False)
    adapter_id: Mapped[str] = mapped_column(String(32), nullable=False)
    external_ref: Mapped[Optional[str]] = mapped_column(String(256))
    cancelled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created()


# --- clubs and branding (plan phase 18, migration 0009_clubs; P4R19) -------------------

CLUB_ROLES = ("admin", "member")
REPORT_REASONS = ("rights", "offensive", "impersonation", "other")
REPORT_STATUSES = ("open", "dismissed", "actioned")


class BrandingImage(Base):
    """An image checked by the controller's ``images.py`` (the same limits as the controller's uploads), stored
    once as checked (metadata stripped) and named by the SHA-256 of those bytes, which controllers fetch it by.
    Who uploaded it is in the audit log, not here; one no club, field or saved team uses is deleted by the daily
    purge a day after its upload."""

    __tablename__ = "branding_images"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    content_type: Mapped[str] = mapped_column(String(16), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = _created()


class Club(Base):
    """A club's profile: its name, the short name its teams carry on controllers, a description, a colour, a logo
    and a crest. Its public page (``/c/<slug>/``) is off by default; a server administrator can hide it
    (``hidden_at``), after a report or not."""

    __tablename__ = "clubs"
    __table_args__ = (
        CheckConstraint("colour IS NULL OR colour ~ '^#[0-9a-f]{6}$'", name="colour"),
        Index("idx_clubs_created_by", "created_by"),
        Index("idx_clubs_hidden_by", "hidden_by"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    short_name: Mapped[str] = mapped_column(String(32), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    colour: Mapped[Optional[str]] = mapped_column(String(7))
    logo_sha256: Mapped[Optional[str]] = mapped_column(ForeignKey("branding_images.sha256"))
    crest_sha256: Mapped[Optional[str]] = mapped_column(ForeignKey("branding_images.sha256"))
    public_page: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    hidden_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    hidden_reason: Mapped[Optional[str]] = mapped_column(String(512))
    hidden_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ClubMember(Base):
    """An account's membership of a club, with its club role: ``admin`` edits the club and its members,
    ``member`` is listed. A club admin invites an account by its username; it is a member once the person
    accepts (``accepted_at``); an invitation not accepted goes after 30 days. Personal data
    (``personal_data.py``)."""

    __tablename__ = "club_members"
    __table_args__ = (
        UniqueConstraint("club_id", "user_id"),
        CheckConstraint("role IN ('admin', 'member')", name="role"),
        Index("idx_club_members_user", "user_id"),
        Index("idx_club_members_added_by", "added_by"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    club_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="member")
    added_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class ClubReport(Base):
    """A report of a public club page (its report button): a reason and a text, the reporting account if
    logged in (no address is kept), and the server administrator's decision."""

    __tablename__ = "club_reports"
    __table_args__ = (
        CheckConstraint("reason IN ('rights', 'offensive', 'impersonation', 'other')", name="reason"),
        CheckConstraint("status IN ('open', 'dismissed', 'actioned')", name="status"),
        Index("idx_club_reports_status_created", "status", "created_at"),
        Index("idx_club_reports_club", "club_id"),
        Index("idx_club_reports_reporter", "reporter_id"),
        Index("idx_club_reports_decided_by", "decided_by"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    club_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[Optional[str]] = mapped_column(Text)
    reporter_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _created()


class FieldTeam(Base):
    """A field's saved team (a controller's team preset, BR14): a club's team (its short name and crest unless
    the team sets its own) or a team of its own; the colour it usually plays. Synced to the field's controllers
    with ``[sync] branding = "site"``. A club's deletion takes its teams with it."""

    __tablename__ = "field_teams"
    __table_args__ = (
        CheckConstraint("name IS NOT NULL OR club_id IS NOT NULL", name="named"),
        Index("idx_field_teams_field", "field_id"),
        Index("idx_field_teams_club", "club_id"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    field_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("fields.id", ondelete="CASCADE"), nullable=False)
    club_id: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("clubs.id", ondelete="CASCADE"))
    name: Mapped[Optional[str]] = mapped_column(String(32))
    colour: Mapped[Optional[str]] = mapped_column(String(23))
    crest_sha256: Mapped[Optional[str]] = mapped_column(ForeignKey("branding_images.sha256"))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class FirmwareRelease(Base):
    """A firmware release in the catalogue (plan phase 19): a list only, no image is stored or served (the
    field controller holds the images it offers its boxes: decision FU3-3). Each entry is signed with Ed25519 by a release key the server trusts
    (``ATALAIA_FIRMWARE_KEYS``) over ``firmware.manifest``: platform, version, size and the image's SHA-256;
    ``key_id`` names the key. A withdrawn release keeps its row with ``yanked_at`` (decision S19-6)."""

    __tablename__ = "firmware_releases"
    __table_args__ = (
        UniqueConstraint("platform", "version"),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256"),
        CheckConstraint("size > 0", name="size"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    platform: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(String(88), nullable=False)
    key_id: Mapped[str] = mapped_column(String(16), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    released_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    added_by: Mapped[Optional[uuid.UUID]] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    yanked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    yank_reason: Mapped[Optional[str]] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


# Plan phase 20's tables (game history and the scenario library, migration 0011_history) live in their own
# module; importing it here puts them in Base.metadata.
from . import history_models  # noqa: E402,F401  (after Base and the tables it points at)
# The remote ATAK relay's certificates (Phase 4 follow-up FU5, migration 0012_atak).
from . import atak_models  # noqa: E402,F401
# The preview deployment's feedback form (decisions PV-*, migration 0013_preview_feedback).
from . import preview_models  # noqa: E402,F401
