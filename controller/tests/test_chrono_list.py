# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The "replicas to chrono" list (ADR-P3-13): signed readings from a marshal's phone, verified with
the marshal's registered Ed25519 key (controller/atalaia_controller/chrono.py and the shared vectors of
protocol/vectors/chrono_record.json), make declarations passed or refused; nothing else does.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path

from p3support import GM, READ, T0, Marshal, P3Case, bearer, declaration

# The rifle limit of the Portugal template is 1.14 J: 106.8 m/s with 0.20 g is 1.141 J (over),
# 105 m/s is 1.103 J (under).
PASS = [100.0, 104.5, 105.0]
FAIL = [104.0, 106.8, 103.0]
VECTORS = json.loads((Path(__file__).resolve().parents[2] / "protocol" / "vectors" / "chrono_record.json")
                     .read_text(encoding="utf-8"))


class ChronoListTests(P3Case):
    def setUp(self):
        super().setUp()
        self.game = self.new_game()
        self.gid = self.game["id"]
        self.marshal, self.mtoken = self.make_marshal(self.gid)

    def player(self, *replicas: str, name: str = "Jogador"):
        decls = [declaration(r) for r in replicas]
        me = self.check_in(self.gid, name=name, replicas=decls)
        return me, decls

    def states(self, me) -> dict[str, str]:
        r = self.client.get("/api/v1/checkin/me", headers=bearer(me["token"])).json()
        return {d["replica_id"] or d["declaration_id"]: d["state"] for d in r["declarations"]}

    def test_pass_fail_and_retest(self):
        r1, r2 = str(uuid.uuid4()), str(uuid.uuid4())
        me, _ = self.player(r1, r2)
        pid = me["player_id"]
        self.assertEqual(self.states(me), {r1: "pending", r2: "pending"})
        cl = self.chrono_list(self.gid)
        self.assertEqual(cl["counts"], {"pending": 2, "passed": 0, "refused": 0})
        out = self.upload(self.mtoken, self.marshal.series(r1, pid, PASS, game_id=self.gid))
        self.assertEqual((out["outcome"], out["class"], out["limit_j"]), ("pass", "rifle", 1.14))
        # PKD-3: the class limit the series was judged against is kept with its readings, for the site sync.
        self.assertEqual({r["limit_j"] for r in self.ctrl.store.readings_unsynced(10)}, {1.14})
        failing = self.marshal.series(r2, pid, FAIL, game_id=self.gid)
        self.assertEqual(self.upload(self.mtoken, failing)["outcome"], "fail")
        self.assertEqual(self.states(me), {r1: "passed", r2: "refused"})
        # A retest that passes after adjustment: passed, and both series stay.
        retest = self.marshal.series(r2, pid, [101.0, 102.0], rtype="retest", game_id=self.gid,
                                     ref=failing[1]["reading_id"])
        self.assertEqual(self.upload(self.mtoken, retest)["outcome"], "pass")
        self.assertEqual(self.states(me)[r2], "passed")
        self.assertEqual(len(self.ctrl.store.readings(replica_id=r2)), 5)
        # chrono.checkin once per passing series, with its highest reading; a refusal adds no event.
        evs = self.events(self.gid, "chrono.checkin")
        self.assertEqual([(e["data"]["replica"], e["data"]["reading_mps"]) for e in evs], [(r1, 105.0), (r2, 102.0)])

    def test_unverifiable_readings_change_nothing(self):
        r1 = str(uuid.uuid4())
        me, _ = self.player(r1)
        pid = me["player_id"]
        unsigned = self.marshal.series(r1, pid, PASS, sign=False)
        out = self.upload(self.mtoken, unsigned, expect=422)
        self.assertEqual({x["reason"] for x in out["reasons"]}, {"unsigned"})
        stranger = Marshal("m-stranger", "Desconhecido")
        out = self.upload(self.mtoken, stranger.series(r1, pid, PASS), expect=422)
        self.assertEqual({x["reason"] for x in out["reasons"]}, {"marshal"})
        changed = self.marshal.series(r1, pid, PASS)
        changed[0]["marshal_name"] = "Outra"
        out = self.upload(self.mtoken, changed, expect=422)
        self.assertEqual(out["reasons"][0]["reason"], "signature")
        other_field = Marshal(self.marshal.marshal_id, self.marshal.name, field_id="campo-sul")
        other_field.key = self.marshal.key
        out = self.upload(self.mtoken, other_field.series(r1, pid, PASS), expect=422)
        self.assertEqual(out["reasons"][0]["reason"], "field")
        self.assertEqual(self.states(me), {r1: "pending"})
        self.assertEqual(self.ctrl.store.readings(replica_id=r1), [])
        # Only marshals upload readings.
        self.upload(me["token"], self.marshal.series(r1, pid, PASS), expect=403)
        self.upload("read-secret", self.marshal.series(r1, pid, PASS), expect=403)

    def test_replay_changes_nothing(self):
        r1 = str(uuid.uuid4())
        me, _ = self.player(r1)
        series = self.marshal.series(r1, me["player_id"], FAIL)
        self.assertEqual(self.upload(self.mtoken, series)["outcome"], "fail")
        again = self.upload(self.mtoken, series)
        self.assertTrue(again["duplicate"])
        self.assertEqual(len(self.ctrl.store.readings(replica_id=r1)), 3)
        self.upload(self.mtoken, series[:1] + self.marshal.series(r1, me["player_id"], [90.0]), expect=409)

    def test_day_validity(self):
        r1 = str(uuid.uuid4())
        me, _ = self.player(r1)
        self.upload(self.mtoken, self.marshal.series(r1, me["player_id"], PASS))
        self.client.post(f"/api/v1/games/{self.gid}/end", json={}, headers=GM)
        second = self.new_game(name="Tarde")
        me2 = self.check_in(second["id"], ident=me["_ident"], expect=201, replicas=[declaration(r1)])
        self.assertEqual(self.states(me2), {r1: "passed"})  # once a day is enough

    def test_game_validity_asks_again(self):
        self.client.put("/api/v1/checkin/settings", json={"chrono_valid_for": "game"}, headers=GM)
        r1 = str(uuid.uuid4())
        me, _ = self.player(r1)
        self.upload(self.mtoken, self.marshal.series(r1, me["player_id"], PASS))
        self.client.post(f"/api/v1/games/{self.gid}/end", json={}, headers=GM)
        second = self.new_game(name="Tarde")
        me2 = self.check_in(second["id"], ident=me["_ident"], expect=201, replicas=[declaration(r1)])
        self.assertEqual(self.states(me2), {r1: "pending"})

    def test_refused_earlier_today_is_flagged(self):
        r1 = str(uuid.uuid4())
        me, _ = self.player(r1)
        self.upload(self.mtoken, self.marshal.series(r1, me["player_id"], FAIL))
        self.client.post(f"/api/v1/games/{self.gid}/end", json={}, headers=GM)
        second = self.new_game(name="Tarde")
        self.check_in(second["id"], ident=me["_ident"], expect=201, replicas=[declaration(r1)])
        cl = self.chrono_list(second["id"])
        d = cl["players"][0]["declarations"][0]
        self.assertEqual((d["state"], d.get("refused_today")), ("pending", True))

    def test_linking_an_unregistered_replica(self):
        me, decls = self.player()
        r = self.client.put("/api/v1/checkin/me/replicas", headers=bearer(me["token"]),
                            json={"replicas": [declaration(rclass="dmr")]})
        did = r.json()["declarations"][0]["declaration_id"]
        rid = str(uuid.uuid4())
        replica = {"replica_id": rid, "owner_player_id": me["player_id"], "type": "aeg", "class": "dmr",
                   "registered_at": "2027-01-15T09:59:00Z", "tag_type": "qr", "tag_uid": "LBL-0042"}
        out = self.upload(self.mtoken, self.marshal.series(rid, me["player_id"], [130.0, 135.0]),
                          declaration_id=did, replica=replica)
        self.assertEqual((out["outcome"], out["class"]), ("pass", "dmr"))  # 1.823 J under 1.88
        self.assertEqual(self.states(me), {rid: "passed"})
        self.assertEqual(self.ctrl.store.replica(rid)["tag_uid"], "LBL-0042")

    def test_chronographed_replica_cannot_be_withdrawn_by_the_player(self):
        r1 = str(uuid.uuid4())
        me, decls = self.player(r1)
        self.upload(self.mtoken, self.marshal.series(r1, me["player_id"], PASS))
        r = self.client.put("/api/v1/checkin/me/replicas", headers=bearer(me["token"]), json={"replicas": []})
        self.assertEqual(r.status_code, 409)
        r = self.client.patch(f"/api/v1/games/{self.gid}/checkins/{me['player_id']}", headers=bearer(self.mtoken),
                              json={"replicas": []})
        self.assertEqual(r.status_code, 200, r.text)  # staff can
        self.assertEqual(self.states(me), {r1: "withdrawn"})

    def test_spot_checks(self):
        r1 = str(uuid.uuid4())
        me, _ = self.player(r1)
        pid = me["player_id"]
        self.upload(self.mtoken, self.marshal.series(r1, pid, [95.0], game_id=self.gid))  # 0.903 J
        self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
        out = self.upload(self.mtoken, self.marshal.series(r1, pid, [96.0], rtype="spotcheck", game_id=self.gid))
        self.assertEqual(out["outcome"], "pass")
        out = self.upload(self.mtoken, self.marshal.series(r1, pid, [99.0], rtype="spotcheck", game_id=self.gid))
        self.assertEqual(out["outcome"], "warn")  # 0.980 J: over 0.903 J + 5%
        out = self.upload(self.mtoken, self.marshal.series(r1, pid, [110.0], rtype="spotcheck", game_id=self.gid))
        self.assertEqual(out["outcome"], "fail")
        self.assertEqual(self.states(me), {r1: "passed"})  # spot checks do not change the list
        self.assertEqual(len(self.events(self.gid, "chrono.spotcheck")), 3)
        violations = self.events(self.gid, "chrono.violation")
        self.assertEqual([v["data"]["reading_mps"] for v in violations], [99.0, 110.0])
        self.assertEqual(violations[0]["prio"], "critical")

    def test_list_order_and_access(self):
        r1, r2, r3 = (str(uuid.uuid4()) for _ in range(3))
        first, _ = self.player(r1, name="Primeiro")
        second, _ = self.player(r2, r3, name="Segundo")
        self.upload(self.mtoken, self.marshal.series(r1, first["player_id"], PASS))
        cl = self.chrono_list(self.gid, bearer(self.mtoken))
        self.assertEqual([p["display_name"] for p in cl["players"]], ["Segundo", "Primeiro"])  # pending first
        self.assertEqual(cl["counts"], {"pending": 2, "passed": 1, "refused": 0})
        for headers in (READ, bearer(first["token"])):
            r = self.client.get(f"/api/v1/games/{self.gid}/chrono-list", headers=headers)
            self.assertEqual(r.status_code, 403)
        start = self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True}).json()
        self.assertEqual(start["pending_declarations"], 2)  # a warning, the game started anyway
        self.assertEqual(start["state"], "running")

    def test_membership_and_a_pending_player_without_replicas(self):
        """APDF-3, APDF-4 (protocol/apd.md): a row carries the membership the marshal checks, and a player who
        waits for a marshal is listed even with no replica (only while they wait); the counts stay the replicas'."""
        r = self.client.put("/api/v1/checkin/settings", headers=GM, json={"confirm": "staff", "federation": "optional",
                            "apd": {"checkin": True, "expiry": True, "accepted": ["apd-a"]}})
        self.assertEqual(r.status_code, 200, r.text)
        r1 = str(uuid.uuid4())
        with_replica, _ = self.player(r1, name="Com Réplica")
        self.check_in(self.gid, name="Sem Réplica", federation_number="N-9", apd_id="apd-a",
                      membership_expires="2020-01-01")
        walk_in = self.client.post(f"/api/v1/games/{self.gid}/checkins", json={"display_name": "À Mão"}, headers=GM)
        self.assertEqual(walk_in.status_code, 201, walk_in.text)
        cl = self.chrono_list(self.gid, bearer(self.mtoken))
        self.assertEqual(cl["counts"], {"pending": 1, "passed": 0, "refused": 0})
        by_name = {p["display_name"]: p for p in cl["players"]}
        self.assertEqual(set(by_name), {"Com Réplica", "Sem Réplica"})  # not the marshal, not the walk-in
        lapsed = by_name["Sem Réplica"]
        self.assertEqual((lapsed["status"], lapsed["pending"], lapsed["declarations"]), ("pending", 0, []))
        self.assertEqual((lapsed["apd_id"], lapsed["membership_number"], lapsed["membership_expires"],
                          lapsed["apd_status"], lapsed["apd_override"]),
                         ("apd-a", "N-9", "2020-01-01", "expired", False))
        self.assertEqual(by_name["Com Réplica"]["apd_status"], "missing")  # no number declared
        self.assertIsNone(by_name["Com Réplica"]["apd_id"])
        # The marshal lets them in: the verdict is kept as an override and they leave the list (no replica).
        self.gm_patch(self.gid, lapsed["player_id"], status="checked_in")
        cl = self.chrono_list(self.gid, bearer(self.mtoken))
        self.assertEqual([p["display_name"] for p in cl["players"]], ["Com Réplica"])
        self.assertEqual(self.ctrl.store.checkin(self.gid, lapsed["player_id"])["apd_override"], True)
        # A field whose rule does not check at check-in has no verdict to show.
        self.client.put("/api/v1/checkin/settings", headers=GM, json={"apd": {}})
        self.assertIsNone(self.chrono_list(self.gid, bearer(self.mtoken))["players"][0]["apd_status"])

    def test_shared_vectors_verify_through_the_api(self):
        """protocol/vectors/chrono_record.json through POST /api/v1/chrono/readings: the valid records
        are stored, every invalid one is refused with the vector's reason (the API adds none)."""
        first = VECTORS["valid"][0]["record"]
        r = self.client.post("/api/v1/marshals", headers=GM, json={
            "marshal_id": first["marshal_id"], "name": first["marshal_name"], "public_key": VECTORS["public_key"]})
        self.assertEqual(r.status_code, 201, r.text)
        self.svc.cfg.field_id = first["field_id"]
        for bad in VECTORS["invalid"]:
            with self.subTest(bad["name"]):
                out = self.upload(self.mtoken, [bad["record"]], expect=422)
                self.assertEqual(out["reasons"][0]["reason"], bad["reason"])
        self.assertEqual(self.ctrl.store.readings(), [])
        stored = set()
        for v in VECTORS["valid"]:
            with self.subTest(v["name"]):
                self.svc.cfg.field_id = v["record"]["field_id"]
                out = self.upload(self.mtoken, [v["record"]])
                self.assertEqual(out["duplicate"], v["record"]["reading_id"] in stored)
                stored.add(v["record"]["reading_id"])
        self.assertEqual(len(self.ctrl.store.readings()), len(stored))


