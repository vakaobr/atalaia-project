<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# Firmware updates over the air

How a Field Box gets a new firmware image from its field controller over the field's Wi-Fi, and why it can trust it. Design: decisions FU3-1 onwards in `docs/review/decisions-to-review.md`; the radio side is RFC 0001 Amendment 6 (CMD opcode 9). In software and in host tests; the over-the-air path has not yet run on a real board (`firmware/esp32/docs/BRING_UP.md`, "Firmware update over the air").

Code: the box's checks and update job `firmware/esp32/main/fw_update.c` (platform-free, host-tested with fakes) and its ESP-IDF side `fw_update_esp.c`; the shared Python `controller/atalaia_controller/firmware_release.py` (the site server's catalogue, the controller and `tools/firmware_release.py` use it); the controller's service `firmware_updates.py`; the Android field controller's `app/lib/protocol/firmware_release.dart` and `app/lib/controller/controller_firmware.dart` (slice S7c of PE24: the same API, the release keys set on the controller's screen, the boxes fetching over the phone's HTTPS with its field CA); the vectors `protocol/vectors/firmware.json`.

## Trust

- A **release key** (Ed25519, RFC 8032) signs each release. Its private half stays offline with the maintainer (`firmware/esp32/docs/RELEASE_SIGNING.md`); its public half is built into the firmware (`CONFIG_ATALAIA_OTA_RELEASE_KEYS`, up to 4 keys so that one can be rotated), set on the controllers (`[firmware] release_keys`) and on the site server (`ATALAIA_FIRMWARE_KEYS`, the catalogue of plan phase 19).
- **The box decides.** The controller and the site server check the signature too, but only to keep a bad release out of their lists; the box checks everything again with the keys in its own firmware before it writes a byte of the image to flash (decision S19-8).
- The image travels over **HTTPS pinned to the field CA**: the box trusts exactly the certificate authority whose SHA-256 its signed join payload carries (key 13), for the addresses the payload lists (key 14). It needs no clock (mbedTLS's validity dates are not checked without one) and no other trust store. The signature, not the channel, is what makes the image safe; the channel keeps a stranger on the field network from feeding the box garbage that it would only download to refuse.

## The release

The signed text (the **manifest**), exactly, UTF-8, a line feed after each line:

```
atalaia-firmware-release-v1
platform=esp32s3
version=0.3.0
size=1572864
sha256=<64 lower-case hex digits: the SHA-256 of the whole image file>
```

- `platform`: HELLO's names (`esp32`, `esp32s3`, `linux`, `android`); a Field Box is `esp32s3`.
- `version`: `MAJOR.MINOR.PATCH` (1-4 digits each) with an optional pre-release (`-` then 1-20 of `0-9A-Za-z.`, no empty identifier) and optional build metadata (`+` then the same), at most 35 characters, ordered as Semantic Versioning 2.0.0 section 11 orders versions: the build metadata is ignored (section 10), so `0.3.0-dev.7+gaaaaaaa` and `0.3.0-dev.7+gbbbbbbb` are equal and neither is newer. A Field Box's version is at most 31 characters (`esp_app_desc_t`). Build metadata is new (decision FV-2): a box, controller or site server from before it refuses such a version (`bad_release`, or the upload); a mode package's version never takes it.
- `size`: decimal, no leading zero, 1 to 4294967295.

The signature is the Ed25519 signature of those bytes, in standard base64 with its padding (88 characters). The **release id** is the first 16 hex digits of `sha256`.

`tools/firmware_release.py sign` writes `<image>.release.json`:

```json
{"format": "atalaia-firmware-release-v1", "platform": "esp32s3", "version": "0.3.0", "size": 1572864,
 "sha256": "...", "signature": "...", "key_id": "...", "variant": "box", "board": "heltec_v4_3"}
```

`key_id` is the first 16 hex digits of the SHA-256 of the public key's 32 bytes; `variant` and `board` are what the image says about itself (below).

## The image

An ESP-IDF application image (`atalaia_esp32.bin`). Its first 324 bytes, which a box reads before it writes anything:

| Offset | Bytes | What |
| --- | --- | --- |
| 0 | 24 | ESP image header (byte 0: `0xE9`) |
| 24 | 8 | the first segment's header |
| 32 | 256 | `esp_app_desc_t`: magic `0xABCD5432` (little-endian), version at 48 (32 bytes, NUL-terminated), project name at 80 (`atalaia_esp32`) |
| 288 | 36 | the Atalaia descriptor (`main/fw_desc.c`): `ATFW`, format `1`, 3 reserved bytes, variant (12 bytes: `box`, `box-bench`, `box-dev`), board (16 bytes: `heltec_v4_3`, `heltec_v4_2`), NUL-terminated and zero-filled |

The version in `esp_app_desc_t` is the firmware's version (`PROJECT_VER`: `ATALAIA_FW_VERSION` given to the build, or the core's version), which HELLO reports as `fw_version`. `tools/docker_fw.py` gives every build the commit it was built from (decisions FV-1 to FV-4): the core's version (`core/include/atalaia/version.h`, `0.3.0-dev` while 0.3.0 is developed), `.` and the commits since the last release tag `vX.Y.Z` (or since the first commit), `+g` and the commit's first 7 hex digits, and `.dirty` when tracked files had uncommitted changes: `0.3.0-dev.412+g8560d54`. So every development build of 0.3.0 sorts above `0.2.0` and below `0.3.0`, and a later commit above an earlier one. A release is built from its tag with `ATALAIA_VERSION_PRERELEASE` empty (`0.3.0`), or with `--fw-version=`; a copy with no commit history gets the core's version (`0.3.0-dev`, below every counted build).

