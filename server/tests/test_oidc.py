# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The OpenID Connect client without a database: ID token validation against a local JWKS, the JWKS cache, the
authorization URL, the token request, Apple's client secret (decisions LG-1, LG-8). A fake provider signs the
test tokens (tests/login_fakes.py); nothing reaches the Internet."""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from atalaia_server import oidc
from atalaia_server.config import ConfigError, OidcClient, Settings

from .login_fakes import FakeIdp, apple_key_pem

DB = "postgresql+asyncpg://u:p@localhost:5432/d"
NONCE = "nonce-1"
TENANT_A = "11111111-2222-3333-4444-555555555555"


class OidcTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.idp = FakeIdp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        key_file = Path(self.dir.name) / "AuthKey.p8"
        key_file.write_bytes(apple_key_pem())
        self.now = time.time()
        self.settings = Settings(allow_signup_without_notice=True, database_url=DB, secret_key="s" * 43, oidc=(
            OidcClient("google", "google-id", client_secret="google-secret"),
            OidcClient("microsoft", "ms-id", client_secret="ms-secret", tenant="common"),
            OidcClient("apple", "apple.services.id", team_id="TEAM123456", key_id="KEY1234567",
                       key_file=str(key_file))))
        self.service = oidc.OidcService(self.settings, http=self.idp, clock=lambda: self.now)

    def token(self, provider: str = "google", subject: str = "sub-1", **over: Any) -> str:
        client = self.service.clients[provider]
        return self.idp.id_token(self.idp.claims(provider, client.client_id, subject, NONCE, **over))

    async def refused(self, token: str, provider: str = "google", nonce: str = NONCE) -> None:
        with self.assertRaises(oidc.OidcError) as caught:
            await self.service.validate(provider, token, nonce)
        self.assertEqual(caught.exception.code, "id_token_invalid")


class ValidationTests(OidcTestCase):
    async def test_a_good_token_gives_its_subject_for_each_provider(self) -> None:
        for provider in ("google", "microsoft", "apple"):
            with self.subTest(provider=provider):
                self.assertEqual(await self.service.validate(provider, self.token(provider, "abc"), NONCE), "abc")

    async def test_the_google_issuer_may_be_written_either_way(self) -> None:
        self.assertEqual(await self.service.validate("google", self.token(iss="accounts.google.com"), NONCE), "sub-1")

    async def test_wrong_audience_issuer_nonce(self) -> None:
        await self.refused(self.token(aud="somebody-else"))
        await self.refused(self.token(aud=["google-id", "another"]))
        await self.refused(self.token(iss="https://evil.example"))
        await self.refused(self.token("apple", iss="https://accounts.google.com"), "apple")
        await self.refused(self.token(), nonce="other")
        await self.refused(self.token(nonce=None))

    async def test_expiry_and_issue_time(self) -> None:
        now = int(time.time())
        await self.refused(self.token(exp=now - 3600))
        await self.refused(self.token(iat=now + 3600))
        await self.refused(self.token(exp=None))
        self.assertEqual(await self.service.validate("google", self.token(exp=now - 10), NONCE), "sub-1")  # leeway

    async def test_the_algorithm_is_fixed_not_read_from_the_token(self) -> None:
        claims = self.idp.claims("google", "google-id", "x", NONCE)
        await self.refused(self.idp.id_token(claims, alg="none"))
        await self.refused(self.idp.id_token(claims, alg="HS256"))
        # RS256, but signed by a key the provider never published.
        stranger = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        await self.refused(self.idp.id_token(claims, key=stranger))
        await self.refused("not a jwt")
        await self.refused("a.b.c")

    async def test_unknown_key_id(self) -> None:
        await self.refused(self.idp.id_token(self.idp.claims("google", "google-id", "x", NONCE), kid="nope"))

    async def test_the_subject(self) -> None:
        await self.refused(self.token(sub=""))
        await self.refused(self.token(sub="x" * 256))
        await self.refused(self.token(sub=42))
        await self.refused(self.token(sub=None))

    async def test_microsoft_issuer_follows_the_tenant(self) -> None:
        good = self.token("microsoft", iss="https://login.microsoftonline.com/tenant-1/v2.0", tid="tenant-1")
        self.assertEqual(await self.service.validate("microsoft", good, NONCE), "sub-1")
        await self.refused(self.token("microsoft", iss="https://login.microsoftonline.com/tenant-2/v2.0"), "microsoft")
        await self.refused(self.token("microsoft", tid=None, iss="https://login.microsoftonline.com/x/v2.0"),
                           "microsoft")

    async def test_microsoft_single_tenant_and_consumers(self) -> None:
        for tenant, tid, ok in (("consumers", oidc.MSA_TENANT, True), ("consumers", "tenant-1", False),
                                ("organizations", "tenant-1", True), ("organizations", oidc.MSA_TENANT, False),
                                (TENANT_A, TENANT_A, True), (TENANT_A, "tenant-2", False)):
            with self.subTest(tenant=tenant, tid=tid):
                service = oidc.OidcService(Settings(allow_signup_without_notice=True, database_url=DB, secret_key="s" * 43, oidc=(
                    OidcClient("microsoft", "ms-id", client_secret="x", tenant=tenant),)), http=self.idp)
                claims = self.idp.claims("microsoft", "ms-id", "s", NONCE, tid=tid,
                                         iss=f"https://login.microsoftonline.com/{tid}/v2.0")
                token = self.idp.id_token(claims)
                if ok:
                    self.assertEqual(await service.validate("microsoft", token, NONCE), "s")
                else:
                    with self.assertRaises(oidc.OidcError):
                        await service.validate("microsoft", token, NONCE)


class JwksCacheTests(OidcTestCase):
    def gets(self) -> int:
        return len([r for r in self.idp.requests if r[0] == "get"])

    async def test_the_jwks_is_cached(self) -> None:
        for _ in range(3):
            await self.service.validate("google", self.token(), NONCE)
        self.assertEqual(self.gets(), 1)
        self.now += oidc.JWKS_TTL_S + 1  # after an hour it is fetched again
        await self.service.validate("google", self.token(), NONCE)
        self.assertEqual(self.gets(), 2)

    async def test_a_rotated_key_is_followed(self) -> None:
        await self.service.validate("google", self.token(), NONCE)
        self.idp.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.idp.kid = "test-key-2"
        self.now += oidc.JWKS_MIN_REFETCH_S + 1
        self.assertEqual(await self.service.validate("google", self.token(), NONCE), "sub-1")
        self.assertEqual(self.gets(), 2)

    async def test_forged_key_ids_do_not_flood_the_provider(self) -> None:
        await self.service.validate("google", self.token(), NONCE)
        for i in range(20):
            await self.refused(self.idp.id_token(self.idp.claims("google", "google-id", "x", NONCE), kid=f"k{i}"))
        self.assertEqual(self.gets(), 1)  # an unknown kid right after a fetch is not a reason to fetch again

    async def test_the_providers_have_their_own_caches(self) -> None:
        for provider in ("google", "microsoft", "apple"):
            await self.service.validate(provider, self.token(provider), NONCE)
        urls = {r[1] for r in self.idp.requests if r[0] == "get"}
        self.assertEqual(urls, {"https://www.googleapis.com/oauth2/v3/certs",
                                "https://login.microsoftonline.com/common/discovery/v2.0/keys",
                                "https://appleid.apple.com/auth/keys"})


class RequestTests(OidcTestCase):
    def test_the_authorization_url(self) -> None:
        verifier = oidc.new_verifier()
        self.assertGreaterEqual(len(verifier), 43)
        for provider, host, scope in (("google", "accounts.google.com", "openid"),
                                      ("microsoft", "login.microsoftonline.com", "openid"),
                                      ("apple", "appleid.apple.com", None)):
            with self.subTest(provider=provider):
                url = self.service.authorization_url(provider, "https://campo.test/cb", "S", "N",
                                                     oidc.pkce_challenge(verifier))
                parts = urlsplit(url)
                q = {k: v[0] for k, v in parse_qs(parts.query).items()}
                self.assertEqual(parts.scheme + "://" + parts.netloc, "https://" + host)
                self.assertEqual((q["response_type"], q["state"], q["nonce"], q["redirect_uri"]),
                                 ("code", "S", "N", "https://campo.test/cb"))
                self.assertEqual((q["code_challenge_method"], q["code_challenge"]), ("S256", oidc.pkce_challenge(verifier)))
                self.assertEqual(q.get("scope"), scope)  # never email, never profile
                self.assertNotIn("email", url)
                self.assertNotIn("profile", url)

    def test_pkce_s256_known_answer(self) -> None:
        # RFC 7636 appendix B.
        self.assertEqual(oidc.pkce_challenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"),
                         "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")

    async def test_the_token_request_and_the_apple_secret(self) -> None:
        verifier = oidc.new_verifier()
        for provider in ("google", "apple"):
            with self.subTest(provider=provider):
                client = self.service.clients[provider]
                params = self.idp.authorize(self.service.authorization_url(
                    provider, "https://campo.test/cb", f"s-{provider}", NONCE, oidc.pkce_challenge(verifier)))
                code = self.idp.grant(params, self.idp.claims(provider, client.client_id, "sub-9", NONCE))
                token = await self.service.exchange(provider, code, "https://campo.test/cb", verifier)
                self.assertEqual(await self.service.validate(provider, token, NONCE), "sub-9")
        secret = jwt.decode(self.idp.last_client_secret, options={"verify_signature": False})
        header = jwt.get_unverified_header(self.idp.last_client_secret)
        self.assertEqual((header["alg"], header["kid"]), ("ES256", "KEY1234567"))
        self.assertEqual((secret["iss"], secret["sub"], secret["aud"]), ("TEAM123456", "apple.services.id",
                                                                      "https://appleid.apple.com"))
        self.assertLessEqual(secret["exp"] - secret["iat"], 600)
        # A wrong verifier is refused by the (fake) provider, as a real one's PKCE check would.
        params = self.idp.authorize(self.service.authorization_url("google", "https://campo.test/cb", "s2", NONCE,
                                                                   oidc.pkce_challenge(verifier)))
        code = self.idp.grant(params, self.idp.claims("google", "google-id", "x", NONCE))
        with self.assertRaises(oidc.OidcError):
            await self.service.exchange("google", code, "https://campo.test/cb", oidc.new_verifier())

    async def test_an_answer_without_an_id_token(self) -> None:
        class Empty:
            async def post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
                return {"access_token": "x"}

            async def get_json(self, url: str) -> dict[str, Any]:
                return {}

        service = oidc.OidcService(self.settings, http=Empty())
        with self.assertRaises(oidc.OidcError):
            await service.exchange("google", "c", "https://campo.test/cb", "v" * 43)


class ConfigTests(unittest.TestCase):
    def test_a_provider_with_only_some_settings_is_an_error(self) -> None:
        base = {"ATALAIA_DATABASE_URL": DB, "ATALAIA_SECRET_KEY": "s" * 43}
        with self.assertRaisesRegex(ConfigError, "ATALAIA_OIDC_GOOGLE_CLIENT_SECRET"):
            Settings.from_env({**base, "ATALAIA_OIDC_GOOGLE_CLIENT_ID": "x"})
        with self.assertRaisesRegex(ConfigError, "KEY_ID.*KEY_FILE|KEY_FILE.*"):
            Settings.from_env({**base, "ATALAIA_OIDC_APPLE_CLIENT_ID": "x", "ATALAIA_OIDC_APPLE_TEAM_ID": "t"})
        with self.assertRaisesRegex(ConfigError, "KEY_FILE is not a file"):
            Settings.from_env({**base, "ATALAIA_OIDC_APPLE_CLIENT_ID": "x", "ATALAIA_OIDC_APPLE_TEAM_ID": "t",
                               "ATALAIA_OIDC_APPLE_KEY_ID": "k", "ATALAIA_OIDC_APPLE_KEY_FILE": "/nonexistent"})
        with self.assertRaisesRegex(ConfigError, "TENANT"):
            Settings.from_env({**base, "ATALAIA_OIDC_MICROSOFT_CLIENT_ID": "x",
                               "ATALAIA_OIDC_MICROSOFT_CLIENT_SECRET": "y", "ATALAIA_OIDC_MICROSOFT_TENANT": "a b"})

    def test_providers_are_off_unless_configured(self) -> None:
        base = {"ATALAIA_DATABASE_URL": DB, "ATALAIA_SECRET_KEY": "s" * 43}
        self.assertEqual(Settings.from_env(base).oidc, ())
        self.assertTrue(Settings.from_env(base).password_login)
        s = Settings.from_env({**base, "ATALAIA_OIDC_GOOGLE_CLIENT_ID": "g", "ATALAIA_OIDC_GOOGLE_CLIENT_SECRET": "g-secret-xyz",
                               "ATALAIA_OIDC_MICROSOFT_CLIENT_ID": "m", "ATALAIA_OIDC_MICROSOFT_CLIENT_SECRET": "m-secret-xyz",
                               "ATALAIA_PASSWORD_LOGIN": "off"})
        self.assertEqual([c.provider for c in s.oidc], ["google", "microsoft"])
        self.assertEqual(s.oidc_client("microsoft").tenant, "common")
        self.assertFalse(s.password_login)
        self.assertNotIn("-secret-xyz", repr(s))  # no secret in a log line
        with self.assertRaisesRegex(ConfigError, "must be on or off"):
            Settings.from_env({**base, "ATALAIA_PASSWORD_LOGIN": "maybe"})

    def test_an_unreadable_apple_key_stops_the_server_starting(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "k.p8"
            path.write_text("not a key")
            settings = Settings(allow_signup_without_notice=True, database_url=DB, secret_key="s" * 43, oidc=(
                OidcClient("apple", "a", team_id="t", key_id="k", key_file=str(path)),))
            with self.assertRaisesRegex(ConfigError, "PEM private key"):
                oidc.OidcService(settings)

