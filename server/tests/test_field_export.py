# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A field administrator's data export (S21-12; ``atalaia_server/field_export.py``, ``api/export.py``).

The export is the field's own data without credentials, addresses or e-mails: tested by what is in the archive
(every dataset against the database, none of the secrets, nothing of another field), who may ask, the cooldown, the
one-at-a-time lock, the size limit and the audit row. The coverage tests make a new table or column a decision.

    python3 tools/docker_server.py test tests.test_field_export
"""

from __future__ import annotations

import io
import json
import hashlib
import unittest
import unittest.mock
import uuid
import zipfile
from typing import Any, Optional

from atalaia_server import field_export
from atalaia_server.config import Settings
from atalaia_server.models import Base

from .base import METRICS_TOKEN, PASSWORD, SECRET_KEY
from .test_sync import SyncTestCase, event


class CoverageTests(unittest.TestCase):
    def test_every_table_is_exported_or_skipped(self) -> None:
        self.assertEqual(set(Base.metadata.tables) | {"alembic_version"}, field_export.covered_tables(),
                         "a new table needs a decision in field_export.py: a Dataset, or SKIPPED with the reason")

    def test_no_exported_column_looks_like_a_secret(self) -> None:
        for ds in field_export.DATASETS:
            for column in ds.columns():
                if column in field_export.NOT_SECRET:
                    continue
                for word in field_export.SECRET_WORDS:
                    self.assertNotIn(word, column, f"{ds.name}.{column} looks like a secret or an address: "
                                                   "omit it (with the reason) or add it to NOT_SECRET")

    def test_the_omitted_columns_exist_and_have_a_reason(self) -> None:
        for ds in field_export.DATASETS:
            names = {c.name for c in ds.table.columns}
            for column, reason in ds.omit.items():
                self.assertIn(column, names, ds.name)
                self.assertTrue(reason, f"{ds.name}.{column}")
        users = next(d for d in field_export.DATASETS if d.name == "users")
        self.assertEqual(set(users.omit), {"email", "password_hash", "totp_secret_enc", "totp_last_step"})


class ExportCase(SyncTestCase):
    min_interval = 0
    max_mb = 512

    def settings(self) -> Settings:
        return Settings(database_url=self.database_url, secret_key=SECRET_KEY, metrics_token=METRICS_TOKEN,
                        db_timeout_s=2.0, purge_hour=None, export_min_interval_s=self.min_interval,
                        export_max_mb=self.max_mb)

    async def admin(self, field_id: Optional[uuid.UUID] = None, role_id: int = 7) -> dict[str, str]:
        user_id, name, secret = await self.make_user(with_totp=True)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)",
                         user_id, field_id or self.field_id, role_id)
        return await self.auth(name, secret=secret)

    def url(self, field_id: Optional[uuid.UUID] = None) -> str:
        return f"/api/v1/fields/{field_id or self.field_id}/export"

    def archive(self, content: bytes) -> dict[str, bytes]:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            self.assertIsNone(zf.testzip())
            return {n: zf.read(n) for n in zf.namelist()}


class ExportTests(ExportCase):
    async def seed(self) -> None:
        await self.make_game()
        await self.events([event(1), event(2)])
        other_field, other_key = await self.make_field("campo-outro")
        await self.make_game(key=other_key, game={"game_id": 7, "game_seed": 8}, name="Jogo do vizinho")
        await self.fetch("INSERT INTO users (username, email, password_hash, totp_enabled, totp_secret_enc) "
                         "VALUES ('marta', 'marta-privada@example.pt', 'HASH-OF-MARTA', true, '\\x0102'::bytea)")
        marta = (await self.fetch("SELECT id FROM users WHERE username = 'marta'"))[0][0]
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 1)",
                         marta, self.field_id)
        await self.fetch("INSERT INTO users (username, password_hash) VALUES ('vizinho', 'HASH-OF-VIZINHO')")
        await self.fetch("INSERT INTO scheduled_games (field_id, title, starts_at, ends_at, status) VALUES ($1, "
                         "'Domingo no bosque', now() + interval '2 days', now() + interval '3 days', 'published')",
                         self.field_id)
        await self.fetch("INSERT INTO sessions (user_id, ip_address, expires_at) VALUES ($1, '203.0.113.9', "
                         "now() + interval '1 day')", marta)
        await self.fetch("INSERT INTO audit_log (user_id, action, ip_address) VALUES ($1, 'login', '203.0.113.9')",
                         marta)

    async def test_the_archive_holds_the_fields_data_and_no_secret(self) -> None:
        await self.seed()
        admin = await self.admin()
        r = await self.client.get(self.url(), headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["content-type"], "application/zip")
        self.assertIn("attachment", r.headers["content-disposition"])
        self.assertIn("campo", r.headers["content-disposition"])
        self.assertEqual(r.headers["cache-control"], "no-store")
        files = self.archive(r.content)
        manifest = json.loads(files["manifest.json"])
        self.assertEqual((manifest["format"], manifest["version"], manifest["mode"]), ("atalaia-field-data", 1, "single"))
        self.assertEqual(manifest["field"]["id"], str(self.field_id))
        self.assertIn("README.txt", files)
        # Every dataset matches the database.
        by_name = {d["name"]: d for d in manifest["datasets"]}
        self.assertNotIn("clubs", by_name)  # a single-field server's clubs are the server's
        self.assertIn("clubs", {s["table"] for s in manifest["skipped"]})
        self.assertEqual({d["file"] for d in manifest["datasets"]} | {"manifest.json", "README.txt"}, set(files))
        games = [json.loads(line) for line in files["data/games.jsonl"].decode().splitlines()]
        self.assertEqual([g["name"] for g in games], ["Domingo"])
        self.assertEqual(by_name["games"]["rows"], 1)
        self.assertEqual(by_name["game_events"]["rows"], 2)
        self.assertEqual(by_name["scheduled_games"]["rows"], 1)
        for name, entry in by_name.items():
            lines = files[entry["file"]].decode().splitlines()
            self.assertEqual(len(lines), entry["rows"], name)
            self.assertEqual(hashlib.sha256(files[entry["file"]]).hexdigest(), entry["sha256"], name)
        users = {json.loads(line)["username"] for line in files["data/users.jsonl"].decode().splitlines()}
        self.assertIn("marta", users)
        self.assertNotIn("vizinho", users)  # an account with nothing to do with this field
        # No secret, no address, no e-mail, nothing of the other field, anywhere in the archive.
        blob = b"\n".join(files.values())
        for marker in (b"HASH-OF-MARTA", b"HASH-OF-VIZINHO", b"marta-privada", b"203.0.113.9", b"Jogo do vizinho",
                       b"campo-outro"):
            self.assertNotIn(marker, blob, marker)
        data = b"\n".join(v for n, v in files.items() if n.startswith("data/"))  # the manifest names what it omits
        for marker in (b"password_hash", b"totp_secret", b"key_sha256", b"ip_address", b"ticket_hash", b"config_enc"):
            self.assertNotIn(marker, data, marker)
        # The audit log of the field's accounts is in, without the address.
        audit = [json.loads(line) for line in files["data/audit_log.jsonl"].decode().splitlines()]
        self.assertIn("login", {a["action"] for a in audit})
        self.assertTrue(all("ip_address" not in a for a in audit))

    async def test_the_export_is_audit_logged_with_its_hash(self) -> None:
        await self.make_game()
        admin = await self.admin()
        r = await self.client.get(self.url(), headers=admin)
        self.assertEqual(r.status_code, 200, r.text)
        rows = await self.fetch("SELECT user_id, resource, resource_id, details, ip_address FROM audit_log "
                                "WHERE action = 'field_export'")
        self.assertEqual(len(rows), 1)
        details = json.loads(rows[0]["details"])
        self.assertEqual(details["sha256"], r.headers["x-content-sha256"])
        self.assertEqual(details["bytes"], len(r.content))
        self.assertEqual((rows[0]["resource"], rows[0]["resource_id"]), ("field", self.field_id))
        self.assertEqual(details["rows"]["games"], 1)
        self.assertNotIn("games.jsonl", json.dumps(details))

    async def test_only_the_fields_admin(self) -> None:
        other_field, _ = await self.make_field("campo-b")
        self.assertEqual((await self.client.get(self.url())).status_code, 401)
        for role_id, name in ((1, "player"), (4, "marshal"), (5, "gm")):
            with self.subTest(role=name):
                headers = await self.admin(role_id=role_id)
                r = await self.client.get(self.url(), headers=headers)
                self.assertEqual((r.status_code, r.json()["detail"]), (403, "role_required"))
        admin_of_b = await self.admin(other_field)
        self.assertEqual((await self.client.get(self.url(), headers=admin_of_b)).status_code, 403)
        self.assertEqual((await self.client.get(self.url(other_field), headers=admin_of_b)).status_code, 200)
        r = await self.client.get(self.url(uuid.uuid4()), headers=await self.admin())
        self.assertEqual(r.status_code, 403)  # no role on a field that is not there
        self.assertEqual(await self.fetch("SELECT 1 FROM audit_log WHERE action = 'field_export' "
                                          "AND resource_id = $1", self.field_id), [])

    async def test_a_server_admin_may_export_any_field(self) -> None:
        _, name, secret = await self.make_user(server_admin=True)
        headers = await self.auth(name, secret=secret)
        self.assertEqual((await self.client.get(self.url(), headers=headers)).status_code, 200)
        self.assertEqual((await self.client.get(self.url(uuid.uuid4()), headers=headers)).status_code, 404)

    async def test_without_a_totp_session_an_admin_is_only_a_player(self) -> None:
        user_id, name, _ = await self.make_user()
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 7)",
                         user_id, self.field_id)
        headers = await self.auth(name)
        self.assertEqual((await self.client.get(self.url(), headers=headers)).status_code, 403)

    async def test_the_archive_is_consistent_with_later_changes(self) -> None:
        await self.make_game()
        admin = await self.admin()
        first = self.archive((await self.client.get(self.url(), headers=admin)).content)
        await self.events([event(1)])
        second = self.archive((await self.client.get(self.url(), headers=admin)).content)
        self.assertEqual(first["data/game_events.jsonl"], b"")
        self.assertEqual(len(second["data/game_events.jsonl"].decode().splitlines()), 1)


class LimitTests(ExportCase):
    min_interval = 300

    async def test_one_export_per_interval(self) -> None:
        admin = await self.admin()
        self.assertEqual((await self.client.get(self.url(), headers=admin)).status_code, 200)
        r = await self.client.get(self.url(), headers=admin)
        self.assertEqual((r.status_code, r.json()), (429, {"detail": "too_many_requests"}))
        self.assertTrue(250 <= int(r.headers["retry-after"]) <= 301)
        # Another field has its own interval.
        other, _ = await self.make_field("campo-b")
        self.assertEqual((await self.client.get(self.url(other), headers=await self.admin(other))).status_code, 200)

    async def test_one_at_a_time(self) -> None:
        admin = await self.admin()
        self.app.state.export_state[(None, self.field_id)] = {"running": True, "last": None}
        r = await self.client.get(self.url(), headers=admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "export_running"))
        self.app.state.export_state[(None, self.field_id)]["running"] = False
        self.assertEqual((await self.client.get(self.url(), headers=admin)).status_code, 200)

    async def test_a_failed_export_does_not_leave_the_lock(self) -> None:
        admin = await self.admin()
        with unittest.mock.patch.object(field_export, "build", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                await self.client.get(self.url(), headers=admin)
        self.assertFalse(self.app.state.export_state[(None, self.field_id)]["running"])


class SizeTests(ExportCase):
    max_mb = 1

    async def test_too_large_is_refused(self) -> None:
        await self.make_game()
        game = (await self.fetch("SELECT id FROM games"))[0][0]
        await self.fetch("INSERT INTO game_events (game, node_id, seq, game_time_ms, event_type, priority, data) "
                         "SELECT $1, 1, g, g, 'zone.captured', 'normal', jsonb_build_object('pad', repeat('x', 1000)) "
                         "FROM generate_series(1, 1500) g", game)
        r = await self.client.get(self.url(), headers=await self.admin())
        self.assertEqual((r.status_code, r.json()["detail"]), (413, "export_too_large"))
        self.assertEqual(await self.fetch("SELECT 1 FROM audit_log WHERE action = 'field_export'"), [])


if __name__ == "__main__":
    unittest.main()
