# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario compiler and validator (atalaia_controller.scenarios, ADR-P4-6 as amended, plan
phase 7; since decision PE24-109 the core's, core/scenario/, with Python reading the text): the
shared vectors (protocol/vectors/scenario.json), every objective type compiled and run in the
simulator over org.atalaia.objectives, Foxhound recompiled from a manifest and played by the
objectives package's own YAML tests, Lua escaping of hostile texts, the core's load check, the
manifest's data tree (aliases, dates, depth) and the command line. Every simulated run fails on a
Simulation.problems entry (run_test).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import copy
import datetime
import io
import json
import os
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

from support import CORE
from atalaia_controller.modes import ModeRegistry
from atalaia_controller.scenarios import (CoreUnavailable, LuaError, ManifestError, ScenarioError, check_package,
                                          compile_scenario, load, lua_literal, validate)
from atalaia_controller.scenarios import cli, compiler
from atalaia_controller.scenarios.validator import errors
from atalaia_controller.store import Store
from atalaia_sim.core import Node
from atalaia_sim.mode import ModeError, load_mode
from atalaia_sim.testing import run_test

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
MANIFESTS = HERE / "scenarios"
OBJECTIVES_DIR = REPO / "modes" / "objectives"
VECTORS = json.loads((REPO / "protocol" / "vectors" / "scenario.json").read_text(encoding="utf-8"))
HOSTILE = 'Pon"te]] os.exit(1) --[[ \\'


def lua_value(value: Any) -> str:
    """A value as field.lua writes it (core/scenario/luagen.lua)."""
    return lua_literal(value)


def lua_string(text: str) -> str:
    assert isinstance(text, str)
    return lua_literal(text)


def manifest(objectives: list[dict[str, Any]], nodes: dict[str, Any] | None = None, **top: Any) -> dict[str, Any]:
    return {"id": "org.test.scenario", "version": 1, "name": "Test", "nodes": nodes if nodes is not None else
            {"a": {"role": "objective"}, "b": {"role": "objective"}, "site": {"role": "bomb_site"}},
            "objectives": objectives, **top}


