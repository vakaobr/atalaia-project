<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# Signing firmware releases

A Field Box installs a firmware update only if a **release key** built into its own firmware signed it (Ed25519 over the release's manifest: [protocol/firmware-update.md](../../../protocol/firmware-update.md)). Whoever holds a release key's private half can put firmware on every box that trusts it, so the key is kept like one: offline, encrypted, backed up, never in the repository, never on a field controller, a site server or a CI runner. The tool is `tools/firmware_release.py` (it needs Python's `cryptography` package; the dev container has it).

## The key ceremony (once per key)

1. On a machine you trust, ideally offline (a laptop with Wi-Fi off, a live USB system), make the key with a passphrase:

   ```sh
   python3 tools/firmware_release.py keygen --out ~/atalaia-release-keys/release-2026.pem
   ```

   The tool refuses a path inside the repository and never overwrites a key. It prints the key's id and its public halves: hex for the firmware, base64 for the controllers and the site server.
2. Back the `.pem` up to two offline places (encrypted USB sticks kept apart); write the passphrase down separately. Note the key id and the date in the maintainers' records.
3. Publish the public halves, which are not secret:
   - firmware: `CONFIG_ATALAIA_OTA_RELEASE_KEYS` in `sdkconfig.defaults` (a commit, reviewed like any other: it decides what every box will accept);
   - controllers: `[firmware] release_keys` in `controller.toml`;
   - site server: `ATALAIA_FIRMWARE_KEYS`.

Boxes already in the field learn a new key only from a firmware release that carries it, signed by a key they already trust.

## Signing a release

1. Build the release from a clean checkout of the tagged commit: `python3 tools/docker_fw.py build` (the version is the core's, `core/include/atalaia/version.h`, or `--fw-version=` for a release candidate).
2. Copy `firmware/esp32/build/atalaia_esp32.bin` to the signing machine and sign it:

   ```sh
   python3 tools/firmware_release.py sign atalaia_esp32.bin --key ~/atalaia-release-keys/release-2026.pem
   ```

   It refuses an image whose own descriptors are missing or say another version, and writes `atalaia_esp32.bin.release.json` (platform, version, size, SHA-256, signature, key id, variant, board).
3. Check it as a box would: `python3 tools/firmware_release.py verify atalaia_esp32.bin atalaia_esp32.bin.release.json --keys <public key>`.
4. Publish both files together. A GM uploads them in the console's *Boxes* tab; a server administrator may add the release to the site server's catalogue with the same fields.

## Rotating or withdrawing a key

- **Rotation:** make a new key (ceremony above); ship a release with both public keys in `CONFIG_ATALAIA_OTA_RELEASE_KEYS` (up to 4), signed with the old key; once the boxes run it, sign later releases with the new key and drop the old one in a later release. Add the new key to the controllers and the site server before the first release it signs.
- **A key that leaked:** remove it from every controller and the site server at once (their lists withdraw every release it signed), and ship a release, signed with another trusted key, that no longer carries it. Until a box runs that release it still trusts the leaked key: a box with an older firmware cannot be protected by software alone. The production option is ESP-IDF secure boot with flash encryption and the eFuse secure version (decision FU3-8).

## Bench keys

For a test on the desk (`BRING_UP.md`, "Firmware update over the air") make a throw-away key with `keygen --unencrypted` outside the repository, build bench images with `--release-keys=<its hex>`, and delete it afterwards. A bench key must never sign anything meant for a Field Box; bench images (`box-bench`) do not install on Field Boxes anyway.
