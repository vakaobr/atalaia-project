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
   ``<slug>.<ATALAIA_HOSTED_DOMAIN>`` (or the field's custom host name, once the operator verified it by a DNS
   TXT challenge: ``hosted domain``, decisions PKC-6), and looks it up in the registry. An
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
4. Under both, the grants (S2113-1, ``tenant_roles.py``): every field has a database role of its own that alone
   holds the grants on its schema, and each transaction starts with ``set_config('role', <field's role>, true)``
   (``SET LOCAL ROLE``). The server's login role holds no grant on any field's table, so even a statement that
   calls ``set_config('atalaia.tenant', <another field>, ...)`` reaches no row of another field: ``permission
   denied``; and a field's role cannot call ``pg_catalog.set_config`` (revoked from PUBLIC by
   ``server/hosted-roles.sh``; ``check_app_role`` refuses to start otherwise), so a statement running as it cannot
   switch role or setting at all (``SET ROLE`` is a command, and the server's driver sends one statement at a
   time). What stays across fields is by design and explicit: the registry, the quota inbox, the lookups of
   the host name and the watcher read as the server's login role; the chrono sharing's hub tables as the field's
   role, their policy keyed on that role (``atalaia_caller_tenant``), not on the setting.

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
from dataclasses import dataclass, field as dc_field
from typing import Any, Awaitable, Callable, Iterator, Mapping, Optional

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.orm import Session, SessionTransaction

from . import quotas, tenant_roles

# A tenant's slug is one DNS label (its host name is <slug>.<domain>) of at most 40 characters.
TENANT_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?")
SCHEMA_NAME = re.compile(r"field_[a-z0-9_]{1,40}")
SETTING = "atalaia.tenant"
NO_TENANT_PATH = "pg_catalog"
# Answered without a tenant: the container's health check calls 127.0.0.1, not a field's name.
OPEN_PATHS = frozenset({"/api/v1/health"})
STATUSES = ("active", "suspended")
HOST_STATUSES = ("pending", "active")
# A field's custom host name (PKC-6): two or more DNS labels, lower case, the last one letters (so never an address).
CUSTOM_HOST = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?")
CHALLENGE_LABEL = "_atalaia-challenge"
CHALLENGE_PREFIX = "atalaia-verify="


class TenantError(ValueError):
    """A slug or schema name that is not valid."""


def check_custom_host(host: str, domain: str) -> str:
    """A field's custom host name, lower case with no trailing dot; ``TenantError`` unless it is a plain DNS name of
    two labels or more that is not the hub's domain or a name under it (those are the fields' own addresses)."""
    name = (host or "").strip().lower().rstrip(".") if isinstance(host, str) else ""
    if not CUSTOM_HOST.fullmatch(name):
        raise TenantError("a custom host name is a DNS name such as jogos.example.pt: two or more labels of lower-case "
                          "letters, digits and hyphens, no scheme, port, path or wildcard")
    if name == domain or name.endswith("." + domain):
        raise TenantError(f"{name} is the hub's own domain or under it: a field's own address is <slug>.{domain}")
    return name


def challenge_name(host: str) -> str:
    """Where the field puts its proof of control: a TXT record at this name."""
    return f"{CHALLENGE_LABEL}.{host}"


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
    # The operator's per-field quota overrides (name -> limit, 0 for none), and the field's custom host name, which
    # routes only once its DNS challenge passed (``custom_host_status`` ``active``).
    quotas: Mapping[str, int] = dc_field(default_factory=dict, hash=False, compare=False)
    custom_host: Optional[str] = dc_field(default=None, compare=False)
    custom_host_status: Optional[str] = dc_field(default=None, compare=False)

    @property
    def role(self) -> str:
        """The field's own database role (``tenant_roles``): what every request of the field runs as."""
        return tenant_roles.role_for(self.field_id)

    def host(self, domain: str) -> str:
        return f"{self.slug}.{domain}"

    def serving_host(self, domain: str, request_host: str = "") -> str:
        """The name this request reached the field by: its custom host name when it came that way (and the name is
        on), else ``<slug>.<domain>`` (the page addresses, a passkey's origin and the like follow it)."""
        if self.custom_host and self.custom_host_status == "active" and host_name(request_host) == self.custom_host:
            return self.custom_host
        return self.host(domain)


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


COLUMNS = "slug, schema_name, field_id, status, quotas, custom_host, custom_host_status"
_REGISTRY_ROW = text(f"SELECT {COLUMNS} FROM public.atalaia_tenants WHERE slug = :slug")
_REGISTRY_HOST = text(f"SELECT {COLUMNS} FROM public.atalaia_tenants "
                      "WHERE custom_host = :host AND custom_host_status = 'active'")
