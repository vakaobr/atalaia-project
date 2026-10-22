# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The sandbox-escape battery through the ctypes bindings and the simulator (phase 5 plan
phase 5, decisions P5R-13, P5C-14 to P5C-16).

The C battery (core/tests/test_sandbox_escape.c, under ASan and UBSan in CI) tries every
escape against the runtime itself. These tests run escape attempts where the core meets
a host: box and field scripts loaded through the simulator's ctypes bindings, with field
ops answered from Python (odd answers, a callback that raises), and a whole mode in the
simulator whose box script trips the sandbox while the rest of the field plays on.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from atalaia_sim.core import Core, FieldOps, Node, find_library
from atalaia_sim.mode import load_mode
from atalaia_sim.testing import run_test

try:
    CORE = Core(find_library())
except (FileNotFoundError, OSError):  # pragma: no cover - check.sh always has it
    CORE = None

REDUCED = 64 * 1024  # a Reduced box's Lua heap (P2-1)

GLOBALS = """
for _, name in ipairs({'io', 'os', 'require', 'package', 'debug', 'load', 'loadfile', 'dofile',
                       'loadstring', 'collectgarbage', 'setfenv', 'getfenv', 'newproxy', 'module'}) do
  if _G[name] ~= nil or rawget(_G, name) ~= nil then log('escaped ' .. name) end
end
if string.dump or math.random or ('').dump then log('escaped') end
on('go', function() log('ok') end)
"""

# (name, script, the status it ends in after "go": running with "ok" logged, or halted)
CASES = [
    ("globals", GLOBALS, "running"),
    ("busy_loop", "on('go', function() while true do end end)", "halted"),
    ("coroutine_loop", "on('go', function() coroutine.wrap(function() while true do end end)() end)", "halted"),
    ("pcall_loop", "on('go', function() while true do pcall(function() while true do end end) end end)", "halted"),
    ("memory", "on('go', function() local t = {} for i = 1, 1e7 do t[i] = {i} end end)", "halted"),
    ("error_tostring_loop",
     "on('go', function() error(setmetatable({}, { __tostring = function() while true do end end })) end)\n"
     "on('again', function() log('ok') end)", "any"),
    ("cycles",
     "local t = {} t.t = t\n"
     "on('go', function() pcall(emit, 'x.club.c', t) pcall(ui.screen, 'x', t)\n"
     "  if field then pcall(field.send, 1, 'mode', t) end log('ok') end)", "running"),
]


class Ops:
    """Field ops a host gives a controller's script, with odd answers on purpose."""

    def __init__(self, raise_in_send: bool = False):
        self.sent = []
        self.raise_in_send = raise_in_send

    def nodes(self, role):
        if role == "odd":
            return [{"id": 70000}, {"id": -1}, {"id": "x"}, {"role": "zone"}, {"id": 1.5}, "text", None]
        return [{"id": 1, "role": "zone"}, {"id": 2, "role": "zone"}]

    def owner(self, node_id):
        return "red" if node_id == 1 else ("é" * 300 if node_id == 2 else None)

    def send(self, node_id, cmd, params):
        if self.raise_in_send:
            raise RuntimeError("the host failed")
        self.sent.append((node_id, cmd, params))
        return True

    def field_ops(self) -> FieldOps:
        return FieldOps(nodes=self.nodes, owner=self.owner, send=self.send)


