#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes protocol/vectors/scenario_compile.json, the scenario compiler's golden outputs.

    python3 tools/scenario_compile_vectors.py           write the file
    python3 tools/scenario_compile_vectors.py --check   fail if it is stale

The scenario compiler (core/scenario/, in the C core since decision PE24-109; the Pi reads the
manifest's text with PyYAML, controller/atalaia_controller/scenarios) compiles a set of manifests: the valid ones of protocol/vectors/scenario.json, the examples in
controller/tests/scenarios and the cases below, which use every objective type, parameter and
effect, translations, scenario parameters, YAML 1.1's readings (yes, 0815, 1:30, merge keys),
anchors, and names and descriptions with quotes, Unicode and control characters. For each one
the file holds the manifest's text, its problems (path, code, level) and, when it compiles, the
package's field.lua and mode.yaml in full and mode.yaml read back as data. A second list,
``loads``, holds YAML texts with what the manifest loader reads from them (typed, so that a date,
a float and an integer stay apart) or that it refuses them.

The Android field controller, which reads the text with its own PyYAML-compatible reader
(app/lib/controller/scenarios/scenario_manifest.dart) and calls the same core, must give the same
problems and byte-identical files: app/test/controller/scenarios_test.dart reads this file, and
controller/tests/test_scenario_compile_vectors.py runs ``--check`` so that a change to the
compiler without new vectors fails the Pi's tests too. These files were first written by the Pi's
Python compiler; the core's gives every one of them byte for byte. Needs PyYAML and the core
library (ATALAIA_CORE_LIB, or a build folder of the repository).
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "controller"))

import yaml  # noqa: E402

from atalaia_controller.scenarios import ManifestError, load  # noqa: E402
from atalaia_controller.scenarios.package import compile_package  # noqa: E402

OUT = REPO / "protocol" / "vectors" / "scenario_compile.json"
SHARED = REPO / "protocol" / "vectors" / "scenario.json"
EXAMPLES = REPO / "controller" / "tests" / "scenarios"

DESCRIPTION = (
    "Golden outputs of the scenario compiler (ADR-P4-6 as amended, decisions P4R7, P4R8, P4R9), "
    "written by tools/scenario_compile_vectors.py with the scenario compiler of the C core "
    "(core/scenario/, decision PE24-109; first with the Pi's Python one, whose outputs these are byte "
    "for byte) and the Pi's PyYAML reader (controller/atalaia_controller/scenarios). 'compile' lists manifests: the valid ones "
    "of protocol/vectors/scenario.json (as JSON text), controller/tests/scenarios/*.yaml and cases "
    "written in the tool. Each has its name and manifest_text; 'manifest_error' true when the "
    "loader refuses the text (then nothing else); otherwise 'problems', every problem validate() "
    "gives, in its order, as path, code and level (the messages are free text); and when there is "
    "no error, the compiled package: field_lua and mode_yaml (the files' full text, which another "
    "implementation must give byte for byte) and mode_yaml_data (mode.yaml read back with "
    "yaml.safe_load, as JSON). 'loads' lists YAML texts and what the manifest loader reads from "
    "them, or 'error' true when it refuses one: values are typed, as {\"str\": s}, {\"int\": "
    "decimal text}, {\"float\": Python's repr}, {\"bool\": b}, {\"null\": null}, {\"timestamp\": "
    "Python's str of the date or datetime}, {\"list\": [values]} and {\"map\": [[key, value], ...]} "
    "in the map's order. Read by app/test/controller/scenarios_test.dart (the Android field "
    "controller's reader and its calls into the core) and checked for staleness by "
    "controller/tests/test_scenario_compile_vectors.py."
)

