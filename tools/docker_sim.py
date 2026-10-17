#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs a simulator command in the dev container, for machines without a C compiler.

    python tools/docker_sim.py serve modes/bomb
    python tools/docker_sim.py serve modes/domination --node alpha=zone --node bravo=zone
    python tools/docker_sim.py test

Takes the same arguments as `python -m atalaia_sim` and works from any folder
and any shell (cmd, PowerShell, bash). Paths are relative to the current
folder, as they would be natively. Docker must be running. The atalaia-dev
image is built on the first run and rebuilt whenever tools/dev/Dockerfile
changes; the core is rebuilt (incrementally, in the atalaia-core-build volume)
before each command, so changes to it are picked up.
For `serve`, the page is published on localhost only.
"""

from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
IMAGE = "atalaia-dev"
VOLUME = "atalaia-core-build"
LABEL = "org.atalaia.dockerfile"


def fail(message: str) -> int:
    print(f"docker_sim: {message}", file=sys.stderr)
    return 1


def docker(*args: str, quiet: bool = False) -> int:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.call(["docker", *args], stdout=out, stderr=out)


def container_args(args: list[str]) -> list[str]:
    """Turns host paths into paths inside the container, where the repository is /src."""
    out = []
    for i, arg in enumerate(args):
        path = Path(arg)
        if i > 0 and not arg.startswith("-") and path.exists():
            try:
                arg = "/src/" + path.resolve().relative_to(REPO).as_posix()
            except ValueError:
                raise SystemExit(fail(f"{arg} is outside the repository, so the container cannot see it"))
        out.append(arg)
    return out


def port_of(args: list[str]) -> str:
    for i, arg in enumerate(args):
        if arg == "--port" and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("--port="):
            return arg.split("=", 1)[1]
    return "8000"


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1
    try:
        if docker("info", quiet=True) != 0:
            return fail("Docker is not running; start Docker Desktop and try again")
    except FileNotFoundError:
        return fail("the docker command was not found; install Docker Desktop")

    dockerfile = (REPO / "tools" / "dev" / "Dockerfile").read_bytes().replace(b"\r\n", b"\n")
    wanted = hashlib.sha256(dockerfile).hexdigest()[:16]
    label_format = "{{index .Config.Labels \"%s\"}}" % LABEL
    built = subprocess.run(["docker", "image", "inspect", "-f", label_format, IMAGE],
                           capture_output=True, text=True)
    if built.returncode != 0 or built.stdout.strip() != wanted:
        print(f"Building the {IMAGE} image (first run, or tools/dev/Dockerfile changed)...", flush=True)
        if docker("build", "--label", f"{LABEL}={wanted}", "-t", IMAGE, str(REPO / "tools" / "dev")) != 0:
            return fail("building the image failed")

    args = container_args(argv)
    run = ["run", "--rm", "--init", "-v", f"{REPO}:/src", "-v", f"{VOLUME}:/build"]
    if sys.stdin.isatty() and sys.stdout.isatty():
        run.append("-it")
    if args[0] == "serve":
        port = port_of(args)
        name = f"atalaia-serve-{port}"
        if docker("container", "inspect", name, quiet=True) == 0:
            return fail(f"something already serves on port {port}; stop it with: docker rm -f {name}")
        run += ["--name", name, "-p", f"127.0.0.1:{port}:{port}"]
        if "--host" not in args:
            args += ["--host", "0.0.0.0"]  # inside the container; Docker publishes it on localhost only
    script = (
        "echo 'Building the core...' && "
        "{ cmake -S core -B /build -DATALAIA_SHARED=ON -DBUILD_TESTING=OFF && cmake --build /build; } "
        "> /tmp/build.log 2>&1 || { cat /tmp/build.log; exit 1; } && "
        "cd simulator && exec python3 -m atalaia_sim --lib /build/libatalaia_core.so "
        + shlex.join(args)
    )
    try:
        return docker(*run, IMAGE, "sh", "-c", script)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
