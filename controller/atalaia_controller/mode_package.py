# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed mode packages: the archive, the signed manifest, the registry index and revocation.

One Python implementation (decision P5R-7), shared by the signing tool
(``tools/mode_package.py``), the field controller's import of signed packages
(``signed_modes.py``, phase 5 plan phase 6) and, later, the registry's CI. The
format is ``protocol/mode-packages.md``; the shared vectors are
``protocol/vectors/mode_package.json``. Signing reuses the firmware releases'
scheme and code (``firmware_release.py``): Ed25519 (RFC 8032), base64
signatures, key ids of 16 hex digits.

**The archive** is a POSIX ustar tar of the package's files under one root
folder named after the mode's id, in one canonical form, so that the same files
always give the same bytes and SHA-256: regular files only, sorted by name,
mode 0644, owner 0, time 0, no user or group names, names of at most 100 bytes
(no prefix field), ending with two zero blocks and nothing after them. Only the
files the controller takes (``mode.yaml``, ``node.lua``, ``field.lua``,
``assets/...``), UTF-8 text. A reader takes only this form: any other archive is
refused (``bad_archive``), so nothing in it can name a path outside its root, a
link or a device.

**The manifest** a mode key signs, exactly (a line feed after each line)::

    atalaia-mode-package-v1
    id=org.club.my-mode
    version=0.1.0
    kind=mode
    min_tier=reduced
    size=4608
    sha256=<64 lower-case hex digits of the archive>

``kind`` is ``mode``, ``modifier``, ``role`` or ``scenario`` (a box never takes
a scenario); ``min_tier`` is ``reduced`` or ``full`` (decision P5B-10). The
*release text* a box will fetch (plan phase 13) is the manifest followed by
``signature=<base64>`` and a line feed.

Verifying fails closed: every check below must pass, in this order, or
``PackageError`` says which failed (``code``): the release's fields, the size
limit, the archive's size and SHA-256 as signed, a signature by one of the
trusted keys (``no_key`` when none of them is the key it names, else
``bad_signature``), the key not revoked, the archive's form, and the archive's
own ``mode.yaml`` agreeing with the manifest (id, version, kind, tier) and naming
an approved licence (ADR-P5-5).

No web stack here: like ``firmware_release.py`` it may be imported where
FastAPI is not.
"""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import yaml

from . import firmware_release as fr

MANIFEST_HEADER = "atalaia-mode-package-v1"
KINDS = ("mode", "modifier", "role", "scenario")
BOX_KINDS = ("mode", "modifier", "role")  # what a box may take (P5B-10)
TIERS = ("reduced", "full")
# The approved licences of community modes (ADR-P5-5); the editor offers the same.
LICENCES = ("GPL-3.0-or-later", "LGPL-3.0-or-later", "MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause",
            "CC0-1.0")
MAX_PACKAGE_BYTES = 1_000_000  # the controller's limit for a package (decision P5-6)
MAX_FILES = 64
MODE_ID = re.compile(r"[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+")
MODE_ID_MAX = 63  # bytes: a game's whole id is at most 63
FILE_NAME = re.compile(r"(mode\.yaml|node\.lua|field\.lua|assets/[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*)")
KEY_ID = re.compile(r"[0-9a-f]{16}")
BLOCK = 512
NAME_MAX = 100


class PackageError(ValueError):
    """Something a package, a release, an index or a revocation list must not be: ``code`` says what."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


# ---- the archive -------------------------------------------------------------------------------


def _octal(value: int, width: int) -> bytes:
    """A ustar number field: width - 1 octal digits, then NUL."""
    return format(value, "o").rjust(width - 1, "0").encode("ascii") + b"\0"


def _header(name: bytes, size: int) -> bytes:
    h = bytearray(BLOCK)
    h[0:len(name)] = name
    h[100:108] = _octal(0o644, 8)
    h[108:116] = _octal(0, 8)
    h[116:124] = _octal(0, 8)
    h[124:136] = _octal(size, 12)
    h[136:148] = _octal(0, 12)
    h[148:156] = b" " * 8
    h[156:157] = b"0"
    h[257:263] = b"ustar\0"
    h[263:265] = b"00"
    h[329:337] = _octal(0, 8)
    h[337:345] = _octal(0, 8)
    h[148:156] = format(sum(h), "o").rjust(6, "0").encode("ascii") + b"\0 "
    return bytes(h)


