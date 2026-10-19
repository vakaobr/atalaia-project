# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""geo.distance() and geo.in_zone() from Lua, through the ctypes bindings (ADR-P4-9).

    cd simulator && python -m unittest discover -s tests

Runs every vector of protocol/vectors/geo.json in the shared core library, as
core/tests/test_geo.c does in C: known answers within their tolerance (the
values come from the sources the vectors cite, not from the core) and the
exact bits of every distance (the determinism pins, decision M3-1). Numbers
cross into Lua as hexadecimal float literals and come back with %a, so no
digit is lost on the way.
"""

from __future__ import annotations

import json
import math
import os
import struct
import unittest
from pathlib import Path

from atalaia_sim.core import Core, Node, find_library

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "geo.json")
                     .read_text(encoding="utf-8"))


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()
if os.environ.get("ATALAIA_REQUIRE_ALL") == "1" and CORE is None:
    raise ImportError("ATALAIA_REQUIRE_ALL=1 but the shared core library is not built")


def run(body: str) -> tuple[list[str], list[dict]]:
    """Runs body in a handler of a node script; returns its logs and script errors."""
    logs: list[str] = []
    errors: list[dict] = []
    src = f"on('go', function()\n{body}\nend)\n"
    node = Node(CORE, 3, 1, ["red", "blue"], {}, src, "=test", instr_limit=200000,
                on_log=logs.append,
                on_event=lambda e: errors.append(e.data) if e.type == "script.error" else None)
    try:
        assert node.loaded, node.last_error
        assert node.input("go")
        assert node.status == "running", node.status
    finally:
        node.close()
    return logs, errors


def bits(x: float) -> str:
    return f"0x{struct.unpack('>Q', struct.pack('>d', x))[0]:016x}"


@unittest.skipIf(CORE is None, "shared core library not built")
class GeoTests(unittest.TestCase):
    def test_distances(self):
        for v in VECTORS["distances"]:
            with self.subTest(v["name"]):
                (a_lat, a_lon), (b_lat, b_lon) = v["a"], v["b"]
                logs, errors = run(
                    f"log(string.format('%a', geo.distance({a_lat.hex()}, {a_lon.hex()}, "
                    f"{b_lat.hex()}, {b_lon.hex()})),\n"
                    f"    string.format('%a', geo.distance({b_lat.hex()}, {b_lon.hex()}, "
                    f"{a_lat.hex()}, {a_lon.hex()})))")
                self.assertEqual(errors, [])
                self.assertEqual(len(logs), 1)
                there, back = (float.fromhex(s) for s in logs[0].split())
                if "metres" in v:
                    self.assertLessEqual(abs(there - v["metres"]), v["tolerance_m"])
                self.assertEqual(bits(there), v["bits"])
                self.assertEqual(bits(back), v["bits"])

    def test_zones(self):
        for v in VECTORS["zones"]:
            with self.subTest(v["name"]):
                z = v["zone"]
                if z["type"] == "circle":
                    zone = (f"{{ type = 'circle', lat = {float(z['lat']).hex()}, "
                            f"lon = {float(z['lon']).hex()}, radius_m = {float(z['radius_m']).hex()} }}")
                else:
                    points = ", ".join(f"{{{float(p[0]).hex()}, {float(p[1]).hex()}}}" for p in z["points"])
                    zone = f"{{ type = 'polygon', points = {{ {points} }} }}"
                lat, lon = v["point"]
                logs, errors = run(f"log(geo.in_zone({float(lat).hex()}, {float(lon).hex()}, {zone}))")
                self.assertEqual(errors, [])
                self.assertEqual(logs, ["true" if v["inside"] else "false"])

    def test_argument_errors_are_script_errors(self):
        for v in VECTORS["errors"]:
            with self.subTest(v["name"]):
                logs, errors = run(v["script"])
                self.assertEqual(len(errors), 1)
                self.assertIn(v["message"], json.dumps(errors[0], ensure_ascii=False))

    def test_vectors_cite_their_sources(self):
        """Every known answer names where it comes from; pins say they are pins."""
        for v in VECTORS["distances"] + VECTORS["zones"]:
            with self.subTest(v["name"]):
                self.assertTrue(v["source"])
                if "metres" not in v and "inside" not in v:
                    self.assertTrue(v["source"].startswith("determinism pin"))
        self.assertTrue(any("rosettacode.org" in v["source"] for v in VECTORS["distances"]))
        self.assertTrue(any("geographiclib" in v["source"].lower() for v in VECTORS["distances"]))

    def test_haversine_from_the_formula(self):
        """A second, independent check of the known answers: the textbook haversine with
        Python's math library, which matches the core to about 1e-9 relative (math.sin and
        math.cos differ from the core's polynomials in the last bits, so not exactly)."""
        r = VECTORS["radius_m"]
        for v in VECTORS["distances"]:
            if "metres" not in v or v["name"].startswith("antipodes") or v["metres"] < 1000:
                continue
            with self.subTest(v["name"]):
                (p1, l1), (p2, l2) = (map(math.radians, v["a"]), map(math.radians, v["b"]))
                h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
                d = 2 * r * math.asin(math.sqrt(h))
                core = struct.unpack(">d", bytes.fromhex(v["bits"][2:]))[0]
                self.assertAlmostEqual(d, core, delta=core * 1e-9)


if __name__ == "__main__":
    unittest.main()
