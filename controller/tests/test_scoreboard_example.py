# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The example MQTT scoreboard (examples/scoreboard/scoreboard.py) against a real Mosquitto.

    cd controller && python -m unittest discover -s tests

The controller's MQTT bridge publishes a game's score and events to a
private broker; the example runs as its own process, as a user would run
it, and must print them.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from support import MOSQUITTO, FakeModem, Mosquitto, config, wait_for
from atalaia_controller.engine import Controller
from atalaia_controller.mqtt import MqttBridge
from atalaia_controller.store import Store
from atalaia_sim import codec

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "scoreboard" / "scoreboard.py"


def load_example():
    spec = importlib.util.spec_from_file_location("scoreboard_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FormatTests(unittest.TestCase):
    def test_formatting_and_topics(self):
        sb = load_example()
        self.assertEqual(sb.format_score(4242, {"red": 30, "blue": 15}), "game 4242: red 30 · blue 15")
        self.assertEqual(sb.format_event(4242, {"t": 65000, "type": "zone.captured", "node": 7, "team": "red"}),
                         "game 4242 01:05 zone.captured node 7 red")
        self.assertEqual(sb.parse("field/v1/12/score", b'{"teams": {"red": 1}}'),
                         ("score", "12", {"teams": {"red": 1}}))
        self.assertEqual(sb.parse("field/v1/12/events/game.start", b'{"type": "game.start"}')[0], "event")
        for topic, payload in (("field/v1/12/score", b"not json"), ("other/v1/12/score", b"{}"),
                               ("field/v1/12/nodes/3/state", b"{}"), ("field/v1/12/score", b"[1]")):
            self.assertIsNone(sb.parse(topic, payload), topic)


@unittest.skipUnless(MOSQUITTO, "mosquitto not installed")
class ExampleAgainstBrokerTests(unittest.TestCase):
    def setUp(self):
        self.broker = Mosquitto()
        self.tmp = tempfile.TemporaryDirectory()
        cfg = config(self.tmp.name, mqtt_enabled=True, mqtt_port=self.broker.port)
        self.store = Store(cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(cfg, self.store, modem=self.modem)
        self.bridge = MqttBridge(cfg, self.ctrl)
        self.bridge.start()
        self.assertTrue(self.bridge.wait_connected(5))
        game = self.ctrl.create_game({"name": "g", "mode_id": "org.atalaia.domination",
                                      "teams": ["red", "blue"], "assignments": {"4": "zone"}})
        self.gid = game["id"]
        self.ctrl.start_game(self.gid)

    def tearDown(self):
        self.bridge.stop()
        self.ctrl.stop()
        self.store.close()
        self.broker.close()
        self.tmp.cleanup()

    def run_example(self, *args: str, timeout: float = 20) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(EXAMPLE), "--host", "127.0.0.1", "--port",
                               str(self.broker.port), *args], capture_output=True, text=True, timeout=timeout)

    def test_prints_the_retained_score(self):
        self.ctrl.adjust_score(self.gid, "red", 10, "bonus")
        self.assertTrue(wait_for(lambda: self.bridge.published > 0, 5))
        out = self.run_example("--once", "--timeout", "10", "--game", str(self.gid))
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout.strip().splitlines()[-1], f"game {self.gid}: red 10 · blue 0")

    def test_follows_events_and_score_changes(self):
        proc = subprocess.Popen([sys.executable, str(EXAMPLE), "--host", "127.0.0.1", "--port",
                                 str(self.broker.port)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        lines: list[str] = []
        try:
            def reader() -> None:
                for line in proc.stdout:
                    lines.append(line.rstrip("\n"))
            threading.Thread(target=reader, daemon=True).start()
            # Events are not retained: first see the retained score, which proves the subscription.
            self.ctrl.adjust_score(self.gid, "blue", 1, "probe")
            self.assertTrue(wait_for(lambda: f"game {self.gid}: red 0 · blue 1" in lines, 10), lines)
            ev = codec.encode_event({"node": 4, "seq": 1, "t": 4000, "type": "zone.captured", "team": 2,
                                     "data": {"team": "blue"}})
            self.modem.rx(4, 0, "EVENT", ev, game_id=self.gid, epoch=1, ack=True)
            self.ctrl.adjust_score(self.gid, "blue", 24, "bonus")
            self.assertTrue(wait_for(lambda: f"game {self.gid} 00:04 zone.captured node 4 blue" in lines, 10), lines)
            self.assertTrue(wait_for(lambda: f"game {self.gid}: red 0 · blue 25" in lines, 10), lines)
        finally:
            proc.terminate()
            proc.wait(10)
            proc.stdout.close()
            proc.stderr.close()

    def test_unreachable_broker_is_an_error(self):
        out = subprocess.run([sys.executable, str(EXAMPLE), "--host", "127.0.0.1", "--port", "1",
                              "--once", "--timeout", "2"], capture_output=True, text=True, timeout=20)
        self.assertEqual(out.returncode, 1)
        self.assertIn("cannot reach", out.stderr)


if __name__ == "__main__":
    unittest.main()
