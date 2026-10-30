# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The per-source replay window (RFC 0001 Amendment 23, decision SR-20) and the controller's use of it.

    cd simulator && python -m unittest discover -s tests

The Python port passes protocol/vectors/replay_window.json, as the C core (core/tests/test_replay.c)
and the Dart port (app/test/radio/replay_test.dart) do.
"""

from __future__ import annotations

import json
import os
import unittest

from atalaia_sim.field_controller import FieldController
from atalaia_sim.packet import Header, vf_make
from atalaia_sim.protocol import MESSAGE_TYPES
from atalaia_sim.replay import DUPLICATE, FRESH, TOO_OLD, WIDTH, ReplayWindow, counter

VECTORS = os.path.join(os.path.dirname(__file__), "..", "..", "protocol", "vectors", "replay_window.json")


class ReplayWindowTests(unittest.TestCase):
    def test_shared_vectors(self):
        with open(VECTORS) as f:
            vectors = json.load(f)
        self.assertEqual(vectors["width"], WIDTH)
        for case in vectors["cases"]:
            with self.subTest(case["name"]):
                w = ReplayWindow()
                for step, (epoch, seq, verdict) in enumerate(case["steps"]):
                    self.assertEqual(w.accept(counter(epoch, seq)), verdict, f"step {step}")

    def test_check_changes_nothing(self):
        w = ReplayWindow()
        self.assertEqual(w.accept(100), FRESH)
        self.assertEqual(w.check(5000), FRESH)
        self.assertEqual(w.high, 100)
        self.assertEqual(w.check(100), DUPLICATE)
        self.assertEqual(w.check(36), TOO_OLD)


def _header(source: int, seq: int, kind: str = "EVENT") -> Header:
    return Header(vf_make(1, 1, 0, 1), 1, source, seq, 2, MESSAGE_TYPES[kind])


class _Sink:
    seq = 0

    def send(self, msg_type, payload, *, priority, ack_req, hop_limit, now_ms):
        self.seq += 1
        return self.seq


class ControllerReplayTests(unittest.TestCase):
    def setUp(self):
        self.ctrl = FieldController(transport=_Sink(), teams=["red", "blue"], node_id=0,
                                    wall_clock=lambda: 1_700_000_000.0)

    def test_a_packet_played_back_after_the_old_dedupe_time_is_refused(self):
        # FLD-1: the controller's table forgot packets after 60 s; the window does not.
        c = self.ctrl
        c.on_packet(4, _header(4, 5, "STATE"), b"\xa0", {"epoch": 1})
        self.assertEqual(c.replays_refused, 0)
        c.on_packet(4, _header(4, 5, "STATE"), b"\xa0", {"epoch": 1})  # a relayed copy
        self.assertEqual(c.replays_refused, 1)
        for seq in range(6, 80):
            c.on_packet(4, _header(4, seq, "STATE"), b"\xa0", {"epoch": 1})
        c.tick(10 * 60_000)
        c.on_packet(4, _header(4, 5, "STATE"), b"\xa0", {"epoch": 1})  # recorded, played back later
        c.on_packet(4, _header(4, 70, "STATE"), b"\xa0", {"epoch": 1})
        self.assertEqual(c.replays_refused, 3)

    def test_each_source_has_its_own_window(self):
        c = self.ctrl
        for source in range(1, 41):  # a field of 40 nodes
            c.on_packet(source, _header(source, 9, "STATE"), b"\xa0", {"epoch": 1})
        self.assertEqual(c.replays_refused, 0)
        for source in range(1, 41):
            c.on_packet(source, _header(source, 9, "STATE"), b"\xa0", {"epoch": 1})
        self.assertEqual(c.replays_refused, 40)

    def test_a_rebooted_source_is_not_a_replay(self):
        c = self.ctrl
        c.on_packet(4, _header(4, 300, "STATE"), b"\xa0", {"epoch": 1})
        c.on_packet(4, _header(4, 0, "STATE"), b"\xa0", {"epoch": 2})  # restarted seq, new epoch
        self.assertEqual(c.replays_refused, 0)
        c.on_packet(4, _header(4, 300, "STATE"), b"\xa0", {"epoch": 1})  # the old epoch's
        self.assertEqual(c.replays_refused, 1)


if __name__ == "__main__":
    unittest.main()