# Every objective type, parameter and effect, translations, parameters, squads, levels, lang en.
EVERY_TYPE = """\
id: org.club.every-type
version: 2.0.1
name: Every type
description: |
  A description on two lines; the first runs on and on, well past the hundred columns of mode.yaml, so that it folds.
  The second has "quotes", 'apostrophes', a colon: here, and a # hash.
author: The GM's team
lang: en
teams: [red, blue, green]
squads: 3
params:
  bonus: { type: int, min: 0, max: 500, default: 25, label: "Bonus points", gm_only: true }
  extra: { type: int, default: 0 }
  plain: { type: int, min: 5, max: 5, default: 5, label: null }
i18n:
  pt:
    name: Todos os tipos
    description: Uma descrição em português, com acentuação e cedilhas.
    params: { bonus: Pontos extra, extra: Mais }
nodes:
  alpha: { role: objective, level: 2 }
  bravo: { role: objective, level: 0 }
  charlie: { role: objective, level: null }
  delta: { role: objective }
  site: { role: bomb_site }
  vip: { player: true, role: vip }
  courier: { player: true }
objectives:
  - id: hill
    type: capture_and_hold
    name: Hill
    description: Hold it.
    i18n: { pt: { name: Colina, description: Segura-a. } }
    target: alpha
    assignee: { team: red, squad: 2 }
    params: { hold_ms: 3000, duration_s: 120 }
    time_window: { start_min: 5, end_min: 60 }
    effect: { points: { param: bonus }, win: false }
  - id: vault
    type: enter_code
    name: Vault
    target: bravo
    assignee: { team: blue }
    params: { code: "0815" }
    visibility: hidden
    depends_on: [hill]
    effect: { points: 100, reveal: [intel] }
  - id: intel
    type: scan_tags
    name: Intel
    target: charlie
    params: { tag_count: 3, any: true }
    visibility: hidden
    effect: { points: 0 }
  - id: rescue
    type: escort
    name: Rescue
    target: vip
    assignee: { team: red, squad: 1 }
    visibility: squad
    params:
      destination: { lat: 38, lon: -9.1393, radius_m: 25 }
      max_acc_m: 40
    effect: { points: 75, reveal: [extract] }
  - id: extract
    type: escort
    name: Extract
    target: vip
    assignee: { team: red }
    visibility: hidden
    params:
      destination: { points: [[38.7, -9.1], [38.7001, -9.1], [38.7001, -9.0999], [38, -9]] }
  - id: courier_run
    type: escort
    name: Courier
    target: courier
    params: { destination: { lat: -45.5, lon: 179.99999, radius_m: 12.5 } }
  - id: sabotage
    type: destroy
    name: Bomb
    target: site
    params: { hold_ms: 500, defuse_ms: 700, fuse_s: 60 }
    depends_on: [vault, intel]
    effect: { points: 30, win: true }
  - id: hq
    type: defend
    name: HQ
    target: delta
    assignee: { team: blue }
    visibility: team
    params: { duration_s: 2700, hold_ms: 0 }
    effect: { points: 60 }
  - id: last_stand
    type: survive
    name: Last stand
    assignee: { team: green }
    params: { minimum_lives: 5 }
    time_window: { end_min: 90 }
    effect: { points: { param: extra } }
"""

