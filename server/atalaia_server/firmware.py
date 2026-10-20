# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The firmware catalogue's rules (plan phase 19; RESEARCH section 8, decisions S19-5 to S19-7).

A list only: OTA is not built (``firmware/esp32/README.md``), so the site
server stores no image and sends nothing to a controller or a box. An entry
names an image by its platform, version, size and SHA-256, and must carry an
Ed25519 signature over exactly these, made with a release key the server
trusts (``ATALAIA_FIRMWARE_KEYS``): with no key configured the catalogue takes
nothing. The signed text (``manifest``) is::

    atalaia-firmware-release-v1
    platform=esp32s3
    version=0.4.0
    size=1572864
    sha256=<64 lower-case hex digits>

with a line feed after each line, UTF-8. Entries are checked again whenever
they are listed, so removing a key from the setting withdraws everything it
signed. This check guards the list; it never replaces the box's own check: when
OTA is built, a box must verify the image's signature itself, with keys in its
firmware, before it installs anything (the A/B partitions of RESEARCH section 8).

Platforms are HELLO's (``protocol/schema/messages.yaml``): ``esp32`` (0),
``esp32s3`` (1), ``linux`` (2), ``android`` (3). Versions are
``MAJOR.MINOR.PATCH`` with an optional pre-release (``-rc.1``), as
``atalaia_version()`` makes them; a pre-release is never "the latest".
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from typing import Any, Iterable, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MANIFEST_HEADER = "atalaia-firmware-release-v1"
PLATFORMS = {0: "esp32", 1: "esp32s3", 2: "linux", 3: "android"}  # HELLO's platform byte
PLATFORM_NAMES = tuple(PLATFORMS.values())
VERSION = re.compile(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-([0-9A-Za-z][0-9A-Za-z.]{0,19}))?")
SHA256 = re.compile(r"[0-9a-f]{64}")
MAX_SIZE = 64 * 1024 * 1024  # bytes: far above an ESP32-S3 app slot (2 MiB) or a phone's package


class FirmwareError(ValueError):
    """An entry the catalogue refuses: ``code`` and the ``field`` it is about."""

    def __init__(self, code: str, field: str = "") -> None:
        super().__init__(f"{code} at {field or 'the entry'}")
        self.code = code
        self.field = field


def manifest(platform: str, version: str, size: int, sha256: str) -> bytes:
    """The exact bytes a release key signs."""
    return (f"{MANIFEST_HEADER}\nplatform={platform}\nversion={version}\nsize={size}\nsha256={sha256}\n"
            ).encode("utf-8")


def key_id(public_key_b64: str) -> str:
    """A key's id: the first 16 hex digits of the SHA-256 of its 32 bytes."""
    return hashlib.sha256(base64.b64decode(public_key_b64)).hexdigest()[:16]


def version_key(version: str) -> Optional[tuple[Any, ...]]:
    """A sortable key, or None for a version of another form. As Semantic Versioning 2.0.0 section 11 orders
    them: a pre-release sorts before its release, its identifiers compared one by one, numbers as numbers and
    before words (``1.0.0-rc.2`` < ``1.0.0-rc.10`` < ``1.0.0``)."""
    m = VERSION.fullmatch(version or "") if isinstance(version, str) else None
    if m is None:
        return None
    pre = m.group(4)
    if pre is not None and "" in pre.split("."):
        return None
    ids = tuple((0, int(p)) if p.isdigit() else (1, p) for p in pre.split(".")) if pre else ()
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if pre else 1, ids


def platform_name(value: Any) -> Optional[str]:
    """A node's platform as the sync carries it (HELLO's byte, as text) or a catalogue name, as a name."""
    if isinstance(value, str) and value in PLATFORM_NAMES:
        return value
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return PLATFORMS.get(value)
    return None


def check_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """An entry's fields in form (not its signature): platform, version, size, sha256, signature."""
    if entry.get("platform") not in PLATFORM_NAMES:
        raise FirmwareError("bad_platform", "platform")
    if not isinstance(entry.get("version"), str) or version_key(entry["version"]) is None:
        raise FirmwareError("bad_version", "version")
    size = entry.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_SIZE:
        raise FirmwareError("bad_size", "size")
    if not isinstance(entry.get("sha256"), str) or not SHA256.fullmatch(entry["sha256"]):
        raise FirmwareError("bad_sha256", "sha256")
    if signature_bytes(entry.get("signature")) is None:
        raise FirmwareError("bad_signature", "signature")
    return entry


def signature_bytes(value: Any) -> Optional[bytes]:
    if not isinstance(value, str) or len(value) != 88:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == 64 else None


def verify_signature(public_key: bytes, message: bytes, signature: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        return True
    except (InvalidSignature, ValueError):
        return False


def signer(keys: Iterable[str], platform: str, version: str, size: int, sha256: str,
           signature: str) -> Optional[str]:
    """The id of the trusted key whose signature this is, or None (no trusted key signed exactly this)."""
    sig = signature_bytes(signature)
    if sig is None:
        return None
    message = manifest(platform, version, size, sha256)
    for key in keys:
        if verify_signature(base64.b64decode(key), message, sig):
            return key_id(key)
    return None
