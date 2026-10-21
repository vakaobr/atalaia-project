# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Firmware releases: the signed manifest, versions, the image's descriptors and a box's report.

One Python implementation, shared (P4R16) by the site server's catalogue
(``server/atalaia_server/firmware.py``, plan phase 19), the field controller's
update service (``firmware_updates.py``) and the signing tool
(``tools/firmware_release.py``). The Field Box's C side
(``firmware/esp32/main/fw_update.c``) checks the same shared vectors
(``protocol/vectors/firmware.json``); the format is ``protocol/firmware-update.md``.

A release key signs, with Ed25519 (RFC 8032), exactly this text (the ``manifest``)::

    atalaia-firmware-release-v1
    platform=esp32s3
    version=0.4.0
    size=1572864
    sha256=<64 lower-case hex digits>

with a line feed after each line, UTF-8. A box fetches the ``release text``:
the manifest followed by ``signature=<base64 of the 64 bytes>`` and a line feed.

Platforms are HELLO's (``protocol/schema/messages.yaml``): ``esp32`` (0),
``esp32s3`` (1), ``linux`` (2), ``android`` (3). Versions are
``MAJOR.MINOR.PATCH`` with an optional pre-release (``-rc.1``), ordered as
Semantic Versioning 2.0.0 section 11 orders them.

No web stack here: the site server imports this module with FastAPI blocked
(``server/tests/test_shared_imports.py``).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import re
import struct
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MANIFEST_HEADER = "atalaia-firmware-release-v1"
PLATFORMS = {0: "esp32", 1: "esp32s3", 2: "linux", 3: "android"}  # HELLO's platform byte
PLATFORM_NAMES = tuple(PLATFORMS.values())
VERSION = re.compile(r"(\d{1,4})\.(\d{1,4})\.(\d{1,4})(?:-([0-9A-Za-z][0-9A-Za-z.]{0,19}))?")
VERSION_MAX = 35  # bytes: 4.4.4 digits, a hyphen and 20 characters of pre-release
SHA256 = re.compile(r"[0-9a-f]{64}")
KEY_LEN = 32
SIGNATURE_LEN = 64

# The ESP-IDF application image (esp_app_format): a 24-byte image header and an
# 8-byte segment header, then the first segment, which starts with esp_app_desc_t
# (256 bytes: magic, secure version, two reserved words, version[32],
# project_name[32], ...) and, right after it, the Atalaia descriptor
# (firmware/esp32/main/fw_desc.c: "ATFW", a format byte, three reserved, variant[12],
# board[16]).
ESP_IMAGE_MAGIC = 0xE9
APP_DESC_OFFSET = 32
APP_DESC_MAGIC = 0xABCD5432
APP_DESC_SIZE = 256
ATALAIA_DESC_OFFSET = APP_DESC_OFFSET + APP_DESC_SIZE
ATALAIA_DESC_MAGIC = b"ATFW"
ATALAIA_DESC_FORMAT = 1
ATALAIA_DESC_SIZE = 36
IMAGE_HEAD = ATALAIA_DESC_OFFSET + ATALAIA_DESC_SIZE  # bytes a box reads before it trusts the stream
PROJECT_NAME = "atalaia_esp32"

# A box's report on an update it tried (protocol/firmware-update.md).
REPORT_HEADER = "atalaia-firmware-report-v1"
REPORT_RESULTS = ("installed", "busy", "bad_offer", "no_key", "no_link", "no_wifi", "unreachable",
                  "bad_release", "bad_signature", "wrong_platform", "not_newer", "too_big",
                  "bad_image", "wrong_board", "download", "bad_hash", "flash", "battery", "cancelled")
RELEASE_ID = re.compile(r"[0-9a-f]{16}")


class ReleaseError(ValueError):
    """Something a release, an image or a report must not be: ``code`` says what."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def manifest(platform: str, version: str, size: int, sha256: str) -> bytes:
    """The exact bytes a release key signs."""
    return (f"{MANIFEST_HEADER}\nplatform={platform}\nversion={version}\nsize={size}\nsha256={sha256}\n"
            ).encode("utf-8")


def release_text(platform: str, version: str, size: int, sha256: str, signature: str) -> bytes:
    """What a box fetches: the manifest, then the signature (base64) on its own line."""
    return manifest(platform, version, size, sha256) + f"signature={signature}\n".encode("ascii")


def key_id(public_key_b64: str) -> str:
    """A key's id: the first 16 hex digits of the SHA-256 of its 32 bytes."""
    return hashlib.sha256(base64.b64decode(public_key_b64)).hexdigest()[:16]


def public_key_bytes(value: Any) -> Optional[bytes]:
    """A release public key as configured (standard base64 of 32 bytes), or None."""
    if not isinstance(value, str):
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == KEY_LEN else None


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


