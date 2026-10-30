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

Revocations fail closed (security review FLD-7). With an index set, every install and every upload first
fetches the index's ``revoked.json`` again: a revocation list that is missing, unreadable or malformed refuses
the install, and so does a list that cannot be reached for longer than ``[modes] revocation_max_age_days``
(default 30). A controller with no internet goes on with the last list it fetched (kept in the store, so it
survives a restart) until that age; with none yet, or an older one, it installs nothing signed until the index
answers (or the field sets no index and keeps ``[modes] revoked`` itself). ``[modes] min_versions`` is a floor
per mode id: an older version is refused.

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
REVOCATIONS_SETTING = "modes.revocations"  # the last revocation list fetched: {"keys": {id: reason}, "fetched_at"}
DAY_S = 86400.0


class FetchError(Exception):
    """A document that could not be fetched; ``missing`` when it is simply not there."""

    def __init__(self, message: str, missing: bool = False, offline: bool = False) -> None:
        super().__init__(message)
        self.missing = missing
        self.offline = offline  # the network (or the server) did not answer: not a document that is wrong


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
        raise FetchError(f"{url}: HTTP {exc.code}", missing=exc.code == 404, offline=exc.code >= 500) from None
    except (urllib.error.URLError, OSError) as exc:
        raise FetchError(f"{url}: {exc}", offline=True) from None
    except ValueError as exc:
        raise FetchError(f"{url}: {exc}") from None
    if len(data) > limit:
        raise FetchError(f"{url}: over {limit} bytes")
    return data


