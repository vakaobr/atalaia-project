# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The CLAIM election state machine on its own (ADR-P2-8).

    cd simulator && python -m unittest discover -s tests

No radio and no core library: these feed TIME and CLAIM messages by hand.
test_failover_sim.py runs the same code over the radio model.
"""

from __future__ import annotations

import unittest

from atalaia_sim.election import (
    CANDIDATE,
    FOLLOWER,
    LEADER,
    POWER_MAINS,
    POWER_SMALL_BATTERY,
    Election,
    beacon_interval_ms,
    priority_score,
)


class PriorityTests(unittest.TestCase):
    def test_formula(self):
        # ADR-P2-8: power * 4096 + battery * 32 + storage * 512 + link * 2.
        self.assertEqual(priority_score(POWER_MAINS, 100, True, 100), 3 * 4096 + 3200 + 512 + 200)
        self.assertEqual(priority_score(POWER_SMALL_BATTERY, 50, False, 40), 4096 + 1600 + 80)

    def test_a_mains_pi_beats_a_battery_box(self):
        pi = priority_score(POWER_MAINS, 0, True, 0)
        box = priority_score(POWER_SMALL_BATTERY, 100, False, 100)
        self.assertGreater(pi, box)

    def test_clamped_to_uint16_and_ranges(self):
        self.assertLessEqual(priority_score(9, 500, True, 500), 0xFFFF)
        self.assertEqual(priority_score(-1, -5, False, -3), 0)

    def test_beacon_interval(self):
        self.assertEqual(beacon_interval_ms("manual"), 30_000)
        self.assertEqual(beacon_interval_ms("auto"), 10_000)

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            Election(1, 100, mode="sometimes")


class AutoElectionTests(unittest.TestCase):
    def setUp(self):
        self.e = Election(5, priority=1000, mode="auto")
        self.e.follow(0)
        self.e.on_time(1, source=0, now_ms=0)

    def test_heartbeats_keep_a_follower_quiet(self):
        for t in range(10_000, 200_000, 10_000):
            self.assertTrue(self.e.on_time(1, source=0, now_ms=t))
            self.assertIsNone(self.e.tick(t + 1))
        self.assertEqual(self.e.role, FOLLOWER)

    def test_three_missed_beacons_start_a_claim(self):
        self.assertIsNone(self.e.tick(29_999))
        claim = self.e.tick(30_000)
        self.assertIsNotNone(claim)
        self.assertEqual((claim.term, claim.priority, claim.node_id), (2, 1000, 5))
        self.assertEqual(self.e.role, CANDIDATE)

    def test_unopposed_candidate_leads_after_the_timeout(self):
        self.e.tick(30_000)
        self.e.tick(34_999)
        self.assertEqual(self.e.role, CANDIDATE)
        self.e.tick(35_000)
        self.assertEqual(self.e.role, LEADER)
        self.assertEqual(self.e.term, 2)

    def test_better_claim_wins(self):
        self.e.tick(30_000)
        self.e.on_claim(2, priority=2000, node_id=9, now_ms=30_100)
        self.assertEqual(self.e.role, FOLLOWER)
        self.e.tick(40_000)
        self.assertEqual(self.e.role, FOLLOWER)  # waits for the winner's TIME

    def test_worse_claim_is_ignored(self):
        self.e.tick(30_000)
        self.e.on_claim(2, priority=500, node_id=1, now_ms=30_100)
        self.assertEqual(self.e.role, CANDIDATE)
        self.e.tick(35_000)
        self.assertEqual(self.e.role, LEADER)

    def test_equal_priority_lowest_node_id_wins(self):
        self.e.tick(30_000)
        self.e.on_claim(2, priority=1000, node_id=7, now_ms=30_100)
        self.assertEqual(self.e.role, CANDIDATE)  # 5 < 7
        self.e.on_claim(2, priority=1000, node_id=3, now_ms=30_200)
        self.assertEqual(self.e.role, FOLLOWER)  # 3 < 5

    def test_higher_term_beats_priority(self):
        self.e.tick(30_000)
        self.e.on_claim(3, priority=1, node_id=99, now_ms=30_100)
        self.assertEqual(self.e.role, FOLLOWER)
        self.assertEqual(self.e.term, 3)

    def test_leader_steps_down_on_a_higher_term(self):
        self.e.tick(30_000)
        self.e.tick(35_000)
        self.assertTrue(self.e.is_leader)
        self.assertFalse(self.e.on_time(1, source=0, now_ms=36_000))  # the old controller: ignored
        self.assertTrue(self.e.is_leader)
        self.assertTrue(self.e.on_time(3, source=8, now_ms=37_000))
        self.assertEqual(self.e.role, FOLLOWER)
        self.assertEqual(self.e.leader, 8)

    def test_stale_claim_is_ignored(self):
        self.e.on_claim(1, priority=60_000, node_id=0, now_ms=1000)
        self.assertEqual(self.e.term, 1)
        self.assertEqual(self.e.role, FOLLOWER)

    def test_history_records_role_changes(self):
        self.e.tick(30_000)
        self.e.tick(35_000)
        roles = [role for _, role, _ in self.e.history]
        self.assertEqual(roles[-2:], [CANDIDATE, LEADER])


class ManualElectionTests(unittest.TestCase):
    def test_manual_mode_never_claims_on_its_own(self):
        e = Election(5, priority=1000, mode="manual")
        e.follow(0)
        for t in range(0, 600_000, 1000):
            self.assertIsNone(e.tick(t))
        self.assertEqual(e.role, FOLLOWER)

    def test_promote(self):
        e = Election(5, priority=1000, mode="manual")
        e.follow(0)
        e.on_time(4, source=0, now_ms=0)
        claim = e.promote(1000)
        self.assertEqual(claim.term, 5)
        e.tick(6000)
        self.assertTrue(e.is_leader)

    def test_incapable_node_cannot_be_promoted(self):
        e = Election(5, priority=0, capable=False)
        with self.assertRaises(ValueError):
            e.promote(0)

    def test_two_leaders_same_term_resolve_by_node_id(self):
        a = Election(2, priority=100)
        a.lead(7, 0)
        self.assertFalse(a.on_time(7, source=4, now_ms=10))  # higher id: a keeps the role
        self.assertTrue(a.is_leader)
        b = Election(4, priority=100)
        b.lead(7, 0)
        self.assertTrue(b.on_time(7, source=2, now_ms=10))  # lower id: b yields
        self.assertEqual(b.role, FOLLOWER)


if __name__ == "__main__":
    unittest.main()
