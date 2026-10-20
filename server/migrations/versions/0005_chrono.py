# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The chrono registry (ADR-P4-5 as amended; plan phase 14, decisions P4R14, P4R15, S14-*).

Revision ID: 0005_chrono
Revises: 0004_sync
Created: 2026-10-20

- ``field_player_ids``: an account's pseudonymous player id per field (ADR-P4-11's table,
  made here for the chrono registry's own history, erasure and sharing, decision S14-3).
- ``marshal_keys``: the marshals' Ed25519 public keys with their periods; never a private key.
- ``replicas``: the fields' replica registries, by the app's ``replica_id``.
- ``chrono_readings``: one row per signed reading, the record as received, verified.
- ``chrono_rejects``: readings that did not verify, kept apart with their reason.
- ``chrono_violations``: spot checks that failed or warned, one per series.
- ``consents.field_id``: the field a ``chrono_sharing`` consent is for; the one-live-consent
  index becomes two (account-wide purposes, per-field purposes).

The downgrade drops the registry with what was synced (the controllers still have it and
send it again: ``python3 -m atalaia_controller sync-key --resend``) and the per-field
consents (``chrono_sharing``), which the 0004 schema cannot hold.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_chrono"
down_revision = "0004_sync"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _uuid_pk() -> sa.Column:
    return sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def _field_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name=f"fk_{table}_field_id_fields", ondelete="CASCADE")


def _controller_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["controller"], ["controllers.id"], name=f"fk_{table}_controller_controllers",
                                   ondelete="SET NULL")


