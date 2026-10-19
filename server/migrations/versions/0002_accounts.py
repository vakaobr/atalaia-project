# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accounts and sessions: TOTP replay guard, server administrators, hashed refresh tokens (ADR-P4-2).

Revision ID: 0002_accounts
Revises: 0001_base
Created: 2026-10-19

- ``users``: ``totp_last_step`` (the step of the last TOTP code accepted, so
  a code works once), ``server_admin``, and a check that usernames are stored
  lower-case.
- ``sessions``: ``refresh_token`` is dropped (a session has a chain of
  refresh tokens now, kept as hashes in ``refresh_tokens``); ``mfa`` (the
  login passed the TOTP step) and ``last_used_at`` are added.
- ``refresh_tokens``: one row per refresh token issued, its SHA-256 only;
  ``used_at`` marks a token already rotated, so presenting it again is a
  replay.

No released server ever stored a session (plan phase 10 created the table
empty), so dropping ``sessions.refresh_token`` needs no two-step migration.
The downgrade deletes every session, since the 0001 schema has nowhere to
keep their tokens: after a downgrade everyone logs in again.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_accounts"
down_revision = "0001_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("totp_last_step", sa.BigInteger(), nullable=True))
    op.add_column("users", sa.Column("server_admin", sa.Boolean(), nullable=False, server_default="false"))
    op.create_check_constraint(op.f("ck_users_username_lower"), "users", "username = lower(username)")

    op.drop_constraint("uq_sessions_refresh_token", "sessions", type_="unique")
    op.drop_column("sessions", "refresh_token")
    op.add_column("sessions", sa.Column("mfa", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("sessions", sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_tokens"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name="fk_refresh_tokens_session_id_sessions",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_refresh_tokens_token_hash"),
    )
    op.create_index("idx_refresh_tokens_session", "refresh_tokens", ["session_id"])


def downgrade() -> None:
    op.drop_index("idx_refresh_tokens_session", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")

    op.execute("DELETE FROM sessions")
    op.drop_column("sessions", "last_used_at")
    op.drop_column("sessions", "mfa")
    op.add_column("sessions", sa.Column("refresh_token", sa.String(512), nullable=False))
    op.create_unique_constraint("uq_sessions_refresh_token", "sessions", ["refresh_token"])

    op.drop_constraint(op.f("ck_users_username_lower"), "users", type_="check")
    op.drop_column("users", "server_admin")
    op.drop_column("users", "totp_last_step")
