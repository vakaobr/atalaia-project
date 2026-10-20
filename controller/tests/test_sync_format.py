# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The sync bodies' checker (protocol/sync.md) against the shared vectors (protocol/vectors/sync.json).

The site server runs the same vectors through its endpoints (server/tests/test_sync.py).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import copy
import json
import unittest

from support import REPO  # noqa: F401  (puts the controller on the path)

from atalaia_controller import sync_format as fmt
from atalaia_sim.field_controller import FieldController

class NoRadio:
    def send(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return None


VECTORS = json.loads((REPO / "protocol" / "vectors" / "sync.json").read_text(encoding="utf-8"))


class VectorTests(unittest.TestCase):
    def test_counts(self) -> None:
        self.assertEqual((len(VECTORS["valid"]), len(VECTORS["invalid"]), len(VECTORS["merge"])), (14, 65, 3))
        self.assertEqual((len(VECTORS["answers"]["valid"]), len(VECTORS["answers"]["invalid"])), (9, 32))
        self.assertEqual({v["kind"] for v in VECTORS["answers"]["valid"]}, set(fmt.ANSWERS))
        self.assertEqual({v["kind"] for v in VECTORS["valid"]}, set(fmt.CHECKS))
        self.assertEqual({v["kind"] for v in VECTORS["invalid"]}, set(fmt.CHECKS))

    def test_valid(self) -> None:
        for vector in VECTORS["valid"]:
            with self.subTest(vector=vector["name"]):
                body = fmt.CHECKS[vector["kind"]](copy.deepcopy(vector["body"]))
                if "info" in vector:
                    self.assertEqual({str(n["node_id"]): n["info"] for n in body["nodes"]}, vector["info"])
                raw = json.dumps(vector["body"]).encode()
                self.assertEqual(fmt.parse(vector["kind"], raw).get("game"), vector["body"].get("game"))
                self.assertEqual("game" in vector["body"], vector["kind"] in fmt.GAME_KINDS)

    def test_invalid(self) -> None:
        for vector in VECTORS["invalid"]:
            with self.subTest(vector=vector["name"]):
                with self.assertRaises(fmt.SyncFormatError) as caught:
                    fmt.CHECKS[vector["kind"]](copy.deepcopy(vector["body"]))
                self.assertEqual((caught.exception.code, caught.exception.path), (vector["error"], vector["path"]))

    def test_answers(self) -> None:
        """The answers of the GET endpoints the controller pulls (plan phase 16)."""
        for vector in VECTORS["answers"]["valid"]:
            with self.subTest(vector=vector["name"]):
                fmt.ANSWERS[vector["kind"]](copy.deepcopy(vector["body"]))
        for vector in VECTORS["answers"]["invalid"]:
            with self.subTest(vector=vector["name"]):
                with self.assertRaises(fmt.SyncFormatError) as caught:
                    fmt.ANSWERS[vector["kind"]](copy.deepcopy(vector["body"]))
                self.assertEqual((caught.exception.code, caught.exception.path), (vector["error"], vector["path"]))

    def test_stream(self) -> None:
        """The remote GM's messages on the stream (plan phase 19): the controller's and the site server's."""
        stream = VECTORS["stream"]
        self.assertEqual((len(stream["valid"]), len(stream["invalid"])), (13, 24))
        self.assertEqual({v["kind"] for v in stream["valid"]}, set(fmt.STREAM))
        for vector in stream["valid"]:
            with self.subTest(vector=vector["name"]):
                fmt.STREAM[vector["kind"]](copy.deepcopy(vector["body"]))
        for vector in stream["invalid"]:
            with self.subTest(vector=vector["name"]):
                with self.assertRaises(fmt.SyncFormatError) as caught:
                    fmt.STREAM[vector["kind"]](copy.deepcopy(vector["body"]))
                self.assertEqual((caught.exception.code, caught.exception.path), (vector["error"], vector["path"]))

    def test_command_defaults(self) -> None:
        body = copy.deepcopy(next(v["body"] for v in VECTORS["stream"]["valid"] if v["name"] == "command_mode_every_node"))
        self.assertEqual(fmt.check_command(body)["params"], {"name": "refill", "node": 0xFFFF})
        body = copy.deepcopy(next(v["body"] for v in VECTORS["stream"]["valid"] if v["name"] == "command_end"))
        self.assertEqual(fmt.check_command(body)["params"], {"reason": ""})
        self.assertEqual(set(fmt.REMOTE_COMMANDS), {"start", "pause", "resume", "end", "message", "mode"})

    def test_merge(self) -> None:
        for case in VECTORS["merge"]:
            with self.subTest(case=case["name"]):
                counters: dict = {}
                for snapshot in case["snapshots"]:
                    counters = fmt.merge_counters(counters, snapshot)
                self.assertEqual(counters, case["counters"])
                deltas = [tuple(d) for d in case["deltas"]]
                self.assertEqual(fmt.totals(case["teams"], counters, deltas), case["totals"])

    def test_merge_is_the_controllers(self) -> None:
        """The controller's own FieldController reaches the same totals from the same reports (P4R10)."""
        for case in VECTORS["merge"]:
            with self.subTest(case=case["name"]):
                fc = FieldController(game_id=1, teams=case["teams"], node_id=0, transport=NoRadio())
                for snapshot in case["snapshots"]:
                    for source, teams in snapshot.items():
                        fc.merge_counters(source, teams)
                for team, amount in case["deltas"]:
                    fc.adjust_score(team, amount)
                self.assertEqual({t: fc.total_scores.get(t, 0) for t in case["teams"]}, case["totals"])


class ChronoRegistryTests(unittest.TestCase):
    """The chrono registry's bodies (plan phase 14) against the records and keys they carry."""

    CHRONO = json.loads((REPO / "protocol" / "vectors" / "chrono_record.json").read_text(encoding="utf-8"))

    def test_the_lists_are_the_controllers(self) -> None:
        from atalaia_controller import checkin  # noqa: PLC0415

        self.assertEqual(fmt.REPLICA_TYPES, checkin.REPLICA_TYPES)
        self.assertEqual(fmt.REPLICA_CLASS.pattern, checkin.CLASS_RE.pattern)

    def test_the_valid_readings_carry_valid_signed_records(self) -> None:
        """The chrono vector's records verify with the key the marshals vector sends (the shared test key)."""
        from atalaia_controller import chrono  # noqa: PLC0415

        marshals = next(v for v in VECTORS["valid"] if v["kind"] == "marshals")["body"]["marshals"]
        current = next(m for m in marshals if m["replaced_at"] is None)
        key = fmt.public_key_bytes(current["public_key"])
        self.assertEqual(key.hex(), self.CHRONO["public_key"])
        for reading in next(v for v in VECTORS["valid"] if v["kind"] == "chrono")["body"]["readings"]:
            with self.subTest(series=reading["series_id"]):
                fields = chrono.parse(reading["record"], key)
                self.assertGreaterEqual(reading["received_at"], current["registered_at"])
                self.assertIn(fields["reading_id"], {v["record"]["reading_id"] for v in self.CHRONO["valid"]})

    def test_public_keys(self) -> None:
        import base64  # noqa: PLC0415

        raw = bytes(range(32))
        self.assertEqual(fmt.public_key_bytes(base64.b64encode(raw).decode()), raw)
        for bad in (raw.hex(), base64.urlsafe_b64encode(b"\xfb" * 32).decode(), base64.b64encode(raw).decode()[:-1] + "B",
                    None, 32):
            with self.subTest(bad=bad):
                with self.assertRaises(fmt.SyncFormatError):
                    fmt.public_key_bytes(bad)

    def test_check_reading_fills_defaults(self) -> None:
        entry = fmt.check_reading({"record": "{}", "series_id": "0f6e5d4c-3b2a-4198-8776-655443322110",
                                   "outcome": None, "received_at": 1.0})
        self.assertIsNone(entry["game_seed"])


class ParseTests(unittest.TestCase):
    def test_not_json_and_too_large(self) -> None:
        for raw, code in ((b"{nope", "not_json"), (b"\xff\xfe", "not_json"), (b" " * (fmt.MAX_BODY + 1), "too_large")):
            with self.subTest(code=code):
                with self.assertRaises(fmt.SyncFormatError) as caught:
                    fmt.parse("events", raw)
                self.assertEqual(caught.exception.code, code)

    def test_check_event_fills_defaults(self) -> None:
        ev = fmt.check_event({"id": 1, "node": 2, "seq": 3, "t": 4, "type": "game.start", "prio": "critical"})
        self.assertEqual((ev["team"], ev["squad"], ev["data"], ev["epoch"], ev["pkt_seq"]), (None, None, {}, None, None))

    def test_every_standard_event_type_has_the_form(self) -> None:
        from atalaia_sim.protocol import EVENTS  # noqa: PLC0415

        for name in EVENTS:
            with self.subTest(name=name):
                self.assertIsNotNone(fmt.EVENT_TYPE.fullmatch(name))
                self.assertLessEqual(len(name), fmt.EVENT_TYPE_MAX)

    def test_no_standard_data_key_is_a_position(self) -> None:
        from atalaia_sim.protocol import DATA_FIELDS  # noqa: PLC0415

        self.assertFalse(set(DATA_FIELDS) & fmt.POSITION_KEYS)
        for name in DATA_FIELDS:
            self.assertIsNotNone(fmt.DATA_KEY.fullmatch(name), name)


if __name__ == "__main__":
    unittest.main()
