# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""field.* and state.field in a field script, through the ctypes bindings (ADR-P2-14).

    cd simulator && python -m unittest discover -s tests

Runs a small field.lua in the real core with Python field_ops callbacks,
as the field controller does.
"""

from __future__ import annotations

import os
import unittest

from atalaia_sim.core import Core, FieldOps, Node, find_library


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and CORE is None:
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the shared core library is not built")

FIELD_SCRIPT = """
local fs = state.field { held = 0 }

on("zone.captured", function(ev)
  local zones = field.nodes("zone")
  local ids = {}
  for _, n in ipairs(zones) do ids[#ids + 1] = n.id end
  local owner = field.common_owner(ids)
  fs.held = #zones
  if owner then
    emit("x.test.allheld", { team = owner })
    field.send(ids[1], "message", { text = owner .. " holds all" })
  end
  log("owner of 2: " .. tostring(field.owner(2)))
end)
"""


@unittest.skipIf(CORE is None, "the shared core library is not built")
class FieldOpsTests(unittest.TestCase):
    def make(self, owners):
        self.sent = []
        self.state = []
        self.events = []
        self.logs = []
        self.roles = []

        def nodes(role):
            self.roles.append(role)
            return [{"id": 1, "name": "alpha", "role": "zone"}, {"id": 2, "name": "bravo", "role": "zone"}]

        ops = FieldOps(
            nodes=nodes,
            owner=lambda node_id: owners.get(node_id),
            send=lambda node_id, cmd, params: self.sent.append((node_id, cmd, params)) or True,
            on_state=lambda key, value: self.state.append((key, value)),
        )
        node = Node(CORE, 0, 1, ["red", "blue"], {}, FIELD_SCRIPT, "test/field.lua",
                    on_event=self.events.append, on_log=self.logs.append, field_ops=ops)
        self.assertTrue(node.loaded, node.last_error)
        node.input("game.start")
        return node

    def test_common_owner_reaches_python(self):
        node = self.make({1: "red", 2: "red"})
        self.assertTrue(node.input("zone.captured", {"team": "red"}))
        self.assertEqual(self.roles, ["zone"])
        self.assertEqual(self.state, [("held", 2)])
        self.assertEqual(self.sent, [(1, "message", {"text": "red holds all"})])
        custom = [e for e in self.events if e.type == "x.test.allheld"]
        self.assertEqual(len(custom), 1)
        self.assertEqual(custom[0].data, {"team": "red"})
        self.assertIn("owner of 2: red", self.logs)

    def test_split_owners(self):
        self.make({1: "red", 2: "blue"}).input("zone.captured", {"team": "red"})
        self.assertEqual(self.sent, [])
        self.assertIn("owner of 2: blue", self.logs)

    def test_no_owner_is_nil(self):
        self.make({}).input("zone.captured", {"team": "red"})
        self.assertIn("owner of 2: nil", self.logs)

    def test_regular_node_has_no_field_api(self):
        node = Node(CORE, 3, 1, ["red"], {}, "assert(field == nil)\nlocal f = state.field{}\n",
                    "test/node.lua")
        self.assertTrue(node.loaded, node.last_error)


if __name__ == "__main__":
    unittest.main()
