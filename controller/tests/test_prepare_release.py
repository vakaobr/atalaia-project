# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/prepare_release.py makes the release commit 331dcaad made by hand (decisions PREP-1 to PREP-8)."""

from __future__ import annotations

import importlib.util
import re
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prepare_release", REPO / "tools" / "prepare_release.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

FILES = [tool.VERSION_H, tool.CMAKE, tool.PUBSPEC, tool.DART, tool.CONTROLLER, tool.SERVER, tool.CHANGELOG]


def V(text: str):
    return tool.parse_version(text)


class Tree(unittest.TestCase):
    """A scratch copy of the files the tool edits, from the real repository."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for name in FILES:
            (self.root / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO / name, self.root / name)
        # The tree as just after the 0.4.0 release, whatever the real repository says now (a dev
        # version after a release, an rc before one).
        files: dict[str, str] = {}
        tool._set_core(self.root, V("0.4.0"), "", files)
        tool._write_all(self.root, files)
        for name, pattern in ((tool.PUBSPEC, r"^(version:\s*)[^\s+]+"), (tool.DART, r"^(const appVersion = ')[^']+"),
                              (tool.CONTROLLER, r'^(__version__ = ")[^"]+'), (tool.SERVER, r'^(__version__ = ")[^"]+')):
            p = self.root / name
            p.write_text(re.sub(pattern, r"\g<1>0.4.0", p.read_text(encoding="utf-8"), count=1, flags=re.M),
                         encoding="utf-8", newline="")
        self.set_changelog("## [Unreleased]\n\n### Added\n- A thing.\n\n## [0.4.0] - 2026-10-28\n\nOld.\n\n### Added\n- Old thing.\n")

    def set_changelog(self, text: str) -> None:
        (self.root / tool.CHANGELOG).write_text("# Changelog\n\n" + text, encoding="utf-8")

    def text(self, name: str) -> str:
        return (self.root / name).read_text(encoding="utf-8")


class VersionTests(unittest.TestCase):
    def test_parse_and_order(self) -> None:
        self.assertEqual(str(V("0.5.0-rc.1")), "0.5.0-rc.1")
        for bad in ("0.5", "v0.5.0", "1.2.3.4", "0.5.0-", "0.5.0-a" + "b" * 25):
            with self.assertRaises(tool.PrepareError, msg=bad):
                V(bad)
        order = [V(t).order() for t in ("0.4.0", "0.5.0-rc.1", "0.5.0-rc.2", "0.5.0-rc.10", "0.5.0", "0.5.1", "1.0.0")]
        self.assertEqual(order, sorted(order))
        self.assertLess(V("0.5.0-9").order(), V("0.5.0-alpha").order())  # numbers below words

    def test_bumps(self) -> None:
        last = V("0.4.0")
        self.assertEqual(str(tool.next_version(last, "patch", None)), "0.4.1")
        self.assertEqual(str(tool.next_version(last, "minor", None)), "0.5.0")
        self.assertEqual(str(tool.next_version(last, "major", None)), "1.0.0")
        self.assertEqual(str(tool.next_version(last, "minor", None, "rc.1")), "0.5.0-rc.1")
        self.assertEqual(str(tool.next_version(last, None, "0.9.2")), "0.9.2")
        self.assertEqual(str(tool.next_version(last, None, "0.5.0", "beta")), "0.5.0-beta")

    def test_the_release_after_a_pre_release_is_its_own_numbers(self) -> None:
        self.assertEqual(str(tool.next_version(V("0.5.0-rc.1"), "patch", None)), "0.5.0")
        self.assertEqual(str(tool.next_version(V("0.5.0-rc.1"), None, "0.5.0-rc.2")), "0.5.0-rc.2")

    def test_refusals(self) -> None:
        last = V("0.4.0")
        for args in (("patch", "0.5.0"), (None, None), ("huge", None), (None, "0.4.0"), (None, "0.3.9"),
                     (None, "0.4.0-rc.1"), (None, "0.5.0-rc.1")):
            if args == (None, "0.5.0-rc.1"):
                with self.assertRaises(tool.PrepareError):
                    tool.next_version(last, None, "0.5.0-rc.1", "rc.2")  # two pre-releases
                continue
            with self.assertRaises(tool.PrepareError, msg=str(args)):
                tool.next_version(last, *args)

    def test_last_released_is_the_newest_section_not_the_first(self) -> None:
        text = "## [Unreleased]\n## [0.4.1] - d\nx\n## [0.10.0] - d\nx\n## [0.5.0-rc.1] - d\n"
        self.assertEqual(str(tool.last_released(text)), "0.10.0")
        with self.assertRaises(tool.PrepareError):
            tool.last_released("## [Unreleased]\n")


class PrepareTests(Tree):
    def test_the_real_tree_is_a_release_of_its_own_version(self) -> None:
        """The checkout's files agree with each other, as test_versions.py needs."""
        v = tool.core_version(REPO)
        self.assertEqual(tool.check(REPO, v) if not v.pre else [], [])

    def test_prepare_does_what_331dcaad_did(self) -> None:
        (self.root / tool.VERSION_H).write_text(
            self.text(tool.VERSION_H).replace('PRERELEASE ""', 'PRERELEASE "dev"'), encoding="utf-8")
        self.assertEqual(str(tool.prepare(self.root, "minor", None, "", "2026-11-02")), "0.5.0")
        self.assertEqual(tool.check(self.root, V("0.5.0")), [])
        h = self.text(tool.VERSION_H)
        self.assertIn("#define ATALAIA_VERSION_MINOR      5", h)
        self.assertIn('#define ATALAIA_VERSION_PRERELEASE ""', h)
        self.assertIn("project(atalaia_core VERSION 0.5.0 ", self.text(tool.CMAKE))
        self.assertIn("\nversion: 0.5.0\n", self.text(tool.PUBSPEC))
        self.assertIn("const appVersion = '0.5.0';", self.text(tool.DART))
        self.assertIn('__version__ = "0.5.0"', self.text(tool.CONTROLLER))
        self.assertIn('__version__ = "0.5.0"', self.text(tool.SERVER))
        log = self.text(tool.CHANGELOG)
        self.assertIn("## [Unreleased]\n\n## [0.5.0] - 2026-11-02\n\n### Added\n- A thing.\n\n## [0.4.0] - 2026-10-28\n", log)
        self.assertEqual(log.count("## [Unreleased]"), 1)

    def test_a_pre_release_goes_into_every_file(self) -> None:
        tool.prepare(self.root, None, "0.5.0", "rc.1", "2026-11-02")
        self.assertEqual(tool.check(self.root, V("0.5.0-rc.1")), [])
        self.assertIn('PRERELEASE "rc.1"', self.text(tool.VERSION_H))
        self.assertIn("VERSION 0.5.0 ", self.text(tool.CMAKE))  # CMake keeps no pre-release
        self.assertIn("version: 0.5.0-rc.1", self.text(tool.PUBSPEC))

    def test_a_pubspec_build_number_survives(self) -> None:
        p = self.root / tool.PUBSPEC
        p.write_text(p.read_text(encoding="utf-8").replace("version: 0.4.0", "version: 0.4.0+7"), encoding="utf-8")
        tool.prepare(self.root, "patch", None, "", "2026-11-02")
        self.assertIn("\nversion: 0.4.1+7\n", self.text(tool.PUBSPEC))

    def test_an_empty_unreleased_section_is_refused_and_nothing_changes(self) -> None:
        self.set_changelog("## [Unreleased]\n\n  \n## [0.4.0] - 2026-10-28\n\nOld.\n")
        before = {n: self.text(n) for n in FILES}
        with self.assertRaisesRegex(tool.PrepareError, "empty"):
            tool.prepare(self.root, "minor", None, "", "2026-11-02")
        self.assertEqual(before, {n: self.text(n) for n in FILES})

    def test_a_file_that_changed_shape_stops_before_any_write(self) -> None:
        (self.root / tool.SERVER).write_text("version = 1\n", encoding="utf-8")
        before = {n: self.text(n) for n in FILES}
        with self.assertRaisesRegex(tool.PrepareError, "expected one match"):
            tool.prepare(self.root, "minor", None, "", "2026-11-02")
        self.assertEqual(before, {n: self.text(n) for n in FILES})

    def test_no_unreleased_heading_and_a_repeated_version_are_refused(self) -> None:
        self.set_changelog("## [0.4.0] - 2026-10-28\n\nOld.\n")
        with self.assertRaisesRegex(tool.PrepareError, "no .*Unreleased"):
            tool.prepare(self.root, "minor", None, "", "2026-11-02")
        with self.assertRaises(tool.PrepareError):
            tool.prepare(self.root, "minor", None, "", "02/11/2026")

    def test_a_second_run_finds_nothing_to_release(self) -> None:
        tool.prepare(self.root, "minor", None, "", "2026-11-02")
        with self.assertRaises(tool.PrepareError):
            tool.prepare(self.root, "minor", None, "", "2026-11-02")


