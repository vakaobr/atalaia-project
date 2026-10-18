# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed chrono readings against protocol/vectors/chrono_record.json (also checked by the app's Dart tests).

    cd controller && python -m unittest test_chrono_records

The records are signed by the app (app/lib/chrono/record_signer.dart); this
is the verifier the controller, and later the site server, use. Every vector
is checked; none is skipped.
"""

from __future__ import annotations

import base64
import copy
import json
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from atalaia_controller import chrono

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "chrono_record.json")
                     .read_text(encoding="utf-8"))
SEED = bytes.fromhex(VECTORS["seed"])
PUBLIC = bytes.fromhex(VECTORS["public_key"])


class VectorTests(unittest.TestCase):
    def test_vector_counts(self) -> None:
        self.assertGreaterEqual(len(VECTORS["valid"]), 4)
        self.assertGreaterEqual(len(VECTORS["invalid"]), 20)
        self.assertEqual(len(VECTORS["rfc8032"]), 3)

    def test_key_pair(self) -> None:
        key = Ed25519PrivateKey.from_private_bytes(SEED)
        raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.assertEqual(raw, PUBLIC)

    def test_rfc8032(self) -> None:
        for v in VECTORS["rfc8032"]:
            with self.subTest(v["name"]):
                key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(v["seed"]))
                self.assertEqual(key.sign(bytes.fromhex(v["message"])).hex(), v["signature"])

    def test_valid(self) -> None:
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                record = v["record"]
                canon = chrono.canonical(record)
                self.assertEqual(canon, v["canonical"].encode("utf-8"))
                self.assertEqual(canon.hex(), v["canonical_hex"])
                # The phase 4 snippet (ADR-P4-5) gives the same bytes.
                without = {k: x for k, x in record.items() if k != "signature"}
                self.assertEqual(json.dumps(without, sort_keys=True, separators=(",", ":"),
                                            ensure_ascii=False).encode("utf-8"), canon)
                fields = chrono.verify(record, PUBLIC)
                self.assertEqual(fields, without)
                # Ed25519 is deterministic: signing again gives the vector's signature.
                sig = Ed25519PrivateKey.from_private_bytes(SEED).sign(canon)
                self.assertEqual(base64.b64encode(sig).decode("ascii"), record["signature"])
                # Through JSON text, and with whole numbers written as integers.
                self.assertEqual(chrono.parse(json.dumps(record), PUBLIC), fields)
                ints = {k: (int(x) if isinstance(x, float) and x.is_integer() else x) for k, x in record.items()}
                self.assertEqual(chrono.verify(ints, PUBLIC), fields)
                with self.assertRaises(chrono.ChronoError) as ctx:
                    chrono.verify(record, bytes(31) + b"\x01")
                self.assertIn(ctx.exception.reason, ("signature",))

    def test_invalid(self) -> None:
        for v in VECTORS["invalid"]:
            with self.subTest(v["name"]):
                with self.assertRaises(chrono.ChronoError) as ctx:
                    chrono.verify(v["record"], PUBLIC)
                self.assertEqual(ctx.exception.reason, v["reason"])

    def test_numbers(self) -> None:
        for v in VECTORS["numbers"]:
            with self.subTest(v["text"]):
                self.assertEqual(json.dumps(float(v["value"])), v["text"])

    def test_energies(self) -> None:
        for v in VECTORS["energies"]:
            with self.subTest(v):
                e = chrono.round_half_away(chrono.energy_j(v["bb_weight_g"], v["velocity_mps"]), 3)
                self.assertEqual(e, v["energy_j"])
        for v in VECTORS["fps"]:
            with self.subTest(v):
                self.assertEqual(chrono.round_half_away(v["fps"] * 0.3048, 2), v["velocity_mps"])


class CheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.record = copy.deepcopy(VECTORS["valid"][0]["record"])

    def test_not_an_object(self) -> None:
        for value in ([], "x", None, 1):
            with self.assertRaises(chrono.ChronoError) as ctx:
                chrono.verify(value, PUBLIC)
            self.assertEqual(ctx.exception.reason, "format")

    def test_not_json(self) -> None:
        with self.assertRaises(chrono.ChronoError) as ctx:
            chrono.parse("{", PUBLIC)
        self.assertEqual(ctx.exception.reason, "format")

    def test_boolean_is_not_a_number(self) -> None:
        self.record["bb_weight_g"] = True
        with self.assertRaises(chrono.ChronoError):
            chrono.check(self.record)

    def test_lone_surrogate_in_name(self) -> None:
        self.record["marshal_name"] = "Jo\ud800se"
        with self.assertRaises(chrono.ChronoError):
            chrono.check(self.record)

    def test_round_half_away(self) -> None:
        self.assertEqual(chrono.round_half_away(1.050625, 3), 1.051)
        self.assertEqual(chrono.round_half_away(350 * 0.3048, 2), 106.68)
        self.assertEqual(chrono.round_half_away(2.5, 0), 3.0)
        self.assertEqual(chrono.round_half_away(0.0625, 3), 0.063)
        self.assertEqual(chrono.round_half_away(0.0, 3), 0.0)


if __name__ == "__main__":
    unittest.main()