# Texts a GM may write: quotes, Lua and YAML syntax, Unicode, control characters in descriptions.
HOSTILE = r"""
id: org.club.hostile-texts
version: "1.0"
name: 'Pon"te]] os.exit(1) --[[ \'
description: "Tab\there, escape \e, bell \a, NUL \0, NEL \N, LS \L, PS \P, nbsp \_, BOM \uFEFF, RLO \u202E, private \uE000, astral \U0001F600, unassigned \U000E0080, end with spaces  "
author: "Ana Conceição 🚀 — 東京 עברית"
lang: pt
teams: ['r"ed', "it's", "yes", "null", "1", "~", "- x", "a: b"]
nodes:
  "al\"pha]]": { role: objective }
  "box #1": { role: objective }
  "? q": { role: objective }
  "[x]": { role: objective }
  "&z *w !t": { role: objective }
  "@q `r %p": { role: objective }
  "Ponte São João": { role: objective }
  "null": { role: objective }
  "2026-10-23": { role: bomb_site }
objectives:
  - id: bridge
    name: 'Pon"te]] os.exit(1) --[[ \'
    description: |
      line one ]] --[[
        indented line two, with trailing spaces
      line three
    type: capture_and_hold
    target: 'al"pha]]'
    assignee: { team: 'r"ed' }
    effect: { points: 7 }
  - id: hash
    name: "a # not a comment: really"
    description: "  leading spaces, and a final newline\n"
    type: capture_and_hold
    target: "box #1"
    assignee: { team: "it's" }
  - id: query
    name: "?"
    description: "-"
    type: enter_code
    target: "? q"
    params: { code: "00000001" }
    assignee: { team: "yes" }
  - id: brackets
    name: "Café ﷺ ∑ ½ ⅷ € ✓ 𝔘 ⃝"
    description: "e\u0301 combining, ﬁ ligature, ǅ titlecase, ʰ modifier, 〇 ideograph"
    type: scan_tags
    target: "[x]"
    params: { tag_count: 100 }
    assignee: { team: "null" }
  - id: amp
    name: "x\u00a0nbsp \u3000 ideographic space"
    type: capture_and_hold
    target: "&z *w !t"
    assignee: { team: "1" }
  - id: at
    name: "\uE000 private and \U000E0080 unassigned"
    type: capture_and_hold
    target: "@q `r %p"
    assignee: { team: "~" }
  - id: ponte
    name: "true"
    i18n: { pt: { name: "1.5" } }
    type: capture_and_hold
    target: "Ponte São João"
    assignee: { team: "- x" }
  - id: nulls
    name: "null"
    i18n: { pt: { name: "'quoted'" } }
    type: capture_and_hold
    target: "null"
    assignee: { team: "a: b" }
  - id: datebox
    name: "2026-10-23"
    i18n: { pt: { name: '"double"' } }
    type: destroy
    target: "2026-10-23"
"""

# Long texts: plain, single-quoted and double-quoted scalars folded at mode.yaml's width.
LONG_TEXTS = r"""
id: org.club.long-texts
version: 3
name: Long texts
description: "This description is a single line of plain words that runs on well past the one hundred columns of the width, and on, and on, until it has to fold twice over at least, which it does here."
author: "  Leading spaces: single-quoted"
teams: [red, blue]
nodes:
  a: { role: objective }
  b: { role: objective }
  c: { role: objective }
  d: { role: objective }
  e: { role: objective }
objectives:
  - id: one
    name: One
    description: "A backslash \\ and a tab\t make this double-quoted, and it is long enough to fold past the hundred columns, twice over even, so: there."
    type: capture_and_hold
    target: a
  - id: two
    name: Two
    description: "Averyveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryveryverylongword then words"
    type: capture_and_hold
    target: b
  - id: three
    name: Three
    description: "Many    spaces    between    words    that    run    past    the    width    of    the    line    so    that    it    folds    here"
    type: capture_and_hold
    target: c
  - id: four
    name: Four
    description: "Ünïcödé wörds öf twö bytes each, Ünïcödé wörds öf twö bytes each, Ünïcödé wörds öf twö bytes each, folded by code points"
    type: capture_and_hold
    target: d
  - id: five
    name: Five
    description: "  Leading spaces make this single-quoted, and it is long enough to fold past the hundred columns of the width, and it's got an apostrophe too."
    type: capture_and_hold
    target: e
"""

# YAML 1.1 as PyYAML reads it: yes/on are true, 0815 is text, 0x10 and 1:30 are numbers, merge keys.
YAML11 = """
id: org.club.yaml-eleven
version: 1.10
name: YAML 1.1
teams: [red, blue]
nodes:
  alpha: &objective { role: objective }
  bravo: *objective
  charlie: { <<: *objective, level: 1 }
  site: { role: bomb_site }
  vip: { player: yes, role: vip }
params:
  bonus: { type: int, default: 1_0, gm_only: off }
objectives:
  - id: hill
    name: Hill
    type: capture_and_hold
    target: alpha
    params: { hold_ms: 0x10, duration_s: 1:30 }
    effect: &shared { points: { param: bonus }, win: on }
  - id: vault
    name: Vault
    type: enter_code
    target: bravo
    params: { code: 0815 }
    effect: *shared
  - id: intel
    name: Intel
    type: scan_tags
    target: charlie
    params: { tag_count: 0b11, any: yes }
    time_window: { start_min: 010, end_min: ~ }
  - id: sabotage
    name: Sabotage
    type: destroy
    target: site
    params: { fuse_s: 1:00 }
    effect: { points: +5 }
  - id: rescue
    name: Rescue
    type: escort
    target: vip
    params: { destination: { lat: 1.5e+1, lon: .5, radius_m: 1_0.5 } }
"""

