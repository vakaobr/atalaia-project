# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The deployment test's client (plan phase 22): what a browser and a field controller see through Caddy.

Not a unittest module (no ``test_`` prefix): ``python3 tools/docker_server.py
deploy`` runs it in the test image, in a container on the deployment's
public network only, with the site's name pointing at Caddy:

    python -m tests.deploy_probe before|after

Settings: ATALAIA_PROBE_HOST (the site's name), ATALAIA_PROBE_CA (Caddy's
local root certificate), ATALAIA_PROBE_KEY (a field API key the test wrote
to the database), ATALAIA_PROBE_CLOSED (host:port pairs that must not answer:
the database and the server's own port). ``before`` checks HTTPS, the
headers, the redirect, the closed ports, a failed login (for the client's
address in the audit log) and the sync over the WebSocket through Caddy,
which stores a game with two events; ``after`` (once the backup is restored
into a fresh database) checks that the same key still works and the same
events are already there. Prints one line per check; exit code 1 on the
first failure.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import warnings

import httpx

from atalaia_controller.ws_client import WebSocket, WsError

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from .test_sync import META, adjustment, envelope, event

HOST = os.environ.get("ATALAIA_PROBE_HOST", "atalaia.test")
CA = os.environ.get("ATALAIA_PROBE_CA", "/ca.crt")
KEY = os.environ.get("ATALAIA_PROBE_KEY", "")
CLOSED = [p for p in os.environ.get("ATALAIA_PROBE_CLOSED", "").split(",") if p]
BATCH = {"type": "events", **envelope(after_id=0, events=[event(1), adjustment(2, "red", -20)])}


def check(ok: bool, what: str) -> None:
    print(f"deploy_probe: {'ok  ' if ok else 'FAIL'} {what}", flush=True)
    if not ok:
        sys.exit(1)


def stream(key: str) -> WebSocket:
    return WebSocket.connect(f"wss://{HOST}/api/v1/sync/stream", {"Authorization": f"Bearer {key}"}, ca_file=CA)


def ask(ws: WebSocket, msg: dict) -> dict:
    ws.send_text(json.dumps(msg))
    answer = ws.recv(10.0)
    if answer is None:
        check(False, f"an answer to {msg['type']} within 10 s")
    return json.loads(answer)


def https_checks(client: httpx.Client) -> None:
    r = client.get(f"https://{HOST}/api/v1/health")
    check(r.status_code == 200 and r.json().get("status") == "ok",
          f"GET /api/v1/health over HTTPS: {r.status_code}")
    check(r.http_version in ("HTTP/1.1", "HTTP/2"), f"answered over {r.http_version}")
    h = r.headers
    check(h.get("strict-transport-security", "").startswith("max-age="), "HSTS (from the server)")
    check("default-src 'self'" in h.get("content-security-policy", ""), "the content security policy (from the server)")
    check(h.get("x-content-type-options") == "nosniff", "nosniff (from the server)")
    check("camera=()" in h.get("permissions-policy", ""), "Permissions-Policy (from Caddy)")
    check(h.get("cross-origin-opener-policy") == "same-origin", "Cross-Origin-Opener-Policy (from Caddy)")
    check("server" not in h and "via" not in h,
          f"no Server or Via header (got {h.get('server')!r}, {h.get('via')!r})")
    with httpx.Client(verify=ssl.create_default_context(), timeout=10) as public:
        try:
            public.get(f"https://{HOST}/api/v1/health")
            check(False, "the system's CAs must not trust Caddy's local test CA")
        except httpx.ConnectError:
            check(True, "the certificate is Caddy's own CA's, which only the test trusts")
    r = client.get(f"https://{HOST}/staff/login")
    check(r.status_code == 200 and '<script type="module" src="/static/staff/login.js">' in r.text
          and h.get("content-security-policy") == r.headers.get("content-security-policy"),
          f"GET /staff/login through Caddy, under the same policy: {r.status_code}")
    r = client.get(f"https://{HOST}/static/staff/staff.js")
    check(r.status_code == 200 and r.headers.get("content-type", "").startswith("text/javascript"),
          f"the staff pages' script through Caddy: {r.status_code}")
    r = httpx.get(f"http://{HOST}/api/v1/health", timeout=10)
    check(r.status_code in (301, 308) and r.headers.get("location") == f"https://{HOST}/api/v1/health",
          f"HTTP redirects to HTTPS: {r.status_code} {r.headers.get('location')}")


def closed_checks() -> None:
    for pair in CLOSED:
        host, _, port = pair.rpartition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=3):
                reached = True
        except OSError:
            reached = False
        check(not reached, f"{pair} cannot be reached from the public network")


def before() -> None:
    with httpx.Client(verify=CA, timeout=10) as client:
        https_checks(client)
        r = client.post(f"https://{HOST}/api/v1/auth/login", json={"username": "nobody-here", "password": "wrong"})
        check(r.status_code == 401, f"a wrong login is refused through Caddy: {r.status_code}")
    closed_checks()
    try:
        stream("A" * 43)
        check(False, "a wrong API key is refused")
    except WsError as exc:
        check(exc.status == 403 or exc.code == 4401, f"a wrong API key is refused ({exc})")
    ws = stream(KEY)
    try:
        check(ask(ws, {"type": "ping"}) == {"type": "pong"}, "WebSocket through Caddy: ping, pong")
        check(ask(ws, {"type": "games", **envelope(meta=META)})["type"] == "games.ack", "the game synced")
        got = ask(ws, BATCH)
        check(got == {"type": "events.ack", "acked_id": 2, "inserted": 2, "duplicates": 0}, f"two events stored: {got}")
        got = ask(ws, {"type": "scores", **envelope(counters={"node-3": {"red": 50}})})
        check(got.get("totals") == {"red": 30, "blue": 0}, f"the scores: {got}")
    finally:
        ws.close()


def after() -> None:
    with httpx.Client(verify=CA, timeout=10) as client:
        https_checks(client)
    ws = stream(KEY)
    try:
        check(ask(ws, {"type": "ping"}) == {"type": "pong"}, "the restored API key works over the WebSocket")
        got = ask(ws, BATCH)
        check(got == {"type": "events.ack", "acked_id": 2, "inserted": 0, "duplicates": 2},
              f"the restored game already has both events: {got}")
    finally:
        ws.close()


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("before", "after") or not KEY:
        print("usage: ATALAIA_PROBE_KEY=... python -m tests.deploy_probe before|after", file=sys.stderr)
        sys.exit(2)
    before() if sys.argv[1] == "before" else after()
    print(f"deploy_probe: {sys.argv[1]}: every check passed")
