# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Platform adapters (ADR-P4-12; plan phase 17, decisions S17-*).

Revision ID: 0008_integrations
Revises: 0007_registration
Created: 2026-10-20

- ``platform_links``: a field's link to an external platform through one adapter, off by default, its
  configuration encrypted.
- ``external_game_links``: a scheduled game's reference on that platform, the last send and its error.

The registration import itself needs no new column: ``game_registrations.source`` and
``external_ref`` (and their unique key per scheduled game) came with 0007_registration. The downgrade
drops both tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_integrations"
down_revision = "0007_registration"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _ts(name: str, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def _id() -> sa.Column:
    return sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    op.create_table(
        "platform_links",
        _id(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("adapter_id", sa.String(32), nullable=False),
        sa.Column("config_enc", sa.LargeBinary(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        _ts("created_at", nullable=False, default=True),
        _ts("updated_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_platform_links"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_platform_links_field_id_fields",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("field_id", "adapter_id", name="uq_platform_links_field_id_adapter_id"),
    )
    op.create_table(
        "external_game_links",
        _id(),
        sa.Column("scheduled_game_id", UUID, nullable=False),
        sa.Column("adapter_id", sa.String(32), nullable=False),
        sa.Column("external_ref", sa.String(256), nullable=True),
        sa.Column("cancelled", sa.Boolean(), nullable=False, server_default="false"),
        _ts("last_synced_at"),
        sa.Column("last_error", sa.String(64), nullable=True),
        _ts("created_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_external_game_links"),
        sa.ForeignKeyConstraint(["scheduled_game_id"], ["scheduled_games.id"],
                                name="fk_external_game_links_scheduled_game_id_scheduled_games", ondelete="CASCADE"),
        sa.UniqueConstraint("scheduled_game_id", "adapter_id",
                            name="uq_external_game_links_scheduled_game_id_adapter_id"),
    )


def downgrade() -> None:
    op.drop_table("external_game_links")
    op.drop_table("platform_links")
