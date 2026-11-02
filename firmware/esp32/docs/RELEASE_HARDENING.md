<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# Plan: a hardened release image (flash encryption, NVS encryption, secure boot v2, anti-rollback)

**Status: a plan, nothing here is built or burned.** It answers review finding FLD-2 and carries FLD-3 (the eFuse anti-rollback floor that decision FU3-8 left as a production option). Burning an eFuse cannot be undone, and a wrong step can leave a box that never boots again, so **every step that burns one is the maintainer's call** (decision SR-42 asks for it). The repository's `sdkconfig.defaults` stays as it is until then.

## 1. Where we are

The images the project builds and releases (Field Box, modem, I/O pod) have **none** of the four protections, and a box flashed from a release has all its eFuses unburnt:

| Protection | Today | Consequence |
| --- | --- | --- |
| NVS encryption | off (the box logs `NVS encryption is off` at boot) | the field join key, the game key, the admin PIN and the field Wi-Fi password sit in plain flash |
| Flash encryption | off | `esptool read_flash` returns the whole chip |
| Secure boot v2 | off | any image can be flashed over USB; a modified image can print the key |
| Anti-rollback | off | only the box's own version check (`fw_update.c`) stops an older image, and a USB flash skips it |

What is already in place: Ed25519-signed OTA images checked by the app (RELEASE_SIGNING.md, `protocol/firmware-update.md`), the app-level version floor, `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` (a new image that fails its self-test is rolled back), the admin PIN with counted waits, and decision AD-12's list of what a production Field Box needs (`protocol/adoption.md` section 2). SECURITY.md says what a lost box exposes today.

Decision S1 (2026-10-21) kept Ed25519 for modes and update packages and left hardware secure boot as "a separate, one-time eFuse decision". This is where that decision is prepared. On the ESP32-S3, ESP-IDF's secure boot v2 signs with **RSA-3072 (RSA-PSS)**; it cannot use Ed25519, so the hardware signature is a second signature beside the Ed25519 one (check the ESP-IDF version in use when the work starts: v5.3.2 today).

## 2. The target configuration

One new overlay, `firmware/esp32/sdkconfig.release` (not written yet), used only by the release workflow and `tools/docker_fw.py release`, on top of `sdkconfig.defaults`:

