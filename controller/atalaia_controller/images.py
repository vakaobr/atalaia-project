# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Uploaded branding images: checked and stripped of metadata, without an image library.

A field's logo and wallpaper and a team's crest (decisions BR1-BR24) are
PNG, JPEG or WebP. SVG is refused (it can carry scripts), and so is
anything else, whatever its Content-Type says: the type is taken from the
file's own signature and must match the declared one.

The controller has no image library (Pillow is not one of its dependencies
and its decoders are a large attack surface, decision BR7), so this module
reads each format's structure with the standard library:

- PNG: every chunk's length and CRC, a valid IHDR, the image data
  inflated with a cap and checked to be exactly as long as the IHDR says
  (so a truncated file or a decompression bomb is refused), IEND last and
  nothing after it; animated PNG (acTL) and unknown critical chunks are
  refused.
- JPEG: the segments up to the first scan, exactly one frame header with
  its size, the end-of-image marker; data after it is dropped.
- WebP: the RIFF size, the VP8, VP8L or VP8X header with its size;
  animation (the ANIM flag or ANIM/ANMF chunks) is refused.

Metadata is stripped by rewriting the container without it (no pixel is
re-encoded): PNG text, time and EXIF chunks and unknown ancillary chunks;
JPEG APP1 (EXIF, XMP), APP3-APP13 (IPTC, ...), APP15 and comments; WebP
EXIF and XMP chunks (and their VP8X flags). Colour profiles stay. The
pixels themselves are decoded only by the browsers and phones that show
the image, with their own decoders.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

PNG_SIG = b"\x89PNG\r\n\x1a\n"
TYPES = ("image/png", "image/jpeg", "image/webp")


