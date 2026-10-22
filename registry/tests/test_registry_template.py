# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The registry repository's template and its CI (phase 5 plan phase 8, decisions P5G-1 onwards).

A registry is made from registry/template/ in a temporary folder, with the
sample submission registry/examples/org.example.hill/ and throwaway keys made
here (an author's and the project's): listed, then given the verified badge,
with tools/registry_check.py as an author and a maintainer would. Then every
step of the template's workflow whose id starts with "check-" runs as written
(with $ATALAIA pointing at this repository), as the registry's CI would: the
JSON Schemas, lint, REUSE, each mode's tests in the simulator and the
published site. Then lint must refuse what the process forbids: tampered
archives, a source that is not the package, a badge without the project's key,
revoked keys, the review checklist's automated items, reserved ids, two owners
of one id, and a published version changed.

check-jsonschema and reuse are not in the dev container: their steps are
skipped without them unless ATALAIA_REQUIRE_REGISTRY_TOOLS=1 (CI's
registry-template job); the simulator's step needs the shared core
(ATALAIA_CORE_LIB; with ATALAIA_REQUIRE_ALL=1 it must be there).

    python3 -m unittest discover -s registry/tests -v
"""

from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "registry" / "template"
SAMPLE = REPO / "registry" / "examples" / "org.example.hill"
WORKFLOW = TEMPLATE / ".github" / "workflows" / "registry.yml"
SAMPLE_ID = "org.example.hill"

_spec = importlib.util.spec_from_file_location("registry_check", REPO / "tools" / "registry_check.py")
rc = importlib.util.module_from_spec(_spec)
sys.modules["registry_check"] = rc  # dataclasses look their module up
_spec.loader.exec_module(rc)  # type: ignore[union-attr]

REQUIRE_TOOLS = os.environ.get("ATALAIA_REQUIRE_REGISTRY_TOOLS") == "1"
REQUIRE_ALL = os.environ.get("ATALAIA_REQUIRE_ALL") == "1"


def core_lib() -> str:
    lib = os.environ.get("ATALAIA_CORE_LIB", "")
    if lib and Path(lib).is_file():
        return lib
    if REQUIRE_ALL:
        raise AssertionError("ATALAIA_REQUIRE_ALL=1 but ATALAIA_CORE_LIB is not the built shared core")
    return ""


def quiet(argv: list[str]) -> int:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = rc.main([str(a) for a in argv])
    if code:
        print(out.getvalue(), err.getvalue(), file=sys.stderr)
    return code


def new_key(folder: Path, name: str) -> tuple[Path, str]:
    """A throwaway Ed25519 key (unencrypted PEM outside the repository) and its public base64."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    path = folder / f"{name}.pem"
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return path, base64.b64encode(public).decode("ascii")


def set_version(folder: Path, version: str) -> None:
    path = folder / "mode.yaml"
    text = path.read_text(encoding="utf-8")
    old = yaml.safe_load(text)["version"]
    path.write_text(text.replace(f"version: {old}\n", f"version: {version}\n"), encoding="utf-8")


def copy_licences(root: Path, names: list[str]) -> None:
    (root / "LICENSES").mkdir(exist_ok=True)
    for name in names:
        shutil.copyfile(REPO / "LICENSES" / f"{name}.txt", root / "LICENSES" / f"{name}.txt")


