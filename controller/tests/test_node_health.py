# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Node health events in the controller engine: node.online, node.offline and battery.low.

    cd controller && python -m unittest discover -s tests

The FieldController decides them (simulator/tests/test_node_health.py); here:
the [health] settings, the store and the sync's own event check, the live
stream (a link event carries the box's last-heard time), the nodes list, a
restart (seq, link and battery carried over), and a field.lua that is not
fed the controller's own health events (decisions FU1-1 to FU1-5).
"""

from __future__ import annotations

import tempfile
import unittest

from test_engine import EngineCase, ev, state

from support import config
from atalaia_controller import sync_format
from atalaia_controller.config import ConfigError, load_config
from atalaia_sim.packet import hello_encode, state_decode, state_encode

HEALTH = ("node.online", "node.offline", "battery.low")


def hello(battery=None):
    msg = {"node_name": "alpha", "platform": 1, "fw_version": "0.9.0", "core_version": "0.9.0", "tier": 1,
           "capabilities": [], "transports": 1, "epoch": 2}
    if battery is not None:
        msg["battery_pct"] = battery
    return hello_encode(msg)


def low_state(battery, epoch=2):
    """A STATE with a battery level."""
    msg = state_decode(state(0, {}, epoch=epoch))
    msg["battery_pct"] = battery
    return state_encode(msg)


class NodeHealthEngineTests(EngineCase):
    def setUp(self):
        super().setUp()
        self.reopen(persist_game_key=True)
        self.gid = self.create()["id"]
        self.ctrl.start_game(self.gid, force=True)

    def health(self):
        return [e for e in self.store.events(self.gid) if e["type"] in HEALTH]

    def advance(self, seconds, step=1.0):
        t = 0.0
        while t < seconds:
            self.clock.advance(step)
            self.ctrl.tick()
            t += step

    def test_online_offline_stored_streamed_and_syncable(self):
        self.rx(4, 0, "HELLO", hello(), epoch=2)
        [online] = self.health()
        self.assertEqual((online["node"], online["seq"], online["type"], online["prio"], online["epoch"]),
                         (4, 1, "node.online", "telemetry", None))
        self.assertEqual(online["data"], {"fw": "0.9.0", "tier": "reduced"})
        nodes = {n["node_id"]: n for n in self.ctrl.nodes()}
        self.assertEqual((nodes[4]["link"], nodes[4]["battery_low"]), ("online", False))
        self.assertIsNone(nodes[5]["link"])  # assigned, never heard: neither

        self.advance(119)
        self.assertEqual([e["type"] for e in self.health()], ["node.online"])
        self.advance(2)
        offline = self.health()[-1]
        self.assertEqual((offline["node"], offline["seq"], offline["type"]), (4, 2, "node.offline"))
        self.assertEqual(offline["data"], {"last_seen": 0})
        msg = [m for m in self.messages if m["type"] == "node" and m["kind"] == "offline"][-1]
        self.assertEqual(msg["node"]["link"], "offline")
        self.assertGreaterEqual(msg["node"]["seen_ms_ago"], 120_000)  # not "just now"
        self.assertTrue(any(m["type"] == "event" and m["event"]["type"] == "node.offline" for m in self.messages))
        self.assertEqual({n["node_id"]: n["link"] for n in self.ctrl.nodes()}[4], "offline")

        # What the sync sends: every one passes the sync's own check (protocol/sync.md).
        for e in self.store.events_after(self.gid, 0, 100):
            sync_format.check_event(dict(e))

    def test_battery_low_from_state_once_and_not_from_the_box_twice(self):
        self.rx(4, 0, "STATE", low_state(15), epoch=2)
        self.advance(29)
        self.assertNotIn("battery.low", [e["type"] for e in self.health()])
        self.advance(2)
        [low] = [e for e in self.health() if e["type"] == "battery.low"]
        self.assertEqual((low["node"], low["data"], low["epoch"]), (4, {"percent": 15}, None))
        self.assertTrue({n["node_id"]: n for n in self.ctrl.nodes()}[4]["battery_low"])
        # Box 5 sends its own: the controller does not add another.
        self.rx(5, 0, "STATE", low_state(9, epoch=1), epoch=1)
        self.rx(5, 1, "EVENT", ev(5, 0, 3000, "battery.low", percent=9), epoch=1)
        self.advance(60)
        lows = [(e["node"], e["epoch"]) for e in self.health() if e["type"] == "battery.low"]
        self.assertEqual(sorted(lows, key=str), [(4, None), (5, 1)])

    def test_a_restart_carries_the_health_on(self):
        self.rx(4, 0, "HELLO", hello(battery=12), epoch=2)
        self.advance(31)
        self.assertEqual([e["type"] for e in self.health()], ["node.online", "battery.low"])
        self.reopen(persist_game_key=True)  # the Pi rebooted
        fc = self.ctrl.fc
        self.assertEqual((fc.health_seq, fc.nodes[4].link, fc.nodes[4].battery_low), (2, "online", True))
        # Not heard since the restart: offline once node_offline_s has passed from it.
        self.advance(119)
        self.assertEqual(len(self.health()), 2)
        self.advance(2)
        self.assertEqual([(e["type"], e["seq"]) for e in self.health()][-1], ("node.offline", 3))
        # Heard again: online at once (a box restored as offline has no gap to wait),
        # and its low battery, already logged, is not logged again.
        self.reopen(persist_game_key=True)
        self.rx(4, 1, "STATE", low_state(11), epoch=2)
        self.advance(40)
        self.assertEqual([(e["type"], e["seq"]) for e in self.health()],
                         [("node.online", 1), ("battery.low", 2), ("node.offline", 3), ("node.online", 4)])

    def test_off(self):
        self.ctrl.end_game(self.gid)
        self.reopen(persist_game_key=True, health_node_offline_s=0.0, health_battery_low_pct=0)
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        self.rx(4, 0, "STATE", low_state(3), epoch=2, game_id=gid)
        self.advance(300, step=10)
        self.assertEqual([e for e in self.store.events(gid) if e["type"] in HEALTH], [])


class FieldScriptTests(EngineCase):
    """A field.lua gets a box's own battery.low, never the controller's health events."""

    def test_field_lua_is_not_fed_controller_health_events(self):
        gid = self.create()["id"]
        self.ctrl.start_game(gid, force=True)
        fed = []

        class Recorder:
            def input(self, type_, data=None):
                fed.append(type_)

            def advance(self, game_time_ms):
                pass

            def gains(self):
                return {}

            def close(self):
                pass

            pending_end = None
            score_key = "field-1"

        self.ctrl.field = Recorder()
        self.rx(4, 0, "STATE", low_state(5), epoch=2)
        self.rx(4, 1, "EVENT", ev(4, 0, 0, "battery.low", percent=5), epoch=2)
        self.clock.advance(200)
        self.ctrl.tick()
        types = [e["type"] for e in self.store.events(gid) if e["type"] in HEALTH]
        self.assertIn("node.online", types)
        self.assertIn("node.offline", types)
        self.assertEqual(fed, ["battery.low"])
        self.ctrl.field = None


class HealthConfigTests(unittest.TestCase):
    def test_defaults_bounds_and_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp)
            self.assertEqual((cfg.health_node_offline_s, cfg.health_battery_low_pct), (120.0, 20))
            for bad in ({"health_node_offline_s": 0.5}, {"health_node_offline_s": 3601.0},
                        {"health_battery_low_pct": 100}, {"health_battery_low_pct": -1}):
                with self.subTest(bad), self.assertRaises(ConfigError):
                    config(tmp, **bad)
            cfg = load_config(None, {"ATALAIA_HEALTH_NODE_OFFLINE_S": "300",
                                     "ATALAIA_HEALTH_BATTERY_LOW_PCT": "0"})
            self.assertEqual((cfg.health_node_offline_s, cfg.health_battery_low_pct), (300.0, 0))


if __name__ == "__main__":
    unittest.main()
