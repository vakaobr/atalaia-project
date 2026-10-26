# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The GM's marshal list (decisions MR-1 to MR-14, ADR-P3-13): a marshal exists only on the list the GM
makes, the app learns its id from GET /api/v1/checkin/me and registers its key for that id and no other,
and a marshal taken off the list is refused at once.

    cd controller && python -m unittest discover -s tests -p "test_marshal_list.py"
"""

from __future__ import annotations

import base64
import sqlite3
import tempfile
import unittest
import uuid

from atalaia_controller.store import Store
from p3support import GM, READ, Marshal, P3Case, bearer


class MarshalListTests(P3Case):
    def setUp(self):
        super().setUp()
        self.gid = self.new_game()["id"]

    def add(self, expect: int = 201, **body):
        r = self.client.post("/api/v1/marshals", headers=GM, json=body)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def me(self, token: str):
        r = self.client.get("/api/v1/checkin/me", headers=bearer(token))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def fresh_token(self, token: str) -> str:
        r = self.client.post("/api/v1/checkin/token", headers=bearer(token))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["token"]

    def test_only_the_gm_edits_the_list(self):
        me = self.check_in(self.gid, name="Ana")
        body = {"player_id": me["player_id"]}
        self.assertEqual(self.client.post("/api/v1/marshals", json=body).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/marshals", headers=READ, json=body).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/marshals", headers=bearer(me["token"]), json=body).status_code,
                         401)  # a player token is not a GM token
        self.assertEqual(self.client.get("/api/v1/marshals", headers=READ).status_code, 403)
        self.assertEqual(self.client.patch("/api/v1/marshals/M-01", headers=READ, json={}).status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/marshals/M-01", headers=READ).status_code, 403)

    def test_adding_a_player_makes_the_id_the_name_and_the_role(self):
        ana = self.check_in(self.gid, name="Ana")
        bob = self.check_in(self.gid, name="Bob")
        first = self.add(player_id=ana["player_id"])
        self.assertEqual((first["marshal_id"], first["name"], first["player_id"], first["key_registered"]),
                         ("M-01", "Ana", ana["player_id"], False))
        self.assertIsNone(first["public_key"])
        self.assertEqual(self.add(player_id=bob["player_id"])["marshal_id"], "M-02")
        rows = {r["player_id"]: r for r in self.client.get(f"/api/v1/games/{self.gid}/checkins", headers=GM)
                .json()["checkins"]}
        self.assertEqual(rows[ana["player_id"]]["role"], "marshal")
        self.assertEqual([m["marshal_id"] for m in self.client.get("/api/v1/marshals", headers=GM).json()],
                         ["M-01", "M-02"])
        # The same player again is the same marshal, not a second id.
        self.assertEqual(self.add(201, player_id=ana["player_id"])["marshal_id"], "M-01")
        self.add(409, marshal_id="M-07", player_id=ana["player_id"])

    def test_bad_requests(self):
        self.add(400, name="Nobody", marshal_id="bad id!")
        self.add(400, name="Nobody", surprise=True)
        self.add(400)  # no name, no player
        self.add(400, name="Nobody", player_id="not-a-player")
        self.add(404, player_id="p-aaaaaaaaaaaa")  # never checked in here
        self.add(400, name="Nobody", public_key="not a key")
        r = self.client.patch("/api/v1/marshals/M-99", headers=GM, json={"name": "x"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(self.client.delete("/api/v1/marshals/M-99", headers=GM).status_code, 404)

    def test_the_phone_learns_its_id_and_registers_its_key_for_it(self):
        m = Marshal(marshal_id="M-01", name="Ana")
        ana = self.check_in(self.gid, name="Ana")
        # The GM gave the role by hand, but has not listed the player: no id, no key (MR-5).
        self.gm_patch(self.gid, ana["player_id"], role="marshal")
        token = self.fresh_token(ana["token"])
        self.assertIsNone(self.me(token)["marshal"])
        r = self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(token), json={"public_key": m.public_b64})
        self.assertEqual(r.status_code, 403)
        self.assertIn("marshal list", r.json()["detail"])
        self.assertEqual(self.client.get("/api/v1/marshals", headers=GM).json(), [])
        # Listed: the phone is told its id, and that the controller holds no key for it yet.
        self.add(player_id=ana["player_id"])
        mine = self.me(token)["marshal"]
        self.assertEqual(mine, {"marshal_id": "M-01", "name": "Ana", "public_key": None, "valid_for_s": 7200})
        # Only its own id (MR-2).
        r = self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(token),
                            json={"marshal_id": "M-02", "public_key": m.public_b64})
        self.assertEqual(r.status_code, 409)
        r = self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(token), json={"public_key": "no"})
        self.assertEqual(r.status_code, 400)
        r = self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(token),
                            json={"marshal_id": "M-01", "name": "other", "public_key": m.public_b64})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json(), {"marshal_id": "M-01", "name": "Ana", "public_key": m.public_b64,
                                    "player_id": ana["player_id"]})  # the GM's name stands
        self.assertEqual(self.me(token)["marshal"]["public_key"], m.public_b64)
        listed = self.client.get("/api/v1/marshals", headers=GM).json()[0]
        self.assertTrue(listed["key_registered"])
        self.assertEqual(listed["public_key"], m.public_b64)
        # A player who is not a marshal gets no "marshal" in me().
        bob = self.check_in(self.gid, name="Bob")
        self.assertNotIn("marshal", self.me(bob["token"]))

    def test_nobody_else_registers_a_key_for_an_id(self):
        ana = self.check_in(self.gid, name="Ana")
        self.add(player_id=ana["player_id"])
        bob = self.check_in(self.gid, name="Bob")
        self.gm_patch(self.gid, bob["player_id"], role="marshal")  # a marshal role, but not on the list
        token = self.fresh_token(bob["token"])
        r = self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(token),
                            json={"marshal_id": "M-01", "public_key": Marshal().public_b64})
        self.assertEqual(r.status_code, 403)

    def test_readings_need_a_listed_marshal_and_stop_when_removed(self):
        m = Marshal(marshal_id="M-01", name="Ana")
        me = self.check_in(self.gid, name="Ana")
        self.add(player_id=me["player_id"], marshal_id="M-01")
        token = self.fresh_token(me["token"])
        self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(token), json={"public_key": m.public_b64})
        owner = self.check_in(self.gid, name="Dono")
        replica = str(uuid.uuid4())
        batch = m.series(replica, owner["player_id"], [90.0], game_id=self.gid)
        self.assertEqual(self.upload(token, batch)["stored"], 1)
        # Taken off the list: the key stops at once, the token stops being staff's, the old reading stays (MR-8, MR-9).
        out = self.client.delete("/api/v1/marshals/M-01", headers=GM)
        self.assertEqual((out.status_code, out.json()), (200, {"marshal_id": "M-01", "removed": True}))
        later = m.series(replica, owner["player_id"], [91.0], game_id=self.gid)
        self.upload(token, later, expect=403)
        # The GM token uploads for anyone, and still a removed marshal's records are refused (their key is gone).
        again = self.upload("gm-secret", later, expect=422)
        self.assertEqual(again["reasons"][0]["reason"], "marshal")
        self.assertIn("marshal list", again["reasons"][0]["detail"])
        self.assertEqual(len(self.ctrl.store.readings()), 1)
        row = next(r for r in self.client.get(f"/api/v1/games/{self.gid}/checkins", headers=GM).json()["checkins"]
                   if r["player_id"] == me["player_id"])
        self.assertEqual(row["role"], "player")
        self.assertEqual(self.client.get("/api/v1/marshals", headers=GM).json(), [])
        # What it signed still verifies elsewhere: the key went to the history, not away.
        history = self.ctrl.store.marshal_key_history()
        self.assertEqual([(h["marshal_id"], h["public_key"]) for h in history],
                         [("M-01", base64.b64decode(m.public_b64))])
        self.assertEqual(self.ctrl.store.marshals(), [])

    def test_putting_the_marshal_back_takes_the_same_key_back_once(self):
        m = Marshal(marshal_id="M-01", name="Ana")
        me = self.check_in(self.gid, name="Ana")
        self.add(player_id=me["player_id"])
        token = self.fresh_token(me["token"])
        self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(token), json={"public_key": m.public_b64})
        first = self.ctrl.store.marshal("M-01")["registered_at"]
        self.client.delete("/api/v1/marshals/M-01", headers=GM)
        self.assertEqual(self.add(player_id=me["player_id"])["marshal_id"], "M-01")
        token = self.fresh_token(me["token"])
        self.assertEqual(self.me(token)["marshal"]["public_key"], None)
        self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(token), json={"public_key": m.public_b64})
        self.assertEqual(self.ctrl.store.marshal_key_history(), [])  # one row per (marshal, key) for the site
        self.assertEqual(self.ctrl.store.marshal("M-01")["registered_at"], first)

    def test_rebinding_an_id_drops_the_old_phones_key(self):
        old, new = Marshal(marshal_id="M-01", name="Ana"), Marshal(marshal_id="M-01", name="Bob")
        ana = self.check_in(self.gid, name="Ana")
        bob = self.check_in(self.gid, name="Bob")
        self.add(player_id=ana["player_id"])
        t_old = self.fresh_token(ana["token"])
        self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(t_old), json={"public_key": old.public_b64})
        r = self.client.patch("/api/v1/marshals/M-01", headers=GM, json={"player_id": bob["player_id"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["player_id"], r.json()["key_registered"]), (bob["player_id"], False))
        self.assertEqual(self.ctrl.store.marshals(), [])
        roles = {c["player_id"]: c["role"] for c in
                 self.client.get(f"/api/v1/games/{self.gid}/checkins", headers=GM).json()["checkins"]}
        self.assertEqual((roles[ana["player_id"]], roles[bob["player_id"]]), ("player", "marshal"))
        t_new = self.fresh_token(bob["token"])
        self.assertEqual(self.client.put("/api/v1/checkin/me/marshal-key", headers=bearer(t_new),
                                         json={"public_key": new.public_b64}).status_code, 200)
        # A name change keeps the key; unbinding takes the role and the key.
        self.client.patch("/api/v1/marshals/M-01", headers=GM, json={"name": "Roberto"})
        self.assertEqual(self.ctrl.store.marshal("M-01")["name"], "Roberto")
        self.assertTrue(self.client.get("/api/v1/marshals", headers=GM).json()[0]["key_registered"])
        r = self.client.patch("/api/v1/marshals/M-01", headers=GM, json={"player_id": None})
        self.assertEqual((r.json()["player_id"], r.json()["key_registered"]), (None, False))
        self.add(201, marshal_id="M-02", player_id=bob["player_id"])  # bound to another id now

    def test_the_list_without_a_player_and_a_marshal_with_a_key_from_the_gm(self):
        m = Marshal(marshal_id="gate-1", name="Gate")
        out = self.add(marshal_id="gate-1", name="Gate", public_key=m.public_b64)
        self.assertEqual((out["player_id"], out["key_registered"]), (None, True))
        bare = self.add(name="Free")
        self.assertEqual(bare["marshal_id"], "M-01")

    def test_the_old_marshal_keys_are_on_the_list_after_the_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/old.db"
            store = Store(path)
            store.put_marshal("m-old", "Old", bytes(32), "p-aaaaaaaaaaaa", 5.0)
            store.close()
            raw = sqlite3.connect(path)
            raw.execute("DELETE FROM marshal_roster")  # what a database from before schema 12 looks like
            raw.commit()
            raw.close()
            store = Store(path)
            self.assertEqual([(r["marshal_id"], r["name"], r["player_id"]) for r in store.roster()],
                             [("m-old", "Old", "p-aaaaaaaaaaaa")])
            store.close()


if __name__ == "__main__":
    unittest.main()
