# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Skirmesh-RF packet codec: header, nonce, AAD, and message payloads.

Encodes and decodes the on-air packet format used between field nodes.
The header is a fixed 9-byte big-endian structure.  AES-128-CCM with an
8-byte MIC provides authenticated encryption; the ``cryptography``
library is an optional dependency -- importing this module never fails,
but :func:`aes_ccm_encrypt` and :func:`aes_ccm_decrypt` raise
:exc:`ImportError` when the library is absent.

Payload codecs for every message type convert between Python dicts with
string keys and CBOR bytes with compact integer keys.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any, Optional

from . import cbor
from .protocol import MESSAGE_TYPES

# --- constants ----------------------------------------------------------------

HEADER_SIZE = 9
MIC_SIZE = 8
PAYLOAD_MAX = 200
NONCE_SIZE = 13
KEY_SIZE = 16
AAD_SIZE = 8

# version_flags bit layout:  VVV PP A E x
#   V = version (3 bits, bits 7-5)
#   P = priority (2 bits, bits 4-3)
#   A = ack requested (1 bit, bit 2)
#   E = encrypted (1 bit, bit 1)
#   x = reserved (1 bit, bit 0)

# --- integer-key tables for payload codecs ------------------------------------

# Integer-key tables derived from the generated PAYLOAD_FIELDS in protocol.py.
from .protocol import PAYLOAD_FIELDS as _PF

def _key_table(msg: str) -> dict[str, int]:
    """Build a {field_name: cbor_key} mapping from PAYLOAD_FIELDS."""
    return {name: pf.key for name, pf in _PF[msg].items()}

_HELLO_KEYS = _key_table("HELLO")
_ACK_KEYS = _key_table("ACK")
_STATE_KEYS = _key_table("STATE")
_CMD_KEYS = _key_table("CMD")
_TIME_KEYS = _key_table("TIME")
_CONFIG_KEYS = _key_table("CONFIG")
_CLAIM_KEYS = _key_table("CLAIM")

_ALL_KEY_TABLES: dict[str, dict[str, int]] = {
    msg.lower(): _key_table(msg) for msg in _PF
}


# --- Header dataclass ---------------------------------------------------------


@dataclass
class Header:
    """Fixed 9-byte packet header."""

    version_flags: int  # 1 byte: version(3) | prio(2) | ack(1) | enc(1) | reserved(1)
    game_id: int        # 2 bytes, big-endian
    source: int         # 2 bytes, big-endian
    seq: int            # 2 bytes, big-endian
    hop_limit: int      # 1 byte
    type: int           # 1 byte (MESSAGE_TYPES value)


# --- version_flags helpers ----------------------------------------------------


def vf_make(version: int, prio: int, ack: bool, enc: bool) -> int:
    """Build a version_flags byte from its components."""
    return ((version & 0x07) << 5) | ((prio & 0x03) << 3) | (int(ack) << 2) | (int(enc) << 1)


def vf_version(vf: int) -> int:
    """Extract the 3-bit protocol version."""
    return (vf >> 5) & 0x07


def vf_prio(vf: int) -> int:
    """Extract the 2-bit priority."""
    return (vf >> 3) & 0x03


def vf_ack(vf: int) -> bool:
    """True when the ACK-requested flag is set."""
    return bool((vf >> 2) & 1)


def vf_enc(vf: int) -> bool:
    """True when the encrypted flag is set."""
    return bool((vf >> 1) & 1)


# --- header encode/decode ----------------------------------------------------


def header_encode(hdr: Header) -> bytes:
    """Encode a Header into 9 bytes (big-endian)."""
    return struct.pack(
        ">BHHHBB",
        hdr.version_flags & 0xFF,
        hdr.game_id & 0xFFFF,
        hdr.source & 0xFFFF,
        hdr.seq & 0xFFFF,
        hdr.hop_limit & 0xFF,
        hdr.type & 0xFF,
    )


def header_decode(data: bytes) -> Header:
    """Decode 9 bytes into a Header."""
    if len(data) < HEADER_SIZE:
        raise ValueError(f"header needs {HEADER_SIZE} bytes, got {len(data)}")
    vf, gid, src, seq, hop, typ = struct.unpack(">BHHHBB", data[:HEADER_SIZE])
    return Header(
        version_flags=vf,
        game_id=gid,
        source=src,
        seq=seq,
        hop_limit=hop,
        type=typ,
    )


# --- nonce and AAD ------------------------------------------------------------


def nonce_build(hdr: Header, epoch: int) -> bytes:
    """Build the 13-byte AES-CCM nonce.

    Layout: game_id(2 BE) | source(2 BE) | ((epoch << 16) | seq)(4 BE) | zeros(5).
    """
    combined = ((epoch & 0xFFFF) << 16) | (hdr.seq & 0xFFFF)
    return struct.pack(">HHI", hdr.game_id, hdr.source, combined) + b"\x00" * 5


def aad_extract(header_bytes: bytes) -> bytes:
    """Extract the 8-byte AAD from a raw header: bytes 0-6 + byte 8 (skip hop_limit)."""
    if len(header_bytes) < HEADER_SIZE:
        raise ValueError(f"header needs {HEADER_SIZE} bytes, got {len(header_bytes)}")
    return header_bytes[0:7] + header_bytes[8:9]


