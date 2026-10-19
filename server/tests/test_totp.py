# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""TOTP: the RFC's own test vectors, the window, single use, the encrypted seeds (no database)."""

from __future__ import annotations

import base64
import hashlib
import unittest
from urllib.parse import parse_qs, urlsplit

import pyotp
from cryptography.fernet import Fernet

from atalaia_server import totp

# RFC 6238 Appendix B, Table 1 (copied from https://www.rfc-editor.org/rfc/rfc6238.txt): time in
# seconds, the TOTP for each mode, 8 digits, X = 30, T0 = 0. The seeds are the ASCII strings of the
# RFC's reference code in Appendix A (seed, seed32 and seed64: "1234567890" repeated, 20, 32 and
# 64 bytes); Appendix B's text names only the 20-byte one, but the SHA-256 and SHA-512 rows are
# what the reference code prints with the longer ones.
SEEDS = {
    "SHA1": (b"12345678901234567890", hashlib.sha1),
    "SHA256": (b"12345678901234567890123456789012", hashlib.sha256),
    "SHA512": (b"1234567890123456789012345678901234567890123456789012345678901234", hashlib.sha512),
}
RFC6238_TABLE_1 = [
    (59, "94287082", "SHA1"), (59, "46119246", "SHA256"), (59, "90693936", "SHA512"),
    (1111111109, "07081804", "SHA1"), (1111111109, "68084774", "SHA256"), (1111111109, "25091201", "SHA512"),
    (1111111111, "14050471", "SHA1"), (1111111111, "67062674", "SHA256"), (1111111111, "99943326", "SHA512"),
    (1234567890, "89005924", "SHA1"), (1234567890, "91819424", "SHA256"), (1234567890, "93441116", "SHA512"),
    (2000000000, "69279037", "SHA1"), (2000000000, "90698825", "SHA256"), (2000000000, "38618901", "SHA512"),
    (20000000000, "65353130", "SHA1"), (20000000000, "77737706", "SHA256"), (20000000000, "47863826", "SHA512"),
]
# RFC 6238 Appendix B's "Value of T (hex)" column for the same times.
RFC6238_STEPS = {59: 0x1, 1111111109: 0x23523EC, 1111111111: 0x23523ED, 1234567890: 0x273EF07,
                 2000000000: 0x3F940AA, 20000000000: 0x27BC86AA}
# RFC 4226 Appendix D (https://www.rfc-editor.org/rfc/rfc4226.txt): HOTP, 6 digits, the secret
# "12345678901234567890", counts 0-9. TOTP is HOTP over the time step (RFC 6238 section 4.2), and
# these are the 6-digit codes the server itself uses.
RFC4226_APPENDIX_D = ["755224", "287082", "359152", "969429", "338314",
                      "254676", "287922", "162583", "399871", "520489"]


def b32(seed: bytes) -> str:
    return base64.b32encode(seed).decode()


class RfcVectorTests(unittest.TestCase):
    def test_rfc_6238_appendix_b(self) -> None:
        for t, expected, mode in RFC6238_TABLE_1:
            seed, digest = SEEDS[mode]
            with self.subTest(time=t, mode=mode):
                self.assertEqual(totp.step_of(t), RFC6238_STEPS[t])
                self.assertEqual(totp.code_at(b32(seed), t, digits=8, digest=digest), expected)

    def test_rfc_4226_appendix_d_six_digits(self) -> None:
        secret = b32(SEEDS["SHA1"][0])
        hotp = pyotp.HOTP(secret, digits=6)
        for count, expected in enumerate(RFC4226_APPENDIX_D):
            with self.subTest(count=count):
                self.assertEqual(hotp.at(count), expected)
                # The same codes through the server's TOTP at the start of step `count`.
                self.assertEqual(totp.code_at(secret, count * totp.PERIOD_S), expected)

    def test_verify_takes_the_rfc_codes(self) -> None:
        secret = b32(SEEDS["SHA1"][0])
        # Step 1 (t = 30-59) is "287082" (RFC 4226 count 1).
        self.assertEqual(totp.verify(secret, "287082", 59, None), 1)


class VerifyTests(unittest.TestCase):
    secret = b32(SEEDS["SHA1"][0])
    t = 1111111111  # step 0x23523ED

    def code(self, step: int) -> str:
        return totp.code_at(self.secret, step * totp.PERIOD_S)

    def test_one_step_either_side(self) -> None:
        now = totp.step_of(self.t)
        for offset in (-1, 0, 1):
            with self.subTest(offset=offset):
                self.assertEqual(totp.verify(self.secret, self.code(now + offset), self.t, None), now + offset)
        for offset in (-3, -2, 2, 3):
            with self.subTest(offset=offset):
                self.assertIsNone(totp.verify(self.secret, self.code(now + offset), self.t, None))

    def test_a_code_works_once(self) -> None:
        now = totp.step_of(self.t)
        code = self.code(now)
        self.assertEqual(totp.verify(self.secret, code, self.t, None), now)
        self.assertIsNone(totp.verify(self.secret, code, self.t, now))           # the same step again
        self.assertIsNone(totp.verify(self.secret, self.code(now - 1), self.t, now))  # an older one
        self.assertEqual(totp.verify(self.secret, self.code(now + 1), self.t, now), now + 1)

    def test_malformed_codes(self) -> None:
        good = self.code(totp.step_of(self.t))
        for code in ("", "12345", "1234567", "abcdef", good[:5] + "x", " " * 6, "١٢٣٤٥٦"):
            with self.subTest(code=code):
                self.assertIsNone(totp.verify(self.secret, code, self.t, None))
        self.assertIsNotNone(totp.verify(self.secret, f" {good} ", self.t, None))  # spaces around are fine

    def test_another_secret_fails(self) -> None:
        self.assertIsNone(totp.verify(totp.new_secret(), self.code(totp.step_of(self.t)), self.t, None))


class SecretTests(unittest.TestCase):
    def test_new_secrets_have_160_bits(self) -> None:
        secrets_ = {totp.new_secret() for _ in range(50)}
        self.assertEqual(len(secrets_), 50)
        for s in secrets_:
            self.assertEqual(len(base64.b32decode(s)), 20)

    def test_provisioning_uri(self) -> None:
        secret = totp.new_secret()
        parts = urlsplit(totp.provisioning_uri(secret, "marshal.rita"))
        self.assertEqual((parts.scheme, parts.netloc), ("otpauth", "totp"))
        self.assertEqual(parts.path, "/Atalaia:marshal.rita")
        query = parse_qs(parts.query)
        self.assertEqual(query["secret"], [secret])
        self.assertEqual(query["issuer"], ["Atalaia"])

    def test_seeds_are_sealed(self) -> None:
        box = totp.SeedBox(Fernet.generate_key())
        secret = totp.new_secret()
        sealed = box.seal(secret)
        self.assertNotIn(secret.encode(), sealed)
        self.assertEqual(box.open(sealed), secret)
        self.assertEqual(box.open(memoryview(sealed)), secret)  # as the database driver may hand it back
        self.assertIsNone(totp.SeedBox(Fernet.generate_key()).open(sealed))  # another key: unreadable
        tampered = bytearray(sealed)
        tampered[-5] ^= 1
        self.assertIsNone(box.open(bytes(tampered)))


if __name__ == "__main__":
    unittest.main()
