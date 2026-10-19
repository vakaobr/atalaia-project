# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accounts and sessions on PostgreSQL 16: register, login, TOTP, refresh rotation, logout (ADR-P4-2)."""

from __future__ import annotations

import hashlib
import json
import time
import unittest
from http.cookies import SimpleCookie
from typing import Any

import httpx
from argon2 import PasswordHasher, Type

from atalaia_server import tokens, totp
from atalaia_server.api.auth import COOKIE, COOKIE_PATH
from atalaia_server.ratelimit import Limits, Lockout, RequestLimit
from atalaia_server.security_headers import HEADERS

from .base import PASSWORD, AppTestCase

REFRESH = {"X-Atalaia-Refresh": "1"}


class Clock:
    def __init__(self) -> None:
        self.t = 5000.0

    def __call__(self) -> float:
        return self.t


def set_cookie(response: httpx.Response) -> SimpleCookie:
    jar = SimpleCookie()
    for value in response.headers.get_list("set-cookie"):
        jar.load(value)
    return jar


class AuthTestCase(AppTestCase):
    async def audit(self, action: str) -> list[Any]:
        return await self.fetch("SELECT user_id, action, resource, resource_id, details, host(ip_address) AS ip "
                                "FROM audit_log WHERE action = $1 ORDER BY id", action)

    async def register(self, username: str, password: str = PASSWORD, **extra: Any) -> httpx.Response:
        return await self.client.post("/api/v1/auth/register",
                                      json={"username": username, "password": password, "consent": True, **extra})


class RegisterTests(AuthTestCase):
    async def test_register(self) -> None:
        r = await self.register("Rita.Tejo", email=" Rita@Example.PT ")
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        self.assertEqual((body["username"], body["email"]), ("rita.tejo", "rita@example.pt"))
        self.assertEqual((body["totp_enabled"], body["server_admin"], body["roles"]), (False, False, {}))
        self.assertNotIn("password", json.dumps(body))
        row = (await self.fetch("SELECT * FROM users WHERE username = 'rita.tejo'"))[0]
        self.assertTrue(row["password_hash"].startswith("$argon2id$v=19$m=65536,t=3,p=4$"))
        self.assertIsNotNone(row["gdpr_consent_at"])
        self.assertEqual(str(row["id"]), body["id"])
        self.assertEqual(row["id"].version, 7)
        audit = await self.audit("register")
        self.assertEqual((audit[0]["user_id"], audit[0]["ip"]), (row["id"], "127.0.0.1"))
        # The new account can log in.
        self.assertIn("access_token", await self.login("rita.tejo"))

    async def test_refusals(self) -> None:
        cases = [
            ({"username": "ab"}, 400, "username_invalid"),
            ({"username": "-rita"}, 400, "username_invalid"),
            ({"username": "rita tejo"}, 400, "username_invalid"),
            ({"email": "not-an-address"}, 400, "email_invalid"),
            ({"email": "a@b"}, 400, "email_invalid"),
            ({"consent": False}, 400, "consent_required"),
            ({"password": "short pw"}, 400, "password_too_short"),
            ({"password": "basketball"}, 400, "password_breached"),
            ({"password": "Password12"}, 400, "password_breached"),
            ({"username": "fernando.pessoa", "password": "Fernando.Pessoa"}, 400, "password_is_username"),
        ]
        for change, status, code in cases:
            body = {"username": "joana", "password": PASSWORD, "consent": True, **change}
            with self.subTest(change=change):
                r = await self.client.post("/api/v1/auth/register", json=body)
                self.assertEqual((r.status_code, r.json()["detail"]), (status, code))
        self.assertEqual((await self.fetch("SELECT count(*) AS n FROM users"))[0]["n"], 0)

    async def test_taken_whatever_the_case(self) -> None:
        self.assertEqual((await self.register("joana", email="j@example.pt")).status_code, 201)
        for name, extra in (("JOANA", {}), ("joana2", {"email": "J@example.pt"})):
            with self.subTest(name=name):
                r = await self.register(name, **extra)
                self.assertEqual((r.status_code, r.json()["detail"]), (409, "username_or_email_taken"))

    async def test_ten_registrations_an_hour_per_address(self) -> None:
        for i in range(10):
            self.assertEqual((await self.register(f"player{i:02d}")).status_code, 201)
        r = await self.register("player10")
        self.assertEqual(r.status_code, 429)
        self.assertGreater(int(r.headers["retry-after"]), 3500)

    async def test_validation_errors_do_not_echo_the_input(self) -> None:
        secret = "my very secret password 99"
        for body in ({"username": "joana", "password": secret, "consent": True, "admin": True},
                     {"username": ["joana"], "password": secret},
                     {"username": "joana", "password": secret * 200, "consent": True}):
            with self.subTest(keys=sorted(body)):
                r = await self.client.post("/api/v1/auth/register", json=body)
                self.assertEqual(r.status_code, 422)
                self.assertNotIn(secret, r.text)
                self.assertNotIn('"input"', r.text)


