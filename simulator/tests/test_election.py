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
        # A leader on auto, heard beaconing every 10 s (the first TIME's gap is no evidence, then three
        # steady gaps: decisions FAIL-1 to FAIL-3), the last one at 0.
        self.e = Election(5, priority=1000, mode="auto")
        self.e.follow(-40_000)
        for t in range(-40_000, 1, 10_000):
            self.e.on_time(1, source=0, now_ms=t, game_state=1)
        self.assertEqual(self.e.leader_beacon_ms, 10_000)

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


RUNNING, PAUSED = 1, 2
REPEATS_MS = (1_000, 2_500, 5_000, 10_000)  # Amendment 19: the TIMEs after a state change


class MixedModeTests(unittest.TestCase):
    """A standby on auto behind a leader on manual (decisions FAIL-1 to FAIL-6): it counted its own 10 s
    beacons and took a working controller over after one of the leader's 30 s gaps."""

    def run_beacons(self, e, times, states=None, until=None):
        """Feeds the leader's TIMEs at ``times`` and ticks every 100 ms; returns the first CLAIM's time."""
        beacons = dict(zip(times, states or [RUNNING] * len(times)))
        end = until if until is not None else max(times)
        for t in range(0, end + 1, 100):
            if t in beacons:
                e.on_time(1, source=0, now_ms=t, game_state=beacons[t])
            if e.tick(t) is not None:
                return t
        return None

    def test_an_auto_standby_never_takes_over_a_working_manual_leader(self):
        e = Election(5, priority=1000, mode="auto")
        e.follow(0)
        claimed = self.run_beacons(e, list(range(0, 600_001, 30_000)))
        self.assertIsNone(claimed)  # before the fix: a claim 30 s after the first beacon
        self.assertEqual(e.role, FOLLOWER)
        self.assertEqual(e.leader_beacon_ms, 30_000)
        self.assertEqual(e.leader_failover_mode, "manual")
        self.assertEqual(e.takeover_after_ms, 90_000)

    def test_a_late_manual_beacon_is_not_three_missed_ones(self):
        # The leader's tick or the channel delays a beacon by 200 ms: before the fix the standby had
        # counted three 10 s beacons by then and claimed (no game state given here, as an older caller).
        e = Election(5, priority=1000, mode="auto")
        e.follow(0)
        for i in range(20):
            e.on_time(1, source=0, now_ms=i * 30_200)
            for t in range(i * 30_200, (i + 1) * 30_200, 100):
                self.assertIsNone(e.tick(t), f"a claim at {t} ms")
        self.assertEqual(e.leader_failover_mode, "manual")

    def test_it_takes_over_when_the_manual_leader_falls_silent(self):
        e = Election(5, priority=1000, mode="auto")
        e.follow(0)
        claimed = self.run_beacons(e, list(range(0, 120_001, 30_000)), until=400_000)
        self.assertEqual(claimed, 120_000 + 90_000)  # three missed 30 s beacons

    def test_a_state_change_repeated_as_time_is_not_taken_for_auto(self):
        # A manual leader that pauses and resumes: each change is a TIME and four repeats in 10 s, and
        # the 30 s beacon goes on from the last repeat. The short gaps are no evidence of 10 s beacons.
        e = Election(5, priority=1000, mode="auto")
        e.follow(0)
        times, states = [0, 30_000], [RUNNING, RUNNING]
        state, t = RUNNING, 30_000
        for change_after in (10_000, 10_000, 12_000, 9_000, 10_000):
            t += change_after
            state = PAUSED if state == RUNNING else RUNNING
            burst = [t] + [t + r for r in REPEATS_MS]
            times += burst
            states += [state] * len(burst)
            t = burst[-1]
        for _ in range(4):
            t += 30_000
            times.append(t)
            states.append(state)
        claimed = self.run_beacons(e, times, states)
        self.assertIsNone(claimed)
        self.assertNotEqual(e.leader_beacon_ms, 10_000)

    def test_a_manual_standby_sees_an_auto_leader_and_still_waits_for_the_gm(self):
        e = Election(5, priority=1000, mode="manual")
        e.follow(0)
        self.assertIsNone(self.run_beacons(e, list(range(0, 100_001, 10_000)), until=600_000))
        self.assertEqual(e.leader_failover_mode, "auto")
        self.assertIsNone(e.takeover_after_ms)

    def test_until_the_leader_is_heard_the_slowest_interval_counts(self):
        e = Election(5, priority=1000, mode="auto")
        e.follow(0)
        self.assertIsNone(e.leader_beacon_ms)
        self.assertEqual(e.takeover_after_ms, 90_000)
        self.assertIsNone(e.tick(89_999))
        self.assertIsNotNone(e.tick(90_000))

    def test_an_auto_leader_is_learned_and_a_lost_beacon_keeps_it(self):
        e = Election(5, priority=1000, mode="auto")
        e.follow(0)
        # 0 opens the first window (no evidence), 10 s is inside it, then 20, 30, 40: three steady gaps.
        self.assertIsNone(self.run_beacons(e, [0, 10_000, 20_000, 30_000]))
        self.assertIsNone(e.leader_beacon_ms)
        self.assertIsNone(self.run_beacons(e, [40_000]))
        self.assertEqual(e.leader_beacon_ms, 10_000)
        e.on_time(1, source=0, now_ms=60_000, game_state=RUNNING)  # 50 s was lost
        self.assertEqual(e.leader_beacon_ms, 10_000)
        self.assertIsNone(e.tick(89_999))
        self.assertIsNotNone(e.tick(90_000))  # three missed 10 s beacons

    def test_two_lost_beacons_forget_the_auto_cadence(self):
        e = Election(5, priority=1000, mode="auto")
        e.follow(0)
        self.run_beacons(e, [0, 10_000, 20_000, 30_000, 40_000])
        self.assertEqual(e.leader_beacon_ms, 10_000)
        e.on_time(1, source=0, now_ms=70_000, game_state=RUNNING)
        self.assertIsNone(e.leader_beacon_ms)
        self.assertEqual(e.takeover_after_ms, 90_000)

    def test_a_new_leader_or_term_is_measured_afresh(self):
        e = Election(5, priority=1000, mode="auto")
        e.follow(0)
        self.run_beacons(e, [0, 10_000, 20_000, 30_000, 40_000])
        self.assertEqual(e.leader_beacon_ms, 10_000)
        e.on_time(2, source=7, now_ms=45_000, game_state=RUNNING)
        self.assertIsNone(e.leader_beacon_ms)
        self.assertEqual(e.takeover_after_ms, 90_000)


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
