# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""tools/prepare_release.py finishes release-please's release pull request and opens the next dev version
(decisions PREP-3 to PREP-5, RP-1 to RP-12)."""

from __future__ import annotations

import importlib.util
import json
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
MARKED = [tool.PUBSPEC, tool.DART, tool.CONTROLLER, tool.SERVER]  # release-please-config.json extra-files
SEMVER = re.compile(r"\d+\.\d+\.\d+(-[\w.]+)?(\+[-\w.]+)?")  # release-please's generic updater's


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
        self.release_please_ran = False

    def set_changelog(self, text: str) -> None:
        (self.root / tool.CHANGELOG).write_text("# Changelog\n\n" + text, encoding="utf-8")

    def text(self, name: str) -> str:
        return (self.root / name).read_text(encoding="utf-8")

    def release_please(self, version: str, entry: str = "### Features\n\n* **core:** a feature ([#7](u)) ([abc1234](u))\n") -> None:
        """What release-please does to the branch of its release pull request: the manifest, a marked
        line's first version, and its CHANGELOG entry before the first "## [" heading (its
        DEFAULT_VERSION_HEADER_REGEX, which the Unreleased heading matches too)."""
        (self.root / tool.MANIFEST).write_text(f'{{\n  ".": "{version}"\n}}\n', encoding="utf-8")
        for name in MARKED:
            lines = self.text(name).split("\n")
            lines = [SEMVER.sub(version, line, count=1) if "x-release-please-version" in line else line for line in lines]
            (self.root / name).write_text("\n".join(lines), encoding="utf-8")
        log = self.text(tool.CHANGELOG)
        i = re.search(r"\n###? v?[0-9[]", log).start()
        new = f"## [{version}](https://github.com/o/r/compare/v0.4.0...v{version}) (2026-11-02)\n\n\n{entry}"
        (self.root / tool.CHANGELOG).write_text((log[:i] + "\n" + new + "\n" + log[i:]).strip() + "\n", encoding="utf-8")


class VersionTests(unittest.TestCase):
    def test_parse_and_order(self) -> None:
        self.assertEqual(str(V("0.5.0-rc.1")), "0.5.0-rc.1")
        for bad in ("0.5", "v0.5.0", "1.2.3.4", "0.5.0-", "0.5.0-a" + "b" * 25):
            with self.assertRaises(tool.PrepareError, msg=bad):
                V(bad)
        order = [V(t).order() for t in ("0.4.0", "0.5.0-rc.1", "0.5.0-rc.2", "0.5.0-rc.10", "0.5.0", "0.5.1", "1.0.0")]
        self.assertEqual(order, sorted(order))
        self.assertLess(V("0.5.0-9").order(), V("0.5.0-alpha").order())  # numbers below words

    def test_the_markers_are_on_the_version_lines(self) -> None:
        """release-please bumps exactly these lines (release-please-config.json extra-files)."""
        for name in MARKED:
            marked = [line for line in (REPO / name).read_text(encoding="utf-8").splitlines() if "x-release-please-version" in line]
            self.assertEqual(len(marked), 1, name)
            self.assertRegex(marked[0], r"^(version:|const appVersion|__version__)", name)
        config = json.loads((REPO / "release-please-config.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(config["packages"]["."]["extra-files"]), sorted(MARKED))
        self.assertEqual(json.loads((REPO / tool.MANIFEST).read_text(encoding="utf-8")).keys(), {"."})


class ReleasePullRequestTests(Tree):
    def test_the_real_tree_is_a_release_of_its_own_version(self) -> None:
        """The checkout's files agree with each other, as test_versions.py needs."""
        v = tool.core_version(REPO)
        self.assertEqual(tool.check(REPO, v) if not v.pre else [], [])
        released = tool.manifest_version(REPO)  # the manifest names the newest release
        self.assertLessEqual(released.order(), v.order())

    def dev(self, version: str) -> None:
        files: dict[str, str] = {}
        tool._set_core(self.root, V(version), "dev", files)
        tool._write_all(self.root, files)

    def test_release_please_then_release_pr_is_a_release(self) -> None:
        self.dev("0.5.0")
        self.release_please("0.5.0")
        self.assertTrue(tool.check(self.root, V("0.5.0")))  # the core still says 0.5.0-dev
        self.assertEqual(str(tool.release_pr(self.root)), "0.5.0")
        self.assertEqual(tool.check(self.root, V("0.5.0")), [])
        h = self.text(tool.VERSION_H)
        self.assertIn("#define ATALAIA_VERSION_MINOR      5", h)
        self.assertIn('#define ATALAIA_VERSION_PRERELEASE ""', h)
        self.assertIn("project(atalaia_core VERSION 0.5.0 ", self.text(tool.CMAKE))
        self.assertRegex(self.text(tool.PUBSPEC), r"\nversion: 0\.5\.0 # x-release-please-version")
        self.assertIn("const appVersion = '0.5.0';", self.text(tool.DART))
        self.assertIn('__version__ = "0.5.0"', self.text(tool.CONTROLLER))
        self.assertIn('__version__ = "0.5.0"', self.text(tool.SERVER))

    def test_the_hand_written_notes_become_the_sections_details(self) -> None:
        self.release_please("0.5.0")
        tool.release_pr(self.root)
        log = self.text(tool.CHANGELOG)
        self.assertIn("# Changelog\n\n## [Unreleased]\n\n## [0.5.0](https://github.com/o/r/compare/v0.4.0...v0.5.0) (2026-11-02)\n\n"
                      "### Features\n\n* **core:** a feature ([#7](u)) ([abc1234](u))\n\n"
                      "### Details\n\n#### Added\n- A thing.\n\n## [0.4.0] - 2026-10-28\n\nOld.\n\n### Added\n- Old thing.\n", log)
        self.assertEqual(log.count("## [Unreleased]"), 1)
        before = {n: self.text(n) for n in FILES}
        tool.release_pr(self.root)  # every push to main runs it again on the regenerated branch
        self.assertEqual(before, {n: self.text(n) for n in FILES})

    def test_the_next_release_lands_above_the_empty_unreleased_and_folds_again(self) -> None:
        self.release_please("0.5.0")
        tool.release_pr(self.root)
        tool.open_dev(self.root, V("0.5.0"), None)
        log = self.text(tool.CHANGELOG)
        (self.root / tool.CHANGELOG).write_text(log.replace("## [Unreleased]\n", "## [Unreleased]\n\n- More.\n", 1), encoding="utf-8")
        self.release_please("0.6.0", "### Bug Fixes\n\n* a fix\n")
        self.assertEqual(str(tool.release_pr(self.root)), "0.6.0")
        log = self.text(tool.CHANGELOG)
        self.assertIn("## [Unreleased]\n\n## [0.6.0]", log)
        self.assertIn("* a fix\n\n### Details\n\n- More.\n\n## [0.5.0](", log)
        self.assertEqual(log.count("- More."), 1)

    def test_no_hand_written_notes_no_details(self) -> None:
        self.set_changelog("## [Unreleased]\n\n## [0.4.0] - 2026-10-28\n\nOld.\n")
        self.release_please("0.4.1", "### Bug Fixes\n\n* a fix\n")
        tool.release_pr(self.root)
        self.assertIn("## [Unreleased]\n\n## [0.4.1](https://github.com/o/r/compare/v0.4.0...v0.4.1) (2026-11-02)\n\n"
                      "### Bug Fixes\n\n* a fix\n\n## [0.4.0]", self.text(tool.CHANGELOG))
        self.assertNotIn("### Details", self.text(tool.CHANGELOG))

    def test_a_pre_release_goes_into_every_file(self) -> None:
        self.release_please("0.5.0-rc.1")
        tool.release_pr(self.root)
        self.assertEqual(tool.check(self.root, V("0.5.0-rc.1")), [])
        self.assertIn('PRERELEASE "rc.1"', self.text(tool.VERSION_H))
        self.assertIn("VERSION 0.5.0 ", self.text(tool.CMAKE))  # CMake keeps no pre-release
        self.assertIn("version: 0.5.0-rc.1", self.text(tool.PUBSPEC))

    def test_a_pubspec_build_number_survives(self) -> None:
        p = self.root / tool.PUBSPEC
        self.release_please("0.4.1")  # its marker writes the whole version: a build number goes
        p.write_text(self.text(tool.PUBSPEC).replace("version: 0.4.1", "version: 0.4.0+7"), encoding="utf-8")
        tool.release_pr(self.root)
        self.assertIn("\nversion: 0.4.1+7 ", self.text(tool.PUBSPEC))

    def test_without_release_pleases_section_nothing_is_written(self) -> None:
        (self.root / tool.MANIFEST).write_text('{".": "0.5.0"}\n', encoding="utf-8")
        before = {n: self.text(n) for n in FILES}
        with self.assertRaisesRegex(tool.PrepareError, r"no section \[0\.5\.0\]"):
            tool.release_pr(self.root)
        self.assertEqual(before, {n: self.text(n) for n in FILES})

    def test_a_file_that_changed_shape_stops_before_any_write(self) -> None:
        self.release_please("0.5.0")
        (self.root / tool.SERVER).write_text("version = 1\n", encoding="utf-8")
        before = {n: self.text(n) for n in FILES}
        with self.assertRaisesRegex(tool.PrepareError, "expected one match"):
            tool.release_pr(self.root)
        self.assertEqual(before, {n: self.text(n) for n in FILES})

    def test_a_bad_manifest_is_refused(self) -> None:
        for text in ("{}", '{".": "0.5"}', "not json"):
            (self.root / tool.MANIFEST).write_text(text, encoding="utf-8")
            with self.assertRaisesRegex(tool.PrepareError, "release-please-manifest", msg=text):
                tool.release_pr(self.root)


