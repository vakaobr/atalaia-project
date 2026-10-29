# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller engine: games, the radio side through a recording modem, restarts, field.lua.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import tempfile
import unittest

from support import CORE, FakeModem, config
from atalaia_controller.engine import Conflict, Controller, ControllerError, NotFound, Unavailable
from atalaia_controller.store import Store
from atalaia_sim import codec
from atalaia_sim.packet import cmd_decode, hello_encode, state_encode, time_decode, time_encode
from atalaia_sim.protocol import MESSAGE_TYPES

DOMINATION = "org.atalaia.domination"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def ev(node, seq, t, type_, team=0, **data):
    return codec.encode_event({"node": node, "seq": seq, "t": t, "type": type_, "team": team, "data": data})


def state(owner, counters, epoch=1, game_time=0):
    return state_encode({"owner_team": owner, "phase": 1, "game_time_ms": game_time,
                         "counters": counters, "epoch": epoch})


class EngineCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name)
        self.clock = Clock()
        self.open()

    def open(self, **cfg):
        for k, v in cfg.items():
            setattr(self.cfg, k, v)
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, clock=self.clock)
        self.messages = []
        self.ctrl.add_listener(self.messages.append)

    def reopen(self, **cfg):
        self.ctrl.stop()
        self.store.close()
        self.open(**cfg)

    def tearDown(self):
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def create(self, **spec):
        base = {"name": "Sunday", "mode_id": DOMINATION, "teams": ["red", "blue"],
                "assignments": {"4": "zone", "5": "zone"}}
        base.update(spec)
        return self.ctrl.create_game(base)

    def rx(self, *args, **kw):
        kw.setdefault("game_id", self.ctrl.game["id"])
        self.modem.rx(*args, **kw)