# --- AES-CCM (optional cryptography dependency) -------------------------------


def _get_aesccm():
    """Import AESCCM from the cryptography library, or raise ImportError."""
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESCCM
        return AESCCM
    except ImportError:
        raise ImportError(
            "AES-CCM operations require the 'cryptography' package. "
            "Install it with: pip install cryptography>=41.0"
        ) from None


def aes_ccm_encrypt(
    key: bytes, nonce: bytes, aad: bytes, plaintext: bytes
) -> tuple[bytes, bytes]:
    """Encrypt with AES-128-CCM and return (ciphertext, tag).

    The tag is always 8 bytes.  Requires the ``cryptography`` library.
    """
    AESCCM = _get_aesccm()
    cipher = AESCCM(key, tag_length=MIC_SIZE)
    ct_and_tag = cipher.encrypt(nonce, plaintext, aad)
    # cryptography appends the tag to the ciphertext
    ciphertext = ct_and_tag[:-MIC_SIZE]
    tag = ct_and_tag[-MIC_SIZE:]
    return ciphertext, tag


def aes_ccm_decrypt(
    key: bytes, nonce: bytes, aad: bytes, ciphertext: bytes, tag: bytes
) -> bytes:
    """Decrypt with AES-128-CCM and verify the tag.

    Raises ``cryptography.exceptions.InvalidTag`` on failure.
    """
    AESCCM = _get_aesccm()
    cipher = AESCCM(key, tag_length=MIC_SIZE)
    return cipher.decrypt(nonce, ciphertext + tag, aad)


# --- full packet encode/decode ------------------------------------------------


def packet_encrypt(
    hdr: Header, epoch: int, key: bytes, payload: bytes
) -> bytes:
    """Encode a full packet: header(9) + ciphertext + MIC(8).

    The encrypted flag in the header is set automatically.
    """
    hdr.version_flags = hdr.version_flags | 0x02  # set enc bit
    raw_hdr = header_encode(hdr)
    nonce = nonce_build(hdr, epoch)
    aad = aad_extract(raw_hdr)
    ciphertext, tag = aes_ccm_encrypt(key, nonce, aad, payload)
    return raw_hdr + ciphertext + tag


def packet_decrypt(
    data: bytes, epoch: int, key: bytes
) -> tuple[Header, bytes]:
    """Decode a full packet: returns (header, plaintext payload)."""
    if len(data) < HEADER_SIZE + MIC_SIZE:
        raise ValueError(
            f"packet too short: {len(data)} bytes "
            f"(minimum {HEADER_SIZE + MIC_SIZE})"
        )
    raw_hdr = data[:HEADER_SIZE]
    hdr = header_decode(raw_hdr)
    ct_and_tag = data[HEADER_SIZE:]
    ciphertext = ct_and_tag[:-MIC_SIZE]
    tag = ct_and_tag[-MIC_SIZE:]
    nonce = nonce_build(hdr, epoch)
    aad = aad_extract(raw_hdr)
    plaintext = aes_ccm_decrypt(key, nonce, aad, ciphertext, tag)
    return hdr, plaintext


# --- payload codecs -----------------------------------------------------------


def _encode_payload(msg: dict[str, Any], key_table: dict[str, int]) -> bytes:
    """Encode a dict with string keys to CBOR with integer keys."""
    int_keyed: dict[int, Any] = {}
    for k, v in msg.items():
        int_key = key_table.get(k)
        if int_key is not None:
            int_keyed[int_key] = v
        else:
            # Pass through unknown keys as strings for extensibility
            int_keyed[k] = v  # type: ignore[assignment]
    return cbor.encode(int_keyed)


def _decode_payload(data: bytes, key_table: dict[str, int]) -> dict[str, Any]:
    """Decode CBOR with integer keys to a dict with string keys."""
    raw = cbor.decode(data, allow_bytes=True)
    if not isinstance(raw, dict):
        raise ValueError("payload must be a CBOR map")
    reverse: dict[int, str] = {v: k for k, v in key_table.items()}
    result: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(k, int) and k in reverse:
            result[reverse[k]] = v
        elif isinstance(k, str):
            result[k] = v
        else:
            result[str(k)] = v
    return result


# HELLO
def hello_encode(msg: dict[str, Any]) -> bytes:
    """Encode a HELLO payload."""
    return _encode_payload(msg, _HELLO_KEYS)


def hello_decode(data: bytes) -> dict[str, Any]:
    """Decode a HELLO payload."""
    return _decode_payload(data, _HELLO_KEYS)


# ACK
def ack_encode(msg: dict[str, Any]) -> bytes:
    """Encode an ACK payload."""
    return _encode_payload(msg, _ACK_KEYS)


def ack_decode(data: bytes) -> dict[str, Any]:
    """Decode an ACK payload."""
    return _decode_payload(data, _ACK_KEYS)


# STATE
def state_encode(msg: dict[str, Any]) -> bytes:
    """Encode a STATE payload."""
    return _encode_payload(msg, _STATE_KEYS)


