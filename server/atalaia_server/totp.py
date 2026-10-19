# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two-factor login with TOTP (RFC 6238), through pyotp (ADR-P4-2).

Codes are the authenticator apps' default: HMAC-SHA1, 6 digits, a 30-second
step from the Unix epoch. A code is accepted for the current step and one step
either side (clock drift, RFC 6238 section 5.2), compared in constant time,
and **at most once**: the step of the last accepted code is kept per user and
a code for that step or an earlier one is refused (RFC 6238 section 5.2: "the
verifier MUST NOT accept the second attempt of the OTP after the successful
validation has been issued for the first OTP").

Secrets are 160 random bits (RFC 4226 section 4 recommends 160), shown once as
base32 and an ``otpauth://`` URI, and stored encrypted with Fernet under a key
derived from ATALAIA_SECRET_KEY (``tokens.Keys``).
"""

from __future__ import annotations

import hashlib
import hmac
import re
from typing import Any, Callable, Optional

import pyotp
from cryptography.fernet import Fernet, InvalidToken

DIGITS = 6
PERIOD_S = 30
WINDOW = 1  # steps accepted either side of the current one
ISSUER = "Atalaia"
_CODE = re.compile(r"[0-9]{6}")


def new_secret() -> str:
    """A new base32 secret of 160 bits."""
    return pyotp.random_base32(32)


def _totp(secret_b32: str, digits: int = DIGITS, digest: Callable[..., Any] = hashlib.sha1) -> pyotp.TOTP:
    return pyotp.TOTP(secret_b32, digits=digits, digest=digest, interval=PERIOD_S)


def code_at(secret_b32: str, unix_time: float, digits: int = DIGITS,
            digest: Callable[..., Any] = hashlib.sha1) -> str:
    """The code for that moment (T0 = 0, X = 30 s, RFC 6238 section 4)."""
    return _totp(secret_b32, digits, digest).at(int(unix_time))


def step_of(unix_time: float) -> int:
    return int(unix_time) // PERIOD_S


def verify(secret_b32: str, code: str, unix_time: float, last_step: Optional[int]) -> Optional[int]:
    """The step the code belongs to when it is valid and newer than ``last_step``, else None.

    All the candidate steps are always computed and compared, so the time taken
    does not depend on which one (if any) matched.
    """
    code = code.strip()
    if not _CODE.fullmatch(code):
        return None
    totp = _totp(secret_b32)
    now = step_of(unix_time)
    matched: Optional[int] = None
    for step in range(now - WINDOW, now + WINDOW + 1):
        if hmac.compare_digest(totp.generate_otp(step).encode(), code.encode()) and matched is None:
            matched = step
    if matched is None or (last_step is not None and matched <= last_step):
        return None
    return matched


def provisioning_uri(secret_b32: str, account: str) -> str:
    """The ``otpauth://totp/...`` URI an authenticator app reads (as a QR code or pasted)."""
    return _totp(secret_b32).provisioning_uri(name=account, issuer_name=ISSUER)


class SeedBox:
    """Encrypts and decrypts TOTP secrets for the ``users.totp_secret_enc`` column (Fernet)."""

    def __init__(self, fernet_key: bytes) -> None:
        self._fernet = Fernet(fernet_key)

    def seal(self, secret_b32: str) -> bytes:
        return self._fernet.encrypt(secret_b32.encode("ascii"))

    def open(self, sealed: bytes) -> Optional[str]:
        """The secret, or None if it was sealed under another key (ATALAIA_SECRET_KEY changed)."""
        try:
            return self._fernet.decrypt(bytes(sealed)).decode("ascii")
        except InvalidToken:
            return None
