# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""End to end: the real controller's CoT through the real site server to an enrolled TAK client (FU5).

The site server runs under uvicorn on 127.0.0.1 (its WebSocket through wsproto, as in the image) with
its ATAK relay on; the controller's engine runs a Domination game with a georeferenced field image, a
box placed on it and a player's GPS fix, with ``[atak] enabled``, ``remote`` and ``remote_players`` on
and no multicast. Its ``RemoteGm`` thread opens the stream (the controller opens the connection) and
its ``AtakEmitter`` pushes the box and the player on it. Two devices enrolled through the API with a
gm's TOTP session (one for a gm with positions, one for a player without) connect with the standard
library's TLS to the relay: the gm's device gets the box and the player, the player's device the box
only; a device without a certificate is refused; a revoked one is closed at once. A second site server
with the relay off (the default) tells the controller so, and nothing is sent.

    python3 tools/docker_server.py test tests.test_atak_e2e
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import socket
import ssl
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Optional

from atalaia_controller import atak as cot
from atalaia_controller import georef
from atalaia_controller.atak import AtakEmitter
from atalaia_controller.config import Config
from atalaia_controller.engine import Controller
from atalaia_controller.remote_gm import RemoteGm
from atalaia_controller.store import Store
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from atalaia_server import atak_pki, passwords, sync, totp

from .base import PASSWORD, TempDatabase
from .test_sync_e2e import CORE, DOMINATION, REPO, SiteServer

for name in ("atalaia.remote_gm", "atalaia.atak", "atalaia.atak_relay"):
    logging.getLogger(name).setLevel(logging.CRITICAL)
CONTROLLER_ID = "0192f3a4-5b6c-7d8e-9f01-23456789abcd"
HOST = "campo.test"
TL = georef.ControlPoint(0.0, 0.0, 38.7240, -9.1420)
BR = georef.ControlPoint(1.0, 1.0, 38.7200, -9.1360)
PLAYER = "p-abcdefghijk2"


def wait(predicate: Any, timeout: float = 15.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


class Device:
    """A TAK client from its data package, on a blocking TLS socket."""

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer
        with zipfile.ZipFile(io.BytesIO(base64.b64decode(answer["package"]["base64"]))) as z:
            client = pkcs12.load_pkcs12(z.read("certs/client.p12"), answer["password"].encode())
            trust = pkcs12.load_pkcs12(z.read("certs/truststore.p12"), atak_pki.TRUSTSTORE_PASSWORD.encode())
        assert client.key is not None and client.cert is not None
        self.pem = client.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()) + \
            client.cert.certificate.public_bytes(serialization.Encoding.PEM)
        self.ca = atak_pki.pem(trust.additional_certs[0].certificate)
        self.sock: Optional[ssl.SSLSocket] = None
        self.buf = b""

    def context(self, with_cert: bool = True) -> ssl.SSLContext:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cadata=self.ca)
        if with_cert:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "c.pem")
                with open(path, "wb") as f:
                    f.write(self.pem)
                ctx.load_cert_chain(path)
        return ctx

    def connect(self, port: int, with_cert: bool = True) -> None:
        raw = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.sock = self.context(with_cert).wrap_socket(raw, server_hostname=HOST)
        self.sock.settimeout(1.0)

    def pump(self, seconds: float) -> bool:
        """Reads for ``seconds``; False once the relay closed the connection."""
        assert self.sock is not None
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            try:
                data = self.sock.recv(65536)
            except socket.timeout:
                continue
            except (ssl.SSLError, OSError):
                return False
            if not data:
                return False
            self.buf += data
        return True

    def uids(self) -> set[str]:
        out = set()
        for part in self.buf.split(b"</event>")[:-1]:
            text = (part + b"</event>").decode("utf-8")
            assert text.startswith(cot.XML_DECL)
            out.add(ET.fromstring(text[len(cot.XML_DECL):]).get("uid"))
        return out

    def close(self) -> None:
        if self.sock is not None:
            self.sock.close()
            self.sock = None


