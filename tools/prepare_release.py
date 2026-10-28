#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Prepares a release the way commit 331dcaad did by hand (.github/workflows/prepare-release.yml).

    python3 tools/prepare_release.py prepare --bump minor            [--date 2026-11-01]
    python3 tools/prepare_release.py prepare --version 0.5.0 [--prerelease rc.1]
        the next version (the bump is counted from the newest released CHANGELOG section, or the
        explicit version, which must be newer than it), then: CHANGELOG.md's "## [Unreleased]" body
        moves under "## [X.Y.Z] - date" (an empty one is refused) and the version files say X.Y.Z:
        core/include/atalaia/version.h (pre-release emptied, or the label), core/CMakeLists.txt,
        app/pubspec.yaml, app/lib/version.dart, controller and server __init__.py (what
        controller/tests/test_versions.py and app/test/version_test.dart check). Prints the version.
    python3 tools/prepare_release.py open-dev --released 0.5.0 [--next 0.6.0]
        the commit after a release (decision FV-1, PREP-3): the core's version (version.h and
        CMake only, as cfcd1382 did) becomes the next version with "dev" again, so builds sort
        above the release. Default: the next minor; after a pre-release, the same X.Y.Z.
    python3 tools/prepare_release.py check --version 0.5.0
        every version file and the CHANGELOG agree with the version (what a tag may be made from).
    python3 tools/prepare_release.py notes --version 0.5.0 --out notes.md
        the CHANGELOG section, cut to a pull request body's size.

Standard library only; --root runs it on another checkout (the unit tests do).
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path
from typing import NamedTuple, Optional

REPO = Path(__file__).resolve().parents[1]
# GitHub refuses a pull request body over 65536 characters; release.yml's own cap is 120000.
NOTES_MAX = 60000

VERSION_H = "core/include/atalaia/version.h"
CMAKE = "core/CMakeLists.txt"
PUBSPEC = "app/pubspec.yaml"
DART = "app/lib/version.dart"
CONTROLLER = "controller/atalaia_controller/__init__.py"
SERVER = "server/atalaia_server/__init__.py"
CHANGELOG = "CHANGELOG.md"

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


def last_released(changelog: str) -> Version:
    found = released_versions(changelog)
    if not found:
        raise PrepareError("CHANGELOG.md has no released section to count a bump from; use --version")
    return max(found, key=Version.order)


def next_version(last: Version, bump: Optional[str], version: Optional[str], prerelease: str = "") -> Version:
    if bool(bump) == bool(version):
        raise PrepareError("give exactly one of --bump and --version")
    if version:
        target = parse_version(version)
        if prerelease:
            if target.pre:
                raise PrepareError("the version already has a pre-release; drop --prerelease")
            target = parse_version(f"{target}-{prerelease}")
    else:
        if bump not in ("patch", "minor", "major"):
            raise PrepareError("--bump is patch, minor or major")
        if last.pre and bump == "patch":
            base = Version(last.major, last.minor, last.patch)  # the release the last pre-release led to
        elif bump == "patch":
            base = Version(last.major, last.minor, last.patch + 1)
        elif bump == "minor":
            base = Version(last.major, last.minor + 1, 0)
        else:
            base = Version(last.major + 1, 0, 0)
        target = parse_version(f"{base}-{prerelease}" if prerelease else str(base))
    if target.order() <= last.order():
        raise PrepareError(f"version {target} is not newer than the last release, {last}")
    return target


def move_unreleased(text: str, version: Version, date: str) -> str:
    """CHANGELOG: the Unreleased body goes under "## [version] - date"; Unreleased stays, empty."""
    m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.S | re.M)
    if not m:
        raise PrepareError('CHANGELOG.md has no "## [Unreleased]" section')
    body = m[1].strip()
    if not body:
        raise PrepareError("the Unreleased section of CHANGELOG.md is empty: nothing to release")
    if any(v == version for v in released_versions(text)):
        raise PrepareError(f"CHANGELOG.md already has a section [{version}]")
    rest = text[m.end():]
    new = f"## [Unreleased]\n\n## [{version}] - {date}\n\n{body}\n" + ("\n" + rest if rest else "")
    return text[:m.start()] + new


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


def prepare(root: Path, bump: Optional[str], version: Optional[str], prerelease: str, date: str) -> Version:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise PrepareError(f"{date!r} is not a date (YYYY-MM-DD)")
    changelog = _read(root, CHANGELOG)
    target = next_version(last_released(changelog), bump, version, prerelease)
    files: dict[str, str] = {CHANGELOG: move_unreleased(changelog, target, date)}
    _set_core(root, target, target.pre, files)
    files[PUBSPEC] = _sub1(r"^(version:\s*)[^\s+]+", rf"\g<1>{target}", _read(root, PUBSPEC), PUBSPEC)
    files[DART] = _sub1(r"^(const appVersion = ')[^']+(';)", rf"\g<1>{target}\g<2>", _read(root, DART), DART)
    for name in (CONTROLLER, SERVER):
        files[name] = _sub1(r'^(__version__ = ")[^"]+(")', rf"\g<1>{target}\g<2>", _read(root, name), name)
    _write_all(root, files)
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


def notes(root: Path, version: Version, limit: int = NOTES_MAX) -> str:
    m = re.search(rf"^## \[{re.escape(str(version))}\][^\n]*\n(.*?)(?=^## \[|\Z)", _read(root, CHANGELOG), re.S | re.M)
    if not m or not m[1].strip():
        raise PrepareError(f"CHANGELOG.md has no section [{version}]")
    body = m[1].strip() + "\n"
    if len(body) > limit:  # as release_package.py cuts the release's text: at a line, with a pointer
        tail = "\n(The rest of the list is in CHANGELOG.md.)\n"
        body = body[:limit - len(tail)].rsplit("\n", 1)[0] + "\n" + tail
    return body


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=REPO, help="the checkout to work on")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="move the Unreleased section and bump the version files")
    p.add_argument("--bump", choices=["patch", "minor", "major"])
    p.add_argument("--version")
    p.add_argument("--prerelease", default="", help="a label such as rc.1")
    p.add_argument("--date", default=datetime.date.today().isoformat())
    o = sub.add_parser("open-dev", help="after the release: the next version, with dev")
    o.add_argument("--released", required=True)
    o.add_argument("--next")
    c = sub.add_parser("check", help="every version file agrees with the version")
    c.add_argument("--version", required=True)
    n = sub.add_parser("notes", help="the CHANGELOG section, cut to a pull request body's size")
    n.add_argument("--version", required=True)
    n.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            print(prepare(args.root, args.bump, args.version, args.prerelease.strip(), args.date))
        elif args.command == "open-dev":
            print(open_dev(args.root, parse_version(args.released), args.next))
        elif args.command == "check":
            bad = check(args.root, parse_version(args.version))
            for line in bad:
                print(f"prepare_release: {line}", file=sys.stderr)
            return 1 if bad else 0
        else:
            text = notes(args.root, parse_version(args.version))
            args.out.write_text(text, encoding="utf-8")
            print(f"{args.out}: {len(text)} characters")
    except PrepareError as exc:
        print(f"prepare_release: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