class GameLifecycleTests(EngineCase):
    def test_create_validates(self):
        bad = [
            {"mode_id": "org.nope.mode"},
            {"teams": []},
            {"teams": ["red", "red"]},
            {"teams": ["x" * 24]},
            {"assignments": {"4": "goalkeeper"}},
            {"assignments": {"0": "zone"}},
            {"params": {"tick_s": 0}},
            {"params": {"unknown": 1}},
            {"duration_ms": -1},
            {"name": ""},
        ]
        for spec in bad:
            with self.subTest(spec), self.assertRaises(ControllerError):
                self.create(**spec)
        self.assertEqual(self.store.games(), [])
        with self.assertRaises(NotFound):
            self.create(preset_id=99)

    def test_create_configures_the_modem(self):
        game = self.create(params={"tick_s": 5})
        self.assertEqual(game["state"], "ready")
        self.assertEqual(game["params"], {"capture_hold_ms": 3000, "tick_s": 5, "points_per_tick": 1})
        self.assertTrue(game["live"])
        [(gid, node, epoch, hops, channel, key)] = self.modem.configured
        self.assertEqual((gid, node, epoch, hops, channel), (game["id"], 0, 1, 2, 869_525_000))
        self.assertEqual(len(key), 16)
        self.assertEqual(self.ctrl.game_key(game["id"]), key)
        self.assertEqual(self.store.game_key(game["id"]), key)  # kept on disk by default (OT-7)
        with self.assertRaises(Conflict):
            self.create()

    def test_lifecycle_sends_cmd_and_time(self):
        game = self.create(duration_ms=600_000)
        gid = game["id"]
        with self.assertRaises(Conflict):
            self.ctrl.pause_game(gid)
        self.ctrl.start_game(gid, force=True)
        with self.assertRaises(Conflict):
            self.ctrl.start_game(gid, force=True)
        self.clock.advance(2)
        self.ctrl.pause_game(gid, "medic")
        self.clock.advance(5)
        self.ctrl.resume_game(gid)
        self.clock.advance(1)
        out = self.ctrl.end_game(gid, "done")
        self.assertEqual(out["state"], "ended")
        cmds = [cmd_decode(p)["cmd"] for _, p in self.modem.of("CMD")]
        self.assertEqual(cmds, [0, 1, 2, 3])
        times = [time_decode(p) for _, p in self.modem.of("TIME")]
        self.assertEqual([t["game_state"] for t in times], [1, 2, 1, 3])
        self.assertEqual(times[-1]["game_time_ms"], 3000)  # paused 5 s not counted
        self.assertEqual(times[-1]["duration_ms"], 600_000)
        seqs = [h.seq for h, _ in self.modem.sent]
        self.assertEqual(seqs, list(range(len(seqs))))  # one nonce each, in order
        log = [e["type"] for e in self.ctrl.log(gid)]
        self.assertEqual(log, ["game.start", "game.pause", "game.resume", "game.end"])
        self.assertEqual(self.ctrl.log(gid)[1]["data"], {"reason": "medic"})
        self.assertEqual(self.modem.cleared, 1)
        self.assertIsNone(self.ctrl.game)
        with self.assertRaises(Conflict):
            self.ctrl.resume_game(gid)
        game2 = self.create()
        self.assertNotEqual(game2["id"], gid)
        # A new game, a new key: its nonce epochs start at 1 (RFC 0001 amendment of 2026-10-22).
        self.assertEqual(self.modem.configured[-1][2], 1)

    def test_auto_end_at_duration(self):
        gid = self.create(duration_ms=10_000)["id"]
        self.ctrl.start_game(gid, force=True)
        self.clock.advance(9)
        self.ctrl.tick()
        self.assertEqual(self.store.game(gid)["state"], "running")
        self.clock.advance(1.1)
        self.ctrl.tick()
        self.assertEqual(self.store.game(gid)["state"], "ended")
        self.assertEqual(self.ctrl.log(gid)[-1]["data"], {"reason": "time"})

    def test_a_state_change_is_repeated_as_time_for_ten_seconds(self):
        """RFC 0001 Amendment 19, part 2: CMD + TIME at once, then TIME alone at +1, +2.5, +5 and +10 s (a
        lost first frame costs a second, not the 30 s to the next beacon); one TIME per tick at most."""
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        self.assertEqual((len(self.modem.of("CMD")), len(self.modem.of("TIME"))), (1, 1))
        seen = []
        for step in (0.9, 0.1, 1.5, 2.5, 5.0, 10.0):
            self.clock.advance(step)
            self.ctrl.tick()
            seen.append(len(self.modem.of("TIME")))
        self.assertEqual(seen, [1, 2, 3, 4, 5, 5])  # +0.9, +1.0, +2.5, +5.0, +10.0, then nothing at +20
        self.assertEqual(len(self.modem.of("CMD")), 1)
        states = {time_decode(p)["game_state"] for _, p in self.modem.of("TIME")}
        self.assertEqual(states, {1})
        # A pause replaces what is left; its TIMEs say "paused", never "running".
        self.ctrl.pause_game(gid)
        n = len(self.modem.of("TIME"))
        self.clock.advance(1.0)
        self.ctrl.tick()
        self.assertEqual(len(self.modem.of("TIME")), n + 1)
        self.assertEqual(time_decode(self.modem.of("TIME")[-1][1])["game_state"], 2)

    def test_beacons_from_the_tick(self):
        gid = self.create()["id"]
        self.ctrl.fc.state_repeat_gaps_ms = ()  # the repeats have their own test
        self.ctrl.start_game(gid, force=True)
        n = len(self.modem.of("TIME"))
        self.clock.advance(29)
        self.ctrl.tick()
        self.assertEqual(len(self.modem.of("TIME")), n)
        self.clock.advance(1.5)
        self.ctrl.tick()
        self.assertEqual(len(self.modem.of("TIME")), n + 1)

    def test_radio_down(self):
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        self.modem.state = "down"
        with self.assertRaises(Unavailable):
            self.ctrl.send_node_cmd(4, "message", {"text": "x"})
        self.assertEqual(self.ctrl.status()["radio"], "down")


class RadioInputTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.gid = self.create()["id"]
        self.ctrl.start_game(self.gid, force=True)
        self.modem.sent.clear()

    def test_events_are_stored_once_and_acked(self):
        payload = ev(4, 1, 3000, "zone.captured", team=1, zone="alpha")
        self.rx(4, 0, "EVENT", payload, epoch=2, ack=True)
        self.rx(4, 0, "EVENT", payload, epoch=2, ack=True)  # flood copy
        self.rx(4, 7, "EVENT", payload, epoch=2, ack=True)  # replay in a new packet
        captured = [e for e in self.ctrl.log(self.gid) if e["type"] == "zone.captured"]
        self.assertEqual(len(captured), 1)
        self.assertEqual((captured[0]["node"], captured[0]["team"], captured[0]["epoch"]), (4, "red", 2))
        events = [m for m in self.messages if m["type"] == "event" and m["event"]["type"] == "zone.captured"]
        self.assertEqual(len(events), 1)
        self.assertEqual(len(self.modem.of("ACK")), 2)  # the flood copy is not ACKed again

    def test_state_hello_and_scores(self):
        self.rx(4, 0, "HELLO", hello_encode({"node_name": "alpha", "platform": 1, "fw_version": "0.2.0",
                                              "core_version": "0.2.0", "tier": 0, "capabilities": [0, 3],
                                              "transports": 1, "battery_pct": 81, "epoch": 3}), epoch=3)
        self.rx(4, 1, "STATE", state(1, {1: 12}, epoch=3), epoch=3, rssi=-71)
        self.rx(5, 0, "STATE", state(2, {2: 4}), epoch=1)
        self.assertEqual(self.ctrl.score(self.gid)["teams"], {"red": 12, "blue": 4})
        self.assertEqual(self.store.scores(self.gid), {"red": 12, "blue": 4})
        nodes = {n["node_id"]: n for n in self.ctrl.nodes()}
        self.assertEqual((nodes[4]["name"], nodes[4]["owner"], nodes[4]["battery_pct"], nodes[4]["rssi"]),
                         ("alpha", "red", 81, -71))
        self.assertEqual(nodes[4]["capabilities"], [0, 3])
        self.assertEqual(nodes[5]["owner"], "blue")
        stored = {n["node_id"]: n for n in self.store.nodes(self.gid)}
        self.assertEqual(stored[4]["score"], {"red": 12, "blue": 0})
        self.assertTrue(any(m["type"] == "score" and m["teams"] == {"red": 12, "blue": 4}
                            for m in self.messages))

    def test_box_penalties_reach_the_totals_and_survive_a_restart(self):
        """RFC 0001 Amendment 18: STATE key 9 is subtracted; it is stored with the node."""
        gid = self.gid
        lost_state = state_encode({"owner_team": 1, "phase": 1, "game_time_ms": 0, "counters": {1: 12, 2: 4},
                                   "epoch": 3, "lost": {2: 3}})
        self.rx(4, 1, "STATE", lost_state, epoch=3)
        self.assertEqual(self.ctrl.score(gid)["teams"], {"red": 12, "blue": 1})
        self.assertEqual(self.ctrl.nodes()[0]["lost"], {"red": 0, "blue": 3})
        self.assertTrue(any(m["type"] == "score" and m["teams"] == {"red": 12, "blue": 1}
                            for m in self.messages))
        self.assertEqual({n["node_id"]: n for n in self.store.nodes(gid)}[4]["lost"], {"red": 0, "blue": 3})
        self.reopen(persist_game_key=True)  # the Pi rebooted
        self.assertEqual(self.ctrl.score(gid)["teams"], {"red": 12, "blue": 1})
        # The nodes view after the restart, before the box says anything: its stored penalties (BSC-1).
        self.assertEqual(self.ctrl.nodes()[0]["lost"], {"red": 0, "blue": 3})
        self.rx(4, 2, "STATE", state(1, {1: 12, 2: 4}, epoch=3), epoch=3)  # an older box: no key 9
        self.assertEqual(self.ctrl.nodes()[0]["lost"], {"red": 0, "blue": 3})
        self.assertEqual(self.ctrl.score(gid)["teams"], {"red": 12, "blue": 1})

    def test_the_nodes_view_keeps_a_boxs_penalties_across_restarts(self):
        """BSC-1 on the bench: after a controller restart (a new engine on the same store, as often
        as it happens, with the clock running) GET /nodes still has the box's `lost`."""
        gid = self.gid
        lost_state = state_encode({"owner_team": 1, "phase": 1, "game_time_ms": 0, "counters": {1: 12, 2: 4},
                                   "epoch": 3, "lost": {2: 3}})
        self.rx(4, 0, "HELLO", hello_encode({"node_name": "alpha", "platform": 1, "fw_version": "0.2.0",
                                              "core_version": "0.2.0", "tier": 0, "capabilities": [0, 3],
                                              "transports": 1, "battery_pct": 81, "epoch": 3}), epoch=3)
        self.rx(4, 1, "STATE", lost_state, epoch=3)
        for _ in range(3):
            self.reopen(persist_game_key=True)
            self.assertEqual({n["node_id"]: n["lost"] for n in self.ctrl.nodes()}[4], {"red": 0, "blue": 3})
            self.clock.advance(300)  # long enough for the box to be called offline
            self.ctrl.status()
            self.assertEqual({n["node_id"]: n["lost"] for n in self.ctrl.nodes()}[4], {"red": 0, "blue": 3})
            self.assertEqual(self.ctrl.score(gid)["teams"], {"red": 12, "blue": 1})
            self.assertEqual({n["node_id"]: n for n in self.store.nodes(gid)}[4]["lost"], {"red": 0, "blue": 3})

    def test_the_nodes_view_without_the_game_key_and_for_an_old_row(self):
        """The key was not kept (persist_game_key off): the game cannot go on, but the view still has the
        stored `lost`; a row stored before key 9 existed has the map too (all zero)."""
        gid = self.gid
        self.rx(4, 1, "STATE", state_encode({"owner_team": 1, "phase": 1, "game_time_ms": 0,
                                             "counters": {1: 12, 2: 4}, "epoch": 3, "lost": {2: 3}}), epoch=3)
        self.store.upsert_node(gid, 6, "old", "zone", {"score": {"red": 1, "blue": 0}})  # no `lost`
        self.store._exec("UPDATE games SET game_key = NULL WHERE id = ?", (gid,))  # as if never kept
        self.reopen(persist_game_key=False)
        self.assertTrue(self.ctrl.status()["key_lost"])
        nodes ={n["node_id"]: n for n in self.ctrl.nodes(gid)}
        self.assertEqual(nodes[4]["lost"], {"red": 0, "blue": 3})
        self.assertEqual(nodes[6]["lost"], {"red": 0, "blue": 0})
        self.assertEqual(self.ctrl.score(gid)["teams"], {"red": 12, "blue": 1})

    def test_other_games_are_ignored(self):
        self.modem.rx(4, 0, "STATE", state(1, {1: 50}), game_id=(self.gid % 0xFFFE) + 1)
        self.assertEqual(self.ctrl.score(self.gid)["teams"], {"red": 0, "blue": 0})

    def test_adjust_and_commands(self):
        out = self.ctrl.adjust_score(self.gid, "blue", 5, "fair play")
        self.assertEqual(out["score"]["teams"]["blue"], 5)
        self.assertEqual(out["event"]["type"], "score.delta")
        for bad in (("green", 1, ""), ("blue", 0, ""), ("blue", "x", ""), ("blue", 1, "r" * 65)):
            with self.subTest(bad), self.assertRaises(ControllerError):
                self.ctrl.adjust_score(self.gid, *bad)
        result = self.ctrl.send_node_cmd(4, "set_owner", {"team": "red"})
        [(hdr, payload)] = self.modem.of("CMD")
        self.assertEqual(hdr.seq, result["seq"])
        self.assertEqual(cmd_decode(payload), {"cmd": 4, "params": {"team": "red"}, "dest": 4})
        broadcast = self.ctrl.send_node_cmd(0xFFFF, "message", {"text": "5 min"})
        self.assertNotIn("dest", cmd_decode(self.modem.of("CMD")[-1][1]))
        self.assertEqual(broadcast["opcode"], 5)
        for bad in ((4, "start", None), (0, "message", None), (4, "message", "text"),
                    (4, "message", {"text": "x" * 200})):
            with self.subTest(bad), self.assertRaises(ControllerError):
                self.ctrl.send_node_cmd(*bad)

    def test_peer_epochs_after_a_modem_reconnect(self):
        self.rx(4, 0, "STATE", state(1, {1: 1}, epoch=6), epoch=6)
        self.modem.on_state("up")
        self.assertEqual(self.modem.peers, {4: 6})
        self.modem.on_state("down")
        self.assertEqual(self.messages[-1], {"type": "system", "kind": "radio.down"})

    def test_failed_tx_is_reported(self):
        self.modem.on_tx_ack(12, "duty_cycle")
        self.assertEqual(self.ctrl.status()["tx_status"], {"duty_cycle": 1})
        self.assertEqual(self.messages[-1]["kind"], "tx.failed")


