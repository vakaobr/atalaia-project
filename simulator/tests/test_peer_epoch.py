# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A controller names a box's epoch to the other receivers (RFC 0001 Amendment 24, decision SR-110).

    cd simulator && python -m unittest discover -s tests

The Python port passes protocol/vectors/peer_epoch.json, as the Dart port
(app/test/controller/peer_epoch_test.dart) does; the CMD it sends is protocol/vectors/cmd.json's
opcode 11.
"""

from __future__ import annotations

import json
import os
import unittest

from atalaia_sim.packet import cmd_decode as decode_cmd
from atalaia_sim.field_controller import CMD_PEER_EPOCH, FieldController
from atalaia_sim.packet import Header, vf_make
from atalaia_sim.peer_epoch import EPOCH_WINDOW, REPEAT_AFTER_MS, PeerEpochs, should_announce
from atalaia_sim.protocol import MESSAGE_TYPES

VECTORS = os.path.join(os.path.dirname(__file__), "..", "..", "protocol", "vectors", "peer_epoch.json")


class SharedVectorTests(unittest.TestCase):
    def setUp(self):
        with open(VECTORS) as f:
            self.vectors = json.load(f)

    def test_constants(self):
        self.assertEqual(self.vectors["window"], EPOCH_WINDOW)
        self.assertEqual(self.vectors["repeat_after_ms"], list(REPEAT_AFTER_MS))

    def test_the_rule(self):
        for case in self.vectors["rule"]:
            with self.subTest(case["name"]):
                self.assertEqual(should_announce(case["prior"], case["heard"], case["type"]), case["announce"])

    def test_the_sequences(self):
        for case in self.vectors["sequences"]:
            with self.subTest(case["name"]):
                tracker = PeerEpochs()
                for n, step in enumerate(case["steps"]):
                    if "heard" in step:
                        self.assertEqual(tracker.heard(*step["heard"]), step["announce"], f"step {n}")
                    else:
                        sends = [list(s) for s in tracker.due(*step["due"])]
                        self.assertEqual(sends, step["sends"], f"step {n}")


class _Sink:
    def __init__(self):
        self.seq = 0
        self.sent: list[tuple[int, bytes]] = []

    def send(self, msg_type, payload, *, priority, ack_req, hop_limit, now_ms):
        self.sent.append((msg_type, payload))
        self.seq += 1
        return self.seq

    def peer_cmds(self):
        out = []
        for msg_type, payload in self.sent:
            if msg_type == MESSAGE_TYPES["CMD"]:
                cmd = decode_cmd(payload)
                if cmd["cmd"] == CMD_PEER_EPOCH:
                    out.append(cmd["params"])
        return out


def _header(source: int, seq: int, kind: str) -> Header:
    return Header(vf_make(1, 1, 0, 1), 1, source, seq, 2, MESSAGE_TYPES[kind])


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.sink = _Sink()
        self.ctrl = FieldController(transport=self.sink, teams=["red", "blue"], node_id=0,
                                    wall_clock=lambda: 1_700_000_000.0)
        self.told: list[tuple[int, int]] = []
        self.ctrl.on_peer_epoch = lambda node, epoch: self.told.append((node, epoch))

    def hear(self, source, seq, kind, epoch):
        self.ctrl.on_packet(source, _header(source, seq, kind), b"\xa0", {"epoch": epoch})

    def test_a_box_that_lost_its_store_is_named_to_the_modem_and_the_boxes(self):
        c = self.ctrl
        self.hear(4, 0, "HELLO", 1)
        self.hear(4, 1, "STATE", 2)
        self.assertEqual(self.sink.peer_cmds(), [])
        self.hear(4, 0, "HELLO", 41000)  # the epoch store was lost: a random high epoch
        self.assertEqual(self.told, [(4, 41000)])
        self.assertEqual(self.sink.peer_cmds(), [{"src": 4, "epoch": 41000}])
        self.hear(4, 1, "HELLO", 41000)  # its retry: once is enough
        self.assertEqual(len(self.sink.peer_cmds()), 1)
        c.tick(1_000 + REPEAT_AFTER_MS[0] + 1)  # two repeats follow
        c.tick(REPEAT_AFTER_MS[1] + 1)
        c.tick(60_000)
        self.assertEqual(len(self.sink.peer_cmds()), 3)
        self.assertEqual(self.told, [(4, 41000)])

    def test_an_ordinary_box_is_not_announced(self):
        for seq in range(5):
            self.hear(4, seq, "STATE", 1)
        self.hear(4, 0, "STATE", 2)  # a reboot, heard in a STATE, inside the window
        self.hear(5, 0, "HELLO", 1)  # a new box
        self.hear(6, 0, "HELLO", 0)  # a Wi-Fi prop has no epoch
        self.assertEqual(self.sink.peer_cmds(), [])
        self.assertEqual(self.told, [])

    def test_a_restarted_box_announces_itself_with_a_hello(self):
        self.hear(4, 0, "HELLO", 3)
        self.hear(4, 0, "HELLO", 4)  # rebooted: one epoch up, but it says HELLO
        self.assertEqual(self.sink.peer_cmds(), [{"src": 4, "epoch": 4}])

    def test_an_old_recording_cannot_move_an_epoch_back(self):
        self.hear(4, 0, "HELLO", 41000)
        self.assertEqual(len(self.sink.peer_cmds()), 1)
        self.hear(4, 0, "HELLO", 7)  # a recording from an earlier life: not above what is known
        self.hear(4, 9, "STATE", 41000 - 100)
        self.assertEqual(len(self.sink.peer_cmds()), 1)
        self.assertEqual(self.told, [(4, 41000)])

    def test_a_standby_tells_its_modem_but_sends_nothing(self):
        c = self.ctrl
        c.election.follow(0)  # not the leader
        self.hear(4, 0, "HELLO", 41000)
        self.assertEqual(self.told, [(4, 41000)])
        self.assertEqual(self.sink.peer_cmds(), [])
        c.tick(60_000)
        self.assertEqual(self.sink.peer_cmds(), [])


if __name__ == "__main__":
    unittest.main()
