# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""End to end: a remote GM on the real site server acts on the real field controller (plan phase 19; P4R12).

The site server runs under uvicorn on 127.0.0.1 (its WebSocket through
wsproto, as in the image) on the test PostgreSQL; the controller's engine
runs a Domination game on its own SQLite store with ``[sync] remote_gm =
true``, and its ``RemoteGm`` thread opens the stream with the standard
library's sockets (``ws_client.py``): the controller opens the connection,
the site server never connects to it. A user with the ``gm`` role on the field
logs in with TOTP, sees the live game and starts, pauses, resumes and ends it;
both sides log every command. A controller with a wrong key is refused.

    python3 tools/docker_server.py test tests.test_remote_gm_e2e
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from typing import Any

from atalaia_server import passwords, sync, totp

from atalaia_controller.config import Config
from atalaia_controller.engine import Controller
from atalaia_controller.remote_gm import RemoteGm
from atalaia_controller.store import Store

from .base import PASSWORD, TempDatabase
from .test_sync_e2e import CORE, DOMINATION, REPO, SiteServer

logging.getLogger("atalaia.remote_gm").setLevel(logging.CRITICAL)
CONTROLLER_ID = "0192f3a4-5b6c-7d8e-9f01-23456789abcd"


def wait(predicate: Any, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


class RemoteGmEndToEndTests(unittest.TestCase):
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
        self.db.fetch("TRUNCATE fields, users RESTART IDENTITY CASCADE")
        self.tmp.cleanup()

    def api(self, method: str, path: str, body: Any = None, token: str = "") -> tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
        req = urllib.request.Request(self.site.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"null")

    def gm(self, name: str = "gm-norte") -> str:
        """An account with TOTP and the gm role on the field; its access token from a real two-step login."""
        secret = totp.new_secret()
        digest = asyncio.run(passwords.hash_password(PASSWORD))
        sealed = self.site.app.state.seed_box.seal(secret)
        user = self.db.fetch("INSERT INTO users (username, password_hash, totp_enabled, totp_secret_enc) "
                             "VALUES ($1, $2, true, $3) RETURNING id", name, digest, sealed)[0][0]
        self.db.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, 5)", user, self.field)
        status, step = self.api("POST", "/api/v1/auth/login", {"username": name, "password": PASSWORD})
        self.assertEqual(status, 200, step)
        status, out = self.api("POST", "/api/v1/auth/login/totp", {"totp_session": step["totp_session"],
                                                                   "code": totp.code_at(secret, time.time())})
        self.assertEqual(status, 200, out)
        return out["access_token"]

    def controller(self, key: str) -> tuple[Store, Controller, RemoteGm]:
        cfg = Config(db_path=os.path.join(self.tmp.name, "controller.db"), mqtt_enabled=False,
                     modes_dirs=[str(REPO / "modes")], sync_enabled=True, sync_url=self.site.url,
                     sync_api_key=key, sync_timeout_s=5.0, sync_remote_gm=True)
        cfg.validate()
        store = Store(cfg.db_path)
        ctrl = Controller(cfg, store, core=CORE)
        remote = RemoteGm(cfg, store, ctrl, api_key=key, controller_id=lambda: CONTROLLER_ID)
        ctrl.add_listener(remote.on_controller_message)
        remote.start()
        self.addCleanup(store.close)
        self.addCleanup(ctrl.stop)
        self.addCleanup(remote.stop)
        return store, ctrl, remote

    def test_a_remote_gm_runs_the_game(self) -> None:
        store, ctrl, remote = self.controller(self.key)
        gid = ctrl.create_game({"name": "Domingo", "mode_id": DOMINATION, "teams": ["red", "blue"],
                                "assignments": {"3": "zone"}})["id"]
        game = {"game_id": gid, "game_seed": store.game(gid)["game_seed"]}
        token = self.gm()
        path = f"/api/v1/fields/{self.field}/remote-gm"

        def live_state() -> Any:
            status, out = self.api("GET", path, token=token)
            links = out["controllers"] if status == 200 else []
            return links[0]["live"]["state"] if links and links[0]["live"] else None

        self.assertTrue(wait(lambda: live_state() == "ready"), self.api("GET", path, token=token))
        for command, params, state in (("start", {}, "running"), ("pause", {"reason": "medic"}, "paused"),
                                       ("resume", {}, "running"), ("end", {"reason": "time"}, "ended")):
            with self.subTest(command):
                status, out = self.api("POST", f"{path}/commands", {"game": game, "command": command,
                                                                    "params": params}, token=token)
                self.assertEqual((status, out["code"]), (200, "done"), out)
                self.assertEqual(store.game(gid)["state"], state)
        # Something the controller refuses: the game has ended.
        status, out = self.api("POST", f"{path}/commands", {"game": game, "command": "start"}, token=token)
        self.assertEqual((status, out["detail"], out["code"]), (409, "refused_by_controller", "not_live"))
        # Something not in the list never leaves the site server.
        status, out = self.api("POST", f"{path}/commands", {"game": game, "command": "reboot"}, token=token)
        self.assertEqual((status, out["error"]), (400, "not_allowed"))
        # Both sides logged every command.
        log = store.remote_commands()
        self.assertEqual([(e["command"], e["result"], e["username"]) for e in reversed(log)],
                         [("start", "done", "gm-norte"), ("pause", "done", "gm-norte"), ("resume", "done", "gm-norte"),
                          ("end", "done", "gm-norte"), ("start", "not_live", "gm-norte")])
        rows = self.db.fetch("SELECT action, details->>'command', details->>'result' FROM audit_log "
                             "WHERE action LIKE 'remote_gm%' ORDER BY id")
        self.assertEqual([tuple(r) for r in rows],
                         [("remote_gm_command", "start", "done"), ("remote_gm_command", "pause", "done"),
                          ("remote_gm_command", "resume", "done"), ("remote_gm_command", "end", "done"),
                          ("remote_gm_command", "start", "not_live"), ("remote_gm_denied", None, None)])
        self.assertEqual([e["data"] for e in store.events(gid) if e["type"] == "game.pause"], [{"reason": "medic"}])
        self.assertTrue(remote.status()["connected"])
        # The live view follows the controller: no live game once it ended.
        self.assertTrue(wait(lambda: self.api("GET", path, token=token)[1]["controllers"][0]["live"] is None))

    def test_a_wrong_key_is_refused(self) -> None:
        _, _, remote = self.controller(sync.new_key())
        self.assertTrue(wait(lambda: remote.last_error == "the site server refused the API key"), remote.last_error)
        self.assertFalse(remote.connected)


if __name__ == "__main__":
    unittest.main()
