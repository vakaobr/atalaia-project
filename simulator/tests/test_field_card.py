# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The NFC field card codec against protocol/vectors/field_card.json (also checked by
firmware/esp32/test/test_adoption.c). Every vector is checked; none is skipped."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from atalaia_sim import field_card, join

ROOT = Path(__file__).resolve().parents[2] / "protocol" / "vectors"
VECTORS = json.loads((ROOT / "field_card.json").read_text(encoding="utf-8"))
JOIN = json.loads((ROOT / "join.json").read_text(encoding="utf-8"))


class FieldCardVectorTests(unittest.TestCase):
    def test_counts(self) -> None:
        self.assertGreaterEqual(len(VECTORS["valid"]), 4)
        self.assertGreaterEqual(len(VECTORS["invalid"]), 18)
        self.assertEqual(VECTORS["ndef_type"].encode(), field_card.NDEF_TYPE)

    def test_valid(self) -> None:
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                key = bytes.fromhex(v["join_key"])
                payload = bytes.fromhex(v["payload"])
                card = field_card.decode(payload)
                self.assertEqual(card["join_key"], key)
                self.assertEqual(card["name"], v["field_name"])
                self.assertEqual(card["fingerprint"], v["fingerprint"])
                self.assertEqual(field_card.fingerprint(key), v["fingerprint"])
                self.assertEqual(field_card.encode(key, v["field_name"]), payload)
                tag = bytes.fromhex(v["ndef_tag"])
                self.assertEqual(field_card.to_ndef_tag(payload), tag)
                self.assertEqual(field_card.from_ndef_tag(tag), payload)
                # A join card reader finds no join payload on a field card.
                self.assertIsNone(join.from_ndef_tag(tag))

    def test_invalid(self) -> None:
        for v in VECTORS["invalid"]:
            with self.subTest(v["name"]):
                with self.assertRaises(field_card.FieldCardError) as cm:
                    field_card.decode(bytes.fromhex(v["payload"]))
                self.assertEqual(cm.exception.reason, v["reason"])

    def test_a_join_card_is_no_field_card(self) -> None:
        for v in JOIN["valid"]:
            with self.subTest(v["name"]):
                self.assertIsNone(field_card.from_ndef_tag(bytes.fromhex(v["ndef_tag"])))

    def test_encoder_refuses(self) -> None:
        with self.assertRaises(field_card.FieldCardError):
            field_card.encode(bytes(31), "x")
        with self.assertRaises(field_card.FieldCardError):
            field_card.encode(bytes(32), "A" * 49)
        with self.assertRaises(field_card.FieldCardError):
            field_card.encode(bytes(32), 'say "hi"')

    def test_clean_name(self) -> None:
        self.assertEqual(field_card.clean_name('  Clube "Ão"\n  '), "Clube Ão")
        long = field_card.clean_name("É" * 40)  # 80 bytes: cut to 24 characters (48 bytes)
        self.assertEqual(long, "É" * 24)
        self.assertTrue(field_card.name_ok(field_card.clean_name("a\\b" + "ç" * 30).encode()))


if __name__ == "__main__":
    unittest.main()