class Workspace:
    """A temporary GitHub Actions workspace: registry/ (the registry), base/ (its base branch),
    keys outside both, and a `python` on the PATH as setup-python gives."""

    def __init__(self, test: unittest.TestCase):
        self.dir = Path(tempfile.mkdtemp(prefix="atalaia-registry-"))
        test.addCleanup(shutil.rmtree, self.dir, True)
        self.root = self.dir / "registry"
        shutil.copytree(TEMPLATE, self.root)
        self.keys = self.dir / "private"
        self.keys.mkdir()
        self.author_pem, self.author = new_key(self.keys, "author")
        self.project_pem, self.project = new_key(self.keys, "project")
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        (self.bin / "python").symlink_to(sys.executable)

    def submit(self, source: Path = SAMPLE, mode_id: str = SAMPLE_ID, owner: str = "example-club") -> None:
        shutil.copytree(source, self.root / "modes" / mode_id, dirs_exist_ok=True)
        if not (self.root / "keys" / "authors" / f"{rc.fr.key_id(self.author)}.json").exists():
            assert quiet(["key", self.root, "--public", self.author, "--owner", owner, "--name", "Example Club",
                          "--added", "2026-10-22"]) == 0
        assert quiet(["add", self.root, mode_id, "--key", self.author_pem, "--name", "King of the Hill",
                      "--description", "Hold the box to take the hill.", "--author", "Example Club"]) == 0

    def project_key(self) -> None:
        assert quiet(["key", self.root, "--public", self.project, "--owner", "vakaobr", "--project"]) == 0

    def badge(self, version: str = "1.0.0", key: Path | None = None) -> int:
        return quiet(["badge", self.root, SAMPLE_ID, version, "--key", key or self.project_pem])

    def errors(self, base: Path | None = None) -> list[str]:
        return rc.lint(self.root, base).errors

    def index(self) -> dict:
        return json.loads((self.root / "index.json").read_text(encoding="utf-8"))

    def run_step(self, test: unittest.TestCase, job: str, step: dict) -> None:
        command = step["run"]
        needs = {"check-jsonschema": "check-jsonschema", "reuse lint": "reuse"}
        for marker, program in needs.items():
            if marker in command and shutil.which(program) is None:
                if REQUIRE_TOOLS:
                    test.fail(f"ATALAIA_REQUIRE_REGISTRY_TOOLS=1 but {program} is missing ({job}/{step['id']})")
                print(f"\n  skipped {job}/{step['id']}: no {program}", file=sys.stderr)
                return
        env = dict(os.environ)
        if "$ATALAIA_CORE_LIB" in command:
            lib = core_lib()
            if not lib:
                print(f"\n  skipped {job}/{step['id']}: no shared core", file=sys.stderr)
                return
            env["ATALAIA_CORE_LIB"] = lib
        env.update({"ATALAIA": str(REPO), "GITHUB_WORKSPACE": str(self.dir),
                    "PATH": f"{self.bin}{os.pathsep}{env.get('PATH', '')}"})
        env.pop("GITHUB_ACTIONS", None)
        cwd = self.dir / step.get("working-directory", ".")
        result = subprocess.run(["sh", "-ec", command], cwd=cwd, env=env, capture_output=True, text=True,
                                check=False)
        test.assertEqual(result.returncode, 0, f"{job}/{step['id']} failed:\n{result.stdout}\n{result.stderr}")


def check_steps() -> list[tuple[str, dict]]:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return [(name, step) for name, job in workflow["jobs"].items() for step in job["steps"]
            if str(step.get("id", "")).startswith("check-")]


class WorkflowTests(unittest.TestCase):
    def test_the_workflow_has_the_three_jobs_and_publishes_after_them(self):
        workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True))  # YAML 1.1 reads `on` as true
        self.assertIn("pull_request", triggers)
        self.assertNotIn("pull_request_target", triggers)  # no secrets for submitted code
        self.assertEqual(workflow["permissions"], {"contents": "read"})
        self.assertIn("ATALAIA_REF", workflow["env"])
        jobs = workflow["jobs"]
        self.assertEqual(set(jobs), {"registry-lint", "registry-test", "sandbox-escape", "publish"})
        self.assertEqual(set(jobs["publish"]["needs"]), {"registry-lint", "registry-test", "sandbox-escape"})
        self.assertIn("refs/heads/main", jobs["publish"]["if"])
        ids = {(job, step["id"]) for job, step in check_steps()}
        self.assertTrue({("registry-lint", "check-schemas"), ("registry-lint", "check-registry"),
                         ("registry-lint", "check-licensing"), ("registry-test", "check-mode-tests"),
                         ("publish", "check-site")} <= ids)
        for job in jobs.values():
            for step in job["steps"]:
                if str(step.get("uses", "")).startswith("actions/checkout"):
                    self.assertIs(step["with"]["persist-credentials"], False)

    def test_the_sandbox_battery_is_this_repositorys(self):
        """The registry runs the same battery as this repository's CI job of that name."""
        template = "\n".join(s.get("run", "") for s in yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
                             ["jobs"]["sandbox-escape"]["steps"])
        ours = "\n".join(s.get("run", "") for s in yaml.safe_load(
            (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))["jobs"]["sandbox-escape"]["steps"])
        for command in ("cmake --build build-asan --target test_sandbox_escape",
                        "ctest --test-dir build-asan -R sandbox_escape --output-on-failure",
                        "-fsanitize=address,undefined -fno-omit-frame-pointer -fno-sanitize-recover=all",
                        "python -m unittest tests.test_sandbox_escape -v"):
            self.assertIn(command, template)
            self.assertIn(command, ours)


