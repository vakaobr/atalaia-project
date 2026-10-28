# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hosted chrono sharing across tenants: an account's link to a person (SVX-2).

Revision ID: 0020_hub_share_links
Revises: 0019_field_country
Created: 2026-10-28

- ``hub_share_links``: ``user_id`` (the account, one row at most, gone with it) and ``person_id``, the random id
  the person's accounts at the other fields of a hosted hub hold too (ADR-P4-4's amendment of 2026-10-28). The
  table exists on every server and is empty on a single-field one. A person has one account per field, so
  ``person_id`` is unique.

The downgrade drops the table (the hub's own tables are the operator's, ``hosted init`` / ``hosted migrate``).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0020_hub_share_links"
down_revision = "0019_field_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hub_share_links",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_unique_constraint("uq_hub_share_links_person_id", "hub_share_links", ["person_id"])


def downgrade() -> None:
    op.drop_table("hub_share_links")
