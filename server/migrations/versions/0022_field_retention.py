# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""How long a field's controllers keep chrono records and game data (decisions RET-1, RET-2).

Revision ID: 0022_field_retention
Revises: 0019_field_country
Created: 2026-10-28

- ``fields.default_retention_days`` (365, there since the first revision) is now a setting the field's admin can
  change (``PATCH /api/v1/fields/{id}``, the staff settings page) and its controllers follow
  (``settings.chrono_retention_days`` of the field answer): the chrono registry here, and the readings, other
  fields' readings and marshals' earlier keys on the controllers. It gets the range the controllers take, 30-3653
  days; every row is 365 until someone changes it.
- ``fields.game_retention_days`` (365): how long a controller keeps an ended game's events, scores and nodes
  (``settings.game_retention_days``). The site server's own game history keeps its own setting
  (``field_history_settings.retention_days``, 30-730).

The downgrade drops the new column and both ranges.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_field_retention"
down_revision = "0021_hub_share_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fields", sa.Column("game_retention_days", sa.Integer(), nullable=False, server_default="365"))
    op.create_check_constraint("ck_fields_game_retention_days", "fields",
                               "game_retention_days BETWEEN 30 AND 3653")
    op.create_check_constraint("ck_fields_default_retention_days", "fields",
                               "default_retention_days BETWEEN 30 AND 3653")


def downgrade() -> None:
    op.drop_constraint("ck_fields_default_retention_days", "fields", type_="check")
    op.drop_constraint("ck_fields_game_retention_days", "fields", type_="check")
    op.drop_column("fields", "game_retention_days")
