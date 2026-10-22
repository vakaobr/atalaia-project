# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The check-in poster codec against protocol/vectors/checkin.json (also checked by the app's Dart).

Every vector is checked; none is skipped. Also the declarations' and the
field identities' rules from the same file, as the controller applies them.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the controller on the path)
from p3support import P3Case

from atalaia_controller import checkin, checkin_poster as cp
from atalaia_controller.engine import ControllerError

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "checkin.json")
                     .read_text(encoding="utf-8"))


def fields(v: dict) -> dict:
    out = dict(v["fields"])
    out["ca_sha256"] = bytes.fromhex(out["ca_sha256"])
    return out


class PosterVectorTests(unittest.TestCase):
    def test_counts(self) -> None:
        self.assertGreaterEqual(len(VECTORS["valid"]), 3)
        self.assertGreaterEqual(len(VECTORS["invalid"]), 40)
        self.assertGreaterEqual(len(VECTORS["texts"]["invalid"]), 6)

    def test_valid_round_trip(self) -> None:
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(cp.decode(payload), fields(v))
                self.assertEqual(cp.encode(fields(v)), payload)
                self.assertEqual(cp.to_text(payload), v["text"])
                self.assertEqual(cp.parse(v["text"]), fields(v))
                self.assertLessEqual(len(payload), cp.MAX_LEN)

    def test_optional_keys_skipped(self) -> None:
        o = VECTORS["optional_keys_skipped"]
        same = next(v for v in VECTORS["valid"] if v["name"] == o["same_as"])
        self.assertEqual(cp.decode(bytes.fromhex(o["payload"])), fields(same))

    def test_invalid_fail_with_their_reason(self) -> None:
        for v in VECTORS["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(cp.PosterError) as cm:
                cp.decode(bytes.fromhex(v["payload"]))
            self.assertEqual(cm.exception.reason, v["reason"], f"{v['name']}: {cm.exception}")

    def test_texts(self) -> None:
        same = VECTORS["texts"]["same"]
        ref = next(v for v in VECTORS["valid"] if v["name"] == same["same_as"])
        self.assertEqual(cp.from_text(same["text"]).hex(), ref["payload"])
        for v in VECTORS["texts"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(cp.PosterError) as cm:
                cp.from_text(v["text"])
            self.assertEqual(cm.exception.reason, "text")

    def test_encoder_refuses_what_decoders_refuse(self) -> None:
        base = fields(VECTORS["valid"][0])
        for change in ({"urls": ["http://10.0.0.1:8080"]}, {"field_id": "a b"}, {"ca_sha256": b"\0" * 31},
                       {"game_id": 0}, {"wifi_ssid": "x" * 33}, {"extra": 1}):
            with self.subTest(change), self.assertRaises(cp.PosterError):
                cp.encode({**base, **change})
        with self.assertRaises(cp.PosterError) as cm:
            cp.encode({**base, "field_name": "x" * 48,
                       "urls": [f"https://{c * 50}:8443" for c in "abc"]})
        self.assertEqual(cm.exception.reason, "length")

    def test_no_secret_fits_in_a_poster(self) -> None:
        # Constraint 25: only keys 1-6 exist, none of them a key or a password.
        self.assertEqual(set(cp.KEYS), {"field_id", "field_name", "urls", "ca_sha256", "wifi_ssid", "game_id"})

    def test_short_fingerprint(self) -> None:
        self.assertEqual(cp.short_fingerprint(bytes(range(32))), "0001 0203 0405 0607")


class DeclarationVectorTests(unittest.TestCase):
    def test_valid(self) -> None:
        for v in VECTORS["declarations"]["valid"]:
            with self.subTest(v["name"]):
                d = checkin.validate_declaration(v["declaration"])
                self.assertEqual(d["declaration_id"], v["declaration"]["declaration_id"])

    def test_invalid(self) -> None:
        for v in VECTORS["declarations"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(ControllerError):
                checkin.validate_declaration(v["declaration"])

    def test_identities(self) -> None:
        ids = VECTORS["identities"]
        for pid in ids["player_ids"]["valid"]:
            self.assertTrue(checkin.player_id_ok(pid), pid)
        for pid in ids["player_ids"]["invalid"]:
            self.assertFalse(checkin.player_id_ok(pid), pid)
        for s in ids["secrets"]["valid"]:
            self.assertEqual(len(checkin.secret_bytes(s)), 32)
        for s in ids["secrets"]["invalid"]:
            with self.subTest(s), self.assertRaises(ControllerError):
                checkin.secret_bytes(s)
        for _ in range(50):
            self.assertTrue(checkin.player_id_ok(checkin.new_player_id()))


class PosterProblemTests(P3Case):
    """Why the poster cannot be made comes as a code the console translates (OT-5: the bench's
    console showed "HTTPS is off ..." in English), next to the English text."""

    def poster(self) -> dict:
        return self.client.get("/api/v1/checkin/poster", headers={"Authorization": "Bearer gm-secret"}).json()

    def test_problem_codes(self) -> None:
        p = self.poster()
        self.assertTrue(p["text"])
        self.assertIsNone(p["problem"])
        self.assertIsNone(p["problem_code"])
        ca = self.svc.ca_sha256
        self.svc.ca_sha256 = None
        p = self.poster()
        self.assertEqual((p["text"], p["problem_code"]), (None, "https_off"))
        self.assertIn("HTTPS is off", p["problem"])
        self.svc.ca_sha256 = ca
        self.svc.default_urls = []
        p = self.poster()
        self.assertEqual((p["text"], p["problem_code"]), (None, "no_address"))
        self.assertIn("tls_names", p["problem"])
        # Three addresses of 64 bytes and a long name do not fit in a QR code's poster.
        self.svc.default_urls = ["https://" + "a" * 42 + f"{i}.example:8443" for i in range(3)]
        self.svc.cfg.field_name = "N" * 48
        p = self.poster()
        self.assertEqual((p["text"], p["problem_code"]), (None, "too_long"))

    def test_fields_are_checked_with_https_off(self) -> None:
        """Decision PE24-58: without the field CA the poster's fields were kept unchecked, so a
        game_id of "x" closed check-in to every game ("for another game") without an error."""
        self.svc.ca_sha256 = None
        gm = {"Authorization": "Bearer gm-secret"}
        for bad in ({"game_id": "x"}, {"game_id": 0}, {"field_name": " "}, {"wifi_ssid": "s" * 33},
                    {"urls": ["http://10.0.0.1"]}):
            with self.subTest(bad):
                r = self.client.put("/api/v1/checkin/poster", json=bad, headers=gm)
                self.assertEqual(r.status_code, 400, r.text)
        self.assertIsNone(self.poster()["game_id"])
        g = self.new_game()
        r = self.client.put("/api/v1/checkin/poster", json={"game_id": g["id"], "wifi_ssid": "Campo"}, headers=gm)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["game_id"], r.json()["problem_code"]), (g["id"], "https_off"))
        self.check_in(g["id"])


if __name__ == "__main__":
    unittest.main()
