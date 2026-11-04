#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds and tests the expansion port's module firmware in Docker (draft RFC "The expansion port",
increment 8), for machines without GCC for Arm or pico-sdk.

    python tools/docker_module.py build     the target module's UF2 files ->
                                            firmware/target-module/build/atalaia_target_module.uf2
                                            (one plate) and atalaia_target_module_2.uf2 (two plates)
    python tools/docker_module.py test      the target module's host tests and the module core's
                                            (firmware/module-core/), as CI runs them
    python tools/docker_module.py clean     delete firmware/target-module/build/ and the build volume

The image (tools/dev/module/Dockerfile: Ubuntu 24.04 pinned by digest, GCC for Arm from its
packages, pico-sdk 2.2.0 and picotool 2.2.0 pinned by tag and commit) is built on the first run
and again whenever its Dockerfile changes. The build folder is a Docker volume
(atalaia-module-build, plus ATALAIA_VOLUME_SUFFIX to keep two checkouts apart), so pico-sdk's
libraries are compiled once.

To flash a module: hold its BOOTSEL button, plug it into a computer's USB, and copy the UF2 file to
the drive that appears (firmware/target-module/README.md). Never with the module on a box's port.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCKERFILE_DIR = REPO / "tools" / "dev" / "module"
IMAGE = "atalaia-module"
LABEL = "org.atalaia.dockerfile"
VOLUME = "atalaia-module-build" + os.environ.get("ATALAIA_VOLUME_SUFFIX", "")
OUT = REPO / "firmware" / "target-module" / "build"
# (TARGET_PLATES, the UF2's name)
VARIANTS = ((1, "atalaia_target_module"), (2, "atalaia_target_module_2"))


def fail(message: str) -> int:
    print(f"docker_module: {message}", file=sys.stderr)
    return 1


def docker(*args: str) -> int:
    return subprocess.run(["docker", *args]).returncode


def ensure_image() -> bool:
    dockerfile = (DOCKERFILE_DIR / "Dockerfile").read_bytes().replace(b"\r\n", b"\n")
    wanted = hashlib.sha256(dockerfile).hexdigest()[:16]
    fmt = "{{index .Config.Labels \"%s\"}}" % LABEL
    built = subprocess.run(["docker", "image", "inspect", "-f", fmt, IMAGE], capture_output=True, text=True)
    if built.returncode == 0 and built.stdout.strip() == wanted:
        return True
    print(f"Building the {IMAGE} image (first run, or tools/dev/module/Dockerfile changed)...", flush=True)
    return docker("build", "--label", f"{LABEL}={wanted}", "-t", IMAGE, str(DOCKERFILE_DIR)) == 0


def run(script: str) -> int:
    return docker("run", "--rm", "-v", f"{REPO}:/src", "-v", f"{VOLUME}:/build", "-w", "/src",
                  IMAGE, "sh", "-c", script)


def build_script() -> str:
    """The commands of CI's target-module job: each variant's UF2 into firmware/target-module/build/."""
    steps = ["set -e", "mkdir -p firmware/target-module/build"]
    for plates, name in VARIANTS:
        steps += [
            f"cmake -S firmware/target-module -B /build/target-module-{plates} -G Ninja "
            f"-DCMAKE_BUILD_TYPE=Release -DTARGET_PLATES={plates}",
            f"cmake --build /build/target-module-{plates}",
            f"cp /build/target-module-{plates}/{name}.uf2 firmware/target-module/build/",
        ]
    steps.append("cd firmware/target-module/build && sha256sum *.uf2")
    return " && ".join(steps)


def test_script() -> str:
    return " && ".join([
        "set -e",
        "cmake -S firmware/target-module -B /build/target-module-host -G Ninja -DTARGET_MODULE_HOST_TESTS=ON",
        "cmake --build /build/target-module-host",
        "ctest --test-dir /build/target-module-host --output-on-failure",
        "cmake -S firmware/module-core -B /build/module-core -G Ninja -DCMAKE_BUILD_TYPE=Debug",
        "cmake --build /build/module-core",
        "ctest --test-dir /build/module-core --output-on-failure",
    ])


def build() -> int:
    if not ensure_image():
        return fail("building the image failed")
    code = run(build_script())
    if code == 0:
        print("\nTarget module: firmware/target-module/build/atalaia_target_module.uf2 "
              "(two plates: atalaia_target_module_2.uf2); to flash it, see firmware/target-module/README.md")
    return code


def test() -> int:
    if not ensure_image():
        return fail("building the image failed")
    return run(test_script())


def clean() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    subprocess.run(["docker", "volume", "rm", "-f", VOLUME], capture_output=True)
    print(f"Removed {OUT.relative_to(REPO)} and the volume {VOLUME}")
    return 0


def main(argv: list[str]) -> int:
    commands = {"build": build, "test": test, "clean": clean}
    if len(argv) != 1 or argv[0] not in commands:
        print(__doc__)
        return 2
    if shutil.which("docker") is None:
        return fail("Docker is not installed (or not on PATH)")
    return commands[argv[0]]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
