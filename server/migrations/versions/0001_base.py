# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The base tables: fields, users, roles, user_field_roles, sessions, audit_log (ADR-P4-1).

Revision ID: 0001_base
Revises: (none)
Created: 2026-10-19

The roles are seeded here (ADR-P4-1's seven). ``fields`` has no
``api_key_hash``: controller API keys get their own table in 0004_sync (two
active during a rotation, P4R13). ``gen_random_uuid()`` is built into
PostgreSQL 13+, so no extension is needed.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_base"
down_revision = None
branch_labels = None
depends_on = None

ROLES = [
    {"id": 1, "name": "player"}, {"id": 2, "name": "squad_leader"}, {"id": 3, "name": "vip"},
    {"id": 4, "name": "marshal"}, {"id": 5, "name": "gm"}, {"id": 6, "name": "spectator"},
    {"id": 7, "name": "admin"},
]


def _uuid_pk() -> sa.Column:
    return sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def upgrade() -> None:
    op.create_table(
        "fields",
        _uuid_pk(),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("field_type", sa.String(32), nullable=False, server_default="outdoor"),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Lisbon"),
        sa.Column("default_retention_days", sa.Integer(), nullable=False, server_default="365"),
        sa.Column("chrono_sharing_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("public_scoreboard", sa.Boolean(), nullable=False, server_default="false"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_fields"),
        sa.UniqueConstraint("slug", name="uq_fields_slug"),
    )
    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("password_hash", sa.String(256), nullable=False),
        sa.Column("totp_secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default="false"),
        _ts("gdpr_consent_at", nullable=True, default=False),
        sa.Column("data_retention_days", sa.Integer(), nullable=True),
        _ts("last_login_at", nullable=True, default=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.SmallInteger(), autoincrement=False, nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("name", name="uq_roles_name"),
    )
    op.bulk_insert(roles, ROLES)
    op.create_table(
        "user_field_roles",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("field_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        _ts("granted_at"),
        sa.PrimaryKeyConstraint("id", name="pk_user_field_roles"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_field_roles_user_id_users",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_user_field_roles_field_id_fields",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_user_field_roles_role_id_roles"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], name="fk_user_field_roles_granted_by_users"),
        sa.UniqueConstraint("user_id", "field_id", "role_id", name="uq_user_field_roles_user_id_field_id_role_id"),
    )
    op.create_table(
        "sessions",
        _uuid_pk(),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("refresh_token", sa.String(512), nullable=False),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        _ts("expires_at", default=False),
        _ts("created_at"),
        _ts("revoked_at", nullable=True, default=False),
        sa.PrimaryKeyConstraint("id", name="pk_sessions"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_sessions_user_id_users", ondelete="CASCADE"),
        sa.UniqueConstraint("refresh_token", name="uq_sessions_refresh_token"),
    )
    op.create_index("idx_sessions_user", "sessions", ["user_id"])
    op.create_index("idx_sessions_expires", "sessions", ["expires_at"], postgresql_where=sa.text("revoked_at IS NULL"))
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource", sa.String(64), nullable=True),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_audit_log_user_id_users"),
    )
    op.create_index("idx_audit_log_user", "audit_log", ["user_id"])
    op.create_index("idx_audit_log_action", "audit_log", ["action"])
    op.create_index("idx_audit_log_created", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_log_created", table_name="audit_log")
    op.drop_index("idx_audit_log_action", table_name="audit_log")
    op.drop_index("idx_audit_log_user", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("idx_sessions_expires", table_name="sessions")
    op.drop_index("idx_sessions_user", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("user_field_roles")
    op.drop_table("roles")
    op.drop_table("users")
    op.drop_table("fields")