class VectorTests(unittest.TestCase):
    """protocol/vectors/scenario.json: the rules of ADR-P4-6 and controller/README.md, written as
    manifests with the problems (path, code, level) each must give, and nothing else."""

    def test_valid(self):
        for case in VECTORS["valid"]:
            with self.subTest(case["name"]):
                got = {(p.path, p.code, p.level) for p in validate(case["manifest"])}
                want = {(w["path"], w["code"], "warning") for w in case.get("warnings", [])}
                self.assertEqual(got, want)
                compile_scenario(case["manifest"])

    def test_invalid(self):
        for case in VECTORS["invalid"]:
            with self.subTest(case["name"]):
                got = {(p.path, p.code) for p in errors(validate(case["manifest"]))}
                want = {(e["path"], e["code"]) for e in case["errors"]}
                self.assertEqual(got, want)
                with self.assertRaises(ScenarioError) as raised:
                    compile_scenario(case["manifest"])
                self.assertTrue(raised.exception.problems)

    def test_every_problem_says_where_and_why(self):
        for case in VECTORS["invalid"]:
            for p in validate(case["manifest"]):
                self.assertTrue(p.message and p.code and p.level in ("error", "warning"), p)
                self.assertIn(p.code, str(p))

    def test_any_value_anywhere_is_a_problem_not_a_crash(self):
        """Mutated vectors (a fixed seed): validate and compile report, they never raise."""
        rng = random.Random(7)
        values = [None, 0, -1, 1.5, True, "x", "", [], {}, [1], {"a": 1}, "a\nb", 10**30, float("nan"),
                  ["nowhere"], {"team": "red"}]

        def mutate(o: Any, depth: int = 0) -> None:
            if isinstance(o, (dict, list)) and o:
                key = rng.choice(list(o)) if isinstance(o, dict) else rng.randrange(len(o))
                if rng.random() < 0.3 or depth > 4:
                    o[key] = copy.deepcopy(rng.choice(values))
                else:
                    mutate(o[key], depth + 1)

        cases = [c["manifest"] for c in VECTORS["valid"] + VECTORS["invalid"]]
        for _ in range(3000):
            m = copy.deepcopy(rng.choice(cases))
            for _ in range(rng.randint(1, 3)):
                mutate(m)
            try:
                compile_scenario(m)
            except ScenarioError:
                pass

    def test_not_a_manifest(self):
        for text, why in [("- a\n- b\n", "is a map"), ("id: [", "not valid YAML"),
                          ("id: a\nid: b\n", "given twice"), ("objectives:\n  - { id: a, id: b }\n", "given twice"),
                          ("x: " + "a" * 300_000, "larger than")]:
            with self.subTest(why), self.assertRaisesRegex(ManifestError, why):
                load(text)
        self.assertEqual(validate([1])[0].code, "bad_manifest")
        # YAML's safe loader: no Python objects.
        with self.assertRaises(ManifestError):
            load("id: !!python/object/apply:os.system ['true']\n")

    def test_json_is_a_manifest_too(self):
        text = json.dumps(load((MANIFESTS / "foxhound.yaml").read_text(encoding="utf-8")))
        self.assertEqual(validate(load(text)), [])

    def test_a_name_ends_where_it_seems(self):
        """PE24-106: Python's re "$" also matches before a final line feed; the patterns end with \\Z,
        so "hill\\n" is no id, and no name, role or code either."""
        for path, m in [
            ("id", manifest([{"id": "x", "name": "X", "type": "capture_and_hold", "target": "a"}],
                            id="org.test.scenario\n")),
            ("objectives[0].id", manifest([{"id": "hill\n", "name": "X", "type": "capture_and_hold", "target": "a"}])),
            ("objectives[0].params.code", manifest([{"id": "x", "name": "X", "type": "enter_code", "target": "a",
                                                     "params": {"code": "1234\n"}}])),
            ("params.rounds\n", manifest([{"id": "x", "name": "X", "type": "capture_and_hold", "target": "a"}],
                                         params={"rounds\n": {"type": "int", "default": 1}})),
            ("nodes.p.player", manifest([{"id": "x", "name": "X", "type": "escort", "target": "p",
                                          "params": {"destination": {"lat": 1, "lon": 1, "radius_m": 50}}}],
                                        nodes={"p": {"player": "vip\n"}})),
        ]:
            with self.subTest(path):
                self.assertIn(path, [p.path for p in errors(validate(m))])
        self.assertEqual(lua_value({"a\n": 1}), '{ ["a\\n"] = 1 }')

    def test_characters_past_u_ffff_written_as_surrogate_pairs(self):
        """PE24-107: JSON writes an emoji as two escapes (\\ud83d\\ude00) when it keeps to ASCII; PyYAML
        reads them as two surrogates, which made the validator raise (a 500 from POST
        /api/v1/scenarios/check). A pair is the character it encodes; half of one is a problem."""
        base = manifest([{"id": "x", "name": "X \U0001f600", "type": "capture_and_hold", "target": "a"}],
                        nodes={"a": {"role": "objective"}}, description="\U0001f600 \U0001f4a3")
        text = json.dumps(base)  # ensure_ascii: the emoji as surrogate-pair escapes
        self.assertIn("\\ud83d\\ude00", text)
        m = load(text)
        self.assertEqual(m, base)
        self.assertEqual(validate(m), [])
        self.assertIn(lua_string("X \U0001f600"), compile_scenario(m).field_lua)
        # YAML's own escapes too, in a key as well; a key that a pair makes equal to another is twice.
        self.assertEqual(load('a: "\\ud83d\\ude00"\n"\\ud83d\\ude00": "\\U0001F600"\n'),
                         {"a": "\U0001f600", "\U0001f600": "\U0001f600"})
        with self.assertRaisesRegex(ManifestError, "given twice"):
            load('"\\ud83d\\ude00": 1\n"\U0001f600": 2\n')
        # Half a pair, written as an escape, alone or in the wrong order: refused, said in words.
        for half in ("\\ud83d", "\\ude00", "\\ude00\\ud83d", "x\\ud83d y", "\\U0000D83D"):
            with self.subTest(half), self.assertRaisesRegex(ManifestError, "half of a surrogate pair"):
                load(text.replace("\\ud83d\\ude00", half, 1))
        # A lone surrogate in the text itself (a JSON body can carry one): the YAML reader refuses it.
        with self.assertRaisesRegex(ManifestError, "not valid YAML"):
            load(json.dumps(base, ensure_ascii=False).replace("\U0001f600", "\ud83d", 1))
        # A map built in code: the validator says where, rather than raising.
        for path, m in [("name", {**base, "name": "\ud83d"}),
                        ("objectives[0].name", manifest([{"id": "x", "name": "\udc00", "type": "survive"}])),
                        ("nodes", {**base, "nodes": {"\ud83d": {"role": "objective"}}})]:
            with self.subTest(path):
                self.assertEqual([(p.path, p.code) for p in validate(m)], [(path, "bad_unicode")])


