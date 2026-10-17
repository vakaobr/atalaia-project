# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Flood delivery test: packets propagate through chains; dedupe prevents loops.

    cd simulator && python -m unittest discover -s tests

Requires the cryptography library.  Skipped when unavailable.
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim.packet import hello_encode, hello_decode
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
class FloodDeliveryTests(unittest.TestCase):
    """Test flood relay through a chain of nodes."""

    def test_chain_delivery(self):
        """A -> B -> C chain: A sends, C receives via B's relay."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))

        radio.add_node(1)
        radio.add_node(2)
        radio.add_node(3)

        # Create a chain: A(1) <-> B(2) <-> C(3); A and C can't directly reach each other.
        radio.set_link(1, 3, False)

        payload = hello_encode({"node_name": "from-A"})
        radio.send(
            from_node=1,
            payload=payload,
            msg_type=MESSAGE_TYPES["HELLO"],
            source=1,
            seq=1,
            hop_limit=3,
            now_ms=0,
        )

        # First tick: A -> B delivery.
        results1 = radio.tick(100)
        b_received = [r for r in results1 if r[0] == 2]
        self.assertEqual(len(b_received), 1)

        # B should relay with hop_limit - 1.
        # Second tick: B -> C delivery.
        results2 = radio.tick(200)
        c_received = [r for r in results2 if r[0] == 3]
        self.assertEqual(len(c_received), 1)

        # Verify content.
        _, _, c_payload = c_received[0]
        decoded = hello_decode(c_payload)
        self.assertEqual(decoded["node_name"], "from-A")

    def test_dedupe_prevents_loops(self):
        """In a fully connected mesh, a packet is delivered exactly once per node."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(42))

        for nid in range(1, 5):
            radio.add_node(nid)

        payload = hello_encode({"node_name": "mesh"})
        radio.send(
            from_node=1,
            payload=payload,
            msg_type=MESSAGE_TYPES["HELLO"],
            source=1,
            seq=1,
            hop_limit=3,
            now_ms=0,
        )

        all_results: list[tuple[int, ...]] = []
        for t in range(0, 1000, 50):
            results = radio.tick(t)
            all_results.extend(results)

        # Each of nodes 2, 3, 4 should have received exactly once.
        delivered_to = [r[0] for r in all_results]
        for nid in (2, 3, 4):
            count = delivered_to.count(nid)
            self.assertEqual(
                count, 1,
                f"Node {nid} received {count} times (expected 1)",
            )

    def test_hop_limit_1_no_relay(self):
        """hop_limit=1 means no relay: only direct neighbors receive."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))

        radio.add_node(1)
        radio.add_node(2)
        radio.add_node(3)

        # Chain: 1 <-> 2 <-> 3; no direct 1-3 link.
        radio.set_link(1, 3, False)

        payload = hello_encode({"node_name": "no-relay"})
        radio.send(
            from_node=1,
            payload=payload,
            msg_type=MESSAGE_TYPES["HELLO"],
            source=1,
            seq=1,
            hop_limit=1,
            now_ms=0,
        )

        all_results: list[tuple[int, ...]] = []
        for t in range(0, 500, 50):
            results = radio.tick(t)
            all_results.extend(results)

        # Node 2 receives, but node 3 does NOT (hop_limit=1 means no relay).
        delivered_to = [r[0] for r in all_results]
        self.assertIn(2, delivered_to)
        self.assertNotIn(3, delivered_to)

    def test_four_node_diamond(self):
        """Diamond topology: A -> {B, C} -> D.  D receives once despite two paths."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))

        radio.add_node(1)  # A
        radio.add_node(2)  # B
        radio.add_node(3)  # C
        radio.add_node(4)  # D

        # Diamond: A <-> B, A <-> C, B <-> D, C <-> D; no A <-> D, no B <-> C.
        radio.set_link(1, 4, False)
        radio.set_link(2, 3, False)

        payload = hello_encode({"node_name": "diamond"})
        radio.send(
            from_node=1,
            payload=payload,
            msg_type=MESSAGE_TYPES["HELLO"],
            source=1,
            seq=1,
            hop_limit=3,
            now_ms=0,
        )

        all_results: list[tuple[int, ...]] = []
        for t in range(0, 1000, 50):
            results = radio.tick(t)
            all_results.extend(results)

        # D should receive exactly once.
        d_count = sum(1 for r in all_results if r[0] == 4)
        self.assertEqual(d_count, 1)


if __name__ == "__main__":
    unittest.main()
