# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The hosted deployment test's client (Phase 4 follow-up, decisions FU4-*): a hub's fields through Caddy.

Not a unittest module (no ``test_`` prefix): ``python3 tools/docker_server.py
deploy-hosted`` runs it in the test image, in a container on the deployment's
public network only, with every name below pointing at Caddy:

    python -m tests.deploy_probe_hosted before|after

Settings: ATALAIA_PROBE_DOMAIN (the hub's domain), ATALAIA_PROBE_CA (Caddy's
local root certificate), ATALAIA_PROBE_FIELDS (``slug=API key=Field name``
entries separated by ``;``: the active fields), ATALAIA_PROBE_REFUSED (names
that must get no certificate: an unknown field, a suspended one, the hub's
own name) and ATALAIA_PROBE_CLOSED (host:port pairs that must not answer).

Both phases check, for each field, that its own name gets a certificate of
its own from Caddy (on-demand TLS, issued for that name only) and serves that
field: its public page, its controller's API key (over HTTP and the
WebSocket), and nothing of the other field (the other field's page 404, the
other field's key 401 and refused on the socket); that the refused names get
no certificate (the ask endpoint said no) and that a request for an unknown
field that reaches the server anyway (a known name in TLS, another in the
Host header) gets 404 ``unknown_field``. ``before`` syncs a game with two
events into each field; ``after`` (once the backup is restored into a fresh
stack) finds them already there.
"""

from __future__ import annotations

import os
import socket
import ssl
import sys
from dataclasses import dataclass

import httpx

from atalaia_controller.ws_client import WebSocket, WsError

from .deploy_probe import BATCH, ask, check, closed_checks
from .test_sync import META, envelope

DOMAIN = os.environ.get("ATALAIA_PROBE_DOMAIN", "hub.test")
CA = os.environ.get("ATALAIA_PROBE_CA", "/ca.crt")
REFUSED = [n for n in os.environ.get("ATALAIA_PROBE_REFUSED", "").split(",") if n]


@dataclass
class Field:
    slug: str
    key: str
    name: str

    @property
    def host(self) -> str:
        return f"{self.slug}.{DOMAIN}"


def fields() -> list[Field]:
    out = []
    for entry in os.environ.get("ATALAIA_PROBE_FIELDS", "").split(";"):
        if entry:
            slug, key, name = entry.split("=", 2)
            out.append(Field(slug, key, name))
    return out


def handshake(server_name: str) -> dict:
    """The certificate Caddy presents for a name (verified against its root), or an ssl.SSLError."""
    context = ssl.create_default_context(cafile=CA)
    with socket.create_connection((server_name, 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=server_name) as tls:
            return tls.getpeercert() or {}


def raw_request(server_name: str, host_header: str, path: str) -> tuple[int, str]:
    """One HTTPS request whose TLS name and Host header differ (what a misrouted request would be)."""
    context = ssl.create_default_context(cafile=CA)
    context.set_alpn_protocols(["http/1.1"])
    with socket.create_connection((server_name, 443), timeout=10) as raw:
        with context.wrap_socket(raw, server_hostname=server_name) as tls:
            tls.sendall(f"GET {path} HTTP/1.1\r\nHost: {host_header}\r\nConnection: close\r\n\r\n".encode())
            data = b""
            while chunk := tls.recv(65536):
                data += chunk
    head, _, body = data.partition(b"\r\n\r\n")
    return int(head.split(b" ", 2)[1]), body.decode("utf-8", "replace")


def certificate_checks(field: Field) -> None:
    cert = handshake(field.host)
    names = {value for kind, value in cert.get("subjectAltName", ()) if kind == "DNS"}
    check(names == {field.host}, f"{field.host} has a certificate of its own, for that name only: {sorted(names)}")


def refused_checks(known: Field) -> None:
    for name in REFUSED:
        try:
            handshake(name)
            check(False, f"{name} must get no certificate")
        except (ssl.SSLError, ConnectionError) as exc:
            check(True, f"{name} gets no certificate (the ask endpoint said no: {type(exc).__name__})")
    status, body = raw_request(known.host, f"nobody.{DOMAIN}", "/api/v1/fields")
    check(status == 404 and "unknown_field" in body,
          f"an unknown field's name in the Host header reaches the server and gets 404 unknown_field: {status}")


def stream(field: Field, key: str) -> WebSocket:
    return WebSocket.connect(f"wss://{field.host}/api/v1/sync/stream", {"Authorization": f"Bearer {key}"},
                             ca_file=CA)


def field_checks(client: httpx.Client, field: Field, other: Field) -> None:
    base = f"https://{field.host}"
    r = client.get(f"{base}/api/v1/health")
    check(r.status_code == 200 and "camera=()" in r.headers.get("permissions-policy", "")
          and r.headers.get("strict-transport-security", "").startswith("max-age="),
          f"{field.host}: HTTPS through Caddy, with the server's and Caddy's headers: {r.status_code}")
    r = client.get(f"{base}/f/{field.slug}/")
    check(r.status_code == 200 and field.name in r.text, f"{field.host} serves its own field's page: {r.status_code}")
    r = client.get(f"{base}/f/{other.slug}/")
    check(r.status_code == 404, f"{field.host} knows nothing of {other.slug}'s page: {r.status_code}")
    r = client.get(f"{base}/api/v1/sync/field", headers={"Authorization": f"Bearer {field.key}"})
    check(r.status_code == 200, f"{field.host}: its own controller's key works: {r.status_code}")
    r = client.get(f"{base}/api/v1/sync/field", headers={"Authorization": f"Bearer {other.key}"})
    check(r.status_code == 401, f"{field.host}: {other.slug}'s key is unknown there: {r.status_code}")
    r = httpx.get(f"http://{field.host}/api/v1/health", timeout=10)
    check(r.status_code in (301, 308) and r.headers.get("location") == f"https://{field.host}/api/v1/health",
          f"{field.host}: HTTP redirects to HTTPS: {r.status_code}")
    try:
        stream(field, other.key)
        check(False, f"{field.host}: {other.slug}'s key must be refused on the socket")
    except WsError as exc:
        check(exc.status == 403 or exc.code == 4401, f"{field.host}: {other.slug}'s key refused on the socket ({exc})")


def sync(field: Field, first: bool) -> None:
    ws = stream(field, field.key)
    try:
        check(ask(ws, {"type": "ping"}) == {"type": "pong"}, f"{field.host}: WebSocket through Caddy")
        if first:
            check(ask(ws, {"type": "games", **envelope(meta=META)})["type"] == "games.ack", f"{field.host}: game")
        got = ask(ws, BATCH)
        want = {"type": "events.ack", "acked_id": 2, "inserted": 2 if first else 0, "duplicates": 0 if first else 2}
        check(got == want, f"{field.host}: {'two events stored' if first else 'both events already there'}: {got}")
    finally:
        ws.close()


def run(phase: str) -> None:
    hub = fields()
    if len(hub) < 2:
        check(False, "ATALAIA_PROBE_FIELDS names two fields or more")
    with httpx.Client(verify=CA, timeout=10) as client:
        for i, field in enumerate(hub):
            other = hub[(i + 1) % len(hub)]
            certificate_checks(field)
            field_checks(client, field, other)
            sync(field, phase == "before")
    refused_checks(hub[0])
    closed_checks()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("before", "after"):
        print("usage: ATALAIA_PROBE_FIELDS=... python -m tests.deploy_probe_hosted before|after", file=sys.stderr)
        sys.exit(2)
    run(sys.argv[1])
    print(f"deploy_probe_hosted: {sys.argv[1]}: every check passed")
