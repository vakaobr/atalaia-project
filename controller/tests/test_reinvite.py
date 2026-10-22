# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The start guard and re-inviting boxes over the radio (reinvite.py, protocol/field-frames.md).

The start guard (decisions RJ-1 to RJ-4): Start is refused while a role the game needs has no
joined node, with the roles named; {"force": true} starts anyway (logged, and told to the
consoles); a mode's minimums are warnings. The invites: a free box's announcements (made by the
simulator's model of the box, atalaia_sim.lobby.IdleBox) reach the engine through the modem's
FIELD_RX; the GM lists the boxes (the previous game's marked), invites one, and its HELLO in the
new game closes the invite. The real C box does the same in test_box_e2e.py.

    cd controller && python -m unittest tests.test_reinvite
"""

from __future__ import annotations

import random
import tempfile
import unittest

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Conflict, Controller, StartBlocked
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import field_frame as ff
from atalaia_sim import lobby
from atalaia_sim.packet import hello_encode

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
JOIN_KEY = bytes(range(32))
DOMINATION = "org.atalaia.domination"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def hello(name: str = "box", device: bytes | None = None) -> bytes:
    fields = {"node_name": name, "platform": 1, "fw_version": "0.4.0", "core_version": "0.2.0", "tier": 0,
              "capabilities": [0], "transports": 1, "epoch": 1}
    if device is not None:
        fields["device_id"] = device
    return hello_encode(fields)


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name)
        self.clock = Clock()
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, clock=self.clock,
                               join_key=JOIN_KEY)
        self.messages: list[dict] = []
        self.ctrl.add_listener(self.messages.append)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))

    def tearDown(self):
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def game(self, mode: str = DOMINATION, **spec) -> int:
        return self.ctrl.create_game({"name": "g", "mode_id": mode, "teams": ["red", "blue"], **spec})["id"]

    def heard(self, node_id: int, role: str | None = None, device: bytes | None = None, seq: int = 0) -> None:
        """A node says HELLO in the live game (a box over the radio, or a prop: both count)."""
        if role is not None:
            self.ctrl.fc.register_node(node_id, f"node-{node_id}", role)
        self.modem.rx(node_id, seq, "HELLO", hello(f"box-{node_id}", device), game_id=self.ctrl.game["id"], epoch=1)


class SharedNodeIdTests(Case):
    """Review finding 1 (decision BN-18): two devices on one (game key, node id) use the same nonces.
    The controller never issues a node id twice in a game, and says so loudly when two boxes still
    say HELLO on one (one card tapped on two boxes)."""

    def test_a_node_id_is_issued_once(self):
        self.game()
        self.assertEqual(self.ctrl.issue_join({"role": "zone"}, node_id=4)["node_id"], 4)
        with self.assertRaises(Conflict) as cm:
            self.ctrl.issue_join({"role": "zone"}, node_id=4)  # "replace the dead box on node 4"
        self.assertIn("new node id", str(cm.exception))
        # A box heard on a node id the GM pre-assigned: not issued again either.
        self.heard(6, "zone", bytes(range(8)))
        with self.assertRaises(Conflict):
            self.ctrl.issue_join({"role": "zone"}, node_id=6)
        # A replacement gets a new id; the same device invited again keeps its own (reinvite.py).
        self.assertNotIn(self.ctrl.issue_join({"role": "zone"})["node_id"], (4, 6))
        self.assertEqual(self.ctrl.issue_join({"role": "zone"}, node_id=4, same_device=True)["node_id"], 4)
        r = self.client.post("/api/v1/nodes/4/join", headers=GM, json={"role": "zone"})
        self.assertEqual(r.status_code, 409, r.text)

    def test_two_boxes_on_one_node_id_are_flagged(self):
        self.game()
        self.ctrl.issue_join({"role": "zone"}, node_id=4)
        self.heard(4, "zone", bytes(range(8)))
        self.heard(4, "zone", bytes(range(8)), seq=1)  # the same box again: fine
        self.assertFalse(any(m.get("kind") == "conflict" for m in self.messages))
        self.heard(4, "zone", bytes(range(8, 16)), seq=2)  # the card tapped on a second box
        alerts = [m for m in self.messages if m.get("kind") == "conflict"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["node"]["node_id"], 4)
        node = [n for n in self.client.get("/api/v1/nodes", headers=READ).json() if n["node_id"] == 4][0]
        self.assertTrue(node["conflict"])
        self.assertEqual(self.ctrl.conflicts[4], [bytes(range(8)).hex(), bytes(range(8, 16)).hex()])


class StartGuardTests(Case):
    def test_no_box_for_a_role_refuses_start(self):
        gid = self.game(assignments={"4": "zone"})  # assigned, but no box has joined yet
        check = self.ctrl.start_check()
        self.assertEqual((check["needed"], check["missing"], check["ok"]), (["zone"], ["zone"], False))
        self.assertEqual(self.ctrl.get_game(gid)["start_check"]["missing"], ["zone"])
        with self.assertRaises(StartBlocked) as cm:
            self.ctrl.start_game(gid)
        self.assertIn("zone", str(cm.exception))
        self.assertEqual(self.store.game(gid)["state"], "ready")
        self.heard(4)
        self.assertTrue(self.ctrl.start_check()["ok"])
        self.assertEqual(self.ctrl.start_game(gid)["state"], "running")
        self.assertFalse(any(m.get("kind") == "start.forced" for m in self.messages))

    def test_a_hello_updates_the_check_in_the_console(self):
        gid = self.game(assignments={"4": "zone"})
        self.messages.clear()
        self.heard(4)
        games = [m["game"] for m in self.messages if m["type"] == "game"]
        self.assertTrue(games and games[-1]["id"] == gid and games[-1]["start_check"]["ok"])

    def test_the_pushed_check_carries_what_the_invite_dialog_shows(self):
        """Decision GM-1: the invite dialog's "ready to start" comes from the game the controller
        pushes on each HELLO, with the engine's check: needed roles, joined count per role, missing
        roles and unmet minimums; the console computes none of it."""
        gid = self.game("org.atalaia.holdall", assignments={"4": "zone"})  # min_zones 2 by default
        self.messages.clear()
        self.heard(4)
        check = [m["game"] for m in self.messages if m["type"] == "game"][-1]["start_check"]
        self.assertEqual((check["needed"], check["joined"], check["missing"], check["ok"]),
                         (["zone"], {"zone": 1}, [], True))
        self.assertEqual([(w["code"], w["param"], w["value"], w["have"]) for w in check["warnings"]],
                         [("min", "min_zones", 2, 1)])
        self.assertEqual(self.client.get(f"/api/v1/games/{gid}/start-check", headers=GM).json(), check)

    def test_force_starts_anyway_and_says_so(self):
        gid = self.game()
        self.assertEqual(self.ctrl.start_game(gid, force=True)["state"], "running")
        forced = [m for m in self.messages if m.get("kind") == "start.forced"]
        self.assertEqual(forced, [{"type": "system", "kind": "start.forced", "game": gid, "missing": ["zone"]}])
        # A running game has no start check any more.
        self.assertNotIn("start_check", self.ctrl.get_game(gid))

    def test_every_role_of_the_mode_is_needed(self):
        gid = self.game("org.atalaia.master_satellites")
        self.heard(3, "master")
        self.assertEqual(self.ctrl.start_check()["missing"], ["satellite"])
        self.heard(5, "satellite")
        self.assertTrue(self.ctrl.start_check()["ok"])
        self.assertEqual(self.ctrl.start_check()["joined"], {"master": 1, "satellite": 1})
        self.assertEqual(self.ctrl.start_game(gid)["state"], "running")

    def test_a_role_package_needs_its_own_box(self):
        self.game(DOMINATION, modifiers=["org.atalaia.medic"])
        self.heard(4, "zone")
        self.assertEqual(self.ctrl.start_check()["missing"], ["medic"])

    def test_an_android_prop_counts(self):
        """A prop linked over Wi-Fi reaches the FieldController like a box: it counts."""
        gid = self.game("org.atalaia.kill_confirmed")
        self.ctrl.fc.register_node(9, "phone", "station")
        self.ctrl.fc.on_packet(9, self.modem_hello_header(9), hello("phone"), {"epoch": 0, "link": "wifi"})
        self.assertTrue(self.ctrl.start_check()["ok"])
        self.assertEqual(self.ctrl.start_game(gid)["state"], "running")

    def modem_hello_header(self, node: int):
        from atalaia_sim.packet import Header, vf_make
        from atalaia_sim.protocol import MESSAGE_TYPES
        return Header(vf_make(1, 2, False, True), self.ctrl.game["id"], node, 0, 0, MESSAGE_TYPES["HELLO"])

    def test_minimums_are_warnings(self):
        gid = self.game("org.atalaia.holdall", params={"min_zones": 3})
        self.heard(1, "zone")
        self.heard(2, "zone")
        check = self.ctrl.start_check()
        self.assertTrue(check["ok"])
        self.assertEqual([(w["code"], w["param"], w["value"], w["have"]) for w in check["warnings"]],
                         [("min", "min_zones", 3, 2)])
        self.assertEqual(self.ctrl.start_game(gid)["state"], "running")

    def test_last_stand_with_too_few_zones_warns(self):
        self.game("org.atalaia.laststand")
        self.heard(1, "zone")
        codes = sorted(w["code"] for w in self.ctrl.start_check()["warnings"])
        self.assertEqual(codes, ["last", "min"])  # last_zones 1, min_zones 2 by default
        self.heard(2, "zone")
        self.heard(3, "zone")
        self.assertEqual(self.ctrl.start_check()["warnings"], [])

    def test_the_api(self):
        gid = self.game()
        r = self.client.post(f"/api/v1/games/{gid}/start", headers=GM)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()["start_check"]["missing"], ["zone"])
        self.assertIn("zone", r.json()["detail"])
        self.assertEqual(self.client.get(f"/api/v1/games/{gid}/start-check", headers=READ).json()["missing"],
                         ["zone"])
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": "yes"}).status_code,
                         400)
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=READ, json={"force": True}).status_code,
                         403)
        r = self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True})
        self.assertEqual((r.status_code, r.json()["state"]), (200, "running"))
        self.assertEqual(self.client.get(f"/api/v1/games/{gid}/start-check", headers=READ).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/games/9/start-check", headers=READ).status_code, 400)

    def test_force_does_not_skip_the_firmware_guard(self):
        gid = self.game()
        self.ctrl.start_guard = lambda: "firmware updates are on their way"
        r = self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True})
        self.assertEqual(r.status_code, 409)
        self.assertIn("firmware", r.json()["detail"])


class ReinviteTests(Case):
    def setUp(self):
        super().setUp()
        self.box = lobby.IdleBox(JOIN_KEY, "Zona Norte", rng=random.Random(4), now_ms=self.ctrl.now_ms())

    def pump(self, seconds: float = 1.0, step: float = 0.05) -> None:
        """Time passes: the box and the controller tick, and the air carries their field frames."""
        for _ in range(int(seconds / step)):
            self.clock.advance(step)
            now = self.ctrl.now_ms()
            for frame in self.box.tick(now):
                self.modem.on_field_rx(frame, -71, 6)
            self.ctrl.tick()
            while self.modem.fields:
                self.box.on_frame(self.modem.fields.pop(0), now)

    def first_game_with_the_box(self) -> int:
        gid = self.game(assignments={"4": "zone"})
        self.assertEqual(self.box.join(bytes.fromhex(self.ctrl.issue_join({"role": "zone"}, node_id=4)["payload_hex"])),
                         "accepted")
        self.heard(4, device=self.box.device_id)
        self.ctrl.start_game(gid)
        self.box.start()
        self.ctrl.end_game(gid)
        self.box.end(self.ctrl.now_ms())
        return gid

    def test_a_box_from_the_last_game_is_invited_into_the_next(self):
        first = self.first_game_with_the_box()
        self.assertEqual(self.store.nodes(first)[0]["device_id"], self.box.device_id.hex())
        self.pump(21)  # the box's first announcement after the end
        gid = self.game()
        listed = self.client.get("/api/v1/boxes", headers=GM).json()
        self.assertEqual(listed["previous_game"]["id"], first)
        [box] = listed["boxes"]
        self.assertEqual((box["device_id"], box["name"], box["previous"], box["previous_role"], box["rssi"]),
                         (self.box.device_id.hex(), "Zona Norte", True, "zone", -71))
        self.assertNotIn("token", box)
        r = self.client.post(f"/api/v1/games/{gid}/invites", headers=GM,
                             json={"boxes": [{"device_id": self.box.device_id.hex(), "role": "zone"}]})
        self.assertEqual(r.status_code, 200, r.text)
        [inv] = r.json()["invites"]
        self.assertEqual((inv["status"], inv["role"], inv["game"]), ("invited", "zone", gid))
        self.assertTrue(self.modem.fields)  # the INVITE parts, sealed, on their way through FIELD_TX
        self.pump(2)
        self.assertEqual(self.box.game["game_id"], gid)
        self.assertEqual(self.client.get(f"/api/v1/games/{gid}/invites", headers=GM).json()["invites"][0]["status"],
                         "accepted")
        self.assertFalse(self.ctrl.start_check()["ok"])  # accepted is not joined: the HELLO is
        self.heard(inv["node_id"], device=self.box.device_id)
        self.assertEqual(self.client.get(f"/api/v1/games/{gid}/invites", headers=GM).json()["invites"][0]["status"],
                         "joined")
        self.assertTrue(self.ctrl.start_check()["ok"])
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).json()["state"], "running")
        # The consoles were told along the way.
        kinds = {m["type"] for m in self.messages}
        self.assertTrue({"boxes", "invites"} <= kinds)
        statuses = [m["invites"][0]["status"] for m in self.messages if m["type"] == "invites" and m["invites"]]
        self.assertEqual(statuses[-1], "joined")
        self.assertIn("accepted", statuses)

    def test_no_answer_fails_after_three_attempts(self):
        self.first_game_with_the_box()
        self.pump(21)
        gid = self.game()
        device = self.box.device_id.hex()
        self.box.standalone = True  # it will answer busy...
        self.box.key = bytes(16)    # ...no: it cannot read anything any more (another key)
        self.client.post(f"/api/v1/games/{gid}/invites", headers=GM, json={"boxes": [{"device_id": device,
                                                                                       "role": "zone"}]})
        self.pump(lobby.INVITE_ATTEMPTS * (lobby.INVITE_RETRY_MS / 1000 + 2))
        [inv] = self.client.get(f"/api/v1/games/{gid}/invites", headers=GM).json()["invites"]
        self.assertEqual((inv["status"], inv["detail"], inv["attempts"]), ("failed", "no answer", 3))

    def test_a_busy_box_says_so(self):
        self.first_game_with_the_box()
        self.pump(21)
        gid = self.game()
        self.box.standalone = True
        self.client.post(f"/api/v1/games/{gid}/invites", headers=GM,
                         json={"boxes": [{"device_id": self.box.device_id.hex(), "role": "zone"}]})
        self.pump(2)
        [inv] = self.client.get(f"/api/v1/games/{gid}/invites", headers=GM).json()["invites"]
        self.assertEqual((inv["status"], inv["detail"]), ("refused", "busy"))

    def test_discover_and_refusals(self):
        self.pump(21)
        self.assertEqual(len(self.client.get("/api/v1/boxes", headers=GM).json()["boxes"]), 1)
        self.modem.fields.clear()
        self.assertEqual(self.client.post("/api/v1/boxes/discover", headers=GM).json(), {"sent": True})
        self.assertEqual(ff.decode(ff.field_key(JOIN_KEY), self.modem.fields[0]), {"kind": "discover"})
        self.assertEqual(self.client.post("/api/v1/boxes/discover", headers=GM).json(), {"sent": False})
        self.assertEqual(self.client.get("/api/v1/boxes", headers=READ).status_code, 403)
        # No live game, a box nobody heard, a bad device id.
        device = self.box.device_id.hex()
        self.assertEqual(self.client.post("/api/v1/games/5/invites", headers=GM,
                                          json={"boxes": [{"device_id": device}]}).status_code, 409)
        gid = self.game()
        r = self.client.post(f"/api/v1/games/{gid}/invites", headers=GM,
                             json={"boxes": [{"device_id": "00" * 8, "role": "zone"}]})
        self.assertEqual(r.json()["invites"], [{"device_id": "00" * 8, "status": "failed",
                                                "detail": "not announcing itself"}])
        for bad in ({"boxes": []}, {"boxes": [{"device_id": "xyz"}]}, {"boxes": "all"}):
            self.assertEqual(self.client.post(f"/api/v1/games/{gid}/invites", headers=GM, json=bad).status_code, 400)
        # Without a radio: 503.
        self.modem.state = "down"
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/invites", headers=GM,
                                          json={"boxes": [{"device_id": device, "role": "zone"}]}).status_code, 503)
        self.assertEqual(self.client.post("/api/v1/boxes/discover", headers=GM).status_code, 503)
        self.modem.state = "up"
        # Once the game runs, nobody is invited into it.
        self.ctrl.start_game(gid, force=True)
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/invites", headers=GM,
                                          json={"boxes": [{"device_id": device, "role": "zone"}]}).status_code, 409)

    def test_no_retries_after_the_game_ends(self):
        """The GM ends the game while an invite waits for an answer: it goes, nothing more is sent
        into the game that is over (review finding 5)."""
        self.first_game_with_the_box()
        self.pump(21)
        gid = self.game()
        self.box.key = bytes(16)  # the box hears nothing: the invite would be retried
        self.client.post(f"/api/v1/games/{gid}/invites", headers=GM,
                         json={"boxes": [{"device_id": self.box.device_id.hex(), "role": "zone"}]})
        self.ctrl.end_game(gid)
        self.modem.fields.clear()
        self.pump(lobby.INVITE_RETRY_MS / 1000 * 3)
        invites = [ff.decode(ff.field_key(JOIN_KEY), f) for f in self.modem.fields]
        self.assertEqual([m for m in invites if m["kind"] == "invite"], [])
        self.assertEqual(self.ctrl.reinvite.invites(gid), [])

    def test_a_stale_announcement_is_refused(self):
        """An announcement heard again (recorded, played back) changes nothing (review finding 4)."""
        frames = []
        for _ in range(450):
            self.clock.advance(0.05)
            frames += self.box.tick(self.ctrl.now_ms())
        self.assertTrue(frames)
        for f in frames:
            self.modem.on_field_rx(f, -70, 5)
        listed = self.client.get("/api/v1/boxes", headers=GM).json()
        self.assertEqual((len(listed["boxes"]), listed["stale"]), (1, 0))
        self.modem.on_field_rx(frames[0], -40, 5)
        listed = self.client.get("/api/v1/boxes", headers=GM).json()
        self.assertEqual((listed["stale"], listed["boxes"][0]["rssi"]), (1, -70))

    def test_a_new_sender_id_every_run(self):
        """The controller's nonces never roll back (review finding 1): a fresh sender id each run,
        nothing about them stored, so a restored backup or a copied database cannot repeat one."""
        first = self.ctrl.reinvite.sender_id
        self.ctrl.reinvite.inviter.discover(self.ctrl.now_ms())
        nonce_a = self.modem.fields[-1][ff.HEADER_SIZE:ff.HEADER_SIZE + ff.NONCE_SIZE]
        self.assertEqual(nonce_a[8:], (1).to_bytes(3, "big") + (0).to_bytes(2, "big"))
        self.assertIsNone(self.store.get_setting("field.sender_id"))
        self.assertIsNone(self.store.get_setting("field.boot"))
        again = Controller(self.cfg, self.store, modem=self.modem, core=CORE, clock=self.clock, join_key=JOIN_KEY)
        self.assertNotEqual(again.reinvite.sender_id, first)
        again.reinvite.inviter.discover(again.now_ms())
        nonce_b = self.modem.fields[-1][ff.HEADER_SIZE:ff.HEADER_SIZE + ff.NONCE_SIZE]
        self.assertNotEqual(nonce_a, nonce_b)
        again.stop()

    def test_another_fields_box_is_not_listed(self):
        stranger = lobby.IdleBox(bytes(range(1, 33)), "theirs", rng=random.Random(8), now_ms=self.ctrl.now_ms())
        for _ in range(450):
            self.clock.advance(0.05)
            for frame in stranger.tick(self.ctrl.now_ms()):
                self.modem.on_field_rx(frame, -90, 0)
        listed = self.client.get("/api/v1/boxes", headers=GM).json()
        self.assertEqual(listed["boxes"], [])
        self.assertGreater(listed["ignored"], 0)


if __name__ == "__main__":
    unittest.main()
