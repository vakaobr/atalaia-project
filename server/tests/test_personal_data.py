# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Personal data on PostgreSQL 16: access, export, rectification, erasure, consents, the purge (ADR-P4-8)."""

from __future__ import annotations

import asyncio
import dataclasses
import io
import json
import os
import unittest
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from atalaia_server import cli, personal_data
from atalaia_server.api.auth import COOKIE
from atalaia_server.app import create_app
from atalaia_server.config import DEFAULT_NOTICE_VERSION
from atalaia_server.ratelimit import Limits

from .base import PASSWORD, SECRET_KEY, AppTestCase

# Plan phase 14's to 17's counts.
NO_CHRONO = {"chrono_readings": 0, "chrono_rejects": 0, "replicas": 0, "marshal_keys": 0, "scheduled_games": 0,
             "federation_numbers": 0, "player_id_claims": 0, "imported_registrations": 0}

NEW_PASSWORD = "a different long passphrase 7"


def bearer(session: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


class PersonalDataTestCase(AppTestCase):
    async def register(self, username: str, email: str | None = None) -> dict[str, Any]:
        r = await self.client.post("/api/v1/auth/register", json={"username": username, "password": PASSWORD,
                                                                  "email": email, "consent": True})
        assert r.status_code == 201, r.text
        return r.json()

    async def field(self, name: str = "Campo Tejo") -> uuid.UUID:
        return (await self.fetch("INSERT INTO fields (name, slug) VALUES ($1, $2) RETURNING id",
                                 name, name.lower().replace(" ", "-")))[0][0]

    async def grant(self, field_id: uuid.UUID, user_id: uuid.UUID, role: str = "player") -> None:
        """A role granted by the field's admin through the API, so the audit log has it as someone else's act."""
        admin_id, admin, secret = await self.make_user(with_totp=True)
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 7)",
                         admin_id, field_id)
        username = (await self.fetch("SELECT username FROM users WHERE id = $1", user_id))[0][0]
        r = await self.client.put(f"/api/v1/fields/{field_id}/roles", json={"username": username, "role": role},
                                  headers=await self.auth(admin, secret=secret))
        assert r.status_code == 201, r.text

    async def audit(self, action: str) -> list[Any]:
        return await self.fetch("SELECT user_id, resource_id, details, host(ip_address) AS ip FROM audit_log "
                                "WHERE action = $1 ORDER BY id", action)


