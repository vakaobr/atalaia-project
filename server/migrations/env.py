# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alembic's environment: async, on asyncpg, against ATALAIA_DATABASE_URL.

A caller may hand over the URL in ``Config.attributes["database_url"]``
instead (the tests do, for their per-class databases); otherwise the site
server's ATALAIA_DATABASE_URL is read from the environment (nothing else:
migrating needs no secret key). Each migration runs in one transaction (PostgreSQL has
transactional DDL), so a failed upgrade leaves the schema as it was.
"""

from __future__ import annotations

import asyncio
import logging.config

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from atalaia_server.config import database_url_from_env
from atalaia_server.models import Base

config = context.config
if config.config_file_name is not None and not config.attributes.get("skip_logging"):
    logging.config.fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url() -> str:
    return config.attributes.get("database_url") or database_url_from_env()


def _configure(**kwargs: object) -> None:
    context.configure(target_metadata=target_metadata, compare_type=True, compare_server_default=True,
                      transaction_per_migration=True, **kwargs)


def run_offline() -> None:
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection=connection)
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