class FailoverTests(EngineCase):
    def test_step_down_and_promote(self):
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        # Another controller beacons with a higher term: this one steps down.
        beacon = time_encode({"game_time_ms": 4000, "game_state": 1, "duration_ms": 0,
                              "wall_s": 1, "term": 2})
        self.rx(9, 0, "TIME", beacon)
        status = self.ctrl.status()
        self.assertEqual((status["role"], status["term"]), ("follower", 2))
        self.assertEqual(self.store.game(gid)["term"], 2)
        for call in (lambda: self.ctrl.pause_game(gid), lambda: self.ctrl.adjust_score(gid, "red", 1, ""),
                     lambda: self.ctrl.send_node_cmd(4, "message", {})):
            with self.assertRaises(Conflict):
                call()
        n = len(self.modem.of("TIME"))
        self.clock.advance(60)
        self.ctrl.tick()
        self.assertEqual(len(self.modem.of("TIME")), n)  # manual mode: no beacons, no claim
        self.ctrl.promote()
        self.assertEqual(self.ctrl.status()["role"], "candidate")
        self.assertEqual(len(self.modem.of("CLAIM")), 1)
        self.clock.advance(5.1)
        self.ctrl.tick()
        status = self.ctrl.status()
        self.assertEqual((status["role"], status["term"]), ("leader", 3))
        self.assertEqual(time_decode(self.modem.of("TIME")[-1][1])["term"], 3)
        self.ctrl.pause_game(gid)
        with self.assertRaises(Conflict):
            self.ctrl.promote()


