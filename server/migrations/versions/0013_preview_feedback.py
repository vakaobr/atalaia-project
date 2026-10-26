# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The preview deployment's feedback form (decisions PV-*).

Revision ID: 0013_preview_feedback
Revises: 0012_atak
Created: 2026-10-26

- ``preview_feedback``: what a visitor of a preview server wrote (kind, optional role, text, optional
  contact, the page, the language); no account, address or user agent. Only a server started with
  ``ATALAIA_PREVIEW=on`` writes to it.

The downgrade drops the table (the feedback is lost: read it first).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_preview_feedback"
down_revision = "0012_atak"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "preview_feedback",
        sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("who", sa.String(16), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("contact", sa.String(200), nullable=True),
        sa.Column("page", sa.String(128), nullable=True),
        sa.Column("lang", sa.String(8), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="new"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_preview_feedback"),
        sa.CheckConstraint("kind IN ('good', 'usability', 'change', 'bug', 'other')", name="ck_preview_feedback_kind"),
        sa.CheckConstraint("who IS NULL OR who IN ('player', 'organiser', 'staff', 'other')",
                           name="ck_preview_feedback_who"),
        sa.CheckConstraint("status IN ('new', 'seen', 'done')", name="ck_preview_feedback_status"),
        sa.CheckConstraint("length(message) BETWEEN 1 AND 2000", name="ck_preview_feedback_message"),
    )
    op.create_index("idx_preview_feedback_status_created", "preview_feedback", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_preview_feedback_status_created", table_name="preview_feedback")
    op.drop_table("preview_feedback")
