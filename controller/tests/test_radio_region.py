# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's radio region (radio_region.py, RFC 0001 Amendment 12, decisions RF-AS923-*).

The config's [radio] region and its default channel, the GM's choice in the
store, the channels, scan and random pick of the region, join key 18, a
standby join from another region, and a whole Taiwanese field on one machine:
the C host modem and C host boxes built for AS923-TW (--region), and a box
built for EU868 that refuses the Taiwanese join.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from support import BOX_HOST, CORE, MODEM_HOST, AirHub, BoxHost, FakeModem, HostModem, config, wait_for
from atalaia_controller.config import ConfigError, load_config
from atalaia_controller.engine import Conflict, Controller, ControllerError
from atalaia_controller.radio_modem import RadioModem
from atalaia_controller.store import Store
from atalaia_sim import join, regions

DOMINATION = "org.atalaia.domination"
JOIN_KEY = bytes(range(100, 132))


class ConfigTests(unittest.TestCase):
    def load(self, text: str):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
            return load_config(path, env={})

    def test_default_is_eu868(self):
        cfg = self.load("")
        self.assertEqual((cfg.region, cfg.channel_hz), ("eu868", 869_525_000))

    def test_a_region_without_a_channel_gets_its_default(self):
        cfg = self.load('[radio]\nregion = "as923-tw"\n')
        self.assertEqual((cfg.region, cfg.channel_hz), ("as923-tw", 921_500_000))
        cfg = self.load('[radio]\nregion = "as923-tw"\nchannel_hz = 924000000\n')
        self.assertEqual(cfg.channel_hz, 924_000_000)

    def test_a_channel_of_another_region_is_refused(self):
        with self.assertRaises(ConfigError) as cm:
            self.load('[radio]\nregion = "as923-tw"\nchannel_hz = 869525000\n')
        self.assertIn("920-925 MHz", str(cm.exception))
        with self.assertRaises(ConfigError):
            self.load('[radio]\nchannel_hz = 921500000\n')
        with self.assertRaises(ConfigError) as cm:
            self.load('[radio]\nregion = "us915"\n')
        self.assertIn("eu868, as923-tw", str(cm.exception))

    def test_environment(self):
        cfg = load_config(None, env={"ATALAIA_RADIO_REGION": "as923-tw"})
        self.assertEqual((cfg.region, cfg.channel_hz), ("as923-tw", 921_500_000))


class EngineRegionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name, scan_dwell_s=1.1)
        self.open()

    def open(self, ident_region=None):
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        if ident_region is not None:
            self.modem.ident["region"] = ident_region
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=JOIN_KEY)
        self.messages = []
        self.ctrl.add_listener(self.messages.append)

    def reopen(self, ident_region=None):
        self.ctrl.stop()
        self.store.close()
        self.open(ident_region)

    def tearDown(self):
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def test_settings_name_the_region(self):
        r = self.ctrl.radio_settings()
        self.assertEqual((r["region"]["code"], r["region_source"], r["modem_region"], r["region_mismatch"]),
                         ("eu868", "config", "eu868", False))  # a modem without "region" is an EU868 build
        self.assertEqual([x["code"] for x in r["regions"]], ["eu868", "as923-tw"])

    def test_moving_to_taiwan(self):
        self.ctrl.set_field_channel(869_475_000)
        out = self.ctrl.set_field_region("as923-tw")
        self.assertEqual((out["region"]["code"], out["region_source"]), ("as923-tw", "console"))
        self.assertEqual((out["channel"]["channel_hz"], out["source"], out["confirmed"]), (921_500_000, "default", False))
        self.assertEqual(out["channel"]["limit_ref"], "conducted")
        self.assertEqual(len(out["candidates"]), 9)
        self.assertTrue(out["region_mismatch"])  # the fake modem is an EU868 build
        self.assertEqual(self.modem.channels, [869_475_000])  # not retuned: the modem would refuse it
        self.assertTrue(any(m["type"] == "radio" and m["radio"]["region"]["code"] == "as923-tw"
                            for m in self.messages))
        # Only the region's channels; the scan and the random pick too.
        with self.assertRaises(ControllerError):
            self.ctrl.set_field_channel(869_525_000)
        self.ctrl.set_field_channel(922_500_000)
        self.assertEqual(self.ctrl.random_channel()["region"], "as923-tw")
        # The choice survives a restart; a modem built for Taiwan is no mismatch.
        self.reopen(ident_region="as923-tw")
        r = self.ctrl.radio_settings()
        self.assertEqual((r["region"]["code"], r["channel"]["channel_hz"], r["region_mismatch"]),
                         ("as923-tw", 922_500_000, False))
        # Back to Europe: the modem built for Taiwan is not retuned, the channel is EU868's default.
        out = self.ctrl.set_field_region("eu868")
        self.assertEqual((out["channel"]["channel_hz"], out["region_mismatch"]), (869_525_000, True))

    def test_a_modem_of_the_new_region_is_retuned(self):
        self.reopen(ident_region="as923-tw")
        self.ctrl.set_field_region("as923-tw")
        self.assertEqual(self.modem.channels, [921_500_000])

    def test_scan_measures_the_region_s_channels(self):
        self.ctrl.set_field_region("as923-tw")
        scan = self.ctrl.start_scan(9)
        self.assertEqual((scan["channels"], scan["region"]), (9, "as923-tw"))
        self.assertTrue(wait_for(lambda: not self.ctrl.scan.running, 5))
        self.assertEqual([hz for hz, _ in self.modem.measured], list(regions.AS923_TW.candidates))
        self.assertEqual(self.ctrl.scan_status()["suggestion"]["reason"], "quiet_full_power")
        # Changing the region forgets the old region's scan.
        self.ctrl.set_field_region("eu868")
        self.assertIsNone(self.ctrl.radio_settings()["scan"])

    def test_refused_while_locked_and_bad_values(self):
        for bad in ("us915", None, 1, "EU868"):
            with self.subTest(bad), self.assertRaises(ControllerError):
                self.ctrl.set_field_region(bad)
        self.ctrl.create_game({"name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"]})
        with self.assertRaises(Conflict):
            self.ctrl.set_field_region("as923-tw")
        self.assertEqual(self.ctrl.field_region.code, "eu868")

    def test_joins_carry_key_18(self):
        self.ctrl.set_field_region("as923-tw")
        self.ctrl.create_game({"name": "Taipei", "mode_id": DOMINATION, "teams": ["red", "blue"]})
        j = self.ctrl.issue_join({"kind": "node", "role": "zone"})
        decoded = join.decode(bytes.fromhex(j["payload_hex"]), JOIN_KEY)
        self.assertEqual((decoded["region"], decoded["channel_hz"]), ("as923-tw", 921_500_000))
        self.assertEqual(self.modem.configured[-1][4], 921_500_000)  # CONFIGURE

    def test_a_standby_join_of_another_region_is_refused(self):
        payload = join.encode({"game_id": 77, "game_key": bytes(16), "node_id": 3, "controller_id": 1,
                               "channel_hz": 921_500_000, "max_hops": 2, "teams": ["red", "blue"],
                               "mode_id": DOMINATION, "role": "standby", "game_seed": 1, "params": None,
                               "kind": "controller", "region": "as923-tw"}, JOIN_KEY)
        with self.assertRaises(Conflict) as cm:
            self.ctrl.join_as_standby(join.to_text(payload))
        self.assertIn("as923-tw", str(cm.exception))

    def test_pairing_listens_on_the_region_s_default(self):
        self.ctrl.set_field_region("as923-tw")
        self.assertEqual(self.ctrl.pairing._pair_hz(), 921_500_000)