def check_file_name(name: str) -> None:
    # No empty segment and none starting with a dot: no "..", no ".", no hidden files.
    if not isinstance(name, str) or not FILE_NAME.fullmatch(name) or any(
            part == "" or part.startswith(".") for part in name.split("/")):
        raise PackageError("bad_archive", f"file {name!r} is not allowed in a mode package")


def pack(mode_id: str, files: dict[str, str]) -> bytes:
    """The canonical archive of a package's files (name -> text) under the root folder ``mode_id``."""
    if not isinstance(mode_id, str) or not MODE_ID.fullmatch(mode_id) or len(mode_id) > MODE_ID_MAX:
        raise PackageError("bad_archive", "the id must look like org.club.name, at most 63 bytes")
    if not files or len(files) > MAX_FILES:
        raise PackageError("bad_archive", f"a package has 1 to {MAX_FILES} files")
    out = bytearray()
    for name in sorted(files):
        check_file_name(name)
        text = files[name]
        if not isinstance(text, str) or "\0" in text:
            raise PackageError("bad_archive", f"{name}: files are text")
        data = text.encode("utf-8")
        path = f"{mode_id}/{name}".encode("ascii")
        if len(path) > NAME_MAX:
            raise PackageError("bad_archive", f"{name}: the path is longer than {NAME_MAX} bytes")
        out += _header(path, len(data)) + data + b"\0" * (-len(data) % BLOCK)
    out += b"\0" * (2 * BLOCK)
    if len(out) > MAX_PACKAGE_BYTES:
        raise PackageError("too_big", f"the archive is {len(out)} bytes; at most {MAX_PACKAGE_BYTES}")
    return bytes(out)


def _field_octal(raw: bytes, what: str) -> int:
    digits = raw.rstrip(b"\0")
    if not digits or not re.fullmatch(rb"[0-7]+", digits):
        raise PackageError("bad_archive", f"{what} is not an octal number")
    return int(digits, 8)


def unpack(archive: bytes, mode_id: Optional[str] = None, limit: int = MAX_PACKAGE_BYTES) -> tuple[str, dict[str, str]]:
    """The root (the package's id) and files of a canonical archive; PackageError otherwise.

    ``mode_id``, when given, is the root the archive must have. Nothing is written anywhere:
    the files come back as text.
    """
    if not isinstance(archive, (bytes, bytearray)):
        raise PackageError("bad_archive", "not bytes")
    if len(archive) > limit:
        raise PackageError("too_big", f"the archive is {len(archive)} bytes; at most {limit}")
    if len(archive) % BLOCK or len(archive) < 2 * BLOCK:
        raise PackageError("bad_archive", "not a whole number of 512-byte blocks")
    files: dict[str, str] = {}
    root: Optional[str] = None
    pos = 0
    while True:
        if pos + BLOCK > len(archive):
            raise PackageError("bad_archive", "no end of archive")
        head = bytes(archive[pos:pos + BLOCK])
        if head == b"\0" * BLOCK:
            break
        if head[257:265] != b"ustar\x0000":
            raise PackageError("bad_archive", "not a POSIX ustar archive")
        expected = _field_octal(head[148:155], "the checksum")
        if expected != sum(head[:148]) + 8 * 32 + sum(head[156:]):
            raise PackageError("bad_archive", "a header's checksum is wrong")
        if head[156:157] != b"0":
            raise PackageError("bad_archive", "only regular files (no folders, links or devices)")
        raw_name = head[0:NAME_MAX].rstrip(b"\0")
        if b"\0" in raw_name or head[345:500].strip(b"\0"):
            raise PackageError("bad_archive", "a name with a prefix or a NUL inside")
        try:
            path = raw_name.decode("ascii")
        except UnicodeDecodeError:
            raise PackageError("bad_archive", "a name that is not ASCII") from None
        top, sep, name = path.partition("/")
        if not sep or (root is not None and top != root):
            raise PackageError("bad_archive", f"{path!r} is not under the package's one root folder")
        if root is None:
            if not MODE_ID.fullmatch(top) or len(top) > MODE_ID_MAX:
                raise PackageError("bad_archive", f"the root folder {top!r} is not a mode id")
            if mode_id is not None and top != mode_id:
                raise PackageError("mismatch", f"the archive is {top}, not {mode_id}")
            root = top
        check_file_name(name)
        if name in files:
            raise PackageError("bad_archive", f"{name} is in the archive twice")
        if len(files) >= MAX_FILES:
            raise PackageError("bad_archive", f"more than {MAX_FILES} files")
        size = _field_octal(head[124:136], "a size")
        start = pos + BLOCK
        end = start + size
        if end > len(archive):
            raise PackageError("bad_archive", f"{name} runs past the end")
        try:
            text = bytes(archive[start:end]).decode("utf-8")
        except UnicodeDecodeError:
            raise PackageError("bad_archive", f"{name} is not UTF-8 text") from None
        if "\0" in text:
            raise PackageError("bad_archive", f"{name} is not text")
        files[name] = text
        pos = start + size + (-size % BLOCK)
    if root is None:
        raise PackageError("bad_archive", "an empty archive")
    # Only the canonical form: the same files packed again must give exactly these bytes
    # (sorted, the fixed header fields, zero padding, two zero blocks and nothing after).
    if pack(root, files) != bytes(archive):
        raise PackageError("bad_archive", "not in the canonical form (tools/mode_package.py pack makes it)")
    return root, files