_REGISTRY_ALL = text(f"SELECT {COLUMNS} FROM public.atalaia_tenants WHERE status = 'active' ORDER BY slug")


def host_name(value: str) -> str:
    """A Host header's name alone: lower case, no port, no trailing dot ('' for an IPv6 literal)."""
    value = (value or "").strip().lower()
    if not value or value.startswith("["):
        return ""
    return value.rsplit(":", 1)[0].rstrip(".")


def from_row(row: Any) -> Tenant:
    """A tenant from a registry row (``COLUMNS``); the quotas column is jsonb, which a driver may hand over as text."""
    quotas = row[4]
    if isinstance(quotas, (str, bytes)):
        quotas = json.loads(quotas)
    return Tenant(slug=row[0], schema=check_schema(row[1]), field_id=row[2], status=row[3],
                  quotas={str(k): int(v) for k, v in (quotas or {}).items()}, custom_host=row[5],
                  custom_host_status=row[6])


async def lookup(engine: AsyncEngine, slug: str) -> Optional[Tenant]:
    async with engine.connect() as conn:
        row = (await conn.execute(_REGISTRY_ROW, {"slug": slug})).first()
    return from_row(row) if row is not None else None


async def lookup_host(engine: AsyncEngine, host: str) -> Optional[Tenant]:
    """The field whose custom host name is ``host`` and has passed its DNS challenge (a pending name routes nowhere)."""
    name = host_name(host)
    if not CUSTOM_HOST.fullmatch(name):
        return None
    async with engine.connect() as conn:
        row = (await conn.execute(_REGISTRY_HOST, {"host": name})).first()
    return from_row(row) if row is not None else None


async def active_tenants(engine: AsyncEngine) -> list[Tenant]:
    async with engine.connect() as conn:
        rows = (await conn.execute(_REGISTRY_ALL)).all()
    return [from_row(r) for r in rows]


# Sessions -------------------------------------------------------------------------------------

# ``set_config('role', ..., true)`` is ``SET LOCAL ROLE``: the transaction runs as the field's own role (the one
# that alone holds the grants on its schema, S2113-1) and the role goes back to the server's at its end. The role
# comes last: the function calls are checked before the statement runs, as the server's role (the only one that
# may call ``set_config``), and run left to right.
_SCOPE = text("SELECT set_config('search_path', :path, true), set_config('atalaia.tenant', :tenant, true), "
              "set_config('role', :role, true)")
NO_ROLE = "none"


