# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Social login with OpenID Connect: Google, Microsoft (Entra ID) and Apple (decisions LG-1, LG-8).

The authorization code flow with PKCE (RFC 7636, S256), a state and a nonce, no implicit flow and no
profile: the only scope asked for is ``openid`` (none for Apple, whose scopes are ``name`` and ``email``,
neither of which the server wants), so the provider tells the server one thing, an opaque subject, which
is all that is stored (``user_identities``). Email is never asked for and never read.

The ID token is read from the token endpoint's answer (a server-to-server TLS call with the client secret and
the PKCE verifier) and still validated in full, as OpenID Connect Core section 3.1.3.7 asks: the signature
against the provider's JWKS (RS256 only; cached for an hour, refetched at most once a minute when an unknown
``kid`` appears, so a key rotation is followed and a flood of forged ``kid`` values cannot flood the provider),
the issuer, the audience (this client's id, as the only one), the expiry and issue time, and the nonce, in
constant time. A token that says ``alg: none`` or HS256 is refused: the algorithm is fixed, not read from the
token.

The providers' endpoints are fixed here (they do not change; OpenID discovery documents are not fetched, so
there is no document an attacker could redirect). Microsoft's issuer carries the tenant of the account
(``https://login.microsoftonline.com/<tid>/v2.0``), so with the ``common`` tenant it is checked against the
token's own ``tid``; Apple's client secret is a short ES256 JWT signed with the operator's key file.

The network goes through ``Http`` so the tests put a fake provider in its place (signed test tokens, a local
JWKS): nothing in the tests reaches the Internet.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

import jwt
from cryptography.hazmat.primitives.serialization import load_pem_private_key

from .config import ConfigError, OidcClient, Settings

LEEWAY_S = 60
JWKS_TTL_S = 3600
JWKS_MIN_REFETCH_S = 60
HTTP_TIMEOUT_S = 10
MAX_BODY = 1 << 20          # no provider answer is bigger than a megabyte
MAX_SUBJECT = 255
MSA_TENANT = "9188040d-6c67-4c5b-b112-36a304b66dad"   # the tenant id of Microsoft personal accounts
APPLE_ISSUER = "https://appleid.apple.com"
PROVIDER_LABELS = {"google": "Google", "microsoft": "Microsoft", "apple": "Apple"}


class OidcError(Exception):
    """A social login failed; ``code`` is the short reason the page can show (never the provider's text)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Http(Protocol):
    async def post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]: ...

    async def get_json(self, url: str) -> dict[str, Any]: ...


class UrllibHttp:
    """The real network: https only, a timeout, a size cap, JSON answers, in a worker thread."""

    @staticmethod
    def _call(request: urllib.request.Request) -> dict[str, Any]:
        if not request.full_url.startswith("https://"):
            raise OidcError("provider_unreachable")
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_S) as response:  # noqa: S310  (https only)
                body = response.read(MAX_BODY + 1)
        except urllib.error.HTTPError as e:
            raise OidcError("token_exchange_failed" if e.code in (400, 401) else "provider_unreachable") from None
        except (urllib.error.URLError, OSError, ValueError):
            raise OidcError("provider_unreachable") from None
        if len(body) > MAX_BODY:
            raise OidcError("provider_unreachable")
        try:
            data = json.loads(body)
        except ValueError:
            raise OidcError("provider_unreachable") from None
        if not isinstance(data, dict):
            raise OidcError("provider_unreachable")
        return data

    async def post_form(self, url: str, data: dict[str, str]) -> dict[str, Any]:
        request = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode("ascii"), method="POST",
                                         headers={"Content-Type": "application/x-www-form-urlencoded",
                                                  "Accept": "application/json"})
        return await asyncio.to_thread(self._call, request)

    async def get_json(self, url: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._call, urllib.request.Request(url, headers={"Accept": "application/json"}))


@dataclass(frozen=True)
class Endpoints:
    authorize: str
    token: str
    jwks: str
    scope: Optional[str]


def endpoints(client: OidcClient) -> Endpoints:
    if client.provider == "google":
        return Endpoints("https://accounts.google.com/o/oauth2/v2/auth", "https://oauth2.googleapis.com/token",
                         "https://www.googleapis.com/oauth2/v3/certs", "openid")
    if client.provider == "microsoft":
        base = f"https://login.microsoftonline.com/{client.tenant}"
        return Endpoints(f"{base}/oauth2/v2.0/authorize", f"{base}/oauth2/v2.0/token",
                         "https://login.microsoftonline.com/common/discovery/v2.0/keys", "openid")
    return Endpoints(f"{APPLE_ISSUER}/auth/authorize", f"{APPLE_ISSUER}/auth/token", f"{APPLE_ISSUER}/auth/keys",
                     None)


def new_verifier() -> str:
    """A PKCE code verifier: 64 URL-safe characters (RFC 7636 section 4.1 wants 43-128)."""
    return secrets.token_urlsafe(48)


def pkce_challenge(verifier: str) -> str:
    """``BASE64URL(SHA256(verifier))`` without padding (RFC 7636 section 4.2, S256)."""
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


class OidcService:
    """The configured providers, their JWKS cache and the calls to them (``app.state.oidc``)."""

    def __init__(self, settings: Settings, http: Optional[Http] = None, clock: Callable[[], float] = time.time) -> None:
        self.clients = {c.provider: c for c in settings.oidc}
        self.http: Http = http or UrllibHttp()
        self.clock = clock
        self._jwks: dict[str, tuple[float, dict[str, Any]]] = {}     # url -> (fetched at, {kid: jwk})
        self._locks: dict[str, asyncio.Lock] = {}
        self._apple_key: Any = None
        apple = self.clients.get("apple")
        if apple is not None and apple.key_file:
            try:
                with open(apple.key_file, "rb") as f:
                    self._apple_key = load_pem_private_key(f.read(), password=None)
            except (OSError, ValueError, TypeError) as e:
                raise ConfigError(f"ATALAIA_OIDC_APPLE_KEY_FILE is not a readable PEM private key ({type(e).__name__})"
                                  ) from None

    def providers(self) -> list[str]:
        return [p for p in PROVIDER_LABELS if p in self.clients]

    def authorization_url(self, provider: str, redirect_uri: str, state: str, nonce: str, challenge: str) -> str:
        client = self.clients[provider]
        ep = endpoints(client)
        params = {"client_id": client.client_id, "response_type": "code", "redirect_uri": redirect_uri,
                  "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
        if ep.scope:
            params["scope"] = ep.scope
        if provider in ("google", "microsoft"):
            params["prompt"] = "select_account"
        return f"{ep.authorize}?{urllib.parse.urlencode(params)}"

    def client_secret(self, provider: str) -> str:
        client = self.clients[provider]
        if provider != "apple":
            assert client.client_secret is not None
            return client.client_secret
        now = int(self.clock())
        return jwt.encode({"iss": client.team_id, "iat": now, "exp": now + 300, "aud": APPLE_ISSUER,
                           "sub": client.client_id}, self._apple_key, algorithm="ES256",
                          headers={"kid": client.key_id})

    async def exchange(self, provider: str, code: str, redirect_uri: str, verifier: str) -> str:
        """The ID token the token endpoint gives for an authorization code."""
        client = self.clients[provider]
        answer = await self.http.post_form(endpoints(client).token, {
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
            "client_id": client.client_id, "client_secret": self.client_secret(provider),
            "code_verifier": verifier})
        token = answer.get("id_token")
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise OidcError("token_exchange_failed")
        return token

    async def _key(self, url: str, kid: str) -> Any:
        """The provider's public key for ``kid``: from the cache, or after one refetch if it is not there."""
        lock = self._locks.setdefault(url, asyncio.Lock())
        async with lock:
            now = self.clock()
            cached = self._jwks.get(url)
            fresh = cached is not None and now - cached[0] < JWKS_TTL_S
            if fresh and kid in cached[1]:
                jwk = cached[1][kid]
            elif cached is not None and now - cached[0] < JWKS_MIN_REFETCH_S:
                raise OidcError("id_token_invalid")        # an unknown kid right after a fetch: not a rotation
            else:
                document = await self.http.get_json(url)
                keys = {k["kid"]: k for k in document.get("keys", []) if isinstance(k, dict) and "kid" in k}
                self._jwks[url] = (now, keys)
                if kid not in keys:
                    raise OidcError("id_token_invalid")
                jwk = keys[kid]
        try:
            return jwt.PyJWK(jwk).key
        except (jwt.PyJWTError, ValueError, KeyError):
            raise OidcError("id_token_invalid") from None

    async def validate(self, provider: str, id_token: str, nonce: str) -> str:
        """The subject of a valid ID token, else ``OidcError``."""
        client = self.clients[provider]
        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.PyJWTError:
            raise OidcError("id_token_invalid") from None
        kid = header.get("kid")
        if header.get("alg") != "RS256" or not isinstance(kid, str) or not kid:
            raise OidcError("id_token_invalid")
        key = await self._key(endpoints(client).jwks, kid)
        try:
            claims = jwt.decode(id_token, key, algorithms=["RS256"], audience=client.client_id, leeway=LEEWAY_S,
                                options={"require": ["exp", "iat", "iss", "aud", "sub"], "verify_iss": False})
        except jwt.PyJWTError:
            raise OidcError("id_token_invalid") from None
        if not self._issuer_ok(client, claims):
            raise OidcError("id_token_invalid")
        got = claims.get("nonce")
        if not isinstance(got, str) or not hmac.compare_digest(got.encode(), nonce.encode()):
            raise OidcError("id_token_invalid")
        aud = claims["aud"]
        if isinstance(aud, list) and (len(aud) != 1 or claims.get("azp") not in (None, client.client_id)):
            raise OidcError("id_token_invalid")
        subject = claims["sub"]
        if not isinstance(subject, str) or not subject or len(subject) > MAX_SUBJECT or subject != subject.strip():
            raise OidcError("id_token_invalid")
        return subject

    @staticmethod
    def _issuer_ok(client: OidcClient, claims: dict[str, Any]) -> bool:
        iss = claims.get("iss")
        if client.provider == "google":
            return iss in ("https://accounts.google.com", "accounts.google.com")
        if client.provider == "apple":
            return iss == APPLE_ISSUER
        tid = claims.get("tid")
        if not isinstance(tid, str) or iss != f"https://login.microsoftonline.com/{tid}/v2.0":
            return False
        if client.tenant == "consumers":
            return tid == MSA_TENANT
        if client.tenant == "organizations":
            return tid != MSA_TENANT
        if client.tenant != "common":
            return tid == client.tenant
        return True
