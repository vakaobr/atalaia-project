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
from unittest import mock

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from atalaia_controller import wallclock
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
        # A count of one takes "node", not "nodes" (decision PLU-2).
        self.assertEqual(check["warnings"][0]["text"], "1 zone node joined; min_zones is 2")
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
        self.assertEqual(check["warnings"][0]["text"], "2 zone nodes joined; min_zones is 3")
        self.assertEqual(self.ctrl.start_game(gid)["state"], "running")

    def test_last_stand_with_too_few_zones_warns(self):
        self.game("org.atalaia.laststand")
        self.heard(1, "zone")
        codes = sorted(w["code"] for w in self.ctrl.start_check()["warnings"])
        self.assertEqual(codes, ["last", "min"])  # last_zones 1, min_zones 2 by default
        last = [w["text"] for w in self.ctrl.start_check()["warnings"] if w["code"] == "last"]
        self.assertTrue(last[0].startswith("only 1 zone node joined and last_zones is 1"), last)
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
        self.assertEqual(self.client.post("/api/v1/boxes/discover", headers=GM).json(), {"sent": True, "sweep": [], "sweep_refused": None})
        self.assertEqual(ff.decode(ff.field_key(JOIN_KEY), self.modem.fields[0]), {"kind": "discover"})
        self.assertEqual(self.client.post("/api/v1/boxes/discover", headers=GM).json(), {"sent": False, "sweep": [], "sweep_refused": None})
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


class GameOverTests(ReinviteTests):
    """Decisions OT-7 and OT-13: when a game ends, GAME_OVER (its id and its key's tag) goes to its boxes
    over the field radio, three times; a controller that restarted without the game's key ends the game
    this way, and its box leaves it."""

    def restart(self, **cfg) -> None:
        self.client.close()
        self.ctrl.stop()
        for k, v in cfg.items():
            setattr(self.cfg, k, v)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, clock=self.clock, join_key=JOIN_KEY)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))

    def frames(self) -> list[dict]:
        key = ff.field_key(JOIN_KEY)
        return [ff.decode(key, f) for f in self.modem.fields]

    def test_persisted_by_default(self):
        self.assertTrue(config(self.tmp.name).persist_game_key)

    def test_a_restart_without_the_key_still_ends_the_boxes_game(self):
        self.cfg.persist_game_key = False
        gid = self.game(assignments={"4": "zone"})
        key = self.ctrl.game_key(gid)
        self.assertEqual(self.box.join(bytes.fromhex(self.ctrl.issue_join({"role": "zone"}, node_id=4)["payload_hex"])),
                         "accepted")
        self.heard(4, device=self.box.device_id)
        self.ctrl.start_game(gid)
        self.box.start()
        self.restart(persist_game_key=False)  # the Pi restarted, the key was not kept
        self.assertTrue(self.ctrl.status()["key_lost"])
        r = self.client.post(f"/api/v1/games/{gid}/end", headers=GM, json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["state"], r.json()["game_over_frame"]), ("ended", "sent"))
        self.assertEqual(self.frames(), [{"kind": "game_over", "game_id": gid, "key_tag": ff.key_tag(key)}])
        self.assertEqual(self.modem.channels, [])  # the game's channel is the field's: no retuning
        while self.modem.fields:
            self.box.on_frame(self.modem.fields.pop(0), self.ctrl.now_ms())
        self.assertEqual(self.box.phase, "ended")
        # Bounded: three in all, about 4 s apart; the box announces itself and is listed again.
        sent = 1
        for _ in range(int(25 / 0.05)):
            self.clock.advance(0.05)
            self.ctrl.tick()
            sent += len(self.modem.fields)
            self.modem.fields.clear()
            for frame in self.box.tick(self.ctrl.now_ms()):
                self.modem.on_field_rx(frame, -71, 6)
        self.assertEqual(sent, lobby.GAME_OVER_REPEATS)
        listed = self.client.get("/api/v1/boxes", headers=GM).json()["boxes"]
        self.assertEqual([(b["name"], b["last_game"]) for b in listed], [("Zona Norte", gid)])
        # The tag stays (STUCK-3): a box still in the game can be told again.
        self.assertEqual(self.store.get_setting(f"key_tag:{gid}"), ff.key_tag(key).hex())

    def test_after_every_end_and_on_the_games_channel(self):
        gid = self.game(assignments={"4": "zone"})
        key = self.ctrl.game_key(gid)
        self.ctrl.start_game(gid, force=True)
        # The field's channel is another by the time the game ends (chosen while it ran, as a
        # standby's could be); the game's boxes still listen where it was made.
        self.store.set_setting("radio.channel_hz", "868100000")
        self.modem.channels.clear()
        out = self.ctrl.end_game(gid)
        self.assertEqual(out["game_over_frame"], "sent")
        self.assertEqual(self.frames(), [{"kind": "game_over", "game_id": gid, "key_tag": ff.key_tag(key)}])
        self.assertEqual(self.modem.channels, [869_525_000])  # its boxes listen on the game's channel
        for _ in range(int(15 / 0.05)):
            self.clock.advance(0.05)
            self.ctrl.tick()
        self.assertEqual(len(self.modem.fields), lobby.GAME_OVER_REPEATS)
        self.assertEqual(self.modem.channels, [869_525_000, 868_100_000])  # then back on the field's

    def test_no_radio_and_a_standby(self):
        gid = self.game(assignments={"4": "zone"})
        self.modem.state = "down"
        self.assertEqual(self.ctrl.end_game(gid)["game_over_frame"], "no_radio")
        self.assertEqual(self.modem.fields, [])


