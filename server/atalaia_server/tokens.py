# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Keys, access tokens, the TOTP login step and refresh tokens (ADR-P4-2).

Every key is derived from ATALAIA_SECRET_KEY with HKDF-SHA256 (RFC 5869) under
its own label, so a token of one kind can never be read as another and the
TOTP seeds' key is not the tokens' key. Changing ATALAIA_SECRET_KEY ends every
session and makes the stored TOTP seeds unreadable (their owners enrol again).

- **Access tokens:** JWT, HS256 only, 15 minutes, with ``sub`` (the user),
  ``sid`` (the session), ``jti``, ``iss`` and ``typ: "access"``, and the user's
  per-field roles for the client's display. The server does not trust that
  claim: every request re-reads the session and the roles from the database
  (``auth.current_principal``), so a logout or a removed role counts at once.
- **TOTP login step:** a JWT of ``typ: "totp"``, 5 minutes, proving the
  password was right; used once (``UsedTokens``).
- **Refresh tokens:** 256 random bits, not a JWT; only their SHA-256 is stored
  (``refresh_tokens.token_hash``), so the database never holds a usable token.
  A random 256-bit value cannot be guessed, so a fast hash is enough (as for
  the controllers' API keys, P4R13), and looking a token up by its hash leaks
  nothing through timing.

In hosted mode (plan phase 21) both JWTs also carry ``ten``, the tenant's
schema they were made in, and are read only in that tenant: a token from one
field's address is refused at another's even before its session is looked
up (decision S21-6). In single-field mode they carry no ``ten`` and one
that does is refused.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import tenancy

ISSUER = "atalaia-server"
ALGORITHM = "HS256"
ACCESS_TTL_S = 15 * 60
TOTP_STEP_TTL_S = 5 * 60
REFRESH_TTL_S = 7 * 24 * 3600      # a session ends after a week without a refresh
SESSION_MAX_S = 30 * 24 * 3600     # and after 30 days whatever happens
LEEWAY_S = 5


def _derive(secret: str, label: str) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=f"atalaia-server {label} v1".encode()).derive(secret.encode("utf-8"))


class Keys:
    """The keys derived from ATALAIA_SECRET_KEY."""

    def __init__(self, secret_key: str) -> None:
        self.access = _derive(secret_key, "access token")
        self.totp_step = _derive(secret_key, "totp login step")
        self.totp_seed = base64.urlsafe_b64encode(_derive(secret_key, "totp seed"))  # a Fernet key
        self.platform_config = base64.urlsafe_b64encode(_derive(secret_key, "platform config"))  # a Fernet key
        self.webauthn = _derive(secret_key, "webauthn challenge")  # signs the passkey ceremonies' challenges (LG-2)
        self.oidc_ticket = _derive(secret_key, "social login ticket")  # signs the tickets of finished social logins (LG-1)
        self.oidc_relay = _derive(secret_key, "social login relay")  # signs the state the hub-level callback reads (LG-14)
        self.feedback_form = _derive(secret_key, "preview feedback form")  # signs the preview feedback form's token

    def __repr__(self) -> str:
        return "Keys(...)"