class AtakRelayEndToEndTests(unittest.TestCase):
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
        self.devices: list[Device] = []

    def tearDown(self) -> None:
        for d in self.devices:
            d.close()
        self.db.fetch("TRUNCATE fields, users RESTART IDENTITY CASCADE")
        self.tmp.cleanup()

    def start_site(self, relay: bool) -> SiteServer:
        site = SiteServer(self.db.url, public_url=f"https://{HOST}", atak_relay=relay, atak_relay_port=0)
        site.__enter__()
        self.addCleanup(site.__exit__, None, None, None)
        return site

    def api(self, site: SiteServer, method: str, path: str, body: Any = None, token: str = "") -> tuple[int, Any]:
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
        req = urllib.request.Request(site.url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.status, json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"null")

    def account(self, site: SiteServer, name: str, role: int, login: bool = True) -> str:
        secret = totp.new_secret()
        digest = asyncio.run(passwords.hash_password(PASSWORD))
        sealed = site.app.state.seed_box.seal(secret)
        user = self.db.fetch("INSERT INTO users (username, password_hash, totp_enabled, totp_secret_enc) "
                             "VALUES ($1, $2, true, $3) RETURNING id", name, digest, sealed)[0][0]
        self.db.fetch("INSERT INTO user_field_roles (user_id, field_id, role_id) VALUES ($1, $2, $3)", user,
                      self.field, role)
        if not login:
            return ""
        status, step = self.api(site, "POST", "/api/v1/auth/login", {"username": name, "password": PASSWORD})
        self.assertEqual(status, 200, step)
        status, out = self.api(site, "POST", "/api/v1/auth/login/totp",
                               {"totp_session": step["totp_session"], "code": totp.code_at(secret, time.time())})
        self.assertEqual(status, 200, out)
        return str(out["access_token"])

    def enrol(self, site: SiteServer, token: str, **body: Any) -> Device:
        status, answer = self.api(site, "POST", f"/api/v1/fields/{self.field}/atak/certificates", body, token)
        self.assertEqual(status, 201, answer)
        d = Device(answer)
        self.devices.append(d)
        return d

    def controller(self, site: SiteServer) -> tuple[Store, Controller, RemoteGm, AtakEmitter]:
        cfg = Config(db_path=os.path.join(self.tmp.name, "controller.db"), mqtt_enabled=False,
                     modes_dirs=[str(REPO / "modes")], sync_enabled=True, sync_url=site.url, sync_api_key=self.key,
                     sync_timeout_s=5.0, atak_enabled=True, atak_multicast="", atak_interval_s=1.0, atak_remote=True,
                     atak_remote_players=True)
        cfg.validate()
        store = Store(cfg.db_path)
        ctrl = Controller(cfg, store, core=CORE)
        remote = RemoteGm(cfg, store, ctrl, api_key=self.key, controller_id=lambda: CONTROLLER_ID)
        ctrl.add_listener(remote.on_controller_message)
        emitter = AtakEmitter(cfg, ctrl, remote=remote)
        self.addCleanup(store.close)
        self.addCleanup(ctrl.stop)
        self.addCleanup(remote.stop)
        self.addCleanup(emitter.stop)
        gid = ctrl.create_game({"name": "Domingo", "mode_id": DOMINATION, "teams": ["red", "blue"],
                                "assignments": {"3": "zone"}})["id"]
        ctrl.start_game(gid, force=True)
        georef.save(store, georef.Georef([TL, BR]))
        store.set_position(gid, 3, 0.5, 0.5)
        now = time.time()
        store.set_player_position(gid, PLAYER, {"lat": 38.7221, "lon": -9.1391, "accuracy_m": 6.0, "source": "gps",
                                                "team": 1, "received_at": now}, now)
        remote.start()
        emitter.start()
        return store, ctrl, remote, emitter

    def test_cot_from_the_controller_to_enrolled_devices(self) -> None:
        site = self.start_site(relay=True)
        port = site.app.state.atak_relay.port
        gm = self.account(site, "gm-norte", 5)
        self.account(site, "jogador", 1, login=False)
        staff = self.enrol(site, gm, device_name="Posto de comando", positions=True)
        plain = self.enrol(site, gm, device_name="Telemóvel", holder="jogador")
        staff.connect(port)
        plain.connect(port)
        # No certificate: refused in the handshake (or closed before a byte).
        stranger = Device(staff.answer)
        try:
            stranger.connect(port, with_cert=False)
            self.assertFalse(stranger.pump(2.0))
        except (ssl.SSLError, OSError):
            pass
        finally:
            stranger.close()
        _, _, remote, emitter = self.controller(site)
        self.assertTrue(wait(lambda: remote.atak_relay), remote.status())
        box, player = "atalaia.field.node.3", f"atalaia.field.player.{PLAYER}"
        self.assertTrue(wait(lambda: staff.pump(0.2) and {box, player} <= staff.uids()), staff.buf[:400])
        self.assertTrue(wait(lambda: plain.pump(0.2) and box in plain.uids()), plain.buf[:400])
        self.assertTrue(plain.pump(2.5))  # two more full cycles of the emitter: still no position for the player
        self.assertNotIn(player, plain.uids())
        self.assertGreater(emitter.status()["remote_events"], 0)
        self.assertGreater(remote.status()["atak"]["sent"], 0)
        # Revoked: the relay closes the connection at once.
        status, out = self.api(site, "POST", f"/api/v1/fields/{self.field}/atak/certificates/"
                               f"{staff.answer['certificate']['id']}/revoke", {}, gm)
        self.assertEqual((status, out["closed"]), (200, 1), out)
        self.assertTrue(wait(lambda: not staff.pump(0.2), 5.0))
        rows = self.db.fetch("SELECT action FROM audit_log WHERE action LIKE 'atak_%' ORDER BY id")
        self.assertEqual([r[0] for r in rows], ["atak_cert_issued", "atak_cert_issued", "atak_connect",
                                                "atak_connect", "atak_cert_revoked"])

    def test_the_relay_is_off_by_default(self) -> None:
        site = self.start_site(relay=False)
        self.assertIsNone(site.app.state.atak_relay)
        _, _, remote, emitter = self.controller(site)
        self.assertTrue(wait(lambda: remote.connected))
        time.sleep(2.5)  # two full cycles of the emitter
        self.assertFalse(remote.atak_relay)
        self.assertEqual((emitter.status()["remote_events"], remote.status()["atak"]["sent"]), (0, 0))


if __name__ == "__main__":
    unittest.main()
