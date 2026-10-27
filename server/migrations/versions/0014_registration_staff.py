# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""What staff record about a registration, and when a controller pulled a roster (Phase 4 follow-up FU7).

Revision ID: 0014_registration_staff
Revises: 0013_preview_feedback
Created: 2026-10-27

- ``game_registrations.paid_at`` and ``paid_by``: whether staff marked the registration paid, when and who
  (the account is unlinked when it is erased; there is no payment processing).
- ``game_registrations.outcome_by``: the staff account that marked a registration no-show by hand (null for
  an outcome the controller reported, which staff do not undo).
- ``scheduled_games.roster_pulled_at``, ``roster_key_label``, ``roster_key_fingerprint`` and ``roster_agent``:
  the last time a controller pulled the game's roster, with the label and fingerprint of the API key it used
  and its User-Agent (a controller's GET carries no other identity).

The downgrade drops the columns (the marks and the pull times are lost).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_registration_staff"
down_revision = "0013_preview_feedback"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.add_column("game_registrations", sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("game_registrations", sa.Column("paid_by", UUID, nullable=True))
    op.add_column("game_registrations", sa.Column("outcome_by", UUID, nullable=True))
    op.create_foreign_key("fk_game_registrations_paid_by_users", "game_registrations", "users", ["paid_by"], ["id"],
                          ondelete="SET NULL")
    op.create_foreign_key("fk_game_registrations_outcome_by_users", "game_registrations", "users", ["outcome_by"],
                          ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_game_registrations_paid", "game_registrations",
                               "paid_by IS NULL OR paid_at IS NOT NULL")
    op.create_index("idx_game_registrations_paid_by", "game_registrations", ["paid_by"])
    op.create_index("idx_game_registrations_outcome_by", "game_registrations", ["outcome_by"])
    op.add_column("scheduled_games", sa.Column("roster_pulled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("scheduled_games", sa.Column("roster_key_label", sa.String(64), nullable=True))
    op.add_column("scheduled_games", sa.Column("roster_key_fingerprint", sa.String(8), nullable=True))
    op.add_column("scheduled_games", sa.Column("roster_agent", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("scheduled_games", "roster_agent")
    op.drop_column("scheduled_games", "roster_key_fingerprint")
    op.drop_column("scheduled_games", "roster_key_label")
    op.drop_column("scheduled_games", "roster_pulled_at")
    op.drop_index("idx_game_registrations_outcome_by", table_name="game_registrations")
    op.drop_index("idx_game_registrations_paid_by", table_name="game_registrations")
    op.drop_constraint("ck_game_registrations_paid", "game_registrations", type_="check")
    op.drop_constraint("fk_game_registrations_outcome_by_users", "game_registrations", type_="foreignkey")
    op.drop_constraint("fk_game_registrations_paid_by_users", "game_registrations", type_="foreignkey")
    op.drop_column("game_registrations", "outcome_by")
    op.drop_column("game_registrations", "paid_by")
    op.drop_column("game_registrations", "paid_at")
