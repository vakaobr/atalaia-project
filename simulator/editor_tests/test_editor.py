# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Browser tests of the mode editor (phase 5 plan phase A; AC-1 to AC-3).

The editor's page, served by the simulator's real web server, runs in headless
Chromium (Playwright). The Lua generator runs where it runs for a user, in the
page, through window.atalaiaEditor.generate(project), so the same code is
tested: small projects give exact Lua (the generator's unit tests); the two
example projects give node.lua, field.lua and mode.yaml that pass every YAML
test of the modes they copy, in the simulator, with the mode's own tests
(the round trip, AC-1), and keep the style of the hand-written modes (AC-2);
the page itself works in English and Portuguese, offline (AC-3).

Run by simulator/editor_tests/run.sh (python tools/docker_editor.py, CI's
editor job). With ATALAIA_REQUIRE_BROWSER=1 a missing Playwright or core is an
error, never a skip.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

import yaml
from atalaia_sim.core import Core, find_library
from atalaia_sim.live import LiveGame
from atalaia_sim.mode import load_mode
from atalaia_sim.sim import Simulation
from atalaia_sim.testing import run_test
from atalaia_sim.web import make_server

REPO = Path(__file__).resolve().parents[2]
EDITOR = REPO / "simulator" / "atalaia_sim" / "editor"
REQUIRE = os.environ.get("ATALAIA_REQUIRE_BROWSER") == "1"

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover - the test image has it
    if REQUIRE:
        raise
    sync_playwright = None


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        if REQUIRE:
            raise
        return None


CORE = _core() if sync_playwright else None

# ---- small projects, as the editor saves them ----

_ids = itertools.count(1)


def B(type_, fields=None, inputs=None, extra=None, **pos):
    block = {"type": type_, "id": f"t{next(_ids)}", **pos}
    if extra is not None:
        block["extraState"] = extra
    if fields:
        block["fields"] = fields
    if inputs:
        block["inputs"] = {k: {"block": v} for k, v in inputs.items() if v is not None}
    return block


def seq(*blocks):
    for a, b in zip(blocks, blocks[1:]):
        a["next"] = {"block": b}
    return blocks[0]


def num(n):
    return B("math_number", {"NUM": n})


def text(s):
    return B("text", {"TEXT": s})


def ev(key):
    return B("atalaia_event_value", {"KEY": key})


def pair(key, value):
    return B("atalaia_pair", {"KEY": key}, {"VALUE": value})


def on(event, body, kind="node", **pos):
    return B(f"atalaia_on_{kind}", {"EVENT": event}, {"DO": body}, **pos)


def proc(name, body, **pos):
    return B("procedures_defnoreturn", {"NAME": name}, {"STACK": body}, **pos)


def call(name):
    return B("procedures_callnoreturn", extra={"name": name})


def project(node=(), field=(), variables=(), field_variables=(), **mode):
    def ws(blocks, names):
        state = {"blocks": {"languageVersion": 0, "blocks": list(blocks)}}
        if names:
            state["variables"] = [{"name": n, "id": f"v-{n}"} for n in names]
        return state
    info = {"id": "org.test.unit", "name": "Unit", "description": "", "author": "Test", "year": "2026"}
    info.update(mode)
    return {"format": "atalaia-mode-editor", "version": 1, "mode": info,
            "node": ws(node, variables), "field": ws(field, field_variables)}


def body(lua: str) -> str:
    """The generated script without its comment header."""
    lines = lua.splitlines()
    while lines and lines[0].startswith("--"):
        lines.pop(0)
    return "\n".join(lines).strip() + "\n"


@unittest.skipIf(sync_playwright is None or CORE is None, "needs Playwright and the shared core library")
class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        mode = load_mode(REPO / "modes" / "domination")
        params = mode.resolve_params({}, ["red", "blue"])
        cls.game = LiveGame(lambda: Simulation(CORE, mode, {"zone": "zone"}, ["red", "blue"], params))
        cls.server = make_server(cls.game, "127.0.0.1", 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = cls.server.url + "editor/"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.game.close()

    def open(self, lang="en", context_options=None):
        """The editor in a fresh browser context; fails the test on any page error or a request
        that leaves the simulator (the editor works offline)."""
        context = self.browser.new_context(accept_downloads=True, **(context_options or {}))
        self.addCleanup(context.close)
        page = context.new_page()
        self.errors, self.outside = [], []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and self.errors.append(m.text))
        origin = self.server.url.rstrip("/")
        page.on("request", lambda r: r.url.startswith(origin) or r.url.startswith(("blob:", "data:"))
                or self.outside.append(r.url))
        page.on("dialog", lambda d: d.accept())
        page.goto(self.url + (f"?lang={lang}" if lang else ""))
        expect(page.locator("body")).to_have_attribute("data-ready", "true")
        return page

    def tearDown(self):
        self.assertEqual(getattr(self, "errors", []), [])
        self.assertEqual(getattr(self, "outside", []), [])

    def generate(self, page, proj):
        return page.evaluate("p => window.atalaiaEditor.generate(p)", proj)

    # ---- the generator (unit tests through the page) ----

    def test_an_empty_project_has_no_scripts(self):
        page = self.open()
        out = self.generate(page, project())
        self.assertEqual((out["node_lua"], out["field_lua"]), ("", ""))
        manifest = yaml.safe_load(out["mode_yaml"])
        self.assertEqual(manifest["id"], "org.test.unit")
        self.assertEqual(manifest["roles"], {"zone": {}})
        self.assertEqual(out["problems"], [])

    def test_events_timers_and_priority(self):
        page = self.open()
        handler = on("keypad.key", seq(
            B("atalaia_emit", {"TYPE": "x.club.ping", "PRIO": "critical"}),
            B("atalaia_after_as", {"TIMER": {"id": "v-timer"}}, {"SECONDS": num(5), "DO": B(
                "atalaia_emit", {"TYPE": "x.club.key", "PRIO": "default"}, {"DATA": pair("key", ev("key"))})}),
            B("atalaia_cancel", {"TIMER": {"id": "v-timer"}}),
        ))
        out = self.generate(page, project(node=[handler], variables=["timer"]))
        self.assertEqual(body(out["node_lua"]), (
            'local timer\n'
            '\n'
            'on("keypad.key", function(e)\n'
            '  emit("x.club.ping", {}, { prio = "critical" })\n'
            '  timer = after(5, function()\n'
            '    emit("x.club.key", { key = e.key })\n'
            '  end)\n'
            '  cancel(timer)\n'
            'end)\n'))
        self.assertEqual(yaml.safe_load(out["mode_yaml"])["roles"], {"zone": {"requires": ["keypad"]}})
        self.assertEqual(out["problems"], [])

    def test_a_function_comes_before_its_callers(self):
        page = self.open()
        first = proc("announce", call("chime"), y=10)
        second = proc("chime", B("atalaia_sound", {"CLIP": "chime"}), y=200)
        out = self.generate(page, project(node=[first, second, on("game.start", call("announce"), y=400)]))
        self.assertEqual(body(out["node_lua"]), (
            'local function chime()\n'
            '  audio.play("chime")\n'
            'end\n'
            '\n'
            'local function announce()\n'
            '  chime()\n'
            'end\n'
            '\n'
            'on("game.start", announce)\n'))
        self.assertEqual(yaml.safe_load(out["mode_yaml"])["roles"], {"zone": {"optional": ["audio"]}})

    def test_functions_that_call_each_other_are_declared_first(self):
        page = self.open()
        ping = proc("ping", call("pong"), y=10)
        pong = proc("pong", call("ping"), y=200)
        lua = body(self.generate(page, project(node=[ping, pong]))["node_lua"])
        # pong is defined first (ping calls it); ping, called before its definition, is declared.
        self.assertEqual(lua, (
            'local ping\n'
            '\n'
            'local function pong()\n'
            '  ping()\n'
            'end\n'
            '\n'
            'function ping()\n'
            '  pong()\n'
            'end\n'))

    def test_event_values_only_inside_when_blocks(self):
        page = self.open()
        inner = on("team_input.press", B("atalaia_every", inputs={"SECONDS": num(2), "DO": B(
            "atalaia_log", inputs={"TEXT": ev("team")})}))
        out = self.generate(page, project(node=[inner]))
        self.assertIn('on("team_input.press", function(e)\n  every(2, function()\n    log(e.team)', out["node_lua"])
        self.assertEqual(out["problems"], [])
        outside = proc("lost", B("atalaia_log", inputs={"TEXT": ev("team")}))
        out = self.generate(page, project(node=[outside]))
        self.assertEqual([p["key"] for p in out["problems"]], ["problem_event_outside"])

    def test_field_blocks(self):
        page = self.open()
        handler = on("zone.captured", seq(
            B("atalaia_field_send", {"CMD": "set_owner"}, {"NODE": ev("node"), "DATA": pair("team", text("red"))}),
            B("atalaia_score_add", {"REASON": ""}, {"POINTS": num(2), "TEAM": B(
                "atalaia_field_owner", inputs={"NODE": ev("node")})}),
            B("atalaia_log", inputs={"TEXT": B("atalaia_field_score", inputs={"TEAM": text("blue")})}),
        ), kind="field")
        out = self.generate(page, project(field=[handler]))
        self.assertEqual(out["node_lua"], "")
        self.assertEqual(body(out["field_lua"]), (
            'on("zone.captured", function(e)\n'
            '  field.send(e.node, "set_owner", { team = "red" })\n'
            '  score.add(field.owner(e.node), 2)\n'
            '  log(field.score()["blue"])\n'
            'end)\n'))

    def test_text_is_quoted_for_lua(self):
        page = self.open()
        out = self.generate(page, project(node=[on("game.start", B("atalaia_log", inputs={
            "TEXT": text('say "hi" \\ bye\n')}))]))
        self.assertIn('log("say \\"hi\\" \\\\ bye\\n")', out["node_lua"])

    def test_problems_with_settings_and_memory(self):
        page = self.open()
        node = [
            B("atalaia_param_declare", {"NAME": "fuse_s", "TYPE": "int", "DEFAULT": "900", "MIN": "1", "MAX": "600",
                                        "LABEL": "Fuse", "LABEL_PT": ""}, x=500, y=0),
            on("game.start", seq(
                B("atalaia_state_set", {"KEY": "armed"}, {"VALUE": B("atalaia_param", {"NAME": "delay_s"})}),
                B("atalaia_return"),
            )),
        ]
        out = self.generate(page, project(node=node))
        self.assertEqual(sorted(p["key"] for p in out["problems"]), [
            "problem_param_default", "problem_param_undeclared", "problem_state_undeclared"])
        self.assertIn("  s.armed = params.delay_s\n  return\nend)\n", out["node_lua"])
        self.assertTrue(body(out["node_lua"]).startswith("local s = state.node {}\n"))
        bad = self.generate(page, project(id="Not An Id", name=""))
        self.assertEqual(sorted(p["key"] for p in bad["problems"]), ["problem_bad_id", "problem_no_name"])

    def test_generated_scripts_load_in_the_core(self):
        """Every small project above, run for a few seconds in the simulator: no script error."""
        page = self.open()
        cases = [
            project(node=[on("game.start", B("atalaia_log", inputs={"TEXT": B("atalaia_rand", inputs={
                "FROM": num(1), "TO": num(6)})}))]),
            project(node=[B("atalaia_every", inputs={"SECONDS": num(1), "DO": B(
                "atalaia_score_add", {"REASON": "tick"}, {"POINTS": num(1), "TEAM": text("red")})})]),
            project(field=[B("atalaia_every", inputs={"SECONDS": num(1), "DO": B(
                "atalaia_log", inputs={"TEXT": B("lists_length", inputs={"VALUE": B(
                    "atalaia_field_ids", {"ROLE": "zone"})})})})]),
        ]
        for i, proj in enumerate(cases):
            out = self.generate(page, proj)
            self.assertEqual(out["problems"], [])
            with self.subTest(case=i), tempfile.TemporaryDirectory() as tmp:
                folder = Path(tmp) / "unit"
                (folder / "tests").mkdir(parents=True)
                self.write_mode(folder, out)
                (folder / "tests" / "runs.yaml").write_text(
                    "name: runs\nsteps:\n  - wait: 3\n  - expect_no: script.error\n  - expect_no: script.halted\n")
                [test] = load_mode(folder).tests
                result = run_test(CORE, load_mode(folder), test)
                self.assertTrue(result.passed, f"{result.message}\n{out['node_lua']}{out['field_lua']}")

    # ---- the examples: blocks to a mode that passes the hand-written mode's tests (AC-1, AC-2) ----

    @staticmethod
    def write_mode(folder: Path, out: dict) -> None:
        (folder / "mode.yaml").write_text(out["mode_yaml"], encoding="utf-8")
        (folder / "node.lua").write_text(out["node_lua"], encoding="utf-8")
        if out["field_lua"]:
            (folder / "field.lua").write_text(out["field_lua"], encoding="utf-8")

    def round_trip(self, name: str, has_field: bool):
        page = self.open()
        proj = json.loads((EDITOR / "examples" / f"{name}.json").read_text(encoding="utf-8"))
        out = self.generate(page, proj)
        self.assertEqual(out["problems"], [])
        self.assertEqual(bool(out["field_lua"]), has_field)
        original = REPO / "modes" / name
        # The manifest says what the hand-written one says (kind: mode is the default).
        made, hand = yaml.safe_load(out["mode_yaml"]), yaml.safe_load((original / "mode.yaml").read_text())
        made.pop("kind")
        hand.pop("kind", None)
        self.assertEqual(made, hand)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / name
            shutil.copytree(original / "tests", folder / "tests")
            if (original / "assets").is_dir():
                shutil.copytree(original / "assets", folder / "assets")
            self.write_mode(folder, out)
            mode = load_mode(folder)
            self.assertEqual(len(mode.tests), len(load_mode(original).tests))
            for test in mode.tests:
                result = run_test(CORE, mode, test)
                with self.subTest(test=test.name):
                    self.assertTrue(result.passed, f"{result.name}: {result.message}\n" + "\n".join(result.log))
        for script in filter(None, (out["node_lua"], out["field_lua"])):
            self.assertReadable(script)
        return out

    def assertReadable(self, lua: str):
        """ADR-P5-1's style: the licence header, 2-space indents, no tabs, no Blockly boilerplate,
        the memory first, named local functions, a blank line between top-level parts."""
        # REUSE-IgnoreStart
        self.assertTrue(lua.startswith("-- SPDX-FileCopyrightText: 2026 The Atalaia contributors\n"
                                       "-- SPDX-License-Identifier: GPL-3.0-or-later\n"), lua)
        # REUSE-IgnoreEnd
        self.assertNotIn("\t", lua)
        self.assertNotIn("Describe this function", lua)
        self.assertNotRegex(lua, r"(?m)^\s*function [a-z_]+\(")  # only local functions
        code = [line for line in lua.splitlines() if not line.lstrip().startswith("--")]
        self.assertFalse([line for line in code if "'" in line], "strings in double quotes")
        for line in lua.splitlines():
            indent = len(line) - len(line.lstrip(" "))
            self.assertEqual(indent % 2, 0, line)
            self.assertEqual(line, line.rstrip(), "trailing space")
        self.assertRegex(body(lua), r"^local f?s = state\.(node|field) \{")
        self.assertNotIn("\n\n\n", lua)
        self.assertRegex(lua, r"\nend\)?\n\n(on|every|local)")

    def test_domination_round_trip(self):
        out = self.round_trip("domination", has_field=False)
        self.assertIn('on("game.start", show)\n', out["node_lua"])
        self.assertIn("local function show()\n", out["node_lua"])

    def test_holdall_round_trip_with_a_field_script(self):
        out = self.round_trip("holdall", has_field=True)
        self.assertIn("local function capture(team, squad)\n", out["node_lua"])
        self.assertIn("local fs = state.field { holder = nil }\n", out["field_lua"])
        self.assertIn("every(1, check)\n", out["field_lua"])

    # ---- the page ----

    def test_page_in_english_and_portuguese(self):
        page = self.open("en")
        expect(page.locator("#tab-node")).to_have_text("Boxes (node.lua)")
        expect(page.locator("#ws-node .blocklyToolbox")).to_contain_text("Events")
        expect(page.locator("#ws-node .blocklyToolbox")).to_contain_text("Box hardware")
        expect(page.locator("#ws-field .blocklyToolbox")).to_contain_text("Field")
        page = self.open("pt")
        expect(page.locator("html")).to_have_attribute("lang", "pt-PT")
        expect(page.locator("#tab-node")).to_have_text("Caixas (node.lua)")
        expect(page.locator("#ws-node .blocklyToolbox")).to_contain_text("Eventos")
        expect(page.locator("#ws-node .blocklyToolbox")).to_contain_text("Hardware da caixa")
        # Blockly's own blocks speak Portuguese too (its msg/pt.js).
        page.locator("#ws-node .blocklyToolboxCategory", has_text="Lógica").click()
        expect(page.locator("#ws-node .blocklyToolboxFlyout")).to_contain_text("senão")
        # The language chosen sticks.
        page.goto(self.url)
        expect(page.locator("body")).to_have_attribute("data-ready", "true")
        expect(page.locator("#tab-mode")).to_have_text("Modo")

    def test_an_example_through_the_page(self):
        page = self.open("en")
        page.select_option("#example", "holdall")
        expect(page.locator("#code")).to_contain_text('on("team_input.hold", function(e)')
        expect(page.locator("#no-problems")).to_be_visible()
        page.click("#tab-field")
        expect(page.locator("#code")).to_contain_text("local function check()")
        page.click("#tab-mode")
        expect(page.locator("[name=name]")).to_have_value("Hold-All Domination")
        page.fill("[name=name]", "Hold Them All")
        expect(page.locator("#code")).to_contain_text('name: "Hold Them All"')
        page.fill("[name=id]", "Bad Id")
        expect(page.locator("#problems li")).to_have_count(1)
        expect(page.locator("#problems li")).to_have_attribute("data-key", "problem_bad_id")
        page.click("[data-file=node_lua]")
        expect(page.locator("#code")).to_contain_text("-- Hold Them All, on each box.")
        with page.expect_download() as info:
            page.click("#download")
        self.assertEqual(info.value.suggested_filename, "node.lua")
        self.assertEqual(Path(info.value.path()).read_text(encoding="utf-8"),
                         page.evaluate("() => window.atalaiaEditor.files().node_lua"))

    def test_save_open_and_the_draft(self):
        page = self.open("en")
        page.select_option("#example", "domination")
        expect(page.locator("#code")).to_contain_text("local function show()")
        with page.expect_download() as info:
            page.click("#save")
        saved = json.loads(Path(info.value.path()).read_text(encoding="utf-8"))
        self.assertEqual(info.value.suggested_filename, "org.atalaia.domination.blocks.json")
        self.assertEqual(saved["format"], "atalaia-mode-editor")
        lua = page.evaluate("() => window.atalaiaEditor.files().node_lua")
        page.click("#new")
        expect(page.locator("#code")).to_have_text("")
        page.set_input_files("#open-file", files=[{"name": "d.json", "mimeType": "application/json",
                                                   "buffer": json.dumps(saved).encode()}])
        expect(page.locator("#code")).to_contain_text("local function show()")
        self.assertEqual(page.evaluate("() => window.atalaiaEditor.files().node_lua"), lua)
        # The page keeps a draft: a reload brings the blocks back.
        page.reload()
        expect(page.locator("body")).to_have_attribute("data-ready", "true")
        self.assertEqual(page.evaluate("() => window.atalaiaEditor.files().node_lua"), lua)

    def test_a_problem_points_at_its_block(self):
        page = self.open("en")
        proj = project(node=[proc("lost", B("atalaia_log", inputs={"TEXT": ev("team")}))])
        page.evaluate("p => window.atalaiaEditor.load(p)", proj)
        item = page.locator("#problems li")
        expect(item).to_have_text(re.compile("outside a \"when\" block"))
        item.click()
        selected = page.evaluate("() => Blockly.getSelected() && Blockly.getSelected().type")
        self.assertEqual(selected, "atalaia_event_value")


if __name__ == "__main__":
    unittest.main()
