# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The boxes' modules and outputs on the controller (outputs.py; draft RFC "The expansion port", increment 3).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import unittest

from atalaia_controller import outputs
from atalaia_controller.modes import parse_package
from atalaia_sim.mode import ModeError
from atalaia_sim.protocol import CAPABILITY_ROLE_NAMES, CAPABILITY_TYPES

ZONE = {"requires": ["team_input"], "optional": ["team_display", "audio", "display"]}
TARGET = {"requires": ["hit", "led"], "optional": ["display", "audio", "smell"]}
# Bomb's role since increment 4: its outputs are optional, and it names the ones it switches (EXP-22).
BOMB = {"requires": ["team_input"], "optional": ["keypad", "audio", "led", "display", "output"],
        "outputs": ["smoke", "siren"]}
# A role that cannot play without an output.
ALARM = {"requires": ["team_input", "output"], "outputs": ["siren"]}


def node(n: int, role: str, caps, modules=None) -> dict:
    return {"node": n, "name": f"box-{n}", "role": role, "capabilities": caps, "modules": modules}


class RoleNameTests(unittest.TestCase):
    def test_role_names_are_met_by_their_types(self):
        """The mapping a mode's requires: names need (protocol/schema/capabilities.yaml role_names): team_input
        by team buttons, a keypad or an NFC reader; team_display by LEDs or a screen; a type by itself; any
        other name is never checked."""
        self.assertEqual(CAPABILITY_ROLE_NAMES, {"team_input": ("button", "keypad", "nfc"),
                                                 "team_display": ("led", "display")})
        for types, name, want in (({"button"}, "team_input", True), ({"keypad"}, "team_input", True),
                                  ({"nfc"}, "team_input", True), ({"display", "led"}, "team_input", False),
                                  ({"led"}, "team_display", True), ({"display"}, "team_display", True),
                                  ({"audio"}, "team_display", False), ({"hit"}, "hit", True),
                                  ({"button"}, "hit", False), ({"button"}, "smell", None), (set(), "gps", False)):
            with self.subTest(name=name, types=types):
                self.assertIs(outputs.has(types, name), want)

    def test_hello_ids_to_types(self):
        ids = {k: v.id for k, v in CAPABILITY_TYPES.items()}
        self.assertEqual(outputs.types_of([ids["button"], ids["output"], 0, 200, True, "x"]), {"button", "output"})
        self.assertEqual(outputs.types_of(None), set())


