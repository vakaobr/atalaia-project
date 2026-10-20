# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Game history and the scenario library (plan phase 20, decisions S20-*).

Revision ID: 0011_history
Revises: 0010_firmware
Created: 2026-10-20

- ``field_history_settings``: per field, the spectators' delay behind a live game and how long its game
  history is kept (ADR-P4-8: 24 months, per field; a field may keep it shorter, not longer).
- ``game_score_samples``: every rise of a game's score counter as it arrived: the score timeline.
- ``field_scenarios`` and ``field_scenario_revisions``: the field's scenario library, every saved manifest
  a revision.
- ``field_presets``: the field's game presets, pushed to its controllers with the scenarios.

Written beside plan phase 19's migration (built at the same time) and chained after it, 0010_firmware.
The downgrade drops the tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_history"
down_revision = "0010_firmware"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())


def _ts(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def _id() -> sa.Column:
    return sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()"))


def _field_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name=f"fk_{table}_field_id_fields", ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "field_history_settings",
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("spectator_delay_s", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="730"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("field_id", name="pk_field_history_settings"),
        _field_fk("field_history_settings"),
        sa.CheckConstraint("spectator_delay_s BETWEEN 0 AND 3600", name="ck_field_history_settings_delay"),
        sa.CheckConstraint("retention_days BETWEEN 30 AND 730", name="ck_field_history_settings_retention"),
    )
    op.create_table(
        "game_score_samples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game", UUID, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("team", sa.String(32), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        _ts("received_at"),
        sa.PrimaryKeyConstraint("id", name="pk_game_score_samples"),
        sa.ForeignKeyConstraint(["game"], ["games.id"], name="fk_game_score_samples_game_games", ondelete="CASCADE"),
        sa.CheckConstraint("value >= 0", name="ck_game_score_samples_value"),
    )
    op.create_index("idx_game_score_samples_game", "game_score_samples", ["game", "received_at"])
    op.create_table(
        "field_scenarios",
        _id(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        _ts("archived_at", nullable=True, default=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_field_scenarios"),
        _field_fk("field_scenarios"),
        sa.UniqueConstraint("field_id", "scenario_id", name="uq_field_scenarios_field_id_scenario_id"),
        sa.CheckConstraint("revision >= 1", name="ck_field_scenarios_revision"),
    )
    op.create_table(
        "field_scenario_revisions",
        _id(),
        sa.Column("scenario", UUID, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("manifest", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("warnings", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_field_scenario_revisions"),
        sa.ForeignKeyConstraint(["scenario"], ["field_scenarios.id"],
                                name="fk_field_scenario_revisions_scenario_field_scenarios", ondelete="CASCADE"),
        sa.UniqueConstraint("scenario", "revision", name="uq_field_scenario_revisions_scenario_revision"),
    )
    op.create_table(
        "field_presets",
        _id(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("mode_id", sa.String(128), nullable=False),
        sa.Column("params", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_field_presets"),
        _field_fk("field_presets"),
        sa.UniqueConstraint("field_id", "name", name="uq_field_presets_field_id_name"),
    )


def downgrade() -> None:
    op.drop_table("field_presets")
    op.drop_table("field_scenario_revisions")
    op.drop_table("field_scenarios")
    op.drop_index("idx_game_score_samples_game", table_name="game_score_samples")
    op.drop_table("game_score_samples")
    op.drop_table("field_history_settings")
