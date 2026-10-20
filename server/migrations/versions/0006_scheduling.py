# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scheduling, the public field page and its feeds (ADR-P4-11, ADR-P4-12; plan phase 15, decisions S15-*).

Revision ID: 0006_scheduling
Revises: 0005_chrono
Created: 2026-10-20

- ``fields``: ``public_page`` (off by default), ``description``, ``address_text``,
  ``federation_label``.
- ``scheduled_games``: ADR-P4-1's table with ADR-P4-11's columns, times as ``starts_at`` and
  ``ends_at`` (decision S15-2); registrations, ``controller_game_id``, presets and scenarios
  come with plan phases 16 and 20.

The downgrade drops the schedule and the field page's settings.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_scheduling"
down_revision = "0005_chrono"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _ts(name: str, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def upgrade() -> None:
    op.add_column("fields", sa.Column("public_page", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("fields", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("fields", sa.Column("address_text", sa.String(512), nullable=True))
    op.add_column("fields", sa.Column("federation_label", sa.String(16), nullable=True))

    op.create_table(
        "scheduled_games",
        sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        _ts("starts_at", nullable=False),
        _ts("ends_at", nullable=False),
        sa.Column("location_text", sa.String(512), nullable=True),
        sa.Column("mode_id", sa.String(128), nullable=True),
        sa.Column("teams", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("max_players", sa.Integer(), nullable=True),
        _ts("registration_opens_at"),
        _ts("registration_closes_at"),
        sa.Column("federation", sa.String(16), nullable=False, server_default="off"),
        sa.Column("predeclare_replicas", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        _ts("published_at"),
        _ts("cancelled_at"),
        sa.Column("cancelled_reason", sa.String(512), nullable=True),
        sa.Column("ical_sequence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", UUID, nullable=True),
        _ts("created_at", nullable=False, default=True),
        _ts("updated_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_scheduled_games"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_scheduled_games_field_id_fields",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_scheduled_games_created_by_users",
                                ondelete="SET NULL"),
        sa.CheckConstraint("status IN ('draft', 'published', 'in_progress', 'completed', 'cancelled')",
                           name="ck_scheduled_games_status"),
        sa.CheckConstraint("federation IN ('off', 'optional', 'required')", name="ck_scheduled_games_federation"),
        sa.CheckConstraint("ends_at > starts_at", name="ck_scheduled_games_times"),
        sa.CheckConstraint("registration_closes_at IS NULL OR registration_opens_at IS NULL "
                           "OR registration_closes_at > registration_opens_at", name="ck_scheduled_games_window"),
        sa.CheckConstraint("max_players IS NULL OR max_players BETWEEN 1 AND 10000",
                           name="ck_scheduled_games_max_players"),
        sa.CheckConstraint("ical_sequence >= 0", name="ck_scheduled_games_ical_sequence"),
    )
    op.create_index("idx_scheduled_games_field_starts", "scheduled_games", ["field_id", "starts_at"])
    op.create_index("idx_scheduled_games_created_by", "scheduled_games", ["created_by"])


def downgrade() -> None:
    op.drop_index("idx_scheduled_games_created_by", table_name="scheduled_games")
    op.drop_index("idx_scheduled_games_field_starts", table_name="scheduled_games")
    op.drop_table("scheduled_games")
    for column in ("federation_label", "address_text", "description", "public_page"):
        op.drop_column("fields", column)