class LoginTests(AuthTestCase):
    async def test_login(self) -> None:
        user_id, name, _ = await self.make_user()
        r = await self.client.post("/api/v1/auth/login", json={"username": name.upper(), "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["token_type"], body["expires_in"], body["mfa"]), ("bearer", 900, False))
        self.assertEqual(body["user"]["id"], str(user_id))
        self.assertEqual(r.headers["cache-control"], "no-store")
        # The refresh token is only in the cookie, with every protection.
        cookie = set_cookie(r)[COOKIE]
        self.assertEqual((cookie["path"], cookie["samesite"].lower(), cookie["max-age"]),
                         (COOKIE_PATH, "strict", str(tokens.REFRESH_TTL_S)))
        self.assertTrue(cookie["httponly"] and cookie["secure"])
        self.assertNotIn(cookie.value, r.text)
        me = await self.client.get("/api/v1/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        self.assertEqual(me.status_code, 200)
        self.assertEqual((me.json()["username"], me.json()["mfa"]), (name, False))
        row = (await self.fetch("SELECT last_login_at FROM users WHERE id = $1", user_id))[0]
        self.assertIsNotNone(row["last_login_at"])
        session = (await self.fetch("SELECT * FROM sessions WHERE user_id = $1", user_id))[0]
        self.assertEqual((str(session["ip_address"]), session["mfa"], session["revoked_at"]), ("127.0.0.1", False, None))
        self.assertEqual(len(await self.audit("login")), 1)

    async def test_wrong_password_and_unknown_user_answer_alike(self) -> None:
        user_id, name, _ = await self.make_user()
        wrong = await self.client.post("/api/v1/auth/login", json={"username": name, "password": "nope " * 3})
        unknown = await self.client.post("/api/v1/auth/login", json={"username": "nobody-here",
                                                                     "password": PASSWORD})
        for r in (wrong, unknown):
            self.assertEqual((r.status_code, r.json()), (401, {"detail": "invalid_credentials"}))
            self.assertNotIn("set-cookie", r.headers)
        failed = await self.audit("login_failed")
        self.assertEqual([row["user_id"] for row in failed], [user_id, None])
        # Nothing typed is kept: neither the password nor the unknown username.
        text = json.dumps([dict(row) for row in await self.fetch("SELECT * FROM audit_log")], default=str)
        for typed in ("nope", "nobody-here", PASSWORD):
            self.assertNotIn(typed, text)

    async def test_five_failures_lock_that_username_at_that_address(self) -> None:
        """Decisions S11-12 and S12-1: 5 failures lock one (address, username) for 15 minutes."""
        clock = Clock()
        self.app.state.limits = Limits(clock=clock)
        _, name, _ = await self.make_user()
        _, friend, _ = await self.make_user()
        for _ in range(5):
            r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": "wrong password"})
            self.assertEqual(r.status_code, 401)
        r = await self.client.post("/api/v1/auth/login", json={"username": name.upper(), "password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (429, "too_many_attempts"))
        self.assertEqual(r.headers["retry-after"], "900")
        locked = await self.audit("login_locked")
        self.assertEqual(len(locked), 1)
        self.assertEqual(json.loads(locked[0]["details"]), {"where": "login", "scope": "username_address"})
        # Another player behind the same address (a field's 4G link) still logs in.
        self.assertIn("access_token", await self.login(friend))
        # The same username from another address is not locked out either.
        other = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app, client=("198.51.100.4", 4000)),
                                  base_url="https://server.test")
        self.stack.push_async_callback(other.aclose)
        self.assertIn("access_token", await self.login(name, client=other))
        clock.t += 900
        self.assertIn("access_token", await self.login(name))

    async def test_a_success_clears_the_count(self) -> None:
        self.app.state.limits = Limits(clock=Clock())
        _, name, _ = await self.make_user()
        for _ in range(4):
            await self.client.post("/api/v1/auth/login", json={"username": name, "password": "wrong password"})
        await self.login(name)
        for _ in range(4):
            r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": "wrong password"})
            self.assertEqual(r.status_code, 401)

    async def test_spraying_locks_the_address(self) -> None:
        """Many usernames from one address: the per-address ceiling (50 by default) locks it."""
        clock = Clock()
        self.app.state.limits = Limits(clock=clock)
        self.app.state.limits.login_address = Lockout(3, 900, 900, clock)
        _, name, _ = await self.make_user()
        for i in range(3):
            r = await self.client.post("/api/v1/auth/login", json={"username": f"guess{i}", "password": PASSWORD})
            self.assertEqual(r.status_code, 401)
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (429, "too_many_attempts"))
        locked = await self.audit("login_locked")
        self.assertIsNone(locked[0]["user_id"])
        self.assertEqual(json.loads(locked[0]["details"]), {"where": "login", "scope": "address"})
        clock.t += 900
        self.assertIn("access_token", await self.login(name))

    async def test_an_older_hash_is_replaced_at_login(self) -> None:
        weak = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID).hash(PASSWORD)
        await self.fetch("INSERT INTO users (username, password_hash) VALUES ('old.timer', $1)", weak)
        await self.login("old.timer")
        stored = (await self.fetch("SELECT password_hash FROM users WHERE username = 'old.timer'"))[0][0]
        self.assertTrue(stored.startswith("$argon2id$v=19$m=65536,t=3,p=4$"))
        await self.login("old.timer")  # and the new one works

    async def test_the_request_limit(self) -> None:
        self.app.state.limits.requests = RequestLimit(3, 60)
        statuses = [(await self.client.get("/api/v1/me")).status_code for _ in range(4)]
        self.assertEqual(statuses, [401, 401, 401, 429])
        r = await self.client.get("/api/v1/me")
        self.assertEqual(r.json(), {"detail": "too_many_requests"})
        self.assertIn("retry-after", r.headers)
        for name, value in HEADERS:
            self.assertEqual(r.headers[name], value)
        self.assertEqual((await self.client.get("/api/v1/health")).status_code, 200)


class SessionTests(AuthTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        self.user_id, self.name, _ = await self.make_user()
        self.session = await self.login(self.name)
        self.bearer = {"Authorization": f"Bearer {self.session['access_token']}"}

    def cookie(self) -> str:
        return self.client.cookies.get(COOKIE, path=COOKIE_PATH)

    async def refresh(self, client: httpx.AsyncClient | None = None) -> httpx.Response:
        return await (client or self.client).post("/api/v1/auth/refresh", headers=REFRESH)

    async def test_bearer_needed(self) -> None:
        for headers in ({}, {"Authorization": "Bearer nonsense"}, {"Authorization": "Basic abc"},
                        {"Authorization": self.bearer["Authorization"].replace("Bearer", "Token")}):
            with self.subTest(headers=headers):
                r = await self.client.get("/api/v1/me", headers=headers)
                self.assertEqual((r.status_code, r.headers.get("www-authenticate")), (401, "Bearer"))

    async def test_refresh_rotates_and_a_replay_ends_the_session(self) -> None:
        first = self.cookie()
        r = await self.refresh()
        self.assertEqual(r.status_code, 200, r.text)
        second = self.cookie()
        self.assertNotEqual(first, second)
        new_bearer = {"Authorization": f"Bearer {r.json()['access_token']}"}
        self.assertEqual((await self.client.get("/api/v1/me", headers=new_bearer)).status_code, 200)
        # The first token again (a stolen copy): the whole session ends.
        thief = self.other_client()
        thief.cookies.set(COOKIE, first, domain="server.test", path=COOKIE_PATH)
        r = await self.refresh(thief)
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "invalid_refresh_token"))
        self.assertEqual(len(await self.audit("refresh_replay")), 1)
        for headers in (self.bearer, new_bearer):
            self.assertEqual((await self.client.get("/api/v1/me", headers=headers)).status_code, 401)
        r = await self.refresh()  # the legitimate client's newest token is dead too
        self.assertEqual(r.status_code, 401)
        self.assertIn("max-age=0", r.headers["set-cookie"].lower())

    async def test_tokens_are_stored_as_hashes(self) -> None:
        await self.refresh()
        raw = self.cookie()
        rows = await self.fetch("SELECT token_hash, used_at FROM refresh_tokens ORDER BY id")
        self.assertEqual(len(rows), 2)
        self.assertIsNotNone(rows[0]["used_at"])
        self.assertIsNone(rows[1]["used_at"])
        self.assertEqual(rows[1]["token_hash"], hashlib.sha256(raw.encode()).hexdigest())
        dump = json.dumps([dict(r) for r in await self.fetch("SELECT * FROM refresh_tokens")]
                          + [dict(r) for r in await self.fetch("SELECT * FROM sessions")], default=str)
        self.assertNotIn(raw, dump)

    async def test_refresh_needs_its_header_and_its_cookie(self) -> None:
        r = await self.client.post("/api/v1/auth/refresh")
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "refresh_header_required"))
        r = await self.client.post("/api/v1/auth/refresh", headers={"X-Atalaia-Refresh": "yes"})
        self.assertEqual(r.status_code, 403)
        r = await self.refresh(self.other_client())  # no cookie
        self.assertEqual(r.status_code, 401)
        stranger = self.other_client()
        stranger.cookies.set(COOKIE, tokens.new_refresh_token(), domain="server.test", path=COOKIE_PATH)
        self.assertEqual((await self.refresh(stranger)).status_code, 401)
        # A refused cookie is not a replay: the session lives on.
        self.assertEqual((await self.client.get("/api/v1/me", headers=self.bearer)).status_code, 200)

    async def test_logout(self) -> None:
        r = await self.client.post("/api/v1/auth/logout", headers=self.bearer)
        self.assertEqual(r.status_code, 204)
        self.assertIn("max-age=0", r.headers["set-cookie"].lower())
        self.assertIn(f"path={COOKIE_PATH}", r.headers["set-cookie"].lower())
        self.assertEqual((await self.client.get("/api/v1/me", headers=self.bearer)).status_code, 401)
        self.assertEqual((await self.client.post("/api/v1/auth/logout", headers=self.bearer)).status_code, 401)
        row = (await self.fetch("SELECT revoked_at FROM sessions WHERE user_id = $1", self.user_id))[0]
        self.assertIsNotNone(row["revoked_at"])
        self.assertEqual(len(await self.audit("logout")), 1)

    async def test_the_refresh_cookie_is_dead_after_logout(self) -> None:
        cookie = self.cookie()
        await self.client.post("/api/v1/auth/logout", headers=self.bearer)
        again = self.other_client()
        again.cookies.set(COOKIE, cookie, domain="server.test", path=COOKIE_PATH)
        self.assertEqual((await self.refresh(again)).status_code, 401)

    async def test_expiry(self) -> None:
        await self.fetch("UPDATE sessions SET expires_at = now() - interval '1 second'")
        self.assertEqual((await self.client.get("/api/v1/me", headers=self.bearer)).status_code, 401)
        self.assertEqual((await self.refresh()).status_code, 401)

    async def test_thirty_days_at_most(self) -> None:
        await self.fetch("UPDATE sessions SET created_at = now() - interval '29 days 12 hours'")
        r = await self.refresh()
        self.assertEqual(r.status_code, 200)
        row = (await self.fetch("SELECT expires_at - created_at AS left FROM sessions"))[0]
        self.assertEqual(row["left"].total_seconds(), tokens.SESSION_MAX_S)
        await self.fetch("UPDATE sessions SET created_at = now() - interval '30 days 1 second', "
                         "expires_at = now() + interval '1 day'")
        self.assertEqual((await self.refresh()).status_code, 401)

    async def test_refresh_moves_the_expiry_on(self) -> None:
        await self.fetch("UPDATE sessions SET expires_at = now() + interval '1 hour'")
        self.assertEqual((await self.refresh()).status_code, 200)
        row = (await self.fetch("SELECT expires_at - now() AS left FROM sessions"))[0]
        self.assertAlmostEqual(row["left"].total_seconds(), tokens.REFRESH_TTL_S, delta=60)