def compare_versions(a: str, b: str) -> int:
    """-1, 0 or 1 as a sorts before, with or after b; ValueError for a version of another form."""
    ka, kb = version_key(a), version_key(b)
    if ka is None or kb is None:
        raise ValueError("not a firmware version")
    return (ka > kb) - (ka < kb)


def platform_name(value: Any) -> Optional[str]:
    """A node's platform as the sync carries it (HELLO's byte, as text) or a catalogue name, as a name."""
    if isinstance(value, str) and value in PLATFORM_NAMES:
        return value
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return PLATFORMS.get(value)
    return None


def signature_bytes(value: Any) -> Optional[bytes]:
    if not isinstance(value, str) or len(value) != 88:
        return None
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == SIGNATURE_LEN else None


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
        raw = public_key_bytes(key)
        if raw is not None and verify_signature(raw, message, sig):
            return key_id(key)
    return None


# ---- the image -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageInfo:
    """What an ESP-IDF application image says about itself."""

    version: str
    project: str
    variant: str
    board: str


def _cstr(raw: bytes) -> Optional[str]:
    """A NUL-terminated ASCII field (the NUL inside the field, the rest zeros), or None."""
    end = raw.find(b"\x00")
    if end < 0 or raw[end:].strip(b"\x00") or not raw[:end].isascii():
        return None
    return raw[:end].decode("ascii")


def image_info(head: bytes) -> ImageInfo:
    """The version, project, variant and board an image's first ``IMAGE_HEAD`` bytes declare.

    ReleaseError("bad_image") for anything that is not an Atalaia firmware image: no ESP image
    magic, no application descriptor, no Atalaia descriptor, a field that is not plain text.
    """
    if len(head) < IMAGE_HEAD or head[0] != ESP_IMAGE_MAGIC:
        raise ReleaseError("bad_image", "not an ESP32 application image")
    magic, = struct.unpack_from("<I", head, APP_DESC_OFFSET)
    if magic != APP_DESC_MAGIC:
        raise ReleaseError("bad_image", "no application descriptor")
    version = _cstr(head[APP_DESC_OFFSET + 16:APP_DESC_OFFSET + 48])
    project = _cstr(head[APP_DESC_OFFSET + 48:APP_DESC_OFFSET + 80])
    d = head[ATALAIA_DESC_OFFSET:ATALAIA_DESC_OFFSET + ATALAIA_DESC_SIZE]
    if d[:4] != ATALAIA_DESC_MAGIC or d[4] != ATALAIA_DESC_FORMAT:
        raise ReleaseError("bad_image", "no Atalaia descriptor (an image from before OTA, or not Atalaia's)")
    variant, board = _cstr(d[8:20]), _cstr(d[20:36])
    if version is None or project is None or variant is None or board is None:
        raise ReleaseError("bad_image", "a descriptor field is not plain text")
    return ImageInfo(version, project, variant, board)


# ---- a box's report ------------------------------------------------------------------------------


def report_body(game: int, node: int, release: str, result: str, version: str) -> bytes:
    """The text a box posts after an update attempt (it signs it with the game key)."""
    return (f"{REPORT_HEADER}\ngame={game}\nnode={node}\nrelease={release}\nresult={result}\n"
            f"version={version}\n").encode("ascii")


def report_mac(game_key: bytes, body: bytes) -> str:
    """HMAC-SHA256 of the report with the game key, lower-case hex (the X-Atalaia-Mac header)."""
    return hmac.new(game_key, body, hashlib.sha256).hexdigest()


def parse_report(body: bytes) -> dict[str, Any]:
    """A report's fields (ReleaseError("bad_report") otherwise): exactly the lines of report_body."""
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError:
        raise ReleaseError("bad_report", "not ASCII") from None
    lines = text.split("\n")
    names = ("game", "node", "release", "result", "version")
    if len(lines) != len(names) + 2 or lines[0] != REPORT_HEADER or lines[-1] != "":
        raise ReleaseError("bad_report", "not a report")
    out: dict[str, Any] = {}
    for name, line in zip(names, lines[1:-1]):
        key, sep, value = line.partition("=")
        if key != name or not sep:
            raise ReleaseError("bad_report", f"line {name}")
        out[name] = value
    for name in ("game", "node"):
        if not re.fullmatch(r"[1-9][0-9]{0,4}", out[name]) or int(out[name]) > 0xFFFE:
            raise ReleaseError("bad_report", name)
        out[name] = int(out[name])
    if not RELEASE_ID.fullmatch(out["release"]):
        raise ReleaseError("bad_report", "release")
    if out["result"] not in REPORT_RESULTS:
        raise ReleaseError("bad_report", "result")
    if version_key(out["version"]) is None:
        raise ReleaseError("bad_report", "version")
    if body != report_body(out["game"], out["node"], out["release"], out["result"], out["version"]):
        raise ReleaseError("bad_report", "not in its canonical form")
    return out
