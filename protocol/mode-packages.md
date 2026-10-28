<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# Signed mode packages

How a mode (a main mode, a modifier, a role package or a scenario) travels as one signed file, how a registry lists them, and how a field controller checks one before it installs it. Design: ADR-P5-3 and P5-4 as amended 2026-10-22 (`docs/phase-5-community/ADR.md`), decisions P5R-7, P5B-9, P5B-10 and P5C-8 onwards in `docs/review/decisions-to-review.md`. In software (phase 5 plan phases 4 and 6); boxes fetching the signed packages a game needs from their controller is plan phase 13: the controller, console and wire contract in 13a (decisions P5D-1 onwards, section "Fetching missing modes" below), the box in 13b, an Android prop in section 7 (decisions PKF-1 onwards).

Code: the shared Python `controller/atalaia_controller/mode_package.py` (the tool, the controller and, later, the registry's CI use it); the tool `tools/mode_package.py`; the controller's import `controller/atalaia_controller/signed_modes.py`; the vectors `protocol/vectors/mode_package.json` (made by `tools/mode_package_vectors.py`); the index's JSON Schemas `registry/schema/`.

## Trust

- A **mode key** (Ed25519, RFC 8032) signs each package; its id is the first 16 hex digits of the SHA-256 of its 32 public bytes, as a firmware release key's. The private half stays offline with whoever signs (`tools/mode_package.py keygen`, an encrypted PKCS#8 file outside the repository).
- **The controller decides with its own keys.** It installs a signed package only when one of the keys in its own configuration (`[modes] keys`) signed exactly the package's manifest, and that key is not revoked (`[modes] revoked`, and a registry's `revoked.json`). Nothing an index or a release file says about who signed it is trusted: the `key_id` beside a signature only tells "signed by a key I do not trust" (`no_key`) from "not signed" (`bad_signature`).
- **Boxes** (plan phase 13) check the same signature with mode keys built into their firmware only (`CONFIG_ATALAIA_MODE_KEYS`, and the release keys `CONFIG_ATALAIA_OTA_RELEASE_KEYS`; the maintainer's answer to P5B-9, 2026-10-22), never with keys a controller sends. The controller lists those keys as `[modes] box_keys` only to offer what boxes will take.
- A signature says who vouches for a package; the sandbox (`core/tests/test_sandbox_escape.c`, plan phase 5) is what limits its scripts.

## The archive

A POSIX ustar archive (IEEE Std 1003.1, `pax` "ustar" format) of the package's files under one root folder named after the mode's id, in **one canonical form**, so that the same files always give the same bytes and the same SHA-256:

- regular files only (type `0`), no folders, links, devices, GNU or pax extensions;
- names `<id>/<file>` of at most 100 bytes in the name field, the prefix field empty;
- the files the controller takes: `mode.yaml`, `node.lua`, `field.lua` and `assets/...` (letters, digits, `_`, `.`, `-`), no segment empty or starting with a dot; at most 64 files; UTF-8 text without NUL;
- sorted by name (byte order); mode `0000644`, uid and gid `0000000`, mtime `00000000000`, user and group names empty, devmajor and devminor `0000000`, the checksum as six octal digits, NUL and a space;
- each file's data padded with zeros to 512 bytes; the archive ends with exactly two zero blocks;
- at most 1 000 000 bytes (the controller's package limit, P5-6). A box will take at most 256 KiB (P5B-12).

A reader takes only this form: it parses each header strictly, then packs the files it read again and refuses the archive unless the bytes are the same. So nothing in an archive can name a path outside its root, a link or a device, and an archive cannot carry anything a reader does not see. Nothing is extracted to disk: the files are read into memory.

`tools/mode_package.py pack modes/domination` makes it from a mode folder (`tests/` and other files are left out and listed). The mode editor's *Make the package* (`simulator/atalaia_sim/editor/package.js`, decisions P5I-1 to P5I-6) makes the same bytes from the files it generates, in the browser; its tests compare it with `pack` for these vectors and every built-in mode. Neither signs: signing is `tools/mode_package.py sign`, offline.

## The manifest and the release

The signed text (the **manifest**), exactly, UTF-8, a line feed after each line:

```
atalaia-mode-package-v1
id=org.club.my-mode
version=0.1.0
kind=mode
min_tier=reduced
size=4608
sha256=<64 lower-case hex digits: the SHA-256 of the whole archive>
```

- `id`: the mode's reverse-domain id (`[a-z0-9][a-z0-9_-]*` parts joined by dots, at least two), at most 63 bytes; the archive's root folder and its `mode.yaml` say the same.
- `version`: as a firmware release's (`MAJOR.MINOR.PATCH`, an optional pre-release; Semantic Versioning order); `mode.yaml`'s.
- `kind`: `mode`, `modifier`, `role` or `scenario` (`mode.yaml`'s, `mode` when it says none). A box never takes a scenario.
- `min_tier`: `reduced` or `full` (`mode.yaml`'s, `reduced` when it says none: a box checks a script with its own Lua heap anyway).
- `size`: decimal, no leading zero.

The signature is the Ed25519 signature of those bytes in standard base64 with padding (88 characters). Binding the id, version, kind and tier stops a signature being reused for another mode, an older version, or a box it was not meant for.

The **release text** (what a box will fetch, plan phase 13) is the manifest followed by `signature=<base64>` and a line feed, nothing else. `tools/mode_package.py sign` writes `<archive>.release.json`:

```json
{"format": "atalaia-mode-package-v1", "id": "org.club.my-mode", "version": "0.1.0", "kind": "mode",
 "min_tier": "reduced", "size": 4608, "sha256": "...", "signature": "...", "key_id": "...",
 "license": "MIT"}
```

`key_id` and `license` describe the package; a verifier never trusts them.

## Checking a package

In this order, refusing at the first failure (the code in brackets is `PackageError.code`):

1. the release's fields have their forms [`bad_release`];
2. the size is within the limit [`too_big`];
3. the archive's size and SHA-256 are the signed ones [`bad_hash`];
4. a trusted mode key signed exactly the manifest [`no_key` when the key it names is not trusted, else `bad_signature`];
5. that key is not revoked [`revoked`];
6. the archive is in the canonical form, with the id as its root [`bad_archive`, `mismatch`, `too_big`];
7. its `mode.yaml` parses and says the manifest's id, version, kind and tier [`bad_manifest`, `mismatch`], with one of the approved licences of ADR-P5-5: `GPL-3.0-or-later`, `LGPL-3.0-or-later`, `MIT`, `Apache-2.0`, `BSD-2-Clause`, `BSD-3-Clause`, `CC0-1.0` [`licence`].

The controller then installs it through the same checks as an upload (`POST /api/v1/modes`: the manifest, the scripts loading in the core, never a built-in id).

## The registry index

`index.json` (schema `registry/schema/index.schema.json`):

```json
{"schema_version": 1, "name": "Atalaia community modes",
 "modes": [{"id": "org.club.relay", "name": "Relay", "description": "...", "author": "...",
            "versions": [{"version": "1.2.0", "kind": "role", "min_tier": "full", "size": 4608,
                          "sha256": "...", "signature": "...", "key_id": "...", "license": "MIT",
                          "url": "packages/org.club.relay-1.2.0.tar", "verified": true}]}]}
```

- `url`: `https://...`, or a path relative to the index (an index on a USB stick or a folder, for a field without internet); never `http://`, never `..`.
- `verified`: the project reviewed the package against the review checklist (ADR-P5-8): the verified badge. A controller shows packages that are not as *not reviewed by the project*.
- A version is listed once per mode; anything else in the index refuses the whole index (`bad_index`).

`revoked.json` (schema `registry/schema/revoked.schema.json`): `{"schema_version": 1, "keys": [{"key_id": "...", "reason": "...", "date": "2026-10-22"}]}`.

`tools/mode_package.py index index.json <archive>.release.json --url ... --name ...` adds a release to an index.

The community registry (`atalaia-modes`, made from `registry/template/`) keeps its packages beside its index (`url` `packages/<id>-<version>.tar`), each signed by its author and, with the verified badge, by the project's registry key over the same archive (`<archive>.verified.json`; the index then lists that signature). Its rules and CI: [docs/community/registry.md](../docs/community/registry.md); `tools/registry_check.py`.

## Fetching missing modes

A box gets from its field controller, between games, the signed packages a game needs that it lacks (the maintainer's P5R-8; plan phase 13; decisions P5B-8 to P5B-17 and P5D-1 onwards). This section is the contract between the controller (13a: `controller/atalaia_controller/mode_fetch.py`, the console's invite dialog) and the box (13b: `firmware/esp32/main/mode_fetch.c`). The Python reference of every box check and of the report is in `controller/atalaia_controller/mode_package.py` (`box_check_release`, `box_check_archive`, `report_body`, `parse_report`); the shared vectors are `box_limits`, `box_checks` and `reports` in `protocol/vectors/mode_package.json`, and `mode_fetch` in `protocol/vectors/join.json`.

### 1. The join (keys 16 and 17)

Two optional keys of the join payload ([join.md](join.md)): **16 `fetch_modes`** and **17 `forget_modes`**, each CBOR `true` (`0xf5`) when set and left out otherwise. `false`, a number, null or anything else refuses the payload (`body`). The tag covers them as any key. Firmware before 13b skips them (every reader skips keys up to 31), so an old box answers *no mode* as before.

A box reading a join, by card, QR code, text or invite:

1. **Key 17 first**: it forgets every package it fetched (section 5: the files and the slots), whatever else happens to the join afterwards (it is authenticated by the join key).
2. Each `+` part of `mode_id` it has neither built in nor fetched is *missing*. None missing: the join goes on as today (key 16 changes nothing).
3. Missing parts **and** key 16 **and** keys 13 and 14 **and** at least one mode key built in: the box **accepts** the join (an invite's answer is `accepted`, field-frames.md result 0), stores it, and *fetches* (section 2) instead of saying HELLO. Otherwise it answers **`no_mode`** (result 3) as today: the console then says that this box's firmware cannot fetch.
4. Only between games: a box joined, playing or paused never fetches (`busy` as for any join).

The controller writes key 16 only with keys 13 and 14 (it refuses to make such a join without HTTPS, or if the payload with them is longer than 448 bytes), and only when every part the box would run is either built in or offered (section 6).

### 2. What the box fetches, and from where

For each missing part, in the order of `mode_id`, the box joins the field Wi-Fi (as for a firmware update; none: `no_wifi`) and, from the addresses of key 14 in turn, over **HTTPS pinned to the field CA** of key 13 (as [firmware-update.md](firmware-update.md); no address answers the TLS handshake: `unreachable`):

| Request | Answer |
| --- | --- |
| `GET <url>/api/v1/mode-packages/<id>/release` (no token) | `200 text/plain`: the **release text** (the manifest's seven lines and `signature=<base64>`, a line feed after each; at most 512 bytes, so a box reads at most 512). `404` the controller does not offer it, `409` no live game is ready (a game started): **`not_offered`** |
| `GET <url>/api/v1/mode-packages/<id>/package` (no token) | `200 application/x-tar` with `Content-Length`: the archive exactly as signed. `404`, `409` as above (`not_offered`) |

`<id>` is the part's id as in `mode_id` (letters, digits, `.`, `_`, `-`: no escaping). The controller serves a part only while its live game is `ready`, only a `+` part of that game's mode id, and only if it offers it (section 6). Both answers carry `Cache-Control: no-store`.

### 3. What the box checks, in order

Refusing at the first failure, with the code it reports (the vectors' `box_checks` are each case's result, in this order):

1. no mode key built in: `no_key` (normally caught at the join already, step 1.3);
2. the release text is exactly the manifest's lines and a signature, in the canonical form (as `parse_release_text`), and its `id` is the part it asked for: `bad_release`;
3. Ed25519 over exactly the manifest's bytes with **one of its own keys** (`CONFIG_ATALAIA_MODE_KEYS`, then the release keys): `bad_signature`;
4. `kind` is `mode`, `modifier` or `role` (never `scenario`): `kind`;
5. a Reduced box refuses `min_tier=full`: `tier`;
6. `id` is not one of its built-in modes (the firmware owns those, K10): `builtin`;
7. `size` at most **262144** bytes (256 KiB): `too_big`; room for it (section 5, after dropping what it may drop): `no_space`;
8. the archive: a `Content-Length` other than `size`, more or fewer bytes, a broken connection: `download`; streamed into a temporary file while its SHA-256 is computed, and size and SHA-256 must be the signed ones: `bad_hash`;
9. the archive's canonical ustar form (section "The archive") with the id as its root, and a `node.lua`: `bad_archive`. The box keeps only `node.lua` and `assets/screens/*.yaml`; it never reads `mode.yaml` (the signed manifest says what it needs);
10. `node.lua` loads in a fresh sandbox with the box's tier limits (the same `node_runner` load as a game, no game started), its screens parse, and the composed game (every part of `mode_id`) fits the 16 KB preset buffer: `load`;
11. written to storage and the slot marked, atomically (section 5): a flash error is `storage`.

A game starting while a fetch is on (a CMD start of another game, a card, the picker): `cancelled`. Only after the last part is in does the box say HELLO in the joined game, as after any join (a failure it must say over LoRa also goes through a HELLO: section 4, "The HELLO and the event"). At the first failure it reports (section 4), stops (the parts installed before it stay), **leaves the join** (it is free again, announces itself with a new token, and the game is *not* counted among its ended games, so the GM can invite it again), and shows why on its screen.

### 4. The report

After each part (installed, or the code it stopped with), once an address has answered, the box posts `POST <url>/api/v1/mode-packages/report` (no token), `Content-Type: text/plain`, `X-Atalaia-Mac: <HMAC-SHA256 of the body with the game key, lower-case hex>`, at most 1024 bytes:

```
atalaia-mode-report-v1
game=<game id>
node=<node id>
mode=<the part's id>
version=<the version of the release it read, or - when it read none>
result=<installed, or the code it stopped with>
kept=<every package it keeps now, id@version, sorted by id, joined by commas; - for none>
```

Results: `installed`, `no_wifi`, `unreachable`, `not_offered`, `download`, `no_key`, `bad_release`, `bad_signature`, `kind`, `tier`, `builtin`, `too_big`, `bad_hash`, `bad_archive`, `load`, `no_space`, `storage`, `cancelled`. Numbers without leading zeros; game and node 1-65534; at most 8 in `kept`. The controller answers `200 {"accepted": true}` for a fetch it is waiting for from that node, `{"accepted": false}` otherwise (it still records `kept`), `400` for a body or MAC that does not verify, `409` for a game that is not its live game, `413` over 1024 bytes.

**Over LoRa when HTTPS cannot carry it** (no Wi-Fi, no address answered, or the report got no `200`): the standard event **`node.modes_failed`**, id **53**, priority **critical** (retried until acknowledged), data **`mode`** (a new data field, **key 38**, string: the part's id) and **`reason`** (key 3: the code), sent in the joined game, sealed with the game key, from the join's node id, *before* the box leaves the join. 13b adds it to `protocol/schema/events.yaml` (`node.modes_failed: { id: 53, prio: critical, data: [mode, reason] }`, `mode: { key: 38, type: string, doc: "mode package id: a part of a game's mode id" }`) and regenerates the tables. The controller marks that node's fetch failed; a node heard only this way does not count as joined for the start guard.

**The HELLO and the event** (found on the bench, 2026-10-23; decisions P5E-8 and P5D-14 to P5D-18). The event needs the game's link, so a box saying a failure over LoRa first says **HELLO** in the joined game (its STATE says *waiting*), then sends `node.modes_failed`, then leaves the join once the event is acknowledged (or after 60 s). A HELLO from a fetching node therefore does not by itself mean the fetch succeeded. The controller:

- counts a fetch as **done** on its HELLO only when it holds HTTPS reports that the box keeps every part it was offered for that join (each reported `installed`, or listed in the `kept` of a report of that fetch, or, without key 17 in the join, of the box's last report before it: a box that lacked nothing when the join came fetches and reports nothing);
- otherwise leaves the fetch on its way (`fetching`, with `hello_seen`): the node does not count as joined, the invite shows `accepted`, and the start guard keeps waiting;
- then takes `node.modes_failed` for that node and game: the fetch is `failed` with its `reason`, the invite shows `failed`, the node does not count as joined, the start guard stops waiting, and the box (free again once it announces itself) can be invited again into the same game; or a late report that completes the parts: `done`, joined; or neither within `[modes] fetch_timeout_s`: `timeout` with reason **`report_lost`**, not joined;
- takes `node.modes_failed` even after a fetch ended `done` in its HELLO (every part reported installed, yet the composed game does not load on the box: `load`, P5E-10), and the node stops counting as joined; a fetch already `failed` keeps its first reason, and a HELLO never ends a failed fetch;
- never hears the box leave (it goes quiet on the game's link and announces itself in field frames): a node whose fetch did not end in its HELLO is not shown as in the game.

A plain join for the same node (no key 16 or 17) ends a fetch made for it before. No change on the box: it already reports each part before its HELLO and sends the event after it.

### 5. On the box (13b)

On the `storage` LittleFS partition: `/littlefs/modes/<id>/node.lua`, `/littlefs/modes/<id>/assets/screens/*.yaml` and `/littlefs/modes/<id>/release` (the release text as fetched); a slot table (`/littlefs/modes/index`, or NVS) with, per package, id, version, signer key id, SHA-256, archive size and when a game last used it. At most **8** packages and **524288** bytes (512 KiB) of archives in all (`box_limits` in the vectors). A newer version replaces an older one only once it passed every check (written under a temporary name, then renamed; the slot updated last), so a failed fetch leaves the box as it was. When space is needed it drops the package a game used least recently, never one of the joined game's parts and never a built-in one; nothing to drop: `no_space`. Key 17 and a factory reset forget all of them. Fetched packages are used exactly as built-in ones (the preset store and the screen parser read them). At boot the box verifies each kept release's signature again with the keys of the firmware it now runs: a package whose key left the firmware (a revocation shipped in a release) is not used and is dropped.

### 6. What the controller offers (13a)

A part is **offered** when it is installed on the controller as a signed package (its archive kept, store schema 10), signed by a key the controller trusts now (`[modes] keys`, not revoked), of kind `mode`, `modifier` or `role`, at most 256 KiB, and its signer is one of `[modes] box_keys` (the keys built into the boxes' firmware; at most 8). Otherwise the console says why: `builtin`, `missing`, `unsigned`, `revoked`, `untrusted`, `kind`, `no_box_key`, `too_big`. For a box's role, a fetch can help only when every part of what it runs is built in or offered and at least one is offered (all built in: the box's firmware is older, `firmware`), with `box_keys` set (`no_box_keys`) and HTTPS on (`no_https`); a Reduced box (its announcement's tier 1) is not sent a `min_tier=full` part (`tier`).

`GET /api/v1/mode-fetch` (GM): `box_keys` (ids), `https`, `timeout_s`, `max_package_bytes`, `game`, `roles` (per role of the live game: `mode_id`, `parts` with their `state`, `ok`, `why`), `fetches` (per node: `state` `sent`, `fetching`, `installed`, `done`, `failed`, `timeout`, `cancelled` or `forget`, `reason` (also `report_lost`: section 4), `mode`, `installed`, `parts` (the parts it was offered), `kept` (from this fetch's last report, or null), `hello_seen` (its HELLO came before the reports: section 4), `device_id`), `boxes` (each box's `kept` from its last report, `forget`). `DELETE /api/v1/mode-fetch` stops waiting. `PUT /api/v1/mode-fetch/forget/<device id> {"forget": true|false}` marks a box to get key 17 in its next invite (the mark goes when it says HELLO, even a HELLO that does not end its fetch: the box reads key 17 first). Invites (`GET /api/v1/games/{id}/invites`, `/boxes`) show a box whose fetch did not end in its HELLO as `accepted` while the controller waits, `failed` (detail `mode fetch <state>: <reason>`) after, never `joined`. Invites take `fetch_modes: true` per box (`POST /api/v1/games/{id}/invites`), and so do card joins (`POST /api/v1/join`, `/nodes/{id}/join`). The live game cannot start while a fetch is `sent`, `fetching` or `installed`, for `[modes] fetch_timeout_s` (300 s) at most; `{"force": true}` does not skip it (as the firmware guard). The stream sends `{"type": "mode_fetch", "game", "fetches", "boxes"}` on every change.

### 7. An Android prop (PKF-1 onwards)

An Android prop fetches the packages a joined game needs the way a box does (`app/lib/modes/prop_mode_fetch.dart`; the box's contract above, with these differences and no others):

- **Same checks, same order, same codes**: it runs the Dart ports of `box_check_release` and `box_check_archive` (`app/lib/controller/mode_package.dart`, which pass `box_limits` and `box_checks`), as a Full device (a phone takes `min_tier=full`), with the same `builtin` rule (the app's built-in modes are never replaced), the 256 KiB limit and the 8 packages and 512 KiB of the box's store.
- **Trust roots**: the mode keys built into the app (`--dart-define=ATALAIA_MODE_KEYS="<base64> <base64>"`) and the *Mode keys for fetched modes* of its settings (at most 4, public halves in base64), the counterpart of `CONFIG_ATALAIA_MODE_KEYS`; never a key a controller sends (P5B-9). None: nothing is fetched (`no_key`, before any request). A key that is not trusted any more drops what it signed from the phone's store the next time the store is read.
- **When**: only at the join (the setup screen), when a part of `mode_id` is neither built into the app nor kept, the join has keys 13 and 14 **and key 16**, and never with a game running. Without key 16 the prop says as before that it lacks the mode. Key 17 makes it forget what it kept before it looks.
- **What it keeps and runs**: unlike a box, a phone parses YAML, so it also reads the package's `mode.yaml` (roles, parameters, names) and requires that it say the signed manifest's id, version, kind and tier (`bad_archive` otherwise); it keeps the archive and its signed release, and runs `node.lua` and the screens in the core's sandbox with a Full tier's limits. Before keeping anything it starts the composed game once in that sandbox (`load` when it does not load).
- **The report** is the box's (`atalaia-mode-report-v1`, section 4) with the game key's HMAC, posted after each part to each address in turn; a prop has no LoRa path for `node.modes_failed`, so a failure whose report got no `200` is the controller's `report_lost` after `fetch_timeout_s`. A prop that failed does not start the game; it stays on its setup screen with the reason, and the GM can invite it again.
- **What the user sees**: a message for each code (`propmodes.err.<code>` in `app/lib/l10n/`): an unsigned or badly signed package is refused with "not signed, or not signed by a key this phone trusts. It was not run."

### 8. The field's logo (decision PKG-1)

Additive: it needs no join key and changes no frame. The same box that fetches packages shows the field's logo on its big screen, fetched from the same controller over the same HTTPS (never over LoRa). Firmware without it does not ask, and a controller without it answers `404` to the box's request, so every pair works as before.

**When.** Once for each joined game, while the box waits for the game to start: a join whose keys 13 and 14 name the controller (fetching modes, key 16, is not needed), a box that is not playing or fetching, the field Wi-Fi up (none: nothing happens, no report). A box taken to another field (adoption) forgets the logo.

**What the controller prepares.** The box has no PNG or JPEG decoder (its image has no room for one), so the controller converts the field's logo, kept as uploaded by [branding](../controller/README.md), into `96 x 96` pixels: only a **PNG** is converted (the controller has no JPEG or WebP decoder, decision BR7), up to 1,048,576 pixels, every PNG colour type and depth, Adam7 included, a `tRNS` palette, key or alpha. The picture is fitted into 96 x 96 keeping its shape, centred; each output pixel is the average of the source pixels it covers (the nearest pixel when the logo is smaller), alpha composited on the box's screen colour `#101418`; all sums on whole integers, so the Pi's controller and the phone's give the same bytes. The result is `"ALG1"`, `u16le 96`, `u16le 96` and 9,216 little-endian RGB565 words (`r5 = r >> 3`, `g6 = g >> 2`, `b5 = b >> 3`), 18,440 bytes. `protocol/vectors/box_logo.json` holds PNG files for every case and the SHA-256 of their 18,440 bytes (made by `tools/box_logo_vectors.py`; both controllers' tests check them).

| Request | Answer |
| --- | --- |
| `GET <url>/api/v1/field/box-logo/release` (no token) | `200 text/plain`: `atalaia-box-logo-v1`, `id=<64 hex>` (the SHA-256 of the logo image as the controller stores it, the id in `GET /api/v1/field/branding`), `sha256=<64 hex>` and `bytes=18440` (of the box-ready bytes), a line feed after each; at most 192 bytes. `404`: no logo, or one the controller cannot convert (not a PNG, too large, damaged). |
| `GET <url>/api/v1/field/box-logo` (no token) | `200 application/octet-stream` with `Content-Length: 18440` and `ETag: "<id>"`: the bytes above. `404` as above. |

Both carry `Cache-Control: no-cache` and count against the branding endpoints' rate limit.

**What the box does.** It asks for the release text from the addresses of key 14 in turn (HTTPS pinned to the field CA, as above). The `id` is the one it keeps: nothing more, the common case. Another `id`: it streams the bytes into a temporary file, hashed as they come, and keeps them only when they are exactly 18,440 bytes of the promised SHA-256 with the header above (anything else, or a connection that breaks, a game that starts: the logo it kept stays, and nothing half-written is left). `404`: it removes the logo it kept and shows the Atalaia logo again. It keeps `/littlefs/logo.bin`: the 64 hex digits of the `id` and the 18,440 bytes; nothing else changes on the storage partition. The big screen shows the logo on the **READY** screen (no game) and on the bomb's *waiting* screen, with the Atalaia towers in its place when the box keeps none; the OLED keeps the Atalaia tower.

## Vectors

`protocol/vectors/mode_package.json`: RFC 8032's TEST 1 and 2 (copied from the RFC; TEST 1's key signs the vectors' releases, a public test key, never a mode key), the canonical archive of a small role package (also read back with Python's `tarfile`), 28 archives every reader refuses (path traversal, an absolute name, links, a folder, GNU and pax headers, the prefix field, a wrong checksum, an old GNU header, non-canonical times, modes, owners and order, a file twice, two roots, a file outside a root, a root that is not an id, a file the controller does not take, a hidden file, text that is not UTF-8 or has a NUL, data after the end, no end, a truncated file, a partial block, an empty archive), signed releases and copies changed after signing, whole checks with their result, release texts a reader refuses, and a valid and invalid indexes and revocation lists. For plan phase 13: `box_limits`; `box_checks`, 18 cases of a box's checks in its order (each with the release text, the part asked for, the box's keys, tier and built-in ids, the archive it downloads or none, and the result: `ok` with the signer and the files kept, or the code); `reports`, 3 reports with their MACs under `game_key` and 12 bodies to refuse. `python3 tools/mode_package_vectors.py --check` (in `tools/check.sh` and CI) fails when the file is stale. `protocol/vectors/box_logo.json` (the field's logo, section 8: 7 PNG logos and the SHA-256 of their box-ready bytes, and the release text). `protocol/vectors/join.json`'s `mode_fetch` has 4 payloads with keys 16 and 17 and 6 that must be refused.