class AccessTests(PersonalDataTestCase):
    async def test_everything_held_about_the_account(self) -> None:
        user = await self.register("rita", "rita@example.pt")
        user_id = uuid.UUID(user["id"])
        await self.grant(await self.field(), user_id)
        await self.client.post("/api/v1/auth/login", json={"username": "rita", "password": "not the password"})
        first = await self.login("rita")
        current = await self.login("rita", client=self.other_client())
        _, stranger, _ = await self.make_user()
        await self.login(stranger)

        r = await self.client.get("/api/v1/me/data", headers=bearer(current))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        data = r.json()
        self.assertEqual(set(data), {"format", "generated_at", "user", "field_roles", "sessions", "audit_log",
                                     "audit_log_about_you", "consents", "games", "player_ids", "chrono_records",
                                     "marshal_keys", "scheduled_games", "registrations", "player_id_claims"})
        self.assertEqual(data["format"], "atalaia-personal-data/1")
        self.assertEqual((data["user"]["id"], data["user"]["username"], data["user"]["email"]),
                         (user["id"], "rita", "rita@example.pt"))
        self.assertIsNotNone(data["user"]["gdpr_consent_at"])
        self.assertEqual(data["field_roles"], [{"field_id": data["field_roles"][0]["field_id"], "field": "Campo Tejo",
                                                "role": "player", "granted_at": data["field_roles"][0]["granted_at"]}])
        sessions = {s["id"]: s for s in data["sessions"]}
        self.assertEqual(len(sessions), 2)
        self.assertEqual(sum(s["current"] for s in sessions.values()), 1)
        self.assertEqual({s["ip_address"] for s in sessions.values()}, {"127.0.0.1"})
        actions = [a["action"] for a in data["audit_log"]]
        self.assertEqual(actions, ["register", "login_failed", "login", "login"])
        self.assertEqual(data["audit_log"][1]["ip_address"], "127.0.0.1")
        # What the field's admin did to the account: what and when, not who or from where.
        self.assertEqual([(a["action"], a["details"]["role"]) for a in data["audit_log_about_you"]],
                         [("role_grant", "player")])
        self.assertEqual(set(data["audit_log_about_you"][0]), {"id", "action", "details", "created_at"})
        self.assertEqual([(c["purpose"], c["notice_version"], c["withdrawn_at"]) for c in data["consents"]],
                         [("account", DEFAULT_NOTICE_VERSION, None)])
        # Never the credentials, never anyone else.
        row = (await self.fetch("SELECT password_hash FROM users WHERE id = $1", user_id))[0]
        self.assertNotIn(row["password_hash"], r.text)
        self.assertNotIn("totp_secret", r.text)
        self.assertNotIn(stranger, r.text)
        self.assertTrue(first["access_token"])

    async def test_every_route_needs_a_login(self) -> None:
        for method, path in (("GET", "/api/v1/me/data"), ("GET", "/api/v1/me/export"), ("PATCH", "/api/v1/me"),
                             ("POST", "/api/v1/me/password"), ("DELETE", "/api/v1/me")):
            with self.subTest(method=method, path=path):
                r = await self.client.request(method, path, json={"password": PASSWORD})
                self.assertEqual(r.status_code, 401)

    async def test_export(self) -> None:
        await self.register("joana")
        session = await self.login("joana")
        data = (await self.client.get("/api/v1/me/data", headers=bearer(session))).json()
        r = await self.client.get("/api/v1/me/export", headers=bearer(session))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-type"], "application/zip")
        self.assertRegex(r.headers["content-disposition"], r'^attachment; filename="atalaia-export-joana-\d{8}\.zip"$')
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertIsNone(zf.testzip())
            names = sorted(zf.namelist())
            self.assertEqual(names, sorted(f"export/{n}" for n in (
                "profile.json", "field_roles.json", "sessions.json", "audit_log.json", "audit_log_about_you.json",
                "consents.json", "games.json", "player_ids.json", "chrono_records.json", "marshal_keys.json",
                "scheduled_games.json", "registrations.json", "player_id_claims.json", "README.txt")))
            files = {n: zf.read(n).decode("utf-8") for n in names}
        self.assertEqual(json.loads(files["export/profile.json"]), data["user"])
        self.assertEqual(json.loads(files["export/consents.json"]), data["consents"])
        self.assertEqual([a["action"] for a in json.loads(files["export/audit_log.json"])], ["register", "login"])
        self.assertIn("atalaia-personal-data/1", files["export/README.txt"])
        self.assertIn("joana", files["export/README.txt"])


class RectificationTests(PersonalDataTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.user = await self.register("rita", "rita@example.pt")
        self.headers = bearer(await self.login("rita"))

    async def patch(self, **body: Any) -> httpx.Response:
        return await self.client.patch("/api/v1/me", json={"password": PASSWORD, **body}, headers=self.headers)

    async def test_new_username_and_email(self) -> None:
        r = await self.patch(username=" Rita.Silva ", email="RITA@novo.pt")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["username"], r.json()["email"]), ("rita.silva", "rita@novo.pt"))
        audit = await self.audit("profile_update")
        self.assertEqual(json.loads(audit[0]["details"]), {"fields": ["email", "username"]})
        text = json.dumps([dict(a) for a in await self.fetch("SELECT * FROM audit_log")], default=str)
        self.assertNotIn("novo.pt", text)  # which fields changed, never the values
        self.assertIn("access_token", await self.login("rita.silva"))
        r = await self.client.post("/api/v1/auth/login", json={"username": "rita", "password": PASSWORD})
        self.assertEqual(r.status_code, 401)

    async def test_the_email_can_be_removed(self) -> None:
        for value in (None, ""):
            with self.subTest(value=value):
                r = await self.patch(email=value)
                self.assertEqual((r.status_code, r.json()["email"]), (200, None))
        # Nothing given, nothing changed (and nothing logged).
        r = await self.patch()
        self.assertEqual((r.status_code, r.json()["username"]), (200, "rita"))
        self.assertEqual(len(await self.audit("profile_update")), 1)

    async def test_refusals(self) -> None:
        await self.register("joana", "joana@example.pt")
        for body, status, code in (({"password": "not my password", "email": "x@y.pt"}, 403, "invalid_password"),
                                   ({"username": "ab"}, 400, "username_invalid"),
                                   ({"username": "deleted-0123abcd"}, 400, "username_reserved"),
                                   ({"email": "nope"}, 400, "email_invalid"),
                                   ({"username": "JOANA"}, 409, "username_or_email_taken"),
                                   ({"email": "joana@example.pt"}, 409, "username_or_email_taken"),
                                   ({"username": "correct.horse"}, 200, None)):
            with self.subTest(body=body):
                r = await self.patch(**body)
                self.assertEqual(r.status_code, status, r.text)
                if code:
                    self.assertEqual(r.json()["detail"], code)
        row = (await self.fetch("SELECT username, email FROM users WHERE id = $1", uuid.UUID(self.user["id"])))[0]
        self.assertEqual(tuple(row), ("correct.horse", "rita@example.pt"))

    async def test_the_password_may_not_become_the_username(self) -> None:
        password = "fernando.pessoa"
        _, name, _ = await self.make_user(password=password)
        headers = await self.auth(name, password=password)
        r = await self.client.patch("/api/v1/me", json={"password": password, "username": "Fernando.Pessoa"},
                                    headers=headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "password_is_username"))

    async def test_registration_refuses_reserved_names(self) -> None:
        r = await self.client.post("/api/v1/auth/register", json={"username": "deleted-cafe", "password": PASSWORD,
                                                                  "consent": True})
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "username_reserved"))


