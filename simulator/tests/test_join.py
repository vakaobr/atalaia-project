# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The join payload codec against protocol/vectors/join.json (also checked by core/tests/test_join.c).

Every vector is checked; none is skipped. The tags are also checked with
Python's own hmac module, and HMAC-SHA256 against RFC 4231.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from pathlib import Path

from atalaia_sim import join

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "join.json")
                     .read_text(encoding="utf-8"))
KEY = bytes.fromhex(VECTORS["join_key"])
WRONG = bytes.fromhex(VECTORS["wrong_key"])


def fields(v: dict) -> dict:
    out = dict(v["fields"])
    out["game_key"] = bytes.fromhex(out["game_key"])
    return out


class ValidVectorTests(unittest.TestCase):
    def test_vector_count(self) -> None:
        self.assertGreaterEqual(len(VECTORS["valid"]), 4)
        self.assertGreaterEqual(len(VECTORS["invalid"]), 30)

    def test_decode_encode_round_trip(self) -> None:
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(join.decode(payload, KEY), fields(v))
                self.assertEqual(join.encode(fields(v), KEY), payload)

    def test_tag_is_hmac_sha256_over_version_and_body(self) -> None:
        for v in VECTORS["valid"]:
            payload = bytes.fromhex(v["payload"])
            self.assertEqual(payload[0], 1)
            self.assertEqual(payload[-32:], hmac.new(KEY, payload[:-32], hashlib.sha256).digest())

    def test_wrong_key_is_refused(self) -> None:
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]), self.assertRaises(join.JoinError) as cm:
                join.decode(bytes.fromhex(v["payload"]), WRONG)
            self.assertEqual(cm.exception.reason, "mac")

    def test_text_form(self) -> None:
        for v in VECTORS["valid"]:
            payload = bytes.fromhex(v["payload"])
            self.assertEqual(join.to_text(payload), v["text"])
            self.assertEqual(join.from_text(v["text"]), payload)
            self.assertEqual(join.from_text(f"  {v['text']}\n"), payload)

    def test_ndef_tag(self) -> None:
        for v in VECTORS["valid"]:
            payload = bytes.fromhex(v["payload"])
            tag = bytes.fromhex(v["ndef_tag"])
            self.assertEqual(join.to_ndef_tag(payload), tag)
            self.assertEqual(join.from_ndef_tag(tag), payload)
            # NULL and lock control TLVs before the message are skipped.
            self.assertEqual(join.from_ndef_tag(b"\x00\x01\x03\xa0\x10\x44" + tag), payload)
            self.assertIsNone(join.from_ndef_tag(tag[:len(tag) // 2]))

    def test_long_record_vector_exists(self) -> None:
        # One vector is long enough for a long NDEF record and a 3-byte TLV length.
        self.assertTrue(any(len(bytes.fromhex(v["payload"])) >= 256 for v in VECTORS["valid"]))

    def test_optional_key_is_skipped(self) -> None:
        got = join.decode(bytes.fromhex(VECTORS["optional_key_skipped"]), KEY)
        self.assertEqual(got, fields(VECTORS["valid"][0]))


class InvalidVectorTests(unittest.TestCase):
    def test_every_invalid_vector_fails_with_its_reason(self) -> None:
        for v in VECTORS["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(join.JoinError) as cm:
                join.decode(bytes.fromhex(v["payload"]), KEY)
            self.assertEqual(cm.exception.reason, v["reason"], f"{v['name']}: {cm.exception}")

    def test_body_vectors_carry_a_correct_tag(self) -> None:
        # So they test the body checks, not the tag.
        for v in VECTORS["invalid"]:
            if v["reason"] == "body":
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(payload[-32:], hmac.new(KEY, payload[:-32], hashlib.sha256).digest(),
                                 v["name"])


class EncoderTests(unittest.TestCase):
    def base(self) -> dict:
        return fields(VECTORS["valid"][0])

    def test_encoder_refuses_out_of_range_fields(self) -> None:
        for change in ({"max_hops": 4}, {"channel_hz": 915_000_000}, {"teams": []},
                       {"teams": ["a", "a"]}, {"node_id": 0}, {"kind": "box"},
                       {"params": {"x": "y" * 200}}, {"game_key": b"short"}):
            with self.subTest(change), self.assertRaises(join.JoinError):
                join.encode({**self.base(), **change}, KEY)

    def test_payload_over_448_bytes_is_refused(self) -> None:
        j = {**self.base(), "teams": [f"{i}" * 23 for i in range(8)], "mode_id": "m" * 63,
             "role": "r" * 31, "params": {"k": "v" * 180}}
        with self.assertRaises(join.JoinError) as cm:
            join.encode(j, KEY)
        self.assertEqual(cm.exception.reason, "length")

    def test_bad_text(self) -> None:
        for text in ("atalaia:join:AQ+D", "atalaia:join:A", "atalaia:join:AQJ", "join:AQID"):
            with self.subTest(text), self.assertRaises(join.JoinError):
                join.from_text(text)


class HmacTests(unittest.TestCase):
    def test_rfc4231(self) -> None:
        for v in VECTORS["hmac_sha256"]:
            mac = hmac.new(bytes.fromhex(v["key"]), bytes.fromhex(v["data"]), hashlib.sha256).hexdigest()
            self.assertEqual(mac, v["mac"], v["name"])


if __name__ == "__main__":
    unittest.main()
