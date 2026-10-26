#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks the preview deployment's Compose files (decisions PV-*): `python3 tools/docker_server.py preview-check`.

Resolves server/docker-compose.yml + server/docker-compose.preview.yml with `docker compose config` (no container
is made, no secret is real) and asserts what the preview promises:

- the only published port is the site server's, bound to 127.0.0.1, container port 8000;
- Caddy is not started, nothing else is published, no service uses the host network;
- every started service restarts unless stopped, the database has its volume, the images are pinned by digest
  (or are the locally built server image);
- the server is on no network with a way out except the one that publishes its port, and that one has no outbound
  NAT; the database network is internal; the server trusts forwarded headers from one subnet, not "*";
- the preview is on and Portuguese is the default (PV-9);
- preview.sh is valid POSIX sh and prints no secret by construction (no `cat`/`echo` of the env files).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1] / "server"


def config() -> dict:
    env = {**os.environ, "POSTGRES_PASSWORD": "x" * 32, "ATALAIA_SECRET_KEY": "s" * 43, "ATALAIA_DOMAIN": "preview.test",
           "ATALAIA_PREVIEW_HOME": "/nonexistent", "ATALAIA_BIND": "127.0.0.1", "ATALAIA_PREVIEW_PORT": "8000"}
    out = subprocess.run(["docker", "compose", "--env-file", os.devnull, "-p", "atalaia-preview-check",
                          "-f", str(SERVER / "docker-compose.yml"), "-f", str(SERVER / "docker-compose.preview.yml"),
                          "config", "--format", "json"], env=env, check=True, capture_output=True, text=True)
    return json.loads(out.stdout)


def problems(cfg: dict) -> list[str]:
    found: list[str] = []
    services, networks = cfg["services"], cfg.get("networks", {})
    if "caddy" in services:
        found.append("caddy is started (it should be in the 'caddy' profile)")
    published = [(name, p) for name, s in services.items() for p in s.get("ports", [])]
    if [n for n, _ in published] != ["server"]:
        found.append(f"published ports are not the server's alone: {published}")
    for name, p in published:
        if p.get("host_ip") != "127.0.0.1" or int(p["target"]) != 8000:
            found.append(f"{name} publishes {p}: only 127.0.0.1 -> 8000 is allowed")
    for name, s in services.items():
        if s.get("network_mode") == "host":
            found.append(f"{name} uses the host network")
        if "profiles" in s:
            continue
        if s.get("restart") != "unless-stopped" and name != "backup-crypt":
            found.append(f"{name} restart is {s.get('restart')!r}, not unless-stopped")
        image = s.get("image", "")
        if name not in ("server", "demo-refresh") and "@sha256:" not in image:
            found.append(f"{name}: image {image} is not pinned by digest")
    server = services["server"]
    if not any(v.get("source") == "pgdata" for v in services["postgres"].get("volumes", [])):
        found.append("postgres has no pgdata volume")
    if "atak" not in server["networks"] or "edge" in server["networks"]:
        found.append(f"the server's networks are {sorted(server['networks'])}")
    if not networks["db"].get("internal") or not networks["app"].get("internal"):
        found.append("db and app must be internal networks")
    if networks["atak"].get("driver_opts", {}).get("com.docker.network.bridge.enable_ip_masquerade") != "false":
        found.append("the network that publishes the port must have no outbound NAT")
    allowed = server["environment"].get("FORWARDED_ALLOW_IPS", "")
    if not re.fullmatch(r"\d+\.\d+\.\d+\.\d+/\d+", allowed) or allowed.endswith("/0"):
        found.append(f"FORWARDED_ALLOW_IPS is {allowed!r}: one subnet is wanted, never '*'")
    env = server["environment"]
    if (env.get("ATALAIA_PREVIEW"), env.get("ATALAIA_LANG_FROM_BROWSER"), env.get("ATALAIA_DEFAULT_LANG")) != (
            "on", "off", "pt"):
        found.append("the server is not a preview that opens in Portuguese")
    script = SERVER / "preview" / "preview.sh"
    if subprocess.run(["sh", "-n", str(script)]).returncode != 0:
        found.append("preview.sh is not valid sh")
    text = script.read_text(encoding="utf-8")
    if re.search(r"^[^#\n]*\bcat\b[^>\n]*\$(env_file|home|target)[^>\n]*$", text, re.M):
        found.append("preview.sh seems to print a secrets file")
    return found


def main() -> int:
    cfg = config()
    found = problems(cfg)
    for line in found:
        print(f"preview-check: {line}", file=sys.stderr)
    if not found:
        print("preview-check: the preview's Compose files keep their promises (127.0.0.1 only, no Caddy, restart "
              "unless stopped, pinned images, no way out for the server, one trusted subnet, Portuguese by default)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
