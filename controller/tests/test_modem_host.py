# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller against the modem's real C logic (firmware/esp32/test/modem_host).

    cd controller && ATALAIA_MODEM_HOST=... python -m unittest discover -s tests

The host modem runs main/modem/modem.c and modem_framing.c with mbedtls
AES-CCM; its serial link is a TCP socket (pyserial socket://) and its air
is UDP. So these tests cross every boundary the field has: Python framing
against C framing, C encryption against Python decryption and back, the
watchdog against a modem that dies and comes back, and the whole engine
(store, ACKs, CMD, TIME) over it.
"""

from __future__ import annotations

import json
import tempfile
import unittest

from support import MODEM_HOST, WAIT_FLOOR_S, HostModem, config, node_packet, packet_decrypt, wait_for
from atalaia_controller import modem_framing as mf
from atalaia_controller.engine import Controller
from atalaia_controller import channels
from atalaia_controller.radio_modem import UP, MeasureError, RadioModem
from atalaia_controller.store import Store
from atalaia_sim import codec, eu868
from atalaia_sim.packet import (Header, ack_decode, cmd_decode, hello_encode, state_encode,
                                time_decode, time_encode, vf_ack, vf_enc, vf_make)
from atalaia_sim.protocol import MESSAGE_TYPES

KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
GAME = 0x2345


@unittest.skipUnless(MODEM_HOST, "host modem not built")
class ModemHostTests(unittest.TestCase):
    def setUp(self):
        self.host = HostModem()
        self.rx: list[mf.RxPacket] = []
        self.acks: list[tuple[int, str]] = []
        self.errors: list[tuple[str, str]] = []
        self.modem = RadioModem(self.host.url, ping_interval=0.1, retry_interval=0.2,
                                on_rx=self.rx.append, on_tx_ack=lambda s, st: self.acks.append((s, st)),
                                on_error=lambda c, m: self.errors.append((c, m)))
        self.modem.start()
        self.assertTrue(self.modem.wait_up(5))

    def tearDown(self):
        self.modem.stop()
        self.host.close()

    def configure(self, epoch: int = 3) -> None:
        self.modem.configure(GAME, 0, epoch, 2, 869_525_000, KEY)
        self.assertTrue(wait_for(lambda: (self.modem.status or {}).get("configured") is True, 3))

    def test_ident_from_the_c_modem(self):
        self.assertTrue(wait_for(lambda: self.modem.ident is not None))
        ident = self.modem.ident
        self.assertEqual((ident["fw"], ident["radio"], ident["framing"], ident["payload_max"]),
                         ("atalaia-modem", "sx1262", 1, 200))
        self.assertEqual(ident["epoch_window"], 16)
        self.assertIn("ping", self.modem.status)

    def test_screen_language_over_the_c_modem(self):
        """SET_LANG against the C logic (decision MOD-2): IDENT says "lang", the code is taken
        (a STATUS for it) and anything that is not a code is an ERROR."""
        self.assertTrue(wait_for(lambda: self.modem.has_language))
        replies: list[dict] = []
        dispatch = self.modem._dispatch

        def spy(frame_type, payload):
            if frame_type == mf.STATUS:
                replies.append(json.loads(payload))
            dispatch(frame_type, payload)

        self.modem._dispatch = spy
        self.modem.set_language("zh-tw")
        self.assertTrue(wait_for(lambda: any(r.get("cmd") == mf.CMD_SET_LANG for r in replies)))
        self.assertEqual(self.errors, [])
        self.modem._write(mf.CMD, bytes([mf.CMD_SET_LANG]) + b"zh-tw-hant")
        self.modem._write(mf.CMD, bytes([mf.CMD_SET_LANG]) + b"p\x00")
        self.assertTrue(wait_for(lambda: len(self.errors) >= 2))
        self.assertEqual({code for code, _ in self.errors}, {"bad_params"})

    def test_c_encrypts_python_decrypts(self):
        self.configure(epoch=3)
        payload = time_encode({"game_time_ms": 1234, "game_state": 1, "duration_ms": 0,
                               "wall_s": 1_700_000_000, "term": 1})
        hdr = Header(vf_make(1, 2, False, False), GAME, 0, 0, 3, MESSAGE_TYPES["TIME"])
        self.assertTrue(self.modem.send_packet(hdr, payload))
        air = self.host.transmitted()
        got_hdr, plain = packet_decrypt(air, 3, KEY)
        self.assertEqual(plain, payload)
        self.assertTrue(vf_enc(got_hdr.version_flags))
        self.assertEqual(got_hdr.hop_limit, 2)  # clamped to max_hops
        self.assertEqual(time_decode(plain)["game_time_ms"], 1234)
        self.assertTrue(wait_for(lambda: self.acks == [(0, "ok")]))

    def test_python_encrypts_c_decrypts(self):
        self.configure()
        hello = hello_encode({"node_name": "box-7", "platform": 1, "fw_version": "0.2.0",
                              "core_version": "0.2.0", "tier": 0, "capabilities": [0, 2],
                              "transports": 1, "epoch": 5})
        self.host.hear(node_packet(KEY, GAME, 7, 0, 5, "HELLO", hello))
        self.assertTrue(wait_for(lambda: self.rx))
        rx = self.rx[0]
        self.assertEqual((rx.header.source, rx.header.seq, rx.epoch, rx.rssi, rx.snr), (7, 0, 5, -42, 7))
        self.assertEqual(rx.payload, hello)
        # Wrong key, other game, lower epoch: nothing reaches the controller.
        self.host.hear(node_packet(bytes(16), GAME, 8, 0, 0, "HELLO", hello))
        self.host.hear(node_packet(KEY, GAME + 1, 9, 0, 0, "HELLO", hello))
        self.host.hear(node_packet(KEY, GAME, 7, 1, 4, "HELLO", hello))
        self.host.hear(node_packet(KEY, GAME, 7, 0, 5, "HELLO", hello))  # duplicate
        self.host.hear(node_packet(KEY, GAME, 7, 2, 5, "STATE", state_encode(
            {"owner_team": 0, "phase": 0, "game_time_ms": 0, "counters": {}, "epoch": 5})))
        self.assertTrue(wait_for(lambda: len(self.rx) >= 2))
        self.assertTrue(wait_for(lambda: (self.modem.status or {}).get("rx_auth_fail", 0) >= 2, 3))
        self.assertEqual([r.header.seq for r in self.rx], [0, 2])

    def test_nonce_guard_and_bad_tx(self):
        self.configure(epoch=3)
        hdr = Header(vf_make(1, 1, False, True), GAME, 0, 4, 2, MESSAGE_TYPES["CMD"])
        self.assertTrue(self.modem.send_packet(hdr, b"\xa1\x01\x05"))
        self.assertTrue(self.modem.send_packet(hdr, b"\xa1\x01\x05"))  # same seq again
        wrong_source = Header(vf_make(1, 1, False, True), GAME, 5, 6, 2, MESSAGE_TYPES["CMD"])
        self.assertTrue(self.modem.send_packet(wrong_source, b"\xa1\x01\x05"))
        self.assertTrue(wait_for(lambda: len(self.acks) == 3))
        self.assertEqual(self.acks, [(4, "ok"), (4, "nonce_reuse"), (6, "invalid")])
        self.assertEqual(len(self.host.transmitted_all()), 1)

    def test_bad_configure_is_an_error(self):
        self.modem.configure(GAME, 0, 1, 2, 915_000_000, KEY)  # not EU868
        self.assertTrue(wait_for(lambda: self.errors))
        self.assertEqual(self.errors[0][0], "bad_params")

    def test_modem_restart_is_survived(self):
        self.configure(epoch=3)
        port = self.host.serial_port
        self.host.kill()
        self.assertTrue(wait_for(lambda: self.modem.state != UP, 5))
        self.host.serial_port = port
        self.host.start()  # same port: the modem came back (a reboot)
        self.assertTrue(self.modem.wait_up(10))
        # The key and game were sent again on reconnect: TX works and decrypts.
        hdr = Header(vf_make(1, 2, False, True), GAME, 0, 10, 2, MESSAGE_TYPES["TIME"])
        self.assertTrue(wait_for(lambda: (self.modem.status or {}).get("configured") is True, 3))
        self.assertTrue(self.modem.send_packet(hdr, b"\xa0"))
        self.assertEqual(packet_decrypt(self.host.transmitted(), 3, KEY)[1], b"\xa0")
        self.assertGreaterEqual(self.modem.reconnects, 1)


@unittest.skipUnless(MODEM_HOST, "host modem not built")
class DutyCycleAndNoRadioTests(unittest.TestCase):
    def run_modem(self, *args):
        host = HostModem(0, *args)
        acks = []
        modem = RadioModem(host.url, ping_interval=0.1, on_tx_ack=lambda s, st: acks.append((s, st)))
        modem.start()
        try:
            self.assertTrue(modem.wait_up(5))
            modem.configure(GAME, 0, 1, 2, 869_525_000, KEY)
            self.assertTrue(wait_for(lambda: (modem.status or {}).get("configured") is True, 3))
            for seq in range(3):
                modem.send_packet(Header(vf_make(1, 1, False, True), GAME, 0, seq, 2, 5), bytes(30))
            self.assertTrue(wait_for(lambda: len(acks) == 3))
            return acks
        finally:
            modem.stop()
            host.close()

    def test_duty_cycle_budget(self):
        # 9 + 30 + 8 bytes = 47 -> 92.4 ms on air at SF7/BW125; a 200 ms budget fits two.
        self.assertEqual(self.run_modem("--duty-budget-ms", "200"),
                         [(0, "ok"), (1, "ok"), (2, "duty_cycle")])

    def test_no_radio(self):
        self.assertEqual({s for _, s in self.run_modem("--no-radio")}, {"no_radio"})


@unittest.skipUnless(MODEM_HOST, "host modem not built")
class ChannelLimitsAndMeasureTests(unittest.TestCase):
    """The C modem's channel rule, per-sub-band budget and MEASURE (RFC 0001 Amendment 3)."""

    NOISE = ("--noise", "868100000:-96", "--noise", "868300000:-117:60", "--noise", "869475000:-109",
             "--noise", "869525000:-104", "--noise", "869850000:-114", "--noise-floor", "-100",
             "--measure-fail", "869925000")

    def start(self, *args):
        self.host = HostModem(0, *args)
        self.errors = []
        self.modem = RadioModem(self.host.url, ping_interval=0.1,
                                on_error=lambda c, m: self.errors.append((c, m)))
        self.modem.start()
        self.assertTrue(self.modem.wait_up(5))
        self.assertTrue(wait_for(lambda: self.modem.ident is not None))

    def tearDown(self):
        self.modem.stop()
        self.host.close()

    def status(self):
        """The modem's answer to STATUS (RadioModem.request_status): `modem.status` is the latest reply
        to any command, and a ping's reply could replace this one before a poll saw it."""
        reply = self.modem.request_status(WAIT_FLOOR_S)
        self.assertIsNotNone(reply, "no STATUS reply")
        return reply

    def test_budget_follows_the_channel(self):
        self.start()
        self.assertEqual(self.status()["duty_ms"], 360_000)    # 869.525: 10% of an hour
        for hz, budget in ((868_100_000, 36_000), (868_800_000, 3_600), (869_850_000, 36_000),
                           (869_475_000, 360_000)):
            self.assertTrue(self.modem.set_channel(hz))
            self.assertTrue(wait_for(lambda: (self.modem.status or {}).get("channel_hz") == hz, 3))
            self.assertEqual(self.status()["duty_ms"], budget, hz)
        # The edges: a centre inside 869.4-869.65 MHz whose channel spills over is refused.
        for hz in (869_400_000, 869_650_000, 870_000_000):
            self.modem.set_channel(hz)
        self.assertTrue(wait_for(lambda: len(self.errors) == 3, 3))
        self.assertEqual({c for c, _ in self.errors}, {"bad_params"})
        self.assertEqual(self.status()["channel_hz"], 869_475_000)

    def test_measure(self):
        self.start(*self.NOISE)
        self.assertTrue(self.modem.can_measure)
        n = self.modem.measure(868_100_000, 200)
        self.assertEqual((n.channel_hz, n.dwell_ms, n.samples), (868_100_000, 200, 200))
        self.assertTrue(-98 <= n.p50_dbm <= -94 and -98 <= n.mean_dbm <= -93, n)
        self.assertTrue(-88 <= n.max_dbm <= -84, n)  # the simulated 10 dB spikes
        self.assertEqual((n.cad_tries, n.cad_detected), (2, 0))
        busy = self.modem.measure(868_300_000, 500)
        self.assertEqual((busy.cad_tries, busy.cad_detected), (5, 3))
        self.assertTrue(-102 <= self.modem.measure(869_775_000, 50).p90_dbm <= -98)  # the floor
        with self.assertRaises(MeasureError) as cm:
            self.modem.measure(869_925_000, 50)
        self.assertEqual(cm.exception.code, "radio")
        # Errors: an illegal centre, and a configured game (measuring would leave its channel).
        with self.assertRaises(MeasureError) as cm:
            self.modem.measure(869_400_000, 50)
        self.assertEqual(cm.exception.code, "bad_params")
        self.modem.configure(GAME, 0, 1, 2, 869_525_000, KEY)
        self.assertTrue(wait_for(lambda: (self.modem.status or {}).get("configured") is True, 3))
        with self.assertRaises(MeasureError) as cm:
            self.modem.measure(868_100_000, 50)
        self.assertEqual(cm.exception.code, "busy")
        self.modem.clear()
        self.assertTrue(wait_for(lambda: (self.modem.status or {}).get("configured") is False, 3))
        self.assertEqual(self.modem.measure(868_100_000, 20).dwell_ms, 20)
        self.assertEqual(self.errors, [])  # MEASURE answers are not alerts

    def test_no_radio(self):
        self.start("--no-radio")
        self.assertFalse(self.modem.can_measure)
        self.assertEqual(self.modem.ident["measure"], False)
        with self.assertRaises(MeasureError) as cm:
            self.modem.measure(869_525_000, 50)
        self.assertEqual(cm.exception.code, "no_radio")

    def test_engine_scan_over_the_c_modem(self):
        self.start(*self.NOISE)
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp, port=self.host.url, scan_dwell_s=1.1)
            store = Store(cfg.db_path)
            ctrl = Controller(cfg, store, modem=self.modem)
            try:
                ctrl.start_scan()
                self.assertTrue(wait_for(lambda: ctrl.scan_status()["state"] != "running", 10))
                scan = ctrl.scan_status()
                self.assertEqual(scan["state"], "failed")  # --measure-fail on 869.925, the last one
                self.assertEqual(scan["measured"], 10)
                ranked = [r["channel_hz"] for r in scan["results"]]
                self.assertEqual(ranked[-1], 868_300_000)  # LoRa activity: last
                self.assertLess(ranked.index(869_850_000), ranked.index(869_475_000))
                # Without the failing channel the scan completes and suggests 869.475 MHz:
                # the quietest full-power channel, at or below -105 dBm.
                ctrl.scan = channels.Scan(lambda hz, ms: self.modem.measure(hz, ms), 1.0, -105,
                                          ctrl._on_scan,
                                          channels=[h for h in eu868.scan_candidates() if h != 869_925_000])
                ctrl.scan.start()
                self.assertTrue(wait_for(lambda: ctrl.scan_status()["state"] == "done", 10))
                self.assertEqual(ctrl.scan_status()["suggestion"],
                                 {"channel_hz": 869_475_000, "reason": "quiet_full_power"})
                ctrl.set_field_channel(869_475_000, "scan")
                self.assertEqual(self.status()["channel_hz"], 869_475_000)
            finally:
                ctrl.stop()
                store.close()


