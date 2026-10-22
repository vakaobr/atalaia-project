#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks and maintains a community mode registry (the atalaia-modes repository, registry/template/).

    python3 tools/registry_check.py lint REGISTRY [--base BASE]
        every check the registry's CI makes without running a mode (registry-lint): the index, the
        keys and revocations, each version's archive and both signatures, the sources in modes/
        against the newest package, the review checklist's automated items; with --base (the pull
        request's base branch) also that no published version changed
    python3 tools/registry_check.py test REGISTRY [--lib libatalaia_core.so]
        each mode's own tests in the simulator, on the real core (registry-test)
    python3 tools/registry_check.py key REGISTRY --public BASE64 --owner GITHUB_HANDLE [--name TEXT]
            [--project]
        adds a public mode key: keys/authors/<key id>.json (or keys/project/ with --project)
    python3 tools/registry_check.py add REGISTRY ID --key AUTHOR_KEY.pem [--name ...] [--description ...]
            [--author ...]
        packs modes/ID, signs it with the author's key and lists it in the index, not reviewed
    python3 tools/registry_check.py badge REGISTRY ID VERSION --key PROJECT_KEY.pem [--remove]
        the verified badge: the project's registry key signs the same archive (or, with --remove,
        the badge is taken away and the author's signature listed again)
    python3 tools/registry_check.py site REGISTRY OUT
        what the registry publishes: index.json, revoked.json, keys.json, packages/, badges/

The registry's layout, its review checklist and its processes are
docs/community/ (the registry, the review, keys, moderation). The package
format and every check of a package are the shared
``controller/atalaia_controller/mode_package.py`` (protocol/mode-packages.md);
signing is ``tools/mode_package.py``'s. Private keys never go into either
repository. Needs PyYAML and cryptography.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "controller"))

from atalaia_controller import firmware_release as fr  # noqa: E402
from atalaia_controller import mode_package as mp  # noqa: E402

_spec = importlib.util.spec_from_file_location("mode_package_tool", REPO / "tools" / "mode_package.py")
tool = importlib.util.module_from_spec(_spec)
sys.modules["mode_package_tool"] = tool
_spec.loader.exec_module(tool)  # type: ignore[union-attr]

RESERVED_PREFIX = "org.atalaia."     # the project's built-in modes (decision P5G-6)
OWNER = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?")  # a GitHub handle
KEY_FILE_KEYS = {"key_id", "public_key", "owner", "name", "added"}
MAX_ASSETS_BYTES = 512 * 1024        # review checklist item 9 (ADR-P5-8)
PACKAGE_SUFFIXES = (".tar", ".tar.release.json", ".tar.verified.json", ".tar.license")
# Review checklist item 5: what a mode's Lua must not name (the sandbox removes them anyway;
# the battery, core/tests/test_sandbox_escape.c, proves it). Field and method names (e.load,
# t:os) are not these globals.
FORBIDDEN_LUA = re.compile(
    r"(?<![\w.:])(io|os|require|load|loadfile|dofile|loadstring|debug|package|_G|_ENV|collectgarbage)\b"
    r"|\bstring\s*\.\s*dump\b|:\s*dump\s*\(")
# REUSE-IgnoreStart (SPDX text the checks look for, not this file's licence)
SPDX_LICENCE = re.compile(r"SPDX-License-Identifier:\s*(\S+)")
# REUSE-IgnoreEnd


# ---- reading a registry -----------------------------------------------------------------------

