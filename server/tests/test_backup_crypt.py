# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The backups' encryption (plan phase 22, decision S22-3), with no database: also run by tools/check.sh.

AES-256-GCM itself is checked with Test Cases 13 and 14 of McGrew and Viega,
"The Galois/Counter Mode of Operation (GCM)" (the NIST submission, 2005,
appendix B); then the STREAM framing: round trips at the chunk boundaries and
every way a backup can be damaged. The whole backup and restore, on
PostgreSQL behind Caddy: ``python3 tools/docker_server.py deploy``.
"""

from __future__ import annotations

import io
import os
import struct
import subprocess
import sys
import unittest
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from atalaia_server import backup_crypt as bc

SERVER = Path(__file__).resolve().parents[1]
KEY = bytes(range(32))
OTHER = bytes(range(1, 33))


def sealed(data: bytes, key: bytes = KEY, prefix: bytes = b"\x07" * 7) -> bytes:
    out = io.BytesIO()
    bc.seal(key, io.BytesIO(data), out, prefix=prefix)
    return out.getvalue()


def opened(blob: bytes, key: bytes = KEY) -> bytes:
    out = io.BytesIO()
    bc.open_(key, io.BytesIO(blob), out)
    return out.getvalue()


def records(blob: bytes) -> list[bytes]:
    """The length-prefixed records after the header, each with its length."""
    out, at = [], bc.HEADER
    while at < len(blob):
        (size,) = struct.unpack(">I", blob[at:at + 4])
        out.append(blob[at:at + 4 + size])
        at += 4 + size
    return out


class GcmVectorTests(unittest.TestCase):
    def test_mcgrew_viega_cases_13_and_14(self) -> None:
        aead = AESGCM(bytes(32))
        self.assertEqual(aead.encrypt(bytes(12), b"", None).hex(), "530f8afbc74536b9a963b4f1c4cb738b")
        self.assertEqual(aead.encrypt(bytes(12), bytes(16), None).hex(),
                         "cea7403d4d606b6e074ec5d3baf39d18" "d0d1c8a799996bf0265b98b5d48ab919")


class StreamTests(unittest.TestCase):
    def test_round_trips_at_the_chunk_boundaries(self) -> None:
        for size in (0, 1, bc.CHUNK - 1, bc.CHUNK, bc.CHUNK + 1, 3 * bc.CHUNK, 3 * bc.CHUNK + 5):
            with self.subTest(size=size):
                data = os.urandom(size)
                blob = sealed(data)
                self.assertEqual(opened(blob), data)
                chunks = max(1, -(-size // bc.CHUNK))
                self.assertEqual(len(records(blob)), chunks)
                self.assertEqual(len(blob), bc.HEADER + size + chunks * (4 + bc.TAG))

    def test_the_layout(self) -> None:
        blob = sealed(b"PGDMP", prefix=b"\x01\x02\x03\x04\x05\x06\x07")
        self.assertEqual(blob[:8], b"ATLBAK\x00\x01")
        self.assertEqual(blob[8:15], bytes(range(1, 8)))
        nonce = bytes(range(1, 8)) + b"\x00\x00\x00\x00\x01"  # chunk 0, the last
        self.assertEqual(blob[15:], struct.pack(">I", 21) + AESGCM(KEY).encrypt(nonce, b"PGDMP", blob[:15]))
        self.assertNotIn(b"PGDMP", blob)

    def test_a_new_prefix_each_time(self) -> None:
        out1, out2 = io.BytesIO(), io.BytesIO()
        bc.seal(KEY, io.BytesIO(b"same"), out1)
        bc.seal(KEY, io.BytesIO(b"same"), out2)
        self.assertNotEqual(out1.getvalue()[8:15], out2.getvalue()[8:15])
        self.assertNotEqual(out1.getvalue(), out2.getvalue())

    def assert_refused(self, blob: bytes, key: bytes = KEY) -> None:
        with self.assertRaises(bc.BackupError):
            opened(blob, key)

    def test_damage_is_refused(self) -> None:
        data = os.urandom(3 * bc.CHUNK + 100)
        blob = sealed(data)
        recs = records(blob)
        head = blob[:bc.HEADER]
        self.assert_refused(blob, OTHER)                                       # another key
        self.assert_refused(head + b"".join(recs[:3]))                         # the last chunk dropped
        self.assert_refused(head + b"".join(recs[:1]))
        self.assert_refused(blob[:-1])                                         # cut inside a record
        self.assert_refused(blob[:bc.HEADER + 2])
        self.assert_refused(head)                                              # no record at all
        self.assert_refused(head + recs[1] + recs[0] + recs[2] + recs[3])      # reordered
        self.assert_refused(head + recs[0] + recs[0] + recs[2] + recs[3])      # repeated
        self.assert_refused(blob + recs[3])                                    # a record added
        for at in (0, 9, bc.HEADER + 2, bc.HEADER + 10, len(blob) // 2, len(blob) - 1):
            with self.subTest(flipped=at):
                bad = bytearray(blob)
                bad[at] ^= 0x01
                self.assert_refused(bytes(bad))

    def test_splicing_two_backups_is_refused(self) -> None:
        a, b = sealed(os.urandom(2 * bc.CHUNK + 1), prefix=b"A" * 7), sealed(os.urandom(2 * bc.CHUNK + 1),
                                                                             prefix=b"B" * 7)
        ra, rb = records(a), records(b)
        self.assert_refused(a[:bc.HEADER] + ra[0] + rb[1] + ra[2])
        self.assert_refused(b[:bc.HEADER] + ra[0] + ra[1] + ra[2])

    def test_a_bad_length_is_refused(self) -> None:
        blob = sealed(b"x")
        self.assert_refused(blob[:bc.HEADER] + struct.pack(">I", bc.MAX_RECORD + 1) + blob[bc.HEADER + 4:])
        self.assert_refused(blob[:bc.HEADER] + struct.pack(">I", 3) + b"abc")

    def test_not_a_backup(self) -> None:
        self.assert_refused(b"PGDMP\x01\x0e\x00" + bytes(64))
        self.assert_refused(b"")


class KeyTests(unittest.TestCase):
    def test_the_key_setting(self) -> None:
        self.assertEqual(bc.key_from_env({"ATALAIA_BACKUP_KEY": KEY.hex()}), KEY)
        self.assertEqual(bc.key_from_env({"ATALAIA_BACKUP_KEY": f" {KEY.hex().upper()}\n"}), KEY)
        for bad in ("", "  ", "ab" * 31, "ab" * 33, "zz" * 32, "0x" + "ab" * 31):
            with self.subTest(bad=bad), self.assertRaises(bc.BackupError):
                bc.key_from_env({"ATALAIA_BACKUP_KEY": bad})
        with self.assertRaises(bc.BackupError):
            bc.key_from_env({})


class CommandTests(unittest.TestCase):
    def run_tool(self, what: str, data: bytes, key: str = KEY.hex()) -> subprocess.CompletedProcess:
        env = {**os.environ, "ATALAIA_BACKUP_KEY": key, "PYTHONPATH": str(SERVER)}
        return subprocess.run([sys.executable, "-m", "atalaia_server.backup_crypt", what], input=data,
                              capture_output=True, env=env, cwd=SERVER, timeout=60)

    def test_seal_then_open(self) -> None:
        data = os.urandom(bc.CHUNK * 2 + 7)
        done = self.run_tool("seal", data)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(done.stderr, b"")
        back = self.run_tool("open", done.stdout)
        self.assertEqual(back.returncode, 0, back.stderr)
        self.assertEqual(back.stdout, data)
        bad = self.run_tool("open", done.stdout[:-5])
        self.assertEqual(bad.returncode, 1)
        self.assertIn(b"cut short", bad.stderr)
        self.assertNotIn(KEY.hex().encode(), bad.stderr)

    def test_usage_and_a_missing_key(self) -> None:
        self.assertEqual(self.run_tool("lock", b"").returncode, 2)
        done = self.run_tool("seal", b"x", key="")
        self.assertEqual(done.returncode, 1)
        self.assertIn(b"ATALAIA_BACKUP_KEY is not set", done.stderr)
        self.assertEqual(done.stdout, b"")


if __name__ == "__main__":
    unittest.main()
