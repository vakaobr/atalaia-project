#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds and tests the ESP32 firmware in Docker, for machines without a C compiler.

    python tools/docker_fw.py build            Field Box firmware -> firmware/esp32/build/
    python tools/docker_fw.py wokwi            Wokwi emulator variant -> firmware/esp32/build-wokwi/
    python tools/docker_fw.py modem            USB radio modem variant -> firmware/esp32/build-modem/
    python tools/docker_fw.py pod              I/O pod variant -> firmware/esp32/build-pod/
    python tools/docker_fw.py bench            bare board on the desk (serial keys, no setup portal)
                                               -> firmware/esp32/build-bench/
    python tools/docker_fw.py test             host tests and screen reference images (as CI)
    python tools/docker_fw.py test --update-screens
                                               accept new screen renders as the references
    python tools/docker_fw.py clean            delete the firmware build folders

    python tools/docker_fw.py version          the version a build here would carry (no Docker)

Every image's version (esp_app_desc_t, HELLO's fw_version, a firmware update's check) is
the core's (core/include/atalaia/version.h, 0.3.0-dev while 0.3.0 is developed) with the
commit it was built from, worked out here from the checkout: 0.3.0-dev.412+g8560d54 (commits
since the last release tag v<X.Y.Z>, or since the first commit; the commit's first 7 hex
digits), with ".dirty" when tracked files have uncommitted changes. A copy with no commit
(a tarball, a fresh `git init`) or no git gets the core's version alone (decisions FV-1 to FV-4).

`build`, `bench` and `wokwi` (the Field Box) also take:
    --fw-version=0.3.0-rc.1                    the exact version instead (a release or a release
                                               candidate, or a bench test of an update)
    --release-keys=<hex or base64>[,...]       the release public keys a box accepts updates from
                                               (CONFIG_ATALAIA_OTA_RELEASE_KEYS; default: none, and
                                               the box refuses every update). Public keys only:
                                               tools/firmware_release.py keygen prints them.
    --mode-keys=<hex or base64>[,...]          the mode public keys a box accepts fetched mode
                                               packages from (CONFIG_ATALAIA_MODE_KEYS; default:
                                               none, and the box fetches no modes). Public keys
                                               only: tools/mode_package.py pubkey prints them.
All three apply to that build folder only, and are reset when left out.

Works from any folder and any shell (cmd, PowerShell, bash). Docker must be
running. `build`, `wokwi`, `modem`, `pod` and `bench` use the espressif/idf:v5.3.2 image, the same as
CI's esp32-build job, and write into firmware/esp32/ so that flashing tools
and the Wokwi extension find the files. `test` runs CI's firmware-test
commands in the atalaia-dev image (built on first use, like docker_sim.py)
and copies the rendered screens to firmware/esp32/build-test/screens/.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
FW = REPO / "firmware" / "esp32"
VERSION_H = REPO / "core" / "include" / "atalaia" / "version.h"
FW_VERSION_LEN = 31  # esp_app_desc_t's version (32 bytes with its NUL)
IDF_IMAGE = "espressif/idf:v5.3.2"
DEV_IMAGE = "atalaia-dev"
DEV_LABEL = "org.atalaia.dockerfile"
# ATALAIA_VOLUME_SUFFIX keeps the build cache of two checkouts (e.g. a git worktree) apart.
TEST_VOLUME = "atalaia-fw-test-build" + os.environ.get("ATALAIA_VOLUME_SUFFIX", "")

WOKWI_BUILD = "build-wokwi"
WOKWI_DEFAULTS = ("sdkconfig.defaults", "sdkconfig.wokwi")
MODEM_BUILD = "build-modem"
MODEM_DEFAULTS = ("sdkconfig.defaults", "sdkconfig.modem")
POD_BUILD = "build-pod"
POD_DEFAULTS = ("sdkconfig.defaults", "sdkconfig.pod")
BENCH_BUILD = "build-bench"
BENCH_DEFAULTS = ("sdkconfig.defaults", "sdkconfig.bench")