class AcceptanceTests(P3Case):
    """AC-13: a poster's check-in with no internet, two declared replicas, one passed and one refused,
    the read token never seeing the name, and nothing lost across a restart."""

    def test_ac13(self):
        g = self.new_game()
        poster = self.client.get("/api/v1/checkin/poster", headers=GM).json()
        self.assertTrue(poster["text"].startswith("atalaia:checkin:"))
        self.assertIn("https://10.0.2.2:8443", poster["urls"])
        ca = self.client.get("/api/v1/controller/ca")
        import hashlib

        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        der = x509.load_pem_x509_certificate(ca.content).public_bytes(serialization.Encoding.DER)
        self.assertEqual(hashlib.sha256(der).hexdigest(), poster["ca_sha256"])
        r1, r2 = str(uuid.uuid4()), str(uuid.uuid4())
        me = self.check_in(g["id"], name="Ana Paula", replicas=[declaration(r1), declaration(r2, rclass="dmr")])
        marshal, mtoken = self.make_marshal(g["id"], Marshal("m-rui", "Rui"))
        for headers in (GM, bearer(mtoken)):
            cl = self.chrono_list(g["id"], headers)
            self.assertEqual(cl["counts"]["pending"], 2)
        self.upload(mtoken, marshal.series(r1, me["player_id"], PASS))
        self.upload(mtoken, marshal.series(r2, me["player_id"], [140.0, 145.0]))  # 2.103 J over 1.88
        self.assertEqual(self.chrono_list(g["id"])["counts"], {"pending": 0, "passed": 1, "refused": 1})
        self.assertNotIn("Ana Paula", self.everything_public(g["id"]))
        self.restart()
        cl = self.chrono_list(g["id"])
        self.assertEqual(cl["counts"], {"pending": 0, "passed": 1, "refused": 1})
        self.assertEqual(cl["players"][0]["display_name"], "Ana Paula")
        self.assertEqual(self.client.get("/api/v1/checkin/me", headers=bearer(me["token"])).status_code, 200)


if __name__ == "__main__":
    unittest.main()
