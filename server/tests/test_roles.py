# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server administrators, fields and per-field roles on PostgreSQL 16 (ADR-P4-2)."""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import subprocess
import sys
import time
import unittest.mock
import uuid
from typing import Any

import jwt

from atalaia_server import cli, passwords, totp
from atalaia_server.models import ROLES

from .base import PASSWORD, SECRET_KEY, SERVER, AppTestCase, next_time


class CreateAdminTests(AppTestCase):
    async def create(self, username: str, password: str = PASSWORD, codes: Any = None) -> uuid.UUID:
        t = next_time()
        out = io.StringIO()

        def read_code(uri: str, secret: str) -> str:
            self.assertIn(secret, uri)
            return next(codes) if codes is not None else totp.code_at(secret, t)

        return await cli.create_admin(self.settings(), username, None, password, read_code, out, clock=lambda: t)

    async def test_create_admin_then_log_in_with_totp(self) -> None:
        user_id = await self.create("Chefe")
        row = (await self.fetch("SELECT * FROM users WHERE id = $1", user_id))[0]
        self.assertEqual((row["username"], row["server_admin"], row["totp_enabled"]), ("chefe", True, True))
        secret = self.app.state.seed_box.open(row["totp_secret_enc"])
        r = await self.client.post("/api/v1/auth/login", json={"username": "chefe", "password": PASSWORD})
        self.assertTrue(r.json()["totp_required"])
        me = await self.client.get("/api/v1/me", headers=await self.auth("chefe", secret=secret))
        self.assertEqual((me.json()["server_admin"], me.json()["mfa"]), (True, True))
        audit = await self.fetch("SELECT user_id, details FROM audit_log WHERE action = 'admin_create'")
        self.assertEqual(audit[0]["user_id"], user_id)

    async def test_refusals_create_nothing(self) -> None:
        await self.create("chefe")
        for username, password, codes, message in (
                ("chefe", PASSWORD, None, "already exists"),
                ("x", PASSWORD, None, "username"),
                ("outro", "basketball", None, "breached"),
                ("outro", "short", None, "at least 10"),
                ("outro", PASSWORD, iter(["000000", "111111", "222222"]), "no valid TOTP code")):
            with self.subTest(username=username, message=message):
                with self.assertRaisesRegex(cli.CommandError, message):
                    await self.create(username, password, codes)
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 1)

    async def test_the_command(self) -> None:
        """``python -m atalaia_server create-admin --password-stdin``, typing the code it asks for."""
        env = {**os.environ, "ATALAIA_DATABASE_URL": self.database_url, "ATALAIA_SECRET_KEY": SECRET_KEY,
               "PYTHONUNBUFFERED": "1"}
        out = await asyncio.to_thread(_run_create_admin, env)
        self.assertEqual(out["code"], 0, out["text"])
        self.assertIn("otpauth://totp/Atalaia:operadora?secret=", out["text"])
        self.assertIn("TOTP code: Server administrator 'operadora' created", out["text"])
        self.assertTrue((await self.fetch("SELECT server_admin FROM users WHERE username = 'operadora'"))[0][0])

    async def test_the_command_needs_the_settings(self) -> None:
        err = io.StringIO()
        saved = {k: os.environ.pop(k) for k in ("ATALAIA_DATABASE_URL", "ATALAIA_SECRET_KEY") if k in os.environ}
        try:
            code = await asyncio.to_thread(cli.main, ["create-admin", "--username", "x1x"], io.StringIO(),
                                           io.StringIO(), err)
        finally:
            os.environ.update(saved)
        self.assertEqual(code, 2)
        self.assertIn("ATALAIA_DATABASE_URL", err.getvalue())