def fail(message: str) -> int:
    print(f"docker_fw: {message}", file=sys.stderr)
    return 1


# ---- the firmware's version (decisions FV-1 to FV-4) ------------------------------------

_IDS = r"[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*"
FW_VERSION = re.compile(rf"\d{{1,4}}\.\d{{1,4}}\.\d{{1,4}}(?:-({_IDS}))?(?:\+({_IDS}))?")


def valid_fw_version(version: str) -> bool:
    """MAJOR.MINOR.PATCH[-pre-release][+build] as the box takes it (fw_update.c's fw_version_valid:
    1-20 characters each for the pre-release and the build metadata) and at most 31 characters."""
    m = FW_VERSION.fullmatch(version)
    return (m is not None and len(version) <= FW_VERSION_LEN
            and all(part is None or len(part) <= 20 for part in m.groups()))


def core_version(text: Optional[str] = None) -> str:
    """The core's version from version.h: MAJOR.MINOR.PATCH, and -PRERELEASE when it has one."""
    text = VERSION_H.read_text(encoding="utf-8") if text is None else text
    numbers = [re.search(rf"#define ATALAIA_VERSION_{name} +(\d+)", text)
               for name in ("MAJOR", "MINOR", "PATCH")]
    if not all(numbers):
        raise ValueError("version.h: ATALAIA_VERSION_MAJOR, _MINOR and _PATCH")
    out = ".".join(m.group(1) for m in numbers if m)
    pre = re.search(r'#define ATALAIA_VERSION_PRERELEASE +"([0-9A-Za-z.]*)"', text)
    return f"{out}-{pre.group(1)}" if pre and pre.group(1) else out


@dataclass(frozen=True)
class Checkout:
    """What the checkout says about the commit being built."""

    commit: str  # the first 7 hex digits of HEAD
    count: int  # commits since the last release tag (or since the first commit)
    tag: Optional[str]  # that release tag (v0.2.0), or None
    dirty: bool  # tracked files differ from HEAD


