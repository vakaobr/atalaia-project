# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The firmware catalogue (plan phase 19, decisions S19-*).

Revision ID: 0010_firmware
Revises: 0009_clubs
Created: 2026-10-20

- ``firmware_releases``: the catalogue's entries, a list only (no image is stored: OTA is not built): the
  platform, the version, the image's size and SHA-256, the Ed25519 signature over them by a release key the
  server trusts and that key's id, notes, when it was released, who added it and, for a withdrawn release,
  when and why. Unique on (platform, version).

Device health needs no table: it is read from the synced ``game_nodes`` and ``game_events``. The remote GM keeps
nothing but its audit log rows. The downgrade drops the table.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_firmware"
down_revision = "0009_clubs"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _ts(name: str, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def upgrade() -> None:
    op.create_table(
        "firmware_releases",
        sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("size", sa.BigInteger, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("signature", sa.String(88), nullable=False),
        sa.Column("key_id", sa.String(16), nullable=False),
        sa.Column("notes", sa.Text),
        _ts("released_at"),
        sa.Column("added_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL",
                                                  name="fk_firmware_releases_added_by_users")),
        _ts("yanked_at"),
        sa.Column("yank_reason", sa.String(200)),
        _ts("created_at", nullable=False, default=True),
        _ts("updated_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_firmware_releases"),
        sa.UniqueConstraint("platform", "version", name="uq_firmware_releases_platform_version"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_firmware_releases_sha256"),
        sa.CheckConstraint("size > 0", name="ck_firmware_releases_size"),
    )


def downgrade() -> None:
    op.drop_table("firmware_releases")
