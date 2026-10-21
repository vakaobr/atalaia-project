#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The site server's deployment test (plan phase 22): `python3 tools/docker_server.py deploy`.

Runs the real deployment (server/setup.sh, server/docker-compose.yml with
Caddy, server/backup.sh, server/restore.sh) on this machine in Docker, with
Caddy's own CA instead of a public certificate (ATALAIA_TLS=internal) and the
site name atalaia.test, ports on 127.0.0.1 only:

 1. setup.sh writes the env file (mode 0600, secrets never printed) and,
    run again, changes nothing;
 2. the stack comes up behind Caddy; tests/deploy_probe.py, in a container
    on the public network only, checks HTTPS, the headers, the redirect, that
    the database and the server's port cannot be reached, and syncs a game
    over the WebSocket through Caddy; the audit log has the probe's own
    address (the proxy headers) and the server runs one worker;
 3. backup.sh makes an encrypted backup (0600, not a plain dump) and prunes
    old ones; a damaged backup is refused by restore.sh with nothing changed;
 4. everything is deleted (`down --volumes`), a fresh stack starts with an
    empty database, restore.sh restores the backup into a fresh database, and
    every table's contents match what they were; the probe checks that the
    restored data and API key work through Caddy.
Everything it made is removed at the end, whatever the result.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "server"
DOMAIN = "atalaia.test"
SECRETS = ("POSTGRES_PASSWORD", "ATALAIA_SECRET_KEY", "ATALAIA_METRICS_TOKEN", "ATALAIA_BACKUP_KEY")
# Every table's rows, in a stable order, as one digest: equal before the backup and after the restore.
FINGERPRINT_SQL = r"""
DO $$ BEGIN CREATE TEMP TABLE fp (name text, rows bigint, digest text); END $$;
DO $$
DECLARE t record;
BEGIN
  FOR t IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename LOOP
    EXECUTE format('INSERT INTO fp SELECT %L, count(*), md5(coalesce(string_agg(x::text, %L ORDER BY x::text), %L))
                    FROM %I x', t.tablename, E'\n', '', t.tablename);
  END LOOP;
END $$;
SELECT name || ' ' || rows || ' ' || digest FROM fp ORDER BY name;
"""


class DeployFailure(Exception):
    pass


def say(text: str) -> None:
    print(f"server_deploy: {text}", flush=True)


def expect(ok: bool, what: str) -> None:
    say(f"{'ok  ' if ok else 'FAIL'} {what}")
    if not ok:
        raise DeployFailure(what)


def free_port() -> int:
    """A random port below the ephemeral ranges, for Caddy's 80 and 443 (TCP, and UDP for HTTP/3) on
    127.0.0.1. Not tried here first: on WSL a port that a Linux process even briefly listened on is
    taken on the Windows side, and Docker Desktop then cannot publish it; Deployment.up retries."""
    return secrets.SystemRandom().randrange(20000, 32000)


