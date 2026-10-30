# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The username step, the "use my name" round, renaming with the account's own login method, the consent error's
place on the login page, and merging two accounts of one person (decisions LG-10, LG-11, LG-12).

    python3 tools/docker_server.py test tests.test_account_names_merge
"""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Any, Optional
from urllib.parse import parse_qs

import httpx

from atalaia_server import oidc, personal_data
from atalaia_server.api import account_merge
from atalaia_server.web import staff_pages
from atalaia_server.web.staff_i18n import STRINGS

from .base import PASSWORD
from .test_login_methods import ORIGIN, LoginTestCase, bearer


class NameDerivationTests(LoginTestCase):
    async def test_a_name_becomes_a_username_of_the_allowed_characters(self) -> None:
        cases = {"Ana Silva": "ana.silva", "José Ñandú": "jose.nandu", "  Ana   Maria-Costa ": "ana.maria-costa",
                 "O'Brien, Pat": "o.brien.pat", "Ünal": "unal", "x" * 100: "x" * 64}
        for name, want in cases.items():
            with self.subTest(name=name):
                self.assertEqual(oidc.username_from_name({"name": name}), want)
        # Nothing usable: too short, or no Latin letters at all.
        for name in ("Al", "李小龍", "", "...", None, 42):
            with self.subTest(name=name):
                self.assertIsNone(oidc.username_from_name({"name": name}))
        self.assertEqual(oidc.username_from_name({"name": "李", "given_name": "Beatriz"}), "beatriz")
        self.assertIsNone(oidc.username_from_name({}))


class UsernameStepTests(LoginTestCase):
    async def name_round(self, headers: dict[str, str], provider: str, subject: str, claims: Optional[dict[str, Any]] = None,
                         return_to: str = "/staff/account?welcome=1&next=%2Fstaff%2F") -> tuple[str, dict[str, str], str]:
        params, r = await self.begin(provider, headers=headers, purpose="name", return_to=return_to)
        self.assertEqual(r.status_code, 200, r.text)
        self.round_scope = params.get("scope")
        return self.landed(await self.callback(provider, params, subject, claims=claims))

    async def test_a_new_account_is_told_so_once(self) -> None:
        first = await self.social("google", "g-new")
        self.assertEqual((first["new_account"], first["provider"]), (True, "google"))
        self.assertTrue(first["user"]["username"].startswith("user-"))
        again = await self.social("google", "g-new", client=self.other_client())
        self.assertNotIn("new_account", again)
        password_login = await self.auth((await self.make_user())[1])
        self.assertTrue(password_login)

    async def test_the_account_keeps_working_if_the_step_is_skipped(self) -> None:
        body = await self.social("google", "g-skip")
        r = await self.client.get("/api/v1/me", headers=bearer(body))
        self.assertEqual(r.status_code, 200)
        methods = (await self.client.get("/api/v1/me/login-methods", headers=bearer(body))).json()
        self.assertEqual(methods["username"], body["user"]["username"])

    async def test_the_name_button_is_for_the_provider_the_account_signed_up_with(self) -> None:
        google = bearer(await self.social("google", "g-1"))
        methods = (await self.client.get("/api/v1/me/login-methods", headers=google)).json()
        self.assertEqual(methods["name_provider"], {"provider": "google", "label": "Google"})
        microsoft = bearer(await self.social("microsoft", "m-1", client=self.other_client()))
        methods = (await self.client.get("/api/v1/me/login-methods", headers=microsoft)).json()
        self.assertEqual(methods["name_provider"], {"provider": "microsoft", "label": "Microsoft"})
        apple = bearer(await self.social("apple", "a-1", client=self.other_client()))
        self.assertIsNone((await self.client.get("/api/v1/me/login-methods", headers=apple)).json()["name_provider"])
        # A password account that linked Google later did not sign up with it.
        _, name, _ = await self.make_user()
        headers = await self.auth(name)
        await self.link("google", "g-linked", headers)
        self.assertIsNone((await self.client.get("/api/v1/me/login-methods", headers=headers)).json()["name_provider"])

    async def test_the_name_round_asks_for_the_profile_scope_only_then(self) -> None:
        for provider in ("google", "microsoft"):
            with self.subTest(provider=provider):
                headers = bearer(await self.social(provider, f"{provider}-1", client=self.other_client()))
                self.assertEqual((await self.begin(provider, consent=False))[0]["scope"], "openid")  # a login
                for purpose in ("link", "reauth"):
                    params, _ = await self.begin(provider, headers=headers, purpose=purpose, password="")
                    self.assertEqual(params["scope"], "openid", purpose)
                path, query, fragment = await self.name_round(headers, provider, f"{provider}-1",
                                                              {"name": "Ana Sílva"})
                self.assertEqual(self.round_scope, "openid profile")
                self.assertEqual((path, query), ("/staff/account", {"welcome": "1", "next": "/staff/", "oidc": "name"}))
                self.assertEqual(parse_qs(fragment), {"username": ["ana.silva"]})

    async def test_a_name_is_never_stored(self) -> None:
        headers = bearer(await self.social("google", "g-priv"))
        _, _, fragment = await self.name_round(headers, "google", "g-priv", {
            "name": "Beatriz Quintanilha", "given_name": "Beatriz", "family_name": "Quintanilha",
            "email": "bia@example.pt"})
        self.assertEqual(parse_qs(fragment), {"username": ["beatriz.quintanilha"]})
        every_row = []
        for table in ("users", "audit_log", "user_identities", "oidc_logins", "sessions", "consents", "refresh_tokens"):
            every_row += [r["row"] for r in await self.fetch(f"SELECT row_to_json(t)::text AS row FROM {table} t")]
        dump = json.dumps(every_row).lower()
        for word in ("quintanilha", "beatriz", "bia@example", "bia@"):
            self.assertNotIn(word, dump)
        self.assertEqual([d for d in await self.audit("oidc_name_read")], [{"provider": "google", "usable": True}])
        # Only what the person confirms is saved, and it goes in as any rename does (fields, never values).
        headers_again = headers
        r = await self.client.patch("/api/v1/me", headers=headers_again, json={"username": "bia.q"})
        self.assertEqual((r.status_code, r.json()["username"]), (200, "bia.q"))
        self.assertEqual(await self.audit("profile_update"), [{"fields": ["username"]}])

    async def test_the_round_refusals(self) -> None:
        headers = bearer(await self.social("google", "g-1"))
        ms = bearer(await self.social("microsoft", "m-1", client=self.other_client()))
        # Apple: no name round (its name comes once, in a form post this flow does not use).
        apple = bearer(await self.social("apple", "a-1", client=self.other_client()))
        r = await self.client.post("/api/v1/auth/oidc/apple/start", headers=apple, json={"purpose": "name"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "name_not_offered"))
        # A provider the account did not sign up with.
        await self.link("microsoft", "m-extra", headers)
        r = await self.client.post("/api/v1/auth/oidc/microsoft/start", headers=headers, json={"purpose": "name"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "name_not_offered"))
        # A password account never signed up with a provider.
        _, name, _ = await self.make_user()
        plain = await self.auth(name)
        r = await self.client.post("/api/v1/auth/oidc/google/start", headers=plain, json={"purpose": "name"})
        self.assertEqual(r.status_code, 409)
        # Not for the app's return address, and a session is needed.
        r = await self.client.post("/api/v1/auth/oidc/google/start", headers=headers,
                                   json={"purpose": "name", "return_to": "/app/oidc"})
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "name_not_offered"))
        r = await self.client.post("/api/v1/auth/oidc/google/start", json={"purpose": "name"})
        self.assertEqual(r.status_code, 401)
        # Somebody else's provider account proves nothing; a name with no usable letters gives no username.
        self.assertEqual((await self.name_round(headers, "google", "g-other", {"name": "Ana"}))[1],
                         {"oidc_error": "identity_mismatch", "welcome": "1", "next": "/staff/"})
        path, query, fragment = await self.name_round(headers, "google", "g-1", {"name": "李小龍"})
        self.assertEqual((query["oidc_error"], fragment), ("name_unusable", ""))
        self.assertIsNotNone(ms)

    async def test_the_name_round_confirms_the_session_like_a_reauth(self) -> None:
        headers = bearer(await self.social("google", "g-1"))
        await self.age_confirmation()
        r = await self.client.patch("/api/v1/me", headers=headers, json={"username": "ana.silva"})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "confirmation_required"))
        await self.name_round(headers, "google", "g-1", {"name": "Ana Silva"})
        r = await self.client.patch("/api/v1/me", headers=headers, json={"username": "ana.silva"})
        self.assertEqual(r.status_code, 200, r.text)


class RenameTests(LoginTestCase):
    """Any account renames itself, confirming with its own login method."""

    async def rename(self, headers: dict[str, str], username: str, **body: Any) -> httpx.Response:
        return await self.client.patch("/api/v1/me", headers=headers, json={"username": username, **body})

    async def test_a_passkey_confirms(self) -> None:
        headers = bearer(await self.social("google", "g-1"))
        authenticator, added = await self.add_passkey(headers, password="")
        self.assertEqual(added.status_code, 201, added.text)
        await self.age_confirmation()
        self.assertEqual((await self.rename(headers, "ana.silva")).json()["detail"], "confirmation_required")
        parts = (await self.client.post("/api/v1/auth/stepup/passkey/options", headers=headers)).json()
        r = await self.client.post("/api/v1/auth/stepup/passkey", headers=headers, json={
            "challenge_token": parts["challenge_token"], "credential": authenticator.get(parts["options"], ORIGIN)})
        self.assertEqual(r.status_code, 200, r.text)
        r = await self.rename(headers, "ana.silva")
        self.assertEqual((r.status_code, r.json()["username"]), (200, "ana.silva"))

    async def test_a_linked_provider_confirms(self) -> None:
        headers = bearer(await self.social("microsoft", "m-1"))
        await self.age_confirmation()
        self.assertEqual((await self.rename(headers, "ana.silva")).status_code, 403)
        params, _ = await self.begin("microsoft", headers=headers, purpose="reauth")
        self.assertEqual(self.landed(await self.callback("microsoft", params, "m-1"))[1], {"oidc": "reauth"})
        self.assertEqual((await self.rename(headers, "ana.silva")).status_code, 200)

    async def test_a_totp_code_confirms(self) -> None:
        headers = bearer(await self.social("google", "g-1"))
        r = await self.client.post("/api/v1/auth/totp/enrol", headers=headers, json={"password": ""})
        self.assertEqual(r.status_code, 200, r.text)
        secret = r.json()["secret"]
        r = await self.client.post("/api/v1/auth/totp/confirm", headers=headers, json={"code": self.code(secret)})
        self.assertEqual(r.status_code, 204, r.text)
        await self.age_confirmation()
        self.assertEqual((await self.rename(headers, "ana.silva")).status_code, 403)
        r = await self.client.post("/api/v1/auth/stepup/totp", headers=headers, json={"code": self.code(secret)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((await self.rename(headers, "ana.silva")).status_code, 200)

    async def test_a_password_account_confirms_with_its_password(self) -> None:
        _, name, _ = await self.make_user()
        headers = await self.auth(name)
        self.assertEqual((await self.rename(headers, "novo.nome")).json()["detail"], "invalid_password")
        self.assertEqual((await self.rename(headers, "novo.nome", password="wrong")).status_code, 403)
        r = await self.rename(headers, "novo.nome", password=PASSWORD)
        self.assertEqual((r.status_code, r.json()["username"]), (200, "novo.nome"))
        self.assertEqual(await self.audit("profile_update"), [{"fields": ["username"]}])

    async def test_the_rules_of_a_username_still_hold(self) -> None:
        headers = bearer(await self.social("google", "g-1"))
        taken_id, taken, _ = await self.make_user("ocupado")
        self.assertIsNotNone(taken_id)
        r = await self.rename(headers, taken)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "username_or_email_taken"))
        for bad, code in (("ab", "username_invalid"), ("Ana Silva", "username_invalid"),
                          (personal_data.ERASED_PREFIX + "abc", "username_reserved")):
            r = await self.rename(headers, bad)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, code), bad)
        r = await self.rename(headers, "  Ana.Silva ")  # trimmed and lower-cased, as everywhere
        self.assertEqual(r.json()["username"], "ana.silva")
        again = await self.client.get("/api/v1/me", headers=headers)
        self.assertEqual(again.json()["username"], "ana.silva")


class ConsentErrorTests(LoginTestCase):
    async def test_the_login_page_puts_the_error_next_to_the_box(self) -> None:
        template = (staff_pages.TEMPLATE_DIR / "login.html").read_text(encoding="utf-8")
        self.assertIn('<p id="consent-error" class="field-error" role="alert" hidden></p>', template)
        self.assertLess(template.index('id="consent-error"'), template.index('id="consent"'))  # the note is at the box
        script = (staff_pages.STATIC / "login.js").read_text(encoding="utf-8")
        for needle in ("function consentMissing", "aria-invalid", "box.focus()", "scrollIntoView",
                       "classList.add('invalid')", "oidc_err_consent_required"):
            self.assertIn(needle, script)
        self.assertIn("failure === 'consent_required'", script)
        css = (staff_pages.STATIC / "staff.css").read_text(encoding="utf-8")
        self.assertIn(".field-error", css)
        self.assertIn(".consent.invalid", css)
        for lang in STRINGS:
            r = await self.client.get("/staff/login", params={"lang": lang})
            self.assertIn('id="consent-error"', r.text, lang)
            self.assertIn('role="alert"', r.text, lang)

    async def test_the_text_points_at_the_box_in_every_language(self) -> None:
        where = {"pt": "abaixo", "en": "below", "de": "darunter", "zh-tw": "下"}
        texts = {lang: STRINGS[lang]["oidc_err_consent_required"] for lang in STRINGS}
        self.assertEqual(len(set(texts.values())), 4)
        for lang, text in texts.items():
            with self.subTest(lang=lang):
                self.assertIn(where[lang], text)
                for stale in ("acima", "above", "oben", "上方"):
                    self.assertNotIn(stale, text)
        # pt-PT in the staff texts' own form: an infinitive, no gendered form of address.
        self.assertTrue(texts["pt"].startswith("Para criar uma conta nova, marcar"))

    async def test_the_consent_text_says_the_providers_name_is_read_only_on_request_and_not_kept(self) -> None:
        said = {"pt": "não fica guardado", "en": "is not kept", "de": "nicht gespeichert", "zh-tw": "不會保存"}
        for lang, words in said.items():
            self.assertIn(words, STRINGS[lang]["login_consent"], lang)

    async def test_a_login_without_the_box_is_still_refused_and_makes_no_account(self) -> None:
        params, r = await self.begin("google", consent=False)
        self.assertEqual(r.status_code, 200)
        _, query, _ = self.landed(await self.callback("google", params, "g-no-box"))
        self.assertEqual(query, {"oidc_error": "consent_required"})
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 0)


class MergeTests(LoginTestCase):
    """Account A (Google) and account B (Microsoft, made by a second social login)."""

    async def two(self) -> tuple[dict[str, Any], dict[str, Any]]:
        a = await self.social("google", "g-1")
        b = await self.social("microsoft", "m-1", client=self.other_client())
        return a, b

    async def ticket_for(self, headers: dict[str, str], provider: str = "microsoft", subject: str = "m-1",
                         password: str = PASSWORD) -> str:
        params, r = await self.begin(provider, headers=headers, purpose="link", password=password)
        self.assertEqual(r.status_code, 200, r.text)
        path, query, fragment = self.landed(await self.callback(provider, params, subject))
        self.assertEqual((path, query), ("/staff/login", {"oidc": "merge"}), query)
        return parse_qs(fragment)["merge"][0]

    async def merge(self, headers: dict[str, str], ticket: str, **body: Any) -> httpx.Response:
        return await self.client.post("/api/v1/me/merge", headers=headers, json={"ticket": ticket, **body})

    async def preview(self, headers: dict[str, str], ticket: str) -> httpx.Response:
        return await self.client.post("/api/v1/me/merge/preview", headers=headers, json={"ticket": ticket})

    async def seed(self, a: uuid.UUID, b: uuid.UUID) -> dict[str, Any]:
        """Rows of both accounts in every table the merge moves, with the conflicts it must resolve."""
        sql = self.fetch
        f1 = (await sql("INSERT INTO fields (id, name, slug) VALUES (gen_random_uuid(), 'Um', 'um') RETURNING id"))[0][0]
        f2 = (await sql("INSERT INTO fields (id, name, slug) VALUES (gen_random_uuid(), 'Dois', 'dois') RETURNING id"))[0][0]
        for uid, role, field in ((a, 1, f1), (b, 1, f1), (b, 6, f1), (b, 2, f2)):
            await sql("INSERT INTO user_field_roles (id, user_id, field_id, role_id, granted_by) "
                      "VALUES (gen_random_uuid(), $1, $2, $3, $4)", uid, field, role, b)
        for uid, field in ((a, f1), (b, f1), (b, f2)):
            await sql("INSERT INTO consents (id, user_id, purpose, field_id, notice_version) "
                      "VALUES (gen_random_uuid(), $1, 'chrono_sharing', $2, 'v1')", uid, field)
        c1 = (await sql("INSERT INTO clubs (id, name, short_name, slug, created_by) VALUES (gen_random_uuid(), "
                        "'C1', 'c1', 'c1', $1) RETURNING id", b))[0][0]
        c2 = (await sql("INSERT INTO clubs (id, name, short_name, slug) VALUES (gen_random_uuid(), 'C2', 'c2', 'c2') "
                        "RETURNING id"))[0][0]
        for uid, club in ((a, c1), (b, c1), (b, c2)):
            await sql("INSERT INTO club_members (id, club_id, user_id, added_by) VALUES (gen_random_uuid(), $1, $2, $3)",
                      club, uid, b)
        g1 = (await sql("INSERT INTO scheduled_games (id, field_id, title, starts_at, ends_at) VALUES "
                        "(gen_random_uuid(), $1, 'g1', now() + interval '1 day', now() + interval '2 days') RETURNING id",
                        f1))[0][0]
        g2 = (await sql("INSERT INTO scheduled_games (id, field_id, title, starts_at, ends_at, created_by) VALUES "
                        "(gen_random_uuid(), $1, 'g2', now() + interval '3 day', now() + interval '4 days', $2) "
                        "RETURNING id", f1, b))[0][0]
        for uid, game, pid in ((a, g1, "p-aaa"), (b, g1, "p-bbb"), (b, g2, "p-ccc")):
            await sql("INSERT INTO game_registrations (id, scheduled_game, field_id, user_id, player_id, display_name) "
                      "VALUES (gen_random_uuid(), $1, $2, $3, $4, 'Nome')", game, f1, uid, pid)
        await sql("INSERT INTO field_player_ids (id, field_id, player_id, user_id) VALUES "
                  "(gen_random_uuid(), $1, 'p-bplayer', $2)", f1, b)
        await sql("INSERT INTO player_id_claims (id, user_id, field_id, player_id, secret_sha256) VALUES "
                  "(gen_random_uuid(), $1, $2, 'p-bplayer2', $3)", b, f1, "0" * 64)
        await sql("INSERT INTO marshal_keys (id, field_id, marshal_id, name, public_key, user_id, source, valid_from, "
                  "revoked_by) VALUES (gen_random_uuid(), $1, 'm1', 'M', $2, $3, 'account', now(), $3)",
                  f1, b"\x01" * 32, b)
        await sql("INSERT INTO atak_certs (id, field_id, serial, sha256, device_name, holder_id, issued_by, issued_at, "
                  "not_after) VALUES (gen_random_uuid(), $1, 'ab01', $2, 'Tab', $3, $3, now(), now() + interval '1 day')",
                  f1, "a" * 64, b)
        await sql("INSERT INTO hub_share_links (user_id, person_id) VALUES ($1, gen_random_uuid())", b)
        return {"f1": f1, "f2": f2, "c1": c1, "c2": c2, "g1": g1, "g2": g2}

    async def count(self, table: str, column: str, user: uuid.UUID) -> int:
        return (await self.fetch(f"SELECT count(*) FROM {table} WHERE {column} = $1", user))[0][0]

    async def test_linking_a_login_of_another_account_offers_a_merge_and_changes_nothing(self) -> None:
        a, b = await self.two()
        ticket = await self.ticket_for(bearer(a))
        self.assertEqual((await self.fetch("SELECT count(*) FROM user_identities WHERE user_id = $1",
                                           uuid.UUID(a["user"]["id"])))[0][0], 1)
        info = (await self.preview(bearer(a), ticket)).json()
        self.assertEqual(info, {"username": b["user"]["username"], "provider": "microsoft", "label": "Microsoft",
                                "logins": ["Microsoft"], "passkeys": 0, "other_has_password": False,
                                "has_password": False, "blocked": None})
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 2)  # the preview changed nothing

    async def test_the_merge_moves_everything_and_keeps_a(self) -> None:
        a, b = await self.two()
        ua, ub = uuid.UUID(a["user"]["id"]), uuid.UUID(b["user"]["id"])
        b_name = b["user"]["username"]
        ids = await self.seed(ua, ub)
        # B also has a passkey.
        _, added = await self.add_passkey(bearer(b), password="")
        self.assertEqual(added.status_code, 201)
        ticket = await self.ticket_for(bearer(a))
        r = await self.merge(bearer(a), ticket)
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual((body["merged"], body["password_dropped"], body["has_password"]), (True, False, False))
        for key in ("user_identities", "passkeys", "user_field_roles", "consents", "club_members", "game_registrations",
                    "field_player_ids", "player_id_claims", "marshal_keys", "atak_certs.holder_id", "hub_share_links",
                    "clubs.created_by"):
            self.assertIn(key, body["moved"])
        # Every table moved, and the conflicts kept A's.
        for table, column in (("user_identities", "user_id"), ("passkeys", "user_id"), ("field_player_ids", "user_id"),
                              ("player_id_claims", "user_id"), ("marshal_keys", "user_id"), ("hub_share_links", "user_id"),
                              ("atak_certs", "holder_id"), ("clubs", "created_by"), ("scheduled_games", "created_by"),
                              ("user_field_roles", "granted_by"), ("marshal_keys", "revoked_by"),
                              ("atak_certs", "issued_by"), ("club_members", "added_by")):
            with self.subTest(table=table, column=column):
                self.assertEqual(await self.count(table, column, ub), 0)
                self.assertGreaterEqual(await self.count(table, column, ua), 1)
        identities = await self.fetch("SELECT provider FROM user_identities WHERE user_id = $1 ORDER BY provider", ua)
        self.assertEqual([i[0] for i in identities], ["google", "microsoft"])
        roles = await self.fetch("SELECT field_id, role_id FROM user_field_roles WHERE user_id = $1 ORDER BY role_id", ua)
        self.assertEqual([(r[0], r[1]) for r in roles], [(ids["f1"], 1), (ids["f2"], 2), (ids["f1"], 6)])  # one player role
        self.assertEqual(await self.count("user_field_roles", "user_id", ub), 0)
        consents = await self.fetch("SELECT purpose, field_id, withdrawn_at FROM consents WHERE user_id = $1 "
                                    "ORDER BY purpose, field_id", ua)
        self.assertEqual(sum(1 for c in consents if c[0] == "account"), 1)
        self.assertEqual(sum(1 for c in consents if c[0] == "chrono_sharing"), 2)  # f1 once, f2 moved
        self.assertEqual(await self.count("consents", "user_id", ub), 0)
        members = await self.fetch("SELECT club_id FROM club_members WHERE user_id = $1", ua)
        self.assertEqual(sorted(str(m[0]) for m in members), sorted([str(ids["c1"]), str(ids["c2"])]))
        regs = {r["player_id"]: r for r in await self.fetch("SELECT * FROM game_registrations")}
        self.assertEqual(regs["p-aaa"]["user_id"], ua)
        self.assertEqual(regs["p-ccc"]["user_id"], ua)       # moved
        self.assertIsNone(regs["p-bbb"]["user_id"])           # the duplicate for A's game: dropped from B
        self.assertEqual((regs["p-bbb"]["status"], regs["p-bbb"]["display_name"]), ("cancelled", None))
        self.assertEqual(regs["p-ccc"]["status"], "registered")
        # B is anonymised and kept (the audit log points at it); its sessions are gone; its name is free.
        row = (await self.fetch("SELECT * FROM users WHERE id = $1", ub))[0]
        self.assertTrue(row["username"].startswith(personal_data.ERASED_PREFIX))
        self.assertEqual(row["password_hash"], personal_data.ERASED_PASSWORD)
        self.assertIsNone(row["email"])
        self.assertEqual((await self.client.get("/api/v1/me", headers=bearer(b))).status_code, 401)
        self.assertEqual(await self.count("sessions", "user_id", ub), (await self.fetch(
            "SELECT count(*) FROM sessions WHERE user_id = $1 AND revoked_at IS NOT NULL", ub))[0][0])
        self.assertEqual((await self.fetch("SELECT count(*) FROM users WHERE username = $1", b_name))[0][0], 0)
        # A's own things stay.
        self.assertEqual((await self.client.get("/api/v1/me", headers=bearer(a))).json()["username"],
                         a["user"]["username"])
        # Both providers now sign in to A.
        for provider, subject in (("google", "g-1"), ("microsoft", "m-1")):
            again = await self.social(provider, subject, client=self.other_client())
            self.assertEqual(again["user"]["id"], str(ua))
        # The audit entries of both, with counts and ids and no names.
        merged = await self.audit("account_merge")
        self.assertEqual(len(merged), 1)
        self.assertEqual((merged[0]["from"], merged[0]["provider"]), (str(ub), "microsoft"))
        self.assertGreater(merged[0]["moved"]["user_field_roles"], 0)
        self.assertEqual(await self.audit("account_merged_into"), [{"into": str(ua), "provider": "microsoft"}])
        entries = await self.fetch("SELECT user_id, action FROM audit_log WHERE action IN "
                                   "('account_merge', 'account_merged_into') ORDER BY id")
        self.assertEqual([(e[0], e[1]) for e in entries], [(ua, "account_merge"), (ub, "account_merged_into")])
        self.assertNotIn(b_name, json.dumps([r["details"] for r in await self.fetch("SELECT details FROM audit_log")]))

    async def test_every_column_that_points_at_an_account_is_covered(self) -> None:
        columns = {(t.name, c.name) for t, c in account_merge.user_columns()}
        for wanted in (("user_identities", "user_id"), ("passkeys", "user_id"), ("user_field_roles", "user_id"),
                       ("user_game_roles", "user_id"), ("game_registrations", "user_id"), ("consents", "user_id"),
                       ("club_members", "user_id"), ("field_player_ids", "user_id"), ("player_id_claims", "user_id"),
                       ("hub_share_links", "user_id"), ("marshal_keys", "user_id"), ("atak_certs", "holder_id"),
                       ("clubs", "created_by"), ("firmware_releases", "added_by"), ("club_reports", "reporter_id")):
            self.assertIn(wanted, columns)
        self.assertNotIn(("audit_log", "user_id"), columns)  # B's history stays under B's id
        self.assertEqual(account_merge.NOT_MOVED, {"audit_log", "sessions", "oidc_logins", "users"})

    async def test_game_roles_move_and_deduplicate(self) -> None:
        a, b = await self.two()
        ua, ub = uuid.UUID(a["user"]["id"]), uuid.UUID(b["user"]["id"])
        f = (await self.fetch("INSERT INTO fields (id, name, slug) VALUES (gen_random_uuid(), 'F', 'f') RETURNING id"))[0][0]
        g = (await self.fetch("INSERT INTO games (id, field_id, game_id, game_seed, name, mode_id, teams, state, "
                              "controller_created_at) VALUES (gen_random_uuid(), $1, 1, 1, 'G', 'm', '[]', 'ready', now()) "
                              "RETURNING id", f))[0][0]
        for uid, role in ((ua, 1), (ub, 1), (ub, 6)):
            await self.fetch("INSERT INTO user_game_roles (id, user_id, game, role_id) VALUES (gen_random_uuid(), $1, $2, $3)",
                             uid, g, role)
        r = await self.merge(bearer(a), await self.ticket_for(bearer(a)))
        self.assertEqual(r.status_code, 200, r.text)
        rows = await self.fetch("SELECT user_id, role_id FROM user_game_roles ORDER BY role_id")
        self.assertEqual([(x[0], x[1]) for x in rows], [(ua, 1), (ua, 6)])

    async def test_a_staff_account_is_not_merged(self) -> None:
        a, b = await self.two()
        ua, ub = uuid.UUID(a["user"]["id"]), uuid.UUID(b["user"]["id"])
        f = (await self.fetch("INSERT INTO fields (id, name, slug) VALUES (gen_random_uuid(), 'F', 'f') RETURNING id"))[0][0]
        for role in (5, 4, 7):  # gm, marshal, admin
            with self.subTest(role=role):
                await self.fetch("DELETE FROM user_field_roles")
                await self.fetch("INSERT INTO user_field_roles (id, user_id, field_id, role_id) VALUES "
                                 "(gen_random_uuid(), $1, $2, $3)", ub, f, role)
                ticket = await self.ticket_for(bearer(a))
                self.assertEqual((await self.preview(bearer(a), ticket)).json()["blocked"], "merge_staff_account")
                r = await self.merge(bearer(a), ticket)
                self.assertEqual((r.status_code, r.json()["detail"]), (409, "merge_staff_account"))
                self.assertEqual(await self.count("user_identities", "user_id", ub), 1)
                self.assertEqual(await self.count("user_field_roles", "user_id", ub), 1)
        await self.fetch("DELETE FROM user_field_roles")
        await self.fetch("UPDATE users SET server_admin = true WHERE id = $1", ub)
        ticket = await self.ticket_for(bearer(a))
        self.assertEqual((await self.merge(bearer(a), ticket)).json()["detail"], "merge_staff_account")
        await self.fetch("UPDATE users SET server_admin = false WHERE id = $1", ub)
        g = (await self.fetch("INSERT INTO games (id, field_id, game_id, game_seed, name, mode_id, teams, state, "
                              "controller_created_at) VALUES (gen_random_uuid(), $1, 1, 1, 'G', 'm', '[]', 'ready', now()) "
                              "RETURNING id", f))[0][0]
        await self.fetch("INSERT INTO user_game_roles (id, user_id, game, role_id) VALUES (gen_random_uuid(), $1, $2, 5)",
                         ub, g)
        ticket = await self.ticket_for(bearer(a))
        self.assertEqual((await self.merge(bearer(a), ticket)).json()["detail"], "merge_staff_account")
        self.assertEqual(await self.count("user_identities", "user_id", ua), 1)
        # A staff role on A's side is fine: A keeps it, and B's plain roles come in.
        await self.fetch("DELETE FROM user_game_roles")
        await self.fetch("INSERT INTO user_field_roles (id, user_id, field_id, role_id) VALUES (gen_random_uuid(), $1, $2, 5)",
                         ua, f)
        await self.fetch("INSERT INTO passkeys (id, user_id, credential_id, public_key, name, rp_id) VALUES "
                         "(gen_random_uuid(), $1, $2, $3, 'k', 'server.test')", ua, secrets.token_bytes(16), b"x")
        await self.second_factor(bearer(a))  # a staff account's merge needs a second factor (SR-1)
        r = await self.merge(bearer(a), await self.ticket_for(bearer(a)))
        self.assertEqual(r.status_code, 200, r.text)

    async def test_a_social_session_cannot_merge_into_a_staff_account(self) -> None:
        """SRV-1 path 2: an attacker's account B, with a passkey the attacker holds, merged into a staff A."""
        a, b = await self.two()
        ua, ub = uuid.UUID(a["user"]["id"]), uuid.UUID(b["user"]["id"])
        f = (await self.fetch("INSERT INTO fields (id, name, slug) VALUES (gen_random_uuid(), 'F', 'f') RETURNING id"))[0][0]
        await self.fetch("INSERT INTO user_field_roles (id, user_id, field_id, role_id) VALUES (gen_random_uuid(), $1, $2, 5)",
                         ua, f)
        await self.fetch("INSERT INTO passkeys (id, user_id, credential_id, public_key, name, rp_id) VALUES "
                         "(gen_random_uuid(), $1, $2, $3, 'owner', 'server.test')", ua, b"owner", b"x")
        await self.fetch("INSERT INTO passkeys (id, user_id, credential_id, public_key, name, rp_id) VALUES "
                         "(gen_random_uuid(), $1, $2, $3, 'attacker', 'server.test')", ub, b"attacker", b"x")
        # The social session of A (mfa false) cannot even start the link round that yields a ticket ...
        r = await self.client.post("/api/v1/auth/oidc/microsoft/start", headers=bearer(a),
                                   json={"purpose": "link", "password": ""})
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "mfa_required"))
        # ... and after a second factor, B's passkeys are not carried into a staff account.
        await self.second_factor(bearer(a))
        ticket = await self.ticket_for(bearer(a))
        self.assertEqual((await self.preview(bearer(a), ticket)).json()["blocked"], "merge_passkeys_into_staff")
        await self.fetch("UPDATE sessions SET mfa = false WHERE user_id = $1", ua)
        r = await self.merge(bearer(a), ticket)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "mfa_required"))
        await self.second_factor(bearer(a))
        r = await self.merge(bearer(a), ticket)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "merge_passkeys_into_staff"))
        self.assertEqual(await self.count("passkeys", "user_id", ua), 1)
        self.assertEqual(await self.count("passkeys", "user_id", ub), 1)
        # Without the passkeys it goes through, with A's second factor.
        await self.fetch("DELETE FROM passkeys WHERE user_id = $1", ub)
        r = await self.merge(bearer(a), await self.ticket_for(bearer(a)))
        self.assertEqual(r.status_code, 200, r.text)

    async def test_a_plain_account_merges_with_b_passkeys_as_before(self) -> None:
        a, b = await self.two()
        ub = uuid.UUID(b["user"]["id"])
        await self.fetch("INSERT INTO passkeys (id, user_id, credential_id, public_key, name, rp_id) VALUES "
                         "(gen_random_uuid(), $1, $2, $3, 'k', 'server.test')", ub, b"b-key", b"x")
        r = await self.merge(bearer(a), await self.ticket_for(bearer(a)))
        self.assertEqual((r.status_code, r.json()["moved"].get("passkeys")), (200, 1))

    async def test_two_logins_of_one_provider_or_too_many_passkeys_refuse(self) -> None:
        a, b = await self.two()
        ua, ub = uuid.UUID(a["user"]["id"]), uuid.UUID(b["user"]["id"])
        await self.fetch("INSERT INTO user_identities (id, user_id, provider, subject) VALUES "
                         "(gen_random_uuid(), $1, 'google', 'g-of-b')", ub)
        ticket = await self.ticket_for(bearer(a))
        self.assertEqual((await self.preview(bearer(a), ticket)).json()["blocked"], "merge_provider_conflict")
        r = await self.merge(bearer(a), ticket)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "merge_provider_conflict"))
        await self.fetch("DELETE FROM user_identities WHERE subject = 'g-of-b'")
        for i in range(20):
            await self.fetch("INSERT INTO passkeys (id, user_id, credential_id, public_key, name, rp_id) VALUES "
                             "(gen_random_uuid(), $1, $2, $3, 'k', 'server.test')", ua, secrets.token_bytes(16), b"x")
        await self.second_factor(bearer(a))  # A has passkeys, so its merge needs a second factor (SR-1)
        await self.fetch("INSERT INTO passkeys (id, user_id, credential_id, public_key, name, rp_id) VALUES "
                         "(gen_random_uuid(), $1, $2, $3, 'k', 'server.test')", ub, secrets.token_bytes(16), b"x")
        r = await self.merge(bearer(a), await self.ticket_for(bearer(a)))
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "merge_too_many_passkeys"))

    async def test_the_ticket_is_the_callers_single_use_and_signed(self) -> None:
        a, b = await self.two()
        other = await self.social("apple", "a-1", client=self.other_client())
        ticket = await self.ticket_for(bearer(a))
        for headers, tampered in ((bearer(other), ticket), (bearer(a), ticket[:-3] + "AAA"), (bearer(a), "nope")):
            r = await self.merge(headers, tampered)
            self.assertEqual((r.status_code, r.json()["detail"]), (400, "merge_ticket_invalid"))
        self.assertEqual((await self.merge(bearer(a), ticket)).status_code, 200)
        again = await self.merge(bearer(a), ticket)
        self.assertEqual((again.status_code, again.json()["detail"]), (400, "merge_ticket_invalid"))
        self.assertEqual((await self.client.post("/api/v1/me/merge", json={"ticket": ticket})).status_code, 401)

    async def test_a_ticket_for_an_account_that_is_gone_is_refused(self) -> None:
        a, b = await self.two()
        ticket = await self.ticket_for(bearer(a))
        await self.fetch("DELETE FROM user_identities WHERE subject = 'm-1'")
        r = await self.merge(bearer(a), ticket)
        self.assertEqual((r.status_code, r.json()["detail"]), (409, "merge_ticket_invalid"))

    async def test_the_merge_is_confirmed_like_a_sensitive_change(self) -> None:
        a, b = await self.two()
        ticket = await self.ticket_for(bearer(a))
        await self.age_confirmation()
        r = await self.merge(bearer(a), ticket)
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "confirmation_required"))
        self.assertEqual(await self.count("user_identities", "user_id", uuid.UUID(b["user"]["id"])), 1)
        # A provider login confirms it again, and the same ticket (not spent by the refusal) goes through.
        params, _ = await self.begin("google", headers=bearer(a), purpose="reauth")
        self.landed(await self.callback("google", params, "g-1"))
        self.assertEqual((await self.merge(bearer(a), ticket)).status_code, 200)

    async def test_a_password_account_confirms_with_its_password_and_keeps_it(self) -> None:
        _, name, _ = await self.make_user()
        headers = await self.auth(name)
        await self.link("google", "g-1", headers)
        b = await self.social("microsoft", "m-1", client=self.other_client())
        ticket = await self.ticket_for(headers)
        r = await self.merge(headers, ticket, password="wrong")
        self.assertEqual((r.status_code, r.json()["detail"]), (403, "invalid_password"))
        r = await self.merge(headers, ticket, password=PASSWORD)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["password_dropped"], r.json()["has_password"]), (False, True))
        await self.auth(name)  # the password still logs in
        self.assertEqual((await self.client.get("/api/v1/me", headers=bearer(b))).status_code, 401)

    async def test_a_password_of_the_other_account_is_never_carried_over(self) -> None:
        a = await self.social("google", "g-1")
        _, name, _ = await self.make_user()
        b_headers = await self.auth(name)
        await self.link("microsoft", "m-1", b_headers)
        ticket = await self.ticket_for(bearer(a))
        info = (await self.preview(bearer(a), ticket)).json()
        self.assertEqual((info["other_has_password"], info["has_password"], info["username"]), (True, False, name))
        r = await self.merge(bearer(a), ticket)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["password_dropped"], r.json()["has_password"]), (True, False))
        row = (await self.fetch("SELECT password_hash FROM users WHERE id = $1", uuid.UUID(a["user"]["id"])))[0]
        self.assertIsNone(row["password_hash"])
        login = await self.client.post("/api/v1/auth/login", json={"username": name, "password": PASSWORD})
        self.assertEqual(login.status_code, 401)  # B's old name and password reach nothing

    async def test_a_login_with_the_other_identity_while_a_is_open_is_just_a_login_to_b(self) -> None:
        a, b = await self.two()
        # A's session is open (a bearer token in the browser); the browser signs in with Microsoft.
        again = await self.social("microsoft", "m-1", client=self.other_client())
        self.assertEqual(again["user"]["id"], b["user"]["id"])
        self.assertEqual((await self.fetch("SELECT count(*) FROM users"))[0][0], 2)
        self.assertEqual(await self.count("user_identities", "user_id", uuid.UUID(a["user"]["id"])), 1)
        self.assertEqual(await self.audit("account_merge"), [])
        # The Account page's link round for the same identity is what offers the merge, nothing else.
        self.assertEqual((await self.client.get("/api/v1/me", headers=bearer(a))).status_code, 200)

    async def test_the_app_never_gets_a_merge_ticket(self) -> None:
        a, b = await self.two()
        r = await self.client.post("/api/v1/auth/oidc/microsoft/start", headers=bearer(a), json={
            "purpose": "link", "password": "", "return_to": f"{ORIGIN}/app/oidc?s=lnk"})
        self.assertEqual(r.status_code, 200, r.text)
        async with self.other_client() as browser:
            go = await browser.get(r.json()["browser_url"] + "&go=1")
            params = self.idp.authorize(go.headers["location"])
            path, query, fragment = self.landed(await self.callback("microsoft", params, "m-1", client=browser))
        self.assertEqual((path, query, fragment), ("/app/oidc", {"s": "lnk", "oidc_error": "identity_taken"}, ""))

    async def test_the_same_provider_already_on_this_account_is_not_a_merge(self) -> None:
        a, b = await self.two()
        params, _ = await self.begin("microsoft", headers=bearer(b), purpose="link", password="")
        self.assertEqual(self.landed(await self.callback("microsoft", params, "m-1"))[1], {"oidc_error": "already_linked"})
        # A has a different Microsoft login already: nothing to merge into.
        await self.fetch("INSERT INTO user_identities (id, user_id, provider, subject) VALUES "
                         "(gen_random_uuid(), $1, 'microsoft', 'm-mine')", uuid.UUID(a["user"]["id"]))
        params, _ = await self.begin("microsoft", headers=bearer(a), purpose="link", password="")
        self.assertEqual(self.landed(await self.callback("microsoft", params, "m-1"))[1],
                         {"oidc_error": "provider_already_linked"})