@unittest.skipUnless(MODEM_HOST and BOX_HOST, "host modem or host box not built")
class TaiwaneseFieldTests(unittest.TestCase):
    """The C modem and boxes built for AS923-TW (--region), the controller in a Taiwanese field."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = AirHub()
        self.host = HostModem(0, "--region", "as923-tw", hub=self.hub)
        self.hub.add(self.host.air_port)
        self.modem = RadioModem(self.host.url, ping_interval=0.2, retry_interval=0.2)
        self.modem.start()
        self.assertTrue(self.modem.wait_up(5))
        self.cfg = config(self.tmp.name, region="as923-tw", channel_hz=921_500_000)
        self.store = Store(self.cfg.db_path)
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=JOIN_KEY)
        self.ctrl.start()
        self.boxes: list[BoxHost] = []

    def tearDown(self):
        for box in self.boxes:
            box.close()
        self.ctrl.stop()
        self.modem.stop()
        self.store.close()
        self.host.close()
        self.hub.close()
        self.tmp.cleanup()

    def box(self, name: str, region: str) -> BoxHost:
        b = BoxHost(self.hub, os.path.join(self.tmp.name, name), JOIN_KEY, state_ms=500, name=name,
                    extra=("--region", region))
        self.boxes.append(b)
        return b

    def test_the_c_modem_names_its_region(self):
        self.assertTrue(wait_for(lambda: self.modem.ident is not None))
        self.assertEqual(self.modem.ident["region"], "as923-tw")
        self.assertFalse(self.ctrl.radio_settings()["region_mismatch"])

    def test_a_taiwanese_box_plays_and_a_european_one_refuses(self):
        self.ctrl.create_game({"name": "Taipei", "mode_id": DOMINATION, "teams": ["red", "blue"]})
        self.assertTrue(wait_for(lambda: (self.modem.status or {}).get("configured") is True, 5))
        self.assertEqual(self.modem.status["channel_hz"], 921_500_000)
        tw = self.box("tw", "as923-tw")
        j = self.ctrl.issue_join({"kind": "node", "role": "zone"})
        tw.join(j["text"])
        self.assertTrue(wait_for(lambda: tw.logged("LOG join: joined"), 5), tw.lines[-5:])
        self.assertTrue(tw.logged("LOG channel 921500000 Hz"))
        nid = j["node_id"]
        self.assertTrue(wait_for(lambda: nid in self.ctrl.fc.nodes, 10), tw.lines[-5:])
        eu = self.box("eu", "eu868")
        eu.join(self.ctrl.issue_join({"kind": "node", "role": "zone"})["text"])
        self.assertTrue(wait_for(lambda: eu.logged("another radio region"), 5), eu.lines[-5:])
        self.assertFalse(eu.logged("LOG channel 921500000 Hz"))


if __name__ == "__main__":
    unittest.main()