# Floats as Python writes them in field.lua (repr): exponents, -0.0, the shortest round trip.
FLOATS = """
id: org.club.floats
version: 123456789012345678901234567890
name: Floats
teams: [red]
nodes:
  vip: { player: true }
objectives:
  - id: tiny
    name: Tiny
    type: escort
    target: vip
    params: { destination: { lat: 0.00001, lon: -0.0, radius_m: 0.0001 } }
  - id: near
    name: Near
    type: escort
    target: vip
    params: { destination: { lat: 0.0001, lon: 1.0000000000000002, radius_m: 9999.999999999998 } }
  - id: polygon
    name: Polygon
    type: escort
    target: vip
    params:
      destination:
        points: [[0.1, 0.2], [0.30000000000000004, 0.2], [0.3, 1.0e-7], [89.99999999999999, -179.99999999999997], [1.5e-5, 0]]
      max_acc_m: 1000
"""

# Python's re "$" also matches before a final newline: ids that end with one pass, as in Python.
TRAILING_NEWLINE = """
id: "org.club.trailing\\n"
version: "1"
name: Trailing newline
teams: [red]
nodes:
  a: { role: objective }
objectives:
  - id: "hill\\n"
    name: Hill
    type: enter_code
    target: a
    params: { code: "1234\\n" }
"""

# Characters past U+FFFF as JSON writes them when it keeps to ASCII: two escapes, a surrogate pair,
# which PyYAML reads as two code points and the loader joins (decision PE24-107).
SURROGATE_PAIRS = json.dumps({
    "id": "org.club.emoji", "version": "1", "name": "Ponte \U0001f309", "lang": "en",
    "description": "\U0001f4a3 and \u00e9", "teams": ["red", "blue"], "nodes": {"a": {"role": "objective"}},
    "objectives": [{"id": "hill", "name": "Hill \U0001f600", "type": "capture_and_hold", "target": "a"}],
}, indent=2)
assert "\\ud83c\\udf09" in SURROGATE_PAIRS

# The same escapes where YAML does not read escapes (a plain and a single-quoted text) and where it
# does, in one text: only the double-quoted ones are characters.
SURROGATE_PAIRS_YAML = """\
id: org.club.emoji-yaml
version: '1'
name: "Ponte \\ud83c\\udf09 \\U0000D83D\\U0000DE00 \\ud83d\\
  \\ude00"
description: plain \\ud83c\\udf09 text
author: 'single \\ud83c\\udf09'
nodes: { a: { role: objective } }
objectives:
  - { id: hill, name: "\\\\ud83d\\U0001F600", type: capture_and_hold, target: a }
"""

JSON_TEXT = json.dumps({
    "id": "org.club.json", "version": 1.0, "name": "JSON", "lang": "en", "teams": ["red", "blue"],
    "nodes": {"a": {"role": "objective"}, "b": {"role": "bomb_site"}},
    "objectives": [
        {"id": "hill", "name": "Hill", "type": "capture_and_hold", "target": "a", "assignee": {"team": "red"},
         "time_window": {"start_min": 0, "end_min": 30}, "effect": {"points": 10, "win": True}},
        {"id": "bomb", "name": "Bomb", "type": "destroy", "target": "b", "depends_on": ["hill"]},
    ],
}, indent=2, ensure_ascii=False)

