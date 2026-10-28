# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drop ``users.data_retention_days`` (decision CONS-3).

Revision ID: 0020_drop_user_retention
Revises: 0019_field_country
Created: 2026-10-28

The column was meant as a per-account override of the field's retention, and nothing ever read it: it was only
exported and set to null on erasure. GDPR asks for a defined period per kind of data, which the daily purge applies
(``personal_data.py``, ``fields.default_retention_days``), so a per-account field only promised what the code does not
do. Whatever was in it is dropped with it (it was never set by any call).

The downgrade adds the empty column back.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_drop_user_retention"
down_revision = "0019_field_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("users", "data_retention_days")


def downgrade() -> None:
    op.add_column("users", sa.Column("data_retention_days", sa.Integer(), nullable=True))
