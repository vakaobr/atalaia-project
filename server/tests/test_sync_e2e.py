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
controller that was offline catches up. And the field's chrono registry: a
marshal's key, rotated (a lost phone) between two series, the replica and the
signed readings reach the site server, which verifies every one with the key
of its period and stores the record exactly as the controller had it.

This runs in the site server's test image (``python3 tools/docker_server.py
test tests.test_sync_e2e``): the image has the controller and simulator
packages and the core library (decision P4R16).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import tempfile
import threading
import time
import unittest
import uuid
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

    def test_the_chrono_registry_reaches_the_site_server(self) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        from atalaia_controller import chrono

        cfg, store, ctrl = self.controller()
        replica = "8a1f0c2e-7b3d-4c5e-8f9a-0b1c2d3e4f50"
        store.put_replica({"replica_id": replica, "owner_player_id": "p-abcdefghijkl", "type": "dmr",
                           "class": "dmr", "make_model": "SR-25"}, 1792000000.0)
        now = time.time()

        def phone() -> tuple[Ed25519PrivateKey, bytes]:
            key = Ed25519PrivateKey.generate()
            return key, key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)

        def series(key: Ed25519PrivateKey, at: float, n: int = 3) -> list[str]:
            sid, out = str(uuid.uuid4()), []
            for i in range(n):
                v = 100.0 + i
                rec = {"reading_id": str(uuid.uuid4()), "replica_id": replica, "player_id": "p-abcdefghijkl",
                       "type": "checkin", "velocity_mps": v, "bb_weight_g": 0.25,
                       "energy_j": chrono.round_half_away(chrono.energy_j(0.25, v), 3), "chrono_id": "c-1",
                       "marshal_id": "m-ana", "marshal_name": "Ana", "field_id": "campo",
                       "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))}
                rec["signature"] = base64.b64encode(key.sign(chrono.canonical(rec))).decode()
                store.add_reading(rec, sid, "pass", at + 1)
                out.append(rec["reading_id"])
            return out

        first, first_pub = phone()
        store.put_marshal("m-ana", "Ana", first_pub, None, now - 3600)
        before = series(first, now - 1800)
        client = SyncClient(cfg, store)
        self.assertTrue(client.run_once(), client.last_error)
        second, second_pub = phone()  # a lost phone: a new key, the old one keeps its period
        store.put_marshal("m-ana", "Ana", second_pub, None, now - 600)
        after = series(second, now - 300)
        self.assertTrue(client.run_once(), client.last_error)
        self.assertEqual(client.refused_readings, 0)

        rows = self.db.fetch("SELECT r.reading_id, r.record_json, k.public_key FROM chrono_readings r "
                             "JOIN marshal_keys k ON k.id = r.marshal_key")
        self.assertEqual({str(r["reading_id"]) for r in rows}, set(before + after))
        stored = {r["reading_id"]: r["record"] for r in store.readings(replica_id=replica)}
        for r in rows:
            self.assertEqual(json.loads(r["record_json"]), stored[str(r["reading_id"])])
            chrono.parse(r["record_json"], bytes(r["public_key"]))
            self.assertEqual(bytes(r["public_key"]), first_pub if str(r["reading_id"]) in before else second_pub)
        keys = self.db.fetch("SELECT public_key, valid_until IS NULL AS current FROM marshal_keys ORDER BY valid_from")
        self.assertEqual([(bytes(k[0]), k[1]) for k in keys], [(first_pub, False), (second_pub, True)])
        self.assertEqual(tuple(self.db.fetch("SELECT replica_type, make_model FROM replicas")[0]), ("dmr", "SR-25"))
        self.assertEqual(self.db.fetch("SELECT count(*) FROM chrono_rejects")[0][0], 0)
        # Everything again: duplicates only.
        store.reset_sync_state()
        self.assertTrue(SyncClient(cfg, store).run_once())
        self.assertEqual(self.db.fetch("SELECT count(*) FROM chrono_readings")[0][0], 6)

    def test_a_wrong_key_is_refused_and_nothing_moves(self) -> None:
        cfg, store, ctrl = self.controller()
        self.play(ctrl)
        client = SyncClient(cfg, store, api_key="B" * 43)
        self.assertFalse(client.run_once())
        self.assertEqual(client.last_error, "invalid_api_key")
        self.assertEqual(self.db.fetch("SELECT count(*) FROM games")[0][0], 0)


if __name__ == "__main__":
    unittest.main()
