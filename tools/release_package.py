#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Packages a firmware build for a GitHub release (.github/workflows/release.yml).

    python3 tools/release_package.py package --variant field-box --build-dir firmware/esp32/build \\
            --version 0.4.0 --out dist
        writes, from one ESP-IDF build folder (needs esptool, which the build image has):
          atalaia-<variant>-<version>-usb.zip     bootloader, partition table, app, flash_args and a
                                                  README with the esptool command
          atalaia-<variant>-<version>-merged.bin  one image to write at offset 0 (browser flashers)
          atalaia-<variant>-<version>.bin         the app image alone, what tools/firmware_release.py
                                                  signs (and what a controller or a box installs);
                                                  the field-box variant only: the modem and the pod
                                                  are not updated over the air (no Atalaia descriptor)
    python3 tools/release_package.py notes --version 0.4.0 --tag v0.4.0 --out notes.md
        the GitHub release's text: a pre-alpha warning, the CHANGELOG's section and links

Standard library only. It never touches a key: signing is tools/firmware_release.py's job.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SLUG = "vakaobr/atalaia-project"
NOTES_MAX = 120000  # GitHub's release body limit is 125000 characters

# What each image is for (the flashing README and the release notes).
VARIANTS = {
    "field-box": "Field Box (also the Satellite: the same image)",
    "modem": "USB radio modem (the second board, plugged into the controller)",
    "io-pod": "I/O pod (a board that lends its buttons and radio to an Android phone)",
}
# The variants a box installs over the air, so the ones with an app image and a signed release.
OTA_VARIANTS = ("field-box",)
# Fixed ZIP timestamps: the same build gives the same bundle.
ZIP_TIME = (2026, 1, 1, 0, 0, 0)


def fail(message: str) -> int:
    print(f"release_package: {message}", file=sys.stderr)
    return 1


def flash_files(build: Path) -> list[tuple[str, str]]:
    """(offset, path relative to the build folder) of every line of flash_args after the options."""
    out = []
    for line in (build / "flash_args").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"0x[0-9a-fA-F]+", parts[0]):
            out.append((parts[0], parts[1]))
    return out


def readme(variant: str, version: str, files: list[tuple[str, str]]) -> str:
    listing = "\n".join(f"  {offset}  {path}" for offset, path in files)
    return f"""Atalaia {version} firmware: {VARIANTS[variant]}

PRE-ALPHA, NOT FIELD-TESTED. Heltec WiFi LoRa 32 V4 only (ESP32-S3, 16 MB flash).
Fit the LoRa antenna before you power the board.

This folder is a build of the project's own source at tag v{version}, made by the
release workflow, with the project's two mode keys and two release keys built in.

Files and where they go (flash_args lists them for esptool):
{listing}

Flash it (esptool 4.8.1; install once with: python3 -m pip install esptool==4.8.1).
Use your board's port instead of COM5 (/dev/ttyACM0 on Linux). In this folder:

  First flash of a new board only (this erases the settings and any adoption):
    python3 -m esptool --chip esp32s3 -p COM5 erase_flash

  Write the image:
    python3 -m esptool --chip esp32s3 -p COM5 -b 921600 write_flash "@flash_args"

If the connection fails, hold PRG, press and release RST, release PRG (download
mode), or use -b 460800 or -b 115200. To flash from a browser instead, use the
-merged.bin file from the release at address 0x0.

Check the download first against SHA256SUMS on the release page. The full guide:
https://github.com/{SLUG}/blob/v{version}/docs/manuals/en/firmware.md
"""