def _git(*args: str) -> Optional[str]:
    try:
        out = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def checkout() -> Optional[Checkout]:
    """HEAD's commit, the commits since the last release tag (v<digits>..., no pre-release: an
    rc tag never resets the count), and whether tracked files changed; None without git or
    without a commit (a tarball, the verify script's fresh `git init`)."""
    head = _git("rev-parse", "--verify", "--quiet", "HEAD^{commit}")
    if not head or not re.fullmatch(r"[0-9a-f]{40,64}", head):
        return None
    tag = _git("describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "--exclude", "v*-*", "HEAD")
    count = _git("rev-list", "--count", f"{tag}..HEAD" if tag else "HEAD")
    if count is None or not count.isdigit():
        return None
    status = _git("status", "--porcelain", "--untracked-files=no")
    return Checkout(commit=head[:7], count=int(count), tag=tag or None, dirty=bool(status))


def build_version(core: str, co: Optional[Checkout]) -> str:
    """The version a development build carries. While the core's version is a pre-release
    (0.3.0-dev), <core>.<count>+g<commit>[.dirty]: dev.N compares as a number, so a later commit
    is newer, every dev build is older than the release and newer than 0.2.0, and the build
    metadata (the commit) is ignored in the order. A release's version (0.3.0) is kept as it is
    on its tag with no change; any other commit gets <core>+<count>.g<commit>[.dirty], equal to
    the release in the order (FV-3). No checkout: the core's version."""
    if co is None:
        return core
    meta = f"g{co.commit}" + (".dirty" if co.dirty else "")
    if "-" in core:
        return f"{core}.{co.count}+{meta}"
    if co.tag == f"v{core}" and co.count == 0 and not co.dirty:
        return core
    return f"{core}+{co.count}.{meta}"


def firmware_version() -> str:
    """--fw-version when given, else this checkout's build version."""
    return FW_OPTIONS.get("fw_version") or build_version(core_version(), checkout())


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
    # Like the variants, the Field Box keeps its sdkconfig in its build folder,
    # made from sdkconfig.defaults alone: a firmware/esp32/sdkconfig left by an
    # earlier Wokwi build (keypad matrix on GPIO 1/2/7/39) must never end up
    # in a Field Box image, where GPIO 2 and 7 drive the radio front end.
    code = variant("build", ("sdkconfig.defaults",))
    if code == 0:
        print("\nFirmware: firmware/esp32/build/atalaia_esp32.bin (to flash it, see firmware/esp32/docs/BRING_UP.md)")
    return code


# Field Box options (main sets them): the firmware's version, its release keys and its mode keys.
FW_OPTIONS: dict[str, str] = {}
FIELD_BOX_BUILDS = ("build", WOKWI_BUILD, BENCH_BUILD)


def release_keys_hex(text: str) -> str | None:
    """Release public keys, hex or base64, separated by commas or spaces, as the Kconfig string."""
    import base64
    import binascii

    out = []
    for item in text.replace(",", " ").split():
        try:
            raw = bytes.fromhex(item) if len(item) == 64 else base64.b64decode(item, validate=True)
        except (ValueError, binascii.Error):
            return None
        if len(raw) != 32:
            return None
        out.append(raw.hex())
    return " ".join(out) if len(out) <= 4 else None


def field_box_options(build_dir: str) -> tuple[str, ...]:
    """The Field Box's release and mode keys (a defaults file in the build folder, rewritten only
    when it changes)."""
    if build_dir not in FIELD_BOX_BUILDS:
        return ()
    keys_file = FW / build_dir / "sdkconfig.release_keys"
    text = ("# Written by tools/docker_fw.py (--release-keys): public keys only.\n"
            f'CONFIG_ATALAIA_OTA_RELEASE_KEYS="{FW_OPTIONS.get("release_keys", "")}"\n'
            f'CONFIG_ATALAIA_MODE_KEYS="{FW_OPTIONS.get("mode_keys", "")}"\n')
    keys_file.parent.mkdir(parents=True, exist_ok=True)
    if not keys_file.exists() or keys_file.read_text() != text:
        keys_file.write_text(text)
    return (f"{build_dir}/sdkconfig.release_keys",)


def variant(build_dir: str, defaults: tuple[str, ...]) -> int:
    """Builds a variant (defaults applied on top of sdkconfig.defaults) into build_dir, with the
    firmware's version (a CMake cache value, set on every build so that it never sticks)."""
    version = firmware_version()
    if not valid_fw_version(version):
        return fail(f"the version {version!r} is not MAJOR.MINOR.PATCH[-pre-release][+build] of at most "
                    f"{FW_VERSION_LEN} characters; give one with --fw-version=")
    print(f"docker_fw: firmware version {version}", flush=True)
    cmake_args = [f"-D ATALAIA_FW_VERSION={version}"]
    defaults = defaults + field_box_options(build_dir)
    # The variant's sdkconfig lives in its build folder. Regenerate it when
    # the defaults change, so edits to them always take effect.
    sdkconfig = FW / build_dir / "sdkconfig"
    if sdkconfig.exists():
        newest = max((FW / name).stat().st_mtime for name in defaults)
        if newest > sdkconfig.stat().st_mtime:
            sdkconfig.unlink()
    script = (
        "set -e; . $IDF_PATH/export.sh > /dev/null; "
        f"idf.py -B {build_dir} -D SDKCONFIG={build_dir}/sdkconfig "
        f"-D 'SDKCONFIG_DEFAULTS={';'.join(defaults)}' {' '.join(cmake_args)} build"
    )
    code = run_idf(script)
    if code == 0:
        print(f"\nVersion: {version} (firmware/esp32/{build_dir}/, HELLO's fw_version)")
    return code


def wokwi() -> int:
    code = variant(WOKWI_BUILD, WOKWI_DEFAULTS)
    if code == 0:
        print(f"\nWokwi firmware: firmware/esp32/{WOKWI_BUILD}/. Open firmware/esp32/diagram.json "
              "in VS Code and start the simulator (see firmware/esp32/docs/WOKWI.md).")
    return code


def modem() -> int:
    code = variant(MODEM_BUILD, MODEM_DEFAULTS)
    if code == 0:
        print(f"\nModem firmware: firmware/esp32/{MODEM_BUILD}/atalaia_esp32.bin "
              "(flash it to the board plugged into the controller; see controller/README.md)")
    return code


def pod() -> int:
    code = variant(POD_BUILD, POD_DEFAULTS)
    if code == 0:
        print(f"\nI/O pod firmware: firmware/esp32/{POD_BUILD}/atalaia_esp32.bin "
              "(flash it to the pod's board; see firmware/esp32/README.md, \"The I/O pod\")")
    return code


def bench() -> int:
    code = variant(BENCH_BUILD, BENCH_DEFAULTS)
    if code == 0:
        print(f"\nBench firmware: firmware/esp32/{BENCH_BUILD}/atalaia_esp32.bin "
              "(for a bare board on the desk, never a box in a game; see BRING_UP.md)")
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
        "cp -r /build/fw-test/screens/oled firmware/esp32/build-test/screens/ 2>/dev/null; "
        "exit $code; }"
    )
    code = docker("run", "--rm", *interactive(), *env, "-v", f"{REPO}:/src",
                  "-v", f"{TEST_VOLUME}:/build", DEV_IMAGE, "sh", "-c", script)
    print("\nRendered screens: firmware/esp32/build-test/screens/ and screens/oled/ "
          "(references: firmware/esp32/test/screens/ and screens/oled/)")
    if update_screens and code == 0:
        print("References updated: look at every changed PNG (git status) before committing.")
    return code


