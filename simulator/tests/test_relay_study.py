# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The relay study's harness (atalaia_sim/relay_study.py): its model of the firmware's relay rules,
duty-cycle accounting and channel, checked against the rules it ports, and short runs of the
whole thing. The numbers of decisions SL-7 to SL-20 come from long runs of this code
(``python -m atalaia_sim.relay_study``); these tests keep it honest.

    cd simulator && python -m unittest tests.test_relay_study
"""

from __future__ import annotations

import os
import unittest

from atalaia_sim import regions, relay_report
from atalaia_sim.core import find_library
from atalaia_sim.field_controller import AckTracker
from atalaia_sim.relay_study import (
    CONTROLLER, DEDUPE, FIRMWARE, LAYOUTS, POLICIES, Box, CoreDutyCycle, Engine, Frame,
    GapSkippingAckTracker, Layout, Tx, air_us, flood_jitter_ms, layout_all_in_range, layout_long, run_matrix, run_one,
    should_relay, state_frame_bytes,
)
from atalaia_sim.relay_traces import Trace, TraceEvent


def _lib():
    try:
        return str(find_library())
    except (FileNotFoundError, OSError):
        if os.environ.get("ATALAIA_REQUIRE_ALL") == "1":
            raise
        return None


LIB = _lib()
EU, TW = regions.get("eu868"), regions.get("as923-tw")


def _empty(n: int, minutes: int = 5, teams: int = 3, events: list[TraceEvent] | None = None) -> Trace:
    t = Trace("domination", n, minutes, teams)
    t.events = events or []
    return t.finish()


def _chain(n: int) -> Layout:
    """Controller - b1 - b2 - ... - bn: every box hears only its neighbours."""
    size = n + 1
    rssi = [[-150.0] * size for _ in range(size)]
    for i in range(size - 1):
        rssi[i][i + 1] = rssi[i + 1][i] = -80.0
    for i in range(size):
        rssi[i][i] = 0.0
    return Layout("chain", n, rssi)


def _mesh(n: int, level: float = -80.0) -> Layout:
    rssi = [[0.0 if i == j else level for j in range(n + 1)] for i in range(n + 1)]
    return Layout("mesh", n, rssi)


class FirmwareRulesTests(unittest.TestCase):
    def test_jitter_is_the_cores_fnv_value(self):
        # printed by core/src/flood.c's atalaia_flood_jitter_ms (gcc, tests/ vectors made once by hand)
        known = {(7, 1): 48, (7, 78): 42, (7, 155): 35, (1007, 1): 24, (1007, 78): 49, (1007, 155): 18,
                 (2007, 1): 19, (2007, 78): 15, (2007, 155): 17}
        for (src, seq), ms in known.items():
            self.assertEqual(flood_jitter_ms(src, seq), ms, (src, seq))

    def test_every_box_that_hears_a_frame_picks_the_same_jitter(self):
        """The jitter is a function of (source, seq) only: all relayers go at the same moment."""
        self.assertEqual({flood_jitter_ms(9, 4) for _ in range(20)}, {flood_jitter_ms(9, 4)})

    def test_hop_limit_rule(self):
        self.assertEqual(should_relay(2, 2), 1)
        self.assertEqual(should_relay(1, 2), 0)  # relayed with hop_limit 0: the last hop
        self.assertIsNone(should_relay(0, 2))
        self.assertEqual(should_relay(7, 2), 1)  # clamped to the game's max_hops

    def test_state_size_and_airtime_are_sl4s(self):
        self.assertEqual(state_frame_bytes(3), 52)
        self.assertEqual((state_frame_bytes(2), state_frame_bytes(4)), (48, 56))
        self.assertAlmostEqual(air_us(EU, 52) / 1000, 102.7, delta=0.1)
        self.assertAlmostEqual(air_us(TW, 52) / 1000, 82.2, delta=0.1)

    def test_duty_cycle_budget_window_and_refusal(self):
        dc = CoreDutyCycle(100_000)  # 10 %
        self.assertEqual(dc.budget_us, 360_000_000)
        for minute in range(60):
            dc.record(6_000_000, minute * 60_000)  # 6 s every minute: exactly 10 %
        self.assertEqual(dc.used_us, 360_000_000)
        self.assertFalse(dc.can_send(1, 59 * 60_000 + 30_000))  # not even one more microsecond
        self.assertTrue(dc.can_send(6_000_000, 60 * 60_000))  # the first minute left the window
        self.assertEqual(dc.used_us, 354_000_000)

    def test_dedupe_is_a_64_entry_fifo_with_a_30_s_life(self):
        eng = Engine(_mesh(2), _empty(2), "eu868", FIRMWARE)
        box: Box = eng.nodes[1]  # type: ignore[assignment]
        for i in range(DEDUPE):
            self.assertFalse(box.seen_before((5, i), 1000 + i))
        self.assertTrue(box.seen_before((5, 0), 1100))
        self.assertFalse(box.seen_before((5, DEDUPE), 1200))  # the 65th evicts the oldest ...
        self.assertEqual(box.stats.dedupe_evictions, 1)
        self.assertFalse(box.seen_before((5, 0), 1300))  # ... which is then processed again
        self.assertEqual(box.stats.dup_after_evict, 1)
        self.assertFalse(box.seen_before((6, 0), 40_000))  # 30 s later everything has expired
        self.assertFalse(box.seen_before((5, 3), 40_100))


def _covers(payload: dict, seq: int) -> bool:
    contig = -1 if payload["ack_seq"] == 0xFFFF else payload["ack_seq"]
    bits = payload.get("ack_bitmap", b"")
    n = seq - contig - 1
    return seq <= contig or (0 <= n < 8 * len(bits) and bool((bits[n // 8] >> (n % 8)) & 1))


class AckWindowTests(unittest.TestCase):
    """SL-8: one packet lost for good stops a box's ACKs 256 packets later."""

    def _fed(self, tracker):
        for seq in list(range(0, 6)) + list(range(7, 300)):  # seq 6 never arrives
            tracker.record(5, 0, seq)
        return tracker.ack_payload(5, 0)

    def test_the_shipped_tracker_acknowledges_past_a_hole(self):
        # Before SL-8 was built (2026-10-26) the shipped tracker stayed at the hole (ack_seq 5) and could not
        # cover 299, 256 numbers past it; now it skips a hole older than 128 as the study's model does.
        payload = self._fed(AckTracker())
        self.assertTrue(all(_covers(payload, s) for s in (200, 290, 299)))
        self.assertEqual(payload, self._fed(GapSkippingAckTracker(128)))

    def test_skipping_a_hole_keeps_the_newest_packets_covered(self):
        payload = self._fed(GapSkippingAckTracker(128))
        self.assertTrue(all(_covers(payload, s) for s in (200, 290, 299)))
        self.assertGreaterEqual(payload["ack_seq"], 299 - 128)

    def test_a_recent_hole_is_kept(self):
        t = GapSkippingAckTracker(128)
        for seq in (0, 1, 2, 4, 5):
            t.record(1, 0, seq)
        payload = t.ack_payload(1, 0)
        self.assertEqual(payload["ack_seq"], 2)
        self.assertFalse(_covers(payload, 3))  # 3 may still arrive: not claimed


