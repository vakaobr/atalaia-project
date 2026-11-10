#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The hardened Field Box image's burn and secure boot, in Espressif's QEMU, never on a board.

Runs where ESP-IDF's environment is exported (the espressif/idf:v5.3.2 image, whose qemu-xtensa
esp_develop_9.0.0_20240606 emulates the ESP32-S3 with its real ROM, its eFuses in a file, the RSA
and SHA peripherals and an XTS-AES flash encryption peripheral). `python3 tools/docker_fw.py
qemu-hardened` runs it after building the image. Everything happens in a temporary folder that is
deleted at the end: three throw-away RSA-3072 keys (root, CI, and one no eFuse knows), a
throw-away flash-encryption key, a blank 16 MB flash file and the eFuse file. No serial port of
the computer is opened and no chip is touched: esptool and espefuse talk to the emulator over a
TCP socket.

    python3 tools/hardened_qemu.py firmware/esp32/build-hardened

What it checks (RELEASE_HARDENING.md, section 8):
  1. tools/hardened_burn.py burns the emulated chip as it would a board (the MAC and blank checks,
     the flash write, the flash key, two digests with the spare slot empty, the security version,
     secure boot) and writes its record line; run again, it refuses the chip (not blank);
  2. the ROM: the bootloader signed by the root and the CI key passes secure boot with slots 0 and
     1 valid; one signed by a key no eFuse knows, and an unsigned one, are refused;
  3. the bootloader: an app signed by an unknown key, and an unsigned app, are refused before the
     first-boot flash encryption starts (the flash is left as it was), while the CI-signed app is
     accepted and the encryption starts.
What it cannot check, because this QEMU's ESP32-S3 flash encryption does not behave like the chip
(section 8): the end of the first boot, the app running, the encrypted flash, NVS encryption, the
secure download mode and the anti-rollback at run time. Exit status 0 when every check passed.
"""
from __future__ import annotations

import binascii
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

REPO = Path(__file__).resolve().parents[1]
TOOLS = REPO / "tools"
PORT = 5555
APP_OFFSET = 0x20000
BOOT_ROOM = 0x8000
FLASH_SIZE = 16 * 1024 * 1024
ROM_OK = b"secure boot verification succeeded"
ROM_FAILED = b"secure boot verification failed"
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'} {name}" + (f": {detail}" if detail else ""), flush=True)
    return ok


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def espsecure(*args: str) -> None:
    out = run([sys.executable, "-m", "espsecure", *args])
    if out.returncode != 0:
        raise SystemExit(f"espsecure {args[0]} failed:\n{out.stdout}{out.stderr}")


def default_efuse() -> bytes:
    """ESP-IDF's own default eFuse file for an ESP32-S3 in QEMU (chip revision 0.3)."""
    src = (Path(os.environ["IDF_PATH"]) / "tools" / "idf_py_actions" / "qemu_ext.py").read_text()
    block = src[src.index("'esp32s3': QemuTarget("):]
    return binascii.unhexlify("".join(re.findall(r"'([0-9a-f]+)'", block[:block.index("))")])))


def listening(port: int) -> bool:
    """Whether a TCP socket listens on this port (Linux's /proc/net/tcp*; elsewhere a 3 s wait)."""
    hexport = f":{port:04X}"
    seen = False
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            lines = Path(name).read_text().splitlines()[1:]
        except OSError:
            continue
        seen = True
        for line in lines:
            f = line.split()
            if len(f) > 3 and f[1].endswith(hexport) and f[3] == "0A":
                return True
    if not seen:
        time.sleep(3)
        return True
    return False


