# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alembic's environment: async, on asyncpg, against ATALAIA_DATABASE_URL.

A caller may hand over the URL in ``Config.attributes["database_url"]``
instead (the tests do, for their per-class databases); otherwise the site
server's ATALAIA_DATABASE_URL is read from the environment (nothing else:
migrating needs no secret key). Each migration runs in one transaction (PostgreSQL has
transactional DDL), so a failed upgrade leaves the schema as it was.

Hosted mode (plan phase 21): ``Config.attributes["schema"]`` names one tenant's
schema (``field_<slug>``); the migrations then run in it, with its own
``alembic_version`` and the tenant setting the row-level security policies
check, so a migration that changes rows sees that tenant's. The operator's
``python -m atalaia_server hosted migrate`` runs them over every tenant
(``hosted.py``). With ATALAIA_HOSTED=on and no schema named, nothing runs: the
single-field tables must never be made in a hosted database's ``public``.
"""

from __future__ import annotations

import asyncio
import logging.config
import os
import re

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from atalaia_server.config import database_url_from_env
from atalaia_server.models import Base

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging"):
    logging.config.fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
SCHEMA = config.attributes.get("schema")
if SCHEMA is not None and not re.fullmatch(r"field_[a-z0-9_]{1,40}", SCHEMA):
    raise RuntimeError(f"not a tenant schema: {SCHEMA!r}")
if SCHEMA is None and os.environ.get("ATALAIA_HOSTED", "").strip().lower() == "on":
    raise RuntimeError("ATALAIA_HOSTED=on: migrate the tenants with python -m atalaia_server hosted migrate "
                       "(the owner role's ATALAIA_DATABASE_URL), not with alembic upgrade")


def _url() -> str:
    return config.attributes.get("database_url") or database_url_from_env()


def _configure(**kwargs: object) -> None:
    context.configure(target_metadata=target_metadata, compare_type=True, compare_server_default=True,
                      transaction_per_migration=True, **kwargs)


def run_offline() -> None:
    if SCHEMA is not None:
        raise RuntimeError("offline migrations of a tenant's schema are not supported")
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    if SCHEMA is None:
        _configure(connection=connection)
    else:  # one tenant (hosted mode): its schema first on the path, its tenant setting for the session
        connection.execute(text(f'SET search_path TO "{SCHEMA}"'))
        connection.execute(text("SELECT set_config('atalaia.tenant', :schema, false)"), {"schema": SCHEMA})
        connection.commit()
        connection.dialect.default_schema_name = SCHEMA
        _configure(connection=connection, version_table_schema=SCHEMA)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
            await connection.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
