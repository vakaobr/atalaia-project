# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Alembic migrations: reversible, linear, and exactly the ORM models (ADR-P4-1, PostgreSQL 16).

``tools/docker_server.py migrations`` runs the same round trip with the
alembic command (upgrade head, downgrade base, upgrade head, check); these
tests also step through every revision on its own and compare the schema
before and after each downgrade.
"""

from __future__ import annotations

import asyncio
import re
import unittest
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from atalaia_server.models import ROLES, Base

from .base import SERVER, TempDatabase, alembic_config

BASE_TABLES = {"fields", "users", "roles", "user_field_roles", "sessions", "audit_log"}

SCHEMA_SQL = (
    ("columns", "SELECT table_name, column_name, data_type, is_nullable, column_default, character_maximum_length "
                "FROM information_schema.columns WHERE table_schema = 'public' ORDER BY 1, 2"),
    ("indexes", "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = 'public' ORDER BY 1, 2"),
    ("constraints", "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = 'public' ORDER BY 1, 2"),
    ("sequences", "SELECT sequence_name FROM information_schema.sequences WHERE sequence_schema = 'public' ORDER BY 1"),
    ("types", "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
              "WHERE n.nspname = 'public' AND t.typtype = 'e' ORDER BY 1"),
)


class MigrationTests(unittest.TestCase):
    db: TempDatabase

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = TempDatabase()
        cls.db.create(migrate=False)
        cls.cfg = alembic_config(cls.db.url)
        cls.script = ScriptDirectory.from_config(cls.cfg)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.drop()

    def setUp(self) -> None:
        command.downgrade(self.cfg, "base")

    def schema(self) -> dict[str, list[tuple]]:
        return {name: [tuple(r) for r in self.db.fetch(sql)] for name, sql in SCHEMA_SQL}

    def tables(self) -> set[str]:
        return {r["table_name"] for r in self.db.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}

    def test_round_trip(self) -> None:
        empty = self.schema()
        command.upgrade(self.cfg, "head")
        self.assertEqual(self.tables(), BASE_TABLES | {"alembic_version"})
        first = self.schema()
        command.downgrade(self.cfg, "base")
        self.assertEqual(self.tables(), {"alembic_version"})
        self.assertEqual(self.schema(), empty)
        self.assertEqual(self.db.fetch("SELECT count(*) AS n FROM alembic_version")[0]["n"], 0)
        command.upgrade(self.cfg, "head")
        self.assertEqual(self.schema(), first)

    def test_every_revision_downgrades_to_what_was_before(self) -> None:
        revisions = list(reversed(list(self.script.walk_revisions("base", "heads"))))
        self.assertTrue(revisions)
        for rev in revisions:
            with self.subTest(revision=rev.revision):
                before = self.schema()
                command.upgrade(self.cfg, rev.revision)
                after = self.schema()
                self.assertNotEqual(after, before, "the migration changes nothing")
                command.downgrade(self.cfg, rev.down_revision or "base")
                self.assertEqual(self.schema(), before)
                command.upgrade(self.cfg, rev.revision)
                self.assertEqual(self.schema(), after)

    def test_migrations_build_exactly_the_models(self) -> None:
        command.upgrade(self.cfg, "head")

        def diff(connection) -> list:
            ctx = MigrationContext.configure(connection, opts={"compare_type": True,
                                                               "compare_server_default": True})
            return compare_metadata(ctx, Base.metadata)

        async def run() -> list:
            engine = create_async_engine(self.db.url, poolclass=NullPool)
            try:
                async with engine.connect() as conn:
                    return await conn.run_sync(diff)
            finally:
                await engine.dispose()

        self.assertEqual(asyncio.run(run()), [])

    def test_roles_are_seeded(self) -> None:
        command.upgrade(self.cfg, "head")
        rows = self.db.fetch("SELECT id, name FROM roles ORDER BY id")
        self.assertEqual([(r["id"], r["name"]) for r in rows], list(ROLES))

    def test_one_linear_history(self) -> None:
        self.assertEqual(len(self.script.get_heads()), 1)
        self.assertEqual(len(self.script.get_bases()), 1)
        for rev in self.script.walk_revisions():
            with self.subTest(revision=rev.revision):
                self.assertRegex(rev.revision, r"^\d{4}_[a-z0-9_]+$")
                self.assertEqual(Path(rev.path).name, f"{rev.revision}.py")
                self.assertFalse(rev.is_merge_point)
                source = Path(rev.path).read_text(encoding="utf-8")
                body = re.search(r"^def downgrade\(\) -> None:\n((?:    .*\n|\n)+)", source, re.M)
                self.assertIsNotNone(body, "no downgrade()")
                self.assertNotRegex(body.group(1).strip(), r"^(pass|\.\.\.)$", "an empty downgrade()")
        self.assertTrue((SERVER / "migrations" / "versions").is_dir())


if __name__ == "__main__":
    unittest.main()
