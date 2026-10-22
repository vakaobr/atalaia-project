# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Missing modes sent to boxes from the GM console (phase 5 plan phase 13a, mode_fetch.py,
protocol/mode-packages.md "Fetching missing modes", decisions P5B-8 to P5B-17 and P5D-*).

The real engine with a fake modem (as test_reinvite.py) and a signed package uploaded with a
trusted mode key: what the controller offers boxes for each of the game's roles (and why not),
the endpoints a box fetches from (no token, only a part of the live game's mode, only between
games, exactly the signed bytes), join keys 16 and 17 in invites and card joins, the start guard
waiting while a box fetches, the box's report (an HMAC with the game key), node.modes_failed,
timeouts, the GM's "stop waiting" and "forget its fetched modes".

The box's side is a test double of firmware/esp32/main/mode_fetch.c (plan phase 13b): the
simulator's model of a free box (atalaia_sim.lobby.IdleBox) takes the invite, and FetchingBox
fetches each part it lacks through the API, checks it as a box does (mode_package.box_check_*,
the shared vectors' reference), loads node.lua in the core's sandbox, reports and says HELLO.

    cd controller && python -m unittest tests.test_mode_fetch
"""

from __future__ import annotations

import base64
import json
import random
import tempfile
import unittest
from typing import Any, Optional

from fastapi.testclient import TestClient

from support import CORE, FakeModem, config
from test_reinvite import JOIN_KEY, Clock, hello
from test_signed_modes import KEY, MANIFEST, NODE, OTHER, OTHER_SIGNING, SIGNING, package, query

from atalaia_controller import mode_package as mp
from atalaia_controller.api import Auth, create_app
from atalaia_controller.config import ConfigError, load_config
from atalaia_controller.engine import Controller
from atalaia_controller.mode_fetch import ModeFetch
from atalaia_controller.signed_modes import SignedModes
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub
from atalaia_sim import join as joinfmt
from atalaia_sim import lobby
from atalaia_sim.core import Node
from atalaia_sim.protocol import EVENTS

GM = {"Authorization": "Bearer gm-secret"}
READ = {"Authorization": "Bearer read-secret"}
TAGGER = "org.club.tagger"
BUILTIN = {"org.atalaia.domination", "org.atalaia.holdall", "org.atalaia.codes"}
CA = b"\xca" * 32
URLS = ["https://10.42.0.1:8443"]


class FetchingBox:
    """A Field Box fetching the parts it lacks (the test double of main/mode_fetch.c): over the
    controller's API, with the checks of mode_package.box_check_*, then its sandbox."""

    def __init__(self, case: "Case", box: lobby.IdleBox, keys: list[str], tier: str = "full") -> None:
        self.case, self.box, self.keys, self.tier = case, box, keys, tier
        self.reports: list[dict[str, Any]] = []

    def report(self, part: str, version: Optional[str], result: str) -> None:
        j = self.box.game
        body = mp.report_body(j["game_id"], j["node_id"], part, version, result, self.box.fetched)
        r = self.case.client.post("/api/v1/mode-packages/report", content=body, headers={
            "Content-Type": "text/plain", "X-Atalaia-Mac": mp.report_mac(j["game_key"], body)})
        self.reports.append({"part": part, "result": result, "status": r.status_code, "answer": r.json()})

    def fetch_one(self, part: str) -> tuple[Optional[str], str]:
        client = self.case.client
        r = client.get(f"/api/v1/mode-packages/{part}/release")
        if r.status_code != 200:
            return None, "not_offered"
        try:
            release, _ = mp.box_check_release(r.content, part, self.keys, self.tier, BUILTIN)
        except mp.PackageError as exc:
            return None, exc.code
        a = client.get(f"/api/v1/mode-packages/{part}/package")
        if a.status_code != 200 or int(a.headers["content-length"]) != release.size:
            return release.version, "download"
        try:
            kept = mp.box_check_archive(a.content, release)
        except mp.PackageError as exc:
            return release.version, exc.code
        node = Node(CORE, 1, 1, ["red", "blue"], {}, kept["node.lua"], f"{part}/node.lua")
        try:
            if not node.loaded:
                return release.version, "load"
        finally:
            node.close()
        self.box.fetched_part(part, release.version)
        return release.version, "installed"

    def run(self, seq: int = 0) -> list[str]:
        """Every part it lacks, in order, stopping at the first failure; HELLO when all are in."""
        results = []
        for part in list(self.box.fetching):
            version, result = self.fetch_one(part)
            self.report(part, version, result)
            results.append(result)
            if result != "installed":
                self.box.fetch_failed()
                return results
        j = self.box.game
        self.case.modem.rx(j["node_id"], seq, "HELLO", hello(self.box.name, self.box.device_id),
                           game_id=j["game_id"], epoch=1)
        return results


@unittest.skipIf(CORE is None, "needs the shared core library")
class Case(unittest.TestCase):
    box_keys = [KEY["public_key_b64"]]
    https = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = config(self.tmp.name, modes_keys=[KEY["public_key_b64"], OTHER["public_key_b64"]],
                          modes_box_keys=list(self.box_keys))
        self.clock = Clock()
        self.store = Store(self.cfg.db_path)
        self.modem = FakeModem()
        self.ctrl = Controller(self.cfg, self.store, modem=self.modem, core=CORE, clock=self.clock,
                               join_key=JOIN_KEY)
        if self.https:
            self.ctrl.ca_sha256, self.ctrl.link_urls = CA, list(URLS)
        SignedModes(self.ctrl, self.cfg.modes_keys, [], "")
        self.fetch = ModeFetch(self.ctrl, self.cfg.modes_box_keys, self.cfg.modes_fetch_timeout_s, clock=self.clock)
        self.messages: list[dict] = []
        self.ctrl.add_listener(self.messages.append)
        self.client = TestClient(create_app(self.ctrl, Hub(), Auth(self.cfg.gm_token, self.cfg.read_token)))

    def tearDown(self):
        self.client.close()
        self.ctrl.stop()
        self.store.close()
        self.tmp.cleanup()

    def upload(self, archive: bytes, release: dict, expect: int = 201) -> dict:
        r = self.client.post("/api/v1/mode-packages", params=query(release), content=archive,
                             headers={**GM, "Content-Type": "application/octet-stream"})
        self.assertEqual(r.status_code, expect, r.text)
        return r.json()

    def game(self, mode: str = TAGGER, **spec) -> int:
        r = self.client.post("/api/v1/games", headers=GM, json={"name": "g", "mode_id": mode,
                                                                 "teams": ["red", "blue"], **spec})
        self.assertEqual(r.status_code, 201, r.text)
        return r.json()["id"]

    def status(self) -> dict:
        r = self.client.get("/api/v1/mode-fetch", headers=GM)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def pump(self, box: lobby.IdleBox, seconds: float = 1.0, step: float = 0.05) -> None:
        for _ in range(int(seconds / step)):
            self.clock.advance(step)
            now = self.ctrl.now_ms()
            for frame in box.tick(now):
                self.modem.on_field_rx(frame, -71, 6)
            self.ctrl.tick()
            while self.modem.fields:
                box.on_frame(self.modem.fields.pop(0), now)

    def free_box(self, installed: set[str], tier: int = 0, seed: int = 4) -> lobby.IdleBox:
        """A box that played a game of Domination and is free again, announcing itself."""
        box = lobby.IdleBox(JOIN_KEY, "Zona Norte", rng=random.Random(seed), tier=tier,
                            now_ms=self.ctrl.now_ms(), installed=set(installed))
        first = self.game("org.atalaia.domination", assignments={"4": "zone"})
        payload = bytes.fromhex(self.ctrl.issue_join({"role": "zone"}, node_id=4)["payload_hex"])
        self.assertEqual(box.join(payload), "accepted")
        self.modem.rx(4, 0, "HELLO", hello("box-4", box.device_id), game_id=first, epoch=1)
        self.ctrl.start_game(first)
        box.start()
        self.ctrl.end_game(first)
        box.end(self.ctrl.now_ms())
        self.pump(box, 21)
        return box

    def invite(self, gid: int, box: lobby.IdleBox, **extra) -> dict:
        r = self.client.post(f"/api/v1/games/{gid}/invites", headers=GM,
                             json={"boxes": [{"device_id": box.device_id.hex(), "role": "zone", **extra}]})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["invites"][0]

    def invite_status(self, gid: int) -> dict:
        return self.client.get(f"/api/v1/games/{gid}/invites", headers=GM).json()["invites"][0]

    def fetch_of(self, node_id: int) -> dict:
        return next(f for f in self.status()["fetches"] if f["node_id"] == node_id)


class OfferTests(Case):
    def test_what_boxes_are_offered_and_fetch(self):
        archive, release = package()
        self.upload(archive, release)
        gid = self.game()
        status = self.status()
        self.assertEqual((status["box_keys"], status["https"], status["game"], status["timeout_s"]),
                         ([KEY["key_id"]], True, gid, 300.0))
        zone = status["roles"]["zone"]
        self.assertEqual((zone["mode_id"], zone["ok"], zone["why"]), (TAGGER, True, None))
        [part] = zone["parts"]
        self.assertEqual((part["id"], part["state"], part["version"], part["key_id"], part["size"], part["min_tier"]),
                         (TAGGER, "offered", "0.1.0", KEY["key_id"], len(archive), "reduced"))
        # What a box fetches, with no token: the signed text, then the archive, exactly as signed.
        text = self.client.get(f"/api/v1/mode-packages/{TAGGER}/release")
        self.assertEqual(text.status_code, 200, text.text)
        self.assertEqual(text.content, mp.release_from(release).text())
        self.assertTrue(text.headers["content-type"].startswith("text/plain"))
        self.assertEqual(text.headers["cache-control"], "no-store")
        got = self.client.get(f"/api/v1/mode-packages/{TAGGER}/package")
        self.assertEqual((got.status_code, got.content, got.headers["content-length"]),
                         (200, archive, str(len(archive))))
        # The box's own checks take it.
        rel, who = mp.box_check_release(text.content, TAGGER, [KEY["public_key_b64"]], "reduced", BUILTIN)
        self.assertEqual((who, sorted(mp.box_check_archive(got.content, rel))), (KEY["key_id"], ["node.lua"]))
        # Not a part of the live game, a built-in one, nonsense: 404.
        self.assertEqual(self.client.get("/api/v1/mode-packages/org.atalaia.domination/release").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/mode-packages/org.club.other/package").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/mode-packages/..%2F..%2Fetc/release").status_code, 404)
        # The GM's view needs the GM token.
        self.assertEqual(self.client.get("/api/v1/mode-fetch", headers=READ).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/mode-fetch").status_code, 401)
        # Only between games: once the game runs, nothing is served.
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True}).status_code,
                         200)
        self.assertEqual(self.client.get(f"/api/v1/mode-packages/{TAGGER}/release").status_code, 409)
        self.assertEqual(self.client.get(f"/api/v1/mode-packages/{TAGGER}/package").status_code, 409)

    def test_why_a_part_is_not_offered(self):
        archive, release = package()
        self.upload(archive, release)
        other_archive, other_release = package("org.club.other", key=OTHER_SIGNING)
        self.upload(other_archive, other_release)  # the controller trusts it; the boxes do not
        # An unsigned upload, a Full-only package, one too big for a box.
        files = mp.unpack(package("org.club.plain")[0])[1]
        self.assertEqual(self.client.post("/api/v1/modes", headers=GM, json={"files": files}).status_code, 201)
        full_files = {"mode.yaml": MANIFEST.format(id="org.club.full", version="0.1.0").replace(
            "min_tier: reduced", "min_tier: full"), "node.lua": NODE}
        full = mp.pack("org.club.full", full_files)
        self.upload(full, mp.release_json(mp.sign_release(SIGNING, full), KEY["key_id"], "MIT"))
        big_files = {"mode.yaml": MANIFEST.format(id="org.club.big", version="0.1.0"), "node.lua": NODE,
                     "assets/notes.txt": "x" * (mp.BOX_MAX_PACKAGE_BYTES + 1)}
        big = mp.pack("org.club.big", big_files)
        self.upload(big, mp.release_json(mp.sign_release(SIGNING, big), KEY["key_id"], "MIT"))
        self.game()
        cases = {"org.club.other": "no_box_key", "org.club.plain": "unsigned", "org.club.big": "too_big",
                 "org.atalaia.domination": "builtin", "org.club.nothere": "missing", TAGGER: "offered",
                 "org.club.full": "offered"}
        for part, state in cases.items():
            with self.subTest(part):
                self.assertEqual(self.fetch.part(part)["state"], state)
        self.assertEqual(self.fetch.offer("org.atalaia.domination")["why"], "firmware")
        self.assertEqual(self.fetch.offer("org.club.full")["why"], None)
        self.assertEqual(self.fetch.offer("org.club.full", tier=1)["why"], "tier")
        self.assertEqual(self.fetch.offer(TAGGER, tier=1)["why"], None)
        self.assertEqual(self.fetch.offer("org.atalaia.domination+org.club.other")["why"], "no_box_key")
        # A key revoked on this controller: no longer offered.
        self.fetch.controller.signed_modes.revoked_config.add(KEY["key_id"])
        self.assertEqual(self.fetch.part(TAGGER)["state"], "revoked")
        self.assertEqual(self.client.get(f"/api/v1/mode-packages/{TAGGER}/release").status_code, 404)


