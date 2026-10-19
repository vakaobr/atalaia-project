# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""UUIDv7 keys (no database; also run by tools/check.sh)."""

from __future__ import annotations

import sys
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atalaia_server.ids import uuid7, uuid7_from_parts, uuid7_time_ms  # noqa: E402


class Uuid7Tests(unittest.TestCase):
    def test_rfc_9562_example(self) -> None:
        # RFC 9562, Appendix A.6 "Example of a UUIDv7 Value": unix_ts_ms 0x017F22E279B0
        # (2022-02-22 14:22:22 -05:00), rand_a 0xCC3, rand_b 0x18C4DC0C0C07398F.
        value = uuid7_from_parts(0x017F22E279B0, 0xCC3, 0x18C4DC0C0C07398F)
        self.assertEqual(value, uuid.UUID("017F22E2-79B0-7CC3-98C4-DC0C0C07398F"))
        self.assertEqual(uuid7_time_ms(value), 1645557742000)

    def test_version_and_variant(self) -> None:
        value = uuid7()
        self.assertEqual(value.version, 7)
        self.assertEqual(value.variant, uuid.RFC_4122)

    def test_carries_the_time(self) -> None:
        before = time.time_ns() // 1_000_000
        value = uuid7()
        after = time.time_ns() // 1_000_000
        self.assertLessEqual(before, uuid7_time_ms(value))
        self.assertLessEqual(uuid7_time_ms(value), after + 1)  # +1: a counter overflow moves the time on

    def test_keys_sort_in_creation_order(self) -> None:
        values = [uuid7() for _ in range(20000)]  # many share a millisecond
        self.assertEqual(values, sorted(values, key=lambda v: v.int))
        self.assertEqual(len(set(values)), len(values))

    def test_parts_out_of_range(self) -> None:
        for args in ((1 << 48, 0, 0), (-1, 0, 0), (0, 1 << 12, 0), (0, 0, 1 << 62)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                uuid7_from_parts(*args)
        with self.assertRaises(ValueError):
            uuid7_time_ms(uuid.uuid4())


if __name__ == "__main__":
    unittest.main()
