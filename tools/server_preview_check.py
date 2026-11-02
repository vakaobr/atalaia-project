#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks the preview deployment's Compose files (decisions PV-*): `python3 tools/docker_server.py preview-check`.

Resolves server/docker-compose.yml + server/docker-compose.preview.yml with `docker compose config` (no container
is made, no secret is real) and asserts what the preview promises:

- the only published ports are the site server's (127.0.0.1, container port 8000) and the live demo's read-only
  proxy (127.0.0.1, container port 8001);
- Caddy is not started, nothing else is published, no service uses the host network;
- every started service restarts unless stopped, the database has its volume, the images are pinned by digest
  (or are the locally built server image);
- the server is on no network with a way out except the one that publishes its port, and that one has no outbound
  NAT; the database network is internal; the server trusts forwarded headers from one subnet, not "*";
- the live demo (DEMO-*) is on a network with no outbound NAT and on an internal one shared with the site server
  alone, runs read-only with every capability dropped, and only its one-shot `demo-init` does not restart;
- the preview is on and Portuguese is the default (PV-9);
- preview.sh is valid POSIX sh and prints no secret by construction (no `cat`/`echo` of the env files);
- `preview.sh restore` (with a stand-in `docker` that only records what it is asked): restore.sh goes through the
  preview's Compose file and never starts Caddy, the live demo is stopped before the database is replaced, its key
  step (`demo live --key-out`) runs on the restored database and only then does the demo start again; restore.sh
  without ATALAIA_PREVIEW still starts Caddy and does not use the preview's file.
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
    if sorted(n for n, _ in published) != ["demo-field", "server"]:
        found.append(f"published ports are not the server's and the demo's alone: {published}")
    for name, p in published:
        if p.get("host_ip") != "127.0.0.1" or int(p["target"]) != {"server": 8000, "demo-field": 8001}.get(name):
            found.append(f"{name} publishes {p}: only 127.0.0.1 -> 8000 (server) and -> 8001 (demo-field) are allowed")
    for name, s in services.items():
        if s.get("network_mode") == "host":
            found.append(f"{name} uses the host network")
        if "profiles" in s:
            continue
        if s.get("restart") != "unless-stopped" and name not in ("backup-crypt", "demo-init"):
            found.append(f"{name} restart is {s.get('restart')!r}, not unless-stopped")
        image = s.get("image", "")
        if name not in ("server", "demo-refresh", "demo-init", "demo-field") and "@sha256:" not in image:
            found.append(f"{name}: image {image} is not pinned by digest")
    server = services["server"]
    if not any(v.get("source") == "pgdata" for v in services["postgres"].get("volumes", [])):
        found.append("postgres has no pgdata volume")
    if "atak" not in server["networks"] or not set(server["networks"]) <= {"app", "db", "atak", "demo-sync"}:
        found.append(f"the server's networks are {sorted(server['networks'])}")
    demo = services["demo-field"]
    if sorted(demo["networks"]) != ["demo", "demo-sync"]:
        found.append(f"the demo's networks are {sorted(demo['networks'])}: demo and demo-sync only")
    if networks["demo"].get("driver_opts", {}).get("com.docker.network.bridge.enable_ip_masquerade") != "false":
        found.append("the demo's published network must have no outbound NAT")
    if not networks["demo-sync"].get("internal") or "demo-sync" not in server["networks"]:
        found.append("demo-sync must be an internal network, shared with the server")
    if not demo.get("read_only") or demo.get("cap_drop") != ["ALL"] or "no-new-privileges:true" not in demo.get(
            "security_opt", []):
        found.append("the demo must run read-only, with every capability dropped and no-new-privileges")
    if [v.get("source") for v in demo.get("volumes", []) if v.get("target") == "/secrets" and not v.get("read_only")]:
        found.append("the demo must mount the sync key read-only")
    if services["demo-init"].get("network_mode") != "none":
        found.append("demo-init must have no network")
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
    return found + notice_problems() + restore_problems()


def notice_problems() -> list[str]:
    """`preview.sh notice` (and so up and update) installs the files of ATALAIA_PRIVACY_NOTICE_VERSION into the
    folder the server reads, and refuses when that version's files are missing (FU30-1)."""
    import shutil
    import tempfile
    found: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        (home / "src" / "server" / "preview").mkdir(parents=True)
        shutil.copy(SERVER / "preview" / "preview.sh", home / "src" / "server" / "preview" / "preview.sh")
        shutil.copytree(SERVER / "preview" / "privacy-notice", home / "src" / "server" / "preview" / "privacy-notice")
        env = {"PATH": os.environ.get("PATH", ""), "HOME": tmp, "ATALAIA_PREVIEW_HOME": str(home)}

        def run(version: str) -> subprocess.CompletedProcess:
            (home / "preview.env").write_text(f"ATALAIA_PRIVACY_NOTICE_VERSION={version}\n", encoding="utf-8")
            return subprocess.run(["sh", str(home / "src" / "server" / "preview" / "preview.sh"), "notice"],
                                  env=env, capture_output=True, text=True)

        have = sorted((SERVER / "preview" / "privacy-notice").glob("privacy-notice-en-*.md"))
        if not have:
            return ["server/preview/privacy-notice/ has no notice"]
        version = have[-1].name[len("privacy-notice-en-"):-len(".md")]
        done = run(version)
        target = home / "src" / "server" / "privacy-notice"
        want = {f"privacy-notice-{lang}-{version}.md" for lang in ("pt", "en")}
        if done.returncode != 0 or not want <= {f.name for f in target.glob("*.md")}:
            found.append(f"preview.sh notice did not install the notice files of {version}: {done.stderr.strip()}")
        elif any(version not in f.name for f in target.glob("*.md")):
            found.append("preview.sh notice installed files of another version")
        gone = run("preview-9999-01-01")
        if gone.returncode == 0 or "missing" not in gone.stderr:
            found.append("preview.sh notice must refuse a version whose files are missing")
    return found