class OpenDevTests(Tree):
    def test_opens_the_next_minor_with_dev_in_the_core_only(self) -> None:
        before = {n: self.text(n) for n in (tool.PUBSPEC, tool.DART, tool.CONTROLLER, tool.SERVER, tool.CHANGELOG)}
        self.assertEqual(str(tool.open_dev(self.root, V("0.4.0"), None)), "0.5.0-dev")
        self.assertEqual(str(tool.core_version(self.root)), "0.5.0-dev")
        self.assertIn("VERSION 0.5.0 ", self.text(tool.CMAKE))
        self.assertEqual(before, {n: self.text(n) for n in before})

    def test_explicit_next_and_after_a_pre_release(self) -> None:
        self.assertEqual(str(tool.open_dev(self.root, V("0.4.0"), "1.0.0")), "1.0.0-dev")
        tool.prepare(self.root, None, "1.0.0", "rc.1", "2026-11-02")
        self.assertEqual(str(tool.open_dev(self.root, V("1.0.0-rc.1"), None)), "1.0.0-dev")

    def test_refuses_what_is_not_the_release(self) -> None:
        with self.assertRaisesRegex(tool.PrepareError, "not the released"):
            tool.open_dev(self.root, V("0.3.0"), None)
        with self.assertRaises(tool.PrepareError):
            tool.open_dev(self.root, V("0.4.0"), "0.4.0")
        with self.assertRaises(tool.PrepareError):
            tool.open_dev(self.root, V("0.4.0"), "0.5.0-rc.1")

    def test_a_release_then_dev_then_the_next_release(self) -> None:
        tool.prepare(self.root, "minor", None, "", "2026-11-02")
        tool.open_dev(self.root, V("0.5.0"), None)
        self.set_changelog("## [Unreleased]\n\n- More.\n\n" + self.text(tool.CHANGELOG).split("## [Unreleased]\n", 1)[1])
        self.assertEqual(str(tool.prepare(self.root, "minor", None, "", "2026-12-01")), "0.6.0")
        self.assertEqual(tool.check(self.root, V("0.6.0")), [])


