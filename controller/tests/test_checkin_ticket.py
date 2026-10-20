# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The check-in ticket codec against the ``tickets`` vectors of protocol/vectors/checkin.json (also
checked by the app's Dart, app/test/protocol/checkin_ticket_test.dart). Every vector is checked."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

import support  # noqa: F401  (puts the controller on the path)

from atalaia_controller import checkin_ticket as ct

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "checkin.json")
                     .read_text(encoding="utf-8"))["tickets"]


def fields(v: dict) -> dict:
    out = dict(v["fields"])
    out["secret"] = bytes.fromhex(out["secret"])
    return out


class TicketVectorTests(unittest.TestCase):
    def test_counts(self) -> None:
        self.assertGreaterEqual(len(VECTORS["valid"]), 2)
        self.assertGreaterEqual(len(VECTORS["invalid"]), 20)
        self.assertGreaterEqual(len(VECTORS["texts"]["invalid"]), 6)

    def test_valid_round_trip(self) -> None:
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(ct.decode(payload), fields(v))
                self.assertEqual(ct.encode(fields(v)), payload)
                self.assertEqual(ct.to_text(payload), v["text"])
                self.assertEqual(ct.make(fields(v)), v["text"])
                self.assertEqual(ct.parse(v["text"]), fields(v))
                self.assertEqual(ct.secret_sha256(fields(v)["secret"]), v["secret_sha256"])
                self.assertEqual(v["secret_sha256"], hashlib.sha256(fields(v)["secret"]).hexdigest())
                text = ct.secret_text(fields(v)["secret"])
                self.assertEqual((len(text), ct.secret_from_text(text)), (43, fields(v)["secret"]))

    def test_optional_keys_skipped(self) -> None:
        o = VECTORS["optional_keys_skipped"]
        same = next(v for v in VECTORS["valid"] if v["name"] == o["same_as"])
        self.assertEqual(ct.decode(bytes.fromhex(o["payload"])), fields(same))

    def test_invalid_fail_with_their_reason(self) -> None:
        for v in VECTORS["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(ct.TicketError) as cm:
                ct.decode(bytes.fromhex(v["payload"]))
            self.assertEqual(cm.exception.reason, v["reason"], f"{v['name']}: {cm.exception}")

    def test_texts(self) -> None:
        same = VECTORS["texts"]["same"]
        ref = next(v for v in VECTORS["valid"] if v["name"] == same["same_as"])
        self.assertEqual(ct.from_text(same["text"]).hex(), ref["payload"])
        for v in VECTORS["texts"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(ct.TicketError) as cm:
                ct.parse(v["text"])
            self.assertEqual(cm.exception.reason, v["reason"])

    def test_secret_text_rules(self) -> None:
        for bad in ("A" * 42, "A" * 44, "A" * 42 + "+", "A" * 42 + "B", None, 7):
            with self.subTest(bad), self.assertRaises(ct.TicketError):
                ct.secret_from_text(bad)


if __name__ == "__main__":
    unittest.main()
