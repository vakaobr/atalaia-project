# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the FieldController: TIME beacons, score merge, event log.

    cd simulator && python -m unittest discover -s tests

These tests do NOT require the C core library.
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim.field_controller import (
    GAME_ENDED,
    GAME_PAUSED,
    GAME_RUNNING,
    GAME_WAITING,
    FieldController,
)
from atalaia_sim.packet import (
    hello_encode,
    state_encode,
    time_decode,
)
from atalaia_sim.protocol import MESSAGE_TYPES
from atalaia_sim.radio_model import RadioConfig, RadioModel


def _has_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        return True
    except ImportError:
        return False


if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and not _has_crypto():
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but cryptography is not available")


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class FieldControllerLifecycleTests(unittest.TestCase):
    """Test game lifecycle: start, pause, end."""

    def setUp(self):
        config = RadioConfig(loss_rate=0.0, game_id=1)
        self.radio = RadioModel(config=config, rng=random.Random(1))
        self.ctrl = FieldController(
            radio=self.radio,
            game_id=1,
            teams=["red", "blue"],
            beacon_interval_ms=30_000,
        )

    def test_initial_state(self):
        self.assertEqual(self.ctrl.game_state, GAME_WAITING)
        self.assertEqual(self.ctrl.game_time_ms, 0)

    def test_start_game(self):
        self.ctrl.start_game(duration_ms=600_000, now_ms=0)
        self.assertEqual(self.ctrl.game_state, GAME_RUNNING)
        self.assertEqual(self.ctrl.duration_ms, 600_000)

    def test_pause_game(self):
        self.ctrl.start_game(now_ms=0)
        self.ctrl.pause_game(now_ms=1000)
        self.assertEqual(self.ctrl.game_state, GAME_PAUSED)

    def test_end_game(self):
        self.ctrl.start_game(now_ms=0)
        self.ctrl.end_game(now_ms=5000)
        self.assertEqual(self.ctrl.game_state, GAME_ENDED)


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class TimeBeaconTests(unittest.TestCase):
    """Test TIME beacon sending and timing."""

    def test_beacon_sent_on_start(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, beacon_interval_ms=1000)
        ctrl.register_node(1, "node-1", "shell")

        ctrl.start_game(now_ms=0)
        # There should be pending packets (TIME beacon).
        self.assertTrue(len(radio.pending) > 0)

    def test_beacon_auto_sent_at_interval(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, beacon_interval_ms=1000)
        ctrl.register_node(1, "node-1", "shell")

        ctrl.start_game(now_ms=0)
        # Tick past the beacon interval.
        ctrl.tick(1100)
        # Another beacon should have been sent.
        self.assertGreaterEqual(ctrl.seq, 3)  # start cmd + initial beacon + auto beacon

    def test_beacon_received_by_nodes(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, beacon_interval_ms=5000)
        ctrl.register_node(1, "node-1", "shell")

        ctrl.start_game(now_ms=0)
        deliveries = ctrl.tick(100)
        # Node 1 should receive the CMD and TIME beacon.
        node_1_deliveries = [d for d in deliveries if d[0] == 1]
        self.assertGreater(len(node_1_deliveries), 0)


