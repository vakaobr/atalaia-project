# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scenarios in the controller (plan phase 8): the scenario endpoints (check, install, list,
read), the boxes' scenario names given in the join (P4R8, M6-7: the names field.nodes() returns),
and who gets which objective (P4R24): the assignee's team and squad, staff everything, and a hidden
objective nothing before its reveal; the game's scenario block for each viewer; the standby's
missing scenario (M6-1).

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from test_engine import ev
from atalaia_controller import scenario_service
from atalaia_controller.api import Auth, create_app, make_route
from atalaia_controller.checkin import Viewer
from atalaia_controller.engine import Controller
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import join
from atalaia_sim.field_controller import CMD_MODE
from atalaia_sim.packet import cmd_decode, hello_encode
from atalaia_sim.protocol import MESSAGE_TYPES

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
JOIN_KEY = bytes(range(32))
HERE = Path(__file__).resolve().parent
OBJECTIVES = "org.atalaia.objectives"
SCENARIO = "org.test.two"

# Three box objectives: the bridge for anyone (public), then the vault, hidden, for red's squad 1,
# and blue's radio (team).
MANIFEST = """\
id: org.test.two
version: 1
name: Two objectives
lang: en
teams: [red, blue]
squads: 2
i18n: { pt: { name: Dois objetivos } }
nodes:
  bridge: { role: objective }
  vault: { role: objective }
  radio: { role: objective }
objectives:
  - id: bridge
    name: Take the bridge
    i18n: { pt: { name: Tomar a ponte } }
    type: capture_and_hold
    target: bridge
    effect: { points: 50 }
  - id: vault
    name: Open the vault
    i18n: { pt: { name: Abrir o cofre } }
    type: enter_code
    assignee: { team: red, squad: 1 }
    target: vault
    params: { code: "4711" }
    visibility: hidden
    depends_on: [bridge]
    effect: { points: 100 }
  - id: radio
    name: Call home
    type: enter_code
    assignee: { team: blue }
    target: radio
    params: { code: "12" }
    effect: { points: 10 }
"""

RED, BLUE = 1, 2


def player(game_id: int, team: int, squad: int = 0, role: str = "player") -> Viewer:
    return Viewer("player", {"player_id": f"p-{team}{squad}{role[:2]}", "game_id": game_id, "team": team,
                             "squad": squad, "role": role})


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name)
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=JOIN_KEY)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))

    def tearDown(self):
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def install(self, text: str = MANIFEST):
        r = self.client.post("/api/v1/scenarios", headers=GM, json={"manifest": text})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()

    def create(self, **spec) -> dict:
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "Two", "mode_id": SCENARIO, "modifiers": [OBJECTIVES], "teams": ["red", "blue"],
            "squads": 2, **spec})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()


