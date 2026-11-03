# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A box's outputs in the simulator and a role's `outputs:` in a manifest (draft RFC "The expansion
port", increment 4): box_outputs.py against the box's output layer's rules, field.send(node, "output")
as CMD 12, and the manifest check.

    cd simulator && python -m unittest discover -s tests
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from atalaia_sim.box_outputs import GRACE_MS, BoxOutputs, fitted_outputs
from atalaia_sim.core import Core, find_library
from atalaia_sim.live import LiveGame
from atalaia_sim.mode import ModeError, load_mode
from atalaia_sim.sim import Simulation

MODES = Path(__file__).resolve().parents[2] / "modes"
TEAMS = ["red", "blue"]


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and CORE is None:
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the shared core library is not built")


class ModelTests(unittest.TestCase):
    def box(self, **fitted):
        told: list[tuple[int, dict]] = []
        box = BoxOutputs(fitted_outputs(fitted or {"siren": 30, "smoke": 5}, "box"), lambda t, d: told.append((t, d)))
        return box, told

    def test_only_while_the_game_runs_and_within_its_max_on(self):
        box, told = self.box()
        self.assertEqual(box.switch(0, "siren", "pulse", 5000), "not_now")  # no game yet
        box.game_start(1000)
        self.assertEqual(box.switch(1000, "smoke", "pulse", 60_000), "ok")  # max on 5 s
        self.assertEqual(box.switch(1000, "siren", "on"), "ok")             # on: its max on
        self.assertEqual(box.switch(1000, "strobe", "on"), "no_such")       # not fitted: nothing
        self.assertEqual(told, [(1000, {"capability": "smoke", "ms": 5000, "source": "script"}),
                                (1000, {"capability": "siren", "ms": 30_000, "source": "script"})])
        self.assertTrue(box.level("smoke", 5999))
        self.assertFalse(box.level("smoke", 6000))
        box.switch(2000, "siren", "off")
        self.assertEqual(told[-1], (2000, {"capability": "siren", "ms": 0, "source": "script"}))
        box.switch(2500, "siren", "off")  # already off: nothing more told
        self.assertEqual(len(told), 3)

    def test_pause_end_grace_and_halt(self):
        box, told = self.box()
        box.game_start(0)
        box.switch(0, "siren", "pulse", 20_000)
        box.pause(1000)
        self.assertFalse(box.level("siren", 1000))
        box.resume(2000)
        self.assertFalse(box.level("siren", 2000))  # a resumed game does not turn it back on
        box.switch(3000, "siren", "pulse", 20_000)
        box.end(4000)
        self.assertFalse(box.level("siren", 4000))  # off at the end, untold
        self.assertEqual(len(told), 2)
        self.assertEqual(box.switch(4000, "siren", "pulse", 20_000), "ok")  # the end's grace: at most 10 s
        self.assertEqual(told[-1][1]["ms"], GRACE_MS)
        self.assertFalse(box.level("siren", 4000 + GRACE_MS))
        self.assertEqual(box.switch(4000 + GRACE_MS - 400, "smoke", "pulse", 1000), "not_now")
        self.assertEqual(box.switch(4000 + GRACE_MS, "smoke", "pulse", 1000), "not_now")
        box.game_start(20_000)
        box.switch(20_000, "siren", "on")
        box.halt(21_000)
        self.assertFalse(box.level("siren", 21_000))
        self.assertEqual(box.switch(21_000, "siren", "on"), "not_now")

    def test_patterns_and_the_simple_outputs_floor(self):
        box, told = self.box()
        box.game_start(0)
        self.assertEqual(box.switch(0, "siren", "pattern", 10_000, 400, 600), "bad_args")  # under 500 ms
        self.assertEqual(box.switch(0, "siren", "pattern", 10_000, 1000, 500), "ok")
        self.assertEqual([box.level("siren", t) for t in (0, 999, 1000, 1499, 1500)], [True, True, False, False, True])
        self.assertEqual(box.switch(0, "smoke", "pulse", 100), "ok")
        self.assertEqual(told[-1][1]["ms"], 500)  # a switch shows a change for at least 500 ms
        self.assertEqual(box.switch(0, "smoke", "pulse", 0), "bad_args")

    def test_a_scripts_calls(self):
        box, told = self.box()
        box.game_start(0)
        self.assertTrue(box.script_call(0, "siren", "pulse", [2500.0]))
        self.assertTrue(box.script_call(0, "smoke", "pulse", []))  # no duration: nothing
        self.assertTrue(box.script_call(0, "smoke", "pattern", [600, 600]))  # no ms: nothing
        self.assertFalse(box.script_call(0, "ring", "fill", ["red"]))  # not an output: the shell's
        self.assertFalse(box.script_call(0, "siren", "fill", ["red"]))
        self.assertEqual([d["capability"] for _, d in told], ["siren"])
        self.assertEqual(box.states(1000)[0], {"capability": "siren", "on": True, "left_ms": 1500, "pattern": None,
                                               "source": "script", "max_on_s": 30})

    def test_a_tests_outputs(self):
        self.assertEqual(fitted_outputs(["siren"], "x"), {"siren": 30_000})
        self.assertEqual(fitted_outputs({"smoke": 4}, "x"), {"smoke": 4000})
        for bad in ("siren", {"siren": 0}, {"siren": 601}, {"siren": True}, [3]):
            with self.subTest(bad), self.assertRaises(ValueError):
                fitted_outputs(bad, "x")