class ResetTotpTests(AppTestCase):
    async def reset(self, username: str, yes: bool = True, typed: str = "", reason: str = "lost phone") -> uuid.UUID:
        return await cli.reset_totp(self.settings(), username, reason, yes, lambda prompt: typed, io.StringIO(),
                                    actor="system:operator")

    async def test_reset_clears_totp_ends_sessions_and_is_audited(self) -> None:
        _, name, secret = await self.make_user("chefe", server_admin=True)
        headers = await self.auth(name, secret=secret)
        self.assertEqual((await self.client.get("/api/v1/me", headers=headers)).status_code, 200)
        other = await self.make_user("outra", with_totp=True)
        user_id = await self.reset("Chefe")
        row = (await self.fetch("SELECT * FROM users WHERE id = $1", user_id))[0]
        self.assertEqual((row["totp_enabled"], row["totp_secret_enc"], row["totp_last_step"], row["server_admin"]),
                         (False, None, None, True))
        self.assertEqual((await self.client.get("/api/v1/me", headers=headers)).status_code, 401)
        self.assertEqual((await self.fetch("SELECT count(*) FROM sessions WHERE user_id = $1 AND revoked_at IS NULL",
                                           user_id))[0][0], 0)
        self.assertTrue((await self.fetch("SELECT totp_enabled FROM users WHERE id = $1", other[0]))[0][0])
        audit = await self.fetch("SELECT user_id, resource, details FROM audit_log WHERE action = 'totp_reset'")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["user_id"], user_id)
        details = json.loads(audit[0]["details"])
        self.assertEqual((details["via"], details["actor"], details["reason"], details["sessions_revoked"]),
                         ("cli", "system:operator", "lost phone", 1))

    async def test_the_account_enrols_again_at_next_login(self) -> None:
        _, name, secret = await self.make_user("chefe", server_admin=True)
        await self.reset("chefe")
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        self.assertNotIn("totp_required", r.json())
        self.assertEqual((r.json()["mfa"], r.json()["user"]["totp_enabled"]), (False, False))
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.assertEqual((await self.client.get("/api/v1/metrics", headers=headers)).status_code, 403)
        r = await self.client.post("/api/v1/auth/totp/enrol", json={"password": PASSWORD}, headers=headers)
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()["secret"], secret)
        r = await self.client.post("/api/v1/auth/totp/confirm", json={"code": self.code(r.json()["secret"])},
                                   headers=headers)
        self.assertEqual(r.status_code, 204)
        self.assertTrue((await self.client.get("/api/v1/me", headers=headers)).json()["server_admin"])

    async def test_refusals_change_nothing(self) -> None:
        await self.make_user("chefe", server_admin=True)
        await self.make_user("semtotp")
        for username, yes, typed, reason, message in (
                ("ninguem", True, "", "x", "no account named 'ninguem'"),
                ("semtotp", True, "", "x", "no TOTP enrolment"),
                ("chefe", False, "outro", "x", "not confirmed"),
                ("chefe", True, "", "  ", "--reason")):
            with self.subTest(username=username, message=message):
                with self.assertRaisesRegex(cli.CommandError, message):
                    await self.reset(username, yes, typed, reason)
        self.assertTrue((await self.fetch("SELECT totp_enabled FROM users WHERE username = 'chefe'"))[0][0])
        self.assertEqual((await self.fetch("SELECT count(*) FROM audit_log WHERE action = 'totp_reset'"))[0][0], 0)

    async def test_typing_the_username_confirms(self) -> None:
        await self.make_user("chefe", server_admin=True)
        await self.reset("chefe", yes=False, typed=" Chefe ")
        self.assertFalse((await self.fetch("SELECT totp_enabled FROM users WHERE username = 'chefe'"))[0][0])

    async def test_the_command(self) -> None:
        await self.make_user("chefe", server_admin=True)
        saved = {k: os.environ.get(k) for k in ("ATALAIA_DATABASE_URL", "ATALAIA_SECRET_KEY")}
        os.environ.update({"ATALAIA_DATABASE_URL": self.database_url, "ATALAIA_SECRET_KEY": SECRET_KEY})
        try:
            runs = []
            for argv in (["reset-totp", "--username", "nobody", "--reason", "x", "--yes"],
                         ["reset-totp", "--username", "chefe", "--reason", "lost phone"],
                         ["reset-totp", "--username", "chefe", "--reason", "lost phone", "--yes"]):
                out, err = io.StringIO(), io.StringIO()
                code = await asyncio.to_thread(cli.main, argv, io.StringIO(), out, err, confirm=lambda p: "no")
                runs.append((code, out.getvalue(), err.getvalue()))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual(runs[0][0], 1)
        self.assertIn("no account named 'nobody'", runs[0][2])
        self.assertEqual(runs[1][0], 1)
        self.assertIn("not confirmed", runs[1][2])
        self.assertEqual(runs[2][0], 0)
        self.assertIn("TOTP cleared for 'chefe'", runs[2][1])


