#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Secure boot v2 signing and checks for the hardened Field Box release (RELEASE_HARDENING.md).

Runs where ESP-IDF's environment is exported (espsecure.py: the espressif/idf image, CI's ESP32
jobs); `tools/docker_fw.py release-hardened` runs it for you. Nothing here touches a board or an eFuse.

    python3 tools/secure_boot_sign.py sign IMAGE [IMAGE...] --key ~/keys/sb-ci.pem [--key ~/keys/sb-root.pem]
        signs bootloader and app images with espsecure.py sign_data --version 2 (RSA-3072; one
        signature block per key, at most 3, all in the image's one 4 KB signature sector), checks
        every signature with verify_signature and prints each key's public-key digest (what
        espefuse burns). Writes each IMAGE's name with .signed.bin (--out: for a single image).
        Keys outside the repository only.
    python3 tools/secure_boot_sign.py sign IMAGE [IMAGE...] --throwaway-test-key
        the same with one RSA-3072 key made for this run in a temporary folder and deleted
        afterwards (every image of the run gets the same key): IMAGE's name with .test-signed.bin.
        TEST ONLY: no box will ever trust it, and nothing signed with it may be flashed to a board
        that is to keep working.
    python3 tools/secure_boot_sign.py check-config BUILD/sdkconfig [--overlay firmware/esp32/sdkconfig.release]
        fails unless every option the overlay sets is in the build's sdkconfig with the same value
        (a misspelt or renamed option is dropped by ESP-IDF without a word) and no bench option is on
    python3 tools/secure_boot_sign.py check-sizes BUILD
        the signed bootloader against the room below the partition table, the signed app against
        the smallest app slot of the build's partition table; fails when either does not fit
    python3 tools/secure_boot_sign.py --selftest
        the checks above on made-up files (no ESP-IDF needed; tools/check.sh runs it)

In a release, the app is signed here BEFORE tools/firmware_release.py sign: the Ed25519 manifest
hashes the exact bytes a box downloads, signature block included (RELEASE_SIGNING.md, "Secure boot
signature").
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OVERLAY = REPO / "firmware" / "esp32" / "sdkconfig.release"
MAX_KEYS = 3  # the ESP32-S3's secure boot digest slots
BENCH_OPTIONS = ("CONFIG_ATALAIA_SERIAL_KEYS", "CONFIG_ATALAIA_SKIP_SETUP", "CONFIG_ATALAIA_RADIO_LOG_PACKETS",
                 "CONFIG_ATALAIA_LBT_BENCH")
SET = re.compile(r"^(CONFIG_[A-Z0-9_]+)=(.*)$")
UNSET = re.compile(r"^# (CONFIG_[A-Z0-9_]+) is not set$")


def fail(message: str) -> int:
    print(f"secure_boot_sign: {message}", file=sys.stderr)
    return 1


def outside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO)
    except ValueError:
        return True
    return False


# ---- sdkconfig -------------------------------------------------------------------------------

def read_options(text: str) -> dict[str, str | None]:
    """CONFIG_X=value lines and "# CONFIG_X is not set" lines (None) of an sdkconfig or a defaults file."""
    out: dict[str, str | None] = {}
    for line in text.splitlines():
        line = line.strip()
        if m := SET.match(line):
            out[m.group(1)] = m.group(2)
        elif m := UNSET.match(line):
            out[m.group(1)] = None
    return out


def config_problems(overlay: str, sdkconfig: str) -> list[str]:
    wanted, built = read_options(overlay), read_options(sdkconfig)
    problems = []
    for name, value in wanted.items():
        got = built.get(name)
        if value is None and got not in (None, "n"):
            problems.append(f"{name} should be unset, the build has {got}")
        elif value is not None and got != value:
            problems.append(f"{name}={value} wanted, the build has "
                            + ("no such option (renamed, misspelt, or its dependencies are off?)"
                               if name not in built else f"{name}={got}" if got is not None else "it unset"))
    problems += [f"{name} (a bench option) is on" for name in BENCH_OPTIONS if built.get(name) == "y"]
    return problems


def cmd_check_config(args: argparse.Namespace) -> int:
    problems = config_problems(Path(args.overlay).read_text(encoding="utf-8"),
                               Path(args.sdkconfig).read_text(encoding="utf-8"))
    for p in problems:
        print(f"FAIL {p}")
    if problems:
        return fail(f"{args.sdkconfig} is not the configuration of {args.overlay}")
    print(f"OK: every option of {Path(args.overlay).name} is in {args.sdkconfig}, no bench option on")
    return 0


# ---- sizes -----------------------------------------------------------------------------------