class TenantSession(Session):
    """A session of one tenant: the one current when it was made (or none: then nothing resolves)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        tenant = current()
        self.info["atalaia_tenant"] = tenant.schema if tenant is not None else None
        self.info["atalaia_role"] = tenant.role if tenant is not None else None


@event.listens_for(TenantSession, "after_begin")
def _scope_transaction(session: Session, transaction: SessionTransaction, connection: Connection) -> None:
    if transaction.parent is not None:
        return  # a savepoint: its outer transaction is already scoped, and now runs as the field's role
    schema = session.info.get("atalaia_tenant")
    if schema is not None:
        check_schema(schema)
    role = session.info.get("atalaia_role")
    if role is not None:
        tenant_roles.check_tenant_role(role)
    connection.execute(_SCOPE, {"role": role or NO_ROLE, "path": schema or NO_TENANT_PATH, "tenant": schema or ""})


def engine_options() -> dict[str, Any]:
    """asyncpg's start-up settings for the hosted server's connections: no schema on the path, and no JIT (the
    driver's type introspection would switch it off with ``set_config``, see ``keep_set_config_to_the_server``)."""
    return {"server_settings": {"search_path": NO_TENANT_PATH, "jit": "off"}}


def keep_set_config_to_the_server(engine: AsyncEngine) -> None:
    """asyncpg learns a type it has not met by a query that calls ``set_config('jit', 'off', false)`` first, as
    whatever role the connection has then: a field's role, which may not call ``set_config`` (S2113-1,
    ``hosted-roles.sh``). The connections start with JIT off already (``engine_options``), so tell the driver not
    to bother: its ``jit`` capability is off, and it never calls ``set_config``. ``asyncpg`` is pinned by hash; the
    hosted tests run a query that needs the introspection as a field's role, and fail if a new release changes this."""
    @event.listens_for(engine.sync_engine, "connect")
    def _no_jit_toggle(dbapi_connection: Any, record: Any) -> None:
        raw = dbapi_connection.driver_connection
        raw._server_caps = raw._server_caps._replace(jit=False)


# The server's database role ---------------------------------------------------------------------

_ROLE_CHECK = text(r"""
SELECT r.rolsuper, r.rolbypassrls,
       (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE c.relowner = r.oid AND (n.nspname LIKE 'field\_%' OR c.relname LIKE 'atalaia\_%')) AS tables_owned,
       (SELECT count(*) FROM pg_namespace n WHERE n.nspowner = r.oid AND n.nspname LIKE 'field\_%') AS schemas_owned,
       to_regclass('public.atalaia_tenants') IS NOT NULL AS registry,
       (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public'
                  AND table_name = 'atalaia_tenants' AND column_name IN ('custom_host', 'role_name')) = 2
           AS current_registry,
       to_regclass('public.atalaia_quota_hits') IS NOT NULL AS hits,
       EXISTS (SELECT 1 FROM pg_proc p, aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a
                WHERE p.oid = 'pg_catalog.set_config(text, text, boolean)'::regprocedure
                  AND a.grantee = 0 AND a.privilege_type = 'EXECUTE') AS set_config_public,
       has_function_privilege('pg_catalog.set_config(text, text, boolean)'::regprocedure, 'EXECUTE') AS set_config_own,
       (SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname LIKE 'field\_%' AND c.relkind IN ('r', 'p')
           AND (has_table_privilege(c.oid, 'SELECT') OR has_table_privilege(c.oid, 'INSERT')
                OR has_table_privilege(c.oid, 'UPDATE') OR has_table_privilege(c.oid, 'DELETE'))) AS direct_grants
  FROM pg_roles r WHERE r.rolname = current_user
""")
_ROLES_MISSING = text("SELECT t.slug FROM public.atalaia_tenants t LEFT JOIN pg_roles r ON r.rolname = t.role_name "
                      "WHERE r.oid IS NULL OR NOT pg_has_role(r.oid, 'SET') ORDER BY t.slug")
_REGISTRY_WRITE = text("SELECT has_table_privilege('public.atalaia_tenants', 'INSERT, UPDATE, DELETE, TRUNCATE')")


class RoleProblem(RuntimeError):
    """The hosted server's database role could bypass the isolation: it does not start."""


async def check_app_role(engine: AsyncEngine) -> None:
    """Refuses (``RoleProblem``) a role that is a superuser, has BYPASSRLS, owns a tenant's table or schema
    or may change the registry, and a database with no registry (``hosted init`` not run)."""
    async with engine.connect() as conn:
        row = (await conn.execute(_ROLE_CHECK)).one()
        superuser, bypass, tables, schemas, registry, current_registry, hits, set_config_public, set_config_own, direct = row
        problems = []
        if superuser:
            problems.append("is a superuser")
        if bypass:
            problems.append("has BYPASSRLS")
        if tables or schemas:
            problems.append("owns tenant tables or schemas (it must not be the migrations' owner role)")
        if not registry:
            problems.append("finds no public.atalaia_tenants (run: python -m atalaia_server hosted init)")
        elif not (current_registry and hits):
            problems.append("finds the registry of an older release (run: python -m atalaia_server hosted migrate)")
        else:
            if set_config_public or not set_config_own:
                problems.append("finds pg_catalog.set_config callable by every role, or not by itself (a field's "
                                "role must not be able to call it: it could SET ROLE to another field; run "
                                "server/hosted-roles.sh as the database's superuser, server/docs/DEPLOY.md)")
            if await conn.scalar(_REGISTRY_WRITE):
                problems.append("may change public.atalaia_tenants")
            if direct:
                problems.append(f"holds grants on {direct} tenant tables itself (only a field's own role may: run "
                                "python -m atalaia_server hosted migrate)")
            missing = [r[0] for r in (await conn.execute(_ROLES_MISSING)).all()]
            if missing:
                problems.append("cannot SET ROLE to the database role of " + ", ".join(missing[:5])
                                + " (run python -m atalaia_server hosted migrate)")
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
            # <slug>.<domain>, else a field's custom host name that passed its DNS challenge (PKC-6).
            tenant = await lookup(state.engine, slug) if slug else await lookup_host(state.engine, host)
        except Exception:  # noqa: BLE001  (the database is down: no tenant can be found)
            await _refuse(scope, receive, send, 503, "database_unreachable")
            return
        if tenant is None:
            await _refuse(scope, receive, send, 404, "unknown_field")
            return
        if tenant.status != "active":
            await _refuse(scope, receive, send, 403, "field_suspended")
            return
        # The hub's limits (the environment's), with the operator's own for this field over them (PKC-5).
        with use(tenant), quotas.use({**state.settings.quotas, **tenant.quotas}):
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
