# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The SQLite store (ADR-P2-9): dedupe by the events table's UNIQUE key, settings, epochs.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

import support  # noqa: F401
from atalaia_controller.store import EPOCH_KEYS, Store, epoch_tag


def event(**kw):
    ev = {"node": 4, "seq": 1, "t": 5000, "type": "zone.captured", "team": "red", "squad": 0,
          "prio": "normal", "data": {"zone": "a"}, "epoch": 1, "pkt_seq": 0}
    ev.update(kw)
    return ev


def game(game_id=77, **kw):
    g = {"id": game_id, "name": "g", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"],
         "params": {"tick_s": 10}, "assignments": {"4": "zone"}, "duration_ms": 0, "game_seed": 9,
         "state": "ready", "created_at": time.time()}
    g.update(kw)
    return g


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "sub", "c.db")
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_events_are_idempotent(self):
        self.store.create_game(game(), None)
        self.assertTrue(self.store.insert_event(77, event()))
        self.assertFalse(self.store.insert_event(77, event(pkt_seq=9, epoch=2)))  # a replay
        # After a reboot the box's event seq restarts: same seq, later time -> a new event.
        self.assertTrue(self.store.insert_event(77, event(t=65_000, team="blue")))
        self.assertTrue(self.store.insert_event(78, event()))  # another game
        log = self.store.events(77)
        self.assertEqual([(e["t"], e["team"]) for e in log], [(5000, "red"), (65_000, "blue")])
        self.assertEqual(self.store.count_events(77, "zone.captured"), 2)
        self.assertEqual(len(self.store.events(77, since_ms=6000)), 1)
        self.assertEqual(log[0]["data"], {"zone": "a"})

    def test_log_order(self):
        self.store.insert_event(1, event(node=5, seq=2, t=300))
        self.store.insert_event(1, event(node=3, seq=9, t=300))
        self.store.insert_event(1, event(node=9, seq=1, t=100))
        self.assertEqual([(e["t"], e["node"]) for e in self.store.events(1)], [(100, 9), (300, 3), (300, 5)])

    def test_games(self):
        self.store.create_game(game(), b"k" * 16)
        self.store.create_game(game(78, state="ended"), None)
        self.assertEqual(self.store.live_game()["id"], 77)
        self.assertEqual(self.store.game_key(77), b"k" * 16)
        self.assertIsNone(self.store.game_key(78))
        self.store.update_game(77, state="running", term=3, started_at=1.0)
        g = self.store.game(77)
        self.assertEqual((g["state"], g["term"], g["assignments"]), ("running", 3, {"4": "zone"}))
        self.store.update_game(77, state="ended", game_key=None)
        self.assertIsNone(self.store.live_game())
        self.assertIsNone(self.store.game_key(77))
        self.assertEqual(self.store.game_ids(), {77, 78})
        with self.assertRaises(ValueError):
            self.store.update_game(77, name="x")

    def test_presets_modes_nodes_scores(self):
        p = self.store.save_preset("short", "org.atalaia.bomb", {"fuse_s": 60})
        p2 = self.store.save_preset("short", "org.atalaia.bomb", {"fuse_s": 90})
        self.assertEqual(p["id"], p2["id"])
        self.assertEqual(self.store.preset(p["id"])["params"], {"fuse_s": 90})
        self.assertEqual(len(self.store.presets()), 1)
        self.store.save_mode("org.x.y", "1.0", {"mode.yaml": "id: org.x.y"})
        self.assertEqual(self.store.modes()[0]["files"], {"mode.yaml": "id: org.x.y"})
        self.store.upsert_node(77, 4, "alpha", "zone", {"rssi": -70})
        self.store.upsert_node(77, 4, "alpha", "zone", {"rssi": -60})
        self.assertEqual(self.store.nodes(77)[0]["rssi"], -60)
        self.store.save_scores(77, {"red": 5})
        self.store.save_scores(77, {"red": 7, "blue": 1})
        self.assertEqual(self.store.scores(77), {"red": 7, "blue": 1})

    def test_tx_epoch_survives_a_restart(self):
        key = bytes(range(16))
        self.assertEqual(self.store.next_tx_epoch(key), 1)
        self.assertEqual(self.store.next_tx_epoch(key, resuming=True), 2)
        self.store.close()
        self.store = Store(self.path)
        self.assertEqual(self.store.next_tx_epoch(key, resuming=True), 3)
        self.store.set_setting("tx_epochs", json.dumps([[epoch_tag(key), 65535]]))
        with self.assertRaises(RuntimeError):
            self.store.next_tx_epoch(key)

    def test_tx_epoch_per_game_key(self):
        """Found on the bench (2026-10-22): one epoch for every run made the controller unheard by
        the boxes after 16 games (they look 16 above epoch 0 in a new game). Per key now."""
        old = bytes(range(16))
        for _ in range(40):
            self.store.next_tx_epoch(old)
        for game in range(40):
            self.assertEqual(self.store.next_tx_epoch(bytes([game]) * 16), 1)
        # Only the last EPOCH_KEYS keys are kept; the tags, never the keys.
        table = json.loads(self.store.get_setting("tx_epochs"))
        self.assertEqual(len(table), EPOCH_KEYS)
        self.assertEqual(table[0], [epoch_tag(bytes([39]) * 16), 1])
        self.assertNotIn(bytes([39] * 16).hex(), self.store.get_setting("tx_epochs"))
        # A reboot in a game goes on from that game's epoch.
        self.assertEqual(self.store.next_tx_epoch(bytes([38]) * 16, resuming=True), 2)

    def test_tx_epoch_from_an_older_version(self):
        """Before the per-key list, one tx_epoch: a resumed game goes on from it, a new one starts at 1."""
        key = bytes(range(16))
        self.store.set_setting("tx_epoch", "120")
        self.assertEqual(self.store.next_tx_epoch(key, resuming=True), 121)
        self.assertEqual(self.store.next_tx_epoch(bytes(16)), 1)
        other = Store(os.path.join(os.path.dirname(self.path), "other.db"))
        try:
            other.set_setting("tx_epoch", "120")
            self.assertEqual(other.next_tx_epoch(key), 1)
            self.assertEqual(other.next_tx_epoch(key, resuming=True), 2)  # the list exists now
        finally:
            other.close()

    def test_epoch_tag_vectors(self):
        """protocol/vectors/epoch_tag.json, shared with the firmware's test_radio_protocol.c."""
        path = Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "epoch_tag.json"
        doc = json.loads(path.read_text(encoding="utf-8"))
        for v in doc["valid"]:
            key = bytes.fromhex(v["game_key"])
            self.assertEqual(epoch_tag(key), v["tag"], v["name"])
            self.assertEqual(hmac.new(key, doc["label"].encode(), hashlib.sha256).hexdigest()[:16], v["tag"])

    @unittest.skipIf(sys.platform == "win32", "POSIX file modes")
    def test_private_file(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
