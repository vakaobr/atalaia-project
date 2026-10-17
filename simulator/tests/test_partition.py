# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Partition test: disconnect a node, generate events, reconnect, verify delivery.

    cd simulator && python -m unittest discover -s tests

Requires the cryptography library.  Skipped when unavailable.
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim.packet import state_encode
from atalaia_sim.protocol import MESSAGE_TYPES
from atalaia_sim.radio_model import RadioConfig, RadioModel
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
class PartitionAndHealTests(unittest.TestCase):
    """Disconnect a node, send events, reconnect, verify eventual delivery."""

    def test_partition_blocks_then_heal_delivers(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, teams=["red"])
        ctrl.register_node(1, "shell-1", "shell")
        ctrl.register_node(2, "shell-2", "shell")

        # Partition: node 2 isolated from controller (0) and node 1.
        radio.partition({2}, {0, 1})

        # Node 2 sends a STATE -- it should not arrive at the controller.
        payload = state_encode({"node_id": 2, "counters": {"red": 10}})
        radio.send(from_node=2, payload=payload,
                   msg_type=MESSAGE_TYPES["STATE"], source=2, seq=1, now_ms=0)
        ctrl.tick(100)
        self.assertEqual(ctrl.total_scores.get("red", 0), 0)

        # Heal the partition.
        radio.heal()

        # Node 2 re-sends (new seq since the radio deduplicates).
        radio.send(from_node=2, payload=payload,
                   msg_type=MESSAGE_TYPES["STATE"], source=2, seq=2, now_ms=200)
        ctrl.tick(300)
        self.assertEqual(ctrl.total_scores["red"], 10)

    def test_unidirectional_link(self):
        """set_link is bidirectional: breaking it blocks both directions."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, teams=["red"])
        ctrl.register_node(1, "shell-1", "shell")

        # Break link between controller (0) and node 1.
        radio.set_link(0, 1, False)

        # Controller can't reach node 1, and node 1 can't reach controller.
        payload = state_encode({"node_id": 1, "counters": {"red": 5}})
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["STATE"], source=1, seq=1, now_ms=0)
        ctrl.tick(100)
        self.assertEqual(ctrl.total_scores.get("red", 0), 0)

        # Restore link.
        radio.set_link(0, 1, True)
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["STATE"], source=1, seq=2, now_ms=200)
        ctrl.tick(300)
        self.assertEqual(ctrl.total_scores["red"], 5)

    def test_partition_between_groups(self):
        """Two groups can communicate internally but not across."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        radio.add_node(0)
        radio.add_node(1)
        radio.add_node(2)
        radio.add_node(3)

        # Group {0,1} vs {2,3}
        radio.partition({0, 1}, {2, 3})

        # Intra-group links still work.
        self.assertTrue(radio.is_linked(0, 1))
        self.assertTrue(radio.is_linked(2, 3))

        # Cross-group links are broken.
        self.assertFalse(radio.is_linked(0, 2))
        self.assertFalse(radio.is_linked(0, 3))
        self.assertFalse(radio.is_linked(1, 2))
        self.assertFalse(radio.is_linked(1, 3))


if __name__ == "__main__":
    unittest.main()
