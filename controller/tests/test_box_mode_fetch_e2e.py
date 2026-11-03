# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A Field Box fetching a signed mode package from the real controller over HTTPS (phase 5 plan
phase 13, protocol/mode-packages.md "Fetching missing modes").

    cd controller && ATALAIA_MODEM_HOST=... ATALAIA_BOX_HOST=... python -m unittest tests.test_box_mode_fetch_e2e

The controller is the whole program as ``run`` builds it (main.build): the field CA made on its
first start, served by uvicorn on its TLS port with its own certificate, the C host modem on the
air. A signed package is uploaded (a test registry key, protocol/vectors/mode_package.json; never
the project's keys), a game of its mode made, and the join (keys 13, 14 and 16) typed into the C
host box started with ``--mode-keys`` (that test key) and ``--mode-source https``. The box then runs
the firmware's own fetch (main/mode_fetch.c, mode_package.c, mode_store.c) over the firmware's own
field CA pin (main/field_ca_pin.c) and mbedTLS: the release and the archive over HTTPS from the
join's address, its checks, the package kept, the report posted with the game key's HMAC, its
HELLO. The refusals: a join whose field CA is not the controller's (no report reaches it, the box
says ``unreachable`` over LoRa), a package signed by a key the box does not carry
(``bad_signature``), and an archive changed after it was signed (``bad_hash``).
"""

from __future__ import annotations

import os
import ssl
import tempfile
import threading
import unittest

try:  # the client Starlette's TestClient takes: httpx2 on the pinned lock, httpx on Ubuntu's packages (PLK-3)
    import httpx2 as httpx
except ModuleNotFoundError:
    import httpx
import uvicorn

from support import BOX_HOST, CORE, MODEM_HOST, AirHub, BoxHost, HostModem, config, free_port, wait_for
from test_signed_modes import KEY, OTHER, OTHER_SIGNING, package, query

from atalaia_controller.main import build

GM = {"Authorization": "Bearer gm-secret"}
JOIN_KEY = bytes(range(100, 132))
TAGGER = "org.club.tagger"


@unittest.skipUnless(MODEM_HOST and BOX_HOST and CORE is not None, "host modem, host box or core not built")
class BoxFetchOverHttpsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = tmp.name
        self.hub = AirHub()
        self.addCleanup(self.hub.close)
        self.host = HostModem(hub=self.hub)
        self.addCleanup(self.host.close)
        self.hub.add(self.host.air_port)
        self.port = free_port()
        # The controller offers a part to boxes that carry its key: here both test keys, so a package signed
        # by the other key is offered, and the box (which carries only KEY) has to refuse it itself.
        cfg = config(self.tmp, port=self.host.url, api_port=free_port(), tls_port=self.port, host="127.0.0.1",
                     tls_names=["127.0.0.1"], join_key=JOIN_KEY.hex(),
                     modes_keys=[KEY["public_key_b64"], OTHER["public_key_b64"]],
                     modes_box_keys=[KEY["public_key_b64"], OTHER["public_key_b64"]])
        self.bundle = build(cfg, core=CORE, load_core_lib=False)
        self.addCleanup(self.bundle.store.close)
        self.ctrl = self.bundle.controller
        self.assertIsNotNone(self.bundle.tls)  # the field CA, made on this first start
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "tls", "ca.key")))
        # The join's address (key 14): loopback, which the controller leaves out of its own list, by the
        # name its certificate always carries. Not 127.0.0.1: the host's mbedTLS (Debian's 2.28) checks only
        # DNS names; the firmware's (ESP-IDF 5.3, 3.6.2) also checks the address names a field uses.
        self.ctrl.link_urls = [f"https://localhost:{self.port}"]
        server = uvicorn.Server(uvicorn.Config(self.bundle.app, host="127.0.0.1", port=self.port, log_level="error",
                                               lifespan="on", ssl_certfile=str(self.bundle.tls.server_cert),
                                               ssl_keyfile=str(self.bundle.tls.server_key)))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(setattr, server, "should_exit", True)
        self.assertTrue(wait_for(lambda: server.started, 10))
        self.assertTrue(self.bundle.modem.wait_up(10))
        # The GM's own requests trust the field CA and nothing else, as a pinned phone does.
        ctx = ssl.create_default_context(cadata=self.bundle.tls.ca_pem.decode())
        self.http = httpx.Client(base_url=f"https://127.0.0.1:{self.port}", verify=ctx, timeout=10)
        self.addCleanup(self.http.close)
        self.assertEqual(self.http.get("/api/v1/controller/ca").headers["x-atalaia-ca-sha256"],
                         self.bundle.tls.ca_sha256.hex())

    def upload(self, archive: bytes, release: dict) -> None:
        r = self.http.post("/api/v1/mode-packages", params=query(release), content=archive,
                           headers={**GM, "Content-Type": "application/octet-stream"})
        self.assertEqual(r.status_code, 201, r.text)

    def box(self) -> BoxHost:
        b = BoxHost(self.hub, os.path.join(self.tmp, "box"), JOIN_KEY, state_ms=500, name="box",
                    extra=("--mode-keys", KEY["public_key"], "--mode-source", "https"))
        self.addCleanup(b.close)
        return b

    def join_fetching(self, box: BoxHost) -> int:
        r = self.http.post("/api/v1/games", headers=GM, json={"name": "fetch", "mode_id": TAGGER,
                                                               "teams": ["red", "blue"]})
        self.assertEqual(r.status_code, 201, r.text)
        r = self.http.post("/api/v1/join", headers=GM, json={"role": "zone", "fetch_modes": True})
        self.assertEqual(r.status_code, 200, r.text)
        box.join(r.json()["text"])
        return r.json()["node_id"]

    def fetch_state(self, node_id: int) -> dict:
        fetches = self.http.get("/api/v1/mode-fetch", headers=GM).json()["fetches"]
        return next((f for f in fetches if f["node_id"] == node_id), {})

    def fetched(self, box: BoxHost, result: str) -> None:
        self.assertTrue(wait_for(lambda: box.logged(f"FETCH result={result} part={TAGGER}"), 20), box.lines[-10:])

    def test_the_box_fetches_verifies_installs_and_reports(self):
        archive, release = package()
        self.upload(archive, release)
        box = self.box()
        nid = self.join_fetching(box)
        self.fetched(box, "installed")
        # The report went over HTTPS, the controller answered 200 and took it; then the box's HELLO.
        self.assertTrue(box.logged("REPORT atalaia-mode-report-v1|"), box.lines[-10:])
        self.assertTrue(box.logged("REPORT taken=yes"), box.lines[-10:])
        self.assertFalse(box.logged("LOG https:"), [line for line in box.lines if "https" in line])
        self.assertTrue(wait_for(lambda: self.fetch_state(nid).get("state") == "done", 10), self.fetch_state(nid))
        state = self.fetch_state(nid)
        self.assertEqual((state["installed"], state["kept"], state["reason"]), ([TAGGER], {TAGGER: "0.1.0"}, None))
        # Kept in its flash (mode_store), by the id and version the signed manifest gave.
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "box", "presets", "modes", TAGGER, "node.lua")),
                        sorted(os.listdir(os.path.join(self.tmp, "box"))))
        # The box is in the game now: the game starts with it and its mode runs.
        self.assertEqual(self.http.post("/api/v1/games/" + str(self.ctrl.game["id"]) + "/start", headers=GM,
                                        json={"force": True}).status_code, 200)
        self.assertTrue(wait_for(lambda: box.status()["phase"] == 2, 10))

    def test_a_join_with_another_field_ca_is_refused(self):
        archive, release = package()
        self.upload(archive, release)
        self.ctrl.ca_sha256 = bytes(32)  # the join pins a CA this controller's certificate does not chain to
        box = self.box()
        nid = self.join_fetching(box)
        self.fetched(box, "unreachable")
        self.assertTrue(box.logged("not the field CA of the join"), box.lines[-10:])
        self.assertFalse(box.logged("REPORT taken=yes"))
        # No byte of the package and no report over HTTPS: the box said it over LoRa (node.modes_failed).
        self.assertTrue(wait_for(lambda: (self.fetch_state(nid).get("state"), self.fetch_state(nid).get("reason"))
                                 == ("failed", "unreachable"), 15), self.fetch_state(nid))
        self.assertIsNone(self.fetch_state(nid)["kept"])
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "box", "presets", "modes", TAGGER)))

    def test_a_package_signed_by_a_key_the_box_lacks_is_refused(self):
        archive, release = package(key=OTHER_SIGNING)
        self.upload(archive, release)
        box = self.box()
        nid = self.join_fetching(box)
        self.fetched(box, "bad_signature")
        self.assertTrue(box.logged("REPORT taken=yes"), box.lines[-10:])
        self.assertTrue(wait_for(lambda: (self.fetch_state(nid).get("state"), self.fetch_state(nid).get("reason"))
                                 == ("failed", "bad_signature"), 10), self.fetch_state(nid))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "box", "presets", "modes", TAGGER)))

    def test_a_tampered_package_is_refused(self):
        archive, release = package()
        self.upload(archive, release)
        # The stored archive changed after it was signed (same size): the bytes are not the signed ones.
        changed = bytearray(archive)
        at = archive.index(b"presses")
        changed[at] ^= 0x20
        with self.bundle.store._lock:  # noqa: SLF001 (a test reaching under the API on purpose)
            self.bundle.store._exec("UPDATE modes SET package = ? WHERE id = ?", (bytes(changed), TAGGER))  # noqa: SLF001
        self.assertEqual(self.bundle.store.mode_package(TAGGER), bytes(changed))
        box = self.box()
        nid = self.join_fetching(box)
        self.fetched(box, "bad_hash")
        self.assertTrue(box.logged("REPORT taken=yes"), box.lines[-10:])
        self.assertTrue(wait_for(lambda: (self.fetch_state(nid).get("state"), self.fetch_state(nid).get("reason"))
                                 == ("failed", "bad_hash"), 10), self.fetch_state(nid))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "box", "presets", "modes", TAGGER)))


if __name__ == "__main__":
    unittest.main()
