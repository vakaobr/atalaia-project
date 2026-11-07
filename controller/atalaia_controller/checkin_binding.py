# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Proof that a self check-in comes from the phone that registered (decisions TKB-1 to TKB-8;
protocol/checkin.md, "The registering phone").

A printed ticket is a bearer credential: a copy or a photo works like the paper. When the player's app
registers for a game (or gets a new ticket) it makes an Ed25519 key pair for that registration, keeps the
private key sealed on the phone and gives the site server the public key (``PUT
/api/v1/me/registrations/{id}/binding``). The roster carries it as ``binding_key`` (standard base64, as the
sync's marshal keys) to a controller that asks for it (``?binding=1``). At check-in the app fetches a
challenge from the controller (``GET /api/v1/checkin/challenge``) and signs:

    atalaia-checkin-binding-v1 LF challenge LF game_id LF registration_id LF player_id LF sha256_hex(player_secret)

(``LF`` a single line feed, no trailing one), sent as ``"binding": {"challenge", "signature"}`` with the
check-in, the signature in base64url without padding (86 characters). Pure RFC 8032 Ed25519, as the chrono
records. The controller holds only public keys, so it cannot make a proof itself or replay one to another
controller; the message names the phone's field identity (the secret's hash), so a proof seen once does not
fit another phone's check-in.

A challenge is stateless: 8 bytes of the controller's monotonic seconds, 8 random bytes and the first 16
bytes of HMAC-SHA256(a key made at start and kept in memory, "atalaia checkin challenge v1" | those 16
bytes), 32 bytes in base64url without padding (43 characters). It is good for ``CHALLENGE_TTL`` seconds and
dies with a restart. The Dart side is app/lib/protocol/checkin_binding.dart; both check the ``binding``
vectors of protocol/vectors/checkin.json.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import secrets
import time
from typing import Any, Callable, Optional

CHALLENGE_TTL = 300  # seconds a challenge is good for
CHALLENGE_LEN = 32
SIGNATURE_LEN = 64
MESSAGE_PREFIX = "atalaia-checkin-binding-v1"
_DOMAIN = b"atalaia checkin challenge v1"
_SKEW = 5  # seconds a challenge may be "from the future" (a clock read on another thread)
CHALLENGE_RE = re.compile(r"[A-Za-z0-9_-]{43}")
SIGNATURE_RE = re.compile(r"[A-Za-z0-9_-]{86}")
STATES = ("bound", "unbound")
CHALLENGE_EXPIRED = "binding_challenge_expired: the check-in challenge is unknown or too old (GET /api/v1/checkin/challenge)"


class BindingError(ValueError):
    """A ``binding`` member that is not a proof's shape."""


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Challenges:
    """Issues and checks the controller's check-in challenges, keeping nothing per challenge."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, key: Optional[bytes] = None,
                 ttl: int = CHALLENGE_TTL) -> None:
        self._clock = clock
        self._key = key if key is not None else secrets.token_bytes(32)
        self.ttl = ttl

    def _mac(self, head: bytes) -> bytes:
        return hmac.new(self._key, _DOMAIN + head, hashlib.sha256).digest()[:16]

    def issue(self) -> str:
        head = max(0, int(self._clock())).to_bytes(8, "big") + secrets.token_bytes(8)
        return _b64url(head + self._mac(head))

    def valid(self, text: Any) -> bool:
        if not isinstance(text, str) or not CHALLENGE_RE.fullmatch(text):
            return False
        raw = _unb64url(text)
        head, mac = raw[:16], raw[16:]
        if not hmac.compare_digest(mac, self._mac(head)):
            return False
        age = int(self._clock()) - int.from_bytes(head[:8], "big")
        return -_SKEW <= age <= self.ttl


def parse_proof(value: Any) -> tuple[str, bytes]:
    """``{"challenge": ..., "signature": ...}``: the challenge's text and the 64-byte signature."""
    if not isinstance(value, dict) or set(value) != {"challenge", "signature"}:
        raise BindingError("binding: {challenge, signature}")
    challenge, signature = value["challenge"], value["signature"]
    if not isinstance(challenge, str) or not CHALLENGE_RE.fullmatch(challenge):
        raise BindingError("binding.challenge: the controller's challenge (43 characters)")
    if not isinstance(signature, str) or not SIGNATURE_RE.fullmatch(signature):
        raise BindingError("binding.signature: 64 bytes in base64url without padding (86 characters)")
    raw = _unb64url(signature)
    if len(raw) != SIGNATURE_LEN or _b64url(raw) != signature:
        raise BindingError("binding.signature: 64 bytes in base64url without padding (86 characters)")
    return challenge, raw


def message(challenge: str, game_id: int, registration_id: str, player_id: str, player_secret: bytes) -> bytes:
    """What the registering phone signs."""
    return "\n".join((MESSAGE_PREFIX, challenge, str(game_id), registration_id, player_id,
                      hashlib.sha256(player_secret).hexdigest())).encode("utf-8")


def public_key(text: Any) -> Optional[bytes]:
    """A binding key as the roster carries it (32 bytes, standard base64 with padding), or None."""
    if not isinstance(text, str) or len(text) != 44:
        return None
    try:
        raw = base64.b64decode(text.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError):
        return None
    return raw if len(raw) == 32 and base64.b64encode(raw).decode("ascii") == text else None


def verify(key_text: Any, msg: bytes, signature: bytes) -> bool:
    """Whether ``signature`` is the binding key's Ed25519 signature of ``msg`` (False for a bad key)."""
    from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: PLC0415

    raw = public_key(key_text)
    if raw is None:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(raw).verify(signature, msg)
    except (InvalidSignature, ValueError):
        return False
    return True


def state(row: dict[str, Any]) -> Optional[str]:
    """A registered row's app check-in as staff see it: ``bound`` (the registering phone proved its key),
    ``unbound`` (anything else: an older app or roster, no key, another phone) or None (no app check-in on a
    registration)."""
    if not row.get("registration_id") or row.get("app_checkin_at") is None:
        return None
    return "bound" if row.get("app_bound") else "unbound"
