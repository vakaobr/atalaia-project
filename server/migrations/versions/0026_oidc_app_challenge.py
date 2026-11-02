# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The app's PKCE-style verifier hash on a social login in progress (APP-4).

Revision ID: 0026_oidc_app_challenge
Revises: 0025_oidc_notice_version
Created: 2026-10-30

``oidc_logins.app_challenge`` is nullable: the staff pages (they hold the binding cookie) and apps from before APP-4
leave it empty. Rows live ten minutes; nothing to backfill.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0026_oidc_app_challenge"
down_revision = "0025_oidc_notice_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("oidc_logins", sa.Column("app_challenge", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("oidc_logins", "app_challenge")