@dataclass
class Key:
    key_id: str
    public_key: str
    owner: str
    name: str
    project: bool


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")

    def print(self) -> None:
        gha = os.environ.get("GITHUB_ACTIONS") == "true"
        for kind, items in (("warning", self.warnings), ("error", self.errors)):
            for item in items:
                where = item.partition(": ")[0]
                if gha:
                    print(f"::{kind} file={where.split(' ')[0]}::{item}")
                else:
                    print(f"{kind.upper()} {item}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_keys(root: Path, report: Report) -> dict[str, Key]:
    keys: dict[str, Key] = {}
    for folder, project in (("authors", False), ("project", True)):
        for path in sorted((root / "keys" / folder).glob("*")):
            rel = path.relative_to(root).as_posix()
            if path.name == "README.md":
                continue
            if path.suffix != ".json":
                report.error(rel, "keys/authors/ and keys/project/ hold <key id>.json files only")
                continue
            try:
                data = read_json(path)
            except (ValueError, UnicodeDecodeError) as exc:
                report.error(rel, f"not JSON: {exc}")
                continue
            if not isinstance(data, dict) or set(data) - KEY_FILE_KEYS or {"key_id", "public_key", "owner"} - set(data):
                report.error(rel, "a key file is {key_id, public_key, owner, name?, added?}")
                continue
            raw = fr.public_key_bytes(data["public_key"])
            if raw is None:
                report.error(rel, "public_key is not 32 bytes of base64")
                continue
            kid = fr.key_id(data["public_key"])
            if data["key_id"] != kid or path.stem != kid:
                report.error(rel, f"the key's id is {kid}: the file is keys/{folder}/{kid}.json with that key_id")
                continue
            if not isinstance(data["owner"], str) or not OWNER.fullmatch(data["owner"]):
                report.error(rel, "owner is the GitHub handle of who holds the key")
                continue
            for name in ("name", "added"):
                if name in data and (not isinstance(data[name], str) or len(data[name]) > 120):
                    report.error(rel, f"{name} is a short text")
            if "added" in data and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data["added"])):
                report.error(rel, "added is YYYY-MM-DD")
            if kid in keys:
                report.error(rel, "the same key is both an author's and the project's")
                continue
            keys[kid] = Key(kid, data["public_key"], data["owner"], str(data.get("name", "")), project)
    return keys


def package_name(mode_id: str, version: str) -> str:
    return f"{mode_id}-{version}.tar"


def newest(versions: list[str]) -> str:
    return max(versions, key=lambda v: fr.version_key(v) or ())


def code_only(lua: str) -> str:
    """Lua with comments and string literals blanked out (so FORBIDDEN_LUA sees code only)."""
    out: list[str] = []
    i, n = 0, len(lua)
    long_open = re.compile(r"\[(=*)\[")
    while i < n:
        c = lua[i]
        if lua.startswith("--", i):
            m = long_open.match(lua, i + 2)
            if m:
                end = lua.find("]" + m.group(1) + "]", m.end())
                i = n if end < 0 else end + len(m.group(1)) + 2
            else:
                end = lua.find("\n", i)
                i = n if end < 0 else end
            out.append(" ")
            continue
        m = long_open.match(lua, i) if c == "[" else None
        if m:
            end = lua.find("]" + m.group(1) + "]", m.end())
            i = n if end < 0 else end + len(m.group(1)) + 2
            out.append('""')
            continue
        if c in "\"'":
            j = i + 1
            while j < n and lua[j] != c and lua[j] != "\n":
                j += 2 if lua[j] == "\\" else 1
            i = j + 1 if j < n and lua[j] == c else j
            out.append('""')
            continue
        out.append(c)
        i += 1
    return "".join(out)


def check_package_files(where: str, files: dict[str, str], licence: str, report: Report) -> None:
    """The review checklist's automated items on a package's files (3, 5, 9, 11)."""
    for name, text in sorted(files.items()):
        if name.endswith((".lua", ".yaml", ".yml")):
            head = "\n".join(text.splitlines()[:10])
            found = SPDX_LICENCE.search(head)
            if not found:
                report.error(where, f"{name} has no SPDX-License-Identifier header (checklist item 3)")
            elif found.group(1) != licence:
                report.error(where, f"{name} says {found.group(1)}, mode.yaml says {licence} (checklist item 3)")
        if name.endswith(".lua"):
            code = code_only(text)
            for m in FORBIDDEN_LUA.finditer(code):
                line = code.count("\n", 0, m.start()) + 1
                report.error(where, f"{name}:{line} uses {m.group(0).strip()!r}, which the sandbox removes "
                                    f"(checklist item 5)")
    assets = sum(len(t.encode("utf-8")) for n, t in files.items() if n.startswith("assets/"))
    if assets > MAX_ASSETS_BYTES:
        report.error(where, f"assets/ is {assets} bytes; at most {MAX_ASSETS_BYTES} (checklist item 9)")
    try:
        import yaml  # noqa: PLC0415

        manifest = yaml.safe_load(files.get("mode.yaml", "")) or {}
    except Exception:  # noqa: BLE001 - verify() already parsed it
        return
    i18n = manifest.get("i18n") if isinstance(manifest, dict) else None
    if isinstance(i18n, dict) and i18n:
        def paths(value: Any, prefix: str = "") -> set[str]:
            if isinstance(value, dict):
                return set().union(*(paths(v, f"{prefix}{k}.") for k, v in value.items())) if value else set()
            return {prefix.rstrip(".")}

        sets = {lang: paths(strings) for lang, strings in i18n.items()}
        every = set().union(*sets.values())
        for lang, keys in sorted(sets.items()):
            if keys != every:
                report.error(where, f"mode.yaml i18n.{lang} lacks {', '.join(sorted(every - keys))} "
                                    f"(every language has the same keys, checklist item 11)")
        for lang, strings in i18n.items():
            for section in ("params", "commands"):
                declared = manifest.get(section) or {}
                for name in (strings or {}).get(section, {}) if isinstance(strings, dict) else {}:
                    if name not in declared:
                        report.error(where, f"mode.yaml i18n.{lang}.{section}.{name} is not a declared {section[:-1]}")


