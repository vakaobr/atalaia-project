#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The eFuse burn of a hardened Field Box, written down as a script that refuses to run by default.

ON HOLD (maintainer's decision, 2026-11-07, RELEASE_HARDENING.md section 5 question 1): no board,
bench or field, gets the hardened image or any eFuse burn until the maintainer decides otherwise.
This script exists so that the sequence is reviewed, tested and fixed before that day; by default
it only prints it.

    python3 tools/hardened_burn.py --build firmware/esp32/build-hardened \\
            --flash-key ~/atalaia-hardened/flash-key.bin \\
            --root-pubkey ~/atalaia-sb-keys/sb-root.pub.pem --ci-pubkey ~/atalaia-sb-keys/sb-ci.pub.pem \\
            [--spare-pubkey ~/atalaia-sb-keys/sb-spare.pub.pem] [--security-version 1] \\
            [--record ~/atalaia-hardened-boxes.log]
        THE DEFAULT: a dry run. Checks the build (every option of sdkconfig.release, the security
        version, the bootloader signed by both the root and the CI key, the app by one of them),
        the flash key and the public keys, then prints every esptool/espefuse command in order and
        the record line it would write. Opens no port.

    ... --port /dev/cu.usbmodemXXXX --i-understand-this-is-permanent=<the board's MAC>
        THE BURN. Refused unless both are given. Reads the chip's MAC and refuses unless it is the
        one typed; reads its eFuses and refuses unless the chip is blank (no key, no secure boot,
        no flash encryption, security version 0); then erases and writes the flash and burns, in
        this order: the flash-encryption key, the secure boot digests, the security version,
        secure boot. Appends a record line (MAC, digests, security version, flash key id) to
        --record whatever happens after the first burn.

    python3 tools/hardened_burn.py --selftest
        the planning, the argument checks and the guards with a fake device (no esptool needed)

The sequence (plan section 2 and 4, decisions HPR-*):
  1. esptool write_flash, with the ROM loader alone (--no-stub): one image from 0x0 to the end of
     the last data partition below the app (the signed bootloader, the partition table and
     otadata, with nvs, phy_init and nvs_keys blank: no NVS of the board's plain life, where its
     old join key, PIN and Wi-Fi password were, survives), and the signed app at its slot; all
     plaintext, which the first boot encrypts in place. ota_1 and storage are not rewritten:
     nothing secret is kept there, and a stale image in ota_1 fails secure boot. --erase-first
     adds an esptool erase_flash before it (with the flasher stub: the ROM has no erase_flash),
     for a board with a past; the emulator test leaves it out, as its stub session does not come
     back to the ROM, and writing the whole 16 MB through the emulated ROM takes 40 minutes.
  2. espefuse burn_key BLOCK_KEY0 <flash key> XTS_AES_128_KEY: the host-made key, kept offline
     (question 2), read- and write-protected by espefuse.
  3. espefuse burn_key BLOCK_KEY1 <root digest> SECURE_BOOT_DIGEST0 BLOCK_KEY2 <CI digest>
     SECURE_BOOT_DIGEST1 [BLOCK_KEY3 <spare digest> SECURE_BOOT_DIGEST2] (question 4). Without
     --spare-pubkey the third slot stays empty, which works only because secure boot is enabled
     here, from the host, before the first boot (step 5), and the image allows unused slots
     (CONFIG_SECURE_BOOT_ALLOW_UNUSED_DIGEST_SLOTS): the bootloader would revoke it otherwise.
  4. espefuse burn_efuse SECURE_VERSION <bits>: anti-rollback at security version 1 (question 5).
  5. espefuse burn_efuse SOFT_DIS_JTAG 7 SECURE_BOOT_EN 1, last: from here the ROM checks the
     bootloader's signature. The bootloader skips its own secure boot enable (and the eFuses it
     would burn with it) when secure boot is on already; the JTAG soft-disable is the one it
     would burn that its flash-encryption enable does not (it burns HARD_DIS_JTAG, DIS_USB_JTAG,
     DIS_DIRECT_BOOT, the download caches, the manual encryption off and the secure download mode
     at the first boot, in release mode).
NVS encryption takes no eFuse: with the flash-encryption scheme (question 3) the app makes its
keys in the nvs_keys partition at its first start. Then reset the box and do not cut its power
during the first boot (it encrypts the whole flash in place).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import secure_boot_sign as sbs  # noqa: E402

CHIP = "esp32s3"
CONFIRM = "--i-understand-this-is-permanent"
MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
DEFAULT_RECORD = Path("~/atalaia-hardened-boxes.log")
KEY_BLOCKS = ("BLOCK_KEY0", "BLOCK_KEY1", "BLOCK_KEY2", "BLOCK_KEY3", "BLOCK_KEY4", "BLOCK_KEY5")
# eFuses that must be blank before a burn (espefuse summary --format json values).
BLANK = {"SECURE_BOOT_EN": False, "SECURE_VERSION": 0, "SOFT_DIS_JTAG": 0, "ENABLE_SECURITY_DOWNLOAD": False,
         "DIS_DOWNLOAD_MODE": False, "SECURE_BOOT_KEY_REVOKE0": False, "SECURE_BOOT_KEY_REVOKE1": False,
         "SECURE_BOOT_KEY_REVOKE2": False, "SECURE_BOOT_AGGRESSIVE_REVOKE": False}