def smallest_app_slot(partitions_csv: str) -> int:
    sizes = []
    for row in csv.reader(io.StringIO(partitions_csv)):
        cells = [c.strip() for c in row]
        if not cells or not cells[0] or cells[0].startswith("#") or len(cells) < 5:
            continue
        if cells[1] == "app":
            size = cells[4].lower()
            sizes.append(int(size[:-1]) * (1024 if size.endswith("k") else 1024 * 1024)
                         if size[-1:] in ("k", "m") else int(size, 0))
    if not sizes:
        raise ValueError("no app partition in the partition table")
    return min(sizes)


def size_report(boot_size: int, boot_room: int, app_size: int, slot: int) -> tuple[list[str], bool]:
    lines = [f"signed bootloader: {boot_size} bytes (0x{boot_size:x}) of {boot_room} (0x{boot_room:x}) below "
             f"the partition table, {boot_size * 100 / boot_room:.2f} %, {boot_room - boot_size} bytes free",
             f"signed app: {app_size} bytes (0x{app_size:x}) of the {slot} byte (0x{slot:x}) app slot, "
             f"{app_size * 100 / slot:.2f} %, {slot - app_size} bytes free"]
    ok = boot_size <= boot_room and app_size <= slot
    return lines, ok


def signed_outputs(build: Path) -> tuple[Path, Path]:
    """The signed bootloader and app of a build folder (real-key signatures before test ones)."""
    def pick(folder: Path, stem: str) -> Path:
        for suffix in (".signed.bin", ".test-signed.bin"):
            if (folder / (stem + suffix)).exists():
                return folder / (stem + suffix)
        raise FileNotFoundError(f"{folder / stem}.signed.bin (or .test-signed.bin): sign it first")
    return pick(build / "bootloader", "bootloader"), pick(build, "atalaia_esp32")


def cmd_check_sizes(args: argparse.Namespace) -> int:
    build = Path(args.build)
    opts = read_options((build / "sdkconfig").read_text(encoding="utf-8"))
    table_offset = int(opts.get("CONFIG_PARTITION_TABLE_OFFSET") or "0x8000", 0)
    boot_offset = int(opts.get("CONFIG_BOOTLOADER_OFFSET_IN_FLASH") or "0x0", 0)
    table_name = (opts.get("CONFIG_PARTITION_TABLE_CUSTOM_FILENAME") or '"partitions.csv"').strip('"')
    table = (build.parent / table_name).read_text(encoding="utf-8")
    try:
        boot, app = signed_outputs(build)
    except FileNotFoundError as exc:
        return fail(str(exc))
    lines, ok = size_report(boot.stat().st_size, table_offset - boot_offset, app.stat().st_size,
                            smallest_app_slot(table))
    print(f"{boot.relative_to(build.parent)}, {app.relative_to(build.parent)}:")
    for line in lines:
        print(f"  {line}")
    if not ok:
        return fail("an image does not fit (RELEASE_HARDENING.md, section 3: a bigger bootloader moves the "
                    "partition table, which is a new layout)")
    return 0


# ---- signing ---------------------------------------------------------------------------------

def espsecure(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "espsecure", *args], capture_output=True, text=True)


def run_espsecure(*args: str) -> str:
    out = espsecure(*args)
    if out.returncode != 0:
        raise SystemExit(fail(f"espsecure.py {args[0]} failed:\n{out.stdout}{out.stderr}"))
    return out.stdout


def sign(jobs: list[tuple[Path, Path]], keys: list[Path], test_only: bool) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        digests = []
        for key in keys:
            digest_file = Path(tmp) / "digest.bin"
            run_espsecure("digest_sbv2_public_key", "--keyfile", str(key), "--output", str(digest_file))
            digests.append(digest_file.read_bytes().hex())
    for i, (key, digest) in enumerate(zip(keys, digests), 1):
        label = "THROW-AWAY TEST KEY, deleted after this run" if test_only else str(key)
        print(f"key {i}: public-key digest {digest} ({label})")
    for image, out in jobs:
        run_espsecure("sign_data", "--version", "2", "--keyfile", *map(str, keys), "--output", str(out), str(image))
        for key in keys:
            run_espsecure("verify_signature", "--version", "2", "--keyfile", str(key), str(out))
        print(f"{out}: {out.stat().st_size} bytes (unsigned {image.stat().st_size}), "
              f"{len(keys)} secure boot v2 signature block(s), each verified")
    if test_only:
        print("TEST ONLY: signed with a key that no longer exists; never flash these to a board meant to keep working")
    return 0


