# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""rand() seeded from the game's key (LIVE2-2), through the ctypes bindings.

    cd simulator && python -m unittest discover -s tests

Runs every case of protocol/vectors/rand.json in the shared core library, as core/tests/test_rand.c
does in C, and recomputes the seed state from hashlib alone, so the specification (HMAC-SHA256 under
the game key over a label, the seed and the node id) is checked and not only the core against itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import unittest
from pathlib import Path

from atalaia_sim.core import Core, Node, find_library

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "rand.json")
                     .read_text(encoding="utf-8"))


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and CORE is None:
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the shared core library is not built")

SOURCE = "on('go', function()\nfor i = 1, 4 do log(rand(1, 1000000)) end\nend)\n"


def lua_values(game_key, seed: int, node_id: int) -> list[int]:
    logs: list[str] = []
    node = Node(CORE, node_id, seed, ["red", "blue"], {}, SOURCE, "=test", instr_limit=200000,
                on_log=logs.append, game_key=game_key)
    try:
        assert node.loaded, node.last_error
        assert node.input("go")
    finally:
        node.close()
    return [int(x) for x in logs]


@unittest.skipIf(CORE is None, "the core library is not built")
class RandVectors(unittest.TestCase):
    def test_every_case(self) -> None:
        for case in VECTORS["cases"]:
            with self.subTest(case["name"]):
                key = bytes.fromhex(case["game_key"])
                self.assertEqual(lua_values(key, case["game_seed"], case["node_id"]), case["lua_rand_1_1000000"])

    def test_the_state_is_the_documented_hmac(self) -> None:
        for case in VECTORS["cases"]:
            with self.subTest(case["name"]):
                msg = VECTORS["label"].encode() + case["game_seed"].to_bytes(4, "big") + case["node_id"].to_bytes(2, "big")
                mac = hmac.new(bytes.fromhex(case["game_key"]), msg, hashlib.sha256).digest()
                self.assertEqual(mac[:16].hex(), case["state"])

    def test_nothing_a_player_sees_is_enough(self) -> None:
        base = VECTORS["cases"][0]
        key = bytes.fromhex(base["game_key"])
        same_seed_and_node = lua_values(bytes.fromhex(VECTORS["cases"][3]["game_key"]), base["game_seed"], base["node_id"])
        self.assertNotEqual(same_seed_and_node, lua_values(key, base["game_seed"], base["node_id"]))
        # no key at all (a stand-alone game) is the old, predictable sequence, and stays the same
        self.assertEqual(lua_values(None, base["game_seed"], base["node_id"]),
                         lua_values(None, base["game_seed"], base["node_id"]))
        self.assertNotEqual(lua_values(None, base["game_seed"], base["node_id"]),
                            lua_values(key, base["game_seed"], base["node_id"]))

    def test_the_same_inputs_replay_the_same_game(self) -> None:
        base = VECTORS["cases"][0]
        key = bytes.fromhex(base["game_key"])
        self.assertEqual(lua_values(key, 99, 5), lua_values(key, 99, 5))


if __name__ == "__main__":
    unittest.main()