def read_source(folder: Path) -> tuple[dict[str, str], list[str]]:
    return tool.read_folder(folder)


# ---- lint ---------------------------------------------------------------------------------------

@dataclass
class Registry:
    root: Path
    index: dict[str, Any]
    entries: list[mp.IndexEntry]
    revoked: dict[str, str]
    keys: dict[str, Key]


def load(root: Path, report: Report) -> Optional[Registry]:
    try:
        index = read_json(root / "index.json")
        entries = mp.parse_index(index)
    except (OSError, ValueError) as exc:
        report.error("index.json", str(exc))
        return None
    try:
        revoked = mp.parse_revoked(read_json(root / "keys" / "revoked.json"))
    except (OSError, ValueError) as exc:
        report.error("keys/revoked.json", str(exc))
        return None
    return Registry(root, index, entries, revoked, read_keys(root, report))


def lint(root: Path, base: Optional[Path] = None) -> Report:
    report = Report()
    reg = load(root, report)
    if reg is None:
        return report
    author_keys = [k.public_key for k in reg.keys.values() if not k.project]
    project_keys = [k.public_key for k in reg.keys.values() if k.project]
    for kid in reg.revoked:
        if kid not in reg.keys:
            report.warn("keys/revoked.json", f"{kid} is revoked but has no key file (kept for history?)")

    referenced: set[str] = set()
    owners: dict[str, set[str]] = {}
    by_id: dict[str, list[str]] = {}
    for entry in reg.entries:
        rel = entry.release
        where = f"index.json {rel.id} {rel.version}"
        by_id.setdefault(rel.id, []).append(rel.version)
        if rel.id.startswith(RESERVED_PREFIX):
            report.error(where, f"ids starting {RESERVED_PREFIX} are the project's built-in modes")
        name = package_name(rel.id, rel.version)
        if entry.url != f"packages/{name}":
            report.error(where, f"url must be packages/{name}: the registry keeps every package it lists")
            continue
        archive_path = root / "packages" / name
        release_path = root / "packages" / (name + ".release.json")
        verified_path = root / "packages" / (name + ".verified.json")
        licence_path = root / "packages" / (name + ".license")
        referenced.update(p.name for p in (archive_path, release_path, verified_path, licence_path))
        missing = [p.name for p in (archive_path, release_path, licence_path) if not p.is_file()]
        if missing:
            report.error(where, f"missing packages/{', packages/'.join(missing)}")
            continue
        archive = archive_path.read_bytes()
        # The author's signature: who made it (checklist item 12).
        try:
            data = read_json(release_path)
            author_release = mp.release_from(data)
            named = data.get("key_id") if isinstance(data.get("key_id"), str) else None
            package = mp.verify(archive, author_release, author_keys, reg.revoked, named_key=named)
        except (ValueError, OSError) as exc:
            report.error(f"packages/{release_path.name}", f"the author's signature: {exc}")
            continue
        if (author_release.id, author_release.version) != (rel.id, rel.version) or author_release.manifest() != \
                rel.manifest():
            report.error(where, "the index's id, version, kind, tier, size or sha256 are not the author's release")
            continue
        if data.get("license") != package.license or entry.license != package.license:
            report.error(where, f"license must be the package's own: {package.license}")
        owner = reg.keys[package.key_id].owner
        owners.setdefault(rel.id, set()).add(owner)
        lic_text = licence_path.read_text(encoding="utf-8")
        # REUSE-IgnoreStart (SPDX text the checks look for, not this file's licence)
        if f"SPDX-License-Identifier: {package.license}" not in lic_text or "SPDX-FileCopyrightText:" not in lic_text:
            report.error(f"packages/{licence_path.name}",
                         f"needs SPDX-FileCopyrightText and SPDX-License-Identifier: {package.license}")
        # REUSE-IgnoreEnd
        check_package_files(where, package.files, package.license, report)
        # The index's signature: the author's, or the project's with the badge.
        if entry.verified:
            if not verified_path.is_file():
                report.error(where, f"verified needs packages/{verified_path.name} (the project's signature)")
                continue
            try:
                vdata = read_json(verified_path)
                vrel = mp.release_from(vdata)
                vnamed = vdata.get("key_id") if isinstance(vdata.get("key_id"), str) else None
                vpackage = mp.verify(archive, vrel, project_keys, reg.revoked, named_key=vnamed)
            except (ValueError, OSError) as exc:
                report.error(f"packages/{verified_path.name}", f"the project's signature: {exc}")
                continue
            if (entry.release.signature, entry.key_id) != (vrel.signature, vpackage.key_id):
                report.error(where, "a verified version lists the project's signature and key id")
        else:
            if verified_path.exists():
                report.error(where, f"not verified, but packages/{verified_path.name} is there: remove one or "
                                    f"the other")
            if (entry.release.signature, entry.key_id) != (author_release.signature, package.key_id):
                report.error(where, "a version that is not verified lists the author's signature and key id")

    for mode_id, who in sorted(owners.items()):
        if len(who) > 1:
            report.error(f"index.json {mode_id}", f"versions signed by keys of different owners: "
                                                  f"{', '.join(sorted(who))} (one id, one owner)")
    for path in sorted((root / "packages").glob("*")) if (root / "packages").is_dir() else []:
        if path.name not in referenced and path.name != "README.md":
            report.error(f"packages/{path.name}", "not a file of any version in index.json")

    # The sources: what the review reads must be what is signed (checklist items 1 and 4).
    sources = {p.name for p in (root / "modes").glob("*") if p.is_dir()} if (root / "modes").is_dir() else set()
    for mode_id, versions in sorted(by_id.items()):
        folder = root / "modes" / mode_id
        where = f"modes/{mode_id}"
        if mode_id not in sources:
            report.error(where, "missing: the source of the newest version, with its tests/")
            continue
        top = newest(versions)
        files, _ = read_source(folder)
        try:
            own = mp.manifest_fields(files)
            packed = mp.pack(own["id"], files)
        except mp.PackageError as exc:
            report.error(where, str(exc))
            continue
        archive_path = root / "packages" / package_name(mode_id, top)
        if archive_path.is_file() and packed != archive_path.read_bytes():
            report.error(where, f"does not pack to packages/{archive_path.name}, the newest version: pack and "
                                f"sign again (a new version if {top} was published)")
        tests = sorted((folder / "tests").glob("*.yaml"))
        if not tests:
            report.error(where, "has no tests/*.yaml (checklist item 4)")
    for name in sorted(sources - set(by_id)):
        report.error(f"modes/{name}", "not in index.json (add it with registry_check.py add)")

    if base is not None:
        compare_base(root, base, reg, report)
    return report


