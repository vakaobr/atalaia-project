# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The phase 2 mode pack in the simulator: modifiers composed with main modes,
and field scripts (Hold-All Domination, Last Stand) run as the controller runs them.

    cd simulator && python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from atalaia_sim.core import Core, find_library
from atalaia_sim.mode import ModeError, compose, compose_scripts, load_mode
from atalaia_sim.sim import CONTROLLER, Simulation

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


class ComposeTests(unittest.TestCase):
    def test_a_modifier_joins_a_main_mode(self):
        dom, codes = load_mode(MODES / "domination"), load_mode(MODES / "codes")
        self.assertEqual((dom.kind, codes.kind), ("mode", "modifier"))
        both = compose(dom, [codes])
        self.assertEqual(both.id, "org.atalaia.domination+org.atalaia.codes")
        self.assertEqual(both.parts, ("org.atalaia.domination", "org.atalaia.codes"))
        self.assertEqual(both.roles, dom.roles)
        self.assertEqual(set(both.params), set(dom.params) | {"codes"})
        self.assertEqual(both.node_script, f"do\n{dom.node_script}\nend\ndo\n{codes.node_script}\nend\n")
        self.assertIsNone(both.field_script)
        self.assertEqual(both.i18n["pt"]["name"], "Domínio + Códigos")
        self.assertIn("codes", both.i18n["pt"]["params"])
        self.assertIs(compose(dom, []), dom)

    def test_one_script_is_left_alone(self):
        self.assertEqual(compose_scripts(["x = 1"]), "x = 1")
        self.assertEqual(compose_scripts(["a", "b"]), "do\na\nend\ndo\nb\nend\n")

    def test_field_scripts_compose_too(self):
        holdall, codes = load_mode(MODES / "holdall"), load_mode(MODES / "codes")
        both = compose(holdall, [codes])
        self.assertEqual(both.field_script, holdall.field_script)

    def test_bad_combinations_are_refused(self):
        dom, bomb, codes = (load_mode(MODES / n) for n in ("domination", "bomb", "codes"))
        with self.assertRaisesRegex(ModeError, "is a modifier"):
            compose(codes, [codes])
        with self.assertRaisesRegex(ModeError, "not a modifier"):
            compose(dom, [bomb])
        with self.assertRaisesRegex(ModeError, "named twice"):
            compose(dom, [codes, codes])
        clash = load_mode(MODES / "codes")
        clash.id, clash.params = "org.test.clash", {"tick_s": {"type": "int", "default": 1}}
        with self.assertRaisesRegex(ModeError, "both have"):
            compose(dom, [clash])
        long = load_mode(MODES / "codes")
        long.id = "org.example." + "x" * 40
        with self.assertRaisesRegex(ModeError, "63 bytes"):
            compose(dom, [long])

    def test_manifest_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "node.lua").write_text("local x = 1\n")
            for manifest, message in [
                ("kind: plugin", "kind must be"),
                ("i18n: [pt]", "i18n must map"),
                ("i18n: { pt: { name: 3 } }", "must be text"),
                ("i18n: { pt: { title: x } }", "unknown key"),
                ("i18n: { pt: { params: { a: 1 } } }", "maps parameter names"),
            ]:
                (path / "mode.yaml").write_text(f"id: org.t.m\nversion: 1\nroles: {{ a: {{}} }}\n{manifest}\n")
                with self.subTest(manifest), self.assertRaisesRegex(ModeError, message):
                    load_mode(path)

    def test_string_params_have_a_byte_limit(self):
        codes = load_mode(MODES / "codes")
        with self.assertRaisesRegex(ModeError, "at most 120 bytes"):
            codes.resolve_params({"codes": "1:hint," * 30}, TEAMS)