class Refused(Exception):
    """A reason not to go on; nothing (more) is done to the device."""


@dataclass
class Step:
    tool: str               # "esptool" or "espefuse"
    args: list[str]         # after --chip/--port
    what: str
    permanent: bool = False  # an eFuse burn


@dataclass
class Plan:
    mac: str                # "" in a dry run
    digests: list[str]      # root, CI, and the spare (or "")
    security_version: int
    flash_key_id: str
    app_sha256: str
    firmware: str
    steps: list[Step] = field(default_factory=list)
    digest_files: list[Path] = field(default_factory=list)  # what espefuse burns: root, CI, spare
    flash_image: Optional[Path] = None                       # the image from 0x0 (step 1)
    flash_parts: dict = field(default_factory=dict)          # offset -> file, what it is made of
    flash_size: int = 0                                      # of that image

    def record_line(self, status: str, when: Optional[str] = None) -> str:
        when = when or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return "\t".join([when, f"mac={self.mac or '<the board MAC>'}", f"security_version={self.security_version}",
                          f"digest0={self.digests[0]}", f"digest1={self.digests[1]}",
                          f"digest2={self.digests[2] or 'empty'}", f"flash_key_id={self.flash_key_id}",
                          f"firmware={self.firmware}", f"app_sha256={self.app_sha256}", f"status={status}"])


def normal_mac(text: str) -> Optional[str]:
    mac = text.strip().lower().replace("-", ":")
    if re.fullmatch(r"[0-9a-f]{12}", mac):
        mac = ":".join(mac[i:i + 2] for i in range(0, 12, 2))
    return mac if MAC.match(mac) else None


def secure_version_bits(version: int) -> int:
    """The SECURE_VERSION eFuse's value for a security version: one bit per step (ESP-IDF counts the
    ones, esp_efuse_read_secure_version), so 1 is 0b1, 2 is 0b11."""
    if not 1 <= version <= 16:
        raise Refused("the security version is 1 to 16 (16 eFuse bits for the chip's whole life)")
    return (1 << version) - 1


def outside_repo(path: Path) -> bool:
    return sbs.outside_repo(path)


# ---- the build -------------------------------------------------------------------------------

@dataclass
class Build:
    folder: Path
    sdkconfig: dict
    bootloader: Path
    app: Path
    flash: dict          # offset (int) -> path, besides the bootloader
    write_args: list[str]
    low_end: int        # the end of the last partition below the app: the image from 0x0 covers it
    bootloader_offset: int
    firmware: str


def read_build(folder: Path) -> Build:
    sdk = folder / "sdkconfig"
    if not sdk.is_file():
        raise Refused(f"{sdk}: no such file (build it with tools/docker_fw.py release-hardened)")
    sdk_text = sdk.read_text(encoding="utf-8")
    problems = sbs.config_problems(sbs.OVERLAY.read_text(encoding="utf-8"), sdk_text)
    if problems:
        raise Refused(f"{sdk} is not the hardened configuration: " + "; ".join(problems))
    opts = sbs.read_options(sdk_text)
    boot, app = folder / "bootloader" / "bootloader.signed.bin", folder / "atalaia_esp32.signed.bin"
    for image in (boot, app):
        if not image.is_file():
            test = image.with_name(image.name.replace(".signed.bin", ".test-signed.bin"))
            raise Refused(f"{image}: no such file" + (
                f" ({test.name} is signed with a key that no longer exists: never burn a box for it)"
                if test.exists() else " (docker_fw.py release-hardened --secure-boot-key ...)"))
    args = json.loads((folder / "flasher_args.json").read_text(encoding="utf-8"))
    flash = {}
    for offset, name in args["flash_files"].items():
        path = folder / name
        if path.resolve() == (folder / "atalaia_esp32.bin").resolve():
            path = app
        if not path.is_file():
            raise Refused(f"{path}: no such file (an incomplete build)")
        flash[int(offset, 0)] = path
    if app not in flash.values():
        raise Refused("flasher_args.json has no app")
    desc = json.loads((folder / "project_description.json").read_text(encoding="utf-8")) \
        if (folder / "project_description.json").exists() else {}
    return Build(folder=folder, sdkconfig=opts, bootloader=boot, app=app, flash=flash,
                 write_args=list(args.get("write_flash_args", [])),
                 low_end=low_end(folder, opts, min(o for o, p in flash.items() if p == app)),
                 bootloader_offset=int(opts.get("CONFIG_BOOTLOADER_OFFSET_IN_FLASH") or "0x0", 0),
                 firmware=str(desc.get("project_version", "unknown")))


