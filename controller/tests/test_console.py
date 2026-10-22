# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The GM console's files as the controller serves them (plan AC-6), without a browser.

    cd controller && python -m unittest discover -s tests

Checks the static mount and its security headers, that every file the
pages, the service worker and the manifest name exists and is served, the
icons' sizes, that both languages have the same keys, the vendored
libraries' checksums and the licence headers. The pages themselves run in
a real browser in controller/console/tests/ (python tools/docker_console.py).
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from support import FakeModem, config
from atalaia_controller.api import (CONSOLE_DIR, FIELD_MAP_HEADERS, FIELD_MAP_ORIGINS, SECURITY_HEADERS, Auth,
                                   create_app)
from atalaia_controller.engine import Controller
from atalaia_controller.firmware_release import REPORT_RESULTS
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub

SRC = Path(__file__).resolve().parents[1] / "console" / "src"
VENDORED = {
    "lib/preact.module.js": "9ba8bb591b0c9a72132ff65a76e69c5a4e49cf71721b47b659f3243658bde05b",
    "lib/htm.module.js": "ab33dd3f38059b9be4d5f5350128eefb2356639c4e0bbe9d9e8b3ba75847e9e4",
    "lib/qrcode.module.js": "ea91d7118a5395289170da848b7c6758b996163bfbccf312591ab65a4911b7c0",
}


class Refs(HTMLParser):
    """src and href attributes of a page."""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[str] = []
        self.inline_scripts = 0
        self.style_attrs = 0
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for name in ("src", "href"):
            if a.get(name):
                self.refs.append(a[name])
        if "style" in a:
            self.style_attrs += 1
        if tag == "script":
            self._in_script = True
            if not a.get("src"):
                self.inline_scripts += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False


def imports(js: str) -> list[str]:
    """Relative module imports of a script (static and import())."""
    return re.findall(r"""(?:from\s+|import\s*\(\s*|import\s+)['"](\.{1,2}/[^'"]+)['"]""", js)


def png_size(data: bytes) -> tuple[int, int]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG"
    return struct.unpack(">II", data[16:24])


class ConsoleFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = config(cls.tmp.name)
        cls.store = Store(cfg.db_path)
        cls.ctrl = Controller(cfg, cls.store, modem=FakeModem())
        cls.client = TestClient(create_app(cls.ctrl, Hub(), Auth(cfg.gm_token, cfg.read_token)))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.ctrl.stop()
        cls.store.close()
        cls.tmp.cleanup()

    def test_the_mount_is_the_source_folder(self):
        self.assertEqual(CONSOLE_DIR.resolve(), SRC.resolve())

    def test_index_served_with_security_headers(self):
        for path in ("/console/", "/console/index.html"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn("<title>Atalaia</title>", r.text)
            for k, v in SECURITY_HEADERS.items():
                self.assertEqual(r.headers.get(k), v, f"{path}: {k}")
        csp = SECURITY_HEADERS["Content-Security-Policy"]
        self.assertIn("script-src 'self';", csp)
        self.assertNotIn("unsafe-inline", csp)
        self.assertNotIn("unsafe-eval", csp)
        # No token needed for the static files; the API still needs one.
        self.assertEqual(self.client.get("/api/v1/nodes").status_code, 401)

    def test_only_the_field_map_page_may_reach_the_internet(self):
        """MF-27: the field-map page's CSP adds exactly OSM's tiles (images), the Overpass API and the DGT's
        WMS (connections); every other page of the console stays same-origin only."""
        r = self.client.get("/console/field-map.html")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-security-policy"], FIELD_MAP_HEADERS["Content-Security-Policy"])
        csp = dict(d.strip().split(" ", 1) for d in r.headers["content-security-policy"].split(";"))
        self.assertEqual(csp["script-src"], "'self'")
        self.assertEqual(csp["style-src"], "'self'")
        self.assertEqual(csp["default-src"], "'self'")
        self.assertEqual(csp["img-src"], "'self' blob: data: https://tile.openstreetmap.org")
        self.assertEqual(csp["connect-src"], "'self' https://overpass-api.de https://ortos.dgterritorio.gov.pt")
        self.assertNotIn("unsafe", r.headers["content-security-policy"])
        for k in ("X-Content-Type-Options", "Referrer-Policy"):
            self.assertEqual(r.headers[k], SECURITY_HEADERS[k])
        for path in ("/console/", "/console/field-map.js", "/console/components/field-render.js",
                     "/console/scoreboard.html"):
            got = self.client.get(path).headers["content-security-policy"]
            self.assertEqual(got, SECURITY_HEADERS["Content-Security-Policy"], path)
            for origin in FIELD_MAP_ORIGINS.values():
                self.assertNotIn(origin, got, path)
        # The page and its scripts name only those origins.
        code = "".join((SRC / rel).read_text(encoding="utf-8")
                       for rel in ("field-map.js", "components/field-render.js", "components/tile-map.js"))
        for url in set(re.findall(r"https://[a-z0-9.-]+", code)):
            self.assertIn(url, [*FIELD_MAP_ORIGINS.values(), "https://www.openstreetmap.org"], url)

    def test_redirects(self):
        for path, target in (("/", "/console/"), ("/console", "/console/"),
                             ("/scoreboard", "/console/scoreboard.html")):
            r = self.client.get(path, follow_redirects=False)
            self.assertIn(r.status_code, (302, 307), path)
            self.assertEqual(r.headers["location"], target)

    def test_pages_have_no_inline_scripts_or_styles(self):
        for page in ("index.html", "scoreboard.html", "field-map.html"):
            p = Refs()
            p.feed((SRC / page).read_text(encoding="utf-8"))
            self.assertEqual((p.inline_scripts, p.style_attrs), (0, 0), page)

    def served(self, rel: str) -> bytes:
        r = self.client.get(f"/console/{rel}")
        self.assertEqual(r.status_code, 200, rel)
        return r.content

    def test_every_referenced_file_exists_and_is_served(self):
        seen: set[str] = set()
        todo: list[str] = []
        for page in ("index.html", "scoreboard.html", "field-map.html"):
            p = Refs()
            p.feed((SRC / page).read_text(encoding="utf-8"))
            todo += p.refs
        while todo:
            rel = todo.pop()
            if rel in seen:
                continue
            seen.add(rel)
            self.assertTrue((SRC / rel).is_file(), rel)
            body = self.served(rel)
            if rel.endswith(".js"):
                base = Path(rel).parent
                for imp in imports(body.decode("utf-8")):
                    todo.append(_norm(base, imp))
        for must in ("app.js", "ui.js", "scoreboard.js", "lib/preact.module.js", "lib/htm.module.js",
                     "lib/qrcode.module.js", "components/join-panel.js", "manifest.json"):
            self.assertIn(must, seen)
        r = self.client.get("/console/app.js")
        self.assertIn("javascript", r.headers["content-type"])

    def test_service_worker_precaches_every_shell_file(self):
        sw = (SRC / "sw.js").read_text(encoding="utf-8")
        block = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
        shell = re.findall(r"'([^']+)'", block)
        self.assertIn("./", shell)
        for rel in shell:
            if rel == "./":
                continue
            self.assertTrue((SRC / rel).is_file(), rel)
            self.served(rel)
        # Every page, script, style, language file and icon is in the shell.
        for path in SRC.rglob("*"):
            rel = path.relative_to(SRC).as_posix()
            if path.suffix in (".html", ".js", ".css", ".json", ".png") and rel != "sw.js":
                self.assertIn(rel, shell, f"{rel} is not precached by sw.js")
        self.assertNotIn("/api/", block)

    def test_manifest_and_icons(self):
        manifest = json.loads(self.served("manifest.json"))
        self.assertEqual((manifest["display"], manifest["start_url"]), ("standalone", "./"))
        self.assertIn("Atalaia", manifest["name"])
        sizes = {}
        for icon in manifest["icons"]:
            w, h = png_size(self.served(icon["src"]))
            self.assertEqual(icon["sizes"], f"{w}x{h}")
            self.assertEqual(icon["type"], "image/png")
            sizes[w] = h
        self.assertEqual(sizes, {192: 192, 512: 512})

    def test_languages_have_the_same_keys(self):
        def flat(d, prefix=""):
            out = {}
            for k, v in d.items():
                if isinstance(v, dict):
                    out.update(flat(v, f"{prefix}{k}."))
                else:
                    out[f"{prefix}{k}"] = v
            return out

        pt = flat(json.loads((SRC / "i18n" / "pt.json").read_text(encoding="utf-8")))
        en = flat(json.loads((SRC / "i18n" / "en.json").read_text(encoding="utf-8")))
        self.assertEqual(sorted(pt), sorted(en))
        for lang, d in (("pt", pt), ("en", en)):
            for k, v in d.items():
                self.assertIsInstance(v, str, f"{lang}: {k}")
                self.assertTrue(v.strip(), f"{lang}: {k} is empty")
            # Placeholders match between the languages.
        for k in pt:
            self.assertEqual(sorted(re.findall(r"\{(\w+)\}", pt[k])), sorted(re.findall(r"\{(\w+)\}", en[k])), k)
        # Every key the code asks for exists (literal t('...') calls).
        code = "".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.js") if "lib" not in p.parts)
        used = set(re.findall(r"\bt\('([a-z_]+(?:\.[a-z_0-9]+)+)'", code))
        self.assertGreater(len(used), 100)
        for key in used:
            self.assertIn(key, pt, f"t('{key}') has no text")
        # Keys built at run time: game states, controller roles, radio states, tiers, kinds.
        for prefix, names in (("game.states", ("ready", "running", "paused", "ended")),
                              ("controller.roles", ("leader", "follower", "candidate")),
                              ("controller.radio_states", ("up", "down", "connecting", "closed", "none")),
                              ("controller.failover_modes", ("manual", "auto")),
                              ("nodes.tiers", ("full", "reduced", "proxy")),
                              ("tabs", ("game", "field", "nodes", "join", "presets", "feed", "controller")),
                              ("app", ("lang_pt", "lang_en")),
                              ("firmware.states", ("sent", "installed", "done", "failed", "rolled_back", "timeout",
                                                   "cancelled")),
                              ("firmware.reasons", tuple(r for r in REPORT_RESULTS if r != "installed")
                               + ("self_test",)),
                              ("firmware.results", ("sent", "unknown", "wrong_platform", "wrong_tier",
                                                    "unknown_version", "not_newer", "in_progress", "not_in_game",
                                                    "radio"))):
            for name in names:
                self.assertIn(f"{prefix}.{name}", pt)
        # European Portuguese, not Brazilian.
        text = " ".join(pt.values()).lower()
        for br in ("celular", "tela ", "time ", "você", "arquivo", "usuário"):
            self.assertNotIn(br, text, br)

    def test_vendored_libraries_are_unmodified(self):
        for rel, digest in VENDORED.items():
            self.assertEqual(hashlib.sha256((SRC / rel).read_bytes()).hexdigest(), digest, rel)
            self.assertIn(digest, (SRC / "lib" / "README.md").read_text(encoding="utf-8"), rel)

    def test_licence_headers(self):
        for path in sorted(SRC.rglob("*")):
            rel = path.relative_to(SRC).as_posix()
            if path.is_dir() or rel in VENDORED or path.suffix in (".png", ".json"):
                continue  # vendored, binary and JSON files are covered by REUSE.toml
            head = path.read_text(encoding="utf-8")[:400]
            # Split so that REUSE does not read these strings as this file's own tags. The
            # console is GPL-3.0-or-later with the app-store permission (decision PE24-8).
            self.assertIn("SPDX-" + "License-Identifier: GPL-3.0-or-later", head, rel)
            self.assertIn("SPDX-" + "FileCopyrightText: 2026 The Atalaia contributors", head, rel)

    def test_field_info_and_whoami(self):
        gm = {"Authorization": "Bearer gm-secret"}
        read = {"Authorization": "Bearer read-secret"}
        self.assertEqual(self.client.get("/api/v1/whoami", headers=gm).json()["role"], "gm")
        self.assertEqual(self.client.get("/api/v1/whoami", headers=read).json()["role"], "read")
        self.assertIsNone(self.client.get("/api/v1/field", headers=read).json()["image"])
        png = (SRC / "icons" / "icon-192.png").read_bytes()
        r = self.client.put("/api/v1/field/image", headers={**gm, "Content-Type": "image/png"}, content=png)
        self.assertEqual(r.status_code, 200, r.text)
        info = self.client.get("/api/v1/field", headers=read).json()["image"]
        self.assertEqual((info["content_type"], info["bytes"]), ("image/png", len(png)))
        self.assertEqual(self.client.get("/api/v1/field/image", headers=read).content, png)
        self.assertEqual(self.client.put("/api/v1/field/image", headers={**read, "Content-Type": "image/png"},
                                         content=png).status_code, 403)
        self.assertEqual(self.client.put("/api/v1/field/image", headers={**gm, "Content-Type": "text/plain"},
                                         content=b"x").status_code, 415)
        self.assertTrue(self.client.delete("/api/v1/field/image", headers=gm).json()["deleted"])
        self.assertIsNone(self.client.get("/api/v1/field", headers=read).json()["image"])


def _norm(base: Path, imp: str) -> str:
    parts = list(base.parts) if str(base) != "." else []
    for piece in imp.split("/"):
        if piece == "..":
            parts.pop()
        elif piece not in ("", "."):
            parts.append(piece)
    return "/".join(parts)


if __name__ == "__main__":
    unittest.main()