class OpenDevTests(Tree):
    def test_opens_the_next_minor_with_dev_in_the_core_only(self) -> None:
        before = {n: self.text(n) for n in (tool.PUBSPEC, tool.DART, tool.CONTROLLER, tool.SERVER, tool.CHANGELOG)}
        self.assertEqual(str(tool.open_dev(self.root, V("0.4.0"), None)), "0.5.0-dev")
        self.assertEqual(str(tool.core_version(self.root)), "0.5.0-dev")
        self.assertIn("VERSION 0.5.0 ", self.text(tool.CMAKE))
        self.assertEqual(before, {n: self.text(n) for n in before})

    def test_explicit_next_and_after_a_pre_release(self) -> None:
        self.assertEqual(str(tool.open_dev(self.root, V("0.4.0"), "1.0.0")), "1.0.0-dev")
        self.release_please("1.0.0-rc.1")
        tool.release_pr(self.root)
        self.assertEqual(str(tool.open_dev(self.root, V("1.0.0-rc.1"), None)), "1.0.0-dev")

    def test_refuses_what_is_not_the_release(self) -> None:
        with self.assertRaisesRegex(tool.PrepareError, "not the released"):
            tool.open_dev(self.root, V("0.3.0"), None)
        with self.assertRaises(tool.PrepareError):
            tool.open_dev(self.root, V("0.4.0"), "0.4.0")
        with self.assertRaises(tool.PrepareError):
            tool.open_dev(self.root, V("0.4.0"), "0.5.0-rc.1")