def low_end(folder: Path, opts: dict, app_offset: int) -> int:
    """The end of the last partition that starts below the app's slot (partitions.csv as the build
    names it): the image from 0x0 blanks everything up to there."""
    name = (opts.get("CONFIG_PARTITION_TABLE_CUSTOM_FILENAME") or '"partitions.csv"').strip('"')
    table = folder.parent / name
    if not table.is_file():
        raise Refused(f"{table}: no such file (the build's partition table)")
    end = 0
    for line in table.read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < 5 or not cells[0] or cells[0].startswith("#") or not cells[3]:
            continue
        offset, size = int(cells[3], 0), cells[4].lower()
        size = (int(size[:-1]) * (1024 if size.endswith("k") else 1024 * 1024) if size[-1:] in ("k", "m")
                else int(size, 0))
        if offset < app_offset:
            end = max(end, offset + size)
    if end == 0 or end > app_offset:
        raise Refused(f"{table}: no data partitions below the app at 0x{app_offset:x}, or one runs into it")
    return end


def whole_flash(parts: dict, size: int) -> bytes:
    """parts at their offsets in an image of size bytes from 0x0, 0xFF everywhere else."""
    image = bytearray(b"\xff" * size)
    end = 0
    for offset in sorted(parts):
        data = Path(parts[offset]).read_bytes()
        if offset < end or offset + len(data) > size:
            raise Refused(f"{parts[offset]} at 0x{offset:x} overlaps another part or the end of the flash")
        image[offset:offset + len(data)] = data
        end = offset + len(data)
    return bytes(image)


# ---- espsecure (host files only) -------------------------------------------------------------

def espsecure_digest(pubkey: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="atalaia-burn-") as tmp:
        out = Path(tmp) / "digest.bin"
        sbs.run_espsecure("digest_sbv2_public_key", "--keyfile", str(pubkey), "--output", str(out))
        return out.read_bytes().hex()


def espsecure_signed_by(image: Path, pubkey: Path) -> bool:
    return sbs.espsecure("verify_signature", "--version", "2", "--keyfile", str(pubkey), str(image)).returncode == 0


# ---- the plan --------------------------------------------------------------------------------

def make_plan(build: Build, flash_key: Path, pubkeys: list[Optional[Path]], security_version: int,
              digest_of: Callable[[Path], str] = espsecure_digest,
              signed_by: Callable[[Path, Path], bool] = espsecure_signed_by,
              key_dir: Optional[Path] = None, erase_first: bool = False) -> Plan:
    """Every check that needs no device, then the steps. pubkeys: root, CI, spare (or None).
    key_dir: where the digest files for espefuse go (a temporary folder at burn time)."""
    root, ci, spare = pubkeys
    if root is None or ci is None:
        raise Refused("--root-pubkey and --ci-pubkey are both needed (two digests, plan question 4)")
    want = int(build.sdkconfig.get("CONFIG_BOOTLOADER_APP_SECURE_VERSION") or 0)
    if want != security_version:
        raise Refused(f"the image's security version is {want}, not {security_version}")
    bits = secure_version_bits(security_version)
    if spare is None and build.sdkconfig.get("CONFIG_SECURE_BOOT_ALLOW_UNUSED_DIGEST_SLOTS") != "y":
        raise Refused("an empty spare slot needs CONFIG_SECURE_BOOT_ALLOW_UNUSED_DIGEST_SLOTS in the image; "
                      "give --spare-pubkey or rebuild")
    for path in (flash_key, *[p for p in pubkeys if p is not None]):
        if not path.is_file():
            raise Refused(f"{path}: no such file")
        if not outside_repo(path):
            raise Refused(f"{path} is inside the repository: keys never go there")
    key = flash_key.read_bytes()
    if len(key) != 32:
        raise Refused(f"{flash_key}: an XTS-AES-128 key is 32 bytes as espefuse takes it, not {len(key)}")
    if key in (bytes(32), b"\xff" * 32):
        raise Refused(f"{flash_key}: all zeros or all ones is not a key")
    digests = [digest_of(root), digest_of(ci), digest_of(spare) if spare is not None else ""]
    if len({d for d in digests if d}) != len([d for d in digests if d]):
        raise Refused("two of the public keys are the same key")
    if not (signed_by(build.bootloader, root) and signed_by(build.bootloader, ci)):
        raise Refused(f"{build.bootloader} must be signed by both the root and the CI key "
                      "(docker_fw.py release-hardened --secure-boot-key ROOT --secure-boot-key CI)")
    if not (signed_by(build.app, root) or signed_by(build.app, ci)):
        raise Refused(f"{build.app} is signed by neither the root nor the CI key: the box would not boot it")

    kd = key_dir or Path("<temporary folder>")
    names = ["root", "ci", "spare"]
    digest_files = [kd / f"sb-{names[i]}.digest.bin" for i in range(3)]
    plan = Plan(mac="", digests=digests, security_version=security_version,
                flash_key_id=hashlib.sha256(key).hexdigest()[:16],
                app_sha256=hashlib.sha256(build.app.read_bytes()).hexdigest(), firmware=build.firmware)
    plan.flash_parts = {o: p for o, p in {build.bootloader_offset: build.bootloader, **build.flash}.items()
                        if o < build.low_end}
    plan.flash_size = build.low_end
    plan.flash_image = kd / "boot-region.bin"
    whole_flash(plan.flash_parts, build.low_end)  # the parts fit, or Refused
    made_of = ", ".join(f"0x{o:x} {Path(f).name}" for o, f in sorted(plan.flash_parts.items()))
    apps = [(o, p) for o, p in sorted(build.flash.items()) if o >= build.low_end]
    if erase_first:
        plan.steps.append(Step("esptool", ["erase_flash"], "erase the whole flash (with the flasher stub)"))
    plan.steps.append(Step("esptool", ["write_flash", *build.write_args, "0x0", str(plan.flash_image),
                                       *[x for o, p in apps for x in (hex(o), str(p))]],
                           f"write 0x0-0x{build.low_end:x} ({made_of}; nvs, phy_init and nvs_keys blank) and "
                           + ", ".join(f"0x{o:x} {Path(p).name}" for o, p in apps)))
    plan.steps.append(Step("espefuse", ["burn_key", "BLOCK_KEY0", str(flash_key), "XTS_AES_128_KEY"],
                           f"the flash-encryption key (id {plan.flash_key_id}), read- and write-protected",
                           permanent=True))
    sb = ["burn_key", "BLOCK_KEY1", str(digest_files[0]), "SECURE_BOOT_DIGEST0",
          "BLOCK_KEY2", str(digest_files[1]), "SECURE_BOOT_DIGEST1"]
    if spare is not None:
        sb += ["BLOCK_KEY3", str(digest_files[2]), "SECURE_BOOT_DIGEST2"]
    plan.steps.append(Step("espefuse", sb, "the secure boot digests: root (slot 0), CI (slot 1), "
                           + ("spare (slot 2)" if spare is not None else "slot 2 left empty"), permanent=True))
    plan.steps.append(Step("espefuse", ["burn_efuse", "SECURE_VERSION", hex(bits)],
                           f"anti-rollback: security version {security_version}", permanent=True))
    plan.steps.append(Step("espefuse", ["burn_efuse", "SOFT_DIS_JTAG", "7", "SECURE_BOOT_EN", "1"],
                           "secure boot on (the ROM checks the bootloader from the next boot), JTAG soft-disabled",
                           permanent=True))
    plan.digest_files = digest_files
    return plan