class Qemu:
    """One emulator run on work/flash.bin and work/efuse.bin. The ESP32-S3's eFuse device is
    nvram.esp32c3.efuse in this QEMU: ESP-IDF 5.3's `idf.py qemu` names it nvram.esp32s3.efuse,
    which QEMU ignores with a warning, so its eFuses would not be kept in the file."""

    def __init__(self, work: Path, download: bool, log: Optional[Path] = None, settle: float = 3.0):
        cmd = ["qemu-system-xtensa", "-nographic", "-M", "esp32s3",
               "-drive", f"file={work / 'flash.bin'},if=mtd,format=raw",
               "-drive", f"file={work / 'efuse.bin'},if=none,format=raw,id=efuse",
               "-global", "driver=nvram.esp32c3.efuse,property=drive,value=efuse"]
        if download:
            # GPIO0 low: the ROM's download mode, its UART0 a TCP socket.
            cmd += ["-global", "driver=esp32s3.gpio,property=strap_mode,value=0x00",
                    "-serial", f"tcp::{PORT},server,nowait"]
        else:
            cmd += ["-serial", f"file:{log}"]
        cmd += ["-monitor", "none"]
        self.log = log
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if download:
            # The emulated ROM answers only some seconds after the socket listens; a fixed 3 s from
            # the start was sometimes too short on a GitHub runner (every start then failed within
            # seconds). Wait until the socket listens (read from /proc, never by connecting: the ROM
            # takes the first session as esptool's), then a settle time, longer on each new start.
            deadline = time.time() + 30
            while time.time() < deadline and self.proc.poll() is None and not listening(PORT):
                time.sleep(0.25)
            time.sleep(settle)
        else:
            time.sleep(3)

    def text(self) -> bytes:
        return self.log.read_bytes() if self.log and self.log.exists() else b""

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


