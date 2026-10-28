# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Passkeys: WebAuthn registration and authentication through the ``webauthn`` library (Duo Labs, decision LG-2).

The library does the protocol (clientDataJSON, authenticator data, attestation and assertion signatures,
origin and RP ID checks, the signature counter); this module fixes the choices the server makes:

- **RP ID** is the host name of the address the account's pages are served from (a hosted field's
  ``<slug>.<domain>``), the origin is that address; a passkey made at one host name is not accepted at another.
- **User verification is required** (PIN, biometric) at registration and at every use, and the credential is
  discoverable (a resident key), so a login needs no username. A passkey login therefore proves two factors, and
  counts as both for the roles that need a second factor (LG-4).
- **No attestation**: the server does not ask which authenticator model it is, so it keeps nothing that
  identifies the device (``attestation: none``).
- The **challenge** is made here and carried in a signed token (``tokens.make_webauthn_challenge``), not kept in
  the database; it expires after 5 minutes and is accepted once.
- The signature counter is checked by the library when either side is non-zero (a clone shows as a counter that
  did not move forward); synced passkeys report zero and are accepted.
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Optional
from urllib.parse import urlsplit

from webauthn import (generate_authentication_options, generate_registration_options, options_to_json,
                      verify_authentication_response, verify_registration_response)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (AttestationConveyancePreference, AuthenticatorSelectionCriteria,
                                      PublicKeyCredentialDescriptor, ResidentKeyRequirement,
                                      UserVerificationRequirement)

RP_NAME = "Atalaia"
MAX_PER_ACCOUNT = 20
MAX_CREDENTIAL_JSON = 16384


class PasskeyError(Exception):
    """The browser's answer is not a valid registration or assertion."""


def rp_id_of(origin: str) -> str:
    host = urlsplit(origin).hostname
    if not host:
        raise PasskeyError("no host")
    return host


def registration_options(origin: str, user_id: bytes, username: str,
                         existing: list[bytes]) -> tuple[dict[str, Any], bytes]:
    """The options for ``navigator.credentials.create`` and the challenge to remember."""
    challenge = secrets.token_bytes(32)
    options = generate_registration_options(
        rp_id=rp_id_of(origin), rp_name=RP_NAME, user_id=user_id, user_name=username, user_display_name=username,
        challenge=challenge, attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in existing])
    return json.loads(options_to_json(options)), challenge


def verify_registration(credential: dict[str, Any], challenge: bytes, origin: str) -> Any:
    """The library's ``VerifiedRegistration`` (credential id, public key, sign count...) or ``PasskeyError``."""
    _check_size(credential)
    try:
        return verify_registration_response(credential=credential, expected_challenge=challenge,
                                            expected_rp_id=rp_id_of(origin), expected_origin=origin,
                                            require_user_verification=True)
    except Exception as e:  # noqa: BLE001  (the library raises its own and parsing errors; all mean "refused")
        raise PasskeyError(type(e).__name__) from None


def authentication_options(origin: str, allow: Optional[list[bytes]] = None) -> tuple[dict[str, Any], bytes]:
    """The options for ``navigator.credentials.get``: with ``allow`` the account's own credentials (a step-up),
    without it any discoverable one (a login)."""
    challenge = secrets.token_bytes(32)
    options = generate_authentication_options(
        rp_id=rp_id_of(origin), challenge=challenge, user_verification=UserVerificationRequirement.REQUIRED,
        allow_credentials=[PublicKeyCredentialDescriptor(id=c) for c in allow] if allow else None)
    return json.loads(options_to_json(options)), challenge


def credential_id_of(credential: dict[str, Any]) -> bytes:
    """The credential id the browser says it used (checked against the stored credential's by the library)."""
    _check_size(credential)
    try:
        raw = credential["rawId"]
        if not isinstance(raw, str):
            raise TypeError
        return base64url_to_bytes(raw)
    except (KeyError, TypeError, ValueError):
        raise PasskeyError("no credential id") from None


def user_handle_of(credential: dict[str, Any]) -> Optional[bytes]:
    try:
        handle = credential["response"].get("userHandle")
        return base64url_to_bytes(handle) if handle else None
    except (KeyError, TypeError, ValueError, AttributeError):
        raise PasskeyError("bad user handle") from None


def verify_authentication(credential: dict[str, Any], challenge: bytes, origin: str, public_key: bytes,
                          sign_count: int) -> Any:
    """The library's ``VerifiedAuthentication`` (``new_sign_count``...) or ``PasskeyError``."""
    _check_size(credential)
    try:
        return verify_authentication_response(
            credential=credential, expected_challenge=challenge, expected_rp_id=rp_id_of(origin),
            expected_origin=origin, credential_public_key=public_key, credential_current_sign_count=sign_count,
            require_user_verification=True)
    except Exception as e:  # noqa: BLE001
        raise PasskeyError(type(e).__name__) from None


def _check_size(credential: dict[str, Any]) -> None:
    if not isinstance(credential, dict) or len(json.dumps(credential)) > MAX_CREDENTIAL_JSON:
        raise PasskeyError("bad credential")