class ChannelTests(unittest.TestCase):
    def _chan(self, rssi_rows):
        n = len(rssi_rows) - 1
        lay = Layout("t", n, [[float(x) for x in row] for row in rssi_rows])
        eng = Engine(lay, _empty(n), "eu868", FIRMWARE)
        got: list[tuple[int, int]] = []
        eng.deliver = lambda r, f, t: got.append((r, f.src))  # type: ignore[assignment]
        return eng, got

    @staticmethod
    def _tx(eng, sender, src, start, end):
        f = Frame(src, 1, "STATE", 52, False, 2, ("state", src, 0), start)
        tx = Tx(sender, f, start, end)
        eng.chan.begin(tx)
        return tx

    def test_overlapping_equal_frames_are_both_lost_and_a_10_db_stronger_one_survives(self):
        # receiver 3 hears boxes 1 and 2 equally; receiver 0 hears 1 loudly and 2 faintly
        rows = [[0, -60, -85, -80],
                [-60, 0, -80, -80],
                [-85, -80, 0, -80],
                [-80, -80, -80, 0]]
        eng, got = self._chan(rows)
        a = self._tx(eng, 1, 1, 0, 100_000)
        b = self._tx(eng, 2, 2, 20_000, 120_000)
        eng.chan.finish(a)
        eng.chan.finish(b)
        self.assertNotIn((3, 1), got)  # equal power at 3: collision
        self.assertNotIn((3, 2), got)
        self.assertIn((0, 1), got)  # at the controller box 1 is 25 dB above box 2: it is captured
        self.assertNotIn((0, 2), got)
        self.assertGreaterEqual(eng.nodes[3].stats.rx_collided, 2)

    def test_a_radio_does_not_hear_while_it_transmits(self):
        eng, got = self._chan([[0, -70, -70], [-70, 0, -70], [-70, -70, 0]])
        a = self._tx(eng, 1, 1, 0, 100_000)
        b = self._tx(eng, 2, 2, 50_000, 150_000)  # 2 starts talking in the middle of 1's frame
        eng.chan.finish(a)
        self.assertNotIn((2, 1), got)
        self.assertEqual(eng.nodes[2].stats.rx_halfduplex, 1)

    def test_ideal_channel_has_no_collisions(self):
        n = 3
        lay = _mesh(n)
        eng = Engine(lay, _empty(n), "eu868", FIRMWARE, ideal_channel=True)
        got: list[tuple[int, int]] = []
        eng.deliver = lambda r, f, t: got.append((r, f.src))  # type: ignore[assignment]
        a = self._tx(eng, 1, 1, 0, 100_000)
        b = self._tx(eng, 2, 2, 10_000, 110_000)
        eng.chan.finish(a)
        eng.chan.finish(b)
        self.assertIn((3, 1), got)
        self.assertIn((3, 2), got)