def cmd_package(args: argparse.Namespace) -> int:
    if args.variant not in VARIANTS:
        return fail(f"--variant: one of {', '.join(VARIANTS)}")
    build = Path(args.build_dir)
    app = build / "atalaia_esp32.bin"
    if not app.is_file() or not (build / "flash_args").is_file():
        return fail(f"{build}: no atalaia_esp32.bin and flash_args (is the build done?)")
    files = flash_files(build)
    if not files or any(not (build / path).is_file() for _, path in files):
        return fail("flash_args names a file the build folder does not have")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"atalaia-{args.variant}-{args.version}"
    # The app image alone: what the release tool signs.
    names = [f"{stem}-usb.zip", f"{stem}-merged.bin"]
    if args.variant in OTA_VARIANTS:
        shutil.copyfile(app, out / f"{stem}.bin")
        names.insert(0, f"{stem}.bin")
    # The USB bundle: the build's own relative paths, so that flash_args works as it is.
    with zipfile.ZipFile(out / f"{stem}-usb.zip", "w", zipfile.ZIP_DEFLATED) as z:
        def add(name: str, data: bytes) -> None:
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, data)
        add("flash_args", (build / "flash_args").read_bytes())
        for _, path in files:
            add(path, (build / path).read_bytes())
        add("README.txt", readme(args.variant, args.version, files).encode("utf-8"))
    # One image for a browser flasher: everything of flash_args merged, to write at offset 0.
    merged = out / f"{stem}-merged.bin"
    code = subprocess.call([sys.executable, "-m", "esptool", "--chip", "esp32s3", "merge_bin",
                            "-o", str(merged.resolve()), "@flash_args"], cwd=build)
    if code != 0 or not merged.is_file():
        return fail("esptool merge_bin failed")
    for name in names:
        print(f"{name}: {(out / name).stat().st_size} bytes")
    return 0


def changelog_section(version: str) -> str | None:
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else None


def cmd_notes(args: argparse.Namespace) -> int:
    section = changelog_section(args.version)
    if not section:
        return fail(f"CHANGELOG.md has no section [{args.version}]")
    base = f"https://github.com/{SLUG}"
    head = f"""> **Pre-alpha. Not field-tested.** This is a pre-release for builders and testers. The software is
> tested in simulation and on a bench with real Heltec V4.3 boards, not in a real game. Do not rely on it
> for a game that matters, and expect things to change.

**Which file?** Field Box (also the Satellite), USB radio modem and I/O pod are separate images (`atalaia-field-box-`,
`atalaia-modem-`, `atalaia-io-pod-`). Each comes as `-usb.zip` (flash it with esptool over USB, a README inside says
how) and `-merged.bin` (one file for a browser flasher, written at address 0x0). The Field Box also has the plain
`.bin` with its signed `.release.json`, what a controller or a box checks for an update over the air (the modem and
the pod are not updated that way). Check what you downloaded against `SHA256SUMS`.

**Signed with two release keys:** root `424d053af5cdbc35` (held offline by the maintainer) and CI
`32b3c815ac30ad43` (this release is signed with the CI key; both are built into the firmware).

Guides: [Firmware guide]({base}/blob/{args.tag}/docs/manuals/en/firmware.md) (download, flash, build it yourself) ·
[Release signing]({base}/blob/{args.tag}/firmware/esp32/docs/RELEASE_SIGNING.md) ·
[Controller setup]({base}/blob/{args.tag}/docs/manuals/en/controller-setup.md)

## What is in this release

"""
    body = head + section + "\n"
    if len(body) > NOTES_MAX:
        cut = NOTES_MAX - 400
        body = (body[:cut].rsplit("\n", 1)[0]
                + f"\n\n(The rest of the list is in [CHANGELOG.md]({base}/blob/{args.tag}/CHANGELOG.md).)\n")
    Path(args.out).write_text(body, encoding="utf-8")
    print(f"{args.out}: {len(body)} characters")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("package", help="the USB bundle, the merged image and the app image of one build")
    p.add_argument("--variant", required=True)
    p.add_argument("--build-dir", required=True)
    p.add_argument("--version", required=True)
    p.add_argument("--out", required=True)
    n = sub.add_parser("notes", help="the GitHub release's text")
    n.add_argument("--version", required=True)
    n.add_argument("--tag", required=True)
    n.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    return cmd_package(args) if args.command == "package" else cmd_notes(args)


if __name__ == "__main__":
    sys.exit(main())
