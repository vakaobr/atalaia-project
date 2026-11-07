# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registering phone's public key on a registration (TKB-1 to TKB-8).

Revision ID: 0032_registration_binding
Revises: 0031_hub_history
Created: 2026-11-07

``game_registrations.binding_key``: the Ed25519 public key (standard base64, 44 characters) the player's app gives a
registration it keeps a ticket for, sent in the roster to a controller that asks (``?binding=1``) so that a self
check-in can prove it comes from that phone. Nothing to backfill: every registration made before has none, and its
self check-ins show as unbound, as before.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0032_registration_binding"
down_revision = "0031_hub_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_registrations", sa.Column("binding_key", sa.String(44), nullable=True))


def downgrade() -> None:
    op.drop_column("game_registrations", "binding_key")