@unittest.skipIf(CORE is None, "needs the shared core library")
class SandboxEscapeTests(unittest.TestCase):
    def run_script(self, script, controller, mem_limit, ops=None):
        logs = []
        node = Node(CORE, 0 if controller else 3, 7, ["red", "blue"], {}, script, "=escape", mem_limit=mem_limit,
                    instr_limit=200000, on_log=logs.append,
                    field_ops=(ops or Ops()).field_ops() if controller else None)
        try:
            loaded = node.loaded
            if loaded:
                node.advance(1000)
                node.input("go")
                node.input("again")
                node.advance(5000)
            return loaded, node.status, logs
        finally:
            node.close()

    def test_box_and_field_scripts(self):
        for name, script, expected in CASES:
            for controller in (False, True):
                for mem_limit in (REDUCED, 256 * 1024):
                    with self.subTest(case=name, controller=controller, mem=mem_limit):
                        loaded, status, logs = self.run_script(script, controller, mem_limit)
                        self.assertTrue(loaded)
                        self.assertFalse([line for line in logs if line.startswith("escaped")], logs)
                        if expected == "running":
                            self.assertEqual(status, "running")
                            self.assertIn("ok", logs)
                        elif expected == "halted":
                            self.assertEqual(status, "halted")

    def test_odd_host_answers(self):
        script = """
        on('go', function()
          local ids = {}
          for _, n in ipairs(field.nodes('odd')) do ids[#ids + 1] = tostring(n.id) end
          log('odd ' .. table.concat(ids, ','))
          log('owner ' .. tostring(field.owner(2) and #field.owner(2)))
          pcall(field.send, 1, 'set_owner', { team = 'blue' })
          log('ok')
        end)
        """
        loaded, status, logs = self.run_script(script, True, REDUCED)
        self.assertTrue(loaded)
        self.assertEqual(status, "running", logs)
        self.assertIn("ok", logs)
        # A callback that raises in the host: the script goes on, the send failed.
        ops = Ops(raise_in_send=True)
        script = "on('go', function() local ok, sent = pcall(field.send, 1, 'set_owner', {}) log(tostring(sent)) log('ok') end)"
        with self.assertLogs("atalaia_sim.core", level="ERROR") as host:
            loaded, status, logs = self.run_script(script, True, REDUCED, ops)
        self.assertIn("field.send failed in the host", host.output[0])
        self.assertEqual(status, "running", logs)
        self.assertIn("ok", logs)
        self.assertNotIn("true", logs)

    def test_bytecode_is_refused(self):
        for source in ("\x1bLua", "\x1bLuaT\x00\x19\x93\r\n\x1a\n"):
            node = Node(CORE, 3, 7, ["red", "blue"], {}, source, "=bytecode")
            try:
                self.assertFalse(node.loaded)
            finally:
                node.close()

    def test_a_box_that_trips_the_sandbox_leaves_the_game_playing(self):
        """In the simulator: one box's script halts (the watchdog), the other box and the
        controller's script play on; nothing in either script reaches outside the sandbox."""
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "escape"
            (folder / "tests").mkdir(parents=True)
            (folder / "mode.yaml").write_text(
                "id: org.test.escape\nversion: 0.1.0\nlicense: MIT\nmin_tier: reduced\nkind: mode\n"
                "name: Escape\nroles:\n  zone: { requires: [team_input] }\n", encoding="utf-8")
            (folder / "node.lua").write_text(
                GLOBALS.replace("log('escaped", "emit('x.test.escaped', {}) log('escaped") +
                "on('x.test.loop', function() while true do end end)\n"
                "on('team_input.press', function(e) emit('x.test.pressed', { team = e.team }) end)\n",
                encoding="utf-8")
            (folder / "field.lua").write_text(
                GLOBALS.replace("log('escaped", "emit('x.test.escaped', {}) log('escaped") +
                "on('x.test.pressed', function(e) score.add(e.team, 1, 'press') end)\n", encoding="utf-8")
            (folder / "tests" / "escape.yaml").write_text(
                "name: escape\nnodes: { alpha: zone, bravo: zone }\nsteps:\n"
                "  - input: { node: alpha, type: x.test.loop }\n"
                "  - expect: { type: script.halted, node: alpha }\n"
                "  - expect_status: { node: alpha, status: halted }\n"
                "  - press: { node: bravo, team: red }\n"
                "  - expect: { type: x.test.pressed, node: bravo }\n"
                "  - wait: 1\n"
                "  - expect_score: { team: red, points: 1 }\n"
                "  - expect_status: { node: bravo, status: running }\n", encoding="utf-8")
            mode = load_mode(folder)
            result = run_test(CORE, mode, mode.tests[0])
            self.assertTrue(result.passed, result.message + "\n" + "\n".join(result.log))
            self.assertFalse([line for line in result.log if "x.test.escaped" in line], result.log)


if __name__ == "__main__":
    unittest.main()