class SetPasswordTests(AppTestCase):
    NEW = "correct horse battery 99"

    async def setpw(self, username: str, password: str = NEW, yes: bool = True, typed: str = "",
                    reason: str = "passwordless admin") -> uuid.UUID:
        return await cli.set_password(self.settings(), username, password, reason, yes, lambda prompt: typed,
                                      io.StringIO(), actor="system:operator")

    async def make_passwordless(self, username: str, server_admin: bool = True) -> uuid.UUID:
        user_id, _, _ = await self.make_user(username, server_admin=server_admin)
        await self.fetch("UPDATE users SET password_hash = NULL, totp_enabled = false, totp_secret_enc = NULL "
                         "WHERE id = $1", user_id)
        return user_id

    async def test_sets_a_password_ends_sessions_and_is_audited(self) -> None:
        user_id, name, secret = await self.make_user("chefe", server_admin=True)
        headers = await self.auth(name, secret=secret)
        other_id, other, _ = await self.make_user("outra")
        user_id = await self.setpw("Chefe")
        h = (await self.fetch("SELECT password_hash, totp_enabled FROM users WHERE id = $1", user_id))[0]
        self.assertTrue(await passwords.verify_password(h["password_hash"], self.NEW))
        self.assertTrue(h["totp_enabled"])  # the second factor is not touched
        self.assertEqual((await self.client.get("/api/v1/me", headers=headers)).status_code, 401)
        self.assertEqual((await self.fetch("SELECT count(*) FROM sessions WHERE user_id = $1 AND revoked_at IS NULL",
                                           user_id))[0][0], 0)
        o = (await self.fetch("SELECT password_hash FROM users WHERE id = $1", other_id))[0]
        self.assertTrue(await passwords.verify_password(o["password_hash"], PASSWORD))
        audit = await self.fetch("SELECT user_id, details FROM audit_log WHERE action = 'password_set'")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["user_id"], user_id)
        details = json.loads(audit[0]["details"])
        self.assertEqual((details["via"], details["actor"], details["reason"], details["had_password"],
                          details["sessions_revoked"]), ("cli", "system:operator", "passwordless admin", True, 1))
        self.assertNotIn(self.NEW, json.dumps(details))

    async def test_a_passwordless_staff_account_can_log_in_afterwards(self) -> None:
        """The case SR-2 leaves to the operator: no password, no second factor."""
        user_id = await self.make_passwordless("semsenha")
        await self.setpw("semsenha")
        h = (await self.fetch("SELECT password_hash FROM users WHERE id = $1", user_id))[0]
        self.assertTrue(await passwords.verify_password(h["password_hash"], self.NEW))
        audit = await self.fetch("SELECT details FROM audit_log WHERE action = 'password_set'")
        self.assertFalse(json.loads(audit[0]["details"])["had_password"])
        r = await self.client.post("/api/v1/auth/login", json={"username": "semsenha", "password": self.NEW})
        self.assertEqual(r.status_code, 200, r.text)

    async def test_refusals_change_nothing(self) -> None:
        await self.make_user("chefe", server_admin=True)
        for username, password, yes, typed, reason, message in (
                ("ninguem", self.NEW, True, "", "x", "no account named 'ninguem'"),
                ("chefe", "curta", True, "", "x", "at least"),
                ("chefe", "chefe", True, "", "x", "at least"),
                ("chefe", self.NEW, False, "outro", "x", "not confirmed"),
                ("chefe", self.NEW, True, "", "  ", "--reason")):
            with self.subTest(username=username, message=message):
                with self.assertRaisesRegex(cli.CommandError, message):
                    await self.setpw(username, password, yes, typed, reason)
        h = (await self.fetch("SELECT password_hash FROM users WHERE username = 'chefe'"))[0]
        self.assertTrue(await passwords.verify_password(h["password_hash"], PASSWORD))
        self.assertEqual((await self.fetch("SELECT count(*) FROM audit_log WHERE action = 'password_set'"))[0][0], 0)

    async def test_the_api_policy_is_the_one_applied(self) -> None:
        """A password on the breached list or equal to the username is refused for the reason the API gives."""
        await self.make_user("chefe", server_admin=True)
        with unittest.mock.patch.object(passwords, "policy_problem", return_value="password_breached") as policy:
            with self.assertRaisesRegex(cli.CommandError, "breached"):
                await self.setpw("chefe")
        policy.assert_called_once_with(self.NEW, "chefe")

    async def test_an_erased_account_is_refused(self) -> None:
        user_id, _, _ = await self.make_user("apagada")
        await self.fetch("UPDATE users SET password_hash = 'DELETED' WHERE id = $1", user_id)
        with self.assertRaisesRegex(cli.CommandError, "no account named"):
            await self.setpw("apagada")

    async def test_typing_the_username_confirms(self) -> None:
        await self.make_user("chefe", server_admin=True)
        await self.setpw("chefe", yes=False, typed=" Chefe ")
        h = (await self.fetch("SELECT password_hash FROM users WHERE username = 'chefe'"))[0]
        self.assertTrue(await passwords.verify_password(h["password_hash"], self.NEW))

    async def test_the_command_asks_and_never_takes_the_password_from_argv(self) -> None:
        await self.make_user("chefe", server_admin=True)
        saved = {k: os.environ.get(k) for k in ("ATALAIA_DATABASE_URL", "ATALAIA_SECRET_KEY")}
        os.environ.update({"ATALAIA_DATABASE_URL": self.database_url, "ATALAIA_SECRET_KEY": SECRET_KEY})
        base = ["set-password", "--username", "chefe", "--reason", "x", "--yes"]
        try:
            runs = []
            for argv, answers, stdin in (
                    (base + ["--password", self.NEW], [], ""),
                    (base + ["--password=" + self.NEW], [], ""),
                    (base, [self.NEW, "outra coisa"], ""),
                    (base, ["curta", "curta"], ""),
                    (["set-password", "--username", "chefe", "--reason", "x", "--password-stdin"], [], self.NEW + "\n"),
                    (base + ["--password-stdin"], [], self.NEW + "\n"),
                    (base, [self.NEW, self.NEW], "")):
                out, err = io.StringIO(), io.StringIO()
                given = iter(answers)
                try:
                    with contextlib.redirect_stderr(io.StringIO()):  # argparse's usage message
                        code = await asyncio.to_thread(cli.main, argv, io.StringIO(stdin), out, err,
                                                       ask=lambda p: next(given))
                except SystemExit as e:  # argparse: an unknown option
                    code = e.code
                runs.append((code, out.getvalue(), err.getvalue()))
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        self.assertEqual([r[0] for r in runs[:2]], [2, 2])  # there is no --password option
        self.assertEqual(runs[2][0], 1)
        self.assertIn("passwords differ", runs[2][2])
        self.assertEqual(runs[3][0], 1)
        self.assertIn("at least", runs[3][2])
        self.assertEqual(runs[4][0], 2)
        self.assertIn("needs --yes", runs[4][2])
        self.assertEqual(runs[5][0], 0)
        self.assertEqual(runs[6][0], 0)
        self.assertEqual(runs[6][2], "")
        self.assertIn("Password set for 'chefe'", runs[6][1])
        for _, o, e in runs:
            self.assertNotIn(self.NEW, o + e)
        self.assertEqual((await self.fetch("SELECT count(*) FROM audit_log WHERE action = 'password_set'"))[0][0], 2)


