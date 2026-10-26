# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-squad objective chains and who of a squad is told them (decisions SQ-1 to SQ-8).

A scenario with ``reveal: active`` gives each squad only the objective it can play now: the next
one is revealed when the one before it is completed, and nothing about a later one reaches a
player's phone (not in the game, the log, the stream's events). With ``disclosure: leader`` only the
squad's leader gets the objective; the squad's members are told their leader has orders. The GM
changes that for one game (``PUT /games/{id}/objective-disclosure``) or when creating it.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import json
import unittest

import yaml
from test_engine import ev
from test_scenario_api import CORE, GM, OBJECTIVES, READ, BLUE, RED, Case, player
from atalaia_controller import scenario_service
from atalaia_controller.api import make_route
from atalaia_controller.checkin import Viewer
from atalaia_sim.packet import hello_encode

SCENARIO = "org.test.chains"

# Red's squad 1 has three steps, squad 2 two; blue has one for the whole team. The names of the
# later steps are what a leak would show.
MANIFEST = """\
id: org.test.chains
version: 1
name: Chains
lang: en
teams: [red, blue]
squads: 2
reveal: active
disclosure: leader
nodes:
  a1: { role: objective }
  a2: { role: objective }
  a3: { role: objective }
  b1: { role: objective }
  b2: { role: objective }
  c1: { role: objective }
objectives:
  - { id: a1, name: Alpha one, type: capture_and_hold, target: a1, assignee: { team: red, squad: 1 } }
  - { id: a2, name: Alpha two SECRET, type: capture_and_hold, target: a2, assignee: { team: red, squad: 1 },
      depends_on: [a1] }
  - { id: a3, name: Alpha three SECRET, type: capture_and_hold, target: a3, assignee: { team: red, squad: 1 },
      depends_on: [a2] }
  - { id: b1, name: Bravo one, type: capture_and_hold, target: b1, assignee: { team: red, squad: 2 } }
  - { id: b2, name: Bravo two SECRET, type: capture_and_hold, target: b2, assignee: { team: red, squad: 2 },
      depends_on: [b1] }
  - { id: c1, name: Charlie one, type: capture_and_hold, target: c1, assignee: { team: blue } }
"""
NODES = {4: "a1", 5: "a2", 6: "a3", 7: "b1", 8: "b2", 9: "c1"}


