# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The core's relay rules (RFC 0001 Amendment 13, decision SL-16) through ctypes, and the relay
study's ``A_backoff_core`` policy that runs the study's harness on them.

The rules' own unit tests are in C (core/tests/test_flood.c); these check that the Python view of the
core's struct is right, that the rules do what the study's model of them did, and that the harness
run on the real code lands where the model's run does.

    cd simulator && python -m unittest tests.test_relay_core
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim import relay_core
from atalaia_sim.core import find_library
from atalaia_sim.relay_study import ACK_RETRY_MS, run_one


def _lib():
    try:
        return str(find_library())
    except (FileNotFoundError, OSError):
        if os.environ.get("ATALAIA_REQUIRE_ALL") == "1":
            raise
        return None


LIB = _lib()


@unittest.skipIf(LIB is None, "the shared core is not built")
class CoreRelayTests(unittest.TestCase):
    def relay(self, seed: int = 1) -> relay_core.CoreRelay:
        return relay_core.CoreRelay(random.Random(seed), LIB)

    def test_struct_layout_matches_the_c_struct(self) -> None:
        r = self.relay()
        r.heard(9, 1000)
        slot = r.plan(relay_core.ASKS_ACK, 9, 77, 0, 5000)
        self.assertEqual(slot, 0)
        s = r.state.slots[slot]
        self.assertTrue(s.used and s.wait_ack)
        self.assertEqual((s.source, s.seq), (9, 77))
        self.assertTrue(5000 + 350 <= s.due_ms <= 5000 + 700)
        self.assertEqual(r.state.neighbours[0].source, 9)
        self.assertEqual(r.state.neighbours[0].heard_ms, 1000)

    def test_eight_slots_and_a_dropped_ninth(self) -> None:
        r = self.relay()
        r.heard(9, 1000)
        self.assertEqual([r.plan(relay_core.OTHER, 9, i, 0, 1000) for i in range(8)], list(range(8)))
        self.assertEqual(r.plan(relay_core.OTHER, 9, 8, 0, 1000), relay_core.NO_SLOT)
        self.assertEqual(r.pending(), 8)

    def test_ack_cancels_the_waiting_frame_and_only_that_one(self) -> None:
        r = self.relay()
        a = r.plan(relay_core.ASKS_ACK, 9, 10, 0, 0)
        b = r.plan(relay_core.ASKS_ACK, 9, 12, 0, 0)
        c = r.plan(relay_core.ASKS_ACK, 8, 10, 0, 0)
        # ack_seq 10, bit 1 (seq 12) set
        self.assertEqual(r.ack_heard(9, 10, {12}), 2)
        self.assertFalse(r.state.slots[a].used or r.state.slots[b].used)
        self.assertTrue(r.state.slots[c].used)
        self.assertEqual(r.ack_heard(9, -1, set()), 0)

    def test_ack_is_relayed_only_after_a_frame_of_that_box_was_relayed(self) -> None:
        r = self.relay()
        self.assertEqual(r.plan(relay_core.ACK, 0, 1, 9, 1000), relay_core.SKIP)
        slot = r.plan(relay_core.ASKS_ACK, 9, 4, 0, 1000)
        self.assertEqual(r.take_due(1000 + 700), slot)
        self.assertGreaterEqual(r.plan(relay_core.ACK, 0, 2, 9, 1700), 0)
        self.assertEqual(r.plan(relay_core.ACK, 0, 3, 8, 1700), relay_core.SKIP)

    def test_probability_is_three_over_neighbours(self) -> None:
        for n in (6, 12, 30):
            r = self.relay(n)
            for i in range(n):
                r.heard(100 + i, 1000)
            relayed = 0
            for i in range(6000):
                slot = r.plan(relay_core.OTHER, 9, i, 0, 1000)
                if slot >= 0:
                    relayed += 1
                    r.take_due(10_000)
            self.assertAlmostEqual(relayed / 6000, 3 / n, delta=0.03, msg=f"n={n}")

    def test_retry_gap_schedule(self) -> None:
        r = self.relay()
        base = [3000, 6000, 12000, 24000, 30000, 30000, 30000]
        for sends, b in enumerate(base, start=1):
            for _ in range(200):
                g = r.retry_gap_ms(sends)
                self.assertTrue(0.75 * b - 1 <= g <= 1.25 * b + 1, (sends, g))
        self.assertEqual(base[0], ACK_RETRY_MS)


@unittest.skipIf(LIB is None, "the shared core is not built")
class HarnessOnTheCoreTests(unittest.TestCase):
    """The study's harness, with every box running the core's rules, against its own model of them."""

    def test_core_rules_land_where_the_model_does(self) -> None:
        model = run_one("domination", 20, "all_in_range", "eu868", "A_backoff", minutes=12, seed=1, lib=LIB)
        real = run_one("domination", 20, "all_in_range", "eu868", "A_backoff_core", minutes=12, seed=1, lib=LIB)
        for res in (model, real):
            self.assertEqual(res["dc_dropped"]["total"], 0)
        self.assertAlmostEqual(real["airtime_pct"]["mean"], model["airtime_pct"]["mean"], delta=0.6)
        self.assertGreaterEqual(real["events"]["captures"]["delivered_pct"], 99.0)
        self.assertGreaterEqual(real["events"]["captures"]["acked_pct"], 95.0)


if __name__ == "__main__":
    unittest.main()