class TokenError(Exception):
    """The token is missing, malformed, expired, of another kind or not signed by this server."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: uuid.UUID
    session_id: uuid.UUID
    jti: str
    expires_at: int


def _encode(key: bytes, claims: dict[str, Any], ttl_s: int, now: Optional[float]) -> tuple[str, int]:
    issued = int(time.time() if now is None else now)
    exp = issued + ttl_s
    payload = {"iss": ISSUER, "iat": issued, "exp": exp, "jti": secrets.token_urlsafe(16), **claims}
    tenant = tenancy.current_schema()
    if tenant is not None:
        payload["ten"] = tenant
    return jwt.encode(payload, key, algorithm=ALGORITHM), exp


def _decode(key: bytes, token: str, typ: str) -> dict[str, Any]:
    try:
        claims = jwt.decode(token, key, algorithms=[ALGORITHM], issuer=ISSUER, leeway=LEEWAY_S,
                            options={"require": ["iss", "iat", "exp", "jti", "sub", "typ"]})
    except jwt.PyJWTError as e:
        raise TokenError(type(e).__name__) from None
    if claims.get("typ") != typ:
        raise TokenError("wrong token type")
    if claims.get("ten") != tenancy.current_schema():
        raise TokenError("another tenant's token")
    return claims


def make_access_token(keys: Keys, user_id: uuid.UUID, session_id: uuid.UUID, username: str,
                      roles: dict[str, list[str]], now: Optional[float] = None) -> tuple[str, int]:
    """The token and its expiry (Unix seconds)."""
    return _encode(keys.access, {"typ": "access", "sub": str(user_id), "sid": str(session_id),
                                 "username": username, "roles": roles}, ACCESS_TTL_S, now)


def read_access_token(keys: Keys, token: str) -> AccessClaims:
    claims = _decode(keys.access, token, "access")
    try:
        return AccessClaims(uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"]), claims["jti"], int(claims["exp"]))
    except (KeyError, ValueError, TypeError):
        raise TokenError("malformed claims") from None


def make_totp_step_token(keys: Keys, user_id: uuid.UUID, now: Optional[float] = None) -> tuple[str, str]:
    """The token for ``POST /api/v1/auth/login/totp`` and its ``jti``."""
    token, _ = _encode(keys.totp_step, {"typ": "totp", "sub": str(user_id)}, TOTP_STEP_TTL_S, now)
    return token, jwt.decode(token, options={"verify_signature": False})["jti"]


def read_totp_step_token(keys: Keys, token: str) -> tuple[uuid.UUID, str, int]:
    """The user, the ``jti`` and the expiry of a TOTP login step token."""
    claims = _decode(keys.totp_step, token, "totp")
    try:
        return uuid.UUID(claims["sub"]), claims["jti"], int(claims["exp"])
    except (KeyError, ValueError, TypeError):
        raise TokenError("malformed claims") from None


OIDC_TICKET_TTL_S = 60


def make_oidc_ticket(keys: Keys, user_id: uuid.UUID, provider: str, now: Optional[float] = None,
                     new_account: bool = False, app_challenge: Optional[str] = None) -> str:
    """What a finished social login hands the browser (LG-1): a signed, one-minute, single-use ticket that
    ``POST /api/v1/auth/oidc/complete`` turns into a session. The session itself is made by that same-site
    call, so the refresh cookie is set by a request the site started, not by a redirect from the provider."""
    claims: dict[str, Any] = {"typ": "oidc", "sub": str(user_id), "prov": provider}
    if new_account:
        claims["new"] = True  # this login made the account: the pages offer the "choose your username" step (LG-10)
    if app_challenge:
        claims["acr"] = app_challenge  # the app's verifier hash (APP-4): /auth/oidc/complete wants the verifier
    token, _ = _encode(keys.oidc_ticket, claims, OIDC_TICKET_TTL_S, now)
    return token


def read_oidc_ticket(keys: Keys, token: str) -> tuple[uuid.UUID, str, str, int, bool, Optional[str]]:
    """The user, the provider, the ``jti``, the expiry, whether it made the account and the app's verifier hash
    (None for a browser's ticket), of a social login ticket."""
    claims = _decode(keys.oidc_ticket, token, "oidc")
    try:
        return (uuid.UUID(claims["sub"]), str(claims["prov"]), claims["jti"], int(claims["exp"]),
                claims.get("new") is True, str(claims["acr"]) if claims.get("acr") else None)
    except (KeyError, ValueError, TypeError):
        raise TokenError("malformed claims") from None


MERGE_TICKET_TTL_S = 5 * 60


def make_merge_ticket(keys: Keys, user_id: uuid.UUID, other_id: uuid.UUID, provider: str,
                      now: Optional[float] = None) -> str:
    """What the provider round of an account that links a login belonging to another account hands the browser
    (LG-11): the proof, for five minutes and one use, that ``user_id`` just completed ``provider``'s login of
    ``other_id``. It asks for nothing by itself: the merge is a separate, confirmed call by ``user_id``."""
    token, _ = _encode(keys.oidc_ticket, {"typ": "merge", "sub": str(user_id), "oth": str(other_id), "prov": provider},
                       MERGE_TICKET_TTL_S, now)
    return token


def read_merge_ticket(keys: Keys, token: str) -> tuple[uuid.UUID, uuid.UUID, str, str, int]:
    """The account that proved it, the account whose login it was, the provider, the ``jti`` and the expiry."""
    claims = _decode(keys.oidc_ticket, token, "merge")
    try:
        return (uuid.UUID(claims["sub"]), uuid.UUID(claims["oth"]), str(claims["prov"]), claims["jti"],
                int(claims["exp"]))
    except (KeyError, ValueError, TypeError):
        raise TokenError("malformed claims") from None


WEBAUTHN_TTL_S = 5 * 60
WEBAUTHN_PURPOSES = ("register", "login", "stepup")


def make_webauthn_challenge(keys: Keys, purpose: str, challenge: bytes, user_id: Optional[uuid.UUID] = None,
                            session_id: Optional[uuid.UUID] = None, now: Optional[float] = None) -> str:
    """A WebAuthn challenge, signed, to come back with the browser's answer (LG-2): the server keeps no state,
    and the challenge is single use (``UsedTokens``). ``purpose`` is register, login or stepup; a token made
    for one purpose, user or session is refused for another."""
    if purpose not in WEBAUTHN_PURPOSES:
        raise ValueError(purpose)
    claims: dict[str, Any] = {"typ": "webauthn", "sub": str(user_id) if user_id else "-", "pur": purpose,
                              "ch": base64.urlsafe_b64encode(challenge).rstrip(b"=").decode("ascii")}
    if session_id is not None:
        claims["sid"] = str(session_id)
    token, _ = _encode(keys.webauthn, claims, WEBAUTHN_TTL_S, now)
    return token


@dataclass(frozen=True)
class WebauthnChallenge:
    purpose: str
    challenge: bytes
    user_id: Optional[uuid.UUID]
    session_id: Optional[uuid.UUID]
    jti: str
    expires_at: int


def read_webauthn_challenge(keys: Keys, token: str) -> WebauthnChallenge:
    claims = _decode(keys.webauthn, token, "webauthn")
    try:
        sub = claims["sub"]
        return WebauthnChallenge(
            claims["pur"], base64.urlsafe_b64decode(claims["ch"] + "=" * (-len(claims["ch"]) % 4)),
            None if sub == "-" else uuid.UUID(sub), uuid.UUID(claims["sid"]) if "sid" in claims else None,
            claims["jti"], int(claims["exp"]))
    except (KeyError, ValueError, TypeError):
        raise TokenError("malformed claims") from None


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def refresh_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class UsedTokens:
    """Ids of single-use tokens already spent, forgotten once they would have expired anyway.

    In memory, as ADR-P4-2 has it: the site server runs one worker process.
    """

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._spent: dict[str, int] = {}
        self._lock = threading.Lock()

    def spent(self, jti: str) -> bool:
        with self._lock:
            return jti in self._spent

    def spend(self, jti: str, expires_at: int) -> bool:
        """Marks it spent; False if it already was."""
        with self._lock:
            now = self._clock()
            for old in [k for k, exp in self._spent.items() if exp + LEEWAY_S < now]:
                del self._spent[old]
            if jti in self._spent:
                return False
            self._spent[jti] = expires_at
            return True