def compare_base(root: Path, base: Path, reg: Registry, report: Report) -> None:
    """A published version never changes (its archive and the author's signature); it may be
    removed (moderation) or gain or lose the badge. An id keeps its owner."""
    old_report = Report()
    old = load(base, old_report)
    if old is None:
        report.warn("index.json", "the base branch's index does not read; not compared")
        return
    now = {(e.release.id, e.release.version): e for e in reg.entries}
    old_owner: dict[str, str] = {}
    for entry in old.entries:
        key = (entry.release.id, entry.release.version)
        name = package_name(*key)
        try:
            data = read_json(base / "packages" / (name + ".release.json"))
            kid = data.get("key_id")
            if kid in old.keys:
                old_owner[key[0]] = old.keys[kid].owner
        except (OSError, ValueError):
            pass
        if key not in now:
            report.warn(f"index.json {key[0]} {key[1]}", "removed from the index (a moderation decision?)")
            continue
        if now[key].release.sha256 != entry.release.sha256 or now[key].release.size != entry.release.size:
            report.error(f"index.json {key[0]} {key[1]}", "a published version changed: publish a new version")
    for entry in reg.entries:
        mode_id = entry.release.id
        try:
            data = read_json(root / "packages" / (package_name(mode_id, entry.release.version) + ".release.json"))
            owner = reg.keys[data["key_id"]].owner
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if mode_id in old_owner and owner != old_owner[mode_id]:
            report.warn(f"index.json {mode_id}", f"owner changes from {old_owner[mode_id]} to {owner}: only with "
                                                 f"the maintainers' decision (docs/community/moderation.md)")