class RestartTests(EngineCase):
    def test_resume_with_a_persisted_key(self):
        self.reopen(persist_game_key=True)
        game = self.create()
        gid = game["id"]
        key = self.ctrl.game_key(gid)
        self.ctrl.start_game(gid, force=True)
        self.rx(4, 0, "STATE", state(1, {1: 9}, epoch=4), epoch=4)
        self.ctrl.adjust_score(gid, "blue", 2, "")
        self.clock.advance(12)
        self.ctrl.tick()
        self.ctrl.pause_game(gid)
        self.reopen(persist_game_key=True)  # the Pi rebooted
        self.assertEqual(self.ctrl.game["id"], gid)
        self.assertEqual(self.ctrl.game_key(gid), key)
        self.assertEqual(self.ctrl.score(gid)["teams"], {"red": 9, "blue": 2})
        self.assertEqual(self.ctrl.fc.game_time_ms, 12_000)
        self.assertEqual(self.modem.configured[-1][2], 2)  # a fresh epoch for the new run
        self.rx(4, 1, "STATE", state(1, {1: 11}, epoch=4), epoch=4)
        self.assertEqual(self.ctrl.score(gid)["teams"], {"red": 11, "blue": 2})  # not 9 + 11
        self.ctrl.resume_game(gid)
        self.ctrl.end_game(gid)
        self.assertIsNone(self.store.game_key(gid))

    def test_lost_key_only_allows_ending(self):
        self.reopen(persist_game_key=False)
        gid = self.create()["id"]
        self.assertIsNone(self.store.game_key(gid))  # never on disk with persist_game_key = false
        self.ctrl.start_game(gid, force=True)
        self.reopen(persist_game_key=False)
        self.assertTrue(self.ctrl.status()["key_lost"])
        with self.assertRaises(Conflict):
            self.ctrl.pause_game(gid)
        with self.assertRaises(Conflict):
            self.create()
        out = self.ctrl.end_game(gid)
        # No field join key here: no GAME_OVER either (test_reinvite.GameOverTests sends one).
        self.assertEqual((out["state"], out["game_over_frame"]), ("ended", "no_join_key"))
        self.create()

    def test_own_event_seq_goes_on_after_a_restart(self):
        """Decision PE24-42: a second adjustment at the same game time is not taken for a replay."""
        gid = self.create()["id"]
        self.ctrl.adjust_score(gid, "red", 5, "")
        self.reopen()
        self.assertEqual(self.ctrl.adjust_score(gid, "red", 3, "")["event"]["seq"], 2)
        self.reopen()
        self.assertEqual(self.ctrl.score(gid)["teams"]["red"], 8)

    def test_the_default_survives_a_restart(self):
        """Decision OT-7: persist_game_key is on by default; a restart mid-game carries on."""
        self.assertTrue(self.cfg.persist_game_key)
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        self.reopen()
        self.assertFalse(self.ctrl.status()["key_lost"])
        self.assertEqual(self.ctrl.game["state"], "running")
        self.ctrl.pause_game(gid)
        self.assertEqual(self.ctrl.end_game(gid)["state"], "ended")
        self.assertIsNone(self.store.game_key(gid))  # the key does not outlive the game


