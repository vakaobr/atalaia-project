# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pairing a box by its code over the radio (protocol/adoption.md section 7, decisions AD-15 to AD-27).

First the controller's service against a box modelled in Python on the shared codec
(atalaia_sim.pair_frame, atalaia_sim.cpace), through a fake modem: the whole run, a
wrong code, a low-order point, replays, resends and timeouts, a DONE with a bad tag
or the wrong fingerprint, the channel it listens on, the API's tokens and records.
Then end to end on the firmware's own code: the C host box (main/box_pair.c,
main/adoption.c, main/box_lobby.c) unadopted with "--pair", the C host modem
carrying type 10 as FIELD_TX/RX, the real controller: the box's code read from its
log, typed into the API, the box adopted with this field's key and then announcing
itself in field frames; a wrong code first leaves it unadopted with a new code.
"""

from __future__ import annotations

import hmac
import os
import re
import tempfile
import unittest

from fastapi.testclient import TestClient

from support import CORE, AirHub, BoxHost, FakeModem, HostModem, config, wait_for
from atalaia_controller.api import Auth, create_app
from atalaia_controller.engine import Controller
from atalaia_controller.pairing import PAIR_CHANNEL_HZ, RESEND_MS, STEP_MS
from atalaia_controller.radio_modem import RadioModem
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import cpace, field_card
from atalaia_sim import pair_frame as pf

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
KEY = bytes(range(32))


class BoxModel:
    """A box as box_pair.c behaves, on the Python codec: OFFER, then REPLY and DONE."""

    def __init__(self, code: str, pair_id: bytes = b"\xb0" * 8, name: str = "porta-norte") -> None:
        self.code, self.pair_id, self.name = code, pair_id, name
        self.keys = None
        self.sid = None
        self.adopted: tuple | None = None

    def offer(self) -> bytes:
        return pf.encode({"kind": "offer", "pair_id": self.pair_id, "name": self.name, "tier": 0})

    def answer(self, frame: bytes) -> bytes | None:
        msg = pf.decode(frame)
        if msg["kind"] == "start":
            yb_secret = os.urandom(32)
            yb = cpace.scalar_mult(yb_secret, pf.generator(self.code, self.pair_id, msg["sid"]))
            k = cpace.scalar_mult_vfy(yb_secret, msg["point"])
            self.sid = msg["sid"]
            self.keys = pf.keys(pf.isk(msg["sid"], k, msg["point"], yb), msg["sid"])
            return pf.encode({"kind": "reply", "pair_id": self.pair_id, "sid": msg["sid"], "point": yb,
                              "tag": pf.tag_reply(self.keys)})
        if msg["kind"] == "key":
            assert hmac.compare_digest(pf.tag_key(self.keys), msg["tag"])
            key, name = pf.open_key(self.keys, msg["nonce"], self.pair_id, self.sid, msg["sealed"])
            self.adopted = (key, name, msg["nonce"])
            fp = pf.fingerprint_bytes(key)
            return pf.encode({"kind": "done", "pair_id": self.pair_id, "sid": self.sid, "result": "adopted",
                              "fingerprint": fp, "tag": pf.tag_done(self.keys, "adopted", fp)})
        return None


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = config(self.tmp.name)
        self.store = Store(self.cfg.db_path)
        self.addCleanup(self.store.close)
        self.modem = FakeModem()
        self.clock = Clock()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=KEY, clock=self.clock)
        from atalaia_controller.adoption import Adoption
        Adoption(self.ctrl)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))
        self.p = self.ctrl.pairing

    def hear(self, frame: bytes) -> None:
        self.modem.on_field_rx(frame, -70, 4)

    def advance(self, ms: int) -> None:
        self.clock.t += ms / 1000
        self.ctrl.tick()

    def offer(self, box: BoxModel) -> None:
        self.hear(box.offer())
        offers = self.client.get("/api/v1/adopt/pair", headers=GM).json()["offers"]
        self.assertEqual(offers[0]["name"], box.name)

    def test_a_whole_run(self) -> None:
        box = BoxModel("042137")
        self.offer(box)
        self.assertEqual(self.client.get("/api/v1/adopt/pair", headers=READ).status_code, 403)
        r = self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": box.pair_id.hex(), "code": "042 137"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["run"]["state"], "starting")
        start = self.modem.fields[-1]
        self.assertEqual(pf.decode(start)["kind"], "start")
        self.hear(box.answer(start))
        key = self.modem.fields[-1]
        self.assertEqual(pf.decode(key)["kind"], "key")
        self.hear(box.answer(key))
        status = self.client.get("/api/v1/adopt/pair", headers=GM).json()
        self.assertEqual((status["run"]["state"], status["run"]["result"]), ("done", "adopted"))
        self.assertEqual(status["offers"], [])  # an adopted box offers no more
        k, name, nonce = box.adopted
        self.assertEqual((k, name), (KEY, "Atalaia"))
        self.assertEqual(nonce[8:], b"\x00\x00\x01\x00\x00")  # boot 1, count 0: no RNG in it
        log = self.client.get("/api/v1/adopt", headers=GM).json()["log"]
        self.assertEqual((log[0]["method"], log[0]["result"], log[0]["box"]), ("radio", "adopted", "porta-norte"))
        self.assertNotIn(KEY.hex(), str(log))
        # Every run has its own sender id: two runs' KEY nonces differ in their pseudonym.
        box2 = BoxModel("111111", pair_id=b"\xb1" * 8, name="porta-sul")
        self.offer(box2)
        self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": box2.pair_id.hex(), "code": "111111"})
        self.hear(box2.answer(self.modem.fields[-1]))
        self.hear(box2.answer(self.modem.fields[-1]))
        self.assertNotEqual(box2.adopted[2][:8], nonce[:8])

    def test_a_wrong_code_never_sends_the_key(self) -> None:
        box = BoxModel("042138")  # the box shows another code than the GM types
        self.offer(box)
        self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": box.pair_id.hex(), "code": "042137"})
        self.hear(box.answer(self.modem.fields[-1]))
        status = self.p.status()
        self.assertEqual((status["run"]["state"], status["run"]["detail"]), ("failed", "wrong_code"))
        self.assertEqual([pf.decode(f)["kind"] for f in self.modem.fields], ["start"])  # no KEY
        self.assertEqual(self.client.get("/api/v1/adopt", headers=GM).json()["log"][0]["result"], "wrong_code")

    def test_low_order_point_and_replays(self) -> None:
        box = BoxModel("042137")
        self.offer(box)
        self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": box.pair_id.hex(), "code": "042137"})
        start = pf.decode(self.modem.fields[-1])
        reply = {"kind": "reply", "pair_id": box.pair_id, "sid": start["sid"], "point": bytes(32), "tag": bytes(16)}
        # Another run's sid first: ignored; then a low-order point: the run fails.
        self.hear(pf.encode(dict(reply, sid=bytes(16))))
        self.assertEqual(self.p.status()["run"]["state"], "starting")
        self.hear(pf.encode(reply))
        self.assertEqual(self.p.status()["run"]["detail"], "bad_answer")
        # A REPLY played back after the run is over changes nothing.
        before = len(self.modem.fields)
        self.hear(pf.encode(reply))
        self.assertEqual(len(self.modem.fields), before)

    def test_resends_and_timeouts(self) -> None:
        box = BoxModel("042137")
        self.offer(box)
        self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": box.pair_id.hex(), "code": "042137"})
        for _ in range(5):
            self.advance(RESEND_MS)
        starts = [f for f in self.modem.fields if pf.decode(f)["kind"] == "start"]
        self.assertEqual(len(starts), 3)  # at most three STARTs
        self.assertEqual(len(set(starts)), 1)  # the same one: the same sid
        self.advance(STEP_MS)
        self.assertEqual(self.p.status()["run"]["detail"], "no_answer")
        # A new run, its DONE lost: three KEYs, then "no_done".
        self.offer(box)
        self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": box.pair_id.hex(), "code": "042137"})
        self.hear(box.answer(self.modem.fields[-1]))
        for _ in range(5):
            self.advance(RESEND_MS)
        keys = [f for f in self.modem.fields if pf.decode(f)["kind"] == "key"]
        self.assertEqual(len(keys), 3)
        self.advance(STEP_MS)
        self.assertEqual(self.p.status()["run"]["detail"], "no_done")

    def test_done_is_checked(self) -> None:
        box = BoxModel("042137")
        self.offer(box)
        self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": box.pair_id.hex(), "code": "042137"})
        self.hear(box.answer(self.modem.fields[-1]))
        done = pf.decode(box.answer(self.modem.fields[-1]))
        self.hear(pf.encode(dict(done, tag=bytes(16))))  # a forged DONE: ignored
        self.assertEqual(self.p.status()["run"]["state"], "sealing")
        fp = b"\x00\x00\x00\x01"  # adopted, but to another key than ours
        self.hear(pf.encode(dict(done, fingerprint=fp, tag=pf.tag_done(box.keys, "adopted", fp))))
        self.assertEqual(self.p.status()["run"]["detail"], "fingerprint")

    def test_refusals(self) -> None:
        post = lambda body: self.client.post("/api/v1/adopt/pair", headers=GM, json=body)  # noqa: E731
        self.assertEqual(post({"pair_id": "00" * 8, "code": "123456"}).status_code, 404)  # not offering
        box = BoxModel("042137")
        self.offer(box)
        self.assertEqual(post({"pair_id": box.pair_id.hex(), "code": "12345"}).status_code, 400)
        self.assertEqual(post({"pair_id": "zz", "code": "123456"}).status_code, 400)
        self.assertEqual(post({"pair_id": box.pair_id.hex(), "code": "042137"}).status_code, 200)
        self.assertEqual(post({"pair_id": box.pair_id.hex(), "code": "042137"}).status_code, 409)  # one at a time
        # Offers are forgotten a minute after the last one.
        self.advance(61_000)
        self.assertEqual(self.p.status()["offers"], [])
        self.modem.state = "down"
        self.assertEqual(self.client.post("/api/v1/adopt/pair/listen", headers=GM).status_code, 503)

    def test_the_channel(self) -> None:
        # On the default channel: nothing to tune.
        r = self.client.post("/api/v1/adopt/pair/listen", headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(r.json()["listening"])
        self.assertEqual(self.modem.channels, [])
        # The field on 868.3 MHz: listening tunes the modem to 869.525 MHz, then back.
        self.store.set_setting("radio.channel_hz", "868300000")
        r = self.client.post("/api/v1/adopt/pair/listen", headers=GM)
        self.assertEqual(self.modem.channels, [PAIR_CHANNEL_HZ])
        self.assertTrue(r.json()["listening"] and r.json()["listen_ms_left"] > 0)
        self.advance(300_001)
        self.assertEqual(self.modem.channels, [PAIR_CHANNEL_HZ, 868300000])
        # With a game live on 868.3 MHz: refused (the boxes' HELLOs come on the game's channel).
        r = self.client.post("/api/v1/games", headers=GM, json={"name": "g", "mode_id": "org.atalaia.domination",
                                                                "teams": ["red", "blue"]})
        self.assertEqual(r.status_code, 201, r.text)
        self.assertEqual(self.client.post("/api/v1/adopt/pair/listen", headers=GM).status_code, 409)
        # A modem without pair frames in its firmware: refused.
        self.client.post(f"/api/v1/games/{r.json()['id']}/end", headers=GM, json={})
        self.modem.has_pair_frames = False
        self.assertEqual(self.client.post("/api/v1/adopt/pair/listen", headers=GM).status_code, 503)

    def test_offers_under_one_name_or_one_id(self) -> None:
        """Decision AD-26: a fake box offering under a real box's name, or a real box's pair id
        under another name, is flagged; each entry shows the id the box's screen shows."""
        real = BoxModel("042137", pair_id=bytes.fromhex("b0c5b0c5a1a2a3a4"), name="porta-norte")
        self.hear(real.offer())
        offers = self.p.status()["offers"]
        self.assertEqual((offers[0]["short_id"], offers[0]["duplicate_name"], offers[0]["conflict"]),
                         ("b0c5", False, False))
        # The real box's pair id under another name: refused, the first name stays, flagged.
        self.hear(BoxModel("0", pair_id=real.pair_id, name="intruso").offer())
        [entry] = self.p.status()["offers"]
        self.assertEqual((entry["name"], entry["conflict"]), ("porta-norte", True))
        # Another pair id under the real box's name: both flagged as a duplicate name.
        self.hear(BoxModel("0", pair_id=b"\x11" * 8, name="porta-norte").offer())
        offers = self.p.status()["offers"]
        self.assertEqual(len(offers), 2)
        self.assertTrue(all(o["duplicate_name"] for o in offers))
        self.assertEqual(sorted(o["short_id"] for o in offers), ["1111", "b0c5"])

    def test_the_modem_moved_while_listening(self) -> None:
        """Finding 3: the field's channel set, a scan and the modem back up all tune the modem to the
        field's channel: pairing stops saying it listens on 869.525 MHz, and a run under way fails."""
        self.store.set_setting("radio.channel_hz", "868300000")
        self.client.post("/api/v1/adopt/pair/listen", headers=GM)
        self.assertTrue(self.p.status()["listening"])
        # The GM sets the field's channel (868.1 MHz): no longer listening.
        r = self.client.put("/api/v1/radio/channel", headers=GM, json={"channel_hz": 868100000, "source": "manual"})
        self.assertEqual(r.status_code, 200, r.text)
        status = self.p.status()
        self.assertEqual((status["listening"], status["radio_channel_hz"]), (False, 868100000))
        # Listening again, a run under way, then the modem reconnects: the run fails, said why.
        self.client.post("/api/v1/adopt/pair/listen", headers=GM)
        box = BoxModel("042137")
        self.hear(box.offer())
        self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": box.pair_id.hex(), "code": "042137"})
        self.ctrl._on_modem_state("up")
        status = self.p.status()
        self.assertFalse(status["listening"])
        self.assertEqual((status["run"]["state"], status["run"]["detail"]), ("failed", "channel_changed"))
        self.assertEqual(self.modem.channels[-1], 868100000)
        # A scan's end does it too.
        self.client.post("/api/v1/adopt/pair/listen", headers=GM)
        self.assertTrue(self.p.status()["listening"])
        self.ctrl._on_scan({"state": "done"})
        self.assertFalse(self.p.status()["listening"])
        # On the pairing channel itself nothing changes for a run under way.
        self.client.put("/api/v1/radio/channel", headers=GM, json={"channel_hz": PAIR_CHANNEL_HZ, "source": "manual"})
        box2 = BoxModel("111111", pair_id=b"\xb1" * 8)
        self.hear(box2.offer())
        self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": box2.pair_id.hex(), "code": "111111"})
        self.ctrl._on_modem_state("up")
        self.assertEqual(self.p.status()["run"]["state"], "starting")

    def test_field_frames_still_go_to_the_invites(self) -> None:
        from atalaia_sim import field_frame as ff
        nonces = ff.NonceSource(KEY, b"\x02" * 8)  # a box's nonces carry its own device id's pseudonym
        frame = ff.encode(ff.field_key(KEY), {"kind": "announce", "device_id": b"\x02" * 8, "token": b"\x03" * 8,
                                              "name": "box", "tier": 0}, nonces.next())
        self.hear(frame)
        self.assertEqual(len(self.ctrl.reinvite.inviter.boxes), 1)
        self.assertEqual(self.p.status()["offers"], [])