class TotpTests(AuthTestCase):
    async def enrol(self, name: str) -> tuple[dict[str, str], str]:
        headers = await self.auth(name)
        r = await self.client.post("/api/v1/auth/totp/enrol", headers=headers, json={"password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)
        secret = r.json()["secret"]
        r = await self.client.post("/api/v1/auth/totp/confirm", headers=headers, json={"code": self.code(secret)})
        self.assertEqual(r.status_code, 204, r.text)
        return headers, secret

    async def test_enrol_confirm_and_log_in_with_a_code(self) -> None:
        user_id, name, _ = await self.make_user()
        headers = await self.auth(name)
        r = await self.client.post("/api/v1/auth/totp/enrol", headers=headers, json={"password": "wrong one!"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_password"))
        r = await self.client.post("/api/v1/auth/totp/enrol", headers=headers, json={"password": PASSWORD})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual((body["digits"], body["period_s"]), (6, 30))
        self.assertTrue(body["otpauth_uri"].startswith(f"otpauth://totp/Atalaia:{name}?secret={body['secret']}"))
        # Not on yet: a wrong code does not confirm it.
        r = await self.client.post("/api/v1/auth/totp/confirm", headers=headers, json={"code": "000000"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_code"))
        self.assertFalse((await self.client.get("/api/v1/me", headers=headers)).json()["totp_enabled"])
        r = await self.client.post("/api/v1/auth/totp/confirm", headers=headers,
                                   json={"code": self.code(body["secret"])})
        self.assertEqual(r.status_code, 204)
        me = (await self.client.get("/api/v1/me", headers=headers)).json()
        self.assertEqual((me["totp_enabled"], me["mfa"]), (True, True))
        self.assertEqual(len(await self.audit("totp_enabled")), 1)
        # The seed is encrypted at rest.
        sealed = (await self.fetch("SELECT totp_secret_enc FROM users WHERE id = $1", user_id))[0][0]
        self.assertNotIn(body["secret"].encode(), sealed)
        self.assertEqual(self.app.state.seed_box.open(sealed), body["secret"])
        # From now on the password alone is not a login.
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        self.assertEqual(set(r.json()), {"totp_required", "totp_session"})
        self.assertNotIn("set-cookie", r.headers)
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": r.json()["totp_session"],
                                                                    "code": self.code(body["secret"])})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["mfa"])
        self.assertIn(COOKIE, r.headers["set-cookie"])
        self.assertTrue((await self.fetch("SELECT bool_and(mfa) FROM sessions WHERE user_id = $1 "
                                          "AND created_at = (SELECT max(created_at) FROM sessions)", user_id))[0][0])

    async def test_enrol_twice(self) -> None:
        _, name, _ = await self.make_user()
        headers, _ = await self.enrol(name)
        r = await self.client.post("/api/v1/auth/totp/enrol", headers=headers, json={"password": PASSWORD})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "totp_already_enabled"))

    async def step_token(self, name: str) -> str:
        r = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        return r.json()["totp_session"]

    async def test_the_totp_session_is_single_use_and_short(self) -> None:
        user_id, name, secret = await self.make_user(with_totp=True)
        step = await self.step_token(name)
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": step, "code": self.code(secret)})
        self.assertEqual(r.status_code, 200)
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": step, "code": self.code(secret)})
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "invalid_totp_session"))
        old, _ = tokens.make_totp_step_token(self.app.state.keys, user_id, now=time.time() - 400)
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": old, "code": self.code(secret)})
        self.assertEqual(r.status_code, 401)
        # It is not an access token either.
        self.assertEqual((await self.client.get("/api/v1/me",
                                                headers={"Authorization": f"Bearer {step}"})).status_code, 401)

    async def test_a_code_works_once(self) -> None:
        _, name, secret = await self.make_user(with_totp=True)
        first, second = await self.step_token(name), await self.step_token(name)
        code = self.code(secret)
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": first, "code": code})
        self.assertEqual(r.status_code, 200)
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": second, "code": code})
        self.assertEqual((r.status_code, r.json()["detail"]), (401, "invalid_code"))
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": second, "code": self.code(secret)})
        self.assertEqual(r.status_code, 200)

    async def test_five_wrong_codes_lock_the_account(self) -> None:
        clock = Clock()
        self.app.state.limits = Limits(clock=clock)
        user_id, name, secret = await self.make_user(with_totp=True)
        step = await self.step_token(name)
        for _ in range(5):
            r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": step, "code": "123456"})
            self.assertEqual(r.status_code, 401)
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": step, "code": self.code(secret)})
        self.assertEqual((r.status_code, r.headers["retry-after"]), (429, "900"))
        self.assertEqual([row["user_id"] for row in await self.audit("totp_locked")], [user_id])
        self.assertEqual(len(await self.audit("totp_failed")), 5)
        clock.t += 900
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": step, "code": self.code(secret)})
        self.assertEqual(r.status_code, 200)

    async def test_a_changed_secret_key_leaves_the_seed_unreadable(self) -> None:
        _, name, secret = await self.make_user(with_totp=True)
        await self.fetch("UPDATE users SET totp_secret_enc = $1", b"garbage that is not a fernet token")
        step = await self.step_token(name)
        r = await self.client.post("/api/v1/auth/login/totp", json={"totp_session": step, "code": self.code(secret)})
        self.assertEqual(r.status_code, 401)

    async def test_disable(self) -> None:
        user_id, name, _ = await self.make_user()
        headers, secret = await self.enrol(name)
        r = await self.client.post("/api/v1/auth/totp/disable", headers=headers,
                                   json={"password": PASSWORD, "code": "000000"})
        self.assertEqual(r.status_code, 403)
        r = await self.client.post("/api/v1/auth/totp/disable", headers=headers,
                                   json={"password": PASSWORD, "code": self.code(secret)})
        self.assertEqual(r.status_code, 204)
        row = (await self.fetch("SELECT totp_enabled, totp_secret_enc, totp_last_step FROM users WHERE id = $1",
                                user_id))[0]
        self.assertEqual(tuple(row), (False, None, None))
        self.assertFalse((await self.fetch("SELECT bool_or(mfa) FROM sessions WHERE user_id = $1", user_id))[0][0])
        self.assertEqual(len(await self.audit("totp_disabled")), 1)
        self.assertIn("access_token", await self.login(name))

    async def test_disable_is_refused_while_a_role_needs_it(self) -> None:
        user_id, name, secret = await self.make_user(with_totp=True)
        field = (await self.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id"))[0][0]
        await self.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 4)",
                         user_id, field)  # marshal
        headers = await self.auth(name, secret=secret)
        r = await self.client.post("/api/v1/auth/totp/disable", headers=headers,
                                   json={"password": PASSWORD, "code": self.code(secret)})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "totp_required_by_role"))
        _, admin, admin_secret = await self.make_user(server_admin=True)
        headers = await self.auth(admin, secret=admin_secret)
        r = await self.client.post("/api/v1/auth/totp/disable", headers=headers,
                                   json={"password": PASSWORD, "code": self.code(admin_secret)})
        self.assertEqual(r.status_code, 409)


class TotpModuleClockTests(unittest.TestCase):
    def test_the_app_clock_is_real_time_by_default(self) -> None:
        from atalaia_server.app import create_app
        from atalaia_server.config import Settings
        app = create_app(Settings(database_url="postgresql+asyncpg://u:p@db/x", secret_key="k" * 40))
        self.assertAlmostEqual(app.state.clock(), time.time(), delta=5)
        self.assertEqual(totp.DIGITS, 6)


if __name__ == "__main__":
    unittest.main()