def sha256(archive: bytes) -> str:
    return hashlib.sha256(archive).hexdigest()


# ---- the manifest and its signature -----------------------------------------------------------


@dataclass(frozen=True)
class Release:
    """A package's signed manifest and its signature."""

    id: str
    version: str
    kind: str
    min_tier: str
    size: int
    sha256: str
    signature: str

    def manifest(self) -> bytes:
        return manifest(self.id, self.version, self.kind, self.min_tier, self.size, self.sha256)

    def text(self) -> bytes:
        return self.manifest() + f"signature={self.signature}\n".encode("ascii")


def manifest(mode_id: str, version: str, kind: str, min_tier: str, size: int, digest: str) -> bytes:
    """The exact bytes a mode key signs."""
    return (f"{MANIFEST_HEADER}\nid={mode_id}\nversion={version}\nkind={kind}\nmin_tier={min_tier}\n"
            f"size={size}\nsha256={digest}\n").encode("utf-8")


def release_from(value: Any) -> Release:
    """A release from its JSON form (``.release.json``, an index entry): its fields checked."""
    if not isinstance(value, dict):
        raise PackageError("bad_release", "a release is an object")
    mode_id, version, kind, tier = (value.get(k) for k in ("id", "version", "kind", "min_tier"))
    size, digest, signature = value.get("size"), value.get("sha256"), value.get("signature")
    if not isinstance(mode_id, str) or not MODE_ID.fullmatch(mode_id) or len(mode_id) > MODE_ID_MAX:
        raise PackageError("bad_release", "id")
    if not isinstance(version, str) or fr.version_key(version) is None:
        raise PackageError("bad_release", "version")
    if kind not in KINDS:
        raise PackageError("bad_release", "kind")
    if tier not in TIERS:
        raise PackageError("bad_release", "min_tier")
    if not isinstance(size, int) or isinstance(size, bool) or not 0 < size <= MAX_PACKAGE_BYTES:
        raise PackageError("bad_release", "size")
    if not isinstance(digest, str) or not fr.SHA256.fullmatch(digest):
        raise PackageError("bad_release", "sha256")
    if fr.signature_bytes(signature) is None:
        raise PackageError("bad_release", "signature")
    return Release(mode_id, version, kind, tier, size, digest, signature)


def parse_release_text(text: bytes) -> Release:
    """A release text (what a box fetches): exactly the manifest's lines and the signature."""
    try:
        decoded = text.decode("ascii")
    except (UnicodeDecodeError, AttributeError):
        raise PackageError("bad_release", "not ASCII") from None
    lines = decoded.split("\n")
    names = ("id", "version", "kind", "min_tier", "size", "sha256", "signature")
    if len(lines) != len(names) + 2 or lines[0] != MANIFEST_HEADER or lines[-1] != "":
        raise PackageError("bad_release", "not a mode package release")
    values: dict[str, Any] = {}
    for name, line in zip(names, lines[1:-1]):
        key, sep, value = line.partition("=")
        if key != name or not sep:
            raise PackageError("bad_release", f"line {name}")
        values[name] = value
    if not re.fullmatch(r"[1-9][0-9]{0,6}", values["size"]):
        raise PackageError("bad_release", "size")
    values["size"] = int(values["size"])
    release = release_from(values)
    if release.text() != text:
        raise PackageError("bad_release", "not in its canonical form")
    return release


