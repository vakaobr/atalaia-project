# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's radio channel (channels.py, RFC 0001 Amendment 3): the setting,
the noise scan and its suggestion, the random pick, the edge rule, the API.

    cd controller && python -m unittest discover -s tests

The engine runs over a recording modem (FakeModem) whose MEASURE answers
come from a table; test_modem_host.py runs the same scan over the C modem.
"""

from __future__ import annotations

import random
import tempfile
import threading
import unittest

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config, wait_for
from atalaia_controller import channels
from atalaia_controller import modem_framing as mf
from atalaia_controller.api import Auth, create_app
from atalaia_controller.config import ConfigError, load_config
from atalaia_controller.engine import Conflict, Controller, ControllerError, Unavailable
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import eu868, join

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
DOMINATION = "org.atalaia.domination"


def noise(hz: int, p90: int, hits: int = 0, tries: int = 10, mean: int = None) -> mf.Noise:
    mean = p90 - 3 if mean is None else mean
    return mf.Noise(hz, 1000, 1000, p90 - 6, mean, p90 - 4, p90, p90 + 9, tries, hits)


class EdgeRuleConfigTests(unittest.TestCase):
    def test_channel_must_fit_in_a_sub_band(self):
        with tempfile.TemporaryDirectory() as tmp:
            for hz in (869_400_000, 869_650_000, 868_000_000, 870_000_000, 869_587_501, 915_000_000):
                with self.subTest(hz), self.assertRaises(ConfigError) as cm:
                    config(tmp, channel_hz=hz)
                self.assertIn("125 kHz", str(cm.exception))
            for hz in (869_462_500, 869_587_500, 868_062_500, 869_937_500, 868_100_000):
                self.assertEqual(config(tmp, channel_hz=hz).channel_hz, hz)
            with self.assertRaises(ConfigError):
                load_config(None, env={"ATALAIA_RADIO_CHANNEL_HZ": "869400000"})
            self.assertEqual(load_config(None, env={"ATALAIA_RADIO_CHANNEL_HZ": "869475000"}).channel_hz,
                             869_475_000)
            for name, value in (("scan_dwell_s", 0.5), ("scan_dwell_s", 601.0),
                                ("quiet_threshold_dbm", 5), ("quiet_threshold_dbm", -129)):
                with self.subTest(name), self.assertRaises(ConfigError):
                    config(tmp, **{name: value})

    def test_join_payload_refuses_a_spilling_channel(self):
        j = {"game_id": 7, "game_key": bytes(16), "node_id": 1, "controller_id": 0,
             "channel_hz": 869_650_000, "max_hops": 2, "teams": ["red"], "mode_id": DOMINATION,
             "role": "zone", "game_seed": 1, "params": None, "kind": "node"}
        with self.assertRaises(join.JoinError):
            join.encode(j, bytes(32))
        j["channel_hz"] = 869_587_500
        self.assertEqual(join.decode(join.encode(j, bytes(32)), bytes(32))["channel_hz"], 869_587_500)


class RankingTests(unittest.TestCase):
    def test_quietest_first_lora_activity_last(self):
        results = [noise(868_100_000, -100), noise(868_300_000, -118, hits=4),
                   noise(869_525_000, -112), noise(869_850_000, -116)]
        ranked = [n.channel_hz for n in sorted(results, key=channels.rank_key)]
        # 40% CAD detections on 868.3: other LoRa traffic, last despite its low noise.
        self.assertEqual(ranked, [869_850_000, 869_525_000, 868_100_000, 868_300_000])

    def test_suggests_the_quiet_full_power_channel(self):
        results = [noise(868_100_000, -118), noise(869_475_000, -110), noise(869_525_000, -108)]
        self.assertEqual(channels.suggest(results, -105),
                         {"channel_hz": 869_475_000, "reason": "quiet_full_power"})

    def test_otherwise_the_quietest_overall(self):
        # The full-power channels are noisy (above -105 dBm), so the quietest of all wins.
        results = [noise(868_100_000, -118), noise(869_525_000, -100), noise(869_575_000, -98)]
        self.assertEqual(channels.suggest(results, -105),
                         {"channel_hz": 868_100_000, "reason": "quietest"})
        # Full power but busy with LoRa (3 detections of 10): not quiet enough either.
        results = [noise(868_200_000, -116), noise(869_525_000, -119, hits=3)]
        self.assertEqual(channels.suggest(results, -105)["channel_hz"], 868_200_000)
        # Everything is noisy: still a suggestion, marked as such.
        results = [noise(868_200_000, -90), noise(869_525_000, -95)]
        self.assertEqual(channels.suggest(results, -105),
                         {"channel_hz": 869_525_000, "reason": "quietest_but_noisy"})
        self.assertIsNone(channels.suggest([], -105))

    def test_dwell_split(self):
        self.assertAlmostEqual(channels.per_channel_dwell_s(60, 11), 60 / 11)
        self.assertEqual(channels.per_channel_dwell_s(600, 11), 10.0)  # one MEASURE: at most 10 s
        self.assertEqual(channels.per_channel_dwell_s(0.05, 11), 0.01)

    def test_random_pick(self):
        rng = random.Random(3)
        seen = set()
        for _ in range(500):
            pick = channels.random_choice(rng)
            self.assertTrue(pick["usable"])
            self.assertNotEqual(pick["band"], "g1")  # 0.1%: never drawn (decision CH5)
            self.assertEqual((pick["pool"], pick["pool_full_power"]), (11, 3))
            seen.add(pick["channel_hz"])
        self.assertEqual(seen, set(eu868.scan_candidates()))

    def test_candidates_list(self):
        cands = channels.candidates()
        self.assertEqual([c["channel_hz"] for c in cands], list(eu868.CANDIDATES))
        default = next(c for c in cands if c["channel_hz"] == 869_525_000)
        self.assertEqual((default["duty_pct"], default["erp_mw"], default["notes"]), (10.0, 500, ["default"]))


class EngineChannelCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name, scan_dwell_s=1.1)
        self.open()

    def open(self, modem: bool = True):
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem() if modem else None
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=bytes(32))
        self.messages = []
        self.ctrl.add_listener(self.messages.append)

    def reopen(self, modem: bool = True):
        self.ctrl.stop()
        self.store.close()
        self.open(modem)

    def tearDown(self):
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def game(self):
        return self.ctrl.create_game({"name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"]})


class FieldChannelTests(EngineChannelCase):
    def test_default_until_the_gm_chooses(self):
        r = self.ctrl.radio_settings()
        self.assertEqual(r["channel"]["channel_hz"], 869_525_000)
        self.assertEqual((r["source"], r["confirmed"], r["locked"], r["scan_unavailable"]),
                         ("default", False, None, None))
        self.assertEqual(r["channel"]["duty_pct"], 10.0)
        self.assertEqual(len(r["candidates"]), len(eu868.CANDIDATES))
        self.assertFalse(self.ctrl.status()["channel_confirmed"])

    def test_choice_is_kept_used_and_sent(self):
        out = self.ctrl.set_field_channel(868_300_000, "manual")
        self.assertEqual((out["channel"]["channel_hz"], out["source"], out["confirmed"]),
                         (868_300_000, "manual", True))
        self.assertEqual(out["channel"]["erp_mw"], 25)
        self.assertEqual(self.modem.channels, [868_300_000])  # SET_CHANNEL
        self.assertTrue(any(m["type"] == "radio" for m in self.messages))
        # A restart keeps it (a field setting in the store), and new games use it.
        self.reopen()
        self.assertEqual(self.ctrl.field_channel, 868_300_000)
        self.assertTrue(self.ctrl.radio_settings()["confirmed"])
        game = self.game()
        self.assertEqual(game["channel_hz"], 868_300_000)
        self.assertEqual(self.modem.configured[-1][4], 868_300_000)  # CONFIGURE
        j = self.ctrl.issue_join({"kind": "node", "role": "zone"})
        self.assertEqual(j["channel_hz"], 868_300_000)
        self.assertEqual(join.decode(bytes.fromhex(j["payload_hex"]), bytes(32))["channel_hz"],
                         868_300_000)

    def test_accepting_the_default_confirms_it(self):
        out = self.ctrl.set_field_channel(869_525_000, "default")
        self.assertEqual((out["source"], out["confirmed"]), ("default", True))

    def test_refused_while_a_game_is_live(self):
        self.game()
        self.assertIn("live", self.ctrl.radio_settings()["locked"])
        with self.assertRaises(Conflict):
            self.ctrl.set_field_channel(868_100_000)
        with self.assertRaises(Conflict):
            self.ctrl.start_scan()
        self.assertEqual(self.modem.channels, [])

    def test_bad_values(self):
        for hz in (869_400_000, 869_650_000, 870_000_000, 915_000_000, "x", True, None):
            with self.subTest(hz), self.assertRaises(ControllerError):
                self.ctrl.set_field_channel(hz)
        with self.assertRaises(ControllerError):
            self.ctrl.set_field_channel(868_100_000, "guess")
        self.assertEqual(self.ctrl.field_channel, 869_525_000)

    def test_a_bad_stored_channel_falls_back(self):
        self.store.set_setting("radio.channel_hz", "869650000")
        self.reopen()
        self.assertEqual(self.ctrl.field_channel, 869_525_000)

    def test_modem_back_up_is_tuned_to_the_field_channel(self):
        self.ctrl.set_field_channel(869_850_000)
        self.modem.channels.clear()
        self.ctrl._on_modem_state("up")
        self.assertEqual(self.modem.channels, [869_850_000])


class ScanTests(EngineChannelCase):
    def test_scan_ranks_and_suggests(self):
        self.modem.noise = {868_100_000: (-95, 0), 869_475_000: (-109, 0), 869_525_000: (-104, 0),
                            869_575_000: (-111, 6), 869_850_000: (-117, 0)}
        self.ctrl.set_field_channel(868_500_000)
        self.modem.channels.clear()
        state = self.ctrl.start_scan()
        self.assertIn(state["state"], ("running", "done"))  # the fake modem answers at once
        self.assertTrue(wait_for(lambda: self.ctrl.scan_status()["state"] == "done", 5))
        scan = self.ctrl.scan_status()
        self.assertEqual([hz for hz, _ in self.modem.measured], eu868.scan_candidates())
        self.assertEqual({ms for _, ms in self.modem.measured}, {100})  # 1.1 s over 11 channels
        self.assertEqual(scan["measured"], 11)
        self.assertEqual(scan["results"][0]["channel_hz"], 868_200_000)  # -118: the fake's floor
        self.assertEqual(scan["results"][-1]["channel_hz"], 869_575_000)  # LoRa activity: last
        self.assertEqual(scan["suggestion"], {"channel_hz": 869_475_000, "reason": "quiet_full_power"})
        row = next(r for r in scan["results"] if r["channel_hz"] == 869_525_000)
        self.assertEqual((row["p90_dbm"], row["quiet"], row["duty_pct"], row["erp_mw"]),
                         (-104, False, 10.0, 500))
        # The scan changed nothing: the GM accepts or overrides.
        self.assertEqual(self.ctrl.field_channel, 868_500_000)
        # Back on the field's channel: the scan thread retunes after it reports "done".
        self.assertTrue(wait_for(lambda: self.modem.channels == [868_500_000], 5), self.modem.channels)
        self.assertTrue(any(m["type"] == "radio_scan" and m["scan"]["state"] == "done"
                            for m in self.messages))
        self.ctrl.set_field_channel(scan["suggestion"]["channel_hz"], "scan")
        self.assertEqual(self.ctrl.radio_settings()["source"], "scan")
        # The last scan survives a restart.
        self.reopen()
        self.assertEqual(self.ctrl.radio_settings()["scan"]["suggestion"]["channel_hz"], 869_475_000)

    def test_no_games_or_changes_while_scanning(self):
        gate = threading.Event()
        self.modem.measure_gate = gate
        self.ctrl.start_scan()
        self.assertTrue(wait_for(lambda: self.modem.measured, 2))
        with self.assertRaises(Conflict):
            self.game()
        with self.assertRaises(Conflict):
            self.ctrl.set_field_channel(868_100_000)
        with self.assertRaises(Conflict):
            self.ctrl.start_scan()
        self.ctrl.cancel_scan()
        gate.set()
        self.assertTrue(wait_for(lambda: self.ctrl.scan_status()["state"] == "cancelled", 5))
        self.assertLess(len(self.modem.measured), 11)
        with self.assertRaises(Conflict):
            self.ctrl.cancel_scan()
        self.game()  # allowed again

    def test_a_failed_measurement_stops_the_scan(self):
        def broken(hz, ms, cad=True, timeout=None):
            from atalaia_controller.radio_modem import MeasureError
            raise MeasureError("radio", "MEASURE: the radio failed while measuring")
        self.modem.measure = broken
        self.ctrl.start_scan()
        self.assertTrue(wait_for(lambda: self.ctrl.scan_status()["state"] == "failed", 5))
        self.assertIn("radio failed", self.ctrl.scan_status()["error"])
        self.assertIsNone(self.ctrl.scan_status()["suggestion"])

    def test_dwell_override(self):
        self.ctrl.start_scan(2.2)
        self.assertTrue(wait_for(lambda: self.ctrl.scan_status()["state"] == "done", 5))
        self.assertEqual({ms for _, ms in self.modem.measured}, {200})
        for bad in (0, 601, "60", True):
            with self.subTest(bad), self.assertRaises(ControllerError):
                self.ctrl.start_scan(bad)

    def test_unavailable_without_a_radio(self):
        self.modem.state = "down"
        with self.assertRaises(Unavailable):
            self.ctrl.start_scan()
        self.modem.state = "up"
        self.modem.ident = {"fw": "atalaia-modem", "radio": "none"}
        self.assertEqual(self.ctrl.radio_settings()["scan_unavailable"], "no_radio")
        with self.assertRaises(Unavailable):
            self.ctrl.start_scan()
        self.modem.ident = {"fw": "atalaia-modem", "radio": "sx1262"}
        self.modem.can_measure = False
        with self.assertRaises(Unavailable) as cm:
            self.ctrl.start_scan()
        self.assertIn("firmware", str(cm.exception))
        self.reopen(modem=False)
        self.assertEqual(self.ctrl.radio_settings()["scan_unavailable"], "no_modem")
        with self.assertRaises(Unavailable) as cm:
            self.ctrl.start_scan()
        self.assertIn("no USB radio modem", str(cm.exception))
        # Without a modem the channel can still be chosen (it goes to the boxes' join payload).
        self.assertEqual(self.ctrl.set_field_channel(869_525_000, "default")["confirmed"], True)


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cfg = config(self.tmp.name, scan_dwell_s=1.1)
        self.store = Store(cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(cfg, self.store, modem=self.modem, core=CORE)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(cfg.gm_token, cfg.read_token)))

    def tearDown(self):
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def test_endpoints(self):
        c = self.client
        r = c.get("/api/v1/radio", headers=READ)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["recommended_hz"], 869_525_000)
        # The read token sees, the GM token changes.
        self.assertEqual(c.put("/api/v1/radio/channel", json={"channel_hz": 868_100_000},
                               headers=READ).status_code, 403)
        self.assertEqual(c.post("/api/v1/radio/scan", headers=READ).status_code, 403)
        self.assertEqual(c.post("/api/v1/radio/random", headers=READ).status_code, 403)
        self.assertEqual(c.get("/api/v1/radio").status_code, 401)
        r = c.put("/api/v1/radio/channel", json={"channel_hz": 869_400_000}, headers=GM)
        self.assertEqual(r.status_code, 400)
        self.assertIn("125 kHz", r.json()["detail"])
        r = c.put("/api/v1/radio/channel", json={"channel_hz": 869_575_000, "source": "manual"}, headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["channel"]["channel_hz"], 869_575_000)
        r = c.post("/api/v1/radio/random", headers=GM)
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.json()["suggestion"]["channel_hz"], eu868.scan_candidates())
        self.assertEqual(self.ctrl.field_channel, 869_575_000)  # a suggestion changes nothing
        r = c.post("/api/v1/radio/scan", json={"dwell_s": 1.1}, headers=GM)
        self.assertEqual(r.status_code, 202, r.text)
        self.assertTrue(wait_for(lambda: c.get("/api/v1/radio/scan", headers=READ).json()["scan"]["state"]
                                 == "done", 5))
        self.assertEqual(c.delete("/api/v1/radio/scan", headers=GM).status_code, 409)
        # A live game locks the channel.
        r = c.post("/api/v1/games", json={"name": "x", "mode_id": DOMINATION}, headers=GM)
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["channel_hz"], 869_575_000)
        self.assertEqual(c.put("/api/v1/radio/channel", json={"channel_hz": 868_100_000},
                               headers=GM).status_code, 409)
        self.assertEqual(c.post("/api/v1/radio/scan", headers=GM).status_code, 409)

    def test_scan_without_a_modem_is_503(self):
        self.modem.state = "down"
        r = self.client.post("/api/v1/radio/scan", headers=GM)
        self.assertEqual(r.status_code, 503)
        self.assertIn("modem", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
