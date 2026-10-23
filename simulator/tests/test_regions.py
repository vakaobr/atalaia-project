# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The radio regions (regions.py, RFC 0001 Amendment 12): EU868 and AS923 as
Taiwan uses it. The table, the channel rule at each region's bandwidth, the
power for each kind of limit (failing closed when the radio cannot go low
enough), the radio model and a free box in a Taiwanese field.

The channel rule and the time on air are also checked against the C core
(atalaia_region_channel_ok, atalaia_region_airtime_us in core/src/duty_cycle.c)
when the shared core is built (always with ATALAIA_REQUIRE_ALL=1).
"""

from __future__ import annotations

import ctypes
import os
import random
import unittest

from atalaia_sim import eu868, join, lobby, regions
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
TW = regions.AS923_TW


class TableTests(unittest.TestCase):
    def test_regions(self):
        self.assertEqual([r.code for r in regions.REGIONS], ["eu868", "as923-tw"])
        self.assertEqual([r.number for r in regions.REGIONS], [0, 1])
        self.assertIs(regions.get("as923-tw"), TW)
        for bad in ("us915", "AS923-TW", None, 1):
            with self.assertRaises(ValueError):
                regions.get(bad)
        self.assertEqual((TW.sf, TW.bw_hz, TW.default_channel_hz), (9, 500_000, 921_500_000))
        self.assertEqual((TW.lo_hz, TW.hi_hz), (920_000_000, 925_000_000))
        band = TW.band_of(TW.default_channel_hz)
        self.assertEqual((band.limit_dbm, band.limit_mw, band.limit_ref, band.free_gain_dbi),
                         (27, 500, regions.CONDUCTED, 6))
        self.assertTrue(band.full_power)
        self.assertEqual(band.budget_ms_per_hour, 360_000)

    def test_eu868_module_is_the_eu868_region(self):
        self.assertIs(eu868.REGION, regions.EU868)
        self.assertEqual(eu868.CANDIDATES, regions.EU868.candidates)
        self.assertEqual(eu868.DEFAULT_CHANNEL_HZ, 869_525_000)

    def test_default_channels_belong_to_their_region_only(self):
        for r in regions.REGIONS:
            for other in regions.REGIONS:
                self.assertEqual(other.channel_ok(r.default_channel_hz), other is r, (r.code, other.code))

    def test_taiwan_channel_edges(self):
        for hz in (920_250_000, 921_500_000, 924_750_000):
            self.assertTrue(TW.channel_ok(hz), hz)
        for hz in (920_249_999, 924_750_001, 920_000_000, 925_000_000, 915_000_000, 869_525_000):
            self.assertFalse(TW.channel_ok(hz), hz)
        self.assertFalse(TW.channel_ok(921_500_000.0))

    def test_taiwan_candidates(self):
        self.assertEqual(len(TW.candidates), 9)
        self.assertIn(TW.default_channel_hz, TW.scan_candidates())
        self.assertEqual(TW.scan_candidates(), list(TW.candidates))
        for hz in TW.candidates:
            band = TW.band_of(hz)
            self.assertGreaterEqual(hz - TW.bw_hz // 2 - band.lo_hz, 12_500, hz)
            self.assertGreaterEqual(band.hi_hz - hz - TW.bw_hz // 2, 12_500, hz)
        # The default keeps clear of LoRaWAN AS923-1's default channels and Meshtastic's TW default.
        self.assertFalse(TW.overlaps_busy(TW.default_channel_hz))
        self.assertTrue(TW.overlaps_busy(923_000_000))
        self.assertTrue(TW.overlaps_busy(924_000_000))

    def test_describe(self):
        d = TW.describe(921_500_000)
        self.assertEqual((d["band"], d["duty_pct"], d["limit_mw"], d["limit_ref"], d["full_power"],
                          d["region"], d["bw_khz"], d["sf"], d["notes"]),
                         ("tw", 10.0, 500, "conducted", True, "as923-tw", 500, 9, ["default"]))
        self.assertNotIn("erp_mw", d)  # not an ERP limit
        self.assertEqual(TW.describe(923_500_000)["notes"], ["lorawan_default"])
        eu = regions.EU868.describe(869_525_000)
        self.assertEqual((eu["erp_mw"], eu["limit_mw"], eu["limit_ref"], eu["region"]), (500, 500, "erp", "eu868"))
        with self.assertRaises(ValueError):
            TW.describe(869_525_000)


class PowerTests(unittest.TestCase):
    def test_kinds_of_limit(self):
        # ERP: + 2.15 dB; EIRP: the gains only; conducted: the FEM, and the antenna above 6 dBi.
        self.assertEqual(regions.tx_power_dbm(27, 14, 2, regions.ERP), 13)
        self.assertEqual(regions.tx_power_dbm(27, 14, 2, regions.EIRP), 11)
        self.assertEqual(regions.tx_power_dbm(27, 14, 2, regions.CONDUCTED, 6), 13)
        self.assertEqual(regions.tx_power_dbm(27, 14, 9, regions.CONDUCTED, 6), 10)
        self.assertEqual(regions.tx_power_dbm(30, 0, 0, regions.CONDUCTED, 6), 22)
        with self.assertRaises(ValueError):
            regions.tx_power_dbm(27, 14, 2, "watts")

    def test_fails_closed_below_the_radio_s_lowest_setting(self):
        tw = TW.sub_bands[0]
        self.assertEqual(regions.legal_tx_power_dbm(tw, 14, 2), 13)
        g = regions.EU868.band_of(868_100_000)
        self.assertEqual(regions.legal_tx_power_dbm(g, 14, 2), 0)
        # 14 dBm ERP with 30 dB of FEM: -14 dBm would be needed, the SX1262 goes down to -9.
        self.assertIsNone(regions.legal_tx_power_dbm(g, 30, 2))
        # The old clamp would have sent at -9 dBm, over the limit; it stays for the old callers.
        self.assertEqual(regions.tx_power_dbm(14, 30, 2), -9)


class AirtimeTests(unittest.TestCase):
    def test_sf9_at_500_khz(self):
        # The same symbol time (1.024 ms) as SF7 at 125 kHz: the same preamble, fewer payload symbols.
        eu, tw = regions.EU868.airtime_ms(53), TW.airtime_ms(53)
        self.assertEqual(eu, regions.airtime_ms(53, 7, 125_000))
        self.assertLess(tw, eu)
        self.assertGreater(tw, eu / 2)
        self.assertLess(TW.airtime_ms(255), 400)


@unittest.skipIf(CORE is None, "the shared core library is not built")
class SameRuleAsTheCoreTests(unittest.TestCase):
    def test_channel_sweep_per_region(self):
        fn = CORE.lib.atalaia_region_channel_ok
        fn.argtypes = [ctypes.c_int, ctypes.c_uint32]
        fn.restype = ctypes.c_bool
        rng = random.Random(11)
        for region in regions.REGIONS:
            points = set(range(region.lo_hz - 600_000, region.hi_hz + 600_001, 25_000))
            half = region.bw_hz // 2
            for band in region.sub_bands:
                for edge in (band.lo_hz, band.hi_hz):
                    for d in (-half - 1, -half, -half + 1, half - 1, half, half + 1):
                        points.add(edge + d)
            points.update(rng.randrange(860_000_000, 930_000_000) for _ in range(2000))
            for hz in sorted(points):
                self.assertEqual(bool(fn(region.number, hz)), region.channel_ok(hz), (region.code, hz))
            self.assertFalse(fn(len(regions.REGIONS), region.default_channel_hz))

    def test_airtime(self):
        fn = CORE.lib.atalaia_region_airtime_us
        fn.argtypes = [ctypes.c_int, ctypes.c_size_t]
        fn.restype = ctypes.c_uint32
        for region in regions.REGIONS:
            for n in (1, 20, 47, 53, 217, 255):
                self.assertAlmostEqual(fn(region.number, n) / 1000.0, region.airtime_ms(n), places=3)


class RadioModelTests(unittest.TestCase):
    def test_taiwan_field(self):
        radio = RadioModel(RadioConfig(region="as923-tw"))
        radio.add_node(1)
        self.assertEqual(radio.config.channel_hz, 921_500_000)
        self.assertEqual((radio.max_erp_dbm, radio.tx_power_dbm), (27, 13))
        self.assertAlmostEqual(radio.duty_budget_ms_per_hour, 360_000)
        self.assertEqual(radio._estimate_airtime(53), TW.airtime_ms(53))

    def test_another_region_s_channel_is_refused(self):
        with self.assertRaises(ValueError):
            RadioModel(RadioConfig(region="as923-tw", channel_hz=869_525_000))
        with self.assertRaises(ValueError):
            RadioModel(RadioConfig(channel_hz=921_500_000))
        with self.assertRaises(ValueError):
            RadioModel(RadioConfig(region="us915"))

    def test_too_much_gain_refuses_the_channel(self):
        with self.assertRaises(ValueError):
            RadioModel(RadioConfig(channel_hz=868_100_000, fem_gain_db=30))


class FreeBoxTests(unittest.TestCase):
    KEY = bytes(range(32))

    def _join(self, **kw) -> bytes:
        j = {"game_id": 5, "game_key": bytes(16), "node_id": 3, "controller_id": 0,
             "channel_hz": 921_500_000, "max_hops": 2, "teams": ["red", "blue"], "mode_id": "org.atalaia.domination",
             "role": "zone", "game_seed": 1, "params": None, "kind": "node", "region": "as923-tw"}
        j.update(kw)
        return join.encode(j, self.KEY)

    def test_a_taiwanese_box_takes_its_region_s_join(self):
        box = lobby.IdleBox(self.KEY, region="as923-tw", rng=random.Random(1))
        self.assertEqual(box.channel_hz, 921_500_000)
        self.assertEqual(box.join(self._join()), "accepted")
        self.assertEqual(box.channel_hz, 921_500_000)

    def test_a_box_refuses_another_region_s_join(self):
        eu_box = lobby.IdleBox(self.KEY, rng=random.Random(2))
        self.assertEqual(eu_box.join(self._join()), "refused")
        self.assertEqual(eu_box.phase, "idle")
        tw_box = lobby.IdleBox(self.KEY, region="as923-tw", rng=random.Random(3))
        self.assertEqual(tw_box.join(self._join(channel_hz=869_525_000, region="eu868")), "refused")

    def test_announcements_follow_the_region(self):
        import math
        self.assertEqual(lobby.announce_interval_ms(921_500_000, 60, TW),
                         max(lobby.ANNOUNCE_MIN_MS, math.ceil(TW.airtime_ms(60) / (lobby.ANNOUNCE_SHARE * 0.10))))
        self.assertLessEqual(lobby.announce_interval_ms(921_500_000, 60, TW),
                             lobby.announce_interval_ms(869_525_000, 60))


if __name__ == "__main__":
    unittest.main()
