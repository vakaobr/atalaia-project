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
import datetime
import re
import unittest
import uuid
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from atalaia_server.models import ROLES, Base

from .base import SERVER, TempDatabase, alembic_config

TABLES = {"fields", "users", "roles", "user_field_roles", "sessions", "audit_log", "refresh_tokens", "consents",
          "field_api_keys", "controllers", "games", "game_events", "game_node_scores", "game_nodes", "user_game_roles",
          "field_player_ids", "marshal_keys", "replicas", "chrono_readings", "chrono_rejects", "chrono_violations",
          "scheduled_games", "game_registrations", "registration_replicas", "player_id_claims",
          "platform_links", "external_game_links", "branding_images", "clubs", "club_members", "club_reports",
          "field_teams", "firmware_releases", "field_history_settings", "game_score_samples", "field_scenarios",
          "field_scenario_revisions", "field_presets", "atak_cas", "atak_certs", "preview_feedback"}

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
        self.assertEqual(self.tables(), TABLES | {"alembic_version"})
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

    def test_0002_with_data(self) -> None:
        """0002_accounts on a database with a user and an old-style session, and back."""
        command.upgrade(self.cfg, "0001_base")
        user = self.db.fetch("INSERT INTO users (username, password_hash) VALUES ('rita', 'x') RETURNING id")[0][0]
        self.db.fetch("INSERT INTO sessions (user_id, refresh_token, expires_at) VALUES ($1, 'old', now())", user)
        command.upgrade(self.cfg, "0002_accounts")
        row = self.db.fetch("SELECT server_admin, totp_last_step FROM users")[0]
        self.assertEqual(tuple(row), (False, None))
        self.assertEqual(self.db.fetch("SELECT mfa FROM sessions")[0][0], False)  # kept, with the new default
        with self.assertRaisesRegex(Exception, "ck_users_username_lower"):
            self.db.fetch("INSERT INTO users (username, password_hash) VALUES ('Rita2', 'x')")
        self.db.fetch("INSERT INTO refresh_tokens (session_id, token_hash) SELECT id, repeat('a', 64) FROM sessions")
        # Down again: sessions cannot keep their tokens in the 0001 schema, so they go; users stay.
        command.downgrade(self.cfg, "0001_base")
        self.assertEqual(self.db.fetch("SELECT count(*) FROM sessions")[0][0], 0)
        self.assertEqual(self.db.fetch("SELECT username FROM users")[0][0], "rita")
        self.db.fetch("DELETE FROM users")

    def test_0003_with_data(self) -> None:
        """0003_personal_data gives earlier accounts their account consent, and goes back."""
        command.upgrade(self.cfg, "0002_accounts")
        self.db.fetch("INSERT INTO users (username, password_hash, gdpr_consent_at) "
                      "VALUES ('rita', 'x', '2026-10-01T10:00:00Z'), ('joana', 'x', NULL)")
        command.upgrade(self.cfg, "0003_personal_data")
        rows = self.db.fetch("SELECT u.username, c.purpose, c.notice_version, c.given_at = u.gdpr_consent_at AS same, "
                             "c.withdrawn_at FROM consents c JOIN users u ON u.id = c.user_id")
        self.assertEqual([tuple(r) for r in rows], [("rita", "account", "before-0003", True, None)])
        # One live consent per account and purpose; a withdrawn one may sit beside it.
        with self.assertRaisesRegex(Exception, "uq_consents_live"):
            self.db.fetch("INSERT INTO consents (user_id, purpose, notice_version) "
                          "SELECT id, 'account', 'v2' FROM users WHERE username = 'rita'")
        self.db.fetch("INSERT INTO consents (user_id, purpose, notice_version, withdrawn_at) "
                      "SELECT id, 'account', 'v0', now() FROM users WHERE username = 'rita'")
        command.downgrade(self.cfg, "0002_accounts")
        self.assertEqual(self.db.fetch("SELECT count(*) FROM users WHERE gdpr_consent_at IS NOT NULL")[0][0], 1)
        self.db.fetch("DELETE FROM users")

    def test_0004_with_data(self) -> None:
        """0004_sync: the unique keys of games and events, and back down with the data."""
        command.upgrade(self.cfg, "0004_sync")
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        game = self.db.fetch("INSERT INTO games (field_id, game_id, game_seed, name, mode_id, teams, state, "
                             "controller_created_at) VALUES ($1, 7, 4294967295, 'g', 'm', '[\"red\"]', 'ready', now()) "
                             "RETURNING id", field)[0][0]
        with self.assertRaisesRegex(Exception, "uq_games_field_id_game_id_game_seed"):
            self.db.fetch("INSERT INTO games (field_id, game_id, game_seed, name, mode_id, teams, state, "
                          "controller_created_at) VALUES ($1, 7, 4294967295, 'g', 'm', '[]', 'ready', now())", field)
        with self.assertRaisesRegex(Exception, "ck_games_state"):
            self.db.fetch("INSERT INTO games (field_id, game_id, game_seed, name, mode_id, teams, state, "
                          "controller_created_at) VALUES ($1, 8, 1, 'g', 'm', '[]', 'archived', now())", field)
        insert = ("INSERT INTO game_events (game, node_id, seq, game_time_ms, event_type, priority) "
                  "VALUES ($1, 3, 1, 100, 'zone.captured', 'normal')")
        self.db.fetch(insert, game)
        with self.assertRaisesRegex(Exception, "uq_game_events_game_node_id_seq_game_time_ms_event_type"):
            self.db.fetch(insert, game)
        with self.assertRaisesRegex(Exception, "ck_game_node_scores_value"):
            self.db.fetch("INSERT INTO game_node_scores (game, source, team, value) VALUES ($1, 'node-3', 'red', -1)",
                          game)
        command.downgrade(self.cfg, "0003_personal_data")
        self.assertNotIn("games", self.tables())
        self.db.fetch("DELETE FROM fields")

    def test_0005_with_data(self) -> None:
        """0005_chrono: per-field consents beside the account consent, the registry's keys and checks, and
        back down (the per-field consents go, the account consent stays)."""
        command.upgrade(self.cfg, "0004_sync")
        user = self.db.fetch("INSERT INTO users (username, password_hash) VALUES ('rita', 'x') RETURNING id")[0][0]
        self.db.fetch("INSERT INTO consents (user_id, purpose, notice_version) VALUES ($1, 'account', 'v1')", user)
        command.upgrade(self.cfg, "0005_chrono")
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        other = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Arena', 'arena') RETURNING id")[0][0]
        share = "INSERT INTO consents (user_id, purpose, notice_version, field_id) VALUES ($1, 'chrono_sharing', 'v1', $2)"
        self.db.fetch(share, user, field)
        self.db.fetch(share, user, other)  # one live consent per field
        with self.assertRaisesRegex(Exception, "uq_consents_live_field"):
            self.db.fetch(share, user, field)
        with self.assertRaisesRegex(Exception, "uq_consents_live"):
            self.db.fetch("INSERT INTO consents (user_id, purpose, notice_version) VALUES ($1, 'account', 'v2')", user)
        key = ("INSERT INTO marshal_keys (field_id, marshal_id, name, public_key, source, valid_from) "
               "VALUES ($1, 'm-ana', 'Ana', $2, 'controller', now()) RETURNING id")
        key_id = self.db.fetch(key, field, bytes(32))[0][0]
        with self.assertRaisesRegex(Exception, "uq_marshal_keys_field_id_marshal_id_public_key"):
            self.db.fetch(key, field, bytes(32))
        with self.assertRaisesRegex(Exception, "ck_marshal_keys_public_key"):
            self.db.fetch(key, field, bytes(31))  # a public key is 32 bytes; nothing longer (no private key) fits
        reading = ("INSERT INTO chrono_readings (field_id, reading_id, record_json, replica_id, player_id, type, "
                   "velocity_mps, bb_weight_g, energy_j, chrono_id, marshal_id, record_field_id, timestamp, series_id, "
                   "marshal_key, received_at) VALUES ($1, $2, '{}', gen_random_uuid(), 'p-1', $3, 100, 0.2, 1.0, 'c', "
                   "'m-ana', 'f', now(), gen_random_uuid(), $4, now())")
        rid = uuid.uuid4()
        self.db.fetch(reading, field, rid, "checkin", key_id)
        with self.assertRaisesRegex(Exception, "uq_chrono_readings_field_id_reading_id"):
            self.db.fetch(reading, field, rid, "checkin", key_id)
        with self.assertRaisesRegex(Exception, "ck_chrono_readings_type"):
            self.db.fetch(reading, field, uuid.uuid4(), "guess", key_id)
        command.downgrade(self.cfg, "0004_sync")
        self.assertNotIn("chrono_readings", self.tables())
        rows = self.db.fetch("SELECT purpose FROM consents")
        self.assertEqual([r[0] for r in rows], ["account"])
        self.db.fetch("DELETE FROM consents")
        self.db.fetch("DELETE FROM fields")
        self.db.fetch("DELETE FROM users")

    def test_0006_with_data(self) -> None:
        """0006_scheduling: fields keep their rows with the page off, the schedule's checks, and back down."""
        command.upgrade(self.cfg, "0005_chrono")
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        command.upgrade(self.cfg, "0006_scheduling")
        self.assertEqual(tuple(self.db.fetch("SELECT public_page, description, address_text FROM fields")[0]),
                         (False, None, None))
        insert = ("INSERT INTO scheduled_games (field_id, title, starts_at, ends_at, status) "
                  "VALUES ($1, 'Domingo', '2030-11-09T09:00:00Z', $2, $3)")
        self.db.fetch(insert, field, datetime.datetime(2030, 11, 9, 13, tzinfo=datetime.timezone.utc), "draft")
        row = self.db.fetch("SELECT status, federation, predeclare_replicas, ical_sequence, teams FROM scheduled_games")
        self.assertEqual(tuple(row[0]), ("draft", "off", True, 0, "[]"))
        with self.assertRaisesRegex(Exception, "ck_scheduled_games_times"):
            self.db.fetch(insert, field, datetime.datetime(2030, 11, 9, 8, tzinfo=datetime.timezone.utc), "draft")
        with self.assertRaisesRegex(Exception, "ck_scheduled_games_status"):
            self.db.fetch(insert, field, datetime.datetime(2030, 11, 9, 13, tzinfo=datetime.timezone.utc),
                          "registering")  # computed from the window, never stored
        command.downgrade(self.cfg, "0005_chrono")
        self.assertNotIn("scheduled_games", self.tables())
        self.assertEqual(self.db.fetch("SELECT name FROM fields")[0][0], "Campo")
        self.db.fetch("DELETE FROM fields")

    def test_0007_with_data(self) -> None:
        """0007_registration: a field gets the controller's default rules, registrations' checks, and back down."""
        command.upgrade(self.cfg, "0006_scheduling")
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        game = self.db.fetch("INSERT INTO scheduled_games (field_id, title, starts_at, ends_at, status) VALUES "
                             "($1, 'Domingo', '2030-11-09T09:00:00Z', '2030-11-09T13:00:00Z', 'published') "
                             "RETURNING id", field)[0][0]
        command.upgrade(self.cfg, "0007_registration")
        self.assertEqual(tuple(self.db.fetch("SELECT limit_template, max_replicas FROM fields")[0]), ("portugal", 5))
        self.assertEqual(tuple(self.db.fetch("SELECT controller_game, walkins FROM scheduled_games")[0]), (None, None))
        insert = ("INSERT INTO game_registrations (scheduled_game, field_id, player_id, display_name, status) "
                  "VALUES ($1, $2, $3, 'Falcão', $4) RETURNING id")
        reg = self.db.fetch(insert, game, field, "p-abcdefgh2345", "registered")[0][0]
        with self.assertRaisesRegex(Exception, "uq_game_registrations_scheduled_game_player_id"):
            self.db.fetch(insert, game, field, "p-abcdefgh2345", "registered")
        with self.assertRaisesRegex(Exception, "ck_game_registrations_status"):
            self.db.fetch(insert, game, field, "p-zzzzzzzzzzzz", "maybe")
        decl = ("INSERT INTO registration_replicas (registration, declaration_id, replica_type, replica_class, "
                "position, state) VALUES ($1, $2, 'aeg', 'rifle', 0, $3)")
        did = uuid.uuid4()
        self.db.fetch(decl, reg, did, None)
        with self.assertRaisesRegex(Exception, "uq_registration_replicas_declaration_id"):
            self.db.fetch(decl, reg, did, None)
        with self.assertRaisesRegex(Exception, "ck_registration_replicas_state"):
            self.db.fetch(decl, reg, uuid.uuid4(), "chronographed")
        self.db.fetch("DELETE FROM scheduled_games")  # registrations and their replicas go with the game
        self.assertEqual(self.db.fetch("SELECT count(*) FROM registration_replicas")[0][0], 0)
        command.downgrade(self.cfg, "0006_scheduling")
        self.assertNotIn("game_registrations", self.tables())
        self.assertEqual(self.db.fetch("SELECT name FROM fields")[0][0], "Campo")
        self.db.fetch("DELETE FROM fields")

    def test_0008_with_data(self) -> None:
        """0008_integrations: a field's platform link (off by default) and a game's external link, and back."""
        command.upgrade(self.cfg, "0007_registration")
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        game = self.db.fetch("INSERT INTO scheduled_games (field_id, title, starts_at, ends_at, status) VALUES "
                             "($1, 'Domingo', '2030-11-09T09:00:00Z', '2030-11-09T13:00:00Z', 'published') "
                             "RETURNING id", field)[0][0]
        command.upgrade(self.cfg, "0008_integrations")
        self.db.fetch("INSERT INTO platform_links (field_id, adapter_id) VALUES ($1, 'test')", field)
        self.assertEqual(tuple(self.db.fetch("SELECT enabled, config_enc FROM platform_links")[0]), (False, None))
        with self.assertRaisesRegex(Exception, "uq_platform_links_field_id_adapter_id"):
            self.db.fetch("INSERT INTO platform_links (field_id, adapter_id) VALUES ($1, 'test')", field)
        self.db.fetch("INSERT INTO external_game_links (scheduled_game_id, adapter_id, external_ref) "
                      "VALUES ($1, 'test', 'ev-1')", game)
        self.db.fetch("DELETE FROM scheduled_games")  # the external links go with the game
        self.assertEqual(self.db.fetch("SELECT count(*) FROM external_game_links")[0][0], 0)
        command.downgrade(self.cfg, "0007_registration")
        self.assertNotIn("platform_links", self.tables())
        self.assertNotIn("external_game_links", self.tables())
        self.db.fetch("DELETE FROM fields")

    def test_0009_with_data(self) -> None:
        """0009_clubs: a club with a member and a report, a field's branding and saved team, and back."""
        command.upgrade(self.cfg, "0008_integrations")
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        user = self.db.fetch("INSERT INTO users (username, password_hash) VALUES ('rita', 'x') RETURNING id")[0][0]
        command.upgrade(self.cfg, "0009_clubs")
        sha = "ab" * 32
        self.db.fetch("INSERT INTO branding_images (sha256, content_type, width, height, bytes, data) "
                      "VALUES ($1, 'image/png', 16, 16, 3, 'abc')", sha)
        club = self.db.fetch("INSERT INTO clubs (name, short_name, slug, crest_sha256, created_by) "
                             "VALUES ('Lobos', 'Lobos', 'lobos', $1, $2) RETURNING id", sha, user)[0][0]
        self.assertEqual(self.db.fetch("SELECT public_page FROM clubs")[0][0], False)  # off by default
        self.db.fetch("INSERT INTO club_members (club_id, user_id) VALUES ($1, $2)", club, user)
        self.assertEqual(tuple(self.db.fetch("SELECT role, accepted_at FROM club_members")[0]), ("member", None))
        with self.assertRaisesRegex(Exception, "ck_club_members_role"):
            self.db.fetch("UPDATE club_members SET role = 'owner'")
        with self.assertRaisesRegex(Exception, "ck_clubs_colour"):
            self.db.fetch("UPDATE clubs SET colour = 'red'")
        self.db.fetch("INSERT INTO club_reports (club_id, reason) VALUES ($1, 'rights')", club)
        with self.assertRaisesRegex(Exception, "ck_field_teams_named"):
            self.db.fetch("INSERT INTO field_teams (field_id) VALUES ($1)", field)
        self.db.fetch("INSERT INTO field_teams (field_id, club_id) VALUES ($1, $2)", field, club)
        self.db.fetch("UPDATE fields SET accent = '#1e6b3a', logo_sha256 = $1", sha)
        with self.assertRaisesRegex(Exception, "ck_fields_accent"):
            self.db.fetch("UPDATE fields SET accent = '#1E6B3A'")
        with self.assertRaisesRegex(Exception, "fk_clubs_crest_sha256_branding_images"):
            self.db.fetch("DELETE FROM branding_images")  # an image in use cannot go
        self.db.fetch("DELETE FROM users")  # the account's membership goes; the club stays, unlinked
        self.assertEqual(self.db.fetch("SELECT count(*) FROM club_members")[0][0], 0)
        self.assertIsNone(self.db.fetch("SELECT created_by FROM clubs")[0][0])
        self.db.fetch("DELETE FROM clubs")  # its reports and the fields' teams of it go with it
        self.assertEqual(self.db.fetch("SELECT count(*) FROM club_reports")[0][0], 0)
        self.assertEqual(self.db.fetch("SELECT count(*) FROM field_teams")[0][0], 0)
        command.downgrade(self.cfg, "0008_integrations")
        for table in ("clubs", "club_members", "club_reports", "field_teams", "branding_images"):
            self.assertNotIn(table, self.tables())
        self.assertEqual(self.db.fetch("SELECT name FROM fields")[0][0], "Campo")
        self.db.fetch("DELETE FROM fields")

    def test_0010_with_data(self) -> None:
        """0010_firmware: a release, its checks, an account's deletion, and back."""
        command.upgrade(self.cfg, "0009_clubs")
        user = self.db.fetch("INSERT INTO users (username, password_hash) VALUES ('rita', 'x') RETURNING id")[0][0]
        command.upgrade(self.cfg, "0010_firmware")
        insert = ("INSERT INTO firmware_releases (platform, version, size, sha256, signature, key_id, added_by) "
                  "VALUES ('esp32s3', $1, $2, $3, $4, 'abcdef0123456789', $5)")
        self.db.fetch(insert, "0.4.0", 1024, "ab" * 32, "A" * 88, user)
        with self.assertRaisesRegex(Exception, "uq_firmware_releases_platform_version"):
            self.db.fetch(insert, "0.4.0", 1024, "cd" * 32, "A" * 88, user)
        with self.assertRaisesRegex(Exception, "ck_firmware_releases_sha256"):
            self.db.fetch(insert, "0.4.1", 1024, "AB" * 32, "A" * 88, user)
        with self.assertRaisesRegex(Exception, "ck_firmware_releases_size"):
            self.db.fetch(insert, "0.4.2", 0, "ab" * 32, "A" * 88, user)
        self.db.fetch("DELETE FROM users")  # the release stays, unlinked from who added it
        self.assertIsNone(self.db.fetch("SELECT added_by FROM firmware_releases")[0][0])
        command.downgrade(self.cfg, "0009_clubs")
        self.assertNotIn("firmware_releases", self.tables())

    def test_0011_with_data(self) -> None:
        """0011_history: the per-field settings' ranges, one scenario per id and field, revisions and samples
        going with their scenario and game, and back down (the field and its game stay)."""
        command.upgrade(self.cfg, "0011_history")
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        self.db.fetch("INSERT INTO field_history_settings (field_id) VALUES ($1)", field)
        row = self.db.fetch("SELECT spectator_delay_s, retention_days FROM field_history_settings")[0]
        self.assertEqual(tuple(row), (60, 730))
        for column, value, check in (("spectator_delay_s", 3601, "ck_field_history_settings_delay"),
                                     ("retention_days", 731, "ck_field_history_settings_retention"),
                                     ("retention_days", 29, "ck_field_history_settings_retention")):
            with self.subTest(column=column, value=value), self.assertRaisesRegex(Exception, check):
                self.db.fetch(f"UPDATE field_history_settings SET {column} = $1", value)
        scenario = self.db.fetch("INSERT INTO field_scenarios (field_id, scenario_id, revision) "
                                 "VALUES ($1, 'org.club.fox', 1) RETURNING id", field)[0][0]
        with self.assertRaisesRegex(Exception, "uq_field_scenarios_field_id_scenario_id"):
            self.db.fetch("INSERT INTO field_scenarios (field_id, scenario_id, revision) "
                          "VALUES ($1, 'org.club.fox', 1)", field)
        self.db.fetch("INSERT INTO field_scenario_revisions (scenario, revision, version, name, manifest, "
                      "manifest_sha256) VALUES ($1, 1, '1', 'Fox', 'id: org.club.fox', repeat('a', 64))", scenario)
        game = self.db.fetch("INSERT INTO games (field_id, game_id, game_seed, name, mode_id, teams, state, "
                             "controller_created_at) VALUES ($1, 7, 1, 'g', 'm', '[\"red\"]', 'ended', now()) "
                             "RETURNING id", field)[0][0]
        self.db.fetch("INSERT INTO game_score_samples (game, source, team, value) "
                      "VALUES ($1, 'node-3', 'red', 5)", game)
        self.db.fetch("DELETE FROM field_scenarios")
        self.assertEqual(self.db.fetch("SELECT count(*) FROM field_scenario_revisions")[0][0], 0)
        self.db.fetch("DELETE FROM games")
        self.assertEqual(self.db.fetch("SELECT count(*) FROM game_score_samples")[0][0], 0)
        command.downgrade(self.cfg, "0010_firmware")
        for table in ("field_history_settings", "game_score_samples", "field_scenarios", "field_scenario_revisions",
                      "field_presets"):
            self.assertNotIn(table, self.tables())
        self.assertEqual(self.db.fetch("SELECT name FROM fields")[0][0], "Campo")
        self.db.fetch("DELETE FROM fields")

    def test_0012_with_data(self) -> None:
        """0012_atak: one CA per field, unique serials and fingerprints, the checks, the holder unlinked when the
        account goes, everything gone with the field, and back down."""
        command.upgrade(self.cfg, "0012_atak")
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        user = self.db.fetch("INSERT INTO users (username, password_hash) VALUES ('rita', 'x') RETURNING id")[0][0]
        self.db.fetch("INSERT INTO atak_cas (field_id, cert_pem, key_sealed, ski, not_after) "
                      "VALUES ($1, 'pem', '\\x00', repeat('a', 40), now() + interval '1 year')", field)
        with self.assertRaisesRegex(Exception, "uq_atak_cas_field_id"):
            self.db.fetch("INSERT INTO atak_cas (field_id, cert_pem, key_sealed, ski, not_after) "
                          "VALUES ($1, 'pem', '\\x00', repeat('b', 40), now())", field)
        insert = ("INSERT INTO atak_certs (field_id, serial, sha256, device_name, holder_id, issued_at, not_after) "
                  "VALUES ($1, $2, $3, $4, $5, now(), now() + interval '7 days')")
        self.db.fetch(insert, field, "0a1b", "c" * 64, "Tablet 1", user)
        for serial, sha, name, check in (("0a1b", "d" * 64, "x", "uq_atak_certs_serial"),
                                         ("0a1c", "c" * 64, "x", "uq_atak_certs_sha256"),
                                         ("0A1C", "d" * 64, "x", "ck_atak_certs_serial"),
                                         ("0a1c", "D" * 64, "x", "ck_atak_certs_sha256"),
                                         ("0a1c", "d" * 64, "", "ck_atak_certs_device_name")):
            with self.subTest(check=check), self.assertRaisesRegex(Exception, check):
                self.db.fetch(insert, field, serial, sha, name, user)
        with self.assertRaisesRegex(Exception, "ck_atak_certs_lifetime"):
            self.db.fetch("INSERT INTO atak_certs (field_id, serial, sha256, device_name, issued_at, not_after) "
                          "VALUES ($1, 'ff', repeat('e', 64), 'x', now(), now())", field)
        self.db.fetch("DELETE FROM users")
        self.assertIsNone(self.db.fetch("SELECT holder_id FROM atak_certs")[0][0])
        self.db.fetch("DELETE FROM fields")
        self.assertEqual(self.db.fetch("SELECT (SELECT count(*) FROM atak_cas) + (SELECT count(*) FROM atak_certs)")
                         [0][0], 0)
        command.downgrade(self.cfg, "0011_history")
        for table in ("atak_cas", "atak_certs"):
            self.assertNotIn(table, self.tables())

    def test_0013_with_data(self) -> None:
        """0013_preview_feedback: the checks on kind, role, state and the message's length, the defaults, and
        back down."""
        command.upgrade(self.cfg, "0013_preview_feedback")
        insert = "INSERT INTO preview_feedback (kind, who, message, lang) VALUES ($1, $2, $3, 'en') RETURNING status"
        self.assertEqual(self.db.fetch(insert, "good", None, "Nice")[0][0], "new")
        self.assertEqual(self.db.fetch(insert, "bug", "staff", "x" * 2000)[0][0], "new")
        for check, args in (("ck_preview_feedback_kind", ("praise", None, "x")),
                            ("ck_preview_feedback_who", ("good", "robot", "x")),
                            ("ck_preview_feedback_message", ("good", None, "")),
                            ("ck_preview_feedback_message", ("good", None, "x" * 2001))):
            with self.subTest(check=check), self.assertRaisesRegex(Exception, check):
                self.db.fetch(insert, *args)
        with self.assertRaisesRegex(Exception, "ck_preview_feedback_status"):
            self.db.fetch("UPDATE preview_feedback SET status = 'lost'")
        command.downgrade(self.cfg, "0012_atak")
        self.assertNotIn("preview_feedback", self.tables())

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
