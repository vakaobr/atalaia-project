# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The issuer (and Microsoft's tenant) of a social login is stored with its subject (SRV-8).

Revision ID: 0027_identity_issuer
Revises: 0026_oidc_app_challenge
Created: 2026-10-30

``user_identities`` was unique on ``(provider, subject)``; a subject is only unique within one issuer, so identities of
two Microsoft tenants (or two issuers of one provider) could collide. Now ``issuer`` is part of the key
(``uq_user_identities_provider_issuer_subject``) and ``tenant`` keeps Microsoft's ``tid``.

Existing rows: Google and Apple have one issuer each, filled in here. Microsoft's issuer carries the tenant, which was
not stored: those rows keep an empty ``issuer`` and the next login by them records it (the server matches the empty
issuer once, by provider and subject, then sets it). Downgrade drops the columns and goes back to ``(provider, subject)``;
two rows that differ only by issuer would then collide, so the downgrade refuses (the constraint fails) rather than
merging identities.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_identity_issuer"
down_revision = "0026_oidc_app_challenge"
branch_labels = None
depends_on = None

OLD = "uq_user_identities_provider_subject"
NEW = "uq_user_identities_provider_issuer_subject"


def upgrade() -> None:
    op.add_column("user_identities", sa.Column("issuer", sa.String(255), nullable=False, server_default=""))
    op.add_column("user_identities", sa.Column("tenant", sa.String(64), nullable=True))
    op.execute("UPDATE user_identities SET issuer = 'https://accounts.google.com' WHERE provider = 'google'")
    op.execute("UPDATE user_identities SET issuer = 'https://appleid.apple.com' WHERE provider = 'apple'")
    op.drop_constraint(OLD, "user_identities", type_="unique")
    op.create_unique_constraint(NEW, "user_identities", ["provider", "issuer", "subject"])


def downgrade() -> None:
    op.drop_constraint(NEW, "user_identities", type_="unique")
    op.create_unique_constraint(OLD, "user_identities", ["provider", "subject"])
    op.drop_column("user_identities", "tenant")
    op.drop_column("user_identities", "issuer")
