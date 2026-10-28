# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""APD membership at registration and check-in (protocol/apd.md, decisions APD-*).

Revision ID: 0016_apd_membership
Revises: 0015_login_methods
Created: 2026-10-28

- ``fields.apd_rule``: the field's rule (which APDs it accepts, whether membership is needed to register and at
  check-in, whether the expiry is checked, the field's own APD entries); null is the default rule (accepts any,
  asks for nothing).
- ``game_registrations.apd_id`` and ``membership_expires``: the APD the player declared and the expiry of their
  membership. The existing ``federation_number`` column is the membership number: a number that was there stays,
  as "membership number, APD unknown" (``apd_id`` null), so nothing is copied or lost.

The downgrade drops the columns (the declared APDs, expiries and rules are lost; the number stays).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0016_apd_membership"
down_revision = "0015_login_methods"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fields", sa.Column("apd_rule", postgresql.JSONB(), nullable=True))
    op.add_column("game_registrations", sa.Column("apd_id", sa.String(32), nullable=True))
    op.add_column("game_registrations", sa.Column("membership_expires", sa.Date(), nullable=True))
    op.create_check_constraint("ck_game_registrations_apd_id", "game_registrations",
                               "apd_id IS NULL OR apd_id ~ '^[a-z0-9][a-z0-9-]{0,31}$'")


def downgrade() -> None:
    op.drop_constraint("ck_game_registrations_apd_id", "game_registrations", type_="check")
    op.drop_column("game_registrations", "membership_expires")
    op.drop_column("game_registrations", "apd_id")
    op.drop_column("fields", "apd_rule")