@unittest.skipIf(CORE is None, "the shared core library is not built")
class FieldScriptSimTests(unittest.TestCase):
    def sim(self, folder: str, nodes: dict[str, str], params=None, modifiers=()):
        mode = compose(load_mode(MODES / folder), [load_mode(MODES / m) for m in modifiers])
        sim = Simulation(CORE, mode, nodes, TEAMS, mode.resolve_params(params or {}, TEAMS))
        self.addCleanup(sim.close)
        sim.start()
        return sim

    def types(self, sim: Simulation, node: str = CONTROLLER) -> list[str]:
        return [e.type for e in sim.events if e.node == node]

    def test_holdall_over_five_boxes(self):
        boxes = {f"box{i}": "zone" for i in range(1, 6)}
        sim = self.sim("holdall", boxes, {"tick_s": 5, "points_per_tick": 3})
        for name in boxes:
            sim.hold(name, "red", 3)               # red holds all five at 15 s
        self.assertEqual(self.types(sim), ["game.start", "holdall.scoring_start"])
        sim.wait(20)                               # ticks at 20, 25, 30, 35
        self.assertEqual(sim.score("red"), 12)
        self.assertEqual([sim.score("red", n) for n in boxes], [0] * 5)
        sim.hold("box3", "blue", 3)
        sim.wait(30)
        self.assertEqual(sim.score("red"), 12)
        self.assertEqual(self.types(sim)[-1], "holdall.scoring_stop")
        self.assertEqual(sim.owners, {1: "red", 2: "red", 3: "blue", 4: "red", 5: "red"})
        self.assertEqual(sim.problems, [])

    def test_last_stand_ends_the_game_on_every_box(self):
        sim = self.sim("laststand", {"a": "zone", "b": "zone", "c": "zone"}, {"countdown_s": 30})
        sim.hold("a", "red", 3)
        sim.hold("b", "red", 3)
        sim.wait(30)
        end = [e for e in sim.events if e.type == "game.end" and e.node == CONTROLLER]
        self.assertEqual([(e.t_ms, e.data) for e in end], [(36_000, {"reason": "win", "winner": "red"})])
        self.assertEqual({v.runtime.status for v in sim.nodes.values()}, {"ended"})
        self.assertEqual(sim.field.status, "ended")
        # Nothing more happens after the end.
        sim.wait(60)
        self.assertEqual(len([e for e in sim.events if e.type == "game.end"]), 1)

    def test_field_send_reaches_the_box(self):
        mode = load_mode(MODES / "holdall")
        mode.field_script = ('on("game.start", function()\n'
                             '  for _, n in ipairs(field.nodes("zone")) do\n'
                             '    field.send(n.id, "set_owner", { team = "blue" })\n'
                             '  end\n'
                             '  field.send(1, "message", { text = "hello" })\n'
                             '  log(tostring(field.send(1, "reboot", {})))\n'
                             'end)\n')
        sim = Simulation(CORE, mode, {"a": "zone", "b": "zone"}, TEAMS, mode.resolve_params({}, TEAMS))
        self.addCleanup(sim.close)
        sim.start()
        self.assertEqual([(c[1], c[2]) for c in sim.field_commands],
                         [("a", "set_owner"), ("b", "set_owner"), ("a", "message")])
        self.assertEqual(sim.owners, {1: "blue", 2: "blue"})
        self.assertEqual(sim.field_logs, ["false"])  # reboot is not a mode command
        captured = [(e.node, e.team, e.t_ms) for e in sim.events if e.type == "zone.captured"]
        self.assertEqual(captured, [("a", "blue", 0), ("b", "blue", 0)])

    def test_codes_on_every_box_of_a_composed_game(self):
        sim = self.sim("domination", {"x": "zone", "y": "zone"}, {"codes": "11:points:5,22:hint"},
                       modifiers=("codes",))
        sim.hold("x", "red", 3)
        sim.keys("x", "11#")
        sim.keys("y", "22#")
        used = [(e.node, e.team, e.data) for e in sim.events if e.type == "code.used"]
        self.assertEqual(used, [("x", "red", {"team": "red", "code": "1", "kind": "points", "amount": 5,
                                              "holder": "red"}),
                                ("y", None, {"code": "2", "kind": "hint"})])
        # Codes are per box: the same code works once on each box.
        sim.hold("y", "blue", 3)
        sim.keys("y", "11#")
        self.assertEqual(sim.score("blue", "y"), 5)
        self.assertEqual(sim.problems, [])