@unittest.skipIf(CORE is None, "the shared core library is not built")
class EndpointTests(Case):
    def test_check_lists_every_problem_for_the_editor(self):
        r = self.client.post("/api/v1/scenarios/check", headers=READ, json={"manifest": MANIFEST})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertEqual((out["ok"], out["problems"], out["id"], out["installed"], out["checked_in_core"]),
                         (True, [], SCENARIO, None, True))
        self.assertEqual([n["name"] for n in out["nodes"]], ["bridge", "vault", "radio"])
        self.assertEqual([o["id"] for o in out["objectives"]], ["bridge", "vault", "radio"])

        bad = MANIFEST.replace("depends_on: [bridge]", "depends_on: [nowhere]").replace("target: radio",
                                                                                       "target: attic")
        out = self.client.post("/api/v1/scenarios/check", headers=GM, json={"manifest": bad}).json()
        self.assertFalse(out["ok"])
        codes = {(p["path"], p["code"]) for p in out["problems"]}
        self.assertIn(("objectives[1].depends_on[0]", "unknown_reference"), codes)
        self.assertIn(("objectives[2].target", "unknown_node"), codes)
        self.assertTrue(all(p["message"] and p["level"] in ("error", "warning") for p in out["problems"]))

        out = self.client.post("/api/v1/scenarios/check", headers=GM, json={"manifest": "- a list"}).json()
        self.assertEqual((out["ok"], [p["code"] for p in out["problems"]]), (False, ["bad_manifest"]))
        r = self.client.post("/api/v1/scenarios/check", headers=GM, json={"text": MANIFEST})
        self.assertEqual((r.status_code, r.json()["problems"][0]["code"]), (400, "bad_manifest"))
        self.assertEqual(self.client.post("/api/v1/scenarios/check", json={"manifest": MANIFEST}).status_code, 401)

    def test_check_reads_surrogate_pairs_and_refuses_half_of_one(self):
        """PE24-107: an emoji written as JSON's two escapes was a 500; now it is the emoji, and half of a
        pair is a problem in words (bad_manifest), as is a lone surrogate in the request's own text."""
        m = yaml.safe_load(MANIFEST)
        m["name"] = "Ponte \U0001f309"
        text = json.dumps(m)
        self.assertIn("\\ud83c\\udf09", text)
        r = self.client.post("/api/v1/scenarios/check", headers=GM, json={"manifest": text})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["ok"], r.json()["name"]), (True, "Ponte \U0001f309"))
        for bad in (text.replace("\\ud83c\\udf09", "\\ud83c"),  # an escape
                    json.dumps(m, ensure_ascii=False).replace("\U0001f309", "\udf09")):  # the text itself
            r = self.client.post("/api/v1/scenarios/check", headers=GM, json={"manifest": bad})
            self.assertEqual(r.status_code, 200, r.text)
            out = r.json()
            self.assertEqual((out["ok"], [p["code"] for p in out["problems"]]), (False, ["bad_manifest"]))

    def test_check_hands_back_the_manifest_for_the_block_view(self):
        """Phase 5 plan phase 7 (P5F-3): the manifest as the controller read it, when JSON holds it
        unchanged (the console's block view is made from it); else None."""
        out = self.client.post("/api/v1/scenarios/check", headers=READ, json={"manifest": MANIFEST}).json()
        self.assertEqual(out["manifest"], yaml.safe_load(MANIFEST))
        # Read as YAML (the version is a number here, kept as one), errors and all.
        bad = MANIFEST.replace("target: radio", "target: attic")
        out = self.client.post("/api/v1/scenarios/check", headers=GM, json={"manifest": bad}).json()
        self.assertFalse(out["ok"])
        self.assertEqual(out["manifest"]["version"], 1)
        self.assertEqual(out["manifest"]["objectives"][2]["target"], "attic")
        for text in (MANIFEST.replace("version: 1", "version: 2026-10-22"),  # a date
                     MANIFEST.replace("version: 1", "version: .nan"),  # not a finite number
                     MANIFEST.replace("version: 1", "version: 9007199254740993"),  # beyond 2**53
                     MANIFEST.replace("squads: 2", "squads: 2\n7: seven"),  # a number as a key
                     "- a list"):
            out = self.client.post("/api/v1/scenarios/check", headers=GM, json={"manifest": text}).json()
            self.assertIsNone(out["manifest"], text[:60])

    def test_install_list_and_read(self):
        self.assertEqual(self.client.post("/api/v1/scenarios", headers=READ,
                                          json={"manifest": MANIFEST}).status_code, 403)
        out = self.install()
        self.assertEqual((out["id"], out["version"], out["manifest"], out["compiled"], out["replaced"]),
                         (SCENARIO, "1", True, True, False))
        modes = {m["id"]: m for m in self.client.get("/api/v1/modes", headers=READ).json()}
        self.assertEqual((modes[SCENARIO]["kind"], modes[SCENARIO]["builtin"]), ("scenario", False))

        listed = self.client.get("/api/v1/scenarios", headers=READ).json()
        self.assertEqual([(s["id"], s["manifest"]) for s in listed], [(SCENARIO, True)])
        self.assertEqual([o["id"] for o in listed[0]["objectives"]], ["bridge", "vault", "radio"])
        self.assertEqual(listed[0]["i18n"]["pt"]["name"], "Dois objetivos")
        self.assertNotIn("4711", str(listed))  # codes are only in field.lua

        # The manifest and the Lua are the GM's: they hold the codes.
        self.assertEqual(self.client.get(f"/api/v1/scenarios/{SCENARIO}", headers=READ).status_code, 403)
        full = self.client.get(f"/api/v1/scenarios/{SCENARIO}", headers=GM)
        self.assertEqual((full.status_code, full.headers["cache-control"]), (200, "no-store"))
        self.assertEqual(full.json()["manifest_text"], MANIFEST)
        self.assertIn('"4711"', full.json()["files"]["field.lua"])
        self.assertEqual(self.client.get("/api/v1/scenarios/org.test.none", headers=GM).status_code, 404)

        # Installed again (a new version): replaced; the check says what is installed.
        out = self.install(MANIFEST.replace("version: 1", "version: 2"))
        self.assertEqual((out["version"], out["replaced"]), ("2", True))
        check = self.client.post("/api/v1/scenarios/check", headers=GM, json={"manifest": MANIFEST}).json()
        self.assertEqual(check["installed"], "2")

    def test_install_refusals(self):
        r = self.client.post("/api/v1/scenarios", headers=GM,
                             json={"manifest": MANIFEST.replace("type: enter_code", "type: dance", 1)})
        self.assertEqual(r.status_code, 400)
        self.assertIn(("objectives[1].type", "unknown_type"),
                      {(p["path"], p["code"]) for p in r.json()["problems"]})
        self.assertEqual(self.client.get("/api/v1/scenarios", headers=GM).json(), [])
        # An id another kind of package has.
        files = {"mode.yaml": "id: org.test.two\nversion: 1\nroles: { zone: {} }\n", "node.lua": "-- nothing\n"}
        self.assertEqual(self.client.post("/api/v1/modes", headers=GM, json={"files": files}).status_code, 201)
        r = self.client.post("/api/v1/scenarios", headers=GM, json={"manifest": MANIFEST})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("installed as a mode", r.json()["detail"])

    def test_a_live_game_keeps_its_scenario(self):
        self.install()
        game = self.create()
        r = self.client.post("/api/v1/scenarios", headers=GM, json={"manifest": MANIFEST})
        self.assertEqual(r.status_code, 409)
        self.client.post(f"/api/v1/games/{game['id']}/end", headers=GM)
        self.install()

    def test_a_game_id_that_no_join_can_carry_is_refused(self):
        long_id = "org.club." + "x" * 31  # 40 bytes: the scenario's limit (M7-1)
        self.install(MANIFEST.replace(f"id: {SCENARIO}", f"id: {long_id}"))
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "x", "mode_id": long_id, "modifiers": ["org.atalaia.respawn", OBJECTIVES]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("at most 63 bytes", r.json()["detail"])
        self.create(mode_id=long_id)