class StartCheckTests(unittest.TestCase):
    def check(self, *nodes):
        return outputs.check_nodes(nodes, {"zone": ZONE, "target": TARGET, "bomb": BOMB, "alarm": ALARM}.get)

    def test_a_box_without_what_its_role_requires(self):
        out = self.check(node(4, "zone", [1, 3, 5]), node(5, "zone", [3, 12]), node(6, "target", [3, 4, 5]))
        self.assertEqual(out["missing_caps"], [
            {"node": 5, "name": "box-5", "role": "zone", "capability": "team_input"},
            {"node": 6, "name": "box-6", "role": "target", "capability": "hit"}])
        self.assertEqual([(w["node"], w["capabilities"]) for w in out["warnings"]], [(5, ["audio"])])
        self.assertEqual(out["warnings"][0]["code"], "optional_caps")

    def test_nodes_that_report_nothing_are_not_checked(self):
        """A box from before the RFC (an empty HELLO list), a phone, ids this controller does not know."""
        out = self.check(node(4, "zone", []), node(5, "zone", None), node(6, "target", [0, 99]),
                         node(7, "nosuchrole", [3]))
        self.assertEqual(out, {"missing_caps": [], "warnings": [], "not_checked": [], "outputs_disabled": []})

    def test_a_simple_output_counts_and_is_not_checked(self):
        mods = outputs.modules_of("g46:servo:siren;5c:out4/1.0.0:strobe,smoke")
        out = self.check(node(4, "zone", [1, 3, 5, 11], mods))
        self.assertEqual(out["missing_caps"], [])
        self.assertEqual([(u["node"], u["capability"]) for u in out["not_checked"]], [(4, "siren")])
        self.assertEqual(out["not_checked"][0]["text"], "siren on box-4: not checked (simple output)")


    def test_a_roles_outputs(self):
        """Required and optional outputs feed missing_caps and optional_caps; a box with outputs but none of
        those its role's outputs: names gets the "outputs" warning; one with any of them, none (increment 4)."""
        ids = {k: v.id for k, v in CAPABILITY_TYPES.items()}
        b, o = ids["button"], ids["output"]
        out = self.check(node(4, "bomb", [b]), node(5, "alarm", [b]))
        self.assertEqual(out["missing_caps"], [{"node": 5, "name": "box-5", "role": "alarm", "capability": "output"}])
        self.assertEqual([(w["code"], w["node"], w["capabilities"]) for w in out["warnings"]],
                         [("optional_caps", 4, ["keypad", "audio", "led", "display", "output"])])
        horn = outputs.modules_of("g46:servo:horn")
        out = self.check(node(4, "bomb", [b, ids["keypad"], ids["audio"], ids["led"], ids["display"], o], horn),
                         node(5, "alarm", [b, o], horn))
        self.assertEqual(out["missing_caps"], [])
        self.assertEqual([(w["code"], w["node"], w["capabilities"]) for w in out["warnings"]],
                         [("outputs", 4, ["smoke", "siren"]), ("outputs", 5, ["siren"])])
        self.assertEqual(out["warnings"][0]["text"],
                         "box-4 (bomb) has none of the outputs the mode would switch: smoke, siren")
        self.assertEqual([u["capability"] for u in out["not_checked"]], ["horn", "horn"])
        smoke = outputs.modules_of("g46:servo:smoke")
        out = self.check(node(4, "bomb", [b, o], smoke), node(5, "alarm", [b, o], None))  # 5: no node.modules yet
        self.assertEqual([w["code"] for w in out["warnings"]], ["optional_caps"])
        lost = outputs.mark_lost(outputs.modules_of("5c:out4/1.0.0:siren"), "5c:out4/1.0.0:siren")
        out = self.check(node(5, "alarm", [b, o], lost))
        self.assertEqual([(w["code"], w["node"]) for w in out["warnings"]], [("outputs", 5)])

    def test_a_scenarios_triggers_count_as_the_roles_outputs(self):
        """A scenario's box runs the objectives package's role, which lists no output: the functions its
        triggers switch on that box (the node's ``outputs``) count as the role's outputs: with output
        optional (increment 5's leftover)."""
        objective = {"requires": ["team_input"], "optional": ["keypad", "display"]}
        ids = {k: v.id for k, v in CAPABILITY_TYPES.items()}
        b, o = ids["button"], ids["output"]
        spec = outputs.with_outputs(objective, ["siren", "horn", "siren"])
        self.assertEqual(spec, {"requires": ["team_input"], "optional": ["keypad", "display", "output"],
                                "outputs": ["siren", "horn"]})
        self.assertIs(outputs.with_outputs(objective, []), objective)
        self.assertIs(outputs.with_outputs(objective, None), objective)
        self.assertEqual(outputs.with_outputs(BOMB, ["horn", "smoke"])["outputs"], ["smoke", "siren", "horn"])
        self.assertEqual(outputs.with_outputs(ALARM, ["horn"])["optional"], [])  # output already required
        self.assertEqual(outputs.with_outputs(None, ["horn"]), {"optional": ["output"], "outputs": ["horn"]})

        def check(*nodes):
            return outputs.check_nodes(nodes, {"objective": objective}.get)

        def scenario_node(n, caps, mods, fns):
            return {**node(n, "objective", caps, mods), "outputs": fns}

        k, d = ids["keypad"], ids["display"]
        strobe = outputs.modules_of("g46:servo:strobe")
        out = check(scenario_node(4, [b, k, d, o], strobe, ["siren", "horn"]),
                    scenario_node(5, [b, k, d], None, ["horn"]), scenario_node(6, [b, k, d, o], strobe, []))
        self.assertEqual(out["missing_caps"], [])
        self.assertEqual([(w["code"], w["node"], w["capabilities"]) for w in out["warnings"]],
                         [("outputs", 4, ["siren", "horn"]), ("optional_caps", 5, ["output"])])
        self.assertEqual(out["warnings"][0]["text"],
                         "box-4 (objective) has none of the outputs the mode would switch: siren, horn")
        out = check(scenario_node(4, [b, k, d, o], outputs.modules_of("g46:servo:horn"), ["siren", "horn"]))
        self.assertEqual(out["warnings"], [])


    def test_outputs_fitted_but_not_enabled_are_a_note(self):
        """EXPL-12, EXPL-13: a box's node.outputs_disabled names outputs its admin has not enabled; when its
        role's outputs: (or its scenario's) would switch one, the start check gives a note, never a
        refusal or a warning of its own; outputs no role would switch, or a box that never said, give none."""
        ids = {k: v.id for k, v in CAPABILITY_TYPES.items()}
        b, o = ids["button"], ids["output"]

        def with_off(n, role, caps, mods, off, **extra):
            return {**node(n, role, caps, mods), "outputs_disabled": outputs.modules_of(off), **extra}

        out = self.check(with_off(4, "bomb", [b, o], outputs.modules_of("g46:servo:smoke"), "g45:servo:siren"),
                         with_off(5, "bomb", [b], None, "g46:servo:horn;g45:servo:smoke"),
                         with_off(6, "bomb", [b], None, "g46:servo:horn"),
                         with_off(7, "alarm", [b], None, "g46:servo:siren"),
                         with_off(8, "zone", [b], None, "g46:servo:siren"),
                         node(9, "bomb", [b]))
        self.assertEqual([(d["node"], d["capabilities"]) for d in out["outputs_disabled"]],
                         [(4, ["siren"]), (5, ["smoke"]), (7, ["siren"])])
        self.assertEqual(out["outputs_disabled"][0], {
            "node": 4, "name": "box-4", "role": "bomb", "capabilities": ["siren"],
            "text": "box-4 (bomb): siren fitted, not enabled by the box's admin (enable at the box with the admin PIN)"})
        # A note only: what the box lacks right now is still missing_caps or a warning, as before.
        self.assertEqual(out["missing_caps"], [{"node": 7, "name": "box-7", "role": "alarm", "capability": "output"}])
        self.assertNotIn("outputs_disabled", {w["code"] for w in out["warnings"]})
        # Every output enabled: the empty text, no note.
        out = self.check(with_off(4, "bomb", [b, o], outputs.modules_of("g46:servo:siren"), ""))
        self.assertEqual(out["outputs_disabled"], [])
        # A scenario's box: the functions its triggers switch count as its role's outputs:.
        objective = {"requires": ["team_input"], "optional": ["keypad", "display"]}
        out = outputs.check_nodes([with_off(4, "objective", [b], None, "g46:servo:horn;g45:servo:strobe",
                                            outputs=["strobe", "siren"])], {"objective": objective}.get)
        self.assertEqual([(d["node"], d["capabilities"]) for d in out["outputs_disabled"]], [(4, ["strobe"])])
        self.assertEqual(outputs.modules_of(""), [])


