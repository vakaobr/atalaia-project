<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# Plan: a hardened release image (flash encryption, NVS encryption, secure boot v2, anti-rollback)

**Status (2026-11-06): step 2 of section 4 is built, nothing is burned.** The maintainer answered questions 2 to 6 of section 5 (the plan's recommendations, below); question 1, when to burn, is open. `firmware/esp32/sdkconfig.release`, `tools/docker_fw.py release-hardened` and `tools/secure_boot_sign.py` build the hardened Field Box image and sign it for secure boot v2 with a throw-away key or a given one, and CI's `esp32-hardened-build` job builds it on every firmware change; no board has been flashed with it and no eFuse has been touched. Steps 3 and later need a sacrificial board and the maintainer. The plan answers review finding FLD-2 and carries FLD-3 (the eFuse anti-rollback floor that decision FU3-8 left as a production option). Burning an eFuse cannot be undone, and a wrong step can leave a box that never boots again, so **every step that burns one is the maintainer's call** (decision SR-42 asks for it). The repository's `sdkconfig.defaults` stays as it is until then.

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

One overlay, `firmware/esp32/sdkconfig.release` (written 2026-11-06, step 2), used only by `tools/docker_fw.py release-hardened` (and CI's `esp32-hardened-build` job; the release workflow later), on top of `sdkconfig.defaults`:

- **Flash encryption, release mode** (`CONFIG_SECURE_FLASH_ENC_ENABLED`, `CONFIG_SECURE_FLASH_ENCRYPTION_MODE_RELEASE`): app, bootloader and the `storage` partition are encrypted on the chip with an AES-XTS key held in an eFuse block that software cannot read.
- **NVS encryption** (`CONFIG_NVS_ENCRYPTION`). Two schemes exist; the plan prefers the **flash-encryption scheme** over the HMAC scheme the repository documents today (BRING_UP.md step 0, decision AD-12), because with flash encryption on its key is unique per chip and needs no second eFuse key; the HMAC scheme with one fleet-wide key means one dumped box gives the NVS key of all of them (BRING_UP.md says "all boxes in the same fleet should use the same key"). The `nvs_keys` partition (already in `partitions.csv`) gets the `encrypted` flag. Either way a *running* image can read the NVS, so this protects a box that is dumped, not one that is attacked with code running on it.
- **Secure boot v2** (`CONFIG_SECURE_BOOT`, `CONFIG_SECURE_SIGNED_APPS_RSA_SCHEME`): the ROM verifies the bootloader, the bootloader verifies the partition table and the app. Up to three public-key digests can be burned; use **two, like the project's other keys** (`docs/community/keys.md`): a root key kept offline by the maintainer and a CI key (a repository secret) that signs the GitHub releases, and keep the third slot empty for a replacement. A digest can be revoked later, which is the way out of a leaked CI key.
- **Anti-rollback** (`CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK` with `CONFIG_BOOTLOADER_APP_SECURE_VERSION`): the image carries a security version, the bootloader refuses lower ones, and a confirmed new image burns it into the eFuse. The S3 has **16 steps** (one eFuse bit each) for the whole life of the chip: raise it only for a security fix that old firmware must not be allowed to come back from, never with every release. The app-level version check stays.
- **Debug and download paths**: `DIS_USB_JTAG` (the JTAG half of the S3's USB port goes; the serial half stays, because `@adopt` over USB needs it), `SOFT_DIS_JTAG`/`HARD_DIS_JTAG`, the ROM's secure download mode (`CONFIG_SECURE_ENABLE_SECURE_ROM_DL_MODE`: no flash read-out over the ROM downloader), and no UART download re-enable. A `CONFIG_SECURE_DISABLE_ROM_DL_MODE` variant removes USB flashing altogether and is **not** recommended: it leaves no way to recover a box.

**Checked against ESP-IDF v5.3.2 (the pinned image) in step 2.** The Kconfig names above are right, with these findings from the IDF tree and the build:

- `DIS_USB_JTAG`, `SOFT_DIS_JTAG` and `HARD_DIS_JTAG` are eFuses, not options: the bootloader burns all three (and `DIS_DOWNLOAD_MANUAL_ENCRYPT`, `DIS_DIRECT_BOOT`, the download caches) when it enables secure boot or flash encryption, unless `CONFIG_SECURE_BOOT_ALLOW_JTAG` is set (it is not). `DIS_USB_SERIAL_JTAG` is not burned, so the USB serial port stays. "No UART download re-enable" is the default too.
- ESP-IDF 5.3.2 treats the `nvs_keys` partition as encrypted whenever flash encryption is on (`esp_partition`'s `partition.c`), so `partitions.csv` needs no `encrypted` flag and **the partition table does not change**. The `storage` partition (LittleFS: logos, mode files, no keys) is **not** encrypted by this overlay: that would need the `encrypted` flag on its row and a check that LittleFS's writes suit flash encryption's 16-byte blocks; left for a later decision, since the keys are in NVS.
- Secure boot v2 does not sign the partition table: the ROM checks the bootloader, the bootloader checks the app (the build lists only those two to sign). With flash encryption on, the table is encrypted.
- Keeping a digest slot empty (question 4) needs `CONFIG_SECURE_BOOT_ALLOW_UNUSED_DIGEST_SLOTS`, which ESP-IDF puts under "potentially insecure options" (`CONFIG_SECURE_BOOT_INSECURE`; no other option of that menu is set), **and** secure boot enabled from the host with `espefuse.py` before the first boot: when the bootloader enables secure boot itself it revokes every unused slot, whatever the option says. The more conservative alternative is to burn a third, spare root key's digest now (kept offline) and set neither option; step 3 decides between the two.
- The ROM downloader in secure download mode does not run `espefuse.py`: once a box is burned, its eFuses (a digest revocation, a new key in the spare slot) change only from code running on it, signed by a trusted key.
- `CONFIG_SECURE_FLASH_ENCRYPTION_AES128` (XTS-AES-128, one key block) is set; a key burned before the first boot decides the size anyway. With 2 + 1 digest slots and the flash key, 2 of the chip's 6 key blocks stay free.
- The bootloader does not fit with its log on (below, section 3): the overlay sets `CONFIG_BOOTLOADER_LOG_LEVEL_NONE`.

`tools/secure_boot_sign.py check-config` fails a build in which any option of the overlay is missing or has another value, so a later IDF that renames one cannot drop it in silence.

## 3. What it means for each way of putting software on a box

### USB re-flashing

- **Today**: `esptool write_flash`, the release's `-usb.zip` or the browser flasher with the `-merged.bin` at offset 0 work on any box, any time.
- **After the burn**: a plaintext image no longer boots. The bootloader and the app must be signed (secure boot) and **encrypted for the chip's flash key**. Whether that can be done over USB depends on **who made the flash-encryption key**:
  - *Key generated on the chip at first boot* (ESP-IDF's default): nobody knows it. A box can only be updated over the air from then on, and an OTA that fails in a way the rollback cannot catch (for example a bootloader or partition-table change) is a dead box. This is the strongest option and has no recovery.
  - *Key generated on the maintainer's computer and burned with `espefuse`*: `espsecure.py encrypt_flash_data` can encrypt an image for the chip and `esptool` writes it, so USB re-flashing and recovery stay possible, for whoever holds the key. A stolen key does not by itself open a box (reading is disabled), but it lets its holder write images; with secure boot also on, those still have to be signed. The key is as sensitive as the root release key: offline, encrypted, backed up.
  - **Recommended: the host-generated, fleet-wide flash key kept offline**, because losing the ability to recover boxes is the larger risk for a small project with no support staff. The maintainer chose this (2026-11-06, question 2).
- **The partition table can then never change over the air** (it never could: `main/fw_layout.c`) and now a table change also needs a signed table and a USB visit. The bootloader grows with secure boot and flash encryption; **check that it still fits below the partition table at 0x8000** (on the ESP32-S3 the bootloader starts at 0x0, so the area is 32 KB, its signature sector included). **Measured in step 2:** with secure boot v2 and flash encryption the bootloader is 0xb000 (45,056 bytes) at the default log level and 0x9000 (36,864) at Warning or Error, too big; with its log off (`CONFIG_BOOTLOADER_LOG_LEVEL_NONE`) it is 0x6000 (24,576), **0x7000 (28,672 bytes, 87.5 %) signed** with one, two or three keys (the signature blocks share one 4 KB sector), leaving 4 KB. The plain bootloader is 21,728 bytes. So the table does not move; the cost is a silent second-stage bootloader on a hardened box (the ROM's messages and the app's log stay). If it did not fit, the table would move (`CONFIG_PARTITION_TABLE_OFFSET`), which is a new layout (`FW_LAYOUT_VERSION` raised) and a first USB flash of every box. Decide this with the first test board, before any fleet burn: it is the one thing that can force a layout change.
- Boxes flashed before the burn are plain: **every existing box needs one USB visit** (new bootloader, the burn), there is no retrofit over the air. Today that is a handful of bench boards; once boxes are in customers' hands it would be a recall, which is a reason to decide before the first customer.

### The bench

- The bench build (`sdkconfig.bench`: `CONFIG_ATALAIA_SERIAL_KEYS`, no setup portal, radio logging, `@hold`, the listen-before-talk commands) and the Wokwi build are **never** signed with a release key and are never burned. Keep dedicated bench boards that stay un-burned, labelled so. A bench image flashed to a burned box will not boot, and a release image on a bench board is just a release image.
- Flash encryption can be tried in its *development* mode first: reversible a few times, so a test board can be flashed with a test key repeatedly. The sequence in section 4 uses a sacrificial board for it.
- Wokwi runs the plain build: unaffected. `tools/docker_fw.py build` for the Wokwi and bench variants stays as it is.
- The bench scripts and BRING_UP.md type `@joinkey` and `@update` without a PIN, which still works on a bench build (decision SR-40); a release build wants the PIN as the last word.
- A burned box cannot be bench-tested with ad-hoc images. The bench checklist for a hardened box is: boots, `NVS encryption is on` in the log, an unsigned image refused, an OTA of a signed image accepted, the old image refused after the security version is raised.

### Over-the-air updates

- The OTA path keeps its **Ed25519 manifest check** (decision S1) and the version floor. With secure boot on, the image **also** carries the RSA signature block and the bootloader verifies it before it boots the new slot; flash encryption encrypts the image as the box writes it (the OTA code needs no change).
- **The release pipeline gets one more step, before the Ed25519 manifest** (the manifest hashes the exact bytes of the image): build, sign with the RSA secure-boot key (`espsecure.py sign_data --version 2`), then `tools/firmware_release.py sign`. The CI key's RSA half goes into the release workflow as a second secret next to `ATALAIA_RELEASE_CI_KEY`; the root RSA key stays offline with the maintainer (RELEASE_SIGNING.md grows a section with the same compromise steps: revoke the digest). **Step 2:** `tools/secure_boot_sign.py sign` is that step and RELEASE_SIGNING.md has the section ("Secure boot signature"); the workflow is deliberately left unchanged and no secret has been added: an untested signing step in the release path, even an opt-in one, buys nothing before a board is burned, and wiring it in is a change for after step 4.
- The signature block adds a sector (4 KB) to the image, after padding to a 64 KB boundary. **Measured in step 2 (v0.9.0 + this change):** the hardened app is 2,228,224 bytes unsigned and **2,232,320 signed (0x221000), 53.22 % of the 4 MB slot** (the plain image: 2,194,160 bytes, 52.31 %); `tools/check_fw_ram.py` leaves **185,077 bytes** of internal RAM to the heap (plain: 185,805; the floor is 122,880). The build has no warnings.
- `CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE` stays; with anti-rollback on, a rolled-back image is one whose security version the eFuse still allows.
- A leaked CI RSA key: release signed with the root key, and revoke the CI key's digest with an OTA signed by the root key whose code calls `esp_efuse_set_digest_revoke` (not written yet). `espefuse` over USB does not work on a burned box: its ROM downloader is in secure download mode (section 2). Until then it is the same exposure RELEASE_SIGNING.md describes for the Ed25519 CI key, with a hardware floor under it.
- The modem and the I/O pod are USB-attached to a controller, not in the field's hands: their hardening is a separate, later decision (SR-42 asks only about the Field Box).

## 4. Proposed order of work (each burn a maintainer go-ahead)

1. Maintainer decides the questions in section 5. **Done for questions 2 to 6 (2026-11-06); question 1 open.**
2. Write `sdkconfig.release`, `tools/docker_fw.py release` and the pipeline step; build it. **No burn.** Check the bootloader size, the signed image size and `tools/check_fw_ram.py`. **Done (2026-11-06):** `sdkconfig.release`, `tools/docker_fw.py release-hardened` (with `--secure-boot-key PATH`, up to 3; a throw-away test key otherwise), `tools/secure_boot_sign.py` (sign, check the configuration, check the sizes) and CI's `esp32-hardened-build` job; the numbers are in sections 2 and 3. The pipeline step is written down, not wired: RELEASE_SIGNING.md, "Secure boot signature" (the release workflow is unchanged and has no new secret).
3. On **one sacrificial board**: flash encryption in development mode with a test key, secure boot with a throw-away RSA key, NVS encryption; run the hardened bench checklist above; try an OTA, a downgrade, an unsigned image and a power cut during the first-boot encryption (the first boot encrypts the whole flash in place and must not be interrupted).
4. Release mode on that board; repeat; keep it as the hardened reference board.
5. Fleet: burn boxes one at a time as they are built, in the build manual's step order (`hardware/field-box/BUILD.md` and the firmware guide get a step for it), with a record of each box's MAC and security version.
6. Raise the app-level docs: SECURITY.md (what a lost box exposes now becomes "the radio keys are not readable from the flash; the box can still be erased"), protocol/adoption.md section 2.

## 5. Questions for the maintainer

1. Do we burn eFuses on Field Boxes at all before the first customer, and on which build date? **Open.**
2. Flash-encryption key: made on the chip (no recovery) or on a host and kept offline (recoverable)? Recommended: host-made, offline. **Answered: host-made, kept offline.**
3. NVS encryption by the flash-encryption scheme (per chip) or the HMAC scheme (one fleet key)? Recommended: flash-encryption scheme. **Answered: the flash-encryption scheme** (`CONFIG_NVS_SEC_KEY_PROTECT_USING_FLASH_ENC`).
4. Two secure-boot digests (root offline + CI) and one spare slot, as proposed? **Answered: yes** (but see section 2: the spare slot survives only a host-side secure boot enable).
5. Anti-rollback: on from the first hardened release (security version 1), accepting that only 16 raises exist? **Answered: yes** (`CONFIG_BOOTLOADER_APP_SECURE_VERSION=1`).
6. May the modem and the I/O pod stay plain for now? **Answered: yes.**

## 6. What does not change

The Ed25519 release and mode keys, the app-level checks, the admin PIN, the field join key's rotation procedure (SECURITY.md), the box's OTA protocol and the partition table (unless the bootloader forces it, section 3). A hardened box still loses its key if the box is erased (a factory reset), and still lets anyone with code running on it read its NVS: this plan is about the box in a thief's hands, not about a compromised image.
