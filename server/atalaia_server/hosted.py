# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hosted hub's operator tooling (ADR-P4-4 as built; plan phase 21; decisions S21-*).

    python -m atalaia_server hosted init     [--app-role ROLE]
    python -m atalaia_server hosted create   SLUG --name NAME [--field-type T] [--timezone TZ] [--app-role ROLE]
    python -m atalaia_server hosted list
    python -m atalaia_server hosted migrate  [--app-role ROLE]
    python -m atalaia_server hosted check    [--app-role ROLE]
    python -m atalaia_server hosted suspend  SLUG --reason TEXT
    python -m atalaia_server hosted resume   SLUG --reason TEXT
    python -m atalaia_server hosted quota    SLUG NAME VALUE --reason TEXT      (VALUE: a number, off or default)
    python -m atalaia_server hosted usage    [SLUG]
    python -m atalaia_server hosted quota-hits
    python -m atalaia_server hosted domain   set SLUG HOST --reason TEXT | verify SLUG | remove SLUG --reason TEXT
    python -m atalaia_server hosted export   SLUG --out FILE.zip --reason TEXT
    python -m atalaia_server hosted delete   SLUG --confirm SLUG --reason TEXT
    python -m atalaia_server import-field    FILE.zip          (into a single-field server)

They run with ATALAIA_DATABASE_URL set to the **owner** role (the one that
owns the schemas and runs the migrations), never the server's role, which
``--app-role`` names (ATALAIA_APP_ROLE, ``atalaia_app`` by default): a login
role that is no superuser, has no BYPASSRLS and owns nothing.

- ``init`` makes the registry (``public.atalaia_tenants``; the server may only
  read it) and the hub's audit log (``public.atalaia_hub_audit``; the server
  cannot read it), and refuses a database whose ``public`` already holds the
  single-field tables.
  Since SVX-2 it also makes the hub-level chrono sharing's three ``public.atalaia_share_*`` tables and two
  SECURITY DEFINER functions (``SHARE_DDL``; ``migrate`` brings an older hub up to date).
- ``create`` makes the schema ``field_<slug>``, runs every migration in it,
  writes the field's one ``fields`` row, applies the grants and the row-level
  security (``apply_security``) and registers the tenant; a failure leaves no
  schema behind.
- ``migrate`` brings every tenant to the newest revision, then applies the
  grants and policies again (a new table gets them too).
- ``check`` reads what keeps the fields apart (``check_hub``: ownership,
  forced row-level security and the one policy on every table, the server
  role's exact privileges) and exits 1 on any problem; ``server/restore.sh``
  runs it after restoring a hosted hub (Phase 4 follow-up, decisions FU4-*).
- ``quota`` gives one field its own limit on one resource (``config.QUOTA_DEFAULTS`` names them) in the registry,
  over the hub's ``ATALAIA_QUOTA_*``: a whole number, ``off`` (no limit) or ``default`` (the hub's again). ``usage``
  prints what each field (or one) uses against its effective limits. ``quota-hits`` moves the notes the server left
  when a field was refused for a quota (``public.atalaia_quota_hits``, which the server may only add to) into the
  hub's audit log and prints them; ``list`` and ``check`` say how many wait (decisions PKC-5).
- ``domain`` gives a field one custom host name besides ``<slug>.<domain>`` (decisions PKC-6): ``set`` records it as
  *pending* and prints the DNS TXT record the field must publish, ``verify`` reads that record and, only if it is
  there, turns the name on (routing, and a certificate through the ``ask`` endpoint), ``remove`` takes it away.
- ``export`` writes one ZIP: ``manifest.json`` (format, revision, tables in load
  order, row counts, SHA-256 of each file) and ``tables/<table>.csv`` for every
  table of the tenant's schema (``COPY ... TO STDOUT``), read in one
  repeatable-read, read-only transaction. It is the field's whole dataset,
  personal data and credential hashes included, for the data controller (the
  field operator) on their instruction or at the end of the contract (the DPA):
  the file is made with mode 0600 and never overwrites one.
- ``import-field`` loads such a ZIP into an empty single-field database at the
  same revision (``public``), in one transaction: the migration to self-hosting
  that ADR-P4-4 describes, without ``pg_dump`` in the image (S21-8).
- ``delete`` drops the schema with everything in it and the registry row, in
  one transaction, and writes the deletion (counts per table, never rows) to
  the hub's audit log.

Every command is written to ``public.atalaia_hub_audit`` with ``--actor`` (by
default the system user) and, where asked, ``--reason``.
"""

from __future__ import annotations

import asyncio
import csv
import getpass
import hashlib
import io
import json
import os
import re
import secrets
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg
from sqlalchemy.engine import make_url

from . import dnsquery, tenant_roles
from .config import MAX_QUOTA, QUOTA_DEFAULTS, quotas_from_env
from .tenancy import (CHALLENGE_PREFIX, COLUMNS, STATUSES, Tenant, TenantError, challenge_name, check_custom_host,
                      check_schema, check_slug, from_row, schema_for)

EXPORT_FORMAT = "atalaia-field-export"
EXPORT_VERSION = 1
ROLE_NAME = re.compile(r"[a-z_][a-z0-9_]{0,62}")
DEFAULT_APP_ROLE = "atalaia_app"
FIELD_TYPES = ("outdoor", "cqb", "indoor")  # as api/fields.py
# Rows the migrations themselves write: an import checks them instead of loading them.
SEEDED_TABLES = frozenset({"roles"})
MAX_EXPORT_MEMBER = 1 << 31  # 2 GiB of CSV per table, a sanity limit on import

EXPORT_README = """An Atalaia site server field export (format atalaia-field-export, version 1).

manifest.json   the field's slug and id, the database revision (Alembic), the time of the
                export and, for each table in load order, its columns, row count and the
                SHA-256 of its file
