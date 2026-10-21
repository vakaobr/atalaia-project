# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The join flow (ADR-P2-12, protocol/join.md) on the controller.

    cd controller && python -m unittest discover -s tests

- Issuing join payloads through the API: ids, roles, assignments, tokens, no caching.
- A second controller joining as standby (kind "controller"): through the
  API, then over a real radio: two C host modems sharing one 'air', the
  standby following the primary's TIME beacons and box traffic, and taking
  over the game when the GM promotes it after the primary stops.
"""

from __future__ import annotations

import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from support import CORE, MODEM_HOST, AirHub, FakeModem, HostModem, config, node_packet, packet_decrypt, wait_for
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.main import ensure_join_key, main
from atalaia_controller.radio_modem import RadioModem
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import codec, join
from atalaia_sim.packet import state_encode, time_decode, time_encode
from atalaia_sim.protocol import MESSAGE_TYPES

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
DOMINATION = "org.atalaia.domination"
JOIN_KEY = bytes(range(32))


class Side:
    """One controller with its API, store and (fake or real) modem."""

    def __init__(self, tmp: str, name: str, modem=None, **cfg) -> None:
        self.cfg = config(tmp, db_path=f"{tmp}/{name}.db", **cfg)
        self.store = Store(self.cfg.db_path)
        self.modem = modem if modem is not None else FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=JOIN_KEY)
        self.app = create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token))
        self.client = TestClient(self.app)

    def close(self) -> None:
        self.client.close()
        self.ctrl.stop()
        self.store.close()


class IssueJoinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = Side(self.tmp.name, "a")
        r = self.a.client.post("/api/v1/games", headers=GM, json={
            "name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"],
            "assignments": {"4": "zone"}, "params": {"tick_s": 5}})
        self.assertEqual(r.status_code, 201, r.text)
        self.game = r.json()

    def tearDown(self):
        self.a.close()
        self.tmp.cleanup()

    def test_box_join_payload(self):
        r = self.a.client.post("/api/v1/join", headers=GM, json={"role": "zone"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.headers["cache-control"], "no-store")
        out = r.json()
        self.assertEqual((out["node_id"], out["kind"], out["role"], out["controller_id"]), (1, "node", "zone", 0))
        payload = bytes.fromhex(out["payload_hex"])
        self.assertEqual(join.from_text(out["text"]), payload)
        self.assertEqual(join.from_ndef_tag(bytes.fromhex(out["ndef_tag_hex"])), payload)
        self.assertEqual(out["bytes"], len(payload))
        j = join.decode(payload, JOIN_KEY)
        self.assertEqual(j["game_id"], self.game["id"])
        self.assertEqual(j["game_key"], self.a.ctrl.game_key(self.game["id"]))
        self.assertEqual((j["node_id"], j["controller_id"], j["channel_hz"], j["max_hops"]),
                         (1, 0, 869_525_000, 2))
        self.assertEqual((j["teams"], j["mode_id"], j["role"], j["kind"]),
                         (["red", "blue"], DOMINATION, "zone", "node"))
        self.assertEqual(j["params"]["tick_s"], 5)
        self.assertEqual(j["game_seed"], self.game["game_seed"])
        # Another field's key does not open it.
        with self.assertRaises(join.JoinError):
            join.decode(payload, bytes(32))
        # The box is assigned its role; the next join gets the next free id.
        self.assertEqual(self.a.client.get(f"/api/v1/games/{self.game['id']}", headers=READ)
                         .json()["assignments"], {"4": "zone", "1": "zone"})
        out2 = self.a.client.post("/api/v1/join", headers=GM, json={}).json()  # one role: zone
        self.assertEqual(out2["node_id"], 2)

    def test_explicit_id_and_standby_kind(self):
        r = self.a.client.post("/api/v1/nodes/9/join", headers=GM, json={"role": "zone"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["node_id"], 9)
        r = self.a.client.post("/api/v1/join", headers=GM, json={"kind": "controller"})
        self.assertEqual(r.status_code, 200, r.text)
        j = join.decode(bytes.fromhex(r.json()["payload_hex"]), JOIN_KEY)
        self.assertEqual((j["kind"], j["role"], j["node_id"]), ("controller", "controller", 1))
        self.assertNotIn("1", self.a.ctrl.game["assignments"])  # a standby is not a box

    def test_refusals(self):
        c = self.a.client
        self.assertEqual(c.post("/api/v1/join", json={"role": "zone"}).status_code, 401)
        self.assertEqual(c.post("/api/v1/join", headers=READ, json={"role": "zone"}).status_code, 403)
        self.assertEqual(c.post("/api/v1/join", headers=GM, json={"role": "bomb"}).status_code, 400)
        self.assertEqual(c.post("/api/v1/join", headers=GM, json={"kind": "drone"}).status_code, 400)
        self.assertEqual(c.post("/api/v1/nodes/0/join", headers=GM, json={}).status_code, 400)
        self.assertEqual(c.post("/api/v1/nodes/65535/join", headers=GM, json={}).status_code, 400)
        self.assertEqual(c.post("/api/v1/join", headers=GM, json={"kind": "controller", "node_id": 4})
                         .status_code, 409)  # node 4 is a box
        c.post(f"/api/v1/games/{self.game['id']}/end", headers=GM, json={})
        self.assertEqual(c.post("/api/v1/join", headers=GM, json={"role": "zone"}).status_code, 409)

    def test_join_key_is_generated_once_and_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp)
            store = Store(cfg.db_path)
            key = ensure_join_key(cfg, store)
            self.assertEqual(len(key), 32)
            self.assertEqual(ensure_join_key(cfg, store), key)
            store.close()
            cfg.join_key = "ab" * 32
            self.assertEqual(ensure_join_key(cfg, Store(cfg.db_path)), bytes([0xAB]) * 32)


class StandbyApiTests(unittest.TestCase):
    """A standby joins from the text, follows TIME, and leaves when the game ends."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = Side(self.tmp.name, "a")
        self.b = Side(self.tmp.name, "b", node_id=0)
        r = self.a.client.post("/api/v1/games", headers=GM, json={
            "name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"]})
        self.game = r.json()
        self.text = self.a.client.post("/api/v1/join", headers=GM, json={"kind": "controller"}).json()["text"]

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.tmp.cleanup()

    def time_packet(self, state: int, game_time: int, term: int = 1) -> bytes:
        return time_encode({"game_time_ms": game_time, "game_state": state, "duration_ms": 600_000,
                            "wall_s": int(time.time()), "term": term})

    def test_join_follow_and_leave(self):
        c = self.b.client
        self.assertEqual(c.post("/api/v1/controller/join", headers=READ, json={"text": self.text}).status_code, 403)
        r = c.post("/api/v1/controller/join", headers=GM, json={"text": self.text})
        self.assertEqual(r.status_code, 201, r.text)
        game = r.json()
        self.assertEqual((game["id"], game["joined"], game["node_id"], game["controller_id"]),
                         (self.game["id"], True, 1, 0))
        status = c.get("/api/v1/controller", headers=READ).json()
        self.assertEqual((status["role"], status["node_id"], status["joined"]), ("follower", 1, True))
        # The modem got the game key, the standby's own id and the channel.
        args = self.b.modem.configured[-1]
        self.assertEqual(args[:2], (self.game["id"], 1))
        self.assertEqual(args[4:], (869_525_000, self.a.ctrl.game_key(self.game["id"])))
        # On standby the game cannot be driven, and a second join is refused.
        self.assertEqual(c.post(f"/api/v1/games/{self.game['id']}/start", headers=GM).status_code, 409)
        self.assertEqual(c.post("/api/v1/controller/join", headers=GM, json={"text": self.text}).status_code, 409)

        # The primary's TIME says running: the standby's game follows it.
        self.b.modem.rx(0, 1, "TIME", self.time_packet(1, 5000), game_id=self.game["id"], epoch=1)
        self.b.ctrl.tick()
        self.assertEqual(c.get(f"/api/v1/games/{self.game['id']}", headers=READ).json()["state"], "running")
        # A box's capture is logged on the standby too.
        ev = codec.encode_event({"node": 5, "seq": 1, "t": 6000, "type": "zone.captured", "team": 1,
                                 "data": {"team": "red"}})
        self.b.modem.rx(5, 0, "EVENT", ev, game_id=self.game["id"], epoch=1, ack=True)
        self.assertEqual([e["type"] for e in c.get(f"/api/v1/games/{self.game['id']}/log", headers=READ).json()],
                         ["zone.captured"])
        self.assertEqual(self.b.modem.of("ACK"), [])  # only the controller acknowledges
        # The game ends: the standby leaves it and forgets the key.
        self.b.modem.rx(0, 2, "TIME", self.time_packet(3, 9000), game_id=self.game["id"], epoch=1)
        self.b.ctrl.tick()
        self.assertEqual(c.get(f"/api/v1/games/{self.game['id']}", headers=READ).json()["state"], "ended")
        self.assertIsNone(self.b.ctrl.game)
        self.assertEqual(self.b.modem.cleared, 1)

    def test_refused_payloads(self):
        c = self.b.client
        box = self.a.client.post("/api/v1/join", headers=GM, json={"role": "zone"}).json()["text"]
        r = c.post("/api/v1/controller/join", headers=GM, json={"text": box})
        self.assertEqual(r.status_code, 400)
        self.assertIn("box", r.json()["detail"])
        self.assertEqual(c.post("/api/v1/controller/join", headers=GM, json={"text": "nope"}).status_code, 400)
        other = Side(self.tmp.name, "c")
        other.ctrl.join_key = bytes(32)  # another field
        r = other.client.post("/api/v1/controller/join", headers=GM, json={"text": self.text})
        self.assertEqual(r.status_code, 400)
        self.assertIn("mac", r.json()["detail"])
        other.close()

    def test_leave_on_request_and_promote(self):
        c = self.b.client
        c.post("/api/v1/controller/join", headers=GM, json={"text": self.text})
        r = c.post("/api/v1/controller/promote", headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["role"], "candidate")
        claims = self.b.modem.of("CLAIM")
        self.assertEqual(claims[-1][0].source, 1)
        # A standby that is not promoted can leave the game on request.
        d = Side(self.tmp.name, "d")
        d.client.post("/api/v1/controller/join", headers=GM, json={"text": self.text})
        r = d.client.post(f"/api/v1/games/{self.game['id']}/end", headers=GM, json={})
        self.assertEqual((r.status_code, r.json()["state"]), (200, "ended"))
        self.assertIsNone(d.ctrl.game)
        d.close()


