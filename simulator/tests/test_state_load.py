# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
"""The air time of a state change, a channel change and a sweep (atalaia_sim/state_load.py; RFC 0001 Amendment 19,
decisions RB-4, RB-6 and RB-8): the frames' sizes against the real codecs, the repeats' schedule in the relay
study's engine, and the hourly totals against each EU868 sub-band's limit.

    cd simulator && python -m unittest tests.test_state_load
"""

from __future__ import annotations

import unittest
from dataclasses import replace

from atalaia_sim import field_frame, lobby, regions, state_load
from atalaia_sim.field_controller import STATE_REPEAT_GAPS_MS
from atalaia_sim.relay_study import CONTROLLER, FIRMWARE, Engine, Layout
from atalaia_sim.relay_traces import Trace

EU = regions.get("eu868")


def _mesh(n: int) -> Layout:
    return Layout("mesh", n, [[0.0 if i == j else -80.0 for j in range(n + 1)] for i in range(n + 1)])


def _empty(n: int, minutes: int) -> Trace:
    t = Trace("domination", n, minutes, 3)
    t.events = []
    return t.finish()


def _controller_frames(changes, minutes=3, gaps=STATE_REPEAT_GAPS_MS, n=4):
    """[(ms after the game's start, ptype)] of what the controller sends (relay copies are not counted)."""
    eng = Engine(_mesh(n), _empty(n, minutes), "eu868", replace(FIRMWARE, time_repeat_gaps_ms=gaps), seed=1,
                 ideal_channel=True, state_changes=changes)
    sent: list[tuple[int, str]] = []
    begin = eng.chan.begin

    def spy(tx):
        if tx.sender == CONTROLLER and tx.frame.ptype in ("TIME", "CMD"):
            sent.append((round((tx.start - 30_000_000) / 1000), tx.frame.ptype))
        return begin(tx)

    eng.chan.begin = spy  # type: ignore[method-assign]
    eng.run()
    return eng, sent


class FrameSizeTests(unittest.TestCase):
    def test_a_move_is_45_bytes_as_the_codec_makes_it(self):
        key = field_frame.field_key(bytes(range(32)))
        pkt = field_frame.encode(key, {"kind": "move", "channel_hz": 869_525_000, "rev": 1_790_000_000}, bytes(13))
        self.assertEqual(len(pkt), state_load.MOVE_BYTES)

    def test_the_rfcs_figures_hold(self):
        move = state_load.move_cost_ms(4)
        self.assertAlmostEqual(move["channel_change"], 277, delta=2)  # "0.27 s of air"
        self.assertAlmostEqual(move["sweep"] / 4, 185, delta=2)  # "0.18 s per remembered channel"
        change = state_load.state_change_air_ms()
        self.assertAlmostEqual(change["time_repeats"], 329, delta=3)  # "four more frames, 0.36 s" (at 90 ms: 82 ms)
        self.assertLess(change["time_repeats"], 360)
        self.assertEqual(lobby.MOVE_REPEATS, 3)
        self.assertEqual(lobby.SWEEP_REPEATS, 2)

    def test_the_gaps_are_the_ones_the_controller_uses(self):
        self.assertEqual(STATE_REPEAT_GAPS_MS, (1000, 1500, 2500, 5000))  # +1, +2.5, +5, +10 s


class RepeatScheduleTests(unittest.TestCase):
    def test_a_start_is_a_cmd_and_a_time_then_four_times_at_the_built_gaps(self):
        eng, sent = _controller_frames([(0, "start")], minutes=1)
        times = [t for t, p in sent if p == "TIME"]
        self.assertEqual([p for t, p in sent if t < 100], ["CMD", "TIME"])
        repeats = [t for t in times if 500 < t < 20_000]
        for got, want in zip(repeats, (1000, 2500, 5000, 10_000)):
            self.assertAlmostEqual(got, want, delta=250)  # the clock's drift, the queue and the radio loop
        self.assertEqual(len(repeats), 4)
        self.assertEqual(eng.ctl.time_repeats_sent, 4)

    def test_the_30_s_beacon_goes_on_from_the_last_repeat(self):
        _, sent = _controller_frames([(0, "start")], minutes=1)
        later = [t for t, p in sent if p == "TIME" and t > 20_000]
        self.assertAlmostEqual(later[0], 10_000 + 30_000, delta=300)

    def test_a_new_change_replaces_the_repeats_still_due(self):
        eng, sent = _controller_frames([(0, "start"), (1_200, "pause")], minutes=1)
        self.assertEqual(eng.ctl.time_repeats_sent, 1 + 4)  # the start's first repeat (+1.0 s), then the pause's four
        self.assertEqual(eng.ctl.state_changes_sent, 2)

    def test_no_repeats_is_the_controller_as_before(self):
        eng, sent = _controller_frames([(0, "start"), (60_000, "pause"), (120_000, "resume")], minutes=3, gaps=())
        self.assertEqual(eng.ctl.time_repeats_sent, 0)
        self.assertEqual(sum(1 for _, p in sent if p == "CMD"), 3)

    def test_without_state_changes_nothing_new_is_sent(self):
        eng = Engine(_mesh(4), _empty(4, 2), "eu868", FIRMWARE, seed=1, ideal_channel=True)
        eng.run()
        self.assertEqual((eng.ctl.state_changes_sent, eng.ctl.time_repeats_sent), (0, 0))

    def test_every_repeat_is_relayed_like_any_time(self):
        """In a mesh of 5 (at most 3 neighbours: probability 1 under Amendment 13 on the model's rules) each box
        relays each TIME once: the controller's 5 TIMEs of a start are 5 x 4 relays."""
        eng, sent = _controller_frames([(0, "start")], minutes=1, n=3)
        relayed = sum(b.stats.air_ptype.get("TIME", 0) for b in eng.nodes[1:])
        one = int(round(state_load.frame_ms(state_load.TIME_BYTES) * 1000))
        self.assertGreaterEqual(relayed / one, 3 * 5)  # at least the start's 5 frames, 3 boxes


class HourlyLimitTests(unittest.TestCase):
    """The numbers of decisions RL-1 to RL-6 in arithmetic: what a typical game's state changes add to the
    controller's own air against each sub-band's budget (a box adds less: it relays with probability 3/n)."""

    def test_a_typical_game_is_seven_state_changes_an_hour(self):
        self.assertEqual(len(state_load.typical_game(60, 3)), 7)

    def test_the_controller_stays_inside_every_budget_it_met_before(self):
        per_change = state_load.state_change_air_ms()["total"] / 1000
        gain = state_load.per_hour(7, per_change)
        self.assertLess(gain["air_s"], 4.0)
        self.assertLess(gain["pct_of_10%"], 1.2)  # of the default sub-band's 360 s
        self.assertLess(gain["pct_of_1%"], 12.0)  # of a 1 % one's 36 s
        # a 0.1 % sub-band (not recommended; 3.6 s an hour) is nearly spent by these frames alone
        self.assertGreater(gain["pct_of_0.1%"], 50.0)

    def test_the_old_controller_costs_a_cmd_and_a_time(self):
        c = state_load.state_change_air_ms()
        self.assertAlmostEqual(c["before_amendment_19"], c["cmd"] + c["time_first"])
        self.assertLess(c["before_amendment_19"] / c["total"], 0.35)


if __name__ == "__main__":
    unittest.main()
