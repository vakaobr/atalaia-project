# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""protocol/vectors/scenario_compile.json is current: the scenario compiler's golden outputs,
which the Android field controller's Dart port (app/lib/controller/scenarios) must give byte for
byte, are what this compiler writes today (tools/scenario_compile_vectors.py --check). A change to
the compiler, the validator or runtime.lua without new vectors fails here, not only in the app.

    cd controller && python -m unittest tests.test_scenario_compile_vectors
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TOOL = REPO / "tools" / "scenario_compile_vectors.py"


def _tool():
    spec = importlib.util.spec_from_file_location("scenario_compile_vectors", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScenarioCompileVectorTests(unittest.TestCase):
    def test_the_vectors_are_current(self):
        stale = _tool().check()
        self.assertEqual(stale, [], "run python3 tools/scenario_compile_vectors.py")

    def test_every_case_is_there(self):
        vectors = json.loads((REPO / "protocol" / "vectors" / "scenario_compile.json").read_text(encoding="utf-8"))
        compiled = [c for c in vectors["compile"] if "field_lua" in c]
        self.assertGreaterEqual(len(compiled), 14)
        for case in compiled:
            self.assertFalse([p for p in case["problems"] if p["level"] == "error"], case["name"])
            self.assertTrue(case["field_lua"].startswith("-- SPDX-" "License-Identifier: GPL-3.0-or-later\n"))
        self.assertTrue(any(c.get("manifest_error") for c in vectors["compile"]))
        self.assertTrue(any(c.get("error") for c in vectors["loads"]))


if __name__ == "__main__":
    unittest.main()