class FirmwareBuiltinTests(unittest.TestCase):
    """The Field Box carries every built-in mode a box can run, with the manifests' default
    parameters; the others are named here, with the reason."""

    FIRMWARE = MODES.parent / "firmware" / "esp32"
    # Folders that are not Field Box presets (decision P4R23).
    NOT_ON_THE_BOX = {
        "target_windows": "needs the target addon's hit sensor and its driver (P4R4, HW2)",
    }

    def box_folders(self):
        folders = {p.parent.name for p in MODES.glob("*/mode.yaml")}
        self.assertLessEqual(set(self.NOT_ON_THE_BOX), folders)
        return folders - set(self.NOT_ON_THE_BOX)

    def test_presets_match_the_manifests(self):
        src = (self.FIRMWARE / "main" / "builtin_presets.c").read_text(encoding="utf-8")
        start = src.index("builtin[] = {")
        body = src[start:src.index("\n};", start)]
        entries = re.findall(r'\{"([^"]+)", "([^"]+)",((?:\s*"(?:[^"\\]|\\.)*")+)\}', body)
        modes = {m.id: m for m in (load_mode(MODES / f) for f in sorted(self.box_folders()))}
        self.assertEqual({e[1] for e in entries}, set(modes))
        for label, mode_id, literals in entries:
            text = "".join(s.encode().decode("unicode_escape")
                           for s in re.findall(r'"((?:[^"\\]|\\.)*)"', literals))
            with self.subTest(mode_id):
                self.assertEqual(json.loads(text), modes[mode_id].resolve_params({}, TEAMS))
                self.assertEqual(label, modes[mode_id].name.split(" / ")[0])

    def test_every_mode_is_in_the_image(self):
        folders = self.box_folders()
        cmake = (self.FIRMWARE / "main" / "CMakeLists.txt").read_text(encoding="utf-8")
        listed = re.search(r"foreach\(mode ([a-z_\s]+)\)", cmake).group(1).split()
        self.assertEqual(set(listed), folders)
        shell = (self.FIRMWARE / "main" / "shell.c").read_text(encoding="utf-8")
        host = (self.FIRMWARE / "test" / "box_host" / "box_host.c").read_text(encoding="utf-8")
        for folder in folders:
            mode_id = load_mode(MODES / folder).id
            self.assertIn(f"_binary_{folder}_node_lua_start", shell)
            self.assertIn(f'{{"{folder}", "{mode_id}"}}', host)
        for folder in self.NOT_ON_THE_BOX:
            self.assertNotIn(f"_binary_{folder}_node_lua_start", shell)

    def test_scripts_fit_a_preset_and_a_reduced_box(self):
        """A preset holds 16 KB of script (PRESET_SOURCE_MAX): every main mode with every
        modifier fits with room to spare, and runs in a Reduced-tier box's 64 KB Lua heap."""
        modes = [load_mode(p.parent) for p in sorted(MODES.glob("*/mode.yaml"))]
        mods = [m for m in modes if m.kind == "modifier"]
        for main in (m for m in modes if m.kind == "mode"):
            with self.subTest(main.id):
                both = compose(main, mods)
                self.assertLess(len(both.node_script.encode()), 16 * 1024 - 2048)
                if CORE is None:
                    continue
                role = next(iter(both.roles))
                params = both.resolve_params({"codes": "4711:points:5,0815:hint"}, TEAMS)
                sim = Simulation(CORE, both, {"a": role}, TEAMS, params, mem_limit=64 * 1024)
                self.addCleanup(sim.close)
                # Loaded, the largest (Bomb with Codes) takes about 50 KB of the 64 KB.
                self.assertLess(sim.node("a").runtime.mem_used, 56 * 1024)
                sim.start()
                sim.hold("a", "red", 6)
                sim.keys("a", "4711#")
                sim.wait(30)
                runtime = sim.node("a").runtime
                self.assertEqual(runtime.status, "running", runtime.last_error)
                self.assertEqual([e for e in sim.events if e.type == "script.error"], [])


class TemplateLanguageTests(unittest.TestCase):
    """The built-in modes' screens in every language of the boxes (decision P5H-12): a template
    that picks its texts by language (lang from the box, or the mode's params.lang) has German
    and Traditional Chinese wherever it has Portuguese, and the manifests every language."""

    LANGS = ("pt", "de", "zh-tw")

    def test_every_language_template_has_german_and_chinese(self):
        for path in sorted(MODES.glob("*/assets/screens/*.yaml")):
            text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                             if not line.lstrip().startswith("#"))
            if "lang" not in text:
                continue  # English only (Kill Confirmed, Respawn, Player Check-in)
            with self.subTest(path.relative_to(MODES).as_posix()):
                de = len(re.findall(r"lang == 'de'", text))
                zh = len(re.findall(r"lang == 'zh-tw'", text))
                self.assertGreater(de, 0)
                self.assertGreater(zh, 0)

    def test_every_manifest_has_every_language(self):
        for path in sorted(MODES.glob("*/mode.yaml")):
            mode = load_mode(path.parent)
            with self.subTest(mode.id):
                self.assertEqual(sorted(mode.i18n), sorted(self.LANGS))
                for lang in self.LANGS:
                    self.assertEqual(set(mode.i18n[lang].get("params", {})), set(mode.params))
                    self.assertEqual(set(mode.i18n[lang].get("commands", {})), set(mode.commands or {}))

    @unittest.skipIf(CORE is None, "needs the shared core library")
    def test_a_box_language_picks_the_texts(self):
        neutral = (MODES / "domination" / "assets" / "screens" / "neutral.yaml").read_text(
            encoding="utf-8")
        header = re.search(r'text: "(\{lang == .*\})"', neutral).group(1)
        hold = re.search(r'text: "(\{params.capture_hold_ms / 1000\} s zum .*)"', neutral).group(1)
        for lang, want in (("pt", "ZONA"), ("en", "ZONE"), ("de", "ZONE"), ("zh-tw", "據點"),
                           ("fr", "ZONE"), (None, "ZONE")):
            data = {} if lang is None else {"lang": lang}
            self.assertEqual(CORE.screen_text(header, data, {}), want, lang)
        self.assertEqual(CORE.screen_text(hold, {}, {"capture_hold_ms": 3000}),
                         "3 s zum Einnehmen der Zone")
        seq = (MODES / "hacking_terminal" / "assets" / "screens" / "hack_sequence.yaml").read_text(
            encoding="utf-8")
        turn = re.search(r"""text: "(\{params.lang == 'en' && 'YOUR TURN'.*\})\"""", seq).group(1)
        for lang, want in (("pt", "A TUA VEZ"), ("en", "YOUR TURN"), ("de", "DU BIST DRAN"),
                           ("zh-tw", "換你了")):
            self.assertEqual(CORE.screen_text(turn, {}, {"lang": lang}), want, lang)


if __name__ == "__main__":
    unittest.main()