def _run_create_admin(env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.Popen([sys.executable, "-m", "atalaia_server", "create-admin", "--username", "operadora",
                             "--password-stdin"], cwd=SERVER, env=env, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    assert proc.stdin and proc.stdout
    proc.stdin.write(PASSWORD + "\n")
    proc.stdin.flush()
    text = ""
    secret = None
    for line in proc.stdout:
        text += line
        if line.strip().startswith("secret: "):
            secret = line.split(":", 1)[1].strip()
            break
    if secret is not None:
        proc.stdin.write(totp.code_at(secret, time.time()) + "\n")
    proc.stdin.close()
    # Through the same text wrapper (communicate() would read the pipe itself and miss what it buffered).
    rest = proc.stdout.read()
    proc.stdout.close()
    proc.wait(timeout=60)
    return {"code": proc.returncode, "text": text + rest}


class RoleTestCase(AppTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        _, self.admin, self.admin_secret = await self.make_user("chefe", server_admin=True)
        self.as_admin = await self.auth(self.admin, secret=self.admin_secret)

    async def new_field(self, slug: str) -> str:
        r = await self.client.post("/api/v1/fields", headers=self.as_admin, json={"name": slug.title(), "slug": slug})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    async def grant(self, headers: dict[str, str], field: str, username: str, role: str) -> Any:
        return await self.client.put(f"/api/v1/fields/{field}/roles", headers=headers,
                                     json={"username": username, "role": role})

    async def member(self, field: str, role: str, with_totp: bool = False) -> tuple[uuid.UUID, str, dict[str, str]]:
        """A new account holding that role on the field, logged in."""
        user_id, name, secret = await self.make_user(with_totp=with_totp or role in ("admin", "gm", "marshal"))
        r = await self.grant(self.as_admin, field, name, role)
        self.assertEqual(r.status_code, 201, r.text)
        return user_id, name, await self.auth(name, secret=secret)


class FieldTests(RoleTestCase):
    async def test_a_new_field_gets_its_country_from_its_time_zone(self) -> None:
        """Decision MEM-2: PT in Portugal's three zones, otherwise unset."""
        for zone, want in (("Europe/Lisbon", "PT"), ("Atlantic/Azores", "PT"), ("Atlantic/Madeira", "PT"),
                           ("Europe/Madrid", None), ("UTC", None)):
            with self.subTest(zone=zone):
                slug = "z" + zone.lower().replace("/", "-").replace("_", "-")
                r = await self.client.post("/api/v1/fields", headers=self.as_admin,
                                           json={"name": slug, "slug": slug, "timezone": zone})
                self.assertEqual((r.status_code, r.json()["country"]), (201, want), r.text)

    async def test_server_administrators_create_fields(self) -> None:
        r = await self.client.post("/api/v1/fields", headers=self.as_admin,
                                   json={"name": "Campo Tejo", "slug": "campo-tejo", "field_type": "cqb",
                                         "timezone": "Atlantic/Azores"})
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual((body["slug"], body["field_type"], body["timezone"]), ("campo-tejo", "cqb", "Atlantic/Azores"))
        audit = await self.fetch("SELECT resource_id FROM audit_log WHERE action = 'field_create'")
        self.assertEqual(str(audit[0][0]), body["id"])
        for change, code in (({"slug": "campo-tejo"}, "slug_taken"), ({"slug": "Campo Tejo"}, "slug_invalid"),
                             ({"slug": "x-", "name": "X"}, "slug_invalid"), ({"field_type": "beach"}, "field_type_invalid"),
                             ({"timezone": "Mars/Olympus"}, "timezone_invalid"), ({"name": "  "}, "name_invalid")):
            with self.subTest(change=change):
                r = await self.client.post("/api/v1/fields", headers=self.as_admin,
                                           json={"name": "Outro", "slug": "outro", **change})
                self.assertEqual(r.json()["detail"], code)

    async def test_nobody_else_creates_fields(self) -> None:
        _, name, secret = await self.make_user(with_totp=True)
        for headers in ({}, await self.auth(name, secret=secret)):
            r = await self.client.post("/api/v1/fields", headers=headers, json={"name": "X", "slug": "x"})
            self.assertEqual(r.status_code, 401 if not headers else 403)

    async def test_an_administrator_session_without_totp_counts_for_nothing(self) -> None:
        await self.fetch("UPDATE sessions SET mfa = false")
        r = await self.client.post("/api/v1/fields", headers=self.as_admin, json={"name": "X", "slug": "x"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "server_admin_required"))
        self.assertEqual((await self.client.get("/api/v1/metrics", headers=self.as_admin)).status_code, 403)

    async def test_listing(self) -> None:
        tejo, norte = await self.new_field("tejo"), await self.new_field("norte")
        _, _, player = await self.member(tejo, "player")
        everything = (await self.client.get("/api/v1/fields", headers=self.as_admin)).json()
        self.assertEqual([f["slug"] for f in everything], ["norte", "tejo"])
        mine = (await self.client.get("/api/v1/fields", headers=player)).json()
        self.assertEqual([(f["id"], f["my_roles"]) for f in mine], [(tejo, ["player"])])
        self.assertNotIn(norte, str(mine))


class RoleTests(RoleTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.field = await self.new_field("campo")
        self.other_field = await self.new_field("outro")

    async def test_privileged_roles_need_totp(self) -> None:
        _, plain, _ = await self.make_user()
        for role in ("admin", "gm", "marshal"):
            with self.subTest(role=role):
                r = await self.grant(self.as_admin, self.field, plain, role)
                self.assertEqual((r.status_code, r.json()["detail"]), (409, "totp_required"))
        for role in ("player", "squad_leader", "vip", "spectator"):
            with self.subTest(role=role):
                self.assertEqual((await self.grant(self.as_admin, self.field, plain, role)).status_code, 201)
        _, secure, _ = await self.make_user(with_totp=True)
        self.assertEqual((await self.grant(self.as_admin, self.field, secure, "marshal")).status_code, 201)
        self.assertEqual((await self.grant(self.as_admin, self.field, secure, "marshal")).status_code, 200)
        grants = await self.fetch("SELECT details FROM audit_log WHERE action = 'role_grant'")
        self.assertEqual(len(grants), 5)  # the repeated grant changed nothing, so it is not logged

    async def test_who_grants_what(self) -> None:
        _, _, field_admin = await self.member(self.field, "admin")
        _, _, gm = await self.member(self.field, "gm")
        _, _, marshal = await self.member(self.field, "marshal")
        _, _, player = await self.member(self.field, "player")
        _, _, other_gm = await self.member(self.other_field, "gm")
        _, target, _ = await self.make_user(with_totp=True)
        expected = {
            "admin": {"field_admin": 201, "gm": 403, "marshal": 403, "player": 403, "other_gm": 403},
            "gm": {"field_admin": 201, "gm": 403, "marshal": 403, "player": 403, "other_gm": 403},
            "marshal": {"field_admin": 201, "gm": 403, "marshal": 403, "player": 403, "other_gm": 403},
            "player": {"field_admin": 200, "gm": 200, "marshal": 403, "player": 403, "other_gm": 403},
            "squad_leader": {"field_admin": 200, "gm": 201, "marshal": 403, "player": 403, "other_gm": 403},
            "vip": {"field_admin": 200, "gm": 201, "marshal": 403, "player": 403, "other_gm": 403},
            "spectator": {"field_admin": 200, "gm": 201, "marshal": 403, "player": 403, "other_gm": 403},
        }
        callers = {"field_admin": field_admin, "gm": gm, "marshal": marshal, "player": player, "other_gm": other_gm}
        order = ["gm", "player", "other_gm", "marshal", "field_admin"]  # field_admin last: it may re-grant
        for role, by in expected.items():
            for caller in sorted(by, key=order.index):
                with self.subTest(role=role, caller=caller):
                    r = await self.grant(callers[caller], self.field, target, role)
                    want = by[caller]
                    if want in (200, 201):
                        self.assertIn(r.status_code, (200, 201), r.text)
                    else:
                        self.assertEqual((r.status_code, r.json()["detail"]), (want, "role_required"))

    async def test_revoking_counts_at_once(self) -> None:
        gm_id, _, gm = await self.member(self.field, "gm")
        self.assertEqual((await self.client.get(f"/api/v1/fields/{self.field}/roles", headers=gm)).status_code, 200)
        r = await self.client.delete(f"/api/v1/fields/{self.field}/roles/{gm_id}/gm", headers=self.as_admin)
        self.assertEqual(r.status_code, 204)
        # The same access token, still unexpired, no longer carries the role.
        r = await self.client.get(f"/api/v1/fields/{self.field}/roles", headers=gm)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "role_required"))
        audit = await self.fetch("SELECT resource_id, details FROM audit_log WHERE action = 'role_revoke'")
        self.assertEqual(audit[0]["resource_id"], gm_id)
        r = await self.client.delete(f"/api/v1/fields/{self.field}/roles/{gm_id}/gm", headers=self.as_admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "role_not_found"))
        r = await self.client.delete(f"/api/v1/fields/{self.field}/roles/{gm_id}/boss", headers=self.as_admin)
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "role_invalid"))

    async def test_privileged_roles_count_only_after_the_totp_step(self) -> None:
        gm_id, _, gm = await self.member(self.field, "gm")
        await self.fetch("UPDATE sessions SET mfa = false WHERE user_id = $1", gm_id)
        r = await self.client.get(f"/api/v1/fields/{self.field}/roles", headers=gm)
        self.assertEqual(r.status_code, 403)
        # The field is still listed, with the role the account holds.
        self.assertEqual((await self.client.get("/api/v1/fields", headers=gm)).json()[0]["my_roles"], ["gm"])

    async def test_list_roles(self) -> None:
        gm_id, gm_name, gm = await self.member(self.field, "gm")
        _, player_name, player = await self.member(self.field, "player")
        r = await self.client.get(f"/api/v1/fields/{self.field}/roles", headers=gm)
        self.assertEqual(sorted((x["username"], x["role"]) for x in r.json()),
                         sorted([(gm_name, "gm"), (player_name, "player")]))
        self.assertTrue(all(x["granted_by"] for x in r.json()))
        self.assertEqual((await self.client.get(f"/api/v1/fields/{self.field}/roles", headers=player)).status_code,
                         403)
        self.assertEqual((await self.client.get(f"/api/v1/fields/{self.other_field}/roles",
                                                headers=gm)).status_code, 403)

    async def test_unknown_things(self) -> None:
        r = await self.grant(self.as_admin, self.field, "nobody-at-all", "player")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "user_not_found"))
        # SRV-4: for a role that needs a second factor, "no such account" and "no second factor" are one answer.
        _, plain, _ = await self.make_user()
        answers = {(r.status_code, r.json()["detail"]) for r in (
            await self.grant(self.as_admin, self.field, "nobody-at-all", "gm"),
            await self.grant(self.as_admin, self.field, plain, "gm"))}
        self.assertEqual(answers, {(409, "totp_required")})
        r = await self.grant(self.as_admin, str(uuid.uuid4()), "chefe", "player")
        self.assertEqual((r.status_code, r.json()["detail"]), (404, "field_not_found"))
        r = await self.grant(self.as_admin, self.field, "chefe", "general")
        self.assertEqual((r.status_code, r.json()["detail"]), (400, "role_invalid"))

    async def test_roles_in_the_token_and_in_me(self) -> None:
        _, name, secret = await self.make_user(with_totp=True)
        await self.grant(self.as_admin, self.field, name, "marshal")
        await self.grant(self.as_admin, self.field, name, "player")
        session = await self.login(name, secret=secret)
        self.assertEqual(session["user"]["roles"], {self.field: ["marshal", "player"]})
        claims = jwt.decode(session["access_token"], options={"verify_signature": False})
        self.assertEqual(claims["roles"], {self.field: ["marshal", "player"]})

    def test_the_seven_roles(self) -> None:
        self.assertEqual([name for _, name in ROLES],
                         ["player", "squad_leader", "vip", "marshal", "gm", "spectator", "admin"])
