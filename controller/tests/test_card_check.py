# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The card check at check-in (protocol/apd.md "The card check", decisions LEG-1 to LEG-11) and the position-sharing
choice taken at check-in (protocol/checkin.md "Sharing the position", decisions LEG-12 to LEG-16).

    cd controller && python -m unittest discover -s tests -p "test_card_check.py"
"""

from __future__ import annotations

import logging

from p3support import GM, T0, P3Case, bearer

FUTURE = "2027-12-31"
NUMBER = "MBR-ZQ9917"  # no random id or timestamp can contain it, so the "never logged" checks mean something


def gps(t: int = 1000) -> dict:
    return {"lat": 38.72, "lon": -9.14, "accuracy_m": 5.0, "source": "gps", "t": t}


class CardCheckTests(P3Case):
    def setUp(self):
        super().setUp()
        self.g = self.new_game()
        self.gid = self.g["id"]
        r = self.client.put("/api/v1/checkin/settings", headers=GM, json={
            "confirm": "auto", "federation": "optional", "apd": {"checkin": True, "expiry": True,
                                                                  "accepted": ["apd-a"]}})
        self.assertEqual(r.status_code, 200, r.text)

    def member(self, number=NUMBER, **kw):
        return self.check_in(self.gid, apd_id="apd-a", membership_number=number, membership_expires=FUTURE, **kw)

    def row(self, me):
        return self.ctrl.store.checkin(self.gid, me["player_id"])

    def patch(self, pid, token=None, **body):
        headers = bearer(token) if token else GM
        return self.client.patch(f"/api/v1/games/{self.gid}/checkins/{pid}", headers=headers, json=body)

    def test_a_valid_self_check_in_waits_for_the_card_even_with_confirm_auto(self):
        me = self.member()
        self.assertEqual(me["status"], "pending")
        row = self.row(me)
        self.assertEqual((row["federation_seen"], row["card_checked_at"], row["federation_number"]),
                         (False, None, NUMBER))

    def test_without_a_rule_that_checks_at_check_in_nothing_changes(self):
        self.client.put("/api/v1/checkin/settings", headers=GM, json={"apd": {"checkin": False}})
        self.assertEqual(self.check_in(self.gid)["status"], "checked_in")

    def test_the_tick_records_who_and_when_stores_the_verdict_and_erases_the_number(self):
        me = self.member()
        with self.assertLogs("atalaia.checkin", level=logging.INFO) as logs:
            r = self.patch(me["player_id"], federation_seen=True)
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual((out["status"], out["federation_seen"], out["apd_override"]), ("checked_in", True, False))
        self.assertEqual((out["membership_number"], out["federation_number"]), (None, None))
        self.assertEqual((out["apd_id"], out["membership_expires"]), ("apd-a", FUTURE))
        self.assertEqual((out["apd_status"], out["apd_verdict_on"]), ("valid", "2027-01-15"))
        self.assertEqual((out["card_checked_by"], out["card_checked_at"]), ("gm", T0))
        self.assertTrue(any("card check" in line and "gm" in line for line in logs.output))
        self.assertFalse(any(NUMBER in line for line in logs.output))
        # The stored verdict is what staff and the player keep seeing, whatever the rule does later.
        self.client.put("/api/v1/checkin/settings", headers=GM, json={"apd": {"checkin": True, "accepted": ["x"]}})
        own = self.client.get("/api/v1/checkin/me", headers=bearer(me["token"])).json()
        self.assertEqual((own["apd_status"], own["membership_number"]), ("valid", None))

    def test_a_marshals_tick_names_the_marshal(self):
        _m, mtoken = self.make_marshal(self.gid)
        me = self.member()
        r = self.patch(me["player_id"], mtoken, federation_seen=True)
        self.assertEqual(r.status_code, 200, r.text)
        mine = self.client.get("/api/v1/checkin/me", headers=bearer(mtoken)).json()["player_id"]
        self.assertEqual(r.json()["card_checked_by"], mine)

    def test_a_tick_over_a_verdict_other_than_valid_is_the_marshals_call_and_is_logged(self):
        me = self.check_in(self.gid, apd_id="apd-b", membership_number=NUMBER, membership_expires=FUTURE)
        with self.assertLogs("atalaia.checkin", level=logging.INFO) as logs:
            out = self.patch(me["player_id"], federation_seen=True).json()
        self.assertEqual((out["status"], out["apd_status"], out["apd_override"]),
                         ("checked_in", "not_accepted", True))
        self.assertTrue(any("apd override" in line and "not_accepted" in line for line in logs.output))
        self.assertFalse(any(NUMBER in line for line in logs.output))

    def test_a_confirmation_without_the_card_is_an_override_with_its_reason_and_keeps_the_number(self):
        me = self.member()
        with self.assertLogs("atalaia.checkin", level=logging.INFO) as logs:
            out = self.patch(me["player_id"], status="checked_in").json()
        self.assertEqual((out["status"], out["apd_override"], out["federation_seen"]), ("checked_in", True, False))
        self.assertEqual((out["membership_number"], out["card_checked_by"]), (NUMBER, None))
        self.assertTrue(any("apd override" in line and "no_card" in line for line in logs.output))
        self.assertFalse(any(NUMBER in line for line in logs.output))

    def test_the_app_cannot_put_the_number_back_and_the_tick_is_not_undone_by_a_flag(self):
        me = self.member()
        self.patch(me["player_id"], federation_seen=True)
        self.svc.rate.allow = lambda key: True
        again = self.check_in(self.gid, ident=me["_ident"], expect=200, apd_id="apd-a", membership_number=NUMBER,
                              membership_expires=FUTURE)
        self.assertEqual(again["status"], "checked_in")
        row = self.row(me)
        self.assertEqual((row["federation_number"], row["federation_seen"], row["card_checked_by"]),
                         (None, True, "gm"))
        self.assertEqual(self.patch(me["player_id"], federation_seen=False).status_code, 409)

    def test_new_data_from_staff_replaces_the_check(self):
        me = self.member()
        self.patch(me["player_id"], federation_seen=True)
        out = self.patch(me["player_id"], membership_number="OTHER-1", apd_id="apd-a",
                         membership_expires=FUTURE).json()
        self.assertEqual((out["federation_seen"], out["card_checked_by"], out["apd_verdict_on"]),
                         (False, None, None))
        self.assertEqual(out["membership_number"], "OTHER-1")
        out = self.patch(me["player_id"], federation_seen=True).json()
        self.assertEqual((out["federation_seen"], out["membership_number"]), (True, None))

    def test_a_hand_check_in_with_the_card_erases_and_without_it_is_an_override(self):
        base = {"display_name": "Ana", "membership_number": NUMBER, "apd_id": "apd-a", "membership_expires": FUTURE}
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins", headers=GM, json={**base, "federation_seen": True})
        out = r.json()
        self.assertEqual((r.status_code, out["status"], out["membership_number"], out["card_checked_by"],
                          out["apd_override"], out["apd_status"]), (201, "checked_in", None, "gm", False, "valid"))
        with self.assertLogs("atalaia.checkin", level=logging.INFO) as logs:
            out = self.client.post(f"/api/v1/games/{self.gid}/checkins", headers=GM, json=base).json()
        self.assertEqual((out["status"], out["membership_number"], out["card_checked_by"], out["apd_override"]),
                         ("checked_in", NUMBER, None, True))
        self.assertTrue(any("no_card" in line for line in logs.output))
        self.assertFalse(any(NUMBER in line for line in logs.output))
        bad = self.client.post(f"/api/v1/games/{self.gid}/checkins", headers=GM,
                               json={**base, "federation_seen": "yes"})
        self.assertEqual(bad.status_code, 400)

    def test_an_expected_registered_player_ticked_with_the_card_is_checked_in_and_erased(self):
        data = ("display_name,external_ref,federation_number,apd_id,membership_expires\r\n"
                f"Ana,a1,{NUMBER},apd-a,{FUTURE}\r\n")
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins/import", headers=GM,
                             json={"format": "csv", "data": data, "source": "clube", "basis_confirmed": True})
        self.assertEqual(r.status_code, 200, r.text)
        row = next(c for c in self.client.get(f"/api/v1/games/{self.gid}/checkins", headers=GM).json()["checkins"])
        self.assertEqual((row["status"], row["membership_number"]), ("expected", NUMBER))
        out = self.patch(row["player_id"], federation_seen=True).json()
        self.assertEqual((out["status"], out["membership_number"], out["card_checked_by"], out["apd_status"]),
                         ("checked_in", None, "gm", "valid"))
        # A later import of the same file leaves the arrived player (and the stored check) alone.
        again = self.client.post(f"/api/v1/games/{self.gid}/checkins/import", headers=GM,
                                 json={"format": "csv", "data": data, "source": "clube", "basis_confirmed": True})
        self.assertEqual([e["result"] for e in again.json()["results"]], ["skipped"])
        self.assertIsNone(self.ctrl.store.checkin(self.gid, row["player_id"])["federation_number"])

    def test_the_csv_export_has_who_and_when_and_no_number_after_the_check(self):
        me = self.member()
        self.patch(me["player_id"], federation_seen=True)
        header, line = self.svc.csv_export(self.gid).splitlines()[:2]
        cols, cells = header.split(","), line.split(",")
        self.assertEqual(cells[cols.index("card_checked_by")], "gm")
        self.assertTrue(cells[cols.index("card_checked_at")].startswith("2027-01-15"))
        self.assertEqual((cells[cols.index("federation_number")], cells[cols.index("apd_status")]), ("", "valid"))
        self.assertNotIn(NUMBER, self.svc.csv_export(self.gid))

    def test_leaving_and_the_purge_forget_the_card_check(self):
        a, b = self.member(), self.member("N-2")
        self.patch(a["player_id"], federation_seen=True)
        self.patch(b["player_id"], federation_seen=True)
        self.client.delete("/api/v1/checkin/me", headers=bearer(a["token"]))
        row = self.row(a)
        self.assertEqual((row["card_checked_by"], row["card_checked_at"], row["apd_verdict"], row["apd_verdict_on"]),
                         (None, None, None, None))
        self.client.post(f"/api/v1/games/{self.gid}/end", json={}, headers=GM)
        self.ctrl.store.update_game(self.gid, ended_at=T0)
        self.now = T0 + 31 * 86400
        self.assertEqual(self.svc.purge(force=True)["checkins"], 1)
        row = self.row(b)
        self.assertEqual((row["card_checked_by"], row["apd_verdict"], row["apd_id"], row["membership_expires"]),
                         (None, None, None, None))


class PositionSharingTests(P3Case):
    def setUp(self):
        super().setUp()
        self.gid = self.new_game()["id"]
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})

    def report(self, token, t=1000):
        return self.client.post("/api/v1/positions", headers=bearer(token), json=gps(t))

    def test_the_choice_is_off_unless_ticked_and_declining_blocks_nothing(self):
        yes = self.check_in(self.gid, share_position=True)
        no = self.check_in(self.gid, share_position=False)
        silent = self.check_in(self.gid, name="Rui", share_position=None)  # an older app says nothing: not sharing
        row = self.ctrl.store.checkin(self.gid, silent["player_id"])
        self.assertEqual(row["position_share"], False)
        self.assertEqual(row["position_share_notice"], 2)
        self.assertEqual(row["position_share_at"], T0)
        for who in (no, silent):
            self.assertEqual(who["status"], "checked_in")  # the check-in and the game go on (Art. 7(4))
            r = self.report(who["token"])
            self.assertEqual(r.status_code, 409, r.text)
            self.assertIn("position_sharing_off", r.text)
        self.assertEqual(self.report(yes["token"]).status_code, 200)

    def test_a_notice_bump_turns_an_older_yes_off_until_asked_again(self):
        """NV-3: a yes given under an older notice is not a yes under the new one."""
        me = self.check_in(self.gid, share_position=True)
        self.assertEqual(self.report(me["token"]).status_code, 200)
        self.assertEqual(len(self.client.get("/api/v1/positions", headers=GM).json()["positions"]), 1)
        self.svc.cfg.notice_version = 3  # the field raises the version
        r = self.report(me["token"], 2000)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("position_sharing_off", r.text)
        self.assertEqual(self.client.get("/api/v1/positions", headers=GM).json()["positions"], [])
        mine = self.client.get("/api/v1/checkin/me", headers=bearer(me["token"])).json()
        self.assertFalse(mine["position_share"])
        # A check-in with the old version is refused with a code the app turns into "read it again".
        r = self.client.post("/api/v1/checkin", json={
            "game_id": self.gid, "player_id": me["_ident"][0], "player_secret": me["_ident"][1],
            "display_name": "Falcão", "notice_version": 2, "share_position": True})
        self.assertEqual(r.status_code, 409)
        self.assertIn("notice_version_changed", r.text)
        # The switch in the app names the notice it showed: a stale one is refused, the current one is a new yes.
        put = lambda body: self.client.put("/api/v1/checkin/me/position-sharing", headers=bearer(me["token"]),
                                           json=body)
        stale = put({"share_position": True, "notice_version": 2})
        self.assertEqual(stale.status_code, 409)
        self.assertIn("notice_version_changed", stale.text)
        self.assertFalse(self.client.get("/api/v1/checkin/me", headers=bearer(me["token"])).json()["position_share"])
        self.assertEqual(put({"share_position": True, "notice_version": 3}).status_code, 200)
        self.assertEqual(self.report(me["token"], 3000).status_code, 200)

    def test_the_player_stops_and_starts_any_time_and_stopping_drops_the_position(self):
        me = self.check_in(self.gid, share_position=True)
        self.report(me["token"])
        self.assertEqual(len(self.client.get("/api/v1/positions", headers=GM).json()["positions"]), 1)
        self.now += 60
        r = self.client.put("/api/v1/checkin/me/position-sharing", headers=bearer(me["token"]),
                            json={"share_position": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["position_share"], r.json()["position_share_at"],
                          r.json()["position_share_notice"]), (False, T0 + 60, 2))
        self.assertEqual(self.client.get("/api/v1/positions", headers=GM).json()["positions"], [])
        self.assertEqual(self.report(me["token"], 2000).status_code, 409)
        bad = self.client.put("/api/v1/checkin/me/position-sharing", headers=bearer(me["token"]),
                              json={"share_position": "on"})
        self.assertEqual(bad.status_code, 400)
        self.client.put("/api/v1/checkin/me/position-sharing", headers=bearer(me["token"]),
                        json={"share_position": True})
        self.assertEqual(self.report(me["token"], 3000).status_code, 200)

    def test_the_choice_is_asked_again_on_a_new_check_in_only_when_sent(self):
        me = self.check_in(self.gid, share_position=True)
        self.svc.rate.allow = lambda key: True
        self.check_in(self.gid, ident=me["_ident"], expect=200)  # says nothing: unchanged
        self.assertTrue(self.ctrl.store.checkin(self.gid, me["player_id"])["position_share"])
        self.check_in(self.gid, ident=me["_ident"], expect=200, share_position=False)
        self.assertFalse(self.ctrl.store.checkin(self.gid, me["player_id"])["position_share"])
        bad = self.check_in(self.gid, ident=me["_ident"], expect=400, share_position="yes")
        self.assertIn("share_position", str(bad))

    def test_a_hand_check_in_records_the_choice_too(self):
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins", headers=GM,
                             json={"display_name": "Ana", "share_position": True})
        self.assertEqual((r.status_code, r.json()["position_share"], r.json()["position_share_notice"]),
                         (201, True, 2))
        r = self.client.post(f"/api/v1/games/{self.gid}/checkins", headers=GM, json={"display_name": "Rui"})
        self.assertEqual(r.json()["position_share"], False)

    def test_leaving_drops_the_choice_and_the_position(self):
        me = self.check_in(self.gid, share_position=True)
        self.report(me["token"])
        self.client.delete("/api/v1/checkin/me", headers=bearer(me["token"]))
        self.assertEqual(self.client.get("/api/v1/positions", headers=GM).json()["positions"], [])
        self.assertFalse(self.ctrl.store.checkin(self.gid, me["player_id"])["position_share"])
