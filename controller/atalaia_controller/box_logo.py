# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field's logo in the form a Field Box draws (decision PKG-1; protocol/mode-packages.md, section 8).

The box has no PNG or JPEG decoder (its image is nearly full), so the controller prepares the logo:
the field's PNG logo is decoded with the standard library, fitted into 96x96 pixels (area average, whole
integers, alpha composited on the box's screen colour #101418), and written as RGB565:

    "ALG1"  u16le width (96)  u16le height (96)  96 x 96 pixels, each a little-endian RGB565 word

18,440 bytes. Only PNG is converted: the controller has no JPEG or WebP decoder (decision BR7), so a field whose
logo is one of those keeps the Atalaia logo on its boxes (the box asks, and is told there is none). The Dart
controller (app/lib/controller/controller_box_logo.dart) does the same sums on whole integers, so both give the
same bytes; protocol/vectors/box_logo.json holds the PNG files and the SHA-256 of the result.
"""

from __future__ import annotations

import hashlib
import struct
import zlib

SIDE = 96
MAGIC = b"ALG1"
HEADER = 8
SIZE = HEADER + SIDE * SIDE * 2  # 18,440
BG = (0x10, 0x14, 0x18)  # the box's screen colour (COLOR_BG in screen_renderer.c)
MAX_PIXELS = 1 << 20  # larger logos are not converted (the work is bounded)
PNG_SIG = b"\x89PNG\r\n\x1a\n"
SAMPLES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


class BoxLogoError(ValueError):
    """The logo cannot be made box-ready (not a PNG, too large to convert, damaged)."""


def release_text(image_id: str, data: bytes) -> str:
    """What the box asks first: the source image's id, and the SHA-256 and size of the bytes to come."""
    return ("atalaia-box-logo-v1\n"
            f"id={image_id}\n"
            f"sha256={hashlib.sha256(data).hexdigest()}\n"
            f"bytes={len(data)}\n")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def _unfilter(raw: bytes, pos: int, rows: int, stride: int, bpp: int) -> tuple[list[bytearray], int]:
    out: list[bytearray] = []
    prev = bytearray(stride)
    for _ in range(rows):
        ftype = raw[pos]
        line = bytearray(raw[pos + 1:pos + 1 + stride])
        pos += 1 + stride
        if ftype == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif ftype == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif ftype == 3:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif ftype == 4:
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                up_left = prev[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + _paeth(left, prev[i], up_left)) & 255
        elif ftype != 0:
            raise BoxLogoError("the PNG has an unknown filter")
        out.append(line)
        prev = line
    return out, pos


