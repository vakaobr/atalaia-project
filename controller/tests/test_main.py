# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration, tokens, and the whole controller served by uvicorn on a real port.

    cd controller && python -m unittest discover -s tests

The server test runs main.build() as `python -m atalaia_controller run`
would, with the C host modem as the radio: HTTP and the WebSocket go over
a real socket.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import httpx
import uvicorn
import websockets

from support import CORE, MODEM_HOST, HostModem, config, free_port, wait_for
from atalaia_controller.config import ConfigError, load_config
from atalaia_controller.main import build, ensure_tokens
from atalaia_controller.store import Store

CONTROLLER_DIR = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text: str) -> str:
        path = os.path.join(self.tmp.name, "c.toml")
        Path(path).write_text(text, encoding="utf-8")
        return path

    def test_defaults(self):
        cfg = load_config(None, env={})
        self.assertEqual((cfg.node_id, cfg.failover_mode, cfg.channel_hz, cfg.max_hops, cfg.api_port),
                         (0, "manual", 869_525_000, 2, 8080))
        self.assertTrue(cfg.modes_dirs[0].endswith("modes"))

    def test_file_then_environment(self):
        path = self.write('[controller]\nnode_id = 3\nfailover_mode = "auto"\n'
                          '[modem]\nport = "/dev/ttyACM0"\n[api]\nport = 9000\n[mqtt]\nenabled = false\n')
        cfg = load_config(path, env={"ATALAIA_API_PORT": "9100", "ATALAIA_CONTROLLER_PERSIST_GAME_KEY": "yes"})
        self.assertEqual((cfg.node_id, cfg.failover_mode, cfg.port, cfg.api_port, cfg.mqtt_enabled,
                          cfg.persist_game_key), (3, "auto", "/dev/ttyACM0", 9100, False, True))

    def test_errors(self):
        for text in ('[nope]\nx = 1\n', '[api]\nnope = 1\n', '[controller]\nfailover_mode = "always"\n',
                     '[radio]\nchannel_hz = 915000000\n', '[radio]\nmax_hops = 5\n', 'not toml ['):
            with self.subTest(text), self.assertRaises(ConfigError):
                load_config(self.write(text), env={})
        with self.assertRaises(ConfigError):
            load_config(None, env={"ATALAIA_API_PORT": "eighty"})

    def test_retention_days(self):
        cfg = load_config(self.write('[checkin]\nchrono_retention_days = 90\ngame_retention_days = 3653\n'), env={})
        self.assertEqual((cfg.chrono_retention_days, cfg.game_retention_days), (90, 3653))
        self.assertEqual(load_config(None, env={}).game_retention_days, 365)  # RET-1: a year by default
        for text in ('[checkin]\ngame_retention_days = 29\n', '[checkin]\nchrono_retention_days = 3654\n',
                     '[checkin]\nchrono_retention_days = true\n'):
            with self.subTest(text), self.assertRaises(ConfigError):
                load_config(self.write(text), env={})

    def test_example_file_loads(self):
        cfg = load_config(str(CONTROLLER_DIR / "controller.example.toml"), env={})
        self.assertEqual(cfg.port, "/dev/ttyACM0")
        self.assertEqual((cfg.chrono_retention_days, cfg.game_retention_days), (365, 365))


class TokenTests(unittest.TestCase):
    def test_generated_once_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp, gm_token="", read_token="")
            store = Store(cfg.db_path)
            gm, read = ensure_tokens(cfg, store)
            self.assertNotEqual(gm, read)
            self.assertGreaterEqual(len(gm), 24)
            self.assertEqual(ensure_tokens(cfg, store), (gm, read))
            store.close()
            env = {**os.environ, "ATALAIA_CONTROLLER_DB_PATH": cfg.db_path, "ATALAIA_MQTT_ENABLED": "false"}
            out = subprocess.run([sys.executable, "-m", "atalaia_controller", "tokens"], cwd=CONTROLLER_DIR,
                                 env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertIn(gm, out.stdout)
            self.assertIn(read, out.stdout)

    def test_same_tokens_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config(tmp, gm_token="same", read_token="same")
            store = Store(cfg.db_path)
            with self.assertRaises(ConfigError):
                ensure_tokens(cfg, store)
            store.close()


@unittest.skipUnless(MODEM_HOST, "host modem not built")
class ServerTests(unittest.TestCase):
    def test_served_over_http_and_websocket(self):
        host = HostModem()
        tmp = tempfile.TemporaryDirectory()
        port = free_port()
        cfg = config(tmp.name, port=host.url, api_port=port, host="127.0.0.1")
        bundle = build(cfg, core=CORE, load_core_lib=False)
        server = uvicorn.Server(uvicorn.Config(bundle.app, host="127.0.0.1", port=port, log_level="error",
                                               lifespan="on"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            self.assertTrue(wait_for(lambda: server.started, 10))
            self.assertTrue(bundle.modem.wait_up(10))  # started by the app's lifespan
            gm = {"Authorization": "Bearer gm-secret"}
            with httpx.Client(base_url=base, timeout=10) as http:
                self.assertEqual(http.get("/healthz").json()["radio"], "up")
                game = http.post("/api/v1/games", headers=gm, json={
                    "name": "served", "mode_id": "org.atalaia.bomb", "teams": ["red", "blue"],
                    "assignments": {"2": "bomb"}}).json()
                self.assertEqual(http.post(f"/api/v1/games/{game['id']}/start", headers=gm, json={"force": True}).status_code, 200)
                self.assertTrue(host.transmitted_all())  # CMD start and TIME went on air

                async def stream():
                    async with websockets.connect(f"ws://127.0.0.1:{port}/api/v1/stream?token=read-secret") as ws:
                        hello = json.loads(await ws.recv())
                        http.post(f"/api/v1/games/{game['id']}/pause", headers=gm, json={"reason": "rain"})
                        while True:
                            msg = json.loads(await asyncio.wait_for(ws.recv(), 5))
                            if msg["type"] == "game":
                                return hello, msg

                hello, msg = asyncio.run(stream())
                self.assertEqual(hello["game"]["id"], game["id"])
                self.assertEqual(msg["game"]["state"], "paused")
                status = http.get("/api/v1/controller", headers=gm).json()
                self.assertEqual(status["modem"]["ident"]["fw"], "atalaia-modem")
        finally:
            server.should_exit = True
            thread.join(10)
            self.assertFalse(thread.is_alive())
            self.assertEqual(bundle.modem.state, "closed")  # stopped by the lifespan
            bundle.store.close()
            host.close()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
