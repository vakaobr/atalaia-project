# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Field frames (atalaia_sim.field_frame) against protocol/vectors/field_frame.json.

The C codec (core/src/field_frame.c) checks the same file in core/tests/test_field_frame.c.
The frames need the cryptography library; with ATALAIA_REQUIRE_ALL=1 it must be there.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from atalaia_sim import field_frame as ff

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "field_frame.json")
                     .read_text(encoding="utf-8"))


def _has_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        return True
    except ImportError:
        return False


if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and not _has_crypto():
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but cryptography is not available")


def fields(v: dict) -> dict:
    out = dict(v["fields"])
    for k in ("device_id", "token", "chunk", "key_tag"):
        if k in out:
            out[k] = bytes.fromhex(out[k])
    return out


class HkdfTests(unittest.TestCase):
    def test_rfc5869_appendix_a(self):
        self.assertEqual(len(VECTORS["hkdf_sha256"]), 3)
        for v in VECTORS["hkdf_sha256"]:
            with self.subTest(v["name"]):
                okm = ff.hkdf_sha256(bytes.fromhex(v["ikm"]), v["length"], bytes.fromhex(v["salt"]),
                                     bytes.fromhex(v["info"]))
                self.assertEqual(okm.hex(), v["okm"])

    def test_field_key(self):
        self.assertEqual(ff.field_key(bytes.fromhex(VECTORS["join_key"])).hex(), VECTORS["field_key"])
        with self.assertRaises(ValueError):
            ff.field_key(bytes(16))