class RelayBehaviourTests(unittest.TestCase):
    def test_a_frame_is_relayed_at_most_twice_so_a_chain_reaches_three_hops(self):
        """Controller - b1 - b2 - b3 - b4: hop_limit 2 reaches b3's HELLO (3 hops), never b4's."""
        eng = Engine(_chain(4), _empty(4, 4), "eu868", FIRMWARE, seed=3)
        eng.run()
        heard = {src for (src, _seq) in eng.ctl.heard}
        self.assertTrue({1, 2, 3} <= heard)
        self.assertNotIn(4, heard)
        self.assertEqual(eng.layout.reach()["unreachable"], 1)

    def test_in_a_full_mesh_every_box_relays_every_frame_once(self):
        """SL-4's assumption, on an ideal channel: a box's frame is relayed by the N-1 other boxes,
        the controller's (it never relays itself) by all N."""
        n = 5
        eng = Engine(_mesh(n), _empty(n, 6), "eu868", FIRMWARE, seed=1, ideal_channel=True)
        origin = {"box": 0, "controller": 0}
        begin = eng.chan.begin

        def counting(tx):
            if tx.frame.hop == 2:  # not a relay copy
                origin["controller" if tx.sender == CONTROLLER else "box"] += 1
            begin(tx)

        eng.chan.begin = counting  # type: ignore[assignment]
        res = eng.run()
        expected = (n - 1) * origin["box"] + n * origin["controller"]
        self.assertGreater(origin["box"], 40)
        self.assertAlmostEqual(res["relays_sent"], expected, delta=0.02 * expected + n)

    def test_the_controller_never_relays_and_acks_each_event(self):
        ev = [TraceEvent(40_000, 0, "zone.captured", "normal", 30)]
        eng = Engine(_mesh(3), _empty(3, 3, events=ev), "eu868", FIRMWARE, seed=2, ideal_channel=True)
        res = eng.run()
        self.assertEqual(eng.ctl.stats.relayed, 0)
        self.assertEqual(res["events"]["captures"]["delivered_pct"], 100.0)
        self.assertEqual(res["events"]["captures"]["acked_pct"], 100.0)
        self.assertEqual(res["events"]["captures"]["mean_transmissions"], 1.0)

    def test_a_frame_over_the_budget_is_dropped_not_delayed(self):
        eng = Engine(_mesh(2), _empty(2, 2), "eu868", FIRMWARE, seed=1, ideal_channel=True)
        box: Box = eng.nodes[1]  # type: ignore[assignment]
        box.dc.tick(0)
        box.dc.used_us = box.dc.budget_us  # spent
        box.dc.buckets[box.dc.current] = box.dc.budget_us
        sent_before = sum(box.stats.air_us.values())
        eng.at(31_000_000, lambda t: box.enqueue(box.state_frame(t), "own_state", t))
        eng.run()
        self.assertGreaterEqual(box.stats.dc_dropped.get("own_state", 0), 1)
        self.assertEqual(sum(box.stats.air_us.values()), sent_before)  # nothing left the antenna
        self.assertEqual(len(box.txq), 0)  # and nothing is queued for later

    def test_the_relay_table_has_four_slots_and_the_transmit_queue_eight(self):
        eng = Engine(_mesh(2), _empty(2), "eu868", FIRMWARE)
        box: Box = eng.nodes[1]  # type: ignore[assignment]
        for i in range(10):
            box.on_rx(Frame(2, i, "STATE", 52, False, 2, ("state", 2, i), 0), 1_000_000 + i)
        self.assertEqual(len(box.pending), 4)
        self.assertEqual(box.stats.relay_slot_dropped, 6)
        for i in range(10):
            box.enqueue(Frame(1, i, "STATE", 52, False, 2, ("state", 1, i), 0), "own_state", 2_000_000)
        self.assertEqual(len(box.txq), 8)
        self.assertEqual(box.stats.queue_dropped["own_state"], 2)

    def test_overheard_ack_cancels_the_relay_of_an_event(self):
        """With ack_gated, a box that hears the controller's ACK first does not relay the event."""
        ev = [TraceEvent(40_000, 0, "zone.captured", "normal", 30)]

        def relays(policy: str) -> int:
            eng = Engine(_mesh(4), _empty(4, 3, events=ev), "eu868", POLICIES[policy], seed=2, ideal_channel=True)
            eng.run()
            return sum(1 for e in eng.events if e.type == "zone.captured") and sum(
                b.stats.relay_cancelled for b in eng.nodes[1:])  # type: ignore[attr-defined]

        self.assertEqual(relays("firmware"), 0)
        self.assertGreater(relays("ack_gated"), 0)

    def test_a_better_rule_uses_less_air_in_a_dense_field(self):
        res = {p: run_one("domination", 12, "all_in_range", "eu868", p, 8, 1, LIB, trace=_empty(12, 8))
               for p in ("firmware", "A_relay")}
        self.assertLess(res["A_relay"]["airtime_pct"]["mean"], res["firmware"]["airtime_pct"]["mean"] * 0.7)
        self.assertLess(res["A_relay"]["relays_sent"], res["firmware"]["relays_sent"] * 0.6)

    def test_retries_back_off_when_asked(self):
        """An event nobody can ACK is resent every 3 s today, at 3, 6, 12, 24, 30 ... s with the backoff."""
        ev = [TraceEvent(1_000, 0, "zone.captured", "critical", 30)]
        lay = _mesh(2)
        lay.rssi[0][1] = lay.rssi[1][0] = -150.0  # the controller cannot hear box 1, nor box 1 it
        lay.rssi[0][2] = lay.rssi[2][0] = -150.0

        def resends(policy: str) -> int:
            eng = Engine(lay, _empty(2, 5, events=ev), "eu868", POLICIES[policy], seed=1)
            eng.run()
            return next(e.tx_count for e in eng.events if e.type == "zone.captured")

        self.assertGreater(resends("firmware"), 80)  # five minutes at one a 3 s
        self.assertLess(resends("backoff"), 20)

    def test_the_run_is_deterministic_per_seed(self):
        a = run_one("domination", 8, "cqb", "eu868", "firmware", 4, 5, LIB, trace=_empty(8, 4))
        b = run_one("domination", 8, "cqb", "eu868", "firmware", 4, 5, LIB, trace=_empty(8, 4))
        c = run_one("domination", 8, "cqb", "eu868", "firmware", 4, 6, LIB, trace=_empty(8, 4))
        self.assertEqual(a, b)
        self.assertNotEqual(a["airtime_pct"], c["airtime_pct"])

    def test_sl4_arithmetic_on_an_ideal_channel(self):
        """N=10 in full view of each other: SL-4 predicts 6.8 % per box on EU868 from STATEs and their
        relays; the model adds only the joins' HELLOs and the controller's ACKs and TIMEs."""
        tr = _empty(10, 30)
        eu = run_one("domination", 10, "all_in_range", "eu868", "firmware", 30, 1, LIB, ideal_channel=True, trace=tr)
        tw = run_one("domination", 10, "all_in_range", "as923-tw", "firmware", 30, 1, LIB, ideal_channel=True, trace=tr)
        self.assertGreater(eu["airtime_pct"]["last30_mean"], 6.5)
        self.assertLess(eu["airtime_pct"]["last30_mean"], 8.0)
        self.assertGreater(tw["airtime_pct"]["last30_mean"], 5.2)
        self.assertLess(tw["airtime_pct"]["last30_mean"], 6.5)


