# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hosted multi-tenant mode at run time (ADR-P4-4 as built; plan phase 21; decisions S21-*).

With ``ATALAIA_HOSTED=on`` one site server serves many fields from one
PostgreSQL database. Each field (a *tenant*) has a schema of its own,
``field_<slug>`` (hyphens become underscores), holding every table the
single-field server has, at the same Alembic revision; ``public`` holds only
the hub's registry (``public.atalaia_tenants``, which the server may read and
not change) and its audit log (which the server cannot read). The operator's
commands that make, migrate, export and delete tenants are in ``hosted.py``.

Per request:

1. ``TenantMiddleware`` takes the field from the host name,
   ``<slug>.<ATALAIA_HOSTED_DOMAIN>``, and looks it up in the registry. An
   unknown host gets 404 ``unknown_field`` (a WebSocket is closed with 4404), a
   suspended field 403 ``field_suspended``; only ``GET /api/v1/health`` answers
   without a field (the container's health check). The tenant is put in a
   context variable for the rest of the request. A controller's API key is
   checked inside the tenant its host name chose, so a key never selects a
   tenant on its own (S21-3).
2. Every database session made during the request belongs to that tenant
   (``TenantSession``): at the start of each of its transactions it runs
   ``set_config('search_path', <schema>, true)`` and
   ``set_config('atalaia.tenant', <schema>, true)``, both transaction-local
   (``SET LOCAL``), so a pooled connection carries neither past the
   transaction. A session with no tenant gets ``pg_catalog`` as its path, where
   no table of the site server resolves.
3. Row-level security under it (defence in depth, ``hosted.apply_security``):
   every table of a tenant's schema has ``ENABLE`` and ``FORCE ROW LEVEL
   SECURITY`` and one policy, ``atalaia.tenant`` = that schema's name. A
   routing mistake that pointed a session's path at another field's schema
   would read and write nothing there; a missing setting reads nothing. The
   server's database role owns no table, has no ``BYPASSRLS`` and is no
   superuser: ``check_app_role`` refuses to start otherwise.

The server's engine opens its connections with ``search_path=pg_catalog``, so
even outside a session's transaction nothing resolves. Access tokens carry
the tenant (``tokens.py``), login lockouts are kept per tenant
(``ratelimit.login_key``) and the remote GM's links are keyed by it
(``remote_gm.py``). Single-field mode (the default) uses none of this.
"""

from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Iterator, Optional

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session, SessionTransaction

# A tenant's slug is one DNS label (its host name is <slug>.<domain>) of at most 40 characters.
TENANT_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?")
SCHEMA_NAME = re.compile(r"field_[a-z0-9_]{1,40}")
SETTING = "atalaia.tenant"
NO_TENANT_PATH = "pg_catalog"
# Answered without a tenant: the container's health check calls 127.0.0.1, not a field's name.
OPEN_PATHS = frozenset({"/api/v1/health"})
STATUSES = ("active", "suspended")


class TenantError(ValueError):
    """A slug or schema name that is not valid."""


def check_slug(slug: str) -> str:
    if not isinstance(slug, str) or not TENANT_SLUG.fullmatch(slug):
        raise TenantError("a field's slug in hosted mode is 1-40 characters: lower-case letters, digits and "
                          "hyphens, starting and ending with a letter or digit")
    return slug


def schema_for(slug: str) -> str:
    """``field_<slug>`` with hyphens as underscores (a slug has no underscore, so two slugs never share one)."""
    return "field_" + check_slug(slug).replace("-", "_")


def check_schema(schema: str) -> str:
    if not isinstance(schema, str) or not SCHEMA_NAME.fullmatch(schema):
        raise TenantError(f"not a tenant schema name: {schema!r}")
    return schema


@dataclass(frozen=True)
class Tenant:
    slug: str
    schema: str
    field_id: uuid.UUID
    status: str = "active"

    def host(self, domain: str) -> str:
        return f"{self.slug}.{domain}"


_current: ContextVar[Optional[Tenant]] = ContextVar("atalaia_tenant", default=None)


def current() -> Optional[Tenant]:
    """The tenant of the request (or command) being served; None in single-field mode."""
    return _current.get()


def current_schema() -> Optional[str]:
    tenant = _current.get()
    return tenant.schema if tenant is not None else None


@contextmanager
def use(tenant: Optional[Tenant]) -> Iterator[None]:
    """Serve ``tenant`` inside the block (the purge, the commands, the tests)."""
    token = _current.set(tenant)
    try:
        yield
    finally:
        _current.reset(token)


def slug_from_host(host: str, domain: str) -> Optional[str]:
    """The tenant's slug from a Host header, ``<slug>.<domain>[:port]``; None for any other name."""
    host = host.strip().lower()
    if not host or host.startswith("["):
        return None
    host = host.rsplit(":", 1)[0].rstrip(".")
    suffix = "." + domain
    if not host.endswith(suffix):
        return None
    label = host[:-len(suffix)]
    return label if TENANT_SLUG.fullmatch(label) else None


_REGISTRY_ROW = text("SELECT slug, schema_name, field_id, status FROM public.atalaia_tenants WHERE slug = :slug")
_REGISTRY_ALL = text("SELECT slug, schema_name, field_id, status FROM public.atalaia_tenants "
                     "WHERE status = 'active' ORDER BY slug")


async def lookup(engine: AsyncEngine, slug: str) -> Optional[Tenant]:
    async with engine.connect() as conn:
        row = (await conn.execute(_REGISTRY_ROW, {"slug": slug})).first()
    if row is None:
        return None
    return Tenant(slug=row[0], schema=check_schema(row[1]), field_id=row[2], status=row[3])


async def active_tenants(engine: AsyncEngine) -> list[Tenant]:
    async with engine.connect() as conn:
        rows = (await conn.execute(_REGISTRY_ALL)).all()
    return [Tenant(slug=r[0], schema=check_schema(r[1]), field_id=r[2], status=r[3]) for r in rows]


# Sessions -------------------------------------------------------------------------------------

_SCOPE = text("SELECT set_config('search_path', :path, true), set_config('atalaia.tenant', :tenant, true)")


class TenantSession(Session):
    """A session of one tenant: the one current when it was made (or none: then nothing resolves)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.info["atalaia_tenant"] = current_schema()


@event.listens_for(TenantSession, "after_begin")
def _scope_transaction(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    schema = session.info.get("atalaia_tenant")
    if schema is not None:
        check_schema(schema)
    connection.execute(_SCOPE, {"path": schema or NO_TENANT_PATH, "tenant": schema or ""})


def engine_options() -> dict[str, Any]:
    """asyncpg's start-up settings for the hosted server's connections: no schema on the path."""
    return {"server_settings": {"search_path": NO_TENANT_PATH}}


# The server's database role ---------------------------------------------------------------------

_ROLE_CHECK = text(r"""
SELECT r.rolsuper, r.rolbypassrls,
       (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relowner = r.oid AND (n.nspname LIKE 'field\_%' OR c.relname LIKE 'atalaia\_%')) AS tables_owned,
       (SELECT count(*) FROM pg_namespace n WHERE n.nspowner = r.oid AND n.nspname LIKE 'field\_%') AS schemas_owned,
       to_regclass('public.atalaia_tenants') IS NOT NULL AS registry
  FROM pg_roles r WHERE r.rolname = current_user
""")
_REGISTRY_WRITE = text("SELECT has_table_privilege('public.atalaia_tenants', 'INSERT, UPDATE, DELETE, TRUNCATE')")


class RoleProblem(RuntimeError):
    """The hosted server's database role could bypass the isolation: it does not start."""


async def check_app_role(engine: AsyncEngine) -> None:
    """Refuses (``RoleProblem``) a role that is a superuser, has BYPASSRLS, owns a tenant's table or schema
    or may change the registry, and a database with no registry (``hosted init`` not run)."""
    async with engine.connect() as conn:
        row = (await conn.execute(_ROLE_CHECK)).one()
        superuser, bypass, tables, schemas, registry = row
        problems = []
        if superuser:
            problems.append("is a superuser")
        if bypass:
            problems.append("has BYPASSRLS")
        if tables or schemas:
            problems.append("owns tenant tables or schemas (it must not be the migrations' owner role)")
        if not registry:
            problems.append("finds no public.atalaia_tenants (run: python -m atalaia_server hosted init)")
        elif await conn.scalar(_REGISTRY_WRITE):
            problems.append("may change public.atalaia_tenants")
    if problems:
        raise RoleProblem("hosted mode: the server's database role " + "; ".join(problems)
                          + " (server/docs/DEPLOY.md, hosted mode)")


# The middleware ---------------------------------------------------------------------------------

Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


class TenantMiddleware:
    """Chooses the tenant of each request from its host name (hosted mode only; a no-op otherwise)."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]], get_state: Callable[[], Any]) -> None:
        self.app = app
        self.get_state = get_state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        state = self.get_state()
        if scope["type"] not in ("http", "websocket") or not state.settings.hosted:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "http" and scope.get("path") in OPEN_PATHS:
            with use(None):
                await self.app(scope, receive, send)
            return
        host = ""
        for name, value in scope.get("headers") or ():
            if name == b"host":
                host = value.decode("latin-1")
                break
        slug = slug_from_host(host, state.settings.hosted_domain)
        try:
            tenant = await lookup(state.engine, slug) if slug else None
        except Exception:  # noqa: BLE001  (the database is down: no tenant can be found)
            await _refuse(scope, receive, send, 503, "database_unreachable")
            return
        if tenant is None:
            await _refuse(scope, receive, send, 404, "unknown_field")
            return
        if tenant.status != "active":
            await _refuse(scope, receive, send, 403, "field_suspended")
            return
        with use(tenant):
            await self.app(scope, receive, send)


async def _refuse(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
    if scope["type"] == "websocket":
        await receive()  # websocket.connect
        await send({"type": "websocket.close", "code": 4000 + status})
        return
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})