def cmd_sign(args: argparse.Namespace) -> int:
    images = [Path(i) for i in args.image]
    for image in images:
        if not image.is_file():
            return fail(f"{image}: no such image")
    if args.throwaway_test_key == bool(args.key):
        return fail("give --key PATH (1 to 3 times) or --throwaway-test-key, not both")
    if args.out and len(images) != 1:
        return fail("--out is for a single image")
    suffix = ".test-signed.bin" if args.throwaway_test_key else ".signed.bin"
    jobs = [(image, Path(args.out) if args.out else image.with_name(image.name.removesuffix(".bin") + suffix))
            for image in images]
    if args.throwaway_test_key:
        if args.out and not args.out.endswith(".test-signed.bin"):
            return fail("an image signed with a throw-away key is named *.test-signed.bin")
        with tempfile.TemporaryDirectory(prefix="atalaia-sb-test-") as tmp:
            key = Path(tmp) / "throwaway-test-only.pem"
            run_espsecure("generate_signing_key", "--version", "2", "--scheme", "rsa3072", str(key))
            return sign(jobs, [key], test_only=True)
    keys = [Path(k).expanduser() for k in args.key]
    if len(keys) > MAX_KEYS:
        return fail(f"at most {MAX_KEYS} keys (the chip's digest slots)")
    for key in keys:
        if not key.is_file():
            return fail(f"{key}: no such key")
        if not outside_repo(key):
            return fail(f"{key} is inside the repository: a private key never goes there")
    if any(out.name.endswith(".test-signed.bin") for _, out in jobs):
        return fail("*.test-signed.bin is for throw-away keys only")
    return sign(jobs, keys, test_only=False)


# ---- self-test -------------------------------------------------------------------------------

def selftest() -> int:
    overlay = "# c\nCONFIG_A=y\n# CONFIG_B is not set\nCONFIG_C=1\n"
    good = "CONFIG_A=y\n# CONFIG_B is not set\nCONFIG_C=1\nCONFIG_D=y\n"
    assert config_problems(overlay, good) == [], config_problems(overlay, good)
    assert config_problems(overlay, good.replace("CONFIG_C=1", "CONFIG_C=2")) == [
        "CONFIG_C=1 wanted, the build has CONFIG_C=2"]
    missing = config_problems(overlay, "CONFIG_A=y\n")
    assert len(missing) == 1 and "no such option" in missing[0], missing
    assert config_problems(overlay, good + "CONFIG_B=y\n") == ["CONFIG_B should be unset, the build has y"]
    assert config_problems("", "CONFIG_ATALAIA_SKIP_SETUP=y\n") == [
        "CONFIG_ATALAIA_SKIP_SETUP (a bench option) is on"]
    real = read_options(OVERLAY.read_text(encoding="utf-8"))
    assert real.get("CONFIG_SECURE_BOOT") == "y" and real.get("CONFIG_SECURE_BOOT_BUILD_SIGNED_BINARIES", 0) is None
    assert real.get("CONFIG_BOOTLOADER_APP_SECURE_VERSION") == "1"
    assert not any(name.startswith("CONFIG_ATALAIA_") for name in real), "the overlay sets no Atalaia option"
    table = (REPO / "firmware" / "esp32" / "partitions.csv").read_text(encoding="utf-8")
    assert smallest_app_slot(table) == 0x400000
    assert smallest_app_slot("a, app, ota_0, 0x10000, 1M,\nb, app, ota_1, , 512K,\n") == 512 * 1024
    _, ok = size_report(0x7000, 0x8000, 0x3F0000, 0x400000)
    assert ok
    _, ok = size_report(0x8001, 0x8000, 0x3F0000, 0x400000)
    assert not ok
    assert not outside_repo(REPO / "x.pem") and outside_repo(Path(os.path.expanduser("~")) / ".nope" / "k.pem")
    print("secure_boot_sign: self-test passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--selftest"]:
        return selftest()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("sign", help="sign an image for secure boot v2")
    s.add_argument("image", nargs="+")
    s.add_argument("--key", action="append", default=[], help="RSA-3072 private key (PEM), outside the repository")
    s.add_argument("--throwaway-test-key", action="store_true", help="a key made for this run only (test only)")
    s.add_argument("--out", default="")
    c = sub.add_parser("check-config", help="the overlay's options against a build's sdkconfig")
    c.add_argument("sdkconfig")
    c.add_argument("--overlay", default=str(OVERLAY))
    z = sub.add_parser("check-sizes", help="the signed images against the flash layout")
    z.add_argument("build")
    args = parser.parse_args(argv)
    return {"sign": cmd_sign, "check-config": cmd_check_config, "check-sizes": cmd_check_sizes}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
