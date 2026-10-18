# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The player tag codec against protocol/vectors/tag.json (also checked by core/tests/test_tag.c).

Every vector is checked; none is skipped. The C core's nfc.tag data (through
ctypes, as the simulator uses it) must equal the Python one for every vector
and for a sweep of generated tags.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import unittest
from pathlib import Path

from atalaia_sim import tag
from atalaia_sim.core import Core, find_library

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "tag.json")
                     .read_text(encoding="utf-8"))
KEY = bytes.fromhex(VECTORS["game_key"])
GAME = VECTORS["game_id"]
TEAMS = VECTORS["teams"]
UID = bytes.fromhex(VECTORS["uid"])


class VectorTests(unittest.TestCase):
    def test_vector_counts(self) -> None:
        self.assertGreaterEqual(len(VECTORS["valid"]), 3)
        self.assertGreaterEqual(len(VECTORS["invalid"]), 9)
        self.assertGreaterEqual(len(VECTORS["events"]), 5)

    def test_valid(self) -> None:
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(tag.decode(payload, GAME, KEY, len(TEAMS)), v["fields"])
                self.assertEqual(tag.encode(v["fields"], KEY), payload)
                # The layout, checked with Python's own hmac module.
                body = payload[:-16]
                self.assertEqual(payload[-16:], hmac.new(KEY, body, hashlib.sha256).digest()[:16])
                self.assertEqual(body[0], 1)
                self.assertEqual(body[1:-3].decode(), v["fields"]["player"])
                ndef = bytes.fromhex(v["ndef_tag"])
                self.assertEqual(tag.to_ndef_tag(payload), ndef)
                self.assertEqual(tag.from_ndef_tag(ndef), payload)
                with self.assertRaises(tag.TagError) as ctx:
                    tag.decode(payload, GAME, bytes(16), len(TEAMS))
                self.assertEqual(ctx.exception.reason, "mac")

    def test_invalid(self) -> None:
        for v in VECTORS["invalid"]:
            with self.subTest(v["name"]):
                with self.assertRaises(tag.TagError) as ctx:
                    tag.decode(bytes.fromhex(v["payload"]), GAME, KEY, len(TEAMS))
                self.assertEqual(ctx.exception.reason, v["reason"])

    def test_events(self) -> None:
        for v in VECTORS["events"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"]) if v["payload"] else None
                data = tag.event_data(UID, payload, GAME, KEY if v["game_key"] else None, TEAMS)
                self.assertEqual(json.dumps(data, separators=(",", ":")), v["json"])

    def test_encode_refuses_bad_fields(self) -> None:
        for bad in ({"player": "", "team": 1, "game_id": 1}, {"player": "a b", "team": 1, "game_id": 1},
                    {"player": "x" * 33, "team": 1, "game_id": 1},
                    {"player": "ok", "team": 256, "game_id": 1}):
            with self.subTest(bad):
                with self.assertRaises(ValueError):
                    tag.encode(bad, KEY)
        with self.assertRaises(ValueError):
            tag.encode({"player": "ok", "team": 1, "game_id": 1}, b"short")

    def test_join_cards_are_not_tags(self) -> None:
        from atalaia_sim import join
        mem = join.to_ndef_tag(b"\x01" + b"x" * 40)
        self.assertIsNone(tag.from_ndef_tag(mem))


class CoreAgreesTests(unittest.TestCase):
    """The C core (atalaia_tag_event_json) and the Python codec give the same nfc.tag data."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.core = Core(find_library())

    def test_vectors_through_the_core(self) -> None:
        for v in VECTORS["events"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"]) if v["payload"] else None
                got = self.core.tag_event_json(UID, payload, GAME, KEY if v["game_key"] else None,
                                               TEAMS)
                self.assertEqual(got, v["json"])

    def test_generated_tags(self) -> None:
        teams = ["red", "blue", "verde-água"]
        keys = [KEY, bytes(range(16))]
        for i in range(60):
            player = f"p{i}" + "-x" * (i % 7)
            t = {"player": player[:32], "team": i % 5, "game_id": 4242 + (i % 3 == 2)}
            payload = tag.encode(t, keys[i % 2])
            if i % 11 == 0:
                payload = payload[:-1] + bytes([payload[-1] ^ 0x80])
            for key in keys:
                with self.subTest(i=i, key=key.hex()):
                    py = json.dumps(tag.event_data(UID, payload, 4242, key, teams),
                                    separators=(",", ":"), ensure_ascii=False)
                    self.assertEqual(self.core.tag_event_json(UID, payload, 4242, key, teams), py)


if __name__ == "__main__":
    unittest.main()