class ImageError(ValueError):
    """An upload that cannot be accepted: ``status`` is the HTTP status (413, 415 or 422)."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Limits:
    """What one kind of image may be (decision BR6)."""

    kind: str
    max_bytes: int
    min_side: int
    max_side: int
    max_aspect: float  # the longer side over the shorter one


LOGO = Limits("logo", 1024 * 1024, 16, 2048, 8.0)
WALLPAPER = Limits("wallpaper", 4 * 1024 * 1024, 320, 4096, 8.0)
CREST = Limits("crest", 512 * 1024, 16, 1024, 4.0)
KINDS = {lim.kind: lim for lim in (LOGO, WALLPAPER, CREST)}


@dataclass(frozen=True)
class Checked:
    content_type: str
    width: int
    height: int
    data: bytes  # the stripped file, as stored and served


def sniff(data: bytes) -> str | None:
    """The image type of a file from its signature, or None."""
    if data.startswith(PNG_SIG):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def check(data: bytes, declared: str, limits: Limits) -> Checked:
    """The upload as it will be stored, or ImageError."""
    declared = (declared or "").split(";")[0].strip().lower()
    if len(data) > limits.max_bytes:
        raise ImageError(413, f"the {limits.kind} is over {limits.max_bytes} bytes")
    if not data:
        raise ImageError(422, "empty image")
    if declared not in TYPES:
        raise ImageError(415, f"the {limits.kind} must be PNG, JPEG or WebP (not {declared or 'untyped'}; "
                              "SVG is not accepted)")
    found = sniff(data)
    if found is None:
        raise ImageError(415, f"the {limits.kind} is not a PNG, JPEG or WebP file")
    if found != declared:
        raise ImageError(415, f"the file is {found}, not {declared} as declared")
    try:
        if found == "image/png":
            width, height, out = _png(data, limits)
        elif found == "image/jpeg":
            width, height, out = _jpeg(data)
        else:
            width, height, out = _webp(data)
    except (struct.error, IndexError, zlib.error) as exc:
        raise ImageError(422, f"the {limits.kind} is damaged ({exc.__class__.__name__})") from None
    lo, hi = min(width, height), max(width, height)
    if lo < limits.min_side or hi > limits.max_side:
        raise ImageError(422, f"the {limits.kind} is {width}x{height} pixels; each side must be "
                              f"{limits.min_side} to {limits.max_side}")
    if hi / lo > limits.max_aspect:
        raise ImageError(422, f"the {limits.kind} is {width}x{height} pixels; at most "
                              f"{limits.max_aspect:g} times as long as it is wide")
    return Checked(found, width, height, out)


# --- PNG ---------------------------------------------------------------------

# Ancillary chunks kept (colour and layout); everything else ancillary is dropped.
PNG_KEEP = {b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"bKGD", b"pHYs", b"cICP"}
PNG_CRITICAL = {b"IHDR", b"PLTE", b"IDAT", b"IEND"}
# Bit depths allowed per colour type, and samples per pixel.
PNG_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
PNG_SAMPLES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
# Adam7: (x start, y start, x step, y step) of each pass.
ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def _bad(message: str) -> ImageError:
    return ImageError(422, message)


def _png_raw_size(width: int, height: int, depth: int, ctype: int, interlace: int) -> int:
    bits = depth * PNG_SAMPLES[ctype]

    def rows(w: int, h: int) -> int:
        return 0 if w == 0 or h == 0 else h * (1 + (w * bits + 7) // 8)

    if interlace == 0:
        return rows(width, height)
    total = 0
    for x0, y0, dx, dy in ADAM7:
        total += rows((width - x0 + dx - 1) // dx if width > x0 else 0,
                      (height - y0 + dy - 1) // dy if height > y0 else 0)
    return total


def _png(data: bytes, limits: Limits) -> tuple[int, int, bytes]:
    pos = len(PNG_SIG)
    out = [PNG_SIG]
    header = None
    inflater = zlib.decompressobj()
    inflated = 0
    expected = 0
    seen_idat = idat_done = seen_end = False
    first = True
    while pos < len(data):
        if pos + 12 > len(data):
            raise _bad("the PNG ends inside a chunk")
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        if length > 0x7FFFFFFF or pos + 12 + length > len(data):
            raise _bad("a PNG chunk is longer than the file")
        body = data[pos + 8:pos + 8 + length]
        crc = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])[0]
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise _bad(f"the PNG chunk {ctype.decode('latin-1')!r} has a bad checksum")
        chunk = data[pos:pos + 12 + length]
        pos += 12 + length
        if not all(65 <= c <= 90 or 97 <= c <= 122 for c in ctype):
            raise _bad("a PNG chunk has an invalid name")
        if first:
            if ctype != b"IHDR" or length != 13:
                raise _bad("the PNG does not start with its header")
            width, height, depth, colour, comp, filt, interlace = struct.unpack(">IIBBBBB", body)
            if not (0 < width <= 0x7FFFFFFF and 0 < height <= 0x7FFFFFFF):
                raise _bad("the PNG has no size")
            if colour not in PNG_DEPTHS or depth not in PNG_DEPTHS[colour] or comp != 0 or filt != 0 \
                    or interlace not in (0, 1):
                raise _bad("the PNG header is invalid")
            header = (width, height, depth, colour, interlace)
            # Checked before inflating, so the size cap bounds the work.
            if max(width, height) > limits.max_side or min(width, height) < limits.min_side:
                raise _bad(f"the {limits.kind} is {width}x{height} pixels; each side must be "
                           f"{limits.min_side} to {limits.max_side}")
            expected = _png_raw_size(width, height, depth, colour, interlace)
            first = False
            out.append(chunk)
            continue
        if ctype == b"IHDR":
            raise _bad("the PNG has two headers")
        if ctype in (b"acTL", b"fcTL", b"fdAT"):
            raise _bad("animated PNG is not accepted")
        if ctype == b"IDAT":
            if idat_done:
                raise _bad("the PNG's image data is split")
            seen_idat = True
            pending = body
            while pending:  # 1 MB of pixels at a time: the inflated data is counted, not kept
                piece = inflater.decompress(pending, min(expected + 1 - inflated, 1 << 20))
                inflated += len(piece)
                if inflated > expected:
                    raise _bad("the PNG's image data is larger than its size says")
                if not piece and pending == inflater.unconsumed_tail:
                    break
                pending = inflater.unconsumed_tail
            out.append(chunk)
            continue
        if seen_idat:
            idat_done = True
        if ctype == b"IEND":
            seen_end = True
            out.append(chunk)
            break
        if ctype == b"PLTE":
            if length == 0 or length % 3 or length > 768:
                raise _bad("the PNG palette is invalid")
            out.append(chunk)
            continue
        if ctype[0] < 97:  # an upper-case first letter: a critical chunk this checker does not know
            raise _bad(f"the PNG has an unknown critical chunk {ctype.decode('latin-1')!r}")
        if ctype in PNG_KEEP:
            out.append(chunk)
        # Anything else (tEXt, zTXt, iTXt, eXIf, tIME, private chunks) is metadata: dropped.
    if header is None or not seen_idat or not seen_end:
        raise _bad("the PNG is incomplete (no image data or no end)")
    if header[3] == 3 and not any(c[4:8] == b"PLTE" for c in out):
        raise _bad("the PNG has a palette colour type and no palette")
    inflated += len(inflater.flush(max(1, expected + 1 - inflated)))
    if not inflater.eof or inflated != expected:
        raise _bad("the PNG's image data is not as long as its size says")
    return header[0], header[1], b"".join(out)


# --- JPEG --------------------------------------------------------------------

# Frame headers: SOF0-SOF15 apart from DHT (C4), JPG (C8) and DAC (CC).
SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
# Application segments kept: APP0 (JFIF), APP2 (ICC profile), APP14 (Adobe colour transform).
JPEG_KEEP_APP = {0xE0, 0xE2, 0xEE}


def _jpeg(data: bytes) -> tuple[int, int, bytes]:
    out = [b"\xff\xd8"]
    pos = 2
    size = None
    while True:
        if pos + 4 > len(data):
            raise _bad("the JPEG ends before its image data")
        if data[pos] != 0xFF:
            raise _bad("the JPEG's segments are damaged")
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            raise _bad("the JPEG has a misplaced marker")
        length = struct.unpack(">H", data[pos + 2:pos + 4])[0]
        if length < 2 or pos + 2 + length > len(data):
            raise _bad("a JPEG segment is longer than the file")
        seg = data[pos:pos + 2 + length]
        body = data[pos + 4:pos + 2 + length]
        pos += 2 + length
        if marker in SOF:
            if size is not None:
                raise _bad("the JPEG has two frames")
            if len(body) < 6:
                raise _bad("the JPEG frame header is short")
            _precision, height, width, comps = struct.unpack(">BHHB", body[:6])
            if width == 0 or height == 0 or comps not in (1, 3, 4) or len(body) != 6 + 3 * comps:
                raise _bad("the JPEG frame header is invalid")
            size = (width, height)
            out.append(seg)
        elif marker == 0xDA:  # start of scan: image data, more tables and scans, then the end
            if size is None:
                raise _bad("the JPEG has no frame header before its image data")
            out.append(seg)
            _jpeg_scans(data, pos, out)
            return size[0], size[1], b"".join(out)  # anything after the end marker is dropped
        elif 0xE0 <= marker <= 0xEF:
            if marker in JPEG_KEEP_APP:
                out.append(seg)
            # APP1 (EXIF, XMP), APP13 (IPTC) and the other application segments: dropped.
        elif marker == 0xFE:
            pass  # a comment: dropped
        else:
            out.append(seg)  # tables (DQT, DHT, DRI, ...)


def _jpeg_scans(data: bytes, pos: int, out: list[bytes]) -> int:
    """Copies the entropy-coded data from pos to the end marker into out (dropping comments and
    application segments between scans); returns the end marker's position."""
    start = pos
    while True:
        i = data.find(b"\xff", pos)
        if i < 0 or i + 1 >= len(data):
            raise _bad("the JPEG has no end")
        marker = data[i + 1]
        if marker == 0x00 or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            pos = i + 1 if marker == 0xFF else i + 2  # stuffed byte, restart marker, fill byte
            continue
        out.append(data[start:i])
        if marker == 0xD9:
            out.append(b"\xff\xd9")
            return i
        if marker in (0xD8, 0x01) or marker in SOF:
            raise _bad("the JPEG has a misplaced marker in its image data")
        if i + 4 > len(data):
            raise _bad("the JPEG ends inside a segment")
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if length < 2 or i + 2 + length > len(data):
            raise _bad("a JPEG segment is longer than the file")
        if not (0xE0 <= marker <= 0xEF or marker == 0xFE) or marker in JPEG_KEEP_APP:
            out.append(data[i:i + 2 + length])  # tables and the next scan's header
        pos = start = i + 2 + length


