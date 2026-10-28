# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's country, for the membership wording and the list it offers (protocol/apd.md, decisions MEM-*).

Revision ID: 0019_field_country
Revises: 0018_chrono_violation_delta
Created: 2026-10-28

- ``fields.country``: an ISO 3166-1 alpha-2 code in capitals, or null (unset). A field with no country offers only
  its own membership entries and its screens say "association membership". Existing fields whose time zone is
  Portugal's (Europe/Lisbon, Atlantic/Azores, Atlantic/Madeira) become ``PT``, so they keep the APD texts and
  the shipped list; any other field stays unset, which is also what a new field in another zone gets.

The downgrade drops the column (a field outside Portugal loses its country).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_field_country"
down_revision = "0018_chrono_violation_delta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fields", sa.Column("country", sa.String(2), nullable=True))
    op.create_check_constraint("ck_fields_country", "fields", "country IS NULL OR country ~ '^[A-Z]{2}$'")
    op.execute("UPDATE fields SET country = 'PT' "
               "WHERE timezone IN ('Europe/Lisbon', 'Atlantic/Azores', 'Atlantic/Madeira')")


def downgrade() -> None:
    op.drop_constraint("ck_fields_country", "fields", type_="check")
    op.drop_column("fields", "country")