FIELD_LUA = """
local fs = state.field { captures = 0 }
on("zone.captured", function(ev)
  fs.captures = fs.captures + 1
  local ids = {}
  for _, n in ipairs(field.nodes("zone")) do ids[#ids + 1] = n.id end
  local owner = field.common_owner(ids)
  if owner then
    emit("x.atalaia.allheld", { team = owner })
    field.send(ids[1], "message", { text = owner .. " holds every zone" })
  end
end)
"""


@unittest.skipIf(CORE is None, "the shared core library is not built")
class FieldScriptTests(EngineCase):
    def install(self):
        files = {"mode.yaml": "id: org.test.holdall\nversion: 0.1.0\nname: Hold all\n"
                              "roles:\n  zone: { requires: [team_input] }\n",
                 "node.lua": 'on("game.start", function() end)\n',
                 "field.lua": FIELD_LUA}
        return self.ctrl.modes.install(files)

    def test_field_lua_runs_on_the_controller(self):
        pkg = self.install()
        self.assertTrue(pkg.to_api()["field_script"])
        gid = self.create(mode_id="org.test.holdall")["id"]
        self.ctrl.start_game(gid, force=True)
        self.modem.sent.clear()
        self.rx(4, 0, "STATE", state(1, {}), epoch=1)
        self.rx(5, 0, "STATE", state(2, {}), epoch=1)
        self.rx(4, 1, "EVENT", ev(4, 1, 100, "zone.captured", team=1))
        self.assertEqual(self.modem.of("CMD"), [])  # owners differ
        self.rx(5, 1, "STATE", state(1, {}), epoch=1)
        self.rx(5, 2, "EVENT", ev(5, 1, 200, "zone.captured", team=1))
        log = self.ctrl.log(gid)
        allheld = [e for e in log if e["type"] == "x.atalaia.allheld"]
        self.assertEqual(len(allheld), 1)
        self.assertEqual((allheld[0]["node"], allheld[0]["team"]), (0, "red"))
        [(_, payload)] = self.modem.of("CMD")
        self.assertEqual(cmd_decode(payload), {"cmd": 5, "params": {"text": "red holds every zone"}, "dest": 4})
        self.assertEqual(self.ctrl.field.state, {"captures": 2})
        self.assertIn({"type": "field_state", "key": "captures", "value": 2}, self.messages)

    def test_bad_uploads_are_refused(self):
        from atalaia_sim.mode import ModeError
        good = {"mode.yaml": "id: org.test.m\nversion: 1\nroles: { zone: {} }\n", "node.lua": "local x = 1\n"}
        bad = [
            {**good, "node.lua": "this is not lua"},
            {**good, "field.lua": "field.nodes(("},
            {"node.lua": "local x = 1\n"},
            {**good, "mode.yaml": "id: Bad Id\nversion: 1\nroles: { zone: {} }\n"},
            {**good, "../escape.lua": "x"},
            {**good, "assets/big.txt": "x" * 1_000_001},
            {**good, "mode.yaml": "id: org.atalaia.domination\nversion: 9\nroles: { zone: {} }\n"},
        ]
        for files in bad:
            with self.subTest(sorted(files)), self.assertRaises(ModeError):
                self.ctrl.modes.install(files)
        self.assertEqual(self.ctrl.modes.install(good).id, "org.test.m")
        self.assertIn("org.test.m", [m.id for m in self.ctrl.modes.all()])


if __name__ == "__main__":
    unittest.main()