@unittest.skipIf(CORE is None, "the shared core library is not built")
class Chains(Case):
    def setUp(self):
        super().setUp()
        self.install(MANIFEST)
        self.gid = self.create(mode_id=SCENARIO)["id"]
        self.route = make_route(self.ctrl)
        self.red1 = player(self.gid, RED, 1)
        self.red1_leader = player(self.gid, RED, 1, role="squad_leader")
        self.red2 = player(self.gid, RED, 2)
        self.red2_leader = player(self.gid, RED, 2, role="squad_leader")
        self.red0 = player(self.gid, RED, 0)
        self.blue = player(self.gid, BLUE, 1)
        self.marshal = player(self.gid, BLUE, 0, role="marshal")
        self.read = Viewer("read")

    def start(self):
        for node_id, name in NODES.items():
            self.assertEqual(self.client.post("/api/v1/join", headers=GM,
                                              json={"node_id": node_id, "name": name}).status_code, 200)
            self.modem.rx(node_id, 0, "HELLO", hello_encode({
                "node_name": f"box-{node_id}", "platform": 1, "fw_version": "0.2.0", "core_version": "0.2.0",
                "tier": 0, "capabilities": [0], "transports": 1, "battery_pct": 90, "epoch": 1}),
                epoch=1, game_id=self.gid)
        r = self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
        self.assertEqual(r.status_code, 200, r.text)

    def capture(self, node: int, seq: int = 1, t: int = 30_000) -> None:
        self.modem.rx(node, seq, "EVENT", ev(node, seq, t, "zone.captured", team=RED), epoch=1, game_id=self.gid)

    def ids(self, viewer) -> list[str]:
        game = self.ctrl.get_game(self.gid)
        if viewer is not None:
            game = self.ctrl.players_game(game, viewer)
        return [o["id"] for o in game["scenario"]["objectives"]]

    def seen(self, viewer) -> list[dict]:
        """Every objective event this viewer gets from the stream, as the route filters it."""
        out = []
        for e in self.ctrl.log(self.gid):
            if e["type"].startswith("scenario.objective."):
                msg = self.route(viewer, {"type": "event", "game": self.gid, "event": e})
                out.append(msg["event"] if msg else None)
        return out

    def everything(self, viewer) -> str:
        """All the viewer can read of the game: its game, the log over REST and the stream's events."""
        parts = [json.dumps(self.ctrl.players_game(self.ctrl.get_game(self.gid), viewer)), json.dumps(self.seen(viewer))]
        sent = {"type": "game", "game": self.ctrl.get_game(self.gid)}
        parts.append(json.dumps(self.route(viewer, sent)))
        return " ".join(parts)

    # --- the compiler ----------------------------------------------------------------------

    def test_a_dependent_objective_is_hidden_by_default_when_reveal_is_active(self):
        files = self.client.get(f"/api/v1/scenarios/{SCENARIO}", headers=GM).json()["files"]
        block = yaml.safe_load(files["mode.yaml"])["scenario"]
        self.assertEqual((block["reveal"], block["disclosure"]), ("active", "leader"))
        self.assertEqual([(o["id"], o["visibility"]) for o in block["objectives"]],
                         [("a1", "squad"), ("a2", "hidden"), ("a3", "hidden"), ("b1", "squad"),
                          ("b2", "hidden"), ("c1", "team")])

    def test_the_two_settings_are_checked_and_optional(self):
        for key, value, code in (("reveal", "later", "bad_reveal"), ("disclosure", "nobody", "bad_disclosure")):
            bad = MANIFEST.replace(f"{key}: {'active' if key == 'reveal' else 'leader'}", f"{key}: {value}")
            out = self.client.post("/api/v1/scenarios/check", headers=GM, json={"manifest": bad}).json()
            self.assertEqual([(p["path"], p["code"]) for p in out["problems"]], [(key, code)])
        plain = MANIFEST.replace("reveal: active\ndisclosure: leader\n", "")
        self.client.post(f"/api/v1/games/{self.gid}/end", headers=GM)
        out = self.client.post("/api/v1/scenarios/check", headers=GM, json={"manifest": plain}).json()
        self.assertEqual((out["ok"], out["problems"]), (True, []))
        # Without them nothing changes: the mode.yaml has neither key and the later steps show from the start.
        files = self.install(plain)
        self.assertEqual(files["id"], SCENARIO)
        block = yaml.safe_load(self.client.get(f"/api/v1/scenarios/{SCENARIO}", headers=GM)
                               .json()["files"]["mode.yaml"])["scenario"]
        self.assertNotIn("reveal", block)
        self.assertNotIn("disclosure", block)
        self.assertEqual([o["visibility"] for o in block["objectives"]],
                         ["squad", "squad", "squad", "squad", "squad", "team"])

    # --- one at a time ---------------------------------------------------------------------

    def test_a_squad_knows_only_its_active_objective_and_the_next_comes_with_the_one_before(self):
        self.start()
        revealed = [e["data"]["objective"] for e in self.ctrl.log(self.gid)
                    if e["type"] == "scenario.objective.revealed"]
        self.assertEqual(sorted(revealed), ["a1", "b1", "c1"])  # not a2, a3, b2
        self.assertEqual(self.ids(None), ["a1", "a2", "a3", "b1", "b2", "c1"])  # the GM sees all
        self.assertEqual(self.ids(self.marshal), ["a1", "a2", "a3", "b1", "b2", "c1"])
        self.assertEqual(self.ids(self.red1_leader), ["a1"])
        self.assertEqual(self.ids(self.red2_leader), ["b1"])
        self.assertEqual(self.ids(self.blue), [])  # a member of blue's squad 1: blue's leaders are told (SQ-3)
        self.assertEqual(self.ids(player(self.gid, BLUE, 1, role="squad_leader")), ["c1"])
        self.assertEqual(self.ids(self.read), [])  # a spectator: nothing of a team's or a squad's

        # Squad 1 completes its first: the second is revealed to it, the first stays, done.
        self.capture(4)
        self.assertEqual(self.ids(self.red1_leader), ["a1", "a2"])
        self.assertEqual(self.ids(self.red2_leader), ["b1"])  # squad 2's chain did not move
        kinds = [(e["type"].rsplit(".", 1)[1], e["data"].get("objective")) for e in self.seen(self.red1_leader) if e]
        self.assertIn(("completed", "a1"), kinds)
        self.assertEqual(kinds[-1], ("revealed", "a2"))
        # The third stays hidden until the second is done.
        self.assertNotIn("a3", self.everything(self.red1_leader))
        self.capture(5, seq=2)
        self.assertEqual(self.ids(self.red1_leader), ["a1", "a2", "a3"])

    def test_nothing_of_a_later_objective_reaches_a_player(self):
        self.start()
        for viewer in (self.red1_leader, self.red1, self.red2_leader, self.red2, self.red0, self.blue, self.read):
            text = self.everything(viewer)
            for secret in ("SECRET", '"a2"', '"a3"', '"b2"', "Alpha two", "Bravo two"):
                self.assertNotIn(secret, text, f"{viewer.role} squad {viewer.squad}: {secret}")
        # Over REST, too: the game list and the log of the read token.
        listing = json.dumps(self.client.get("/api/v1/games", headers=READ).json())
        log = json.dumps(self.client.get(f"/api/v1/games/{self.gid}/log", headers=READ).json())
        self.assertNotIn("SECRET", listing + log)
        self.assertNotIn("depends_on", listing)
        # Staff do see them.
        self.assertIn("SECRET", json.dumps(self.ctrl.get_game(self.gid)))

    def test_a_hidden_objective_that_fails_with_its_dependency_is_never_told(self):
        """The dependency failing fails what depends on it; the squad learns of neither the objective
        nor its failure, since it never saw it (the runtime sends no event of a hidden one)."""
        self.start()
        failed = [e for e in self.ctrl.log(self.gid) if e["type"] == "scenario.objective.failed"]
        self.assertEqual(failed, [])
        self.assertNotIn("a2", self.everything(self.red1_leader))

    # --- who of the squad ------------------------------------------------------------------

    def test_with_leader_disclosure_the_members_are_told_only_that_their_leader_has_orders(self):
        self.start()
        self.assertEqual(self.ids(self.red1), [])  # a member of squad 1: no objective
        self.assertEqual(self.ids(self.red2), [])
        self.assertEqual(self.ids(self.red0), [])  # in no squad: not the squads objectives (they are for squads 1 and 2)
        news = [e for e in self.seen(self.red1) if e]
        revealed = [e for e in news if e["type"] == "scenario.objective.revealed"]
        self.assertEqual(len(revealed), 3)  # the member also learns that a1 was revealed...
        mine = [e for e in revealed if e["data"].get("squad") == "1"]
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["data"], {"team": "red", "squad": "1", "leader_only": True})  # ...without which
        # The other squad's reveal carries no flag for squad 1's member: it is not about their squad.
        # (They only learn that red's squad 2 got an objective, as before.)
        for e in news:
            self.assertNotIn("objective", e["data"])
        self.assertEqual([e["data"].get("objective") for e in self.seen(self.red1_leader) if e
                          and e["data"].get("squad") == "1"], ["a1"])
        # The leader of squad 2 does not get squad 1's.
        self.assertNotIn("a1", self.everything(self.red2_leader))

    def test_a_blue_team_objective_goes_to_blue_leaders_only_under_leader_disclosure(self):
        self.start()
        self.assertEqual(self.ids(self.blue), [])
        blue_leader = player(self.gid, BLUE, 1, role="squad_leader")
        self.assertEqual(self.ids(blue_leader), ["c1"])
        no_squad = player(self.gid, BLUE, 0)
        self.assertEqual(self.ids(no_squad), ["c1"])  # no squad, no leader to go through

    def test_the_gm_can_change_who_is_told_for_one_game(self):
        self.start()
        self.assertEqual(self.ids(self.red1), [])
        seen: list[dict] = []
        self.ctrl.add_listener(seen.append)
        r = self.client.put(f"/api/v1/games/{self.gid}/objective-disclosure", headers=GM,
                            json={"disclosure": "members"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["scenario"]["disclosure"], r.json()["scenario"]["disclosure_default"]),
                         ("members", "leader"))
        self.assertEqual(self.ids(self.red1), ["a1"])  # now the whole squad
        self.assertEqual(self.ids(self.red1_leader), ["a1"])
        self.assertEqual([m["type"] for m in seen if m["type"] == "game"], ["game"])  # the apps hear of it
        sent = [m for m in seen if m["type"] == "game"][-1]
        self.assertEqual([o["id"] for o in self.route(self.red1, sent)["game"]["scenario"]["objectives"]], ["a1"])
        self.assertEqual(scenario_service.disclosure(self.ctrl, self.gid, None), "members")
        # The events of a reveal then reach the members whole.
        self.capture(4)
        self.assertEqual([e["data"].get("objective") for e in self.seen(self.red1) if e
                          and e["data"].get("squad") == "1" and e["type"].endswith("revealed")], ["a1", "a2"])
        # Back to the scenario's own with null.
        r = self.client.put(f"/api/v1/games/{self.gid}/objective-disclosure", headers=GM, json={"disclosure": None})
        self.assertEqual(r.json()["scenario"]["disclosure"], "leader")
        self.assertEqual(self.ids(self.red1), [])
        for body, status in (({"disclosure": "everyone"}, 400), ({"disclosure": "leader", "x": 1}, 400),
                             (None, 400)):
            r = self.client.put(f"/api/v1/games/{self.gid}/objective-disclosure", headers=GM, json=body)
            self.assertEqual(r.status_code, status, (body, r.text))
        # Only the GM.
        r = self.client.put(f"/api/v1/games/{self.gid}/objective-disclosure", headers=READ,
                            json={"disclosure": "members"})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.client.put("/api/v1/games/9/objective-disclosure", headers=GM,
                                         json={"disclosure": "leader"}).status_code, 404)

    def test_the_gm_chooses_when_creating_the_game(self):
        self.client.post(f"/api/v1/games/{self.gid}/end", headers=GM)
        game = self.create(mode_id=SCENARIO, objective_disclosure="members")
        self.assertEqual((game["scenario"]["disclosure"], game["scenario"]["disclosure_default"]),
                         ("members", "leader"))
        self.client.post(f"/api/v1/games/{game['id']}/end", headers=GM)
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "x", "mode_id": SCENARIO, "modifiers": [OBJECTIVES], "teams": ["red", "blue"],
            "squads": 2, "objective_disclosure": "all"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("disclosure", r.json()["detail"])

    def test_a_game_without_a_scenario_has_nothing_to_disclose(self):
        self.client.post(f"/api/v1/games/{self.gid}/end", headers=GM)
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "plain", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"],
            "objective_disclosure": "leader"})
        self.assertEqual(r.status_code, 400, r.text)
        self.assertIn("scenario", r.json()["detail"])


if __name__ == "__main__":
    unittest.main()
