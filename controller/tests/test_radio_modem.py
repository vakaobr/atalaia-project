# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The serial link: pings, the watchdog, reconnects, radio.down and radio.up (ADR-P2-4).

    cd controller && python -m unittest discover -s tests

A scripted fake modem on a fake port, with short intervals. The real modem
logic (C) is exercised by test_modem_host.py.
"""

from __future__ import annotations

import threading
import unittest

from support import FakeSerial, wait_for
from atalaia_controller import modem_framing as mf
from atalaia_controller.radio_modem import DOWN, UP, RadioModem
from atalaia_sim.packet import Header, vf_make

KEY = bytes(range(16))


class Ports:
    """A factory handing out FakeSerial ports; can be told to fail."""

    def __init__(self, mute: bool = False, lang: bool = False) -> None:
        self.mute = mute
        self.lang = lang
        self.fail = False
        self.opened: list[FakeSerial] = []
        self.lock = threading.Lock()

    def __call__(self) -> FakeSerial:
        with self.lock:
            if self.fail:
                raise OSError("no such device")
            port = FakeSerial(mute=self.mute, lang=self.lang)
            self.opened.append(port)
            return port

    @property
    def current(self) -> FakeSerial:
        return self.opened[-1]


def make(ports: Ports, **kw) -> tuple[RadioModem, list[str]]:
    states: list[str] = []
    modem = RadioModem("fake://", serial_factory=ports, ping_interval=0.05, max_missed=3,
                       reconnect_attempts=2, retry_interval=0.2, on_state=states.append, **kw)
    return modem, states


class RadioModemTests(unittest.TestCase):
    def test_connects_and_identifies(self):
        ports = Ports()
        modem, states = make(ports)
        modem.start()
        try:
            self.assertTrue(modem.wait_up(2))
            self.assertTrue(wait_for(lambda: modem.ident is not None))
            self.assertEqual(modem.ident["fw"], "atalaia-modem")
            self.assertTrue(ports.current.frames(mf.CMD, mf.CMD_IDENT))
            self.assertIn(UP, states)
        finally:
            modem.stop()

    def test_configuration_is_sent_and_resent_after_a_reconnect(self):
        ports = Ports()
        modem, _ = make(ports)
        modem.configure(0x1234, 0, 3, 2, 869_525_000, KEY)  # before start: kept for the port
        modem.start()
        try:
            self.assertTrue(modem.wait_up(2))
            first = ports.current
            self.assertEqual(first.frames(mf.CMD, mf.CMD_CONFIGURE),
                             [mf.configure_payload(0x1234, 0, 3, 2, 869_525_000, KEY)])
            modem.set_peer_epochs({7: 4})
            first.mute = True  # the modem hangs
            self.assertTrue(wait_for(lambda: len(ports.opened) >= 2, 3))
            self.assertTrue(modem.wait_up(2))
            second = ports.current
            self.assertEqual(len(second.frames(mf.CMD, mf.CMD_CONFIGURE)), 1)
            self.assertEqual(second.frames(mf.CMD, mf.CMD_SET_PEER_EPOCH), [mf.peer_epoch_payload([(7, 4)])])
            self.assertGreaterEqual(modem.reconnects, 1)
        finally:
            modem.stop()

    def test_the_screen_language_goes_to_a_modem_that_takes_it(self):
        """SET_LANG (decision MOD-2): sent after IDENT says "lang", again on every IDENT (a modem
        that rebooted has forgotten it), cleared with ""; never to a firmware without it."""
        ports = Ports(lang=True)
        modem, _ = make(ports)
        modem.set_language("pt")  # before start: kept for the port
        modem.start()
        try:
            self.assertTrue(modem.wait_up(2))
            self.assertTrue(wait_for(lambda: modem.has_language))
            first = ports.current
            self.assertTrue(wait_for(lambda: first.frames(mf.CMD, mf.CMD_SET_LANG) == [b"\x09pt"]))
            modem.set_language("zh-tw")  # while up: at once
            self.assertTrue(wait_for(lambda: first.frames(mf.CMD, mf.CMD_SET_LANG)[-1] == b"\x09zh-tw"))
            first.mute = True  # the modem hangs: reconnects, and the language goes again
            self.assertTrue(wait_for(lambda: len(ports.opened) >= 2, 3))
            self.assertTrue(modem.wait_up(2))
            self.assertTrue(wait_for(lambda: ports.current.frames(mf.CMD, mf.CMD_SET_LANG) == [b"\x09zh-tw"]))
            modem.set_language(None)  # back to the build's
            self.assertTrue(wait_for(lambda: ports.current.frames(mf.CMD, mf.CMD_SET_LANG)[-1] == b"\x09"))
            with self.assertRaises(ValueError):
                modem.set_language("zh-tw-hant")
            with self.assertRaises(ValueError):
                modem.set_language("p t")
        finally:
            modem.stop()

    def test_no_screen_language_for_an_older_modem(self):
        ports = Ports()  # its IDENT has no "lang"
        modem, _ = make(ports)
        modem.set_language("de")
        modem.start()
        try:
            self.assertTrue(modem.wait_up(2))
            self.assertTrue(wait_for(lambda: modem.ident is not None))
            self.assertFalse(modem.has_language)
            modem.set_language("pt")
            self.assertFalse(ports.current.frames(mf.CMD, mf.CMD_SET_LANG))
        finally:
            modem.stop()

    def test_three_missed_pings_reconnect(self):
        ports = Ports(mute=True)
        modem, states = make(ports)
        modem.start()
        try:
            # Never answers: never up; each port gets 3 pings, then a new port.
            self.assertTrue(wait_for(lambda: len(ports.opened) >= 2, 3))
            pings = ports.opened[0].frames(mf.CMD, mf.CMD_PING)
            self.assertEqual(len(pings), 3)
            self.assertNotIn(UP, states)
        finally:
            modem.stop()

    def test_down_after_failed_reconnects_then_up_again(self):
        ports = Ports()
        modem, states = make(ports)
        modem.start()
        try:
            self.assertTrue(modem.wait_up(2))
            ports.fail = True
            ports.current.mute = True
            self.assertTrue(wait_for(lambda: modem.state == DOWN, 5))
            self.assertFalse(modem.send_packet(Header(0x2E, 1, 0, 1, 2, 6), b"x"))
            ports.fail = False
            self.assertTrue(wait_for(lambda: modem.state == UP, 5))
            self.assertEqual([s for s in states if s in (UP, DOWN)][-2:], [DOWN, UP])
        finally:
            modem.stop()

    def test_port_read_failure_reconnects(self):
        ports = Ports()
        modem, _ = make(ports)
        modem.start()
        try:
            self.assertTrue(modem.wait_up(2))
            ports.current.close()  # unplugged
            self.assertTrue(wait_for(lambda: len(ports.opened) >= 2, 3))
            self.assertTrue(modem.wait_up(2))
        finally:
            modem.stop()

    def test_frames_reach_the_callbacks(self):
        ports = Ports()
        rx, acks, errors = [], [], []
        modem, _ = make(ports, on_rx=rx.append, on_tx_ack=lambda s, st: acks.append((s, st)),
                        on_error=lambda c, m: errors.append((c, m)))
        modem.start()
        try:
            self.assertTrue(modem.wait_up(2))
            port = ports.current
            port.push_raw(b"\x00junk\xa5")
            port.push(mf.RX, bytes([0x2E, 0x12, 0x34, 0, 7, 0, 3, 2, 2]) + b"payload" + bytes([0xC4, 5, 0, 1]))
            port.push(mf.TX_ACK, b"\x00\x05\x00")
            port.push(mf.ERROR, b"\x04needs CONFIGURE first")
            self.assertTrue(wait_for(lambda: rx and acks and errors))
            self.assertEqual((rx[0].header.game_id, rx[0].header.source, rx[0].payload, rx[0].epoch),
                             (0x1234, 7, b"payload", 1))
            self.assertEqual(acks, [(5, "ok")])
            self.assertEqual(errors, [("not_configured", "needs CONFIGURE first")])
        finally:
            modem.stop()

    def test_tx_frame(self):
        ports = Ports()
        modem, _ = make(ports)
        modem.start()
        try:
            self.assertTrue(modem.wait_up(2))
            hdr = Header(vf_make(1, 2, False, True), 0x1234, 0, 9, 2, 6)
            self.assertTrue(modem.send_packet(hdr, b"\xa1\x01\x00"))
            [tx] = ports.current.frames(mf.TX)
            self.assertEqual(tx, bytes([0x32, 0x12, 0x34, 0, 0, 0, 9, 2, 6, 0xA1, 1, 0]))
        finally:
            modem.stop()


if __name__ == "__main__":
    unittest.main()
