<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# Signing firmware releases

A Field Box installs a firmware update only if a **release key** built into its own firmware signed it (Ed25519 over the release's manifest: [protocol/firmware-update.md](../../../protocol/firmware-update.md)). Whoever holds a release key's private half can put firmware on every box that trusts it, so the key is kept like one: offline, encrypted, backed up, never in the repository, never on a field controller or a site server, and never on a CI runner, with one exception: the project's CI release key below. The tool is `tools/firmware_release.py` (it needs Python's `cryptography` package; the dev container has it).

## The project's release keys

Since 2026-10-28 the project signs its firmware releases with **two** release keys, like its mode keys (`docs/community/keys.md`). Both are the default of `CONFIG_ATALAIA_OTA_RELEASE_KEYS` (and `tools/docker_fw.py --release-keys`) and of the Pi's and the phone's `[firmware] release_keys`:

| Key | Key id | Public key (base64) | Where the private half lives | Used for |
| --- | --- | --- | --- | --- |
| **Root** | `424d053af5cdbc35` | `5tzPkN0AJSn+g34CP59linCRf/fcaWFc7GAAg7qzYNc=` | offline, with the maintainer only; its passphrase kept apart | signing by hand when the CI key cannot be used, and the release that drops the CI key if it ever leaks |
| **CI** | `32b3c815ac30ad43` | `rIO8ogMU3LRLLtnt6Rys+URdKYfmNv5mxvuRJQsX9Tw=` | this repository's GitHub secrets `ATALAIA_RELEASE_CI_KEY` (encrypted PKCS#8 PEM) and `ATALAIA_RELEASE_CI_KEY_PASSPHRASE` | the GitHub releases: `.github/workflows/release.yml` signs each Field Box image on a pushed tag `v*` |

Hex, for `--release-keys` and `CONFIG_ATALAIA_OTA_RELEASE_KEYS`: `e6dccf90dd002529fe837e023f9f658a70917ff7dc69615cec600083bab360d7` (root) and `ac83bca20314dcb44b2ed9ede91cacf9445d2987e636fe66c6fb91250b17f53c` (CI).

**What CI signs.** On a tag, the workflow builds the Field Box, USB modem and I/O pod images (the project's keys as defaults, no bench options), and signs the **Field Box** image's manifest with the CI key (`tools/firmware_release.py sign`, the key written to the runner's temporary folder only and deleted; the tool refuses a key inside the repository), checks the signature against the CI public key (a wrong secret fails the release), and publishes the files as a GitHub pre-release with `SHA256SUMS`. The modem and the pod are not updated over the air and have no `.release.json`; their files are covered by `SHA256SUMS` alone. A dry run (the workflow started by hand) signs with a throw-away key and publishes nothing.

This is a deliberate exception to "never on a CI runner" in the paragraph above, chosen by the maintainer (2026-10-28) so that releases can be signed without the root key leaving its offline media. Whoever can push a tag, change the workflow or read the repository's secrets can sign firmware that every box trusts; pull requests from forks never see the secrets.

**If the CI key leaks, or may have:**

1. Delete the two secrets and push no more tags. Remove the CI key from every controller's `[firmware] release_keys` (their lists withdraw every release it signed; the site server's `ATALAIA_FIRMWARE_KEYS` too, if you use it) and say so in a security notice.
2. Make a new CI key (the ceremony below), store it as the two secrets again, and put its id and public key in `release.yml` (`CI_KEY_ID`, `CI_KEY_PUBLIC`).
3. Sign a release **with the root key**, by hand on the offline machine (steps below), whose firmware carries the root key and the new CI key in `CONFIG_ATALAIA_OTA_RELEASE_KEYS` and no longer the old one. A box accepts it because it still trusts the root key, and from then on refuses what the old key signs. Boxes on older firmware keep trusting the leaked key until they run it: software alone cannot protect them, so anyone with the leaked key and a box's controller could push an image, within the update rules (no game running, a higher version, the field's own controller sending the command). Treat every box that has not updated as exposed, and flash it by USB if in doubt.
4. If the **root** key is lost, the boxes need a firmware flashed by USB with new keys. The production hardening, ESP-IDF secure boot with flash encryption and the eFuse secure version (decision FU3-8), is not in use yet.

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

1. Build the release from a clean checkout of the tagged commit: `python3 tools/docker_fw.py build`, or `--fw-version=` for a release candidate. The release commit empties `ATALAIA_VERSION_PRERELEASE` in `core/include/atalaia/version.h` (`0.3.0-dev` becomes `0.3.0`) and is tagged `v0.3.0` (only with the maintainer's go-ahead); built there, clean, the image says exactly `0.3.0` (`docker_fw.py version` prints what a build would carry). Anywhere else a build carries its commit (`0.3.0-dev.412+g8560d54`, `0.3.0+3.gabcdef0` after the tag, `.dirty` with changes; decisions FV-1 to FV-4): sign those only with a bench key. The commit after the release sets the next version with `dev` again (`0.3.1`/`0.4.0`, `"dev"`), so that its builds sort above the release.
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
