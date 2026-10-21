<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->
# Monocypher (vendored)

The Field Box checks the Ed25519 signature of a firmware release before it installs it
(`main/fw_update.c`, `protocol/firmware-update.md`). ESP-IDF 5.3's mbedTLS has no Ed25519,
so the check uses [Monocypher](https://monocypher.org) 4.0.2 and its optional RFC 8032
Ed25519 part (`crypto_ed25519_check`, with its own SHA-512), unmodified.

| File | SHA-256 |
| --- | --- |
| `src/monocypher.c` | `afe2b098c8569577a84488e0b98d276d1fba6506adea68bb9241a52111734c59` |
| `src/monocypher.h` | `f78bb31255cfb7beba66afd2137f5194c8a025cf40488b6cc1e295234d43f374` |
| `src/optional/monocypher-ed25519.c` | `7c9b16056cbd27521919e8a6f56a228808b9e718afc42e3d33f28c08e5abdee2` |
| `src/optional/monocypher-ed25519.h` | `bd546edcd468d64e28caa3dbf4b1d6bfad7435c0ce994723fd81aae26405121b` |

They are the `src/` files of the official `monocypher-4.0.2.tar.gz` (SHA-512
`bf275d4c53ff94af6cdc723a4e002e9f080f4d1436c86c76bb37870b34807f1d7b32331d8ff8a1aeb369e946f3769021e03e63efac25b82efc5abf54dc084714`,
as published on monocypher.org; SHA-256 `38d07179738c0c90677dba3ceb7a7b8496bcfea758ba1a53e803fed30ae0879c`,
the same file as the GitHub release asset). `LICENCE.md` is the release's own.

Licence: CC0-1.0 or BSD-2-Clause, at the user's choice (`LICENCE.md`; REUSE.toml).

Why Monocypher (decision FU3-2): a small, single-file C99 library with no dependencies or
allocation, audited by Cure53 in 2020, used widely in embedded code, with RFC 8032 Ed25519
(SHA-512) in its optional part; it builds unchanged for the ESP32-S3 and for the host tests,
which check it against RFC 8032's own vectors. libsodium (an ESP-IDF registry component)
would also do, but is far larger, pulls its own build system and random number glue, and
is not needed for one signature check. TweetNaCl is slower and unmaintained.

To update: download the new release from <https://monocypher.org/download/>, check its
SHA-512 against the published one, replace the four files and `LICENCE.md`, update the
table above, and run `python3 tools/docker_fw.py test` and the firmware builds.