class BodyTests(unittest.TestCase):
    def test_valid_bodies(self):
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                self.assertEqual(ff.body_decode(bytes.fromhex(v["body"])), fields(v))
                self.assertEqual(ff.body_encode(fields(v)).hex(), v["body"])

    def test_invalid_bodies(self):
        self.assertGreaterEqual(len(VECTORS["invalid_bodies"]), 25)
        for v in VECTORS["invalid_bodies"]:
            with self.subTest(v["name"]):
                with self.assertRaises(ff.FieldFrameError):
                    ff.body_decode(bytes.fromhex(v["body"]))

    def test_optional_key_skipped(self):
        msg = ff.body_decode(bytes.fromhex(VECTORS["optional_key_skipped"]))
        self.assertEqual(msg["name"], "box")
        self.assertNotIn("20", msg)

    def test_encoder_refuses(self):
        good = fields(VECTORS["valid"][1])
        for change in ({"tier": 3}, {"name": ""}, {"name": "x" * 25}, {"last_game": 0}, {"battery_pct": 101},
                       {"answer": 4}, {"device_id": bytes(7)}, {"kind": "hello"}):
            with self.subTest(change):
                with self.assertRaises(ff.FieldFrameError):
                    ff.body_encode({**good, **change})
        over = fields(VECTORS["valid"][7])
        self.assertEqual(over["kind"], "game_over")
        for change in ({"game_id": 0}, {"game_id": 65535}, {"key_tag": bytes(7)}):
            with self.subTest(change):
                with self.assertRaises(ff.FieldFrameError):
                    ff.body_encode({**over, **change})

    def test_key_tag_is_the_epoch_stores(self):
        """GAME_OVER names its game by the key's tag, the one the boxes' epoch store keeps (BN-7)."""
        tags = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "epoch_tag.json")
                          .read_text())["valid"]
        for v in tags:
            self.assertEqual(ff.key_tag(bytes.fromhex(v["game_key"])).hex(), v["tag"])


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class FrameTests(unittest.TestCase):
    key = bytes.fromhex(VECTORS["field_key"])

    def test_valid_frames(self):
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                frame = ff.seal(self.key, bytes.fromhex(v["body"]), bytes.fromhex(v["nonce"]))
                self.assertEqual(frame.hex(), v["frame"])
                self.assertEqual(ff.decode(self.key, frame), fields(v))
        self.assertEqual(max(len(v["frame"]) // 2 for v in VECTORS["valid"]), ff.FRAME_MAX)

    def test_hop_limit_is_not_authenticated(self):
        body = ff.open_frame(self.key, bytes.fromhex(VECTORS["hop_limit_ignored"]))
        self.assertEqual(body.hex(), VECTORS["valid"][1]["body"])

    def test_invalid_frames(self):
        for v in VECTORS["invalid_frames"]:
            with self.subTest(v["name"]):
                frame = bytes.fromhex(v["frame"])
                self.assertEqual(ff.is_frame(frame), v["reason"] == "mac")
                with self.assertRaises(ff.FieldFrameError):
                    ff.open_frame(self.key, frame)

    def test_frames_from_a_nonce_source(self):
        body = bytes.fromhex(VECTORS["valid"][4]["body"])
        src = ff.NonceSource(bytes.fromhex(VECTORS["join_key"]), bytes(8))
        a, b = ff.seal(self.key, body, src.next()), ff.seal(self.key, body, src.next())
        self.assertNotEqual(a, b)
        self.assertEqual(ff.open_frame(self.key, a), ff.open_frame(self.key, b))


class NonceTests(unittest.TestCase):
    """The nonce rule (decision RJ-15): a sender's pseudonym, boot count and frame count."""

    def test_vectors(self):
        nv = VECTORS["nonces"]
        nk = ff.nonce_key(bytes.fromhex(VECTORS["join_key"]))
        self.assertEqual(nk.hex(), nv["nonce_key"])
        for c in nv["cases"]:
            with self.subTest(c["name"]):
                self.assertEqual(ff.nonce(nk, bytes.fromhex(c["sender"]), c["boot"], c["ctr"]).hex(), c["nonce"])

    def test_source_sequence(self):
        src_v = VECTORS["nonces"]["source"]
        stored = {"boot": src_v["stored_boot"]}
        src = ff.NonceSource(bytes.fromhex(VECTORS["join_key"]), bytes.fromhex(src_v["sender"]),
                             lambda: stored["boot"], lambda b: stored.update(boot=b) or True)
        got = [src.next().hex(), src.next().hex()]
        src.ctr = ff.CTR_MAX
        got += [src.next().hex(), src.next().hex()]
        self.assertEqual(got, src_v["nonces"])
        self.assertEqual(stored["boot"], src_v["stored_after"])

    def test_the_boot_count_is_stored_before_use(self):
        saved = []
        src = ff.NonceSource(bytes(32), bytes(8), lambda: 7, lambda b: saved.append(b) or True)
        n = src.next()
        self.assertEqual((saved, n[8:11]), ([8], (8).to_bytes(3, "big")))
        refusing = ff.NonceSource(bytes(32), bytes(8), lambda: 0, lambda b: False)
        with self.assertRaises(ff.NonceError):
            refusing.next()
        full = ff.NonceSource(bytes(32), bytes(8), lambda: ff.BOOT_MAX, lambda b: True)
        with self.assertRaises(ff.NonceError):
            full.next()

    def test_no_repeat_across_runs_and_senders(self):
        seen = set()
        stored = {"a": 0, "b": 0}
        for run in range(3):
            for who in ("a", "b"):
                src = ff.NonceSource(bytes(32), who.encode() * 8, lambda w=who: stored[w],
                                     lambda b, w=who: stored.update({w: b}) or True)
                for _ in range(50):
                    n = src.next()
                    self.assertNotIn(n, seen)
                    seen.add(n)


class PartTests(unittest.TestCase):
    def test_split_vectors(self):
        for v in VECTORS["split"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual([c.hex() for c in ff.split(payload)], v["parts"])
                r = ff.Reassembly()
                parts = [bytes.fromhex(p) for p in v["parts"]]
                got = None
                for i in reversed(range(len(parts))):
                    got = r.add({"invite_id": 5, "token": bytes(8), "parts": len(parts), "part": i, "chunk": parts[i]})
                self.assertEqual(got, payload)

    def test_limits(self):
        self.assertEqual(len(ff.split(bytes(448))), 3)
        with self.assertRaises(ff.FieldFrameError):
            ff.split(bytes(449))
        with self.assertRaises(ff.FieldFrameError):
            ff.split(b"")

    def test_another_invite_starts_over(self):
        r = ff.Reassembly()
        self.assertIsNone(r.add({"invite_id": 1, "token": bytes(8), "parts": 2, "part": 0, "chunk": b"\x01"}))
        self.assertIsNone(r.add({"invite_id": 2, "token": bytes(8), "parts": 2, "part": 1, "chunk": b"\x02"}))
        self.assertIsNone(r.add({"invite_id": 1, "token": bytes(8), "parts": 2, "part": 1, "chunk": b"\x02"}))
        self.assertEqual(r.add({"invite_id": 1, "token": bytes(8), "parts": 2, "part": 0, "chunk": b"\x01"}),
                         b"\x01\x02")


if __name__ == "__main__":
    unittest.main()