class PasswordChangeTests(PersonalDataTestCase):
    async def test_change_ends_the_other_sessions(self) -> None:
        user_id, name, _ = await self.make_user()
        here = bearer(await self.login(name))
        elsewhere = bearer(await self.login(name, client=self.other_client()))
        r = await self.client.post("/api/v1/me/password", json={"password": PASSWORD, "new_password": NEW_PASSWORD},
                                   headers=here)
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual((await self.client.get("/api/v1/me", headers=here)).status_code, 200)
        self.assertEqual((await self.client.get("/api/v1/me", headers=elsewhere)).status_code, 401)
        self.assertIn("access_token", await self.login(name, password=NEW_PASSWORD))
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        self.assertEqual(r.status_code, 401)
        audit = await self.audit("password_change")
        self.assertEqual((audit[0]["user_id"], json.loads(audit[0]["details"])), (user_id, {"sessions_ended": 1}))
        self.assertNotIn(NEW_PASSWORD, json.dumps([dict(a) for a in await self.fetch("SELECT * FROM audit_log")],
                                                  default=str))

    async def test_refusals(self) -> None:
        _, name, _ = await self.make_user()
        headers = await self.auth(name)
        for body, status, code in (({"password": "wrong password", "new_password": NEW_PASSWORD}, 403,
                                    "invalid_password"),
                                   ({"password": PASSWORD, "new_password": "basketball"}, 400, "password_breached"),
                                   ({"password": PASSWORD, "new_password": "short"}, 400, "password_too_short"),
                                   ({"password": PASSWORD, "new_password": name}, 400, "password_is_username")):
            with self.subTest(code=code):
                r = await self.client.post("/api/v1/me/password", json=body, headers=headers)
                self.assertEqual((r.status_code, r.json()["detail"]), (status, code))
        self.assertIn("access_token", await self.login(name))

    async def test_guessing_the_current_password_is_locked_out(self) -> None:
        self.app.state.limits = Limits()
        _, name, _ = await self.make_user()
        headers = await self.auth(name)
        for _ in range(5):
            r = await self.client.post("/api/v1/me/password", json={"password": "a wrong guess",
                                                                    "new_password": NEW_PASSWORD}, headers=headers)
            self.assertEqual(r.status_code, 403)
        r = await self.client.post("/api/v1/me/password", json={"password": PASSWORD, "new_password": NEW_PASSWORD},
                                   headers=headers)
        self.assertEqual(r.status_code, 429)


