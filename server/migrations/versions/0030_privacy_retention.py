# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Privacy review, code part (PRIV-2, PRIV-5, PRIV-7).

Revision ID: 0030_privacy_retention
Revises: 0025_oidc_notice_version
Created: 2026-10-30

- ``users.inactivity_warned_at`` (PRIV-7): when the retention purge warned that an account inactive for the configured
  time will be anonymised. Cleared by the purge when the account is active again.
- ``fields.chrono_ban_days`` (PRIV-2): how long a "ban" outcome of a chrono violation lasts (null: 12 months, never
  more than the field's chrono retention).
- ``chrono_violations.ban_expires_at`` (PRIV-2): when a "ban" outcome ends. A ban recorded before this revision gets the
  end date the rule gives now: its resolution plus 12 months (at most the field's chrono retention), never past its reading's own
  retention (the server never enforced bans: it is a label on the violation).
- Game history keeps 90 days by default (maintainer decision 2026-10-30): the column defaults of
  ``fields.game_retention_days`` (was 365) and ``field_history_settings.retention_days`` (was 730) become 90. A row
  that exists keeps the value it has (a field that wants less sets it; the server cannot tell a chosen 365 from the old
  default). The most a field may choose stays 3653 and 730.
- ``game_results`` (maintainer decision 2026-10-30): a game's team totals, written by the purge just before the game's
  per-player history is deleted at 90 days and kept 365 days after the game ended; no player ids, no member lists.
- ``chrono_copy_revocations`` (PRIV-5): the players whose copies of other fields' chrono records the field's
  controllers must drop (the person erased their account, or withdrew a field's chrono-sharing consent).

The number leaves room: a parallel branch (server hardening) adds its own revision, and the two are chained at merge.
The downgrade drops all of it (the revocation records are lost: controllers keep the copies until their retention).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030_privacy_retention"
down_revision = "0025_oidc_notice_version"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("users", sa.Column("inactivity_warned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fields", sa.Column("chrono_ban_days", sa.Integer(), nullable=True))
    op.create_check_constraint("ck_fields_chrono_ban_days", "fields",
                               "chrono_ban_days IS NULL OR chrono_ban_days BETWEEN 1 AND 3653")
    op.alter_column("fields", "game_retention_days", server_default="90")
    op.alter_column("field_history_settings", "retention_days", server_default="90")
    op.add_column("chrono_violations", sa.Column("ban_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE chrono_violations v SET ban_expires_at = LEAST("
        "COALESCE(v.resolved_at, v.created_at) + LEAST(365, f.default_retention_days) * interval '1 day', "
        "r.timestamp + f.default_retention_days * interval '1 day') "
        "FROM fields f, chrono_readings r "
        "WHERE v.outcome = 'ban' AND f.id = v.field_id AND r.id = v.reading")
    op.create_table(
        "game_results",
        sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("game_seed", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("mode_id", sa.String(128), nullable=False),
        sa.Column("teams", postgresql.JSONB(), nullable=False),
        sa.Column("team_totals", postgresql.JSONB(), nullable=False),
        sa.Column("winner", sa.String(32), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_game_results"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_game_results_field_id_fields",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("field_id", "game_id", "game_seed", name="uq_game_results_field_id_game_id_game_seed"),
    )
    op.create_index("idx_game_results_field_ended", "game_results", ["field_id", "ended_at"])
    op.create_table(
        "chrono_copy_revocations",
        sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("player_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_chrono_copy_revocations"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_chrono_copy_revocations_field_id_fields",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("field_id", "player_id", "reason",
                            name="uq_chrono_copy_revocations_field_id_player_id_reason"),
        sa.CheckConstraint("reason IN ('erasure', 'withdrawn')", name="ck_chrono_copy_revocations_reason"),
    )


def downgrade() -> None:
    op.drop_table("chrono_copy_revocations")
    op.drop_index("idx_game_results_field_ended", table_name="game_results")
    op.drop_table("game_results")
    op.alter_column("field_history_settings", "retention_days", server_default="730")
    op.alter_column("fields", "game_retention_days", server_default="365")
    op.drop_column("chrono_violations", "ban_expires_at")
    op.drop_constraint("ck_fields_chrono_ban_days", "fields", type_="check")
    op.drop_column("fields", "chrono_ban_days")
    op.drop_column("users", "inactivity_warned_at")
