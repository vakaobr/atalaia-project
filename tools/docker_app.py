#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the app's Dart checks in Docker (the pinned Flutter image, as CI does).

    python tools/docker_app.py                    analyze, format check and every test
    python tools/docker_app.py test               only the tests
    python tools/docker_app.py test test/chrono   some of them (any `flutter test` arguments)
    python tools/docker_app.py format             format app/lib and app/test in place
    python tools/docker_app.py lock               resolve app/pubspec.yaml again, write pubspec.lock

Works from any folder and any shell (cmd, PowerShell, bash). Docker must be
running. The image is ghcr.io/cirruslabs/flutter:3.44.0, pinned by digest
(about 2.3 GB, pulled on the first run); CI's "Player app logic (Dart)" job
uses the same one. Inside it, app/tool/check.sh works on a copy of app/ and
protocol/, so check and test mount the checkout read-only and write nothing
into it. Downloaded packages are kept in a named Docker volume
(atalaia-app-pub-cache; ATALAIA_VOLUME_SUFFIX keeps two checkouts apart).

The atalaia-dev image (tools/check.sh) has no Dart, so check.sh does not run
these; the Python side of the shared chrono and token vectors is in the
controller's tests, which check.sh does run.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMAGE = ("ghcr.io/cirruslabs/flutter:3.44.0"
         "@sha256:46691e311715845de03a3ba4753a475476936805b29431b1f00f1816981033f8")
VOLUME = "atalaia-app-pub-cache" + os.environ.get("ATALAIA_VOLUME_SUFFIX", "")
MODES = ("check", "test", "format", "lock")


def fail(message: str) -> int:
    print(f"docker_app: {message}", file=sys.stderr)
    return 1


def main(argv: list[str]) -> int:
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    mode = "check"
    if argv and argv[0] in MODES:
        mode, argv = argv[0], argv[1:]
    elif argv and not argv[0].startswith("-"):
        return fail(f"unknown command {argv[0]!r}; use one of {', '.join(MODES)}")
    try:
        if subprocess.call(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            return fail("Docker is not running; start Docker Desktop and try again")
    except FileNotFoundError:
        return fail("the docker command was not found; install Docker Desktop")
    writable = mode in ("format", "lock")
    mount = f"{REPO}:/src" + ("" if writable else ":ro")
    cmd = ["docker", "run", "--rm", "-v", mount, "-v", f"{VOLUME}:/root/.pub-cache", "-w", "/src",
           IMAGE, "sh", "/src/app/tool/check.sh", mode, *argv]
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace")
        passed = None
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            m = re.search(r"\+(\d+)(?: ~\d+)?(?: -\d+)?: (?:All tests passed|Some tests failed)", line)
            if m:
                passed = int(m.group(1))
        code = proc.wait()
    except KeyboardInterrupt:
        return 130
    if passed is not None:
        print(f"\ndocker_app: {passed} Dart tests passed, exit code {code}")
    elif code != 0:
        print(f"\ndocker_app: exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
