# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""CLAIM election failover test: controller goes down, backup takes over.

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
from atalaia_sim.packet import claim_encode, claim_decode, state_encode
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
class ClaimElectionTests(unittest.TestCase):
    """CLAIM-based controller election / failover."""

    def test_claim_message_logged(self):
        """A CLAIM message is received and logged by the controller."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, teams=["red"])
        ctrl.register_node(1, "shell-1", "shell")
        ctrl.register_node(2, "backup", "controller")

        # Node 2 sends a CLAIM (it wants to be controller for term 2).
        payload = claim_encode({
            "term": 2,
            "candidate": 2,
            "vote_for": 2,
            "last_epoch": 1,
        })
        radio.send(
            from_node=2,
            payload=payload,
            msg_type=MESSAGE_TYPES["CLAIM"],
            source=2,
            seq=1,
            now_ms=0,
        )
        ctrl.tick(100)

        # The controller should have logged the CLAIM.
        claim_entries = [e for e in ctrl.event_log if e["type"] == "claim"]
        self.assertEqual(len(claim_entries), 1)
        self.assertEqual(claim_entries[0]["candidate"], 2)
        self.assertEqual(claim_entries[0]["term"], 2)

    def test_failover_scenario(self):
        """Primary controller goes offline; backup detects and sends CLAIM."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))

        # Primary controller.
        primary = FieldController(
            radio=radio,
            game_id=1,
            teams=["red"],
            beacon_interval_ms=5000,
        )
        primary.register_node(1, "shell-1", "shell")
        primary.register_node(2, "backup", "controller")

        primary.start_game(now_ms=0)
        primary.tick(100)

        # Simulate primary going offline: partition it from all nodes.
        radio.partition({0}, {1, 2})

        # Backup node 2 sends a CLAIM after timeout.
        claim_payload = claim_encode({
            "term": 2,
            "candidate": 2,
            "vote_for": 2,
            "last_epoch": 1,
        })
        radio.send(
            from_node=2,
            payload=claim_payload,
            msg_type=MESSAGE_TYPES["CLAIM"],
            source=2,
            seq=100,
            now_ms=10_000,
        )

        # Node 1 should receive the CLAIM (they're still linked).
        results = radio.tick(10_100)
        node_1_claims = [
            r for r in results
            if r[0] == 1 and r[1].type == MESSAGE_TYPES["CLAIM"]
        ]
        self.assertEqual(len(node_1_claims), 1)

        # Decode the CLAIM that node 1 received.
        _, _, claim_data = node_1_claims[0]
        decoded = claim_decode(claim_data)
        self.assertEqual(decoded["candidate"], 2)
        self.assertEqual(decoded["term"], 2)

    def test_claim_with_higher_term_wins(self):
        """Two backups send CLAIMs; the one with the higher term prevails."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, teams=[])
        ctrl.register_node(1, "backup-a", "controller")
        ctrl.register_node(2, "backup-b", "controller")

        # Backup A claims term 2.
        radio.send(
            from_node=1,
            payload=claim_encode({"term": 2, "candidate": 1, "vote_for": 1, "last_epoch": 1}),
            msg_type=MESSAGE_TYPES["CLAIM"],
            source=1, seq=1, now_ms=0,
        )
        ctrl.tick(100)

        # Backup B claims term 3 (higher).
        radio.send(
            from_node=2,
            payload=claim_encode({"term": 3, "candidate": 2, "vote_for": 2, "last_epoch": 1}),
            msg_type=MESSAGE_TYPES["CLAIM"],
            source=2, seq=1, now_ms=200,
        )
        ctrl.tick(300)

        claims = [e for e in ctrl.event_log if e["type"] == "claim"]
        self.assertEqual(len(claims), 2)

        # The higher-term CLAIM should be the last one logged.
        last_claim = claims[-1]
        self.assertEqual(last_claim["term"], 3)
        self.assertEqual(last_claim["candidate"], 2)

    def test_primary_recovers_after_heal(self):
        """After heal, the primary controller receives STATE messages again."""
        config = RadioConfig(loss_rate=0.0)
        radio = RadioModel(config=config, rng=random.Random(1))
        ctrl = FieldController(radio=radio, teams=["red"])
        ctrl.register_node(1, "shell-1", "shell")

        ctrl.start_game(now_ms=0)
        ctrl.tick(100)

        # Partition.
        radio.partition({0}, {1})

        # Node sends STATE -- controller won't receive it.
        payload = state_encode({"node_id": 1, "counters": {"red": 5}})
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["STATE"], source=1, seq=10, now_ms=1000)
        ctrl.tick(1100)
        self.assertEqual(ctrl.total_scores.get("red", 0), 0)

        # Heal and re-send.
        radio.heal()
        radio.send(from_node=1, payload=payload,
                   msg_type=MESSAGE_TYPES["STATE"], source=1, seq=11, now_ms=2000)
        ctrl.tick(2100)
        self.assertEqual(ctrl.total_scores["red"], 5)


if __name__ == "__main__":
    unittest.main()
