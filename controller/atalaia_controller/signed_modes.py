# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Signed mode packages on the field controller (phase 5 plan phase 6, decisions P5C-17 onwards).

The GM installs a signed package in the console, either by uploading it (the
archive and its ``.release.json`` from ``tools/mode_package.py``) or from the
field's registry index (``[modes] index``: an ``https://`` URL, or a file for a
field without internet, its packages next to it). Each one is checked with
``mode_package.verify`` (protocol/mode-packages.md) against the controller's own
trusted mode keys (``[modes] keys``) and revoked key ids (``[modes] revoked``
and the index's ``revoked.json``), fails closed at the first problem, and is
then installed through the same checks as an upload (``ModeRegistry.install``:
the manifest, the scripts loading in the core, never a built-in id). The store
keeps the archive and its release, so the boxes can be sent exactly the signed
bytes later (plan phase 13).

What the console shows: who signed each installed package (the key id), whether
the project reviewed it (the index's ``verified``; an upload is *not reviewed by
the project*), and whether its key is still trusted here.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from atalaia_sim.mode import ModeError

from . import firmware_release as fr
from . import mode_package as mp

INDEX_MAX = 1_000_000  # bytes of an index or a revocation list
FETCH_TIMEOUT_S = 15.0
INDEX_TTL_S = 300.0  # an index fetched this recently is not fetched again unless asked


class FetchError(Exception):
    """A document that could not be fetched; ``missing`` when it is simply not there."""

    def __init__(self, message: str, missing: bool = False) -> None:
        super().__init__(message)
        self.missing = missing


def https_fetch(url: str, limit: int) -> bytes:
    """GET over HTTPS (the system's trust store), at most ``limit`` bytes; never plain HTTP."""
    if not url.startswith("https://"):
        raise FetchError("only https:// URLs")
    request = urllib.request.Request(url, headers={"User-Agent": "atalaia-controller"})
    try:
        with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:  # noqa: S310 (https only)
            if response.geturl() and not response.geturl().startswith("https://"):
                raise FetchError("redirected away from https://")
            data = response.read(limit + 1)
    except urllib.error.HTTPError as exc:
        raise FetchError(f"{url}: HTTP {exc.code}", missing=exc.code == 404) from None
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise FetchError(f"{url}: {exc}") from None
    if len(data) > limit:
        raise FetchError(f"{url}: over {limit} bytes")
    return data


class SignedModes:
    def __init__(self, controller: Any, keys: list[str], revoked: list[str], index: str,
                 fetch: Callable[[str, int], bytes] = https_fetch) -> None:
        self.controller = controller
        self.keys = list(keys)
        self.revoked_config = set(revoked)
        self.index_source = index.strip()
        self.fetch = fetch
        self._index: Optional[dict[str, Any]] = None  # {"entries", "revoked", "fetched_at"} or {"error"}
        controller.signed_modes = self

    # ---- the trusted keys ----------------------------------------------------------------

    def key_ids(self) -> list[str]:
        return [fr.key_id(k) for k in self.keys]

    def revoked(self) -> set[str]:
        index = self._index or {}
        return self.revoked_config | set(index.get("revoked", {}))

    def trust(self, key_id: Optional[str]) -> str:
        """"trusted", "revoked" or "untrusted" (no longer one of this controller's keys)."""
        if key_id in self.revoked():
            return "revoked"
        return "trusted" if key_id in self.key_ids() else "untrusted"

    # ---- where the index and its packages are ---------------------------------------------

    def _locate(self, relative: str) -> str:
        """An index's (relative) package url, or revoked.json, as an https URL or a file path."""
        source = self.index_source
        if relative.startswith("https://"):
            return relative
        if source.startswith("https://"):
            url = urllib.parse.urljoin(source, relative)
            if not url.startswith("https://"):
                raise FetchError("a package outside https://")
            return url
        folder = Path(source).resolve().parent
        path = (folder / relative).resolve()
        if not path.is_relative_to(folder):
            raise FetchError("a package outside the index's folder")
        return str(path)

    def _read(self, where: str, limit: int) -> bytes:
        if where.startswith("https://"):
            return self.fetch(where, limit)
        if where.startswith(("http://", "file:", "ftp:")):
            raise FetchError("only https:// URLs or files")
        path = Path(where)
        if not path.is_file():
            raise FetchError(f"{where}: no such file", missing=True)
        if path.stat().st_size > limit:
            raise FetchError(f"{where}: over {limit} bytes")
        return path.read_bytes()

    def load_index(self, refresh: bool = False) -> dict[str, Any]:
        """The index's entries and revocations, fetched again when asked or when old."""
        if not self.index_source:
            return {"error": None, "entries": [], "revoked": {}}
        if (not refresh and self._index is not None and "entries" in self._index
                and time.time() - self._index["fetched_at"] < INDEX_TTL_S):
            return self._index
        try:
            entries = mp.parse_index(json.loads(self._read(self.index_source, INDEX_MAX)))
            try:
                revoked = mp.parse_revoked(json.loads(self._read(self._locate("revoked.json"), INDEX_MAX)))
            except FetchError as exc:
                if not exc.missing:
                    raise
                revoked = {}
            self._index = {"entries": entries, "revoked": revoked, "fetched_at": time.time(), "error": None}
        except (FetchError, mp.PackageError, ValueError, UnicodeDecodeError) as exc:
            # Fail closed: an index that cannot be read whole offers nothing.
            self._index = {"error": str(exc), "entries": [], "revoked": {}, "fetched_at": time.time()}
        return self._index

    # ---- installing -----------------------------------------------------------------------

    def _install(self, archive: bytes, release: mp.Release, named_key: Optional[str], verified: bool,
                 source: str) -> dict[str, Any]:
        if not self.keys:
            raise ModeError("no mode keys are set on this controller ([modes] keys): it installs nothing signed")
        try:
            package = mp.verify(archive, release, self.keys, self.revoked(), named_key)
        except mp.PackageError as exc:
            raise ModeError(f"the signed package was refused ({exc.code}): {exc.detail or exc.code}") from None
        signed = {"format": mp.MANIFEST_HEADER, "id": release.id, "version": release.version,
                  "kind": release.kind, "min_tier": release.min_tier, "size": release.size,
                  "sha256": release.sha256, "signature": release.signature, "key_id": package.key_id,
                  "license": package.license, "verified": verified, "source": source}
        pkg = self.controller.modes.install(package.files, signed=signed, archive=archive)
        return self.annotate(pkg.to_api())

    def upload(self, archive: bytes, fields: dict[str, Any]) -> dict[str, Any]:
        """A package the GM uploaded with its release's fields (the .release.json): never verified
        by the project, whoever signed it."""
        try:
            release = mp.release_from({**fields, "size": len(archive), "sha256": mp.sha256(archive)})
        except mp.PackageError as exc:
            raise ModeError(f"the release file is not one ({exc.detail})") from None
        named = fields.get("key_id") if isinstance(fields.get("key_id"), str) else None
        return self._install(archive, release, named, False, "upload")

    def install_from_index(self, mode_id: Any, version: Any) -> dict[str, Any]:
        index = self.load_index(refresh=True)
        if index.get("error"):
            raise ModeError(f"the index could not be read: {index['error']}")
        entry = next((e for e in index["entries"] if e.release.id == mode_id and e.release.version == version), None)
        if entry is None:
            raise ModeError(f"{mode_id} {version} is not in the index")
        try:
            archive = self._read(self._locate(entry.url), mp.MAX_PACKAGE_BYTES)
        except FetchError as exc:
            raise ModeError(f"the package could not be fetched: {exc}") from None
        return self._install(archive, entry.release, entry.key_id, entry.verified, "index")

    # ---- what the console shows -------------------------------------------------------------

    def annotate(self, mode: dict[str, Any]) -> dict[str, Any]:
        """A mode's API form with its signature's trust today (or null for unsigned ones)."""
        signed = mode.get("signed")
        if signed:
            mode["signed"] = {k: signed[k] for k in ("key_id", "verified", "sha256", "source", "license")}
            mode["signed"]["trust"] = self.trust(signed.get("key_id"))
        return mode

    def status(self, refresh: bool = False) -> dict[str, Any]:
        index = self.load_index(refresh)
        installed = {m.id: m for m in self.controller.modes.all()}
        entries = []
        for e in index["entries"]:
            have = installed.get(e.release.id)
            if e.key_id in self.revoked():
                state = "revoked"
            elif e.key_id not in self.key_ids():
                state = "no_key"
            elif have is not None and have.builtin:
                state = "builtin"
            elif have is not None and have.mode.version == e.release.version:
                state = "installed"
            else:
                state = "available"
            entries.append({"id": e.release.id, "name": e.name, "description": e.description, "author": e.author,
                            "version": e.release.version, "kind": e.release.kind, "min_tier": e.release.min_tier,
                            "size": e.release.size, "license": e.license, "key_id": e.key_id,
                            "verified": e.verified, "installed_version": have.mode.version if have else None,
                            "state": state})
        return {"keys": self.key_ids(), "revoked": sorted(self.revoked()),
                "index": {"source": self.index_source or None, "error": index.get("error"),
                          "entries": entries}}