class SignedModes:
    def __init__(self, controller: Any, keys: list[str], revoked: list[str], index: str,
                 fetch: Callable[[str, int], bytes] = https_fetch, min_versions: Optional[dict[str, str]] = None,
                 revocation_max_age_days: float = 30.0, wall: Callable[[], float] = time.time) -> None:
        self.controller = controller
        self.keys = list(keys)
        self.revoked_config = set(revoked)
        self.index_source = index.strip()
        self.fetch = fetch
        self.min_versions = dict(min_versions or {})
        self.revocation_max_age_s = max(0.0, revocation_max_age_days) * DAY_S
        self._wall = wall
        self._index: Optional[dict[str, Any]] = None  # {"entries", "fetched_at"} or {"error"}
        # The last revocation list fetched, kept apart from the index: a failed fetch never erases it.
        self._rev: Optional[dict[str, Any]] = self._load_revocations()
        controller.signed_modes = self

    # ---- the revocation list, fetched and kept ---------------------------------------------

    def _load_revocations(self) -> Optional[dict[str, Any]]:
        store = getattr(self.controller, "store", None)
        try:
            saved = json.loads(store.get_setting(REVOCATIONS_SETTING) or "null") if store is not None else None
            if isinstance(saved, dict) and isinstance(saved.get("keys"), dict) \
                    and isinstance(saved.get("fetched_at"), (int, float)):
                return {"keys": {str(k): str(v) for k, v in saved["keys"].items()}, "fetched_at": float(saved["fetched_at"])}
        except (ValueError, TypeError, OSError):
            pass
        return None

    def _fetch_revocations(self) -> None:
        """revoked.json from the index's place, now; keeps it (and the time) when it is a good one. A list that is
        missing is an error: nothing says nothing was revoked."""
        revoked = mp.parse_revoked(json.loads(self._read(self._locate("revoked.json"), INDEX_MAX)))
        self._rev = {"keys": revoked, "fetched_at": self._wall()}
        store = getattr(self.controller, "store", None)
        if store is not None:
            store.set_setting(REVOCATIONS_SETTING, json.dumps(self._rev, sort_keys=True))

    def revocations_age_s(self) -> Optional[float]:
        return None if self._rev is None else max(0.0, self._wall() - self._rev["fetched_at"])

    def require_current_revocations(self) -> None:
        """Before an install or an upload (FLD-7): the revocation list again, or the last one while it is young
        enough, or nothing is installed. No index set: the field keeps ``[modes] revoked`` itself."""
        if not self.index_source:
            return
        try:
            self._fetch_revocations()
            return
        except FetchError as exc:
            if not exc.offline:
                raise ModeError(f"the revocation list could not be read, so nothing is installed: {exc}") from None
            reason = str(exc)
        except (mp.PackageError, ValueError, UnicodeDecodeError) as exc:
            raise ModeError(f"the revocation list is not a good one, so nothing is installed: {exc}") from None
        age = self.revocations_age_s()
        if age is None or age > self.revocation_max_age_s:
            have = "none was ever fetched" if age is None else f"the last one is {int(age // DAY_S)} days old"
            raise ModeError(f"the revocation list cannot be reached ({reason}) and {have} "
                            f"([modes] revocation_max_age_days = {self.revocation_max_age_s / DAY_S:g}): "
                            "nothing signed is installed until the index answers")

    # ---- the trusted keys ----------------------------------------------------------------

    def key_ids(self) -> list[str]:
        return [fr.key_id(k) for k in self.keys]

    def revoked(self) -> set[str]:
        return self.revoked_config | set((self._rev or {}).get("keys", {}))

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
            return {"error": None, "entries": []}
        if (not refresh and self._index is not None and "entries" in self._index
                and time.time() - self._index["fetched_at"] < INDEX_TTL_S):
            return self._index
        try:
            entries = mp.parse_index(json.loads(self._read(self.index_source, INDEX_MAX)))
            self._fetch_revocations()  # a missing revoked.json is an error too (FLD-7)
            self._index = {"entries": entries, "fetched_at": time.time(), "error": None}
        except (FetchError, mp.PackageError, ValueError, UnicodeDecodeError) as exc:
            # Fail closed: an index that cannot be read whole offers nothing. What was revoked stays revoked
            # (self._rev is not touched).
            self._index = {"error": str(exc), "entries": [], "fetched_at": time.time()}
        return self._index

    # ---- installing -----------------------------------------------------------------------

    def below_floor(self, mode_id: Any, version: Any) -> Optional[str]:
        """The floor ([modes] min_versions) a version is under, else None."""
        floor = self.min_versions.get(mode_id) if isinstance(mode_id, str) else None
        if floor is None or not isinstance(version, str):
            return None
        have, want = fr.version_key(version), fr.version_key(floor)
        return floor if have is not None and want is not None and have < want else None

    def _install(self, archive: bytes, release: mp.Release, named_key: Optional[str], verified: bool,
                 source: str, revocations_current: bool = False) -> dict[str, Any]:
        if not self.keys:
            raise ModeError("no mode keys are set on this controller ([modes] keys): it installs nothing signed")
        floor = self.below_floor(release.id, release.version)
        if floor:
            raise ModeError(f"{release.id} {release.version} is below this controller's floor for it, {floor} "
                            "([modes] min_versions): install a newer version")
        if not revocations_current:
            self.require_current_revocations()
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
        return self._install(archive, entry.release, entry.key_id, entry.verified, "index", revocations_current=True)

    # ---- what the console shows -------------------------------------------------------------

    def annotate(self, mode: dict[str, Any]) -> dict[str, Any]:
        """A mode's API form with its signature's trust today (or null for unsigned ones)."""
        signed = mode.get("signed")
        if signed:
            mode["signed"] = {k: signed[k] for k in ("key_id", "verified", "sha256", "source", "license")}
            mode["signed"]["trust"] = self.trust(signed.get("key_id"))
            if self.below_floor(mode.get("id"), mode.get("version")):
                mode["signed"]["below_floor"] = True
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
        age = self.revocations_age_s()
        return {"keys": self.key_ids(), "revoked": sorted(self.revoked()),
                "revocations_age_s": None if age is None else int(age),
                "index": {"source": self.index_source or None, "error": index.get("error"),
                          "entries": entries}}
