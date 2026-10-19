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
        self.assertEqual((len(VECTORS["valid"]), len(VECTORS["invalid"]), len(VECTORS["merge"])), (7, 30, 3))

    def test_valid(self) -> None:
        for vector in VECTORS["valid"]:
            with self.subTest(vector=vector["name"]):
                body = fmt.CHECKS[vector["kind"]](copy.deepcopy(vector["body"]))
                if "info" in vector:
                    self.assertEqual({str(n["node_id"]): n["info"] for n in body["nodes"]}, vector["info"])
                raw = json.dumps(vector["body"]).encode()
                self.assertEqual(fmt.parse(vector["kind"], raw)["game"], vector["body"]["game"])

    def test_invalid(self) -> None:
        for vector in VECTORS["invalid"]:
            with self.subTest(vector=vector["name"]):
                with self.assertRaises(fmt.SyncFormatError) as caught:
                    fmt.CHECKS[vector["kind"]](copy.deepcopy(vector["body"]))
                self.assertEqual((caught.exception.code, caught.exception.path), (vector["error"], vector["path"]))

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