class ProjectedScoreTests(EngineCase):
    """Decision BSC-2: a mode that says how a box scores while it holds (mode.yaml `scoring`) gets
    a projected total between STATEs; display only, replaced by every STATE."""

    def start(self, **params):
        gid = self.create(params={"tick_s": 10, "points_per_tick": 2, **params})["id"]
        self.ctrl.start_game(gid, force=True)
        return gid

    def run_to(self, game_ms):
        self.clock.advance(game_ms / 1000 - self.ctrl.fc.game_time_ms / 1000)
        self.ctrl.tick()

    def test_projection_counts_the_ticks_since_the_last_state_and_every_state_replaces_it(self):
        gid = self.start()
        self.assertEqual(self.ctrl.score(gid)["projected"], {"red": 0, "blue": 0})  # nothing held yet
        self.rx(4, 1, "STATE", state(1, {}, game_time=0))
        self.run_to(25_000)  # the boxes ticked at 10 s and 20 s: 2 x 2 points, not reported yet
        out = self.ctrl.score(gid)
        self.assertEqual((out["teams"], out["projected"]), ({"red": 0, "blue": 0}, {"red": 4, "blue": 0}))
        ticks = [m for m in self.messages if m["type"] == "score" and m.get("tick")]
        self.assertEqual(ticks[-1]["projected"], {"red": 4, "blue": 0})
        self.assertEqual(ticks[-1]["teams"], {"red": 0, "blue": 0})
        # The next STATE (box time 20 s) says what the box really has: the projection was right.
        self.rx(4, 2, "STATE", state(1, {1: 4}, game_time=20_000))
        out = self.ctrl.score(gid)
        self.assertEqual((out["teams"]["red"], out["projected"]["red"]), (4, 4))
        self.assertEqual(self.store.scores(gid), {"red": 4, "blue": 0})  # stored: reports only
        self.assertEqual(self.ctrl.status()["projection"]["max_abs"], 0)
        self.run_to(35_000)
        self.assertEqual(self.ctrl.score(gid)["projected"]["red"], 6)  # one more tick at 30 s
        # A box that said less than the projection (it missed a tick): the drift is measured
        # and the total never accumulates it.
        self.rx(4, 3, "STATE", state(1, {1: 4}, game_time=35_000))
        out = self.ctrl.score(gid)
        self.assertEqual((out["teams"]["red"], out["projected"]["red"]), (4, 4))
        stats = self.ctrl.status()["projection"]
        self.assertEqual((stats["samples"], stats["off"], stats["max_abs"]), (2, 1, 2))
        self.assertEqual(stats["last"]["drift"], 2)

    def test_no_projection_while_paused_for_an_offline_box_or_a_box_with_no_owner(self):
        gid = self.start()
        self.rx(4, 1, "STATE", state(1, {}, game_time=0))
        self.rx(5, 1, "STATE", state(0, {}, game_time=0))  # nobody holds box 5
        self.run_to(15_000)
        self.assertEqual(self.ctrl.score(gid)["projected"], {"red": 2, "blue": 0})
        self.ctrl.fc.nodes[4].link = "offline"
        self.assertEqual(self.ctrl.score(gid)["projected"], {"red": 0, "blue": 0})
        self.ctrl.fc.nodes[4].link = "online"
        self.ctrl.pause_game(gid)
        self.assertNotIn("projected", self.ctrl.score(gid))
        self.ctrl.resume_game(gid)
        self.ctrl.end_game(gid)
        self.assertNotIn("projected", self.ctrl.score(gid))

    def test_a_mode_that_does_not_opt_in_has_no_projection(self):
        gid = self.create(mode_id="org.atalaia.holdall")["id"]
        self.ctrl.start_game(gid, force=True)
        self.rx(4, 1, "STATE", state(1, {}, game_time=0))
        self.run_to(15_000)
        self.assertNotIn("projected", self.ctrl.score(gid))
        self.assertIsNone(self.ctrl.status()["projection"])
        self.assertFalse([m for m in self.messages if m["type"] == "score" and m.get("tick")])

    def test_the_games_own_tick_and_points_are_used(self):
        gid = self.start(tick_s=5, points_per_tick=3)
        self.rx(4, 1, "STATE", state(2, {}, game_time=0))
        self.run_to(12_000)
        self.assertEqual(self.ctrl.score(gid)["projected"], {"red": 0, "blue": 6})