# ---- test ---------------------------------------------------------------------------------------

def run_tests(root: Path, lib: str) -> int:
    folders = sorted(p for p in (root / "modes").glob("*") if (p / "mode.yaml").is_file())
    if not folders:
        print("registry_check: no modes in modes/")
        return 0
    env = dict(os.environ)
    if lib:
        env["ATALAIA_CORE_LIB"] = str(Path(lib).resolve())
    cmd = [sys.executable, "-m", "atalaia_sim", "test", *[str(p.resolve()) for p in folders]]
    return subprocess.run(cmd, cwd=REPO / "simulator", env=env, check=False).returncode


# ---- key, add, badge ----------------------------------------------------------------------------

def fail(message: str) -> int:
    print(f"registry_check: {message}", file=sys.stderr)
    return 1


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def cmd_key(args: argparse.Namespace) -> int:
    root = Path(args.registry)
    public = tool.parse_keys(args.public)
    if len(public) != 1:
        return fail("--public is one key")
    if not OWNER.fullmatch(args.owner):
        return fail("--owner is a GitHub handle")
    kid = fr.key_id(public[0])
    folder = root / "keys" / ("project" if args.project else "authors")
    other = root / "keys" / ("authors" if args.project else "project") / f"{kid}.json"
    if other.exists():
        return fail(f"{kid} is already listed in {other.parent.name}/")
    folder.mkdir(parents=True, exist_ok=True)
    data = {"key_id": kid, "public_key": public[0], "owner": args.owner}
    if args.name:
        data["name"] = args.name
    if args.added:
        data["added"] = args.added
    (folder / f"{kid}.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"keys/{folder.name}/{kid}.json: {args.owner}")
    return 0


def copyright_lines(files: dict[str, str]) -> list[str]:
    found: list[str] = []
    for text in files.values():
        for line in text.splitlines()[:10]:
            m = re.search(r"SPDX-FileCopyrightText:\s*(.+)$", line)
            if m and m.group(1).strip() not in found:
                found.append(m.group(1).strip())
    return found


def set_entry(root: Path, mode_id: str, version: str, update: dict[str, Any]) -> None:
    index = read_json(root / "index.json")
    for mode in index["modes"]:
        if mode["id"] == mode_id:
            for entry in mode["versions"]:
                if entry["version"] == version:
                    entry.update(update)
    mp.parse_index(index)
    (root / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def sign_to(root: Path, archive_path: Path, key_path: Path, out: Path, licence: str) -> str:
    """Signs an archive's manifest with a key outside both repositories; the key's id."""
    if inside(key_path, root) or not tool.outside_repo(key_path):
        raise SystemExit(fail(f"{key_path} is inside a repository: a private key never goes there"))
    key = tool.load_private(key_path)
    release = mp.sign_release(key, archive_path.read_bytes())
    kid = fr.key_id(base64.b64encode(tool.raw_public(key)).decode("ascii"))
    out.write_text(json.dumps(mp.release_json(release, kid, licence), indent=2) + "\n", encoding="utf-8")
    return kid


def cmd_add(args: argparse.Namespace) -> int:
    root = Path(args.registry)
    folder = root / "modes" / args.id
    if not (folder / "mode.yaml").is_file():
        return fail(f"modes/{args.id}/mode.yaml is missing: the source goes there first")
    files, skipped = read_source(folder)
    try:
        own = mp.manifest_fields(files)
        archive = mp.pack(own["id"], files)
    except mp.PackageError as exc:
        return fail(str(exc))
    if own["id"] != args.id:
        return fail(f"modes/{args.id}/mode.yaml says id {own['id']}")
    name = package_name(own["id"], own["version"])
    packages = root / "packages"
    packages.mkdir(exist_ok=True)
    archive_path = packages / name
    if archive_path.exists() and archive_path.read_bytes() != archive:
        return fail(f"packages/{name} exists with other files: {own['version']} is published; raise the version")
    archive_path.write_bytes(archive)
    kid = sign_to(root, archive_path, Path(args.key).expanduser(), packages / (name + ".release.json"),
                  own["license"])
    key_file = root / "keys" / "authors" / f"{kid}.json"
    if not key_file.is_file():
        print(f"registry_check: note: key {kid} is not in keys/authors/ yet; add it with `key` (lint refuses "
              f"the package until then)", file=sys.stderr)
    copyright_text = copyright_lines(files) or ["the author"]
    # REUSE-IgnoreStart (SPDX text the checks look for, not this file's licence)
    (packages / (name + ".license")).write_text(
        "".join(f"SPDX-FileCopyrightText: {c}\n" for c in copyright_text)
        + f"SPDX-License-Identifier: {own['license']}\n", encoding="utf-8")
    # REUSE-IgnoreEnd
    stale = packages / (name + ".verified.json")
    if stale.exists():
        stale.unlink()
    rc = tool.main(["index", str(root / "index.json"), str(packages / (name + ".release.json")),
                    "--url", f"packages/{name}"] + [f"--{k}={getattr(args, k)}" for k in ("name", "description",
                                                                                         "author") if getattr(args, k)])
    for left in skipped:
        if not left.startswith("tests/"):
            print(f"  left out of the package: {left}")
    return rc


def cmd_badge(args: argparse.Namespace) -> int:
    root = Path(args.registry)
    name = package_name(args.id, args.version)
    packages = root / "packages"
    archive_path = packages / name
    if not archive_path.is_file():
        return fail(f"packages/{name} is not there")
    author = read_json(packages / (name + ".release.json"))
    verified_path = packages / (name + ".verified.json")
    if args.remove:
        if verified_path.exists():
            verified_path.unlink()
        set_entry(root, args.id, args.version, {"signature": author["signature"], "key_id": author["key_id"],
                                                "verified": False})
        print(f"{args.id} {args.version}: not reviewed")
        return 0
    kid = sign_to(root, archive_path, Path(args.key).expanduser(), verified_path, author["license"])
    if not (root / "keys" / "project" / f"{kid}.json").is_file():
        verified_path.unlink()
        return fail(f"key {kid} is not one of the project's (keys/project/)")
    vdata = read_json(verified_path)
    set_entry(root, args.id, args.version, {"signature": vdata["signature"], "key_id": kid, "verified": True})
    print(f"{args.id} {args.version}: verified, signed by the project's key {kid}")
    return 0


# ---- site ---------------------------------------------------------------------------------------

def badge_svg(label: str, value: str, colour: str) -> str:
    lw, vw = 6 * len(label) + 12, 6 * len(value) + 12
    w = lw + vw
    esc = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}
    value = "".join(esc.get(c, c) for c in value)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="20" role="img" '
            f'aria-label="{label}: {value}"><title>{label}: {value}</title>'
            f'<rect width="{lw}" height="20" fill="#3b3b3b"/><rect x="{lw}" width="{vw}" height="20" '
            f'fill="{colour}"/><g fill="#fff" font-family="Verdana,DejaVu Sans,sans-serif" font-size="11" '
            f'text-anchor="middle"><text x="{lw / 2}" y="14">{label}</text><text x="{lw + vw / 2}" '
            f'y="14">{value}</text></g></svg>\n')