class ManifestTests(unittest.TestCase):
    def test_a_roles_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "node.lua").write_text("local x = 1\n")
            good = ("{ optional: [output], outputs: [smoke, siren] }", "{ requires: [output], outputs: [siren.2] }",
                    "{ optional: [led, output], outputs: [out.3, horn, light, strobe] }")
            bad = [("{ optional: [output], outputs: siren }", "outputs is a list"),
                   ("{ optional: [output], outputs: [] }", "outputs is a list"),
                   ("{ optional: [output], outputs: [siren, siren] }", "different"),
                   ("{ optional: [output], outputs: [bell] }", "output functions"),
                   ("{ optional: [output], outputs: [out.0] }", "output functions"),
                   ("{ optional: [output], outputs: [Siren] }", "output functions"),
                   ("{ optional: [output], outputs: [siren, smoke, strobe, light, horn, out.1, out.2, out.3, out.4] }",
                    "1-8"),
                   ("{ optional: [led], outputs: [siren] }", "needs output"),
                   ("{ outputs: [siren] }", "needs output")]
            for role in good:
                (path / "mode.yaml").write_text(f"id: org.t.m\nversion: 1\nroles: {{ a: {role} }}\n")
                with self.subTest(role):
                    self.assertIn("outputs", load_mode(path).roles["a"])
            for role, message in bad:
                (path / "mode.yaml").write_text(f"id: org.t.m\nversion: 1\nroles: {{ a: {role} }}\n")
                with self.subTest(role), self.assertRaisesRegex(ModeError, message):
                    load_mode(path)

    def test_the_built_in_roles_that_use_outputs(self):
        self.assertEqual(load_mode(MODES / "bomb").roles["bomb"]["outputs"], ["smoke", "siren"])
        self.assertEqual(load_mode(MODES / "master_satellites").roles["master"]["outputs"], ["siren"])
        self.assertNotIn("outputs", load_mode(MODES / "master_satellites").roles["satellite"])


@unittest.skipIf(CORE is None, "the shared core library is not built")
class FieldSendTests(unittest.TestCase):
    def sim(self, field_script: str, outputs=None) -> Simulation:
        mode = load_mode(MODES / "master_satellites")
        mode.field_script = field_script
        sim = Simulation(CORE, mode, {"m": "master", "s": "satellite"}, TEAMS, mode.resolve_params({}, TEAMS),
                         outputs=outputs)
        self.addCleanup(sim.close)
        return sim

    def test_cmd_12_from_a_field_script(self):
        sim = self.sim('on("game.start", function()\n'
                       '  log(tostring(field.send(1, "output", { capability = "siren", act = "pulse", ms = 3000 })))\n'
                       '  log(tostring(field.send(1, "output", { capability = "siren", act = "pulse", ms = 3000 })))\n'
                       '  log(tostring(field.send(1, "output", { capability = "siren", act = "off", ms = 9 })))\n'
                       '  log(tostring(field.send(1, "output", { capability = "siren", act = "on" })))\n'
                       '  log(tostring(field.send(1, "output", { capability = "*", act = "pulse", ms = 9 })))\n'
                       '  log(tostring(field.send(2, "output", { capability = "siren", act = "pulse", ms = 3000 })))\n'
                       'end)\n'
                       'on("output.switched", function(e) log("switched " .. e.capability .. " " .. e.ms) end)\n')
        sim.start()
        # The second start within 2 s is held back, an off goes, an on without ms and * with pulse are
        # refused; the satellite has no siren, so its CMD 12 does nothing there.
        self.assertEqual(sim.field_logs, ["true", "false", "true", "false", "false", "true",
                                          "switched siren 3000", "switched siren 0"])
        self.assertEqual([(c[1], c[3]) for c in sim.field_commands],
                         [("m", {"capability": "siren", "act": "pulse", "ms": 3000, "src": "field"}),
                          ("m", {"capability": "siren", "act": "off", "src": "field"}),
                          ("s", {"capability": "siren", "act": "pulse", "ms": 3000, "src": "field"})])
        self.assertEqual([(e.node, e.data) for e in sim.events if e.type == "output.switched"],
                         [("m", {"capability": "siren", "ms": 3000, "source": "field"}),
                          ("m", {"capability": "siren", "ms": 0, "source": "field"})])

    def test_an_unreachable_box_misses_it_and_a_reboot_turns_outputs_off(self):
        sim = self.sim('on("cmd.mode", function() end)\n', outputs={"m": ["siren"], "s": ["siren"]})
        sim.start()
        sim.set_reachable("s", False)
        self.assertTrue(sim._field_send(2, "output", {"capability": "siren", "act": "pulse", "ms": 5000}))
        self.assertFalse(sim.outputs("s").level("siren", sim.time_ms))
        sim._field_send(1, "output", {"capability": "siren", "act": "pulse", "ms": 5000})
        self.assertTrue(sim.outputs("m").level("siren", sim.time_ms))
        sim.reboot("m")
        self.assertFalse(sim.outputs("m").level("siren", sim.time_ms))
        self.assertEqual(sim.outputs("m").game, "running")

    def test_the_web_view_shows_the_outputs(self):
        def make() -> Simulation:
            mode = load_mode(MODES / "bomb")
            return Simulation(CORE, mode, {"bomb": "bomb"}, TEAMS, mode.resolve_params({"smoke_s": 3}, TEAMS))

        live = LiveGame(make)
        self.addCleanup(live.close)
        node = live.snapshot()["nodes"][0]
        self.assertEqual([(o["capability"], o["on"]) for o in node["switched"]], [("smoke", False), ("siren", False)])


if __name__ == "__main__":
    unittest.main()
