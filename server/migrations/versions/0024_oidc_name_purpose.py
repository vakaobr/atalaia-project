# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A fourth purpose for a social login round: ``name`` (LG-10).

Revision ID: 0024_oidc_name_purpose
Revises: 0023_tenant_roles
Created: 2026-10-29

The "use my Google/Microsoft name" button of the "choose your username" step runs a round with the ``profile`` scope
whose purpose is ``name``: it proves the account's own login and hands the browser a username proposed from the name,
which is stored nowhere. Only the check constraint of ``oidc_logins.purpose`` changes (no data, no column).
"""

from __future__ import annotations

from alembic import op

revision = "0024_oidc_name_purpose"
down_revision = "0023_tenant_roles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_oidc_logins_purpose", "oidc_logins", type_="check")
    op.create_check_constraint("ck_oidc_logins_purpose", "oidc_logins",
                               "purpose IN ('login', 'link', 'reauth', 'name')")


def downgrade() -> None:
    op.execute("DELETE FROM oidc_logins WHERE purpose = 'name'")
    op.drop_constraint("ck_oidc_logins_purpose", "oidc_logins", type_="check")
    op.create_check_constraint("ck_oidc_logins_purpose", "oidc_logins", "purpose IN ('login', 'link', 'reauth')")
