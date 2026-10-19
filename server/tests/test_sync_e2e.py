# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""End to end: the real field controller syncs with the real site server on PostgreSQL 16.

The controller's engine (``atalaia_controller.engine.Controller``) runs a
Domination game on its own SQLite store, with no radio: node events and
STATE counters go in through the engine's own hooks, as the modem would
deliver them, and the GM adjusts the score down. Its sync client
(``sync_client.SyncClient``, urllib over a real TCP socket) pushes to the
site server, served by uvicorn on 127.0.0.1 in this process, which stores in
the test PostgreSQL. Then: the totals on both sides agree; a replay of
everything changes nothing; a restarted client sends nothing new; a
controller that was offline catches up.

This runs in the site server's test image (``python3 tools/docker_server.py
test tests.test_sync_e2e``): the image has the controller and simulator
packages and the core library (decision P4R16).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any

import uvicorn

from atalaia_sim.core import Core, find_library

from atalaia_controller.config import Config
from atalaia_controller.engine import Controller
from atalaia_controller.store import Store
from atalaia_controller.sync_client import SyncClient
from atalaia_server import sync
from atalaia_server.app import create_app
from atalaia_server.config import Settings

from .base import SECRET_KEY, TempDatabase

REPO = Path(__file__).resolve().parents[2]
DOMINATION = "org.atalaia.domination"
CORE = Core(find_library())
logging.getLogger("atalaia.sync").setLevel(logging.CRITICAL)  # the tests provoke its warnings  # the image's core library (ATALAIA_CORE_LIB)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SiteServer:
    """The site server app under uvicorn in a thread, on a loopback port."""

    def __init__(self, database_url: str) -> None:
        self.port = free_port()
        app = create_app(Settings(database_url=database_url, secret_key=SECRET_KEY, purge_hour=None))
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning",
                                                    lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self) -> "SiteServer":
        self.thread.start()
        end = time.monotonic() + 20
        while not self.server.started:
            if time.monotonic() > end or not self.thread.is_alive():
                raise RuntimeError("the site server did not start")
            time.sleep(0.02)
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)


