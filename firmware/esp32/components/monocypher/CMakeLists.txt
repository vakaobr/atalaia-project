# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Monocypher 4.0.2 (vendored, unmodified; README.md): the Field Box verifies
# firmware release signatures (Ed25519, RFC 8032) with its optional
# monocypher-ed25519 part. The linker keeps only what that check uses.

idf_component_register(
    SRCS
        "src/monocypher.c"
        "src/optional/monocypher-ed25519.c"
    INCLUDE_DIRS
        "src"
        "src/optional"
)
