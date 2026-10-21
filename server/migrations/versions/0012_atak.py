# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The remote ATAK relay's certificates (Phase 4 follow-up, decisions FU5-*).

Revision ID: 0012_atak
Revises: 0011_history
Created: 2026-10-21

- ``atak_cas``: one certificate authority per field; its private key only sealed under the server's
  secret key (``atak_pki.CaBox``).
- ``atak_certs``: every client certificate a field's CA issued (by SHA-256 and serial), its device,
  holder, whether it may see player positions, expiry and revocation.

The downgrade drops both tables (every enrolled ATAK device must then be enrolled again).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_atak"
down_revision = "0011_history"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _ts(name: str, nullable: bool = False, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def _id() -> sa.Column:
    return sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()"))


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ["users.id"], name=f"fk_{table}_{column}_users", ondelete="SET NULL")


def upgrade() -> None:
    op.create_table(
        "atak_cas",
        _id(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("cert_pem", sa.Text(), nullable=False),
        sa.Column("key_sealed", sa.LargeBinary(), nullable=False),
        sa.Column("ski", sa.String(40), nullable=False),
        _ts("not_after"),
        _ts("created_at", default=True),
        sa.PrimaryKeyConstraint("id", name="pk_atak_cas"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_atak_cas_field_id_fields", ondelete="CASCADE"),
        sa.UniqueConstraint("field_id", name="uq_atak_cas_field_id"),
        sa.UniqueConstraint("ski", name="uq_atak_cas_ski"),
        sa.CheckConstraint("ski ~ '^[0-9a-f]{40}$'", name="ck_atak_cas_ski"),
    )
    op.create_table(
        "atak_certs",
        _id(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("serial", sa.String(40), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("device_name", sa.String(48), nullable=False),
        sa.Column("holder_id", UUID, nullable=True),
        sa.Column("positions", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("issued_by", UUID, nullable=True),
        sa.Column("issued_via", sa.String(8), nullable=False, server_default=sa.text("'api'")),
        _ts("issued_at"),
        _ts("not_after"),
        _ts("revoked_at", nullable=True),
        sa.Column("revoked_by", UUID, nullable=True),
        sa.Column("revoke_reason", sa.String(32), nullable=True),
        _ts("last_connected_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_atak_certs"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_atak_certs_field_id_fields",
                                ondelete="CASCADE"),
        _user_fk("atak_certs", "holder_id"),
        _user_fk("atak_certs", "issued_by"),
        _user_fk("atak_certs", "revoked_by"),
        sa.UniqueConstraint("serial", name="uq_atak_certs_serial"),
        sa.UniqueConstraint("sha256", name="uq_atak_certs_sha256"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_atak_certs_sha256"),
        sa.CheckConstraint("serial ~ '^[0-9a-f]{1,40}$'", name="ck_atak_certs_serial"),
        sa.CheckConstraint("char_length(device_name) BETWEEN 1 AND 48", name="ck_atak_certs_device_name"),
        sa.CheckConstraint("not_after > issued_at", name="ck_atak_certs_lifetime"),
        sa.CheckConstraint("issued_via IN ('api', 'command')", name="ck_atak_certs_issued_via"),
    )
    op.create_index("ix_atak_certs_field_id", "atak_certs", ["field_id", "issued_at"])


def downgrade() -> None:
    op.drop_index("ix_atak_certs_field_id", table_name="atak_certs")
    op.drop_table("atak_certs")
    op.drop_table("atak_cas")
