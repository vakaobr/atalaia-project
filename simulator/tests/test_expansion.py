# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The expansion port's protocol v1 (protocol/expansion-port.md) against protocol/vectors/expansion.json and
cmd.json's output_params, with the Python reference (atalaia_sim/expansion.py); and the capability type ids
(protocol/schema/capabilities.yaml) against the generated table and HELLO's vectors. Every vector is checked."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

import yaml

from atalaia_sim import expansion as ex
from atalaia_sim.packet import hello_decode
from atalaia_sim.protocol import CAPABILITY_TYPES, EVENTS

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "protocol" / "vectors" / "expansion.json").read_text(encoding="utf-8"))
CMD = json.loads((ROOT / "protocol" / "vectors" / "cmd.json").read_text(encoding="utf-8"))


class ConstantsTests(unittest.TestCase):
    def test_the_file_and_the_reference_agree(self) -> None:
        self.assertEqual(VECTORS["protocol_version"], ex.PROTOCOL_VERSION)
        self.assertEqual(VECTORS["magic"].encode(), ex.MAGIC)
        a = VECTORS["addresses"]
        self.assertEqual((a["first"], a["last"], a["input_default"], a["output_default"], a["most_modules"]),
                         (0x58, 0x5F, 0x58, 0x5C, 4))
        lease = VECTORS["lease"]
        self.assertEqual((lease["default_100ms"], lease["least_100ms"], lease["most_100ms"]),
                         (ex.LEASE_DEFAULT_100MS, ex.LEASE_LEAST_100MS, ex.LEASE_MOST_100MS))
        self.assertEqual(lease["relay_least_change_ms"], ex.RELAY_LEAST_CHANGE_MS)
        self.assertEqual(VECTORS["command"]["ops"], ex.OPS)
        self.assertEqual(VECTORS["command"]["modes"], ex.MODES)
        self.assertEqual(VECTORS["command"]["parameters"], ex.PARAMETERS)
        self.assertEqual(VECTORS["status"]["flags"], ex.STATUS_FLAGS)
        self.assertEqual(VECTORS["channel"]["hints"], ex.HINTS)
        for reg, length in (("ident", ex.IDENT_LEN), ("channel", ex.CHANNEL_LEN), ("status", ex.STATUS_LEN)):
            self.assertEqual(VECTORS[reg]["length"], length)

    def test_crc8(self) -> None:
        self.assertGreaterEqual(len(VECTORS["crc8"]), 7)
        for c in VECTORS["crc8"]:
            with self.subTest(c["name"]):
                self.assertEqual(ex.crc8(bytes.fromhex(c["data"])), c["crc"])
        self.assertEqual(ex.crc8(b"123456789"), 0xF4)  # CRC-8/SMBUS's check value


