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

import json
import os
import tempfile
import time
import unittest

from fastapi.testclient import TestClient

from support import (BOX_HOST, CORE, MODEM_HOST, AirHub, BoxHost, HostModem, config, wait_for)
from atalaia_sim import tag as player_tag
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

    def test_hold_all_scores_from_the_controller(self):
        """Hold-All Domination: two boxes, the controller's field.lua scores while red holds both."""
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "hold all", "mode_id": "org.atalaia.holdall", "teams": ["red", "blue"],
            "params": {"capture_hold_ms": 1000, "tick_s": 1, "points_per_tick": 5}})
        self.assertEqual(r.status_code, 201, r.text)
        gid = r.json()["id"]
        alpha, bravo = self.box("alpha"), self.box("bravo")
        n_alpha, n_bravo = self.join(alpha), self.join(bravo)
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).status_code, 200)
        self.assertTrue(wait_for(lambda: bravo.status()["phase"] == 2, 5))
        alpha.hold(1, 1300)
        self.assertTrue(wait_for(lambda: self.node(n_alpha).get("owner") == "red", 8))
        self.assertEqual(self.score(gid, "red"), 0)  # one box is not enough
        bravo.hold(1, 1300)
        ctrl = self.ctrl.node_id
        self.assertTrue(wait_for(lambda: "holdall.scoring_start" in self.log_types(gid, ctrl), 8))
        self.assertTrue(wait_for(lambda: self.score(gid, "red") >= 10, 8))
        self.assertEqual((alpha.status()["phase"], self.node(n_bravo)["owner"]), (2, "red"))
        bravo.hold(2, 1300)  # blue takes one back: the scoring stops
        self.assertTrue(wait_for(lambda: "holdall.scoring_stop" in self.log_types(gid, ctrl), 8))

    def test_master_and_satellites_frees_the_satellites_over_the_radio(self):
        """Master and Satellites: the controller's field.lua scores the master's holder with the
        satellite bonus, and when the master changes hands its field.send(set_owner none) reaches
        the satellite box over the radio, which frees itself."""
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "master", "mode_id": "org.atalaia.master_satellites", "teams": ["red", "blue"],
            "params": {"capture_hold_ms": 1000, "tick_s": 1, "points_per_tick": 2}})
        self.assertEqual(r.status_code, 201, r.text)
        gid = r.json()["id"]
        master, sat = self.box("master"), self.box("sat")
        n_master, n_sat = self.join(master, role="master"), self.join(sat, role="satellite")
        self.assertTrue(master.logged("org.atalaia.master_satellites, master"), master.lines[-5:])
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).status_code, 200)
        self.assertTrue(wait_for(lambda: sat.status()["phase"] == 2, 5))
        sat.hold(1, 1300)
        self.assertTrue(wait_for(lambda: self.node(n_sat).get("owner") == "red", 8))
        self.assertEqual(self.score(gid, "red"), 0)  # a satellite alone scores nothing
        master.hold(1, 1300)
        self.assertTrue(wait_for(lambda: self.node(n_master).get("owner") == "red", 8))
        self.assertTrue(wait_for(lambda: self.score(gid, "red") >= 9, 10))  # 3 a tick: 2 + 1
        master.hold(2, 1300)  # blue takes the master: the satellite is freed
        self.assertTrue(wait_for(lambda: "zone.neutralized" in self.log_types(gid, n_sat), 8))
        self.assertTrue(wait_for(lambda: self.node(n_sat).get("owner") is None, 8))
        self.assertTrue(wait_for(lambda: self.score(gid, "blue") >= 4, 8))  # 2 a tick, no bonus
        freed = [e for e in self.client.get(f"/api/v1/games/{gid}/log", headers=READ).json()
                 if e["type"] == "zone.neutralized"][0]
        self.assertEqual((freed["node"], freed["data"]["previous_team"]), (n_sat, "red"))

    def test_hacking_terminal_on_a_box(self):
        """The Hacking Terminal on a host box: red presses its button, a key shows the sequence on
        the box's screen (read here from its SCREEN lines, as a player reads the screen), typing
        it back solves it; hacking.solved (critical) with the code it reveals, the capture and
        red's points reach the controller over the radio; the GM's "reset" gives a new puzzle
        at once."""
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "hack", "mode_id": "org.atalaia.hacking_terminal", "teams": ["red", "blue"],
            "params": {"puzzle": "sequence", "digits": 3, "reveal_code": "4711", "capture": True}})
        self.assertEqual(r.status_code, 201, r.text)
        gid = r.json()["id"]
        box = self.box("terminal")
        nid = self.join(box, role="terminal")
        self.assertTrue(box.logged("org.atalaia.hacking_terminal, terminal"), box.lines[-5:])
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).status_code, 200)
        self.assertTrue(wait_for(lambda: box.status()["phase"] == 2, 5))
        box.hold(1, 100)  # red at the keypad

        def screens(name: str) -> list[dict]:
            return [json.loads(line.split(" ", 2)[2]) for line in list(box.lines)
                    if line.startswith(f"SCREEN {name} ")]

        box.send("keys 5")
        self.assertTrue(wait_for(lambda: any(d.get("phase") == "input" for d in screens("hack_sequence")), 8),
                        box.lines[-12:])
        shown = {d["step"]: d["key"] for d in screens("hack_sequence") if d.get("phase") == "show"}
        self.assertEqual(sorted(shown), [1, 2, 3])
        self.assertTrue(all(1 <= k <= 9 for k in shown.values()), shown)
        box.send("keys " + "".join(str(shown[i]) for i in (1, 2, 3)))
        self.assertTrue(wait_for(lambda: any(d.get("code") == "4711" for d in screens("hack_solved")), 5))
        # The solved screen stays 10 s before the next puzzle; the GM's "New puzzle" (a mode
        # command, CMD opcode 8, over the radio) brings one at once.
        before = len(screens("hack_sequence"))
        r = self.client.post(f"/api/v1/nodes/{nid}/cmd", headers=GM,
                             json={"cmd": "mode", "params": {"name": "reset"}})
        self.assertEqual(r.status_code, 202, r.text)
        self.assertTrue(wait_for(lambda: len(screens("hack_sequence")) > before, 5), box.lines[-5:])
        self.assertEqual((screens("hack_sequence")[-1]["phase"], screens("hack_sequence")[-1]["owner"]),
                         ("idle", "red"))

        self.assertTrue(wait_for(lambda: "hacking.solved" in self.log_types(gid, nid), 8))
        solved = [e for e in self.client.get(f"/api/v1/games/{gid}/log", headers=READ).json()
                  if e["type"] == "hacking.solved"][0]
        self.assertEqual((solved["team"], solved["prio"], solved["data"]["puzzle"], solved["data"]["code"]),
                         ("red", "critical", "sequence", "4711"))
        self.assertTrue(wait_for(lambda: self.node(nid).get("owner") == "red", 8))
        self.assertTrue(wait_for(lambda: self.score(gid, "red") >= 10, 8))

    def test_codes_modifier_on_a_box(self):
        """Domination with the Codes modifier: the box composes both scripts; a code reaches the GM."""
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "codes", "mode_id": "org.atalaia.domination", "modifiers": ["org.atalaia.codes"],
            "teams": ["red", "blue"], "params": {"capture_hold_ms": 1000, "codes": "4711:points:50"}})
        self.assertEqual(r.status_code, 201, r.text)
        gid = r.json()["id"]
        box = self.box("alpha")
        nid = self.join(box)
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).status_code, 200)
        self.assertTrue(wait_for(lambda: box.status()["phase"] == 2, 5))
        box.hold(1, 1300)
        self.assertTrue(wait_for(lambda: "zone.captured" in self.log_types(gid, nid), 8))
        box.send("keys 4711#")
        self.assertTrue(wait_for(lambda: "code.used" in self.log_types(gid, nid), 8))
        used = [e for e in self.client.get(f"/api/v1/games/{gid}/log", headers=READ).json()
                if e["type"] == "code.used"][0]
        self.assertEqual((used["team"], used["data"]["kind"], used["data"]["amount"], used["data"]["holder"]),
                         ("red", "points", 50, "red"))
        self.assertTrue(wait_for(lambda: self.score(gid, "red") >= 50, 8))

    def test_medic_kits_share_a_players_limit(self):
        """Domination with the Medic Kit (a role package): two boxes join as kits and run the
        kit alone; a player healed at one kit is at the limit at the other, because the
        controller's field.lua tells it over the radio (CMD opcode 8); the GM refills a kit."""
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "medics", "mode_id": "org.atalaia.domination", "modifiers": ["org.atalaia.medic"],
            "teams": ["red", "blue"],
            "params": {"heal_hold_s": 1, "charges": 1, "max_heals_per_player": 1, "lang": "en"}})
        self.assertEqual(r.status_code, 201, r.text)
        gid = r.json()["id"]
        north, south = self.box("north"), self.box("south")
        n_north, n_south = self.join(north, role="medic"), self.join(south, role="medic")
        self.assertTrue(north.logged("org.atalaia.medic, medic"), north.lines[-5:])
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).status_code, 200)
        self.assertTrue(wait_for(lambda: south.status()["phase"] == 2, 5))
        key = self.ctrl.game_key(gid)

        def scan(box: BoxHost, player: str) -> None:
            payload = player_tag.encode({"player": player, "team": 2, "game_id": gid}, key)
            before = box.lines.count("LOG tag read")
            box.send(f"@tag 04a1b2c3d4e5f6 {payload.hex()}")
            self.assertTrue(wait_for(lambda: box.lines.count("LOG tag read") > before, 3))

        def heals(node_id: int) -> list[dict]:
            return [e for e in self.client.get(f"/api/v1/games/{gid}/log", headers=READ).json()
                    if e["type"] == "medic.heal" and e["node"] == node_id]

        scan(north, "b1")
        north.hold(2, 1300)
        self.assertTrue(wait_for(lambda: heals(n_north), 8))
        self.assertEqual((heals(n_north)[0]["team"], heals(n_north)[0]["data"]),
                         ("blue", {"team": "blue", "player": "b1", "remaining": 0, "player_heals_used": 1}))
        self.assertTrue(wait_for(lambda: "medic.empty" in self.log_types(gid, n_north), 8))
        # The controller's word reaches the south kit: b1 is at the limit there.
        time.sleep(1.0)
        scan(south, "b1")
        south.hold(2, 1300)
        time.sleep(2.5)
        self.assertEqual(heals(n_south), [])
        # Another player is healed there; the GM refills the north kit, which heals again.
        scan(south, "b2")
        south.hold(2, 1300)
        self.assertTrue(wait_for(lambda: heals(n_south), 8))
        r = self.client.post(f"/api/v1/nodes/{n_north}/cmd", headers=GM,
                             json={"cmd": "mode", "params": {"name": "refill"}})
        self.assertEqual(r.status_code, 202, r.text)
        time.sleep(1.0)
        scan(north, "b3")
        north.hold(1, 1300)
        self.assertTrue(wait_for(lambda: len(heals(n_north)) == 2, 8))

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
