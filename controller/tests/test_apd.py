# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""APD membership (protocol/apd.md): the shared vectors, the shipped list, and the controller's rule, check-in,
roster, erasure and console API.

    cd controller && python -m unittest discover -s tests -p "test_apd.py"
"""

from __future__ import annotations

import json
import logging
import unittest
from pathlib import Path

from p3support import GM, T0, P3Case, bearer
import copy

from test_sync_branding import SETTINGS, FakeSite
from atalaia_controller.sync_client import SyncClient
from atalaia_controller import apd, sync_format
from atalaia_controller.checkin import declared_membership
from atalaia_controller.engine import ControllerError

ROOT = Path(__file__).resolve().parents[2]
VECTORS = json.loads((ROOT / "protocol" / "vectors" / "apd.json").read_text(encoding="utf-8"))
TODAY = "2027-01-15"  # T0's date
FUTURE, PAST = "2027-12-31", "2026-12-31"


class VectorTests(unittest.TestCase):
    def test_rules(self):
        for v in VECTORS["rule_valid"]:
            with self.subTest(v["name"]):
                self.assertEqual(apd.check_rule(v["input"]), v["rule"])
        for v in VECTORS["rule_invalid"]:
            with self.subTest(v["name"]):
                with self.assertRaises(apd.ApdError) as cm:
                    apd.check_rule(v["input"])
                self.assertEqual(cm.exception.code, v["error"])

    def test_memberships(self):
        for v in VECTORS["membership_valid"]:
            with self.subTest(v["name"]):
                self.assertEqual(apd.check_membership(v["input"]), v["membership"])
        for v in VECTORS["membership_invalid"]:
            with self.subTest(v["name"]):
                with self.assertRaises(apd.ApdError) as cm:
                    apd.check_membership(v["input"])
                self.assertEqual(cm.exception.code, v["error"])

    def test_status(self):
        for v in VECTORS["status"]:
            with self.subTest(v["name"]):
                m = v["membership"]
                self.assertEqual(apd.status(apd.check_rule(v["rule"]), m["apd"], m["number"], m["expires"], v["on"]),
                                 v["status"])

    def test_the_shipped_list_is_the_registrys(self):
        mine = (Path(apd.DATA)).read_bytes()
        self.assertEqual(mine, (ROOT / "registry" / "apds" / "apds.json").read_bytes())
        self.assertIsInstance(apd.project_list(), list)

    def test_choices_put_the_countrys_entries_first_then_the_fields_own(self):
        rule = apd.check_rule({"custom": [{"id": "x-a", "name": "A", "short_name": "A"}]})
        self.assertEqual([e["id"] for e in apd.choices(rule, "PT")], [e["id"] for e in apd.project_list()] + ["x-a"])
        self.assertEqual([e["id"] for e in apd.choices(rule, "ES")], ["x-a"])
        self.assertEqual([e["id"] for e in apd.choices(rule, None)], ["x-a"])

    def test_countries(self):
        for v in VECTORS["country_valid"]:
            with self.subTest(v["name"]):
                self.assertEqual(apd.check_country(v["input"]), v["country"])
        for v in VECTORS["country_invalid"]:
            with self.subTest(v["name"]):
                with self.assertRaises(apd.ApdError) as cm:
                    apd.check_country(v["input"])
                self.assertEqual(cm.exception.code, v["error"])
        for v in VECTORS["default_country"]:
            with self.subTest(v["zone"]):
                self.assertEqual(apd.default_country(v["zone"]), v["country"])
        for v in VECTORS["wording"]:
            with self.subTest(v["country"]):
                self.assertEqual(apd.wording(v["country"]), v["wording"])

    def test_the_vectors_choices(self):
        for v in VECTORS["choices"]:
            with self.subTest(v["name"]):
                got = apd.offered(v["project"], apd.check_rule(v["rule"]), v["country"])
                self.assertEqual([e["id"] for e in got], v["ids"])

    def test_every_shipped_entry_has_a_country(self):
        for e in apd.project_list():
            self.assertRegex(e["country"], "^[A-Z]{2}$")
        with self.assertRaises(apd.ApdError):
            apd.check_entry({"id": "x-a", "country": "PT", "name": "A", "short_name": "A"})  # own entries have none
        with self.assertRaises(apd.ApdError):
            apd.check_entry({"id": "a", "name": "A", "short_name": "A"}, own=False)

    def test_the_old_and_new_number_names_agree(self):
        self.assertEqual(declared_membership({"federation_number": "1"})["number"], "1")
        self.assertEqual(declared_membership({"membership_number": "1", "federation_number": "1"})["number"], "1")
        with self.assertRaises(ControllerError):
            declared_membership({"membership_number": "1", "federation_number": "2"})
        with self.assertRaises(ControllerError):
            declared_membership({"membership_expires": "2027-02-30"})


def rule(**kw):
    return {"checkin": True, **kw}


class ApdCheckinTests(P3Case):
    def put_rule(self, **kw):
        r = self.client.put("/api/v1/checkin/settings", json={"apd": kw}, headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def row(self, gid, me):
        return self.ctrl.store.checkin(gid, me["player_id"])

    def put_country(self, country):
        return self.client.put("/api/v1/checkin/settings", json={"country": country}, headers=GM)

    def test_the_country_and_the_list_it_offers(self):
        self.svc.cfg.country = ""
        self.svc._zone_name = lambda: "Europe/Madrid"
        self.assertIsNone(self.info()["settings"]["country"])  # no country: only the field's own entries
        self.assertEqual(self.info()["apds"], [])
        self.assertEqual(self.put_country("es").json()["country"], "ES")  # capitals whatever the case typed
        self.assertEqual(self.info()["apds"], [])  # the shipped list has no entry for ES yet
        own = {"id": "x-club", "name": "Club", "short_name": "Club", "website": None}
        self.put_rule(custom=[own])
        self.assertEqual(self.info()["apds"], [own])
        self.assertEqual(self.put_country("pt").json()["country"], "PT")
        self.assertEqual(self.info()["apds"], apd.project_list() + [own])
        self.restart()  # saved
        self.assertEqual(self.svc.settings()["country"], "PT")
        self.assertEqual(self.put_country("").json()["country"], None)  # back to the default: none for Madrid
        r = self.put_country("PRT")
        self.assertEqual(r.status_code, 400, r.text)
        r = self.put_country(5)
        self.assertEqual(r.status_code, 400, r.text)

    def test_the_default_country_follows_the_time_zone(self):
        self.svc._zone_name = lambda: "Atlantic/Azores"
        self.assertEqual(self.svc.settings()["country"], "PT")
        self.svc._zone_name = lambda: "Europe/Berlin"
        self.assertIsNone(self.svc.settings()["country"])
        self.svc.cfg.country = "DE"  # [checkin] country wins over the zone
        self.assertEqual(self.svc.settings()["country"], "DE")

    def test_settings_and_the_choices(self):
        self.put_country("PT")
        info = self.info()
        self.assertEqual(info["settings"]["apd"], apd.default_rule())
        self.assertEqual(info["apds"], apd.project_list())
        own = {"id": "x-clube", "name": "Clube", "short_name": "Clube", "website": None}
        out = self.put_rule(checkin=True, expiry=True, accepted=["x-clube"], custom=[own])
        self.assertEqual(out["apd"]["custom"], [own])
        self.assertEqual(self.info()["apds"][-1], own)
        r = self.client.put("/api/v1/checkin/settings", json={"apd": {"checkin": "yes"}}, headers=GM)
        self.assertEqual(r.status_code, 400, r.text)
        self.restart()  # saved
        self.assertTrue(self.svc.settings()["apd"]["expiry"])

    def test_without_a_rule_nothing_changes(self):
        g = self.new_game()
        me = self.check_in(g["id"], federation_number="X1")
        self.assertEqual(me["status"], "checked_in")
        self.assertIsNone(self.row(g["id"], me)["federation_number"])  # federation off: not kept
        r = self.client.get(f"/api/v1/games/{g['id']}/checkins", headers=GM).json()
        self.assertIsNone(r[0]["apd_status"] if isinstance(r, list) else r["checkins"][0]["apd_status"])

    def test_a_valid_membership_checks_in_and_is_kept_with_the_new_names(self):
        g = self.new_game()
        self.put_rule(checkin=True, expiry=True, accepted=["apd-a"])
        me = self.check_in(g["id"], apd_id="apd-a", membership_number="123", membership_expires=FUTURE)
        self.assertEqual(me["status"], "checked_in")
        row = self.row(g["id"], me)
        self.assertEqual((row["apd_id"], row["federation_number"], row["membership_expires"]),
                         ("apd-a", "123", FUTURE))
        own = self.client.get("/api/v1/checkin/me", headers=bearer(me["token"])).json()
        self.assertEqual((own["apd_status"], own["membership_number"], own["federation_number"]),
                         ("valid", "123", "123"))

    def test_the_verdicts_wait_for_a_marshal_and_staff_may_override(self):
        g = self.new_game()
        self.put_rule(checkin=True, expiry=True, accepted=["apd-a"])
        # Membership numbers no random id or timestamp can contain, so the "never logged" check means something.
        cases = {"missing": dict(),
                 "expired": dict(apd_id="apd-a", membership_number="MBR-QX71", membership_expires=PAST),
                 "not_accepted": dict(apd_id="apd-b", membership_number="MBR-QX72", membership_expires=FUTURE)}
        m, mtoken = self.make_marshal(g["id"])
        for want, body in cases.items():
            with self.subTest(want):
                me = self.check_in(g["id"], **body)
                self.assertEqual(me["status"], "pending")  # even with confirm = auto
                self.assertEqual(self.row(g["id"], me)["apd_override"], False)
                with self.assertLogs("atalaia.checkin", level=logging.INFO) as logs:
                    r = self.client.patch(f"/api/v1/games/{g['id']}/checkins/{me['player_id']}",
                                          headers=bearer(mtoken), json={"status": "checked_in"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertEqual((r.json()["status"], r.json()["apd_status"], r.json()["apd_override"]),
                                 ("checked_in", want, True))
                self.assertTrue(any("apd override" in line and want in line for line in logs.output))
                self.assertFalse(any("MBR-QX" in line for line in logs.output))  # the number is never logged

    def test_a_hand_check_in_is_never_refused_and_is_logged(self):
        g = self.new_game()
        self.put_rule(checkin=True)
        with self.assertLogs("atalaia.checkin", level=logging.INFO) as logs:
            r = self.client.post(f"/api/v1/games/{g['id']}/checkins", headers=GM, json={"display_name": "Ana"})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual((r.json()["status"], r.json()["apd_status"], r.json()["apd_override"]),
                         ("checked_in", "missing", True))
        self.assertTrue(any("apd override" in line for line in logs.output))
        r = self.client.post(f"/api/v1/games/{g['id']}/checkins", headers=GM,
                             json={"display_name": "Rui", "membership_number": "9", "apd_id": "apd-a"})
        self.assertEqual((r.json()["apd_status"], r.json()["apd_override"]), ("valid", False))

    def test_a_marshal_may_correct_the_membership(self):
        g = self.new_game()
        self.put_rule(checkin=True)
        me = self.check_in(g["id"])
        self.assertEqual(me["status"], "pending")
        r = self.client.patch(f"/api/v1/games/{g['id']}/checkins/{me['player_id']}", headers=GM,
                              json={"apd_id": "apd-a", "membership_number": "55"})
        self.assertEqual((r.status_code, r.json()["apd_status"]), (200, "valid"))

    def test_leaving_and_the_purge_erase_the_membership(self):
        g = self.new_game()
        self.put_rule(checkin=True, expiry=True)
        a = self.check_in(g["id"], apd_id="apd-a", membership_number="1", membership_expires=FUTURE)
        b = self.check_in(g["id"], apd_id="apd-a", membership_number="2", membership_expires=FUTURE)
        r = self.client.delete("/api/v1/checkin/me", headers=bearer(a["token"]))
        self.assertEqual(r.status_code, 200, r.text)
        row = self.row(g["id"], a)
        self.assertEqual((row["apd_id"], row["membership_expires"], row["federation_number"]), (None, None, None))
        self.client.post(f"/api/v1/games/{g['id']}/end", json={}, headers=GM)
        self.ctrl.store.update_game(g["id"], ended_at=T0)
        self.now = T0 + 31 * 86400
        self.assertEqual(self.svc.purge(force=True)["checkins"], 1)
        row = self.row(g["id"], b)
        self.assertEqual((row["apd_id"], row["membership_expires"], row["federation_number"]), (None, None, None))

    def test_the_csv_export_has_the_verdict(self):
        g = self.new_game()
        self.put_rule(checkin=True)
        self.check_in(g["id"], apd_id="apd-a", membership_number="1")
        header, line = self.svc.csv_export(g["id"]).splitlines()[:2]
        cols = header.split(",")
        self.assertEqual(line.split(",")[cols.index("apd_status")], "valid")
        self.assertEqual(line.split(",")[cols.index("apd_id")], "apd-a")

    def test_the_roster_brings_the_membership(self):
        g = self.new_game()
        self.put_rule(checkin=True, expiry=True)
        roster = {"sync_version": 1, "scheduled_game_id": "0192f3a4-5b6c-7d8e-9f01-23456789abcd", "status": "published",
                  "federation": "off", "apd": rule(expiry=True),
                  "registrations": [{"registration_id": "0192f3a4-5b6c-7d8e-9f01-23456789abce",
                                     "player_id": "p-aaaaaaaaaaaa", "display_name": "Ana", "replicas": [],
                                     "federation_number": "77", "apd_id": "apd-a", "membership_expires": FUTURE}]}
        roster = sync_format.check_roster(roster)
        self.svc.apply_roster(g["id"], roster)
        row = self.ctrl.store.checkin(g["id"], "p-aaaaaaaaaaaa")
        self.assertEqual((row["status"], row["federation_number"], row["apd_id"], row["membership_expires"]),
                         ("expected", "77", "apd-a", FUTURE))
        r = self.client.get(f"/api/v1/games/{g['id']}/checkins", headers=GM).json()
        rows = r if isinstance(r, list) else r["checkins"]
        self.assertEqual(rows[0]["apd_status"], "valid")

    def test_the_site_rule_overrides_the_console_with_branding_site(self):
        self.cfg.sync_branding = "site"
        self.svc.set_site_apd(apd.check_rule({"checkin": True, "accepted": ["apd-a"]}))
        self.assertEqual(self.svc.settings()["apd"]["accepted"], ["apd-a"])
        r = self.client.put("/api/v1/checkin/settings", json={"apd": {}}, headers=GM)
        self.assertEqual(r.status_code, 409, r.text)
        r = self.client.put("/api/v1/checkin/settings", json={"confirm": "staff"}, headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["apd"]["accepted"], ["apd-a"])

    def test_the_site_country_overrides_the_console_with_branding_site(self):
        self.cfg.sync_branding = "site"
        self.client.put("/api/v1/checkin/settings", json={"country": "ES"}, headers=GM)
        self.assertEqual(self.svc.settings()["country"], "ES")
        self.svc.store.set_setting("checkin.country_site", json.dumps("DE"))
        self.assertEqual(self.svc.settings()["country"], "DE")
        r = self.client.put("/api/v1/checkin/settings", json={"country": "PT"}, headers=GM)
        self.assertEqual(r.status_code, 409, r.text)
        self.svc.store.set_setting("checkin.country_site", json.dumps(None))  # the site says: unset
        self.assertIsNone(self.svc.settings()["country"])


class SiteRuleTests(P3Case):
    """With ``[sync] branding = "site"`` the settings of the field answer carry the APD rule (BR24's ``settings``)."""

    cfg_overrides = {"sync_url": "https://site.example.org", "sync_enabled": True, "sync_branding": "site"}

    def test_the_pull_sets_the_rule_and_an_older_site_server_leaves_it_alone(self):
        site = FakeSite()
        site.settings = copy.deepcopy(SETTINGS)
        site.settings["apd"] = {"checkin": True, "expiry": True, "accepted": ["apd-a"]}
        sync = SyncClient(self.cfg, self.bundle.store, api_key="k" * 43, transport=site, checkin=self.svc,
                          branding=self.ctrl.branding)
        self.assertTrue(sync.run_once(), sync.last_error)
        self.assertIn("/api/v1/sync/field?settings=1", site.gets)
        self.assertEqual(self.svc.settings()["apd"]["accepted"], ["apd-a"])
        self.assertTrue(self.client.get("/api/v1/checkin").json()["settings"]["apd"]["expiry"])
        r = self.client.put("/api/v1/checkin/settings", json={"apd": {}}, headers=GM)
        self.assertEqual(r.status_code, 409, r.text)
        site.settings = copy.deepcopy(SETTINGS)  # a site server that sends settings without an apd key
        self.assertTrue(sync.run_once(), sync.last_error)
        self.assertEqual(self.svc.settings()["apd"]["accepted"], ["apd-a"])
        site.settings["apd"] = {}  # the site's rule is the default again
        self.assertTrue(sync.run_once(), sync.last_error)
        self.assertEqual(self.svc.settings()["apd"], apd.default_rule())

    def test_the_pull_sets_the_country(self):
        self.svc._zone_name = lambda: "Europe/Lisbon"
        site = FakeSite()
        site.settings = copy.deepcopy(SETTINGS)
        sync = SyncClient(self.cfg, self.bundle.store, api_key="k" * 43, transport=site, checkin=self.svc,
                          branding=self.ctrl.branding)
        self.assertTrue(sync.run_once(), sync.last_error)
        self.assertEqual(self.svc.settings()["country"], "PT")  # an older site sends none: the default stays
        site.settings["country"] = "ES"
        self.assertTrue(sync.run_once(), sync.last_error)
        self.assertEqual(self.client.get("/api/v1/checkin").json()["settings"]["country"], "ES")
        site.settings["country"] = None  # the site's field has no country
        self.assertTrue(sync.run_once(), sync.last_error)
        self.assertIsNone(self.svc.settings()["country"])


class RosterFormatTests(unittest.TestCase):
    BASE = {"sync_version": 1, "scheduled_game_id": "0192f3a4-5b6c-7d8e-9f01-23456789abcd", "status": "published",
            "federation": "off",
            "registrations": [{"registration_id": "0192f3a4-5b6c-7d8e-9f01-23456789abce", "player_id": "p-aaaaaaaaaaaa",
                               "display_name": "Ana", "replicas": [], "federation_number": "1"}]}

    def test_a_number_needs_the_game_or_the_rule_to_ask(self):
        with self.assertRaises(sync_format.SyncFormatError) as cm:
            sync_format.check_roster(json.loads(json.dumps(self.BASE)))
        self.assertEqual(cm.exception.code, "not_asked")
        ok = json.loads(json.dumps(self.BASE))
        ok["apd"] = {"checkin": True}
        self.assertTrue(sync_format.check_roster(ok)["apd"]["checkin"])

    def test_a_bad_rule_or_membership_fails(self):
        for edit in ({"apd": {"checkin": 1}}, {"apd": {"x": 1}}):
            with self.subTest(edit):
                bad = {**json.loads(json.dumps(self.BASE)), **edit, "federation": "optional"}
                with self.assertRaises(sync_format.SyncFormatError) as cm:
                    sync_format.check_roster(bad)
                self.assertEqual(cm.exception.code, "bad_apd_rule")
        bad = json.loads(json.dumps(self.BASE))
        bad["federation"] = "optional"
        bad["registrations"][0]["membership_expires"] = "2027-02-30"
        with self.assertRaises(sync_format.SyncFormatError):
            sync_format.check_roster(bad)

    def test_the_settings_carry_a_rule_and_the_plain_answer_does_not(self):
        st = copy.deepcopy(SETTINGS)
        st["apd"] = {"checkin": True, "expiry": True}
        ans = {"sync_version": 1, "field": {}, "teams": [], "settings": st}
        out = sync_format.check_field(ans)
        self.assertEqual(out["settings"]["apd"], rule(expiry=True) | {"accepted": None, "register": False,
                                                                       "custom": []})
        st["apd"] = {"bogus": 1}
        with self.assertRaises(sync_format.SyncFormatError):
            sync_format.check_field(ans)
        st["apd"] = {}
        for good in ("PT", None):
            st["country"] = good
            self.assertEqual(sync_format.check_field(copy.deepcopy(ans))["settings"]["country"], good)
        for bad in ("pt", "PRT", 7):
            st["country"] = bad
            with self.assertRaises(sync_format.SyncFormatError) as cm:
                sync_format.check_field(copy.deepcopy(ans))
            self.assertEqual((cm.exception.code, cm.exception.path), ("bad_value", "settings.country"))
        plain = {"sync_version": 1, "field": {"apd": {"checkin": True}}, "teams": []}
        with self.assertRaises(sync_format.SyncFormatError):  # no rule in the branding part
            sync_format.check_field(plain)


if __name__ == "__main__":
    unittest.main()
