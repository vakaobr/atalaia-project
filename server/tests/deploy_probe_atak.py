# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The deployment tests' TAK client (Phase 4 follow-up FU5): the remote ATAK relay through the stack.

Not a unittest module (no ``test_`` prefix): ``python3 tools/docker_server.py deploy`` and
``deploy-hosted`` run it in the test image, in a container on the deployment's public network (to reach
Caddy, every field's name pointing at it) and on its ``atak`` network (the relay's published port's
network), after the operator issued one data package per field with ``python -m atalaia_server atak
issue``:

    python -m tests.deploy_probe_atak

Settings: ATALAIA_PROBE_CA (Caddy's local root certificate), ATALAIA_PROBE_ATAK_RELAY (the relay's
host:port on the ``atak`` network) and ATALAIA_PROBE_ATAK_FIELDS (``host|API key|package path|password``
entries separated by ``;``). For each field: a connection without a client certificate is refused; the
field's device connects with its package (once the relay has loaded the CA the command made, within
its reload period); the field's controller (its API key, over the WebSocket through Caddy) says hello
with ``atak`` and pushes a box, which that device gets and every other field's device does not. Prints
one line per check; exit code 1 on the first failure.
"""

from __future__ import annotations

import io
import json
import os
import socket
import ssl
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from typing import Optional

from atalaia_controller import atak as cot
from atalaia_controller.ws_client import WebSocket
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12

from atalaia_server import atak_pki

from .deploy_probe import check

CA = os.environ.get("ATALAIA_PROBE_CA", "/ca.crt")
RELAY = os.environ.get("ATALAIA_PROBE_ATAK_RELAY", "")
CONTROLLER = {"id": "0192f3a4-5b6c-7d8e-9f01-23456789abcd", "version": "0.1.0"}


@dataclass
class Field:
    host: str
    key: str
    package: str
    password: str
    sock: Optional[ssl.SSLSocket] = None
    buf: bytes = b""

    def context(self, with_cert: bool = True) -> ssl.SSLContext:
        with open(self.package, "rb") as f, zipfile.ZipFile(io.BytesIO(f.read())) as z:
            client = pkcs12.load_pkcs12(z.read("certs/client.p12"), self.password.encode())
            trust = pkcs12.load_pkcs12(z.read("certs/truststore.p12"), atak_pki.TRUSTSTORE_PASSWORD.encode())
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.load_verify_locations(cadata=atak_pki.pem(trust.additional_certs[0].certificate))
        if with_cert:
            assert client.key is not None and client.cert is not None
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "c.pem")
                with open(path, "wb") as out:
                    out.write(client.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                       serialization.NoEncryption()))
                    out.write(client.cert.certificate.public_bytes(serialization.Encoding.PEM))
                ctx.load_cert_chain(path)
        return ctx

    def connect(self, with_cert: bool = True) -> ssl.SSLSocket:
        host, _, port = RELAY.rpartition(":")
        raw = socket.create_connection((host, int(port)), timeout=10)
        sock = self.context(with_cert).wrap_socket(raw, server_hostname=self.host)
        sock.settimeout(0.5)
        return sock

    def read(self, seconds: float) -> bool:
        """Reads for ``seconds``; False when the relay closed the connection."""
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


def fields() -> list[Field]:
    out = []
    for entry in os.environ.get("ATALAIA_PROBE_ATAK_FIELDS", "").split(";"):
        if entry:
            host, key, package, password = entry.split("|")
            out.append(Field(host, key, package, password))
    return out


def refused_without_a_certificate(field: Field) -> None:
    try:
        sock = field.connect(with_cert=False)
    except (ssl.SSLError, OSError):
        check(True, f"{field.host}: a connection without a client certificate is refused in the handshake")
        return
    try:
        sock.settimeout(5)
        data = sock.recv(1)
        check(data == b"", f"{field.host}: a connection without a client certificate is closed")
    except (ssl.SSLError, OSError):
        check(True, f"{field.host}: a connection without a client certificate is refused")
    finally:
        sock.close()


def accepted(field: Field, timeout: float = 60.0) -> None:
    """The device's certificate connects and stays (the relay loads a CA the command made within its reload
    period; until then OpenSSL refuses it)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            field.sock = field.connect()
            if field.read(2.0):
                version = field.sock.version()
                check(version in ("TLSv1.2", "TLSv1.3"), f"{field.host}: its device is connected over {version}")
                return
        except (ssl.SSLError, OSError):
            pass
        if field.sock is not None:
            field.sock.close()
            field.sock = None
        time.sleep(2)
    check(False, f"{field.host}: its device is connected within {timeout:.0f} s")


def push(field: Field, uid: str) -> None:
    ws = WebSocket.connect(f"wss://{field.host}/api/v1/sync/stream", {"Authorization": f"Bearer {field.key}"},
                           ca_file=CA)
    try:
        ws.send_text(json.dumps({"type": "hello", "sync_version": 1, "controller": CONTROLLER, "remote_gm": False,
                                 "atak": True}))
        answer = ws.recv(10.0)
        check(answer is not None and json.loads(answer) == {"type": "hello.ack", "remote_gm": False,
                                                            "atak_relay": True},
              f"{field.host}: the controller's hello through Caddy: the relay takes its events ({answer})")
        now = time.time()
        event = cot.event_xml(uid=uid, cot_type=cot.TYPE_PROP, how=cot.HOW_IMAGE, lat=38.72, lon=-9.14, now=now,
                              start=now, stale=now + 120, detail=cot.marker_detail("Caixa 7", "Atalaia: -", -1))
        ws.send_text(json.dumps({"type": "cot", "sync_version": 1, "controller": CONTROLLER,
                                 "events": [event.decode()]}))
        ws.send_text(json.dumps({"type": "ping"}))
        answer = ws.recv(10.0)
        check(answer is not None and json.loads(answer) == {"type": "pong"}, f"{field.host}: the cot was taken")
    finally:
        ws.close()


def main() -> None:
    every = fields()
    if not every or not RELAY:
        print("usage: ATALAIA_PROBE_ATAK_RELAY=host:port ATALAIA_PROBE_ATAK_FIELDS=... python -m "
              "tests.deploy_probe_atak", file=sys.stderr)
        sys.exit(2)
    for field in every:
        refused_without_a_certificate(field)
        accepted(field)
    for n, field in enumerate(every):
        uid = f"atalaia.probe-{n}.node.7"
        before = {f.host: len(f.buf) for f in every}
        push(field, uid)
        end = time.monotonic() + 10
        while uid.encode() not in field.buf and time.monotonic() < end:
            check(field.read(0.5), f"{field.host}: its device stays connected")
        check(uid.encode() in field.buf, f"{field.host}: its device got the box its controller pushed")
        for other in every:
            if other is not field:
                check(other.read(1.0), f"{other.host}: its device stays connected")
                check(uid.encode() not in other.buf[before[other.host]:],
                      f"{other.host}: its device did not get {field.host}'s box")
    for field in every:
        if field.sock is not None:
            field.sock.close()
    print("deploy_probe_atak: every check passed")


if __name__ == "__main__":
    main()
