# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Club profiles and branding sync (P4R19; plan phase 18, decisions S18-*).

Revision ID: 0009_clubs
Revises: 0008_integrations
Created: 2026-10-20

- ``branding_images``: images checked by the controller's ``images.py``, stored once by the SHA-256 of
  their checked bytes.
- ``clubs``: a club's profile (name, short name, slug, description, colour, logo, crest), its public page
  off by default and a server administrator's hiding of it.
- ``club_members``: accounts' memberships with their club role (``admin`` or ``member``) and when the person
  accepted the invitation: personal data.
- ``club_reports``: reports of public club pages and their decisions.
- ``field_teams``: a field's saved teams (a club's, or its own), synced to its controllers.
- ``fields``: the field's branding (``branding_name``, ``accent``, ``logo_sha256``, ``wallpaper_sha256``).

The downgrade drops the columns and the tables.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_clubs"
down_revision = "0008_integrations"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _ts(name: str, nullable: bool = True, default: bool = False) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable,
                     server_default=sa.text("now()") if default else None)


def _id() -> sa.Column:
    return sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()"))


def _image_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ["branding_images.sha256"],
                                   name=f"fk_{table}_{column}_branding_images")


def _user_fk(table: str, column: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], ["users.id"], name=f"fk_{table}_{column}_users", ondelete="SET NULL")


def upgrade() -> None:
    op.create_table(
        "branding_images",
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(16), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        _ts("created_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("sha256", name="pk_branding_images"),
    )
    op.create_table(
        "clubs",
        _id(),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("short_name", sa.String(32), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("colour", sa.String(7), nullable=True),
        sa.Column("logo_sha256", sa.String(64), nullable=True),
        sa.Column("crest_sha256", sa.String(64), nullable=True),
        sa.Column("public_page", sa.Boolean(), nullable=False, server_default="false"),
        _ts("hidden_at"),
        sa.Column("hidden_reason", sa.String(512), nullable=True),
        sa.Column("hidden_by", UUID, nullable=True),
        sa.Column("created_by", UUID, nullable=True),
        _ts("created_at", nullable=False, default=True),
        _ts("updated_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_clubs"),
        sa.UniqueConstraint("slug", name="uq_clubs_slug"),
        sa.CheckConstraint("colour IS NULL OR colour ~ '^#[0-9a-f]{6}$'", name="ck_clubs_colour"),
        _image_fk("clubs", "logo_sha256"),
        _image_fk("clubs", "crest_sha256"),
        _user_fk("clubs", "hidden_by"),
        _user_fk("clubs", "created_by"),
    )
    op.create_index("idx_clubs_created_by", "clubs", ["created_by"])
    op.create_index("idx_clubs_hidden_by", "clubs", ["hidden_by"])
    op.create_table(
        "club_members",
        _id(),
        sa.Column("club_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="member"),
        sa.Column("added_by", UUID, nullable=True),
        _ts("accepted_at"),
        _ts("created_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_club_members"),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_club_members_club_id_clubs", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_club_members_user_id_users", ondelete="CASCADE"),
        _user_fk("club_members", "added_by"),
        sa.UniqueConstraint("club_id", "user_id", name="uq_club_members_club_id_user_id"),
        sa.CheckConstraint("role IN ('admin', 'member')", name="ck_club_members_role"),
    )
    op.create_index("idx_club_members_user", "club_members", ["user_id"])
    op.create_index("idx_club_members_added_by", "club_members", ["added_by"])
    op.create_table(
        "club_reports",
        _id(),
        sa.Column("club_id", UUID, nullable=False),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("reporter_id", UUID, nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        _ts("decided_at"),
        sa.Column("decided_by", UUID, nullable=True),
        _ts("created_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_club_reports"),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_club_reports_club_id_clubs", ondelete="CASCADE"),
        _user_fk("club_reports", "reporter_id"),
        _user_fk("club_reports", "decided_by"),
        sa.CheckConstraint("reason IN ('rights', 'offensive', 'impersonation', 'other')",
                           name="ck_club_reports_reason"),
        sa.CheckConstraint("status IN ('open', 'dismissed', 'actioned')", name="ck_club_reports_status"),
    )
    op.create_index("idx_club_reports_status_created", "club_reports", ["status", "created_at"])
    op.create_index("idx_club_reports_club", "club_reports", ["club_id"])
    op.create_index("idx_club_reports_reporter", "club_reports", ["reporter_id"])
    op.create_index("idx_club_reports_decided_by", "club_reports", ["decided_by"])
    op.create_table(
        "field_teams",
        _id(),
        sa.Column("field_id", UUID, nullable=False),
        sa.Column("club_id", UUID, nullable=True),
        sa.Column("name", sa.String(32), nullable=True),
        sa.Column("colour", sa.String(23), nullable=True),
        sa.Column("crest_sha256", sa.String(64), nullable=True),
        _ts("created_at", nullable=False, default=True),
        _ts("updated_at", nullable=False, default=True),
        sa.PrimaryKeyConstraint("id", name="pk_field_teams"),
        sa.ForeignKeyConstraint(["field_id"], ["fields.id"], name="fk_field_teams_field_id_fields", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["club_id"], ["clubs.id"], name="fk_field_teams_club_id_clubs", ondelete="CASCADE"),
        _image_fk("field_teams", "crest_sha256"),
        sa.CheckConstraint("name IS NOT NULL OR club_id IS NOT NULL", name="ck_field_teams_named"),
    )
    op.create_index("idx_field_teams_field", "field_teams", ["field_id"])
    op.create_index("idx_field_teams_club", "field_teams", ["club_id"])
    op.add_column("fields", sa.Column("branding_name", sa.String(48), nullable=True))
    op.add_column("fields", sa.Column("accent", sa.String(7), nullable=True))
    op.add_column("fields", sa.Column("logo_sha256", sa.String(64), nullable=True))
    op.add_column("fields", sa.Column("wallpaper_sha256", sa.String(64), nullable=True))
    op.create_check_constraint("ck_fields_accent", "fields", "accent IS NULL OR accent ~ '^#[0-9a-f]{6}$'")
    op.create_foreign_key("fk_fields_logo_sha256_branding_images", "fields", "branding_images", ["logo_sha256"],
                          ["sha256"])
    op.create_foreign_key("fk_fields_wallpaper_sha256_branding_images", "fields", "branding_images",
                          ["wallpaper_sha256"], ["sha256"])


def downgrade() -> None:
    op.drop_constraint("fk_fields_wallpaper_sha256_branding_images", "fields", type_="foreignkey")
    op.drop_constraint("fk_fields_logo_sha256_branding_images", "fields", type_="foreignkey")
    op.drop_constraint("ck_fields_accent", "fields", type_="check")
    for column in ("wallpaper_sha256", "logo_sha256", "accent", "branding_name"):
        op.drop_column("fields", column)
    op.drop_table("field_teams")
    op.drop_table("club_reports")
    op.drop_table("club_members")
    op.drop_table("clubs")
    op.drop_table("branding_images")
