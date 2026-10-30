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

import json
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


class BoxLanguageTests(unittest.TestCase):
    """The boxes' screen language (join key 15, RFC 0001 Amendment 10): the field setting
    (GET|PUT /api/v1/settings/box-language), "auto" by default, which takes the language of the
    console that creates the game; every join of the game carries it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.a = Side(self.tmp.name, "a")

    def tearDown(self):
        self.a.close()
        self.tmp.cleanup()

    def game(self, **extra) -> int:
        r = self.a.client.post("/api/v1/games", headers=GM, json={
            "name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"], **extra})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def end(self, gid: int) -> None:
        self.assertEqual(self.a.client.post(f"/api/v1/games/{gid}/end", headers=GM, json={}).status_code, 200)

    def lang_of(self, **spec) -> str | None:
        r = self.a.client.post("/api/v1/join", headers=GM, json={"role": "zone", **spec})
        self.assertEqual(r.status_code, 200, r.text)
        return join.decode(bytes.fromhex(r.json()["payload_hex"]), JOIN_KEY)["lang"]

    def test_auto_takes_the_consoles_language(self):
        c = self.a.client
        self.assertEqual(c.get("/api/v1/settings/box-language", headers=READ).json(),
                         {"box_language": "auto", "choices": ["auto", "pt", "en", "de", "zh-tw"],
                          "game_box_language": None})
        gid = self.game(console_lang="pt")
        self.assertEqual(self.lang_of(), "pt")
        self.assertEqual(c.get("/api/v1/settings/box-language", headers=READ).json()["game_box_language"], "pt")
        # A standby controller's join carries it too.
        r = c.post("/api/v1/join", headers=GM, json={"kind": "controller"})
        self.assertEqual(join.decode(bytes.fromhex(r.json()["payload_hex"]), JOIN_KEY)["lang"], "pt")
        self.end(gid)
        gid = self.game(console_lang="en")
        self.assertEqual(self.lang_of(), "en")
        self.end(gid)
        # German (plan phase 10): key 15 "de"; older boxes show English (BN-15).
        gid = self.game(console_lang="de")
        self.assertEqual(self.lang_of(), "de")
        self.end(gid)
        # Traditional Chinese, Taiwan (plan phase 11): key 15 "zh-tw", within its 2-8 letters.
        gid = self.game(console_lang="zh-tw")
        self.assertEqual(self.lang_of(), "zh-tw")
        self.end(gid)
        # Created through the API without a console: no key 15 (English).
        self.game()
        self.assertIsNone(self.lang_of())

    def test_a_lang_parameter_left_empty_is_the_games_language(self):
        """The Medic Kit, the Hacking Terminal and VIP / Payload take their screens' language from
        a `lang` parameter (their scripts cannot read the box's): empty, it is the game's."""
        c = self.a.client
        for mode, role in (("org.atalaia.medic", "medic"), ("org.atalaia.hacking_terminal", "terminal"),
                           ("org.atalaia.vip_payload", "checkpoint")):
            for console_lang, want in (("pt", "pt"), ("de", "de"), ("zh-tw", "zh-tw"), ("en", "en"), (None, "en")):
                spec = {"name": "x", "mode_id": mode, "teams": ["red", "blue"]}
                if console_lang:
                    spec["console_lang"] = console_lang
                r = c.post("/api/v1/games", headers=GM, json=spec)
                self.assertEqual(r.status_code, 201, r.text)
                self.assertEqual(r.json()["params"]["lang"], want, (mode, console_lang))
                # The boxes get it in their join's parameters, as the nodes run with it.
                j = c.post("/api/v1/join", headers=GM, json={"role": role})
                self.assertEqual(j.status_code, 200, j.text)
                self.assertEqual(join.decode(bytes.fromhex(j.json()["payload_hex"]), JOIN_KEY)["params"]["lang"], want)
                self.end(r.json()["id"])
            # The GM's own choice, in the game or in a preset's parameters, stays.
            r = c.post("/api/v1/games", headers=GM, json={"name": "x", "mode_id": mode, "teams": ["red", "blue"],
                                                          "console_lang": "de", "params": {"lang": "pt"}})
            self.assertEqual((r.status_code, r.json()["params"]["lang"]), (201, "pt"), r.text)
            self.end(r.json()["id"])
        # A mode with no such parameter gets none.
        gid = self.game(console_lang="pt")
        self.assertNotIn("lang", c.get(f"/api/v1/games/{gid}", headers=READ).json()["params"])
        self.end(gid)

    def test_a_fixed_setting_wins_and_a_game_keeps_its_language(self):
        c = self.a.client
        self.assertEqual(c.put("/api/v1/settings/box-language", headers=READ,
                               json={"box_language": "pt"}).status_code, 403)
        self.assertEqual(c.put("/api/v1/settings/box-language", headers=GM,
                               json={"box_language": "fr"}).status_code, 400)
        r = c.put("/api/v1/settings/box-language", headers=GM, json={"box_language": "pt"})
        self.assertEqual((r.status_code, r.json()["box_language"]), (200, "pt"))
        gid = self.game(console_lang="en")
        self.assertEqual(self.lang_of(), "pt")
        # Changed during the game: the live game keeps its language; the next game takes the new one.
        c.put("/api/v1/settings/box-language", headers=GM, json={"box_language": "en"})
        self.assertEqual(self.lang_of(), "pt")
        self.end(gid)
        self.game(console_lang="pt")
        self.assertEqual(self.lang_of(), "en")
        # A console language the controller does not know is refused while "auto" decides.
        c.put("/api/v1/settings/box-language", headers=GM, json={"box_language": "auto"})
        self.end(self.a.ctrl.game["id"])
        r = c.post("/api/v1/games", headers=GM, json={"name": "x", "mode_id": DOMINATION, "console_lang": "xx"})
        self.assertEqual(r.status_code, 400)

    def test_the_modems_screen_follows_the_boxes_language(self):
        """The modem board's OLED (decision MOD-2): the fixed setting at once and at a restart,
        with "auto" the live game's language, and nothing to say when no game says one."""
        c, modem = self.a.client, self.a.modem
        modem.languages.clear()
        c.put("/api/v1/settings/box-language", headers=GM, json={"box_language": "de"})
        self.assertEqual(modem.languages, ["de"])
        c.put("/api/v1/settings/box-language", headers=GM, json={"box_language": "auto"})
        self.assertEqual(modem.languages, ["de"])  # no game: it keeps what it has
        gid = self.game(console_lang="pt")
        self.assertEqual(modem.languages, ["de", "pt"])
        self.end(gid)
        c.put("/api/v1/settings/box-language", headers=GM, json={"box_language": "zh-tw"})
        self.assertEqual(modem.languages[-1], "zh-tw")
        # A restart: the setting is read again and the modem told.
        self.a.close()
        self.a = Side(self.tmp.name, "keep", persist_game_key=True)
        self.assertEqual(self.a.modem.languages, [])  # a new store: no setting yet
        self.a.client.put("/api/v1/settings/box-language", headers=GM, json={"box_language": "en"})
        self.a.close()
        self.a = Side(self.tmp.name, "keep", persist_game_key=True)
        self.assertEqual(self.a.modem.languages, ["en"])

    def test_the_setting_survives_a_restart(self):
        self.a.close()
        self.a = Side(self.tmp.name, "keep", persist_game_key=True)
        self.a.client.put("/api/v1/settings/box-language", headers=GM, json={"box_language": "en"})
        self.assertEqual(self.a.store.get_setting("box_language"), "en")
        gid = self.game(console_lang="pt")
        self.a.ctrl.stop()
        ctrl = Controller(self.a.cfg, self.a.store, modem=FakeModem(), core=CORE, join_key=JOIN_KEY)
        try:
            self.assertEqual(ctrl.game["id"], gid)
            self.assertEqual(join.decode(bytes.fromhex(ctrl.issue_join({"role": "zone"})["payload_hex"]),
                                         JOIN_KEY)["lang"], "en")
        finally:
            ctrl.stop()


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
        # On standby the game cannot be driven. A second join of the same game and key only refreshes what the
        # join carries (BBC-20); a join of another game is refused while this one is live.
        self.assertEqual(c.post(f"/api/v1/games/{self.game['id']}/start", headers=GM, json={"force": True}).status_code, 409)
        again = c.post("/api/v1/controller/join", headers=GM, json={"text": self.text})
        self.assertEqual((again.status_code, again.json()["id"]), (201, self.game["id"]))
        self.assertEqual(len(self.b.modem.configured), 1)  # nothing was reconfigured

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

    def beacon_view(self, side, headers):
        r = side.client.get("/api/v1/beacons", headers=headers)
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        # What a phone (or the console) reads: the same list, whichever controller serves it.
        return out["beacons"], out.get("box_beacons")

    def place_box(self, side, node, x, y):
        side.ctrl.store.set_position(self.game["id"], node, x, y)

    def test_box_beacon_choices_travel_to_the_standby_and_survive_a_failover(self):
        """BBC-20: the GM's field switch, disabled boxes and rooms made on the primary are the standby's
        after its join (key 19 and key 21), and a join made again brings later changes."""
        from atalaia_controller import box_beacons as bb
        a, b, gid = self.a.client, self.b.client, self.game["id"]
        boxes = [a.post("/api/v1/join", headers=GM, json={"role": "zone"}).json()["node_id"] for _ in range(3)]
        self.assertEqual(len(boxes), 3)
        # Before the standby joins: box 1 disabled, box 2 given a room, the field switch off.
        self.assertEqual(a.put(f"/api/v1/box-beacons/{boxes[0]}", headers=GM, json={"enabled": False}).status_code, 200)
        self.assertEqual(a.put(f"/api/v1/box-beacons/{boxes[1]}", headers=GM, json={"room": "Kitchen"}).status_code, 200)
        text = a.post("/api/v1/join", headers=GM, json={"kind": "controller"}).json()["text"]
        got = join.decode(join.from_text(text), JOIN_KEY)
        self.assertEqual(got["box_beacons"], {"off": [boxes[0]], "rooms": {boxes[1]: "Kitchen"}})
        self.assertTrue(got["box_beacon"])
        self.assertEqual(b.post("/api/v1/controller/join", headers=GM, json={"text": text}).status_code, 201)
        # The primary's later choices: the field switch, a second room, the box enabled again. The text made
        # earlier does not have them; a standby join made again does, and changes nothing else.
        self.assertEqual(a.put("/api/v1/box-beacons", headers=GM, json={"enabled": False}).status_code, 200)
        self.assertEqual(a.put(f"/api/v1/box-beacons/{boxes[0]}", headers=GM, json={"enabled": True}).status_code, 200)
        self.assertEqual(a.put(f"/api/v1/box-beacons/{boxes[2]}", headers=GM, json={"room": "Hall"}).status_code, 200)
        self.assertEqual(a.put(f"/api/v1/box-beacons/{boxes[2]}", headers=GM, json={"enabled": False}).status_code, 200)
        self.assertEqual(a.put("/api/v1/box-beacons", headers=GM, json={"enabled": True}).status_code, 200)
        self.assertEqual(a.put(f"/api/v1/box-beacons/{boxes[0]}", headers=GM, json={"room": "Garage"}).status_code, 200)
        self.assertEqual(a.put("/api/v1/box-beacons", headers=GM, json={"enabled": False}).status_code, 200)
        text2 = a.post("/api/v1/join", headers=GM, json={"kind": "controller"}).json()["text"]
        r = b.post("/api/v1/controller/join", headers=GM, json={"text": text2})
        self.assertEqual(r.status_code, 201, r.text)  # a refresh answers with the game, as a join does
        self.assertEqual((r.json()["id"], r.json()["joined"]), (gid, True))
        self.assertEqual(self.b.ctrl.game["id"], gid)

        # Both controllers know the boxes (placed on the field view as the GM does on each) ...
        for side in (self.a, self.b):
            for n, box in enumerate(boxes):
                self.place_box(side, box, 0.1 * (n + 1), 0.5)
        self.b.ctrl.fc.register_node(boxes[0], f"node-{boxes[0]}", "zone")
        self.b.ctrl.fc.register_node(boxes[1], f"node-{boxes[1]}", "zone")
        self.b.ctrl.fc.register_node(boxes[2], f"node-{boxes[2]}", "zone")
        # ... and serve the same registry: the field switch (off), the disabled box, the rooms.
        self.assertFalse(bb.enabled(self.a.ctrl))
        self.assertEqual(self.beacon_view(self.a, GM), self.beacon_view(self.b, GM))
        self.assertEqual(self.beacon_view(self.a, READ), self.beacon_view(self.b, READ))
        self.assertEqual(self.beacon_view(self.b, READ)[0], [])  # off: a phone listens for no box
        by = {x["minor"]: x for x in self.beacon_view(self.b, GM)[0]}
        self.assertEqual((by[boxes[0]]["room"], by[boxes[0]]["enabled"]), ("Garage", True))
        self.assertEqual((by[boxes[1]]["room"], by[boxes[1]]["room_given"]), ("Kitchen", True))
        self.assertEqual((by[boxes[2]]["room"], by[boxes[2]]["enabled"]), ("Hall", False))
        # The primary goes away; the GM switches the field's boxes on again on the primary and joins a third
        # time: a promoted standby makes joins that say the same (key 19) and lists the same boxes.
        self.assertEqual(a.put("/api/v1/box-beacons", headers=GM, json={"enabled": True}).status_code, 200)
        text3 = a.post("/api/v1/join", headers=GM, json={"kind": "controller"}).json()["text"]
        self.assertEqual(b.post("/api/v1/controller/join", headers=GM, json={"text": text3}).status_code, 201)
        self.assertEqual(self.beacon_view(self.a, READ), self.beacon_view(self.b, READ))
        self.assertEqual(len(self.beacon_view(self.b, READ)[0]), 2)  # the disabled one is left out
        self.assertEqual(self.b.ctrl.store.get_setting("box_beacons"), "on")
        self.assertEqual(b.post("/api/v1/controller/promote", headers=GM).json()["role"], "candidate")

    def test_box_places_travel_to_the_standby_and_a_move_reaches_it(self):
        """BBC-25: where the GM placed the boxes on the primary (key 22) is the standby's after its join, so a
        promoted standby locates players by the boxes without anyone placing them again; a box moved after the
        standby joined reaches it with the next join, as BBC-21 does for the choices."""
        from atalaia_controller import box_beacons as bb
        a, b, gid = self.a.client, self.b.client, self.game["id"]
        boxes = [a.post("/api/v1/join", headers=GM, json={"role": "zone"}).json()["node_id"] for _ in range(3)]
        self.assertEqual(a.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 3}).status_code, 200)
        self.assertEqual(b.put("/api/v1/field/levels", headers=GM, json={"enabled": True, "count": 3}).status_code, 200)
        self.a.ctrl.store.set_position(gid, boxes[0], 0.25, 0.5, 2)
        self.a.ctrl.store.set_position(gid, boxes[1], 1.0, 0.0, 0)
        # boxes[2] is not placed: it has no place to mirror.
        self.assertEqual(self.a.ctrl.store.positions(gid)[boxes[0]]["level"], 2)

        def standby_text():
            return a.post("/api/v1/join", headers=GM, json={"kind": "controller"}).json()["text"]

        text = standby_text()
        got = join.decode(join.from_text(text), JOIN_KEY)
        self.assertEqual(got["box_places"], [[boxes[0], 2, join.quantize(0.25), join.quantize(0.5)],
                                             [boxes[1], 0, 65535, 0]])
        self.assertEqual(b.post("/api/v1/controller/join", headers=GM, json={"text": text}).status_code, 201)
        # Nothing placed on the standby, and no HELLO yet: it lists the boxes from the join alone, in place.
        by = {x["minor"]: x for x in self.beacon_view(self.b, GM)[0]}
        self.assertEqual(sorted(by), sorted(boxes[:2]))
        self.assertEqual((by[boxes[0]]["level"], by[boxes[0]]["x"], by[boxes[0]]["y"]),
                         (2, join.dequantize(join.quantize(0.25)), join.dequantize(join.quantize(0.5))))
        self.assertEqual((by[boxes[1]]["level"], by[boxes[1]]["x"], by[boxes[1]]["y"]), (0, 1.0, 0.0))
        self.assertEqual([(x["id"], x["uuid"]) for x in self.beacon_view(self.b, READ)[0]],
                         [(x["id"], x["uuid"]) for x in self.beacon_view(self.a, READ)[0]])
        # A box moved and one placed after the standby joined: the text made earlier does not have them.
        self.a.ctrl.store.set_position(gid, boxes[1], 0.0, 1.0, 1)
        self.a.ctrl.store.set_position(gid, boxes[2], 0.5, 0.5, 0)
        self.assertEqual(len(self.beacon_view(self.b, GM)[0]), 2)
        self.assertEqual(b.post("/api/v1/controller/join", headers=GM, json={"text": standby_text()}).status_code, 201)
        by = {x["minor"]: x for x in self.beacon_view(self.b, GM)[0]}
        self.assertEqual(sorted(by), sorted(boxes))
        self.assertEqual((by[boxes[1]]["level"], by[boxes[1]]["x"], by[boxes[1]]["y"]), (1, 0.0, 1.0))
        self.assertEqual((by[boxes[2]]["level"], by[boxes[2]]["x"]), (0, join.dequantize(32768)))
        # Promoted, the standby places a player who hears a box exactly where the primary would.
        place = bb.place_of(self.b.ctrl, bb.box_id(boxes[1]))
        self.assertEqual((place["level"], place["x"], place["y"]), (1, 0.0, 1.0))
        self.assertEqual(self.b.ctrl.store.get_setting(f"box_places_mirrored:{gid}"), json.dumps(sorted(boxes)))

    def test_box_places_that_do_not_fit_are_refused_not_dropped(self):
        """BBC-25: more than 28 placed boxes cannot travel in the join: the standby join is refused, and says so."""
        a, gid = self.a.client, self.game["id"]
        boxes = [a.post("/api/v1/join", headers=GM, json={"role": "zone"}).json()["node_id"] for _ in range(29)]
        for n, box in enumerate(boxes):
            self.a.ctrl.store.set_position(gid, box, (n + 1) / 100, 0.5)
        r = a.post("/api/v1/join", headers=GM, json={"kind": "controller"})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("box_places", r.text)
        self.assertIn("28", r.text)
        # A box's own join is not affected: it never carries the places.
        self.assertEqual(a.post("/api/v1/join", headers=GM, json={"role": "zone"}).status_code, 200)

    def test_a_refreshing_join_is_for_the_game_and_key_the_standby_follows(self):
        b = self.b.client
        self.assertEqual(b.post("/api/v1/controller/join", headers=GM, json={"text": self.text}).status_code, 201)
        # Another game's standby join (another key) is not a refresh.
        other = Side(self.tmp.name, "e")
        other.client.post("/api/v1/games", headers=GM, json={"name": "Other", "mode_id": DOMINATION,
                                                            "teams": ["red", "blue"]})
        text = other.client.post("/api/v1/join", headers=GM, json={"kind": "controller"}).json()["text"]
        other.close()
        r = b.post("/api/v1/controller/join", headers=GM, json={"text": text})
        self.assertEqual(r.status_code, 409)
        self.assertIn("still live", r.json()["detail"])

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
        self.assertEqual(a.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True}).status_code, 200)
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
