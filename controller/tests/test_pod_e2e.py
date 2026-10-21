# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A phone's I/O pod on the field's radio: the controller, its C host modem and a C host pod.

    cd controller && ATALAIA_MODEM_HOST=... ATALAIA_POD_HOST=... python -m unittest discover -s tests

The host pod runs the I/O pod firmware's own proxy and radio code
(main/pod/pod.c with main/modem/modem.c and mbedtls AES-CCM); this test
plays the phone on the pod's USB link with the capability proxy frames
(protocol/capability-proxy.md), as the app's radio link does
(app/lib/radio/pod_radio_link.dart). The pod and the controller's modem
share one UDP 'air': a node that joined with a join payload is heard by the
controller through the pod, its HELLO, events and STATE are taken and
acknowledged over the radio, and the controller's commands reach it.
"""

from __future__ import annotations

import tempfile
import unittest

from fastapi.testclient import TestClient

from support import CORE, MODEM_HOST, POD_HOST, AirHub, HostModem, PodHost, config, wait_for
from atalaia_sim import capability_proxy as cp
from atalaia_sim import join as join_codec
from atalaia_sim.codec import encode_event
from atalaia_sim.packet import (Header, ack_decode, cmd_decode, header_decode, header_encode,
                                hello_encode, state_encode, time_decode, vf_make)
from atalaia_sim.protocol import MESSAGE_TYPES
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.radio_modem import RadioModem
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
JOIN_KEY = bytes(range(100, 132))


@unittest.skipUnless(MODEM_HOST and POD_HOST, "host modem or host pod not built")
class PodOnTheFieldRadio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = AirHub()
        self.host = HostModem(hub=self.hub)
        self.hub.add(self.host.air_port)
        self.modem = RadioModem(self.host.url, ping_interval=0.2, retry_interval=0.2)
        self.modem.start()
        self.assertTrue(self.modem.wait_up(5))
        self.cfg = config(self.tmp.name)
        self.store = Store(self.cfg.db_path)
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=JOIN_KEY)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))
        self.ctrl.start()
        self.pod = PodHost(self.hub)
        self.phone = self.pod.phone()
        self.seq = 0

    def tearDown(self):
        self.phone.close()
        self.pod.close()
        self.client.close()
        self.ctrl.stop()
        self.modem.stop()
        self.store.close()
        self.host.close()
        self.hub.close()
        self.tmp.cleanup()

    # ---- the phone's side ---------------------------------------------------------

    def joined(self) -> dict:
        r = self.client.post("/api/v1/games", headers=GM, json={
            "name": "pod", "mode_id": "org.atalaia.domination", "teams": ["red", "blue"]})
        self.assertEqual(r.status_code, 201, r.text)
        self.gid = r.json()["id"]
        r = self.client.post("/api/v1/join", headers=GM, json={"role": "zone"})
        self.assertEqual(r.status_code, 200, r.text)
        j = join_codec.decode(join_codec.from_text(r.json()["text"]), JOIN_KEY)
        self.assertEqual(j["node_id"], r.json()["node_id"])
        return j

    def configure(self, j: dict, epoch: int = 1) -> None:
        mark = len(self.phone.frames)
        self.phone.send(cp.RADIO_CMD, cp.radio_configure(j["game_id"], j["node_id"], epoch,
                                                         j["max_hops"], j["channel_hz"], j["game_key"]))
        status = self.phone.wait(cp.RADIO_STATUS, start=mark)
        self.assertIsNotNone(status)
        self.assertIn('"configured":true', status.decode())

    def tx(self, j: dict, msg_type: str, payload: bytes, prio: int = 1, ack: bool = True) -> int:
        """A packet from the phone's node through the pod; returns its seq once the radio sent it."""
        seq = self.seq
        self.seq += 1
        hdr = Header(vf_make(1, prio, ack, False), j["game_id"], j["node_id"], seq, j["max_hops"],
                     MESSAGE_TYPES[msg_type])
        mark = len(self.phone.frames)
        self.phone.send(cp.RADIO_TX, cp.radio_tx(header_encode(hdr), payload))
        result = self.phone.wait(cp.RADIO_TX_ACK, lambda p: p[:2] == seq.to_bytes(2, "big"), start=mark)
        self.assertIsNotNone(result, f"no RADIO_TX_ACK for seq {seq}")
        self.assertEqual(result[2], 0, f"RADIO_TX_ACK status {result[2]}")
        return seq

    def received(self, msg_type: str, match=None, timeout: float = 5.0):
        """The plaintext payload of a packet the pod heard (RADIO_RX) of msg_type."""
        def ok(p: bytes) -> bool:
            if header_decode(p[:9]).type != MESSAGE_TYPES[msg_type]:
                return False
            return match is None or match(p[9:-4])
        frame = self.phone.wait(cp.RADIO_RX, ok, timeout=timeout)
        return None if frame is None else frame[9:-4]

    def acked(self, j: dict, seq: int) -> bool:
        def covers(pl: bytes) -> bool:
            a = ack_decode(pl)
            if a["ack_node"] != j["node_id"]:
                return False
            if seq <= a["ack_seq"] and a["ack_seq"] != 0xFFFF:
                return True
            bit = seq - a["ack_seq"] - 1
            bitmap = a.get("ack_bitmap", b"")
            return 0 <= bit < 8 * len(bitmap) and bitmap[bit // 8] >> (bit % 8) & 1 == 1
        return self.received("ACK", covers) is not None

    def node(self, node_id: int) -> dict:
        for n in self.client.get("/api/v1/nodes", headers=READ).json():
            if n["node_id"] == node_id:
                return n
        return {}

    # ---- the tests --------------------------------------------------------------------

    def test_hello_events_state_and_commands(self):
        j = self.joined()
        nid = j["node_id"]
        # The phone's first frame on a new link: the pod's IDENT, with its radio.
        self.phone.send(cp.RADIO_CMD, bytes([cp.OP_IDENT]))
        ident = cp.decode_ident(self.phone.wait(cp.IDENT))
        self.assertTrue(ident["has_radio"])
        self.assertIn({"id": "btn.1", "type": "button"}, ident["capabilities"])
        self.configure(j)

        # HELLO (critical, ACK requested): the controller registers the phone's node.
        seq = self.tx(j, "HELLO", hello_encode({
            "node_name": f"phone-{nid}", "platform": 3, "fw_version": "app-0.3.0",
            "core_version": "0.2.0", "tier": 0, "capabilities": [], "transports": 0b011,
            "epoch": 1}), prio=2)
        self.assertTrue(wait_for(lambda: self.node(nid).get("fw_version") == "app-0.3.0", 5))
        self.assertEqual(self.node(nid)["platform"], 3)
        self.assertTrue(self.acked(j, seq))

        # The GM starts the game: the phone hears the start (a CMD, and TIME says running).
        self.assertEqual(self.client.post(f"/api/v1/games/{self.gid}/start", headers=GM).status_code, 200)
        self.assertIsNotNone(self.received("CMD", lambda pl: cmd_decode(pl)["cmd"] == 0))
        self.assertIsNotNone(self.received("TIME", lambda pl: time_decode(pl)["game_state"] == 1))

        # A capture by red, from the phone's mode: logged once, acknowledged over the radio.
        payload = encode_event({"node": nid, "seq": 1, "t": 4000, "type": "zone.captured",
                                "team": 1, "prio": "normal", "data": {"team": "red"}})
        seq = self.tx(j, "EVENT", payload)
        self.assertTrue(self.acked(j, seq))
        log = self.client.get(f"/api/v1/games/{self.gid}/log", headers=READ).json()
        # (and the controller's own node.online about the phone's node, decision FU1-1)
        self.assertEqual([e["type"] for e in log if e["node"] == nid], ["node.online", "zone.captured"])
        # The same event again (as the Wi-Fi link would resend it): no second entry.
        self.assertTrue(self.acked(j, self.tx(j, "EVENT", payload)))
        log = self.client.get(f"/api/v1/games/{self.gid}/log", headers=READ).json()
        self.assertEqual(len([e for e in log if e["node"] == nid and e["type"] == "zone.captured"]), 1)

        # STATE with red's counter: the controller's score follows (merged by maximum).
        self.tx(j, "STATE", state_encode({"owner_team": 1, "phase": 1, "game_time_ms": 9000,
                                          "counters": {1: 7}, "epoch": 1}), prio=0, ack=False)
        self.assertTrue(wait_for(lambda: self.client.get(
            f"/api/v1/games/{self.gid}/score", headers=READ).json()["teams"]["red"] >= 7, 5))

        # A GM command to this node only reaches it.
        r = self.client.post(f"/api/v1/nodes/{nid}/cmd", headers=GM,
                             json={"cmd": "message", "params": {"text": "hi"}})
        self.assertIn(r.status_code, (200, 202), r.text)
        msg = self.received("CMD", lambda pl: cmd_decode(pl)["cmd"] == 5)
        self.assertIsNotNone(msg)
        self.assertEqual(cmd_decode(msg).get("dest"), nid)

    def test_the_key_goes_with_the_phone(self):
        j = self.joined()
        self.phone.send(cp.RADIO_CMD, bytes([cp.OP_IDENT]))
        self.assertIsNotNone(self.phone.wait(cp.IDENT))
        self.configure(j)
        self.assertTrue(self.pod.status()["radio_configured"])
        # The phone leaves the USB link: the pod forgets the game key.
        self.phone.close()
        self.assertTrue(wait_for(lambda: not self.pod.status()["radio_configured"], 5))
        # A phone that links again must configure again before it can send.
        self.phone = self.pod.phone()
        self.phone.send(cp.RADIO_CMD, bytes([cp.OP_IDENT]))
        self.assertIsNotNone(self.phone.wait(cp.IDENT))
        hdr = Header(vf_make(1, 1, True, False), j["game_id"], j["node_id"], 0, j["max_hops"],
                     MESSAGE_TYPES["HELLO"])
        self.phone.send(cp.RADIO_TX, cp.radio_tx(header_encode(hdr), b"\xa0"))
        result = self.phone.wait(cp.RADIO_TX_ACK)
        self.assertIsNotNone(result)
        self.assertEqual(result[2], 3)  # not_configured
        # Configured again, with the next epoch (the phone stores it before every new
        # link, so no nonce repeats under the game key), it sends again.
        self.configure(j, epoch=2)
        self.tx(j, "HELLO", hello_encode({"node_name": "p", "platform": 3, "fw_version": "x",
                                          "core_version": "0.2.0", "tier": 0, "capabilities": [],
                                          "transports": 3, "epoch": 2}), prio=2)


if __name__ == "__main__":
    unittest.main()