class ErasureTests(PersonalDataTestCase):
    async def erase(self, headers: dict[str, str], **body: Any) -> httpx.Response:
        return await self.client.request("DELETE", "/api/v1/me", json={"password": PASSWORD, **body},
                                         headers=headers)

    async def test_erasure_anonymises(self) -> None:
        user = await self.register("rita", "rita@example.pt")
        user_id = uuid.UUID(user["id"])
        field_id = await self.field()
        await self.grant(field_id, user_id, "player")
        await self.client.post("/api/v1/auth/login", json={"username": "rita", "password": "not the password"})
        session = await self.login("rita")
        headers = bearer(session)
        await self.login("rita", client=self.other_client())

        r = await self.erase(headers)
        self.assertEqual(r.status_code, 204, r.text)
        self.assertIn(COOKIE, r.headers["set-cookie"])
        self.assertIn("max-age=0", r.headers["set-cookie"].lower())
        row = (await self.fetch("SELECT * FROM users WHERE id = $1", user_id))[0]
        self.assertRegex(row["username"], r"^deleted-[0-9a-f]{16}$")
        self.assertEqual((row["email"], row["password_hash"], row["totp_secret_enc"], row["gdpr_consent_at"],
                          row["last_login_at"], row["server_admin"]), (None, "DELETED", None, None, None, False))
        for table in ("user_field_roles", "sessions", "consents"):
            with self.subTest(table=table):
                n = (await self.fetch(f"SELECT count(*) FROM {table} WHERE user_id = $1", user_id))[0][0]
                self.assertEqual(n, 0)
        self.assertEqual((await self.fetch("SELECT count(*) FROM refresh_tokens"))[0][0],
                         (await self.fetch("SELECT count(*) FROM refresh_tokens r JOIN sessions s ON s.id = r.session_id "
                                           "WHERE s.user_id <> $1", user_id))[0][0])
        # The log keeps what happened, without the addresses; the erasure itself names no one.
        own = await self.fetch("SELECT action, ip_address FROM audit_log WHERE user_id = $1 ORDER BY id", user_id)
        self.assertEqual([a["action"] for a in own], ["register", "login_failed", "login", "login"])
        self.assertTrue(all(a["ip_address"] is None for a in own))
        erasure = await self.audit("gdpr_erasure")
        self.assertEqual((erasure[0]["user_id"], erasure[0]["resource_id"], erasure[0]["ip"]), (None, user_id, None))
        self.assertEqual(json.loads(erasure[0]["details"]), {"reason": "user_request"})
        text = json.dumps([dict(a) for a in await self.fetch("SELECT * FROM audit_log")], default=str)
        self.assertNotIn("rita", text)
        # Gone for good: the token, the login; the name is free again.
        self.assertEqual((await self.client.get("/api/v1/me", headers=headers)).status_code, 401)
        r = await self.client.post("/api/v1/auth/login", json={"username": "rita", "password": PASSWORD})
        self.assertEqual(r.status_code, 401)
        r = await self.client.post("/api/v1/auth/login", json={"username": row["username"], "password": "DELETED"})
        self.assertEqual(r.status_code, 401)
        self.assertNotEqual((await self.register("rita", "rita@example.pt"))["id"], user["id"])

    async def test_nothing_changes_without_the_password(self) -> None:
        user_id, name, _ = await self.make_user()
        headers = await self.auth(name)
        r = await self.erase(headers, password="not my password")
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_password"))
        self.assertEqual((await self.fetch("SELECT username FROM users WHERE id = $1", user_id))[0][0], name)

    async def test_an_account_with_totp_needs_a_code(self) -> None:
        user_id, name, secret = await self.make_user(with_totp=True)
        headers = await self.auth(name, secret=secret)
        r = await self.erase(headers)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "code_required"))
        r = await self.erase(headers, code="000000")
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_code"))
        r = await self.erase(headers, code=self.code(secret))
        self.assertEqual(r.status_code, 204, r.text)
        row = (await self.fetch("SELECT username, totp_enabled, totp_secret_enc FROM users WHERE id = $1", user_id))[0]
        self.assertTrue(row["username"].startswith("deleted-"))
        self.assertEqual((row["totp_enabled"], row["totp_secret_enc"]), (False, None))

    async def test_the_last_server_administrator_stays(self) -> None:
        first_id, first, first_secret = await self.make_user(server_admin=True)
        headers = await self.auth(first, secret=first_secret)
        r = await self.erase(headers, code=self.code(first_secret))
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "last_server_admin"))
        _, second, second_secret = await self.make_user(server_admin=True)
        r = await self.erase(headers, code=self.code(first_secret))
        self.assertEqual(r.status_code, 204, r.text)
        headers = await self.auth(second, secret=second_secret)
        r = await self.erase(headers, code=self.code(second_secret))
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "last_server_admin"))
        self.assertFalse((await self.fetch("SELECT server_admin FROM users WHERE id = $1", first_id))[0][0])