class NoKeysTests(Case):
    box_keys: list[str] = []
    https = False

    def test_nothing_is_offered_without_box_keys_or_https(self):
        archive, release = package()
        self.upload(archive, release)
        self.game(assignments={"4": "zone"})
        self.assertEqual(self.status()["roles"]["zone"]["why"], "no_box_keys")
        self.fetch.box_keys = [KEY["public_key_b64"]]
        self.assertEqual(self.status()["roles"]["zone"]["why"], "no_https")
        r = self.client.post("/api/v1/join", headers=GM, json={"role": "zone", "fetch_modes": True})
        self.assertEqual(r.status_code, 409, r.text)
        self.assertIn("HTTPS", r.json()["detail"])


class FetchTests(Case):
    def setUp(self):
        super().setUp()
        archive, release = package()
        self.upload(archive, release)

    def test_send_missing_modes_from_the_invite_dialog(self):
        """The whole path: no mode, Send missing modes (key 16), fetching, the start guard, the
        report, the HELLO, start."""
        box = self.free_box({"org.atalaia.domination"})
        gid = self.game()
        self.invite(gid, box)
        self.pump(box, 2)
        self.assertEqual((self.invite_status(gid)["status"], self.invite_status(gid)["detail"]), ("refused", "no_mode"))
        self.pump(box, 70)  # its next announcement, with a new token
        inv = self.invite(gid, box, fetch_modes=True)
        self.assertEqual(inv["status"], "invited")
        fetch = self.fetch_of(inv["node_id"])
        self.assertEqual((fetch["state"], fetch["device_id"], fetch["mode_id"], fetch["fetch"]),
                         ("sent", box.device_id.hex(), TAGGER, True))
        self.pump(box, 2)
        # The box took the join fetching: key 16, with the field CA and the addresses.
        self.assertEqual((box.phase, box.fetching), ("joined", [TAGGER]))
        self.assertTrue(box.game["fetch_modes"])
        self.assertEqual((box.game["ca_sha256"], box.game["urls"]), (CA, URLS))
        self.assertFalse(box.game["forget_modes"])
        self.assertEqual(self.fetch_of(inv["node_id"])["state"], "fetching")
        # The game waits for it, even forced.
        r = self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True})
        self.assertEqual(r.status_code, 409)
        self.assertIn("fetching", r.json()["detail"])
        self.assertFalse(self.ctrl.start_check()["ok"])
        results = FetchingBox(self, box, [KEY["public_key_b64"]]).run()
        self.assertEqual(results, ["installed"])
        fetch = self.fetch_of(inv["node_id"])
        self.assertEqual((fetch["state"], fetch["installed"]), ("done", [TAGGER]))
        self.assertEqual(self.invite_status(gid)["status"], "joined")
        self.assertTrue(self.ctrl.start_check()["ok"])
        [kept] = [b for b in self.status()["boxes"] if b["device_id"] == box.device_id.hex()]
        self.assertEqual((kept["kept"], kept["node_id"], kept["game"], kept["forget"]),
                         ({TAGGER: "0.1.0"}, inv["node_id"], gid, False))
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM).json()["state"], "running")
        # The consoles were told along the way.
        states = [f["state"] for m in self.messages if m["type"] == "mode_fetch" for f in m["fetches"]]
        self.assertTrue({"sent", "fetching", "installed", "done"} <= set(states))

    def test_a_box_that_cannot_fetch_answers_no_mode_again(self):
        """Firmware before key 16 (or a box without a mode key) answers no_mode: the fetch failed."""
        box = self.free_box({"org.atalaia.domination"})
        gid = self.game()
        self.pump(box, 1)
        old = lobby.can_fetch
        lobby.can_fetch = lambda j: False  # the firmware of before: key 16 skipped
        try:
            inv = self.invite(gid, box, fetch_modes=True)
            self.pump(box, 2)
        finally:
            lobby.can_fetch = old
        fetch = self.fetch_of(inv["node_id"])
        self.assertEqual((fetch["state"], fetch["reason"]), ("failed", "no_mode"))
        self.assertIsNone(self.fetch.busy())

    def test_a_refused_package_fails_the_fetch_and_frees_the_box(self):
        """The box's own keys do not include the signer: bad_signature, reported over HTTPS; the
        box leaves the join; the game does not wait; Start says the role is missing."""
        box = self.free_box({"org.atalaia.domination"})
        gid = self.game()
        inv = self.invite(gid, box, fetch_modes=True)
        self.pump(box, 2)
        fb = FetchingBox(self, box, [OTHER["public_key_b64"]])
        self.assertEqual(fb.run(), ["bad_signature"])
        self.assertEqual(fb.reports[0]["answer"], {"accepted": True})
        fetch = self.fetch_of(inv["node_id"])
        self.assertEqual((fetch["state"], fetch["reason"], fetch["mode"]), ("failed", "bad_signature", TAGGER))
        self.assertTrue(box.available)
        self.assertIsNone(self.fetch.busy())
        self.assertEqual(self.ctrl.start_check()["missing"], ["zone"])

    def test_node_modes_failed_over_the_radio(self):
        """A box with no Wi-Fi says so over LoRa (node.modes_failed, critical, sealed with the game
        key): the fetch failed, and the node it was heard on does not count as joined."""
        box = self.free_box({"org.atalaia.domination"})
        gid = self.game()
        inv = self.invite(gid, box, fetch_modes=True)
        self.pump(box, 2)
        node = inv["node_id"]
        event = {"node": node, "seq": 0, "t": 0, "type": "node.modes_failed",
                 "data": {"mode": TAGGER, "reason": "no_wifi"}}
        if "node.modes_failed" in EVENTS:  # in the schema from plan phase 13b: over the real radio path
            from atalaia_sim import codec  # noqa: PLC0415
            self.modem.rx(node, 1, "EVENT", codec.encode_event(event), game_id=gid, epoch=1, ack=True)
        else:  # until then: the engine's decoded event, as it reaches the listeners
            self.ctrl.fc.register_node(node, f"node-{node}", "zone")
            self.ctrl.fc.nodes[node].heard = True
            self.ctrl._emit({"type": "event", "game": gid, "event": event})
        fetch = self.fetch_of(node)
        self.assertEqual((fetch["state"], fetch["reason"], fetch["mode"]), ("failed", "no_wifi", TAGGER))
        self.assertEqual(self.ctrl.start_check()["missing"], ["zone"])  # heard, but not joined
        # An event for a node that was not fetching changes nothing.
        self.ctrl._emit({"type": "event", "game": gid, "event": {**event, "node": 99}})
        self.assertEqual(len(self.status()["fetches"]), 1)

    def test_reports_are_checked(self):
        box = self.free_box({"org.atalaia.domination"})
        gid = self.game()
        inv = self.invite(gid, box, fetch_modes=True)
        self.pump(box, 2)
        key = box.game["game_key"]
        body = mp.report_body(gid, inv["node_id"], TAGGER, "0.1.0", "load", {})

        def post(data: bytes, mac: Optional[str]):
            headers = {"Content-Type": "text/plain"}
            if mac is not None:
                headers["X-Atalaia-Mac"] = mac
            return self.client.post("/api/v1/mode-packages/report", content=data, headers=headers)
        self.assertEqual(post(body, mp.report_mac(bytes(16), body)).status_code, 400)  # another key
        self.assertEqual(post(body, None).status_code, 400)
        self.assertEqual(post(b"atalaia-mode-report-v1\n", mp.report_mac(key, b"x")).status_code, 400)
        self.assertEqual(post(b"x" * 2000, "0" * 64).status_code, 413)
        other = mp.report_body(gid + 7, inv["node_id"], TAGGER, "0.1.0", "load", {})
        self.assertEqual(post(other, mp.report_mac(key, other)).status_code, 409)  # not the live game
        # A node that was not sent key 16: accepted as news of what it keeps, changes no fetch.
        stray = mp.report_body(gid, 77, TAGGER, "0.1.0", "installed", {TAGGER: "0.1.0"})
        self.assertEqual(post(stray, mp.report_mac(key, stray)).json(), {"accepted": False})
        self.assertEqual(self.fetch_of(inv["node_id"])["state"], "fetching")
        self.assertEqual(post(body, mp.report_mac(key, body)).json(), {"accepted": True})
        self.assertEqual((self.fetch_of(inv["node_id"])["state"], self.fetch_of(inv["node_id"])["reason"]),
                         ("failed", "load"))

    def test_timeout_and_stop_waiting(self):
        box = self.free_box({"org.atalaia.domination"})
        gid = self.game()
        inv = self.invite(gid, box, fetch_modes=True)
        self.pump(box, 2)
        self.assertIsNotNone(self.fetch.busy())
        self.assertEqual(self.client.delete("/api/v1/mode-fetch", headers=READ).status_code, 403)
        self.assertEqual(self.client.delete("/api/v1/mode-fetch", headers=GM).json(), {"cancelled": [inv["node_id"]]})
        self.assertEqual(self.fetch_of(inv["node_id"])["state"], "cancelled")
        self.assertIsNone(self.fetch.busy())
        # Another fetch, never heard of: timed out after fetch_timeout_s, and the game may start.
        self.pump(box, 70)
        self.fetch.attempts.clear()
        inv = self.invite(gid, box, fetch_modes=True)
        self.assertIsNotNone(self.fetch.busy())
        self.clock.advance(301)
        self.assertIsNone(self.fetch.busy())
        self.assertEqual(self.fetch_of(inv["node_id"])["state"], "timeout")
        self.assertEqual(self.client.post(f"/api/v1/games/{gid}/start", headers=GM, json={"force": True}).status_code,
                         200)

    def test_a_reduced_box_is_not_sent_a_full_package(self):
        full_files = {"mode.yaml": MANIFEST.format(id="org.club.full", version="0.1.0").replace(
            "min_tier: reduced", "min_tier: full"), "node.lua": NODE}
        full = mp.pack("org.club.full", full_files)
        self.upload(full, mp.release_json(mp.sign_release(SIGNING, full), KEY["key_id"], "MIT"))
        box = self.free_box({"org.atalaia.domination"}, tier=1)
        gid = self.game("org.club.full")
        inv = self.invite(gid, box, fetch_modes=True)
        self.assertEqual(inv["status"], "not_sent")
        self.assertIn("Reduced", inv["detail"])
        self.assertEqual(self.status()["fetches"], [])

    def test_a_card_join_with_key_16(self):
        """A card or a QR code with key 16 does the same (protocol/join.md): the join carries keys
        13, 14 and 16 and the fetch is followed by node id."""
        gid = self.game()
        r = self.client.post("/api/v1/join", headers=GM, json={"role": "zone", "fetch_modes": True})
        self.assertEqual(r.status_code, 200, r.text)
        out = r.json()
        self.assertTrue(out["fetch_modes"])
        j = joinfmt.decode(bytes.fromhex(out["payload_hex"]), JOIN_KEY)
        self.assertEqual((j["fetch_modes"], j["forget_modes"], j["ca_sha256"], j["urls"]), (True, False, CA, URLS))
        fetch = self.fetch_of(out["node_id"])
        self.assertEqual((fetch["state"], fetch["device_id"], fetch["game"]), ("sent", None, gid))
        bad = self.client.post("/api/v1/join", headers=GM, json={"role": "zone", "fetch_modes": "yes"})
        self.assertEqual(bad.status_code, 400)
        ctl = self.client.post("/api/v1/join", headers=GM, json={"kind": "controller", "fetch_modes": True})
        self.assertEqual(ctl.status_code, 400)
        # A game whose every part is built in: a fetch cannot help (its firmware is older).
        self.client.post(f"/api/v1/games/{gid}/end", headers=GM, json={})
        self.game("org.atalaia.domination")
        r = self.client.post("/api/v1/join", headers=GM, json={"role": "zone", "fetch_modes": True})
        self.assertEqual(r.status_code, 409)
        self.assertIn("firmware update", r.json()["detail"])
        plain = self.client.post("/api/v1/join", headers=GM, json={"role": "zone"}).json()
        self.assertNotIn("fetch_modes", plain)
        self.assertFalse(joinfmt.decode(bytes.fromhex(plain["payload_hex"]), JOIN_KEY)["fetch_modes"])


