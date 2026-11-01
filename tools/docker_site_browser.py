#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the project page's browser test in Docker (headless Chromium, Playwright).

    python tools/docker_site_browser.py                 every test of tools/site_browser_test.py
    python tools/docker_site_browser.py -k flags        only tests whose name matches
    python tools/docker_site_browser.py -v              any other argument goes to unittest

Works from any folder and any shell (cmd, PowerShell, bash). Docker must be running. The image comes
from tools/dev/site-browser/Dockerfile (Playwright's Ubuntu 24.04 image plus the Playwright Python
client pinned with hashes in tools/dev/site-browser/requirements.txt: the base image's python3 does
not have it); it is built on the first run and rebuilt whenever either file changes. The test serves
site/ from the read-only mounted repository, opens every generated page in all four languages at
phone and desktop widths, and FAILS (never skips) if Playwright is missing. When
ATALAIA_VOLUME_SUFFIX is set (a verification copy or a git worktree), the image gets that suffix and
is removed after the run, so that parallel runs never share or leave images behind; without it the
image stays as a build cache, like the console's. The container always runs with --rm.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SUFFIX = os.environ.get("ATALAIA_VOLUME_SUFFIX", "").lower()
IMAGE = "atalaia-site-browser-test" + SUFFIX
LABEL = "org.atalaia.dockerfile"
CONTEXT = REPO / "tools" / "dev" / "site-browser"
INPUTS = (CONTEXT / "Dockerfile", CONTEXT / "requirements.txt")


def fail(message: str) -> int:
    print(f"docker_site_browser: {message}", file=sys.stderr)
    return 1


def docker(*args: str, quiet: bool = False) -> int:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.call(["docker", *args], stdout=out, stderr=out)


def ensure_image() -> bool:
    digest = hashlib.sha256()
    for path in INPUTS:
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    wanted = digest.hexdigest()[:16]
    label_format = "{{index .Config.Labels \"%s\"}}" % LABEL
    built = subprocess.run(["docker", "image", "inspect", "-f", label_format, IMAGE],
                           capture_output=True, text=True)
    if built.returncode == 0 and built.stdout.strip() == wanted:
        return True
    print(f"Building the {IMAGE} image (first run, or {CONTEXT.relative_to(REPO).as_posix()} changed)...",
          flush=True)
    return docker("build", "--label", f"{LABEL}={wanted}", "-t", IMAGE, str(CONTEXT)) == 0


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
    cmd = ["docker", "run", "--rm", "--ipc=host", "-v", f"{REPO}:/src:ro", "-w", "/src", IMAGE,
           "python3", "tools/site_browser_test.py", *argv]
    code = 1
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        ran = skipped = None
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            m = re.match(r"Ran (\d+) tests?", line)
            if m:
                ran = int(m.group(1))
            m = re.search(r"skipped=(\d+)", line)
            if m:
                skipped = int(m.group(1))
        code = proc.wait()
    except KeyboardInterrupt:
        return 130
    finally:
        if SUFFIX:
            docker("image", "rm", "-f", IMAGE, quiet=True)
    if ran is not None:
        print(f"\ndocker_site_browser: {ran} browser tests, exit code {code}")
        if code == 0 and skipped:
            return fail(f"{skipped} test(s) were skipped: a skip is a failure here")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
