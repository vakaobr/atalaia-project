# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""VIP / Payload (modes/vip_payload) beyond its YAML tests: positions reach field.lua only, no
event may carry a position, a malformed extraction zone stops the field script from loading,
and the gm_only parameters and event data of the schema (decision M5-1).

    cd simulator && python -m unittest discover -s tests
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from atalaia_sim.core import Core, find_library
from atalaia_sim.mode import compose, load_mode
from atalaia_sim.protocol import EVENTS
from atalaia_sim.sim import CONTROLLER, SimError, Simulation, coordinate_keys

MODES = Path(__file__).resolve().parents[2] / "modes"
TEAMS = ["red", "blue"]
ZONE = "38.722345,-9.139312"


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and CORE is None:
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the shared core library is not built")


class SchemaTests(unittest.TestCase):
    def test_vip_extracted_is_46_and_critical(self):
        self.assertEqual(EVENTS["vip.extracted"].id, 46)
        self.assertEqual(EVENTS["vip.extracted"].prio, "critical")
        self.assertEqual(EVENTS["vip.extracted"].data, ("player",))

    def test_gm_only_data_and_parameters(self):
        self.assertEqual(EVENTS["hacking.solved"].gm_only, ("code",))
        # Which objective a scenario event is about is the staff's too, until the player view
        # routes objectives per team (decision M6-5).
        self.assertEqual({n for n, e in EVENTS.items() if e.gm_only},
                         {"hacking.solved", "scenario.objective.completed", "scenario.objective.failed",
                          "scenario.objective.revealed"})
        self.assertEqual(EVENTS["scenario.objective.revealed"].gm_only, ("objective",))
        self.assertEqual(load_mode(MODES / "hacking_terminal").gm_only_params, {"reveal_code"})
        self.assertEqual(load_mode(MODES / "bomb").gm_only_params, {"team_codes"})
        bomb_codes = compose(load_mode(MODES / "bomb"), [load_mode(MODES / "codes")])
        self.assertEqual(bomb_codes.gm_only_params, {"team_codes", "codes"})
        self.assertEqual(bomb_codes.public_params({"fuse_s": 60, "team_codes": "red=1", "codes": "1:hint"}),
                         {"fuse_s": 60})
        self.assertEqual(load_mode(MODES / "vip_payload").gm_only_params, frozenset())

    def test_coordinate_keys(self):
        self.assertEqual(coordinate_keys({"team": "red", "player": "p-1"}), [])
        self.assertEqual(coordinate_keys({"where": {"lat": 1, "lon": 2}}), ["lat", "lon"])
        self.assertEqual(coordinate_keys({"path": [{"x": 1}]}), ["x"])


