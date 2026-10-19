# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field CA and the controller's HTTPS (ADR-P3-9, P3-8): made once, kept, its fingerprint on the
poster and in join payloads (key 13), the server certificate for the controller's names, renewed
when they change or it is about to expire, and a real TLS connection pinned to the CA only.

    cd controller && python -m unittest discover -s tests
"""

from __future__ import annotations

import datetime
import hashlib
import os
import socket
import ssl
import stat
import tempfile
import threading
import unittest

import httpx
import uvicorn

from support import CORE, config, free_port, wait_for
from atalaia_controller import tls
from atalaia_controller.main import build, poster_urls
from atalaia_sim import join


class FieldCaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "tls")

    def tearDown(self):
        self.tmp.cleanup()

    def test_made_once_and_kept(self):
        a = tls.ensure(self.dir, ["10.42.0.1", "atalaia.local"], "Campo Norte")
        b = tls.ensure(self.dir, ["10.42.0.1", "atalaia.local"], "Campo Norte")
        self.assertEqual(a.ca_sha256, b.ca_sha256)
        self.assertEqual(a.ca_sha256, hashlib.sha256(a.ca_der).digest())
        cert_a = a.server_cert.read_bytes()
        self.assertEqual(cert_a, b.server_cert.read_bytes())  # nothing changed: not made again
        c = tls.ensure(self.dir, ["10.42.0.2", "atalaia.local"], "Campo Norte")
        self.assertEqual(c.ca_sha256, a.ca_sha256)  # the CA stays (pinned phones keep working)
        self.assertNotEqual(c.server_cert.read_bytes(), cert_a)  # new names: a new server certificate
        if os.name == "posix":
            for name in ("ca.key", "server.key"):
                self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, name)).st_mode), 0o600)

    def test_names_and_renewal(self):
        from cryptography import x509

        a = tls.ensure(self.dir, ["10.0.2.2", "atalaia.local"])
        first = a.server_cert.read_bytes()
        cert = x509.load_pem_x509_certificate(first)
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        self.assertEqual([str(i) for i in san.get_values_for_type(x509.IPAddress)], ["10.0.2.2"])
        self.assertEqual(san.get_values_for_type(x509.DNSName), ["atalaia.local"])
        ca = x509.load_pem_x509_certificate(a.ca_pem)
        self.assertTrue(ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca)
        later = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=340)
        b = tls.ensure(self.dir, ["10.0.2.2", "atalaia.local"], now=later)
        self.assertNotEqual(b.server_cert.read_bytes(), first)  # under 30 days left

    def test_local_names(self):
        names = tls.local_names(["campo.example"])
        self.assertEqual(names[0], "campo.example")
        self.assertIn("localhost", names)
        self.assertIn("127.0.0.1", names)
        self.assertNotIn("0.0.0.0", names)

    def test_poster_urls(self):
        cfg = config(self.tmp.name, tls_names=["10.42.0.1", "fd00::1"])
        fake = tls.FieldTls(None, b"", b"\0" * 32, None, None, ["10.42.0.1", "fd00::1", "localhost", "x.local"])
        self.assertEqual(poster_urls(cfg, fake),
                         ["https://10.42.0.1:8443", "https://[fd00::1]:8443", "https://x.local:8443"])


class HttpsServerTests(unittest.TestCase):
    """The whole controller on HTTPS, as `run` serves it, reached with only the field CA trusted."""

    def test_pinned_tls_connection_and_join_key_13(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        port = free_port()
        cfg = config(tmp.name, tls_port=port, api_port=free_port(), tls_names=["127.0.0.1"],
                     join_key=bytes(range(32)).hex())
        bundle = build(cfg, core=CORE, load_core_lib=False)
        self.addCleanup(bundle.store.close)
        server = uvicorn.Server(uvicorn.Config(bundle.app, host="127.0.0.1", port=port, log_level="error",
                                               ssl_certfile=str(bundle.tls.server_cert),
                                               ssl_keyfile=str(bundle.tls.server_key), lifespan="off"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(setattr, server, "should_exit", True)
        self.assertTrue(wait_for(lambda: server.started, 10))
        ca_file = os.path.join(tmp.name, "pinned-ca.pem")
        with open(ca_file, "wb") as f:
            f.write(bundle.tls.ca_pem)
        ctx = ssl.create_default_context(cafile=ca_file)  # the field CA and nothing else
        with httpx.Client(base_url=f"https://127.0.0.1:{port}", verify=ctx, timeout=10) as http:
            r = http.get("/api/v1/controller/ca")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.headers["x-atalaia-ca-sha256"], bundle.tls.ca_sha256.hex())
            info = http.get("/api/v1/checkin").json()
            self.assertEqual(info["field"]["id"], "field")
            gm = {"Authorization": "Bearer gm-secret"}
            g = http.post("/api/v1/games", headers=gm, json={"name": "TLS", "mode_id": "org.atalaia.domination",
                                                              "teams": ["red", "blue"]}).json()
            j = http.post("/api/v1/join", headers=gm, json={"role": "zone"}).json()
            self.assertTrue(j["wifi_link"])
            payload = join.decode(bytes.fromhex(j["payload_hex"]), bytes(range(32)))
            self.assertEqual(payload["ca_sha256"], bundle.tls.ca_sha256)
            self.assertEqual(payload["game_id"], g["id"])
            self.assertTrue(all(u.startswith("https://") for u in payload["urls"]))
        # A client that does not trust the field CA is refused.
        with httpx.Client(base_url=f"https://127.0.0.1:{port}", timeout=10) as http, \
                self.assertRaises(httpx.ConnectError):
            http.get("/healthz")
        # Plain sockets cannot speak HTTP to the TLS port either.
        with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
            s.sendall(b"GET /healthz HTTP/1.0\r\n\r\n")
            self.assertNotIn(b"200 OK", s.recv(100))


if __name__ == "__main__":
    unittest.main()