# Manifests with errors, some of which depend on how the text is read.
INVALID = [
    ("A scenario id too long for any event",
     f"id: org.{'a' * 196}\nversion: 1\nname: Long\nnodes: {{a: {{role: objective}}}}\n"
     "objectives:\n  - { id: hill, name: Hill, type: capture_and_hold, target: a }\n"
     "  - { id: vale, name: Vale, type: survive, assignee: { team: red }, params: { minimum_lives: 1 }, "
     "time_window: { end_min: 1 } }\n"),
    ("YAML 1.1 readings that are errors",
     "id: org.club.errors\nversion: 2026-10-23\nname: Errors\n"
     "teams: [red, no]\ndescription: 2026-10-23 10:00:00\nnodes:\n  yes: { role: objective }\n"
     "  a: { role: objective }\n"
     "objectives:\n  - id: hill\n    name: Hill\n    on: 1\n    type: enter_code\n    target: a\n"
     "    params: { code: 0755 }\n    time_window: { start_min: 1:30.5 }\n"),
    ("Values of the wrong kind everywhere",
     "id: [org.club.x]\nversion: 1.5\nname: {a: 1}\nlang: 5\nsquads: 1.0\n"
     "params: { 1: { type: int }, p: { type: int, min: 3, max: 1, default: 2 }, "
     "q: { type: int, default: 9, gm_only: 1 } }\n"
     "i18n: { pt: { params: { nope: x } }, en: { name: x } }\n"
     "nodes: { 7: { role: objective }, a: [1], b: { role: objective, level: 10 }, c: { player: 1 } }\n"
     "objectives:\n  - 1\n"
     "  - { id: 2, name: '', type: [], visibility: none, depends_on: x, time_window: [], effect: [] }\n"
     "  - { id: a, name: A, type: escort, target: c, "
     "params: { destination: { points: [[0, 0], [1, 1], [1, 0], [0, 1]] }, x: 1 } }\n"
     "  - { id: b, name: B, type: escort, target: b, "
     "params: { destination: { lat: .nan, lon: .inf, radius_m: -1 } } }\n"
     "  - { id: c, name: C, type: defend, target: a, assignee: { team: red, squad: 1 }, "
     "params: { duration_s: true } }\n"
     "  - { id: d, name: D, type: survive, depends_on: [d, e, e, 1], "
     "effect: { points: { param: p, x: 1 }, win: 1, reveal: 1 } }\n"
     "  - { id: e, name: E, type: capture_and_hold, target: a, depends_on: [d], "
     "time_window: { start_min: 5, end_min: 5 } }\n"),
    ("A setup over a box's command in English, with Unicode",
     "id: org.club.big\nversion: 1\nname: Big\nlang: en\n"
     "teams: [abcdefghijklmnopqrstuvw, b]\nnodes: { a: { role: bomb_site } }\nobjectives:\n"
     "  - { id: a, name: 'Ç日本語のテキストは長いですね本当に', type: destroy, target: a, assignee: { team: b }, "
     "params: { hold_ms: 600000, defuse_ms: 600000, fuse_s: 3600 } }\n"),
    ("Not a manifest: a key twice", "id: a\nname: x\nid: b\n"),
    ("Not a manifest: yes and true are one key", "nodes:\n  yes: { role: objective }\n  true: { role: objective }\n"),
    ("Not a manifest: a merge key overridden",
     "nodes:\n  a: &a { role: objective }\n  b: { <<: *a, role: bomb_site }\n"),
    ("Not a manifest: a list", "- id: org.club.list\n"),
    ("Not a manifest: a value '='", "id: =\n"),
    ("Not a manifest: half of a surrogate pair, as an escape (PE24-107)",
     SURROGATE_PAIRS.replace("\\ud83c\\udf09", "\\ud83c", 1)),
    ("Not a manifest: a low surrogate before the high one", SURROGATE_PAIRS.replace("\\ud83c\\udf09", "\\udf09\\ud83c", 1)),
]