@unittest.skipIf(CORE is None, "the shared core library is not built")
class VipPayloadSimTests(unittest.TestCase):
    def sim(self, nodes, **params):
        mode = load_mode(MODES / "vip_payload")
        sim = Simulation(CORE, mode, nodes, TEAMS, mode.resolve_params(params, TEAMS))
        self.addCleanup(sim.close)
        return sim

    def test_a_position_is_never_an_event_and_never_reaches_a_node(self):
        sim = self.sim({"cp1": "checkpoint", "cargo": "payload"}, extraction=ZONE, end_on_extract=False)
        sim.start()
        sim.position("p-vip", "red", "vip", 38.723244, -9.139312, 5.0)
        sim.position("p-vip", "red", "vip", 38.722390, -9.139312, 5.0)
        self.assertEqual([(e.node, e.type, e.data) for e in sim.events if e.type == "vip.extracted"],
                         [(CONTROLLER, "vip.extracted", {"team": "red", "player": "p-vip"})])
        for vnode in sim.nodes.values():
            self.assertIsNone(vnode.last_input)  # no node got anything
        self.assertEqual(sim.problems, [])
        for e in sim.events:
            self.assertEqual(coordinate_keys(e.data), [], e.describe())

    def test_a_position_without_a_field_script_is_refused(self):
        mode = load_mode(MODES / "domination")
        sim = Simulation(CORE, mode, {"z": "zone"}, TEAMS, mode.resolve_params({}, TEAMS))
        self.addCleanup(sim.close)
        with self.assertRaises(SimError):
            sim.position("p-1", "red", "vip", 38.7, -9.1)

    def test_an_event_with_a_position_is_a_problem(self):
        sim = self.sim({"cp1": "checkpoint"})
        sim.start()
        sim._record_field(type("E", (), {"type": "x.club.where", "team": 1, "prio": "normal", "t_ms": 0,
                                         "data": {"lat": 38.7, "lon": -9.1}})())
        self.assertTrue(any("carries a position (lat, lon)" in p for p in sim.problems), sim.problems)

    def test_a_malformed_extraction_zone_stops_field_lua(self):
        for bad in ("38.7", "north,south", "91,0", "38.7,-181", "38.7;-9.1"):
            with self.subTest(bad), self.assertRaisesRegex(SimError, "extraction: latitude,longitude"):
                self.sim({"cp1": "checkpoint"}, extraction=bad)
        # Spaces and an explicit sign are fine, as map apps copy them.
        self.sim({"cp1": "checkpoint"}, extraction=" +38.722345, -9.139312 ")

    def test_the_join_parameters_fit(self):
        from atalaia_sim.join import PARAMS_MAX, params_json

        mode = load_mode(MODES / "vip_payload")
        params = mode.resolve_params({"vip_team": "orange", "extraction": "-38.7223456, -109.1393123",
                                      "radius_m": 1000, "vip_points": 1000, "checkpoint_points": 1000,
                                      "tick_s": 600, "capture_hold_ms": 60000, "end_on_extract": False},
                                     ["orange", "purple"])
        self.assertLessEqual(len(params_json(params).encode()), PARAMS_MAX)


class ScreenLanguageTests(unittest.TestCase):
    """The screens follow the box's language, data `lang`, like the other modes' (decision TFT-9),
    whatever the old `lang` parameter says."""

    @staticmethod
    def _texts(name):
        import yaml

        doc = yaml.safe_load((MODES / "vip_payload" / "assets" / "screens" / f"{name}.yaml")
                             .read_text(encoding="utf-8"))
        found = []

        def walk(node):
            if isinstance(node, dict):
                if isinstance(node.get("text"), str) and "lang" in node["text"]:
                    found.append(node["text"])
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(doc)
        return found

    @unittest.skipIf(CORE is None, "needs the shared core library")
    def test_every_text_follows_the_box_language_and_ignores_the_parameter(self):
        data = {"team": "red", "since": 95, "age": 130, "live": 1, "metres": 40}
        params = {"capture_hold_ms": 3000, "lang": "en"}  # a game saved with an old lang
        seen = {}
        for name in ("checkpoint_free", "checkpoint_held", "payload"):
            texts = self._texts(name)
            self.assertTrue(texts, name)
            for text in texts:
                self.assertNotIn("params.lang", text)
                for lang in ("pt", "en", "de", "zh-tw"):
                    with self.subTest(name, text=text[:40], lang=lang):
                        got = CORE.screen_text(text, dict(data, lang=lang), params)
                        self.assertTrue(got.strip(), "an empty text: literals over the scratch?")
                        seen.setdefault((name, text), set()).add(got)
        # The words differ by language (a word like "PAYLOAD" is shared by en and de only).
        for (name, text), outs in seen.items():
            self.assertGreaterEqual(len(outs), 2, (name, text))

    @unittest.skipIf(CORE is None, "needs the shared core library")
    def test_the_held_checkpoint_reads_in_each_language(self):
        (live,) = [t for t in self._texts("checkpoint_held") if "age|clock" in t]
        want = {"pt": "capturado há 2:10", "en": "held 2:10", "de": "gehalten seit 2:10",
                "zh-tw": "已佔領 2:10"}
        for lang, text in want.items():
            with self.subTest(lang):
                self.assertEqual(CORE.screen_text(live, {"lang": lang, "age": 130, "live": 1},
                                                  {"lang": "pt"}), text)
        # No language given (a box that has none): English.
        self.assertEqual(CORE.screen_text(live, {"age": 130, "live": 1}, {"lang": "pt"}), "held 2:10")


if __name__ == "__main__":
    unittest.main()
