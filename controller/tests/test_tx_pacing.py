# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller's TX pacing (decision SL-13; the relay study's H_paced): the controller's own frames
leave one at a time, controller_pace_ms apart, through a fake modem and a clock the test moves.

    cd controller && python -m unittest tests.test_tx_pacing   (or discover -s tests)
"""

from __future__ import annotations

import tempfile
import unittest

from support import CORE, FakeModem, config
from atalaia_controller.config import ConfigError
from atalaia_controller.engine import PACE_QUEUE_MAX, Controller, ModemTransport
from atalaia_controller.store import Store
from atalaia_sim.packet import cmd_decode
from atalaia_sim.protocol import MESSAGE_TYPES

KEY = bytes(range(16))
CMD, TIME, ACK = MESSAGE_TYPES["CMD"], MESSAGE_TYPES["TIME"], MESSAGE_TYPES["ACK"]


class TransportCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(f"{self.tmp.name}/t.db")
        self.modem = FakeModem()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def transport(self, pace_ms=800, **kw) -> ModemTransport:
        return ModemTransport(self.modem, self.store, 7, 0, 2, 869_525_000, KEY, pace_ms=pace_ms, **kw)

    def send(self, tr, msg_type=CMD, now=0, payload=b"x"):
        return tr.send(msg_type, payload, priority=2, ack_req=False, hop_limit=2, now_ms=now)

    def seqs(self):
        return [h.seq for h, _ in self.modem.sent]


class SpacingTests(TransportCase):
    def test_the_first_frame_leaves_at_once_the_rest_wait_their_gap(self):
        tr = self.transport()
        self.assertEqual([self.send(tr, now=0) for _ in range(3)], [0, 1, 2])
        self.assertEqual(self.seqs(), [0])
        self.assertEqual(tr.queued, 2)
        tr.pump(799)
        self.assertEqual(self.seqs(), [0])
        tr.pump(800)
        self.assertEqual(self.seqs(), [0, 1])
        tr.pump(1599)
        self.assertEqual(self.seqs(), [0, 1])
        tr.pump(1600)
        self.assertEqual(self.seqs(), [0, 1, 2])
        self.assertEqual(tr.queued, 0)

    def test_one_frame_per_pump_even_when_the_clock_jumps(self):
        tr = self.transport()
        for _ in range(4):
            self.send(tr)
        tr.pump(60_000)
        self.assertEqual(self.seqs(), [0, 1])  # the gap runs from the hand-over, not from the due time
        tr.pump(60_800)
        self.assertEqual(self.seqs(), [0, 1, 2])

    def test_an_idle_queue_sends_at_once_again_after_the_gap(self):
        tr = self.transport()
        self.send(tr, now=0)
        self.send(tr, now=5000)  # long after the gap: no wait
        self.assertEqual(self.seqs(), [0, 1])
        self.send(tr, now=5100)  # inside the new gap
        self.assertEqual(self.seqs(), [0, 1])

    def test_the_gap_runs_from_the_modems_tx_ack(self):
        tr = self.transport()
        self.send(tr, now=0)
        self.send(tr, now=0)
        tr.tx_done(0, 350)  # on the air till 350 ms: the next may go at 1150
        tr.pump(800)
        self.assertEqual(self.seqs(), [0])
        tr.pump(1149)
        self.assertEqual(self.seqs(), [0])
        tr.pump(1150)
        self.assertEqual(self.seqs(), [0, 1])

    def test_a_tx_ack_of_another_frame_changes_nothing(self):
        tr = self.transport()
        self.send(tr, now=0)
        self.send(tr, now=0)
        tr.tx_done(99, 700)
        tr.pump(800)
        self.assertEqual(self.seqs(), [0, 1])

    def test_a_lost_tx_ack_does_not_stall_the_queue(self):
        tr = self.transport()
        self.send(tr, now=0)
        self.send(tr, now=0)
        tr.pump(800)  # no TX_ACK ever came: the gap from the hand-over is enough
        self.assertEqual(self.seqs(), [0, 1])

    def test_zero_is_no_pacing(self):
        tr = self.transport(pace_ms=0)
        for _ in range(5):
            self.send(tr)
        self.assertEqual(self.seqs(), [0, 1, 2, 3, 4])
        self.assertEqual(tr.queued, 0)


class OrderAndPriorityTests(TransportCase):
    def test_every_kind_of_frame_waits_in_one_fifo(self):
        # H_paced has no priorities: an ACK, a TIME beacon and a CMD take their turn as they came.
        tr = self.transport()
        for kind in (CMD, ACK, TIME, CMD, ACK):
            self.send(tr, kind)
        for t in range(0, 4000, 800):
            tr.pump(t)
        self.assertEqual([h.type for h, _ in self.modem.sent], [CMD, ACK, TIME, CMD, ACK])
        self.assertEqual(self.seqs(), [0, 1, 2, 3, 4])

    def test_the_header_keeps_what_the_caller_asked(self):
        tr = self.transport()
        tr.send(CMD, b"p", priority=3, ack_req=True, hop_limit=3, now_ms=0)
        tr.send(TIME, b"q", priority=1, ack_req=False, hop_limit=2, now_ms=0)
        tr.pump(800)
        (h0, p0), (h1, p1) = self.modem.sent
        self.assertEqual((h0.hop_limit, (h0.version_flags >> 3) & 3, bool(h0.version_flags & 4), p0), (3, 3, True, b"p"))
        self.assertEqual((h1.hop_limit, (h1.version_flags >> 3) & 3, bool(h1.version_flags & 4), p1), (2, 1, False, b"q"))


class QueueLimitTests(TransportCase):
    def test_a_full_queue_drops_the_new_frame_and_counts_it(self):
        tr = self.transport()
        got = [self.send(tr) for _ in range(1 + PACE_QUEUE_MAX + 2)]
        self.assertEqual(got[:1 + PACE_QUEUE_MAX], list(range(1 + PACE_QUEUE_MAX)))
        self.assertEqual(got[1 + PACE_QUEUE_MAX:], [None, None])
        self.assertEqual((tr.queued, tr.queue_dropped, tr.refused), (PACE_QUEUE_MAX, 2, 2))
        # a dropped frame leaves no hole in the seqs
        tr.pump(800)
        self.assertEqual(self.send(tr, now=800), 1 + PACE_QUEUE_MAX)

    def test_the_queue_length_is_a_setting(self):
        tr = self.transport(queue_max=2)
        self.assertEqual([self.send(tr) for _ in range(5)], [0, 1, 2, None, None])

    def test_the_default_is_the_modems_own_queue(self):
        self.assertEqual(PACE_QUEUE_MAX, 8)  # RADIO_TX_QUEUE_LEN, the study's TX_QUEUE


class LinkTests(TransportCase):
    def test_a_modem_that_is_down_refuses_at_once(self):
        tr = self.transport()
        self.modem.state = "down"
        self.assertIsNone(self.send(tr))
        self.assertEqual((tr.refused, tr.queued), (1, 0))

    def test_the_link_goes_down_while_frames_wait(self):
        tr = self.transport()
        for _ in range(3):
            self.send(tr)
        self.modem.state = "down"
        tr.pump(800)
        tr.pump(1600)
        self.assertEqual((self.seqs(), tr.queued, tr.refused), ([0], 0, 2))

    def test_discard_drops_what_waits_and_counts_it(self):
        tr = self.transport()
        for kind in (CMD, CMD, ACK, TIME):
            self.send(tr, kind)
        self.assertEqual(tr.discard(), 2)  # the CMD and the TIME go, the ACK stays
        self.assertEqual((tr.queued, tr.queue_dropped, self.seqs()), (1, 2, [0]))
        tr.flush()
        self.assertEqual([h.type for h, _ in self.modem.sent], [CMD, ACK])

    def test_flush_hands_everything_over_in_order_without_the_gap(self):
        tr = self.transport()
        for _ in range(5):
            self.send(tr)
        self.assertEqual(tr.flush(), 4)
        self.assertEqual(self.seqs(), [0, 1, 2, 3, 4])
        self.assertEqual((tr.queued, tr.flush()), (0, 0))

    def test_seq_wrap_sends_the_old_epoch_first(self):
        tr = self.transport()
        order = []
        configure = self.modem.configure
        self.modem.configure = lambda *a: (order.append(("configure", a[2])), configure(*a))
        send_packet = self.modem.send_packet
        self.modem.send_packet = lambda h, p: (order.append(("tx", h.seq)), send_packet(h, p))[1]
        tr._next = 0xFFFE
        self.send(tr)  # 0xFFFE leaves
        self.send(tr)  # 0xFFFF waits for its gap
        self.send(tr)  # the seqs of epoch 1 are spent: 0xFFFF goes first, then epoch 2
        self.assertEqual(tr.epoch, 2)
        self.assertEqual(order, [("tx", 0xFFFE), ("tx", 0xFFFF), ("configure", 2)])
        self.assertEqual(tr.queued, 1)  # epoch 2's seq 0, waiting its gap


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name, controller_pace_ms=800)
        self.t = 1000.0
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, clock=lambda: self.t)

    def tearDown(self):
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def advance(self, seconds):
        self.t += seconds
        self.ctrl.tick()

    def create(self):
        return self.ctrl.create_game({"name": "S", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"],
                                      "assignments": {"4": "zone", "5": "zone"}})

    def kinds(self):
        names = {v: k for k, v in MESSAGE_TYPES.items()}
        return [names[h.type] for h, _ in self.modem.sent]


class EngineTests(EngineCase):
    def test_pacing_is_off_by_default_and_the_example_names_800_as_the_candidate(self):
        from atalaia_controller.config import Config
        self.assertEqual(Config().controller_pace_ms, 0)  # off until the field test decides
        with open(__file__.rsplit("/tests/", 1)[0] + "/controller.example.toml") as f:
            text = f.read()
            self.assertIn("controller_pace_ms = 0", text)
            self.assertIn("800", text)

    def test_bad_values_are_refused(self):
        for bad in (-1, 10_001):
            with self.assertRaises(ConfigError):
                config(self.tmp.name, controller_pace_ms=bad)

    def test_start_sends_the_cmd_then_the_time_beacon_a_gap_later(self):
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        self.assertEqual(self.kinds(), ["CMD"])
        self.advance(0.5)
        self.assertEqual(self.kinds(), ["CMD"])
        self.advance(0.31)
        self.assertEqual(self.kinds(), ["CMD", "TIME"])
        self.assertEqual([h.seq for h, _ in self.modem.sent], [0, 1])

    def test_a_modem_tx_ack_moves_the_gap(self):
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        self.advance(0.5)
        self.ctrl._on_tx_ack(0, "ok")  # on the air till now: the next at +0.8 s from here
        self.advance(0.5)
        self.assertEqual(self.kinds(), ["CMD"])
        self.advance(0.31)
        self.assertEqual(self.kinds(), ["CMD", "TIME"])

    def test_commands_to_boxes_are_paced_too(self):
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        for node in (4, 5):
            self.ctrl.send_node_cmd(node, "message", {"text": "hi"})
        self.assertEqual(self.kinds(), ["CMD"])
        for _ in range(40):
            self.advance(0.1)
        cmds = [cmd_decode(p) for h, p in self.modem.sent if h.type == CMD]
        self.assertEqual([c["cmd"] for c in cmds], [0, 5, 5])  # START, then the two messages
        self.assertEqual([c.get("dest") for c in cmds[1:]], [4, 5])

    def test_the_end_of_the_game_drops_what_waits_and_sends_its_own_frames_before_the_key_goes(self):
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)  # START leaves, its TIME waits
        for node in (4, 5):
            self.ctrl.send_node_cmd(node, "message", {"text": "hi"})
        self.assertEqual(self.ctrl.transport.queued, 3)
        self.ctrl.transport.send(ACK, b"a", priority=1, ack_req=False, hop_limit=2, now_ms=self.ctrl.now_ms())
        sent_at_clear = []
        clear = self.modem.clear
        self.modem.clear = lambda: (sent_at_clear.append(len(self.modem.sent)), clear())
        self.advance(0.1)
        self.ctrl.end_game(gid, "done")
        self.assertEqual(sent_at_clear, [len(self.modem.sent)])  # everything was handed over before CLEAR
        cmds = [cmd_decode(p)["cmd"] for h, p in self.modem.sent if h.type == CMD]
        self.assertEqual(cmds, [0, 3])  # START, then END: the stale messages are gone
        self.assertEqual(self.kinds(), ["CMD", "ACK", "CMD", "TIME"])  # the box's ACK, then END and its TIME
        self.assertEqual(self.modem.cleared, 1)
        self.assertIsNone(self.ctrl.status()["tx_queue"])  # no game: no transport

    def test_status_shows_the_queue(self):
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        self.assertEqual(self.ctrl.status()["tx_queue"], {"queued": 1, "dropped": 0, "pace_ms": 800})

    def test_pace_zero_keeps_the_old_burst(self):
        self.ctrl.stop()
        self.store.close()
        self.cfg.controller_pace_ms = 0  # the default
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, clock=lambda: self.t)
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        self.assertEqual(self.kinds(), ["CMD", "TIME"])


if __name__ == "__main__":
    unittest.main()