def state_decode(data: bytes) -> dict[str, Any]:
    """Decode a STATE payload."""
    return _decode_payload(data, _STATE_KEYS)


# CMD
def cmd_encode(msg: dict[str, Any]) -> bytes:
    """Encode a CMD payload."""
    return _encode_payload(msg, _CMD_KEYS)


def cmd_decode(data: bytes) -> dict[str, Any]:
    """Decode a CMD payload."""
    return _decode_payload(data, _CMD_KEYS)


# TIME
def time_encode(msg: dict[str, Any]) -> bytes:
    """Encode a TIME payload."""
    return _encode_payload(msg, _TIME_KEYS)


def time_decode(data: bytes) -> dict[str, Any]:
    """Decode a TIME payload."""
    return _decode_payload(data, _TIME_KEYS)


# CONFIG
def config_encode(msg: dict[str, Any]) -> bytes:
    """Encode a CONFIG payload."""
    return _encode_payload(msg, _CONFIG_KEYS)


def config_decode(data: bytes) -> dict[str, Any]:
    """Decode a CONFIG payload."""
    return _decode_payload(data, _CONFIG_KEYS)


# CLAIM
def claim_encode(msg: dict[str, Any]) -> bytes:
    """Encode a CLAIM payload."""
    return _encode_payload(msg, _CLAIM_KEYS)


def claim_decode(data: bytes) -> dict[str, Any]:
    """Decode a CLAIM payload."""
    return _decode_payload(data, _CLAIM_KEYS)


# EVENT -- uses the existing codec module's CBOR format
def event_payload_encode(msg: dict[str, Any]) -> bytes:
    """Encode an EVENT payload (delegates to the event codec)."""
    from . import codec as _codec
    return _codec.encode_event(msg)


def event_payload_decode(data: bytes) -> dict[str, Any]:
    """Decode an EVENT payload (delegates to the event codec)."""
    from . import codec as _codec
    return _codec.decode_event(data)


# Convenience: dispatch by message type name
PAYLOAD_ENCODERS: dict[str, Any] = {
    "HELLO": hello_encode,
    "ACK": ack_encode,
    "STATE": state_encode,
    "CMD": cmd_encode,
    "TIME": time_encode,
    "CONFIG": config_encode,
    "CLAIM": claim_encode,
}

PAYLOAD_DECODERS: dict[str, Any] = {
    "HELLO": hello_decode,
    "ACK": ack_decode,
    "STATE": state_decode,
    "CMD": cmd_decode,
    "TIME": time_decode,
    "CONFIG": config_decode,
    "CLAIM": claim_decode,
}


# --- schema checks ------------------------------------------------------------

_UINT_MAX = {"uint8": 0xFF, "uint16": 0xFFFF, "uint32": 0xFFFFFFFF}


def _is_uint(value: Any, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= hi


def _type_problem(kind: str, value: Any, max_len: Optional[int]) -> Optional[str]:
    if kind in _UINT_MAX:
        return None if _is_uint(value, _UINT_MAX[kind]) else f"must be a {kind}"
    if kind == "int8":
        ok = isinstance(value, int) and not isinstance(value, bool) and -128 <= value <= 127
        return None if ok else "must be an int8"
    if kind == "text":
        if not isinstance(value, str):
            return "must be text"
        if max_len is not None and len(value.encode("utf-8")) > max_len:
            return f"longer than {max_len} bytes"
        return None
    if kind == "bytes":
        if not isinstance(value, (bytes, bytearray)):
            return "must be a byte string"
        if max_len is not None and len(value) > max_len:
            return f"longer than {max_len} bytes"
        return None
    if kind == "array_uint8":
        ok = isinstance(value, list) and all(_is_uint(v, 0xFF) for v in value)
        return None if ok else "must be an array of uint8"
    if kind == "array_text":
        ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
        return None if ok else "must be an array of text"
    if kind in ("map_u8_u32", "map_u16_u16"):
        khi, vhi = (0xFF, 0xFFFFFFFF) if kind == "map_u8_u32" else (0xFFFF, 0xFFFF)
        ok = isinstance(value, dict) and all(_is_uint(k, khi) and _is_uint(v, vhi)
                                             for k, v in value.items())
        return None if ok else f"must be a {kind} map"
    if kind == "map":
        ok = isinstance(value, dict) and all(isinstance(k, str) for k in value)
        return None if ok else "must be a map with text keys"
    return f"unknown field type {kind}"


def payload_problems(msg_type: str, fields: dict[str, Any]) -> list[str]:
    """What makes a decoded payload break protocol/schema/messages.yaml (empty if valid).

    The same rules the C decoders in core/src/msg_codec.c enforce: every
    required field present, every known field of its schema type and size.
    Unknown fields are allowed (newer senders may add optional ones).
    """
    problems = []
    schema = _PF[msg_type]
    for name, pf in schema.items():
        if name not in fields:
            if pf.required:
                problems.append(f"missing required field {name} (key {pf.key})")
            continue
        problem = _type_problem(pf.type, fields[name], pf.max)
        if problem:
            problems.append(f"{name} {problem}")
    return problems
