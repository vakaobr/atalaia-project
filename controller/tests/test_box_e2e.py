# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A whole field on one machine: the controller, its C host modem and C host boxes.

    cd controller && ATALAIA_MODEM_HOST=... ATALAIA_BOX_HOST=... python -m unittest discover -s tests

The boxes run the Field Box firmware's own game and radio code
(main/box_game.c, main/radio/field_link.c, the node runner and the core,
with mbedtls AES-CCM) as the host box program; the modem runs
main/modem/modem.c; they share one UDP 'air' through the hub. So a join
payload made by the controller, typed into a box's console, makes that box
join the game; the controller's CMD and TIME drive it; its captures, STATE
and score counters reach the controller and are acknowledged; a battery
pull brings it back with a new epoch; a box out of the modem's range is
heard through another box's relay. Decision D18 is the box side of this.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from support import (BOX_HOST, CORE, MODEM_HOST, AirHub, BoxHost, HostModem, config, wait_for)
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.radio_modem import RadioModem
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
JOIN_KEY = bytes(range(100, 132))
FAST = {"capture_hold_ms": 1000, "tick_s": 1, "points_per_tick": 5}


@unittest.skipUnless(MODEM_HOST and BOX_HOST, "host modem or host box not built")
class FieldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = AirHub()
        self.host = HostModem(hub=self.hub)
        self.hub.add(self.host.air_port)
        self.modem = RadioModem(self.host.url, ping_interval=0.2, retry_interval=0.2)
        self.modem.start()
        self.assertTrue(self.modem.wait_up(5))
        self.cfg = config(self.tmp.name)
        self.store = Store(self.cfg.db_path)
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=JOIN_KEY)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))
        self.ctrl.start()
        self.boxes: list[BoxHost] = []

    def tearDown(self):
        for box in self.boxes:
            box.close()
        self.client.close()
        self.ctrl.stop()
        self.modem.stop()
        self.store.close()
        self.host.close()
        self.hub.close()
        self.tmp.cleanup()

    def box(self, name: str) -> BoxHost:
        b = BoxHost(self.hub, os.path.join(self.tmp.name, name), JOIN_KEY, state_ms=500, name=name)
        self.boxes.append(b)
        return b

    def game(self) -> int:
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "e2e", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"],
            "params": FAST})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def join(self, box: BoxHost, **spec) -> int:
        r = self.client.post("/api/v1/join", headers=GM, json={"role": "zone", **spec})
        self.assertEqual(r.status_code, 200, r.text)
        box.join(r.json()["text"])
        self.assertTrue(wait_for(lambda: box.logged("LOG join: joined"), 5), box.lines[-5:])
        return r.json()["node_id"]

    def node(self, node_id: int) -> dict:
        for n in self.client.get("/api/v1/nodes", headers=READ).json():
            if n["node_id"] == node_id:
                return n
        return {}

    def log_types(self, gid: int, node_id: int) -> list[str]:
        return [e["type"] for e in self.client.get(f"/api/v1/games/{gid}/log", headers=READ).json()
                if e["node"] == node_id]

    def score(self, gid: int, team: str) -> int:
        return self.client.get(f"/api/v1/games/{gid}/score", headers=READ).json()["teams"][team]

    def test_join_play_reboot_end(self):
        gid = self.game()
        box = self.box("alpha")
        nid = self.join(box)

        # HELLO reaches the controller, which registers the box and acknowledges it.
        self.assertTrue(wait_for(lambda: self.node(nid).get("fw_version") == "host", 5))
        self.assertEqual(self.node(nid)["platform"], 2)
        self.assertTrue(wait_for(lambda: box.status()["acked"] >= 1, 5))
        st = box.status()
        self.assertEqual((st["phase"], st["game_id"], st["node_id"], st["epoch"]), (1, gid, nid, 1))

        # The GM starts the game: the CMD reaches the box, which starts the mode.
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).status_code, 200)
        self.assertTrue(wait_for(lambda: box.status()["phase"] == 2, 5))

        # Red holds the button: a capture, logged once and acknowledged.
        box.hold(1, 1300)
        self.assertTrue(wait_for(lambda: "zone.captured" in self.log_types(gid, nid), 6))
        cap = [e for e in self.client.get(f"/api/v1/games/{gid}/log", headers=READ).json()
               if e["type"] == "zone.captured"][0]
        self.assertEqual((cap["node"], cap["team"], cap["epoch"]), (nid, "red", 1))
        self.assertTrue(wait_for(lambda: box.status()["pending"] == 0, 8))

        # Holding the zone scores; STATE counters bring the total to the controller.
        self.assertTrue(wait_for(lambda: self.score(gid, "red") >= 10, 8))
        self.assertEqual(self.node(nid)["owner"], "red")

        # Pause and resume reach the box.
        self.client.post(f"/api/v1/games/{gid}/pause", headers=GM, json={"reason": "safety"})
        self.assertTrue(wait_for(lambda: box.status()["paused"], 5))
        self.client.post(f"/api/v1/games/{gid}/resume", headers=GM)
        self.assertTrue(wait_for(lambda: not box.status()["paused"], 5))

        # Battery pull: the box comes back by itself, in the same game, with a new epoch.
        before = self.score(gid, "red")
        box.kill()
        box.start()
        self.assertTrue(wait_for(lambda: box.logged("rejoined the stored game"), 5))
        st = box.status()
        self.assertEqual((st["phase"], st["epoch"], st["node_id"]), (2, 2, nid))
        self.assertTrue(wait_for(lambda: "node.rebooted" in self.log_types(gid, nid), 6))
        self.assertTrue(wait_for(lambda: self.node(nid).get("epoch") == 2, 5))
        # Scores never go back (counters merge by maximum), and a capture after the reboot,
        # with the box's event seq restarted, is logged too (decision D6).
        self.assertGreaterEqual(self.score(gid, "red"), before)
        box.hold(2, 1300)
        self.assertTrue(wait_for(lambda: self.log_types(gid, nid).count("zone.captured") == 2, 8))
        self.assertTrue(wait_for(lambda: self.score(gid, "blue") >= 5, 8))

        # End: the box ends, its last events are acknowledged, and it forgets the key.
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/end", headers=GM, json={}).status_code, 200)
        self.assertTrue(wait_for(lambda: box.status()["phase"] == 0, 10), box.lines[-8:])
        self.assertFalse(box.status()["have_key"])
        self.assertFalse(os.path.exists(os.path.join(box.state_dir, "join")))

    def test_relay_through_another_box(self):
        """A box out of the modem's range is heard, and hears the controller, through another box."""
        gid = self.game()
        near, far = self.box("near"), self.box("far")
        self.hub.block(far.air_port, self.host.air_port)
        n_near = self.join(near)
        n_far = self.join(far)
        self.assertTrue(wait_for(lambda: self.node(n_far).get("fw_version") == "host", 8))
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).status_code, 200)
        self.assertTrue(wait_for(lambda: far.status()["phase"] == 2, 8))
        far.hold(2, 1300)
        self.assertTrue(wait_for(lambda: "zone.captured" in self.log_types(gid, n_far), 8))
        self.assertTrue(wait_for(lambda: far.status()["pending"] == 0, 10))
        self.assertGreater(near.status()["relayed"], 0)
        self.assertTrue(wait_for(lambda: self.score(gid, "blue") >= 5, 8))
        self.assertNotEqual(n_near, n_far)

    def test_wrong_field_key_is_refused(self):
        self.game()
        stranger = BoxHost(self.hub, os.path.join(self.tmp.name, "stranger"), bytes(32), name="x")
        self.boxes.append(stranger)
        text = self.client.post("/api/v1/join", headers=GM, json={"role": "zone"}).json()["text"]
        stranger.join(text)
        self.assertTrue(wait_for(lambda: stranger.logged("LOG join: refused"), 5))
        self.assertEqual(stranger.status()["phase"], 0)


if __name__ == "__main__":
    unittest.main()
