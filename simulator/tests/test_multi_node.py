# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Multi-node integration test: 3 nodes + controller, captures via radio.

    cd simulator && python -m unittest discover -s tests

Requires the cryptography library.  Skipped when unavailable.
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim.field_controller import (
    GAME_RUNNING,
    FieldController,
)
from atalaia_sim.packet import state_encode
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
class MultiNodeScoreTest(unittest.TestCase):
    """Three shells send STATE messages with scores; controller merges them."""

    def test_three_node_score_convergence(self):
        config = RadioConfig(loss_rate=0.0, game_id=1)
        radio = RadioModel(config=config, rng=random.Random(42))

        ctrl = FieldController(
            radio=radio,
            game_id=1,
            teams=["red", "blue"],
            beacon_interval_ms=10_000,
        )
        ctrl.register_node(1, "shell-a", "shell")
        ctrl.register_node(2, "shell-b", "shell")
        ctrl.register_node(3, "shell-c", "shell")

        ctrl.start_game(duration_ms=300_000, now_ms=0)
        ctrl.tick(100)

        # Shell A captures for red (5 points).
        payload_a = state_encode({"node_id": 1, "counters": {"red": 5}})
        radio.send(from_node=1, payload=payload_a,
                   msg_type=MESSAGE_TYPES["STATE"], source=1, seq=10, now_ms=1000)
        ctrl.tick(1100)

        # Shell B captures for blue (3 points).
        payload_b = state_encode({"node_id": 2, "counters": {"blue": 3}})
        radio.send(from_node=2, payload=payload_b,
                   msg_type=MESSAGE_TYPES["STATE"], source=2, seq=20, now_ms=2000)
        ctrl.tick(2100)

        # Shell C captures for red (7 points).
        payload_c = state_encode({"node_id": 3, "counters": {"red": 7}})
        radio.send(from_node=3, payload=payload_c,
                   msg_type=MESSAGE_TYPES["STATE"], source=3, seq=30, now_ms=3000)
        ctrl.tick(3100)

        scores = ctrl.total_scores
        self.assertEqual(scores["red"], 12)   # 5 from shell-a + 7 from shell-c
        self.assertEqual(scores["blue"], 3)   # 3 from shell-b

    def test_duplicate_state_idempotent(self):
        """Sending the same STATE twice does not double the score."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, teams=["red"])
        ctrl.register_node(1, "shell-1", "shell")

        payload = state_encode({"node_id": 1, "counters": {"red": 10}})
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["STATE"], source=1, seq=1, now_ms=0)
        ctrl.tick(100)

        # Same counters, different seq (so not deduped at radio level).
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["STATE"], source=1, seq=2, now_ms=200)
        ctrl.tick(300)

        scores = ctrl.total_scores
        self.assertEqual(scores["red"], 10)  # max(10, 10) = 10, not 20

    def test_score_increases_over_time(self):
        """Later STATE with higher counters updates the total."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, teams=["red"])
        ctrl.register_node(1, "shell-1", "shell")

        payload1 = state_encode({"node_id": 1, "counters": {"red": 5}})
        radio.send(from_node=1, payload=payload1,
                   msg_type=MESSAGE_TYPES["STATE"], source=1, seq=1, now_ms=0)
        ctrl.tick(100)
        self.assertEqual(ctrl.total_scores["red"], 5)

        payload2 = state_encode({"node_id": 1, "counters": {"red": 15}})
        radio.send(from_node=1, payload=payload2,
                   msg_type=MESSAGE_TYPES["STATE"], source=1, seq=2, now_ms=200)
        ctrl.tick(300)
        self.assertEqual(ctrl.total_scores["red"], 15)


if __name__ == "__main__":
    unittest.main()