class LuaEscapingTests(unittest.TestCase):
    """No text from a manifest is ever Lua code: every one is a quoted literal (core/scenario/luagen.lua)."""

    def test_literals(self):
        self.assertEqual(lua_string('a"b\\c\nd\re\tf'), '"a\\"b\\\\c\\nd\\re\\tf"')
        self.assertEqual(lua_string("]]--[["), '"]]--[["')
        self.assertEqual(lua_string("\x00\x1b\x7f"), '"\\000\\027\\127"')
        self.assertEqual(lua_string("Informações"), '"Informações"')
        self.assertEqual(lua_string("‮ "), '"\\226\\128\\174\\226\\128\\168"')  # bidi, line separator
        self.assertEqual(lua_value({"end": 1, "a b": True, "x": None, "n": [1, 2.5]}),
                         '{ ["end"] = 1, ["a b"] = true, n = { 1, 2.5 } }')
        self.assertEqual(lua_value(38.0), "38.0")
        for bad in (float("nan"), float("inf"), 2**64, -2**63, object(), {1: 2}):
            with self.subTest(bad), self.assertRaises(LuaError):
                lua_value(bad)

    @unittest.skipIf(CORE is None, "the shared core library is not built")
    def test_round_trip_through_the_core(self):
        """Each text comes back from Lua byte for byte, and no text runs."""
        texts = ["", HOSTILE, "a\nb\r\nc", "\x00x", "]==]", '"; os.exit(1) --', "\\0\\x41\\u{41}", "\\",
                 "‮evil", "emoji \U0001f600", "".join(chr(c) for c in range(1, 32)), "ã" * 50]
        for text in texts:
            with self.subTest(text=text):
                logs: list[str] = []
                script = (f"local s = {lua_string(text)}\nlocal h = {{}}\n"
                          "for i = 1, #s do h[#h + 1] = string.format('%02x', s:byte(i)) end\n"
                          "log('hex:' .. table.concat(h))\n")
                node = Node(CORE, 1, 1, ["red", "blue"], {}, script, "t", on_log=logs.append)
                try:
                    self.assertTrue(node.loaded, node.last_error)
                finally:
                    node.close()
                self.assertEqual([line for line in logs if "hex:" in line][-1].split("hex:", 1)[1],
                                 text.encode().hex())

    def test_generated_lua_quotes_every_text(self):
        m = manifest([{"id": "bridge", "name": HOSTILE, "type": "capture_and_hold", "target": 'al"pha]]',
                       "description": "line one\nline two ]] --[[", "assignee": {"team": 'r"ed'}}],
                     nodes={'al"pha]]': {"role": "objective"}}, teams=['r"ed', "blue"])
        lua = compile_scenario(m).field_lua
        self.assertIn(lua_string(HOSTILE), lua)
        self.assertIn(lua_string('al"pha]]'), lua)
        self.assertNotIn("line one", lua)  # descriptions are for people: mode.yaml only
        code = lua.split("local SCENARIO = ", 1)[1]
        self.assertNotIn("os.exit(1) --[[ \\'", code.replace(lua_string(HOSTILE), ""))

    def test_names_must_be_one_line(self):
        for o in ({"name": "a\nb"}, {"name": "‮evil"}):
            m = manifest([{"id": "x", "type": "capture_and_hold", "target": "a", **o}])
            self.assertEqual([(p.path, p.code) for p in errors(validate(m))], [("objectives[0].name", "bad_text")])


