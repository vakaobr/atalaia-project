# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The privacy-notice version the person saw when they began a social sign-up (CONS-7).

Revision ID: 0025_oidc_notice_version
Revises: 0024_oidc_name_purpose
Created: 2026-10-29

``oidc_logins.notice_version`` is nullable: a client that names no version (older apps, older pages) leaves it empty and
the callback records the server's current version, as before. Rows live ten minutes; nothing to backfill.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0025_oidc_notice_version"
down_revision = "0024_oidc_name_purpose"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oidc_logins", sa.Column("notice_version", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("oidc_logins", "notice_version")