def upgrade() -> None:
    op.add_column("consents", sa.Column("field_id", UUID, nullable=True))
    op.create_foreign_key("fk_consents_field_id_fields", "consents", "fields", ["field_id"], ["id"],
                          ondelete="CASCADE")
    op.drop_index("uq_consents_live", table_name="consents")
    op.create_index("uq_consents_live", "consents", ["user_id", "purpose"], unique=True,
                    postgresql_where=sa.text("withdrawn_at IS NULL AND field_id IS NULL"))
    op.create_index("uq_consents_live_field", "consents", ["user_id", "purpose", "field_id"], unique=True,
                    postgresql_where=sa.text("withdrawn_at IS NULL AND field_id IS NOT NULL"))

    op.create_table(
        "field_player_ids",
        _uuid_pk(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("player_id", sa.String(64), nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_field_player_ids"),
        _field_fk("field_player_ids"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_field_player_ids_user_id_users",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("field_id", "player_id", name="uq_field_player_ids_field_id_player_id"),
    )
    op.create_index("idx_field_player_ids_user", "field_player_ids", ["user_id"])

    op.create_table(
        "marshal_keys",
        _uuid_pk(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("marshal_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("player_id", sa.String(64), nullable=True),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("source", sa.String(16), nullable=False),
        _ts("valid_from", default=False),
        _ts("valid_until", nullable=True, default=False),
        _ts("revoked_at", nullable=True, default=False),
        sa.Column("revoked_by", UUID, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_marshal_keys"),
        _field_fk("marshal_keys"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_marshal_keys_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], name="fk_marshal_keys_revoked_by_users",
                                ondelete="SET NULL"),
        sa.UniqueConstraint("field_id", "marshal_id", "public_key",
                            name="uq_marshal_keys_field_id_marshal_id_public_key"),
        sa.CheckConstraint("octet_length(public_key) = 32", name="ck_marshal_keys_public_key"),
        sa.CheckConstraint("source IN ('controller', 'account')", name="ck_marshal_keys_source"),
    )
    op.create_index("idx_marshal_keys_user", "marshal_keys", ["user_id"])

    op.create_table(
        "replicas",
        _uuid_pk(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("replica_id", UUID, nullable=False),
        sa.Column("owner_player_id", sa.String(64), nullable=False),
        sa.Column("replica_type", sa.String(16), nullable=False),
        sa.Column("replica_class", sa.String(32), nullable=False),
        sa.Column("make_model", sa.String(64), nullable=True),
        sa.Column("tag_type", sa.String(8), nullable=True),
        sa.Column("tag_uid", sa.String(64), nullable=True),
        _ts("registered_at", nullable=True, default=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.PrimaryKeyConstraint("id", name="pk_replicas"),
        _field_fk("replicas"),
        sa.UniqueConstraint("field_id", "replica_id", name="uq_replicas_field_id_replica_id"),
    )
    op.create_index("idx_replicas_owner", "replicas", ["field_id", "owner_player_id"])

    op.create_table(
        "chrono_readings",
        _uuid_pk(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("reading_id", UUID, nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.Column("replica_id", UUID, nullable=False),
        sa.Column("player_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("velocity_mps", sa.Float(), nullable=False),
        sa.Column("bb_weight_g", sa.Float(), nullable=False),
        sa.Column("energy_j", sa.Float(), nullable=False),
        sa.Column("chrono_id", sa.String(64), nullable=False),
        sa.Column("marshal_id", sa.String(64), nullable=False),
        sa.Column("record_field_id", sa.String(64), nullable=False),
        sa.Column("record_game_id", sa.String(64), nullable=True),
        _ts("timestamp", default=False),
        sa.Column("ref_reading_id", UUID, nullable=True),
        sa.Column("series_id", UUID, nullable=False),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.Column("marshal_key", UUID, nullable=False),
        sa.Column("game", UUID, nullable=True),
        sa.Column("controller", UUID, nullable=True),
        _ts("received_at", default=False),
        _ts("verified_at"),
        sa.PrimaryKeyConstraint("id", name="pk_chrono_readings"),
        _field_fk("chrono_readings"),
        sa.ForeignKeyConstraint(["marshal_key"], ["marshal_keys.id"], name="fk_chrono_readings_marshal_key_marshal_keys"),
        sa.ForeignKeyConstraint(["game"], ["games.id"], name="fk_chrono_readings_game_games", ondelete="SET NULL"),
        _controller_fk("chrono_readings"),
        sa.UniqueConstraint("field_id", "reading_id", name="uq_chrono_readings_field_id_reading_id"),
        sa.CheckConstraint("type IN ('checkin', 'spotcheck', 'retest')", name="ck_chrono_readings_type"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('pass', 'fail', 'warn', 'unjudged')",
                           name="ck_chrono_readings_outcome"),
    )
    op.create_index("idx_chrono_readings_player", "chrono_readings", ["field_id", "player_id"])
    op.create_index("idx_chrono_readings_replica", "chrono_readings", ["field_id", "replica_id"])
    op.create_index("idx_chrono_readings_series", "chrono_readings", ["field_id", "series_id"])
    op.create_index("idx_chrono_readings_time", "chrono_readings", ["field_id", "timestamp"])
    op.create_index("idx_chrono_readings_key", "chrono_readings", ["marshal_key"])

    op.create_table(
        "chrono_rejects",
        _uuid_pk(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("record_text", sa.Text(), nullable=False),
        sa.Column("record_sha256", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("detail", sa.String(256), nullable=False),
        sa.Column("reading_id", sa.String(64), nullable=True),
        sa.Column("player_id", sa.String(64), nullable=True),
        sa.Column("marshal_id", sa.String(64), nullable=True),
        sa.Column("series_id", UUID, nullable=True),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.Column("controller", UUID, nullable=True),
        _ts("received_at", nullable=True, default=False),
        sa.Column("times", sa.Integer(), nullable=False, server_default="1"),
        _ts("first_seen_at"),
        _ts("last_seen_at"),
        sa.PrimaryKeyConstraint("id", name="pk_chrono_rejects"),
        _field_fk("chrono_rejects"),
        _controller_fk("chrono_rejects"),
        sa.UniqueConstraint("field_id", "record_sha256", name="uq_chrono_rejects_field_id_record_sha256"),
        sa.CheckConstraint("reason IN ('format', 'unsigned', 'signature', 'marshal', 'conflict')",
                           name="ck_chrono_rejects_reason"),
    )
    op.create_index("idx_chrono_rejects_player", "chrono_rejects", ["field_id", "player_id"])

    op.create_table(
        "chrono_violations",
        _uuid_pk(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("series_id", UUID, nullable=False),
        sa.Column("reading", UUID, nullable=False),
        sa.Column("player_id", sa.String(64), nullable=False),
        sa.Column("replica_id", UUID, nullable=False),
        sa.Column("violation_type", sa.String(32), nullable=False),
        sa.Column("energy_j", sa.Float(), nullable=False),
        sa.Column("game", UUID, nullable=True),
        sa.Column("outcome", sa.String(16), nullable=True),
        sa.Column("resolved_by", UUID, nullable=True),
        _ts("resolved_at", nullable=True, default=False),
        _ts("created_at"),
        sa.PrimaryKeyConstraint("id", name="pk_chrono_violations"),
        _field_fk("chrono_violations"),
        sa.ForeignKeyConstraint(["reading"], ["chrono_readings.id"], name="fk_chrono_violations_reading_chrono_readings",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["game"], ["games.id"], name="fk_chrono_violations_game_games", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], name="fk_chrono_violations_resolved_by_users",
                                ondelete="SET NULL"),
        sa.UniqueConstraint("field_id", "series_id", name="uq_chrono_violations_field_id_series_id"),
        sa.CheckConstraint("violation_type IN ('over_limit', 'over_tolerance')",
                           name="ck_chrono_violations_violation_type"),
        sa.CheckConstraint("outcome IS NULL OR outcome IN ('warning', 'pulled', 'ban')",
                           name="ck_chrono_violations_outcome"),
    )
    op.create_index("idx_chrono_violations_reading", "chrono_violations", ["reading"])
    op.create_index("idx_chrono_violations_player", "chrono_violations", ["field_id", "player_id"])


def downgrade() -> None:
    op.drop_index("idx_chrono_violations_player", table_name="chrono_violations")
    op.drop_index("idx_chrono_violations_reading", table_name="chrono_violations")
    op.drop_table("chrono_violations")
    op.drop_index("idx_chrono_rejects_player", table_name="chrono_rejects")
    op.drop_table("chrono_rejects")
    for name in ("key", "time", "series", "replica", "player"):
        op.drop_index(f"idx_chrono_readings_{name}", table_name="chrono_readings")
    op.drop_table("chrono_readings")
    op.drop_index("idx_replicas_owner", table_name="replicas")
    op.drop_table("replicas")
    op.drop_index("idx_marshal_keys_user", table_name="marshal_keys")
    op.drop_table("marshal_keys")
    op.drop_index("idx_field_player_ids_user", table_name="field_player_ids")
    op.drop_table("field_player_ids")
    # The 0004 schema holds account-wide consents only: the per-field ones (chrono_sharing) go.
    op.execute("DELETE FROM consents WHERE field_id IS NOT NULL")
    op.drop_index("uq_consents_live_field", table_name="consents")
    op.drop_index("uq_consents_live", table_name="consents")
    op.create_index("uq_consents_live", "consents", ["user_id", "purpose"], unique=True,
                    postgresql_where=sa.text("withdrawn_at IS NULL"))
    op.drop_constraint("fk_consents_field_id_fields", "consents", type_="foreignkey")
    op.drop_column("consents", "field_id")