class PurgeTests(PersonalDataTestCase):
    async def test_purge_follows_the_retention_table(self) -> None:
        user_id, _, _ = await self.make_user()
        now = datetime.now(timezone.utc)
        sessions = {}
        for name, expires, revoked in (("expired_long_ago", now - timedelta(days=31), None),
                                       ("expired_recently", now - timedelta(days=29), None),
                                       ("revoked_long_ago", now + timedelta(days=3), now - timedelta(days=31)),
                                       ("revoked_recently", now + timedelta(days=3), now - timedelta(days=1)),
                                       ("live", now + timedelta(days=7), None)):
            sessions[name] = (await self.fetch(
                "INSERT INTO sessions (user_id, expires_at, revoked_at) VALUES ($1, $2, $3) RETURNING id",
                user_id, expires, revoked))[0][0]
            await self.fetch("INSERT INTO refresh_tokens (session_id, token_hash) VALUES ($1, $2)",
                             sessions[name], name.ljust(64, "0"))
        for days in (1096, 1094):
            await self.fetch("INSERT INTO audit_log (action, created_at) VALUES ('login', $1)", now - timedelta(days=days))

        async with self.app.state.sessionmaker() as db:
            self.assertEqual(await personal_data.purge(db, now, dry_run=True),
                             {"sessions": 2, "audit_log": 1, "games": 0, **NO_CHRONO})
        self.assertEqual((await self.fetch("SELECT count(*) FROM sessions"))[0][0], 5)
        async with self.app.state.sessionmaker() as db:
            self.assertEqual(await personal_data.purge(db, now),
                             {"sessions": 2, "audit_log": 1, "games": 0, **NO_CHRONO})
        left = {r[0] for r in await self.fetch("SELECT id FROM sessions")}
        self.assertEqual(left, {sessions[n] for n in ("expired_recently", "revoked_recently", "live")})
        self.assertEqual((await self.fetch("SELECT count(*) FROM refresh_tokens"))[0][0], 3)
        self.assertEqual((await self.fetch("SELECT count(*) FROM audit_log WHERE action = 'login'"))[0][0], 1)
        purges = await self.audit("retention_purge")
        self.assertEqual(json.loads(purges[0]["details"]), {"sessions": 2, "audit_log": 1, "games": 0, **NO_CHRONO})
        async with self.app.state.sessionmaker() as db:  # again: nothing left to do
            self.assertEqual(await personal_data.purge(db, now),
                             {"sessions": 0, "audit_log": 0, "games": 0, **NO_CHRONO})

    async def test_the_command(self) -> None:
        user_id, _, _ = await self.make_user()
        await self.fetch("INSERT INTO sessions (user_id, expires_at) VALUES ($1, now() - interval '40 days')", user_id)
        saved = {k: os.environ.get(k) for k in ("ATALAIA_DATABASE_URL", "ATALAIA_SECRET_KEY")}
        os.environ.update({"ATALAIA_DATABASE_URL": self.database_url, "ATALAIA_SECRET_KEY": SECRET_KEY})
        try:
            outputs = []
            for argv in (["purge", "--dry-run"], ["purge"]):
                out = io.StringIO()
                code = await asyncio.to_thread(cli.main, argv, io.StringIO(), out, io.StringIO())
                self.assertEqual(code, 0)
                outputs.append(out.getvalue())
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        rest = (", 0 chrono readings rows, 0 chrono rejects rows, 0 replicas rows, 0 marshal keys rows, "
                "0 scheduled games rows, 0 federation numbers rows, 0 player id claims rows, "
                "0 imported registrations rows\n")
        self.assertEqual(outputs, ["Retention purge would delete: 1 sessions rows, 0 audit log rows, 0 games rows" + rest,
                                   "Retention purge deleted: 1 sessions rows, 0 audit log rows, 0 games rows" + rest])
        self.assertEqual((await self.fetch("SELECT count(*) FROM sessions"))[0][0], 0)

    async def test_the_daily_task(self) -> None:
        """``purge_daily`` sleeps until the hour, purges, and goes on until cancelled."""
        just_before = datetime(2026, 10, 19, 2, 59, 59, 900000, tzinfo=timezone.utc)
        task = asyncio.create_task(personal_data.purge_daily(self.app.state.sessionmaker, 3, now=lambda: just_before))
        try:
            for _ in range(100):
                if await self.audit("retention_purge"):
                    break
                await asyncio.sleep(0.05)
            self.assertTrue(await self.audit("retention_purge"))
            self.assertFalse(task.done())
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

    async def test_the_app_runs_it(self) -> None:
        settings = self.settings()
        app = create_app(dataclasses.replace(settings, purge_hour=3))
        async with app.router.lifespan_context(app):
            task = app.state.purge_task
            self.assertEqual(task.get_name(), "retention-purge")
            await asyncio.sleep(0)
            self.assertFalse(task.done())
        self.assertTrue(task.cancelled())
        self.assertIsNone(self.app.state.purge_task)  # the tests' own app runs none