def cmd_site(args: argparse.Namespace) -> int:
    root, out = Path(args.registry), Path(args.out)
    report = lint(root)
    report.print()
    if report.errors:
        return fail("the registry does not pass lint; nothing published")
    reg = load(root, Report())
    assert reg is not None
    if out.exists():
        shutil.rmtree(out)
    (out / "packages").mkdir(parents=True)
    (out / "badges").mkdir()
    shutil.copyfile(root / "index.json", out / "index.json")
    shutil.copyfile(root / "keys" / "revoked.json", out / "revoked.json")
    keys = {"project": [], "authors": []}
    for k in sorted(reg.keys.values(), key=lambda k: k.key_id):
        keys["project" if k.project else "authors"].append(
            {"key_id": k.key_id, "public_key": k.public_key, "owner": k.owner, "name": k.name,
             "revoked": k.key_id in reg.revoked})
    (out / "keys.json").write_text(json.dumps(keys, indent=2) + "\n", encoding="utf-8")
    newest_entry: dict[str, mp.IndexEntry] = {}
    for entry in reg.entries:
        name = package_name(entry.release.id, entry.release.version)
        for suffix in ("", ".release.json", ".verified.json", ".license"):
            if (root / "packages" / (name + suffix)).is_file():
                shutil.copyfile(root / "packages" / (name + suffix), out / "packages" / (name + suffix))
        current = newest_entry.get(entry.release.id)
        if current is None or (fr.version_key(entry.release.version) or ()) > (
                fr.version_key(current.release.version) or ()):
            newest_entry[entry.release.id] = entry
    for mode_id, entry in sorted(newest_entry.items()):
        svg = (badge_svg("atalaia", f"verified {entry.release.version}", "#2e7d32") if entry.verified
               else badge_svg("atalaia", f"not reviewed {entry.release.version}", "#757575"))
        (out / "badges" / f"{mode_id}.svg").write_text(svg, encoding="utf-8")
    print(f"{out}: {len(reg.entries)} version(s) of {len(newest_entry)} mode(s), {len(reg.keys)} key(s), "
          f"{len(reg.revoked)} revoked")
    return 0


