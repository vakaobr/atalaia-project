<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# RFC 0000: Mode packages, their signed manifest and the registry index

- **Author(s):** The Atalaia contributors (phase 5 plan phase 9)
- **Status:** Draft (2026-10-22): for discussion; the maintainer accepts it and gives it a number (decision P5G-12)
- **Discussion:** the pull request that adds this file

## Summary

Version 1 of how a community game mode travels: one canonical ustar archive of
the mode's files, a seven-line text manifest signed with Ed25519, a release
text and file next to the archive, a registry index listing signed versions and
a revocation list of keys; and the registry repository's rules built on them
(two signatures, the verified badge). All of it is built and tested (phase 5
plan phases 4, 6, 8 and 13a); this RFC records it as the project's commitment,
so that later changes follow ADR-P5-8's rule: a new index `schema_version`, a
new signing algorithm, a change to the approved licences or to the sandbox's
limits needs an RFC.

The normative text is [`protocol/mode-packages.md`](../../protocol/mode-packages.md)
(format and checks) and [`docs/community/registry.md`](../community/registry.md)
(the registry); the shared vectors are `protocol/vectors/mode_package.json`; the
JSON Schemas are `registry/schema/`. This RFC summarises them and gives the
reasons.

## Motivation

- **Fields** install community scenarios and field scripts on their
  controller, and (from plan phase 13) boxes fetch the community modes a game
  needs. Both must know exactly what they run and who vouches for it.
- **Implementers** (the Pi controller in Python, the Field Box in C, the
  Android controller in Dart) need one byte-exact format with known answers.
- **The registry** needs rules a CI can check, so that review is about the game
  and not the mechanics.

## Design

### The archive

A POSIX ustar archive of `mode.yaml`, `node.lua`, `field.lua` and `assets/...`
under one root folder named after the mode's id, in one canonical form (regular
files only, sorted by name, mode 0644, owner 0, time 0, no prefix field, two
zero blocks at the end and nothing after); at most 1 000 000 bytes and 64 files;
UTF-8 text without NUL. A reader parses strictly, packs what it read again and
refuses the archive unless the bytes are equal: no path traversal, links,
devices or hidden data, and one SHA-256 for the same files. Not compressed: a
box hashes it while streaming, with no decompressor (P5C-8).

### The manifest, the signature and the release

```
atalaia-mode-package-v1
id=<reverse-domain id, at most 63 bytes>
version=<MAJOR.MINOR.PATCH[-pre]>
kind=<mode|modifier|role|scenario>
min_tier=<reduced|full>
size=<bytes of the archive>
sha256=<64 lower-case hex digits of the archive>
```

UTF-8, a line feed after each line. The signature is Ed25519 (RFC 8032) over
exactly these bytes, standard base64 with padding. The **release text** is the
manifest followed by `signature=<base64>` and a line feed; the
`<archive>.release.json` beside an archive carries the same fields plus
`key_id` and `license`, which describe and are never trusted. A key's id is the
first 16 hex digits of the SHA-256 of its 32 public bytes. This is the firmware
releases' scheme (`protocol/firmware-update.md`, P5R-7), with the id, version,
kind and tier bound so a signature cannot be moved to another mode, an older
version or a box it was not meant for (P5B-10, P5C-9).

### Checking a package

In a fixed order, refusing at the first failure with a code: the release's
form (`bad_release`), the size limit (`too_big`), size and SHA-256
(`bad_hash`), a **trusted** key's signature (`no_key`, `bad_signature`), the key
not revoked (`revoked`), the canonical archive with the id as its root
(`bad_archive`, `mismatch`), its `mode.yaml` agreeing with the manifest and
naming an approved licence (`bad_manifest`, `mismatch`, `licence`). The verifier
decides with its own keys only (P5C-10, P5C-18; a box with keys built into its
firmware, P5B-9).

### The index and the revocation list

```json
{"schema_version": 1, "name": "...",
 "modes": [{"id": "...", "name": "...", "description": "...", "author": "...",
            "versions": [{"version": "...", "kind": "...", "min_tier": "...", "size": 0,
                          "sha256": "...", "signature": "...", "key_id": "...",
                          "license": "...", "url": "packages/<id>-<version>.tar",
                          "verified": true}]}]}
```

`url` is `https://...` or a path relative to the index (a field without
internet); never `http://` or `..`. Anything unexpected refuses the whole index
(P5C-11). `revoked.json` beside the index: `{"schema_version": 1, "keys":
[{"key_id", "reason"?, "date"?}]}`.

### The registry's rules

- **Two signatures** (P5G-2): every version is signed by its author's key; a
  version the project reviewed is also signed by the project's registry key over
  the same archive, and the index lists that signature with `verified: true`.
  The project's key is the one Field Boxes have built in, so the badge is what
  lets a mode reach boxes.
- The registry keeps every package it lists, next to its index, with the source
  of each mode's newest version; the source must pack to exactly the newest
  archive (P5G-1, P5G-5).
- A published version never changes; one id has one owner; ids starting
  `org.atalaia.` are the project's (P5G-6).
- Revoking a key removes or re-signs every version it signed, in the same
  change (P5G-7).

## Compatibility

This is version 1: `atalaia-mode-package-v1` in the manifest and
`schema_version: 1` in the index and the revocation list. A reader refuses any
other value, so a later version needs new readers before an index uses it: a
new manifest header or `schema_version` 2, with registries publishing both
until fields have moved. Unknown fields are refused rather than ignored (an
index is data from elsewhere), so adding a field is also a version change.
Firmware without plan phase 13 never fetches packages (join key 16 is skipped).

## Alternatives

- **gzip or zip archives** (ADR-P5-3's first design): a box would need a
  decompressor, and the same files could give many archives and hashes.
- **Signing the bare SHA-256** (ADR-P5-4's first design): a signature could be
  reused for another id or an older version.
- **SSH-style `SHA256:` fingerprints and `registry/tools/`**: a second scheme
  beside the firmware's; one set of tools and vectors instead.
- **Packages as GitHub Release assets**: the index's packages would live
  outside the reviewed pull request and could change after review; a mirror for
  an offline field would need every author's releases.
- **One signature (the author's) and a `verified` flag only**: a flag in an
  index is not something a box can check; the project's signature is.
- **The project signing everything, no author keys**: loses attribution, and
  every listing would need the project's key.

## Open questions

- Whether a field may add its own key to its boxes for its club's modes
  (P5B-9 says firmware-built keys only, for now).
- Whether the project's registry key should be held by more than one person,
  and how (P5G-3).
- A per-mode changelog or a minimum core version in the index (ADR-P5-3 had
  `min_core`): not in version 1.
