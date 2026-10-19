# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""WS /api/v1/sync/stream on PostgreSQL 16: the sync's four bodies on one socket (protocol/sync.md).

Starlette's TestClient runs the app (and its lifespan) in a thread of its
own, so these are plain synchronous tests on a database of their own.
"""

from __future__ import annotations

import unittest
import warnings

with warnings.catch_warnings():  # Starlette 1.x would rather have httpx2; httpx is what the tests pin
    warnings.simplefilter("ignore")
    from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from atalaia_server import sync
from atalaia_server.app import create_app
from atalaia_server.config import Settings

from .base import SECRET_KEY, TempDatabase
from .test_sync import META, adjustment, envelope, event


class StreamTests(unittest.TestCase):
    db: TempDatabase

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = TempDatabase()
        cls.db.create()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.db.drop()

    def setUp(self) -> None:
        self.db.fetch("TRUNCATE fields, field_api_keys, games, controllers RESTART IDENTITY CASCADE")
        field = self.db.fetch("INSERT INTO fields (name, slug) VALUES ('Campo', 'campo') RETURNING id")[0][0]
        self.key = sync.new_key()
        self.key_id = self.db.fetch("INSERT INTO field_api_keys (field_id, key_sha256) VALUES ($1, $2) RETURNING id",
                                    field, sync.key_hash(self.key))[0][0]
        app = create_app(Settings(database_url=self.db.url, secret_key=SECRET_KEY, purge_hour=None))
        self.client = TestClient(app, base_url="https://server.test")
        self.client.__enter__()

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)

    def connect(self, key: str):
        return self.client.websocket_connect("/api/v1/sync/stream", headers={"Authorization": f"Bearer {key}"})

    def test_the_four_kinds_and_a_ping(self) -> None:
        with self.connect(self.key) as ws:
            ws.send_json({"type": "ping"})
            self.assertEqual(ws.receive_json(), {"type": "pong"})
            ws.send_json({"type": "games", **envelope(meta=META)})
            self.assertEqual(ws.receive_json()["type"], "games.ack")
            batch = {"type": "events", **envelope(after_id=0, events=[event(1), adjustment(2, "red", -20)])}
            ws.send_json(batch)
            self.assertEqual(ws.receive_json(), {"type": "events.ack", "acked_id": 2, "inserted": 2, "duplicates": 0})
            ws.send_json(batch)  # a replay over the socket is as harmless as over HTTP
            self.assertEqual(ws.receive_json()["duplicates"], 2)
            ws.send_json({"type": "scores", **envelope(counters={"node-3": {"red": 50}})})
            self.assertEqual(ws.receive_json()["totals"], {"red": 30, "blue": 0})
            ws.send_json({"type": "nodes", **envelope(nodes=[{"node_id": 3, "name": "node-3", "role": "zone",
                                                              "last_seen": 1792000000.0}])})
            self.assertEqual(ws.receive_json(), {"type": "nodes.ack", "nodes": 1})
        self.assertEqual(self.db.fetch("SELECT count(*) FROM game_events")[0][0], 2)

    def test_errors_keep_the_socket_open(self) -> None:
        with self.connect(self.key) as ws:
            ws.send_text("{nope")
            self.assertEqual(ws.receive_json()["error"], "not_json")
            ws.send_json({"type": "launch"})
            self.assertEqual(ws.receive_json()["error"], "bad_type")
            ws.send_json({"type": "events", **envelope(after_id=0, events=[event(1)])})
            self.assertEqual(ws.receive_json(), {"type": "error", "detail": "game_not_found"})
            ws.send_json({"type": "games", **envelope(meta={**META, "game_key": "00"})})
            self.assertEqual(ws.receive_json(), {"type": "error", "detail": "invalid_body", "error": "unknown_field",
                                                 "path": "meta.game_key"})
            ws.send_json({"type": "ping"})
            self.assertEqual(ws.receive_json(), {"type": "pong"})

    def test_a_wrong_or_revoked_key_is_refused(self) -> None:
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.connect("A" * 43) as ws:
                ws.receive_json()
        self.assertEqual(caught.exception.code, 4401)
        with self.connect(self.key) as ws:
            self.db.fetch("UPDATE field_api_keys SET revoked_at = now() WHERE id = $1", self.key_id)
            ws.send_json({"type": "games", **envelope(meta=META)})
            with self.assertRaises(WebSocketDisconnect) as caught:
                ws.receive_json()
            self.assertEqual(caught.exception.code, 4401)
        self.assertEqual(self.db.fetch("SELECT count(*) FROM games")[0][0], 0)


if __name__ == "__main__":
    unittest.main()
