# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Field frames (protocol/field-frames.md, RFC 0001 Amendment 7): the radio outside any game.

A box with no game announces itself (ANNOUNCE), a field controller asks who is
free (DISCOVER) and invites a free box into its next game (INVITE: a join
payload, protocol/join.md, in one to three parts, for the box's device id and
the token of its last announcement), and says that a game is over (GAME_OVER:
the game id and its key's tag, for a controller that lost the game's key;
decision OT-13), and says that the field has moved to another channel (MOVE: the new channel
and a revision that only rises, RFC 0001 Amendment 19). On air::

    header (9: game_id 0, source 0, seq 0, hop_limit 0, type 9) | nonce (13) | body | MIC (8)

sealed with AES-128-CCM under ``field_key(join_key)``: HKDF-SHA256 (RFC 5869)
of the field join key with the label ``atalaia field frame v1``. The nonce, in
the clear, never comes from a random number generator (decision RJ-15): the
sender's pseudonym (HMAC of its 8-byte sender id, 8 bytes), its boot count
(3 bytes, stored before its first use) and a frame count (2 bytes), made by a
``NonceSource``. The C codec is core/src/field_frame.c; both check
protocol/vectors/field_frame.json.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any, Optional

from . import cbor
from .packet import (HEADER_SIZE, MIC_SIZE, PAYLOAD_MAX, Header, aad_extract, header_decode, header_encode, vf_enc,
                     vf_make, vf_version)

FIELD_TYPE = 9
NONCE_SIZE = 13
KEY_SIZE = 16
BODY_MAX = PAYLOAD_MAX - NONCE_SIZE           # 187
FRAME_MIN = HEADER_SIZE + NONCE_SIZE + 1 + MIC_SIZE
FRAME_MAX = HEADER_SIZE + PAYLOAD_MAX + MIC_SIZE  # 217
DEVICE_SIZE = 8
TOKEN_SIZE = 8
NAME_MAX = 24
ROLE_MAX = 31
PARTS_MAX = 3
CHUNK_MAX = 153  # an INVITE's other fields take at most 34 bytes of the 187
JOIN_MAX = 448
LABEL = b"atalaia field frame v1"
NONCE_LABEL = b"atalaia field nonce v1"
SENDER_SIZE = 8
TAG_SIZE = 8  # a game key's tag: HMAC-SHA256(game key, "atalaia epoch tag")[:8]
BOOT_MAX = 0xFFFFFF
CTR_MAX = 0xFFFF

ANNOUNCE, DISCOVER, INVITE, GAME_OVER, MOVE = 1, 2, 3, 4, 5
KINDS = {"announce": ANNOUNCE, "discover": DISCOVER, "invite": INVITE, "game_over": GAME_OVER, "move": MOVE}
KIND_NAMES = {v: k for k, v in KINDS.items()}

# What a box answers to an invite (ANNOUNCE key 10).
RESULTS = ("accepted", "busy", "refused", "no_mode", "not_box", "storage", "radio", "ended")
RESULT = {name: i for i, name in enumerate(RESULTS)}

# Body keys.
K_KIND, K_DEVICE, K_TOKEN = 1, 2, 3
K_NAME, K_TIER, K_LAST_GAME, K_LAST_ROLE, K_BATTERY, K_ANSWER, K_RESULT = 4, 5, 6, 7, 8, 9, 10
K_INVITE, K_PART, K_PARTS, K_CHUNK = 4, 5, 6, 7
K_GAME, K_KEY_TAG = 4, 5
K_CHANNEL, K_REV = 4, 5  # MOVE: the field's new channel (Hz) and its revision
KNOWN_KEYS = set(range(1, 11))  # a key another kind uses is not an "unknown" one

_HEADER = Header(vf_make(1, 1, False, True), 0, 0, 0, 0, FIELD_TYPE)


class FieldFrameError(ValueError):
    """A frame or a body that this codec refuses."""


# --- keys --------------------------------------------------------------------