def signer(keys: Iterable[str], release: Release) -> Optional[str]:
    """The id of the trusted key (base64) that signed exactly this manifest, or None."""
    return _signer(keys, release.manifest(), release.signature)


def _signer(keys: Iterable[str], message: bytes, signature: str) -> Optional[str]:
    sig = fr.signature_bytes(signature)
    if sig is None:
        return None
    for key in keys:
        raw = fr.public_key_bytes(key)
        if raw is not None and fr.verify_signature(raw, message, sig):
            return fr.key_id(key)
    return None


def manifest_fields(files: dict[str, str]) -> dict[str, Any]:
    """What a package's own mode.yaml says the manifest must say: id, version, kind, min_tier
    (``reduced`` when it says none) and licence; PackageError("bad_manifest") otherwise."""
    if "mode.yaml" not in files:
        raise PackageError("bad_manifest", "the package has no mode.yaml")
    try:
        data = yaml.safe_load(files["mode.yaml"]) or {}
    except yaml.YAMLError as exc:
        raise PackageError("bad_manifest", f"mode.yaml: {exc}") from None
    if not isinstance(data, dict):
        raise PackageError("bad_manifest", "mode.yaml must be a map")
    out = {"id": data.get("id"), "version": str(data.get("version", "")), "kind": data.get("kind", "mode"),
           "min_tier": data.get("min_tier", "reduced"), "license": data.get("license")}
    if not isinstance(out["id"], str) or not MODE_ID.fullmatch(out["id"]) or len(out["id"]) > MODE_ID_MAX:
        raise PackageError("bad_manifest", "mode.yaml: id must look like org.club.name")
    if fr.version_key(out["version"]) is None:
        raise PackageError("bad_manifest", "mode.yaml: version must be MAJOR.MINOR.PATCH")
    if out["kind"] not in KINDS:
        raise PackageError("bad_manifest", "mode.yaml: kind")
    if out["min_tier"] not in TIERS:
        raise PackageError("bad_manifest", "mode.yaml: min_tier must be reduced or full")
    if out["license"] not in LICENCES:
        raise PackageError("licence", f"mode.yaml: license must be one of {', '.join(LICENCES)}")
    return out


@dataclass(frozen=True)
class VerifiedPackage:
    """A package that passed every check: its release, its files and who signed it."""

    release: Release
    files: dict[str, str]
    key_id: str
    license: str


def verify(archive: bytes, release: Release, keys: Iterable[str], revoked: Iterable[str] = (),
           named_key: Optional[str] = None, limit: int = MAX_PACKAGE_BYTES) -> VerifiedPackage:
    """Checks a package as the controller installs it; PackageError at the first failure.

    ``keys``: the trusted mode keys (base64); ``revoked``: key ids that no longer count, even when
    a key is still listed; ``named_key``: the key id the release says signed it (only to tell
    ``no_key`` from ``bad_signature``; never trusted for anything else).
    """
    if release.size > limit:
        raise PackageError("too_big", f"{release.size} bytes; at most {limit}")
    if len(archive) != release.size:
        raise PackageError("bad_hash", f"the archive has {len(archive)} bytes, the release says {release.size}")
    if sha256(archive) != release.sha256:
        raise PackageError("bad_hash", "the archive is not the one signed")
    keys = list(keys)
    who = signer(keys, release)
    if who is None:
        known = {fr.key_id(k) for k in keys if fr.public_key_bytes(k) is not None}
        if named_key is not None and named_key not in known:
            raise PackageError("no_key", f"signed with key {named_key}, which this controller does not trust")
        raise PackageError("bad_signature", "no trusted mode key signed this manifest")
    if who in set(revoked):
        raise PackageError("revoked", f"key {who} is revoked")
    root, files = unpack(archive, release.id, limit)
    own = manifest_fields(files)
    for name in ("id", "version", "kind", "min_tier"):
        if own[name] != getattr(release, name):
            raise PackageError("mismatch", f"mode.yaml says {name} {own[name]!r}, the signed manifest "
                                           f"{getattr(release, name)!r}")
    return VerifiedPackage(release, files, who, own["license"])


def sign_release(private_key: Any, archive: bytes) -> Release:
    """Signs an archive's manifest with an Ed25519 private key (cryptography's object); the
    manifest's fields come from the archive's own mode.yaml."""
    _, files = unpack(archive)
    own = manifest_fields(files)
    digest = sha256(archive)
    message = manifest(own["id"], own["version"], own["kind"], own["min_tier"], len(archive), digest)
    signature = base64.b64encode(private_key.sign(message)).decode("ascii")
    return Release(own["id"], own["version"], own["kind"], own["min_tier"], len(archive), digest, signature)