LOADS = [
    "a: [yes, Yes, YES, no, No, NO, on, On, ON, off, Off, OFF, true, True, TRUE, false, False, FALSE, y, n, yEs]",
    "a: [0815, 0755, 010, 00, 0, -0, +12, 1_000, 0x1F, 0x_1f, -0b101, 0b, 0x, 0o17, 1:30, -1:30, 190:20:30, "
    "1:70]",
    "a: [99999999999999999999, -9223372036854775808, 9223372036854775807, 9223372036854775808]",
    "a: [1.5, 1., .5, -.5, 1e5, 1.0e5, 1.0e+5, 1.e+5, 6.8523015e+5, 685.230_15e+03, 190:20:30.15, 1_0.5, "
    "1.2.3, ..5]",
    "a: [.inf, -.Inf, +.INF, .nan, .NaN, 1.0e+400, 0.1, 100.0, 1e16, 1.0e+16, 1234567890123456.0]",
    "a: [~, null, Null, NULL, nULL, '', \"\", None]",
    "{\"a\": \"\\ud83d\\ude00\", \"\\ud83d\\udca3\": [\"x\\ud83d\\ude00y\", \"\\U0001F600\"]}",
    "a: x\\ud83d\\ude00\nb: 'y\\ud83d\\ude00'\nc: \"\\\\\\\\ud83d\\\\ude00\"\nd: \"\\U0000d83d\\U0000DE00\"\n# \\ud83d\n",
    "a: \"\\\\ud83d\\ude00\"\n",
    "a: \"\\ud83d\\\n  \\ude00\"\n",
    "a: \"\\ud83d\"\n",
    "a: \"\\ude00\"\n",
    "a: [\"\\ud83d\", \"\\ude00\"]\n",
    "\"\\ud83d\\ude00\": 1\n\"\\U0001F600\": 2\n",
    "a: [2026-10-23, 2026-1-2, 2026-10-23 10:00:00, 2026-10-23T10:00:00Z, 2026-10-23t10:00:00.5+01:30, "
    "2026-1-2 3:04:05 -5, 2026-10-23T10:00:00.1234567]",
    "yes: 1\nno: 2\n3: 3\n1.5: 4\n~: 5\n2026-10-23: 6\n=: 8\n",
    "a: !!str yes\nb: ! 12\nc: ! \"12\"\nd: !!str\ne: !!int 0o17\nf: !!float 10\ng: !!null ~\nh: !!int 010\n",
    "a: &x {p: 1}\nb: {<<: *x, q: 2}\nc: &y {r: 1}\nd: {<<: [*x, *y], s: 3}\ne: [*x, *x]\n",
    "a: \"\\x01 \\e \\N \\L \\P \\_ \\t \\u00e9 \\U0001F600\"\nb: 'it''s'\n"
    "c: |\n  x\n   y\nd: >-\n  folded\n  lines\n\n  kept\n"
    "e: plain\n  continued\n",
    "{\"id\": \"org.club.json\", \"version\": 1, \"n\": [1, 1.0, true, null, \"x\"]}",
    "\ufeffa: 1\n",
    "a: 1 \u3000\nb: [2\u00a0, 3]\nc: true\u2003\n",
    "a: x # comment\nb: 'x # not'\n",
    "a: \"tab\tin quotes\"\n",
    "a: x\ty\n",
    "a: 1\t# c\n",
    "a: 1 # c\td\n# x\ty\nb: |\n  x\ty\n",
    "a:\t1\n",
    "{\"a\":\t1}\n",
    "a:\n  - 1\t\n",
    "a: 1\n---\nb: 2\n",
    "a: \x7f\n",
    "a: x\u2028y\n",
    "? [a]\n: 1\n",
    "a: =\n",
    "a: <<\n",
    "a: !!python/object/apply:os.system ['true']\n",
    "a: 2026-13-45\n",
    "a: 1\na: 2\n",
    "1: a\n1.0: b\n",
    "yes: a\n1: b\n",
    "a: {p: 1}\nb: {<<: {p: 2}, p: 3}\n",
]


