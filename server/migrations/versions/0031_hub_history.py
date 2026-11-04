# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A field's opt-in to share its game history with the other fields of a hosted hub (HUBH-1 to HUBH-14).

Revision ID: 0031_hub_history
Revises: 0030_sharing_terms
Created: 2026-11-04

``fields.history_sharing_enabled`` (off by default: the maintainer's decision of 2026-11-04, "fields can choose to share
their games or not, should be an opt-in") and ``fields.history_shared_since`` (when the field's admin last turned it on,
null while off). Nothing to backfill: every field starts not sharing.

The shared copies themselves cannot live in a field's schema (no other field may read it, S2113-1): they are in the
hub's ``public.atalaia_hub_history_members`` and ``public.atalaia_hub_games``, made by ``hosted init`` and ``hosted
migrate`` (``hosted.HISTORY_DDL``, with the same row-level security as the chrono sharing's tables, SVX-2), which runs
before this migration in every field's schema. In a single-field server only the two columns are added (the feature is a
hosted hub's).

The downgrade drops the two columns and, in a registered hosted field's schema, withdraws what that field shared (its rows
of the hub's tables): without the switch nothing may stay shared.
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op

revision = "0031_hub_history"
down_revision = "0030_sharing_terms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fields", sa.Column("history_sharing_enabled", sa.Boolean(), nullable=False,
                                      server_default=sa.false()))
    op.add_column("fields", sa.Column("history_shared_since", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    schema = bind.scalar(sa.text("SELECT current_schema()"))
    if isinstance(schema, str) and re.fullmatch(r"field_[a-z0-9_]{1,40}", schema) \
            and bind.scalar(sa.text("SELECT to_regclass('public.atalaia_hub_history_members') IS NOT NULL")):
        # The owner role runs the migrations; the hub's tables have row-level security enabled, not forced, so it sees
        # every field's rows and deletes this field's only. The games go with the member row (ON DELETE CASCADE).
        bind.execute(sa.text("DELETE FROM public.atalaia_hub_history_members WHERE tenant = :s"), {"s": schema})
    op.drop_column("fields", "history_shared_since")
    op.drop_column("fields", "history_sharing_enabled")
