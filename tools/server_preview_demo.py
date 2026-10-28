#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The preview's live demo, end to end (decisions DEMO-*): `python3 tools/docker_server.py preview-demo`.

Brings the preview stack up in a scratch Compose project (its own name, ports, subnets, images and volumes; the real
preview is never touched), with the demo's pace shortened (a game is a minute), and checks what the demo promises:

 1. the stack is healthy and the demo's read-only proxy answers on its own port, 127.0.0.1 only;
 2. a game is played on its own: the simulated boxes join, players check in, the game runs, scores rise, positions
    and the chronograph's readings exist (seen through the player's view), the game ends and another begins;
 3. nothing can be changed through the proxy: every method but GET is refused, the controller's own write and staff
    endpoints are not there, a wrong token or none gets 401, the WebSocket is one way (what is sent on it changes
    nothing) and refuses a bad token; the GM token is unknown to anyone but the demo itself;
 4. nothing personal: every name any read endpoint shows is one of the made-up callsigns; no e-mail address, telephone
    number or address-like text is in anything a visitor can read;
 5. the site server shows the demo: its landing page links to it, and the live demo field's public page and scoreboard
    show the games the simulated controller synced (also a finished game's scores);
 6. it restarts cleanly: after a restart of the demo container a game that was running is ended, boxes rejoin, and a
    new game is played; the old games are not listed any more (a fresh controller database).
Everything it made is removed at the end, whatever the result.
"""

from __future__ import annotations

import json
import os
import random
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "server"
SUFFIX = os.environ.get("ATALAIA_VOLUME_SUFFIX", "").lower()
PROJECT = f"atalaia-preview-demo{SUFFIX}"
READ_TOKEN = "atalaia-demo"
PACE = {"ATALAIA_DEMO_LOBBY_S": "4", "ATALAIA_DEMO_GAME_S": "45", "ATALAIA_DEMO_PAUSE_S": "8"}

sys.path.insert(0, str(SERVER / "preview" / "demo" / "field"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def free_subnets() -> tuple[str, str]:
    """Two neighbouring /24 subnets that overlap no Docker network that exists now."""
    import ipaddress  # noqa: PLC0415

    taken = subprocess.run(["docker", "network", "ls", "-q"], capture_output=True, text=True).stdout.split()
    nets = []
    if taken:
        for net in json.loads(subprocess.run(["docker", "network", "inspect", *taken], capture_output=True, text=True).stdout):
            for cfg in (net.get("IPAM") or {}).get("Config") or []:
                if cfg.get("Subnet"):
                    nets.append(ipaddress.ip_network(cfg["Subnet"], strict=False))
    while True:
        n = random.randint(100, 240)
        a, b = ipaddress.ip_network(f"172.30.{n}.0/24"), ipaddress.ip_network(f"172.30.{n + 1}.0/24")
        if not any(a.overlaps(t) or b.overlaps(t) for t in nets):
            return str(a), str(b)


class Check:
    def __init__(self) -> None:
        self.failures: list[str] = []

    def ok(self, condition: bool, what: str) -> bool:
        print(("  ok    " if condition else "  FAIL  ") + what, flush=True)
        if not condition:
            self.failures.append(what)
        return condition


def get(url: str, token: Optional[str] = None, method: str = "GET", data: Optional[bytes] = None,
        timeout: float = 15) -> tuple[int, bytes]:
    req = urllib.request.Request(url, method=method, data=data)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def jget(url: str, token: Optional[str] = READ_TOKEN) -> Any:
    code, body = get(url, token)
    return json.loads(body) if code == 200 else None


def wait(predicate, seconds: float, step: float = 2.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


WS_PROBE = r"""
import asyncio, json, sys, websockets
async def main():
    out = {}
    url = "ws://127.0.0.1:8001/api/v1/stream"
    async with websockets.connect(url + "?token=atalaia-demo") as ws:
        out["hello"] = json.loads(await asyncio.wait_for(ws.recv(), 10)).get("type")
        for text in ('{"type":"ping"}', '{"cmd":"end"}', 'x'):
            await ws.send(text)
        await asyncio.sleep(1)
        out["still_open"] = ws.open
    for bad in ("?token=wrong", "", "?token=" + sys.argv[1]):
        try:
            async with websockets.connect(url + bad) as ws:
                await asyncio.wait_for(ws.recv(), 3)
                out["bad_" + bad] = "accepted"
        except Exception as exc:
            out["bad_" + bad] = "refused"
    print(json.dumps(out))
asyncio.run(main())
"""


def unit() -> int:
    """`preview-demo-unit`: the demo's own tests (server/preview/demo/field/test_demo.py), run in the demo's image."""
    image = f"atalaia-demo{SUFFIX}"
    build = subprocess.run(["docker", "build", "-f", str(SERVER / "preview" / "demo" / "Dockerfile"), "-t", image, str(REPO)])
    if build.returncode != 0:
        return build.returncode
    try:
        return subprocess.run(["docker", "run", "--rm", "--network", "none", image,
                               "python3", "-m", "unittest", "discover", "-s", "/app/demo", "-v"]).returncode
    finally:
        subprocess.run(["docker", "image", "rm", "-f", image], capture_output=True)


def main() -> int:
    check = Check()
    tmp = Path(tempfile.mkdtemp(prefix="atalaia-demo-check-"))
    env_file = tmp / "preview.env"
    port, dport = free_port(), free_port()
    sub_a, sub_b = free_subnets()
    server_image, demo_image = f"atalaia-server{SUFFIX}", f"atalaia-demo{SUFFIX}"
    lines = {
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24), "ATALAIA_SECRET_KEY": secrets.token_urlsafe(32),
        "ATALAIA_DOMAIN": "preview.test", "ATALAIA_BIND": "127.0.0.1", "ATALAIA_PREVIEW": "on",
        "ATALAIA_PREVIEW_PORT": str(port), "ATALAIA_DEMO_PORT": str(dport),
        "ATALAIA_PUBLIC_URL": f"http://127.0.0.1:{port}", "ATALAIA_DEMO_PUBLIC_URL": f"http://127.0.0.1:{dport}",
        "ATALAIA_SERVER_IMAGE": server_image, "ATALAIA_DEMO_IMAGE": demo_image,
        "ATALAIA_PREVIEW_SUBNET": sub_a, "ATALAIA_DEMO_SUBNET": sub_b, **PACE}
    fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("".join(f"{k}={v}\n" for k, v in lines.items()))

    def dc(*args: str, check_rc: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", "compose", "--env-file", str(env_file), "-p", PROJECT,
                               "-f", str(SERVER / "docker-compose.yml"), "-f", str(SERVER / "docker-compose.preview.yml"),
                               *args], check=check_rc, capture_output=capture, text=True)

    base, site = f"http://127.0.0.1:{dport}", f"http://127.0.0.1:{port}"
    try:
        print(f"building the images and starting {PROJECT} (site {port}, demo {dport})", flush=True)
        dc("build", "server", "demo-field")
        dc("up", "-d", "--wait", "--wait-timeout", "240", "server", "postgres", "demo-refresh", "demo-field")

        print("1. the stack", flush=True)
        check.ok(get(f"{base}/demo/health")[0] == 200, "the demo's proxy answers and the controller is up")
        ports = dc("ps", "--format", "json", capture=True).stdout
        published = {json.loads(line)["Service"]: [p for p in json.loads(line).get("Publishers", []) if p["PublishedPort"]]
                     for line in ports.splitlines() if line.strip()}
        check.ok(all(p["URL"] == "127.0.0.1" for ps in published.values() for p in ps), "everything is published on 127.0.0.1 only")

        print("2. a game plays itself", flush=True)
        running = wait(lambda: next((g for g in (jget(f"{base}/api/v1/games") or []) if g["state"] == "running"), None), 150)
        check.ok(bool(running), "a game is running")
        if running:
            gid = running["id"]
            nodes = jget(f"{base}/api/v1/nodes") or []
            check.ok(len(nodes) == 3 and all(n["link"] == "online" for n in nodes), "three simulated boxes are online")
            first = (jget(f"{base}/api/v1/games/{gid}/score") or {}).get("teams", {})
            later = wait(lambda: (lambda t: t if sum(t.values()) > sum(first.values()) + 2 else None)(
                (jget(f"{base}/api/v1/games/{gid}/score") or {}).get("teams", {})), 40)
            check.ok(bool(later), f"scores rise ({first} then {later})")
            log = jget(f"{base}/api/v1/games/{gid}/log") or []
            check.ok(any(e["type"] == "zone.captured" for e in log), "boxes were captured (zone.captured events)")
            view = wait(lambda: (lambda v: v if v and len(v.get("positions", [])) >= 3 else None)(
                jget(f"{base}/player/data.json", None)), 40)
            check.ok(bool(view), "the player's view shows the team's positions")
            check.ok(bool(view) and view["me"]["replicas"] and view["me"]["replicas"][0]["state"] in ("passed", "refused"),
                     "the chronograph's reading of the player's replica is in")
            check.ok(bool(view) and view["game"]["id"] == gid and view["score"] is not None, "the player's view follows this game")
            ended = wait(lambda: next((g for g in (jget(f"{base}/api/v1/games") or []) if g["id"] == gid and g["state"] == "ended"), None), 90)
            check.ok(bool(ended), "the game ends on its own")
            nxt = wait(lambda: next((g for g in (jget(f"{base}/api/v1/games") or []) if g["id"] != gid and g["state"] in ("ready", "running")), None), 60)
            check.ok(bool(nxt), "another game begins")

        print("3. nothing can be changed", flush=True)
        games = jget(f"{base}/api/v1/games") or []
        gid = games[0]["id"] if games else 1
        for method, path in (("POST", "/api/v1/games"), ("POST", f"/api/v1/games/{gid}/end"), ("POST", f"/api/v1/games/{gid}/start"),
                             ("PUT", "/api/v1/field/image"), ("DELETE", f"/api/v1/games/{gid}"), ("PATCH", f"/api/v1/games/{gid}/checkins/x"),
                             ("POST", "/api/v1/join"), ("POST", "/api/v1/checkin"), ("POST", "/api/v1/positions"),
                             ("OPTIONS", "/api/v1/games")):
            code, _ = get(base + path, READ_TOKEN, method, b"{}" if method != "OPTIONS" else None)
            check.ok(code == 405, f"{method} {path} is refused (405, got {code})")
        for path in ("/api/v1/join", "/api/v1/boxes", "/api/v1/adopt", "/api/v1/firmware", "/api/v1/marshals",
                     "/api/v1/checkin/settings", "/api/v1/checkin/poster", "/api/v1/mode-packages", "/api/v1/remote-gm",
                     f"/api/v1/games/{gid}/checkins.csv", f"/api/v1/games/{gid}/invites", "/api/v1/scoreboard-link",
                     "/api/v1/controller/ca", "/healthz", "/../etc/passwd", "/console/../api/v1/boxes"):
            code, _ = get(base + path, READ_TOKEN)
            check.ok(code == 404, f"GET {path} is not served (404, got {code})")
        check.ok(get(f"{base}/api/v1/games")[0] == 401, "no token: 401")
        check.ok(get(f"{base}/api/v1/games", "wrong")[0] == 401, "a wrong token: 401")
        check.ok(get(f"{base}/api/v1/games", READ_TOKEN)[0] == 200, "the public read token reads")
        # the GM token is made for each run and handed to the controller and the director by environment only
        files = dc("exec", "-T", "demo-field", "sh", "-c", "grep -rl 'GM_TOKEN' /data 2>/dev/null | head -1", check_rc=False,
                   capture=True).stdout.strip()
        check.ok(files == "", "the GM token is written to no file in the demo's data folder")
        ws = dc("exec", "-T", "demo-field", "python3", "-c", WS_PROBE, "gm-secret", check_rc=False, capture=True)
        try:
            out = json.loads(ws.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            out = {}
        check.ok(out.get("hello") is not None, f"the stream says hello to the read token ({out.get('hello')})")
        check.ok(out.get("still_open") is True, "what a visitor sends on the stream is ignored")
        check.ok(out.get("bad_?token=wrong") == "refused" and out.get("bad_") == "refused" and out.get("bad_?token=gm-secret") == "refused",
                 "the stream refuses no token and tokens that are not the read token")
        after = jget(f"{base}/api/v1/games") or []
        check.ok(not any(g["name"] == "x" for g in after), "nothing the probes sent changed a game")

        print("4. nothing personal", flush=True)
        from director import CALLSIGNS, MARSHAL_NAME

        blobs: list[str] = []
        for path in ("/api/v1/games", "/api/v1/nodes", "/api/v1/controller", "/api/v1/field", "/api/v1/presets", "/api/v1/schedule",
                     "/api/v1/scenarios", "/api/v1/modes", f"/api/v1/games/{gid}", f"/api/v1/games/{gid}/log",
                     f"/api/v1/games/{gid}/score", f"/api/v1/games/{gid}/checkins", f"/api/v1/games/{gid}/chrono-list",
                     "/api/v1/positions", f"/api/v1/games/{gid}/positions", "/api/v1/beacons", "/api/v1/field/features"):
            code, body = get(base + path, READ_TOKEN)
            blobs.append(body.decode("utf-8", "replace"))
        code, body = get(f"{base}/player/data.json")
        blobs.append(body.decode("utf-8", "replace"))
        text = "\n".join(blobs)
        check.ok(not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text), "no e-mail address in anything a visitor can read")
        check.ok(not re.search(r'"(email|phone|telephone|address|federation_number|membership_number|ip)":\s*"[^"]+"', text),
                 "no contact or membership field with a value")
        names = set(re.findall(r'"(?:display_name|name)":\s*"([^"]*)"', text))
        player_names = {n for n in names if n in CALLSIGNS or n == MARSHAL_NAME}
        view = jget(f"{base}/player/data.json", None) or {}
        check.ok(view.get("me", {}).get("display_name") in CALLSIGNS, "the player's view is a made-up callsign")
        check.ok(set(re.findall(r'"display_name":\s*"([^"]*)"', text)) <= set(CALLSIGNS) | {MARSHAL_NAME},
                 f"every display name is a made-up callsign ({sorted(player_names)[:4]}...)")

        print("5. the site server shows the demo", flush=True)
        code, landing = get(f"{site}/?lang=en")
        check.ok(code == 200 and f"http://127.0.0.1:{dport}/?lang=en" in landing.decode() and "/f/demo-ao-vivo/" in landing.decode(),
                 "the preview's landing page links to the demo and to the live field")
        field = wait(lambda: get(f"{site}/f/demo-ao-vivo/")[0] == 200, 30)
        check.ok(bool(field), "the live demo field's public page is there")
        board = wait(lambda: (lambda d: d if d and d.get("game") else None)(jget(f"{site}/f/demo-ao-vivo/scoreboard.json", None)), 120)
        check.ok(bool(board), f"its public scoreboard shows a game the simulated controller synced ({str(board)[:90]})")
        check.ok(get(f"{base}/")[0] == 200 and b"demo" in get(f"{base}/")[1].lower(), "the demo's home page")

        print("6. it restarts cleanly", flush=True)
        before = {g["id"] for g in (jget(f"{base}/api/v1/games") or [])}
        dc("restart", "demo-field")
        up = wait(lambda: get(f"{base}/demo/health")[0] == 200, 90)
        check.ok(bool(up), "the demo is back after a restart")
        newgame = wait(lambda: next((g for g in (jget(f"{base}/api/v1/games") or []) if g["state"] == "running"), None), 150)
        check.ok(bool(newgame) and newgame["id"] not in before, "a new game is played after the restart")
        after_games = jget(f"{base}/api/v1/games") or []
        check.ok(len([g for g in after_games if g["state"] in ("running", "paused")]) <= 1, "no game is left half-played")
        check.ok(not (before & {g["id"] for g in after_games}), "the old games are gone (a fresh controller database)")
        nodes = jget(f"{base}/api/v1/nodes") or []
        check.ok(len(nodes) == 3, "the three boxes rejoined")
    finally:
        print("removing everything the check made", flush=True)
        subprocess.run(["docker", "compose", "--env-file", str(env_file), "-p", PROJECT, "-f", str(SERVER / "docker-compose.yml"),
                        "-f", str(SERVER / "docker-compose.preview.yml"), "down", "--volumes", "--remove-orphans"],
                       capture_output=True, text=True)
        subprocess.run(["docker", "image", "rm", "-f", demo_image], capture_output=True, text=True)
        env_file.unlink(missing_ok=True)
        try:
            tmp.rmdir()
        except OSError:
            pass
    if check.failures:
        print(f"\npreview-demo: {len(check.failures)} check(s) failed", file=sys.stderr)
        return 1
    print("\npreview-demo: the live demo plays by itself, is read-only, shows nothing personal, reaches the site server and "
          "restarts cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
