# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Player tokens against protocol/vectors/player_token.json (also checked by the app's Dart tests).

    cd controller && python -m unittest test_player_token

Every vector is checked; none is skipped. The MAC is recomputed with
Python's own hmac module, independently of the module under test.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import unittest
from pathlib import Path

from atalaia_controller import player_token as pt

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "player_token.json")
                     .read_text(encoding="utf-8"))
KEY = bytes.fromhex(VECTORS["key"])
GAME = VECTORS["game_id"]
TEAMS = VECTORS["team_count"]
NOW = VECTORS["now"]


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class VectorTests(unittest.TestCase):
    def test_vector_counts(self) -> None:
        self.assertGreaterEqual(len(VECTORS["valid"]), 3)
        self.assertGreaterEqual(len(VECTORS["invalid"]), 20)

    def test_valid(self) -> None:
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                self.assertEqual(pt.verify(v["token"], KEY, game_id=GAME, team_count=TEAMS, now=NOW), v["claims"])
                self.assertEqual(pt.issue(v["claims"], KEY), v["token"])
                payload = v["payload"].encode("ascii")
                self.assertEqual(payload, json.dumps(v["claims"], sort_keys=True, separators=(",", ":")).encode())
                signed = "apt1." + _b64(payload)
                mac = hmac.new(KEY, signed.encode("ascii"), hashlib.sha256).digest()
                self.assertEqual(mac.hex(), v["mac"])
                self.assertEqual(v["token"], signed + "." + _b64(mac))
                with self.assertRaises(pt.TokenError) as ctx:
                    pt.verify(v["token"], bytes(32), game_id=GAME, team_count=TEAMS, now=NOW)
                self.assertEqual(ctx.exception.reason, "mac")

    def test_invalid(self) -> None:
        for v in VECTORS["invalid"]:
            with self.subTest(v["name"]):
                with self.assertRaises(pt.TokenError) as ctx:
                    pt.verify(v["token"], KEY, game_id=GAME, team_count=TEAMS, now=NOW)
                self.assertEqual(ctx.exception.reason, v["reason"])


class IssueTests(unittest.TestCase):
    def test_key_size(self) -> None:
        claims = VECTORS["valid"][0]["claims"]
        for size in (0, 15, 65):
            with self.assertRaises(ValueError):
                pt.issue(claims, bytes(size))
        self.assertTrue(pt.issue(claims, bytes(16)).startswith("apt1."))

    def test_refuses_bad_claims(self) -> None:
        claims = dict(VECTORS["valid"][0]["claims"])
        for change in ({"role": "admin"}, {"team": 9}, {"squad": -1}, {"game_id": 0}, {"exp": 0},
                       {"player_id": ""}, {"player_id": "x" * 33}):
            with self.subTest(change):
                with self.assertRaises(pt.TokenError):
                    pt.issue({**claims, **change}, KEY)

    def test_not_a_string(self) -> None:
        for token in (None, 1, b"apt1.x.y", "apt1.é.x", "a" * 513):
            with self.assertRaises(pt.TokenError) as ctx:
                pt.verify(token, KEY, game_id=GAME, team_count=TEAMS, now=NOW)
            self.assertEqual(ctx.exception.reason, "format")


if __name__ == "__main__":
    unittest.main()