# --- WebP --------------------------------------------------------------------

VP8X_EXIF = 0x08
VP8X_XMP = 0x04
VP8X_ANIM = 0x02


def _webp(data: bytes) -> tuple[int, int, bytes]:
    riff = struct.unpack("<I", data[4:8])[0]
    if riff + 8 != len(data) and riff + 8 + 1 != len(data):
        raise _bad("the WebP file's size does not match its header")
    pos = 12
    chunks: list[tuple[bytes, bytes]] = []
    while pos < riff + 8:
        if pos + 8 > len(data):
            raise _bad("the WebP ends inside a chunk")
        fourcc, length = struct.unpack("<4sI", data[pos:pos + 8])
        if pos + 8 + length > len(data):
            raise _bad("a WebP chunk is longer than the file")
        chunks.append((fourcc, data[pos + 8:pos + 8 + length]))
        pos += 8 + length + (length & 1)
    if not chunks:
        raise _bad("the WebP has no image")
    first, body = chunks[0]
    if any(c[0] in (b"ANIM", b"ANMF") for c in chunks):
        raise _bad("animated WebP is not accepted")
    if first == b"VP8 ":
        width, height = _vp8(body)
        kept = [chunks[0]]
    elif first == b"VP8L":
        width, height = _vp8l(body)
        kept = [chunks[0]]
    elif first == b"VP8X":
        if len(body) < 10:
            raise _bad("the WebP extended header is short")
        flags = body[0]
        if flags & VP8X_ANIM:
            raise _bad("animated WebP is not accepted")
        width = 1 + int.from_bytes(body[4:7], "little")
        height = 1 + int.from_bytes(body[7:10], "little")
        frames = [c for c in chunks if c[0] in (b"VP8 ", b"VP8L")]
        if len(frames) != 1:
            raise _bad("the WebP must hold exactly one image")
        fw, fh = _vp8(frames[0][1]) if frames[0][0] == b"VP8 " else _vp8l(frames[0][1])
        if (fw, fh) != (width, height):
            raise _bad("the WebP image does not fill its canvas")
        header = bytes([flags & ~(VP8X_EXIF | VP8X_XMP)]) + body[1:]
        kept = [(b"VP8X", header)] + [c for c in chunks[1:] if c[0] in (b"ICCP", b"ALPH", b"VP8 ", b"VP8L")]
    else:
        raise _bad("the WebP has no image header")
    payload = b"".join(fourcc + struct.pack("<I", len(b)) + b + (b"\x00" if len(b) & 1 else b"")
                       for fourcc, b in kept)
    return width, height, b"RIFF" + struct.pack("<I", 4 + len(payload)) + b"WEBP" + payload


def _vp8(body: bytes) -> tuple[int, int]:
    if len(body) < 10 or body[3:6] != b"\x9d\x01\x2a" or body[0] & 1:
        raise _bad("the WebP's VP8 image is not a key frame")
    width, height = struct.unpack("<HH", body[6:10])
    return width & 0x3FFF, height & 0x3FFF


def _vp8l(body: bytes) -> tuple[int, int]:
    if len(body) < 5 or body[0] != 0x2F:
        raise _bad("the WebP's lossless image header is invalid")
    bits = int.from_bytes(body[1:5], "little")
    if bits >> 29:  # version must be 0
        raise _bad("the WebP's lossless image has an unknown version")
    return 1 + (bits & 0x3FFF), 1 + ((bits >> 14) & 0x3FFF)