## The offer

The GM uploads the image and its `.release.json` in the console (*Boxes* tab), or with `POST /api/v1/firmware?platform=&version=&signature=` (the raw image as the body, GM token). The controller keeps it (at most 4 releases) only if a key of `[firmware] release_keys` signed it, the image fits a 2 MiB OTA slot, and its descriptors say `atalaia_esp32`, the release's version, variant `box`.

`POST /api/v1/firmware/{id}/install` with `{"nodes": [7, 8]}` or `{"nodes": "all"}` (GM token): only while the live game is `ready` (never running, paused or ended: 409), only when the controller serves HTTPS (its joins carry keys 13 and 14), and for each box only if its HELLO says the release's platform, a box's tier (full or reduced) and a lower version (`not_newer` otherwise). The controller then sends each box, over the radio:

**CMD opcode 9, `update`** (RFC 0001 Amendment 6), to that box alone: `params` `{"id": "<release id>", "version": "<version>"}`.

The live game cannot start while an update is on its way (`sent` or `installed`, until `[firmware] update_timeout_s`, 600 s); the GM can stop waiting (`DELETE /api/v1/firmware/updates`), or send the update again at once to a box it names (`{"nodes": [7]}`) while its update is still `sent` (decision OT-9: a box already updating ignores the second offer; `"all"` skips such boxes, and an `installed` box is never sent another). A box stops a download as soon as a game starts. A mode's `field.lua` can never send `update`.

**The radio that carries the offer** is whatever the controller has: the Pi's USB radio modem, or, on the Android field controller, an I/O pod or a USB radio modem plugged into the phone (decision PE24-130). The offer is an ordinary game packet (RADIO_TX through a pod, [capability-proxy.md](capability-proxy.md)) under the radio's duty-cycle budget; a controller never reports an offer `sent` that its radio could not send: with no radio, a pod with no radio chip or a radio that is down, the answer is `radio` for that box (409 `box N: radio (why)` for one box, `radio_problem` in the answer for `"all"`), and a phone whose radio takes the offer and then refuses it (its TX_ACK: `duty_cycle`, `queue_full`, or another status) marks the update `failed` with the reason `radio_duty_cycle`, `radio_queue_full` or `radio_failed` at once, instead of `sent` until the timeout. The Pi's controller does not yet follow a refused offer's TX_ACK.

## The box

On CMD update (or `@update <version> <id>` on its serial console, which runs the same checks), a box refuses at once, showing why:

- `busy`: a game is being played (running or paused);
- `bad_offer`, `no_key` (no release key built in), `no_link` (the join has no field CA or no address), `not_newer` (the offered version is not above its own: **anti-rollback by version**; another build with the same version but other build metadata is not above it either), `battery` (below `CONFIG_ATALAIA_OTA_MIN_BATTERY_PCT`, with a gauge fitted).

Then, on its own task, while the radio and the joined game carry on:

1. Joins the field Wi-Fi (`@wifi <ssid> <password>` or the setup portal): `no_wifi`.
2. `GET <url>/api/v1/firmware/<id>/release` from the join's addresses in turn, over HTTPS pinned to the field CA: `unreachable`.
3. Checks the release text: exactly the manifest's five lines and `signature=<base64>`, nothing else (`bad_release`); the offered id and version (`bad_release`); the Ed25519 signature over the manifest with one of its own release keys (`bad_signature`); its platform (`wrong_platform`); a version above its own (`not_newer`); a size within the inactive OTA slot (`too_big`).
4. `GET <url>/api/v1/firmware/<id>/image`: a `Content-Length` other than the signed size is refused (`download`). The first 324 bytes must declare the release's version and `atalaia_esp32` (`bad_image`), the box's own variant and board (`wrong_board`); only then is the inactive slot opened (`esp_ota_begin`, which erases it) and written as the bytes come, hashed with SHA-256 on the way. More bytes than signed, fewer, a broken connection (`download`), a game starting (`cancelled`), a flash error (`flash`) abort the write (`esp_ota_abort`).
5. The size and the SHA-256 must be the signed ones (`bad_hash`); `esp_ota_end` must find the image valid (`flash`); **only then** does `esp_ota_set_boot_partition` make it the next boot.
6. Reports to the controller, reboots.

Whatever stops it, the controller hears why: over HTTPS once an address has answered, over LoRa otherwise (below).

Until step 5 the running image and the boot choice are never touched: an update that fails, or a power cut at any point before it, leaves the box running what it ran.

**After the reboot** the new image is `ESP_OTA_IMG_PENDING_VERIFY`. Once its radio and its storage have come up it runs its self-test (`fw_update_self_test`: SHA-256 and Ed25519 known answers, its release keys present, a join payload round trip, a Lua node running a script) and only then calls `esp_ota_mark_app_valid_cancel_rollback()`. If a check fails it calls `esp_ota_mark_app_invalid_rollback_and_reboot()`; if it crashes or reboots before, the bootloader (`CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE`) boots the previous image. Either way the old image comes back, and its HELLO tells the controller.

Production option, not enabled (decision FU3-8): ESP-IDF's secure version in eFuse (`CONFIG_BOOTLOADER_APP_ANTI_ROLLBACK`), with secure boot and flash encryption, would add a hardware floor under the box's own version check.

## The report

After step 2 has found an address, the box posts what happened to `POST <url>/api/v1/firmware/report` (no token), `Content-Type: text/plain`, with `X-Atalaia-Mac: <HMAC-SHA256 of the body with the game key, lower-case hex>`:

```
atalaia-firmware-report-v1
game=<game id>
node=<node id>
release=<release id>
result=<installed, or the code it stopped with>
version=<the version it will run: the new one when installed, its own otherwise>
```

The controller accepts it only for its live game, with that game's key, and for an update it sent to that box.

**Over LoRa when HTTPS cannot carry it** (decision OT-8, RFC 0001 Amendment 11): a box whose update failed before an address answered (`no_wifi`, `unreachable`), was refused before any network (the refusals above, `busy` included), or whose report got no `200` sends the standard event **`node.update_failed`** (id 52, critical: retried until the controller acknowledges it) in its joined game, with `release` (the offer's id, data key 37), `reason` (the result code) and `fw` (the version it still runs). It is sealed with the game key like all its events, and its event `seq` is the header seq of the first packet that carries it, so a second failure is a new event. The controller marks the update `failed` with that reason (only an update it sent to that box, still `sent` or `timeout`), the console shows it, and the event is in the game's log. A box in no game (an `@update` typed on its console) has no key to send it with.

The box's next HELLO shows the version it runs: the new one (`done`) or, after `installed`, the old one (`rolled_back`: the new image did not confirm itself). With no news for `update_timeout_s` the update is `timeout`. `GET /api/v1/firmware` (GM token) lists the releases and the updates; the console shows them, and the stream sends `{"type": "firmware", "updates": [...]}` on every change.

## Vectors

`protocol/vectors/firmware.json`: RFC 8032 section 7.1's five Ed25519 test vectors (copied from the RFC); releases signed with TEST 1's public test key (valid ones, and others whose version, size, hash or platform changed after signing, signed by another key, with a malleable `S + L`, with a flipped bit); release texts a box must refuse before any signature check; versions (Semantic Versioning's own ordering example, and this project's rule); image heads; reports and their MACs. `tools/protogen.py` turns them into `firmware/esp32/test/firmware_vectors.h`; the controller's tests check the same file in Python.
