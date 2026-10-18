#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the GM console's browser tests in Docker (headless Chromium, Playwright).

    python tools/docker_console.py                 every browser test
    python tools/docker_console.py -k scoreboard   only tests whose name matches

Works from any folder and any shell (cmd, PowerShell, bash). Docker must be
running. The image comes from tools/dev/console/Dockerfile (Playwright's
Ubuntu 24.04 image plus the controller's dependencies, Mosquitto and
zbar-tools); it is built on the first run and rebuilt whenever that file
changes. The tests run controller/console/tests/run.sh, as CI's console job
does: it builds the core library and the C host modem, starts the real
controller for each test and drives the console in Chromium. A missing
browser or tool is an error there, never a skip.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMAGE = "atalaia-console-test"
LABEL = "org.atalaia.dockerfile"
VOLUME = "atalaia-console-build"
DOCKERFILE = REPO / "tools" / "dev" / "console" / "Dockerfile"


def fail(message: str) -> int:
    print(f"docker_console: {message}", file=sys.stderr)
    return 1


def docker(*args: str, quiet: bool = False) -> int:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.call(["docker", *args], stdout=out, stderr=out)


def ensure_image() -> bool:
    wanted = hashlib.sha256(DOCKERFILE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]
    label_format = "{{index .Config.Labels \"%s\"}}" % LABEL
    built = subprocess.run(["docker", "image", "inspect", "-f", label_format, IMAGE],
                           capture_output=True, text=True)
    if built.returncode == 0 and built.stdout.strip() == wanted:
        return True
    print(f"Building the {IMAGE} image (first run, or {DOCKERFILE.relative_to(REPO).as_posix()} changed)...",
          flush=True)
    return docker("build", "--label", f"{LABEL}={wanted}", "-t", IMAGE, str(DOCKERFILE.parent)) == 0


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    try:
        if docker("info", quiet=True) != 0:
            return fail("Docker is not running; start Docker Desktop and try again")
    except FileNotFoundError:
        return fail("the docker command was not found; install Docker Desktop")
    if not ensure_image():
        return fail("building the image failed")
    cmd = ["docker", "run", "--rm", "--ipc=host", "-e", "ATALAIA_REQUIRE_BROWSER=1",
           "-v", f"{REPO}:/src", "-v", f"{VOLUME}:/tmp/console-build", "-w", "/src", IMAGE,
           "sh", "controller/console/tests/run.sh", *argv]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        ran = None
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            m = re.match(r"Ran (\d+) tests?", line)
            if m:
                ran = int(m.group(1))
        code = proc.wait()
    except KeyboardInterrupt:
        return 130
    if ran is not None:
        print(f"\ndocker_console: {ran} browser tests, exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