def clean() -> int:
    for name in ("build", WOKWI_BUILD, MODEM_BUILD, POD_BUILD, BENCH_BUILD, "build-test"):
        path = FW / name
        if path.exists():
            shutil.rmtree(path)
            print(f"removed firmware/esp32/{name}/")
    # A plain `idf.py build` (BRING_UP.md, CI) writes firmware/esp32/sdkconfig;
    # remove it too, so the next build starts from sdkconfig.defaults.
    for name in ("sdkconfig", "sdkconfig.old"):
        path = FW / name
        if path.exists():
            path.unlink()
            print(f"removed firmware/esp32/{name}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv else 1
    command, options = argv[0], argv[1:]
    box = ["--fw-version=", "--release-keys=", "--mode-keys="]
    known = {"build": box, "wokwi": box, "modem": [], "pod": [], "bench": box,
             "test": ["--update-screens"], "clean": [], "version": []}
    if command not in known:
        return fail(f"unknown command {command!r}; run with --help")
    for option in options:
        name = option.split("=", 1)[0] + "=" if "=" in option else option
        if name not in known[command]:
            return fail(f"unknown option {option!r} for {command}")
        if name == "--fw-version=":
            value = option.split("=", 1)[1]
            if not valid_fw_version(value):
                return fail("--fw-version: MAJOR.MINOR.PATCH[-pre-release][+build], at most 31 characters")
            FW_OPTIONS["fw_version"] = value
        elif name == "--release-keys=":
            keys = release_keys_hex(option.split("=", 1)[1])
            if keys is None:
                return fail("--release-keys: 1-4 Ed25519 public keys, 64 hex digits or 44 base64 characters each")
            FW_OPTIONS["release_keys"] = keys
        elif name == "--mode-keys=":
            keys = release_keys_hex(option.split("=", 1)[1])
            if keys is None:
                return fail("--mode-keys: 1-4 Ed25519 public keys, 64 hex digits or 44 base64 characters each")
            FW_OPTIONS["mode_keys"] = keys
    if command == "clean":
        return clean()
    if command == "version":
        print(firmware_version())
        return 0
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
        if command == "modem":
            return modem()
        if command == "pod":
            return pod()
        if command == "bench":
            return bench()
        return test("--update-screens" in options)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
