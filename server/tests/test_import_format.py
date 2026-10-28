# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The registration import's format with no database (plan phase 17, decisions F20, S17-*; also run by
tools/check.sh): reading CSV (RFC 4180) and JSON, only the listed columns, the file and row checks, the
limits, and the export's protection against spreadsheet formulas (the controller's check-in export's rule).

The CSV examples follow RFC 4180 section 2 (CRLF records, a header line, quoted fields with commas, line
breaks and doubled quotes), written out here rather than copied: the RFC itself gives only fragments.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atalaia_server import import_format as fmt  # noqa: E402
from atalaia_controller import checkin  # noqa: E402

RULES = fmt.Rules(teams=("red", "blue"), federation="optional", predeclare_replicas=True,
                  classes=("dmr", "pistol", "rifle", "sniper"), max_replicas=3)


def rows(parsed: fmt.Parsed, rules: fmt.Rules = RULES) -> list[object]:
    """Each row as a Row or the code it was refused with."""
    out: list[object] = []
    for raw in parsed.rows:
        try:
            out.append(fmt.check_row(raw, rules))
        except fmt.RowError as exc:
            out.append(exc.code)
    return out


class CsvTests(unittest.TestCase):
    def test_rfc4180_records(self) -> None:
        data = ('display_name,external_ref,team_preference,federation_number,replicas\r\n'
                '"Falcão, o Velho",ref-1,red,FPA-1,"aeg:rifle:Tokyo Marui M4|pistol:pistol"\r\n'
                '"Diz ""Lobo""",ref-2,,,\r\n'
                '"Duas\r\nlinhas",ref-3,blue,,\r\n').encode("utf-8")
        parsed = fmt.parse_csv(data)
        self.assertEqual(parsed.columns, tuple(c for c in fmt.COLUMNS if c not in ("apd_id", "membership_expires")))
        self.assertEqual((parsed.ignored, parsed.ignored_more), ([], 0))
        out = rows(parsed)
        self.assertEqual(out[0].display_name, "Falcão, o Velho")
        self.assertEqual(out[0].replicas, [{"type": "aeg", "class": "rifle", "make_model": "Tokyo Marui M4"},
                                           {"type": "pistol", "class": "pistol", "make_model": None}])
        self.assertEqual((out[1].display_name, out[1].team_preference, out[1].replicas), ('Diz "Lobo"', None, []))
        self.assertEqual(out[2], "display_name_invalid")  # a line break is not one line
        self.assertEqual([r.number for r in parsed.rows], [2, 3, 4])

    def test_only_the_listed_columns_are_read(self) -> None:
        data = ("Email,Display_Name , telefone,,external_ref\n"
                "rita@example.pt,Rita,912345678,x,7\n").encode("utf-8")
        parsed = fmt.parse_csv(data)
        self.assertEqual(parsed.columns, ("display_name", "external_ref"))
        self.assertEqual(parsed.ignored, ["Email", "telefone", "(column 4)"])
        self.assertEqual(parsed.rows[0].values, {"display_name": "Rita", "external_ref": "7"})
        self.assertNotIn("rita@example.pt", repr(parsed))
        self.assertNotIn("912345678", repr(parsed))

    def test_bom_lf_and_blank_lines(self) -> None:
        parsed = fmt.parse_csv("﻿display_name\nAna\n\nBea\n".encode("utf-8"))
        self.assertEqual([r.values["display_name"] for r in parsed.rows], ["Ana", "Bea"])
        self.assertEqual([r.number for r in parsed.rows], [2, 4])

    def test_files_refused_whole(self) -> None:
        cases = {
            b"": "empty",
            b"name,email\nAna,a@b\n": "display_name_column_missing",
            b"display_name,Display_name\nA,B\n": "column_twice",
            "display_name\nJo\xe3o\n".encode("latin-1"): "encoding_invalid",
            b"display_name\nA\x00B\n": "encoding_invalid",
            b'display_name\n"Ana\n': "csv_invalid",
            b'display_name\n"Ana"x\n': "csv_invalid",
            b"display_name\n" + b"A" * fmt.MAX_BYTES: "too_large",
            ("display_name\n" + "A\n" * (fmt.MAX_ROWS + 1)).encode(): "too_many_rows",
        }
        for data, code in cases.items():
            with self.subTest(code=code), self.assertRaises(fmt.FileError) as caught:
                fmt.parse_csv(data)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(len(fmt.parse_csv(("display_name\n" + "A\n" * fmt.MAX_ROWS).encode()).rows), fmt.MAX_ROWS)

    def test_a_row_of_the_wrong_length(self) -> None:
        parsed = fmt.parse_csv(b"display_name,external_ref\nAna,1,extra\nBea\nCris,3\n")
        self.assertEqual(rows(parsed)[:2], ["row_length", "row_length"])
        self.assertEqual(rows(parsed)[2].display_name, "Cris")

    def test_replicas_text(self) -> None:
        def one(text: str, rules: fmt.Rules = RULES) -> object:
            parsed = fmt.parse_csv(f"display_name,replicas\nAna,{text}\n".encode())
            r = rows(parsed, rules)[0]
            return r if isinstance(r, str) else r.replicas
        self.assertEqual(one('"AEG : rifle : G&G: CM16"'), [{"type": "aeg", "class": "rifle", "make_model": "G&G: CM16"}])
        self.assertEqual(one(""), [])
        self.assertEqual(one("aeg"), "replicas_invalid")
        self.assertEqual(one("laser:rifle"), "replica_type_invalid")
        self.assertEqual(one("aeg:minigun"), "replica_class_invalid")
        self.assertEqual(one("aeg:rifle|aeg:rifle|aeg:rifle|aeg:rifle"), "too_many_replicas")
        self.assertEqual(one("aeg:rifle:" + "x" * 65), "make_model_invalid")
        no = fmt.Rules(**{**RULES.__dict__, "predeclare_replicas": False})
        self.assertEqual(one("aeg:rifle", no), "replicas_not_asked")
        self.assertEqual(one("", no), [])


