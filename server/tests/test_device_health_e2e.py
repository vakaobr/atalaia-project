# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""End to end: the controller's node health events reach the site server's device health.

The real controller engine (``atalaia_controller.engine.Controller``, its own
SQLite store, a clock the test moves) runs a Domination game with two boxes
whose HELLO and STATE packets go in through the engine's radio receive path,
as the USB modem would deliver them: box "norte-1" keeps talking, box
"sul-2" reports 15 % and then falls silent. The controller logs node.online
for both, battery.low for "sul-2" (from its STATE level, since the box's own
event never came) and node.offline once "sul-2" has been silent for
``[health] node_offline_s``. Its sync client pushes everything to the site
server (uvicorn on 127.0.0.1, the test PostgreSQL), and a user with the
``gm`` role, logged in with TOTP, reads the field's device health
(decisions S19-9, FU1-1 to FU1-5).

    python3 tools/docker_server.py test tests.test_device_health_e2e
"""

from __future__ import annotations

import logging
import os
import tempfile
import unittest

from atalaia_controller.config import Config
from atalaia_controller.engine import Controller
from atalaia_controller.modem_framing import RxPacket
from atalaia_controller.store import Store
from atalaia_controller.sync_client import SyncClient
from atalaia_server import sync
from atalaia_sim.packet import Header, header_encode, hello_encode, state_encode, vf_make
from atalaia_sim.protocol import MESSAGE_TYPES

from .base import TempDatabase
from . import test_remote_gm_e2e as remote  # its class not in this module's namespace: not run twice
from .test_sync_e2e import CORE, DOMINATION, REPO, SiteServer

logging.getLogger("atalaia.sync").setLevel(logging.CRITICAL)
HEALTH = ("node.online", "node.offline", "battery.low")


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class DeviceHealthEndToEndTests(unittest.TestCase):
    db: TempDatabase
    # A gm's two-step login and the HTTP helper, as in the remote GM's end-to-end test.
    api = remote.RemoteGmEndToEndTests.api
    gm = remote.RemoteGmEndToEndTests.gm

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
        self.seq = 0

    def tearDown(self) -> None:
        self.site.__exit__(None, None, None)
        self.db.fetch("TRUNCATE fields, users RESTART IDENTITY CASCADE")
        self.tmp.cleanup()

    def rx(self, ctrl: Controller, gid: int, node: int, msg_type: str, payload: bytes) -> None:
        """A packet the modem heard and authenticated, as its RX frame reaches the engine."""
        self.seq += 1
        header = Header(vf_make(1, 0, False, True), gid, node, self.seq, 2, MESSAGE_TYPES[msg_type])
        ctrl._on_rx(RxPacket(header, header_encode(header), payload, -80, 6, 1))

    def test_offline_and_low_battery_reach_device_health(self) -> None:
        cfg = Config(db_path=os.path.join(self.tmp.name, "controller.db"), mqtt_enabled=False,
                     modes_dirs=[str(REPO / "modes")], sync_enabled=True, sync_url=self.site.url,
                     sync_api_key=self.key, sync_timeout_s=5.0)
        cfg.validate()
        self.assertEqual((cfg.health_node_offline_s, cfg.health_battery_low_pct), (120.0, 20))
        store = Store(cfg.db_path)
        self.addCleanup(store.close)
        clock = Clock()
        ctrl = Controller(cfg, store, core=CORE, clock=clock)
        self.addCleanup(ctrl.stop)
        gid = ctrl.create_game({"name": "Domingo", "mode_id": DOMINATION, "teams": ["red", "blue"],
                                "assignments": {"3": "zone", "4": "zone"}})["id"]
        ctrl.start_game(gid, force=True)
        for node, name, battery in ((3, "norte-1", 80), (4, "sul-2", 15)):
            self.rx(ctrl, gid, node, "HELLO", hello_encode({
                "node_name": name, "platform": 1, "fw_version": "0.9.0", "core_version": "0.9.0", "tier": 0,
                "capabilities": [], "transports": 1, "battery_pct": battery, "epoch": 1}))
        for second in range(1, 200):
            clock.t += 1
            if second % 15 == 0:
                self.rx(ctrl, gid, 3, "STATE", state_encode({"owner_team": 0, "phase": 1, "game_time_ms": 0,
                                                            "counters": {}, "battery_pct": 80, "epoch": 1}))
            if second == 10:
                self.rx(ctrl, gid, 4, "STATE", state_encode({"owner_team": 0, "phase": 1, "game_time_ms": 0,
                                                            "counters": {}, "battery_pct": 15, "epoch": 1}))
            ctrl.tick()
        logged = [(e["node"], e["type"]) for e in store.events(gid) if e["type"] in HEALTH]
        self.assertEqual(sorted(logged), [(3, "node.online"), (4, "battery.low"), (4, "node.offline"),
                                          (4, "node.online")])

        client = SyncClient(cfg, store)
        self.assertTrue(client.run_once(), client.last_error)
        token = self.gm()
        status, out = self.api("GET", f"/api/v1/fields/{self.field}/devices", token=token)
        self.assertEqual(status, 200, out)
        devices = {d["name"]: d for d in out["devices"]}
        self.assertEqual(set(devices), {"norte-1", "sul-2"})
        norte, sul = devices["norte-1"], devices["sul-2"]
        self.assertEqual((norte["offline"], norte["battery_low"], norte["battery_pct"]), (False, False, 80))
        self.assertEqual(norte["events"], {"node.online": 1})
        self.assertEqual((sul["offline"], sul["battery_low"], sul["battery_pct"]), (True, True, 15))
        self.assertEqual(sul["events"], {"node.online": 1, "node.offline": 1, "battery.low": 1})
        self.assertEqual((sul["game"]["game_id"], sul["game"]["state"]), (gid, "running"))

        # The box comes back: online again after the next sync.
        self.rx(ctrl, gid, 4, "STATE", state_encode({"owner_team": 0, "phase": 1, "game_time_ms": 0,
                                                    "counters": {}, "battery_pct": 15, "epoch": 1}))
        clock.t += 1
        ctrl.tick()
        self.assertTrue(client.run_once(), client.last_error)
        status, out = self.api("GET", f"/api/v1/fields/{self.field}/devices", token=token)
        sul = {d["name"]: d for d in out["devices"]}["sul-2"]
        self.assertEqual((sul["offline"], sul["events"]["node.online"]), (False, 2))


if __name__ == "__main__":
    unittest.main()