# ---- main ---------------------------------------------------------------------------------------

def cmd_lint(args: argparse.Namespace) -> int:
    report = lint(Path(args.registry), Path(args.base) if args.base else None)
    report.print()
    if report.errors:
        print(f"registry_check: {len(report.errors)} problem(s)")
        return 1
    reg = load(Path(args.registry), Report())
    count = len(reg.entries) if reg else 0
    print(f"registry_check: OK ({count} version(s), {len(report.warnings)} warning(s))")
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    return run_tests(Path(args.registry), args.lib)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("lint", help="check the registry (registry-lint)")
    p.add_argument("registry")
    p.add_argument("--base", default="", help="the base branch's checkout: published versions must not change")
    p.set_defaults(func=cmd_lint)
    p = sub.add_parser("test", help="run each mode's tests in the simulator (registry-test)")
    p.add_argument("registry")
    p.add_argument("--lib", default="", help="libatalaia_core.so (default: ATALAIA_CORE_LIB or the usual places)")
    p.set_defaults(func=cmd_test)
    p = sub.add_parser("key", help="add a public mode key")
    p.add_argument("registry")
    p.add_argument("--public", required=True, help="the public key, base64 or hex (tools/mode_package.py pubkey)")
    p.add_argument("--owner", required=True, help="the GitHub handle of who holds it")
    p.add_argument("--name", default="")
    p.add_argument("--added", default="", help="YYYY-MM-DD")
    p.add_argument("--project", action="store_true", help="a project registry key (maintainers only)")
    p.set_defaults(func=cmd_key)
    p = sub.add_parser("add", help="pack, sign and list modes/ID (not reviewed)")
    p.add_argument("registry")
    p.add_argument("id")
    p.add_argument("--key", required=True, help="the author's private mode key (outside every repository)")
    p.add_argument("--name", default="")
    p.add_argument("--description", default="")
    p.add_argument("--author", default="")
    p.set_defaults(func=cmd_add)
    p = sub.add_parser("badge", help="the verified badge: the project's key signs a version")
    p.add_argument("registry")
    p.add_argument("id")
    p.add_argument("version")
    p.add_argument("--key", default="", help="the project's registry key (outside every repository)")
    p.add_argument("--remove", action="store_true", help="take the badge away")
    p.set_defaults(func=cmd_badge)
    p = sub.add_parser("site", help="what the registry publishes")
    p.add_argument("registry")
    p.add_argument("out")
    p.set_defaults(func=cmd_site)
    args = parser.parse_args(argv)
    if args.command == "badge" and not args.remove and not args.key:
        return fail("badge needs --key (or --remove)")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
