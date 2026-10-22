# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The mode editor's files and how the simulator serves them (phase 5 plan phase A).

No browser here (the browser tests are in simulator/editor_tests/, run by
tools/docker_editor.py): the web server's routes and headers for /editor/,
the vendored Blockly against its checksums, the two languages' keys, and the
example projects. These run in tools/check.sh with the rest of the
simulator's tests.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import threading
import unittest
from pathlib import Path

from atalaia_sim.web import EDITOR, make_server

VENDOR = EDITOR / "vendor" / "blockly"


class _Clock:
    """The web server ticks its game; the editor's routes need none."""

    def tick(self, now=None):
        pass


class EditorFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(_Clock(), "127.0.0.1", 0)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def get(self, path, host="localhost"):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        conn.request("GET", path, headers={"Host": host})
        response = conn.getresponse()
        body = response.read()
        conn.close()
        return response, body

    def test_the_editor_is_served_with_its_own_policy(self):
        response, body = self.get("/editor/")
        self.assertEqual(response.status, 200)
        self.assertEqual(body, (EDITOR / "index.html").read_bytes())
        self.assertEqual(response.getheader("Content-Type"), "text/html; charset=utf-8")
        csp = response.getheader("Content-Security-Policy")
        self.assertIn("default-src 'self'", csp)
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)
        self.assertNotIn("script-src", csp)  # scripts only from the page's own origin
        self.assertIn("frame-ancestors 'none'", csp)
        self.assertEqual(response.getheader("X-Content-Type-Options"), "nosniff")
        # The simulator's own page keeps its stricter policy.
        response, _ = self.get("/")
        self.assertNotIn("unsafe-inline", response.getheader("Content-Security-Policy"))

    def test_routes(self):
        response, _ = self.get("/editor")
        self.assertEqual((response.status, response.getheader("Location")), (301, "/editor/"))
        for path, kind in (("/editor/editor.js", "text/javascript; charset=utf-8"),
                           ("/editor/package.js", "text/javascript; charset=utf-8"),
                           ("/editor/i18n/pt.json", "application/json"),
                           ("/editor/vendor/blockly/media/sprites.svg", "image/svg+xml"),
                           ("/editor/vendor/blockly/msg/pt.js", "text/javascript; charset=utf-8"),
                           ("/editor/vendor/blockly/msg/de.js", "text/javascript; charset=utf-8"),
                           ("/editor/i18n/de.json", "application/json"),
                           ("/editor/examples/holdall.json", "application/json")):
            response, _ = self.get(path)
            self.assertEqual((response.status, response.getheader("Content-Type")), (200, kind), path)
        for path in ("/editor/../web.py", "/editor/%2e%2e/web.py", "/editor/vendor/blockly/README.md",
                     "/editor/.draft.js", "/editor/missing.js", "/editor//editor.js", "/editor/i18n"):
            response, _ = self.get(path)
            self.assertEqual(response.status, 404, path)
        response, _ = self.get("/editor/", host="evil.example")
        self.assertEqual(response.status, 403)

    def test_every_file_the_page_names_exists(self):
        html = (EDITOR / "index.html").read_text(encoding="utf-8")
        names = re.findall(r'(?:src|href)="([^"]+)"', html)
        self.assertIn("vendor/blockly/blockly_compressed.js", names)
        for name in names:
            if name == "/":
                continue
            self.assertTrue((EDITOR / name).is_file(), name)
        self.assertNotRegex(html, r"<script>|<style>|\son[a-z]+=", "no inline scripts, styles or handlers")
        self.assertNotRegex(html, r"https?://", "nothing from the network")
        for name in ("editor.js", "blocks.js", "generator.js", "package.js"):
            self.assertNotRegex((EDITOR / name).read_text(encoding="utf-8"), r"https?://", name)

    def test_vendored_blockly_is_unmodified(self):
        readme = (VENDOR / "README.md").read_text(encoding="utf-8")
        listed = dict(re.findall(r"^\| `([^`]+)` \| [^|]+ \| `([0-9a-f]{64})` \|$", readme, re.M))
        present = {p.relative_to(VENDOR).as_posix() for p in VENDOR.rglob("*") if p.is_file()} - {"README.md"}
        self.assertEqual(set(listed), present)
        for name, digest in listed.items():
            self.assertEqual(hashlib.sha256((VENDOR / name).read_bytes()).hexdigest(), digest, name)
        self.assertIn("blockly 13.3.0", readme)

    def test_languages_have_the_same_keys(self):
        en = json.loads((EDITOR / "i18n" / "en.json").read_text(encoding="utf-8"))
        pt = json.loads((EDITOR / "i18n" / "pt.json").read_text(encoding="utf-8"))
        for part in ("ui", "blocks"):
            self.assertEqual(set(en[part]), set(pt[part]), part)
            for key, text in en[part].items():
                # The same %1, %2 ... and {name} in both languages.
                self.assertEqual(sorted(re.findall(r"%\d|\{\w+\}", text)),
                                 sorted(re.findall(r"%\d|\{\w+\}", pt[part][key])), key)
        # German (plan phase 10, P5H-2): may lack a key (English shows), never have one English
        # lacks or other placeholders; the page offers every language it has a table for.
        de = json.loads((EDITOR / "i18n" / "de.json").read_text(encoding="utf-8"))
        for part in ("ui", "blocks"):
            self.assertEqual(set(de[part]) - set(en[part]), set(), part)
            for key, text in de[part].items():
                self.assertTrue(text.strip(), key)
                self.assertEqual(sorted(re.findall(r"%\d|\{\w+\}", text)),
                                 sorted(re.findall(r"%\d|\{\w+\}", en[part][key])), key)
        html = (EDITOR / "index.html").read_text(encoding="utf-8")
        offered = re.findall(r'<option value="([a-z]{2})">', html)
        self.assertEqual(sorted(offered), sorted(p.stem for p in (EDITOR / "i18n").glob("*.json")))
        for lang in offered:
            if lang != "en":
                self.assertTrue((VENDOR / "msg" / f"{lang}.js").is_file(), lang)
        for key in re.findall(r'data-i18n="([a-z_]+)"', html):
            self.assertIn(key, en["ui"], key)
        code = "".join((EDITOR / n).read_text(encoding="utf-8") for n in ("blocks.js", "generator.js", "editor.js"))
        for key in re.findall(r"\bt\('([a-z_]+)'\)|'(problem_[a-z_]+)'|\['(ev_[a-z_]+|key_[a-z_]+|type_[a-z]+)'", code):
            key = next(k for k in key if k)
            self.assertIn(key, en["blocks"], key)
        for key in re.findall(r"\bui\('([a-z_]+)'\)", code):
            self.assertIn(key, en["ui"], key)

    def test_examples_are_editor_projects(self):
        for name in ("domination", "holdall", "master_satellites"):
            project = json.loads((EDITOR / "examples" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertEqual((project["format"], project["version"]), ("atalaia-mode-editor", 1))
            self.assertEqual(project["mode"]["id"], f"org.atalaia.{name}")
            self.assertTrue(project["node"]["blocks"]["blocks"])
        for name in ("holdall", "master_satellites"):
            project = json.loads((EDITOR / "examples" / f"{name}.json").read_text(encoding="utf-8"))
            self.assertTrue(project["field"]["blocks"]["blocks"])
        # The example's screens are the mode's files (the browser round trip checks them byte for byte).
        project = json.loads((EDITOR / "examples" / "master_satellites.json").read_text(encoding="utf-8"))
        screens = EDITOR.parents[2] / "modes" / "master_satellites" / "assets" / "screens"
        self.assertEqual(project["screens"], {p.stem: p.read_text(encoding="utf-8") for p in sorted(screens.glob("*.yaml"))})
        self.assertEqual([r["name"] for r in project["mode"]["roles"]], ["master", "satellite"])


if __name__ == "__main__":
    unittest.main()
