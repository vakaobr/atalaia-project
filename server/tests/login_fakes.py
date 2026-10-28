# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test doubles for the login methods: a fake OpenID Connect provider and a soft WebAuthn authenticator.

``FakeIdp`` stands in for ``oidc.Http``: it serves a JWKS and a token endpoint, and signs ID tokens with an RSA
key of its own (RS256). The test says what the next token holds (``issue``); the token endpoint checks what a
real one checks (the code, the redirect URI, the client secret, the PKCE verifier against the challenge the
authorization request carried) so a broken flow fails here.

``SoftAuthenticator`` is a virtual authenticator: an ES256 key pair, a credential id and a signature counter, making
the registration (attestation ``none``) and assertion objects a browser would hand over. Nothing here is the
server's own code: it is built from the WebAuthn Level 2 specification's byte layouts (sections 6.1 and 6.5.1).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from typing import Any, Optional
from urllib.parse import parse_qs, urlsplit

import cbor2
import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature  # noqa: F401

from atalaia_server import oidc


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64u(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class FakeIdp:
    """A provider's token endpoint and JWKS in one."""

    def __init__(self, kid: str = "test-key-1") -> None:
        self.kid = kid
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.requests: list[tuple[str, str]] = []                 # ("post"|"get", url)
        self.authorizations: dict[str, dict[str, str]] = {}      # code -> the authorization request's parameters
        self.code_claims: dict[str, dict[str, Any]] = {}         # code -> claims of the token it gives
        self.publish_keys = True
        self.token_status: Optional[int] = None                    # an OidcError code to raise at the token endpoint

    # The JWKS --------------------------------------------------------------------------------

    def jwk(self, kid: Optional[str] = None) -> dict[str, Any]:
        numbers = self.key.public_key().public_numbers()

        def enc(n: int) -> str:
            return b64u(n.to_bytes((n.bit_length() + 7) // 8, "big"))

        return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid or self.kid, "n": enc(numbers.n),
                "e": enc(numbers.e)}

    async def get_json(self, url: str) -> dict[str, Any]:
        self.requests.append(("get", url))
        return {"keys": [self.jwk()] if self.publish_keys else []}

    # Tokens ----------------------------------------------------------------------------------

    def id_token(self, claims: dict[str, Any], *, alg: str = "RS256", kid: Optional[str] = None,
                 key: Any = None) -> str:
        headers = {"kid": kid or self.kid}
        if alg == "none":
            return jwt.encode(claims, None, algorithm="none", headers=headers)
        if alg == "HS256":
            return jwt.encode(claims, "x" * 64, algorithm="HS256", headers=headers)
        return jwt.encode(claims, key or self.key, algorithm=alg, headers=headers)

    def claims(self, provider: str, client_id: str, subject: str, nonce: str, /, **over: Any) -> dict[str, Any]:
        now = int(time.time())
        iss = {"google": "https://accounts.google.com", "apple": oidc.APPLE_ISSUER,
               "microsoft": f"https://login.microsoftonline.com/{over.get('tid', 'tenant-1')}/v2.0"}[provider]
        base: dict[str, Any] = {"iss": iss, "aud": client_id, "sub": subject, "iat": now - 5, "exp": now + 600,
                                "nonce": nonce}
        if provider == "microsoft":
            base["tid"] = "tenant-1"
        base.update(over)
        return {k: v for k, v in base.items() if v is not None}

    def authorize(self, authorization_url: str) -> dict[str, str]:
        """Records the authorization request (what the browser would send to the provider)."""
        parts = urlsplit(authorization_url)
        params = {k: v[0] for k, v in parse_qs(parts.query).items()}
        self.authorizations[params["state"]] = params
        return params

    def grant(self, params: dict[str, str], claims: dict[str, Any], code: Optional[str] = None) -> str:
        """Gives the user's consent for that authorization request: a code that yields these claims."""
        code = code or secrets.token_urlsafe(12)
        self.authorizations[code] = params
        self.code_claims[code] = claims
        return code

    async def post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        self.requests.append(("post", url))
        if self.token_status is not None:
            raise oidc.OidcError("token_exchange_failed")
        code = data.get("code", "")
        params = self.authorizations.get(code)
        if params is None or data.get("grant_type") != "authorization_code":
            raise oidc.OidcError("token_exchange_failed")
        if data.get("redirect_uri") != params["redirect_uri"] or data.get("client_id") != params["client_id"]:
            raise oidc.OidcError("token_exchange_failed")
        if params.get("code_challenge_method") != "S256" or oidc.pkce_challenge(data.get("code_verifier", "")) \
                != params.get("code_challenge"):
            raise oidc.OidcError("token_exchange_failed")
        if not data.get("client_secret"):
            raise oidc.OidcError("token_exchange_failed")
        self.last_client_secret = data["client_secret"]
        return {"access_token": "unused", "token_type": "Bearer", "id_token": self.id_token(self.code_claims[code])}


def apple_key_pem() -> bytes:
    """A P-256 private key in PEM, as Apple's .p8 files are (PKCS#8)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


class SoftAuthenticator:
    """A virtual platform authenticator with user verification."""

    def __init__(self, uv: bool = True, backup: bool = False) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.counter = 0
        self.uv = uv
        self.backup = backup
        self.user_handle: Optional[bytes] = None

    def _cose_key(self) -> bytes:
        numbers = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: numbers.x.to_bytes(32, "big"), -3: numbers.y.to_bytes(32, "big")})

    def _flags(self, attested: bool) -> int:
        flags = 0x01 | (0x04 if self.uv else 0) | (0x40 if attested else 0)
        if self.backup:
            flags |= 0x08 | 0x10
        return flags

    @staticmethod
    def _client_data(kind: str, challenge: str, origin: str) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": origin, "crossOrigin": False}).encode()

    def create(self, options: dict[str, Any], origin: str, rp_id: Optional[str] = None) -> dict[str, Any]:
        """The answer of ``navigator.credentials.create`` to these options."""
        rp = rp_id or options["rp"]["id"]
        self.user_handle = unb64u(options["user"]["id"])
        auth_data = (hashlib.sha256(rp.encode()).digest() + bytes([self._flags(True)]) + self.counter.to_bytes(4, "big")
                     + bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + self._cose_key())
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        return {"id": b64u(self.credential_id), "rawId": b64u(self.credential_id), "type": "public-key",
                "authenticatorAttachment": "platform", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64u(client_data), "attestationObject": b64u(attestation),
                             "transports": ["internal"]}}

    def get(self, options: dict[str, Any], origin: str, rp_id: Optional[str] = None, bump: int = 1,
            user_handle: Optional[bytes] = None, challenge: Optional[str] = None) -> dict[str, Any]:
        """The answer of ``navigator.credentials.get`` (an assertion); the counter moves on by ``bump``."""
        rp = rp_id or options["rpId"]
        self.counter += bump
        auth_data = hashlib.sha256(rp.encode()).digest() + bytes([self._flags(False)]) + self.counter.to_bytes(4, "big")
        client_data = self._client_data("webauthn.get", challenge or options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        handle = user_handle if user_handle is not None else self.user_handle
        return {"id": b64u(self.credential_id), "rawId": b64u(self.credential_id), "type": "public-key",
                "clientExtensionResults": {},
                "response": {"clientDataJSON": b64u(client_data), "authenticatorData": b64u(auth_data),
                             "signature": b64u(signature), "userHandle": b64u(handle) if handle else None}}