def key_tag(game_key: bytes) -> bytes:
    """A game key's tag (8 bytes), as the boxes' epoch store names the key: it says nothing of the key."""
    if len(game_key) != 16:
        raise ValueError("a game key is 16 bytes")
    return hmac.new(game_key, b"atalaia epoch tag", hashlib.sha256).digest()[:TAG_SIZE]


def hkdf_sha256(ikm: bytes, length: int, salt: bytes = b"", info: bytes = b"") -> bytes:
    """HKDF-SHA256, RFC 5869: extract (no salt = 32 zero bytes), then expand."""
    if length > 255 * 32:
        raise ValueError("HKDF-SHA256 gives at most 8160 bytes")
    prk = hmac.new(salt or bytes(32), ikm, hashlib.sha256).digest()
    out, t, i = b"", b"", 1
    while len(out) < length:
        t = hmac.new(prk, t + info + bytes([i]), hashlib.sha256).digest()
        out += t
        i += 1
    return out[:length]


def field_key(join_key: bytes) -> bytes:
    """The field frames' AES-128 key from the 32-byte field join key."""
    if len(join_key) != 32:
        raise ValueError("the field join key is 32 bytes")
    return hkdf_sha256(join_key, KEY_SIZE, info=LABEL)


def nonce_key(join_key: bytes) -> bytes:
    """The key of the nonces' sender pseudonyms (32 bytes)."""
    if len(join_key) != 32:
        raise ValueError("the field join key is 32 bytes")
    return hkdf_sha256(join_key, 32, info=NONCE_LABEL)


def nonce(nkey: bytes, sender: bytes, boot: int, ctr: int) -> bytes:
    """HMAC-SHA256(nkey, sender)[:8] | boot (3 bytes) | ctr (2 bytes), big-endian."""
    if len(sender) != SENDER_SIZE or not 0 <= boot <= BOOT_MAX or not 0 <= ctr <= CTR_MAX:
        raise ValueError("sender: 8 bytes; boot: 0-16777215; ctr: 0-65535")
    return hmac.new(nkey, sender, hashlib.sha256).digest()[:8] + boot.to_bytes(3, "big") + ctr.to_bytes(2, "big")


class NonceSource:
    """A sender's nonces: its boot count is raised and stored (``save_boot``) before the first
    nonce of a run and whenever the frame count would wrap, so none ever repeats, whatever the
    random number generator. ``load_boot`` gives the stored count (0 if none); a save that
    fails (returns False) or a boot count past BOOT_MAX stops the sending (NonceError)."""

    def __init__(self, join_key: bytes, sender: bytes, load_boot=None, save_boot=None) -> None:
        if len(sender) != SENDER_SIZE:
            raise ValueError("the sender id is 8 bytes")
        self.nkey = nonce_key(join_key)
        self.sender = bytes(sender)
        self._stored = 0
        self.load_boot = load_boot or (lambda: self._stored)
        self.save_boot = save_boot or self._remember
        self.boot: Optional[int] = None
        self.ctr = 0

    def _remember(self, boot: int) -> bool:
        self._stored = boot
        return True

    def next(self) -> bytes:
        if self.boot is None or self.ctr > CTR_MAX:
            boot = int(self.load_boot() or 0) + 1
            if boot > BOOT_MAX or not self.save_boot(boot):
                raise NonceError("the boot count cannot be raised: no more field frames")
            self.boot, self.ctr = boot, 0
        out = nonce(self.nkey, self.sender, self.boot, self.ctr)
        self.ctr += 1
        return out


class NonceError(Exception):
    pass


# --- bodies ------------------------------------------------------------------


def _text_ok(value: Any, max_bytes: int) -> bool:
    if not isinstance(value, str) or "\x00" in value:
        return False
    return 1 <= len(value.encode("utf-8")) <= max_bytes


