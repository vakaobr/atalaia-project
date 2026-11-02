# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The account rests on the contract, not on consent: notice records, and the 16-or-older confirmation (LEG-*).

Revision ID: 0029_account_notice_records
Revises: 0028_privacy_retention
Created: 2026-10-30

The maintainer's lawyer approved (2026-10-30) that an account is based on the contract (GDPR Art. 6(1)(b)) and
that consent stays only where it is a real choice (cross-field chrono sharing, position sharing in a game, "use my
Google/Microsoft name"). So:

- ``notice_records``: one row each time an account was shown a version of the privacy notice (``signup``,
  ``shown_again``, or ``migrated`` below), with ``age_confirmed`` on the sign-up row.
- **How the old ``account`` consents were migrated.** Every ``consents`` row with ``purpose = 'account'``, live or
  not, becomes one ``notice_records`` row of kind ``migrated`` with the same user, notice version and time
  (``given_at``), so the history of versions each account was shown is kept whole; ``age_confirmed`` is false
  (those accounts were never asked). A ``withdrawn_at`` on such a row only ever meant "replaced by a newer version"
  (there was no way to withdraw an account consent), so it is not carried: the newest row is what counts. The
  ``account`` rows are then deleted from ``consents``, which holds real consents only. ``users.gdpr_consent_at``
  is unchanged (the time the notice was last shown). The version ``before-0003`` is kept as it was.
- ``oidc_logins``: ``consent`` is renamed ``notice_seen`` (the person ticked that they read the notice) and
  ``age_confirmed`` is added. Rows live ten minutes; one in progress at the upgrade fails its age check and the
  person starts again.

The downgrade turns each account's ``notice_records`` back into ``account`` consents (the newest live, the older
ones withdrawn at the time of the next, as renewals were) and drops the table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0029_account_notice_records"
down_revision = "0028_privacy_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notice_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notice_version", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("age_confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name="pk_notice_records"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_notice_records_user_id_users",
                                ondelete="CASCADE"),
        sa.CheckConstraint("kind IN ('signup', 'shown_again', 'migrated')", name="ck_notice_records_kind"),
    )
    op.create_index("idx_notice_records_user", "notice_records", ["user_id", "recorded_at"])
    op.execute("INSERT INTO notice_records (user_id, notice_version, kind, age_confirmed, recorded_at) "
               "SELECT user_id, notice_version, 'migrated', false, given_at FROM consents WHERE purpose = 'account'")
    op.execute("DELETE FROM consents WHERE purpose = 'account'")
    op.alter_column("oidc_logins", "consent", new_column_name="notice_seen")
    op.add_column("oidc_logins", sa.Column("age_confirmed", sa.Boolean(), nullable=False, server_default="false"))


def downgrade() -> None:
    op.drop_column("oidc_logins", "age_confirmed")
    op.alter_column("oidc_logins", "notice_seen", new_column_name="consent")
    op.execute(
        "INSERT INTO consents (user_id, purpose, notice_version, given_at, withdrawn_at) "
        "SELECT user_id, 'account', notice_version, recorded_at, "
        "lead(recorded_at) OVER (PARTITION BY user_id ORDER BY recorded_at, id) FROM notice_records")
    op.drop_index("idx_notice_records_user", table_name="notice_records")
    op.drop_table("notice_records")