@unittest.skipUnless(MODEM_HOST, "host modem not built")
class EngineOverHostModemTests(unittest.TestCase):
    """The whole controller over the C modem: a box's event is stored and ACKed on air."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.host = HostModem()
        cfg = config(self.tmp.name, port=self.host.url)
        self.store = Store(cfg.db_path)
        self.modem = RadioModem(cfg.port, ping_interval=0.1)
        self.ctrl = Controller(cfg, self.store, modem=self.modem)
        self.messages = []
        self.ctrl.add_listener(self.messages.append)
        self.modem.start()
        self.ctrl.start()
        self.assertTrue(self.modem.wait_up(5))

    def tearDown(self):
        self.ctrl.stop()
        self.modem.stop()
        self.host.close()
        self.store.close()
        self.tmp.cleanup()

    def test_event_is_stored_and_acked_over_the_air(self):
        game = self.ctrl.create_game({"name": "test", "mode_id": "org.atalaia.domination",
                                      "teams": ["red", "blue"], "assignments": {"7": "zone"}})
        key = self.ctrl.game_key(game["id"])
        epoch = self.ctrl.transport.epoch
        self.assertTrue(wait_for(lambda: (self.modem.status or {}).get("configured") is True, 3))
        self.ctrl.start_game(game["id"], force=True)
        start_packets = self.host.transmitted_all()
        types = []
        for pkt in start_packets:
            hdr, plain = packet_decrypt(pkt, epoch, key)
            types.append(hdr.type)
            if hdr.type == MESSAGE_TYPES["CMD"]:
                self.assertEqual(cmd_decode(plain), {"cmd": 0})
        self.assertEqual(types[:2], [MESSAGE_TYPES["CMD"], MESSAGE_TYPES["TIME"]])

        ev = codec.encode_event({"node": 7, "seq": 1, "t": 4000, "type": "zone.captured", "team": 2,
                                 "data": {"zone": "alpha"}})
        pkt = node_packet(key, game["id"], 7, 0, 2, "EVENT", ev, ack=True)
        self.host.hear(pkt)
        self.host.hear(pkt)  # the relayed copy
        acks = []
        for air in self.host.transmitted_all(0.5):
            hdr, plain = packet_decrypt(air, epoch, key)
            if hdr.type == MESSAGE_TYPES["ACK"]:
                acks.append(ack_decode(plain))
        self.assertEqual(acks, [{"ack_node": 7, "ack_seq": 0}])
        log = self.ctrl.log(game["id"])
        captured = [e for e in log if e["type"] == "zone.captured"]
        self.assertEqual(len(captured), 1)
        self.assertEqual((captured[0]["team"], captured[0]["data"], captured[0]["epoch"]),
                         ("blue", {"zone": "alpha"}, 2))
        self.assertTrue(any(m["type"] == "event" and m["event"]["type"] == "zone.captured"
                            for m in self.messages))
        nodes = {n["node_id"]: n for n in self.ctrl.nodes()}
        self.assertEqual(nodes[7]["rssi"], -42)

        # A node command goes out as a unicast CMD.
        result = self.ctrl.send_node_cmd(7, "message", {"text": "hold"})
        # (A TIME repeating the start may be on the air too, RFC 0001 Amendment 19: only the CMD is looked at.)
        [air] = [a for a in self.host.transmitted_all()
                 if packet_decrypt(a, epoch, key)[0].type == MESSAGE_TYPES["CMD"]]
        hdr, plain = packet_decrypt(air, epoch, key)
        self.assertEqual(hdr.seq, result["seq"])
        self.assertEqual(cmd_decode(plain), {"cmd": 5, "params": {"text": "hold"}, "dest": 7})
        self.ctrl.end_game(game["id"])
        self.assertTrue(wait_for(lambda: (self.modem.status or {}).get("configured") is False, 3))


if __name__ == "__main__":
    unittest.main()
