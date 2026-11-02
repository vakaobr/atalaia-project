#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The version files and the CHANGELOG of a release, for release-please (.github/workflows/release-please.yml).

    python3 tools/prepare_release.py release-pr [--version 0.6.0]
        run on release-please's release pull request branch (the version defaults to what
        .release-please-manifest.json says there). release-please writes the CHANGELOG section
        "## [X.Y.Z](compare link) (date)" from the pull request titles and bumps the files that
        carry an x-release-please-version marker; this does what a marker cannot: every version
        file says exactly X.Y.Z (core/include/atalaia/version.h with its pre-release emptied, or
        the version's own label; core/CMakeLists.txt, numbers only; app/pubspec.yaml, its build
        number kept; app/lib/version.dart; controller and server __init__.py: what
        controller/tests/test_versions.py and app/test/version_test.dart check), and the
        hand-written "## [Unreleased]" body moves under that section as "### Details", with an
        empty "## [Unreleased]" back on top. Then `check`. Running it twice changes nothing.
    python3 tools/prepare_release.py open-dev --released 0.5.0 [--next 0.6.0]
        the commit after a release (decision FV-1, PREP-3): the core's version (version.h and
        CMake only, as cfcd1382 did) becomes the next version with "dev" again, so builds sort
        above the release. Default: the next minor; after a pre-release, the same X.Y.Z.
    python3 tools/prepare_release.py check --version 0.5.0
        every version file and the CHANGELOG agree with the version (what a release is made from).

Standard library only; --root runs it on another checkout (the unit tests and the workflow do).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple, Optional

REPO = Path(__file__).resolve().parents[1]

VERSION_H = "core/include/atalaia/version.h"
CMAKE = "core/CMakeLists.txt"
PUBSPEC = "app/pubspec.yaml"
DART = "app/lib/version.dart"
CONTROLLER = "controller/atalaia_controller/__init__.py"
SERVER = "server/atalaia_server/__init__.py"
CHANGELOG = "CHANGELOG.md"
MANIFEST = ".release-please-manifest.json"

_ID = r"[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*"
VERSION = re.compile(rf"(\d{{1,4}})\.(\d{{1,4}})\.(\d{{1,4}})(?:-({_ID}))?")
FW_VERSION_LEN = 31  # fw_version_valid(): the box takes at most 31 characters
PRE_LEN = 20  # and 20 for the pre-release


class PrepareError(Exception):
    """Something the maintainer has to fix; the message says what."""


class Version(NamedTuple):
    major: int
    minor: int
    patch: int
    pre: str = ""

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}" + (f"-{self.pre}" if self.pre else "")

    @property
    def numbers(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def order(self) -> tuple:
        """SemVer order: a pre-release sorts below its release; identifiers compare one by one,
        numbers as numbers and below words."""
        ids = tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in self.pre.split(".")) if self.pre else ()
        return (self.major, self.minor, self.patch, 0 if self.pre else 1, ids)


def parse_version(text: str) -> Version:
    m = VERSION.fullmatch(text.strip())
    if not m:
        raise PrepareError(f"{text!r} is not a version (MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-pre-release)")
    v = Version(int(m[1]), int(m[2]), int(m[3]), m[4] or "")
    if len(v.pre) > PRE_LEN or len(str(v)) > FW_VERSION_LEN:
        raise PrepareError(f"{text!r} is too long for the firmware's version field (pre-release 20, total 31 characters)")
    return v


def _read(root: Path, name: str) -> str:
    try:
        return (root / name).read_text(encoding="utf-8")
    except OSError as exc:
        raise PrepareError(f"cannot read {name}: {exc}") from exc


def _sub1(pattern: str, repl: str, text: str, name: str) -> str:
    """Replace exactly one match, or refuse: a file that changed shape is the maintainer's to look at."""
    out, n = re.subn(pattern, repl, text, flags=re.MULTILINE)
    if n != 1:
        raise PrepareError(f"{name}: expected one match of {pattern!r}, found {n}")
    return out


def core_version(root: Path) -> Version:
    text = _read(root, VERSION_H)
    nums = [re.search(rf"^#define ATALAIA_VERSION_{n}\s+(\d+)", text, re.M) for n in ("MAJOR", "MINOR", "PATCH")]
    pre = re.search(r'^#define ATALAIA_VERSION_PRERELEASE\s+"([0-9A-Za-z.]*)"', text, re.M)
    if not all(nums) or pre is None:
        raise PrepareError(f"{VERSION_H}: no ATALAIA_VERSION_MAJOR/MINOR/PATCH/PRERELEASE")
    return Version(int(nums[0][1]), int(nums[1][1]), int(nums[2][1]), pre[1])  # type: ignore[index]


def released_versions(changelog: str) -> list[Version]:
    out = []
    for m in re.finditer(r"^## \[([^\]]+)\]", changelog, re.M):
        if m[1] != "Unreleased":
            out.append(parse_version(m[1]))
    return out


def _section(name: str) -> re.Pattern[str]:
    """A "## [name]..." section: its heading line, then its body up to the next "## [" or the end."""
    return re.compile(rf"^## \[{re.escape(name)}\][^\n]*\n(.*?)(?=^## \[|\Z)", re.S | re.M)


def fold_changelog(text: str, version: Version) -> str:
    """The hand-written Unreleased body goes to the end of release-please's section for the version,
    as "### Details" (its own ### headings one level down); an empty "## [Unreleased]" goes back
    right above that section, where release-please inserts the next one."""
    unreleased = _section("Unreleased").search(text)
    body = ""
    if unreleased:
        body = unreleased[1].strip()
        text = text[:unreleased.start()] + text[unreleased.end():]
    release = _section(str(version)).search(text)
    if not release:
        raise PrepareError(f"CHANGELOG.md has no section [{version}] (release-please writes it)")
    heading = text[release.start():release.start(1)].rstrip("\n")
    parts = [release[1].strip()]
    if body:
        parts.append("### Details\n\n" + re.sub(r"^(#{3,5}) ", r"#\1 ", body, flags=re.M))
    new = "## [Unreleased]\n\n" + heading + "\n\n" + "\n\n".join(part for part in parts if part) + "\n"
    rest = text[release.end():]
    return text[:release.start()] + new + ("\n" + rest if rest else "")