class ScenarioOutputsTests(unittest.TestCase):
    def test_the_compiled_outputs_in_the_meta(self):
        from atalaia_controller.scenario_service import Meta, box_outputs
        self.assertEqual(box_outputs({"alpha": ["siren", "horn"], "bravo": [], "c": "x", "d": [1, "light"]}),
                         {"alpha": ["siren", "horn"], "d": ["light"]})
        self.assertEqual(box_outputs(None), {})
        text = ("id: org.club.s\nversion: '1'\nkind: scenario\nname: S\nscenario:\n  nodes: {alpha: {role: objective}}\n"
                "  objectives: []\n  outputs: {alpha: [siren, horn]}\n")
        meta = Meta.parse(text)
        assert meta is not None
        self.assertEqual(meta.node_outputs("alpha"), ["siren", "horn"])
        self.assertEqual((meta.node_outputs("bravo"), meta.node_outputs(None)), ([], []))
        before = Meta.parse(text.replace("  outputs: {alpha: [siren, horn]}\n", ""))
        assert before is not None
        self.assertEqual(before.outputs, {})


class ModulesTests(unittest.TestCase):
    def test_modules_and_a_lost_one(self):
        mods = outputs.modules_of("g46:servo:siren;58:target/1.0.0:hit")
        self.assertEqual(mods[0], {"address": "g46", "model": "servo", "fw": None, "caps": ["siren"], "feedback": False})
        self.assertIsNone(outputs.modules_of("nonsense"))
        self.assertIsNone(outputs.modules_of(5))
        lost = outputs.mark_lost(mods, "58:target/1.0.0:hit")
        self.assertEqual([m.get("lost", False) for m in lost], [False, True])
        self.assertIsNone(outputs.mark_lost(mods, "5c:out4/1.0.0:strobe"))  # not one it had
        self.assertEqual(outputs.output_caps(lost), {"siren"})
        self.assertEqual(outputs.simple_outputs(lost), ["siren"])