class _Recorder:
    """A transport that only notes what the controller sends: (ms, type, payload)."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, int, bytes]] = []
        self.seq = 0

    def send(self, msg_type, payload, *, priority, ack_req, hop_limit, now_ms):
        self.sent.append((now_ms, msg_type, payload))
        self.seq += 1
        return self.seq - 1


class StateRepeatTests(unittest.TestCase):
    """A start, pause or resume is repeated as TIME beacons for ten seconds (RFC 0001 Amendment 19),
    so a lost frame costs a second or two, not the 30 s to the next beacon."""

    TIME = MESSAGE_TYPES["TIME"]
    CMD = MESSAGE_TYPES["CMD"]

    def make(self):
        rec = _Recorder()
        ctrl = FieldController(transport=rec, game_id=1, teams=["red", "blue"], beacon_interval_ms=30_000)
        return ctrl, rec

    def run_to(self, ctrl, start_ms, end_ms, step=100):
        for t in range(start_ms, end_ms + 1, step):
            ctrl.tick(t)

    def times(self, rec, kind=None):
        return [(ms, time_decode(p)["game_state"]) for ms, t, p in rec.sent if t == self.TIME]

    def test_start_sends_cmd_and_time_at_once_then_four_time_repeats(self):
        ctrl, rec = self.make()
        ctrl.start_game(now_ms=0)
        self.assertEqual([t for _, t, _ in rec.sent], [self.CMD, self.TIME])
        self.run_to(ctrl, 100, 12_000)
        # +1.0, +2.5, +5.0 and +10.0 s: all four, TIME alone, all saying "running".
        self.assertEqual(self.times(rec), [(0, GAME_RUNNING), (1000, GAME_RUNNING), (2500, GAME_RUNNING),
                                           (5000, GAME_RUNNING), (10000, GAME_RUNNING)])
        self.assertEqual(sum(1 for _, t, _ in rec.sent if t == self.CMD), 1)  # the CMD is not repeated
        self.assertEqual(ctrl.state_repeats_sent, 4)

    def test_the_30_second_beacon_goes_on_afterwards(self):
        ctrl, rec = self.make()
        ctrl.start_game(now_ms=0)
        self.run_to(ctrl, 100, 41_000)
        beacons = [ms for ms, _ in self.times(rec)]
        self.assertEqual(beacons, [0, 1000, 2500, 5000, 10000, 40000])  # 30 s after the last repeat

    def test_a_pause_replaces_the_repeats_of_the_start(self):
        ctrl, rec = self.make()
        ctrl.start_game(now_ms=0)
        self.run_to(ctrl, 100, 1500)
        ctrl.pause_game(now_ms=1500)
        self.run_to(ctrl, 1600, 12_000)
        states = self.times(rec)
        # After the pause no TIME says "running" any more: a repeat of the start never undoes it.
        self.assertTrue(all(state == GAME_PAUSED for ms, state in states if ms >= 1500), states)
        self.assertEqual([ms for ms, state in states if state == GAME_PAUSED], [1500, 2500, 4000, 6500, 11500])

    def test_resume_is_repeated_too(self):
        ctrl, rec = self.make()
        ctrl.start_game(now_ms=0)
        self.run_to(ctrl, 100, 11_000)
        ctrl.pause_game(now_ms=11_000)
        self.run_to(ctrl, 11_100, 30_000)
        ctrl.resume_game(now_ms=30_000)
        self.run_to(ctrl, 30_100, 41_000)
        running = [ms for ms, state in self.times(rec) if state == GAME_RUNNING and ms >= 30_000]
        self.assertEqual(running, [30_000, 31_000, 32_500, 35_000, 40_000])

    def test_an_end_is_not_repeated_by_time(self):
        ctrl, rec = self.make()
        ctrl.start_game(now_ms=0)
        self.run_to(ctrl, 100, 500)
        ctrl.end_game(now_ms=500)
        n = len(rec.sent)
        self.run_to(ctrl, 600, 20_000)
        self.assertEqual(len(rec.sent), n)  # GAME_OVER (field frames) repeats the end, on the controller's side

    def test_a_late_tick_sends_one_beacon_not_a_burst(self):
        ctrl, rec = self.make()
        ctrl.start_game(now_ms=0)
        ctrl.tick(8_000)  # the loop stalled: three repeats are overdue
        self.assertEqual(len(self.times(rec)), 2)  # the start's TIME and one repeat
        ctrl.tick(10_100)
        self.assertEqual(len(self.times(rec)), 3)  # the last one, due at +10 s

    def test_the_repeat_timing_can_be_turned_off(self):
        ctrl, rec = self.make()
        ctrl.state_repeat_gaps_ms = ()
        ctrl.start_game(now_ms=0)
        self.run_to(ctrl, 100, 12_000)
        self.assertEqual(len(self.times(rec)), 1)


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class ScoreMergeTests(unittest.TestCase):
    """Test conflict-free score merging."""

    def setUp(self):
        config = RadioConfig(loss_rate=0.0)
        self.radio = RadioModel(config=config, rng=random.Random(1))
        self.ctrl = FieldController(
            radio=self.radio,
            teams=["red", "blue"],
        )

    def test_merge_by_max(self):
        self.ctrl.merge_scores(1, {"red": 5, "blue": 3})
        self.ctrl.merge_scores(1, {"red": 3, "blue": 7})
        scores = self.ctrl.total_scores
        self.assertEqual(scores["red"], 5)  # max(5, 3)
        self.assertEqual(scores["blue"], 7)  # max(3, 7)

    def test_merge_from_multiple_nodes(self):
        self.ctrl.merge_scores(1, {"red": 5})
        self.ctrl.merge_scores(2, {"red": 3})
        scores = self.ctrl.total_scores
        self.assertEqual(scores["red"], 8)  # 5 from node-1 + 3 from node-2

    def test_merge_idempotent(self):
        self.ctrl.merge_scores(1, {"red": 10})
        self.ctrl.merge_scores(1, {"red": 10})
        scores = self.ctrl.total_scores
        self.assertEqual(scores["red"], 10)  # not 20

    def test_merge_ignores_non_int(self):
        self.ctrl.merge_scores(1, {"red": "five"})
        scores = self.ctrl.total_scores
        self.assertEqual(scores.get("red", 0), 0)


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class StateReceptionTests(unittest.TestCase):
    """Test that STATE messages from nodes are processed."""

    def test_state_updates_scores(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, teams=["red", "blue"])
        ctrl.register_node(1, "node-1", "shell")

        # Node 1 sends a STATE with score counters.
        payload = state_encode({
            "node_id": 1,
            "battery": 90,
            "counters": {"red": 10, "blue": 5},
        })
        radio.send(
            from_node=1,
            payload=payload,
            msg_type=MESSAGE_TYPES["STATE"],
            source=1,
            seq=1,
            now_ms=0,
        )
        ctrl.tick(100)

        scores = ctrl.total_scores
        self.assertEqual(scores["red"], 10)
        self.assertEqual(scores["blue"], 5)


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class HelloReceptionTests(unittest.TestCase):
    """Test that HELLO messages register nodes."""

    def test_hello_registers_node(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio)
        radio.add_node(5)  # Add to radio model but not to controller.

        payload = hello_encode({"node_name": "alpha", "role": "shell"})
        radio.send(
            from_node=5,
            payload=payload,
            msg_type=MESSAGE_TYPES["HELLO"],
            source=5,
            seq=1,
            now_ms=0,
        )
        ctrl.tick(100)

        self.assertIn(5, ctrl.nodes)
        self.assertEqual(ctrl.nodes[5].name, "alpha")
        self.assertEqual(ctrl.nodes[5].role, "shell")


if __name__ == "__main__":
    unittest.main()
