# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The FieldController's node health events: node.online, node.offline, battery.low.

    cd simulator && python -m unittest discover -s tests

The controller in charge logs them about a box (their node is the box's id):
node.online when it first hears a box, node.offline when a box has been
silent for node_offline_ms, at most one link event per box every link_gap_ms,
and battery.low from the level a box's STATE or HELLO reports when the box's
own battery.low has not come within BATTERY_GRACE_MS (decisions FU1-1 to
FU1-4). These tests do NOT require the C core library.
"""

from __future__ import annotations

import unittest
from typing import Any, Optional

from atalaia_sim import codec
from atalaia_sim.election import Election
from atalaia_sim.field_controller import (
    BATTERY_GRACE_MS,
    BATTERY_HYSTERESIS,
    FieldController,
)
from atalaia_sim.packet import Header, hello_encode, state_encode, vf_make
from atalaia_sim.protocol import MESSAGE_TYPES

BOX = 7
OFFLINE_MS = 120_000
GAP_MS = 60_000


class Quiet:
    """A transport that sends nothing anywhere (these tests only listen)."""

    seq = 0

    def send(self, msg_type: int, payload: bytes, *, priority: int, ack_req: bool, hop_limit: int,
             now_ms: int) -> Optional[int]:
        return 0


class NodeHealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fc = self.controller()
        self.seq = 0
        self.nodes: list[tuple[int, str]] = []
        self.fc.on_node = lambda node, kind: self.nodes.append((node.node_id, kind))

    def controller(self, leader: bool = True) -> FieldController:
        election = Election(0, priority=0)
        if leader:
            election.lead(1, 0)
        else:
            election.follow(0)
        fc = FieldController(transport=Quiet(), teams=["red", "blue"], election=election)
        fc.node_offline_ms = OFFLINE_MS
        fc.link_gap_ms = GAP_MS
        fc.battery_low_pct = 20
        fc.register_node(BOX, "alpha", "zone")
        return fc

    def packet(self, now_ms: int, msg_type: str, payload: bytes, node: int = BOX) -> None:
        self.fc.tick(now_ms)
        self.seq += 1
        header = Header(vf_make(1, 0, False, True), 1, node, self.seq, 2, MESSAGE_TYPES[msg_type])
        self.fc.on_packet(node, header, payload, {"epoch": 1, "rssi": -60})

    def hello(self, now_ms: int, battery: Optional[int] = None) -> None:
        msg: dict[str, Any] = {"node_name": "alpha", "platform": 1, "fw_version": "0.9.0",
                               "core_version": "0.9.0", "tier": 0, "capabilities": [], "transports": 1,
                               "epoch": 1}
        if battery is not None:
            msg["battery_pct"] = battery
        self.packet(now_ms, "HELLO", hello_encode(msg))

    def state(self, now_ms: int, battery: Optional[int] = None) -> None:
        msg: dict[str, Any] = {"owner_team": 0, "phase": 1, "game_time_ms": 0, "counters": {}, "epoch": 1}
        if battery is not None:
            msg["battery_pct"] = battery
        self.packet(now_ms, "STATE", state_encode(msg))

    def health(self) -> list[dict[str, Any]]:
        return [e["event"] for e in self.fc.event_log
                if e.get("type") == "event" and e["event"].get("origin") == "controller"]

    def kinds(self) -> list[str]:
        return [e["type"] for e in self.health()]

    def test_online_when_first_heard_then_offline_after_the_silence(self) -> None:
        self.fc.start_game(now_ms=0)
        self.fc.tick(50_000)
        self.assertEqual(self.health(), [])  # registered by the join, never heard: nothing
        self.hello(60_000)
        online = self.health()
        self.assertEqual(len(online), 1)
        ev = online[0]
        self.assertEqual((ev["node"], ev["seq"], ev["type"], ev["prio"], ev["epoch"], ev["pkt_seq"]),
                         (BOX, 1, "node.online", "telemetry", None, None))
        self.assertEqual(ev["data"], {"fw": "0.9.0", "tier": "full"})
        self.assertEqual(ev["t"], 60_000)
        self.assertEqual(self.nodes[-1], (BOX, "online"))
        # STATE every 15 s keeps it online.
        for now in range(75_000, 200_000, 15_000):
            self.state(now)
        last_heard = 195_000
        self.fc.tick(last_heard + OFFLINE_MS - 1)
        self.assertEqual(self.kinds(), ["node.online"])
        self.fc.tick(last_heard + OFFLINE_MS)
        self.assertEqual(self.kinds(), ["node.online", "node.offline"])
        offline = self.health()[-1]
        self.assertEqual((offline["node"], offline["seq"], offline["data"]),
                         (BOX, 2, {"last_seen": last_heard}))
        self.assertEqual(self.fc.nodes[BOX].link, "offline")
        self.assertEqual(self.nodes[-1], (BOX, "offline"))
        self.fc.tick(last_heard + 10 * OFFLINE_MS)
        self.assertEqual(self.kinds(), ["node.online", "node.offline"])  # once
        # Heard again, long after: online at once.
        self.state(last_heard + 10 * OFFLINE_MS + 1)
        self.assertEqual(self.kinds(), ["node.online", "node.offline", "node.online"])
        self.assertEqual(self.health()[-1]["data"], {"fw": "0.9.0", "tier": "full"})

    def test_a_flapping_link_is_debounced(self) -> None:
        # One packet every 125 s for an hour: just over the threshold each time.
        for t in range(0, 3_600_000, 1_000):
            if t % 125_000 == 0:
                self.state(t)
            else:
                self.fc.tick(t)
        events = self.health()
        times = [e["received_ms"] for e in events]
        self.assertTrue(all(b - a >= GAP_MS for a, b in zip(times, times[1:])), times)
        self.assertLessEqual(len(events), 1 + 2 * (3_600_000 // 125_000))
        # Online back only GAP_MS after node.offline, although heard 5 s after it.
        offline = [e["received_ms"] for e in events if e["type"] == "node.offline"]
        online = [e["received_ms"] for e in events if e["type"] == "node.online"]
        self.assertEqual((offline[0], online[1]), (OFFLINE_MS, OFFLINE_MS + GAP_MS))
        kinds = self.kinds()
        self.assertTrue(all(a != b for a, b in zip(kinds, kinds[1:])), kinds)
        # Heard steadily afterwards: it ends online, and nothing more is logged.
        end = 3_600_000
        for t in range(end, end + 5 * GAP_MS, 1_000):
            if t % 10_000 == 0:
                self.state(t)
            else:
                self.fc.tick(t)
        self.assertEqual(self.kinds()[-1], "node.online")
        settled = len(self.health())
        for t in range(end + 5 * GAP_MS, end + 10 * GAP_MS, 10_000):
            self.state(t)
        self.assertEqual(len(self.health()), settled)

    def test_a_short_gap_is_not_reported(self) -> None:
        self.state(0)
        self.fc.tick(OFFLINE_MS - 1_000)
        self.state(OFFLINE_MS - 500)  # 2 minutes less a second: still online
        self.fc.tick(OFFLINE_MS + 30_000)
        self.assertEqual(self.kinds(), ["node.online"])

    def test_battery_low_from_state_after_the_grace(self) -> None:
        self.state(0, battery=60)
        self.state(15_000, battery=19)
        self.fc.tick(15_000 + BATTERY_GRACE_MS - 1)
        self.assertEqual(self.kinds(), ["node.online"])
        self.fc.tick(15_000 + BATTERY_GRACE_MS)
        self.assertEqual(self.kinds(), ["node.online", "battery.low"])
        ev = self.health()[-1]
        self.assertEqual((ev["node"], ev["data"], ev["prio"]), (BOX, {"percent": 19}, "telemetry"))
        # Lower still: nothing more. Inside the hysteresis and down again: nothing.
        t = 15_000 + BATTERY_GRACE_MS
        for battery in (12, 20 + BATTERY_HYSTERESIS - 1, 15):
            for _ in range(4):
                t += 15_000
                self.state(t, battery=battery)
        self.assertEqual(self.kinds().count("battery.low"), 1)
        # Charged past the hysteresis, then low again: a second one.
        t += 15_000
        self.state(t, battery=20 + BATTERY_HYSTERESIS)
        t += 15_000
        self.state(t, battery=10)
        self.fc.tick(t + BATTERY_GRACE_MS)
        self.assertEqual(self.kinds().count("battery.low"), 2)
        self.assertEqual(self.health()[-1]["data"], {"percent": 10})

    def test_battery_low_from_hello(self) -> None:
        self.hello(0, battery=8)
        self.fc.tick(BATTERY_GRACE_MS)
        self.assertEqual(self.kinds(), ["node.online", "battery.low"])

    def test_the_box_own_battery_low_is_not_repeated(self) -> None:
        self.state(0, battery=18)
        payload = codec.encode_event({"node": BOX, "seq": 0, "t": 0, "type": "battery.low",
                                      "data": {"percent": 18}})
        self.packet(5_000, "EVENT", payload)
        self.fc.tick(5_000 + OFFLINE_MS - 1)
        self.assertEqual(self.kinds(), ["node.online"])
        box = [e["event"] for e in self.fc.event_log if e.get("type") == "event"
               and e["event"]["type"] == "battery.low"]
        self.assertEqual([(e["node"], e["epoch"], e.get("origin")) for e in box], [(BOX, 1, None)])
        self.assertTrue(self.fc.nodes[BOX].battery_low)

    def test_a_level_that_recovers_within_the_grace_is_not_reported(self) -> None:
        self.state(0, battery=19)
        self.state(BATTERY_GRACE_MS // 2, battery=21)
        self.fc.tick(3 * BATTERY_GRACE_MS)
        self.assertEqual(self.kinds(), ["node.online"])

    def test_off_by_default(self) -> None:
        fc = FieldController(transport=Quiet(), teams=["red"])
        header = Header(vf_make(1, 0, False, True), 1, BOX, 1, 2, MESSAGE_TYPES["STATE"])
        fc.on_packet(BOX, header, state_encode({"owner_team": 0, "phase": 0, "game_time_ms": 0,
                                                "counters": {}, "battery_pct": 3, "epoch": 1}))
        fc.tick(10 * OFFLINE_MS)
        self.assertEqual([e for e in fc.event_log if e.get("type") == "event"], [])

    def test_a_standby_or_an_ended_game_logs_nothing(self) -> None:
        self.fc = self.controller(leader=False)
        self.state(0, battery=5)
        self.fc.tick(10 * OFFLINE_MS)
        self.assertEqual(self.kinds(), [])
        self.fc = self.controller()
        self.fc.start_game(now_ms=0)
        self.state(1_000, battery=50)
        self.fc.end_game(now_ms=2_000)
        self.state(3_000, battery=5)
        self.fc.tick(10 * OFFLINE_MS)
        self.assertEqual(self.kinds(), ["node.online"])

    def test_seq_continues_from_health_seq(self) -> None:
        self.fc.health_seq = 41  # the host restores it after a restart
        self.state(0)
        self.assertEqual(self.health()[0]["seq"], 42)


if __name__ == "__main__":
    unittest.main()
