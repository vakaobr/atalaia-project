#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the mode editor's browser tests in Docker (headless Chromium, Playwright).

    python tools/docker_editor.py                  every browser test of the editor
    python tools/docker_editor.py -k round_trip    only tests whose name matches

Works from any folder and any shell (cmd, PowerShell, bash). Docker must be
running. The image is the GM console's (tools/dev/console/Dockerfile, built
the same way as by tools/docker_console.py on the first run and whenever that
file changes). The tests run simulator/editor_tests/run.sh, as CI's editor
job does: it builds the core library and drives the editor, served by the
simulator's web server, in Chromium; the generated modes run their tests in
the simulator. A missing browser is an error, never a skip.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from docker_console import IMAGE, REPO, docker, ensure_image, fail  # noqa: E402

# ATALAIA_VOLUME_SUFFIX keeps the build cache of two checkouts (e.g. a git worktree) apart.
VOLUME = "atalaia-editor-build" + os.environ.get("ATALAIA_VOLUME_SUFFIX", "")


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
           "sh", "simulator/editor_tests/run.sh", *argv]
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
        print(f"\ndocker_editor: {ran} browser tests, exit code {code}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