def _uint(value: Any, lo: int, hi: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and lo <= value <= hi


def _fixed(value: Any, size: int) -> bool:
    return isinstance(value, (bytes, bytearray)) and len(value) == size


def validate(msg: dict[str, Any]) -> dict[str, Any]:
    """Checks a message (``kind`` "announce", "discover" or "invite" and its fields)."""
    kind = msg.get("kind")
    if kind == "announce":
        if not _fixed(msg.get("device_id"), DEVICE_SIZE) or not _fixed(msg.get("token"), TOKEN_SIZE):
            raise FieldFrameError("device_id and token are 8 bytes each")
        if not _text_ok(msg.get("name"), NAME_MAX):
            raise FieldFrameError(f"name: 1-{NAME_MAX} bytes of text")
        if not _uint(msg.get("tier"), 0, 2):
            raise FieldFrameError("tier: 0-2")
        if msg.get("last_game") is not None and not _uint(msg["last_game"], 1, 0xFFFE):
            raise FieldFrameError("last_game: 1-65534")
        if msg.get("last_role") is not None and not _text_ok(msg["last_role"], ROLE_MAX):
            raise FieldFrameError(f"last_role: 1-{ROLE_MAX} bytes of text")
        if msg.get("battery_pct") is not None and not _uint(msg["battery_pct"], 0, 100):
            raise FieldFrameError("battery_pct: 0-100")
        if (msg.get("answer") is None) != (msg.get("result") is None):
            raise FieldFrameError("an answer says its result, and only an answer has one")
        if msg.get("answer") is not None:
            if not _uint(msg["answer"], 1, 0xFFFF) or msg["result"] not in RESULT:
                raise FieldFrameError(f"answer: 1-65535 with a result of {RESULTS}")
    elif kind == "discover":
        pass
    elif kind == "game_over":
        if not _uint(msg.get("game_id"), 1, 0xFFFE):
            raise FieldFrameError("game_id: 1-65534")
        if not _fixed(msg.get("key_tag"), TAG_SIZE):
            raise FieldFrameError("key_tag: 8 bytes")
    elif kind == "move":
        if not _uint(msg.get("channel_hz"), 1, 0xFFFFFFFF):
            raise FieldFrameError("channel_hz: 1-4294967295")
        if not _uint(msg.get("rev"), 1, 0xFFFFFFFF):
            raise FieldFrameError("rev: 1-4294967295")
    elif kind == "invite":
        if not _fixed(msg.get("device_id"), DEVICE_SIZE) or not _fixed(msg.get("token"), TOKEN_SIZE):
            raise FieldFrameError("device_id and token are 8 bytes each")
        if not _uint(msg.get("invite_id"), 1, 0xFFFF):
            raise FieldFrameError("invite_id: 1-65535")
        if not _uint(msg.get("parts"), 1, PARTS_MAX) or not _uint(msg.get("part"), 0, msg["parts"] - 1):
            raise FieldFrameError(f"parts: 1-{PARTS_MAX}, part: 0 to parts - 1")
        chunk = msg.get("chunk")
        if not isinstance(chunk, (bytes, bytearray)) or not 1 <= len(chunk) <= CHUNK_MAX:
            raise FieldFrameError(f"chunk: 1-{CHUNK_MAX} bytes")
    else:
        raise FieldFrameError(f"kind: one of {sorted(KINDS)}")
    return msg


def body_encode(msg: dict[str, Any]) -> bytes:
    """The CBOR body: integer keys in order, shortest form, optional fields left out."""
    validate(msg)
    kind = msg["kind"]
    out: dict[int, Any] = {K_KIND: KINDS[kind]}
    if kind == "announce":
        out.update({K_DEVICE: bytes(msg["device_id"]), K_TOKEN: bytes(msg["token"]),
                    K_NAME: msg["name"], K_TIER: msg["tier"]})
        for key, name in ((K_LAST_GAME, "last_game"), (K_LAST_ROLE, "last_role"), (K_BATTERY, "battery_pct")):
            if msg.get(name) is not None:
                out[key] = msg[name]
        if msg.get("answer") is not None:
            out[K_ANSWER] = msg["answer"]
            out[K_RESULT] = RESULT[msg["result"]]
    elif kind == "invite":
        out.update({K_DEVICE: bytes(msg["device_id"]), K_TOKEN: bytes(msg["token"]),
                    K_INVITE: msg["invite_id"], K_PART: msg["part"], K_PARTS: msg["parts"],
                    K_CHUNK: bytes(msg["chunk"])})
    elif kind == "game_over":
        out.update({K_GAME: msg["game_id"], K_KEY_TAG: bytes(msg["key_tag"])})
    elif kind == "move":
        out.update({K_CHANNEL: msg["channel_hz"], K_REV: msg["rev"]})
    body = cbor.encode(out)
    if len(body) > BODY_MAX:
        raise FieldFrameError(f"body of {len(body)} bytes; at most {BODY_MAX}")
    return body


_ANNOUNCE_KEYS = {K_KIND, K_DEVICE, K_TOKEN, K_NAME, K_TIER, K_LAST_GAME, K_LAST_ROLE, K_BATTERY,
                  K_ANSWER, K_RESULT}
_INVITE_KEYS = {K_KIND, K_DEVICE, K_TOKEN, K_INVITE, K_PART, K_PARTS, K_CHUNK}
_GAME_OVER_KEYS = {K_KIND, K_GAME, K_KEY_TAG}
_MOVE_KEYS = {K_KIND, K_CHANNEL, K_REV}


def body_decode(data: bytes) -> dict[str, Any]:
    """Reads a body as the C decoder does (refusing what it refuses)."""
    if not 1 <= len(data) <= BODY_MAX:
        raise FieldFrameError("body length")
    try:
        raw = cbor.decode(data, allow_bytes=True)
    except (cbor.CBORError, ValueError) as exc:
        raise FieldFrameError(f"not CBOR: {exc}") from None
    if not isinstance(raw, dict) or not raw or not all(_uint(k, 0, 0xFFFFFFFF) for k in raw):
        raise FieldFrameError("a body is a map with integer keys")
    if list(raw)[0] != K_KIND or not _uint(raw[K_KIND], 0, 255):
        raise FieldFrameError("the kind comes first")
    kind = KIND_NAMES.get(raw[K_KIND])
    allowed = {"announce": _ANNOUNCE_KEYS, "discover": {K_KIND}, "invite": _INVITE_KEYS,
               "game_over": _GAME_OVER_KEYS, "move": _MOVE_KEYS}.get(kind or "")
    if allowed is None:
        raise FieldFrameError(f"unknown kind {raw[K_KIND]}")
    for k in raw:
        if k >= 32:
            raise FieldFrameError(f"key {k}: keys from 32 up are refused")
        if k not in allowed and k in KNOWN_KEYS:
            raise FieldFrameError(f"key {k} is not a {kind}'s")
    msg: dict[str, Any] = {"kind": kind}
    if kind == "announce":
        names = {K_DEVICE: "device_id", K_TOKEN: "token", K_NAME: "name", K_TIER: "tier",
                 K_LAST_GAME: "last_game", K_LAST_ROLE: "last_role", K_BATTERY: "battery_pct",
                 K_ANSWER: "answer"}
        for key, name in names.items():
            if key in raw:
                msg[name] = raw[key]
        for key in (K_DEVICE, K_TOKEN, K_NAME, K_TIER):
            if key not in raw:
                raise FieldFrameError(f"missing key {key}")
        if K_RESULT in raw:
            if not _uint(raw[K_RESULT], 0, len(RESULTS) - 1):
                raise FieldFrameError("result out of range")
            msg["result"] = RESULTS[raw[K_RESULT]]
    elif kind == "invite":
        names = {K_DEVICE: "device_id", K_TOKEN: "token", K_INVITE: "invite_id", K_PART: "part",
                 K_PARTS: "parts", K_CHUNK: "chunk"}
        for key, name in names.items():
            if key not in raw:
                raise FieldFrameError(f"missing key {key}")
            msg[name] = raw[key]
    elif kind == "game_over":
        for key, name in ((K_GAME, "game_id"), (K_KEY_TAG, "key_tag")):
            if key not in raw:
                raise FieldFrameError(f"missing key {key}")
            msg[name] = raw[key]
    elif kind == "move":
        for key, name in ((K_CHANNEL, "channel_hz"), (K_REV, "rev")):
            if key not in raw:
                raise FieldFrameError(f"missing key {key}")
            msg[name] = raw[key]
    try:
        validate(msg)
    except FieldFrameError:
        raise
    return msg


# --- frames ------------------------------------------------------------------


def _aesccm(key: bytes):
    from cryptography.hazmat.primitives.ciphers.aead import AESCCM
    return AESCCM(key, tag_length=MIC_SIZE)


def is_frame(pkt: bytes) -> bool:
    """A field frame's header and length (before any crypto)."""
    if not FRAME_MIN <= len(pkt) <= FRAME_MAX:
        return False
    try:
        h = header_decode(pkt[:HEADER_SIZE])
    except ValueError:
        return False
    return h.game_id == 0 and h.type == FIELD_TYPE and vf_enc(h.version_flags) and vf_version(h.version_flags) == 1


def seal(key: bytes, body: bytes, nonce: bytes) -> bytes:
    """A whole frame for a body, with the sender's next nonce (NonceSource.next)."""
    if not 1 <= len(body) <= BODY_MAX:
        raise FieldFrameError(f"body: 1-{BODY_MAX} bytes")
    if len(nonce) != NONCE_SIZE:
        raise FieldFrameError("the nonce is 13 bytes")
    header = header_encode(_HEADER)
    return header + nonce + _aesccm(key).encrypt(nonce, body, aad_extract(header))


def open_frame(key: bytes, pkt: bytes) -> bytes:
    """The body of a frame; FieldFrameError if it is not one or does not authenticate."""
    if not is_frame(pkt):
        raise FieldFrameError("not a field frame")
    nonce = pkt[HEADER_SIZE:HEADER_SIZE + NONCE_SIZE]
    from cryptography.exceptions import InvalidTag
    try:
        return _aesccm(key).decrypt(nonce, pkt[HEADER_SIZE + NONCE_SIZE:], aad_extract(pkt[:HEADER_SIZE]))
    except InvalidTag:
        raise FieldFrameError("does not authenticate (another field's key, or altered)") from None


def encode(key: bytes, msg: dict[str, Any], nonce: bytes) -> bytes:
    return seal(key, body_encode(msg), nonce)


def decode(key: bytes, pkt: bytes) -> dict[str, Any]:
    return body_decode(open_frame(key, pkt))


# --- invite parts --------------------------------------------------------------


def split(payload: bytes) -> list[bytes]:
    """A join payload as an invite's chunks: CHUNK_MAX bytes each, the last one shorter."""
    if not 1 <= len(payload) <= JOIN_MAX:
        raise FieldFrameError(f"a join payload is 1-{JOIN_MAX} bytes")
    return [payload[i:i + CHUNK_MAX] for i in range(0, len(payload), CHUNK_MAX)]


def invite_frames(key: bytes, nonces: NonceSource, device_id: bytes, token: bytes, invite_id: int,
                  payload: bytes) -> list[bytes]:
    chunks = split(payload)
    return [encode(key, {"kind": "invite", "device_id": device_id, "token": token, "invite_id": invite_id,
                         "part": i, "parts": len(chunks), "chunk": c}, nonces.next()) for i, c in enumerate(chunks)]


class Reassembly:
    """An invite's parts put back together (as the box does, atalaia_ff_reasm_add)."""

    def __init__(self) -> None:
        self.key: Optional[tuple[int, bytes, int]] = None
        self.chunks: dict[int, bytes] = {}

    def add(self, msg: dict[str, Any]) -> Optional[bytes]:
        key = (msg["invite_id"], bytes(msg["token"]), msg["parts"])
        if key != self.key:
            self.key, self.chunks = key, {}
        self.chunks[msg["part"]] = bytes(msg["chunk"])
        if len(self.chunks) < msg["parts"]:
            return None
        payload = b"".join(self.chunks[i] for i in range(msg["parts"]))
        self.key, self.chunks = None, {}
        if len(payload) > JOIN_MAX:
            raise FieldFrameError("the parts make more than a join payload")
        return payload
