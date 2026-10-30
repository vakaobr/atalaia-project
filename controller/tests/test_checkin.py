# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Field check-in (ADR-P3-13, plan phase E, AC-13): the endpoints and their rules, player tokens
(decision B8: the controller's own per-game key), role re-checks, the role-filtered stream, and
the privacy rules (constraint 26: no names in events, MQTT, logs or read-token views).

    cd controller && python -m unittest discover -s tests

Everything runs in-process over the real engine and store, with no internet and no radio.
"""

from __future__ import annotations

import io
import logging
import os
import stat
import unittest

from p3support import GM, READ, T0, Marshal, P3Case, bearer, declaration, new_identity
from atalaia_controller import player_token
from atalaia_controller.mqtt import MqttBridge
from starlette.websockets import WebSocketDisconnect

NAME = "Falcão Peregrino"
FED = "FPA-12345"


def sentinel(ctrl) -> None:
    ctrl._emit({"type": "pong", "sentinel": True})


def until_sentinel(ws) -> list[dict]:
    got = []
    while True:
        m = ws.receive_json()
        if m.get("sentinel"):
            return got
        got.append(m)


class CheckinTests(P3Case):
    def test_info_lists_open_games_without_names(self):
        g = self.new_game()
        self.check_in(g["id"], name=NAME)
        info = self.info()
        self.assertEqual([x["game_id"] for x in info["games"]], [g["id"]])
        self.assertEqual(info["field"]["id"], "field")
        self.assertEqual(info["settings"]["confirm"], "auto")
        self.assertIn("rifle", info["limits"]["classes"])
        self.assertEqual(info["notice"]["version"], 1)
        self.assertIn("30", info["notice"]["pt"])  # the retention in the default notice
        self.assertNotIn("Falc", self.client.get("/api/v1/checkin").text)
        self.client.post(f"/api/v1/games/{g['id']}/checkin/close", headers=GM)
        self.assertEqual(self.info()["games"], [])

    def test_check_in_issues_a_player_token(self):
        g = self.new_game()
        me = self.check_in(g["id"], name=NAME, team_preference="blue")
        self.assertEqual((me["status"], me["role"], me["team"], me["squad"]), ("checked_in", "player", None, 0))
        key = self.ctrl.store.token_key(g["id"])
        self.assertEqual(len(key), 32)
        self.assertNotEqual(key[:16], self.ctrl.game_key(g["id"]))  # B8: not the game key
        claims = player_token.verify(me["token"], key, game_id=g["id"], team_count=2, now=int(T0))
        self.assertEqual((claims["player_id"], claims["role"]), (me["player_id"], "player"))
        # exp: the end of the field's day (the game has not started, so no planned end yet).
        self.assertEqual(me["exp"], int(T0) + 14 * 3600)
        r = self.client.get("/api/v1/checkin/me", headers=bearer(me["token"]))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["display_name"], r.json()["team_preference"]), (NAME, "blue"))
        who = self.client.get("/api/v1/whoami", headers=bearer(me["token"])).json()
        self.assertEqual((who["role"], who["player_role"]), ("player", "player"))

    def test_token_exp_is_the_planned_end_plus_two_hours(self):
        g = self.new_game(duration_ms=3_600_000)
        self.ctrl.store.update_game(g["id"], started_at=T0)
        me = self.check_in(g["id"])
        self.assertEqual(me["exp"], int(T0 + 3600 + 7200))

    def test_a_known_id_needs_its_secret(self):
        g = self.new_game()
        me = self.check_in(g["id"])
        pid, secret = me["_ident"]
        self.check_in(g["id"], ident=(pid, new_identity()[1]), expect=409)
        again = self.check_in(g["id"], ident=(pid, secret), expect=200, name="Falcão 2")
        self.assertEqual(again["player_id"], pid)
        self.assertEqual(len(self.svc.list_checkins(self.svc_viewer(), g["id"])["checkins"]), 1)

    def svc_viewer(self):
        from atalaia_controller.checkin import Viewer
        return Viewer("gm")

    def test_closed_check_in_and_bad_requests(self):
        g = self.new_game()
        self.client.post(f"/api/v1/games/{g['id']}/checkin/close", headers=GM)
        self.check_in(g["id"], expect=403)
        self.client.post(f"/api/v1/games/{g['id']}/checkin/open", headers=GM)
        self.check_in(g["id"], expect=201)
        self.check_in(g["id"], name="", expect=400)
        self.check_in(g["id"], notice_version=2, expect=409)
        self.check_in(9999 if g["id"] != 9999 else 9998, expect=404)
        r = self.client.post("/api/v1/checkin", json={"game_id": g["id"], "player_id": "x"})
        self.assertEqual(r.status_code, 400)
        self.check_in(g["id"], replicas=[declaration(rclass="laser")], expect=400)
        self.check_in(g["id"], replicas=[declaration() for _ in range(6)], expect=400)

    def test_rate_limit_and_cap(self):
        g = self.new_game()
        for _ in range(10):
            self.check_in(g["id"])
        self.check_in(g["id"], expect=429)  # 10 a minute from one address
        self.svc.rate.allow = lambda key: True
        self.client.put("/api/v1/checkin/settings", json={"max_players": 11}, headers=GM)
        self.check_in(g["id"])
        r = self.check_in(g["id"], expect=403)
        self.assertIn("full", r["detail"])

    def test_staff_confirm_mode(self):
        self.client.put("/api/v1/checkin/settings", json={"confirm": "staff"}, headers=GM)
        g = self.new_game()
        me = self.check_in(g["id"], name=NAME)
        self.assertEqual(me["status"], "pending")
        self.assertEqual(self.events(g["id"], "player.checkin"), [])
        # A pending player already has a token and can declare replicas.
        r = self.client.put("/api/v1/checkin/me/replicas", headers=bearer(me["token"]),
                            json={"replicas": [declaration()]})
        self.assertEqual(r.status_code, 200, r.text)
        m, mtoken = self.make_marshal(g["id"])
        r = self.client.patch(f"/api/v1/games/{g['id']}/checkins/{me['player_id']}", headers=bearer(mtoken),
                              json={"status": "checked_in", "federation_seen": True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["status"], "checked_in")
        evs = self.events(g["id"], "player.checkin")
        self.assertEqual([e["data"]["player"] for e in evs][-1], me["player_id"])
        # A marshal cannot change teams or roles: that is the GM's.
        r = self.client.patch(f"/api/v1/games/{g['id']}/checkins/{me['player_id']}", headers=bearer(mtoken),
                              json={"role": "gm"})
        self.assertEqual(r.status_code, 403)

    def test_player_checkin_event_once_with_the_id_only(self):
        g = self.new_game()
        me = self.check_in(g["id"], name=NAME, federation_number=FED)
        self.client.post("/api/v1/checkin/token", headers=bearer(me["token"]))
        self.check_in(g["id"], ident=me["_ident"], name=NAME, expect=200)
        evs = self.events(g["id"], "player.checkin")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0]["data"], {"player": me["player_id"]})
        self.assertEqual(evs[0]["node"], self.ctrl.node_id)
        self.gm_patch(g["id"], me["player_id"], team="red")
        self.assertEqual(len(self.events(g["id"], "player.checkin")), 1)

    def test_role_change_new_token_and_old_one_downgraded(self):
        g = self.new_game(squads=3)
        me = self.check_in(g["id"])
        pid, old = me["player_id"], me["token"]
        self.gm_patch(g["id"], pid, role="marshal", team="blue", squad=3)
        # The old token keeps only what the row still allows: a player, on the row's team.
        who = self.client.get("/api/v1/whoami", headers=bearer(old)).json()
        self.assertEqual((who["player_role"], who["team"], who["squad"], who["stale"]), ("player", 2, 3, True))
        r = self.client.get(f"/api/v1/games/{g['id']}/checkins", headers=bearer(old))
        self.assertEqual(r.status_code, 403)
        new = self.client.post("/api/v1/checkin/token", headers=bearer(old)).json()
        self.assertEqual((new["role"], new["team"], new["squad"]), ("marshal", "blue", 3))
        r = self.client.get(f"/api/v1/games/{g['id']}/checkins", headers=bearer(new["token"]))
        self.assertEqual(r.status_code, 200)
        # A demotion takes effect at once on the newer token too.
        self.gm_patch(g["id"], pid, role="player")
        r = self.client.get(f"/api/v1/games/{g['id']}/checkins", headers=bearer(new["token"]))
        self.assertEqual(r.status_code, 403)

    def test_squads_only_in_games_that_have_them(self):
        small = self.new_game()
        self.assertEqual(small["squads"], 0)
        a = self.check_in(small["id"])
        for body in ({"squad": 1}, {"role": "squad_leader"}):
            r = self.client.patch(f"/api/v1/games/{small['id']}/checkins/{a['player_id']}", json=body, headers=GM)
            self.assertEqual(r.status_code, 400, body)
            self.assertIn("no squads", r.json()["detail"])
        self.assertEqual(self.info()["games"][0]["squads"], 0)
        self.client.post(f"/api/v1/games/{small['id']}/end", json={}, headers=GM)
        r = self.client.post("/api/v1/games", headers=GM, json={"name": "Milsim", "mode_id": "org.atalaia.domination",
                                                                 "teams": ["red", "blue"], "squads": 17})
        self.assertEqual(r.status_code, 400)
        big = self.new_game(name="Milsim", squads=3)
        self.assertEqual((big["squads"], self.info()["games"][0]["squads"]), (3, 3))
        b = self.check_in(big["id"])
        r = self.client.patch(f"/api/v1/games/{big['id']}/checkins/{b['player_id']}", json={"squad": 2}, headers=GM)
        self.assertEqual(r.status_code, 400)  # a squad is inside a team
        row = self.gm_patch(big["id"], b["player_id"], team="blue", squad=2, role="squad_leader")
        self.assertEqual((row["team"], row["squad"], row["role"]), ("blue", 2, "squad_leader"))
        r = self.client.patch(f"/api/v1/games/{big['id']}/checkins/{b['player_id']}", json={"squad": 4}, headers=GM)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.chrono_list(big["id"])["squads"], 3)

    def test_removed_and_left_tokens_are_refused(self):
        g = self.new_game()
        a = self.check_in(g["id"], name=NAME, federation_number=FED)
        b = self.check_in(g["id"])
        r = self.client.delete(f"/api/v1/games/{g['id']}/checkins/{a['player_id']}", headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.client.get("/api/v1/checkin/me", headers=bearer(a["token"])).status_code, 401)
        self.check_in(g["id"], ident=a["_ident"], expect=403)  # removed by staff stays removed
        row = self.ctrl.store.checkin(g["id"], a["player_id"])
        self.assertEqual((row["display_name"], row["federation_number"]), (None, None))
        # Leaving: the personal fields are erased.
        r = self.client.delete("/api/v1/checkin/me", headers=bearer(b["token"]))
        self.assertEqual(r.json()["status"], "left")
        row = self.ctrl.store.checkin(g["id"], b["player_id"])
        self.assertEqual((row["status"], row["display_name"]), ("left", None))
        self.assertEqual(self.client.get("/api/v1/checkin/me", headers=bearer(b["token"])).status_code, 401)
        # Coming back is a new check-in.
        again = self.check_in(g["id"], ident=b["_ident"], expect=200)
        self.assertEqual(again["status"], "checked_in")

    def test_tokens_survive_a_restart(self):
        g = self.new_game()
        me = self.check_in(g["id"], name=NAME)
        key = self.ctrl.store.token_key(g["id"])
        self.restart()
        self.assertEqual(self.ctrl.store.token_key(g["id"]), key)
        r = self.client.get("/api/v1/checkin/me", headers=bearer(me["token"]))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["display_name"], NAME)

    def test_store_and_tls_files_are_private(self):
        if os.name != "posix":
            self.skipTest("file modes are POSIX")  # the tests run in the Linux container
        db = self.cfg.db_path
        for path in (db, db + "-wal", self.bundle.tls.server_key, self.bundle.tls.dir / "ca.key"):
            if os.path.exists(path):
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600, path)

    def test_retention_purge(self):
        g = self.new_game()
        me = self.check_in(g["id"], name=NAME, federation_number=FED, replicas=[declaration()])
        self.client.post(f"/api/v1/games/{g['id']}/end", json={}, headers=GM)
        self.ctrl.store.update_game(g["id"], ended_at=T0)
        self.now = T0 + 29 * 86400
        self.assertEqual(self.svc.purge(force=True)["checkins"], 0)
        self.now = T0 + 31 * 86400
        out = self.svc.purge(force=True)
        self.assertEqual((out["checkins"], out["declarations"]), (1, 1))
        row = self.ctrl.store.checkin(g["id"], me["player_id"])
        self.assertEqual((row["display_name"], row["federation_number"], row["team_preference"]),
                         (None, None, None))
        self.assertIsNotNone(self.ctrl.store.field_player(me["player_id"]))
        self.now = T0 + 366 * 86400
        self.assertEqual(self.svc.purge(force=True)["identities"], 1)
        self.assertIsNone(self.ctrl.store.field_player(me["player_id"]))

    def test_the_retention_settings_default_to_a_year_and_90_days_and_are_the_gms(self):
        st = self.client.get("/api/v1/checkin/settings", headers=GM).json()
        self.assertEqual((st["chrono_retention_days"], st["game_retention_days"]), (365, 90))
        for bad in (29, 3654, "90", True, None):
            r = self.client.put("/api/v1/checkin/settings", json={"game_retention_days": bad}, headers=GM)
            self.assertEqual(r.status_code, 400, bad)
        r = self.client.put("/api/v1/checkin/settings", json={"chrono_retention_days": 90, "game_retention_days": 400},
                            headers=GM)
        self.assertEqual((r.status_code, r.json()["chrono_retention_days"], r.json()["game_retention_days"]),
                         (200, 90, 400))
        self.restart()  # saved with the other check-in settings
        st = self.client.get("/api/v1/checkin/settings", headers=GM).json()
        self.assertEqual((st["chrono_retention_days"], st["game_retention_days"]), (90, 400))
        # Not told to a player's app (like max_players), and the notice says the days.
        self.assertNotIn("game_retention_days", self.info()["settings"])
        self.assertNotIn("chrono_retention_days", self.info()["settings"])
        self.assertEqual(self.client.put("/api/v1/checkin/settings", json={"federation": "off"},
                                         headers=GM).json()["game_retention_days"], 400)

    def test_chrono_readings_follow_the_fields_retention(self):
        marshal = Marshal()
        rec = marshal.reading("0f6e5d4c-3b2a-4198-8776-655443322110", "p-rita", 100.0, when=T0)
        self.ctrl.store.add_reading(rec, "0f6e5d4c-3b2a-4198-8776-655443322111", "pass", T0)
        self.now = T0 + 100 * 86400
        self.assertEqual(self.svc.purge(force=True)["readings"], 0)  # a year by default
        self.client.put("/api/v1/checkin/settings", json={"chrono_retention_days": 90}, headers=GM)
        self.ctrl.store.record_erasure("p-old", chrono=True, identity=False, now=T0)
        out = self.svc.purge(force=True)
        self.assertEqual((out["readings"], out["erasure_records"]), (1, 1))

    def test_an_ended_game_is_purged_after_the_game_retention(self):
        old, young = self.new_game(), None
        self.check_in(old["id"], name=NAME)
        self.client.post(f"/api/v1/games/{old['id']}/end", json={}, headers=GM)
        young = self.new_game()
        self.check_in(young["id"], name=NAME)
        self.client.post(f"/api/v1/games/{young['id']}/end", json={}, headers=GM)
        live = self.new_game()
        self.ctrl.store.update_game(old["id"], ended_at=T0)
        self.ctrl.store.update_game(young["id"], ended_at=T0 + 300 * 86400)
        store = self.ctrl.store
        store.insert_event(old["id"], {"node": 4, "seq": 1, "t": 10, "type": "zone.captured", "team": "red"})
        store.save_scores(old["id"], {"red": 5})
        store.upsert_node(old["id"], 4, "alpha", "zone", {})
        logged = store.count_events(old["id"])
        self.assertGreaterEqual(logged, 1)
        self.now = T0 + 89 * 86400
        self.assertEqual(self.svc.purge(force=True)["games"], 0)  # 90 days by default (2026-10-30)
        self.now = T0 + 91 * 86400
        out = self.svc.purge(force=True)
        self.assertEqual((out["games"], out["game_events"]), (1, logged))
        self.assertIsNone(store.game(old["id"]))
        self.assertEqual((store.count_events(old["id"]), store.scores(old["id"]), store.nodes(old["id"])), (0, {}, []))
        self.assertEqual(store.checkins(old["id"]), [])
        self.assertIsNone(store.token_key(old["id"]))
        self.assertIsNotNone(store.game(young["id"]))  # not 90 days yet
        self.assertIsNotNone(store.game(live["id"]))   # never a game that has not ended
        self.now = T0 + 366 * 86400
        self.client.put("/api/v1/checkin/settings", json={"game_retention_days": 30}, headers=GM)
        self.assertEqual(self.svc.purge(force=True)["games"], 1)  # the field's own days

    def test_a_purged_games_team_results_stay_365_days_without_a_player(self):
        """SR-88: written as the game goes, no player id, no member list, no squad; gone 365 days after it ended."""
        store = self.ctrl.store
        games = []
        for _ in range(3):
            g = self.new_game()
            self.check_in(g["id"], name=NAME)
            self.client.post(f"/api/v1/games/{g['id']}/end", json={}, headers=GM)
            games.append(g)
        won, tied, old = games
        store.update_game(won["id"], ended_at=T0)
        store.update_game(tied["id"], ended_at=T0 + 3 * 86400)
        store.update_game(old["id"], ended_at=T0 - 200 * 86400)
        store.save_scores(won["id"], {"red": 9, "blue": 4})
        store.save_scores(tied["id"], {"red": 3, "blue": 3})
        self.now = T0 + 89 * 86400
        self.assertEqual(self.svc.purge(force=True)["games"], 1)  # only the old one is past 90 days
        self.now = T0 + 95 * 86400
        out = self.svc.purge(force=True)
        self.assertEqual((out["games"], out["game_results_expired"]), (2, 0))
        got = store.game_results()  # newest first: tied (T0 + 3 days), won (T0), old
        self.assertEqual(len(got), 3)
        self.assertEqual((got[1]["winner"], got[1]["team_totals"]), ("red", {"red": 9, "blue": 4}))
        self.assertEqual((got[0]["winner"], got[0]["team_totals"]), (None, {"red": 3, "blue": 3}))  # a tie has none
        self.assertEqual((got[2]["winner"], got[2]["team_totals"]), (None, {"red": 0, "blue": 0}))   # no points
        for r in got:
            self.assertEqual(set(r), {"name", "mode_id", "teams", "team_totals", "winner", "state", "duration_ms",
                                      "started_at", "ended_at"})
        self.assertEqual(self.client.get("/api/v1/game-results", headers=GM).json()["results"], got)
        self.now = T0 + 366 * 86400
        self.assertEqual(self.svc.purge(force=True)["game_results_expired"], 2)  # the ones that ended up to T0
        self.assertEqual([r["team_totals"] for r in store.game_results()], [{"red": 3, "blue": 3}])
        self.now = T0 + 376 * 86400
        self.svc.purge(force=True)
        self.assertEqual(store.game_results(), [])

    def test_a_game_past_a_year_when_it_goes_leaves_no_result(self):
        old = self.new_game()
        self.client.post(f"/api/v1/games/{old['id']}/end", json={}, headers=GM)
        self.ctrl.store.update_game(old["id"], ended_at=T0)
        self.client.put("/api/v1/checkin/settings", json={"game_retention_days": 730}, headers=GM)
        self.now = T0 + 731 * 86400
        self.assertEqual(self.svc.purge(force=True)["games"], 1)
        self.assertEqual(self.ctrl.store.game_results(), [])

    def test_a_game_the_site_server_has_not_confirmed_is_kept(self):
        """RET-3: with the sync on, the controller's copy is the only one until the site server has all of it."""
        self.cfg.sync_enabled = True
        old = self.new_game()
        self.client.post(f"/api/v1/games/{old['id']}/end", json={}, headers=GM)
        done = self.new_game()
        self.client.post(f"/api/v1/games/{done['id']}/end", json={}, headers=GM)
        for g in (old, done):
            self.ctrl.store.update_game(g["id"], ended_at=T0)
        self.ctrl.store.save_sync_state(done["id"], self.ctrl.store.game(done["id"])["game_seed"], final=True)
        self.now = T0 + 400 * 86400
        out = self.svc.purge(force=True)
        self.assertEqual((out["games"], out["games_unsynced_kept"]), (1, 1))
        self.assertIsNone(self.ctrl.store.game(done["id"]))
        self.assertIsNotNone(self.ctrl.store.game(old["id"]))
        self.cfg.sync_enabled = False  # no site server: age alone decides
        self.assertEqual(self.svc.purge(force=True)["games"], 1)

    def test_an_erasure_is_recorded_for_the_site_server_only_with_a_sync(self):
        g = self.new_game()
        me = self.check_in(g["id"], name=NAME)
        self.client.delete(f"/api/v1/players/{me['player_id']}", headers=GM)
        self.assertEqual(self.ctrl.store.erasures(), [])  # no sync, nothing kept
        self.cfg.sync_enabled = True
        self.client.delete(f"/api/v1/players/{me['player_id']}/chrono", headers=GM)
        self.client.delete("/api/v1/players/p-bea?chrono=true", headers=GM)
        self.client.delete("/api/v1/players/p-rita", headers=GM)
        self.assertEqual({e["player_id"]: (e["chrono"], e["identity"]) for e in self.ctrl.store.erasures()},
                         {me["player_id"]: (True, False), "p-bea": (True, True), "p-rita": (False, True)})

    def test_federation_number(self):
        g = self.new_game()
        me = self.check_in(g["id"], federation_number=FED)
        self.assertIsNone(self.ctrl.store.checkin(g["id"], me["player_id"])["federation_number"])  # off
        self.client.put("/api/v1/checkin/settings", json={"federation": "required"}, headers=GM)
        r = self.check_in(g["id"], expect=400)
        self.assertIn("FPA", r["detail"])
        # Nothing ever checks the number's content.
        me = self.check_in(g["id"], federation_number="não sei, perguntem-me!")
        row = self.ctrl.store.checkin(g["id"], me["player_id"])
        self.assertEqual((row["federation_number"], row["federation_seen"]), ("não sei, perguntem-me!", False))

    def test_manual_check_in(self):
        g = self.new_game()
        r = self.client.post(f"/api/v1/games/{g['id']}/checkins", headers=GM,
                             json={"display_name": "Sem App", "replicas": [declaration(rclass="dmr")]})
        self.assertEqual(r.status_code, 201, r.text)
        row = r.json()
        self.assertTrue(row["manual"])
        self.assertRegex(row["player_id"], r"^p-[a-z2-7]{12}$")
        self.assertEqual(row["declarations"][0]["state"], "pending")
        # Nobody can take a hand check-in's id from an app.
        self.check_in(g["id"], ident=(row["player_id"], new_identity()[1]), expect=409)
        r = self.client.post(f"/api/v1/games/{g['id']}/checkins", headers=READ, json={"display_name": "x"})
        self.assertEqual(r.status_code, 403)

    def test_csv_export(self):
        g = self.new_game()
        self.check_in(g["id"], name="=HYPERLINK(1)", replicas=[declaration()])
        r = self.client.get(f"/api/v1/games/{g['id']}/checkins.csv", headers=GM)
        self.assertEqual(r.status_code, 200)
        text = r.content.decode("utf-8-sig")
        self.assertIn("'=HYPERLINK(1)", text)  # no formula in a spreadsheet
        self.assertIn("pending", text)
        self.assertEqual(self.client.get(f"/api/v1/games/{g['id']}/checkins.csv", headers=READ).status_code, 403)

    def test_declarations(self):
        g = self.new_game()
        me = self.check_in(g["id"])
        r = self.client.put("/api/v1/checkin/me/replicas", headers=bearer(me["token"]),
                            json={"replicas": [declaration(make_model="Tokyo Marui"), declaration(rclass="dmr")]})
        self.assertEqual(r.status_code, 200, r.text)
        decls = r.json()["declarations"]
        self.assertEqual([d["state"] for d in decls], ["pending", "pending"])
        r = self.client.put("/api/v1/checkin/me/replicas", headers=bearer(me["token"]),
                            json={"replicas": [{**declaration(), "state": "passed"}]})
        self.assertEqual(r.status_code, 400)  # the state is the controller's
        # Withdrawing a pending replica is fine.
        r = self.client.put("/api/v1/checkin/me/replicas", headers=bearer(me["token"]),
                            json={"replicas": [{k: v for k, v in decls[0].items()
                                                if k in ("declaration_id", "type", "class", "make_model")}]})
        states = {d["declaration_id"]: d["state"] for d in r.json()["declarations"]}
        self.assertEqual(states[decls[1]["declaration_id"]], "withdrawn")
        # Another player cannot reuse someone's declaration id.
        other = self.check_in(g["id"])
        r = self.client.put("/api/v1/checkin/me/replicas", headers=bearer(other["token"]),
                            json={"replicas": [{"declaration_id": decls[0]["declaration_id"], "type": "aeg",
                                                "class": "rifle"}]})
        self.assertEqual(r.status_code, 409)


class StreamAndPrivacyTests(P3Case):
    def test_stream_by_role(self):
        g = self.new_game()
        a = self.check_in(g["id"], name=NAME, federation_number=FED)
        with self.client.websocket_connect("/api/v1/stream?token=read-secret") as read, \
                self.client.websocket_connect("/api/v1/stream?token=gm-secret") as gm, \
                self.client.websocket_connect(f"/api/v1/stream?token={a['token']}") as mine:
            for ws in (read, gm, mine):
                self.assertEqual(ws.receive_json()["type"], "hello")
            b = self.check_in(g["id"], name="Outra Pessoa")
            self.client.put("/api/v1/checkin/me/replicas", headers=bearer(a["token"]),
                            json={"replicas": [declaration()]})
            sentinel(self.ctrl)
            got_read, got_gm, got_mine = until_sentinel(read), until_sentinel(gm), until_sentinel(mine)
        self.assertNotIn("checkin", {m["type"] for m in got_read})
        self.assertNotIn("Pessoa", str(got_read))
        self.assertIn("Outra Pessoa", str(got_gm))
        self.assertTrue(any(m["type"] == "chrono_list" for m in got_gm))
        # The player sees their own rows only, and no routing marks leave the controller.
        mine_rows = [m for m in got_mine if m["type"] in ("checkin", "chrono_list")]
        self.assertTrue(mine_rows)
        self.assertTrue(all(m.get("checkin", {}).get("player_id", m.get("player_id")) == a["player_id"]
                            for m in mine_rows))
        self.assertNotIn("Outra", str(got_mine))
        self.assertFalse(any(k.startswith("_") for m in got_gm + got_mine for k in m))
        self.assertTrue(any(m["type"] == "event" and m["event"]["data"].get("player") == b["player_id"]
                            for m in got_mine))  # events are public, with the id only

    def test_player_stream_hello_has_history_and_me(self):
        g = self.new_game()
        self.client.post(f"/api/v1/games/{g['id']}/start", headers=GM, json={"force": True})
        a = self.check_in(g["id"], name=NAME)
        with self.client.websocket_connect(f"/api/v1/stream?token={a['token']}") as ws:
            hello = ws.receive_json()
        self.assertEqual(hello["me"]["display_name"], NAME)
        self.assertEqual([e["type"] for e in hello["events"]], ["game.start", "player.checkin"])
        self.assertNotIn("modem", hello["status"])  # no controller internals for players

    def test_assignment_change_closes_the_player_stream(self):
        g = self.new_game()
        a = self.check_in(g["id"])
        with self.client.websocket_connect(f"/api/v1/stream?token={a['token']}") as ws:
            ws.receive_json()
            self.gm_patch(g["id"], a["player_id"], team="red")
            msgs = []
            with self.assertRaises(WebSocketDisconnect) as cm:
                while True:
                    msgs.append(ws.receive_json())
        self.assertEqual(cm.exception.code, 4409)
        self.assertTrue(any(m["type"] == "checkin" and m["assignment"] for m in msgs))

    def test_names_never_reach_events_mqtt_logs_or_read_views(self):
        buf = io.StringIO()
        handler = logging.StreamHandler(buf)
        root = logging.getLogger("atalaia")
        level = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        published = []
        bridge = MqttBridge(self.cfg, self.ctrl)
        bridge._publish = lambda topic, payload, retain=False: published.append((topic, payload))
        try:
            g = self.new_game()
            self.client.post(f"/api/v1/games/{g['id']}/start", headers=GM, json={"force": True})
            me = self.check_in(g["id"], name=NAME, team_preference="red", replicas=[declaration()])
            self.client.put("/api/v1/checkin/settings", json={"federation": "optional"}, headers=GM)
            self.check_in(g["id"], ident=me["_ident"], name=NAME, federation_number=FED, expect=200)
            self.gm_patch(g["id"], me["player_id"], team="red")
            self.client.post(f"/api/v1/games/{g['id']}/checkins", headers=GM, json={"display_name": "Sem App Nome"})
        finally:
            root.removeHandler(handler)
            root.setLevel(level)
        self.assertTrue(published)  # the bridge did publish the game's events
        for text in (str(published), buf.getvalue(), self.everything_public(g["id"])):
            for secret in ("Falc", "Peregrino", FED, "Sem App Nome"):
                self.assertNotIn(secret, text)
        self.assertIn(me["player_id"], str(published))  # the event, with the id


if __name__ == "__main__":
    unittest.main()
