# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The CBOR subset Skirmesh-RF uses (RFC 8949), with no dependencies.

Encodes integers, text, arrays, maps, booleans, null and floats. Integers
and lengths use the shortest form and floats the shortest of half, single
or double precision that keeps the value. Map entries keep their order.

The decoder rejects anything else: byte strings, tags, indefinite lengths,
undefined and other simple values, duplicate map keys, NaN and infinity,
containers nested more than MAX_DEPTH deep, and trailing bytes. It is the
same subset as the C codec in core/src/codec.c.
"""

from __future__ import annotations

import math
import struct
from typing import Any

# Arrays and maps nested inside each other. The event envelope plus the 16
# levels of event data the core's JSON allows.
MAX_DEPTH = 17


class CBORError(ValueError):
    pass


# ---- encoding --------------------------------------------------------------


def _head(major: int, value: int) -> bytes:
    if value < 24:
        return bytes([major << 5 | value])
    if value < 0x100:
        return bytes([major << 5 | 24, value])
    if value < 0x10000:
        return bytes([major << 5 | 25]) + value.to_bytes(2, "big")
    if value < 0x100000000:
        return bytes([major << 5 | 26]) + value.to_bytes(4, "big")
    return bytes([major << 5 | 27]) + value.to_bytes(8, "big")


def _float(x: float) -> bytes:
    if not math.isfinite(x):
        raise CBORError("NaN and infinity are not allowed")
    for fmt, ai in ((">e", 25), (">f", 26)):
        try:
            packed = struct.pack(fmt, x)
        except OverflowError:
            continue
        if struct.unpack(fmt, packed)[0] == x:
            return bytes([0xE0 | ai]) + packed
    return b"\xfb" + struct.pack(">d", x)


def encode_int(n: int) -> bytes:
    if n >= 0:
        if n >= 1 << 64:
            raise CBORError("integer out of range")
        return _head(0, n)
    if n < -(1 << 64):
        raise CBORError("integer out of range")
    return _head(1, -1 - n)


def encode_text(s: str) -> bytes:
    raw = s.encode("utf-8")
    return _head(3, len(raw)) + raw


def encode(value: Any, depth: int = 0) -> bytes:
    """depth is the number of containers around value."""
    if isinstance(value, (list, tuple, dict)) and depth >= MAX_DEPTH:
        raise CBORError(f"containers nested more than {MAX_DEPTH} deep")
    if value is None:
        return b"\xf6"
    if value is True:
        return b"\xf5"
    if value is False:
        return b"\xf4"
    if isinstance(value, int):
        return encode_int(value)
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, str):
        return encode_text(value)
    if isinstance(value, (list, tuple)):
        return _head(4, len(value)) + b"".join(encode(v, depth + 1) for v in value)
    if isinstance(value, dict):
        out = [_head(5, len(value))]
        for k, v in value.items():
            if not isinstance(k, (str, int)) or isinstance(k, bool):
                raise CBORError(f"map keys must be text or integers, not {type(k).__name__}")
            out.append(encode(k, depth + 1))
            out.append(encode(v, depth + 1))
        return b"".join(out)
    raise CBORError(f"cannot encode {type(value).__name__}")


# ---- decoding --------------------------------------------------------------


class Decoder:
    def __init__(self, data: bytes):
        self.data = bytes(data)
        self.pos = 0

    def _take(self, n: int) -> bytes:
        if n > len(self.data) - self.pos:
            raise CBORError("truncated")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def head(self) -> tuple[int, int, int]:
        """Returns (major type, additional info, value)."""
        initial = self._take(1)[0]
        major, ai = initial >> 5, initial & 0x1F
        if ai < 24:
            return major, ai, ai
        if ai <= 27:
            return major, ai, int.from_bytes(self._take(1 << (ai - 24)), "big")
        raise CBORError("indefinite lengths and reserved values are not allowed")

    def _count(self, n: int) -> int:
        if n > len(self.data) - self.pos:
            raise CBORError("truncated")  # every item needs at least one byte
        return n

    def value(self, depth: int = 0) -> Any:
        """depth is the number of containers around the value."""
        major, ai, n = self.head()
        if major in (4, 5) and depth >= MAX_DEPTH:
            raise CBORError(f"containers nested more than {MAX_DEPTH} deep")
        if major == 0:
            return n
        if major == 1:
            return -1 - n
        if major == 3:
            try:
                return self._take(n).decode("utf-8")
            except UnicodeDecodeError:
                raise CBORError("text is not valid UTF-8") from None
        if major == 4:
            return [self.value(depth + 1) for _ in range(self._count(n))]
        if major == 5:
            out: dict[Any, Any] = {}
            for _ in range(self._count(n)):
                k = self.value(depth + 1)
                if not isinstance(k, (str, int)) or isinstance(k, bool):
                    raise CBORError("map keys must be text or integers")
                if k in out:
                    raise CBORError(f"duplicate map key {k!r}")
                out[k] = self.value(depth + 1)
            return out
        if major == 7:
            if ai == 20:
                return False
            if ai == 21:
                return True
            if ai == 22:
                return None
            if ai in (25, 26, 27):
                fmt = {25: ">e", 26: ">f", 27: ">d"}[ai]
                x = struct.unpack(fmt, n.to_bytes(1 << (ai - 24), "big"))[0]
                if not math.isfinite(x):
                    raise CBORError("NaN and infinity are not allowed")
                return x
            raise CBORError("undefined and simple values are not allowed")
        raise CBORError("byte strings and tags are not allowed")

    def done(self) -> None:
        if self.pos != len(self.data):
            raise CBORError("trailing bytes")


def decode(data: bytes) -> Any:
    d = Decoder(data)
    value = d.value()
    d.done()
    return value