def command(step: Step, port: str) -> list[str]:
    base = [sys.executable, "-m", step.tool, "--chip", CHIP, "--port", port, "--before", "default_reset"]
    if step.tool == "esptool":
        stub = [] if step.args[0] == "erase_flash" else ["--no-stub"]
        return base + ["--after", "no_reset", *stub, *step.args]
    return base + ["--do-not-confirm", *step.args]


def print_plan(plan: Plan, port: str) -> None:
    print("The burn, in this order (each eFuse step is permanent):")
    for i, step in enumerate(plan.steps, 1):
        mark = "PERMANENT" if step.permanent else "flash"
        print(f"  {i}. [{mark}] {step.what}")
        print("     " + " ".join(command(step, port)))
    print("  then: reset the box; its first boot encrypts the flash in place and burns the remaining "
          "protections (do not cut its power), and the app makes the NVS keys.")
    print("Record line (appended to the record file after a burn):")
    print("  " + plan.record_line("burned"))


# ---- the device ------------------------------------------------------------------------------

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def run_tool(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def chip_mac(port: str, runner: Runner) -> str:
    out = runner([sys.executable, "-m", "esptool", "--chip", CHIP, "--port", port, "--before", "default_reset",
                  "--after", "no_reset", "--no-stub", "read_mac"])
    if out.returncode != 0:
        raise Refused(f"esptool read_mac failed:\n{out.stdout}{out.stderr}")
    found = re.findall(r"MAC:\s*([0-9a-fA-F:]{17})", out.stdout)
    if not found:
        raise Refused("esptool read_mac printed no MAC")
    return found[-1].lower()


def chip_efuses(port: str, runner: Runner) -> dict:
    with tempfile.TemporaryDirectory(prefix="atalaia-burn-") as tmp:
        path = Path(tmp) / "efuses.json"
        out = runner([sys.executable, "-m", "espefuse", "--chip", CHIP, "--port", port, "--before", "default_reset",
                      "summary", "--format", "json", "--file", str(path)])
        if out.returncode != 0 or not path.exists():
            raise Refused(f"espefuse summary failed:\n{out.stdout}{out.stderr}")
        return json.loads(path.read_text(encoding="utf-8"))


def blank_problems(efuses: dict, blocks: int) -> list[str]:
    """What is not blank on the chip: secure boot, flash encryption, the security version, JTAG,
    download mode, revocations, and the key blocks the burn uses."""
    problems = []
    for name, want in BLANK.items():
        got = efuses.get(name, {}).get("value")
        if got != want:
            problems.append(f"{name} is {got!r}")
    crypt = efuses.get("SPI_BOOT_CRYPT_CNT", {}).get("value")
    if crypt not in ("Disable", 0):
        problems.append(f"SPI_BOOT_CRYPT_CNT is {crypt!r} (flash encryption has been on)")
    for i in range(blocks):
        purpose = efuses.get(f"KEY_PURPOSE_{i}", {}).get("value")
        if purpose != "USER":
            problems.append(f"KEY_PURPOSE_{i} is {purpose!r}")
        value = str(efuses.get(KEY_BLOCKS[i], {}).get("value", "?")).replace(" ", "")
        if value.strip("0") != "":
            problems.append(f"{KEY_BLOCKS[i]} is not empty")
    return problems


def burn(plan: Plan, port: str, confirm_mac: str, record: Path, runner: Runner = run_tool) -> int:
    mac = chip_mac(port, runner)
    if mac != confirm_mac:
        raise Refused(f"the chip on {port} is {mac}, not {confirm_mac}: nothing was done")
    plan.mac = mac
    blocks = 4 if plan.digests[2] else 3
    problems = blank_problems(chip_efuses(port, runner), blocks)
    if problems:
        raise Refused(f"{mac} is not a blank chip: " + "; ".join(problems) + ". Nothing was done")
    burned = 0
    try:
        for i, step in enumerate(plan.steps, 1):
            print(f"step {i}: {step.what}", flush=True)
            out = runner(command(step, port))
            if out.returncode != 0:
                print(out.stdout + out.stderr, file=sys.stderr)
                raise Refused(f"step {i} failed ({step.tool} {step.args[0]})")
            burned += step.permanent
    finally:
        if burned:
            status = "burned" if burned == sum(s.permanent for s in plan.steps) else f"PARTIAL-{burned}-burns"
            record.parent.mkdir(parents=True, exist_ok=True)
            with record.open("a", encoding="utf-8") as f:
                f.write(plan.record_line(status) + "\n")
            print(f"recorded in {record}: {status}")
    print(f"{mac}: done. Reset the box; do not cut its power during its first boot.")
    return 0


# ---- the command line ------------------------------------------------------------------------

def parse(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--build", default=str(REPO / "firmware" / "esp32" / "build-hardened"))
    p.add_argument("--flash-key", required=True, help="the XTS-AES-128 flash-encryption key, 32 bytes")
    p.add_argument("--root-pubkey", required=True, help="the root secure boot key's public half (PEM)")
    p.add_argument("--ci-pubkey", required=True, help="the CI secure boot key's public half (PEM)")
    p.add_argument("--spare-pubkey", default="", help="a third key's public half; left out: slot 2 stays empty")
    p.add_argument("--security-version", type=int, default=1)
    p.add_argument("--record", default=str(DEFAULT_RECORD))
    p.add_argument("--erase-first", action="store_true", help="esptool erase_flash before the write (stub)")
    p.add_argument("--port", default="")
    p.add_argument(CONFIRM, dest="confirm", default="", metavar="MAC")
    return p.parse_args(argv)


def check_device_args(args: argparse.Namespace) -> Optional[str]:
    """None for a dry run, the confirmed MAC for a burn; Refused when only one of the two is given
    or the MAC is not one."""
    if not args.port and not args.confirm:
        return None
    if not args.port or not args.confirm:
        raise Refused(f"a burn needs both --port and {CONFIRM}=<the board's MAC>; without both nothing "
                      "touches a device (leave both out for the dry run)")
    mac = normal_mac(args.confirm)
    if mac is None:
        raise Refused(f"{CONFIRM}: a MAC, aa:bb:cc:dd:ee:ff")
    return mac


def main(argv: Optional[list[str]] = None, runner: Runner = run_tool,
         digest_of: Callable[[Path], str] = espsecure_digest,
         signed_by: Callable[[Path, Path], bool] = espsecure_signed_by) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--selftest"]:
        return selftest()
    args = parse(argv)
    try:
        mac = check_device_args(args)
        record = Path(args.record).expanduser()
        if not outside_repo(record):
            raise Refused(f"{record} is inside the repository: the record of the boxes stays out of it")
        build = read_build(Path(args.build))
        pubkeys = [Path(args.root_pubkey).expanduser(), Path(args.ci_pubkey).expanduser(),
                   Path(args.spare_pubkey).expanduser() if args.spare_pubkey else None]
        if mac is None:
            plan = make_plan(build, Path(args.flash_key).expanduser(), pubkeys, args.security_version,
                             digest_of, signed_by, erase_first=args.erase_first)
            print_plan(plan, "<port>")
            print("\nDRY RUN: nothing was opened, written or burned. The burn is on hold (RELEASE_HARDENING.md, "
                  f"section 5 question 1); it needs --port and {CONFIRM}=<MAC>.")
            return 0
        with tempfile.TemporaryDirectory(prefix="atalaia-burn-") as tmp:
            plan = make_plan(build, Path(args.flash_key).expanduser(), pubkeys, args.security_version,
                             digest_of, signed_by, key_dir=Path(tmp), erase_first=args.erase_first)
            for path, digest in zip(plan.digest_files, plan.digests):
                if digest:
                    path.write_bytes(bytes.fromhex(digest))
            plan.flash_image.write_bytes(whole_flash(plan.flash_parts, plan.flash_size))
            print_plan(plan, args.port)
            return burn(plan, args.port, mac, record, runner)
    except Refused as exc:
        print(f"hardened_burn: REFUSED: {exc}", file=sys.stderr)
        return 2


# ---- self-test (no esptool, no device) ------------------------------------------------------

def selftest() -> int:
    import os
    import unittest
    from unittest import mock

    class Fake:
        """A fake device: answers read_mac and summary, records every other command."""

        def __init__(self, mac: str = "a0:b1:c2:d3:e4:f5", efuses: Optional[dict] = None, fail_at: str = ""):
            self.mac, self.calls, self.fail_at = mac, [], fail_at
            self.efuses = efuses if efuses is not None else blank_efuses()

        def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess:
            self.calls.append(cmd)
            if "read_mac" in cmd:
                return subprocess.CompletedProcess(cmd, 0, f"MAC: {self.mac}\n", "")
            if "summary" in cmd:
                Path(cmd[cmd.index("--file") + 1]).write_text(json.dumps(self.efuses))
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if self.fail_at and self.fail_at in cmd:
                return subprocess.CompletedProcess(cmd, 2, "", "A fatal error occurred")
            return subprocess.CompletedProcess(cmd, 0, "", "")

    def blank_efuses() -> dict:
        e = {name: {"value": v} for name, v in BLANK.items()}
        e["SPI_BOOT_CRYPT_CNT"] = {"value": "Disable"}
        for i in range(6):
            e[f"KEY_PURPOSE_{i}"] = {"value": "USER"}
            e[KEY_BLOCKS[i]] = {"value": " ".join(["00"] * 32)}
        return e

    def no_device(cmd):  # any call is a failure of the test: the dry run must not run a tool
        raise AssertionError(f"a tool was run: {cmd}")

    digests = {"root": "11" * 32, "ci": "22" * 32, "spare": "33" * 32}

    def digest_of(p: Path) -> str:
        return digests[p.name.split(".")[0]]

    class T(unittest.TestCase):
        def setUp(self):
            self.tmp = tempfile.TemporaryDirectory(prefix="atalaia-burn-test-")
            home = Path(self.tmp.name)
            self.build = home / "build-hardened"
            (home / "partitions.csv").write_text((REPO / "firmware" / "esp32" / "partitions.csv").read_text())
            (self.build / "bootloader").mkdir(parents=True)
            sdk = (sbs.OVERLAY.read_text(encoding="utf-8") + "CONFIG_BOOTLOADER_OFFSET_IN_FLASH=0x0\n"
                   "CONFIG_ATALAIA_SB_REVOKE=y\n")
            (self.build / "sdkconfig").write_text(sdk)
            (self.build / "bootloader" / "bootloader.signed.bin").write_bytes(b"boot")
            (self.build / "atalaia_esp32.signed.bin").write_bytes(b"app")
            (self.build / "partition_table").mkdir()
            (self.build / "partition_table" / "partition-table.bin").write_bytes(b"table")
            (self.build / "ota_data_initial.bin").write_bytes(b"\xff" * 0x2000)
            (self.build / "flasher_args.json").write_text(json.dumps({
                "write_flash_args": ["--flash_mode", "dio", "--flash_size", "keep", "--flash_freq", "80m"],
                "flash_files": {"0x20000": "atalaia_esp32.bin", "0x8000": "partition_table/partition-table.bin",
                                "0xf000": "ota_data_initial.bin"}}))
            (self.build / "project_description.json").write_text('{"project_version": "0.11.0"}')
            self.key = home / "flash-key.bin"
            self.key.write_bytes(os.urandom(32))
            for name in ("root", "ci", "spare"):
                (home / f"{name}.pub.pem").write_text("public key")
            self.home = home
            self.record = home / "record.log"

        def tearDown(self):
            self.tmp.cleanup()

        def argv(self, *more: str) -> list[str]:
            h = self.home
            return ["--build", str(self.build), "--flash-key", str(self.key), "--root-pubkey", str(h / "root.pub.pem"),
                    "--ci-pubkey", str(h / "ci.pub.pem"), "--record", str(self.record), *more]

        def go(self, *more: str, runner=no_device, signed=lambda image, key: True) -> int:
            with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                return main(self.argv(*more), runner=runner, digest_of=digest_of, signed_by=signed)

        # -- dry run ---------------------------------------------------------------------------
        def test_dry_run_is_the_default_and_touches_nothing(self):
            self.assertEqual(self.go(), 0)
            self.assertFalse(self.record.exists())

        def test_plan_order_and_contents(self):
            plan = make_plan(read_build(self.build), self.key,
                             [self.home / "root.pub.pem", self.home / "ci.pub.pem", None], 1, digest_of,
                             lambda i, k: True, key_dir=Path("/k"))
            self.assertEqual([s.args[0] for s in plan.steps],
                             ["write_flash", "burn_key", "burn_key", "burn_efuse", "burn_efuse"])
            self.assertEqual(plan.steps[0].args[-4:], ["0x0", "/k/boot-region.bin", "0x20000",
                                                       str(self.build / "atalaia_esp32.signed.bin")])
            self.assertEqual(plan.flash_parts[0x0], self.build / "bootloader" / "bootloader.signed.bin")
            self.assertNotIn(0x20000, plan.flash_parts)
            image = whole_flash(plan.flash_parts, plan.flash_size)
            self.assertEqual(len(image), 0x13000)  # up to the end of nvs_keys (the real partitions.csv)
            self.assertEqual(image[:4], b"boot")
            self.assertEqual(image[0x8000:0x8005], b"table")
            self.assertEqual(image[0x9000:0xf000], b"\xff" * 0x6000)  # nvs blank
            self.assertEqual(image[0x12000:0x13000], b"\xff" * 0x1000)  # nvs_keys blank
            erase = make_plan(read_build(self.build), self.key,
                              [self.home / "root.pub.pem", self.home / "ci.pub.pem", None], 1, digest_of,
                              lambda i, k: True, key_dir=Path("/k"), erase_first=True)
            self.assertEqual(erase.steps[0].args, ["erase_flash"])
            self.assertNotIn("--no-stub", command(erase.steps[0], "P"))
            self.assertEqual(erase.steps[1:], plan.steps)
            self.assertEqual(plan.steps[1].args, ["burn_key", "BLOCK_KEY0", str(self.key), "XTS_AES_128_KEY"])
            self.assertEqual(plan.steps[2].args, ["burn_key", "BLOCK_KEY1", "/k/sb-root.digest.bin",
                                                  "SECURE_BOOT_DIGEST0", "BLOCK_KEY2", "/k/sb-ci.digest.bin",
                                                  "SECURE_BOOT_DIGEST1"])
            self.assertEqual(plan.steps[3].args, ["burn_efuse", "SECURE_VERSION", "0x1"])
            self.assertEqual(plan.steps[4].args, ["burn_efuse", "SOFT_DIS_JTAG", "7", "SECURE_BOOT_EN", "1"])
            self.assertEqual([s.permanent for s in plan.steps], [False, True, True, True, True])
            with self.assertRaises(Refused):  # parts that overlap
                whole_flash({0: plan.flash_parts[0x0], 2: plan.flash_parts[0x0]}, 64)
            self.assertNotIn("SECURE_BOOT_KEY_REVOKE2", " ".join(" ".join(s.args) for s in plan.steps))
            line = plan.record_line("burned", when="T")
            self.assertEqual(line.split("\t")[:6], ["T", "mac=<the board MAC>", "security_version=1",
                                                   "digest0=" + "11" * 32, "digest1=" + "22" * 32, "digest2=empty"])
            self.assertIn(f"flash_key_id={hashlib.sha256(self.key.read_bytes()).hexdigest()[:16]}", line)
            self.assertIn("firmware=0.11.0", line)
            self.assertNotIn(self.key.read_bytes().hex(), line)  # never the key itself
            cmd = command(plan.steps[2], "P")
            self.assertEqual(cmd[1:8], ["-m", "espefuse", "--chip", "esp32s3", "--port", "P", "--before"])
            self.assertIn("--do-not-confirm", cmd)
            self.assertIn("--no-stub", command(plan.steps[0], "P"))

        def test_spare_slot(self):
            plan = make_plan(read_build(self.build), self.key, [self.home / "root.pub.pem", self.home / "ci.pub.pem",
                             self.home / "spare.pub.pem"], 1, digest_of, lambda i, k: True, key_dir=Path("/k"))
            self.assertEqual(plan.steps[2].args[-3:], ["BLOCK_KEY3", "/k/sb-spare.digest.bin", "SECURE_BOOT_DIGEST2"])
            self.assertIn("digest2=" + "33" * 32, plan.record_line("x"))
            # An empty slot needs the image's permission.
            sdk = self.build / "sdkconfig"
            sdk.write_text(sdk.read_text().replace("CONFIG_SECURE_BOOT_ALLOW_UNUSED_DIGEST_SLOTS=y", ""))
            self.assertEqual(self.go(), 2)  # check-config fails first
            b = read_build_unchecked(self.build)
            with self.assertRaises(Refused):
                make_plan(b, self.key, [self.home / "root.pub.pem", self.home / "ci.pub.pem", None], 1, digest_of,
                          lambda i, k: True)

        def test_security_version(self):
            self.assertEqual(secure_version_bits(1), 1)
            self.assertEqual(secure_version_bits(3), 0b111)
            self.assertEqual(secure_version_bits(16), 0xFFFF)
            for bad in (0, 17):
                with self.assertRaises(Refused):
                    secure_version_bits(bad)
            self.assertEqual(self.go("--security-version", "2"), 2)  # the image says 1

        def test_build_refusals(self):
            (self.build / "bootloader" / "bootloader.signed.bin").rename(
                self.build / "bootloader" / "bootloader.test-signed.bin")
            with self.assertRaises(Refused) as ctx:
                read_build(self.build)
            self.assertIn("no longer exists", str(ctx.exception))
            self.assertEqual(self.go(), 2)

        def test_bench_option_refused(self):
            sdk = self.build / "sdkconfig"
            sdk.write_text(sdk.read_text() + "CONFIG_ATALAIA_SERIAL_KEYS=y\n")
            self.assertEqual(self.go(), 2)

        def test_key_refusals(self):
            self.key.write_bytes(b"\x00" * 32)
            self.assertEqual(self.go(), 2)
            self.key.write_bytes(os.urandom(16))
            self.assertEqual(self.go(), 2)
            self.key.write_bytes(os.urandom(32))
            # The same key as root and CI.
            with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                self.assertEqual(main(self.argv(), runner=no_device, digest_of=lambda p: "44" * 32,
                                      signed_by=lambda i, k: True), 2)
            # A key inside the repository.
            with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                inside = main(["--build", str(self.build), "--flash-key", str(REPO / "README.md"),
                               "--root-pubkey", str(self.home / "root.pub.pem"), "--ci-pubkey",
                               str(self.home / "ci.pub.pem"), "--record", str(self.record)],
                              runner=no_device, digest_of=digest_of, signed_by=lambda i, k: True)
            self.assertEqual(inside, 2)
            # The record inside the repository.
            self.assertEqual(self.go("--record", str(REPO / "boxes.log")), 2)

        def test_signature_refusals(self):
            # The bootloader signed by the CI key only: refused.
            self.assertEqual(self.go(signed=lambda image, key: "bootloader" not in image.name or "ci" in key.name), 2)
            # The app signed by neither.
            self.assertEqual(self.go(signed=lambda image, key: "bootloader" in image.name), 2)
            # The app signed by the CI key only is fine.
            self.assertEqual(self.go(signed=lambda image, key: "bootloader" in image.name or "ci" in key.name), 0)

        # -- the device guards -----------------------------------------------------------------
        def test_port_alone_or_confirmation_alone_refused(self):
            self.assertEqual(self.go("--port", "/dev/cu.fake"), 2)
            self.assertEqual(self.go(f"{CONFIRM}=a0:b1:c2:d3:e4:f5"), 2)
            self.assertEqual(self.go("--port", "/dev/cu.fake", f"{CONFIRM}=not-a-mac"), 2)
            self.assertFalse(self.record.exists())

        def test_wrong_mac_refused_before_anything(self):
            fake = Fake(mac="a0:b1:c2:d3:e4:00")
            self.assertEqual(self.go("--port", "P", f"{CONFIRM}=a0:b1:c2:d3:e4:f5", runner=fake), 2)
            self.assertEqual(len(fake.calls), 1)
            self.assertIn("read_mac", fake.calls[0])
            self.assertFalse(self.record.exists())

        def test_not_blank_refused(self):
            for name, value in (("SECURE_BOOT_EN", True), ("SPI_BOOT_CRYPT_CNT", "Enable"), ("SECURE_VERSION", 1),
                                ("KEY_PURPOSE_1", "SECURE_BOOT_DIGEST0"), ("ENABLE_SECURITY_DOWNLOAD", True)):
                e = blank_efuses()
                e[name] = {"value": value}
                fake = Fake(efuses=e)
                self.assertEqual(self.go("--port", "P", f"{CONFIRM}=A0-B1-C2-D3-E4-F5", runner=fake), 2, name)
                self.assertEqual(len(fake.calls), 2, name)  # read_mac and summary only
            e = blank_efuses()
            e["BLOCK_KEY2"] = {"value": "00 " * 31 + "01"}
            fake = Fake(efuses=e)
            self.assertEqual(self.go("--port", "P", f"{CONFIRM}=a0b1c2d3e4f5", runner=fake), 2)
            self.assertFalse(self.record.exists())

        def test_burn_runs_the_plan_and_records(self):
            fake = Fake()
            self.assertEqual(self.go("--port", "P", f"{CONFIRM}=a0:b1:c2:d3:e4:f5", runner=fake), 0)
            ran = [c[c.index("--port") + 3:] for c in fake.calls[2:]]
            self.assertIn("write_flash", ran[0])
            self.assertTrue(any("XTS_AES_128_KEY" in c for c in ran))
            self.assertEqual(fake.calls[-1][-4:], ["SOFT_DIS_JTAG", "7", "SECURE_BOOT_EN", "1"])
            lines = self.record.read_text().splitlines()
            self.assertEqual(len(lines), 1)
            self.assertIn("mac=a0:b1:c2:d3:e4:f5", lines[0])
            self.assertIn("status=burned", lines[0])
            # The digest files given to espefuse held the digests (gone with their folder now).
            self.assertTrue(all(not Path(a).exists() for c in fake.calls for a in c if a.endswith(".digest.bin")))

        def test_partial_burn_is_recorded(self):
            fake = Fake(fail_at="SECURE_VERSION")
            self.assertEqual(self.go("--port", "P", f"{CONFIRM}=a0:b1:c2:d3:e4:f5", runner=fake), 2)
            line = self.record.read_text()
            self.assertIn("status=PARTIAL-2-burns", line)
            self.assertFalse(any("SECURE_BOOT_EN" in c for c in fake.calls))

        def test_flash_failure_burns_nothing_records_nothing(self):
            fake = Fake(fail_at="write_flash")
            self.assertEqual(self.go("--port", "P", f"{CONFIRM}=a0:b1:c2:d3:e4:f5", runner=fake), 2)
            self.assertFalse(any("burn_key" in c for c in fake.calls))
            self.assertFalse(self.record.exists())

        def test_mac_forms(self):
            self.assertEqual(normal_mac("A0-B1-C2-D3-E4-F5"), "a0:b1:c2:d3:e4:f5")
            self.assertEqual(normal_mac("a0b1c2d3e4f5"), "a0:b1:c2:d3:e4:f5")
            self.assertIsNone(normal_mac("a0:b1:c2:d3:e4"))

    def read_build_unchecked(folder: Path) -> Build:
        with mock.patch.object(sbs, "config_problems", return_value=[]):
            return read_build(folder)

    suite = unittest.TestLoader().loadTestsFromTestCase(T)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        return 1
    print("hardened_burn: self-test passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