class GameDataTests(PersonalDataTestCase):
    """Plan phase 13's tables: per-game roles in access, export and erasure; games in the purge."""

    async def game(self, field_id: uuid.UUID, ended: datetime | None, created: datetime) -> uuid.UUID:
        game = (await self.fetch(
            "INSERT INTO games (field_id, game_id, game_seed, name, mode_id, teams, state, controller_created_at, "
            "ended_at) VALUES ($1, (random() * 60000)::int, (random() * 4e9)::bigint, 'Domingo', 'org.atalaia.domination', "
            "'[\"red\", \"blue\"]', $2, $3, $4) RETURNING id", field_id, "ended" if ended else "running", created,
            ended))[0][0]
        await self.fetch("INSERT INTO game_events (game, node_id, seq, game_time_ms, event_type, priority, data) "
                         "VALUES ($1, 0, 1, 10, 'player.checkin', 'normal', '{\"player\": \"p-abcdefghijkl\"}')", game)
        await self.fetch("INSERT INTO game_node_scores (game, source, team, value) VALUES ($1, 'node-3', 'red', 5)", game)
        return game

    async def test_game_roles_in_access_export_and_erasure(self) -> None:
        user = await self.register("rita")
        user_id = uuid.UUID(user["id"])
        field_id = await self.field()
        now = datetime.now(timezone.utc)
        game = await self.game(field_id, None, now)
        await self.fetch("INSERT INTO user_game_roles (user_id, game, role_id) VALUES ($1, $2, 1)", user_id, game)
        session = await self.login("rita")
        data = (await self.client.get("/api/v1/me/data", headers=bearer(session))).json()
        self.assertEqual([(g["game"], g["field"], g["name"], g["role"]) for g in data["games"]],
                         [(str(game), "Campo Tejo", "Domingo", "player")])
        r = await self.client.get("/api/v1/me/export", headers=bearer(session))
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            self.assertEqual(json.loads(zf.read("export/games.json")), data["games"])
        r = await self.client.request("DELETE", "/api/v1/me", json={"password": PASSWORD}, headers=bearer(session))
        self.assertEqual(r.status_code, 204, r.text)
        self.assertEqual((await self.fetch("SELECT count(*) FROM user_game_roles"))[0][0], 0)
        self.assertEqual((await self.fetch("SELECT count(*) FROM games"))[0][0], 1)  # the game is the field's

    async def test_games_go_after_24_months(self) -> None:
        field_id = await self.field()
        now = datetime.now(timezone.utc)
        old = await self.game(field_id, now - timedelta(days=731), now - timedelta(days=740))
        recent = await self.game(field_id, now - timedelta(days=729), now - timedelta(days=740))
        never_ended = await self.game(field_id, None, now - timedelta(days=731))
        user_id, _, _ = await self.make_user()
        await self.fetch("INSERT INTO user_game_roles (user_id, game, role_id) VALUES ($1, $2, 1)", user_id, old)
        async with self.app.state.sessionmaker() as db:
            counts = await personal_data.purge(db, now)
        self.assertEqual(counts["games"], 2)
        self.assertEqual({r[0] for r in await self.fetch("SELECT id FROM games")}, {recent})
        for table in ("game_events", "game_node_scores", "user_game_roles"):
            with self.subTest(table=table):
                left = {r[0] for r in await self.fetch(f"SELECT DISTINCT game FROM {table}")}
                self.assertTrue(left <= {recent})
        self.assertNotIn(never_ended, {r[0] for r in await self.fetch("SELECT id FROM games")})


class ScheduleTests(unittest.TestCase):
    def test_seconds_until(self) -> None:
        def at(h: int, m: int = 0, s: int = 0) -> datetime:
            return datetime(2026, 10, 19, h, m, s, tzinfo=timezone.utc)

        self.assertEqual(personal_data.seconds_until(at(2, 0), 3), 3600)
        self.assertEqual(personal_data.seconds_until(at(3, 0), 3), 86400)  # just ran: tomorrow
        self.assertEqual(personal_data.seconds_until(at(3, 0, 1), 3), 86399)
        self.assertEqual(personal_data.seconds_until(at(23, 30), 0), 1800)
        lisbon_summer = timezone(timedelta(hours=1))
        self.assertEqual(personal_data.seconds_until(datetime(2026, 7, 1, 3, 0, tzinfo=lisbon_summer), 3), 3600)


if __name__ == "__main__":
    unittest.main()