class CheckTests(Tree):
    def test_check_names_each_disagreement(self) -> None:
        self.release_please("0.5.0")
        tool.release_pr(self.root)
        p = self.root / tool.DART
        p.write_text(p.read_text(encoding="utf-8").replace("0.5.0", "0.4.0"), encoding="utf-8")
        bad = tool.check(self.root, V("0.5.0"))
        self.assertEqual(len(bad), 1)
        self.assertIn(tool.DART, bad[0])
        self.assertTrue(tool.check(self.root, V("0.6.0")))


class CommandLineTests(Tree):
    def test_main(self) -> None:
        run = lambda *a: tool.main(["--root", str(self.root), *a])  # noqa: E731
        self.assertEqual(run("release-pr"), 1)  # no manifest yet
        self.release_please("0.4.1")
        self.assertEqual(run("release-pr"), 0)
        self.assertEqual(run("release-pr", "--version", "0.4.1"), 0)
        self.assertEqual(run("check", "--version", "0.4.1"), 0)
        self.assertEqual(run("check", "--version", "0.4.2"), 1)
        self.assertEqual(run("open-dev", "--released", "0.4.1"), 0)
        self.assertEqual(str(tool.core_version(self.root)), "0.5.0-dev")


if __name__ == "__main__":
    unittest.main()