def _set_core(root: Path, version: Version, pre: str, files: dict[str, str]) -> None:
    h = _read(root, VERSION_H)
    for name, value in (("MAJOR", version.major), ("MINOR", version.minor), ("PATCH", version.patch)):
        h = _sub1(rf"^(#define ATALAIA_VERSION_{name}\s+)\d+", rf"\g<1>{value}", h, VERSION_H)
    h = _sub1(r'^(#define ATALAIA_VERSION_PRERELEASE\s+)"[0-9A-Za-z.]*"', rf'\g<1>"{pre}"', h, VERSION_H)
    files[VERSION_H] = h
    c = _read(root, CMAKE)
    files[CMAKE] = _sub1(r"^(project\(atalaia_core VERSION )\d+\.\d+\.\d+", rf"\g<1>{version.numbers}", c, CMAKE)


def _write_all(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():  # every edit succeeded before the first write
        (root / name).write_text(text, encoding="utf-8", newline="")


def set_version_files(root: Path, target: Version, files: dict[str, str]) -> None:
    """Every version file says the version: the core with its pre-release (or none), CMake numbers only."""
    _set_core(root, target, target.pre, files)
    files[PUBSPEC] = _sub1(r"^(version:\s*)[^\s+]+", rf"\g<1>{target}", _read(root, PUBSPEC), PUBSPEC)
    files[DART] = _sub1(r"^(const appVersion = ')[^']+(';)", rf"\g<1>{target}\g<2>", _read(root, DART), DART)
    for name in (CONTROLLER, SERVER):
        files[name] = _sub1(r'^(__version__ = ")[^"]+(")', rf"\g<1>{target}\g<2>", _read(root, name), name)


def manifest_version(root: Path) -> Version:
    """The version release-please's manifest gives the repository's one package (".")."""
    try:
        return parse_version(str(json.loads(_read(root, MANIFEST))["."]))
    except (ValueError, KeyError, TypeError, PrepareError) as exc:
        raise PrepareError(f'{MANIFEST}: no version for the package "." ({exc})') from exc


def release_pr(root: Path, version: Optional[Version] = None) -> Version:
    """What release-please's markers cannot do on its release pull request (the module's doc)."""
    target = version or manifest_version(root)
    files: dict[str, str] = {CHANGELOG: fold_changelog(_read(root, CHANGELOG), target)}
    set_version_files(root, target, files)
    _write_all(root, files)
    bad = check(root, target)
    if bad:
        raise PrepareError("; ".join(bad))
    return target


def open_dev(root: Path, released: Version, next_: Optional[str]) -> Version:
    current = core_version(root)
    if current != released:
        raise PrepareError(f"{VERSION_H} says {current}, not the released {released}: nothing to open")
    if next_:
        target = parse_version(next_)
        if target.pre:
            raise PrepareError("--next is MAJOR.MINOR.PATCH; the pre-release is dev")
    elif released.pre:
        target = Version(released.major, released.minor, released.patch)
    else:
        target = Version(released.major, released.minor + 1, 0)
    if target.order() <= released.order():
        raise PrepareError(f"{target} is not newer than the release {released}")
    files: dict[str, str] = {}
    _set_core(root, target, "dev", files)
    _write_all(root, files)
    return Version(target.major, target.minor, target.patch, "dev")


def check(root: Path, version: Version) -> list[str]:
    """What disagrees with the version, one line each; empty when the tree is a release of it."""
    bad = []
    try:
        if core_version(root) != version:
            bad.append(f"{VERSION_H} says {core_version(root)}")
    except PrepareError as exc:
        bad.append(str(exc))
    expect = {
        CMAKE: (r"^project\(atalaia_core VERSION (\d+\.\d+\.\d+)", version.numbers),
        PUBSPEC: (r"^version:\s*([^\s+]+)", str(version)),
        DART: (r"^const appVersion = '([^']+)';", str(version)),
        CONTROLLER: (r'^__version__ = "([^"]+)"', str(version)),
        SERVER: (r'^__version__ = "([^"]+)"', str(version)),
    }
    for name, (pattern, want) in expect.items():
        m = re.search(pattern, _read(root, name), re.M)
        if not m or m[1] != want:
            bad.append(f"{name} says {m[1] if m else 'nothing'}, not {want}")
    if not any(v == version for v in released_versions(_read(root, CHANGELOG))):
        bad.append(f"CHANGELOG.md has no section [{version}]")
    return bad


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO, help="the checkout to work on")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("release-pr", help="on the release pull request: every version file and the CHANGELOG")
    r.add_argument("--version", help="default: what .release-please-manifest.json says")
    o = sub.add_parser("open-dev", help="after the release: the next version, with dev")
    o.add_argument("--released", required=True)
    o.add_argument("--next")
    c = sub.add_parser("check", help="every version file agrees with the version")
    c.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "release-pr":
            print(release_pr(args.root, parse_version(args.version) if args.version else None))
        elif args.command == "open-dev":
            print(open_dev(args.root, parse_version(args.released), args.next))
        else:
            bad = check(args.root, parse_version(args.version))
            for line in bad:
                print(f"prepare_release: {line}", file=sys.stderr)
            return 1 if bad else 0
    except PrepareError as exc:
        print(f"prepare_release: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