def release_json(release: Release, key_id: str, license: str) -> dict[str, Any]:
    """The ``.release.json`` next to an archive: the manifest's fields, the signature, the key's id
    and the licence (the last two only describe it: verifying never trusts them)."""
    return {"format": MANIFEST_HEADER, "id": release.id, "version": release.version, "kind": release.kind,
            "min_tier": release.min_tier, "size": release.size, "sha256": release.sha256,
            "signature": release.signature, "key_id": key_id, "license": license}


# ---- the registry's index and revocation list -------------------------------------------------

INDEX_SCHEMA_VERSION = 1
ENTRY_KEYS = {"version", "kind", "min_tier", "size", "sha256", "signature", "key_id", "license", "url",
              "verified"}
INDEX_MODE_KEYS = {"id", "name", "description", "author", "versions"}


@dataclass(frozen=True)
class IndexEntry:
    """One version of one mode in an index: where to fetch it and its release."""

    release: Release
    key_id: str
    license: str
    url: str
    verified: bool
    name: str
    description: str = ""
    author: str = ""


def _text(value: Any, what: str, longest: int, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or not value.strip() and required or len(value) > longest:
        raise PackageError("bad_index", what)
    return value


def parse_index(value: Any) -> list[IndexEntry]:
    """Every version of every mode of a registry index (``registry/schema/index.schema.json``).

    The whole index is refused (``bad_index``) for anything it does not allow: an index is
    data from elsewhere, so nothing in it is guessed. A package's ``url`` is ``https://...`` or
    a relative path (an index file next to its packages, for a field without internet).
    """
    if not isinstance(value, dict) or set(value) - {"schema_version", "modes", "name"}:
        raise PackageError("bad_index", "an index is {schema_version, name?, modes}")
    if value.get("schema_version") != INDEX_SCHEMA_VERSION:
        raise PackageError("bad_index", f"schema_version must be {INDEX_SCHEMA_VERSION}")
    modes = value.get("modes")
    if not isinstance(modes, list) or len(modes) > 1000:
        raise PackageError("bad_index", "modes must be a list (at most 1000)")
    out: list[IndexEntry] = []
    seen: set[tuple[str, str]] = set()
    for mode in modes:
        if not isinstance(mode, dict) or set(mode) - INDEX_MODE_KEYS or "versions" not in mode:
            raise PackageError("bad_index", "a mode is {id, name, description?, author?, versions}")
        mode_id = mode.get("id")
        if not isinstance(mode_id, str) or not MODE_ID.fullmatch(mode_id) or len(mode_id) > MODE_ID_MAX:
            raise PackageError("bad_index", "a mode's id")
        name = _text(mode.get("name"), f"{mode_id}: name", 80)
        description = _text(mode.get("description"), f"{mode_id}: description", 2000, required=False)
        author = _text(mode.get("author"), f"{mode_id}: author", 120, required=False)
        versions = mode["versions"]
        if not isinstance(versions, list) or not versions or len(versions) > 100:
            raise PackageError("bad_index", f"{mode_id}: versions must be a list of 1 to 100")
        for entry in versions:
            if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
                raise PackageError("bad_index", f"{mode_id}: a version has exactly {', '.join(sorted(ENTRY_KEYS))}")
            try:
                release = release_from({**entry, "id": mode_id})
            except PackageError as exc:
                raise PackageError("bad_index", f"{mode_id} {entry.get('version')}: {exc.detail}") from None
            if not isinstance(entry["key_id"], str) or not KEY_ID.fullmatch(entry["key_id"]):
                raise PackageError("bad_index", f"{mode_id} {release.version}: key_id")
            if entry["license"] not in LICENCES:
                raise PackageError("bad_index", f"{mode_id} {release.version}: license must be an approved one")
            url = entry["url"]
            if not isinstance(url, str) or len(url) > 500 or not (
                    re.fullmatch(r"https://[^\s\\]+", url)
                    or re.fullmatch(r"[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*", url) and ".." not in url.split("/")):
                raise PackageError("bad_index", f"{mode_id} {release.version}: url must be https:// or a relative path")
            if not isinstance(entry["verified"], bool):
                raise PackageError("bad_index", f"{mode_id} {release.version}: verified is true or false")
            if (mode_id, release.version) in seen:
                raise PackageError("bad_index", f"{mode_id} {release.version} is listed twice")
            seen.add((mode_id, release.version))
            out.append(IndexEntry(release, entry["key_id"], entry["license"], url, entry["verified"], name,
                                  description, author))
    return out


def parse_revoked(value: Any) -> dict[str, str]:
    """A revocation list (``registry/schema/revoked.schema.json``): key id -> reason."""
    if not isinstance(value, dict) or set(value) != {"schema_version", "keys"} or value["schema_version"] != 1:
        raise PackageError("bad_index", "a revocation list is {schema_version: 1, keys}")
    keys = value["keys"]
    if not isinstance(keys, list) or len(keys) > 1000:
        raise PackageError("bad_index", "keys must be a list")
    out: dict[str, str] = {}
    for item in keys:
        if not isinstance(item, dict) or set(item) - {"key_id", "reason", "date"} or "key_id" not in item:
            raise PackageError("bad_index", "a revoked key is {key_id, reason?, date?}")
        if not isinstance(item["key_id"], str) or not KEY_ID.fullmatch(item["key_id"]):
            raise PackageError("bad_index", "a revoked key's key_id")
        reason = item.get("reason", "")
        if not isinstance(reason, str) or len(reason) > 500:
            raise PackageError("bad_index", "a revoked key's reason")
        date = item.get("date", "")
        if not isinstance(date, str) or date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise PackageError("bad_index", "a revoked key's date is YYYY-MM-DD")
        out[item["key_id"]] = reason
    return out


# ---- what a box checks, and its report (phase 5 plan phase 13) -------------------------------
#
# A box that joins with key 16 (fetch_modes) fetches each part of its mode_id it lacks from its
# controller (protocol/mode-packages.md, "Fetching missing modes"). These functions are the
# reference for its checks (firmware/esp32/main/mode_fetch.c, plan phase 13b), in the box's order;
# the shared vectors' box_checks and reports come from them, and the controller uses the same
# rules to offer only what a box will take.

BOX_MAX_PACKAGE_BYTES = 262_144   # a box takes an archive of at most 256 KiB (P5B-12)
BOX_MAX_FETCHED = 8               # fetched packages a box keeps at most
BOX_MAX_FETCHED_BYTES = 524_288   # and their archives' sizes together at most (512 KiB)
SCREEN_FILE = re.compile(r"assets/screens/[A-Za-z0-9_.-]+\.yaml")
REPORT_HEADER = "atalaia-mode-report-v1"
REPORT_MAX = 1024
# What a box reports for each part it fetched: installed, or why it stopped (in the order a box
# meets them; protocol/mode-packages.md says what each means).
BOX_RESULTS = ("installed", "no_wifi", "unreachable", "not_offered", "download", "no_key", "bad_release",
               "bad_signature", "kind", "tier", "builtin", "too_big", "bad_hash", "bad_archive", "load",
               "no_space", "storage", "cancelled")


def box_check_release(text: bytes, wanted_id: str, keys: Iterable[str], tier: str,
                      builtin: Iterable[str] = (), limit: int = BOX_MAX_PACKAGE_BYTES) -> tuple[Release, str]:
    """A box's checks of a release text, before it downloads the archive; (release, key id) or
    PackageError at the first failure, in this order: no mode key built in (``no_key``); the text
    exactly the manifest's lines and a signature, for the id it asked for (``bad_release``); a
    signature by one of its own mode keys (``bad_signature``); not a scenario (``kind``); its tier
    (``tier``: a reduced box refuses ``min_tier=full``); not one of its built-in ids (``builtin``);
    the size within its limit (``too_big``). ``tier`` is the box's: ``reduced`` or ``full``."""
    if tier not in TIERS:
        raise ValueError("tier: reduced or full")
    keys = [k for k in keys if fr.public_key_bytes(k) is not None]
    if not keys:
        raise PackageError("no_key", "no mode key is built into this box")
    try:
        release = parse_release_text(text)
    except PackageError as exc:
        raise PackageError("bad_release", exc.detail) from None
    if release.id != wanted_id:
        raise PackageError("bad_release", f"the release is {release.id}'s, not {wanted_id}'s")
    who = signer(keys, release)
    if who is None:
        raise PackageError("bad_signature", "none of the box's mode keys signed this manifest")
    if release.kind not in BOX_KINDS:
        raise PackageError("kind", f"a {release.kind} never runs on a box")
    if tier == "reduced" and release.min_tier == "full":
        raise PackageError("tier", "the package needs a Full box")
    if release.id in set(builtin):
        raise PackageError("builtin", "the box's firmware has a mode of this id: it is never replaced")
    if release.size > limit:
        raise PackageError("too_big", f"{release.size} bytes; a box takes at most {limit}")
    return release, who


def box_check_archive(archive: bytes, release: Release) -> dict[str, str]:
    """A box's checks of the archive it downloaded for a release it checked: the signed size and
    SHA-256 (``bad_hash``), the canonical form with the id as its root and a ``node.lua``
    (``bad_archive``). The files a box keeps: ``node.lua`` and ``assets/screens/*.yaml``."""
    if len(archive) != release.size or sha256(archive) != release.sha256:
        raise PackageError("bad_hash", "the archive is not the one signed")
    try:
        _, files = unpack(archive, release.id, max(release.size, BLOCK))
    except PackageError as exc:
        raise PackageError("bad_archive", exc.detail) from None
    if "node.lua" not in files:
        raise PackageError("bad_archive", "the package has no node.lua")
    return {name: text for name, text in files.items() if name == "node.lua" or SCREEN_FILE.fullmatch(name)}


def report_body(game: int, node: int, mode_id: str, version: Optional[str], result: str,
                kept: dict[str, str]) -> bytes:
    """The text a box posts for each part it fetched (it signs it with the game key): the part,
    the version it read (``-`` when it read none), the result, and every package it keeps now
    (``id@version`` sorted by id, ``-`` for none)."""
    kept_text = ",".join(f"{k}@{kept[k]}" for k in sorted(kept)) or "-"
    return (f"{REPORT_HEADER}\ngame={game}\nnode={node}\nmode={mode_id}\nversion={version or '-'}\n"
            f"result={result}\nkept={kept_text}\n").encode("ascii")


def report_mac(game_key: bytes, body: bytes) -> str:
    """HMAC-SHA256 of the report with the game key, lower-case hex (the X-Atalaia-Mac header)."""
    return fr.report_mac(game_key, body)


def parse_report(body: bytes) -> dict[str, Any]:
    """A box's report (PackageError("bad_report") otherwise): exactly the lines of report_body."""
    if len(body) > REPORT_MAX:
        raise PackageError("bad_report", "too long")
    try:
        text = body.decode("ascii")
    except UnicodeDecodeError:
        raise PackageError("bad_report", "not ASCII") from None
    lines = text.split("\n")
    names = ("game", "node", "mode", "version", "result", "kept")
    if len(lines) != len(names) + 2 or lines[0] != REPORT_HEADER or lines[-1] != "":
        raise PackageError("bad_report", "not a report")
    out: dict[str, Any] = {}
    for name, line in zip(names, lines[1:-1]):
        key, sep, value = line.partition("=")
        if key != name or not sep:
            raise PackageError("bad_report", f"line {name}")
        out[name] = value
    for name in ("game", "node"):
        if not re.fullmatch(r"[1-9][0-9]{0,4}", out[name]) or int(out[name]) > 0xFFFE:
            raise PackageError("bad_report", name)
        out[name] = int(out[name])
    if not MODE_ID.fullmatch(out["mode"]) or len(out["mode"]) > MODE_ID_MAX:
        raise PackageError("bad_report", "mode")
    if out["version"] == "-":
        out["version"] = None
    elif fr.version_key(out["version"]) is None:
        raise PackageError("bad_report", "version")
    if out["result"] not in BOX_RESULTS:
        raise PackageError("bad_report", "result")
    kept: dict[str, str] = {}
    if out["kept"] != "-":
        for item in out["kept"].split(","):
            mode_id, sep, version = item.partition("@")
            if (not sep or not MODE_ID.fullmatch(mode_id) or len(mode_id) > MODE_ID_MAX
                    or fr.version_key(version) is None or mode_id in kept):
                raise PackageError("bad_report", "kept")
            kept[mode_id] = version
        if len(kept) > BOX_MAX_FETCHED:
            raise PackageError("bad_report", "kept")
    out["kept"] = kept
    if body != report_body(out["game"], out["node"], out["mode"], out["version"], out["result"], kept):
        raise PackageError("bad_report", "not in its canonical form")
    return out
