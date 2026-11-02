# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""One database role per hosted field (decision S2113-1; closes S21-13).

Row-level security keyed on ``set_config('atalaia.tenant', ...)`` is only as strong as the server's ability to
keep that setting honest: any statement that can call ``set_config`` could switch fields. So the privileges, not a
setting, now keep the fields apart:

- every field has a role of its own, ``atalaia_t_<the field's id, 32 hex digits>`` (the id is the registry's
  ``field_id``, never user text), ``NOLOGIN``, no superuser, no ``BYPASSRLS``, owning nothing;
- that role alone holds the grants on its field's schema and tables and on its rows of the hub's sharing tables;
- the server's login role (``atalaia_app``) holds **no** grant on any field's tables: it may read the registry, add
  to the quota inbox and ``SET ROLE`` to a field's role (``GRANT <field role> TO <server role> WITH INHERIT FALSE,
  SET TRUE``), nothing more. Every hosted request's transaction starts with ``set_config('role', <field role>,
  true)`` (``tenancy.TenantSession``), so the connection can reach that field's rows only; a request for field A
  that runs ``set_config('atalaia.tenant', 'field_b', ...)`` finds ``permission denied`` on field B's schema.

This module holds the names and the SQL the operator's commands (``hosted.py``) and migration 0023 share.
"""

from __future__ import annotations

import re
import uuid

PREFIX = "atalaia_t_"
ROLE_PATTERN = re.compile(r"atalaia_t_[0-9a-f]{32}")
SCHEMA_PATTERN = re.compile(r"field_[a-z0-9_]{1,40}")


def role_for(field_id: uuid.UUID) -> str:
    """The role of the field with this id (the registry's generated ``role_name`` column says the same)."""
    return PREFIX + uuid.UUID(str(field_id)).hex


def check_tenant_role(name: str) -> str:
    if not isinstance(name, str) or not ROLE_PATTERN.fullmatch(name):
        raise ValueError(f"not a field's database role: {name!r}")
    return name


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def create_sql(role: str) -> str:
    """Makes the role if it is missing (idempotent). No login, no attribute that could bypass the isolation."""
    r = check_tenant_role(role)
    return (f"DO $do$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{r}') THEN "
            f"CREATE ROLE {_q(r)} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS; "
            f"END IF; END $do$")


def drop_sql(role: str, schema: str) -> list[str]:
    """Takes back every grant the role holds (its schema, its tables and sequences, the hub's sharing objects), then
    drops it. Run as the owner role, which made the grants; the schema may already be gone."""
    r = _q(check_tenant_role(role))
    if not SCHEMA_PATTERN.fullmatch(schema):
        raise ValueError(f"not a tenant schema name: {schema!r}")
    s = _q(schema)
    mine = f"EXISTS (SELECT FROM pg_roles WHERE rolname = '{role}')"
    return [
        f"DO $do$ BEGIN IF {mine} AND to_regnamespace('{schema}') IS NOT NULL THEN "
        f"REVOKE ALL ON ALL TABLES IN SCHEMA {s} FROM {r}; "
        f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {s} FROM {r}; "
        f"REVOKE ALL ON SCHEMA {s} FROM {r}; END IF; END $do$",
        f"DO $do$ BEGIN IF {mine} THEN "
        f"IF to_regclass('public.atalaia_share_members') IS NOT NULL THEN "
        f"REVOKE ALL ON public.atalaia_share_members, public.atalaia_share_records, public.atalaia_share_codes "
        f"FROM {r}; "
        f"REVOKE ALL ON FUNCTION public.atalaia_share_read(uuid[], integer), public.atalaia_share_redeem(bytea), "
        f"public.atalaia_share_peers(uuid), public.atalaia_caller_tenant() FROM {r}; END IF; "
        f"REVOKE ALL ON SCHEMA public FROM {r}; END IF; END $do$",
        f"DROP ROLE IF EXISTS {r}",
    ]