@unittest.skipUnless(MODEM_HOST, "host modem not built")
class StandbyOverTheAirTests(unittest.TestCase):
    """Two controllers, each with a C host modem, on one shared air."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = AirHub()
        self.hosts = [HostModem(hub=self.hub), HostModem(hub=self.hub)]
        for h in self.hosts:
            self.hub.add(h.air_port)
        self.modems = [RadioModem(h.url, ping_interval=0.2, retry_interval=0.2) for h in self.hosts]
        for m in self.modems:
            m.start()
            self.assertTrue(m.wait_up(5))
        self.a = Side(self.tmp.name, "a", modem=self.modems[0], failover_mode="manual")
        self.b = Side(self.tmp.name, "b", modem=self.modems[1], failover_mode="manual")
        self.a.ctrl.start()
        self.b.ctrl.start()

    def tearDown(self):
        for side in (self.a, self.b):
            side.close()
        for m in self.modems:
            m.stop()
        for h in self.hosts:
            h.close()
        self.hub.close()
        self.tmp.cleanup()

    def test_standby_follows_and_takes_over(self):
        a, b = self.a.client, self.b.client
        game = a.post("/api/v1/games", headers=GM, json={
            "name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"]}).json()
        gid = game["id"]
        key = self.a.ctrl.game_key(gid)
        text = a.post("/api/v1/join", headers=GM, json={"kind": "controller"}).json()["text"]
        self.assertEqual(b.post("/api/v1/controller/join", headers=GM, json={"text": text}).status_code, 201)

        # The primary starts the game: its CMD and TIME reach the standby through both C modems.
        self.assertEqual(a.post(f"/api/v1/games/{gid}/start", headers=GM).status_code, 200)
        self.assertTrue(wait_for(lambda: b.get(f"/api/v1/games/{gid}", headers=READ).json()["state"] == "running", 5))
        self.assertEqual(b.get("/api/v1/controller", headers=READ).json()["leader"], 0)

        # A box (played by the test) captures: both controllers log it; only the primary ACKs, and
        # only the primary logs node.online about the box (a standby logs no health events, FU1-1).
        ev = codec.encode_event({"node": 7, "seq": 1, "t": 1000, "type": "zone.captured", "team": 2,
                                 "data": {"team": "blue"}})
        self.hub.send(node_packet(key, gid, 7, 0, 1, "EVENT", ev, ack=True))
        st = state_encode({"owner_team": 2, "phase": 1, "game_time_ms": 1000, "counters": {2: 30}, "epoch": 1})
        self.hub.send(node_packet(key, gid, 7, 1, 1, "STATE", st))
        for side, logged in ((a, ["node.online", "zone.captured"]), (b, ["zone.captured"])):
            self.assertTrue(wait_for(lambda side=side, logged=logged: sorted(e["type"] for e in side.get(
                f"/api/v1/games/{gid}/log", headers=READ).json() if e["node"] == 7) == logged, 5))
            self.assertTrue(wait_for(lambda side=side: side.get(f"/api/v1/games/{gid}/score", headers=READ)
                                     .json()["teams"]["blue"] == 30, 5))
        sources = set()
        for _, p in list(self.hub.heard):
            for epoch_owner in (self.a.ctrl.transport, self.b.ctrl.transport):
                try:
                    hdr, _plain = packet_decrypt(p, epoch_owner.epoch, key)
                except Exception:
                    continue
                if hdr.type == MESSAGE_TYPES["ACK"]:
                    sources.add(hdr.source)
        self.assertEqual(sources, {0})

        # The primary goes away; the GM promotes the standby, which takes over with term 2.
        self.a.ctrl.stop()
        self.modems[0].stop()
        self.hub.remove(self.hosts[0].air_port)
        r = b.post("/api/v1/controller/promote", headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(wait_for(lambda: b.get("/api/v1/controller", headers=READ).json()["role"] == "leader", 10))
        self.assertEqual(b.get("/api/v1/controller", headers=READ).json()["term"], 2)
        # Its TIME beacon is on air from node 1 with term 2, continuing the game clock.
        def standby_time():
            for _, p in list(self.hub.heard):
                try:
                    hdr, plain = packet_decrypt(p, self.b.ctrl.transport.epoch, key)
                except Exception:
                    continue
                if hdr.type == MESSAGE_TYPES["TIME"] and hdr.source == 1:
                    return time_decode(plain)
            return None
        self.assertTrue(wait_for(lambda: standby_time() is not None, 5))
        self.assertEqual(standby_time()["term"], 2)
        # The new controller drives the game and keeps the scores it heard.
        self.assertEqual(b.post(f"/api/v1/games/{gid}/pause", headers=GM, json={}).status_code, 200)
        self.assertEqual(b.get(f"/api/v1/games/{gid}/score", headers=READ).json()["teams"]["blue"], 30)


class JoinKeyCommandTests(unittest.TestCase):
    def test_join_key_command(self):
        import contextlib
        import io
        import os
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "c.toml")
            with open(path, "w", encoding="utf-8") as f:
                f.write(f'[controller]\ndb_path = "{tmp}/x.db"\n[mqtt]\nenabled = false\n')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(main(["join-key", "--config", path, "--log-level", "ERROR"]), 0)
            first = out.getvalue().strip()
            self.assertEqual(len(bytes.fromhex(first)), 32)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main(["join-key", "--config", path, "--log-level", "ERROR"])
            self.assertEqual(out.getvalue().strip(), first)


if __name__ == "__main__":
    unittest.main()
