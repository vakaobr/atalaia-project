# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal data: consent records, and an index for a person's audit entries (ADR-P4-8).

Revision ID: 0003_personal_data
Revises: 0002_accounts
Created: 2026-10-19

- ``consents``: one row per consent given, with its purpose, the version of
  the privacy notice shown and when it was withdrawn; at most one live
  (not withdrawn) consent per account and purpose.
- ``audit_log``: an index on ``resource_id``, so the access request and the
  erasure find the entries about an account (a role granted to it, say) as
  quickly as the ones it made.

Accounts made before this revision consented at registration (plan phase 11
required it) but no notice version was recorded: the upgrade gives each
account with ``gdpr_consent_at`` an ``account`` consent with the version
``before-0003`` and that time. The downgrade drops the table; the time stays
in ``users.gdpr_consent_at``.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_personal_data"
down_revision = "0002_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "consents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("notice_version", sa.String(64), nullable=False),
        sa.Column("given_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_consents"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_consents_user_id_users", ondelete="CASCADE"),
    )
    op.create_index("idx_consents_user", "consents", ["user_id"])
    op.create_index("uq_consents_live", "consents", ["user_id", "purpose"], unique=True,
                    postgresql_where=sa.text("withdrawn_at IS NULL"))
    op.create_index("idx_audit_log_resource", "audit_log", ["resource_id"])
    op.execute("INSERT INTO consents (user_id, purpose, notice_version, given_at) "
               "SELECT id, 'account', 'before-0003', gdpr_consent_at FROM users WHERE gdpr_consent_at IS NOT NULL")


def downgrade() -> None:
    op.drop_index("idx_audit_log_resource", table_name="audit_log")
    op.drop_index("uq_consents_live", table_name="consents")
    op.drop_index("idx_consents_user", table_name="consents")
    op.drop_table("consents")
