# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A field's acceptance of the cross-field sharing terms (LEG-41).

Revision ID: 0030_sharing_terms
Revises: 0029_account_notice_records
Created: 2026-10-30

``fields.sharing_terms_version`` / ``_accepted_at`` / ``_accepted_by`` record which version of the Art. 26 sharing terms
(``docs/templates/sharing-terms.md``) the field accepted, when, and which account accepted for it. Nothing to backfill:
a field that already shares has no acceptance, so its sharing is suspended until its administrator accepts the terms on
the settings page (sharing is live only while the accepted version is the server's current one).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0030_sharing_terms"
down_revision = "0029_account_notice_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fields", sa.Column("sharing_terms_version", sa.String(64), nullable=True))
    op.add_column("fields", sa.Column("sharing_terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fields", sa.Column("sharing_terms_accepted_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_fields_sharing_terms_accepted_by_users", "fields", "users",
                          ["sharing_terms_accepted_by"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_fields_sharing_terms_accepted_by_users", "fields", type_="foreignkey")
    op.drop_column("fields", "sharing_terms_accepted_by")
    op.drop_column("fields", "sharing_terms_accepted_at")
    op.drop_column("fields", "sharing_terms_version")
