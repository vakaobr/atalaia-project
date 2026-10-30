# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The CBOR decoder on hostile input (security review SR-90): nesting is bounded (no recursion
error, no unbounded work) and a length or count larger than the bytes left is refused before
anything is allocated or looped over. Every payload decoder of the simulator and the controller
goes through this one decoder. The Dart twin is app/test/protocol/cbor_test.dart."""

import unittest

from atalaia_sim import cbor


class DepthTests(unittest.TestCase):
    def test_the_deepest_allowed_nesting_decodes_and_one_more_is_refused(self):
        ok = b"\x81" * (cbor.MAX_DEPTH - 1) + b"\x80"  # MAX_DEPTH containers, the last empty
        self.assertIsInstance(cbor.decode(ok), list)
        with self.assertRaisesRegex(cbor.CBORError, "nested"):
            cbor.decode(b"\x81" + ok)

    def test_a_huge_nesting_is_refused_without_a_recursion_error(self):
        for opener in (b"\x81", b"\xa1\x00"):  # [ [ [ ... and { 0: { 0: { ...
            with self.assertRaises(cbor.CBORError):
                cbor.decode(opener * 200_000)

    def test_maps_count_as_nesting_in_keys_and_values(self):
        with self.assertRaises(cbor.CBORError):
            cbor.decode(b"\xa1" + b"\x81" * 40 + b"\x00\x00")  # a deep key
        with self.assertRaises(cbor.CBORError):
            cbor.decode(b"\xa1\x00" + b"\x81" * 40 + b"\x00")  # a deep value


class CountTests(unittest.TestCase):
    def test_a_count_larger_than_the_input_is_refused(self):
        hostile = {
            "array, 8-byte count": b"\x9b" + b"\xff" * 8,
            "array, 4-byte count": b"\x9a\xff\xff\xff\xff\x00",
            "array, 2-byte count": b"\x99\xff\xff\x00",
            "array, 1 byte left for 2": b"\x82\x00",
            "map, 8-byte count": b"\xbb" + b"\xff" * 8,
            "map, 4-byte count": b"\xba\x7f\xff\xff\xff\x00",
            "map, 4 pairs, 4 bytes": b"\xa4\x00\x00\x01\x01",
            "text": b"\x7b" + b"\xff" * 8,
            "text, 3 bytes for 4": b"\x64abc",
            "text, 4-byte length": b"\x7a\xff\xff\xff\xff",
        }
        for name, data in hostile.items():
            with self.subTest(name):
                with self.assertRaises(cbor.CBORError):
                    cbor.decode(data)

    def test_a_byte_string_count_larger_than_the_input_is_refused(self):
        for data in (b"\x5b" + b"\xff" * 8, b"\x58\x05abc", b"\x5a\xff\xff\xff\xff"):
            with self.assertRaises(cbor.CBORError):
                cbor.decode(data, allow_bytes=True)

    def test_a_count_equal_to_the_bytes_left_is_accepted(self):
        self.assertEqual(cbor.decode(b"\x83\x00\x01\x02"), [0, 1, 2])
        self.assertEqual(cbor.decode(b"\xa1\x00\x01"), {0: 1})
        self.assertEqual(cbor.decode(b"\x43abc", allow_bytes=True), b"abc")

    def test_a_truncated_head_is_refused(self):
        for data in (b"", b"\x18", b"\x19\x00", b"\x1a\x00\x00\x00", b"\x1b\x00\x00\x00\x00\x00\x00\x00"):
            with self.assertRaises(cbor.CBORError):
                cbor.decode(data)


if __name__ == "__main__":
    unittest.main()