class LayoutTests(unittest.TestCase):
    def test_layouts_have_the_shape_they_claim(self):
        for n in (5, 20):
            lay = layout_all_in_range(n)
            self.assertEqual(lay.reach()["direct"], n)
            self.assertEqual(sum(len(h) for h in lay.hears()), (n + 1) * n)
        lay = LAYOUTS["cqb"](20, 1)
        self.assertEqual(lay.reach()["unreachable"], 0)
        self.assertLess(lay.reach()["neighbours_mean"], 19)  # walls: not everyone hears everyone

    def test_a_long_field_is_out_of_reach_of_the_default_hop_limit(self):
        """Three neighbours either side and the controller in the middle: 30 boxes need more than 3 hops."""
        self.assertGreater(layout_long(30, 1, k=3).reach()["unreachable"], 5)
        self.assertEqual(layout_long(30, 1).reach()["unreachable"], 0)  # the default picks a k that works

    def test_designated_relays_cover_every_box(self):
        lay = layout_long(20, 1)
        relays = lay.designated_relays()
        dist = lay.hop_distance()
        self.assertTrue(all(1 <= r <= lay.n for r in relays))
        self.assertTrue(all(dist[r] < max(dist) for r in relays))  # the outermost boxes are never relays


class ReportTests(unittest.TestCase):
    def test_tables_from_a_short_matrix(self):
        res = run_matrix(["domination"], [5], ["all_in_range"], ["eu868", "as923-tw"], ["firmware", "A_relay"], 3,
                         [1, 2], LIB, workers=1) if LIB else []
        if not res:
            self.skipTest("no core library")
        self.assertEqual(len(res), 8)
        text = relay_report.summary_table(res)
        self.assertIn("firmware", text)
        self.assertIn("A_relay", text)
        self.assertIn("as923-tw", relay_report.decision_tables(res))
        self.assertIn("air %", relay_report.per_box_table(res[0]))


