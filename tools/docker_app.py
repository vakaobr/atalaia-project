#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Runs the app's checks in Docker, as CI does.

    python tools/docker_app.py                    everything below except format and lock
    python tools/docker_app.py check              the core for this machine, then flutter analyze,
                                                  dart format check and every Dart test (CI: flutter-test)
    python tools/docker_app.py test               the core, then only the Dart tests
    python tools/docker_app.py test test/ffi      some of them (any `flutter test` arguments)
    python tools/docker_app.py ndk                the core cross-compiled with the Android NDK for
                                                  arm64-v8a, armeabi-v7a, x86_64 (CI: core-android-ndk)
    python tools/docker_app.py apk                flutter build apk --debug, with the core built by
                                                  Gradle and the NDK (CI: flutter-build-android)
    python tools/docker_app.py format             format app/lib and app/test in place
    python tools/docker_app.py lock               resolve app/pubspec.yaml again, write pubspec.lock

Works from any folder and any shell (cmd, PowerShell, bash). Docker must be
running. Two images are used:

- atalaia-dev (tools/dev/Dockerfile, built on first use like docker_sim.py)
  builds the core and the FFI stub as shared libraries for the Dart tests
  (cmake ... -DATALAIA_SHARED=ON -DATALAIA_STUB=ON -DATALAIA_MBEDTLS=OFF).
  Both images are Ubuntu 24.04, so the libraries load in the other one.
- ghcr.io/cirruslabs/flutter:3.44.0, pinned by digest (about 2.3 GB on the
  first run), runs app/tool/check.sh. It has no CMake: the NDK 28.2.13676358
  and CMake 3.22.1 come from the Android SDK manager on first use (about
  1 GB) and Gradle 9.1.0 with its dependencies on the first `apk`.

The checkout is mounted read-only (check.sh works on a copy) except for
format and lock. Named volumes keep the downloads and the core's build
between runs: atalaia-app-pub-cache, atalaia-app-core, atalaia-app-ndk,
atalaia-app-cmake and atalaia-app-gradle, each with $ATALAIA_VOLUME_SUFFIX
appended (to keep two checkouts apart). `docker volume rm` any of them to
start fresh.

tools/check.sh (the atalaia-dev image, no Dart) does not run these; it does
build the FFI stub and check the simulator's ctypes structs against it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import docker_sim  # noqa: E402  (the atalaia-dev image)

REPO = Path(__file__).resolve().parents[1]
IMAGE = ("ghcr.io/cirruslabs/flutter:3.44.0"
         "@sha256:46691e311715845de03a3ba4753a475476936805b29431b1f00f1816981033f8")
SUFFIX = os.environ.get("ATALAIA_VOLUME_SUFFIX", "")
PUB_VOLUME = "atalaia-app-pub-cache" + SUFFIX
CORE_VOLUME = "atalaia-app-core" + SUFFIX
NDK_VOLUME = "atalaia-app-ndk" + SUFFIX
CMAKE_VOLUME = "atalaia-app-cmake" + SUFFIX
GRADLE_VOLUME = "atalaia-app-gradle" + SUFFIX
SDK = "/opt/android-sdk-linux"
MODES = ("all", "check", "test", "ndk", "apk", "format", "lock")


def fail(message: str) -> int:
    print(f"docker_app: {message}", file=sys.stderr)
    return 1


def build_core() -> int:
    """The core and the FFI stub as shared libraries, in the atalaia-dev image."""
    if not docker_sim.ensure_image():
        return fail("building the atalaia-dev image failed")
    print("docker_app: building the core and the FFI stub (atalaia-dev)...", flush=True)
    script = ("cmake -S /src/core -B /core-build -DCMAKE_BUILD_TYPE=Debug -DATALAIA_SHARED=ON "
              "-DATALAIA_STUB=ON -DATALAIA_MBEDTLS=OFF -DBUILD_TESTING=OFF > /tmp/build.log 2>&1 "
              "&& cmake --build /core-build >> /tmp/build.log 2>&1 "
              "|| { cat /tmp/build.log; exit 1; }")
    return subprocess.call(["docker", "run", "--rm", "-v", f"{REPO}:/src:ro", "-v",
                            f"{CORE_VOLUME}:/core-build", docker_sim.IMAGE, "sh", "-c", script])


def flutter(mode: str, args: list[str]) -> int:
    """app/tool/check.sh <mode> in the Flutter image; returns its exit code."""
    writable = mode in ("format", "lock")
    cmd = ["docker", "run", "--rm", "-v", f"{REPO}:/src" + ("" if writable else ":ro"),
           "-v", f"{PUB_VOLUME}:/root/.pub-cache", "-w", "/src"]
    if mode in ("check", "test"):
        cmd += ["-v", f"{CORE_VOLUME}:/core-build:ro",
                "-e", "ATALAIA_CORE_LIB=/core-build/libatalaia_core.so",
                "-e", "ATALAIA_CORE_STUB_LIB=/core-build/libatalaia_core_stub.so"]
    if mode in ("ndk", "apk"):
        cmd += ["-v", f"{NDK_VOLUME}:{SDK}/ndk", "-v", f"{CMAKE_VOLUME}:{SDK}/cmake"]
    if mode == "apk":
        cmd += ["-v", f"{GRADLE_VOLUME}:/root/.gradle"]
    cmd += [IMAGE, "sh", "/src/app/tool/check.sh", mode, *args]
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
    if passed is not None:
        print(f"\ndocker_app: {mode}: {passed} Dart tests passed, exit code {code}")
    else:
        print(f"\ndocker_app: {mode}: exit code {code}")
    return code


def main(argv: list[str]) -> int:
    # Flutter prints characters (✓, •) that a Windows code page cannot show when
    # the output is redirected; replace them rather than stop.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    if argv and argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    mode = "all"
    if argv and argv[0] in MODES:
        mode, argv = argv[0], argv[1:]
    elif argv and not argv[0].startswith("-"):
        return fail(f"unknown command {argv[0]!r}; use one of {', '.join(MODES)}")
    if mode in ("all", "ndk", "apk") and argv:
        return fail(f"{mode} takes no arguments")
    try:
        if subprocess.call(["docker", "info"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) != 0:
            return fail("Docker is not running; start Docker Desktop and try again")
    except FileNotFoundError:
        return fail("the docker command was not found; install Docker Desktop")
    try:
        if mode in ("format", "lock", "ndk", "apk"):
            return flutter(mode, argv)
        code = build_core()
        if code != 0:
            return fail(f"building the core failed (exit code {code})")
        if mode in ("check", "test"):
            return flutter(mode, argv)
        results = {}
        for step in ("check", "ndk", "apk"):
            results[step] = flutter(step, [])
        print("\ndocker_app: " + ", ".join(f"{k} exit {v}" for k, v in results.items()))
        return next((v for v in results.values() if v != 0), 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