class Deployment:
    # The Compose files, in order (the hosted test adds docker-compose.hosted.yml).
    files: tuple[str, ...] = ("docker-compose.yml",)
    name = "deploy"

    def __init__(self, suffix: str, server_image: str, test_image: str, work: Path) -> None:
        self.project = f"atalaia-{self.name}{suffix}".lower()
        self.server_image = server_image
        self.test_image = test_image
        self.work = work
        self.env_file = work / "env"
        self.backups = work / "backups"
        self.env = {**os.environ, "ATALAIA_ENV_FILE": str(self.env_file), "COMPOSE_PROJECT_NAME": self.project,
                    "ATALAIA_SERVER_IMAGE": server_image, "ATALAIA_TLS": "internal", "ATALAIA_BIND": "127.0.0.1",
                    "ATALAIA_HTTP_PORT": str(free_port()), "ATALAIA_HTTPS_PORT": str(free_port()),
                    "ATALAIA_BACKUP_DIR": str(self.backups)}
        self.secret_values: list[str] = []

    # --- running things -------------------------------------------------------------------------

    def run(self, cmd: list[str], *, check: bool = True, quiet: bool = False, input: Optional[bytes] = None,
            env: Optional[dict[str, str]] = None) -> subprocess.CompletedProcess:
        done = subprocess.run(cmd, env=env or self.env, input=input, capture_output=True, timeout=900)
        out = done.stdout.decode("utf-8", "replace") + done.stderr.decode("utf-8", "replace")
        leaked = [s for s in self.secret_values if s in out]
        if leaked:
            raise DeployFailure(f"{' '.join(cmd[:4])} printed a secret")
        if not quiet:
            for line in out.splitlines():
                print(f"    {line}")
        if check and done.returncode != 0:
            raise DeployFailure(f"{' '.join(cmd)} exited with {done.returncode}")
        return done

    def dc(self, *args: str, **kw) -> subprocess.CompletedProcess:
        files = [arg for name in self.files for arg in ("-f", str(SERVER / name))]
        return self.run(["docker", "compose", "--env-file", str(self.env_file), *files, *args], **kw)

    def sql(self, statement: str, *, db: str = "atalaia") -> str:
        done = self.dc("exec", "-T", "postgres", "psql", "-U", "atalaia", "-d", db, "-v", "ON_ERROR_STOP=1",
                       "-q", "-At", input=statement.encode(), quiet=True)
        return done.stdout.decode().strip()

    def container_ip(self, service: str, network: str) -> str:
        cid = self.dc("ps", "-q", service, quiet=True).stdout.decode().strip()
        fmt = "{{(index .NetworkSettings.Networks \"%s_%s\").IPAddress}}" % (self.project, network)
        return self.run(["docker", "inspect", "-f", fmt, cid], quiet=True).stdout.decode().strip()

    def probe(self, phase: str, key: str) -> None:
        ca = self.work / "root.crt"
        if ca.exists():
            ca.unlink()
        for _ in range(30):  # Caddy makes its local CA as it starts
            if self.dc("cp", "caddy:/data/caddy/pki/authorities/local/root.crt", str(ca), check=False,
                       quiet=True).returncode == 0:
                break
            time.sleep(1)
        expect(ca.exists(), "Caddy's local root certificate")
        ca.chmod(0o644)
        closed = f"{self.container_ip('postgres', 'db')}:5432,{self.container_ip('server', 'app')}:8000"
        env = {**self.env, "ATALAIA_PROBE_KEY": key}
        self.run(["docker", "run", "--rm", "--network", f"{self.project}_edge",
                  "--add-host", f"{DOMAIN}:{self.container_ip('caddy', 'edge')}",
                  "-v", f"{ca}:/ca.crt:ro", "-e", "ATALAIA_PROBE_KEY", "-e", f"ATALAIA_PROBE_HOST={DOMAIN}",
                  "-e", "ATALAIA_PROBE_CA=/ca.crt", "-e", f"ATALAIA_PROBE_CLOSED={closed}",
                  self.test_image, "python", "-m", "tests.deploy_probe", phase], env=env)

    # --- the steps ------------------------------------------------------------------------------

    def setup(self) -> None:
        say("1. setup.sh")
        self.run(["sh", str(SERVER / "setup.sh"), DOMAIN, "--no-start"])
        mode = stat.S_IMODE(self.env_file.stat().st_mode)
        expect(mode == 0o600, f"the env file is mode 0600 ({oct(mode)})")
        values = dict(line.split("=", 1) for line in self.env_file.read_text().splitlines()
                      if "=" in line and not line.startswith("#"))
        for name in SECRETS:
            expect(bool(re.fullmatch(r"[0-9a-f]{64}", values.get(name, ""))), f"{name}: 32 random bytes")
        self.secret_values = [values[name] for name in SECRETS]
        expect(len(set(self.secret_values)) == len(SECRETS), "every secret is different")
        expect(values.get("ATALAIA_PUBLIC_URL") == f"https://{DOMAIN}", "ATALAIA_PUBLIC_URL")
        before = self.env_file.read_bytes()
        self.env_file.chmod(0o644)
        self.run(["sh", str(SERVER / "setup.sh"), DOMAIN, "--no-start"])
        expect(self.env_file.read_bytes() == before, "run again, setup.sh keeps every value")
        expect(stat.S_IMODE(self.env_file.stat().st_mode) == 0o600, "and puts the mode back to 0600")
        refused = self.run(["sh", str(SERVER / "setup.sh"), "other.example", "--no-start"], check=False)
        expect(refused.returncode != 0 and self.env_file.read_bytes() == before,
               "setup.sh refuses another domain for an existing env file")
        bad = self.run(["sh", str(SERVER / "setup.sh"), "https://x.test/", "--no-start"], check=False)
        expect(bad.returncode == 2, "setup.sh refuses a URL as the domain")

    def up(self) -> None:
        for _ in range(3):
            done = self.dc("up", "-d", "--wait", "--wait-timeout", "180", check=False)
            if done.returncode == 0:
                return
            if b"ports are not available" not in done.stderr:
                break
            # Docker Desktop on Windows cannot publish a port Windows itself holds: try others.
            self.dc("down", "--remove-orphans", check=False, quiet=True)
            self.env["ATALAIA_HTTP_PORT"], self.env["ATALAIA_HTTPS_PORT"] = str(free_port()), str(free_port())
        raise DeployFailure("docker compose up failed")

    def seed(self) -> str:
        key = secrets.token_urlsafe(32)
        self.secret_values.append(key)
        digest = hashlib.sha256(key.encode()).hexdigest()
        self.sql("INSERT INTO fields (name, slug) VALUES ('Campo de teste', 'campo-teste');"
                 f"INSERT INTO field_api_keys (field_id, key_sha256) SELECT id, '{digest}' FROM fields;")
        return key

    def one_worker(self) -> None:
        # Processes running uvicorn or a multiprocessing child (a second worker); the needles are
        # built at run time so this script's own command line does not match.
        script = ("import os\nneedles = (b'uvi' + b'corn', b'multi' + b'processing')\nn = 0\n"
                  "for p in os.listdir('/proc'):\n    if p.isdigit():\n"
                  "        try:\n            c = open(f'/proc/{p}/cmdline', 'rb').read()\n"
                  "        except OSError:\n            continue\n"
                  "        n += any(x in c for x in needles)\nprint(n)")
        count = self.dc("exec", "-T", "server", "python", "-c", script, quiet=True).stdout.decode().strip()
        expect(count == "1", f"one server process (found {count})")

    def backup(self) -> Path:
        say("3. backup.sh")
        self.backups.mkdir(mode=0o700)
        old = self.backups / "atalaia-20200101T000000Z.backup"
        recent = self.backups / "atalaia-20200102T000000Z.backup"
        for path, days in ((old, 40), (recent, 10)):
            path.write_bytes(b"stand-in")
            t = time.time() - days * 86400
            os.utime(path, (t, t))
        self.run(["sh", str(SERVER / "backup.sh")])
        made = sorted(p for p in self.backups.glob("atalaia-*.backup") if p not in (old, recent))
        expect(len(made) == 1, "one new backup")
        made_one = made[0]
        expect(not old.exists() and recent.exists(), "the 40-day-old backup was pruned, the 10-day-old one kept")
        expect(stat.S_IMODE(made_one.stat().st_mode) == 0o600, "the backup is mode 0600")
        expect(stat.S_IMODE(self.backups.stat().st_mode) == 0o700, "its folder is mode 0700")
        data = made_one.read_bytes()
        expect(data.startswith(b"ATLBAK\x00\x01") and b"PGDMP" not in data and b"campo-teste" not in data,
               "the backup is encrypted (no pg_dump header, no table data in clear)")
        expect(not list(self.backups.glob("*.partial")) and not (self.backups / ".lock").exists(),
               "no partial file or lock left behind")
        return made_one

    def refused_restores(self, good: Path) -> None:
        damaged = self.work / "damaged.backup"
        blob = bytearray(good.read_bytes())
        blob[len(blob) // 2] ^= 0x01
        damaged.write_bytes(bytes(blob))
        fingerprint = self.fingerprint()
        done = self.run(["sh", str(SERVER / "restore.sh"), str(damaged), "--yes"], check=False)
        expect(done.returncode != 0 and b"nothing was changed" in done.stderr, "a damaged backup is refused")
        done = self.run(["sh", str(SERVER / "restore.sh"), str(good)], check=False)
        expect(done.returncode != 0, "restore.sh without --yes changes nothing")
        expect(self.fingerprint() == fingerprint, "and the database is untouched")

    def fingerprint(self) -> str:
        return self.sql(FINGERPRINT_SQL)

    def restore(self, backup: Path, expected: str) -> None:
        say("4. a fresh stack, then restore.sh")
        self.dc("down", "--volumes", "--remove-orphans")
        self.up()
        expect(self.sql("SELECT count(*) FROM fields") == "0", "the fresh database is empty")
        self.run(["sh", str(SERVER / "restore.sh"), str(backup), "--yes"])
        got = self.fingerprint()
        expect(got == expected, f"every table matches after the restore ({len(expected.splitlines())} tables)")
        expect(self.sql("SELECT count(*) FROM game_events") == "2", "the synced events are back")

    def down(self) -> None:
        self.dc("down", "--volumes", "--remove-orphans", check=False, quiet=True)


def run(suffix: str, server_image: str, test_image: str) -> int:
    for tool in ("sh", "docker"):
        if shutil.which(tool) is None:
            say(f"{tool} is not installed")
            return 1
    work = Path(tempfile.mkdtemp(prefix="atalaia-deploy-"))
    d = Deployment(suffix, server_image, test_image, work)
    try:
        d.setup()
        say("2. the stack behind Caddy")
        d.up()
        key = d.seed()
        d.probe("before", key)
        address = d.sql("SELECT host(ip_address) FROM audit_log WHERE action = 'login_failed' ORDER BY id DESC LIMIT 1")
        caddy = d.container_ip("caddy", "app")
        expect(bool(address) and address != caddy,
               f"the audit log has the client's address ({address}), not Caddy's ({caddy})")
        d.one_worker()
        expected = d.fingerprint()
        expect(len(expected.splitlines()) >= 30, "every table fingerprinted")
        backup = d.backup()
        d.refused_restores(backup)
        d.restore(backup, expected)
        d.probe("after", key)
        say("every deployment check passed (Caddy's local CA on this machine; not a real domain or certificate)")
        return 0
    except DeployFailure as exc:
        say(f"failed: {exc}")
        d.dc("logs", "--no-color", "--tail", "60", check=False)
        return 1
    finally:
        d.down()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sfx = os.environ.get("ATALAIA_VOLUME_SUFFIX", "")
    sys.exit(run(sfx, f"atalaia-server{sfx}".lower(), f"atalaia-server-test{sfx}".lower()))
