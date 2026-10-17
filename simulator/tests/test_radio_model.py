# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the RadioModel: add/remove nodes, send/receive, loss, dedupe, partition.

    cd simulator && python -m unittest discover -s tests

These tests do NOT require the C core library.
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim.packet import (
    Header,
    hello_encode,
    hello_decode,
    vf_make,
)
from atalaia_sim.protocol import MESSAGE_TYPES
from atalaia_sim.radio_model import (
    DutyCycleTracker,
    RadioConfig,
    RadioModel,
)


def _has_crypto() -> bool:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM  # noqa: F401
        return True
    except ImportError:
        return False


if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and not _has_crypto():
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but cryptography is not available")


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class RadioModelBasicTests(unittest.TestCase):
    """Basic RadioModel tests with encryption available."""

    def setUp(self):
        self.config = RadioConfig(loss_rate=0.0, game_id=1)
        self.radio = RadioModel(config=self.config, rng=random.Random(1))

    def test_add_and_remove_node(self):
        self.radio.add_node(1)
        self.radio.add_node(2)
        self.assertIn(1, self.radio.nodes)
        self.assertIn(2, self.radio.nodes)
        self.assertTrue(self.radio.is_linked(1, 2))

        self.radio.remove_node(2)
        self.assertNotIn(2, self.radio.nodes)

    def test_send_and_receive(self):
        self.radio.add_node(1)
        self.radio.add_node(2)

        payload = hello_encode({"node_name": "n1", "role": "shell"})
        self.radio.send(
            from_node=1,
            payload=payload,
            msg_type=MESSAGE_TYPES["HELLO"],
            source=1,
            seq=1,
            now_ms=0,
        )

        # Advance time enough for delivery (jitter is 5-50ms).
        results = self.radio.tick(100)
        self.assertEqual(len(results), 1)
        dest, hdr, decrypted = results[0]
        self.assertEqual(dest, 2)
        self.assertEqual(hdr.source, 1)
        decoded = hello_decode(decrypted)
        self.assertEqual(decoded["node_name"], "n1")

    def test_no_self_delivery(self):
        self.radio.add_node(1)
        payload = hello_encode({"node_name": "solo"})
        self.radio.send(from_node=1, payload=payload,
                        msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=1, now_ms=0)
        results = self.radio.tick(100)
        self.assertEqual(len(results), 0)

    def test_three_nodes_broadcast(self):
        self.radio.add_node(1)
        self.radio.add_node(2)
        self.radio.add_node(3)

        payload = hello_encode({"node_name": "center"})
        self.radio.send(from_node=1, payload=payload,
                        msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=1, now_ms=0)

        results = self.radio.tick(100)
        dest_ids = {r[0] for r in results}
        self.assertIn(2, dest_ids)
        self.assertIn(3, dest_ids)


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class LossRateTests(unittest.TestCase):
    """Test random packet loss."""

    def test_total_loss(self):
        config = RadioConfig(loss_rate=1.0)
        radio = RadioModel(config=config, rng=random.Random(99))
        radio.add_node(1)
        radio.add_node(2)

        payload = hello_encode({"node_name": "lost"})
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=1, now_ms=0)
        results = radio.tick(100)
        self.assertEqual(len(results), 0)

    def test_partial_loss(self):
        """With 50% loss over many sends, some should be delivered and some lost."""
        config = RadioConfig(loss_rate=0.5)
        radio = RadioModel(config=config, rng=random.Random(42))
        radio.add_node(1)
        radio.add_node(2)

        delivered = 0
        for seq in range(100):
            payload = hello_encode({"node_name": "test"})
            radio.send(from_node=1, payload=payload,
                       msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=seq, now_ms=0)
            results = radio.tick(100)
            delivered += len(results)

        # Expect roughly 50, but with randomness allow wide margin.
        self.assertGreater(delivered, 20)
        self.assertLess(delivered, 80)


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class DedupeTests(unittest.TestCase):
    """Test deduplication of repeated packets."""

    def test_duplicate_rejected(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        radio.add_node(1)
        radio.add_node(2)

        payload = hello_encode({"node_name": "dup"})
        # Send the same (source=1, seq=1) twice.
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=1, now_ms=0)
        results1 = radio.tick(100)
        self.assertEqual(len(results1), 1)

        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=1, now_ms=200)
        results2 = radio.tick(300)
        self.assertEqual(len(results2), 0)

    def test_different_seq_accepted(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        radio.add_node(1)
        radio.add_node(2)

        payload = hello_encode({"node_name": "ok"})
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=1, now_ms=0)
        radio.tick(100)

        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=2, now_ms=200)
        results = radio.tick(300)
        self.assertEqual(len(results), 1)


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class PartitionTests(unittest.TestCase):
    """Test network partition and heal."""

    def test_partition_blocks_delivery(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        radio.add_node(1)
        radio.add_node(2)
        radio.add_node(3)

        # Partition: {1} can't reach {2, 3}
        radio.partition({1}, {2, 3})

        payload = hello_encode({"node_name": "isolated"})
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=1, now_ms=0)
        results = radio.tick(100)
        # Node 1 can't reach 2 or 3.
        self.assertEqual(len(results), 0)

    def test_heal_restores_connectivity(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        radio.add_node(1)
        radio.add_node(2)

        radio.partition({1}, {2})
        payload = hello_encode({"node_name": "before"})
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=1, now_ms=0)
        self.assertEqual(len(radio.tick(100)), 0)

        radio.heal()
        payload = hello_encode({"node_name": "after"})
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["HELLO"], source=1, seq=2, now_ms=200)
        results = radio.tick(300)
        self.assertEqual(len(results), 1)

    def test_set_link(self):
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        radio.add_node(1)
        radio.add_node(2)
        self.assertTrue(radio.is_linked(1, 2))

        radio.set_link(1, 2, False)
        self.assertFalse(radio.is_linked(1, 2))

        radio.set_link(1, 2, True)
        self.assertTrue(radio.is_linked(1, 2))


class DutyCycleTrackerTests(unittest.TestCase):
    """Test the DutyCycleTracker (no crypto needed)."""

    def test_budget_enforcement(self):
        tracker = DutyCycleTracker(budget_ms_per_hour=100.0)
        self.assertTrue(tracker.can_send(50.0, now_ms=0))
        tracker.record(50.0, now_ms=0)
        self.assertTrue(tracker.can_send(50.0, now_ms=0))
        tracker.record(50.0, now_ms=0)
        self.assertFalse(tracker.can_send(1.0, now_ms=0))

    def test_budget_rolls_over(self):
        tracker = DutyCycleTracker(budget_ms_per_hour=100.0)
        tracker.record(100.0, now_ms=0)
        self.assertFalse(tracker.can_send(1.0, now_ms=0))
        # After one hour, the old usage rolls off.
        self.assertTrue(tracker.can_send(1.0, now_ms=DutyCycleTracker.HOUR_MS + 1))

    def test_used(self):
        tracker = DutyCycleTracker()
        tracker.record(10.0, now_ms=100)
        tracker.record(20.0, now_ms=200)
        self.assertAlmostEqual(tracker.used(now_ms=300), 30.0)


if __name__ == "__main__":
    unittest.main()
