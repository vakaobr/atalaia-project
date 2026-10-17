# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""TIME beacon reception and clock offset computation.

    cd simulator && python -m unittest discover -s tests

Requires the cryptography library.  Skipped when unavailable.
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim.field_controller import FieldController
from atalaia_sim.packet import time_decode
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
class TimeSyncTests(unittest.TestCase):
    """Verify nodes can receive TIME beacons and compute a clock offset."""

    def test_time_beacon_received(self):
        """A node receives a TIME beacon and can decode the game time."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(
            radio=radio,
            teams=["red", "blue"],
            beacon_interval_ms=5000,
        )
        ctrl.register_node(1, "node-1", "shell")

        ctrl.start_game(duration_ms=300_000, now_ms=0)
        deliveries = ctrl.tick(100)

        # Find a TIME beacon delivered to node 1.
        time_deliveries = [
            (dest, hdr, payload)
            for dest, hdr, payload in deliveries
            if dest == 1 and hdr.type == MESSAGE_TYPES["TIME"]
        ]
        self.assertGreater(len(time_deliveries), 0)

        # Decode the TIME payload.
        _, _, payload = time_deliveries[0]
        time_msg = time_decode(payload)
        self.assertIn("game_time_ms", time_msg)
        self.assertIn("term", time_msg)
        self.assertIn("game_state", time_msg)

    def test_clock_offset_computation(self):
        """Simulated clock offset: node local time vs beacon game_time_ms."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(
            radio=radio,
            teams=[],
            beacon_interval_ms=5000,
        )
        ctrl.register_node(1, "node-1", "shell")

        # Start game at wall time 1000.
        ctrl.start_game(now_ms=1000)

        # Simulate 5 seconds of game time.
        ctrl.tick(1100)  # deliver the start beacon

        # Now advance to 6000 and send another beacon.
        ctrl.game_time_ms = 5000  # simulate game time advancing
        ctrl.send_time_beacon(now_ms=6000)
        deliveries = ctrl.tick(6100)

        time_deliveries = [
            (dest, hdr, payload)
            for dest, hdr, payload in deliveries
            if dest == 1 and hdr.type == MESSAGE_TYPES["TIME"]
        ]
        self.assertGreater(len(time_deliveries), 0)

        _, _, payload = time_deliveries[0]
        time_msg = time_decode(payload)
        # The node received a beacon with game_time_ms = 5000.
        self.assertEqual(time_msg["game_time_ms"], 5000)

        # The node's "local" time is the radio model time (6100).
        # Clock offset = game_time_ms - local_time = 5000 - 6100 = -1100.
        local_time = 6100
        offset = time_msg["game_time_ms"] - local_time
        self.assertEqual(offset, -1100)

    def test_multiple_beacons(self):
        """Multiple beacons at regular intervals."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(
            radio=radio,
            beacon_interval_ms=1000,
        )
        ctrl.register_node(1, "node-1", "shell")
        ctrl.start_game(now_ms=0)

        beacon_count = 0
        for t in range(0, 5100, 100):
            deliveries = ctrl.tick(t)
            for dest, hdr, _ in deliveries:
                if dest == 1 and hdr.type == MESSAGE_TYPES["TIME"]:
                    beacon_count += 1

        # We should see at least 5 beacons over 5 seconds with 1s interval.
        self.assertGreaterEqual(beacon_count, 4)


if __name__ == "__main__":
    unittest.main()