FAKE_DOCKER = """#!/bin/sh
# Records every call, one line each; answers pg_restore -l with a single-field server's table of contents.
printf '%s\\n' "$*" >> "$DOCKER_LOG"
case "$*" in
    *"pg_restore -l"*) cat > /dev/null; echo "1; 1259 1 TABLE public fields atalaia" ;;
    *" open"*) cat > /dev/null ;;
    *pg_restore*) cat > /dev/null ;;
esac
exit 0
"""


def restore_problems() -> list[str]:
    """`preview.sh restore FILE --yes` and restore.sh, against a stand-in docker: which Compose files, which services
    are started, and the order of the live demo's key step (no container is made)."""
    import shutil
    import tempfile
    found: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        srv = home / "src" / "server"
        (srv / "preview").mkdir(parents=True)
        for name in ("restore.sh", "docker-compose.yml", "docker-compose.preview.yml", "docker-compose.hosted.yml"):
            shutil.copy(SERVER / name, srv / name)
        shutil.copy(SERVER / "preview" / "preview.sh", srv / "preview" / "preview.sh")
        shutil.copytree(SERVER / "preview" / "privacy-notice", srv / "preview" / "privacy-notice")
        bin_dir = home / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker").write_text(FAKE_DOCKER, encoding="utf-8")
        (bin_dir / "docker").chmod(0o755)
        (home / "backups").mkdir()
        backup = home / "backups" / "atalaia-20260101T000000Z.backup"
        backup.write_bytes(b"not really encrypted")
        log = home / "docker.log"
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}", "HOME": tmp,
               "ATALAIA_PREVIEW_HOME": str(home), "DOCKER_LOG": str(log)}
        have = sorted((SERVER / "preview" / "privacy-notice").glob("privacy-notice-en-*.md"))
        version = have[-1].name[len("privacy-notice-en-"):-len(".md")] if have else ""

        def run(env_text: str, *cmd: str) -> tuple[subprocess.CompletedProcess, list[str]]:
            (home / "preview.env").write_text(env_text, encoding="utf-8")
            log.write_text("", encoding="utf-8")
            done = subprocess.run(["sh", *cmd], env=env, capture_output=True, text=True)
            return done, log.read_text(encoding="utf-8").splitlines()

        preview_env = (f"ATALAIA_PREVIEW=on\nCOMPOSE_PROJECT_NAME=atalaia-preview\n"
                       f"ATALAIA_PRIVACY_NOTICE_VERSION={version}\n")
        done, calls = run(preview_env, str(srv / "preview" / "preview.sh"), "restore", str(backup), "--yes")
        if done.returncode != 0:
            return found + [f"preview.sh restore failed against a stand-in docker: {done.stderr.strip()[-400:]}"]
        compose = [c for c in calls if c.startswith("compose ")]
        if any("docker-compose.preview.yml" not in c for c in compose):
            found.append("preview.sh restore made a Compose call without docker-compose.preview.yml (Caddy and the "
                         "server's production settings would come back)")
        if any(re.search(r" up( |$)", c) and re.search(r"\bcaddy\b", c) for c in compose):
            found.append("preview.sh restore starts caddy")

        def first(pattern: str) -> int:
            return next((i for i, c in enumerate(compose) if re.search(pattern, c)), -1)

        stop_demo = first(r" stop demo-field demo-refresh$")
        replace = first(r"pg_restore -U atalaia -d atalaia")
        key = first(r" run .*--entrypoint python demo-refresh -m atalaia_server demo live --key-out /secrets/sync-key$")
        start = max((i for i, c in enumerate(compose) if re.search(r" up .*demo-refresh", c) and "demo-field" in c),
                    default=-1)
        if not 0 <= stop_demo < replace < key < start:
            found.append("preview.sh restore must stop the live demo, replace the database, run `demo live "
                         f"--key-out` and only then start the demo (order seen: stop {stop_demo}, restore {replace}, "
                         f"key {key}, start {start})")

        # restore.sh on its own, with an env file that is not a preview's, then with one that claims to be both.
        env["ATALAIA_ENV_FILE"] = str(home / "preview.env")
        done, calls = run("COMPOSE_PROJECT_NAME=x\n", str(srv / "restore.sh"), str(backup), "--yes")
        compose = [c for c in calls if c.startswith("compose ")]
        if done.returncode != 0:
            found.append(f"restore.sh (not a preview) failed against a stand-in docker: {done.stderr.strip()[-400:]}")
        elif any("docker-compose.preview.yml" in c for c in compose) or not any(
                re.search(r" up -d --wait server caddy$", c) for c in compose):
            found.append("restore.sh without ATALAIA_PREVIEW must use docker-compose.yml alone and start caddy")
        done, calls = run("ATALAIA_PREVIEW=on\nATALAIA_HOSTED=on\n", str(srv / "restore.sh"), str(backup), "--yes")
        if done.returncode == 0 or calls or "never a hosted hub" not in done.stderr:
            found.append("restore.sh must refuse an env file that is both a preview and a hosted hub, before any "
                         "docker call")
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