class ParamsTests(unittest.TestCase):
    def test_the_controller_sets_src_and_the_gms_default(self):
        self.assertEqual(outputs.output_params({"capability": "siren", "act": "on", "src": "field"}, "gm"),
                         ({"capability": "siren", "act": "on", "ms": 5000, "src": "gm"}, None))
        self.assertEqual(outputs.output_params({"capability": "siren", "act": "on"}, "field"),
                         (None, "ms is required for on, pulse and pattern"))
        self.assertEqual(outputs.output_params({"capability": "siren", "act": "off", "ms": 3, "on_ms": 9}, "gm"),
                         ({"capability": "siren", "act": "off", "src": "gm"}, None))
        self.assertEqual(outputs.output_params({"capability": "s", "act": "pulse", "ms": 9, "on_ms": 5}, "gm")[0],
                         {"capability": "s", "act": "pulse", "ms": 9, "src": "gm"})
        self.assertEqual(outputs.output_params(["siren"], "gm")[0], None)

    def test_the_rate_limit(self):
        rate = outputs.RateLimit()
        self.assertEqual(rate.wait_ms(4, "on", 0), 0)
        rate.sent(4, "on", 1000)
        self.assertEqual(rate.wait_ms(4, "pulse", 2000), 1000)
        self.assertEqual(rate.wait_ms(4, "off", 2000), 0)
        self.assertEqual(rate.wait_ms(5, "on", 2000), 0)
        rate.sent(4, "off", 2500)  # an off never moves the next start
        self.assertEqual(rate.wait_ms(4, "on", 3000), 0)



class UploadTests(unittest.TestCase):
    def test_an_uploaded_modes_outputs(self):
        """The Pi takes a role's outputs: (the simulator's check_manifest) and refuses a bad one (increment 4)."""
        def package(role: str) -> dict:
            return {"mode.yaml": f"id: org.test.alarm\nversion: 1.0\nroles: {{ alarm: {role} }}\n",
                    "node.lua": "local x = 1\n"}

        pkg = parse_package(package("{ requires: [team_input], optional: [output], outputs: [siren, strobe] }"))
        self.assertEqual(pkg.mode.roles["alarm"]["outputs"], ["siren", "strobe"])
        for role, message in (("{ optional: [output], outputs: [klaxon] }", "output functions"),
                              ("{ requires: [team_input], outputs: [siren] }", "needs output"),
                              ("{ optional: [output], outputs: siren }", "outputs is a list")):
            with self.subTest(role), self.assertRaisesRegex(ModeError, message):
                parse_package(package(role))


if __name__ == "__main__":
    unittest.main()
