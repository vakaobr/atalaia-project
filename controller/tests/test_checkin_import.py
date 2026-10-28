# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The GM's registration import into the controller's check-in list (PKE-1; F23): the site server's CSV/JSON
format (``import_format.py``, one file for both) read by ``POST /api/v1/games/{id}/checkins/import``, a dry
run first, rows upserting by source + external_ref, the arrivals left alone, no names in the log, and the
same cases as the site server's import where the rules are the same.
"""

from __future__ import annotations

import io
import logging
import unittest

from p3support import GM, READ, P3Case

HEADER = "display_name,external_ref,team_preference,federation_number,replicas\r\n"
CSV = (HEADER +
       "Rita Falcão,r-1,red,FPA-1,aeg:rifle:Tokyo Marui M4|pistol:dmr\r\n"
       "Zé Coruja,r-2,blue,,\r\n"
       "=HYPERLINK(1),r-3,,,\r\n")


class ImportTests(P3Case):
    def post(self, gid: int, expect: int = 200, headers=GM, **body):
        body.setdefault("format", "csv")
        r = self.client.post(f"/api/v1/games/{gid}/checkins/import", json=body, headers=headers)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def rows(self, gid: int):
        return self.client.get(f"/api/v1/games/{gid}/checkins", headers=GM).json()

    def test_dry_run_writes_nothing_then_import_makes_expected_rows(self):
        self.client.put("/api/v1/checkin/settings", json={"federation": "optional"}, headers=GM)
        g = self.new_game()
        dry = self.post(g["id"], data=CSV, source="clube", dry_run=True)
        self.assertEqual((dry["dry_run"], dry["counts"]["created"], dry["rows"]), (True, 3, 3))
        self.assertEqual(self.rows(g["id"])["checkins"], [])
        done = self.post(g["id"], data=CSV, source="clube", basis_confirmed=True)
        self.assertEqual(done["counts"], {"created": 3, "updated": 0, "unchanged": 0, "skipped": 0, "refused": 0})
        listing = self.rows(g["id"])
        self.assertEqual(listing["registrations"], {"expected": 3, "arrived": 0, "walkins": 0})
        rita = next(r for r in listing["checkins"] if r["display_name"] == "Rita Falcão")
        self.assertEqual((rita["status"], rita["team_preference"], rita["federation_number"], rita["registered"]),
                         ("expected", "red", "FPA-1", True))
        self.assertEqual([(d["type"], d["class"], d["make_model"], d["state"]) for d in rita["declarations"]],
                         [("aeg", "rifle", "Tokyo Marui M4", "pending"), ("pistol", "dmr", None, "pending")])

    def test_real_import_needs_the_basis_and_the_gm(self):
        g = self.new_game()
        self.assertEqual(self.post(g["id"], 400, data=CSV, source="clube")["detail"], "basis_not_confirmed")
        self.post(g["id"], 403, headers=READ, data=CSV, source="clube", dry_run=True)
        self.post(g["id"], 400, data=CSV, source="site", dry_run=True)  # the site's own label is reserved
        self.assertEqual(self.rows(g["id"])["checkins"], [])

    def test_same_file_again_changes_nothing_and_an_edit_updates(self):
        g = self.new_game()
        self.post(g["id"], data=CSV, source="clube", basis_confirmed=True)
        again = self.post(g["id"], data=CSV, source="clube", basis_confirmed=True)
        self.assertEqual(again["counts"]["unchanged"], 3)
        self.assertEqual(len(self.rows(g["id"])["checkins"]), 3)
        edited = CSV.replace("Zé Coruja", "José Coruja").replace("r-1,red", "r-1,blue")
        up = self.post(g["id"], data=edited, source="clube", basis_confirmed=True)
        self.assertEqual(up["counts"]["updated"], 2)
        self.assertEqual({e["external_ref"]: e["changed"] for e in up["results"] if e["result"] == "updated"},
                         {"r-1": ["team_preference"], "r-2": ["display_name"]})
        names = sorted(r["display_name"] for r in self.rows(g["id"])["checkins"])
        self.assertEqual(names, ["=HYPERLINK(1)", "José Coruja", "Rita Falcão"])

    def test_a_source_is_a_separate_namespace(self):
        g = self.new_game()
        self.post(g["id"], data=CSV, source="clube", basis_confirmed=True)
        other = self.post(g["id"], data=CSV, source="outro", basis_confirmed=True)
        self.assertEqual(other["counts"]["created"], 3)

    def test_rows_refused_alone_and_the_file_refused_whole(self):
        g = self.new_game()
        data = (HEADER + "Rita,r-1,verde,,\r\n" + "Ana,r-2,red,,\r\n" + "Ana 2,r-2,red,,\r\n"
                + "Bia,r-4,,,aeg:cannon\r\n")
        out = self.post(g["id"], data=data, source="clube", basis_confirmed=True)
        self.assertEqual(out["counts"]["created"], 1)
        self.assertEqual([e.get("code") for e in out["results"]],
                         ["team_preference_invalid", None, "external_ref_twice", "replica_class_invalid"])
        bad = self.post(g["id"], 400, data="email\r\nx\r\n", source="clube", dry_run=True)
        self.assertEqual(bad["detail"], "display_name_column_missing")
        self.assertEqual(self.post(g["id"], 400, data="display_name\r\n\"x\r\n", source="clube", dry_run=True)["detail"],
                         "csv_invalid")
        self.assertEqual(self.post(g["id"], 400, data="[1", format="json", source="clube", dry_run=True)["detail"],
                         "json_invalid")
        self.post(g["id"], 400, data=CSV, format="xml", source="clube", dry_run=True)
        self.post(g["id"], 413, data="display_name\n" + "A" * (1024 * 1024), source="clube", dry_run=True)

    def test_other_columns_are_not_read_and_json_works(self):
        g = self.new_game()
        out = self.post(g["id"], data="Email,display_name\r\nx@example.pt,Rita\r\n", source="clube", dry_run=True)
        self.assertEqual((out["columns"], out["not_imported_columns"]), (["display_name"], ["Email"]))
        js = '[{"display_name": "Rita", "external_ref": 7, "phone": "912"}]'
        out = self.post(g["id"], data=js, format="json", source="clube", basis_confirmed=True)
        self.assertEqual((out["counts"]["created"], out["not_imported_columns"]), (1, ["phone"]))
        self.assertNotIn("912", str(self.rows(g["id"])))

    def test_federation_rules_follow_the_field(self):
        g = self.new_game()
        out = self.post(g["id"], data=CSV, source="clube", dry_run=True)  # federation off: dropped with a warning
        self.assertIn("federation_number_dropped", out["results"][0]["warnings"])
        self.client.put("/api/v1/checkin/settings", json={"federation": "required"}, headers=GM)
        out = self.post(g["id"], data=CSV, source="clube", dry_run=True)
        self.assertEqual([e.get("code") for e in out["results"]],
                         [None, "federation_number_required", "federation_number_required"])

    def test_an_expected_row_is_ticked_by_name_and_then_left_alone(self):
        g = self.new_game()
        out = self.post(g["id"], data=CSV, source="clube", basis_confirmed=True)
        pid = next(r["player_id"] for r in self.rows(g["id"])["checkins"] if r["display_name"] == "Zé Coruja")
        self.assertEqual(self.gm_patch(g["id"], pid, status="checked_in")["status"], "checked_in")
        edited = CSV.replace("Zé Coruja", "Outro Nome")
        again = self.post(g["id"], data=edited, source="clube", basis_confirmed=True)
        self.assertEqual([e.get("code") for e in again["results"] if e["result"] == "skipped"], ["already_arrived"])
        row = next(r for r in self.rows(g["id"])["checkins"] if r["player_id"] == pid)
        self.assertEqual(row["display_name"], "Zé Coruja")
        self.assertEqual(self.rows(g["id"])["registrations"], {"expected": 2, "arrived": 1, "walkins": 0})
        shortened = self.post(g["id"], data=HEADER + "Rita Falcão,r-1,red,FPA-1,\r\n", source="clube", dry_run=True)
        self.assertEqual(shortened["missing"]["count"], 1)  # r-3 (r-2 arrived); never removed by an import
        self.assertEqual(out["counts"]["created"], 3)

    def test_rows_without_a_ref_are_added_each_time(self):
        g = self.new_game()
        data = "display_name\r\nSem Ref\r\n"
        self.post(g["id"], data=data, source="clube", basis_confirmed=True)
        out = self.post(g["id"], data=data, source="clube", basis_confirmed=True)
        self.assertEqual(out["results"][0]["warnings"], ["no_external_ref"])
        self.assertEqual(len(self.rows(g["id"])["checkins"]), 2)

    def test_an_ended_or_unknown_game_is_refused(self):
        self.post(99, 404, data=CSV, source="clube", dry_run=True)
        g = self.new_game()
        self.client.post(f"/api/v1/games/{g['id']}/start", headers=GM, json={"force": True})
        self.client.post(f"/api/v1/games/{g['id']}/end", headers=GM)
        self.post(g["id"], 409, data=CSV, source="clube", dry_run=True)

    def test_imported_registrations_never_go_back_to_a_site_and_a_roster_leaves_them(self):
        g = self.new_game()
        self.post(g["id"], data=CSV, source="clube", basis_confirmed=True)
        self.assertEqual(self.svc.outcomes(g["id"])["registrations"], [])
        self.svc.apply_roster(g["id"], {"registrations": []})
        self.assertEqual(len(self.rows(g["id"])["checkins"]), 3)

    def test_no_name_in_the_log(self):
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        root = logging.getLogger("atalaia.checkin")
        level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            g = self.new_game()
            self.post(g["id"], data=CSV, source="clube", basis_confirmed=True)
        finally:
            root.removeHandler(handler)
            root.setLevel(level)
        self.assertIn("registration import", buf.getvalue())
        for secret in ("Falc", "Coruja", "FPA-1"):
            self.assertNotIn(secret, buf.getvalue())

    def test_the_csv_export_imports_back(self):
        g = self.new_game()
        self.post(g["id"], data=CSV, source="clube", basis_confirmed=True)
        text = self.client.get(f"/api/v1/games/{g['id']}/checkins.csv", headers=GM).content.decode("utf-8-sig")
        out = self.post(g["id"], data=text, source="clube", dry_run=True)
        self.assertIn("player_id", out["not_imported_columns"])
        self.assertEqual(out["counts"]["refused"], 0)


if __name__ == "__main__":
    unittest.main()