- **Flash encryption, release mode** (`CONFIG_SECURE_FLASH_ENC_ENABLED`, `CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE`): app, bootloader and the `storage` partition are encrypted on the chip with an AES-XTS key held in an eFuse block that software cannot read.
- **NVS encryption** (`CONFIG_NVS_ENCRYPTION`). Two schemes exist; the plan prefers the **flash-encryption scheme** over the HMAC scheme the repository documents today (BRING_UP.md step 0, decision AD-12), because with flash encryption on its key is unique per chip and needs no second eFuse key; the HMAC scheme with one fleet-wide key means one dumped box gives the NVS key of all of them (BRING_UP.md says "all boxes in the same fleet should use the same key"). The `nvs_keys` partition (already in `partitions.csv`) gets the `encrypted` flag. Either way a *running* image can read the NVS, so this protects a box that is dumped, not one that is attacked with code running on it.
- **Secure boot v2** (`CONFIG_SECURE_BOOT`, `CONFIG_SECURE_SIGNED_APPS_RSA_SCHEME`): the ROM verifies the bootloader, the bootloader verifies the partition table and the app. Up to three public-key digests can be burned; use **two, like the project's other keys** (`docs/community/keys.md`): a root key kept offline by the maintainer and a CI key (a repository secret) that signs the GitHub releases, and keep the third slot empty for a replacement. A digest can be revoked later, which is the way out of a leaked CI key.
- **Anti-rollback** (`CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK` with `CONFIG_BOOTLOADER_APP_SECURE_VERSION`): the image carries a security version, the bootloader refuses lower ones, and a confirmed new image burns it into the eFuse. The S3 has **16 steps** (one eFuse bit each) for the whole life of the chip: raise it only for a security fix that old firmware must not be allowed to come back from, never with every release. The app-level version check stays.
- **Debug and download paths**: `DIS_USB_JTAG` (the JTAG half of the S3's USB port goes; the serial half stays, because `@adopt` over USB needs it), `SOFT_DIS_JTAG`/`HARD_DIS_JTAG`, the ROM's secure download mode (`CONFIG_SECURE_ENABLE_SECURE_ROM_DL_MODE`: no flash read-out over the ROM downloader), and no UART download re-enable. A `CONFIG_SECURE_DISABLE_ROM_DL_MODE` variant removes USB flashing altogether and is **not** recommended: it leaves no way to recover a box.

These names come from the ESP-IDF 5.x documentation as remembered, not from a build; the first task of the work is to check each against the docs of the IDF version in use and against `idf.py menuconfig`.

## 3. What it means for each way of putting software on a box

### USB re-flashing

- **Today**: `esptool write_flash`, the release's `-usb.zip` or the browser flasher with the `-merged.bin` at offset 0 work on any box, any time.
- **After the burn**: a plaintext image no longer boots. The bootloader and the app must be signed (secure boot) and **encrypted for the chip's flash key**. Whether that can be done over USB depends on **who made the flash-encryption key**:
  - *Key generated on the chip at first boot* (ESP-IDF's default): nobody knows it. A box can only be updated over the air from then on, and an OTA that fails in a way the rollback cannot catch (for example a bootloader or partition-table change) is a dead box. This is the strongest option and has no recovery.
  - *Key generated on the maintainer's computer and burned with `espefuse`*: `espsecure.py encrypt_flash_data` can encrypt an image for the chip and `esptool` writes it, so USB re-flashing and recovery stay possible, for whoever holds the key. A stolen key does not by itself open a box (reading is disabled), but it lets its holder write images; with secure boot also on, those still have to be signed. The key is as sensitive as the root release key: offline, encrypted, backed up.
  - **Recommended: the host-generated, fleet-wide flash key kept offline**, because losing the ability to recover boxes is the larger risk for a small project with no support staff. This is decision SR-42's question, not a settled answer.
- **The partition table can then never change over the air** (it never could: `main/fw_layout.c`) and now a table change also needs a signed table and a USB visit. The bootloader grows with secure boot and flash encryption; **check that it still fits below the partition table at 0x8000** (the default bootloader area is 28 KB). If it does not, the table moves (`CONFIG_PARTITION_TABLE_OFFSET`), which is a new layout (`FW_LAYOUT_VERSION` raised) and a first USB flash of every box. Decide this with the first test board, before any fleet burn: it is the one thing that can force a layout change.
- Boxes flashed before the burn are plain: **every existing box needs one USB visit** (new bootloader, the burn), there is no retrofit over the air. Today that is a handful of bench boards; once boxes are in customers' hands it would be a recall, which is a reason to decide before the first customer.

### The bench

- The bench build (`sdkconfig.bench`: `CONFIG_ATALAIA_SERIAL_KEYS`, no setup portal, radio logging, `@hold`, the listen-before-talk commands) and the Wokwi build are **never** signed with a release key and are never burned. Keep dedicated bench boards that stay un-burned, labelled so. A bench image flashed to a burned box will not boot, and a release image on a bench board is just a release image.
- Flash encryption can be tried in its *development* mode first: reversible a few times, so a test board can be flashed with a test key repeatedly. The sequence in section 4 uses a sacrificial board for it.
- Wokwi runs the plain build: unaffected. `tools/docker_fw.py build` for the Wokwi and bench variants stays as it is.
- The bench scripts and BRING_UP.md type `@joinkey` and `@update` without a PIN, which still works on a bench build (decision SR-40); a release build wants the PIN as the last word.
- A burned box cannot be bench-tested with ad-hoc images. The bench checklist for a hardened box is: boots, `NVS encryption is on` in the log, an unsigned image refused, an OTA of a signed image accepted, the old image refused after the security version is raised.

### Over-the-air updates

- The OTA path keeps its **Ed25519 manifest check** (decision S1) and the version floor. With secure boot on, the image **also** carries the RSA signature block and the bootloader verifies it before it boots the new slot; flash encryption encrypts the image as the box writes it (the OTA code needs no change).
- **The release pipeline gets one more step, before the Ed25519 manifest** (the manifest hashes the exact bytes of the image): build, sign with the RSA secure-boot key (`espsecure.py sign_data --version 2`), then `tools/firmware_release.py sign`. The CI key's RSA half goes into the release workflow as a second secret next to `ATALAIA_RELEASE_CI_KEY`; the root RSA key stays offline with the maintainer (RELEASE_SIGNING.md grows a section with the same compromise steps: revoke the digest).
- The signature block adds a sector (4 KB) to the image; `tools/check_fw_ram.py` and the slot-size check (the box image is 92.95 % of its slot) must be re-run with it.
- `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` stays; with anti-rollback on, a rolled-back image is one whose security version the eFuse still allows.
- A leaked CI RSA key: revoke its digest with `espefuse` (needs a USB visit per box, or an OTA signed by the root key that does it), then release signed with the root key. Until then it is the same exposure RELEASE_SIGNING.md describes for the Ed25519 CI key, with a hardware floor under it.
- The modem and the I/O pod are USB-attached to a controller, not in the field's hands: their hardening is a separate, later decision (SR-42 asks only about the Field Box).

## 4. Proposed order of work (each burn a maintainer go-ahead)

1. Maintainer decides the questions in section 5.
2. Write `sdkconfig.release`, `tools/docker_fw.py release` and the pipeline step; build it. **No burn.** Check the bootloader size, the signed image size and `tools/check_fw_ram.py`.
3. On **one sacrificial board**: flash encryption in development mode with a test key, secure boot with a throw-away RSA key, NVS encryption; run the hardened bench checklist above; try an OTA, a downgrade, an unsigned image and a power cut during the first-boot encryption (the first boot encrypts the whole flash in place and must not be interrupted).
4. Release mode on that board; repeat; keep it as the hardened reference board.
5. Fleet: burn boxes one at a time as they are built, in the build manual's step order (`hardware/field-box/BUILD.md` and the firmware guide get a step for it), with a record of each box's MAC and security version.
6. Raise the app-level docs: SECURITY.md (what a lost box exposes now becomes "the radio keys are not readable from the flash; the box can still be erased"), protocol/adoption.md section 2.

## 5. Questions for the maintainer

1. Do we burn eFuses on Field Boxes at all before the first customer, and on which build date?
2. Flash-encryption key: made on the chip (no recovery) or on a host and kept offline (recoverable)? Recommended: host-made, offline.
3. NVS encryption by the flash-encryption scheme (per chip) or the HMAC scheme (one fleet key)? Recommended: flash-encryption scheme.
4. Two secure-boot digests (root offline + CI) and one spare slot, as proposed?
5. Anti-rollback: on from the first hardened release (security version 1), accepting that only 16 raises exist?
6. May the modem and the I/O pod stay plain for now?

## 6. What does not change

The Ed25519 release and mode keys, the app-level checks, the admin PIN, the field join key's rotation procedure (SECURITY.md), the box's OTA protocol and the partition table (unless the bootloader forces it, section 3). A hardened box still loses its key if the box is erased (a factory reset), and still lets anyone with code running on it read its NVS: this plan is about the box in a thief's hands, not about a compromised image.
