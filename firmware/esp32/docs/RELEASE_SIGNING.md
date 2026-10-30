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

**What guards the CI key (security review SC-1, SC-2).** The `Sign and publish` job of `release.yml` is bound to the GitHub environment `release` (`environment: release`), and it fails unless the tag's commit is an ancestor of `origin/main` (the `version` job checks the same, earlier). The workflow file runs from the tag, so a tag on a commit with an edited workflow could drop that check: the check is defence in depth, and the controls that matter are the environment's required reviewers and the tag ruleset below, which only the maintainer can set (nothing in the repository can). A dry run (a branch) also waits for the environment's approval. Third-party actions are pinned by commit SHA and the ESP-IDF image by digest, `cryptography` in the signing job by hash (`tools/release-requirements.txt`), and `.github/dependabot.yml` proposes updates weekly.

### Repository settings the release needs (the maintainer does these; no workflow can)

Until step 2 is done the workflow's `environment: release` is only a label: GitHub creates an unprotected `release` environment on first use, and **a repository-level secret still reaches the job, and so every run of any workflow that can name it**, whatever the environment says. Do them in this order:

1. **Settings > Environments > New environment** `release`. Turn on **Required reviewers** (the maintainer; a second person if there is one; leave "Prevent self-review" off while the maintainer is the only reviewer, or the release cannot be approved). Under **Deployment branches and tags** choose *Selected branches and tags* and add the tag pattern `v*` and the branch `main` (the branch is for dry runs).
2. **Move the secrets.** In that environment add `ATALAIA_RELEASE_CI_KEY` and `ATALAIA_RELEASE_CI_KEY_PASSPHRASE` as **environment secrets**, then delete both from **Settings > Secrets and variables > Actions** (repository secrets). Run a dry run and a test tag afterwards: the job must show "Waiting for review", and the signature check against `CI_KEY_PUBLIC` must pass.
3. **Settings > Rules > Rulesets > New tag ruleset** for the pattern `v*`: restrict creations, updates and deletions to the maintainer (bypass list: the repository admin role only), and block force pushes. A release tag then cannot be made, moved or deleted by anyone else, and a tag on an unreviewed branch is refused before any workflow starts. `tag-release.yml` pushes the tag with the workflow token: the ruleset's bypass list must include the GitHub Actions app, or that push is refused and the tag is made by the maintainer by hand (`git tag -a vX.Y.Z <merge commit>`, `git push origin vX.Y.Z`, then `gh workflow run release.yml --ref vX.Y.Z`). Prefer the second: the bypass lets any workflow with `contents: write` make a `v*` tag, which is what the ruleset is there to stop.
4. **Reconsider Settings > Actions > General > "Allow GitHub Actions to create and approve pull requests"** (on since 2026-10-28 for `prepare-release.yml` and `tag-release.yml`). With it on, any workflow with `pull-requests: write` can open a pull request and, with the setting's second half, approve one: together with a branch ruleset that counts the bot as a reviewer, a workflow change could merge unreviewed code into `main`, and the release signs what is on `main`. Keep it only if the `main` ruleset requires a review from a code owner (a human, `CODEOWNERS`) and not from the Actions bot; otherwise turn it off and open the release and "Open X.Y.Z-dev" pull requests by hand (`python3 tools/prepare_release.py prepare --bump ...`, see CONTRIBUTING.md).
5. Optional, Settings > Actions > General: **Workflow permissions** to *Read repository contents and packages permissions* (every workflow already declares its own `permissions:`), and *Require approval for all outside collaborators*.

The pins in the workflows are refreshed by Dependabot pull requests; check each one (the commit SHA must be the release the comment names) before merging. To re-resolve a pin by hand: `git ls-remote --tags https://github.com/actions/checkout "v7*"` for an action, `docker buildx imagetools inspect espressif/idf:v5.3.2` for the image's index digest.

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

1. Build the release from a clean checkout of the tagged commit: `python3 tools/docker_fw.py build`, or `--fw-version=` for a release candidate. The release commit empties `ATALAIA_VERSION_PRERELEASE` in `core/include/atalaia/version.h` (`0.3.0-dev` becomes `0.3.0`) and is tagged `v0.3.0` (only with the maintainer's go-ahead); built there, clean, the image says exactly `0.3.0` (`docker_fw.py version` prints what a build would carry). Anywhere else a build carries its commit (`0.3.0-dev.412+g8560d54`, `0.3.0+3.gabcdef0` after the tag, `.dirty` with changes; decisions FV-1 to FV-4): sign those only with a bench key. The commit after the release sets the next version with `dev` again (`0.3.1`/`0.4.0`, `"dev"`), so that its builds sort above the release. Normally none of this is typed: **Prepare release** (`.github/workflows/prepare-release.yml`) opens the release pull request, merging it tags and starts `release.yml`, and a second pull request opens the next `dev` version ("Cutting a release" in `CONTRIBUTING.md`; `tools/prepare_release.py`).
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
