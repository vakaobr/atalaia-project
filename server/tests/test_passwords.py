# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Argon2id parameters, verification and the password policy (no database)."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import unittest

from argon2 import PasswordHasher, Type

from atalaia_server import passwords

# SHA-256 of SecLists' Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt at commit
# 1a7bb9127eca9e6ff2fc0301c597fe6e16a0cb56, the file shipped unmodified (server/README.md).
BREACHED_SHA256 = "3e8b6a7ca06679888e4bfaca865acd049bdd16231d0a0448396d6a45b89704be"  # tools/breached_hashes.py's output from the pinned list


class HashTests(unittest.TestCase):
    def test_argon2id_with_adr_p4_2_parameters(self) -> None:
        h = passwords.hash_password_sync("correct horse battery staple")
        self.assertTrue(h.startswith("$argon2id$v=19$m=65536,t=3,p=4$"), h)
        _, _, _, _, salt, tag = h.split("$")  # unpadded base64 (the PHC string format)
        self.assertEqual(len(base64.b64decode(salt + "=" * (-len(salt) % 4))), 16)
        self.assertEqual(len(base64.b64decode(tag + "=" * (-len(tag) % 4))), 32)
        self.assertFalse(passwords.needs_rehash(h))

    def test_verify(self) -> None:
        h = passwords.hash_password_sync("correct horse battery staple")
        self.assertTrue(passwords.verify_password_sync(h, "correct horse battery staple"))
        self.assertFalse(passwords.verify_password_sync(h, "correct horse battery stapl"))
        self.assertFalse(passwords.verify_password_sync(h, "Correct horse battery staple"))
        # Each hash has its own salt.
        self.assertNotEqual(h, passwords.hash_password_sync("correct horse battery staple"))

    def test_not_argon2_never_verifies(self) -> None:
        for stored in ("DELETED", "GUEST", "", "$argon2id$v=19$broken"):
            with self.subTest(stored=stored):
                self.assertFalse(passwords.verify_password_sync(stored, "anything at all"))
                self.assertTrue(passwords.needs_rehash(stored))

    def test_weaker_hashes_still_verify_and_need_a_rehash(self) -> None:
        old = PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID).hash("old password 12")
        self.assertTrue(passwords.verify_password_sync(old, "old password 12"))
        self.assertTrue(passwords.needs_rehash(old))

    def test_unicode_is_normalised(self) -> None:
        # The same password in composed and decomposed form (NFC "é" and "e" + U+0301) hashes alike.
        h = passwords.hash_password_sync("café com leite e pão")
        self.assertTrue(passwords.verify_password_sync(h, "café com leite e pão"))

    def test_async_helpers(self) -> None:
        async def run() -> None:
            h = await passwords.hash_password("correct horse battery staple")
            self.assertTrue(await passwords.verify_password(h, "correct horse battery staple"))
            self.assertFalse(await passwords.verify_password(h, "wrong horse battery staple"))
            # No such user: a dummy hash is checked, and the answer is no.
            self.assertFalse(await passwords.verify_password(None, "correct horse battery staple"))
            results = await asyncio.gather(*(passwords.verify_password(h, "correct horse battery staple")
                                             for _ in range(5)))
            self.assertEqual(results, [True] * 5)
        asyncio.run(run())


class PolicyTests(unittest.TestCase):
    def test_good_passwords(self) -> None:
        for pw in ("correct horse battery staple", "dez letras!", "x" * 1024, "Tejo-2026 ao fim do dia"):
            with self.subTest(pw=pw[:20]):
                self.assertIsNone(passwords.policy_problem(pw, "rita"))

    def test_length(self) -> None:
        self.assertEqual(passwords.policy_problem("nine char"), "password_too_short")
        self.assertIsNone(passwords.policy_problem("ten chars!"))
        self.assertEqual(passwords.policy_problem("x" * 1025), "password_too_long")
        # Length counts characters after NFKC, not bytes: ten accented letters pass.
        self.assertIsNone(passwords.policy_problem("çççççççççç"))

    def test_no_character_classes_required(self) -> None:
        self.assertIsNone(passwords.policy_problem("all lower case words here"))

    def test_not_the_username(self) -> None:
        self.assertEqual(passwords.policy_problem("Marshal.Rita.Tejo", "marshal.rita.tejo"), "password_is_username")

    def test_breached_passwords_are_refused_whatever_the_case(self) -> None:
        for pw in ("1234567890", "qwertyuiop", "basketball", "Password12", "PASSWORD12", "1q2w3e4r5t"):
            with self.subTest(pw=pw):
                self.assertEqual(passwords.policy_problem(pw), "password_breached")

    def test_the_breached_list_is_the_generated_file(self) -> None:
        data = passwords.BREACHED_LIST.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(), BREACHED_SHA256)
        loaded = passwords.breached_passwords()
        self.assertEqual(len(loaded), 9126)  # the list's entries of 10 characters or more
        self.assertTrue(all(len(h) == 32 and int(h, 16) >= 0 for h in loaded))
        # Hashes only: no entry of the list is there in clear (decision S11-4).
        self.assertNotIn(b"basketball", data.lower())
        self.assertNotIn(b"password12", data.lower())

    def test_a_long_unlisted_password_passes(self) -> None:
        self.assertIsNone(passwords.policy_problem("correct horse battery staple"))
        self.assertNotIn(passwords.breached_hash("correct horse battery staple"), passwords.breached_passwords())


if __name__ == "__main__":
    unittest.main()