class ReadTests(unittest.TestCase):
    def test_ident(self) -> None:
        for v in VECTORS["ident"]["valid"]:
            with self.subTest(v["name"]):
                self.assertEqual(ex.decode_ident(bytes.fromhex(v["bytes"])), v["fields"])
                self.assertEqual(VECTORS["modules"][v["module"]]["ident"], v["fields"])
        for v in VECTORS["ident"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(ex.ExpansionError) as e:
                ex.decode_ident(bytes.fromhex(v["bytes"]))
            self.assertEqual(e.exception.reason, v["reason"], v["name"])

    def test_channel(self) -> None:
        for v in VECTORS["channel"]["valid"]:
            with self.subTest(v["name"]):
                self.assertEqual(ex.decode_channel(bytes.fromhex(v["bytes"]), v["index"]), v["fields"])
        for v in VECTORS["channel"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(ex.ExpansionError) as e:
                ex.decode_channel(bytes.fromhex(v["bytes"]), v["index"])
            self.assertEqual(e.exception.reason, v["reason"], v["name"])

    def test_status(self) -> None:
        for v in VECTORS["status"]["valid"]:
            with self.subTest(v["name"]):
                got = ex.decode_status(bytes.fromhex(v["bytes"]), v["channels"])
                self.assertEqual(got, v["fields"])
                if "t_read_ms" in v:
                    self.assertEqual(ex.event_time(v["t_read_ms"], got["event"]["age_ms"]), v["t_event_ms"])
        for v in VECTORS["status"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(ex.ExpansionError) as e:
                ex.decode_status(bytes.fromhex(v["bytes"]), v["channels"])
            self.assertEqual(e.exception.reason, v["reason"], v["name"])


class CommandTests(unittest.TestCase):
    def test_the_box_writes_these_bytes_and_the_module_takes_them(self) -> None:
        for v in VECTORS["command"]["valid"]:
            with self.subTest(v["name"]):
                module = VECTORS["modules"][v["module"]]
                self.assertEqual(v["address"], module["address"])
                frame = bytes.fromhex(v["bytes"])
                self.assertEqual(ex.encode_command(v["fields"], v["address"]), frame)
                self.assertEqual(ex.decode_command(frame, v["address"], module["channels"]), v["fields"])
                self.assertTrue(3 <= len(frame) <= 11)

    def test_the_module_refuses_these(self) -> None:
        for v in VECTORS["command"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(ex.ExpansionError) as e:
                ex.decode_command(bytes.fromhex(v["bytes"]), v["address"],
                                  VECTORS["modules"][v["module"]]["channels"])
            self.assertEqual(e.exception.reason, v["reason"], v["name"])

    def test_a_refused_write_sets_cmd_error_and_the_next_good_one_clears_it(self) -> None:
        spec = VECTORS["modules"]["out4"]
        m = ex.ModuleModel(spec)
        bad = next(v for v in VECTORS["command"]["invalid"] if v["name"] == "lease_too_long")
        self.assertFalse(m.write(0, bytes.fromhex(bad["bytes"])))
        self.assertEqual(m.state(0), (0, {"fresh", "cmd_error"}))
        self.assertTrue(m.write(1, ex.encode_command({"op": "CLEAR_FRESH"}, spec["address"])))
        self.assertEqual(m.state(1), (0, set()))


class TimelineTests(unittest.TestCase):
    def test_every_timeline(self) -> None:
        names = {t["name"] for t in VECTORS["timelines"]}
        self.assertGreaterEqual(names, {"lease_runs_out", "lost_write_repaired", "module_restart",
                                        "pulse_spanning_missed_polls", "max_on_and_min_off",
                                        "relay_pattern_floor", "relay_switches_at_most_every_100_ms"})
        for t in VECTORS["timelines"]:
            spec = VECTORS["modules"][t["module"]]
            m = ex.ModuleModel(spec)
            for j, step in enumerate(t["steps"]):
                where = f"{t['name']} step {j} at {step['t_ms']} ms"
                if "write" in step:
                    frame = bytes.fromhex(step["bytes"])
                    self.assertEqual(ex.encode_command(step["write"], spec["address"]), frame, where)
                    if step.get("delivered", True):
                        self.assertEqual(m.write(step["t_ms"], frame), step["accepted"], where)
                if step.get("restart"):
                    m.restart(step["t_ms"])
                if "expect" in step:
                    outputs, flags = m.state(step["t_ms"])
                    self.assertEqual(outputs, step["expect"]["outputs"], where)
                    self.assertEqual(sorted(flags), step["expect"]["flags"], where)


class ModulesTextTests(unittest.TestCase):
    def test_modules_text(self) -> None:
        self.assertEqual(VECTORS["modules_text"]["max_bytes"], ex.MODULES_TEXT_MAX)
        for v in VECTORS["modules_text"]["valid"]:
            with self.subTest(v["name"]):
                self.assertEqual(ex.parse_modules(v["text"]), v["modules"])
        for v in VECTORS["modules_text"]["invalid"]:
            with self.subTest(v["name"]), self.assertRaises(ValueError):
                ex.parse_modules(v["text"])

    def test_the_event_vector_parses(self) -> None:
        events = yaml.safe_load((ROOT / "protocol" / "vectors" / "events.yaml").read_text(encoding="utf-8"))
        texts = [v["event"]["data"]["modules"] for v in events["valid"]
                 if v["event"]["type"] in ("node.modules", "node.module_lost")]
        self.assertEqual(len(texts), 2)
        for text in texts:
            self.assertTrue(ex.parse_modules(text))


class OutputParamsTests(unittest.TestCase):
    def test_output_params(self) -> None:
        op = CMD["output_params"]
        for v in op["valid"]:
            with self.subTest(v["name"]):
                self.assertIsNone(ex.output_params_problem(v["params"]))
        for v in op["refused"]:
            with self.subTest(v["name"]):
                self.assertEqual(ex.output_params_problem(v["params"]), v["reason"])

    def test_every_cmd_12_vector_is_one_a_box_takes_and_fits_its_127_bytes(self) -> None:
        cmds = [v["fields"] for v in CMD["valid"] if v["fields"]["cmd"] == 12]
        self.assertEqual(len(cmds), 3)
        for c in cmds:
            self.assertIsNone(ex.output_params_problem(c["params"]))
            self.assertLessEqual(len(json.dumps(c, separators=(",", ":"))), 127)


class CapabilityTypeTests(unittest.TestCase):
    def test_the_generated_table_is_the_schema(self) -> None:
        schema = yaml.safe_load((ROOT / "protocol" / "schema" / "capabilities.yaml").read_text(encoding="utf-8"))
        self.assertEqual({k: (v["id"], bool(v.get("reserved"))) for k, v in schema["types"].items()},
                         {k: (v.id, v.reserved) for k, v in CAPABILITY_TYPES.items()})
        self.assertEqual(CAPABILITY_TYPES["hit"].id, 10)
        self.assertEqual(CAPABILITY_TYPES["output"].id, 11)
        self.assertTrue(CAPABILITY_TYPES["contact"].reserved)
        self.assertIn("feedback", schema["types"]["output"]["descriptor"])

    def test_hello_lists_type_ids(self) -> None:
        hello = json.loads((ROOT / "protocol" / "vectors" / "hello.json").read_text(encoding="utf-8"))
        by_id = {v.id: k for k, v in CAPABILITY_TYPES.items()}
        v = next(v for v in hello["valid"] if v["name"] == "hello_box_capability_ids")
        names = [by_id[i] for i in hello_decode(bytes.fromhex(v["cbor"]))["capabilities"]]
        self.assertEqual(names, ["button", "keypad", "display", "led", "audio", "nfc", "hit", "output", "battery"])
        v = next(v for v in hello["valid"] if v["name"] == "hello_unknown_capability_id")
        self.assertEqual([by_id.get(i) for i in hello_decode(bytes.fromhex(v["cbor"]))["capabilities"]][-1], None)

    def test_the_new_events(self) -> None:
        self.assertEqual((EVENTS["node.modules"].id, EVENTS["node.modules"].prio, EVENTS["node.modules"].data),
                         (57, "normal", ("modules",)))
        self.assertEqual((EVENTS["node.module_lost"].id, EVENTS["node.module_lost"].prio,
                          EVENTS["node.module_lost"].data), (58, "critical", ("modules", "reason")))
        self.assertEqual((EVENTS["output.switched"].id, EVENTS["output.switched"].prio,
                          EVENTS["output.switched"].data), (59, "normal", ("capability", "ms", "source")))


if __name__ == "__main__":
    unittest.main()
