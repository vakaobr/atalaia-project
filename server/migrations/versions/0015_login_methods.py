# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Login methods: social login (OpenID Connect), passkeys (WebAuthn), optional passwords (decisions LG-*).

Revision ID: 0015_login_methods
Revises: 0014_registration_staff
Created: 2026-10-28

- ``users.password_hash`` may be null: an account that signs in with a passkey or a social login has no
  password.
- ``sessions.confirmed_at``: when the session last proved the account is there (a login, a TOTP or passkey
  step-up, a social re-login); an account with no password confirms a sensitive change with a recent one.
- ``user_identities``: a social login linked to an account, the provider and its subject and nothing more.
- ``passkeys``: an account's WebAuthn credentials.
- ``oidc_logins``: a social login in progress (state, nonce, PKCE verifier), ten minutes and one use.

The downgrade drops the tables and the column. It cannot give a passwordless account a password: it refuses
(a clear error) while one exists, so nobody is left with an account that cannot log in.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_login_methods"
down_revision = "0014_registration_staff"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _id() -> sa.Column:
    return sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()"))


def _created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def upgrade() -> None:
    op.alter_column("users", "password_hash", existing_type=sa.String(256), nullable=True)
    op.add_column("sessions", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE sessions SET confirmed_at = created_at")
    op.create_table(
        "user_identities",
        _id(),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        _created(),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_identities"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_identities_user_id_users",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("provider", "subject", name="uq_user_identities_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_identities_user_id_provider"),
        sa.CheckConstraint("provider IN ('google', 'microsoft', 'apple')", name="ck_user_identities_provider"),
    )
    op.create_table(
        "passkeys",
        _id(),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("rp_id", sa.String(255), nullable=False),
        sa.Column("transports", sa.String(128), nullable=True),
        sa.Column("backed_up", sa.Boolean(), nullable=False, server_default="false"),
        _created(),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_passkeys"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_passkeys_user_id_users", ondelete="CASCADE"),
        sa.UniqueConstraint("credential_id", name="uq_passkeys_credential_id"),
    )
    op.create_index("idx_passkeys_user", "passkeys", ["user_id"])
    op.create_table(
        "oidc_logins",
        _id(),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("binding_hash", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("purpose", sa.String(8), nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("session_id", UUID, nullable=True),
        sa.Column("nonce", sa.String(64), nullable=False),
        sa.Column("code_verifier", sa.String(128), nullable=False),
        sa.Column("redirect_uri", sa.String(512), nullable=False),
        sa.Column("return_to", sa.String(512), nullable=False),
        sa.Column("consent", sa.Boolean(), nullable=False, server_default="false"),
        _created(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_oidc_logins"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_oidc_logins_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], name="fk_oidc_logins_session_id_sessions",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("state_hash", name="uq_oidc_logins_state_hash"),
        sa.CheckConstraint("purpose IN ('login', 'link', 'reauth')", name="ck_oidc_logins_purpose"),
    )
    op.create_index("idx_oidc_logins_expires", "oidc_logins", ["expires_at"])


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM users WHERE password_hash IS NULL")):
        raise RuntimeError("0015_login_methods: accounts with no password exist; give them a password or delete "
                           "them before downgrading")
    op.drop_index("idx_oidc_logins_expires", table_name="oidc_logins")
    op.drop_table("oidc_logins")
    op.drop_index("idx_passkeys_user", table_name="passkeys")
    op.drop_table("passkeys")
    op.drop_table("user_identities")
    op.drop_column("sessions", "confirmed_at")
    op.alter_column("users", "password_hash", existing_type=sa.String(256), nullable=False)
