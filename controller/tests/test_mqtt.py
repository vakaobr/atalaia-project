# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The MQTT bridge against a real Mosquitto broker (spec section 11 topics).

    cd controller && python -m unittest discover -s tests

Starts a private mosquitto on a free port, connects the bridge and a
paho subscriber, and checks events, retained score and node topics, the
cmd topics turning into radio CMDs, and republishing after a broker restart.
"""

from __future__ import annotations

import json
import tempfile
import threading
import unittest

import paho.mqtt.client as paho

from support import MOSQUITTO, FakeModem, Mosquitto, config, wait_for
from atalaia_controller.engine import Controller
from atalaia_controller.mqtt import MqttBridge, _client
from atalaia_controller.store import Store
from atalaia_sim import codec
from atalaia_sim.packet import cmd_decode, state_encode


class Listener:
    def __init__(self, port: int, topic: str = "field/v1/#") -> None:
        self.messages: list[tuple[str, dict, bool]] = []
        self.lock = threading.Lock()
        self.client = _client(f"test-{id(self)}")
        self.client.on_message = self._on_message
        self.ready = threading.Event()
        self.client.on_subscribe = lambda *a: self.ready.set()
        self.client.connect("127.0.0.1", port)
        self.client.subscribe(topic, qos=1)
        self.client.loop_start()
        assert self.ready.wait(5)

    def _on_message(self, client, userdata, msg) -> None:
        with self.lock:
            self.messages.append((msg.topic, json.loads(msg.payload), bool(msg.retain)))

    def topic(self, name: str) -> list[dict]:
        with self.lock:
            return [m for t, m, _ in self.messages if t == name]

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


@unittest.skipUnless(MOSQUITTO, "mosquitto not installed")
class MqttTests(unittest.TestCase):
    def setUp(self):
        self.broker = Mosquitto()
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name, mqtt_enabled=True, mqtt_port=self.broker.port)
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem)
        self.bridge = MqttBridge(self.cfg, self.ctrl)
        self.bridge.start()
        self.assertTrue(self.bridge.wait_connected(5))
        self.game = self.ctrl.create_game({"name": "g", "mode_id": "org.atalaia.domination",
                                           "teams": ["red", "blue"], "assignments": {"4": "zone"}})
        self.gid = self.game["id"]
        self.ctrl.start_game(self.gid)

    def tearDown(self):
        self.bridge.stop()
        self.ctrl.stop()
        self.store.close()
        self.broker.close()
        self.tmp.cleanup()

    def test_events_score_and_nodes(self):
        sub = Listener(self.broker.port)
        try:
            self.modem.rx(4, 0, "STATE", state_encode({"owner_team": 2, "phase": 1, "game_time_ms": 900,
                                                       "counters": {2: 6}, "epoch": 1}), game_id=self.gid,
                          epoch=1, rssi=-77)
            self.modem.rx(4, 1, "EVENT", codec.encode_event({"node": 4, "seq": 1, "t": 1000,
                                                             "type": "zone.captured", "team": 2,
                                                             "data": {"zone": "hill"}}),
                          game_id=self.gid, epoch=1)
            base = f"field/v1/{self.gid}"
            self.assertTrue(wait_for(lambda: sub.topic(f"{base}/events/zone.captured"), 5))
            [ev] = sub.topic(f"{base}/events/zone.captured")
            self.assertEqual((ev["game"], ev["node"], ev["team"], ev["data"]), (self.gid, 4, "blue", {"zone": "hill"}))
            self.assertTrue(wait_for(lambda: sub.topic(f"{base}/score"), 5))
            self.assertEqual(sub.topic(f"{base}/score")[-1]["teams"], {"red": 0, "blue": 6})
            state = sub.topic(f"{base}/nodes/4/state")[-1]
            self.assertEqual((state["owner"], state["game_time_ms"]), ("blue", 900))
            self.assertEqual(sub.topic(f"{base}/nodes/4/health")[-1]["rssi"], -77)
            self.ctrl.pause_game(self.gid, "rain")  # lifecycle events go out too
            self.assertTrue(wait_for(lambda: sub.topic(f"{base}/events/game.pause"), 5))
            self.assertEqual(sub.topic(f"{base}/events/game.pause")[0]["data"], {"reason": "rain"})
        finally:
            sub.close()
        # A scoreboard that connects later still gets the retained score.
        late = Listener(self.broker.port, f"field/v1/{self.gid}/score")
        try:
            self.assertTrue(wait_for(lambda: late.messages, 5))
            topic, msg, retained = late.messages[0]
            self.assertTrue(retained)
            self.assertEqual(msg["teams"], {"red": 0, "blue": 6})
        finally:
            late.close()

    def test_cmd_topics(self):
        pub = _client("gm-test")
        pub.connect("127.0.0.1", self.broker.port)
        pub.loop_start()
        try:
            self.modem.sent.clear()
            pub.publish(f"field/v1/{self.gid}/cmd/4", json.dumps({"cmd": "message", "params": {"text": "hi"}}), qos=1)
            pub.publish(f"field/v1/{self.gid}/cmd/all", json.dumps({"cmd": "reset"}), qos=1)
            pub.publish(f"field/v1/{self.gid}/cmd/4", "not json", qos=1)
            pub.publish(f"field/v1/{self.gid}/cmd/4", json.dumps({"cmd": "end"}), qos=1)
            pub.publish(f"field/v1/{self.gid + 1}/cmd/4", json.dumps({"cmd": "reset"}), qos=1)
            self.assertTrue(wait_for(lambda: self.bridge.commands >= 5, 5))
            cmds = [cmd_decode(p) for _, p in self.modem.of("CMD")]
            self.assertEqual(cmds, [{"cmd": 5, "params": {"text": "hi"}, "dest": 4}, {"cmd": 6}])
        finally:
            pub.loop_stop()
            pub.disconnect()

    def test_retained_topics_republished_after_a_broker_restart(self):
        self.ctrl.adjust_score(self.gid, "red", 4, "")
        port = self.broker.port
        self.broker.close()  # the broker restarts and forgets everything (no persistence)
        self.assertTrue(wait_for(lambda: not self.bridge.connected.is_set(), 5))
        self.broker = Mosquitto(port)
        self.assertTrue(self.bridge.wait_connected(20))  # paho reconnects by itself
        sub = Listener(self.broker.port, f"field/v1/{self.gid}/score")
        try:
            self.assertTrue(wait_for(lambda: sub.messages, 5))
            self.assertEqual(sub.messages[-1][1]["teams"], {"red": 4, "blue": 0})
            self.assertTrue(sub.messages[-1][2])
        finally:
            sub.close()

if __name__ == "__main__":
    unittest.main()