class JsonTests(unittest.TestCase):
    def test_objects(self) -> None:
        data = json.dumps([
            {"display_name": "Ana", "external_ref": 12, "federation_number": 345, "email": "a@b.pt",
             "replicas": [{"type": "dmr", "class": "dmr", "make_model": "VFC"}]},
            {"display_name": "Bea", "team_preference": "green"},
            "Cris",
            {"display_name": "Dina", "replicas": "aeg:rifle"},
            {"display_name": "Eva", "replicas": [{"type": "aeg", "class": "rifle", "fps": 350}]},
            {"display_name": "Fá", "external_ref": True},
        ]).encode()
        parsed = fmt.parse_json(data)
        self.assertEqual(parsed.ignored, ["email"])
        out = rows(parsed)
        self.assertEqual((out[0].external_ref, out[0].federation_number), ("12", "345"))
        self.assertEqual(out[0].replicas, [{"type": "dmr", "class": "dmr", "make_model": "VFC"}])
        self.assertEqual(out[1:3], ["team_preference_invalid", "row_not_object"])
        self.assertEqual(out[3].replicas, [{"type": "aeg", "class": "rifle", "make_model": None}])
        self.assertEqual(out[4:], ["replicas_invalid", "external_ref_invalid"])
        self.assertEqual(out[0].present, frozenset({"display_name", "external_ref", "federation_number", "replicas"}))

    def test_files_refused_whole(self) -> None:
        for data, code in ((b'{"display_name": "Ana"}', "json_invalid"), (b"[", "json_invalid"),
                           (b'[{"display_name": "A", "display_name": "B"}]', "json_invalid"),
                           (b"[NaN]", "json_invalid"), (b"\xff[]", "encoding_invalid"),
                           (json.dumps([{}] * (fmt.MAX_ROWS + 1)).encode(), "too_many_rows")):
            with self.subTest(data=data[:30]), self.assertRaises(fmt.FileError) as caught:
                fmt.parse_json(data)
            self.assertEqual(caught.exception.code, code)

    def test_a_key_twice_in_other_case(self) -> None:
        parsed = fmt.parse_json(b'[{"display_name": "A", "Display_Name": "B"}]')
        self.assertEqual(rows(parsed), ["column_twice"])