@unittest.skipUnless(LIB, "the C core's shared library is not built")
class RealCoreTraceTests(unittest.TestCase):
    def test_domination_trace_comes_from_the_real_scripts(self):
        from atalaia_sim.relay_traces import domination_trace
        tr = domination_trace(6, 20, 1, LIB)
        self.assertGreater(len(tr.events), 3)
        self.assertTrue(all(e.type == "zone.captured" for e in tr.events))
        self.assertTrue(all(15 <= e.payload_len <= 40 for e in tr.events))
        self.assertTrue(all(0 <= e.box < 6 for e in tr.events))
        self.assertTrue(tr.owned)  # a captured zone is scoring

    def test_scenario_trace_has_events_and_setup_commands(self):
        from atalaia_sim.relay_traces import scenario_trace
        tr = scenario_trace(8, 10, 1, LIB)
        kinds = {e.type for e in tr.events}
        self.assertIn("zone.captured", kinds)
        self.assertIn("node.rebooted", kinds)
        self.assertGreaterEqual(len(tr.commands), 4)  # a setup command per objective box
        self.assertFalse(tr.scores)

    def test_state_changed_follows_owner_and_events(self):
        tr = Trace("domination", 2, 10, 3, owned={0: [(0, 600_000)]})
        tr.events = [TraceEvent(100_000, 1, "zone.captured", "normal", 30)]
        tr.finish()
        self.assertTrue(tr.changed(0, 0, 30_000))  # box 0 owns a zone: its counters move every tick
        self.assertTrue(tr.changed(1, 90_000, 110_000))  # box 1 captured one in the window
        self.assertFalse(tr.changed(1, 0, 90_000))  # and before that it was silent


if __name__ == "__main__":
    unittest.main()
