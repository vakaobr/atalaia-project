#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds, tests and tries out the site server in Docker (server/, decision P4R17).

    python3 tools/docker_server.py test                       every site server test
    python3 tools/docker_server.py test tests.test_health     only these (unittest names)
    python3 tools/docker_server.py migrations                 upgrade head, downgrade base, upgrade head, check
    python3 tools/docker_server.py build                      build the server image (atalaia-server)
    python3 tools/docker_server.py up                         run it on http://127.0.0.1:8000 (ATALAIA_PORT)
    python3 tools/docker_server.py down                       stop it and delete its database

Works from any folder; Docker with the Compose plugin must be running. `test`
and `migrations` build the test image (server/Dockerfile, target test) and
run `sh tests/run.sh test|migrations` in it with Docker Compose
(server/docker-compose.test.yml) next to an ephemeral postgres:16-alpine in a
tmpfs, then remove the containers whatever the result: CI's server job runs
the same image and the same commands against a service container. `up` is a
local trial with a random database password and secret key
(server/docker-compose.yml): `down` deletes its data. In a running trial,
`docker compose -p atalaia-server-trial exec server python -m atalaia_server
create-admin --username NAME` makes a server administrator. ATALAIA_VOLUME_SUFFIX keeps the Compose projects and
images of two checkouts (e.g. a git worktree) apart.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SERVER = REPO / "server"
SUFFIX = os.environ.get("ATALAIA_VOLUME_SUFFIX", "")
TEST_PROJECT = f"atalaia-server-test{SUFFIX}".lower()
TRIAL_PROJECT = f"atalaia-server-trial{SUFFIX}".lower()
TEST_IMAGE = f"atalaia-server-test{SUFFIX}".lower()
SERVER_IMAGE = f"atalaia-server{SUFFIX}".lower()


def fail(message: str) -> int:
    print(f"docker_server: {message}", file=sys.stderr)
    return 1


def compose(file: str, project: str, *args: str) -> list[str]:
    return ["docker", "compose", "-f", str(SERVER / file), "-p", project, *args]


def run(cmd: list[str], env: dict[str, str], quiet: bool = False) -> int:
    out = subprocess.DEVNULL if quiet else None
    try:
        return subprocess.call(cmd, env=env, stdout=out, stderr=out)
    except KeyboardInterrupt:
        return 130


def run_counting(cmd: list[str], env: dict[str, str]) -> tuple[int, int | None]:
    """Runs cmd, echoing its output; returns the exit code and unittest's "Ran N tests" count."""
    ran = None
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            m = re.match(r"Ran (\d+) tests?", line)
            if m:
                ran = int(m.group(1))
        return proc.wait(), ran
    except KeyboardInterrupt:
        return 130, ran


def in_tests_image(what: str, args: list[str]) -> int:
    env = {**os.environ, "ATALAIA_SERVER_TEST_IMAGE": TEST_IMAGE}
    file = "docker-compose.test.yml"
    if run(compose(file, TEST_PROJECT, "build", "tests"), env) != 0:
        return fail("building the test image failed")
    try:
        code, ran = run_counting(compose(file, TEST_PROJECT, "run", "--rm", "tests", "sh", "tests/run.sh",
                                         what, *args), env)
    finally:
        run(compose(file, TEST_PROJECT, "down", "--volumes", "--remove-orphans"), env, quiet=True)
    if ran is not None:
        print(f"\ndocker_server: {ran} site server tests, exit code {code}")
    elif code == 0:
        print(f"\ndocker_server: {what} passed")
    return code


def trial(what: str) -> int:
    env = {**os.environ, "ATALAIA_SERVER_IMAGE": SERVER_IMAGE}
    file = "docker-compose.yml"
    unused = {"POSTGRES_PASSWORD": "unused", "ATALAIA_SECRET_KEY": "unused"}
    if what == "build":
        return run(compose(file, TRIAL_PROJECT, "build", "server"), {**env, **unused})
    if what == "down":
        return run(compose(file, TRIAL_PROJECT, "down", "--volumes", "--remove-orphans"), {**env, **unused})
    # up: a new password and key each time is fine, since down deletes the database with them.
    env.setdefault("POSTGRES_PASSWORD", secrets.token_urlsafe(24))
    env.setdefault("ATALAIA_SECRET_KEY", secrets.token_urlsafe(32))
    code = run(compose(file, TRIAL_PROJECT, "up", "--detach", "--build", "--wait"), env)
    if code == 0:
        port = env.get("ATALAIA_PORT", "8000")
        print(f"\ndocker_server: the site server is up: http://127.0.0.1:{port}/api/v1/health "
              f"(python3 tools/docker_server.py down stops it and deletes its data; an administrator: "
              f"docker compose -p {TRIAL_PROJECT} exec server python -m atalaia_server create-admin "
              f"--username NAME)")
    return code


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 2
    what, args = argv[0], argv[1:]
    if what not in ("test", "migrations", "build", "up", "down"):
        return fail(f"unknown command '{what}' (test, migrations, build, up, down)")
    if what != "test" and args:
        return fail(f"'{what}' takes no arguments")
    try:
        if run(["docker", "info"], dict(os.environ), quiet=True) != 0:
            return fail("Docker is not running; start it and try again")
        if run(["docker", "compose", "version"], dict(os.environ), quiet=True) != 0:
            return fail("the Docker Compose plugin is missing (docker compose version)")
    except FileNotFoundError:
        return fail("the docker command was not found; install Docker")
    if what in ("test", "migrations"):
        return in_tests_image(what, args)
    return trial(what)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
