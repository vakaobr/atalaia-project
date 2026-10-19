# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Access tokens, the TOTP login step, refresh tokens and key derivation (no database)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import unittest
import uuid
import warnings

import jwt

from atalaia_server import tokens
from atalaia_server.tokens import Keys, TokenError, UsedTokens

KEY = "s" * 43


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class KeyTests(unittest.TestCase):
    def test_each_purpose_has_its_own_key(self) -> None:
        k = Keys(KEY)
        raw_seed = base64.urlsafe_b64decode(k.totp_seed)
        self.assertEqual({len(k.access), len(k.totp_step), len(raw_seed)}, {32})
        self.assertEqual(len({k.access, k.totp_step, raw_seed}), 3)
        self.assertNotIn(KEY.encode(), (k.access, k.totp_step, raw_seed))
        self.assertEqual(Keys(KEY).access, k.access)          # deterministic
        self.assertNotEqual(Keys("t" * 43).access, k.access)  # and tied to the secret
        self.assertNotIn("s" * 10, repr(k))


class AccessTokenTests(unittest.TestCase):
    keys = Keys(KEY)
    user, sid = uuid.uuid4(), uuid.uuid4()

    def test_round_trip(self) -> None:
        token, exp = tokens.make_access_token(self.keys, self.user, self.sid, "rita", {"f": ["gm"]})
        claims = tokens.read_access_token(self.keys, token)
        self.assertEqual((claims.user_id, claims.session_id), (self.user, self.sid))
        self.assertEqual(claims.expires_at, exp)
        self.assertAlmostEqual(exp - time.time(), tokens.ACCESS_TTL_S, delta=5)
        body = jwt.decode(token, options={"verify_signature": False})
        self.assertEqual((body["typ"], body["iss"], body["username"], body["roles"]),
                         ("access", "atalaia-server", "rita", {"f": ["gm"]}))
        self.assertEqual(jwt.get_unverified_header(token)["alg"], "HS256")

    def test_unique_ids(self) -> None:
        a, _ = tokens.make_access_token(self.keys, self.user, self.sid, "rita", {})
        b, _ = tokens.make_access_token(self.keys, self.user, self.sid, "rita", {})
        self.assertNotEqual(jwt.decode(a, options={"verify_signature": False})["jti"],
                            jwt.decode(b, options={"verify_signature": False})["jti"])

    def test_expired(self) -> None:
        token, _ = tokens.make_access_token(self.keys, self.user, self.sid, "rita", {},
                                            now=time.time() - tokens.ACCESS_TTL_S - 60)
        with self.assertRaises(TokenError):
            tokens.read_access_token(self.keys, token)

    def test_another_key(self) -> None:
        token, _ = tokens.make_access_token(Keys("x" * 43), self.user, self.sid, "rita", {})
        with self.assertRaises(TokenError):
            tokens.read_access_token(self.keys, token)

    def test_a_totp_step_token_is_not_an_access_token(self) -> None:
        step, _ = tokens.make_totp_step_token(self.keys, self.user)
        with self.assertRaises(TokenError):
            tokens.read_access_token(self.keys, step)
        # Not even signed with the access key and claiming typ "access".
        forged = jwt.encode({"iss": tokens.ISSUER, "iat": int(time.time()), "exp": int(time.time()) + 60,
                             "jti": "x", "sub": str(self.user), "sid": str(self.sid), "typ": "access"},
                            self.keys.totp_step, algorithm="HS256")
        with self.assertRaises(TokenError):
            tokens.read_access_token(self.keys, forged)

    def test_algorithm_none_and_tampering_are_refused(self) -> None:
        token, _ = tokens.make_access_token(self.keys, self.user, self.sid, "rita", {})
        header, payload, sig = token.split(".")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        none = f"{b64url(json.dumps({'alg': 'none', 'typ': 'JWT'}).encode())}.{payload}."
        claims["sub"] = str(uuid.uuid4())
        swapped = f"{header}.{b64url(json.dumps(claims).encode())}.{sig}"
        with warnings.catch_warnings():  # the right key, the wrong algorithm: PyJWT warns about its length
            warnings.simplefilter("ignore", jwt.warnings.InsecureKeyLengthWarning)
            hs512 = jwt.encode(jwt.decode(token, options={"verify_signature": False}), self.keys.access,
                               algorithm="HS512")
        for bad in (none, swapped, hs512, token + "x", "", "not.a.jwt"):
            with self.subTest(bad=bad[:30]), self.assertRaises(TokenError):
                tokens.read_access_token(self.keys, bad)

    def test_missing_claims(self) -> None:
        for drop in ("exp", "iat", "jti", "sub", "typ", "iss", "sid"):
            claims = {"iss": tokens.ISSUER, "iat": int(time.time()), "exp": int(time.time()) + 60, "jti": "j",
                      "sub": str(self.user), "sid": str(self.sid), "typ": "access"}
            del claims[drop]
            token = jwt.encode(claims, self.keys.access, algorithm="HS256")
            with self.subTest(drop=drop), self.assertRaises(TokenError):
                tokens.read_access_token(self.keys, token)


class TotpStepTokenTests(unittest.TestCase):
    keys = Keys(KEY)

    def test_round_trip_and_lifetime(self) -> None:
        user = uuid.uuid4()
        token, jti = tokens.make_totp_step_token(self.keys, user)
        got_user, got_jti, exp = tokens.read_totp_step_token(self.keys, token)
        self.assertEqual((got_user, got_jti), (user, jti))
        self.assertAlmostEqual(exp - time.time(), tokens.TOTP_STEP_TTL_S, delta=5)
        old, _ = tokens.make_totp_step_token(self.keys, user, now=time.time() - tokens.TOTP_STEP_TTL_S - 60)
        with self.assertRaises(TokenError):
            tokens.read_totp_step_token(self.keys, old)

    def test_an_access_token_is_not_a_totp_step(self) -> None:
        token, _ = tokens.make_access_token(self.keys, uuid.uuid4(), uuid.uuid4(), "rita", {})
        with self.assertRaises(TokenError):
            tokens.read_totp_step_token(self.keys, token)

    def test_single_use(self) -> None:
        now = [1000.0]
        used = UsedTokens(clock=lambda: now[0])
        self.assertFalse(used.spent("a"))
        self.assertTrue(used.spend("a", 1300))
        self.assertTrue(used.spent("a"))
        self.assertFalse(used.spend("a", 1300))
        now[0] = 2000.0  # long expired: forgotten, the token itself is refused by then anyway
        used.spend("b", 2300)
        self.assertFalse(used.spent("a"))


class RefreshTokenTests(unittest.TestCase):
    def test_random_and_stored_as_sha256(self) -> None:
        a, b = tokens.new_refresh_token(), tokens.new_refresh_token()
        self.assertNotEqual(a, b)
        self.assertEqual(len(base64.urlsafe_b64decode(a + "=")), 32)
        self.assertEqual(tokens.refresh_token_hash(a), hashlib.sha256(a.encode()).hexdigest())
        self.assertEqual(len(tokens.refresh_token_hash(a)), 64)


if __name__ == "__main__":
    unittest.main()
