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
import types
import unittest

import paho.mqtt.client as paho

from support import MOSQUITTO, FakeModem, Listener, Mosquitto, config, wait_for
from atalaia_controller.engine import Controller
from atalaia_controller.mqtt import MqttBridge, _client
from atalaia_controller.store import Store
from atalaia_sim import codec
from atalaia_sim.packet import cmd_decode, state_encode


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
        self.ctrl.start_game(self.gid, force=True)

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
            # wait_connected means the bridge's SUBSCRIBE is queued, not that the broker has it. A retained
            # command for another game (refused, nothing on air) reaches the bridge exactly once, live or
            # retained, as soon as its subscription holds.
            pub.publish(f"field/v1/{self.gid + 1}/cmd/4", "{}", qos=1, retain=True)
            self.assertTrue(wait_for(lambda: self.bridge.commands >= 1, 5))
            heard = self.bridge.commands
            self.modem.sent.clear()
            pub.publish(f"field/v1/{self.gid}/cmd/4", json.dumps({"cmd": "message", "params": {"text": "hi"}}), qos=1)
            pub.publish(f"field/v1/{self.gid}/cmd/all", json.dumps({"cmd": "reset"}), qos=1)
            pub.publish(f"field/v1/{self.gid}/cmd/4", "not json", qos=1)
            pub.publish(f"field/v1/{self.gid}/cmd/4", json.dumps({"cmd": "end"}), qos=1)
            pub.publish(f"field/v1/{self.gid + 1}/cmd/4", json.dumps({"cmd": "reset"}), qos=1)
            self.assertTrue(wait_for(lambda: self.bridge.commands >= heard + 5, 5))
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
        topic = f"field/v1/{self.gid}/score"
        # wait_connected means the republish is queued, not that the broker has it: a subscriber faster than
        # the bridge gets the score as a live message (retain flag 0, MQTT 3.1.1 section 3.3.1.3). Seeing it
        # at all proves the broker has it; a scoreboard that subscribes after that gets it retained.
        first = Listener(port, topic)
        try:
            self.assertTrue(wait_for(lambda: first.messages, 5))
            self.assertEqual(first.messages[-1][1]["teams"], {"red": 4, "blue": 0})
        finally:
            first.close()
        sub = Listener(port, topic)
        try:
            self.assertTrue(wait_for(lambda: sub.messages, 5))
            self.assertEqual(sub.messages[-1][1]["teams"], {"red": 4, "blue": 0})
            self.assertTrue(sub.messages[-1][2])
        finally:
            sub.close()


class RepublishOrderTests(unittest.TestCase):
    """The reconnect republish against a score published at the same moment (no broker: publishes recorded)."""

    def test_a_score_published_during_the_reconnect_republish_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp, mqtt_enabled=True)
        bridge = MqttBridge(cfg, types.SimpleNamespace(add_listener=lambda fn: None))  # type: ignore[arg-type]
        sent: list[tuple[str, dict]] = []
        hooks: list = []

        class Client:
            def publish(self, topic, payload, qos=0, retain=False):
                if hooks:
                    hooks.pop()()  # a new score arrives while this republish is on its way
                sent.append((topic, json.loads(payload)))
                return types.SimpleNamespace(rc=0)

            def subscribe(self, *args, **kwargs):
                pass

        bridge.client = Client()  # type: ignore[assignment]
        topic = "field/v1/1/score"
        bridge._publish(topic, {"teams": {"red": 1}}, retain=True)
        racer = threading.Thread(target=bridge._publish, args=(topic, {"teams": {"red": 2}}, True))

        def race() -> None:
            racer.start()
            racer.join(0.2)  # before the fix it ran to the end here, ahead of the republish of red 1

        hooks.append(race)
        bridge._on_connect(bridge.client, None, {}, 0)
        racer.join(5)
        self.assertEqual(sent[-1], (topic, {"teams": {"red": 2}}))  # the broker keeps the newest score
        self.assertEqual(bridge._retained[topic], b'{"teams":{"red":2}}')


if __name__ == "__main__":
    unittest.main()