tables/*.csv    every table of the field, as PostgreSQL's COPY ... CSV HEADER writes it

It holds personal data (accounts, registrations, chrono records) and credential hashes:
keep it as safe as the database itself. To run the field on a server of its own: install
the site server at the same release, let it migrate an empty database, then
    python -m atalaia_server import-field THIS-FILE.zip
(server/docs/DEPLOY.md). Everyone logs in again and enrols TOTP again; platform links
must be set up again.
"""

REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS public.atalaia_tenants (
    slug        text PRIMARY KEY CHECK (slug ~ '^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$'),
    schema_name text NOT NULL UNIQUE CHECK (schema_name ~ '^field_[a-z0-9_]{1,40}$'),
    field_id    uuid NOT NULL UNIQUE,
    status      text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.atalaia_hub_audit (
    id          bigserial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    action      text NOT NULL,
    slug        text,
    schema_name text,
    field_id    uuid,
    actor       text NOT NULL,
    details     jsonb
);
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON public.atalaia_tenants, public.atalaia_hub_audit FROM PUBLIC;
"""

# What later releases added to the registry (PKC-5, PKC-6); idempotent, run by ``init`` and by ``migrate``.
REGISTRY_UPGRADE_DDL = """
ALTER TABLE public.atalaia_tenants
    ADD COLUMN IF NOT EXISTS quotas jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS custom_host text
        CHECK (custom_host IS NULL OR custom_host ~ '^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\\.)+[a-z]([a-z0-9-]{0,61}[a-z0-9])?$'),
    ADD COLUMN IF NOT EXISTS custom_host_status text CHECK (custom_host_status IN ('pending', 'active')),
    ADD COLUMN IF NOT EXISTS custom_host_token text,
    ADD COLUMN IF NOT EXISTS custom_host_verified_at timestamptz,
    ADD COLUMN IF NOT EXISTS role_name text GENERATED ALWAYS AS ('atalaia_t_' || replace(field_id::text, '-', '')) STORED;
CREATE UNIQUE INDEX IF NOT EXISTS atalaia_tenants_custom_host ON public.atalaia_tenants (custom_host);
CREATE UNIQUE INDEX IF NOT EXISTS atalaia_tenants_role_name ON public.atalaia_tenants (role_name);
CREATE TABLE IF NOT EXISTS public.atalaia_quota_hits (
    id          bigserial PRIMARY KEY,
    created_at  timestamptz NOT NULL DEFAULT now(),
    slug        text NOT NULL,
    quota       text NOT NULL,
    limit_value bigint NOT NULL
);
REVOKE ALL ON public.atalaia_quota_hits FROM PUBLIC;
"""

# The hub-level chrono sharing (SVX-2, ADR-P4-4's amendment of 2026-10-28): three tables each tenant fills with
# its own rows only (one row-level policy: ``tenant`` is the schema of the field whose database role runs the
# transaction, ``atalaia_caller_tenant()``, which reads the ``role`` setting that only SET ROLE changes, and not the
# ``atalaia.tenant`` setting any statement could rewrite, S2113-3; ENABLEd, not
# FORCEd, so their owner, which the functions run as, sees every row) and three SECURITY DEFINER functions, the
# only way across: ``atalaia_share_read`` (the other fields' records of the persons the caller is linked to, when
# both are active members and consented) ``atalaia_share_redeem`` (a link code, once) and ``atalaia_share_peers`` (the names of the other fields the
# caller's person is linked at, HLC-2). They read hub tables
# only, never a tenant's schema. Idempotent: run by ``init`` and by ``migrate``.
SHARE_TABLES = ("atalaia_share_members", "atalaia_share_records", "atalaia_share_codes")
SHARE_FUNCTIONS = ("public.atalaia_share_read(uuid[], integer)", "public.atalaia_share_redeem(bytea)",
                   "public.atalaia_share_peers(uuid)")
CALLER_FUNCTION = "public.atalaia_caller_tenant()"
TENANT_FUNCTIONS = SHARE_FUNCTIONS + (CALLER_FUNCTION,)
SHARE_POLICY = "(tenant = atalaia_caller_tenant())"
SHARE_DDL = """
CREATE TABLE IF NOT EXISTS public.atalaia_share_members (
    person_id   uuid NOT NULL,
    tenant      text NOT NULL CHECK (tenant ~ '^field_[a-z0-9_]{1,40}$'),
    active      boolean NOT NULL DEFAULT false,
    field_name  text NOT NULL DEFAULT '',
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (person_id, tenant)
);
CREATE TABLE IF NOT EXISTS public.atalaia_share_records (
    tenant      text NOT NULL,
    person_id   uuid NOT NULL,
    reading_id  uuid NOT NULL,
    taken_at    timestamptz NOT NULL,
    record_json text NOT NULL,
    public_key  text NOT NULL,
    PRIMARY KEY (tenant, reading_id),
    FOREIGN KEY (person_id, tenant) REFERENCES public.atalaia_share_members (person_id, tenant) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS atalaia_share_records_person ON public.atalaia_share_records (person_id, tenant);
CREATE TABLE IF NOT EXISTS public.atalaia_share_codes (
    code_hash   bytea PRIMARY KEY,
    person_id   uuid NOT NULL,
    tenant      text NOT NULL,
    expires_at  timestamptz NOT NULL
);
ALTER TABLE public.atalaia_share_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.atalaia_share_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.atalaia_share_codes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.atalaia_share_members NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.atalaia_share_records NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public.atalaia_share_codes NO FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS atalaia_tenant ON public.atalaia_share_members;
DROP POLICY IF EXISTS atalaia_tenant ON public.atalaia_share_records;
DROP POLICY IF EXISTS atalaia_tenant ON public.atalaia_share_codes;
CREATE OR REPLACE FUNCTION public.atalaia_caller_tenant() RETURNS text
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $fn$
    SELECT t.schema_name FROM public.atalaia_tenants t WHERE t.role_name = current_setting('role', true)
$fn$;
CREATE POLICY atalaia_tenant ON public.atalaia_share_members
    USING (tenant = public.atalaia_caller_tenant()) WITH CHECK (tenant = public.atalaia_caller_tenant());
CREATE POLICY atalaia_tenant ON public.atalaia_share_records
    USING (tenant = public.atalaia_caller_tenant()) WITH CHECK (tenant = public.atalaia_caller_tenant());
CREATE POLICY atalaia_tenant ON public.atalaia_share_codes
    USING (tenant = public.atalaia_caller_tenant()) WITH CHECK (tenant = public.atalaia_caller_tenant());
CREATE OR REPLACE FUNCTION public.atalaia_share_read(p_persons uuid[], p_per_person integer)
RETURNS TABLE (person_id uuid, field_name text, reading_id uuid, taken_at timestamptz, record_json text, public_key text)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $fn$
    SELECT x.person_id, x.field_name, x.reading_id, x.taken_at, x.record_json, x.public_key
    FROM (
        SELECT r.person_id, src.field_name, r.reading_id, r.taken_at, r.record_json, r.public_key,
               row_number() OVER (PARTITION BY r.person_id ORDER BY r.taken_at DESC, r.reading_id DESC) AS n
        FROM public.atalaia_share_members me
        JOIN public.atalaia_share_records r ON r.person_id = me.person_id AND r.tenant <> me.tenant
        JOIN public.atalaia_share_members src ON src.person_id = r.person_id AND src.tenant = r.tenant
        JOIN public.atalaia_tenants t ON t.schema_name = r.tenant
        WHERE me.tenant = public.atalaia_caller_tenant() AND me.active AND src.active
          AND t.status = 'active' AND me.person_id = ANY (p_persons)
    ) x
    WHERE x.n <= p_per_person
$fn$;
CREATE OR REPLACE FUNCTION public.atalaia_share_redeem(p_hash bytea) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
DECLARE
    me  text := public.atalaia_caller_tenant();
    pid uuid;
BEGIN
    IF me IS NULL THEN
        RETURN NULL;
    END IF;
    DELETE FROM public.atalaia_share_codes WHERE expires_at < now();
    DELETE FROM public.atalaia_share_codes WHERE code_hash = p_hash AND tenant <> me RETURNING person_id INTO pid;
    RETURN pid;
END
$fn$;
-- HLC-2: the other fields the caller's person is linked at (name, whether sharing is on there, since when), only
-- when the caller is itself a member for that person; nothing of what those fields hold.
CREATE OR REPLACE FUNCTION public.atalaia_share_peers(p_person uuid)
RETURNS TABLE (field_name text, active boolean, updated_at timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog AS $fn$
    SELECT src.field_name, src.active, src.updated_at
    FROM public.atalaia_share_members me
    JOIN public.atalaia_share_members src ON src.person_id = me.person_id AND src.tenant <> me.tenant
    JOIN public.atalaia_tenants t ON t.schema_name = src.tenant
    WHERE me.tenant = public.atalaia_caller_tenant() AND me.person_id = p_person AND t.status = 'active'
    ORDER BY src.updated_at, src.field_name
$fn$;
"""


class HostedError(Exception):
    """A problem to report in one line (the command exits 1)."""


def dsn(url: str) -> str:
    """asyncpg's DSN for a SQLAlchemy ``postgresql+asyncpg://`` URL."""
    return make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)


def check_role(name: str) -> str:
    if not ROLE_NAME.fullmatch(name or ""):
        raise HostedError(f"not a role name: {name!r} (lower-case letters, digits and _)")
    return name


def default_actor() -> str:
    try:
        return f"system:{getpass.getuser()}"
    except Exception:  # noqa: BLE001  (no user name in a container: still say where it came from)
        return "system:unknown"


async def _connect(url: str) -> asyncpg.Connection:
    return await asyncpg.connect(dsn(url), timeout=10)


async def _audit(conn: asyncpg.Connection, action: str, actor: str, slug: Optional[str] = None,
                 schema: Optional[str] = None, field_id: Optional[uuid.UUID] = None,
                 details: Optional[dict[str, Any]] = None) -> None:
    await conn.execute("INSERT INTO public.atalaia_hub_audit (action, slug, schema_name, field_id, actor, details) "
                       "VALUES ($1, $2, $3, $4, $5, $6::jsonb)", action, slug, schema, field_id, actor,
                       json.dumps(details) if details is not None else None)


async def _registry_exists(conn: asyncpg.Connection) -> bool:
    return bool(await conn.fetchval("SELECT to_regclass('public.atalaia_tenants') IS NOT NULL"))


async def _need_registry(conn: asyncpg.Connection) -> None:
    if not await _registry_exists(conn):
        raise HostedError("this database is not a hosted hub yet: run python -m atalaia_server hosted init")


async def _check_app_role(conn: asyncpg.Connection, app_role: str) -> None:
    row = await conn.fetchrow("SELECT rolsuper, rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = $1", app_role)
    if row is None:
        raise HostedError(f"the server's role {app_role!r} does not exist (CREATE ROLE {app_role} LOGIN "
                          "PASSWORD '...' NOSUPERUSER NOBYPASSRLS; server/docs/DEPLOY.md)")
    if row["rolsuper"] or row["rolbypassrls"]:
        raise HostedError(f"the server's role {app_role!r} is a superuser or has BYPASSRLS: row-level security "
                          "would not apply to it")
    if app_role == await conn.fetchval("SELECT current_user"):
        raise HostedError("the server's role must not be the owner role these commands run as")
    if not await conn.fetchval("SELECT rolcreaterole FROM pg_roles WHERE rolname = current_user"):
        raise HostedError("the owner role must have CREATEROLE: every field has a database role of its own, made "
                          "and dropped by these commands (ALTER ROLE <owner> CREATEROLE; server/hosted-roles.sh "
                          "does it; decisions S2113-1)")


async def _tenant(conn: asyncpg.Connection, slug: str, lock: bool = False) -> Tenant:
    await _need_registry(conn)
    row = await conn.fetchrow(f"SELECT {COLUMNS} FROM public.atalaia_tenants WHERE slug = $1"
                              + (" FOR UPDATE" if lock else ""), check_slug(slug))
    if row is None:
        raise HostedError(f"no field {slug!r} on this hub")
    return from_row(row)


def _q(identifier: str) -> str:
    """A quoted identifier; only ever given names that passed a strict pattern or came from the catalogue."""
    return '"' + identifier.replace('"', '""') + '"'


async def _tables(conn: asyncpg.Connection, schema: str) -> list[str]:
    """The schema's tables, parents before children (foreign keys inside the schema), alembic_version last."""
    names = [r["tablename"] for r in await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = $1 AND tablename <> 'alembic_version' ORDER BY tablename",
        schema)]
    edges = await conn.fetch(
        "SELECT c.conrelid::regclass::text AS child, c.confrelid::regclass::text AS parent FROM pg_constraint c "
        "JOIN pg_namespace n ON n.oid = c.connamespace WHERE c.contype = 'f' AND n.nspname = $1", schema)
    plain = {_strip(name, schema) for name in names}
    parents: dict[str, set[str]] = {name: set() for name in plain}
    for e in edges:
        child, parent = _strip(e["child"], schema), _strip(e["parent"], schema)
        if child in parents and parent in plain and parent != child:
            parents[child].add(parent)
    ordered: list[str] = []
    done: set[str] = set()
    while len(ordered) < len(plain):
        ready = sorted(t for t in plain - done if parents[t] <= done)
        if not ready:
            raise HostedError(f"the foreign keys of {schema} form a cycle: {sorted(plain - done)}")
        ordered.extend(ready)
        done.update(ready)
    return ordered


def _strip(regclass: str, schema: str) -> str:
    """``schema.table`` (as regclass prints a table off the path) to ``table``."""
    name = regclass
    for prefix in (f"{schema}.", f"{_q(schema)}."):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name.strip('"')


async def apply_security(conn: asyncpg.Connection, schema: str, app_role: str, role: str) -> int:
    """The grants and the row-level security of one tenant's schema; returns the tables covered.

    ``role`` is the field's own database role (``tenant_roles.role_for``; made here if missing, no login). It alone
    gets USAGE on the schema, SELECT/INSERT/UPDATE/DELETE on its tables (never TRUNCATE, which row-level security
    does not cover, nor REFERENCES or TRIGGER) and its sequences, and its rows of the hub's sharing tables and the
    functions over them; nothing on ``alembic_version``. The server's login role ``app_role`` gets *no* grant on the
    schema (any it had from an older release is revoked) and only the right to ``SET ROLE`` to ``role`` (``WITH
    INHERIT FALSE``): a connection can reach one field's rows only, whatever it sets. Every table also gets ENABLE
    and FORCE ROW LEVEL SECURITY and the one policy ``atalaia_tenant``: rows are seen and written only while
    ``atalaia.tenant`` is this schema's name (defence in depth, the operator's own commands set it)."""
    check_schema(schema)
    check_role(app_role)
    tenant_roles.check_tenant_role(role)
    s, app, own = _q(schema), _q(app_role), _q(role)
    await conn.execute(tenant_roles.create_sql(role))
    await conn.execute(f"ALTER ROLE {own} NOLOGIN")  # the one attribute an owner role with CREATEROLE may set back
    await conn.execute(f"GRANT {own} TO {app} WITH INHERIT FALSE, SET TRUE")
    await conn.execute(f"REVOKE ALL ON SCHEMA {s} FROM PUBLIC; REVOKE ALL ON SCHEMA {s} FROM {app}; "
                       f"GRANT USAGE ON SCHEMA {s} TO {own}")
    tables = await _tables(conn, schema)
    literal = "'" + schema + "'"  # schema passed check_schema: [a-z0-9_] only
    for table in tables:
        t = f"{s}.{_q(table)}"
        await conn.execute(
            f"REVOKE ALL ON {t} FROM PUBLIC; REVOKE ALL ON {t} FROM {app}; REVOKE ALL ON {t} FROM {own}; "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {own}; "
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY; "
            f"DROP POLICY IF EXISTS atalaia_tenant ON {t}; "
            f"CREATE POLICY atalaia_tenant ON {t} USING (current_setting('atalaia.tenant', true) = {literal}) "
            f"WITH CHECK (current_setting('atalaia.tenant', true) = {literal})")
    if await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.alembic_version"):
        await conn.execute(f"REVOKE ALL ON {s}.alembic_version FROM PUBLIC; REVOKE ALL ON {s}.alembic_version "
                           f"FROM {app}; REVOKE ALL ON {s}.alembic_version FROM {own}")
    await conn.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA {s} FROM {app}; "
                       f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {s} TO {own}")
    # The hub's sharing (SVX-2): the field's role runs it, over the rows its role's policy lets it see.
    if await conn.fetchval("SELECT to_regclass('public.atalaia_share_members') IS NOT NULL"):
        await conn.execute(
            f"GRANT USAGE ON SCHEMA public TO {own}; "
            f"REVOKE ALL ON {', '.join('public.' + t for t in SHARE_TABLES)} FROM {own}; "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON public.atalaia_share_members, public.atalaia_share_records "
            f"TO {own}; "
            f"GRANT SELECT, INSERT, DELETE ON public.atalaia_share_codes TO {own}; "
            f"GRANT EXECUTE ON FUNCTION {', '.join(TENANT_FUNCTIONS)} TO {own}")
    return len(tables)


async def _scope(conn: asyncpg.Connection, schema: str) -> None:
    """Inside a transaction: this tenant's path and setting, transaction-local (FORCE ROW LEVEL SECURITY
    applies to the owner too, unless it is a superuser)."""
    await conn.execute("SELECT set_config('search_path', $1, true), set_config('atalaia.tenant', $1, true)", schema)


# init ---------------------------------------------------------------------------------------------

async def init_hub(url: str, app_role: str = DEFAULT_APP_ROLE, actor: Optional[str] = None) -> None:
    check_role(app_role)
    conn = await _connect(url)
    try:
        await _check_app_role(conn, app_role)
        if await conn.fetchval("SELECT to_regclass('public.fields') IS NOT NULL"):
            raise HostedError("this database's public schema holds a single-field server's tables: a hosted hub "
                              "needs a database of its own")
        async with conn.transaction():
            await conn.execute(REGISTRY_DDL)
            await _upgrade_registry(conn, app_role)
            await _audit(conn, "hub_init", actor or default_actor(), details={"app_role": app_role})
    finally:
        await conn.close()


async def _upgrade_registry(conn: asyncpg.Connection, app_role: str) -> None:
    """The registry's later columns and tables, and the server role's exact rights on the hub's tables: it reads the
    registry, only adds to the quota inbox, and touches nothing else (the sharing's tables and functions belong
    to the fields' own roles, ``apply_security``)."""
    role = _q(check_role(app_role))
    await conn.execute(REGISTRY_UPGRADE_DDL)
    await conn.execute(
        f"GRANT USAGE ON SCHEMA public TO {role}; "
        f"REVOKE ALL ON public.atalaia_tenants, public.atalaia_quota_hits, public.atalaia_hub_audit FROM {role}; "
        f"GRANT SELECT ON public.atalaia_tenants TO {role}; "
        f"GRANT INSERT ON public.atalaia_quota_hits TO {role}; "
        f"GRANT USAGE ON SEQUENCE public.atalaia_quota_hits_id_seq TO {role}")
    await conn.execute(SHARE_DDL)
    await conn.execute(
        f"REVOKE ALL ON {', '.join('public.' + t for t in SHARE_TABLES)} FROM PUBLIC, {role}; "
        f"REVOKE ALL ON FUNCTION {', '.join(TENANT_FUNCTIONS)} FROM PUBLIC, {role}")  # the fields' roles get them


async def upgrade_hub(url: str, app_role: str = DEFAULT_APP_ROLE) -> None:
    """Brings the registry of a hub made by an older release up to date (``migrate`` does this first)."""
    conn = await _connect(url)
    try:
        await _need_registry(conn)
        await _check_app_role(conn, app_role)
        async with conn.transaction():
            await _upgrade_registry(conn, app_role)
    finally:
        await conn.close()


# create / migrate -----------------------------------------------------------------------------------

def alembic_config(url: str, schema: str) -> Any:
    from alembic.config import Config  # only the commands need Alembic

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.attributes["database_url"] = url
    cfg.attributes["schema"] = check_schema(schema)
    cfg.attributes["skip_logging"] = True
    return cfg


def migrate_schema(url: str, schema: str) -> None:
    """Every migration, in one tenant's schema (synchronous: Alembic's env runs its own event loop)."""
    from alembic import command

    command.upgrade(alembic_config(url, schema), "head")


def create_tenant(url: str, slug: str, name: str, field_type: str = "outdoor", timezone_name: str = "Europe/Lisbon",
                  app_role: str = DEFAULT_APP_ROLE, actor: Optional[str] = None) -> Tenant:
    """A new tenant with its schema, its migrations, its field and its security, or nothing at all."""
    schema = schema_for(slug)
    check_role(app_role)
    name = name.strip()
    if not name or len(name) > 128:
        raise HostedError("the field's name must be 1-128 characters")
    if field_type not in FIELD_TYPES:
        raise HostedError(f"the field type must be one of {', '.join(FIELD_TYPES)}")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise HostedError(f"not a time zone: {timezone_name!r}") from None
    asyncio.run(_create_schema(url, slug, schema, app_role))
    try:
        migrate_schema(url, schema)
        return asyncio.run(_finish_create(url, slug, schema, name, field_type, timezone_name, app_role,
                                          actor or default_actor()))
    except BaseException:
        asyncio.run(_drop_unregistered(url, slug, schema))
        raise


async def _create_schema(url: str, slug: str, schema: str, app_role: str) -> None:
    conn = await _connect(url)
    try:
        await _need_registry(conn)
        await _check_app_role(conn, app_role)
        if await conn.fetchval("SELECT 1 FROM public.atalaia_tenants WHERE slug = $1 OR schema_name = $2",
                               slug, schema):
            raise HostedError(f"the field {slug!r} already exists on this hub")
        if await conn.fetchval("SELECT 1 FROM pg_namespace WHERE nspname = $1", schema):
            raise HostedError(f"the schema {schema} already exists but is not registered: check it, then drop it")
        await conn.execute(f"CREATE SCHEMA {_q(schema)}")
    finally:
        await conn.close()


async def _finish_create(url: str, slug: str, schema: str, name: str, field_type: str, timezone_name: str,
                         app_role: str, actor: str) -> Tenant:
    conn = await _connect(url)
    try:
        async with conn.transaction():
            await _scope(conn, schema)
            try:
                field_id = await conn.fetchval(
                    f"INSERT INTO {_q(schema)}.fields (name, slug, field_type, timezone) VALUES ($1, $2, $3, $4) "
                    "RETURNING id", name, slug, field_type, timezone_name)
            except asyncpg.PostgresError as e:
                raise HostedError(f"the field could not be made: {e}") from None
            tables = await apply_security(conn, schema, app_role, tenant_roles.role_for(field_id))
            await conn.execute("INSERT INTO public.atalaia_tenants (slug, schema_name, field_id) VALUES ($1, $2, $3)",
                               slug, schema, field_id)
            revision = await conn.fetchval(f"SELECT version_num FROM {_q(schema)}.alembic_version")
            await _audit(conn, "tenant_create", actor, slug, schema, field_id,
                         {"tables": tables, "revision": revision, "app_role": app_role,
                                                "role": tenant_roles.role_for(field_id)})
        return Tenant(slug=slug, schema=schema, field_id=field_id)
    finally:
        await conn.close()


async def _drop_unregistered(url: str, slug: str, schema: str) -> None:
    conn = await _connect(url)
    try:
        if not await conn.fetchval("SELECT 1 FROM public.atalaia_tenants WHERE schema_name = $1", schema):
            await conn.execute(f"DROP SCHEMA IF EXISTS {_q(schema)} CASCADE")
    finally:
        await conn.close()


async def list_tenants(url: str) -> list[dict[str, Any]]:
    conn = await _connect(url)
    try:
        await _need_registry(conn)
        rows = await conn.fetch("SELECT slug, schema_name, field_id, status, created_at, quotas, custom_host, "
                                "custom_host_status FROM public.atalaia_tenants ORDER BY slug")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def migrate_all(url: str, app_role: str = DEFAULT_APP_ROLE, actor: Optional[str] = None) -> list[str]:
    """Every tenant (active or suspended) to the newest revision, grants and policies again; the slugs done."""
    check_role(app_role)
    asyncio.run(upgrade_hub(url, app_role))
    tenants = asyncio.run(list_tenants(url))
    done = []
    for row in tenants:
        schema = check_schema(row["schema_name"])
        migrate_schema(url, schema)
        asyncio.run(_after_migrate(url, row["slug"], schema, row["field_id"], app_role, actor or default_actor()))
        done.append(row["slug"])
    return done


async def _after_migrate(url: str, slug: str, schema: str, field_id: uuid.UUID, app_role: str, actor: str) -> None:
    conn = await _connect(url)
    try:
        await _check_app_role(conn, app_role)
        async with conn.transaction():
            tables = await apply_security(conn, schema, app_role, tenant_roles.role_for(field_id))
            revision = await conn.fetchval(f"SELECT version_num FROM {_q(schema)}.alembic_version")
            await _audit(conn, "tenant_migrate", actor, slug, schema, field_id, {"tables": tables,
                                                                                  "revision": revision})
    finally:
        await conn.close()


# check --------------------------------------------------------------------------------------------

TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
SERVER_TABLE_PRIVILEGES = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})


@dataclass
class HubCheck:
    fields: int
    tables: int
    problems: list[str]
    quota_hits: int = 0  # notes of refused quotas waiting for ``hosted quota-hits``


# The one function that could change a connection's role from inside a statement: only the server's login role and
# the owner may call it (server/hosted-roles.sh revokes it from PUBLIC, as the superuser: pg_catalog is not the owner's).
SET_CONFIG = "pg_catalog.set_config(text, text, boolean)"
SET_CONFIG_PUBLIC = (f"SELECT EXISTS (SELECT 1 FROM pg_proc p, aclexplode(coalesce(p.proacl, acldefault('f', "
                     f"p.proowner))) a WHERE p.oid = '{SET_CONFIG}'::regprocedure AND a.grantee = 0 "
                     "AND a.privilege_type = 'EXECUTE')")
SHARE_PRIVILEGES = {"atalaia_share_members": {"SELECT", "INSERT", "UPDATE", "DELETE"},
                    "atalaia_share_records": {"SELECT", "INSERT", "UPDATE", "DELETE"},
                    "atalaia_share_codes": {"SELECT", "INSERT", "DELETE"}}


def _same_policy(found: list[str], expected: str) -> bool:
    """The catalogue prints a qualified name as the checking session's path allows: compare without ``public.``."""
    return [f.replace("public.", "") for f in found] == [expected.replace("public.", "")]


async def _check_share(conn: asyncpg.Connection, app_role: str, roles: list[str], me: str,
                       problems: list[str]) -> None:
    """The hub-level chrono sharing's tables and functions (SVX-2): owned by the owner role, row-level security on
    and not forced, exactly the one policy (the caller's own rows, by the field's database role), each field's role
    with its exact privileges and the server's login role with none, and each function a SECURITY DEFINER of the
    owner with a fixed search path that only the fields' roles may run."""
    if not await conn.fetchval("SELECT to_regclass('public.atalaia_share_members') IS NOT NULL"):
        problems.append("the registry is of an older release (no public.atalaia_share_members): run hosted migrate")
        return
    for name, allowed in SHARE_PRIVILEGES.items():
        table = f"public.{name}"
        row = await conn.fetchrow(
            "SELECT c.relrowsecurity, c.relforcerowsecurity, pg_get_userbyid(c.relowner) AS owner, "
            "(SELECT array_agg(p.polname || '|' || p.polcmd::text || '|' || p.polpermissive::text || '|' "
            "|| coalesce(pg_get_expr(p.polqual, p.polrelid), '') || '|' "
            "|| coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') || '|' || p.polroles::text) "
            "FROM pg_policy p WHERE p.polrelid = c.oid) AS policies FROM pg_class c WHERE c.oid = $1::regclass", table)
        if row["owner"] != me:
            problems.append(f"{table} is owned by {row['owner']}, not {me}")
        if not row["relrowsecurity"]:
            problems.append(f"{table}: row-level security is not enabled")
        if row["relforcerowsecurity"]:
            problems.append(f"{table}: row-level security is forced (the sharing functions would read nothing)")
        if not _same_policy(list(row["policies"] or []),
                            f"atalaia_tenant|*|true|{SHARE_POLICY}|{SHARE_POLICY}|{{0}}"):
            problems.append(f"{table}: the policies are not exactly atalaia_tenant for the caller's own rows")
        have = {p for p in TABLE_PRIVILEGES
                if await conn.fetchval("SELECT has_table_privilege($1, $2, $3)", app_role, table, p)}
        if have:
            problems.append(f"{app_role} has {sorted(have)} on {table}, not nothing (only the fields' roles use it)")
        for role in roles:
            have = {p for p in TABLE_PRIVILEGES
                    if await conn.fetchval("SELECT has_table_privilege($1, $2, $3)", role, table, p)}
            if have != allowed:
                problems.append(f"{role} has {sorted(have)} on {table}, not {sorted(allowed)}")
    for signature in TENANT_FUNCTIONS:
        row = await conn.fetchrow(
            "SELECT p.prosecdef, pg_get_userbyid(p.proowner) AS owner, p.proconfig, "
            "EXISTS (SELECT 1 FROM aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a "
            "        WHERE a.grantee = 0 AND a.privilege_type = 'EXECUTE') AS everyone "
            "FROM pg_proc p WHERE p.oid = to_regprocedure($1)", signature)
        if row is None:
            problems.append(f"{signature} is missing: run hosted migrate")
            continue
        if not row["prosecdef"] or row["owner"] != me:
            problems.append(f"{signature} is not a SECURITY DEFINER function of {me}")
        if list(row["proconfig"] or []) != ["search_path=pg_catalog"]:
            problems.append(f"{signature} has no fixed search_path of pg_catalog")
        if row["everyone"]:
            problems.append(f"{signature} can be run by anyone, not only the fields' roles")
        if await conn.fetchval("SELECT has_function_privilege($1, to_regprocedure($2), 'EXECUTE')",
                               app_role, signature):
            problems.append(f"{app_role} can run {signature}: only the fields' roles may")
        for role in roles:
            if not await conn.fetchval("SELECT has_function_privilege($1, to_regprocedure($2), 'EXECUTE')",
                                       role, signature):
                problems.append(f"{role} cannot run {signature}")


async def _check_tenant_role(conn: asyncpg.Connection, app_role: str, role: str, schema: str,
                             problems: list[str]) -> None:
    """One field's database role: it exists, cannot log in, holds no attribute that could bypass the isolation,
    owns nothing, and the server's login role may SET ROLE to it without inheriting its grants."""
    row = await conn.fetchrow(
        "SELECT oid, rolsuper, rolcanlogin, rolbypassrls, rolcreaterole, rolcreatedb, rolreplication, rolinherit "
        "FROM pg_roles WHERE rolname = $1", role)
    if row is None:
        problems.append(f"{schema}: the database role {role} is missing: run hosted migrate")
        return
    bad = [n for n in ("rolsuper", "rolcanlogin", "rolbypassrls", "rolcreaterole", "rolcreatedb", "rolreplication")
           if row[n]]
    if bad:
        problems.append(f"{role} has {', '.join(bad)}")
    owned = await conn.fetchval("SELECT count(*) FROM pg_class WHERE relowner = $1", row["oid"]) \
        + await conn.fetchval("SELECT count(*) FROM pg_namespace WHERE nspowner = $1", row["oid"])
    if owned:
        problems.append(f"{role} owns {owned} schemas or relations")
    member = await conn.fetchrow(
        "SELECT m.set_option, m.inherit_option FROM pg_auth_members m WHERE m.roleid = $1 "
        "AND m.member = (SELECT oid FROM pg_roles WHERE rolname = $2)", row["oid"], app_role)
    if member is None or not member["set_option"]:
        problems.append(f"{app_role} cannot SET ROLE to {role}: run hosted migrate")
    elif member["inherit_option"]:
        problems.append(f"{app_role} inherits the grants of {role} (it must only SET ROLE to it)")
    others = await conn.fetchval(
        "SELECT count(*) FROM pg_auth_members WHERE roleid = $1 AND member <> (SELECT oid FROM pg_roles WHERE "
        "rolname = $2) AND member NOT IN (SELECT oid FROM pg_roles WHERE rolname = current_user)",
        row["oid"], app_role)
    if others:
        problems.append(f"{role} has {others} other members")


async def check_hub(url: str, app_role: str = DEFAULT_APP_ROLE) -> HubCheck:
    """What keeps the fields apart, checked as the owner role (``hosted check``; after a restore above all).

    Every registered field has its schema and every ``field_*`` schema is registered; the owner role owns
    every schema and table; every table has ENABLE and FORCE ROW LEVEL SECURITY and exactly one policy,
    ``atalaia_tenant`` for that schema; the server's role is no superuser, has no BYPASSRLS, owns nothing, has
    *no* privilege on any field's schema or tables or on the sharing's tables and functions (it may only SET ROLE
    to a field's role, without inheriting it), only SELECT on the registry, only INSERT on the quota inbox and
    nothing on the hub's audit log; each field has a database role (``_check_tenant_role``) with exactly SELECT,
    INSERT, UPDATE and DELETE on its tables, nothing on ``alembic_version`` and nothing on another field's; and
    the sharing's tables and functions (``_check_share``). Reads only; returns the problems found (and how many
    quota notes wait)."""
    check_role(app_role)
    conn = await _connect(url)
    try:
        await _need_registry(conn)
        problems: list[str] = []
        me = await conn.fetchval("SELECT current_user")
        role = await conn.fetchrow("SELECT oid, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = $1", app_role)
        if role is None:
            raise HostedError(f"the server's role {app_role!r} does not exist")
        if role["rolsuper"] or role["rolbypassrls"]:
            problems.append(f"{app_role} is a superuser or has BYPASSRLS")
        if app_role == me:  # the server's role has no right to look into the fields: nothing more can be checked
            return HubCheck(fields=0, tables=0, problems=["the check must run as the owner role, not the server's"])
        owned = await conn.fetchval("SELECT count(*) FROM pg_class WHERE relowner = $1", role["oid"]) \
            + await conn.fetchval("SELECT count(*) FROM pg_namespace WHERE nspowner = $1", role["oid"])
        if owned:
            problems.append(f"{app_role} owns {owned} schemas or relations")
        if await conn.fetchval(SET_CONFIG_PUBLIC):
            problems.append("pg_catalog.set_config can be called by every role: a field's role could switch to "
                            "another field's (run server/hosted-roles.sh as the superuser)")
        for who in (app_role, me):
            if not await conn.fetchval("SELECT has_function_privilege($1, $2::regprocedure, 'EXECUTE')", who,
                                       SET_CONFIG):
                problems.append(f"{who} cannot call pg_catalog.set_config (run server/hosted-roles.sh as the "
                                "superuser)")
        if not await conn.fetchval("SELECT to_regclass('public.atalaia_quota_hits') IS NOT NULL"):
            problems.append("the registry is of an older release (no public.atalaia_quota_hits): run hosted migrate")
        for table, allowed in (("public.atalaia_tenants", {"SELECT"}), ("public.atalaia_hub_audit", set()),
                               ("public.atalaia_quota_hits", {"INSERT"})):
            if not await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", table):
                continue
            have = {p for p in TABLE_PRIVILEGES
                    if await conn.fetchval("SELECT has_table_privilege($1, $2, $3)", app_role, table, p)}
            if have != allowed:
                problems.append(f"{app_role} has {sorted(have)} on {table}, not {sorted(allowed)}")
        registered = {r["schema_name"]: r["slug"] for r in await conn.fetch(
            "SELECT slug, schema_name FROM public.atalaia_tenants")}
        role_of = {r["schema_name"]: r["role_name"] for r in await conn.fetch(
            "SELECT schema_name, role_name FROM public.atalaia_tenants")}
        existing = {r["rolname"] for r in await conn.fetch("SELECT rolname FROM pg_roles WHERE rolname = ANY($1)",
                                                          list(role_of.values()))}
        await _check_share(conn, app_role, sorted(existing), me, problems)
        present = {r["nspname"]: r["owner"] for r in await conn.fetch(
            r"SELECT nspname, pg_get_userbyid(nspowner) AS owner FROM pg_namespace WHERE nspname LIKE 'field\_%'")}
        for schema in sorted(set(registered) - set(present)):
            problems.append(f"the field {registered[schema]} is registered but its schema {schema} is missing")
        for schema in sorted(set(present) - set(registered)):
            problems.append(f"the schema {schema} is not registered")
        tables = 0
        for schema in sorted(set(registered) & set(present)):
            check_schema(schema)
            if present[schema] != me:
                problems.append(f"{schema} is owned by {present[schema]}, not {me}")
            role = role_of[schema]
            await _check_tenant_role(conn, app_role, role, schema, problems)
            if role not in existing:
                continue  # said above: the rest cannot be told without it
            if await conn.fetchval("SELECT has_function_privilege($1, $2::regprocedure, 'EXECUTE')", role,
                                   SET_CONFIG):
                problems.append(f"{role} can call pg_catalog.set_config: it could switch to another field's role")
            if await conn.fetchval("SELECT has_schema_privilege($1, $2, 'USAGE, CREATE')", app_role, schema):
                problems.append(f"{app_role} has privileges on {schema} itself: only {role} may")
            if not await conn.fetchval("SELECT has_schema_privilege($1, $2, 'USAGE')", role, schema):
                problems.append(f"{role} has no USAGE on {schema}")
            for other_schema, other_role in role_of.items():
                if other_schema != schema and other_role in existing and await conn.fetchval(
                        "SELECT has_schema_privilege($1, $2, 'USAGE, CREATE')", other_role, schema):
                    problems.append(f"{other_role} has privileges on {schema}, another field's")
            expected = f"(current_setting('atalaia.tenant'::text, true) = '{schema}'::text)"
            rows = await conn.fetch(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, pg_get_userbyid(c.relowner) AS owner, "
                "(SELECT array_agg(p.polname || '|' || p.polcmd::text || '|' || p.polpermissive::text || '|' "
                "|| coalesce(pg_get_expr(p.polqual, p.polrelid), '') || '|' "
                "|| coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') || '|' || p.polroles::text) "
                "FROM pg_policy p WHERE p.polrelid = c.oid) AS policies "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = $1 AND c.relkind IN ('r', 'p') ORDER BY c.relname", schema)
            for r in rows:
                name, qualified = r["relname"], f"{schema}.{r['relname']}"
                if r["owner"] != me:
                    problems.append(f"{qualified} is owned by {r['owner']}, not {me}")
                regular = f"{_q(schema)}.{_q(name)}"
                theirs = {p for p in TABLE_PRIVILEGES if await conn.fetchval(
                    "SELECT has_table_privilege($1, $2, $3)", app_role, regular, p)}
                have = {p for p in TABLE_PRIVILEGES if await conn.fetchval(
                    "SELECT has_table_privilege($1, $2, $3)", role, regular, p)}
                if theirs:
                    problems.append(f"{app_role} has {sorted(theirs)} on {qualified}, not nothing: only {role} may")
                if name == "alembic_version":
                    if have:
                        problems.append(f"{role} has {sorted(have)} on {qualified}")
                    continue
                tables += 1
                if not (r["relrowsecurity"] and r["relforcerowsecurity"]):
                    problems.append(f"{qualified}: row-level security is not enabled and forced")
                if have != SERVER_TABLE_PRIVILEGES:
                    problems.append(f"{role} has {sorted(have)} on {qualified}, not SELECT, INSERT, UPDATE, "
                                    "DELETE")
                if list(r["policies"] or []) != [f"atalaia_tenant|*|true|{expected}|{expected}|{{0}}"]:
                    problems.append(f"{qualified}: the policies are not exactly atalaia_tenant for {schema}")
        waiting = 0
        try:
            if await conn.fetchval("SELECT to_regclass('public.atalaia_quota_hits') IS NOT NULL"):
                waiting = int(await conn.fetchval("SELECT count(*) FROM public.atalaia_quota_hits"))
        except asyncpg.InsufficientPrivilegeError:
            pass  # run as the wrong role (the check says so): it cannot read the inbox
        return HubCheck(fields=len(registered), tables=tables, problems=problems, quota_hits=waiting)
    finally:
        await conn.close()


# suspend / resume ---------------------------------------------------------------------------------

async def set_status(url: str, slug: str, status: str, reason: str, actor: Optional[str] = None) -> None:
    if status not in STATUSES:
        raise HostedError(f"status must be one of {', '.join(STATUSES)}")
    conn = await _connect(url)
    try:
        async with conn.transaction():
            tenant = await _tenant(conn, slug, lock=True)
            await conn.execute("UPDATE public.atalaia_tenants SET status = $2, updated_at = now() WHERE slug = $1",
                               tenant.slug, status)
            await _audit(conn, "tenant_suspend" if status == "suspended" else "tenant_resume",
                         actor or default_actor(), tenant.slug, tenant.schema, tenant.field_id, {"reason": reason})
    finally:
        await conn.close()


# quotas -------------------------------------------------------------------------------------------

def check_quota_value(name: str, value: str) -> Optional[int]:
    """``--NAME VALUE``: a whole number of 1 or more, ``off`` (0: no limit) or ``default`` (None: the hub's own)."""
    if name not in QUOTA_DEFAULTS:
        raise HostedError(f"unknown quota {name!r} (known: {', '.join(QUOTA_DEFAULTS)})")
    word = value.strip().lower()
    if word == "default":
        return None
    if word == "off":
        return 0
    if not word.isdigit() or not 1 <= int(word) <= MAX_QUOTA:
        raise HostedError(f"a quota is a whole number from 1 to {MAX_QUOTA}, off or default, not {value!r}")
    return int(word)


async def set_quota(url: str, slug: str, name: str, value: str, reason: str,
                    actor: Optional[str] = None) -> dict[str, Any]:
    """Gives one field its own limit on one resource, over the hub's; returns {old, new} (None: the hub's own)."""
    new = check_quota_value(name, value)
    if not reason.strip():
        raise HostedError("--reason is required (who asked, or why)")
    conn = await _connect(url)
    try:
        async with conn.transaction():
            tenant = await _tenant(conn, slug, lock=True)
            quotas = dict(tenant.quotas)
            old = quotas.get(name)
            if new is None:
                quotas.pop(name, None)
            else:
                quotas[name] = new
            await conn.execute("UPDATE public.atalaia_tenants SET quotas = $2::jsonb, updated_at = now() "
                               "WHERE slug = $1", tenant.slug, json.dumps(quotas, sort_keys=True))
            await _audit(conn, "tenant_quota", actor or default_actor(), tenant.slug, tenant.schema, tenant.field_id,
                         {"quota": name, "old": old, "new": new, "reason": reason})
        return {"old": old, "new": new}
    finally:
        await conn.close()


_COUNTS = {
    "accounts": "SELECT count(*) FROM users",
    "scheduled_games": "SELECT count(*) FROM scheduled_games",
    "registrations": "SELECT count(*) FROM game_registrations",
    "games": "SELECT count(*) FROM games",
    "atak_certs": "SELECT count(*) FROM atak_certs WHERE revoked_at IS NULL AND not_after > now()",
}


async def usage(url: str, slug: Optional[str] = None,
                env: Optional[dict[str, str]] = None) -> list[dict[str, Any]]:
    """For each field (or one): what it uses against its effective limits (the hub's environment, then its own
    overrides). ``streams`` are open sockets of the running server, which this command cannot see (``None``)."""
    base = quotas_from_env(os.environ if env is None else env)
    conn = await _connect(url)
    try:
        await _need_registry(conn)
        rows = [await _tenant(conn, slug)] if slug else [from_row(r) for r in await conn.fetch(
            f"SELECT {COLUMNS} FROM public.atalaia_tenants ORDER BY slug")]
        out = []
        for tenant in rows:
            limits = {**base, **tenant.quotas}
            used: dict[str, Optional[int]] = {}
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                await _scope(conn, tenant.schema)
                for name, query in _COUNTS.items():
                    used[name] = int(await conn.fetchval(query))
                size = await conn.fetchval(
                    "SELECT coalesce(sum(pg_total_relation_size(c.oid)), 0) FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = $1 AND c.relkind IN ('r', 'm', 't')",
                    tenant.schema)
                used["stored_mb"] = -(-int(size) // (1024 * 1024))
            used["streams"] = None
            out.append({"slug": tenant.slug, "status": tenant.status,
                        "quotas": [{"name": n, "used": used[n], "limit": limits[n] or None,
                                    "own": n in tenant.quotas} for n in QUOTA_DEFAULTS]})
        return out
    finally:
        await conn.close()


async def collect_quota_hits(url: str, actor: Optional[str] = None) -> list[dict[str, Any]]:
    """The notes the server left for refused quotas, grouped per field and quota (count, first and last time), moved
    into the hub's audit log (``quota_hit``) in one transaction; returns the groups."""
    conn = await _connect(url)
    try:
        await _need_registry(conn)
        async with conn.transaction():
            rows = await conn.fetch(
                "DELETE FROM public.atalaia_quota_hits RETURNING slug, quota, limit_value, created_at")
            groups: dict[tuple[str, str], dict[str, Any]] = {}
            for r in sorted(rows, key=lambda r: r["created_at"]):
                g = groups.setdefault((r["slug"], r["quota"]), {"slug": r["slug"], "quota": r["quota"], "count": 0,
                                                                 "limit": r["limit_value"], "first": r["created_at"]})
                g["count"] += 1
                g["limit"], g["last"] = r["limit_value"], r["created_at"]
            for g in groups.values():
                tenant = await conn.fetchrow("SELECT schema_name, field_id FROM public.atalaia_tenants "
                                             "WHERE slug = $1", g["slug"])
                await _audit(conn, "quota_hit", actor or default_actor(), g["slug"],
                             tenant["schema_name"] if tenant else None, tenant["field_id"] if tenant else None,
                             {"quota": g["quota"], "limit": g["limit"], "notes": g["count"],
                              "first": g["first"].isoformat(), "last": g["last"].isoformat()})
        return list(groups.values())
    finally:
        await conn.close()


async def waiting_quota_hits(url: str) -> int:
    conn = await _connect(url)
    try:
        if not await conn.fetchval("SELECT to_regclass('public.atalaia_quota_hits') IS NOT NULL"):
            return 0
        return int(await conn.fetchval("SELECT count(*) FROM public.atalaia_quota_hits"))
    finally:
        await conn.close()


# custom host names --------------------------------------------------------------------------------

DOMAIN_ACTIONS = ("set", "verify", "remove")
Resolver = Any  # (name) -> list of TXT strings; dnsquery.txt by default


def challenge_record(host: str, token: str) -> tuple[str, str]:
    """(the TXT record's name, its value) a field publishes to prove it controls ``host``."""
    return challenge_name(host), CHALLENGE_PREFIX + token


async def set_custom_domain(url: str, slug: str, host: str, domain: str, reason: str,
                            actor: Optional[str] = None) -> tuple[str, str]:
    """Records ``host`` as the field's custom host name, *pending*: it routes nowhere and gets no certificate until
    ``verify_custom_domain`` finds the challenge. Replaces the field's earlier name. Returns the TXT record."""
    host = check_custom_host(host, domain)
    if not reason.strip():
        raise HostedError("--reason is required (who asked, or why)")
    token = secrets.token_hex(16)
    conn = await _connect(url)
    try:
        async with conn.transaction():
            tenant = await _tenant(conn, slug, lock=True)
            taken = await conn.fetchval("SELECT slug FROM public.atalaia_tenants WHERE custom_host = $1 AND slug <> $2",
                                        host, tenant.slug)
            if taken:
                raise HostedError(f"{host} is already the custom host name of the field {taken}")
            await conn.execute("UPDATE public.atalaia_tenants SET custom_host = $2, custom_host_status = 'pending', "
                               "custom_host_token = $3, custom_host_verified_at = NULL, updated_at = now() "
                               "WHERE slug = $1", tenant.slug, host, token)
            await _audit(conn, "tenant_domain_set", actor or default_actor(), tenant.slug, tenant.schema,
                         tenant.field_id, {"host": host, "previous": tenant.custom_host, "status": "pending",
                                           "reason": reason})
        return challenge_record(host, token)
    finally:
        await conn.close()


async def verify_custom_domain(url: str, slug: str, actor: Optional[str] = None,
                               resolver: Optional[Resolver] = None) -> str:
    """Reads the pending name's TXT challenge and, if it holds the field's token, turns the name on; returns it."""
    conn = await _connect(url)
    try:
        async with conn.transaction():
            tenant = await _tenant(conn, slug, lock=True)
            token = await conn.fetchval("SELECT custom_host_token FROM public.atalaia_tenants WHERE slug = $1",
                                        tenant.slug)
            if not tenant.custom_host:
                raise HostedError(f"the field {slug} has no custom host name: hosted domain set {slug} HOST")
            if tenant.custom_host_status == "active":
                raise HostedError(f"{tenant.custom_host} is already verified and on")
            name, value = challenge_record(tenant.custom_host, token or "")
            try:
                found = await asyncio.to_thread(resolver or dnsquery.txt, name)
            except dnsquery.DnsError as e:
                raise HostedError(f"the DNS lookup of {name} failed: {e}") from None
            if not token or value not in [f.strip() for f in found]:
                seen = ", ".join(repr(f) for f in found) or "no TXT record"
                raise HostedError(f"not verified: expected a TXT record at {name} with the value {value}; found "
                                  f"{seen}. DNS changes can take a while; try again.")
            await conn.execute("UPDATE public.atalaia_tenants SET custom_host_status = 'active', "
                               "custom_host_verified_at = now(), updated_at = now() WHERE slug = $1", tenant.slug)
            await _audit(conn, "tenant_domain_verify", actor or default_actor(), tenant.slug, tenant.schema,
                         tenant.field_id, {"host": tenant.custom_host})
        return str(tenant.custom_host)
    finally:
        await conn.close()


async def remove_custom_domain(url: str, slug: str, reason: str, actor: Optional[str] = None) -> Optional[str]:
    """Takes the field's custom host name away (it routes nowhere at once); returns it, None if there was none."""
    if not reason.strip():
        raise HostedError("--reason is required (who asked, or why)")
    conn = await _connect(url)
    try:
        async with conn.transaction():
            tenant = await _tenant(conn, slug, lock=True)
            if not tenant.custom_host:
                return None
            await conn.execute("UPDATE public.atalaia_tenants SET custom_host = NULL, custom_host_status = NULL, "
                               "custom_host_token = NULL, custom_host_verified_at = NULL, updated_at = now() "
                               "WHERE slug = $1", tenant.slug)
            await _audit(conn, "tenant_domain_remove", actor or default_actor(), tenant.slug, tenant.schema,
                         tenant.field_id, {"host": tenant.custom_host, "status": tenant.custom_host_status,
                                           "reason": reason})
        return tenant.custom_host
    finally:
        await conn.close()


# export -------------------------------------------------------------------------------------------

@dataclass
class ExportResult:
    path: Path
    sha256: str
    manifest: dict[str, Any]


async def export_tenant(url: str, slug: str, out: Path, reason: str, actor: Optional[str] = None) -> ExportResult:
    """One tenant's whole schema as a ZIP of CSV files (mode 0600; an existing file is never replaced)."""
    out = Path(out)
    conn = await _connect(url)
    try:
        tenant = await _tenant(conn, slug)
        members: list[tuple[str, bytes]] = []
        tables_meta = []
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            await _scope(conn, tenant.schema)
            revision = await conn.fetchval(f"SELECT version_num FROM {_q(tenant.schema)}.alembic_version")
            for table in await _tables(conn, tenant.schema):
                buf = io.BytesIO()
                await conn.copy_from_query(f"SELECT * FROM {_q(tenant.schema)}.{_q(table)}", output=buf,
                                           format="csv", header=True)
                data = buf.getvalue()
                columns = next(csv.reader(io.StringIO(data.decode("utf-8").split("\n", 1)[0]))) if data else []
                rows = await conn.fetchval(f"SELECT count(*) FROM {_q(tenant.schema)}.{_q(table)}")
                members.append((f"tables/{table}.csv", data))
                tables_meta.append({"name": table, "rows": rows, "columns": columns,
                                    "sha256": hashlib.sha256(data).hexdigest()})
        manifest = {"format": EXPORT_FORMAT, "version": EXPORT_VERSION, "slug": tenant.slug,
                    "field_id": str(tenant.field_id), "revision": revision,
                    "exported_at": datetime.now(timezone.utc).isoformat(), "tables": tables_meta}
        fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as fh, zipfile.ZipFile(fh, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
                zf.writestr("README.txt", EXPORT_README)
                for name, data in members:
                    zf.writestr(name, data)
        except BaseException:
            out.unlink(missing_ok=True)
            raise
        digest = hashlib.sha256(out.read_bytes()).hexdigest()
        await _audit(conn, "tenant_export", actor or default_actor(), tenant.slug, tenant.schema, tenant.field_id,
                     {"reason": reason, "sha256": digest, "revision": revision,
                      "rows": {t["name"]: t["rows"] for t in tables_meta}})
        return ExportResult(out, digest, manifest)
    finally:
        await conn.close()


# import (single-field server) -------------------------------------------------------------------------

async def import_field(url: str, archive: Path) -> dict[str, int]:
    """Loads an export into an empty single-field database at the same revision; returns rows per table.

    In one transaction. Afterwards nobody is logged in (sessions and refresh tokens are deleted), TOTP
    enrolments are reset and platform links are turned off without their configuration: the TOTP seeds and
    the platform credentials were sealed under the hub's ATALAIA_SECRET_KEY, which this server does not have."""
    with zipfile.ZipFile(archive) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        if manifest.get("format") != EXPORT_FORMAT or manifest.get("version") != EXPORT_VERSION:
            raise HostedError("not an Atalaia field export (manifest format or version)")
        files: dict[str, bytes] = {}
        for entry in manifest["tables"]:
            name = entry["name"]
            if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name):
                raise HostedError(f"a table name in the manifest is not valid: {name!r}")
            info = zf.getinfo(f"tables/{name}.csv")
            if info.file_size > MAX_EXPORT_MEMBER:
                raise HostedError(f"tables/{name}.csv is too large")
            data = zf.read(info)
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                raise HostedError(f"tables/{name}.csv does not match its SHA-256 in the manifest")
            files[name] = data
    conn = await _connect(url)
    try:
        if await _registry_exists(conn):
            raise HostedError("this is a hosted hub: import into a single-field server's database")
        revision = await conn.fetchval("SELECT version_num FROM public.alembic_version") \
            if await conn.fetchval("SELECT to_regclass('public.alembic_version') IS NOT NULL") else None
        if revision != manifest["revision"]:
            raise HostedError(f"the export is at revision {manifest['revision']}, this database at {revision}: "
                              "migrate it to the same one first (alembic upgrade)")
        counts: dict[str, int] = {}
        async with conn.transaction():
            target = set(await _tables(conn, "public"))
            for entry in manifest["tables"]:
                name, data = entry["name"], files[entry["name"]]
                if name not in target:
                    raise HostedError(f"this database has no table {name}")
                have = {r["attname"] for r in await conn.fetch(
                    "SELECT attname FROM pg_attribute WHERE attrelid = $1::regclass AND attnum > 0 "
                    "AND NOT attisdropped", f"public.{name}")}
                if set(entry["columns"]) != have:
                    raise HostedError(f"the columns of {name} differ from this database's")
                existing = await conn.fetchval(f"SELECT count(*) FROM public.{_q(name)}")
                if existing:
                    if name in SEEDED_TABLES and await _same_rows(conn, name, data):
                        continue
                    raise HostedError(f"this database is not empty ({name} has rows): import into a fresh one")
                if entry["rows"]:
                    await conn.copy_to_table(name, schema_name="public", source=io.BytesIO(data),
                                             columns=entry["columns"], format="csv", header=True)
                counts[name] = int(entry["rows"])
            await _reset_sequences(conn)
            await conn.execute("DELETE FROM public.refresh_tokens; DELETE FROM public.sessions; "
                               "UPDATE public.users SET totp_enabled = false, totp_secret_enc = NULL, "
                               "totp_last_step = NULL; "
                               "UPDATE public.platform_links SET enabled = false, config_enc = NULL")
            await conn.execute("INSERT INTO public.audit_log (action, resource, resource_id, details) "
                               "VALUES ('field_import', 'field', $1, $2::jsonb)", uuid.UUID(manifest["field_id"]),
                               json.dumps({"from": manifest["slug"], "exported_at": manifest["exported_at"],
                                           "rows": counts}))
        return counts
    finally:
        await conn.close()


async def _same_rows(conn: asyncpg.Connection, table: str, data: bytes) -> bool:
    buf = io.BytesIO()
    await conn.copy_from_query(f"SELECT * FROM public.{_q(table)}", output=buf, format="csv", header=True)
    return sorted(buf.getvalue().splitlines()) == sorted(data.splitlines())


async def _reset_sequences(conn: asyncpg.Connection) -> None:
    rows = await conn.fetch(
        "SELECT c.relname AS tbl, a.attname AS col, pg_get_serial_sequence(format('public.%I', c.relname), a.attname) "
        "AS seq FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_attribute a "
        "ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped WHERE n.nspname = 'public' AND c.relkind = 'r'")
    for r in rows:
        if r["seq"]:
            await conn.execute(f"SELECT setval($1, coalesce((SELECT max({_q(r['col'])}) FROM public.{_q(r['tbl'])}), "
                               "0) + 1, false)", r["seq"])


# delete -------------------------------------------------------------------------------------------

async def delete_tenant(url: str, slug: str, confirm: str, reason: str, actor: Optional[str] = None) -> dict[str, int]:
    """Drops the tenant's schema (every row of the field) and its registry row in one transaction; the hub's
    audit log keeps the deletion with the row counts per table, never a row. Returns those counts."""
    if confirm != slug:
        raise HostedError("--confirm must repeat the field's slug")
    if not reason.strip():
        raise HostedError("--reason is required (the controller's instruction, the contract's end)")
    conn = await _connect(url)
    try:
        async with conn.transaction():
            tenant = await _tenant(conn, slug, lock=True)
            await _scope(conn, tenant.schema)
            counts = {}
            for table in await _tables(conn, tenant.schema):
                counts[table] = await conn.fetchval(f"SELECT count(*) FROM {_q(tenant.schema)}.{_q(table)}")
            if await conn.fetchval("SELECT to_regclass('public.atalaia_share_members') IS NOT NULL"):
                # The field's rows in the hub's sharing tables (SVX-2): the published records go with it.
                counts["hub_share_records"] = await conn.fetchval(
                    "SELECT count(*) FROM public.atalaia_share_records WHERE tenant = $1", tenant.schema)
                counts["hub_share_members"] = await conn.fetchval(
                    "SELECT count(*) FROM public.atalaia_share_members WHERE tenant = $1", tenant.schema)
                await conn.execute("DELETE FROM public.atalaia_share_codes WHERE tenant = $1", tenant.schema)
                await conn.execute("DELETE FROM public.atalaia_share_members WHERE tenant = $1", tenant.schema)
            await conn.execute(f"DROP SCHEMA {_q(tenant.schema)} CASCADE")
            for statement in tenant_roles.drop_sql(tenant.role, tenant.schema):  # the field's role goes with it
                await conn.execute(statement)
            await conn.execute("DELETE FROM public.atalaia_tenants WHERE slug = $1", tenant.slug)
            await _audit(conn, "tenant_delete", actor or default_actor(), tenant.slug, tenant.schema, tenant.field_id,
                         {"reason": reason, "rows": counts})
        return counts
    finally:
        await conn.close()


__all__ = ["HostedError", "TenantError", "apply_security", "challenge_record", "check_hub", "collect_quota_hits",
           "create_tenant", "delete_tenant", "export_tenant", "import_field", "init_hub", "list_tenants", "migrate_all",
           "remove_custom_domain", "set_custom_domain", "set_quota", "set_status", "upgrade_hub", "usage",
           "verify_custom_domain", "waiting_quota_hits"]
