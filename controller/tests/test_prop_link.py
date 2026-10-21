# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""An Android prop on the field's Wi-Fi (decision PD12, protocol/prop-link.md): WS /api/v1/prop.

The prop proves it holds the game key, then sends HELLO, STATE and EVENT fields as JSON; the
controller encodes them with the radio's codecs and hands them to the same FieldController a
box's packets reach, so the node list, the score merge and the log are the radio's. TIME
beacons and commands reach the prop as JSON.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import base64
import unittest

from p3support import GM, READ, P3Case
from atalaia_controller import prop_link
from starlette.websockets import WebSocketDisconnect


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class PropLinkTests(P3Case):
    def setUp(self):
        super().setUp()
        self.game = self.new_game(assignments={"4": "zone", "7": "zone"})
        self.gid = self.game["id"]
        self.key = self.ctrl.game_key(self.gid)

    def connect(self, node_id: int = 7, key: bytes | None = None, game_id: int | None = None):
        ws = self.client.websocket_connect("/api/v1/prop").__enter__()
        challenge = ws.receive_json()
        self.assertEqual(challenge["type"], "challenge")
        nonce = unb64(challenge["nonce"])
        gid = self.gid if game_id is None else game_id
        proof = prop_link.proof(key or self.key, nonce, gid, node_id)
        ws.send_json({"type": "auth", "game_id": gid, "node_id": node_id, "proof": b64(proof)})
        return ws

    def test_a_prop_plays_over_wifi(self):
        ws = self.connect()
        try:
            welcome = ws.receive_json()
            self.assertEqual((welcome["type"], welcome["node_id"], welcome["time"]["state"]),
                             ("welcome", 7, "waiting"))
            ws.send_json({"type": "hello", "node_name": "telemovel-7", "fw_version": "0.3.0",
                          "core_version": "0.2.0", "tier": 0, "capabilities": [0, 2], "battery_pct": 81})
            ws.send_json({"type": "state", "owner_team": 1, "phase": 1, "game_time_ms": 4000,
                          "counters": {"1": 12}, "battery_pct": 80})
            ws.send_json({"type": "event", "event": {"seq": 1, "t": 4000, "type": "zone.captured", "team": 1,
                                                     "data": {"team": "red"}}})
            ack = ws.receive_json()
            self.assertEqual((ack["type"], ack["seq"]), ("ack", 1))
            # The same event again (a resend after a reconnect) is acknowledged and logged once.
            ws.send_json({"type": "event", "event": {"seq": 1, "t": 4000, "type": "zone.captured", "team": 1,
                                                     "data": {"team": "red"}}})
            self.assertEqual(ws.receive_json()["type"], "ack")
            nodes = {n["node_id"]: n for n in self.client.get("/api/v1/nodes", headers=READ).json()}
            self.assertEqual((nodes[7]["name"], nodes[7]["platform"], nodes[7]["owner"]), ("telemovel-7", 3, "red"))
            self.assertEqual(self.client.get(f"/api/v1/games/{self.gid}/score", headers=READ).json()["teams"]["red"], 12)
            self.assertEqual([(e["node"], e["type"]) for e in self.events(self.gid, "zone.captured")],
                             [(7, "zone.captured")])
            # The GM starts the game: the prop gets the command and the TIME beacon, as a box would.
            self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
            got = [ws.receive_json(), ws.receive_json()]
            self.assertEqual({m["type"] for m in got}, {"cmd", "time"})
            cmd = next(m for m in got if m["type"] == "cmd")
            self.assertEqual(cmd["cmd"], "start")
            self.assertEqual(next(m for m in got if m["type"] == "time")["state"], "running")
            # A message to this node only, then node.tamper from the kiosk check.
            r = self.client.post("/api/v1/nodes/7/cmd", headers=GM, json={"cmd": "message", "params": {"text": "olá"}})
            self.assertEqual(r.status_code, 202, r.text)  # no radio modem: the Wi-Fi link took it
            m = ws.receive_json()
            self.assertEqual((m["cmd"], m["params"], m["dest"]), ("message", {"text": "olá"}, 7))
            ws.send_json({"type": "event", "event": {"seq": 1, "t": 9000, "type": "node.tamper", "prio": "critical",
                                                     "data": {"reason": "kiosk_broken"}}})
            self.assertEqual(ws.receive_json()["type"], "ack")
            tamper = self.events(self.gid, "node.tamper")
            self.assertEqual((tamper[0]["node"], tamper[0]["prio"], tamper[0]["data"]),
                             (7, "critical", {"reason": "kiosk_broken"}))
            # A bad event is refused, not logged.
            ws.send_json({"type": "event", "event": {"seq": 2, "t": 9100, "type": "zone.captured",
                                                     "data": {"no_such_field": 1}}})
            self.assertEqual(ws.receive_json()["type"], "error")
        finally:
            ws.__exit__(None, None, None)

    def test_a_command_to_another_node_does_not_reach_this_prop(self):
        ws = self.connect()
        try:
            ws.receive_json()
            self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM, json={"force": True})
            ws.receive_json()
            ws.receive_json()
            self.client.post("/api/v1/nodes/4/cmd", headers=GM, json={"cmd": "reset"})
            ws.send_json({"type": "ping"})
            self.assertEqual(ws.receive_json(), {"type": "pong"})
        finally:
            ws.__exit__(None, None, None)

    def test_refused_without_the_game_key_or_an_assignment(self):
        for kw in ({"key": bytes(16)}, {"node_id": 9}, {"game_id": self.gid + 1 if self.gid < 65534 else 1},
                   {"node_id": self.ctrl.node_id or 65534}):
            with self.subTest(kw):
                ws = self.connect(**kw)
                try:
                    self.assertEqual(ws.receive_json(), {"type": "refused", "reason": "auth"})
                    with self.assertRaises(WebSocketDisconnect) as cm:
                        ws.receive_json()
                    self.assertEqual(cm.exception.code, 4401)
                finally:
                    ws.__exit__(None, None, None)

    def test_a_newer_link_replaces_the_old_one(self):
        old = self.connect()
        try:
            old.receive_json()
            new = self.connect()
            try:
                self.assertEqual(new.receive_json()["type"], "welcome")
                self.assertEqual(old.receive_json(), {"type": "replaced"})
                with self.assertRaises(WebSocketDisconnect) as cm:
                    old.receive_json()
                self.assertEqual(cm.exception.code, 4409)
                self.assertEqual(self.ctrl.prop_links.linked(), [7])
            finally:
                new.__exit__(None, None, None)
        finally:
            old.__exit__(None, None, None)

    def test_join_payload_for_a_prop_carries_the_ca(self):
        from atalaia_sim import join

        j = self.client.post("/api/v1/join", headers=GM, json={"role": "zone"}).json()
        payload = join.decode(bytes.fromhex(j["payload_hex"]), bytes.fromhex(self.ctrl.store.get_setting("join_key")))
        self.assertEqual(payload["ca_sha256"], self.bundle.tls.ca_sha256)
        self.assertIn("https://10.0.2.2:8443", payload["urls"])


if __name__ == "__main__":
    unittest.main()
