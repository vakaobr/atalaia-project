<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# Signed mode packages

How a mode (a main mode, a modifier, a role package or a scenario) travels as one signed file, how a registry lists them, and how a field controller checks one before it installs it. Design: ADR-P5-3 and P5-4 as amended 2026-10-22 (`docs/phase-5-community/ADR.md`), decisions P5R-7, P5B-9, P5B-10 and P5C-8 onwards in `docs/review/decisions-to-review.md`. In software (phase 5 plan phases 4 and 6); boxes fetching signed packages from their controller is plan phase 13, not built.

Code: the shared Python `controller/atalaia_controller/mode_package.py` (the tool, the controller and, later, the registry's CI use it); the tool `tools/mode_package.py`; the controller's import `controller/atalaia_controller/signed_modes.py`; the vectors `protocol/vectors/mode_package.json` (made by `tools/mode_package_vectors.py`); the index's JSON Schemas `registry/schema/`.

## Trust

- A **mode key** (Ed25519, RFC 8032) signs each package; its id is the first 16 hex digits of the SHA-256 of its 32 public bytes, as a firmware release key's. The private half stays offline with whoever signs (`tools/mode_package.py keygen`, an encrypted PKCS#8 file outside the repository).
- **The controller decides with its own keys.** It installs a signed package only when one of the keys in its own configuration (`[modes] keys`) signed exactly the package's manifest, and that key is not revoked (`[modes] revoked`, and a registry's `revoked.json`). Nothing an index or a release file says about who signed it is trusted: the `key_id` beside a signature only tells "signed by a key I do not trust" (`no_key`) from "not signed" (`bad_signature`).
- **Boxes** (plan phase 13) will check the same signature with mode keys built into their firmware only (`CONFIG_ATALAIA_MODE_KEYS`; the maintainer's answer to P5B-9, 2026-10-22), never with keys a controller sends.
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

`tools/mode_package.py pack modes/domination` makes it from a mode folder (`tests/` and other files are left out and listed).

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

## Vectors

`protocol/vectors/mode_package.json`: RFC 8032's TEST 1 and 2 (copied from the RFC; TEST 1's key signs the vectors' releases, a public test key, never a mode key), the canonical archive of a small role package (also read back with Python's `tarfile`), 28 archives every reader refuses (path traversal, an absolute name, links, a folder, GNU and pax headers, the prefix field, a wrong checksum, an old GNU header, non-canonical times, modes, owners and order, a file twice, two roots, a file outside a root, a root that is not an id, a file the controller does not take, a hidden file, text that is not UTF-8 or has a NUL, data after the end, no end, a truncated file, a partial block, an empty archive), signed releases and copies changed after signing, whole checks with their result, release texts a reader refuses, and a valid and invalid indexes and revocation lists. `python3 tools/mode_package_vectors.py --check` (in `tools/check.sh` and CI) fails when the file is stale.
