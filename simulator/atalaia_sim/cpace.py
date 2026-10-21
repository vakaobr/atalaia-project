# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""CPace, CPACE-X25519-SHA512 (draft-irtf-cfrg-cpace-14): Python side of firmware/esp32/main/cpace.c.

The pairing code's key exchange (protocol/adoption.md section 7, decision AD-10).
X25519 is the cryptography library's (its exchange() is the Montgomery ladder on
any u-coordinate, with RFC 7748's clamping); Elligator 2 on Curve25519 is the
map of RFC 9380 section 6.7.1 (Z = 2), in integer arithmetic below; SHA-512 is
hashlib's. Both codecs check the draft's Appendix B.1 vectors
(protocol/vectors/pairing.json).

The initiator (A) is the field controller, the responder (B) the box; the ISK
is computed with the initiator-responder transcript.
"""

from __future__ import annotations

import hashlib

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

P = 2**255 - 19
A = 486662
DSI = b"CPace255"
DSI_ISK = b"CPace255_ISK"
S_IN_BYTES = 128  # SHA-512's input block
FIELD_SIZE = 32


class CpaceError(ValueError):
    """An abort: a peer's point gave the neutral element."""


def prepend_len(data: bytes) -> bytes:
    """The draft's prepend_len: the length as LEB128, then the bytes."""
    n = len(data)
    out = bytearray()
    while True:
        if n < 128:
            out.append(n)
            break
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out) + data


def lv_cat(*parts: bytes) -> bytes:
    return b"".join(prepend_len(p) for p in parts)


def generator_string(prs: bytes, ci: bytes, sid: bytes) -> bytes:
    zpad = max(0, S_IN_BYTES - len(prepend_len(prs)) - len(prepend_len(DSI)) - 1)
    return lv_cat(DSI, prs, b"\x00" * zpad, ci, sid)


def _elligator2(r: int) -> int:
    """map_to_curve_elligator2 for curve25519 (RFC 9380 6.7.1), the u-coordinate only."""
    x1 = (-A * pow(1 + 2 * r * r, P - 2, P)) % P
    gx1 = (x1 * x1 * x1 + A * x1 * x1 + x1) % P
    if pow(gx1, (P - 1) // 2, P) in (0, 1):
        return x1
    return (-x1 - A) % P


def calculate_generator(prs: bytes, ci: bytes, sid: bytes) -> bytes:
    """The generator g: Elligator 2 of the first 32 bytes of SHA-512(generator string)."""
    h = hashlib.sha512(generator_string(prs, ci, sid)).digest()[:FIELD_SIZE]
    r = (int.from_bytes(h, "little") & ((1 << 255) - 1)) % P
    return _elligator2(r).to_bytes(FIELD_SIZE, "little")


def scalar_mult(scalar: bytes, point: bytes) -> bytes:
    """X25519(scalar, point) with RFC 7748's clamping; all zeros for the neutral element."""
    try:
        return X25519PrivateKey.from_private_bytes(scalar).exchange(X25519PublicKey.from_public_bytes(point))
    except ValueError:  # the cryptography library refuses an all-zero shared secret
        return bytes(FIELD_SIZE)


def scalar_mult_vfy(scalar: bytes, point: bytes) -> bytes:
    """As scalar_mult; raises CpaceError for the neutral element (the abort case)."""
    out = scalar_mult(scalar, point)
    if out == bytes(FIELD_SIZE):
        raise CpaceError("the peer's point is of low order")
    return out


def isk_ir(sid: bytes, k: bytes, ya: bytes, ada: bytes, yb: bytes, adb: bytes) -> bytes:
    """ISK = SHA-512(lv_cat(DSI_ISK, sid, K) || transcript_ir(Ya, ADa, Yb, ADb))."""
    return hashlib.sha512(lv_cat(DSI_ISK, sid, k) + lv_cat(ya, ada) + lv_cat(yb, adb)).digest()