class StuckGameTests(GameOverTests):
    """Decisions STUCK-1 to STUCK-19, RFC 0001 Amendment 27 (the bench finding of 2026-11-05): a box switched
    off when its game ended never heard the GAME_OVERs and comes back still in that game. The modem
    reports another game's packets (OTHER_GAME); for a game this controller ran and ended, whose key's
    tag it keeps, the controller says its GAME_OVER again, at most once a minute per game."""

    def ended_game_with_a_stuck_box(self, **cfg) -> tuple[int, bytes]:
        """A game played with the box, the box switched off, the game ended without it."""
        gid = self.game(assignments={"4": "zone"})
        key = self.ctrl.game_key(gid)
        self.assertEqual(self.box.join(bytes.fromhex(self.ctrl.issue_join({"role": "zone"}, node_id=4)["payload_hex"])),
                         "accepted")
        self.heard(4, device=self.box.device_id)
        self.ctrl.start_game(gid)
        self.box.start()
        if cfg:
            self.restart(**cfg)
        self.ctrl.end_game(gid)
        self.drain(10)  # the three GAME_OVERs go, unheard: the box is off
        self.assertEqual(self.box.phase, "playing")
        return gid, key

    def drain(self, seconds: float) -> int:
        """Time passes; the field frames the controller sends are counted and dropped (no box hears)."""
        sent = len(self.modem.fields)
        self.modem.fields.clear()
        for _ in range(int(seconds / 0.05)):
            self.clock.advance(0.05)
            self.ctrl.tick()
            sent += len(self.modem.fields)
            self.modem.fields.clear()
        return sent

    def test_the_modem_is_asked(self):
        self.assertEqual(self.modem.watching, [True])

    def test_a_box_still_in_an_ended_game_is_told_again_and_freed(self):
        gid, key = self.ended_game_with_a_stuck_box()
        self.box.start()  # switched on again: still in the ended game, its packets heard by the modem
        with self.assertLogs("atalaia.reinvite", "INFO") as logs:
            self.modem.other_game(gid, 4)
        self.assertIn(f"game {gid}: a box is still in it; GAME_OVER sent again", logs.output[0])
        self.assertEqual(self.frames(), [{"kind": "game_over", "game_id": gid, "key_tag": ff.key_tag(key)}])
        while self.modem.fields:
            self.box.on_frame(self.modem.fields.pop(0), self.ctrl.now_ms())
        self.assertEqual(self.box.phase, "ended")
        self.pump(21)  # it announces itself free, and is listed for an invite
        listed = self.client.get("/api/v1/boxes", headers=GM).json()
        self.assertEqual([(b["name"], b["last_game"]) for b in listed["boxes"]], [("Zona Norte", gid)])
        [stuck] = listed["stuck"]
        self.assertEqual((stuck["game"], stuck["nodes"], stuck["rssi"], stuck["game_over_resent"]), (gid, [4], -70, 1))
        self.assertEqual((stuck["last_heard_s"], listed["stuck_reports"], listed["stuck_watch"]), (21, 1, True))
        self.assertEqual(listed["radio_kind"], "modem")  # the console's hint fits a USB radio modem (STUCK-64)
        self.assertIn("boxes", {m["type"] for m in self.messages})

    def test_at_most_once_a_minute_per_game(self):
        gid, _ = self.ended_game_with_a_stuck_box()
        self.modem.other_game(gid, 4)
        self.assertEqual(self.drain(10), lobby.GAME_OVER_REPEATS)
        for _ in range(5):  # the modem's next reports, 10 s apart
            self.modem.other_game(gid, 4)
            self.assertEqual(self.drain(10), 0)
        self.modem.other_game(gid, 5)  # a minute after the first burst: another
        self.assertEqual(self.drain(10), lobby.GAME_OVER_REPEATS)
        [stuck] = self.client.get("/api/v1/boxes", headers=GM).json()["stuck"]
        self.assertEqual((stuck["nodes"], stuck["game_over_resent"]), ([4, 5], 2))

    def test_a_game_unheard_for_two_minutes_leaves_the_list_and_comes_back_when_heard(self):
        """STUCK-71 (the bench finding of 2026-11-06): a freed box looked stuck for two hours. The list
        shows a game heard within SHOWN_MS; what was heard stays FORGET_MS, so a box heard again keeps
        its game's resend count and its once-a-minute limit."""
        from atalaia_controller.stuck_games import FORGET_MS, SHOWN_MS
        gid, _ = self.ended_game_with_a_stuck_box()
        self.modem.other_game(gid, 4)
        self.assertEqual(self.drain(10), lobby.GAME_OVER_REPEATS)
        self.clock.advance(SHOWN_MS / 1000 - 10)  # two minutes after it was heard: still listed
        [stuck] = self.client.get("/api/v1/boxes", headers=GM).json()["stuck"]
        self.assertEqual((stuck["game"], stuck["last_heard_s"]), (gid, SHOWN_MS // 1000))
        self.clock.advance(1)  # then silent (freed, or switched off): gone from the list and the stream's
        self.assertEqual(self.client.get("/api/v1/boxes", headers=GM).json()["stuck"], [])
        self.assertEqual(self.ctrl.reinvite.stuck_view()["stuck"], [])
        self.assertIn(gid, self.ctrl.stuck.games)  # remembered
        self.modem.other_game(gid, 5)  # heard again: listed again, the count goes on
        self.drain(10)
        [stuck] = self.client.get("/api/v1/boxes", headers=GM).json()["stuck"]
        self.assertEqual((stuck["nodes"], stuck["last_heard_s"], stuck["game_over_resent"]), ([4, 5], 10, 2))
        self.clock.advance(FORGET_MS / 1000 + 1)
        self.assertEqual(self.client.get("/api/v1/boxes", headers=GM).json()["stuck"], [])
        self.assertNotIn(gid, self.ctrl.stuck.games)  # forgotten after two hours, as before

    def test_after_a_restart_without_the_key(self):
        gid, key = self.ended_game_with_a_stuck_box(persist_game_key=False)
        self.restart(persist_game_key=False)
        self.modem.other_game(gid, 4)
        self.assertEqual(self.frames(), [{"kind": "game_over", "game_id": gid, "key_tag": ff.key_tag(key)}])

    def test_another_fields_game_the_live_game_and_a_game_with_no_tag_change_nothing(self):
        gid, _ = self.ended_game_with_a_stuck_box()
        self.modem.other_game(999, 4)  # not a game of this controller
        live = self.game()
        self.modem.other_game(live, 4)  # the live game's own (not over)
        self.store.delete_setting(f"key_tag:{gid}")  # a game ended before tags were kept
        self.modem.other_game(gid, 4)
        self.assertEqual(self.drain(10), 0)
        listed = self.client.get("/api/v1/boxes", headers=GM).json()
        self.assertEqual((listed["stuck"], listed["stuck_reports"], self.ctrl.stuck.unknown), ([], 3, 2))

    def test_with_a_game_live_on_another_channel_it_is_dropped(self):
        gid, _ = self.ended_game_with_a_stuck_box()
        self.store.set_setting("radio.channel_hz", "868100000")
        self.game()  # live on 868.1 MHz; the stuck box is on 869.525 MHz
        self.modem.channels.clear()
        self.modem.other_game(gid, 4)
        self.assertEqual(self.drain(10), 0)
        self.assertEqual(self.modem.channels, [])

    def test_the_tags_kept_are_bounded(self):
        from atalaia_controller.stuck_games import prune_key_tags
        ids = []
        for _ in range(3):
            g = self.game()
            self.ctrl.end_game(g)
            ids.append(g)
        self.assertTrue(all(self.store.get_setting(f"key_tag:{g}") for g in ids))
        live = self.game()
        prune_key_tags(self.store, keep=2)
        self.assertEqual([self.store.get_setting(f"key_tag:{g}") is not None for g in ids], [False, True, True])
        self.assertIsNotNone(self.store.get_setting(f"key_tag:{live}"))  # a live game's always stays

    def test_a_standby_never_sends_it(self):
        from atalaia_sim import join
        gid, _ = self.ended_game_with_a_stuck_box()
        payload = join.encode({"game_id": 77, "game_key": bytes(range(16)), "node_id": 3, "controller_id": 1,
                               "channel_hz": 869_525_000, "max_hops": 2, "teams": ["red", "blue"],
                               "mode_id": DOMINATION, "role": "standby", "game_seed": 1, "params": None,
                               "kind": "controller"}, JOIN_KEY)
        self.ctrl.join_as_standby(join.to_text(payload))
        self.modem.other_game(gid, 4)  # following a game: its primary tells the boxes
        self.assertEqual(self.drain(10), 0)
        self.ctrl.end_game(77)  # left: its game is the primary's, never told from here
        self.assertIsNotNone(self.store.get_setting("key_tag:77"))
        self.modem.other_game(77, 4)
        self.assertEqual(self.drain(10), 0)

    # --- the GM's Release (decisions STUCK-40 to STUCK-47) ---------------------------------------

    def release(self, gid: int):
        return self.client.post(f"/api/v1/boxes/stuck/{gid}/release", headers=GM)

    def test_the_gms_release_says_the_games_game_over_now(self):
        gid, key = self.ended_game_with_a_stuck_box()
        self.box.start()
        self.modem.other_game(gid, 4)
        self.drain(65)  # the automatic burst is over, the next one is a minute away
        [stuck] = self.client.get("/api/v1/boxes", headers=GM).json()["stuck"]
        self.assertEqual((stuck["game"], stuck["name"], stuck["game_over_resent"]),
                         (gid, self.store.game(gid)["name"], 1))
        self.messages.clear()
        with self.assertLogs("atalaia.reinvite", "INFO") as logs:
            r = self.release(gid)
        self.assertEqual((r.status_code, r.json()), (200, {"game": gid, "game_over_frame": "sent"}))
        self.assertIn(f"game {gid}: released by the GM; GAME_OVER sent again", logs.output[0])
        self.assertEqual(self.frames(), [{"kind": "game_over", "game_id": gid, "key_tag": ff.key_tag(key)}])
        # The consoles hear of it on the stream, with the stuck list.
        [msg] = [m for m in self.messages if m["type"] == "boxes"]
        self.assertEqual((msg["stuck"][0]["game_over_resent"], msg["stuck_watch"], msg["radio_kind"]), (2, True, "modem"))
        while self.modem.fields:
            self.box.on_frame(self.modem.fields.pop(0), self.ctrl.now_ms())
        self.assertEqual(self.box.phase, "ended")

    def test_release_has_a_short_rate_limit(self):
        gid, _ = self.ended_game_with_a_stuck_box()
        self.assertEqual(self.release(gid).json()["game_over_frame"], "sent")  # not heard: allowed too
        r = self.release(gid)  # its GAME_OVERs are still being said
        self.assertEqual(r.status_code, 429, r.text)
        self.assertEqual(self.drain(9), lobby.GAME_OVER_REPEATS)  # the first one included
        self.assertEqual(self.release(gid).status_code, 429)  # under 10 s since the burst started
        self.drain(1.1)
        self.assertEqual(self.release(gid).json()["game_over_frame"], "sent")

    def test_release_refuses_what_it_cannot_end(self):
        gid, _ = self.ended_game_with_a_stuck_box()
        self.assertEqual(self.release(9999).status_code, 404)
        live = self.game()
        self.assertEqual(self.release(live).status_code, 409)  # not over
        self.store.delete_setting(f"key_tag:{gid}")
        self.assertEqual(self.release(gid).json(), {"game": gid, "game_over_frame": "no_tag"})
        self.assertEqual(self.drain(10), 0)

    def test_release_without_a_radio(self):
        gid, _ = self.ended_game_with_a_stuck_box()
        self.modem.has_field_frames = False
        self.assertEqual(self.release(gid).json()["game_over_frame"], "no_radio")

    def test_release_with_a_game_live_on_another_channel_is_refused(self):
        gid, _ = self.ended_game_with_a_stuck_box()
        self.store.set_setting("radio.channel_hz", "868100000")
        self.game()  # live on 868.1 MHz; the stuck box's game was on 869.525 MHz
        r = self.release(gid)
        self.assertEqual(r.status_code, 409)
        self.assertIn("another channel", r.text)
        self.assertEqual(self.drain(10), 0)

    def test_release_from_a_standby_is_refused(self):
        from atalaia_sim import join
        gid, _ = self.ended_game_with_a_stuck_box()
        payload = join.encode({"game_id": 77, "game_key": bytes(range(16)), "node_id": 3, "controller_id": 1,
                               "channel_hz": 869_525_000, "max_hops": 2, "teams": ["red", "blue"],
                               "mode_id": DOMINATION, "role": "standby", "game_seed": 1, "params": None,
                               "kind": "controller"}, JOIN_KEY)
        self.ctrl.join_as_standby(join.to_text(payload))
        self.assertEqual(self.release(gid).status_code, 409)
        self.ctrl.end_game(77)
        self.assertEqual(self.release(77).status_code, 409)  # a game it followed: the primary's
        self.assertEqual(self.drain(10), 0)

    def test_release_needs_the_gm_token(self):
        gid, _ = self.ended_game_with_a_stuck_box()
        self.assertEqual(self.client.post(f"/api/v1/boxes/stuck/{gid}/release",
                                          headers={"Authorization": "Bearer read-secret"}).status_code, 403)


class ReleaseFieldTests(GameOverTests):
    """RFC 0001 Amendment 28 (decisions STUCK-50 to STUCK-59): a controller that lost the game a box is
    stuck in (a new database) has no key tag to name it; RELEASE, sealed with the field key, names the
    live game (or none) and the controller's wall clock, and every box in another game it joined before
    then leaves it, as on GAME_OVER."""

    ended_game_with_a_stuck_box = StuckGameTests.ended_game_with_a_stuck_box
    drain = StuckGameTests.drain

    def release_all(self):
        return self.client.post("/api/v1/boxes/release", headers=GM)

    def test_release_frees_a_box_of_a_game_this_controller_does_not_know(self):
        gid, _ = self.ended_game_with_a_stuck_box()
        self.box.heard_time(int(wallclock.now()) - 60)  # the box took its game's first TIME a minute ago
        self.store.delete_setting(f"key_tag:{gid}")  # as good as a lost database: nothing names the game
        live = self.game()
        with self.assertLogs("atalaia.reinvite", "WARNING") as logs:
            r = self.release_all()
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual((out["live_game"], out["release_frame"]), (live, "sent"))
        self.assertLessEqual(abs(out["time"] - int(wallclock.now())), 1)
        self.assertIn(f"RELEASE: every box in a game other than {live}", logs.output[0])
        self.assertEqual(self.frames(), [{"kind": "release", "live_game": live, "time": out["time"]}])
        frame = self.modem.fields.pop(0)
        self.box.on_frame(frame, self.ctrl.now_ms())
        self.assertEqual(self.box.phase, "ended")
        self.assertIn(f"game {gid} released by a field controller (live game {live})", self.box.log[-1])
        self.assertEqual(self.drain(10), lobby.RELEASE_REPEATS - 1)  # three in all

    def test_a_box_of_the_live_game_and_an_older_release_change_nothing(self):
        live = self.game(assignments={"4": "zone"})
        self.box.join(bytes.fromhex(self.ctrl.issue_join({"role": "zone"}, node_id=4)["payload_hex"]))
        self.box.start()
        self.box.heard_time(int(wallclock.now()))
        self.assertEqual(self.release_all().json()["release_frame"], "sent")
        frame = self.modem.fields.pop(0)
        self.box.on_frame(frame, self.ctrl.now_ms())
        self.assertEqual(self.box.phase, "playing")  # named: the live game's box
        # The same frame, recorded, reaches a box that joined another game since: older than that join.
        other = lobby.IdleBox(JOIN_KEY, "other")
        self.assertEqual(other.join(bytes.fromhex(self.ctrl.issue_join({"role": "zone"}, node_id=5)["payload_hex"])),
                         "accepted")
        other.game["game_id"] = 999
        other.heard_time(int(wallclock.now()) + 3600)
        other.on_frame(frame, self.ctrl.now_ms())
        self.assertEqual(other.phase, "joined")
        self.assertIn("release refused", other.log[-1])

    def test_time_and_release_carry_the_same_corrected_clock(self):
        """A box's join time is the wall_s of its game's first TIME and RELEASE's time is compared with it
        (Amendment 28's replay rule): both are wallclock.now(), with the GM's correction (STUCK-68)."""
        import time as _time
        from atalaia_sim.packet import time_decode
        wallclock._offset = 3600.0  # a GM set the clock an hour forward
        self.addCleanup(wallclock.reset)
        gid = self.game()
        self.ctrl.start_game(gid, force=True)
        times = [time_decode(p)["wall_s"] for _, p in self.modem.of("TIME")]
        self.assertTrue(times)
        self.assertLessEqual(abs(times[0] - int(_time.time() + 3600)), 2)
        self.ctrl.end_game(gid, "done")
        out = self.release_all().json()
        self.assertEqual(out["release_frame"], "sent")
        self.assertLessEqual(abs(out["time"] - int(wallclock.now())), 1)
        self.assertGreaterEqual(out["time"], times[-1])

    def test_release_with_no_game_live_names_none(self):
        self.assertEqual(self.release_all().json()["live_game"], 0)
        self.assertEqual(self.frames()[0]["live_game"], 0)

    def test_release_has_a_rate_limit(self):
        self.assertEqual(self.release_all().status_code, 200)
        self.assertEqual(self.release_all().status_code, 429)  # still being said
        self.drain(10)
        self.assertEqual(self.release_all().status_code, 429)  # under 30 s since
        self.drain(21)
        self.assertEqual(self.release_all().status_code, 200)

    def test_release_without_a_radio(self):
        self.modem.has_field_frames = False
        self.assertEqual(self.release_all().json()["release_frame"], "no_radio")
        self.assertEqual(self.modem.fields, [])

    def test_release_needs_a_plausible_clock(self):
        with mock.patch.object(self.ctrl.clock_guard, "plausible", return_value=False):
            r = self.release_all()
        self.assertEqual(r.status_code, 409)
        self.assertIn("clock", r.text)
        self.assertEqual(self.modem.fields, [])

    def test_release_from_a_standby_is_refused(self):
        from atalaia_sim import join
        payload = join.encode({"game_id": 77, "game_key": bytes(range(16)), "node_id": 3, "controller_id": 1,
                               "channel_hz": 869_525_000, "max_hops": 2, "teams": ["red", "blue"],
                               "mode_id": DOMINATION, "role": "standby", "game_seed": 1, "params": None,
                               "kind": "controller"}, JOIN_KEY)
        self.ctrl.join_as_standby(join.to_text(payload))
        self.assertEqual(self.release_all().status_code, 409)
        self.assertEqual(self.modem.fields, [])

    def test_release_needs_the_gm_token(self):
        self.assertEqual(self.client.post("/api/v1/boxes/release", headers=READ).status_code, 403)


NEW_HZ, OLD_HZ, OLDER_HZ = 869_925_000, 869_525_000, 868_100_000


class MoveTests(Case):
    """RFC 0001 Amendment 19 (the bench finding of 2026-10-29): a change of the field's channel is said on
    the old channel (MOVE, three times) before the modem goes to the new one, then a DISCOVER there asks
    the boxes; a GM's discover sweeps the earlier channels for boxes that were away."""

    def setUp(self):
        super().setUp()
        self.boxes = [lobby.IdleBox(JOIN_KEY, f"box-{i}", rng=random.Random(i), now_ms=0) for i in range(2)]
        self.on_air = OLD_HZ        # the channel the modem is tuned to (SET_CHANNEL, else its own)
        self.asleep: set[int] = set()
        self.heard_by_box: list[tuple[int, str]] = []

    def pump(self, seconds: float = 1.0, step: float = 0.05) -> None:
        for _ in range(int(round(seconds / step))):
            self.clock.advance(step)
            now = self.ctrl.now_ms()
            self.ctrl.tick()
            while self.modem.channels:
                self.on_air = self.modem.channels.pop(0)
            while self.modem.fields:
                frame = self.modem.fields.pop(0)
                kind = ff.decode(ff.field_key(JOIN_KEY), frame)["kind"]
                self.heard_by_box.append((self.on_air, kind))
                for i, box in enumerate(self.boxes):
                    if i not in self.asleep and box.channel_hz == self.on_air:
                        box.on_frame(frame, now)
            for box in self.boxes:
                for frame in box.tick(now):
                    if box.channel_hz == self.on_air:
                        self.modem.on_field_rx(frame, -71, 6)

    def names(self) -> list[str]:
        return sorted(b["name"] for b in self.client.get("/api/v1/boxes", headers=GM).json()["boxes"])

    def settle(self):
        """The boxes announce themselves on the old channel: listed."""
        self.pump(25)
        self.assertEqual(self.names(), ["box-0", "box-1"])

    def test_the_boxes_follow_the_field_to_its_new_channel(self):
        self.settle()
        out = self.ctrl.set_field_channel(NEW_HZ, "scan")
        self.assertEqual(out["channel"]["channel_hz"], NEW_HZ)
        self.assertEqual(out["previous_channels_hz"], [OLD_HZ])
        # The modem stays on the old channel to say it: the SET_CHANNEL for the new one waits.
        self.assertNotIn(NEW_HZ, self.modem.channels)
        self.pump(20)
        kinds = [(hz, k) for hz, k in self.heard_by_box if k in ("move", "discover")]
        self.assertEqual(kinds[:3], [(OLD_HZ, "move")] * 3)
        self.assertEqual(kinds[3:], [(NEW_HZ, "discover")])  # then the modem is on the new channel: DISCOVER
        self.assertEqual(self.on_air, NEW_HZ)
        self.assertEqual([b.channel_hz for b in self.boxes], [NEW_HZ, NEW_HZ])
        self.assertEqual(self.names(), ["box-0", "box-1"])  # found again on the new channel
        # A new game is made on the new channel, and its boxes can be invited there.
        gid = self.game()
        self.assertEqual(self.ctrl.get_game(gid)["channel_hz"], NEW_HZ)

    def test_the_radio_settings_say_how_far_the_move_is(self):
        """RB-13: radio.move is null before a change, then 'telling' (MOVEs said so far) and 'moved'."""
        self.assertIsNone(self.ctrl.radio_settings()["move"])
        self.ctrl.set_field_channel(NEW_HZ, "scan")
        move = self.ctrl.radio_settings()["move"]
        self.assertEqual({k: v for k, v in move.items() if k != "rev"},
                         {"state": "telling", "from_hz": OLD_HZ, "to_hz": NEW_HZ, "sent": 1, "repeats": 3})
        self.assertEqual(move["rev"], self.ctrl.move_rev())
        self.pump(20)
        move = self.ctrl.radio_settings()["move"]
        self.assertEqual((move["state"], move["sent"]), ("moved", 3))
        # A GM's discover sweep (earlier channels) does not touch it.
        self.client.post("/api/v1/boxes/discover", headers=GM)
        self.pump(25)
        self.assertEqual(self.ctrl.radio_settings()["move"]["state"], "moved")
        # Without a modem that carries field frames there are no MOVEs to report.
        self.modem.has_field_frames = False
        self.ctrl.set_field_channel(OLDER_HZ)
        # The earlier change's status stays as it was (the console shows it only for the current channel).
        self.assertEqual(self.ctrl.radio_settings()["move"]["to_hz"], NEW_HZ)

    def test_the_revision_rises_with_every_change(self):
        self.ctrl.set_field_channel(NEW_HZ)
        first = self.ctrl.move_rev()
        self.assertGreater(first, 0)
        self.pump(10)
        self.ctrl.set_field_channel(OLDER_HZ)
        self.assertEqual(self.ctrl.move_rev(), first + 1)  # the wall clock is not above it: +1
        self.assertEqual(self.ctrl.channel_history(), [NEW_HZ, OLD_HZ])
        self.pump(10)
        self.ctrl.set_field_channel(OLD_HZ)
        self.assertEqual(self.ctrl.channel_history(), [OLDER_HZ, NEW_HZ])  # the current one is never in it
        self.pump(10)
        # The same channel again (accepting it): nothing to say.
        n, rev = len(self.heard_by_box), self.ctrl.move_rev()
        self.ctrl.set_field_channel(OLD_HZ)
        self.pump(10)
        self.assertEqual((len(self.heard_by_box), self.ctrl.move_rev()), (n, rev))

    def test_history_is_short_and_a_region_change_forgets_it(self):
        for hz in (868_100_000, 868_300_000, 868_500_000, NEW_HZ, 869_850_000):
            self.ctrl.set_field_channel(hz)
            self.pump(10)
        self.assertEqual(len(self.ctrl.channel_history()), self.ctrl.CHANNEL_HISTORY_MAX)
        self.assertEqual(self.ctrl.channel_history()[0], NEW_HZ)
        self.assertNotIn(OLD_HZ, self.ctrl.channel_history())
        self.ctrl.set_field_region("as923-tw")
        self.assertEqual(self.ctrl.channel_history(), [])

    def test_a_box_that_was_away_is_found_by_the_gms_discover(self):
        self.settle()
        self.asleep = {1}
        self.ctrl.set_field_channel(NEW_HZ)
        self.pump(20)
        self.assertEqual([b.channel_hz for b in self.boxes], [NEW_HZ, OLD_HZ])
        self.asleep = set()
        self.heard_by_box.clear()
        r = self.client.post("/api/v1/boxes/discover", headers=GM)
        self.assertEqual(r.json(), {"sent": True, "sweep": [OLD_HZ], "sweep_refused": None})
        self.pump(25)
        self.assertEqual([b.channel_hz for b in self.boxes], [NEW_HZ, NEW_HZ])
        # DISCOVER on the new channel, then (4 s later) the MOVE twice on the old one, then DISCOVER again.
        self.assertEqual(self.heard_by_box, [(NEW_HZ, "discover"), (OLD_HZ, "move"), (OLD_HZ, "move"),
                                             (NEW_HZ, "discover")])
        self.assertEqual(self.names(), ["box-0", "box-1"])
        # At most one sweep a minute.
        self.assertEqual(self.client.post("/api/v1/boxes/discover", headers=GM).json()["sweep"], [])

    def test_the_hourly_cap_refuses_a_sweep_on_a_1_percent_channel_and_says_when(self):
        """RL-9: on a 1 % sub-band a sweep's MOVEs may use 5 % of the hour; the answer is never an empty sweep
        without a reason, and the 10 % default sub-band keeps only the once-a-minute limit."""
        for hz in (868_100_000, 868_300_000, 868_500_000):  # all in sub-band g (1 %); the history ends in g2
            self.ctrl.set_field_channel(hz)
            self.pump(10)
        self.assertEqual(self.ctrl.channel_history(), [868_300_000, 868_100_000, OLD_HZ])
        out = []
        for _ in range(4):  # two channels on g (369.7 ms of it) and the 10 % one: 1800 ms fit four sweeps
            out.append(self.client.post("/api/v1/boxes/discover", headers=GM).json())
            self.pump(61)
        self.assertEqual([r["sweep"] for r in out], [[868_300_000, 868_100_000, OLD_HZ]] * 4)
        self.assertEqual([r["sweep_refused"] for r in out], [None] * 4)
        r = self.client.post("/api/v1/boxes/discover", headers=GM).json()
        self.assertEqual(r["sweep"], [])
        refused = r["sweep_refused"]
        self.assertEqual((refused["reason"], refused["band"], refused["duty_pct"], refused["limit_ms"]),
                         ("cap", "g", 1.0, 1800))
        # The first sweep is about 4 x 61 s old: it leaves the hour in just under an hour.
        self.assertTrue(3300 <= refused["retry_after_s"] <= 3360, refused)
        self.assertTrue(r["sent"] in (True, False))  # the DISCOVER itself is not capped
        self.pump(refused["retry_after_s"] + 1)
        self.assertIsNone(self.client.post("/api/v1/boxes/discover", headers=GM).json()["sweep_refused"])

    def test_without_a_modem_that_carries_field_frames_the_channel_changes_at_once(self):
        self.modem.has_field_frames = False
        self.ctrl.set_field_channel(NEW_HZ)
        self.assertEqual(self.modem.channels, [NEW_HZ])
        self.assertEqual(self.modem.fields, [])

    def test_no_sweep_while_a_game_is_live(self):
        self.ctrl.set_field_channel(NEW_HZ)
        self.pump(10)
        self.game()
        self.assertEqual(self.client.post("/api/v1/boxes/discover", headers=GM).json()["sweep"], [])
