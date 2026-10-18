# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Controller failover over the radio model (ADR-P2-8, plan AC-9).

    cd simulator && python -m unittest discover -s tests

Two or three FieldControllers share one RadioModel with ordinary nodes.
The primary goes silent (partitioned away, as if powered off); the backup
notices the missing TIME beacons, claims the role with a higher term,
takes over the beacons, and the old controller steps down when it comes
back. Every message is a real encrypted packet on the simulated radio.

Requires the cryptography library.
"""

from __future__ import annotations

import os
import random
import unittest

from atalaia_sim.election import FOLLOWER, LEADER, Election
from atalaia_sim.field_controller import GAME_RUNNING, FieldController, NotController
from atalaia_sim.packet import claim_decode, state_encode, time_decode
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

NODES = (1, 2)


class Field:
    """A radio model with controllers and plain nodes, driven in 100 ms steps."""

    def __init__(self, backups: dict[int, int], mode: str = "auto") -> None:
        self.radio = RadioModel(config=RadioConfig(loss_rate=0.0), rng=random.Random(7))
        primary_election = Election(0, priority=16_000, mode=mode)
        primary_election.lead(1, 0)
        self.primary = FieldController(radio=self.radio, teams=["red", "blue"], node_id=0,
                                       election=primary_election)
        self.ctrls = [self.primary]
        for node_id, priority in backups.items():
            election = Election(node_id, priority=priority, mode=mode)
            election.follow(0)
            ctrl = FieldController(radio=self.radio, teams=["red", "blue"], node_id=node_id,
                                   election=election)
            self.ctrls.append(ctrl)
        for n in NODES:
            self.radio.add_node(n)
        self.t = 0
        self.heard: list[tuple[int, int, int, dict]] = []  # (t, node, source, TIME payload)
        self.seq = 100

    def run_until(self, t_end: int) -> None:
        while self.t < t_end:
            self.t += 100
            deliveries = self.radio.tick(self.t)
            for dest, hdr, payload in deliveries:
                if dest in NODES and hdr.type == MESSAGE_TYPES["TIME"]:
                    self.heard.append((self.t, dest, hdr.source, time_decode(payload)))
            for ctrl in self.ctrls:
                ctrl.tick(self.t, deliveries)

    def node_state(self, node: int, counters: dict[int, int]) -> None:
        self.seq += 1
        self.radio.send(from_node=node, payload=state_encode({"counters": counters, "epoch": 0}),
                        msg_type=MESSAGE_TYPES["STATE"], source=node, seq=self.seq, now_ms=self.t)

    def leaders(self) -> list[int]:
        return [c.node_id for c in self.ctrls if c.election.role == LEADER]

    def live_leaders(self) -> list[int]:
        """Leaders the nodes can hear (a cut-off primary still believes it leads)."""
        return [n for n in self.leaders() if self.radio.is_linked(n, NODES[0])]

    def kill_primary(self) -> None:
        self.radio.partition({0}, set(self.radio.nodes) - {0})


@unittest.skipUnless(_has_crypto(), "cryptography library not available")
class FailoverTests(unittest.TestCase):
    def test_backup_follows_while_beacons_arrive(self):
        f = Field({9: 12_000})
        f.primary.start_game(duration_ms=600_000, now_ms=0)
        f.run_until(120_000)
        backup = f.ctrls[1]
        self.assertEqual(f.leaders(), [0])
        self.assertEqual(backup.election.role, FOLLOWER)
        self.assertEqual(backup.election.term, 1)
        # The standby mirrors the game clock from the beacons.
        self.assertEqual(backup.game_state, GAME_RUNNING)
        self.assertAlmostEqual(backup.game_time_ms, f.primary.game_time_ms, delta=10_100)
        # Failover on: a beacon every 10 s.
        beacons = [h for h in f.heard if h[1] == 1 and h[2] == 0]
        self.assertGreaterEqual(len(beacons), 12)
        with self.assertRaises(NotController):
            backup.start_game(now_ms=f.t)

    def test_backup_takes_over_and_nodes_hear_the_new_term(self):
        f = Field({9: 12_000})
        f.primary.start_game(duration_ms=600_000, now_ms=0)
        f.run_until(20_000)
        f.kill_primary()
        down_at = f.t
        f.run_until(100_000)
        backup = f.ctrls[1]
        self.assertEqual(backup.election.role, LEADER)
        self.assertEqual(backup.election.term, 2)
        stood = next(t for t, role, _ in backup.election.history if role == "candidate")
        took_over = next(t for t, role, _ in backup.election.history if role == LEADER)
        # Three missed 10 s beacons, counted from the last one heard, then the
        # 5 s election timeout (ADR-P2-8). The field-test bound is 40 s.
        last_heard = max(t for t, _, src, _ in f.heard if src == 0)
        self.assertGreaterEqual(stood - last_heard, 30_000 - 100)
        self.assertLessEqual(stood - last_heard, 30_000 + 200)
        self.assertEqual(took_over - stood, 5_000)
        self.assertLessEqual(took_over - down_at, 40_000)
        # Nodes hear TIME from the new controller with the higher term.
        new_beacons = [h for h in f.heard if h[2] == 9]
        self.assertTrue(new_beacons)
        self.assertTrue(all(h[3]["term"] == 2 for h in new_beacons))
        self.assertEqual({h[1] for h in new_beacons}, set(NODES))
        # The game clock continued across the takeover.
        self.assertEqual(backup.game_state, GAME_RUNNING)
        self.assertGreater(backup.game_time_ms, 90_000)

    def test_old_controller_steps_down_when_it_comes_back(self):
        f = Field({9: 12_000})
        f.primary.start_game(duration_ms=600_000, now_ms=0)
        f.run_until(20_000)
        f.kill_primary()
        f.run_until(80_000)
        self.assertEqual(sorted(f.leaders()), [0, 9])  # the cut-off primary still thinks it leads
        f.radio.heal()
        f.run_until(100_000)
        self.assertEqual(f.leaders(), [9])
        self.assertEqual(f.primary.election.role, FOLLOWER)
        self.assertEqual(f.primary.election.term, 2)
        # After stepping down it sends no more beacons.
        healed_beacons = [h for h in f.heard if h[2] == 0 and h[0] > 95_000]
        self.assertEqual(healed_beacons, [])
        with self.assertRaises(NotController):
            f.primary.send_cmd("message", {"text": "hello"}, now_ms=f.t)

    def test_highest_priority_candidate_wins(self):
        f = Field({8: 15_000, 9: 20_000})
        f.primary.start_game(now_ms=0)
        f.run_until(10_000)
        f.kill_primary()
        f.run_until(80_000)
        self.assertEqual(f.live_leaders(), [9])
        loser = f.ctrls[1]
        self.assertEqual(loser.election.role, FOLLOWER)
        claims = [e for e in loser.event_log if e["type"] == "claim"]
        self.assertTrue(any(c["node_id"] == 9 and c["priority"] == 20_000 for c in claims))

    def test_equal_priority_lowest_node_id_wins(self):
        f = Field({8: 15_000, 9: 15_000})
        f.primary.start_game(now_ms=0)
        f.run_until(10_000)
        f.kill_primary()
        f.run_until(80_000)
        self.assertEqual(f.live_leaders(), [8])

    def test_claim_payload_matches_the_schema(self):
        f = Field({9: 12_000})
        f.primary.start_game(now_ms=0)
        f.node_state(1, {1: 3})
        f.run_until(10_000)
        f.kill_primary()
        claims = []
        orig = f.radio.send

        def spy(**kw):
            if kw["msg_type"] == MESSAGE_TYPES["CLAIM"]:
                claims.append(claim_decode(kw["payload"]))
            return orig(**kw)

        f.radio.send = spy  # type: ignore[method-assign]
        f.run_until(60_000)
        self.assertEqual(len(claims), 1)
        claim = claims[0]
        self.assertEqual(claim["term"], 2)
        self.assertEqual(claim["priority"], 12_000)
        self.assertEqual(claim["node_id"], 9)
        self.assertEqual(set(claim) - {"last_ack_seq"}, {"term", "priority", "node_id"})

    def test_manual_mode_waits_for_the_gm(self):
        f = Field({9: 12_000}, mode="manual")
        f.primary.start_game(now_ms=0)
        f.run_until(10_000)
        f.kill_primary()
        f.run_until(200_000)
        backup = f.ctrls[1]
        self.assertEqual(backup.election.role, FOLLOWER)
        backup.promote(f.t)
        f.run_until(f.t + 5_100)
        self.assertEqual(backup.election.role, LEADER)
        self.assertEqual(backup.election.term, 2)

    def test_scores_survive_failover(self):
        f = Field({9: 12_000})
        f.primary.start_game(now_ms=0)
        f.node_state(1, {1: 10, 2: 4})
        f.node_state(2, {1: 1})
        f.run_until(5_000)
        backup = f.ctrls[1]
        self.assertEqual(backup.total_scores, f.primary.total_scores)
        self.assertEqual(backup.total_scores, {"red": 11, "blue": 4})
        f.kill_primary()
        f.run_until(60_000)
        f.node_state(1, {1: 12, 2: 4})
        f.run_until(61_000)
        self.assertEqual(backup.total_scores, {"red": 13, "blue": 4})


if __name__ == "__main__":
    unittest.main()