@unittest.skipIf(CORE is None, "the shared core library is not built")
class GameTests(Case):
    def setUp(self):
        super().setUp()
        self.install()
        self.game = self.create()
        self.gid = self.game["id"]

    def joined(self, **spec) -> dict:
        r = self.client.post("/api/v1/join", headers=GM, json=spec)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def rx(self, *args, **kw):
        kw.setdefault("game_id", self.gid)
        self.modem.rx(*args, **kw)

    def hello(self, node_id: int, name: str) -> None:
        self.rx(node_id, 0, "HELLO", hello_encode({"node_name": name, "platform": 1, "fw_version": "0.2.0",
                                                   "core_version": "0.2.0", "tier": 0, "capabilities": [0],
                                                   "transports": 1, "battery_pct": 90, "epoch": 1}), epoch=1)

    def setups(self) -> dict[int, dict]:
        out = {}
        for header, payload in self.modem.sent:
            if header.type == MESSAGE_TYPES["CMD"]:
                c = cmd_decode(payload)
                if c["cmd"] == CMD_MODE and c["params"].get("name") == "setup":
                    out[c.get("dest")] = c["params"]
        return out

    def start(self) -> None:
        for node_id, name in ((4, "bridge"), (5, "vault"), (6, "radio")):
            self.joined(node_id=node_id, name=name)
            self.hello(node_id, f"box-{node_id}")  # the box's own name is not the scenario's
        self.assertEqual(self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True}).status_code, 200)

    def test_the_join_gives_a_box_its_scenario_name(self):
        out = self.joined(node_id=4, name="bridge")
        self.assertEqual((out["name"], out["role"]), ("bridge", "objective"))
        j = join.decode(bytes.fromhex(out["payload_hex"]), JOIN_KEY)
        self.assertEqual((j["mode_id"], j["role"]), (OBJECTIVES, "objective"))
        # The name moves to another box.
        self.joined(node_id=7, name="bridge")
        self.joined(node_id=5, name="vault")
        game = self.client.get(f"/api/v1/games/{self.gid}", headers=GM).json()
        self.assertEqual(game["scenario_nodes"], {"5": "vault", "7": "bridge"})
        self.assertEqual(sorted(game["scenario"]["nodes"]), ["bridge", "radio", "vault"])
        for spec, why in [({"name": "attic"}, "one of the scenario's boxes"),
                          ({"name": "bridge", "role": "bomb_site"}, "is a objective in the scenario"),
                          ({"name": "bridge", "kind": "controller"}, "only a box"),
                          ({"name": ["bridge"]}, "one of the scenario's boxes")]:
            with self.subTest(spec):
                r = self.client.post("/api/v1/join", headers=GM, json=spec)
                self.assertEqual(r.status_code, 400)
                self.assertIn(why, r.json()["detail"])
        # Not for the read token or players.
        self.assertNotIn("scenario_nodes", self.client.get(f"/api/v1/games/{self.gid}", headers=READ).json())

    def test_the_scenario_finds_its_boxes_by_those_names(self):
        self.start()
        setups = self.setups()
        self.assertEqual(setups[4]["kind"], "capture")
        self.assertEqual((setups[5]["kind"], setups[6]["kind"]), ("off", "code"))
        self.assertEqual(setups[6]["code"], "12")
        self.assertEqual(setups[4]["label"], "Take the bridge")  # lang: en
        # The names are kept with the game, for a controller restart.
        self.assertEqual(scenario_service.node_names(self.ctrl, self.gid), {4: "bridge", 5: "vault", 6: "radio"})

    def test_objectives_reach_the_players_they_are_for(self):
        self.start()
        route = make_route(self.ctrl)
        red1, red2, blue = player(self.gid, RED, 1), player(self.gid, RED, 2), player(self.gid, BLUE, 1)
        marshal = player(self.gid, BLUE, 0, role="marshal")
        read = Viewer("read")

        def objective(viewer, ev_):
            out = route(viewer, {"type": "event", "game": self.gid, "event": ev_})
            return out["event"]["data"].get("objective") if out else "dropped"

        def ids(viewer):
            game = self.client.get(f"/api/v1/games/{self.gid}", headers=GM).json()
            if viewer is not None:
                game = self.ctrl.players_game(game, viewer)
            return [o["id"] for o in game["scenario"]["objectives"]]

        log = self.ctrl.log(self.gid)
        revealed = [e for e in log if e["type"] == "scenario.objective.revealed"]
        self.assertEqual([e["data"]["objective"] for e in revealed], ["bridge", "radio"])  # not the vault yet
        bridge, radio = revealed
        self.assertEqual([objective(v, bridge) for v in (red1, blue, read, marshal)], ["bridge"] * 4)
        self.assertEqual([objective(v, radio) for v in (red1, red2, blue, read, marshal)],
                         [None, None, "radio", None, "radio"])
        self.assertEqual(ids(None), ["bridge", "vault", "radio"])  # the GM sees every objective
        self.assertEqual(ids(red1), ["bridge"])
        self.assertEqual(ids(blue), ["bridge", "radio"])
        self.assertEqual(ids(read), ["bridge"])
        self.assertEqual(ids(marshal), ["bridge", "vault", "radio"])

        # Red captures the bridge: the vault is revealed to red's squad 1, and the game is sent again
        # so that its players get the vault's names.
        seen: list[dict] = []
        self.ctrl.add_listener(seen.append)
        self.rx(4, 1, "EVENT", ev(4, 1, 30_000, "zone.captured", team=RED), epoch=1)
        vault = [e for e in self.ctrl.log(self.gid) if e["type"] == "scenario.objective.revealed"][-1]
        self.assertEqual((vault["data"]["objective"], vault["team"], vault["data"].get("squad")),
                         ("vault", "red", "1"))
        self.assertEqual([objective(v, vault) for v in (red1, red2, blue, read, marshal)],
                         ["vault", None, None, None, "vault"])
        self.assertIn("game", [m["type"] for m in seen if m["type"] in ("game", "event")])
        sent = [m for m in seen if m["type"] == "game"][-1]
        self.assertEqual([o["id"] for o in route(red1, sent)["game"]["scenario"]["objectives"]], ["bridge", "vault"])
        self.assertEqual([o["id"] for o in route(red2, sent)["game"]["scenario"]["objectives"]], ["bridge"])
        self.assertEqual(ids(red1), ["bridge", "vault"])
        player_view = self.ctrl.players_game(self.ctrl.get_game(self.gid), red1)["scenario"]
        self.assertEqual(player_view["objectives"][1], {
            "id": "vault", "type": "enter_code", "name": "Open the vault",
            "i18n": {"pt": {"name": "Abrir o cofre"}}, "team": "red", "squad": 1, "visibility": "hidden",
            "points": 100})
        self.assertEqual(player_view["i18n"], {"pt": {"name": "Dois objetivos"}})
        self.assertNotIn("4711", str(player_view))
        self.assertNotIn("depends_on", str(player_view))

        # The read token's log, and the stream's first message, follow the same rule.
        public = [e["data"].get("objective") for e in
                  self.client.get(f"/api/v1/games/{self.gid}/log", headers=READ).json()
                  if e["type"].startswith("scenario.objective.")]
        self.assertEqual(public, ["bridge", None, "bridge", None])  # revealed x2, completed, vault revealed
        with self.client.websocket_connect("/api/v1/stream?token=read-secret") as ws:
            hello = ws.receive_json()
        self.assertEqual([o["id"] for o in hello["game"]["scenario"]["objectives"]], ["bridge"])
        self.assertEqual([e["data"].get("objective") for e in hello["events"]
                          if e["type"].startswith("scenario.objective.")], public)

    def test_a_standby_needs_the_scenario_too(self):
        text = self.joined(kind="controller")["text"]
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        cfg = config(tmp.name)
        store = Store(cfg.db_path)
        self.addCleanup(store.close)
        standby = Controller(cfg, store, modem=FakeModem(), core=CORE, join_key=JOIN_KEY)
        self.addCleanup(standby.stop)
        client = TestClient(create_app(standby, Hub(), Auth(cfg.gm_token, cfg.read_token)))
        self.addCleanup(client.close)
        r = client.post("/api/v1/controller/join", headers=GM, json={"text": text})
        self.assertEqual(r.status_code, 409)
        self.assertIn(f"missing: {SCENARIO}", r.json()["detail"])
        manifest = self.client.get(f"/api/v1/scenarios/{SCENARIO}", headers=GM).json()["manifest_text"]
        self.assertEqual(client.post("/api/v1/scenarios", headers=GM, json={"manifest": manifest}).status_code, 201)
        r = client.post("/api/v1/controller/join", headers=GM, json={"text": text})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(r.json()["mode_id"], f"{SCENARIO}+{OBJECTIVES}")

    def test_the_packages_scenario_block_is_what_routing_reads(self):
        files = self.client.get(f"/api/v1/scenarios/{SCENARIO}", headers=GM).json()["files"]
        block = yaml.safe_load(files["mode.yaml"])["scenario"]
        self.assertEqual([(o["id"], o["visibility"]) for o in block["objectives"]],
                         [("bridge", "public"), ("vault", "hidden"), ("radio", "team")])


if __name__ == "__main__":
    unittest.main()