def typed(value: Any) -> Any:
    """A value as the 'loads' cases write it: typed, so that 1, 1.0, True and '1' stay apart."""
    if isinstance(value, bool):
        return {"bool": value}
    if isinstance(value, int):
        return {"int": str(value)}
    if isinstance(value, float):
        return {"float": repr(value)}
    if isinstance(value, str):
        return {"str": value}
    if value is None:
        return {"null": None}
    if isinstance(value, (datetime.date, datetime.datetime)):
        return {"timestamp": str(value)}
    if isinstance(value, list):
        return {"list": [typed(v) for v in value]}
    if isinstance(value, dict):
        return {"map": [[typed(k), typed(v)] for k, v in value.items()]}
    raise TypeError(f"no typed form for {type(value).__name__}")


def compile_case(name: str, text: str) -> dict[str, Any]:
    case: dict[str, Any] = {"name": name, "manifest_text": text}
    try:
        manifest = load(text)
    except ManifestError:
        case["manifest_error"] = True
        return case
    problems, package = compile_package(manifest)
    case["problems"] = [{"path": p.path, "code": p.code, "level": p.level} for p in problems]
    if package is not None:
        case["field_lua"] = package.field_lua
        case["mode_yaml"] = package.mode_yaml
        case["mode_yaml_data"] = yaml.safe_load(package.mode_yaml)
    return case


def load_case(text: str) -> dict[str, Any]:
    try:
        return {"text": text, "data": typed(load(text))}
    except (ManifestError, ValueError):  # a date like 2026-13-45 is a ValueError in PyYAML
        return {"text": text, "error": True}


def build_vectors() -> dict[str, Any]:
    shared = json.loads(SHARED.read_text(encoding="utf-8"))
    cases = [compile_case(f"scenario.json: {c['name']}", json.dumps(c["manifest"], indent=1, ensure_ascii=False))
             for c in shared["valid"]]
    cases += [compile_case(f"controller/tests/scenarios/{p.name}", p.read_text(encoding="utf-8"))
              for p in sorted(EXAMPLES.glob("*.yaml"))]
    cases += [compile_case(name, text) for name, text in [
        ("Every objective type, parameter and effect", EVERY_TYPE),
        ("Hostile texts: quotes, Lua and YAML syntax, Unicode and control characters", HOSTILE),
        ("Long texts folded at mode.yaml's width", LONG_TEXTS),
        ("YAML 1.1 readings, merge keys and a shared effect", YAML11),
        ("Floats in field.lua and a version of 30 digits", FLOATS),
        ("Ids and a code that end with a newline: refused (Python's re $ took them before PE24-106)",
         TRAILING_NEWLINE),
        ("A manifest in JSON", JSON_TEXT),
        ("Emoji written as surrogate-pair escapes, as JSON with ensure_ascii writes them (PE24-107)",
         SURROGATE_PAIRS),
        ("Surrogate-pair escapes in double-quoted, plain and single-quoted YAML texts", SURROGATE_PAIRS_YAML),
    ]]
    cases += [compile_case(name, text) for name, text in INVALID]
    return {"description": DESCRIPTION, "compile": cases, "loads": [load_case(t) for t in LOADS]}


def outputs() -> dict[Path, str]:
    # The manifests and packages carry SPDX lines; written "SPDX\u002d" (the same JSON string), so
    # that REUSE does not read them as this file's licence (the protocol's, from REUSE.toml).
    vectors = json.dumps(build_vectors(), indent=1, ensure_ascii=False).replace("SPDX-", "SPDX\\u002d")
    return {OUT: vectors + "\n"}


def check() -> list[str]:
    """The files that are stale (empty when all are current)."""
    return [str(path.relative_to(REPO)) for path, text in outputs().items()
            if not path.exists() or path.read_text(encoding="utf-8") != text]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if a file is stale")
    args = ap.parse_args()
    if args.check:
        stale = check()
        for path in stale:
            print(f"{path} is stale: run python3 tools/scenario_compile_vectors.py", file=sys.stderr)
        return 1 if stale else 0
    for path, text in outputs().items():
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
