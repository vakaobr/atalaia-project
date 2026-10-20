# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Registration and game-day sync (ADR-P4-11; plan phase 16, decisions S16-*).

Revision ID: 0007_registration
Revises: 0006_scheduling
Created: 2026-10-20

- ``fields``: ``limit_template`` and ``max_replicas``, the field controller's check-in rules for
  pre-declared replicas.
- ``scheduled_games``: ``controller_game`` (the synced game made from it) and ``walkins`` (a count).
- ``game_registrations``: ADR-P4-1's table with ADR-P4-11's columns (PLAN.md's ``0006_registration``;
  0006 is the schedule's, decision S12-7's rule).
- ``registration_replicas``: the pre-declared replicas, with the controller's final states.
- ``player_id_claims``: an account's claim to a phone's player id, until the controller confirms it.

The downgrade drops them all.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_registration"
down_revision = "0006_scheduling"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _ts(name: str, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def _id() -> sa.Column:
    return sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    op.add_column("fields", sa.Column("limit_template", sa.String(32), nullable=False, server_default="portugal"))
    op.add_column("fields", sa.Column("max_replicas", sa.SmallInteger(), nullable=False, server_default="5"))
    op.add_column("scheduled_games", sa.Column("controller_game", UUID, nullable=True))
    op.add_column("scheduled_games", sa.Column("walkins", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_scheduled_games_controller_game_games", "scheduled_games", "games",
                          ["controller_game"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_scheduled_games_walkins", "scheduled_games", "walkins IS NULL OR walkins >= 0")
    op.create_index("idx_scheduled_games_controller_game", "scheduled_games", ["controller_game"])

    op.create_table(
        "game_registrations",
        _id(),
        sa.Column("scheduled_game", UUID, nullable=False),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("player_id", sa.String(14), nullable=False),
        sa.Column("display_name", sa.String(32), nullable=True),
        sa.Column("team_preference", sa.String(32), nullable=True),
        sa.Column("federation_number", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="registered"),
        sa.Column("ticket_hash", sa.String(64), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="site"),
        sa.Column("external_ref", sa.String(128), nullable=True),
        _ts("cancelled_at"),
        _ts("outcome_at"),
        _ts("created_at", nullable=False, default=True),
        _ts("updated_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_game_registrations"),
        sa.ForeignKeyConstraint(["scheduled_game"], ["scheduled_games.id"],
                                name="fk_game_registrations_scheduled_game_scheduled_games", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_game_registrations_field_id_fields",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_game_registrations_user_id_users",
                                ondelete="SET NULL"),
        sa.UniqueConstraint("scheduled_game", "player_id", name="uq_game_registrations_scheduled_game_player_id"),
        sa.UniqueConstraint("scheduled_game", "user_id", name="uq_game_registrations_scheduled_game_user_id"),
        sa.UniqueConstraint("scheduled_game", "source", "external_ref",
                            name="uq_game_registrations_scheduled_game_source_external_ref"),
        sa.CheckConstraint("status IN ('registered', 'cancelled', 'checked_in', 'no_show')",
                           name="ck_game_registrations_status"),
    )
    op.create_index("idx_game_registrations_user", "game_registrations", ["user_id"])
    op.create_index("idx_game_registrations_field_player", "game_registrations", ["field_id", "player_id"])

    op.create_table(
        "registration_replicas",
        _id(),
        sa.Column("registration", UUID, nullable=False),
        sa.Column("declaration_id", UUID, nullable=False),
        sa.Column("replica_id", UUID, nullable=True),
        sa.Column("replica_type", sa.String(16), nullable=False),
        sa.Column("replica_class", sa.String(32), nullable=False),
        sa.Column("make_model", sa.String(64), nullable=True),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=True),
        sa.Column("reading_id", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_registration_replicas"),
        sa.ForeignKeyConstraint(["registration"], ["game_registrations.id"],
                                name="fk_registration_replicas_registration_game_registrations", ondelete="CASCADE"),
        sa.UniqueConstraint("declaration_id", name="uq_registration_replicas_declaration_id"),
        sa.CheckConstraint("state IS NULL OR state IN ('pending', 'passed', 'refused', 'withdrawn')",
                           name="ck_registration_replicas_state"),
    )
    op.create_index("idx_registration_replicas_registration", "registration_replicas", ["registration"])

    op.create_table(
        "player_id_claims",
        _id(),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("player_id", sa.String(14), nullable=False),
        sa.Column("secret_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        _ts("created_at", nullable=False, default=True),
        _ts("decided_at"),
        sa.PrimaryKeyConstraint("id", name="pk_player_id_claims"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_player_id_claims_user_id_users",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_player_id_claims_field_id_fields",
                                ondelete="CASCADE"),
        sa.CheckConstraint("status IN ('pending', 'confirmed', 'refused')", name="ck_player_id_claims_status"),
    )
    op.create_index("idx_player_id_claims_field_status", "player_id_claims", ["field_id", "status"])
    op.create_index("idx_player_id_claims_user", "player_id_claims", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_player_id_claims_user", table_name="player_id_claims")
    op.drop_index("idx_player_id_claims_field_status", table_name="player_id_claims")
    op.drop_table("player_id_claims")
    op.drop_index("idx_registration_replicas_registration", table_name="registration_replicas")
    op.drop_table("registration_replicas")
    op.drop_index("idx_game_registrations_field_player", table_name="game_registrations")
    op.drop_index("idx_game_registrations_user", table_name="game_registrations")
    op.drop_table("game_registrations")
    op.drop_index("idx_scheduled_games_controller_game", table_name="scheduled_games")
    op.drop_constraint("ck_scheduled_games_walkins", "scheduled_games", type_="check")
    op.drop_constraint("fk_scheduled_games_controller_game_games", "scheduled_games", type_="foreignkey")
    op.drop_column("scheduled_games", "walkins")
    op.drop_column("scheduled_games", "controller_game")
    op.drop_column("fields", "max_replicas")
    op.drop_column("fields", "limit_template")
