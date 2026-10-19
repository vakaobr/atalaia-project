# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller sync (ADR-P4-3 as amended; plan phase 13, decisions P4R10-P4R13).

Revision ID: 0004_sync
Revises: 0003_personal_data
Created: 2026-10-20

- ``field_api_keys``: a field's API keys for its controllers, as SHA-256 only (two live
  during a rotation).
- ``controllers``: each controller that synced (its own id, version, last seen).
- ``games``: a controller's game, unique on ``(field_id, game_id, game_seed)``.
- ``game_events``: the games' logs, unique on the controller's own key
  ``(game, node_id, seq, game_time_ms, event_type)``.
- ``game_node_scores``: score counters per (game, source, team), merged by maximum.
- ``game_nodes``: the games' nodes (name, role, health).
- ``user_game_roles``: per-game roles (ADR-P4-1; decision S11-6 moved them here).

The downgrade drops them all, with what was synced: the controllers still have
it and send it again (``python3 -m atalaia_controller sync-key --resend``).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_sync"
down_revision = "0003_personal_data"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
EMPTY = sa.text("'{}'::jsonb")


def _uuid_pk() -> sa.Column:
    return sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def _game_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["game"], ["games.id"], name=f"fk_{table}_game_games", ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "field_api_keys",
        _uuid_pk(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("key_sha256", sa.String(64), nullable=False),
        sa.Column("label", sa.String(64), nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        _ts("created_at"),
        _ts("last_used_at", nullable=True, default=False),
        _ts("revoked_at", nullable=True, default=False),
        sa.PrimaryKeyConstraint("id", name="pk_field_api_keys"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_field_api_keys_field_id_fields",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_field_api_keys_created_by_users"),
        sa.UniqueConstraint("key_sha256", name="uq_field_api_keys_key_sha256"),
    )
    op.create_index("idx_field_api_keys_field", "field_api_keys", ["field_id"])
    op.create_table(
        "controllers",
        _uuid_pk(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("controller_id", UUID, nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("api_key_id", UUID, nullable=True),
        _ts("first_seen_at"),
        _ts("last_seen_at"),
        sa.PrimaryKeyConstraint("id", name="pk_controllers"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_controllers_field_id_fields", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["api_key_id"], ["field_api_keys.id"], name="fk_controllers_api_key_id_field_api_keys",
                                ondelete="SET NULL"),
        sa.UniqueConstraint("field_id", "controller_id", name="uq_controllers_field_id_controller_id"),
    )
    op.create_table(
        "games",
        _uuid_pk(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("game_seed", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("mode_id", sa.String(128), nullable=False),
        sa.Column("teams", postgresql.JSONB(), nullable=False),
        sa.Column("team_info", postgresql.JSONB(), nullable=False, server_default=EMPTY),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default=EMPTY),
        sa.Column("squads", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(16), nullable=False),
        _ts("controller_created_at", default=False),
        _ts("started_at", nullable=True, default=False),
        _ts("ended_at", nullable=True, default=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_games"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_games_field_id_fields", ondelete="CASCADE"),
        sa.UniqueConstraint("field_id", "game_id", "game_seed", name="uq_games_field_id_game_id_game_seed"),
        sa.CheckConstraint("state IN ('ready', 'running', 'paused', 'ended')", name="ck_games_state"),
        sa.CheckConstraint("game_id BETWEEN 0 AND 65535 AND game_seed BETWEEN 0 AND 4294967295",
                           name="ck_games_radio_id"),
    )
    op.create_index("idx_games_field_created", "games", ["field_id", "controller_created_at"])
    op.create_table(
        "game_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("game", UUID, nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("game_time_ms", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("team", sa.String(32), nullable=True),
        sa.Column("squad", sa.SmallInteger(), nullable=True),
        sa.Column("priority", sa.String(16), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False, server_default=EMPTY),
        sa.Column("epoch", sa.Integer(), nullable=True),
        sa.Column("pkt_seq", sa.Integer(), nullable=True),
        _ts("received_at"),
        sa.PrimaryKeyConstraint("id", name="pk_game_events"),
        _game_fk("game_events"),
        sa.UniqueConstraint("game", "node_id", "seq", "game_time_ms", "event_type",
                            name="uq_game_events_game_node_id_seq_game_time_ms_event_type"),
    )
    op.create_index("idx_game_events_game_time", "game_events", ["game", "game_time_ms"])
    op.create_index("idx_game_events_type", "game_events", ["game", "event_type"])
    op.create_table(
        "game_node_scores",
        sa.Column("game", UUID, nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("team", sa.String(32), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("game", "source", "team", name="pk_game_node_scores"),
        _game_fk("game_node_scores"),
        sa.CheckConstraint("value >= 0", name="ck_game_node_scores_value"),
    )
    op.create_table(
        "game_nodes",
        sa.Column("game", UUID, nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("info", postgresql.JSONB(), nullable=False, server_default=EMPTY),
        _ts("last_seen_at", default=False),
        sa.PrimaryKeyConstraint("game", "node_id", name="pk_game_nodes"),
        _game_fk("game_nodes"),
    )
    op.create_table(
        "user_game_roles",
        _uuid_pk(),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("game", UUID, nullable=False),
        sa.Column("role_id", sa.SmallInteger(), nullable=False),
        sa.Column("granted_by", UUID, nullable=True),
        _ts("granted_at"),
        sa.PrimaryKeyConstraint("id", name="pk_user_game_roles"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_user_game_roles_user_id_users", ondelete="CASCADE"),
        _game_fk("user_game_roles"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_user_game_roles_role_id_roles"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], name="fk_user_game_roles_granted_by_users"),
        sa.UniqueConstraint("user_id", "game", "role_id", name="uq_user_game_roles_user_id_game_role_id"),
    )
    op.create_index("idx_user_game_roles_game", "user_game_roles", ["game"])


def downgrade() -> None:
    op.drop_index("idx_user_game_roles_game", table_name="user_game_roles")
    op.drop_table("user_game_roles")
    op.drop_table("game_nodes")
    op.drop_table("game_node_scores")
    op.drop_index("idx_game_events_type", table_name="game_events")
    op.drop_index("idx_game_events_game_time", table_name="game_events")
    op.drop_table("game_events")
    op.drop_index("idx_games_field_created", table_name="games")
    op.drop_table("games")
    op.drop_table("controllers")
    op.drop_index("idx_field_api_keys_field", table_name="field_api_keys")
    op.drop_table("field_api_keys")
