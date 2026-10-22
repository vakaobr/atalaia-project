# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Browser tests of the mode editor (phase 5 plan phases 1-3; AC-1 to AC-3).

The editor's page, served by the simulator's real web server, runs in headless
Chromium (Playwright). The Lua generator runs where it runs for a user, in the
page, through window.atalaiaEditor.generate(project), so the same code is
tested: small projects give exact Lua (the generator's unit tests); the three
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
            screens = proj.get("screens") or {}
            if screens:
                # The project's own screen files (plan phase 3) are the mode's, byte for byte.
                (folder / "assets" / "screens").mkdir(parents=True)
                for screen, text in screens.items():
                    self.assertEqual(text, (original / "assets" / "screens" / f"{screen}.yaml").read_text(
                        encoding="utf-8"), screen)
                    (folder / "assets" / "screens" / f"{screen}.yaml").write_text(text, encoding="utf-8")
            elif (original / "assets").is_dir():
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

    def test_master_satellites_round_trip_with_two_roles_and_screens(self):
        """Plan phase 3's example: two roles running one box script, a mode command from the
        controller (cmd.mode "status"), the mode's own screen, the controller's list index."""
        out = self.round_trip("master_satellites", has_field=True)
        self.assertIn('on("cmd.mode", function(e)\n  if e.name ~= "status" then\n    return\n  end\n', out["node_lua"])
        self.assertIn('ui.screen("master_status", {', out["node_lua"])
        self.assertIn('field.send(id, "mode", { name = "status", team = owner,', out["field_lua"])
        self.assertIn('id = (node_ids("master"))[1]\n', out["field_lua"])
        self.assertIn('local count, id, owner,', out["field_lua"])  # n is the loops' own

    # ---- plan phase 3: geo, GM commands, roles, kinds, screens ----

    def test_geo_blocks(self):
        page = self.open()
        zone = B("atalaia_geo_polygon", inputs={"POINTS": seq(*(
            B("atalaia_geo_point", inputs={"LAT": num(lat), "LON": num(lon)}) for lat, lon in ((1, 2), (1, 3), (2, 3))))})
        circle = B("atalaia_geo_circle", inputs={"LAT": num(38.7), "LON": num(-9.1), "RADIUS": num(25)})
        handler = on("gps.fix", seq(
            B("controls_if", inputs={"IF0": B("logic_negate", inputs={"BOOL": B("atalaia_event_has_position")}),
                                     "DO0": B("atalaia_return")}),
            B("controls_if", inputs={"IF0": B("atalaia_geo_in_zone", inputs={"LAT": ev("lat"), "LON": ev("lon"),
                                                                              "ZONE": circle}),
                                     "DO0": B("atalaia_emit", {"TYPE": "x.club.inside", "PRIO": "default"})}),
            B("atalaia_log", inputs={"TEXT": B("atalaia_geo_distance", inputs={
                "LAT1": ev("lat"), "LON1": ev("lon"), "LAT2": num(38.7), "LON2": num(-9.1)})}),
            B("atalaia_log", inputs={"TEXT": B("atalaia_geo_in_zone", inputs={"LAT": num(1.5), "LON": num(2.5),
                                                                              "ZONE": zone})}),
        ))
        out = self.generate(page, project(node=[handler]))
        self.assertEqual(out["problems"], [])
        self.assertEqual(body(out["node_lua"]), (
            'on("gps.fix", function(e)\n'
            '  if not (type(e.lat) == "number" and type(e.lon) == "number") then\n'
            '    return\n'
            '  end\n'
            '  if geo.in_zone(e.lat, e.lon, { type = "circle", lat = 38.7, lon = -9.1, radius_m = 25 }) then\n'
            '    emit("x.club.inside")\n'
            '  end\n'
            '  log(geo.distance(e.lat, e.lon, 38.7, -9.1))\n'
            '  log(geo.in_zone(1.5, 2.5, { type = "polygon", points = { { 1, 2 }, { 1, 3 }, { 2, 3 } } }))\n'
            'end)\n'))
        self.assertEqual(yaml.safe_load(out["mode_yaml"])["roles"], {"zone": {"requires": ["gps"]}})
        # The VIP's field input, with its values; an area needs 3 corners.
        field = on("position.fix", B("controls_if", inputs={
            "IF0": B("logic_compare", {"OP": "EQ"}, {"A": ev("role"), "B": text("vip")}),
            "DO0": B("atalaia_log", inputs={"TEXT": B("atalaia_geo_in_zone", inputs={
                "LAT": ev("lat"), "LON": ev("lon"), "ZONE": B("atalaia_geo_polygon", inputs={
                    "POINTS": B("atalaia_geo_point", inputs={"LAT": num(1), "LON": num(2)})})})})}), kind="field")
        out = self.generate(page, project(field=[field]))
        self.assertIn('if e.role == "vip" then\n    log(geo.in_zone(e.lat, e.lon, { type = "polygon", points = { { 1, 2 } } }))',
                      out["field_lua"])
        self.assertEqual([p["key"] for p in out["problems"]], ["problem_polygon_points"])
        # It runs: a GPS fix inside the circle, in the simulator.
        out = self.generate(page, project(node=[handler]))
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "unit"
            (folder / "tests").mkdir(parents=True)
            self.write_mode(folder, out)
            (folder / "tests" / "geo.yaml").write_text(
                "name: geo\nsteps:\n  - input: { node: zone, type: gps.fix, data: {} }\n"
                "  - input: { node: zone, type: gps.fix, data: { lat: 38.7001, lon: -9.1, acc: 5 } }\n"
                "  - expect: x.club.inside\n  - expect_no: script.error\n")
            mode = load_mode(folder)
            result = run_test(CORE, mode, mode.tests[0])
            self.assertTrue(result.passed, f"{result.message}\n{out['node_lua']}")

    def test_gm_commands_in_the_manifest(self):
        page = self.open()
        declare = B("atalaia_command_declare", {"NAME": "refill", "ROLES": "medic", "LABEL": "Refill the kit",
                                                "LABEL_PT": "Repor as ligaduras"}, x=500)
        handler = B("atalaia_on_command", {"NAME": "refill"}, {"DO": B("atalaia_log", inputs={"TEXT": ev("name")})})
        proj = project(node=[declare, handler], roles=[{"name": "medic", "inputs": None, "needed": True}],
                       name_pt="Kit")
        out = self.generate(page, proj)
        self.assertEqual(out["problems"], [])
        self.assertEqual(body(out["node_lua"]), (
            'on("cmd.mode", function(e)\n'
            '  if e.name ~= "refill" then\n'
            '    return\n'
            '  end\n'
            '  log(e.name)\n'
            'end)\n'))
        manifest = yaml.safe_load(out["mode_yaml"])
        self.assertEqual(manifest["commands"], {"refill": {"roles": ["medic"], "label": "Refill the kit"}})
        self.assertEqual(manifest["i18n"]["pt"]["commands"], {"refill": "Repor as ligaduras"})
        # The manifest is one the simulator and the controller take.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "unit"
            folder.mkdir()
            self.write_mode(folder, out)
            self.assertEqual(load_mode(folder).commands["refill"]["roles"], ["medic"])
        # Problems: a command for a role the mode lacks, one without its handler, one twice (the
        # first on the workspace counts, the medic one further right is the second).
        bad = project(node=[declare, B("atalaia_command_declare", {"NAME": "refill", "ROLES": "zone", "LABEL": "x",
                                                                   "LABEL_PT": ""}),
                            B("atalaia_command_declare", {"NAME": "open", "ROLES": "zone, gate", "LABEL": "Open",
                                                          "LABEL_PT": ""})])
        out = self.generate(page, bad)
        self.assertEqual(sorted((p["key"], p.get("name")) for p in out["problems"]), [
            ("problem_command_twice", "refill"), ("problem_command_unhandled", "open"),
            ("problem_command_unhandled", "refill"), ("problem_role_unknown", "gate")])

    def test_roles_and_kinds(self):
        page = self.open()
        node = [on("team_input.hold", B("atalaia_log", inputs={"TEXT": ev("team")}), y=0),
                on("gps.fix", B("atalaia_log", inputs={"TEXT": ev("lat")}), y=200),
                B("atalaia_screen", {"NAME": "captured"})]
        roles = [{"name": "checkpoint", "inputs": ["team_input"], "needed": True},
                 {"name": "payload", "inputs": ["gps"], "needed": False}]
        out = self.generate(page, project(node=[on("game.start", node[2], y=400), node[0], node[1]], roles=roles,
                                          kind="role"))
        self.assertEqual(out["problems"], [])
        manifest = yaml.safe_load(out["mode_yaml"])
        self.assertEqual(manifest["kind"], "role")
        self.assertEqual(manifest["roles"], {
            "checkpoint": {"requires": ["team_input"], "optional": ["display"]},
            "payload": {"requires": ["gps"], "optional": ["display"], "needed": False}})
        # Without its own inputs a role needs every input the script reacts to (as before plan phase 3).
        out = self.generate(page, project(node=node[:2], roles=[{"name": "zone"}], kind="modifier"))
        manifest = yaml.safe_load(out["mode_yaml"])
        self.assertEqual((manifest["kind"], manifest["roles"]), ("modifier", {"zone": {"requires": ["team_input", "gps"]}}))
        # A project saved before plan phase 3 (one "role") still opens as that role.
        self.assertEqual(yaml.safe_load(self.generate(page, project(role="gate"))["mode_yaml"])["roles"], {"gate": {}})
        # Problems: an input the script never reacts to, a role with none of them, a role twice, a bad
        # name, a role the controller looks for that the mode lacks, an unknown screen.
        field = [B("atalaia_every", inputs={"SECONDS": num(1), "DO": B("atalaia_log", inputs={
            "TEXT": B("lists_length", inputs={"VALUE": B("atalaia_field_ids", {"ROLE": "zone"})})})})]
        bad = project(node=[node[0], on("game.start", B("atalaia_screen", {"NAME": "nowhere"}), y=300)], field=field,
                      roles=[{"name": "a", "inputs": ["keypad"]}, {"name": "b", "inputs": []}, {"name": "a"},
                             {"name": "Bad Name"}])
        out = self.generate(page, bad)
        self.assertEqual(sorted((p["key"], p.get("name")) for p in out["problems"]), [
            ("problem_bad_role", "Bad Name"), ("problem_role_input_unhandled", "a"), ("problem_role_no_input", "b"),
            ("problem_role_twice", "a"), ("problem_role_unknown", "zone"), ("problem_screen_unknown", "nowhere")])
        self.assertEqual(self.generate(page, project(roles=[]))["problems"][0]["key"], "problem_no_role")

    def test_the_mode_tab_roles_kind_and_screens(self):
        page = self.open("en")
        page.click("#tab-mode")
        expect(page.locator(".role-row")).to_have_count(1)
        page.select_option("[name=kind]", "role")
        expect(page.locator("#code")).to_contain_text("kind: role")
        page.click("#role-add")
        page.locator(".role-row").nth(1).locator(".role-name").fill("gate")
        page.locator(".role-row").nth(1).locator(".role-needed").uncheck()
        expect(page.locator("#code")).to_contain_text("  gate: { needed: false }")
        # Its own inputs: a keypad the (empty) box script never reacts to is a problem.
        page.locator(".role-row").nth(1).locator(".role-auto").uncheck()
        page.locator(".role-row").nth(1).locator(".role-input[value=keypad]").check()
        expect(page.locator("#problems li[data-key=problem_role_input_unhandled]")).to_have_count(1)
        page.locator(".role-row").nth(1).locator(".role-remove").click()
        expect(page.locator(".role-row")).to_have_count(1)
        expect(page.locator("#problems li")).to_have_count(0)
        # Screens from files: offered in the boxes' toolbox, kept in the saved project, refused when bad.
        good = b"template: banner\nlayout:\n  - type: label\n    text: Hi\n"
        page.set_input_files("#screen-files", files=[
            {"name": "banner.yaml", "mimeType": "application/yaml", "buffer": good},
            {"name": "other.yaml", "mimeType": "application/yaml", "buffer": b"template: banner\n"}])
        expect(page.locator("#screens li")).to_have_count(1)
        expect(page.locator("#screens li")).to_contain_text("assets/screens/banner.yaml")
        page.click("#tab-node")
        page.locator("#ws-node .blocklyToolboxCategory", has_text="Box hardware").click()
        expect(page.locator("#ws-node .blocklyToolboxFlyout")).to_contain_text("banner")
        page.click("[data-file='assets/screens/banner.yaml']")
        expect(page.locator("#code")).to_have_text(good.decode())
        saved = page.evaluate("() => window.atalaiaEditor.project()")
        self.assertEqual(saved["screens"], {"banner": good.decode()})
        self.assertEqual(saved["mode"]["kind"], "role")
        page.click("#tab-mode")
        page.locator("#screens li button").click()
        expect(page.locator("#screens li")).to_have_count(0)

    def test_the_test_button_starts_a_box_per_role(self):
        page = self.open("en")
        page.select_option("#example", "master_satellites")
        expect(page.locator("#code")).to_contain_text("local function capture(team, squad)")
        page.fill("#test-boxes", "3")
        page.click("#test")
        expect(page.locator("#test-message")).to_have_text(
            "Master and Satellites is running in the simulator with 3 boxes.")
        self.assertEqual(self.game.sim.mode.id, "org.atalaia.master_satellites")
        self.assertEqual(list(self.game.sim.nodes), ["master1", "satellite1", "satellite2"])
        expect(page.locator("#problems li")).to_have_count(0)

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

    def test_page_in_german(self):
        """Plan phase 10 (P5H-2): the editor's German table and Blockly's msg/de.js."""
        page = self.open("de")
        expect(page.locator("html")).to_have_attribute("lang", "de")
        expect(page.locator("#tab-node")).to_have_text("Boxen (node.lua)")
        expect(page.locator("#ws-node .blocklyToolbox")).to_contain_text("Ereignisse")
        expect(page.locator("#ws-node .blocklyToolbox")).to_contain_text("Box-Hardware")
        page.locator("#ws-node .blocklyToolboxCategory", has_text="Logik").click()
        expect(page.locator("#ws-node .blocklyToolboxFlyout")).to_contain_text("sonst")
        expect(page.locator("#lang")).to_have_value("de")

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


    # ---- testing in the simulator (plan phase 2) ----

    def test_each_line_of_the_examples_knows_its_block(self):
        """The map from a generated line to its block (generator.js lineBlocks), which puts the
        simulator's errors on blocks: it exists for every script of both examples, and a line
        maps to the block that wrote it."""
        page = self.open("en")
        for name in ("domination", "holdall", "master_satellites"):
            page.select_option("#example", name)
            expect(page.locator("#code")).to_contain_text("local function")
            for kind in ("node", "field") if name != "domination" else ("node",):
                with self.subTest(example=name, script=kind):
                    lines = page.evaluate("k => window.atalaiaEditor.lineBlocks(k)", kind)
                    code = page.evaluate("k => window.atalaiaEditor.files()[k + '_lua']", kind)
                    self.assertIsNotNone(lines)
                    self.assertEqual(len(lines), len(code.split("\n")))
                    types = page.evaluate("([k, ids]) => ids.map((id) => id && window.atalaiaEditor.blockType(k, id))",
                                          [kind, lines])
                    for number, line in enumerate(code.split("\n")):
                        if line.startswith(("on(", "every(")):
                            self.assertTrue(types[number].startswith(("atalaia_on", "atalaia_every")),
                                            (line, types[number]))
                        if line.strip().startswith("score.add("):
                            self.assertEqual(types[number], "atalaia_score_add", line)

    def test_the_test_button_plays_the_mode_in_the_simulator(self):
        page = self.open("en")
        page.select_option("#example", "holdall")
        expect(page.locator("#code")).to_contain_text("local function capture(team, squad)")
        page.fill("#test-boxes", "2")
        page.click("#test")
        expect(page.locator("#test-message")).to_have_text(
            "Hold-All Domination is running in the simulator with 2 boxes.")
        self.assertEqual(self.game.sim.mode.id, "org.atalaia.holdall")
        self.assertEqual(list(self.game.sim.nodes), ["zone1", "zone2"])
        self.assertTrue(self.game.started)
        # The simulator's page, opened from the editor, shows the mode and its field controller.
        with page.context.expect_page() as info:
            page.click("#test-open")
        sim = info.value
        expect(sim.locator("#mode")).to_have_text(re.compile("^Hold-All Domination"))
        expect(sim.locator("#controller")).to_be_visible()
        expect(sim.locator("#controller-status")).to_have_text("running")
        expect(sim.locator(".node")).to_have_count(2)
        # Playing it: red holds both boxes, and the controller's script scores for red.
        for node in ("zone1", "zone2"):
            self.game.act("hold", {"node": node, "team": "red"})
            self.game.act("step", {"seconds": 3.5})
            self.game.act("release", {"node": node})
        self.game.act("step", {"seconds": 20})
        expect(sim.locator("#controller-scores")).to_contain_text(re.compile(r"red [1-9]"))
        expect(page.locator("#problems li")).to_have_count(0)

    def test_simulator_errors_come_back_to_their_blocks(self):
        page = self.open("en")
        before = self.game.reloads
        # A box script whose top-level code fails while it loads: the simulator keeps its game.
        bad = B("atalaia_log", inputs={"TEXT": B("atalaia_idiv", inputs={"A": num(1), "B": num(0)})},
                x=10, y=200)
        page.evaluate("p => window.atalaiaEditor.load(p)", project(node=[on("game.start", B("atalaia_log", inputs={
            "TEXT": text("hello")})), bad]))
        page.click("#test")
        expect(page.locator("#test-message")).to_contain_text("could not load")
        self.assertEqual(self.game.reloads, before)
        item = page.locator("#problems li[data-key=problem_sim]")
        expect(item).to_have_count(1)
        expect(item).to_contain_text("In the simulator:")
        expect(item).to_contain_text("node.lua:")
        item.click()
        self.assertEqual(page.evaluate("() => Blockly.getSelected().id"), bad["id"])
        self.assertTrue(page.evaluate("() => Blockly.getSelected().hasIcon(Blockly.icons.IconType.WARNING)"))
        # An error in a handler, while the game runs: it loads, and the error points at its block.
        inner = B("atalaia_log", inputs={"TEXT": B("atalaia_idiv", inputs={"A": num(2), "B": num(0)})})
        page.evaluate("p => window.atalaiaEditor.load(p)", project(node=[on("game.start", inner)]))
        expect(page.locator("#problems li")).to_have_count(0)  # the old errors went with the old files
        page.click("#test")
        expect(page.locator("#test-message")).to_contain_text("with script errors")
        self.assertEqual(self.game.reloads, before + 1)
        page.locator("#problems li[data-key=problem_sim]").click()
        self.assertEqual(page.evaluate("() => Blockly.getSelected().id"), inner["id"])
        # Changing the blocks clears the simulator's errors: they were about other files.
        page.fill("#test-boxes", "1")
        page.evaluate("() => window.atalaiaEditor.load(window.atalaiaEditor.project())")  # same files
        expect(page.locator("#problems li[data-key=problem_sim]")).to_have_count(1)
        page.click("#tab-mode")
        page.fill("[name=name]", "Renamed")
        expect(page.locator("#problems li[data-key=problem_sim]")).to_have_count(0)
        expect(page.locator("#test-status")).to_be_hidden()


if __name__ == "__main__":
    unittest.main()
