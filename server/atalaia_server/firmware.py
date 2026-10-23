# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The firmware catalogue's rules (plan phase 19; RESEARCH section 8, decisions S19-5 to S19-7).

A list only: the site server stores no image and sends nothing to a
controller or a box; the field controller holds the images it offers to its
boxes (``controller/atalaia_controller/firmware_updates.py``, decision FU3-3).
An entry names an image by its platform, version, size and SHA-256, and must
carry an Ed25519 signature over exactly these, made with a release key the
server trusts (``ATALAIA_FIRMWARE_KEYS``): with no key configured the
catalogue takes nothing. The signed text (``manifest``) is::

    atalaia-firmware-release-v1
    platform=esp32s3
    version=0.4.0
    size=1572864
    sha256=<64 lower-case hex digits>

with a line feed after each line, UTF-8. The manifest, versions, platforms and
the signature check are the shared ``atalaia_controller.firmware_release``
(the field controller and ``tools/firmware_release.py`` use the same code;
the Field Box's C side checks the same vectors). Entries are checked again
whenever they are listed, so removing a key from the setting withdraws
everything it signed. This check guards the list; it never replaces the box's
own check: a box verifies the image's signature itself, with keys in its
firmware, before it installs anything (``protocol/firmware-update.md``).
"""

from __future__ import annotations

from typing import Any

from atalaia_controller.firmware_release import (  # noqa: F401  (the catalogue's names, re-exported)
    MANIFEST_HEADER,
    PLATFORM_NAMES,
    PLATFORMS,
    SHA256,
    VERSION,
    key_id,
    manifest,
    platform_name,
    signature_bytes,
    signer,
    verify_signature,
    firmware_version_key,
    version_key,
)

MAX_SIZE = 64 * 1024 * 1024  # bytes: far above an ESP32-S3 app slot (2 MiB) or a phone's package


class FirmwareError(ValueError):
    """An entry the catalogue refuses: ``code`` and the ``field`` it is about."""

    def __init__(self, code: str, field: str = "") -> None:
        super().__init__(f"{code} at {field or 'the entry'}")
        self.code = code
        self.field = field


def check_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """An entry's fields in form (not its signature): platform, version, size, sha256, signature."""
    if entry.get("platform") not in PLATFORM_NAMES:
        raise FirmwareError("bad_platform", "platform")
    if not isinstance(entry.get("version"), str) or firmware_version_key(entry["version"]) is None:
        raise FirmwareError("bad_version", "version")
    size = entry.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or not 1 <= size <= MAX_SIZE:
        raise FirmwareError("bad_size", "size")
    if not isinstance(entry.get("sha256"), str) or not SHA256.fullmatch(entry["sha256"]):
        raise FirmwareError("bad_sha256", "sha256")
    if signature_bytes(entry.get("signature")) is None:
        raise FirmwareError("bad_signature", "signature")
    return entry



