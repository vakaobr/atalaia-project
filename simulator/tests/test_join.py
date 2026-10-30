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
    out["ca_sha256"] = bytes.fromhex(out["ca_sha256"]) if out.get("ca_sha256") else None
    out.setdefault("urls", None)
    out.setdefault("lang", None)
    out.setdefault("fetch_modes", False)
    out.setdefault("forget_modes", False)
    out.setdefault("region", "eu868")
    out.setdefault("box_beacon", True)
    out.setdefault("box_places", None)  # key 22: lists of [node id, level, x, y]
    mirror = out.get("box_beacons")  # key 21: JSON has text keys, the codec node ids
    out["box_beacons"] = None if mirror is None else {
        k: ({int(n): t for n, t in v.items()} if k == "rooms" else v) for k, v in mirror.items()}
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


class ControllerLinkTests(unittest.TestCase):
    """Optional keys 13 and 14 (RFC 0001 Amendment 4, proposed): the field CA and the controller's addresses."""

    def test_valid_round_trip(self) -> None:
        link = VECTORS["controller_link"]
        self.assertGreaterEqual(len(link["valid"]), 3)
        for v in link["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(join.decode(payload, KEY), fields(v))
                self.assertEqual(join.encode(fields(v), KEY), payload)
                self.assertEqual(join.to_text(payload), v["text"])

    def test_invalid_fail_as_body(self) -> None:
        for v in VECTORS["controller_link"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(join.JoinError) as cm:
                join.decode(bytes.fromhex(v["payload"]), KEY)
            self.assertEqual(cm.exception.reason, "body", f"{v['name']}: {cm.exception}")


class BoxLanguageTests(unittest.TestCase):
    """Optional key 15 (RFC 0001 Amendment 10, proposed): the language of a box's screens."""

    def test_valid_round_trip(self) -> None:
        section = VECTORS["box_language"]
        self.assertGreaterEqual(len(section["valid"]), 2)
        for v in section["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(join.decode(payload, KEY), fields(v))
                self.assertEqual(join.encode(fields(v), KEY), payload)
                self.assertEqual(join.to_text(payload), v["text"])

    def test_invalid_fail_as_body(self) -> None:
        for v in VECTORS["box_language"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(join.JoinError) as cm:
                join.decode(bytes.fromhex(v["payload"]), KEY)
            self.assertEqual(cm.exception.reason, "body", f"{v['name']}: {cm.exception}")

    def test_absent_is_none_and_encode_checks(self) -> None:
        self.assertIsNone(join.decode(bytes.fromhex(VECTORS["valid"][0]["payload"]), KEY)["lang"])
        for bad in ("", "PT", "p", "toolonglang", "1t", 5):
            with self.subTest(bad), self.assertRaises(join.JoinError):
                join.encode({**fields(VECTORS["valid"][0]), "lang": bad}, KEY)


class ModeFetchTests(unittest.TestCase):
    """Optional keys 16 (fetch_modes) and 17 (forget_modes), phase 5 plan phase 13
    (protocol/mode-packages.md): true when set, left out otherwise."""

    def test_valid_round_trip(self) -> None:
        section = VECTORS["mode_fetch"]
        self.assertGreaterEqual(len(section["valid"]), 4)
        for v in section["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(join.decode(payload, KEY), fields(v))
                self.assertEqual(join.encode(fields(v), KEY), payload)
                self.assertEqual(join.to_text(payload), v["text"])
                self.assertEqual(join.from_text(v["text"]), payload)

    def test_invalid_fail_as_body(self) -> None:
        self.assertGreaterEqual(len(VECTORS["mode_fetch"]["invalid"]), 6)
        for v in VECTORS["mode_fetch"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(join.JoinError) as cm:
                join.decode(bytes.fromhex(v["payload"]), KEY)
            self.assertEqual(cm.exception.reason, "body", f"{v['name']}: {cm.exception}")

    def test_absent_is_false_and_false_is_left_out(self) -> None:
        base = fields(VECTORS["valid"][0])
        got = join.decode(bytes.fromhex(VECTORS["valid"][0]["payload"]), KEY)
        self.assertEqual((got["fetch_modes"], got["forget_modes"]), (False, False))
        # False encodes as nothing at all: the same bytes as a join without the keys.
        self.assertEqual(join.encode({**base, "fetch_modes": False, "forget_modes": False}, KEY),
                         bytes.fromhex(VECTORS["valid"][0]["payload"]))
        for bad in (1, 0, "true", None):
            with self.subTest(bad), self.assertRaises(join.JoinError):
                join.encode({**base, "fetch_modes": bad}, KEY)


class BoxBeaconTests(unittest.TestCase):
    """Optional key 19 (box_beacon), RFC 0001 Amendment 20: false when the GM turned the boxes' iBeacon
    off, the key left out for on."""

    def test_valid_round_trip(self) -> None:
        section = VECTORS["box_beacon"]
        self.assertGreaterEqual(len(section["valid"]), 2)
        for v in section["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertIs(join.decode(payload, KEY)["box_beacon"], False)
                self.assertEqual(join.decode(payload, KEY), fields(v))
                self.assertEqual(join.encode(fields(v), KEY), payload)
                self.assertEqual(join.to_text(payload), v["text"])

    def test_invalid_fail_as_body(self) -> None:
        self.assertGreaterEqual(len(VECTORS["box_beacon"]["invalid"]), 6)
        for v in VECTORS["box_beacon"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(join.JoinError) as cm:
                join.decode(bytes.fromhex(v["payload"]), KEY)
            self.assertEqual(cm.exception.reason, "body", f"{v['name']}: {cm.exception}")

    def test_on_is_the_key_left_out(self) -> None:
        base = fields(VECTORS["valid"][0])
        payload = bytes.fromhex(VECTORS["valid"][0]["payload"])
        self.assertIs(join.decode(payload, KEY)["box_beacon"], True)
        self.assertEqual(join.encode({**base, "box_beacon": True}, KEY), payload)
        self.assertEqual(join.encode({k: v for k, v in base.items() if k != "box_beacon"}, KEY), payload)
        self.assertEqual(len(join.encode({**base, "box_beacon": False}, KEY)), len(payload) + 2)
        for bad in (0, 1, "false", None):
            with self.subTest(bad), self.assertRaises(join.JoinError):
                join.encode({**base, "box_beacon": bad}, KEY)


class BoxBeaconsMirrorTests(unittest.TestCase):
    """Optional key 21 (box_beacons), RFC 0001 Amendment 21 (decision BBC-20): a standby controller's join
    carries the boxes the GM disabled and the rooms the GM gave."""

    def test_valid_round_trip(self) -> None:
        section = VECTORS["box_beacons"]
        self.assertGreaterEqual(len(section["valid"]), 3)
        for v in section["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                got = join.decode(payload, KEY)
                self.assertEqual(got["kind"], "controller")
                self.assertEqual(got, fields(v))
                self.assertEqual(join.encode(fields(v), KEY), payload)
                self.assertEqual(join.to_text(payload), v["text"])

    def test_invalid_fail_as_body(self) -> None:
        self.assertGreaterEqual(len(VECTORS["box_beacons"]["invalid"]), 15)
        for v in VECTORS["box_beacons"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(join.JoinError) as cm:
                join.decode(bytes.fromhex(v["payload"]), KEY)
            self.assertEqual(cm.exception.reason, "body", f"{v['name']}: {cm.exception}")

    def test_the_encoder_refuses_what_the_decoder_does(self) -> None:
        base = fields(VECTORS["box_beacons"]["valid"][0])
        for bad in ({}, {"off": []}, {"off": [9, 4]}, {"off": [0]}, {"rooms": {7: ""}}, {"rooms": {7: "x" * 49}},
                    {"rooms": {n: "x" * 48 for n in range(1, 6)}}, {"off": [1], "other": 1}, "off", 5):
            with self.subTest(bad), self.assertRaises(join.JoinError):
                join.encode({**base, "box_beacons": bad}, KEY)
        node = fields(VECTORS["valid"][0])
        with self.assertRaises(join.JoinError):  # a box's join never carries it
            join.encode({**node, "box_beacons": {"off": [4]}}, KEY)

    def test_absent_is_the_join_of_before(self) -> None:
        base = fields(VECTORS["box_beacons"]["valid"][0])
        plain = join.encode({**base, "box_beacons": None}, KEY)
        self.assertEqual(plain, join.encode({k: v for k, v in base.items() if k != "box_beacons"}, KEY))
        self.assertIsNone(join.decode(plain, KEY)["box_beacons"])
        self.assertLess(len(plain), len(join.encode(base, KEY)))


class BoxPlacesTests(unittest.TestCase):
    """Optional key 22 (box_places), RFC 0001 Amendment 22 (decision BBC-25): a standby controller's join
    carries where the GM placed the boxes, 7 bytes each."""

    def test_valid_round_trip(self) -> None:
        section = VECTORS["box_places"]
        self.assertGreaterEqual(len(section["valid"]), 4)
        for v in section["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                got = join.decode(payload, KEY)
                self.assertEqual(got["kind"], "controller")
                self.assertEqual(got, fields(v))
                self.assertEqual(join.encode(fields(v), KEY), payload)
                self.assertEqual(join.to_text(payload), v["text"])
                self.assertLessEqual(len(payload), join.MAX_LEN)

    def test_invalid_fail_as_body(self) -> None:
        self.assertGreaterEqual(len(VECTORS["box_places"]["invalid"]), 12)
        for v in VECTORS["box_places"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(join.JoinError) as cm:
                join.decode(bytes.fromhex(v["payload"]), KEY)
            self.assertEqual(cm.exception.reason, "body", f"{v['name']}: {cm.exception}")

    def test_the_quantization_is_the_vectors(self) -> None:
        for q in VECTORS["box_places"]["quantize"]:
            with self.subTest(q):
                self.assertEqual(join.quantize(q["v"]), q["q"])
        self.assertEqual(join.dequantize(65535), 1.0)
        self.assertEqual(join.dequantize(0), 0.0)

    def test_the_encoder_refuses_what_the_decoder_does(self) -> None:
        base = fields(VECTORS["box_places"]["valid"][0])
        for bad in ([], [[0, 0, 1, 1]], [[65535, 0, 1, 1]], [[4, 10, 1, 1]], [[4, 0, 65536, 1]], [[4, 0, -1, 1]],
                    [[9, 0, 1, 1], [4, 0, 1, 1]], [[4, 0, 1, 1], [4, 0, 2, 2]], [[4, 0, 1]], [[4, 0, 1, 1.5]],
                    [[n, 0, 1, 1] for n in range(1, 30)], "boxes", 5):
            with self.subTest(bad), self.assertRaises(join.JoinError):
                join.encode({**base, "box_places": bad}, KEY)
        node = fields(VECTORS["valid"][0])
        with self.assertRaises(join.JoinError):  # a box's join never carries it
            join.encode({**node, "box_places": [[4, 0, 1, 1]]}, KEY)

    def test_absent_is_the_join_of_before(self) -> None:
        base = fields(VECTORS["box_places"]["valid"][0])
        plain = join.encode({**base, "box_places": None}, KEY)
        self.assertEqual(plain, join.encode({k: v for k, v in base.items() if k != "box_places"}, KEY))
        self.assertIsNone(join.decode(plain, KEY)["box_places"])
        self.assertLess(len(plain), len(join.encode(base, KEY)))

    def test_what_does_not_fit_is_refused_and_says_so(self) -> None:
        base = fields(VECTORS["box_places"]["valid"][0])
        long_teams = ["t" * 22 + str(n) for n in range(8)]
        with self.assertRaises(join.JoinError) as cm:
            join.encode({**base, "teams": long_teams, "box_beacons": {"rooms": {n: "r" * 48 for n in range(1, 4)}},
                         "box_places": [[n, 0, 1, 1] for n in range(1, 29)]}, KEY)
        self.assertEqual(cm.exception.reason, "length")
        self.assertIn("places take 198", str(cm.exception))

    def test_the_twenty_boxes_of_a_field_fit_with_plenty_of_room(self) -> None:
        base = fields(VECTORS["box_places"]["valid"][0])
        payload = join.encode({**base, "box_places": [[n, n % 4, n * 100, n * 200] for n in range(1, 21)]}, KEY)
        self.assertLess(len(payload), 300)


class RegionTests(unittest.TestCase):
    """Optional key 18 (region), RFC 0001 Amendment 12: the region's number, left out for EU868."""

    def test_valid_round_trip(self) -> None:
        section = VECTORS["region"]
        self.assertGreaterEqual(len(section["valid"]), 3)
        for v in section["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(join.decode(payload, KEY), fields(v))
                self.assertEqual(join.encode(fields(v), KEY), payload)
                self.assertEqual(join.to_text(payload), v["text"])

    def test_invalid_fail_as_body(self) -> None:
        self.assertGreaterEqual(len(VECTORS["region"]["invalid"]), 8)
        for v in VECTORS["region"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(join.JoinError) as cm:
                join.decode(bytes.fromhex(v["payload"]), KEY)
            self.assertEqual(cm.exception.reason, "body", f"{v['name']}: {cm.exception}")

    def test_eu868_is_the_key_left_out(self) -> None:
        base = fields(VECTORS["valid"][0])
        payload = bytes.fromhex(VECTORS["valid"][0]["payload"])
        self.assertEqual(join.decode(payload, KEY)["region"], "eu868")
        self.assertEqual(join.encode({**base, "region": "eu868"}, KEY), payload)
        for bad in ("us915", "EU868", 0, 1, None):
            with self.subTest(bad), self.assertRaises(join.JoinError):
                join.encode({**base, "region": bad}, KEY)
        # The channel must fit in the region the join names.
        with self.assertRaises(join.JoinError):
            join.encode({**base, "region": "as923-tw"}, KEY)
        with self.assertRaises(join.JoinError):
            join.encode({**base, "channel_hz": 921_500_000}, KEY)


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
