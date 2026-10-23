# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Capability proxy protocol v1 against protocol/vectors/capability_proxy.yaml (also checked by
core/tests/test_proxy.c and firmware/esp32/test/test_proxy_codec.c). Every vector is checked."""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from atalaia_sim import capability_proxy as cp

VECTORS = yaml.safe_load((Path(__file__).resolve().parents[2] / "protocol" / "vectors" /
                          "capability_proxy.yaml").read_text(encoding="utf-8"))
KINDS = {"evt": cp.EVT, "cmd": cp.CMD}
RELAY = VECTORS["pod_relay"]  # field and pair frames through the pod, IDENT keys 6-8 (PE24-100)


class FramingTests(unittest.TestCase):
    def test_crc_check_value(self) -> None:
        self.assertEqual(cp.crc16(bytes.fromhex(VECTORS["crc"]["data"])), VECTORS["crc"]["crc"])
        self.assertEqual(VECTORS["crc"]["crc"], 0x29B1)

    def test_every_frame(self) -> None:
        rows = [(cp.IDENT, v) for v in VECTORS["ident"]]
        rows += [(KINDS[k], v) for k in ("evt", "cmd") for v in VECTORS[k]]
        rows += [(cp.ACK, v) for v in VECTORS["ack"]]
        rows += [(v["type"], v) for v in VECTORS["radio"]]
        rows += [(cp.IDENT, v) for v in RELAY["ident"]]
        rows += [(v["type"], v) for v in RELAY["radio"]]
        self.assertGreaterEqual(len(rows), 27)
        for frame_type, v in rows:
            with self.subTest(v["name"]):
                payload, frame = bytes.fromhex(v["payload"]), bytes.fromhex(v["frame"])
                self.assertEqual(cp.encode_frame(frame_type, payload), frame)
                self.assertEqual(cp.FrameDecoder().feed(frame), [(frame_type, payload)])
                dec = cp.FrameDecoder()
                got = [f for b in frame for f in dec.feed(bytes([b]))]
                self.assertEqual(got, [(frame_type, payload)])

    def test_stream_resynchronises(self) -> None:
        st = VECTORS["stream"]
        dec = cp.FrameDecoder()
        data = bytes.fromhex(st["bytes"])
        frames = dec.feed(data[:10]) + dec.feed(data[10:])
        self.assertEqual(frames, [(f["type"], bytes.fromhex(f["payload"])) for f in st["frames"]])
        self.assertEqual(dec.crc_errors, st["crc_errors"])
        self.assertEqual(dec.length_errors, st["length_errors"])

    def test_frame_limits(self) -> None:
        with self.assertRaises(cp.ProxyError):
            cp.encode_frame(cp.EVT, bytes(257))
        self.assertEqual(len(cp.encode_frame(cp.EVT, bytes(256))), 262)


class PayloadTests(unittest.TestCase):
    def test_ident(self) -> None:
        for v in VECTORS["ident"] + RELAY["ident"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                self.assertEqual(cp.encode_ident(v["fields"]), payload)
                self.assertEqual(cp.decode_ident(payload), v["fields"])

    def test_evt_and_cmd(self) -> None:
        for key, kind in KINDS.items():
            for v in VECTORS[key]:
                with self.subTest(v["name"]):
                    payload = bytes.fromhex(v["payload"])
                    self.assertEqual(cp.encode_msg(kind, v["fields"]), payload)
                    self.assertEqual(cp.decode_msg(kind, payload), v["fields"])

    def test_ack(self) -> None:
        for v in VECTORS["ack"]:
            with self.subTest(v["name"]):
                self.assertEqual(cp.encode_ack(v["seq"]).hex(), v["payload"])
                self.assertEqual(cp.decode_ack(bytes.fromhex(v["payload"])), v["seq"])

    def test_radio_payloads(self) -> None:
        by_name = {v["name"]: v for v in VECTORS["radio"]}
        f = by_name["rx"]["fields"]
        self.assertEqual(cp.radio_rx(bytes.fromhex(f["header"]), bytes.fromhex(f["payload"]), f["rssi"],
                                     f["snr"], f["epoch"]).hex(), by_name["rx"]["payload"])
        f = by_name["tx"]["fields"]
        self.assertEqual(cp.radio_tx(bytes.fromhex(f["header"]), bytes.fromhex(f["payload"])).hex(),
                         by_name["tx"]["payload"])
        f = by_name["tx_ack"]["fields"]
        self.assertEqual(cp.radio_tx_ack(f["seq"], f["status"]).hex(), by_name["tx_ack"]["payload"])
        f = by_name["cmd_configure"]["fields"]
        configure = cp.radio_configure(f["game_id"], f["node_id"], f["epoch"], f["max_hops"],
                                       f["channel_hz"], bytes.fromhex(f["key"]))
        self.assertEqual(len(configure), 28)  # opcode + the modem's 27 bytes
        self.assertEqual(configure.hex(), by_name["cmd_configure"]["payload"])
        self.assertEqual(by_name["cmd_ident"]["payload"], "07")
        self.assertEqual(bytes.fromhex(by_name["status"]["payload"]).decode(),
                         by_name["status"]["fields"]["json"])
        f = by_name["error"]["fields"]
        self.assertEqual(cp.radio_error(f["code"], f["message"]).hex(), by_name["error"]["payload"])
        f = by_name["cmd_measure"]["fields"]
        self.assertEqual(cp.radio_measure(f["channel_hz"], f["dwell_ms"], f["flags"] == 1).hex(),
                         by_name["cmd_measure"]["payload"])
        self.assertEqual(cp.radio_noise(by_name["noise"]["fields"]).hex(), by_name["noise"]["payload"])
        # The radio frames are the modem's frame types plus 3, NOISE (0x0B) included.
        for v in VECTORS["radio"]:
            self.assertIn(v["type"], range(cp.RADIO_RX, cp.RADIO_NOISE + 1))
        self.assertEqual(cp.describe(cp.RADIO_NOISE), "RADIO_NOISE")

    def test_relay_payloads(self) -> None:
        """RADIO_FIELD_TX/RX/ACK: the modem's FIELD_TX/RX/ACK (0x09-0x0B) plus 3, as they are."""
        for v in RELAY["radio"]:
            with self.subTest(v["name"]):
                f = v["fields"]
                self.assertIn(v["type"], range(cp.RADIO_FIELD_TX, cp.RADIO_FIELD_ACK + 1))
                if v["type"] == cp.RADIO_FIELD_TX:
                    got = cp.radio_field_tx(f["id"], bytes.fromhex(f["frame"]))
                elif v["type"] == cp.RADIO_FIELD_RX:
                    got = cp.radio_field_rx(bytes.fromhex(f["frame"]), f["rssi"], f["snr"])
                else:
                    got = cp.radio_field_ack(f["id"], f["status"])
                self.assertEqual(got.hex(), v["payload"])
        self.assertEqual(cp.describe(cp.RADIO_FIELD_ACK), "RADIO_FIELD_ACK")
        # An older pod's IDENT says nothing of the flags; this one says each.
        self.assertNotIn("measure", cp.decode_ident(bytes.fromhex(VECTORS["ident"][0]["payload"])))
        flags = cp.decode_ident(bytes.fromhex(RELAY["ident"][1]["payload"]))
        self.assertEqual((flags["measure"], flags["field_frames"], flags["pair_frames"]),
                         (False, True, True))

    def test_invalid(self) -> None:
        self.assertGreaterEqual(len(VECTORS["invalid"]), 20)
        for v in VECTORS["invalid"] + RELAY["invalid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["payload"])
                with self.assertRaises(cp.ProxyError):
                    if v["type"] == cp.IDENT:
                        cp.decode_ident(payload)
                    elif v["type"] == cp.ACK:
                        cp.decode_ack(payload)
                    else:
                        cp.decode_msg(v["type"], payload)

    def test_unknown_keys_are_skipped(self) -> None:
        sk = VECTORS["skipped_keys"]
        self.assertEqual(cp.decode_ident(bytes.fromhex(sk["ident"]["payload"]))["fw_version"],
                         sk["ident"]["fw_version"])
        same = next(v for v in VECTORS["evt"] if v["name"] == sk["evt"]["same_as"])
        self.assertEqual(cp.decode_msg(cp.EVT, bytes.fromhex(sk["evt"]["payload"])), same["fields"])

    def test_encode_refuses(self) -> None:
        good = VECTORS["evt"][0]["fields"]
        for bad in ({**good, "cap_id": "Btn"}, {**good, "seq": 70000}, {**good, "data": [1]},
                    {**good, "event": "x" * 24}):
            with self.subTest(bad):
                with self.assertRaises(cp.ProxyError):
                    cp.encode_msg(cp.EVT, bad)
        ident = VECTORS["ident"][0]["fields"]
        for bad in ({**ident, "battery_pct": 101}, {**ident, "capabilities": [{"id": "x"}]},
                    {**ident, "protocol_version": 2}, {**ident, "has_radio": 1},
                    {**ident, "capabilities": [{"id": "b", "type": "t"}] * 17},
                    {**ident, "measure": 1}, {**ident, "pair_frames": "yes"}):
            with self.subTest(bad):
                with self.assertRaises(cp.ProxyError):
                    cp.encode_ident(bad)


if __name__ == "__main__":
    unittest.main()