class ForgetTests(Case):
    def test_forget_fetched_modes_at_the_next_invite(self):
        archive, release = package()
        self.upload(archive, release)
        box = self.free_box({"org.atalaia.domination"})
        device = box.device_id.hex()
        gid = self.game()
        self.invite(gid, box, fetch_modes=True)
        self.pump(box, 2)
        FetchingBox(self, box, [KEY["public_key_b64"]]).run()
        self.assertEqual(box.fetched, {TAGGER: "0.1.0"})
        # The GM marks it in the Boxes tab.
        self.assertEqual(self.client.put(f"/api/v1/mode-fetch/forget/{device}", headers=READ,
                                         json={"forget": True}).status_code, 403)
        self.assertEqual(self.client.put("/api/v1/mode-fetch/forget/XYZ", headers=GM,
                                         json={"forget": True}).status_code, 400)
        self.assertEqual(self.client.put(f"/api/v1/mode-fetch/forget/{device}", headers=GM,
                                         json={"forget": "yes"}).status_code, 400)
        r = self.client.put(f"/api/v1/mode-fetch/forget/{device}", headers=GM, json={"forget": True})
        self.assertEqual(r.json(), {"device_id": device, "forget": True})
        [b] = [b for b in self.status()["boxes"] if b["device_id"] == device]
        self.assertEqual((b["forget"], b["kept"]), (True, {TAGGER: "0.1.0"}))
        # The game ends; the next game's invite carries key 17; the box forgets, then says HELLO.
        self.client.post(f"/api/v1/games/{gid}/start", headers=GM)
        box.start()
        self.client.post(f"/api/v1/games/{gid}/end", headers=GM, json={})
        box.end(self.ctrl.now_ms())
        self.pump(box, 21)
        nxt = self.game("org.atalaia.domination")
        inv = self.invite(nxt, box)
        self.pump(box, 2)
        self.assertEqual(box.game["game_id"], nxt)
        self.assertTrue(box.game["forget_modes"])
        self.assertFalse(box.game["fetch_modes"])
        self.assertEqual(box.fetched, {})
        self.assertIsNone(self.fetch.busy())  # forgetting is not waited for
        self.assertEqual(self.fetch_of(inv["node_id"])["state"], "forget")
        self.modem.rx(inv["node_id"], 0, "HELLO", hello("Zona Norte", box.device_id), game_id=nxt, epoch=1)
        self.assertEqual(self.fetch.forget_marked(), [])
        self.assertEqual(self.fetch_of(inv["node_id"])["state"], "done")
        # Kept across a restart: the boxes' fetched modes are in the store.
        self.assertIn(device, json.loads(self.store.get_setting("mode_fetch.boxes")))


class ConfigTests(unittest.TestCase):
    def test_box_keys_and_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            key = KEY["public_key_b64"]
            cfg = load_config(None, env={"ATALAIA_MODES_BOX_KEYS": f"{key},{OTHER['public_key_b64']}",
                                         "ATALAIA_MODES_FETCH_TIMEOUT_S": "120",
                                         "ATALAIA_CONTROLLER_DB_PATH": f"{tmp}/c.db"})
            self.assertEqual((cfg.modes_box_keys, cfg.modes_fetch_timeout_s), ([key, OTHER["public_key_b64"]], 120.0))
            for env in ({"ATALAIA_MODES_BOX_KEYS": "nope"}, {"ATALAIA_MODES_FETCH_TIMEOUT_S": "5"},
                        {"ATALAIA_MODES_BOX_KEYS": ",".join([key] * 9)}):
                with self.subTest(env), self.assertRaises(ConfigError):
                    load_config(None, env={**env, "ATALAIA_CONTROLLER_DB_PATH": f"{tmp}/c.db"})
        self.assertEqual(base64.b64decode(key).hex(), KEY["public_key"])


if __name__ == "__main__":
    unittest.main()