class TemplateTests(unittest.TestCase):
    def test_the_empty_template_passes_every_check(self):
        self.assertEqual(rc.lint(TEMPLATE).errors, [])
        ws = Workspace(self)
        copy_licences(ws.root, ["CC0-1.0", "CC-BY-SA-4.0", "GPL-3.0-or-later"])
        for job, step in check_steps():
            with self.subTest(step=step["id"]):
                ws.run_step(self, job, step)
        self.assertEqual(json.loads((ws.dir / "_site" / "index.json").read_text())["modes"], [])

    def test_a_sample_submission_listed_then_verified_passes_the_workflow(self):
        ws = Workspace(self)
        shutil.copytree(TEMPLATE, ws.dir / "base")  # the base branch: the empty registry
        ws.submit()
        entry = ws.index()["modes"][0]
        self.assertEqual((entry["id"], entry["name"], entry["author"]), (SAMPLE_ID, "King of the Hill", "Example Club"))
        listed = entry["versions"][0]
        self.assertEqual((listed["url"], listed["verified"], listed["license"], listed["key_id"]),
                         ("packages/org.example.hill-1.0.0.tar", False, "MIT", rc.fr.key_id(ws.author)))
        self.assertEqual(ws.errors(ws.dir / "base"), [])

        ws.project_key()
        self.assertEqual(ws.badge(), 0)
        verified = ws.index()["modes"][0]["versions"][0]
        self.assertEqual((verified["verified"], verified["key_id"]), (True, rc.fr.key_id(ws.project)))
        self.assertTrue((ws.root / "packages" / "org.example.hill-1.0.0.tar.verified.json").is_file())
        self.assertEqual(ws.errors(ws.dir / "base"), [])

        copy_licences(ws.root, ["CC0-1.0", "CC-BY-SA-4.0", "GPL-3.0-or-later", "MIT"])
        for job, step in check_steps():
            with self.subTest(step=step["id"]):
                ws.run_step(self, job, step)

        site = ws.dir / "_site"
        self.assertEqual(json.loads((site / "index.json").read_text()), ws.index())
        self.assertEqual(json.loads((site / "revoked.json").read_text()), {"schema_version": 1, "keys": []})
        keys = json.loads((site / "keys.json").read_text())
        self.assertEqual([k["public_key"] for k in keys["project"]], [ws.project])
        self.assertEqual([k["public_key"] for k in keys["authors"]], [ws.author])
        self.assertIn("verified 1.0.0", (site / "badges" / f"{SAMPLE_ID}.svg").read_text())
        # A field controller that trusts only the project's key takes the published package.
        archive = site / "packages" / "org.example.hill-1.0.0.tar"
        for release, key in ((".verified.json", ws.project), (".release.json", ws.author)):
            out = subprocess.run([sys.executable, str(REPO / "tools" / "mode_package.py"), "verify", str(archive),
                                  str(archive) + release, "--keys", key, "--revoked", str(site / "revoked.json")],
                                 capture_output=True, text=True, check=False)
            self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        # Taking the badge away lists the author's signature again.
        self.assertEqual(quiet(["badge", ws.root, SAMPLE_ID, "1.0.0", "--remove"]), 0)
        self.assertEqual(ws.index()["modes"][0]["versions"][0]["key_id"], rc.fr.key_id(ws.author))
        self.assertEqual(ws.errors(), [])
        self.assertEqual(quiet(["site", ws.root, site]), 0)
        self.assertIn("not reviewed 1.0.0", (site / "badges" / f"{SAMPLE_ID}.svg").read_text())

    def test_the_mode_tests_run_and_a_failing_one_fails(self):
        lib = core_lib()
        if not lib:
            self.skipTest("no shared core (ATALAIA_CORE_LIB)")
        ws = Workspace(self)
        ws.submit()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(subprocess.run([sys.executable, str(REPO / "tools" / "registry_check.py"), "test",
                                             str(ws.root), "--lib", lib], capture_output=True,
                                            check=False).returncode, 0)
            test = ws.root / "modes" / SAMPLE_ID / "tests" / "take_and_score.yaml"
            test.write_text(test.read_text().replace("points: 3", "points: 4"))
            self.assertNotEqual(subprocess.run([sys.executable, str(REPO / "tools" / "registry_check.py"), "test",
                                                str(ws.root), "--lib", lib], capture_output=True,
                                               check=False).returncode, 0)


