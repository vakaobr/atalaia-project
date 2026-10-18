#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Renders and checks the hardware wiring diagrams in Docker, from any shell.

    python tools/docker_hw.py render     WireViz source -> SVG and PNG next to it
    python tools/docker_hw.py check      the wiring check (tools/check_wiring.py)

Works from any folder and any shell (cmd, PowerShell, bash). Docker must be
running. `render` builds a small image with pinned WireViz and Graphviz
(atalaia-wireviz, rebuilt when the pins below change) and regenerates
the .svg and .png of every diagram in hardware/field-box/wiring/ from the .yml
next to them, with the GPIO numbers taken from the firmware's Kconfig
defaults. Commit the source and both images together. `check` runs
tools/check_wiring.py in the same image, so it needs no Python packages on
the host.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOURCES = [
    "hardware/field-box/wiring/field-box-wiring.yml",
    "hardware/field-box/wiring/field-box-power.yml",
]
IMAGE = "atalaia-wireviz"
LABEL = "org.atalaia.wireviz"
PNG_DPI = 110

# Everything that changes the rendered images is pinned here. Debian bookworm
# ships Graphviz 2.42.2; its exact Debian revision is matched by prefix, so a
# security update does not break the build.
DOCKERFILE = """\
FROM python:3.12.12-slim-bookworm
RUN apt-get update \\
 && apt-get install -y --no-install-recommends 'graphviz=2.42.2-7*' fonts-dejavu-core \\
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir --disable-pip-version-check \\
      wireviz==0.4.1 graphviz==0.20.3 PyYAML==6.0.2 pillow==11.3.0 click==8.1.8
WORKDIR /src
"""

# Runs inside the container, in /src (the repository). check_wiring.py fills
# the GPIO<SYMBOL> placeholders in with the Kconfig defaults; WireViz writes
# the SVG and the Graphviz source; dot draws the PNG at a readable
# resolution. The SVG gets the SHA-256 of the filled-in source, so that
# tools/check_wiring.py can tell a stale render (source or Kconfig changed).
RENDER = r"""
set -eu
out=$(mktemp -d)
for src in "$@"; do
  name=$(basename "$src" .yml)
  dir=$(dirname "$src")
  python tools/check_wiring.py --resolve "$src" > "$out/$name.yml"
  wireviz -f gs -o "$out" "$out/$name.yml"
  dot -Tpng -Gdpi=%(dpi)d -o "$dir/$name.png" "$out/$name.gv"
  sum=$(tr -d '\r' < "$out/$name.yml" | sha256sum | cut -d' ' -f1)
  sed "0,/<svg/s//<!-- atalaia-wiring-source-sha256: $sum -->\n<svg/" "$out/$name.svg" > "$dir/$name.svg"
  echo "rendered $dir/$name.svg and $dir/$name.png"
done
"""


def fail(message: str) -> int:
    print(f"docker_hw: {message}", file=sys.stderr)
    return 1


def docker(*args: str, quiet: bool = False, stdin: bytes | None = None) -> int:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.run(["docker", *args], input=stdin, stdout=out, stderr=out).returncode


def ensure_image() -> bool:
    wanted = hashlib.sha256(DOCKERFILE.encode()).hexdigest()[:16]
    label_format = "{{index .Config.Labels \"%s\"}}" % LABEL
    built = subprocess.run(["docker", "image", "inspect", "-f", label_format, IMAGE],
                           capture_output=True, text=True)
    if built.returncode == 0 and built.stdout.strip() == wanted:
        return True
    print(f"Building the {IMAGE} image (first run, or its pinned versions changed)...", flush=True)
    return docker("build", "--label", f"{LABEL}={wanted}", "-t", IMAGE, "-",
                  stdin=DOCKERFILE.encode()) == 0


def run(*command: str) -> int:
    # The user's own uid on Linux and macOS keeps the written files theirs.
    user = ["--user", f"{os.getuid()}:{os.getgid()}"] if hasattr(os, "getuid") else []
    return docker("run", "--rm", *user, "-e", "HOME=/tmp", "-v", f"{REPO}:/src", "-w", "/src",
                  IMAGE, *command)


def render() -> int:
    code = run("sh", "-c", RENDER % {"dpi": PNG_DPI}, "render", *SOURCES)
    if code == 0:
        print("Now run: python tools/docker_hw.py check")
    return code


def check() -> int:
    return run("python", "tools/check_wiring.py")


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1
    if len(argv) != 1 or argv[0] not in ("render", "check"):
        return fail(f"unknown command {' '.join(argv)!r}; run with --help")
    try:
        if docker("info", quiet=True) != 0:
            return fail("Docker is not running; start Docker Desktop and try again")
    except FileNotFoundError:
        return fail("the docker command was not found; install Docker Desktop")
    try:
        if not ensure_image():
            return fail("building the image failed")
        return render() if argv[0] == "render" else check()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
