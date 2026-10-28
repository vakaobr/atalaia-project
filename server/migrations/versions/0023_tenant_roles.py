# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hosted mode: one database role per field (S2113-1; closes S21-13).

Revision ID: 0023_tenant_roles
Revises: 0022_field_retention
Created: 2026-10-28

Hosted mode runs every migration once in each field's schema (``hosted migrate``, as the owner role). In a field's
schema this migration makes the field's own database role, ``atalaia_t_<the field's id>`` (``tenant_roles``): NOLOGIN,
no superuser, no BYPASSRLS, nothing owned. It is the migration that gives every field a hub already holds its role;
the grants and the server role's right to ``SET ROLE`` to it follow in the same ``hosted migrate`` run
(``hosted.apply_security``), and a field made later gets its role from ``hosted create``.

It does nothing in a single-field server (no registry, schema ``public``) and nothing in a field's schema that is
not registered yet (``hosted create`` runs the migrations before it registers the field; it makes the role itself).

The downgrade takes back the role's grants and drops it. It does not give the server's role back its old direct
grants on the field's tables: run ``hosted migrate`` of the release you went back to (it applies them again).
"""

from __future__ import annotations

import re
import uuid
from typing import Optional

import sqlalchemy as sa
from alembic import op

from atalaia_server import tenant_roles

revision = "0023_tenant_roles"
down_revision = "0022_field_retention"
branch_labels = None
depends_on = None


def _field_of_this_schema() -> Optional[tuple[str, str]]:
    """(the field's role, its schema) when the migration runs in a registered hosted field's schema, else None."""
    bind = op.get_bind()
    schema = bind.scalar(sa.text("SELECT current_schema()"))
    if not isinstance(schema, str) or not re.fullmatch(r"field_[a-z0-9_]{1,40}", schema):
        return None
    if not bind.scalar(sa.text("SELECT to_regclass('public.atalaia_tenants') IS NOT NULL")):
        return None
    field_id = bind.scalar(sa.text("SELECT field_id FROM public.atalaia_tenants WHERE schema_name = :s"),
                           {"s": schema})
    if field_id is None:
        return None
    return tenant_roles.role_for(uuid.UUID(str(field_id))), schema


def upgrade() -> None:
    found = _field_of_this_schema()
    if found is not None:
        op.get_bind().exec_driver_sql(tenant_roles.create_sql(found[0]))


def downgrade() -> None:
    found = _field_of_this_schema()
    if found is not None:
        for statement in tenant_roles.drop_sql(*found):
            op.get_bind().exec_driver_sql(statement)