class SyncEndToEndTests(unittest.TestCase):
    db: TempDatabase

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = TempDatabase()
        cls.db.create()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.drop()

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        self.key = sync.new_key()
        self.db.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2)", self.field,
                      sync.key_hash(self.key))
        self.site = SiteServer(self.db.url).__enter__()

    def tearDown(self) -> None:
        self.site.__exit__(None, None, None)
        self.db.fetch("TRUNCATE fields RESTART IDENTITY CASCADE")
        self.tmp.cleanup()

    def controller(self, name: str = "controller", url: str = "") -> tuple[Config, Store, Controller]:
        cfg = Config(db_path=os.path.join(self.tmp.name, f"{name}.db"), mqtt_enabled=False,
                     modes_dirs=[str(REPO / "modes")], sync_enabled=True, sync_url=url or self.site.url,
                     sync_api_key=self.key, sync_timeout_s=5.0)
        cfg.validate()
        store = Store(cfg.db_path)
        return cfg, store, Controller(cfg, store, core=CORE)

    def play(self, ctrl: Controller) -> int:
        """A short Domination game: a capture, STATE counters, a GM's -50, the end."""
        game = ctrl.create_game({"name": "Domingo", "mode_id": DOMINATION, "teams": ["red", "blue"],
                                 "assignments": {"3": "zone", "4": "zone"}})
        gid = game["id"]
        ctrl.start_game(gid)
        fc = ctrl.fc
        assert fc is not None
        for seq, (node, team, t) in enumerate(((3, "red", 60_000), (4, "blue", 90_000), (3, "red", 120_000)), 1):
            ctrl._on_event({"node": node, "seq": seq, "t": t, "type": "zone.captured", "team": team, "squad": 0,
                            "prio": "normal", "data": {"zone": f"z{node}"}, "epoch": 1, "pkt_seq": 10 + seq})
        fc.merge_scores(3, {1: 120})
        fc.merge_scores(4, {2: 70})
        fc.merge_scores(3, {1: 90})  # an older STATE, late: the counter stays 120
        for node in (3, 4):
            ctrl._on_node(fc.nodes[node], "state")
        ctrl.adjust_score(gid, "red", -50, "penalty")
        ctrl.adjust_score(gid, "blue", 15, "bonus")
        ctrl.end_game(gid, "time")
        return gid

    def server_game(self) -> dict[str, Any]:
        rows = self.db.fetch("SELECT * FROM games")
        self.assertEqual(len(rows), 1)
        return dict(rows[0])

    def server_totals(self, game: dict[str, Any]) -> dict[str, int]:
        counters = self.db.fetch("SELECT team, sum(value) AS v FROM game_node_scores WHERE game = $1 GROUP BY team",
                                 game["id"])
        out = {t: 0 for t in json.loads(game["teams"])}
        for r in counters:
            out[r["team"]] += int(r["v"])
        for r in self.db.fetch("SELECT (data->>'amount')::int AS a, data->>'team' AS t FROM game_events "
                               "WHERE game = $1 AND event_type = 'score.delta'", game["id"]):
            out[r["t"]] += r["a"]
        return out

    def test_a_game_reaches_the_site_server(self) -> None:
        cfg, store, ctrl = self.controller()
        gid = self.play(ctrl)
        client = SyncClient(cfg, store)
        self.assertTrue(client.run_once(), client.last_error)

        game = self.server_game()
        self.assertEqual((game["game_id"], game["game_seed"], game["state"], game["mode_id"]),
                         (gid, store.game(gid)["game_seed"], "ended", DOMINATION))
        n_events = store.count_events(gid)
        self.assertEqual(self.db.fetch("SELECT count(*) FROM game_events")[0][0], n_events)
        self.assertEqual(self.server_totals(game), ctrl.score(gid)["teams"])
        self.assertEqual(ctrl.score(gid)["teams"], {"red": 70, "blue": 85})
        self.assertEqual({r[0] for r in self.db.fetch("SELECT node_id FROM game_nodes")}, {3, 4})
        self.assertTrue(store.sync_state(gid, store.game(gid)["game_seed"])["final"])

        # Everything again (a controller that lost its cursor): duplicates only, the same totals.
        store.reset_sync_state()
        self.assertTrue(SyncClient(cfg, store).run_once())
        self.assertEqual(self.db.fetch("SELECT count(*) FROM game_events")[0][0], n_events)
        self.assertEqual(self.server_totals(self.server_game()), {"red": 70, "blue": 85})

        # A restarted client: nothing left to send, no request made.
        again = SyncClient(cfg, store)
        self.assertTrue(again.run_once())
        self.assertEqual(again.requests, 0)

    def test_an_offline_controller_catches_up(self) -> None:
        dead = f"http://127.0.0.1:{free_port()}"
        cfg, store, ctrl = self.controller(url=dead)
        client = SyncClient(cfg, store)
        gid = self.play(ctrl)  # nothing listens: the game goes on regardless
        self.assertFalse(client.run_once())
        self.assertFalse(client.run_once())
        self.assertEqual((client.last_error, client.failures), ("unreachable", 2))
        self.assertEqual(store.sync_state(gid, store.game(gid)["game_seed"])["acked_id"], 0)
        cfg.sync_url = self.site.url
        back = SyncClient(cfg, store)
        self.assertTrue(back.run_once())
        self.assertEqual(self.db.fetch("SELECT count(*) FROM game_events")[0][0], store.count_events(gid))
        self.assertEqual(self.server_totals(self.server_game()), ctrl.score(gid)["teams"])

    def test_a_wrong_key_is_refused_and_nothing_moves(self) -> None:
        cfg, store, ctrl = self.controller()
        self.play(ctrl)
        client = SyncClient(cfg, store, api_key="B" * 43)
        self.assertFalse(client.run_once())
        self.assertEqual(client.last_error, "invalid_api_key")
        self.assertEqual(self.db.fetch("SELECT count(*) FROM games")[0][0], 0)


if __name__ == "__main__":
    unittest.main()
