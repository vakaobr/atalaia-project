# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""USB modem framing on the Python side (the C side: firmware/esp32/test/test_modem_framing.c).

    cd controller && python -m unittest discover -s tests

test_modem_host.py checks the two against each other through the C host modem.
"""

from __future__ import annotations

import struct
import unittest

import support  # noqa: F401
from atalaia_controller import modem_framing as mf


class FramingTests(unittest.TestCase):
    def test_crc_known_answer(self):
        self.assertEqual(mf.crc16(b"123456789"), 0x29B1)  # CRC catalogue check value
        self.assertEqual(mf.crc16(b""), 0xFFFF)

    def test_layout(self):
        frame = mf.encode_frame(mf.CMD, b"\x01\x02\x03")
        self.assertEqual(frame[:4], bytes([0xA5, 0x05, 0x00, 0x03]))
        self.assertEqual(frame[4:7], b"\x01\x02\x03")
        self.assertEqual(struct.unpack(">H", frame[7:])[0], mf.crc16(frame[1:7]))
        with self.assertRaises(mf.FrameError):
            mf.encode_frame(mf.TX, bytes(257))

    def test_round_trip_sizes(self):
        for size in (0, 1, 200, 256):
            payload = bytes((i * 7) & 0xFF for i in range(size))
            dec = mf.FrameDecoder()
            self.assertEqual(dec.feed(mf.encode_frame(mf.RX, payload)), [(mf.RX, payload)])
            self.assertEqual(dec.dropped_bytes, 0)

    def test_byte_by_byte(self):
        stream = mf.encode_frame(mf.STATUS, b"\xaa\xbb") + mf.encode_frame(mf.ERROR, b"\xa5\xa5\xa5")
        dec = mf.FrameDecoder()
        out = []
        for b in stream:
            out += dec.feed(bytes([b]))
        self.assertEqual(out, [(mf.STATUS, b"\xaa\xbb"), (mf.ERROR, b"\xa5\xa5\xa5")])

    def test_resync_after_junk(self):
        stream = b"ESP-ROM:esp32s3\r\n" + bytes([0xA5, 0x02]) + mf.encode_frame(mf.IDENT, b"\x01\x02\x03\x04")
        dec = mf.FrameDecoder()
        self.assertEqual(dec.feed(stream), [(mf.IDENT, b"\x01\x02\x03\x04")])
        self.assertGreater(dec.dropped_bytes, 17)

    def test_bad_crc_then_good(self):
        bad = bytearray(mf.encode_frame(mf.TX, b"\x09\x09\x09"))
        bad[5] ^= 0xFF
        dec = mf.FrameDecoder()
        self.assertEqual(dec.feed(bytes(bad) + mf.encode_frame(mf.CMD, b"\x07")), [(mf.CMD, b"\x07")])
        self.assertEqual(dec.crc_errors, 1)

    def test_frame_hidden_in_rejected_bytes(self):
        dec = mf.FrameDecoder()
        self.assertEqual(dec.feed(bytes([0xA5, 0x02, 0xFF, 0xFF]) + mf.encode_frame(mf.STATUS, b"\x42")),
                         [(mf.STATUS, b"\x42")])
        self.assertEqual(dec.length_errors, 1)
        inner = mf.encode_frame(mf.TX_ACK, b"\x01\x02")
        outer = bytes([0xA5, 0x02, 0x00, len(inner)]) + inner + b"\x00\x00"
        dec = mf.FrameDecoder()
        self.assertEqual(dec.feed(outer), [(mf.TX_ACK, b"\x01\x02")])
        self.assertEqual(dec.crc_errors, 1)

    def test_payload_helpers(self):
        cfg = mf.configure_payload(0x1234, 0, 7, 2, 869_525_000, bytes(range(16)))
        self.assertEqual(len(cfg), 28)  # MODEM_CONFIGURE_LEN in modem_framing.h
        self.assertEqual(cfg[:12], bytes([2, 0x12, 0x34, 0, 0, 0, 7, 2]) + (869_525_000).to_bytes(4, "big"))
        with self.assertRaises(mf.FrameError):
            mf.configure_payload(1, 0, 1, 2, 869_525_000, b"short")
        self.assertEqual(mf.ping_payload(4242), b"\x01\x00\x00\x10\x92")
        self.assertEqual(mf.peer_epoch_payload([(9, 20)]), b"\x05\x00\x09\x00\x14")
        rx = mf.decode_rx(bytes([0x2E, 0, 1, 0, 7, 0, 3, 2, 2]) + b"hi" + bytes([0xC4, 0x05, 0x00, 0x02]))
        self.assertEqual((rx.header.source, rx.header.seq, rx.payload, rx.rssi, rx.snr, rx.epoch),
                         (7, 3, b"hi", -60, 5, 2))
        self.assertEqual(mf.decode_tx_ack(b"\x00\x08\x01"), (8, "duty_cycle"))
        self.assertEqual(mf.decode_error(b"\x06bad"), ("bad_params", "bad"))
        with self.assertRaises(mf.FrameError):
            mf.decode_rx(b"\x00" * 5)


if __name__ == "__main__":
    unittest.main()