@unittest.skipIf(CORE is None, "the shared core library is not built")
class SimulatedTests(unittest.TestCase):
    """Each objective type compiled and played in the simulator with the objectives package."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.objectives = load_mode(OBJECTIVES_DIR)

    def play(self, m: dict[str, Any], spec: dict[str, Any], name: str = "t") -> None:
        folder = Path(self.tmp.name) / name
        compile_scenario(m).write(folder / "package")
        path = folder / f"{name}.yaml"
        path.write_text(yaml.safe_dump({"name": name, "scenario": str(folder / "package"), **spec},
                                       allow_unicode=True), encoding="utf-8")
        result = run_test(CORE, self.objectives, path)
        self.assertTrue(result.passed, result.message + "\n" + "\n".join(result.log))

    def test_capture_and_hold_for_a_duration(self):
        m = manifest([{"id": "hill", "name": "Hill", "type": "capture_and_hold", "target": "a",
                       "assignee": {"team": "red"}, "params": {"duration_s": 30}, "effect": {"points": 40}}])
        self.play(m, {"nodes": {"a": "objective"}, "steps": [
            {"expect": {"type": "scenario.objective.revealed", "team": "red", "data": {"objective": "hill"}}},
            {"expect_screen": {"node": "a", "template": "obj_capture", "data": {"label": "Hill", "only": "red"}}},
            {"hold": {"node": "a", "team": "red", "s": 3}},
            {"expect": {"type": "zone.captured", "team": "red", "at": 3}},
            {"wait": 20},
            {"input": {"node": "a", "type": "cmd.set_owner", "data": {"team": "none"}}},  # the GM frees it
            {"expect": {"type": "zone.neutralized", "node": "a"}},
            {"wait": 20},
            {"expect_no": "scenario.objective.completed"},
            {"hold": {"node": "a", "team": "red", "s": 3}},
            {"expect": {"type": "zone.captured", "team": "red", "at": 46}},
            {"wait": 29},
            {"expect_no": "scenario.objective.completed"},
            {"wait": 1},
            {"expect": {"type": "scenario.objective.completed", "team": "red", "at": 76,
                        "data": {"objective": "hill"}}},
            {"expect_score": {"team": "red", "points": 40}},
            {"expect_screen": {"node": "a", "template": "obj_status", "data": {"state": "done", "team": "red"}}},
        ]})

    def test_defend_completed_and_failed(self):
        m = manifest([{"id": "hq", "name": "HQ", "type": "defend", "target": "a", "assignee": {"team": "blue"},
                       "params": {"duration_s": 60}, "effect": {"points": 40}}])
        self.play(m, {"nodes": {"a": "objective"}, "steps": [
            {"expect_screen": {"node": "a", "template": "obj_capture", "data": {"team": "blue"}}},
            {"hold": {"node": "a", "team": "blue", "s": 5}},
            {"expect_no": "zone.captured"},
            {"wait": 54},
            {"expect_no": "scenario.objective.completed"},
            {"wait": 1},
            {"expect": {"type": "scenario.objective.completed", "team": "blue", "at": 60}},
            {"expect_score": {"team": "blue", "points": 40}},
        ]}, "held")
        self.play(m, {"nodes": {"a": "objective"}, "steps": [
            {"hold": {"node": "a", "team": "red", "s": 3}},
            {"expect": {"type": "zone.captured", "team": "red"}},
            {"expect": {"type": "scenario.objective.failed", "team": "blue",
                        "data": {"objective": "hq", "reason": "captured"}}},
            {"expect_screen": {"node": "a", "template": "obj_status", "data": {"state": "failed"}}},
            {"wait": 60},
            {"expect_no": "scenario.objective.completed"},
            {"expect_score": {"team": "blue", "points": 0}},
        ]}, "lost")

    def test_enter_code_for_the_last_team_to_press(self):
        m = manifest([{"id": "safe", "name": "Safe", "type": "enter_code", "target": "a",
                       "params": {"code": "0815"}, "effect": {"points": 5}}])
        self.play(m, {"nodes": {"a": "objective"}, "steps": [
            {"expect": {"type": "scenario.objective.revealed", "data": {"objective": "safe"}}},
            {"press": {"node": "a", "team": "blue"}},
            {"keys": {"node": "a", "keys": "0815#"}},
            {"expect": {"type": "code.used", "team": "blue"}},
            {"expect": {"type": "scenario.objective.completed", "team": "blue"}},
            {"expect_score": {"team": "blue", "points": 5}},
        ]})

    def test_escort_with_position_fixes(self):
        vip = {"vip": {"player": True, "role": "vip"}, "a": {"role": "objective"}}
        circle = {"lat": 38.7223, "lon": -9.1393, "radius_m": 15}
        m = manifest([{"id": "rescue", "name": "Rescue", "type": "escort", "target": "vip",
                       "assignee": {"team": "red"}, "params": {"destination": circle},
                       "effect": {"points": 10, "win": True}}], nodes=vip)
        fix = {"player": "v1", "team": "red", "role": "vip", "lat": 38.7223, "lon": -9.1393, "acc": 5}
        self.play(m, {"nodes": {"a": "objective"}, "steps": [
            {"position": {**fix, "lat": 38.73}},  # 860 m north
            {"position": {**fix, "acc": 50}},  # less precise than the zone
            {"position": {**fix, "team": "blue"}},  # the other team's VIP
            {"position": {**fix, "role": "player"}},  # not the VIP
            {"expect_no": "scenario.objective.completed"},
            {"wait": 1},
            {"position": fix},
            {"expect": {"type": "scenario.objective.completed", "team": "red", "at": 1}},
            {"expect": {"type": "game.end", "data": {"winner": "red"}}},
            {"expect_score": {"team": "red", "points": 10}},
        ]}, "circle")
        square = [[38.7220, -9.1400], [38.7220, -9.1390], [38.7230, -9.1390], [38.7230, -9.1400]]
        m["objectives"][0]["params"] = {"destination": {"points": square}, "max_acc_m": 20}
        self.play(m, {"nodes": {"a": "objective"}, "steps": [
            {"position": {**fix, "lon": -9.1380}},
            {"position": {**fix, "acc": 25}},
            {"expect_no": "scenario.objective.completed"},
            {"position": {**fix, "acc": 20}},
            {"expect": {"type": "scenario.objective.completed", "team": "red"}},
        ]}, "polygon")

    def test_survive_against_respawn_lives(self):
        m = manifest([{"id": "alive", "name": "Stay alive", "type": "survive", "assignee": {"team": "red"},
                       "params": {"minimum_lives": 18}, "time_window": {"end_min": 5},
                       "effect": {"points": 25}}], nodes={})
        press = {"press": {"node": "spawn", "team": "red"}}
        self.play(m, {"main": "respawn", "nodes": {"spawn": "respawn"}, "steps": [
            press, {"wait": 3}, press,
            {"expect": {"type": "player.respawn", "team": "red", "data": {"lives_left": 18}}},
            {"wait": 297},
            {"expect": {"type": "scenario.objective.completed", "team": "red", "at": 300}},
            {"expect_score": {"team": "red", "points": 25}},
        ]}, "kept")
        self.play(m, {"main": "respawn", "nodes": {"spawn": "respawn"}, "steps": [
            press, {"wait": 3}, press, {"wait": 3}, press,
            {"expect": {"type": "player.respawn", "team": "red", "data": {"lives_left": 17}}},
            {"expect": {"type": "scenario.objective.failed", "team": "red",
                        "data": {"objective": "alive", "reason": "lives"}}},
            {"wait": 300},
            {"expect_no": "scenario.objective.completed"},
        ]}, "lost")
        m["objectives"][0]["params"]["minimum_lives"] = 0  # 0 lives left is still alive; out is not
        self.play(m, {"main": "respawn", "params": {"lives": 1}, "nodes": {"spawn": "respawn"}, "steps": [
            press,
            {"expect": {"type": "player.respawn", "team": "red", "data": {"lives_left": 0}}},
            {"expect_no": "scenario.objective.failed"},
            {"wait": 3}, press,
            {"expect": {"type": "team.eliminated", "team": "red"}},
            {"expect": {"type": "scenario.objective.failed", "team": "red", "data": {"reason": "lives"}}},
        ]}, "eliminated")

    def test_time_windows(self):
        m = manifest([{"id": "late", "name": "Late", "type": "capture_and_hold", "target": "a",
                       "assignee": {"team": "red"}, "time_window": {"start_min": 1, "end_min": 3}},
                      {"id": "early", "name": "Early", "type": "capture_and_hold", "target": "b",
                       "time_window": {"end_min": 1}, "effect": {"points": 3}}])
        self.play(m, {"nodes": {"a": "objective", "b": "objective"}, "steps": [
            {"expect": {"type": "scenario.objective.revealed", "data": {"objective": "late"}}},
            {"expect_screen": {"node": "a", "template": "obj_status", "data": {"state": "off"}}},
            {"hold": {"node": "a", "team": "red", "s": 3}},
            {"expect_no": {"type": "zone.captured", "node": "a"}},
            {"hold": {"node": "b", "team": "blue", "s": 3}},
            {"expect": {"type": "scenario.objective.completed", "team": "blue", "data": {"objective": "early"}}},
            {"wait": 54},
            {"expect_screen": {"node": "a", "template": "obj_capture"}},
            {"wait": 120},
            {"expect": {"type": "scenario.objective.failed", "team": "red", "at": 180,
                        "data": {"objective": "late", "reason": "time"}}},
            {"expect_no": {"type": "scenario.objective.failed", "data": {"objective": "early"}}},
            {"expect_screen": {"node": "a", "template": "obj_status", "data": {"state": "failed"}}},
        ]})

    def test_the_dependency_chain_of_the_multi_objective_example(self):
        m = load((MANIFESTS / "multi_objective.yaml").read_text(encoding="utf-8"))
        fix = {"player": "v1", "team": "red", "role": "vip", "lat": 38.7223, "lon": -9.1393, "acc": 4}
        self.play(m, {"nodes": {"box-a": "objective", "box-b": "objective", "box-c": "bomb_site"}, "steps": [
            {"expect": {"type": "scenario.started", "data": {"scenario": "org.club.operation-foxhound"}}},
            {"expect": {"type": "scenario.objective.revealed", "team": "red",
                        "data": {"objective": "intel", "squad": "1"}}},
            {"expect": {"type": "scenario.objective.revealed", "team": "blue", "data": {"objective": "defend_hq"}}},
            {"expect": {"type": "scenario.objective.revealed", "team": "red",
                        "data": {"objective": "sabotage", "squad": "1"}}},
            {"expect_no": {"type": "scenario.objective.revealed", "data": {"objective": "rescue"}}},
            {"expect_screen": {"node": "box-c", "template": "obj_status", "data": {"state": "off"}}},
            {"expect_screen": {"node": "box-b", "template": "obj_capture", "data": {"team": "blue"}}},
            {"expect_screen": {"node": "box-a", "template": "obj_tags",
                               "data": {"label": "Informações", "any": True, "count": 3}}},
            {"position": fix},  # not yet: the rescue is hidden and waits for the intel
            {"expect_no": {"type": "scenario.objective.completed", "data": {"objective": "rescue"}}},
            {"scan": {"node": "box-a", "uid": "04000001"}},
            {"scan": {"node": "box-a", "uid": "04000002"}},
            {"scan": {"node": "box-a", "uid": "04000002"}},
            {"expect_no": "scenario.objective.completed"},
            {"scan": {"node": "box-a", "uid": "04000003"}},
            {"expect": {"type": "scenario.objective.completed", "team": "red",
                        "data": {"objective": "intel", "squad": "1"}}},
            {"expect": {"type": "scenario.objective.revealed", "team": "red",
                        "data": {"objective": "rescue", "squad": "2"}}},
            {"expect_score": {"team": "red", "points": 50}},
            {"expect_screen": {"node": "box-c", "template": "obj_bomb",
                               "data": {"label": "Sabotar o rádio", "attackers": "red"}}},
            {"wait": 1},
            {"position": fix},
            {"expect": {"type": "scenario.objective.completed", "team": "red",
                        "data": {"objective": "rescue", "squad": "2"}}},
            {"expect": {"type": "game.end", "data": {"winner": "red"}}},
        ]})

    def test_a_failure_blocks_what_depends_on_it(self):
        m = manifest([{"id": "site", "name": "Site", "type": "destroy", "target": "site",
                       "assignee": {"team": "red"}, "visibility": "public"},
                      {"id": "after", "name": "After", "type": "capture_and_hold", "target": "a",
                       "depends_on": ["site"]},
                      {"id": "secret", "name": "Secret", "type": "capture_and_hold", "target": "b",
                       "depends_on": ["after"], "visibility": "hidden"}])
        self.play(m, {"nodes": {"a": "objective", "b": "objective", "site": "bomb_site"}, "steps": [
            {"hold": {"node": "site", "team": "red", "s": 3}},
            {"expect": {"type": "bomb.armed", "team": "red"}},
            {"hold": {"node": "site", "team": "blue", "s": 3}},
            {"expect": {"type": "bomb.defused", "team": "blue"}},
            {"expect": {"type": "scenario.objective.failed", "team": "red",
                        "data": {"objective": "site", "reason": "defused"}}},
            {"expect": {"type": "scenario.objective.failed", "data": {"objective": "after", "reason": "blocked"}}},
            {"expect_no": {"type": "scenario.objective.failed", "data": {"objective": "secret"}}},
            {"expect_screen": {"node": "a", "template": "obj_status", "data": {"state": "failed"}}},
            {"expect_screen": {"node": "b", "template": "obj_status", "data": {"state": "failed"}}},
        ]})

    def test_a_team_the_game_lacks_is_off(self):
        m = manifest([{"id": "green_hill", "name": "Green", "type": "capture_and_hold", "target": "a",
                       "assignee": {"team": "green"}},
                      {"id": "red_hill", "name": "Red", "type": "capture_and_hold", "target": "b",
                       "assignee": {"team": "red"}}], teams=["red", "blue", "green"])
        self.play(m, {"nodes": {"a": "objective", "b": "objective"}, "steps": [
            {"expect_no": {"type": "scenario.objective.revealed", "data": {"objective": "green_hill"}}},
            {"expect_screen": {"node": "a", "template": "obj_status", "data": {"state": "off"}}},
            {"hold": {"node": "b", "team": "red", "s": 3}},
            {"expect": {"type": "scenario.objective.completed", "team": "red"}},
            {"expect_no": "script.error"},
        ]})

    def test_hostile_names_reach_the_box_unchanged(self):
        m = manifest([{"id": "bridge", "name": HOSTILE, "type": "capture_and_hold", "target": 'al"pha]]',
                       "assignee": {"team": 'r"ed'}, "effect": {"points": 7}}],
                     nodes={'al"pha]]': {"role": "objective"}}, teams=['r"ed', "blue"])
        self.play(m, {"teams": ['r"ed', "blue"], "nodes": {'al"pha]]': "objective"}, "steps": [
            {"expect_screen": {"node": 'al"pha]]', "template": "obj_capture", "data": {"label": HOSTILE}}},
            {"hold": {"node": 'al"pha]]', "team": 'r"ed', "s": 3}},
            {"expect": {"type": "scenario.objective.completed", "team": 'r"ed'}},
            {"expect_score": {"team": 'r"ed', "points": 7}},
            {"expect_no": "script.error"},
        ]})

    def test_the_screens_in_english(self):
        m = manifest([{"id": "bridge", "name": "Bridge", "i18n": {"pt": {"name": "Ponte"}},
                       "type": "capture_and_hold", "target": "a"}], lang="en")
        self.play(m, {"nodes": {"a": "objective"}, "steps": [
            {"expect_screen": {"node": "a", "template": "obj_capture", "data": {"label": "Bridge", "lang": "en"}}},
        ]})


@unittest.skipIf(CORE is None, "the shared core library is not built")
class FoxhoundTests(unittest.TestCase):
    """modes/objectives/tests/fixtures/foxhound was written by hand before the compiler; the same
    scenario as a manifest (tests/scenarios/foxhound.yaml) compiles to a package that passes every
    one of the objectives package's tests that play the hand-written one."""

    def test_the_objectives_tests_pass_with_the_compiled_package(self):
        package = compile_scenario(load((MANIFESTS / "foxhound.yaml").read_text(encoding="utf-8")))
        check_package(CORE, package)
        objectives = load_mode(OBJECTIVES_DIR)
        played = 0
        with tempfile.TemporaryDirectory() as tmp:
            package.write(Path(tmp) / "foxhound")
            for test in objectives.tests:
                spec = yaml.safe_load(test.read_text(encoding="utf-8"))
                if spec.get("scenario") != "fixtures/foxhound":
                    continue
                spec["scenario"] = str(Path(tmp) / "foxhound")
                copy_path = Path(tmp) / test.name
                copy_path.write_text(yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
                with self.subTest(test.name):
                    result = run_test(CORE, objectives, copy_path)
                    self.assertTrue(result.passed, result.message + "\n" + "\n".join(result.log))
                played += 1
        self.assertGreaterEqual(played, 6)

    def test_the_package_installs_on_the_controller(self):
        package = compile_scenario(load((MANIFESTS / "foxhound.yaml").read_text(encoding="utf-8")))
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(str(Path(tmp) / "c.db"))
            self.addCleanup(store.close)
            registry = ModeRegistry(store, [str(OBJECTIVES_DIR)], CORE)
            pkg = registry.install(package.files)
            self.assertEqual((pkg.id, pkg.kind, pkg.mode.params["vault_points"]["default"]),
                             ("org.club.foxhound", "scenario", 100))
            game = registry.get("org.club.foxhound+org.atalaia.objectives")
            self.assertEqual(game.mode.node_mode_id("objective"), "org.atalaia.objectives")
            meta = yaml.safe_load(package.mode_yaml)["scenario"]
            self.assertEqual([o["id"] for o in meta["objectives"]], ["bridge", "intel", "vault", "site_a"])
            self.assertNotIn("4711", package.mode_yaml)  # the code is only in field.lua

    def test_a_lua_error_is_caught_by_the_core_check(self):
        package = compile_scenario(load((MANIFESTS / "foxhound.yaml").read_text(encoding="utf-8")))
        package.files["field.lua"] += "\nlocal = 1\n"
        with self.assertRaisesRegex(ModeError, "field.lua does not load"):
            check_package(CORE, package)

    def test_every_example_manifest_compiles_and_loads(self):
        for path in sorted(MANIFESTS.glob("*.yaml")):
            with self.subTest(path.name):
                check_package(CORE, compile_scenario(load(path.read_text(encoding="utf-8"))))


class SharedLibraryTests(unittest.TestCase):
    def test_imports_without_the_web_stack(self):
        """The site server imports the compiler (P4-1, P4R16): no FastAPI, pydantic or the like."""
        script = (
            "import importlib.abc, sys\n"
            "class Block(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name.split('.')[0] in ('fastapi', 'pydantic', 'starlette', 'uvicorn', 'httpx', 'paho'):\n"
            "            raise ImportError(name)\n"
            "sys.meta_path.insert(0, Block())\n"
            "import atalaia_controller.scenarios, atalaia_controller.scenarios.cli\n"
            "from atalaia_controller.scenarios import compile_scenario, load\n"
            f"compile_scenario(load(open({str(MANIFESTS / 'foxhound.yaml')!r}, encoding='utf-8').read()))\n")
        r = subprocess.run([sys.executable, "-c", script], cwd=HERE.parent, capture_output=True, text=True,
                           timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)


class DataTreeTests(unittest.TestCase):
    """What Python hands the core (decision PE24-109): the manifest's data tree, typed as the 'loads'
    vectors write it, with a YAML alias as {"alias": n}; and what the core makes of values only PyYAML
    builds."""

    def test_the_tree_is_the_loads_vectors_typed_form(self):
        golden = json.loads((REPO / "protocol" / "vectors" / "scenario_compile.json").read_text(encoding="utf-8"))

        def expand(v: Any, shared: list[Any]) -> Any:
            # {"alias": n} as the value it names, as the vectors write it.
            (kind, body), = v.items()
            if kind == "alias":
                return shared[body]
            if kind == "list":
                out: dict[str, Any] = {"list": []}
                shared.append(out)
                out["list"] = [expand(x, shared) for x in body]
                return out
            if kind == "map":
                out = {"map": []}
                shared.append(out)
                out["map"] = [[expand(k, shared), expand(x, shared)] for k, x in body]
                return out
            return v

        cases = [c for c in golden["loads"] if not c.get("error")]
        self.assertGreater(len(cases), 15)
        for case in cases:
            with self.subTest(case["text"]):
                tree = json.loads(compiler.encode(load(case["text"])).decode("utf-8"))
                self.assertEqual(expand(tree, []), case["data"])

    def test_a_map_two_objectives_share_is_written_once(self):
        """As PyYAML writes one object it meets twice: &id001, then *id001 (mode.yaml)."""
        points = {"param": "points"}
        m = manifest([{"id": "one", "name": "One", "type": "capture_and_hold", "target": "a",
                       "effect": {"points": points}},
                      {"id": "two", "name": "Two", "type": "capture_and_hold", "target": "b",
                       "effect": {"points": points}}],
                     params={"points": {"type": "int", "default": 3}})
        tree = json.loads(compiler.encode(m))
        self.assertIn('{"alias":', json.dumps(tree, separators=(",", ":")))
        written = compile_scenario(m).mode_yaml
        self.assertIn("points: &id001\n", written)
        self.assertIn("points: *id001\n", written)
        self.assertEqual(yaml.safe_load(written)["scenario"]["objectives"][1]["points"], {"param": "points"})

    def test_values_only_pyyaml_builds_are_problems_not_crashes(self):
        base = load((MANIFESTS / "foxhound.yaml").read_text(encoding="utf-8"))
        loop: list[Any] = []
        loop.append(loop)
        for key, value, path, code in [
            ("teams", loop, "teams", "bad_teams"),
            ("description", {"a": loop}, "description", "bad_text"),
            ("version", datetime.date(2026, 10, 23), "version", "bad_text"),
            ("version", {1, 2}, "version", "bad_text"),
            ("version", b"bytes", "version", "bad_text"),
            # A language JSON cannot write: Python's json.dumps raised in the size check (a 500).
            ("lang", [datetime.datetime(2026, 1, 2, 3, 4, 5)], "lang", "bad_lang"),
        ]:
            with self.subTest(key=key, value=repr(value)):
                m = copy.copy(base)
                m[key] = value
                self.assertIn((path, code), [(p.path, p.code) for p in errors(validate(m))])
        m = copy.deepcopy(base)
        m["objectives"][0]["target"] = datetime.datetime(2026, 10, 23, 10, 0, tzinfo=datetime.timezone(
            datetime.timedelta(hours=-5)))
        message = [p.message for p in validate(m) if p.path == "objectives[0].target"][0]
        self.assertEqual(message, repr(m["objectives"][0]["target"]) + " is not in the nodes map")

    def test_a_manifest_nested_too_deep_is_refused_in_words(self):
        deep: Any = "x"
        for _ in range(150):
            deep = [deep]
        m = manifest([{"id": "x", "name": "X", "type": "capture_and_hold", "target": "a"}], extra=deep)
        self.assertEqual([(p.path, p.code, p.message) for p in validate(m)],
                         [("", "bad_manifest", "the manifest is nested more than 100 levels deep")])

    def test_a_core_without_the_compiler(self):
        stub = os.environ.get("ATALAIA_CORE_STUB_LIB")
        if not stub or not Path(stub).exists():
            self.skipTest("the FFI stub is not built")
        import ctypes  # noqa: PLC0415

        from atalaia_sim.core import Core  # noqa: PLC0415

        core = Core.__new__(Core)  # the stub has node.h only: no screen templates, tags or scenarios
        core.lib = ctypes.CDLL(stub)
        with self.assertRaises(CoreUnavailable):
            validate({}, core=core)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def bad_manifest(self, tmp: str) -> Path:
        m = copy.deepcopy(load((MANIFESTS / "foxhound.yaml").read_text(encoding="utf-8")))
        m["objectives"][2]["depends_on"] = ["nowhere"]
        path = Path(tmp) / "bad.yaml"
        path.write_text(yaml.safe_dump(m, allow_unicode=True), encoding="utf-8")
        return path

    def test_validate(self):
        code, out, _ = self.run_cli("validate", str(MANIFESTS / "foxhound.yaml"))
        self.assertEqual((code, "4 objectives, no errors" in out), (0, True))
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = self.run_cli("validate", str(self.bad_manifest(tmp)))
            self.assertEqual(code, 1)
            self.assertIn("objectives[2].depends_on[0]: error: 'nowhere' is not an objective id (unknown_reference)",
                          err)
            code, out, _ = self.run_cli("validate", "--json", str(self.bad_manifest(tmp)))
            self.assertEqual((code, json.loads(out)["problems"][0]["code"]), (1, "unknown_reference"))
            (Path(tmp) / "list.yaml").write_text("- 1\n", encoding="utf-8")
            self.assertEqual(self.run_cli("validate", str(Path(tmp) / "list.yaml"))[0], 2)
            self.assertEqual(self.run_cli("validate", str(Path(tmp) / "missing.yaml"))[0], 2)

    @unittest.skipIf(CORE is None, "the shared core library is not built")
    def test_check_and_compile(self):
        code, out, _ = self.run_cli("check", str(MANIFESTS / "multi_objective.yaml"))
        self.assertEqual((code, "the field.lua loads in the core" in out), (0, True))
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self.run_cli("compile", str(MANIFESTS / "foxhound.yaml"), "-o", str(Path(tmp) / "pkg"))
            self.assertEqual(code, 0, out)
            self.assertEqual(sorted(p.name for p in (Path(tmp) / "pkg").iterdir()), ["field.lua", "mode.yaml"])
            self.assertEqual(load_mode(Path(tmp) / "pkg").kind, "scenario")
            code, out, _ = self.run_cli("compile", str(MANIFESTS / "foxhound.yaml"))
            self.assertTrue(out.startswith("-- SPDX-" "License-Identifier: GPL-3.0-or-later"))
            code, out, _ = self.run_cli("compile", "--json", str(MANIFESTS / "foxhound.yaml"))
            self.assertEqual(sorted(json.loads(out)["files"]), ["field.lua", "mode.yaml"])
            self.assertEqual(self.run_cli("compile", str(self.bad_manifest(tmp)), "-o", str(Path(tmp) / "x"))[0], 1)
            self.assertFalse((Path(tmp) / "x").exists())

    def test_through_the_controllers_entry_point(self):
        env = dict(os.environ)
        r = subprocess.run([sys.executable, "-m", "atalaia_controller", "scenario", "validate",
                            str(MANIFESTS / "foxhound.yaml")], cwd=HERE.parent, capture_output=True, text=True,
                           env=env, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("org.club.foxhound: 4 objectives, no errors", r.stdout)


if __name__ == "__main__":
    unittest.main()