def decode_png(data: bytes) -> tuple[int, int, bytearray]:
    """The PNG as width, height and 8-bit RGBA (4 bytes a pixel)."""
    if not data.startswith(PNG_SIG):
        raise BoxLogoError("not a PNG")
    pos = len(PNG_SIG)
    header = None
    palette = b""
    trns = b""
    idat = bytearray()
    try:
        while pos + 12 <= len(data):
            length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
            body = data[pos + 8:pos + 8 + length]
            pos += 12 + length
            if ctype == b"IHDR":
                header = struct.unpack(">IIBBBBB", body)
            elif ctype == b"PLTE":
                palette = body
            elif ctype == b"tRNS":
                trns = body
            elif ctype == b"IDAT":
                idat += body
            elif ctype == b"IEND":
                break
        if header is None:
            raise BoxLogoError("the PNG has no header")
        width, height, depth, colour, _, _, interlace = header
        if width * height > MAX_PIXELS:
            raise BoxLogoError(f"the logo is {width}x{height} pixels; boxes get logos up to {MAX_PIXELS} pixels")
        raw = zlib.decompress(bytes(idat))
    except (struct.error, zlib.error) as exc:
        raise BoxLogoError(f"the PNG is damaged ({exc.__class__.__name__})") from None
    samples = SAMPLES[colour]
    bits = depth * samples
    bpp = max(1, bits // 8)
    rgba = bytearray(width * height * 4)
    # The colour a gray or truecolour PNG's tRNS makes transparent, at the PNG's own depth.
    key = tuple(struct.unpack(f">{len(trns) // 2}H", trns)) if colour in (0, 2) and trns else None
    top = (1 << depth) - 1
    passes = [(0, 0, 1, 1)] if interlace == 0 else ADAM7
    pos = 0
    try:
        for x0, y0, dx, dy in passes:
            pw = (width - x0 + dx - 1) // dx if width > x0 else 0
            ph = (height - y0 + dy - 1) // dy if height > y0 else 0
            if pw == 0 or ph == 0:
                continue
            stride = (pw * bits + 7) // 8
            lines, pos = _unfilter(raw, pos, ph, stride, bpp)
            for ry, line in enumerate(lines):
                y = y0 + ry * dy
                for rx in range(pw):
                    vals = _samples(line, rx, depth, samples)
                    r, g, b, a = _rgba(vals, colour, depth, top, palette, trns, key)
                    o = (y * width + x0 + rx * dx) * 4
                    rgba[o:o + 4] = bytes((r, g, b, a))
    except IndexError:
        raise BoxLogoError("the PNG's image data is short") from None
    return width, height, rgba


def _samples(line: bytearray, index: int, depth: int, samples: int) -> tuple[int, ...]:
    if depth == 8:
        return tuple(line[index * samples:(index + 1) * samples])
    if depth == 16:
        base = index * samples * 2
        return tuple((line[base + 2 * k] << 8) | line[base + 2 * k + 1] for k in range(samples))
    bit = index * depth  # 1, 2 or 4 bits: one sample a pixel
    return ((line[bit >> 3] >> (8 - depth - (bit & 7))) & ((1 << depth) - 1),)


def _to8(v: int, depth: int, top: int) -> int:
    if depth == 8:
        return v
    if depth == 16:
        return v >> 8
    return v * 255 // top


def _rgba(vals: tuple[int, ...], colour: int, depth: int, top: int, palette: bytes, trns: bytes,
          key: tuple[int, ...] | None) -> tuple[int, int, int, int]:
    if colour == 3:
        i = vals[0]
        a = trns[i] if i < len(trns) else 255
        return palette[3 * i], palette[3 * i + 1], palette[3 * i + 2], a
    if colour == 0:
        g = _to8(vals[0], depth, top)
        return g, g, g, 0 if key and vals[0] == key[0] else 255
    if colour == 4:
        g = _to8(vals[0], depth, top)
        return g, g, g, _to8(vals[1], depth, top)
    r, g, b = (_to8(v, depth, top) for v in vals[:3])
    if colour == 6:
        return r, g, b, _to8(vals[3], depth, top)
    return r, g, b, 0 if key and tuple(vals[:3]) == key else 255


def convert(png: bytes) -> bytes:
    """The box-ready bytes of a PNG logo (SIZE bytes), or BoxLogoError."""
    width, height, rgba = decode_png(png)
    if width >= height:
        tw, th = SIDE, max(1, (height * SIDE + width // 2) // width)
    else:
        tw, th = max(1, (width * SIDE + height // 2) // height), SIDE
    ox, oy = (SIDE - tw) // 2, (SIDE - th) // 2
    out = bytearray(SIZE)
    out[0:4] = MAGIC
    struct.pack_into("<HH", out, 4, SIDE, SIDE)
    bg565 = ((BG[0] >> 3) << 11) | ((BG[1] >> 2) << 5) | (BG[2] >> 3)
    for i in range(SIDE * SIDE):
        struct.pack_into("<H", out, HEADER + 2 * i, bg565)
    for dy in range(th):
        y0 = dy * height // th
        y1 = max(y0 + 1, (dy + 1) * height // th)
        for dx in range(tw):
            x0 = dx * width // tw
            x1 = max(x0 + 1, (dx + 1) * width // tw)
            n = (x1 - x0) * (y1 - y0)
            sa = sr = sg = sb = 0
            for y in range(y0, y1):
                o = (y * width + x0) * 4
                for _ in range(x0, x1):
                    a = rgba[o + 3]
                    sa += a
                    sr += rgba[o] * a
                    sg += rgba[o + 1] * a
                    sb += rgba[o + 2] * a
                    o += 4
            full = 255 * n
            back = full - sa
            half = full // 2
            r = (sr + BG[0] * back + half) // full
            g = (sg + BG[1] * back + half) // full
            b = (sb + BG[2] * back + half) // full
            struct.pack_into("<H", out, HEADER + 2 * ((oy + dy) * SIDE + ox + dx),
                             ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3))
    return bytes(out)
