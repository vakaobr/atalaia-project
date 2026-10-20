# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hosted hub's operator tooling (ADR-P4-4 as built; plan phase 21; decisions S21-*).

    python -m atalaia_server hosted init     [--app-role ROLE]
    python -m atalaia_server hosted create   SLUG --name NAME [--field-type T] [--timezone TZ] [--app-role ROLE]
    python -m atalaia_server hosted list
    python -m atalaia_server hosted migrate  [--app-role ROLE]
    python -m atalaia_server hosted suspend  SLUG --reason TEXT
    python -m atalaia_server hosted resume   SLUG --reason TEXT
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
- ``create`` makes the schema ``field_<slug>``, runs every migration in it,
  writes the field's one ``fields`` row, applies the grants and the row-level
  security (``apply_security``) and registers the tenant; a failure leaves no
  schema behind.
- ``migrate`` brings every tenant to the newest revision, then applies the
  grants and policies again (a new table gets them too).
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
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import asyncpg
from sqlalchemy.engine import make_url

from .tenancy import STATUSES, Tenant, TenantError, check_schema, check_slug, schema_for

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


async def _tenant(conn: asyncpg.Connection, slug: str, lock: bool = False) -> Tenant:
    await _need_registry(conn)
    row = await conn.fetchrow("SELECT slug, schema_name, field_id, status FROM public.atalaia_tenants "
                              "WHERE slug = $1" + (" FOR UPDATE" if lock else ""), check_slug(slug))
    if row is None:
        raise HostedError(f"no field {slug!r} on this hub")
    return Tenant(slug=row["slug"], schema=check_schema(row["schema_name"]), field_id=row["field_id"],
                  status=row["status"])


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


async def apply_security(conn: asyncpg.Connection, schema: str, app_role: str) -> int:
    """The server's grants and the row-level security of one tenant's schema; returns the tables covered.

    The server's role gets USAGE on the schema, SELECT/INSERT/UPDATE/DELETE on its tables (never TRUNCATE,
    which row-level security does not cover, nor REFERENCES or TRIGGER) and its sequences; nothing on
    ``alembic_version``. Every table gets ENABLE and FORCE ROW LEVEL SECURITY and the one policy
    ``atalaia_tenant``: rows are seen and written only while ``atalaia.tenant`` is this schema's name."""
    check_schema(schema)
    check_role(app_role)
    s, role = _q(schema), _q(app_role)
    await conn.execute(f"REVOKE ALL ON SCHEMA {s} FROM PUBLIC; GRANT USAGE ON SCHEMA {s} TO {role}")
    tables = await _tables(conn, schema)
    literal = "'" + schema + "'"  # schema passed check_schema: [a-z0-9_] only
    for table in tables:
        t = f"{s}.{_q(table)}"
        await conn.execute(
            f"REVOKE ALL ON {t} FROM PUBLIC; REVOKE ALL ON {t} FROM {role}; "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO {role}; "
            f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY; ALTER TABLE {t} FORCE ROW LEVEL SECURITY; "
            f"DROP POLICY IF EXISTS atalaia_tenant ON {t}; "
            f"CREATE POLICY atalaia_tenant ON {t} USING (current_setting('atalaia.tenant', true) = {literal}) "
            f"WITH CHECK (current_setting('atalaia.tenant', true) = {literal})")
    if await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"{schema}.alembic_version"):
        await conn.execute(f"REVOKE ALL ON {s}.alembic_version FROM PUBLIC; REVOKE ALL ON {s}.alembic_version "
                           f"FROM {role}")
    await conn.execute(f"GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA {s} TO {role}")
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
            await conn.execute(f"GRANT USAGE ON SCHEMA public TO {_q(app_role)}; "
                               f"GRANT SELECT ON public.atalaia_tenants TO {_q(app_role)}")
            await _audit(conn, "hub_init", actor or default_actor(), details={"app_role": app_role})
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
            tables = await apply_security(conn, schema, app_role)
            await conn.execute("INSERT INTO public.atalaia_tenants (slug, schema_name, field_id) VALUES ($1, $2, $3)",
                               slug, schema, field_id)
            revision = await conn.fetchval(f"SELECT version_num FROM {_q(schema)}.alembic_version")
            await _audit(conn, "tenant_create", actor, slug, schema, field_id,
                         {"tables": tables, "revision": revision, "app_role": app_role})
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
        rows = await conn.fetch("SELECT slug, schema_name, field_id, status, created_at FROM public.atalaia_tenants "
                                "ORDER BY slug")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


def migrate_all(url: str, app_role: str = DEFAULT_APP_ROLE, actor: Optional[str] = None) -> list[str]:
    """Every tenant (active or suspended) to the newest revision, grants and policies again; the slugs done."""
    check_role(app_role)
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
            tables = await apply_security(conn, schema, app_role)
            revision = await conn.fetchval(f"SELECT version_num FROM {_q(schema)}.alembic_version")
            await _audit(conn, "tenant_migrate", actor, slug, schema, field_id, {"tables": tables,
                                                                                  "revision": revision})
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
            await conn.execute(f"DROP SCHEMA {_q(tenant.schema)} CASCADE")
            await conn.execute("DELETE FROM public.atalaia_tenants WHERE slug = $1", tenant.slug)
            await _audit(conn, "tenant_delete", actor or default_actor(), tenant.slug, tenant.schema, tenant.field_id,
                         {"reason": reason, "rows": counts})
        return counts
    finally:
        await conn.close()


__all__ = ["HostedError", "TenantError", "apply_security", "create_tenant", "delete_tenant", "export_tenant",
           "import_field", "init_hub", "list_tenants", "migrate_all", "set_status"]
