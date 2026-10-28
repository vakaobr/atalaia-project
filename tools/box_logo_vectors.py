#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Writes protocol/vectors/box_logo.json: PNG logos and the SHA-256 of their box-ready bytes (decision PKG-1).

    python tools/box_logo_vectors.py

The PNG files are made here by hand (every colour type and depth, Adam7, a tRNS key, all five scanline
filters); the answer is controller/atalaia_controller/box_logo.py's. controller/tests/test_box_logo.py and the
Dart controller's test (app/test/controller/controller_box_logo_test.dart) convert each file and compare.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "controller"))
from atalaia_controller import box_logo  # noqa: E402

SAMPLES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def filtered(rows: list[bytes], bpp: int) -> bytes:
    out = bytearray()
    prev = bytes(len(rows[0]))
    for n, row in enumerate(rows):
        f = n % 5
        out.append(f)
        for i, x in enumerate(row):
            left = row[i - bpp] if i >= bpp else 0
            up = prev[i]
            ul = prev[i - bpp] if i >= bpp else 0
            pred = (0, left, up, (left + up) >> 1, paeth(left, up, ul))[f]
            out.append((x - pred) & 255)
        prev = row
    return bytes(out)


def pack_row(vals: list[int], depth: int) -> bytes:
    """Samples (already one per entry) into a scanline at depth bits each."""
    if depth == 8:
        return bytes(vals)
    if depth == 16:
        return b"".join(struct.pack(">H", v) for v in vals)
    out = bytearray((len(vals) * depth + 7) // 8)
    for i, v in enumerate(vals):
        bit = i * depth
        out[bit >> 3] |= v << (8 - depth - (bit & 7))
    return bytes(out)


def make_png(width: int, height: int, depth: int, colour: int, pixel, *, interlace: int = 0,
             plte: bytes = b"", trns: bytes = b"") -> bytes:
    """pixel(x, y) -> the samples of that pixel (a tuple of ints at the PNG's depth)."""
    samples = SAMPLES[colour]
    bpp = max(1, depth * samples // 8)
    passes = [(0, 0, 1, 1)] if interlace == 0 else ADAM7
    raw = b""
    for x0, y0, dx, dy in passes:
        xs = range(x0, width, dx)
        ys = range(y0, height, dy)
        if not len(xs) or not len(ys):
            continue
        rows = [pack_row([s for x in xs for s in pixel(x, y)], depth) for y in ys]
        raw += filtered(rows, bpp)
    body = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", body)
    if plte:
        out += chunk(b"PLTE", plte)
    if trns:
        out += chunk(b"tRNS", trns)
    return out + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def cases() -> list[tuple[str, str, bytes]]:
    out = []
    out.append(("rgba8_square", "8-bit RGBA, 40x40, soft alpha ramp, the five filters",
                make_png(40, 40, 8, 6, lambda x, y: (x * 6, y * 6, 200 - x * 3, min(255, x * 7 + y * 2)))))
    out.append(("palette4_trns_wide", "4-bit palette with tRNS, 60x20 (fitted by width, centred in height)",
                make_png(60, 20, 4, 3, lambda x, y: ((x // 4 + y // 5) % 6,),
                         plte=bytes(v for i in range(6) for v in (i * 40, 255 - i * 40, (i * 97) % 256)),
                         trns=bytes((255, 128, 0, 255, 64, 255)))))
    out.append(("gray16_tall", "16-bit gray, 100x130 (fitted by height, downscaled)",
                make_png(100, 130, 16, 0, lambda x, y: (((x * 655 + y * 301) % 65536),))))
    out.append(("graya8_adam7", "8-bit gray with alpha, Adam7, 50x30",
                make_png(50, 30, 8, 4, lambda x, y: ((x * 5) % 256, 255 if (x + y) % 7 else 0), interlace=1)))
    out.append(("gray1_key", "1-bit gray with a tRNS colour key (white is transparent), 24x24",
                make_png(24, 24, 1, 0, lambda x, y: (1 if (x // 3 + y // 3) % 2 else 0,), trns=b"\x00\x01")))
    out.append(("rgb16_adam7", "16-bit RGB, Adam7, 200x120",
                make_png(200, 120, 16, 2, lambda x, y: (x * 300 % 65536, y * 500 % 65536, (x ^ y) * 700 % 65536),
                         interlace=1)))
    out.append(("rgb8_key_small", "8-bit RGB with a tRNS key (black), 16x16: upscaled",
                make_png(16, 16, 8, 2, lambda x, y: (0, 0, 0) if (x + y) % 5 == 0 else (230, 40 + x * 10, 60 + y * 9),
                         trns=b"\x00\x00\x00\x00\x00\x00")))
    return out


def main() -> None:
    items = []
    for name, note, png in cases():
        box = box_logo.convert(png)
        items.append({"name": name, "note": note, "png_b64": base64.b64encode(png).decode(),
                      "png_sha256": hashlib.sha256(png).hexdigest(), "box_bytes": len(box),
                      "box_head": box[:16].hex(), "box_sha256": hashlib.sha256(box).hexdigest()})
    doc = {
        "description": "PNG logos and the SHA-256 of the 96x96 RGB565 bytes a Field Box draws (decision PKG-1; "
                       "protocol/mode-packages.md, section 8). Made by tools/box_logo_vectors.py; checked by "
                       "controller/tests/test_box_logo.py and app/test/controller/controller_box_logo_test.dart.",
        "side": box_logo.SIDE, "bytes": box_logo.SIZE,
        "background": "%02x%02x%02x" % box_logo.BG,
        "release_text": box_logo.release_text("ab" * 32, b"\x01\x02\x03"),
        "cases": items,
    }
    (ROOT / "protocol" / "vectors" / "box_logo.json").write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"{len(items)} cases")


if __name__ == "__main__":
    main()
