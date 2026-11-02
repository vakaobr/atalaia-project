# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""EU868 game channels (eu868.py): sub-band edges, limits, candidates, and the
radio model's duty cycle and power following the channel (RFC 0001 Amendment 3).

The channel rule is also checked against the C core (atalaia_channel_ok in
core/src/duty_cycle.c) over a sweep of frequencies, when the shared core is
built (always with ATALAIA_REQUIRE_ALL=1).
"""

from __future__ import annotations

import ctypes
import os
import random
import unittest

from atalaia_sim import eu868, join
from atalaia_sim.core import Core, find_library
from atalaia_sim.radio_model import RadioConfig, RadioModel


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        if os.environ.get("ATALAIA_REQUIRE_ALL") == "1":
            raise
        return None


CORE = _core()


class ChannelRuleTests(unittest.TestCase):
    def test_whole_channel_inside_a_sub_band(self):
        ok = [869_525_000, 868_100_000, 868_800_000, 869_850_000,
              869_462_500, 869_587_500, 868_062_500, 868_537_500,
              868_762_500, 869_137_500, 869_762_500, 869_937_500]
        bad = [869_400_000, 869_462_499, 869_587_501, 869_650_000, 868_000_000, 868_600_000,
               868_700_000, 869_200_000, 869_700_000, 870_000_000, 869_300_000, 868_650_000,
               915_000_000, 0, -1]
        for hz in ok:
            self.assertTrue(eu868.channel_ok(hz), hz)
            self.assertTrue(join.channel_ok(hz), hz)
        for hz in bad:
            self.assertFalse(eu868.channel_ok(hz), hz)
            self.assertFalse(join.channel_ok(hz), hz)
        self.assertFalse(eu868.channel_ok(869_525_000.0))  # not an integer
        self.assertFalse(eu868.channel_ok(True))
        self.assertEqual(eu868.band_of(869_412_500, 25_000).name, "g2")  # narrower fits closer
        self.assertIsNone(eu868.band_of(869_412_500))

    def test_limits(self):
        g2 = eu868.band_of(eu868.DEFAULT_CHANNEL_HZ)
        self.assertEqual((g2.name, g2.erc, g2.duty_pct, g2.erp_mw, g2.erp_dbm, g2.full_power),
                         ("g2", "h1.7", 10.0, 500, 27, True))
        self.assertEqual(g2.budget_ms_per_hour, 360_000)
        self.assertEqual(eu868.band_of(868_100_000).budget_ms_per_hour, 36_000)
        self.assertAlmostEqual(eu868.band_of(868_800_000).budget_ms_per_hour, 3_600)
        self.assertEqual(eu868.band_of(869_850_000).erp_mw, 25)

    def test_tx_power_matches_radio_power_h(self):
        # The same cases as firmware/esp32/test/test_radio_power.c.
        self.assertEqual(eu868.tx_power_dbm(14, 14, 2), 0)
        self.assertEqual(eu868.tx_power_dbm(27, 14, 2), 13)
        self.assertEqual(eu868.tx_power_dbm(14, 0, 2), 14)
        self.assertEqual(eu868.tx_power_dbm(14, 14, 6), -4)  # -3.85 rounded down, never up
        self.assertEqual(eu868.tx_power_dbm(14, 14, 10), -8)  # a 10 dBi whip on a 25 mW sub-band (-7.85)
        self.assertEqual(eu868.tx_power_dbm(27, 14, 10), 5)  # and on 869.4-869.65 MHz (5.15)
        self.assertEqual(eu868.tx_power_dbm(14, 30, 5), -9)
        self.assertEqual(eu868.tx_power_dbm(27, 0, 0), 22)

    def test_airtime_matches_the_core(self):
        self.assertAlmostEqual(eu868.airtime_ms(47), 92.416)  # test_radio_limits.c
        self.assertGreater(eu868.airtime_ms(217), eu868.airtime_ms(47))

    def test_candidates(self):
        self.assertEqual(len(set(eu868.CANDIDATES)), len(eu868.CANDIDATES))
        for hz in eu868.CANDIDATES:
            band = eu868.band_of(hz)
            self.assertIsNotNone(band, hz)
            # at least 12.5 kHz between the channel and the sub-band's edges (decision CH1)
            self.assertGreaterEqual(hz - 62_500 - band.lo_hz, 12_500, hz)
            self.assertGreaterEqual(band.hi_hz - hz - 62_500, 12_500, hz)
        scan = eu868.scan_candidates()
        self.assertIn(eu868.DEFAULT_CHANNEL_HZ, scan)
        self.assertTrue(all(eu868.band_of(hz).name != "g1" for hz in scan))
        self.assertEqual(len(scan), 11)
        self.assertEqual({eu868.band_of(hz).name for hz in eu868.CANDIDATES}, {"g", "g1", "g2", "g3"})

    def test_describe(self):
        d = eu868.describe(869_525_000)
        self.assertEqual((d["band"], d["duty_pct"], d["erp_mw"], d["full_power"], d["usable"]),
                         ("g2", 10.0, 500, True, True))
        self.assertEqual(d["notes"], ["default"])
        self.assertIn("lorawan_default", eu868.describe(868_100_000)["notes"])
        g1 = eu868.describe(868_950_000)
        self.assertEqual((g1["duty_pct"], g1["usable"], g1["notes"]), (0.1, False, ["low_airtime"]))
        with self.assertRaises(ValueError):
            eu868.describe(869_650_000)


@unittest.skipIf(CORE is None, "the shared core library is not built")
class SameRuleAsTheCoreTests(unittest.TestCase):
    def test_sweep(self):
        fn = CORE.lib.atalaia_channel_ok
        fn.argtypes = [ctypes.c_uint32]
        fn.restype = ctypes.c_bool
        rng = random.Random(7)
        points = set(range(867_900_000, 870_100_001, 12_500))
        for band in eu868.SUB_BANDS:
            for edge in (band.lo_hz, band.hi_hz):
                for d in (-62_501, -62_500, -62_499, 62_499, 62_500, 62_501):
                    points.add(edge + d)
        points.update(rng.randrange(867_000_000, 871_000_000) for _ in range(2000))
        for hz in sorted(points):
            self.assertEqual(bool(fn(hz)), eu868.channel_ok(hz), hz)


class RadioModelLimitsTests(unittest.TestCase):
    def test_budget_and_power_follow_the_channel(self):
        cases = {869_525_000: (360_000, 27, 13), 868_100_000: (36_000, 14, 0),
                 868_800_000: (3_600, 14, 0), 869_850_000: (36_000, 14, 0)}
        for hz, (budget, erp, conducted) in cases.items():
            radio = RadioModel(RadioConfig(channel_hz=hz))
            radio.add_node(1)
            self.assertAlmostEqual(radio.duty_budget_ms_per_hour, budget)
            self.assertAlmostEqual(radio.nodes[1].duty.budget_ms_per_hour, budget)
            self.assertEqual((radio.max_erp_dbm, radio.tx_power_dbm), (erp, conducted))

    def test_refuses_a_channel_that_spills(self):
        for hz in (869_400_000, 869_650_000, 870_000_000, 915_000_000):
            with self.assertRaises(ValueError):
                RadioModel(RadioConfig(channel_hz=hz))

    def test_a_spent_budget_stops_transmissions(self):
        # 0.1% (3.6 s per hour): 47-byte packets of 92.416 ms -> 38 fit.
        radio = RadioModel(RadioConfig(channel_hz=868_800_000), rng=random.Random(1))
        radio.add_node(1)
        radio.add_node(2)
        for seq in range(60):
            radio.send(1, bytes(30), 5, source=1, seq=seq, now_ms=seq * 10)
        self.assertEqual(radio.nodes[1].duty_refused, 22)
        self.assertLessEqual(radio.nodes[1].duty.used(600), 3_600)
        delivered = radio.tick(10_000)
        self.assertEqual(len(delivered), 38)
        # The same traffic on the 10% channel goes through.
        radio = RadioModel(RadioConfig(channel_hz=869_525_000), rng=random.Random(1))
        radio.add_node(1)
        radio.add_node(2)
        for seq in range(60):
            radio.send(1, bytes(30), 5, source=1, seq=seq, now_ms=seq * 10)
        self.assertEqual(radio.nodes[1].duty_refused, 0)
        self.assertEqual(len(radio.tick(10_000)), 60)


if __name__ == "__main__":
    unittest.main()
