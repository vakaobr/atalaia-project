# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Small PNG files for the branding tests, made with the standard library (no image library in the image)."""

from __future__ import annotations

import struct
import zlib


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def png(width: int = 64, height: int = 64, rgb: tuple[int, int, int] = (200, 30, 30), text: bytes = b"") -> bytes:
    """An RGB PNG of one colour; ``text`` adds a tEXt chunk (metadata the checks strip)."""
    row = b"\x00" + bytes(rgb) * width
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    if text:
        out += chunk(b"tEXt", b"Comment\x00" + text)
    return out + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b"")