class CheckAndNotesTests(Tree):
    def test_check_names_each_disagreement(self) -> None:
        tool.prepare(self.root, "minor", None, "", "2026-11-02")
        p = self.root / tool.DART
        p.write_text(p.read_text(encoding="utf-8").replace("0.5.0", "0.4.0"), encoding="utf-8")
        bad = tool.check(self.root, V("0.5.0"))
        self.assertEqual(len(bad), 1)
        self.assertIn(tool.DART, bad[0])
        self.assertTrue(tool.check(self.root, V("0.6.0")))

    def test_notes_are_the_section_alone(self) -> None:
        tool.prepare(self.root, "minor", None, "", "2026-11-02")
        self.assertEqual(tool.notes(self.root, V("0.5.0")), "### Added\n- A thing.\n")
        with self.assertRaises(tool.PrepareError):
            tool.notes(self.root, V("0.9.0"))

    def test_notes_are_cut_at_a_line_under_the_cap(self) -> None:
        self.set_changelog("## [Unreleased]\n\n" + "".join(f"- line {i}\n" for i in range(5000)) + "\n## [0.4.0] - 2026-10-28\n\nOld.\n")
        tool.prepare(self.root, "minor", None, "", "2026-11-02")
        out = tool.notes(self.root, V("0.5.0"), limit=1000)
        self.assertLessEqual(len(out), 1000)
        self.assertIn("rest of the list is in CHANGELOG.md", out)
        self.assertTrue(out.startswith("- line 0\n"))
        self.assertNotIn("- line 4999", out)


class CommandLineTests(Tree):
    def test_main(self) -> None:
        run = lambda *a: tool.main(["--root", str(self.root), *a])  # noqa: E731
        self.assertEqual(run("prepare", "--bump", "patch", "--date", "2026-11-02"), 0)
        self.assertEqual(run("check", "--version", "0.4.1"), 0)
        self.assertEqual(run("check", "--version", "0.4.2"), 1)
        self.assertEqual(run("prepare", "--bump", "patch"), 1)  # nothing unreleased any more
        out = self.root / "notes.md"
        self.assertEqual(run("notes", "--version", "0.4.1", "--out", str(out)), 0)
        self.assertIn("A thing.", out.read_text(encoding="utf-8"))
        self.assertEqual(run("open-dev", "--released", "0.4.1"), 0)
        self.assertEqual(str(tool.core_version(self.root)), "0.5.0-dev")


if __name__ == "__main__":
    unittest.main()
