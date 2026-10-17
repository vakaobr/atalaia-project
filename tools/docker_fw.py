#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds and tests the ESP32 firmware in Docker, for machines without a C compiler.

    python tools/docker_fw.py build            Field Box firmware -> firmware/esp32/build/
    python tools/docker_fw.py wokwi            Wokwi emulator variant -> firmware/esp32/build-wokwi/
    python tools/docker_fw.py test             host tests and screen reference images (as CI)
    python tools/docker_fw.py test --update-screens
                                               accept new screen renders as the references
    python tools/docker_fw.py clean            delete the firmware build folders

Works from any folder and any shell (cmd, PowerShell, bash). Docker must be
running. `build` and `wokwi` use the espressif/idf:v5.3.2 image, the same as
CI's esp32-build job, and write into firmware/esp32/ so that flashing tools
and the Wokwi extension find the files. `test` runs CI's firmware-test
commands in the atalaia-dev image (built on first use, like docker_sim.py)
and copies the rendered screens to firmware/esp32/build-test/screens/.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FW = REPO / "firmware" / "esp32"
IDF_IMAGE = "espressif/idf:v5.3.2"
DEV_IMAGE = "atalaia-dev"
DEV_LABEL = "org.atalaia.dockerfile"
TEST_VOLUME = "atalaia-fw-test-build"

WOKWI_BUILD = "build-wokwi"
WOKWI_DEFAULTS = ("sdkconfig.defaults", "sdkconfig.wokwi")


def fail(message: str) -> int:
    print(f"docker_fw: {message}", file=sys.stderr)
    return 1


def docker(*args: str, quiet: bool = False) -> int:
    out = subprocess.DEVNULL if quiet else None
    return subprocess.call(["docker", *args], stdout=out, stderr=out)


def interactive() -> list[str]:
    return ["-it"] if sys.stdin.isatty() and sys.stdout.isatty() else []


def drop_broken_components() -> None:
    """Deletes half-downloaded managed components, so the component manager fetches them again."""
    managed = FW / "managed_components"
    if not managed.is_dir():
        return
    for component in managed.iterdir():
        if component.is_dir() and not (component / "CMakeLists.txt").exists():
            print(f"docker_fw: {component.name} is incomplete; it will be downloaded again", flush=True)
            shutil.rmtree(component)


def run_idf(script: str) -> int:
    """Runs a shell script in the ESP-IDF image, in firmware/esp32/."""
    drop_broken_components()
    return docker("run", "--rm", *interactive(), "-v", f"{REPO}:/project",
                  "-w", "/project/firmware/esp32", IDF_IMAGE, "bash", "-c", script)


def build() -> int:
    script = (
        "set -e; . $IDF_PATH/export.sh > /dev/null; "
        "[ -f build/CMakeCache.txt ] || idf.py set-target esp32s3; "
        "idf.py build"
    )
    code = run_idf(script)
    if code == 0:
        print("\nFirmware: firmware/esp32/build/atalaia_esp32.bin (to flash it, see firmware/esp32/docs/BRING_UP.md)")
    return code


def wokwi() -> int:
    # The variant's sdkconfig lives in build-wokwi/. Regenerate it when the
    # defaults change, so edits to sdkconfig.wokwi always take effect.
    sdkconfig = FW / WOKWI_BUILD / "sdkconfig"
    if sdkconfig.exists():
        newest = max((FW / name).stat().st_mtime for name in WOKWI_DEFAULTS)
        if newest > sdkconfig.stat().st_mtime:
            sdkconfig.unlink()
    script = (
        "set -e; . $IDF_PATH/export.sh > /dev/null; "
        f"idf.py -B {WOKWI_BUILD} -D SDKCONFIG={WOKWI_BUILD}/sdkconfig "
        f"-D 'SDKCONFIG_DEFAULTS={';'.join(WOKWI_DEFAULTS)}' build"
    )
    code = run_idf(script)
    if code == 0:
        print(f"\nWokwi firmware: firmware/esp32/{WOKWI_BUILD}/. Open firmware/esp32/diagram.json "
              "in VS Code and start the simulator (see firmware/esp32/docs/WOKWI.md).")
    return code


def ensure_dev_image() -> bool:
    dockerfile = (REPO / "tools" / "dev" / "Dockerfile").read_bytes().replace(b"\r\n", b"\n")
    wanted = hashlib.sha256(dockerfile).hexdigest()[:16]
    label_format = "{{index .Config.Labels \"%s\"}}" % DEV_LABEL
    built = subprocess.run(["docker", "image", "inspect", "-f", label_format, DEV_IMAGE],
                           capture_output=True, text=True)
    if built.returncode == 0 and built.stdout.strip() == wanted:
        return True
    print(f"Building the {DEV_IMAGE} image (first run, or tools/dev/Dockerfile changed)...", flush=True)
    return docker("build", "--label", f"{DEV_LABEL}={wanted}", "-t", DEV_IMAGE,
                  str(REPO / "tools" / "dev")) == 0


def test(update_screens: bool) -> int:
    if not ensure_dev_image():
        return fail("building the image failed")
    env = ["-e", "ATALAIA_UPDATE_SCREENS=1"] if update_screens else []
    # The same commands as CI's firmware-test job; the build folder is a
    # volume, so LVGL is downloaded and compiled only once.
    script = (
        "cmake -S firmware/esp32/test -B /build/fw-test -DCMAKE_BUILD_TYPE=Debug && "
        "cmake --build /build/fw-test && "
        "rm -rf /build/fw-test/screens firmware/esp32/build-test/screens && "
        "{ ctest --test-dir /build/fw-test --output-on-failure; code=$?; "
        "mkdir -p firmware/esp32/build-test/screens && "
        "cp /build/fw-test/screens/*.png firmware/esp32/build-test/screens/ 2>/dev/null; "
        "exit $code; }"
    )
    code = docker("run", "--rm", *interactive(), *env, "-v", f"{REPO}:/src",
                  "-v", f"{TEST_VOLUME}:/build", DEV_IMAGE, "sh", "-c", script)
    print("\nRendered screens: firmware/esp32/build-test/screens/ "
          "(references: firmware/esp32/test/screens/)")
    if update_screens and code == 0:
        print("References updated: look at every changed PNG (git status) before committing.")
    return code


def clean() -> int:
    for name in ("build", WOKWI_BUILD, "build-test"):
        path = FW / name
        if path.exists():
            shutil.rmtree(path)
            print(f"removed firmware/esp32/{name}/")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1
    command, options = argv[0], argv[1:]
    known = {"build": [], "wokwi": [], "test": ["--update-screens"], "clean": []}
    if command not in known:
        return fail(f"unknown command {command!r}; run with --help")
    for option in options:
        if option not in known[command]:
            return fail(f"unknown option {option!r} for {command}")
    if command == "clean":
        return clean()
    try:
        if docker("info", quiet=True) != 0:
            return fail("Docker is not running; start Docker Desktop and try again")
    except FileNotFoundError:
        return fail("the docker command was not found; install Docker Desktop")
    try:
        if command == "build":
            return build()
        if command == "wokwi":
            return wokwi()
        return test("--update-screens" in options)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
