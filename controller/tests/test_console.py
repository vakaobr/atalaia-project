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
from atalaia_controller.api import (CONSOLE_DIR, FEATURES, FIELD_MAP_HEADERS, FIELD_MAP_ORIGINS, FIELD_MAP_ORTHO_TILES,
                                    FIELD_MAP_ORTHOPHOTOS, SECURITY_HEADERS, Auth, create_app)
from atalaia_controller.engine import BOX_LANGUAGES, Controller
from atalaia_controller.firmware_release import REPORT_RESULTS
from atalaia_controller.pod_config import COLOURS as POD_COLOURS
from atalaia_controller.store import Store
from atalaia_controller.ws import Hub

SRC = Path(__file__).resolve().parents[1] / "console" / "src"
VENDORED = {
    "lib/preact.module.js": "9ba8bb591b0c9a72132ff65a76e69c5a4e49cf71721b47b659f3243658bde05b",
    "lib/htm.module.js": "ab33dd3f38059b9be4d5f5350128eefb2356639c4e0bbe9d9e8b3ba75847e9e4",
    "lib/qrcode.module.js": "ea91d7118a5395289170da848b7c6758b996163bfbccf312591ab65a4911b7c0",
    # Blockly 13.3.0 for the scenario blocks (phase 5 plan phase 7): the same files, byte for byte,
    # as the mode editor's (simulator/atalaia_sim/editor/vendor/blockly/README.md).
    "lib/blockly/blockly_compressed.js": "d3f46af56951a7aed27f09f872dca66ed70a932ca8be9aade3d9df06ceacd078",
    "lib/blockly/msg/en.js": "155b0e29ad2bd59ad463ebde5c3ace7685ea5c25d019e950aab625b3259d7e02",
    "lib/blockly/msg/pt.js": "6ff9ce8534c68b16c3ff463d598a7bd1b6d28c534e9eec038d349f13f9478579",
    "lib/blockly/media/delete-icon.svg": "3eee02b06f476ce746566808178543389e53cd4e9d7fd32b69e329eff4fc71ef",
    "lib/blockly/media/foldout-icon.svg": "0ac7478b56f5e5cc583c26710cb7ee5edcedb563cde65cd2385f4dd3e9e08c64",
    "lib/blockly/media/handclosed.cur": "4a1637e16f33e1b02f96f699ada695edededfd089530372126d375ad9ed2f0a5",
    "lib/blockly/media/handdelete.cur": "e53ef200d76fef617bd2e307a100d778834ad49784f80c1abc6da547e50b8040",
    "lib/blockly/media/handopen.cur": "d2ec9a81d9a76b0f64b7168e5f05ee660ffb6ba7e35695caaf9851e6b01a04fd",
    "lib/blockly/media/resize-handle.svg": "c95d07b3fb3aaa088e6665061b01952e7ea9dda462b7032a85e095bf8a12855b",
    "lib/blockly/media/sprites.svg": "862de0ee081fa9baf504e673736d7446439c15246452258cab964a82566ef40f",
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
        """MF-27, MF-45: the field-map page's CSP adds exactly OSM's tiles (images), the Overpass API, the
        DGT's WMS and Nominatim (connections); every other page of the console stays same-origin only.
        MF-51: one more public Overpass instance (VK's left out, pending the maintainer); MF-54: the DGT's
        WMS also as images (the map's *Ortofoto* layer). MF-43: only that page may ask for the GM's
        location."""
        r = self.client.get("/console/field-map.html")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["content-security-policy"], FIELD_MAP_HEADERS["Content-Security-Policy"])
        csp = dict(d.strip().split(" ", 1) for d in r.headers["content-security-policy"].split(";"))
        self.assertEqual(csp["script-src"], "'self'")
        self.assertEqual(csp["style-src"], "'self'")
        self.assertEqual(csp["default-src"], "'self'")
        # MF-65 to MF-80: the open orthophotos, each WMS origin as images (the map's tiles) and as a connection
        # (the drawn image's one picture); a WMTS on an origin of its own as images only (MF-79); nothing else.
        ortho = ("https://ortos.dgterritorio.gov.pt https://www.ign.es https://data.geopf.fr https://service.pdok.nl "
                 "https://wms.ngi.be https://geo.api.vlaanderen.be https://geoservices.wallonie.be "
                 "https://wms.geoportail.lu https://wms.geo.admin.ch https://gdi.berlin.de https://isk.geobasis-bb.de "
                 "https://geoservices.bayern.de https://geodienste.bremen.de https://www.gds-srv.hessen.de "
                 "https://www.geodaten-mv.de https://www.wms.nrw.de https://geo4.service24.rlp.de "
                 "https://geoportal.saarland.de https://geodienste.sachsen.de https://www.geoproxy.geoportal-th.de "
                 "https://mapy.geoportal.gov.pl https://ags.cuzk.gov.cz")
        tiles = "https://wmts1.geoportail.lu https://wmts.geo.admin.ch https://www.wmts.nrw.de"
        self.assertEqual(csp["img-src"], f"'self' blob: data: https://tile.openstreetmap.org {ortho} {tiles}")
        self.assertEqual(csp["connect-src"], "'self' https://overpass-api.de https://overpass.private.coffee "
                                             f"{ortho} https://nominatim.openstreetmap.org")
        self.assertNotIn("mail.ru", r.headers["content-security-policy"])  # MF-51: not without the maintainer
        self.assertNotIn("unsafe", r.headers["content-security-policy"])
        for k in ("X-Content-Type-Options", "Referrer-Policy"):
            self.assertEqual(r.headers[k], SECURITY_HEADERS[k])
        # The GM's location: this page only (the default allowlist is already 'self'; said explicitly).
        self.assertEqual(r.headers["permissions-policy"], "geolocation=(self)")
        for path in ("/console/", "/console/index.html", "/console/field-map.js",
                     "/console/components/field-render.js", "/console/components/place-search.js",
                     "/console/scoreboard.html", "/console/poster.html", "/console/labels.html"):
            got = self.client.get(path)
            self.assertEqual(got.headers["content-security-policy"], SECURITY_HEADERS["Content-Security-Policy"], path)
            for origin in FIELD_MAP_ORIGINS.values():
                self.assertNotIn(origin, got.headers["content-security-policy"], path)
            self.assertEqual(got.headers["permissions-policy"], "geolocation=()", path)
        # The page and its scripts name only those origins (and the credits' links, never fetched).
        code = "".join((SRC / rel).read_text(encoding="utf-8")
                       for rel in ("field-map.js", "components/field-render.js", "components/tile-map.js",
                                   "components/place-search.js", "components/field-levels.js",
                                   "components/ortho-sources.js", "components/ortho-coverage.js"))
        links = ["https://www.openstreetmap.org", "https://www.dgterritorio.gov.pt", "https://www.scne.es",
                 "https://cartes.gouv.fr", "https://www.beeldmateriaal.nl", "https://ngi.be", "https://www.vlaanderen.be",
                 "https://geodata.wallonie.be", "https://data.public.lu", "https://www.swisstopo.admin.ch",
                 "https://www.govdata.de", "https://www.geodaten.bayern.de", "https://creativecommons.org",
                 "https://www.geoportal.gov.pl", "https://www.cuzk.gov.cz"]
        for url in set(re.findall(r"https://[a-z0-9.-]+", code)):
            self.assertIn(url, [*FIELD_MAP_ORIGINS.values(), *links], url)
        # Each orthophoto's WMS (its image, and its tiles where it has no WMTS) is on an origin the policy names
        # as images and connections, each WMTS on one it names as images, and every origin of the policy is used.
        sources = (SRC / "components/ortho-sources.js").read_text(encoding="utf-8")

        def origins(pattern: str) -> set:
            return {re.match(r"https://[a-z0-9.-]+", u).group(0) for u in re.findall(pattern, sources)}
        wms = origins(r"(?:wms: |_WMS = )'(https://[^']+)")
        tiled = origins(r"(?:wmtsTile\(|=> `)'?(https://[^'`]+)")
        self.assertEqual(wms, set(FIELD_MAP_ORTHOPHOTOS))
        self.assertEqual(tiled - wms, set(FIELD_MAP_ORTHO_TILES))

    def test_redirects(self):
        for path, target in (("/", "/console/"), ("/console", "/console/"),
                             ("/scoreboard", "/console/scoreboard.html")):
            r = self.client.get(path, follow_redirects=False)
            self.assertIn(r.status_code, (302, 307), path)
            self.assertEqual(r.headers["location"], target)

    def test_pages_have_no_inline_scripts_or_styles(self):
        for page in ("index.html", "scoreboard.html", "field-map.html", "poster.html", "labels.html"):
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
                              ("app", ("lang_pt", "lang_en", "lang_de")),
                              ("box_language.choices", BOX_LANGUAGES),
                              ("firmware.states", ("sent", "installed", "done", "failed", "rolled_back", "timeout",
                                                   "cancelled")),
                              ("firmware.reasons", tuple(r for r in REPORT_RESULTS if r != "installed")
                               + ("self_test",)),
                              ("pod_config.states", ("sent", "applied", "no_answer", "cancelled")),
                              ("pod_config.colours", POD_COLOURS),
                              ("firmware.results", ("sent", "unknown", "wrong_platform", "wrong_tier",
                                                    "unknown_version", "not_newer", "in_progress", "not_in_game",
                                                    "radio"))):
            for name in names:
                self.assertIn(f"{prefix}.{name}", pt)
        # European Portuguese, not Brazilian.
        text = " ".join(pt.values()).lower()
        for br in ("celular", "tela ", "time ", "você", "arquivo", "usuário"):
            self.assertNotIn(br, text, br)
        # German and Traditional Chinese (plan phases 10 and 11, P5H-2): every language the
        # console offers has a table, a name in the switcher and a box-language choice; either may
        # lack a key (the console shows English: ui.js), never have one English lacks.
        langs = re.search(r"export const LANGS = \[([^\]]*)\]", (SRC / "ui.js").read_text(encoding="utf-8"))
        self.assertEqual(re.findall(r"'([\w-]+)'", langs.group(1)), ["pt", "en", "de", "zh-tw"])
        for code in ("pt", "en", "de", "zh-tw"):
            self.assertIn(f"app.lang_{code}", en)
            self.assertIn(f"box_language.choices.{code}", en)
        for code in ("de", "zh-tw"):
            other = flat(json.loads((SRC / "i18n" / f"{code}.json").read_text(encoding="utf-8")))
            self.assertEqual(set(other) - set(en), set(), code)
            for k, v in other.items():
                self.assertTrue(isinstance(v, str) and v.strip(), f"{code}: {k} is empty")
                self.assertEqual(sorted(re.findall(r"\{(\w+)\}", v)), sorted(re.findall(r"\{(\w+)\}", en[k])),
                                 f"{code}: {k}")
                self.assertEqual(sorted(re.findall(r"%\d", v)), sorted(re.findall(r"%\d", en[k])), f"{code}: {k}")
            self.assertIn(f"i18n/{code}.json", (SRC / "sw.js").read_text(encoding="utf-8"))
        # Taiwan's conventions: full-width punctuation after Han, no Simplified characters and
        # "你", not "您" (docs/translations/glossary.md; the decimal point: test_browser.py).
        zh = flat(json.loads((SRC / "i18n" / "zh-tw.json").read_text(encoding="utf-8")))
        text = "".join(zh.values())
        for simplified in "这设启动队游戏据点无线电开关时间对选择":
            self.assertNotIn(simplified, text, simplified)
        # ("緯度, 經度" is what to type, with the ASCII comma a map app copies.)
        self.assertEqual(re.findall(r"[\u4e00-\u9fff][,;:!?]", text.replace("緯度, 經度", "")), [])
        self.assertNotIn("您", text)

    def test_scenario_blocks_have_their_texts(self):
        """The scenario blocks' texts (phase 5 plan phase 7): every tr('...') of the blocks, the
        names built at run time (objective types, who sees an objective, the blocks' own
        problems), in both languages, with the same %1, %2... as in English."""
        js = (SRC / "components" / "scenario-blocks.js").read_text(encoding="utf-8")
        keys = set(re.findall(r"\btr\('([a-z_]+)'\)", js)) | set(re.findall(r"\bcat\('([a-z_]+)'", js))
        keys |= {f"type_{v}" for v in re.search(r"export const TYPES = \[(.*?)\];", js).group(1)
                 .replace("'", "").replace(" ", "").split(",")}
        keys |= {f"visibility_{v}" for v in ("public", "team", "squad", "hidden")}
        keys |= {f"lang_{v}" for v in ("pt", "en", "de", "zh-tw")}  # the language dropdown (PKB-9)
        # The name and description blocks per i18n language, built from TRANSLATIONS (SCL-1).
        suffixes = re.findall(r"\['[a-z-]+', '([a-z_]+)'\]",
                              re.search(r"export const TRANSLATIONS = \[(.*?)\];", js).group(1))
        self.assertEqual(suffixes, ["pt", "de", "zh_tw"])
        keys |= {f"{what}_{s}" for what in ("name", "description") for s in suffixes}
        self.assertGreater(len(keys), 60)
        for lang in ("pt", "en"):
            d = json.loads((SRC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))["scenario_blocks"]
            for key in keys:
                self.assertIn(key, d["blocks"], f"{lang}: scenario_blocks.blocks.{key}")
            self.assertEqual(sorted(d["problems"]), ["loose", "misplaced", "twice"], lang)
        en = json.loads((SRC / "i18n" / "en.json").read_text(encoding="utf-8"))["scenario_blocks"]["blocks"]
        pt = json.loads((SRC / "i18n" / "pt.json").read_text(encoding="utf-8"))["scenario_blocks"]["blocks"]
        for key in en:
            self.assertEqual(sorted(re.findall(r"%\d", pt[key])), sorted(re.findall(r"%\d", en[key])), key)
        self.assertEqual(sorted(en), sorted(keys), "a text no block uses, or a block without its text")

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

    # One endpoint per console area (decision PE24-70; the Android controller's
    # app/test/controller/console_bundle_test.dart has the same list).
    AREA_ENDPOINTS = {
        "checkin": ("GET", "/api/v1/checkin/poster"),
        "join": ("POST", "/api/v1/join"),
        "box_language": ("GET", "/api/v1/settings/box-language"),
        "positions": ("GET", "/api/v1/positions"),
        "presets": ("GET", "/api/v1/presets"),
        "branding": ("GET", "/api/v1/field/branding"),
        "radio": ("GET", "/api/v1/radio"),
        "boxes": ("GET", "/api/v1/boxes"),
        "adoption": ("GET", "/api/v1/adopt"),
        "firmware": ("GET", "/api/v1/firmware"),
        "pod_config": ("GET", "/api/v1/pod-config"),
        "atak": ("GET", "/api/v1/atak"),
        "field": ("GET", "/api/v1/field/features"),
        "scenarios": ("GET", "/api/v1/scenarios"),
        "schedule": ("GET", "/api/v1/schedule"),
        "mode_packages": ("GET", "/api/v1/mode-fetch"),
        "failover": ("POST", "/api/v1/controller/promote"),
    }

    def test_whoami_features_are_the_consoles_areas_and_served(self):
        for token in ("gm-secret", "read-secret"):
            who = self.client.get("/api/v1/whoami", headers={"Authorization": f"Bearer {token}"}).json()
            self.assertEqual(who["features"], list(FEATURES), token)
        # The console's own list (ui.js AREAS) names the same areas.
        ui = (SRC / "ui.js").read_text(encoding="utf-8")
        listed = re.search(r"export const AREAS = \[([^\]]*)\]", ui)
        self.assertIsNotNone(listed)
        self.assertEqual(re.findall(r"'([a-z_]+)'", listed.group(1)), list(FEATURES))
        self.assertEqual(set(self.AREA_ENDPOINTS), set(FEATURES))
        gm = {"Authorization": "Bearer gm-secret"}
        for area, (method, path) in self.AREA_ENDPOINTS.items():
            r = self.client.request(method, path, headers=gm, json=None if method == "GET" else {})
            unknown = r.status_code == 405 or (r.status_code == 404 and r.json().get("detail") == "Not Found")
            self.assertFalse(unknown, f"{area}: {method} {path} -> {r.status_code}")

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