class RefusalTests(unittest.TestCase):
    def listed(self) -> Workspace:
        ws = Workspace(self)
        ws.submit()
        ws.project_key()
        self.assertEqual(ws.errors(), [])
        return ws

    def assertRefused(self, ws: Workspace, text: str, base: Path | None = None) -> None:
        errors = ws.errors(base)
        self.assertTrue(any(text in e for e in errors), f"no error with {text!r} in {errors}")

    def new_version(self, ws: Workspace, version: str, edit) -> None:
        folder = ws.root / "modes" / SAMPLE_ID
        edit(folder)
        set_version(folder, version)
        self.assertEqual(quiet(["add", ws.root, SAMPLE_ID, "--key", ws.author_pem]), 0)

    def test_a_tampered_archive(self):
        ws = self.listed()
        archive = ws.root / "packages" / "org.example.hill-1.0.0.tar"
        data = bytearray(archive.read_bytes())
        data[data.index(b"score.add")] ^= 0x20
        archive.write_bytes(bytes(data))
        self.assertRefused(ws, "the author's signature: bad_hash: the archive is not the one signed")

    def test_a_source_that_is_not_the_package(self):
        ws = self.listed()
        node = ws.root / "modes" / SAMPLE_ID / "node.lua"
        node.write_text(node.read_text() + "-- changed after signing\n")
        self.assertRefused(ws, "does not pack to packages/org.example.hill-1.0.0.tar")

    def test_verified_without_the_projects_signature(self):
        ws = self.listed()
        index = ws.index()
        index["modes"][0]["versions"][0]["verified"] = True
        (ws.root / "index.json").write_text(json.dumps(index))
        self.assertRefused(ws, "verified needs packages/org.example.hill-1.0.0.tar.verified.json")
        # The badge with an author's key is refused by the tool, and by lint if made by hand.
        self.assertNotEqual(ws.badge(key=ws.author_pem), 0)
        self.assertFalse((ws.root / "packages" / "org.example.hill-1.0.0.tar.verified.json").exists())
        shutil.copyfile(ws.root / "packages" / "org.example.hill-1.0.0.tar.release.json",
                        ws.root / "packages" / "org.example.hill-1.0.0.tar.verified.json")
        self.assertRefused(ws, "the project's signature")

    def test_a_badge_left_behind_and_an_index_signature_that_is_not_the_authors(self):
        ws = self.listed()
        self.assertEqual(ws.badge(), 0)
        index = ws.index()
        index["modes"][0]["versions"][0]["verified"] = False
        (ws.root / "index.json").write_text(json.dumps(index))
        self.assertRefused(ws, "not verified, but packages/org.example.hill-1.0.0.tar.verified.json is there")
        self.assertRefused(ws, "lists the author's signature and key id")

    def test_revoked_keys(self):
        ws = self.listed()
        self.assertEqual(ws.badge(), 0)
        revoked = {"schema_version": 1, "keys": [{"key_id": rc.fr.key_id(ws.project), "reason": "test",
                                                  "date": "2026-10-22"}]}
        (ws.root / "keys" / "revoked.json").write_text(json.dumps(revoked))
        self.assertRefused(ws, "the project's signature: revoked: key")
        revoked["keys"] = [{"key_id": rc.fr.key_id(ws.author)}]
        (ws.root / "keys" / "revoked.json").write_text(json.dumps(revoked))
        self.assertRefused(ws, "the author's signature: revoked: key")

    def test_unknown_and_misnamed_keys(self):
        ws = self.listed()
        authors = ws.root / "keys" / "authors"
        key_file = next(authors.glob("*.json"))
        key_file.rename(authors / "0000000000000000.json")
        self.assertRefused(ws, "the file is keys/authors/")
        self.assertRefused(ws, "which this controller does not trust")

    def test_the_checklists_automated_items(self):
        cases = [
            ("1.0.1", lambda f: (f / "node.lua").write_text((f / "node.lua").read_text().replace(
                "local previous", 'local f = io.open("/etc/passwd")\n  local previous')), "uses 'io'"),
            ("1.0.2", lambda f: (f / "node.lua").write_text((f / "node.lua").read_text().replace(
                "-- SPDX-License-Identifier: MIT", "-- SPDX-License-Identifier: GPL-3.0-or-later")),
             "node.lua says GPL-3.0-or-later, mode.yaml says MIT"),
            ("1.0.3", lambda f: (f / "mode.yaml").write_text((f / "mode.yaml").read_text() + "  de:\n    name: X\n"),
             "i18n.de lacks description"),
            ("1.0.4", lambda f: (f / "assets" / "screens").mkdir(parents=True) or (
                f / "assets" / "screens" / "big.yaml").write_text(
                "# SPDX-FileCopyrightText: 2026 The Atalaia contributors\n# SPDX-License-Identifier: MIT\n"
                + "# padding\n" * 60000), "(checklist item 9)"),
        ]
        for version, edit, text in cases:
            with self.subTest(version=version):
                ws = self.listed()
                self.new_version(ws, version, edit)
                self.assertRefused(ws, text)
        ws = self.listed()
        shutil.rmtree(ws.root / "modes" / SAMPLE_ID / "tests")
        self.assertRefused(ws, "has no tests/*.yaml (checklist item 4)")

    def test_files_and_sources_out_of_place(self):
        ws = self.listed()
        (ws.root / "packages" / "stray.tar").write_bytes(b"x")
        self.assertRefused(ws, "not a file of any version in index.json")
        shutil.copytree(ws.root / "modes" / SAMPLE_ID, ws.root / "modes" / "org.example.other")
        self.assertRefused(ws, "modes/org.example.other: not in index.json")
        shutil.rmtree(ws.root / "modes" / SAMPLE_ID)
        self.assertRefused(ws, "missing: the source of the newest version")

    def test_a_reserved_id(self):
        ws = Workspace(self)
        source = ws.dir / "org.atalaia.hill"
        shutil.copytree(SAMPLE, source)
        (source / "mode.yaml").write_text((source / "mode.yaml").read_text().replace(SAMPLE_ID, "org.atalaia.hill"))
        ws.submit(source, "org.atalaia.hill")
        self.assertRefused(ws, "ids starting org.atalaia. are the project's built-in modes")

    def test_one_id_one_owner(self):
        ws = self.listed()
        other_pem, other = new_key(ws.keys, "other")
        self.assertEqual(quiet(["key", ws.root, "--public", other, "--owner", "someone-else"]), 0)
        set_version(ws.root / "modes" / SAMPLE_ID, "1.1.0")
        self.assertEqual(quiet(["add", ws.root, SAMPLE_ID, "--key", other_pem]), 0)
        self.assertRefused(ws, "versions signed by keys of different owners: example-club, someone-else")

    def test_a_published_version_never_changes(self):
        ws = self.listed()
        base = ws.dir / "base"
        shutil.copytree(ws.root, base)
        # The same version again with other files: add refuses ...
        node = ws.root / "modes" / SAMPLE_ID / "node.lua"
        node.write_text(node.read_text() + "-- a quiet change\n")
        self.assertNotEqual(quiet(["add", ws.root, SAMPLE_ID, "--key", ws.author_pem]), 0)
        # ... and lint against the base refuses it made by hand.
        for name in ("", ".release.json", ".license"):
            (ws.root / "packages" / f"org.example.hill-1.0.0.tar{name}").unlink()
        index = ws.index()
        index["modes"] = []
        (ws.root / "index.json").write_text(json.dumps(index))
        self.assertEqual(quiet(["add", ws.root, SAMPLE_ID, "--key", ws.author_pem]), 0)
        self.assertEqual(ws.errors(), [])
        self.assertRefused(ws, "a published version changed", base)
        # A new version is fine; a version taken down is only reported.
        shutil.rmtree(ws.root)
        shutil.copytree(base, ws.root)
        self.new_version(ws, "1.0.1", lambda f: None)
        report = rc.lint(ws.root, base)
        self.assertEqual(report.errors, [])
        index = ws.index()
        index["modes"][0]["versions"] = [v for v in index["modes"][0]["versions"] if v["version"] != "1.0.0"]
        (ws.root / "index.json").write_text(json.dumps(index))
        for name in ("", ".release.json", ".license"):
            (ws.root / "packages" / f"org.example.hill-1.0.0.tar{name}").unlink()
        report = rc.lint(ws.root, base)
        self.assertEqual(report.errors, [])
        self.assertTrue(any("removed from the index" in w for w in report.warnings), report.warnings)


class LuaScanTests(unittest.TestCase):
    def scan(self, lua: str) -> list[str]:
        return [m.group(0).strip() for m in rc.FORBIDDEN_LUA.finditer(rc.code_only(lua))]

    def test_names_in_code_only(self):
        self.assertEqual(self.scan('-- os.exit()\nlocal t = "io.open"\nlocal u = [[ debug ]]\n--[==[ require ]==]\n'
                                   "local v = e.load + e.os\nt:os()\n"), [])
        self.assertEqual(self.scan('local s = "a \\" io" .. x\nio.write(s)\n'), ["io"])
        self.assertEqual(self.scan("local f = load\nlocal g = string.dump\nlocal h = _G['x']\nx:dump()\n"),
                         ["load", "string.dump", "_G", ":dump("])

    def test_the_built_in_modes_pass(self):
        """No false alarm on the project's own modes."""
        for path in sorted((REPO / "modes").glob("*/*.lua")):
            with self.subTest(path=path.relative_to(REPO).as_posix()):
                self.assertEqual(self.scan(path.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()