class EndToEndTests(unittest.TestCase):
    """The firmware's own pairing (box_host) through the C host modem and the real controller."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.hub = AirHub()
        self.host = HostModem(hub=self.hub)
        self.hub.add(self.host.air_port)
        self.modem = RadioModem(self.host.url, ping_interval=0.2, retry_interval=0.2)
        self.modem.start()
        self.assertTrue(self.modem.wait_up(5))
        self.cfg = config(self.tmp.name)
        self.store = Store(self.cfg.db_path)
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, join_key=KEY)
        from atalaia_controller.adoption import Adoption
        Adoption(self.ctrl)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))
        self.ctrl.start()
        self.boxes: list[BoxHost] = []

    def tearDown(self) -> None:
        for box in self.boxes:
            box.close()
        self.client.close()
        self.ctrl.stop()
        self.modem.stop()
        self.store.close()
        self.host.close()
        self.hub.close()
        self.tmp.cleanup()

    def box(self, name: str) -> BoxHost:
        b = BoxHost(self.hub, os.path.join(self.tmp.name, name), b"", name=name,
                    extra=("--pair", "--announce-ms", "400"))
        self.boxes.append(b)
        return b

    @staticmethod
    def code(box: BoxHost, index: int = -1) -> str:
        codes = [m.group(1) + m.group(2) for m in (re.search(r"code (\d{3}) (\d{3})", line) for line in box.lines)
                 if m]
        return codes[index]

    def offered(self, name: str) -> str | None:
        offers = self.client.get("/api/v1/adopt/pair", headers=GM).json()["offers"]
        return next((o["pair_id"] for o in offers if o["name"] == name), None)

    def run_state(self) -> dict:
        return self.client.get("/api/v1/adopt/pair", headers=GM).json()["run"]

    def test_pair_a_box_by_its_code(self) -> None:
        self.assertTrue(self.modem.has_pair_frames)
        box = self.box("porta-norte")
        self.assertTrue(wait_for(lambda: box.logged("pairing: code"), 5), box.lines[-5:])
        self.assertTrue(box.logged('SCREEN status {"title":"Pair this box","code":"'))
        self.assertTrue(wait_for(lambda: self.offered("porta-norte"), 8))
        pair_id = self.offered("porta-norte")

        # A wrong code: the run fails, the box shows a new one and stays unadopted.
        first = self.code(box)
        wrong = f"{(int(first) + 1) % 1000000:06d}"
        r = self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": pair_id, "code": wrong})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(wait_for(lambda: self.run_state()["state"] == "failed", 15), self.run_state())
        self.assertEqual(self.run_state()["detail"], "wrong_code")
        self.assertTrue(wait_for(lambda: box.logged("pairing: new code"), 12), box.lines[-6:])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "porta-norte", "join_key")))

        # The right (new) code: adopted with this field's key.
        r = self.client.post("/api/v1/adopt/pair", headers=GM, json={"pair_id": pair_id, "code": self.code(box)})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertTrue(wait_for(lambda: self.run_state()["state"] == "done", 15), (self.run_state(), box.lines[-8:]))
        self.assertEqual(self.run_state()["result"], "adopted")
        with open(os.path.join(self.tmp.name, "porta-norte", "join_key"), "rb") as f:
            self.assertEqual(f.read(), KEY)
        self.assertTrue(box.logged(f"adoption (radio): adopted, field {field_card.fingerprint(KEY)}"))
        log = self.client.get("/api/v1/adopt", headers=GM).json()["log"]
        self.assertEqual([x["result"] for x in log[:2]], ["adopted", "wrong_code"])

        # Its field frames start under the new key: the controller lists it as a free box.
        def free() -> list:
            return [b for b in self.client.get("/api/v1/boxes", headers=GM).json()["boxes"]
                    if b["name"] == "porta-norte"]
        self.assertTrue(wait_for(free, 25), box.lines[-6:])


if __name__ == "__main__":
    unittest.main()