class RowTests(unittest.TestCase):
    def check(self, values: dict, rules: fmt.Rules = RULES) -> object:
        try:
            return fmt.check_row(fmt.RawRow(2, values), rules)
        except fmt.RowError as exc:
            return exc.code

    def test_display_name(self) -> None:
        self.assertEqual(self.check({"display_name": "  Ana  "}).display_name, "Ana")
        for value in ("", "   ", None, "x" * 33, "A\tB", "A\u0085B", 7):
            with self.subTest(value=value):
                self.assertEqual(self.check({"display_name": value}), "display_name_invalid")
        self.assertEqual(self.check({"external_ref": "1"}), "display_name_invalid")

    def test_federation_as_the_game_says(self) -> None:
        required = fmt.Rules(**{**RULES.__dict__, "federation": "required"})
        off = fmt.Rules(**{**RULES.__dict__, "federation": "off"})
        self.assertEqual(self.check({"display_name": "A"}, required), "federation_number_required")
        row = self.check({"display_name": "A", "federation_number": "FPA-9", "external_ref": "r"}, off)
        self.assertEqual((row.federation_number, row.warnings), (None, ["federation_number_dropped"]))
        self.assertEqual(self.check({"display_name": "A", "federation_number": "9" * 33}),
                         "federation_number_invalid")

    def test_warnings(self) -> None:
        self.assertEqual(self.check({"display_name": "A"}).warnings, ["no_external_ref"])
        self.assertEqual(self.check({"display_name": "A", "external_ref": "x" * 129}), "external_ref_invalid")

    def test_source_label(self) -> None:
        for good in ("fpa", "clube.exemplo", "a-b_c", "x" * 32):
            self.assertEqual(fmt.check_source(good), good)
        for bad in ("site", "", "Clube", "-x", "x" * 33, "a b", None):
            with self.subTest(bad=bad), self.assertRaises(fmt.FileError):
                fmt.check_source(bad)


class ExportTests(unittest.TestCase):
    def test_formula_injection(self) -> None:
        for value in ("=HYPERLINK(\"http://x\")", "+351", "-1", "@SUM(A1)", "\tx", "\rx"):
            with self.subTest(value=value):
                self.assertEqual(fmt.csv_safe(value), "'" + value)
                self.assertEqual(fmt.csv_unsafe(fmt.csv_safe(value)), value)
                self.assertEqual(fmt.csv_safe(value), checkin._csv_safe(value))  # the controller's rule
        for value in ("Ana", "'quoted", "", None):
            self.assertEqual(fmt.csv_safe(value), value or "")
        self.assertEqual(fmt.csv_unsafe("'quoted"), "'quoted")

    def test_an_export_imports_back_unchanged(self) -> None:
        source = [{"display_name": "=1+1", "external_ref": "-7", "team_preference": "red",
                   "federation_number": "+351", "apd_id": "x-clube", "membership_expires": "2027-03-01",
                   "replicas": [{"type": "aeg", "class": "rifle", "make_model": "@M4|A"}],
                   "registration_id": "r1", "player_id": "p-aaaaaaaaaaaa", "status": "registered", "source": "site"}]
        text = fmt.export_csv(source)
        self.assertTrue(text.startswith(
            "display_name,external_ref,team_preference,federation_number,apd_id,membership_expires,replicas,"))
        self.assertIn("'=1+1", text)
        self.assertTrue(text.endswith("\r\n"))
        row = rows(fmt.parse_csv(text.encode("utf-8")))[0]
        self.assertEqual((row.display_name, row.external_ref, row.federation_number), ("=1+1", "-7", "+351"))
        self.assertEqual((row.apd_id, row.membership_expires), ("x-clube", "2027-03-01"))
        self.assertEqual(row.replicas, [{"type": "aeg", "class": "rifle", "make_model": "@M4/A"}])
        self.assertEqual(fmt.parse_csv(text.encode()).ignored, ["registration_id", "player_id", "status", "source"])


if __name__ == "__main__":
    unittest.main()
