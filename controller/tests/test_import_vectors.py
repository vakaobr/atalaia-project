# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registration import's shared cases (protocol/vectors/registration_import.json) against
``import_format.py``: the same file the phone controller's Dart port (app/lib/controller/registration_import.dart)
is run against, so the site server, the Pi controller and the phone read a registration list the same way.
Plain Python; no controller needed.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from atalaia_controller import import_format as fmt

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors"
                      / "registration_import.json").read_text(encoding="utf-8"))


def data_of(case: dict) -> bytes:
    if "data" in case:
        return case["data"].encode("utf-8")
    if "data_hex" in case:
        return bytes.fromhex(case["data_hex"])
    g = case["data_gen"]
    return (g["head"] + g["unit"] * g["times"] + g.get("tail", "")).encode("utf-8")


class VectorTests(unittest.TestCase):
    def test_cases(self) -> None:
        self.assertGreater(len(VECTORS["cases"]), 40)
        for case in VECTORS["cases"]:
            with self.subTest(case["name"]):
                r = {**VECTORS["rules"], **case.get("rules", {})}
                rules = fmt.Rules(teams=tuple(r["teams"]), federation=r["federation"],
                                  predeclare_replicas=r["predeclare_replicas"], classes=tuple(r["classes"]),
                                  max_replicas=r["max_replicas"])
                want = case["expect"]
                try:
                    parsed = fmt.parse(data_of(case), case["format"])
                except fmt.FileError as exc:
                    self.assertEqual({"error": exc.code, **({"line": exc.line} if exc.line is not None else {})}, want)
                    continue
                self.assertNotIn("error", want)
                self.assertEqual((parsed.format, list(parsed.columns)), (want["format"], want["columns"]))
                if "row_count" in want:
                    self.assertEqual(len(parsed.rows), want["row_count"])
                    continue
                self.assertEqual((parsed.ignored, parsed.ignored_more), (want["ignored"], want["ignored_more"]))
                got = []
                for raw in parsed.rows:
                    try:
                        row = fmt.check_row(raw, rules)
                        res: object = {"display_name": row.display_name, "external_ref": row.external_ref,
                                       "team_preference": row.team_preference,
                                       "federation_number": row.federation_number, "apd_id": row.apd_id,
                                       "membership_expires": row.membership_expires, "replicas": row.replicas,
                                       "present": sorted(row.present), "warnings": row.warnings}
                    except fmt.RowError as exc:
                        res = exc.code
                    got.append({"number": raw.number, "result": res})
                # An expected result may leave the two membership keys out: null (the older cases).
                self.assertEqual(got, [{**r, "result": {"apd_id": None, "membership_expires": None, **r["result"]}
                                        if isinstance(r["result"], dict) else r["result"]} for r in want["rows"]])


if __name__ == "__main__":
    unittest.main()