def esptool(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return run([sys.executable, "-m", "esptool", "--chip", "esp32s3", "--port", f"socket://localhost:{PORT}",
                "--before", "no_reset", "--after", "no_reset", "--no-stub", *args], timeout=timeout)


def download_mode(work: Path) -> tuple[Optional[Qemu], str]:
    """The emulator in download mode and the chip's MAC. The emulated ROM sometimes never answers
    the first esptool session after a start (and then no later one either), so a start whose first
    read_mac fails is stopped and made again, up to 10 times, each after a longer settle. Locally the
    sixth start answered in two runs in a row, at 13 s and at 28 s of settling, so the cause is not the
    wait alone; each failed start prints what esptool said."""
    said = ""
    for attempt in range(10):
        q = Qemu(work, download=True, settle=min(8.0 + 2.0 * attempt, 20.0))
        out = esptool("--connect-attempts", "3", "read_mac", timeout=60)
        found = re.findall(r"MAC:\s*([0-9a-f:]{17})", out.stdout)
        if found:
            return q, found[-1]
        gone = q.proc.poll()
        said = f"start {attempt + 1}: qemu {'exited ' + str(gone) if gone is not None else 'running'}; " + \
            (out.stdout + out.stderr).strip()[-600:]
        print(said, flush=True)
        q.stop()
    return None, said


def flash_with(work: Path, base: bytes, offset: int, room: int, image: Path) -> bytes:
    """work/flash.bin: base with image at offset and the rest of its room blank; returns it."""
    flash = bytearray(base)
    data = image.read_bytes()
    flash[offset:offset + room] = b"\xff" * room
    flash[offset:offset + len(data)] = data
    (work / "flash.bin").write_bytes(bytes(flash))
    return bytes(flash)


def rom_boot(work: Path, name: str) -> bytes:
    """Boots until the ROM has said whether the bootloader passed secure boot (30 s at most)."""
    q = Qemu(work, download=False, log=work / f"{name}.log")
    try:
        deadline = time.time() + 30
        while time.time() < deadline and ROM_OK not in q.text() and ROM_FAILED not in q.text():
            time.sleep(0.5)
        return q.text()
    finally:
        q.stop()


def bootloader_boot(work: Path, name: str, before: bytes, seconds: float) -> bool:
    """Boots with a bootloader the ROM accepts; True as soon as the flash changes (the bootloader
    accepted the app and began the first-boot encryption, which it does only for an image that
    passed its checks: bootloader_utility.c calls load_image only after try_load_partition), False
    if the flash is still as it was after `seconds`."""
    q = Qemu(work, download=False, log=work / f"{name}.log")
    try:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if (work / "flash.bin").read_bytes() != before:
                return True
            time.sleep(2)
        return False
    finally:
        q.stop()


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    build = Path(argv[0]).resolve()
    for name in ("sdkconfig", "flasher_args.json", "bootloader/bootloader.bin", "atalaia_esp32.bin"):
        if not (build / name).is_file():
            print(f"hardened_qemu: {build / name}: no such file (tools/docker_fw.py release-hardened first)")
            return 2
    if shutil.which("qemu-system-xtensa") is None:
        print("hardened_qemu: qemu-system-xtensa is not on the PATH (ESP-IDF's environment, the espressif/idf image)")
        return 2
    started_at = time.time()
    with tempfile.TemporaryDirectory(prefix="atalaia-qemu-") as tmp:
        work = Path(tmp)
        keys = work / "keys"
        keys.mkdir(mode=0o700)
        for name in ("root", "ci", "unknown"):
            espsecure("generate_signing_key", "--version", "2", "--scheme", "rsa3072", str(keys / f"{name}.pem"))
            espsecure("extract_public_key", "--version", "2", "--keyfile", str(keys / f"{name}.pem"),
                      str(keys / f"{name}.pub.pem"))
        flash_key = keys / "flash-key.bin"
        flash_key.write_bytes(os.urandom(32))
        print("throw-away keys made in a temporary folder (deleted at the end): root, CI, unknown, flash key",
              flush=True)

        # A copy of the build signed with the throw-away keys, and the images to be refused.
        b = work / "build-hardened"
        for name in ("sdkconfig", "flasher_args.json", "project_description.json", "ota_data_initial.bin",
                     "atalaia_esp32.bin", "partition_table/partition-table.bin", "bootloader/bootloader.bin"):
            (b / name).parent.mkdir(parents=True, exist_ok=True)
            if (build / name).exists():
                shutil.copy(build / name, b / name)
        shutil.copy(build.parent / "partitions.csv", work / "partitions.csv")
        sign = [sys.executable, str(TOOLS / "secure_boot_sign.py"), "sign"]
        boot_unknown, app_unknown = work / "bootloader.unknown-key.bin", work / "app.unknown-key.bin"
        for image, signers, out in (
                (b / "bootloader/bootloader.bin", ("root", "ci"), b / "bootloader/bootloader.signed.bin"),
                (b / "atalaia_esp32.bin", ("ci",), b / "atalaia_esp32.signed.bin"),
                (b / "bootloader/bootloader.bin", ("unknown",), boot_unknown),
                (b / "atalaia_esp32.bin", ("unknown",), app_unknown)):
            done = run([*sign, str(image), *[x for k in signers for x in ("--key", str(keys / f"{k}.pem"))],
                        "--out", str(out)])
            if done.returncode != 0:
                print(done.stdout + done.stderr)
                return 1

        (work / "flash.bin").write_bytes(b"\xff" * FLASH_SIZE)
        (work / "efuse.bin").write_bytes(default_efuse())

        # 1. The burn, by tools/hardened_burn.py, against the emulator.
        q, mac = download_mode(work)
        if not check("the emulator answers in download mode", q is not None, mac):
            return 1
        burn = [sys.executable, str(TOOLS / "hardened_burn.py"), "--build", str(b), "--flash-key", str(flash_key),
                "--root-pubkey", str(keys / "root.pub.pem"), "--ci-pubkey", str(keys / "ci.pub.pem"),
                "--record", str(work / "record.log"), "--port", f"socket://localhost:{PORT}",
                f"--i-understand-this-is-permanent={mac}"]
        try:
            t0 = time.time()
            out = run(burn)
            said = "\n".join(line for line in (out.stdout + out.stderr).splitlines()
                             if not line.startswith("Writing at"))
            if not check(f"tools/hardened_burn.py burns the emulated chip ({time.time() - t0:.0f} s)",
                         out.returncode == 0, "" if out.returncode == 0 else said[-3000:]):
                return 1
            line = (work / "record.log").read_text() if (work / "record.log").exists() else ""
            check("it records the MAC, the digests and the security version",
                  f"mac={mac}" in line and "status=burned" in line and "security_version=1" in line
                  and "digest2=empty" in line, line.strip())
            again = run(burn)
            check("a second burn of the same chip is refused (not blank)",
                  again.returncode == 2 and "not a blank chip" in again.stderr, again.stderr.strip()[-400:])
        finally:
            q.stop()
        burned_flash = (work / "flash.bin").read_bytes()
        burned_efuse = (work / "efuse.bin").read_bytes()

        # 2. The ROM's secure boot check of the bootloader.
        for name, image, ok in (
                ("the bootloader signed by the root and the CI key", b / "bootloader/bootloader.signed.bin", True),
                ("a bootloader signed by a key no eFuse knows", boot_unknown, False),
                ("an unsigned bootloader", b / "bootloader/bootloader.bin", False)):
            flash_with(work, burned_flash, 0, BOOT_ROOM, image)
            (work / "efuse.bin").write_bytes(burned_efuse)
            text = rom_boot(work, re.sub(r"\W+", "-", name))
            detail, slots_ok = "", True
            if ok:
                slots = re.findall(rb"Valid secure boot key blocks: ([0-9 ]+)", text)
                detail = f"valid key blocks: {slots[-1].decode().strip() if slots else '?'}"
                slots_ok = bool(slots) and slots[-1].split() == [b"0", b"1"]
            check(f"ROM: {name} is {'accepted' if ok else 'refused'}",
                  (ROM_OK if ok else ROM_FAILED) in text and slots_ok, detail)

        # 3. The bootloader's secure boot check of the app: a refused image leaves the flash alone;
        # the CI-signed app starts the first-boot encryption (the positive control, last).
        for name, image, ok, seconds in (
                ("an app signed by a key no eFuse knows", app_unknown, False, 60),
                ("an unsigned app", b / "atalaia_esp32.bin", False, 60),
                ("the CI-signed app", b / "atalaia_esp32.signed.bin", True, 120)):
            flash_with(work, burned_flash, 0, BOOT_ROOM, b / "bootloader/bootloader.signed.bin")
            before = flash_with(work, (work / "flash.bin").read_bytes(), APP_OFFSET, 0x400000, image)
            (work / "efuse.bin").write_bytes(burned_efuse)
            changed = bootloader_boot(work, re.sub(r"\W+", "-", name), before, seconds)
            check(f"bootloader: {name} is "
                  + ("accepted (the first-boot encryption starts)" if ok else "refused (the flash is left alone)"),
                  changed == ok)

        # What the emulator makes of the first boot: not a check (section 8).
        flash = (work / "flash.bin").read_bytes()
        app = (b / "atalaia_esp32.signed.bin").read_bytes()
        enc = work / "app.expected.bin"
        espsecure("encrypt_flash_data", "--aes_xts", "--keyfile", str(flash_key), "--address", hex(APP_OFFSET),
                  "--output", str(enc), str(b / "atalaia_esp32.signed.bin"))
        want, got = enc.read_bytes()[:0x1000], flash[APP_OFFSET:APP_OFFSET + 0x1000]
        same = sum(got[i:i + 16] == want[i:i + 16] for i in range(0, 0x1000, 16))
        print(f"INFO the emulator's encryption of the app's first 4 KB: {same} of 256 16-byte blocks equal "
              "espsecure.py's XTS-AES with the same key (the chip's algorithm); "
              f"still plaintext: {got == app[:0x1000]}", flush=True)

    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed in {time.time() - started_at:.0f} s; "
          "the throw-away keys and the emulator's files are deleted.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
