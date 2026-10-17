# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for the Python event codec and the simulator's schema checks.

    cd simulator && python -m unittest discover -s tests

The vectors in protocol/vectors/events.yaml are shared with the C codec
tests. The simulator tests at the end need the shared core library (see
the simulator README) and are skipped without it.
"""

from __future__ import annotations

import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

from atalaia_sim import cbor, codec
from atalaia_sim.core import Core, find_library
from atalaia_sim.mode import load_mode
from atalaia_sim.testing import run_test

REPO = Path(__file__).resolve().parents[2]
VECTORS = yaml.safe_load((REPO / "protocol/vectors/events.yaml").read_text(encoding="utf-8"))


class VectorTests(unittest.TestCase):
    def test_valid_vectors(self):
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                payload = bytes.fromhex(v["cbor"])
                self.assertEqual(codec.encode_event(v["event"]).hex(), payload.hex())
                expected = {"team": 0, "squad": 0, "prio": codec.default_prio(v["event"]["type"]),
                            "data": {}, **v["event"]}
                self.assertEqual(codec.decode_event(payload), expected)

    def test_invalid_vectors(self):
        for v in VECTORS["invalid"]:
            with self.subTest(v["name"]):
                with self.assertRaises(codec.CodecError):
                    codec.decode_event(bytes.fromhex(v["cbor"]))


class EncodeTests(unittest.TestCase):
    BASE = {"node": 1, "seq": 1, "t": 0, "type": "x.test.data"}

    def encode(self, **fields):
        return codec.encode_event({**self.BASE, **fields})

    def test_bad_envelopes(self):
        for fields in ({"type": ""}, {"type": "x.a b"}, {"type": "x." + "a" * 46}, {"type": 5},
                       {"node": -1}, {"node": 65536}, {"seq": 1.0}, {"t": 1 << 32}, {"team": 251},
                       {"team": True}, {"squad": 256}, {"prio": "urgent"}, {"data": []},
                       {"extra": 1}):
            with self.subTest(fields):
                with self.assertRaises(codec.CodecError):
                    self.encode(**fields)

    def test_bad_data(self):
        deep = 0
        for _ in range(16):
            deep = [deep]
        for data in ({"n": 1 << 63}, {"n": -(1 << 63) - 1}, {"f": float("nan")},
                     {"f": float("inf")}, {"m": {1: 2}}, {"b": b"x"}, {"k": deep},
                     {str(i): 0 for i in range(codec.MAX_KEYS + 1)}):
            with self.subTest(str(data)[:40]):
                with self.assertRaises(codec.CodecError):
                    self.encode(data=data)

    def test_limits_match_the_core(self):
        deep = 0
        for _ in range(15):
            deep = [deep]
        self.encode(data={"k": deep})  # 16 levels of data, like the core's JSON
        self.encode(data={str(i): 0 for i in range(codec.MAX_KEYS)})
        self.encode(data={"n": (1 << 63) - 1, "m": -(1 << 63)})

    def test_empty_data_and_default_prio_are_left_out(self):
        self.assertEqual(self.encode(data={}), self.encode())
        self.assertEqual(self.encode(prio="normal"), self.encode())
        self.assertEqual(codec.encode_event({**self.BASE, "type": "bomb.exploded", "prio": "critical"}),
                         codec.encode_event({**self.BASE, "type": "bomb.exploded"}))

    def test_float_widths(self):
        self.assertEqual(cbor.encode(1.5), bytes.fromhex("f93e00"))
        self.assertEqual(cbor.encode(65504.0), bytes.fromhex("f97bff"))
        self.assertEqual(cbor.encode(5.960464477539063e-08), bytes.fromhex("f90001"))  # smallest half
        self.assertEqual(cbor.encode(65536.0), bytes.fromhex("fa47800000"))
        self.assertEqual(cbor.encode(0.1), bytes.fromhex("fb3fb999999999999a"))


class SchemaTests(unittest.TestCase):
    def test_standard_events(self):
        self.assertEqual(codec.schema_problems("zone.captured", {"team": "red", "zone": "A"}), [])
        self.assertEqual(codec.schema_problems("game.resume", {}), [])
        [problem] = codec.schema_problems("zone.captured", {"points": 3})
        self.assertIn("no data field 'points'", problem)
        [problem] = codec.schema_problems("bomb.armed", {"fuse_s": "300"})
        self.assertIn("must be a number", problem)
        [problem] = codec.schema_problems("target.hit", {"window_open": 1})
        self.assertIn("must be a boolean", problem)

    def test_custom_events(self):
        self.assertEqual(codec.schema_problems("x.myclub.power_plant.upgraded", {"any": 1}), [])
        [problem] = codec.schema_problems("power.upgraded", {})
        self.assertIn("x.<club>.<name>", problem)
        self.assertNotEqual(codec.schema_problems("x.nodot", {}), [])


def _core():
    try:
        return Core(find_library())
    except (FileNotFoundError, OSError):
        return None


CORE = _core()


@unittest.skipIf(CORE is None, "the shared core library is not built")
class SimulatorTests(unittest.TestCase):
    """A mode whose events break the schema fails its tests."""

    def run_mode(self, emit: str) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            mode = Path(tmp)
            (mode / "mode.yaml").write_text("id: x.test.mode\nversion: 0.1.0\nroles:\n  box: {}\n",
                                            encoding="utf-8")
            (mode / "node.lua").write_text(
                f"on('team_input.press', function(e)\n  {emit}\nend)\n", encoding="utf-8")
            test = mode / "t.yaml"
            test.write_text(textwrap.dedent("""\
                name: press
                steps:
                  - press: { team: red }
                """), encoding="utf-8")
            result = run_test(CORE, load_mode(mode), test)
            return "" if result.passed else result.message

    def test_valid_events_pass(self):
        self.assertEqual(self.run_mode("emit('zone.captured', { team = e.team, zone = 'A' })"), "")
        self.assertEqual(self.run_mode("emit('x.test.ping', { anything = { 1, 2 } })"), "")

    def test_unknown_event_fails(self):
        self.assertIn("x.<club>.<name>", self.run_mode("emit('zone.exploded', {})"))

    def test_unknown_data_field_fails(self):
        self.assertIn("no data field 'points'", self.run_mode("emit('zone.captured', { points = 1 })"))

    def test_oversized_event_fails(self):
        message = self.run_mode("emit('x.test.big', { text = string.rep('a', 300) })")
        self.assertIn("LoRa payload", message)


if __name__ == "__main__":
    unittest.main()
