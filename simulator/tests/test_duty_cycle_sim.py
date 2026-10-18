# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Duty-cycle simulation: verify no node exceeds the 10% budget.

    cd simulator && python -m unittest discover -s tests

Requires the cryptography library.  Skipped when unavailable.
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim.packet import hello_encode, state_encode
from atalaia_sim.protocol import MESSAGE_TYPES
from atalaia_sim.radio_model import DutyCycleTracker, RadioConfig, RadioModel
from atalaia_sim.field_controller import FieldController


def _has_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        return True
    except ImportError:
        return False


if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and not _has_crypto():
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but cryptography is not available")


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class DutyCycleSimTests(unittest.TestCase):
    """Simulate a game and verify no node blows the duty-cycle budget."""

    def test_normal_traffic_within_budget(self):
        """Normal game traffic stays within 10% duty cycle."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(42))
        ctrl = FieldController(
            radio=radio,
            teams=["red", "blue"],
            beacon_interval_ms=30_000,
        )
        for nid in (1, 2, 3):
            ctrl.register_node(nid, f"shell-{nid}", "shell")

        ctrl.start_game(duration_ms=300_000, now_ms=0)

        # Simulate 5 minutes of game: each node sends a STATE every 10 seconds.
        t = 0
        for _ in range(30):  # 30 * 10s = 5 minutes
            t += 10_000
            for nid in (1, 2, 3):
                payload = state_encode({
                    "node_id": nid,
                    "battery": 90,
                    "counters": {"red": nid * 2, "blue": nid},
                })
                radio.send(
                    from_node=nid,
                    payload=payload,
                    msg_type=MESSAGE_TYPES["STATE"],
                    source=nid,
                    seq=t + nid,
                    now_ms=t,
                )
            ctrl.tick(t + 100)

        # Check duty cycle: no node should exceed 360_000 ms/hour (g2 10%).
        budget = DutyCycleTracker().budget_ms_per_hour
        for nid, node_obj in radio.nodes.items():
            used = node_obj.duty.used(t + 100)
            self.assertLessEqual(
                used, budget,
                f"Node {nid} used {used:.1f}ms airtime, budget is {budget:.1f}ms",
            )

    def test_burst_traffic_tracked(self):
        """Burst of rapid sends accumulates airtime correctly."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        radio.add_node(1)
        radio.add_node(2)

        for seq in range(50):
            payload = hello_encode({"node_name": "burst"})
            radio.send(
                from_node=1,
                payload=payload,
                msg_type=MESSAGE_TYPES["HELLO"],
                source=1,
                seq=seq,
                now_ms=seq * 10,
            )

        used = radio.nodes[1].duty.used(500)
        self.assertGreater(used, 0)
        # 50 packets at ~30 + ~20 bytes * 0.5 = ~40ms each = ~2000ms total.
        self.assertGreater(used, 1000)


if __name__ == "__main__":
    unittest.main()
