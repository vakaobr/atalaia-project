# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""ORM models (ADR-P4-1; migrations 0001_base, 0002_accounts, 0003_personal_data, 0004_sync, 0005_chrono,
0006_scheduling).

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
``federation_label``). A table that holds personal data must also be added to
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

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, LargeBinary,
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
    default_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="365")
    chrono_sharing_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    public_scoreboard: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # The public field page and its feeds (ADR-P4-11, ADR-P4-12; plan phase 15): off by default.
    public_page: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    description: Mapped[Optional[str]] = mapped_column(Text)
    address_text: Mapped[Optional[str]] = mapped_column(String(512))
    federation_label: Mapped[Optional[str]] = mapped_column(String(16))
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
    when the time, the place or the status of a published game changes (ADR-P4-12). Registrations and
    ``controller_game_id`` come with plan phase 16; presets and scenarios with plan phase 20."""

    __tablename__ = "scheduled_games"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'in_progress', 'completed', 'cancelled')", name="status"),
        CheckConstraint("federation IN ('off', 'optional', 'required')", name="federation"),
        CheckConstraint("ends_at > starts_at", name="times"),
        CheckConstraint("registration_closes_at IS NULL OR registration_opens_at IS NULL "
                        "OR registration_closes_at > registration_opens_at", name="window"),
        CheckConstraint("max_players IS NULL OR max_players BETWEEN 1 AND 10000", name="max_players"),
        CheckConstraint("ical_sequence >= 0", name="ical_sequence"),
        Index("idx_scheduled_games_field_starts", "field_id", "starts_at"),
        Index("idx_scheduled_games_created_by", "created_by"),
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
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
