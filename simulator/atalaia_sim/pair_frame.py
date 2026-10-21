# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Pair frames (protocol/adoption.md section 7, RFC 0001 Amendment 8): Python side of core/src/pair_frame.c.

Adopting a box over the radio with the 6-digit code it shows: message type 10
(PAIR), game id 0, hop_limit 0, never relayed, in the clear (the box holds no
key yet), the security coming from CPace (atalaia_sim.cpace) run with the code:

    header (9: version 1, not encrypted, game 0, source 0, seq 0, hop 0, type 10) | body (CBOR)

    OFFER   box -> controllers   pair id, name, tier            "a box shows a code"
    START   controller -> box    pair id, sid, Ya               CPace's first message
    REPLY   box -> controller    pair id, sid, Yb, tag_b        CPace's answer, the box's confirmation
    KEY     controller -> box    pair id, sid, tag_a, nonce, sealed (the join key and the field's name)
    DONE    box -> controller    pair id, sid, result, fingerprint, tag

From CPace's ISK, HKDF-SHA256 (salt = sid) gives two confirmation keys, the
AES-128-CCM key that seals the join key in KEY and the key of its nonce's
pseudonym; the nonce never depends on a random number generator (decision
RJ-15's rule: a sender id the controller draws fresh for every run, boot 1,
count 0). Both codecs check protocol/vectors/pairing.json.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from . import cbor, cpace
from .field_frame import hkdf_sha256, nonce as ff_nonce
from .packet import HEADER_SIZE, PAYLOAD_MAX, Header, header_decode, header_encode, vf_enc, vf_make, vf_version

PAIR_TYPE = 10
BODY_MAX = PAYLOAD_MAX  # 200
FRAME_MIN = HEADER_SIZE + 1
FRAME_MAX = HEADER_SIZE + BODY_MAX  # 209
PAIR_ID_SIZE = 8
SID_SIZE = 16
POINT_SIZE = 32
TAG_SIZE = 16
NONCE_SIZE = 13
MIC_SIZE = 8
FP_SIZE = 4
KEY_SIZE = 32  # the field join key
NAME_MAX = 24  # the box's name in OFFER
FIELD_NAME_MAX = 48  # the field's name in KEY (adoption.md: a field card's)
SEALED_MIN = KEY_SIZE + 1 + MIC_SIZE
SEALED_MAX = SEALED_MIN + FIELD_NAME_MAX
CODE_DIGITS = 6
CI_LABEL = b"atalaia pair v1"
AD_CONTROLLER = b"atalaia controller"
AD_BOX = b"atalaia box"
AAD_LABEL = b"atalaia pair key v1"

OFFER, START, REPLY, KEY, DONE = 1, 2, 3, 4, 5
KINDS = {"offer": OFFER, "start": START, "reply": REPLY, "key": KEY, "done": DONE}
KIND_NAMES = {v: k for k, v in KINDS.items()}
K_KIND, K_PAIR, K_NAME, K_TIER, K_SID, K_POINT, K_TAG, K_NONCE, K_SEALED, K_RESULT, K_FP = range(1, 12)
KNOWN_KEYS = set(range(1, 12))
# DONE's result: adoption.c's adopt_result_t, in its order.
RESULTS = ("adopted", "same", "readopted", "need_pin", "bad_pin", "locked", "busy", "bad_key", "bad_card",
           "store_failed")
RESULT = {name: i for i, name in enumerate(RESULTS)}
OK_RESULTS = ("adopted", "same", "readopted")

_FIELDS = {  # kind -> [(key, name)], in their order on air
    "offer": [(K_PAIR, "pair_id"), (K_NAME, "name"), (K_TIER, "tier")],
    "start": [(K_PAIR, "pair_id"), (K_SID, "sid"), (K_POINT, "point")],
    "reply": [(K_PAIR, "pair_id"), (K_SID, "sid"), (K_POINT, "point"), (K_TAG, "tag")],
    "key": [(K_PAIR, "pair_id"), (K_SID, "sid"), (K_TAG, "tag"), (K_NONCE, "nonce"), (K_SEALED, "sealed")],
    "done": [(K_PAIR, "pair_id"), (K_SID, "sid"), (K_RESULT, "result"), (K_FP, "fingerprint"), (K_TAG, "tag")],
}
_SIZES = {"pair_id": PAIR_ID_SIZE, "sid": SID_SIZE, "point": POINT_SIZE, "tag": TAG_SIZE, "nonce": NONCE_SIZE,
          "fingerprint": FP_SIZE}

_HEADER = Header(vf_make(1, 1, False, False), 0, 0, 0, 0, PAIR_TYPE)


class PairFrameError(ValueError):
    pass


def _uint(value: Any, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def validate(msg: dict[str, Any]) -> dict[str, Any]:
    kind = msg.get("kind")
    if kind not in _FIELDS:
        raise PairFrameError(f"kind: one of {sorted(KINDS)}")
    for _, name in _FIELDS[kind]:
        value = msg.get(name)
        if name in _SIZES:
            if not isinstance(value, (bytes, bytearray)) or len(value) != _SIZES[name]:
                raise PairFrameError(f"{name}: {_SIZES[name]} bytes")
        elif name == "name":
            if not isinstance(value, str) or "\x00" in value or not 1 <= len(value.encode("utf-8")) <= NAME_MAX:
                raise PairFrameError(f"name: 1-{NAME_MAX} bytes of text")
        elif name == "tier":
            if not _uint(value, 0, 2):
                raise PairFrameError("tier: 0-2")
        elif name == "sealed":
            if not isinstance(value, (bytes, bytearray)) or not SEALED_MIN <= len(value) <= SEALED_MAX:
                raise PairFrameError(f"sealed: {SEALED_MIN}-{SEALED_MAX} bytes")
        elif name == "result":
            if value not in RESULT:
                raise PairFrameError(f"result: one of {RESULTS}")
    return msg


def body_encode(msg: dict[str, Any]) -> bytes:
    validate(msg)
    out: dict[int, Any] = {K_KIND: KINDS[msg["kind"]]}
    for key, name in _FIELDS[msg["kind"]]:
        value = msg[name]
        out[key] = RESULT[value] if name == "result" else bytes(value) if isinstance(value, bytearray) else value
    body = cbor.encode(out)
    if len(body) > BODY_MAX:
        raise PairFrameError(f"body of {len(body)} bytes; at most {BODY_MAX}")
    return body


def body_decode(data: bytes) -> dict[str, Any]:
    """Reads a body as the C decoder does: the kind first, every field of the kind once,
    nothing of another kind, no key from 32 up, unknown keys up to 31 skipped."""
    if not 1 <= len(data) <= BODY_MAX:
        raise PairFrameError("body length")
    try:
        raw = cbor.decode(data, allow_bytes=True)
    except (cbor.CBORError, ValueError) as exc:
        raise PairFrameError(f"not CBOR: {exc}") from None
    if not isinstance(raw, dict) or not raw or not all(_uint(k, 0, 0xFFFFFFFF) for k in raw):
        raise PairFrameError("a body is a map with integer keys")
    if list(raw)[0] != K_KIND or not _uint(raw[K_KIND], 0, 255):
        raise PairFrameError("the kind comes first")
    kind = KIND_NAMES.get(raw[K_KIND])
    if kind is None:
        raise PairFrameError(f"unknown kind {raw[K_KIND]}")
    own = {k for k, _ in _FIELDS[kind]}
    for k in raw:
        if k >= 32:
            raise PairFrameError(f"key {k}: keys from 32 up are refused")
        if k != K_KIND and k in KNOWN_KEYS and k not in own:
            raise PairFrameError(f"key {k} is not a {kind}'s")
    msg: dict[str, Any] = {"kind": kind}
    for key, name in _FIELDS[kind]:
        if key not in raw:
            raise PairFrameError(f"missing key {key}")
        value = raw[key]
        if name == "result":
            if not _uint(value, 0, len(RESULTS) - 1):
                raise PairFrameError("result out of range")
            value = RESULTS[value]
        msg[name] = value
    return validate(msg)


def is_frame(pkt: bytes) -> bool:
    """A pair frame's header and length: version 1, not encrypted, game 0, type 10."""
    if not FRAME_MIN <= len(pkt) <= FRAME_MAX:
        return False
    try:
        h = header_decode(pkt[:HEADER_SIZE])
    except ValueError:
        return False
    return (h.game_id == 0 and h.type == PAIR_TYPE and not vf_enc(h.version_flags)
            and vf_version(h.version_flags) == 1)


def encode(msg: dict[str, Any]) -> bytes:
    return header_encode(_HEADER) + body_encode(msg)


def decode(pkt: bytes) -> dict[str, Any]:
    if not is_frame(pkt):
        raise PairFrameError("not a pair frame")
    return body_decode(pkt[HEADER_SIZE:])


# --- the exchange's keys ------------------------------------------------------------


def channel_id(pair_id: bytes) -> bytes:
    """CPace's CI: lv_cat("atalaia pair v1", pair id)."""
    return cpace.lv_cat(CI_LABEL, pair_id)


def code_ok(code: Any) -> bool:
    return isinstance(code, str) and len(code) == CODE_DIGITS and code.isascii() and code.isdigit()


def generator(code: str, pair_id: bytes, sid: bytes) -> bytes:
    if not code_ok(code):
        raise PairFrameError("the code is 6 digits")
    return cpace.calculate_generator(code.encode("ascii"), channel_id(pair_id), sid)


def isk(sid: bytes, k: bytes, ya: bytes, yb: bytes) -> bytes:
    return cpace.isk_ir(sid, k, ya, AD_CONTROLLER, yb, AD_BOX)


def keys(isk_: bytes, sid: bytes) -> dict[str, bytes]:
    """The run's keys from CPace's ISK: HKDF-SHA256 with the sid as salt."""
    def k(label: bytes, n: int) -> bytes:
        return hkdf_sha256(isk_, n, salt=sid, info=label)
    return {"confirm_a": k(b"atalaia pair confirm a v1", 32), "confirm_b": k(b"atalaia pair confirm b v1", 32),
            "seal": k(b"atalaia pair seal v1", 16), "nonce": k(b"atalaia pair nonce v1", 32)}


def _tag(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()[:TAG_SIZE]


def tag_reply(ks: dict[str, bytes]) -> bytes:
    return _tag(ks["confirm_b"], b"atalaia pair reply")


def tag_key(ks: dict[str, bytes]) -> bytes:
    return _tag(ks["confirm_a"], b"atalaia pair key")


def tag_done(ks: dict[str, bytes], result: str, fingerprint: bytes) -> bytes:
    return _tag(ks["confirm_b"], b"atalaia pair done" + bytes([RESULT[result]]) + fingerprint)


def key_nonce(ks: dict[str, bytes], sender: bytes, boot: int = 1, ctr: int = 0) -> bytes:
    """KEY's nonce: the run's sender id's pseudonym, boot and count (field-frames.md's rule)."""
    return ff_nonce(ks["nonce"], sender, boot, ctr)


def _aad(pair_id: bytes, sid: bytes) -> bytes:
    return AAD_LABEL + pair_id + sid


def seal_key(ks: dict[str, bytes], nonce: bytes, pair_id: bytes, sid: bytes, join_key: bytes, name: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    raw = name.encode("utf-8")
    if len(join_key) != KEY_SIZE or len(raw) > FIELD_NAME_MAX:
        raise PairFrameError("a 32-byte key and a name of at most 48 bytes")
    return AESCCM(ks["seal"], tag_length=MIC_SIZE).encrypt(nonce, join_key + bytes([len(raw)]) + raw,
                                                            _aad(pair_id, sid))


def open_key(ks: dict[str, bytes], nonce: bytes, pair_id: bytes, sid: bytes, sealed: bytes) -> tuple[bytes, str]:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    try:
        plain = AESCCM(ks["seal"], tag_length=MIC_SIZE).decrypt(nonce, sealed, _aad(pair_id, sid))
    except InvalidTag:
        raise PairFrameError("the sealed key does not authenticate") from None
    if len(plain) < KEY_SIZE + 1 or plain[KEY_SIZE] != len(plain) - KEY_SIZE - 1:
        raise PairFrameError("the sealed key's name length")
    return plain[:KEY_SIZE], plain[KEY_SIZE + 1:].decode("utf-8")


def fingerprint_bytes(join_key: bytes) -> bytes:
    """The field's fingerprint (adoption.md) as its 4 bytes."""
    return hmac.new(join_key, b"atalaia-field-fingerprint", hashlib.sha256).digest()[:FP_SIZE]
