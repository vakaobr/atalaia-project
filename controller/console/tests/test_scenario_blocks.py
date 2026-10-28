# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The scenario builder's block view (phase 5 plan phase 7, decisions P5F-1 to P5F-12) in a real
browser (headless Chromium, Playwright), against the real controller.

    python tools/docker_console.py -k ScenarioBlocks

The round trip: every scenario example (the two hand-written manifests in controller/tests/
scenarios/, the console's own example and the valid manifests of protocol/vectors/scenario.json)
becomes blocks in the page, is saved and loaded again as Blockly does, and the YAML the blocks
write is read by the controller's own reader: it compiles to exactly the same package (mode.yaml
and field.lua, byte for byte) and gets the same problems from the validator as the hand-written
text. Then the view itself: Portuguese and English, a change made on a block reaching the YAML
and the installed package, the controller's problems on their blocks, the blocks' own problems,
the keyboard, a phone's width, the read token, what the blocks refuse to show, offline, and
Blockly's stylesheets being exactly the ones the Content-Security-Policy allows. Every page is
checked for JavaScript errors, console errors (a refused inline style is one), failed requests
and Content-Security-Policy violations.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import unittest

from test_browser import CONTROLLER, GM, READ, REQUIRE, Field

from support import CORE, MODEM_HOST

from atalaia_controller.api import BLOCKLY_STYLES, SECURITY_HEADERS
from atalaia_controller.scenarios import compile_scenario, load, validate

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:
    if REQUIRE:
        raise
    sync_playwright = None

REPO = CONTROLLER.parent
SRC = CONTROLLER / "console" / "src"
BUILDER = (SRC / "components" / "scenario-builder.js").read_text(encoding="utf-8")
EXAMPLE = re.search(r"export const EXAMPLE = `(.*?)`;", BUILDER, re.S).group(1)
EXAMPLE_ID = "org.club.bridge-and-vault"


def examples() -> list[tuple[str, str]]:
    """(name, manifest text) of every scenario example."""
    out = [(path.name, path.read_text(encoding="utf-8"))
           for path in sorted((CONTROLLER / "tests" / "scenarios").glob("*.yaml"))]
    out.append(("the console's example", EXAMPLE))
    vectors = json.loads((REPO / "protocol" / "vectors" / "scenario.json").read_text(encoding="utf-8"))
    out += [(f"vector: {v['name']}", json.dumps(v["manifest"], ensure_ascii=False)) for v in vectors["valid"]]
    return out


# The round trip in the page: manifest -> blocks -> Blockly's saved state -> blocks -> YAML.
ROUND_TRIP = """async (manifest) => {
    const mod = await import('./components/scenario-blocks.js');
    const { state, lost } = mod.manifestToState(manifest);
    const first = new Blockly.Workspace();
    Blockly.serialization.workspaces.load(state, first);
    const saved = JSON.parse(JSON.stringify(Blockly.serialization.workspaces.save(first)));
    const second = new Blockly.Workspace();
    Blockly.serialization.workspaces.load(saved, second);
    const out = mod.workspaceToManifest(second);
    const yaml = mod.toYaml(out.manifest);
    first.dispose();
    second.dispose();
    return { lost, problems: out.problems, yaml };
}"""

# Marks a field of the nth block of a type in the view's workspace, so a real click can reach it.
MARK_FIELD = """([type, field, nth]) => {
    const ws = Blockly.getMainWorkspace();
    const b = ws.getAllBlocks(true).filter((x) => x.type === type)[nth];
    ws.centerOnBlock(b.id);
    document.querySelectorAll('[data-testid=blk-field]').forEach((e) => e.removeAttribute('data-testid'));
    b.getField(field).getSvgRoot().setAttribute('data-testid', 'blk-field');
}"""

# Every <style> element's SHA-256, as a Content-Security-Policy names it.
STYLE_HASHES = """async () => {
    const out = [];
    for (const s of document.querySelectorAll('style')) {
        const d = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s.textContent));
        out.push('sha256-' + btoa(String.fromCharCode(...new Uint8Array(d))));
    }
    return out;
}"""

CSP_LOG = """window.__csp = [];
document.addEventListener('securitypolicyviolation',
    (e) => window.__csp.push(`${e.violatedDirective} ${e.blockedURI} ${e.sample}`));"""


@unittest.skipIf(sync_playwright is None, "Playwright is not installed")
@unittest.skipUnless(MODEM_HOST, "host modem not built")
class ScenarioBlocksTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.field = Field()
        self.contexts = []
        self.pages = []
        self.errors: list[str] = []
        self.offline = False

    def tearDown(self):
        violations = [] if self.offline else [v for p in self.pages for v in p.evaluate("window.__csp || []")]
        for ctx in self.contexts:
            ctx.close()
        self.field.close()
        if not self.offline:
            self.assertEqual(self.errors, [], "JavaScript or console errors on the page")
        self.assertEqual(violations, [], "Content-Security-Policy violations")

    # --- helpers ------------------------------------------------------------------------

    def console(self, token: str = GM, width: int = 1280, height: int = 900, lang: str = "pt", dark: bool = False):
        ctx = self.browser.new_context(viewport={"width": width, "height": height},
                                       color_scheme="dark" if dark else "light")
        self.contexts.append(ctx)
        ctx.add_init_script(CSP_LOG)
        page = ctx.new_page()
        page.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        page.on("console", lambda m: self.errors.append(f"console: {m.text}") if m.type == "error" else None)
        page.on("response", lambda r: self.errors.append(f"HTTP {r.status} {r.request.method} {r.url}")
                if r.status >= 400 else None)
        page.goto(self.field.base + "/console/")
        page.get_by_test_id("token").fill(token)
        page.get_by_test_id("login").click()
        expect(page.get_by_test_id("tab-game")).to_be_visible()
        if lang != "pt":
            page.get_by_test_id("lang").first.select_option(lang)
        self.pages.append(page)
        page.get_by_test_id("tab-scenarios").click()
        return page

    def blocks_view(self, page) -> None:
        page.get_by_test_id("scenario-view-blocks").click()
        expect(page.locator(".scn-blocks .blocklySvg").first).to_be_visible()
        expect(page.get_by_test_id("scenario-view-blocks")).to_have_attribute("aria-pressed", "true")

    def example_as_blocks(self, page) -> None:
        page.get_by_test_id("scenario-example").click()
        expect(page.get_by_test_id("scenario-ok")).to_be_visible()
        self.blocks_view(page)

    def yaml_text(self, page) -> str:
        """The editor's text, from the YAML view (the block view is left)."""
        page.get_by_test_id("scenario-view-yaml").click()
        return page.get_by_test_id("scenario-text").input_value()

    def edit_field(self, page, block_type: str, field: str, value: str, nth: int = 0) -> None:
        """Clicks a block's field and types a new value, as a GM does."""
        page.evaluate(MARK_FIELD, [block_type, field, nth])
        page.get_by_test_id("blk-field").click()
        editor = page.locator(".blocklyHtmlInput")
        expect(editor).to_be_visible()
        editor.fill(value)
        editor.press("Enter")
        expect(editor).to_have_count(0)

    def blocks_text(self, page) -> str:
        return page.locator(".scn-blocks").text_content().replace(" ", " ")

    def no_horizontal_scroll(self, page) -> None:
        width = page.evaluate("[document.documentElement.scrollWidth, window.innerWidth]")
        self.assertLessEqual(width[0], width[1], "the page scrolls sideways")

    # --- the round trip -------------------------------------------------------------------

    @unittest.skipIf(CORE is None, "the shared core library is not built")
    def test_round_trip_of_every_example_compiles_identically(self):
        page = self.console()
        self.blocks_view(page)  # loads Blockly and defines the blocks
        cases = examples()
        self.assertEqual(len(cases), 13)  # with scenario.json's emoji as a surrogate pair (PE24-107)
        for name, text in cases:
            with self.subTest(name):
                original = load(text)
                got = page.evaluate(ROUND_TRIP, original)
                self.assertEqual((got["lost"], got["problems"]), ([], []))
                written = load(got["yaml"])
                self.assertEqual([p.to_dict() for p in validate(written)],
                                 [p.to_dict() for p in validate(original)])
                self.assertEqual(compile_scenario(written).files, compile_scenario(original).files)
                # The same manifest, but for what the blocks always write: the version as text,
                # the boxes' language and the teams (the defaults when the text leaves them out).
                expected = {**original, "version": str(original["version"]),
                            "lang": original.get("lang", "pt"), "teams": original.get("teams", ["red", "blue"])}
                self.assertEqual(written, expected)
                # And the controller (its reader, the validator, the core's load check) agrees.
                check = self.field.http.post("/api/v1/scenarios/check", json={"manifest": got["yaml"]}).json()
                self.assertTrue(check["ok"], check["problems"])
                self.assertTrue(check["checked_in_core"])

    @unittest.skipIf(CORE is None, "the shared core library is not built")
    def test_names_in_german_and_chinese_round_trip_and_old_manifests_stay(self):
        """SCL-1: an objective, the scenario and a parameter's label carry names in pt, de and
        zh-tw (blocks of their own, nothing lost); a manifest with only i18n.pt, as written before
        German and Chinese, gives the same blocks and the same YAML as ever; a language the
        manifest format has no translation for (fr, or en: English is the text itself) is named as
        lost, and the compiled German box setup carries the German name."""
        page = self.console()
        self.blocks_view(page)
        base = {"id": "org.club.names", "version": "1", "name": "Names", "lang": "de",
                "teams": ["red", "blue"], "nodes": {"a": {"role": "objective"}},
                "params": {"bonus": {"type": "int", "default": 5, "label": "Bonus"}},
                "objectives": [{"id": "hill", "name": "Hill", "type": "capture_and_hold", "target": "a"}]}
        names = {"pt": "Colina", "de": "H\u00fcgel", "zh-tw": "\u5c71\u4e18"}
        full = json.loads(json.dumps(base))
        full["i18n"] = {lang: {"name": f"S-{n}", "params": {"bonus": f"B-{n}"}} for lang, n in names.items()}
        full["objectives"][0]["i18n"] = {lang: {"name": n, "description": f"D-{n}"} for lang, n in names.items()}
        got = page.evaluate(ROUND_TRIP, full)
        self.assertEqual((got["lost"], got["problems"]), ([], []))
        written = load(got["yaml"])
        self.assertEqual(written["i18n"], full["i18n"])
        self.assertEqual(written["objectives"][0]["i18n"], full["objectives"][0]["i18n"])
        self.assertEqual([p.to_dict() for p in validate(written)], [])
        self.assertIn('label = "H\u00fcgel"', compile_scenario(written).files["field.lua"])
        # Before: only Portuguese, the same as it was.
        old = json.loads(json.dumps(base))
        old["objectives"][0]["i18n"] = {"pt": {"name": "Colina"}}
        old["i18n"] = {"pt": {"name": "Nomes", "params": {"bonus": "Bónus"}}}
        got = page.evaluate(ROUND_TRIP, old)
        self.assertEqual((got["lost"], got["problems"]), ([], []))
        self.assertEqual(load(got["yaml"])["objectives"][0]["i18n"], {"pt": {"name": "Colina"}})
        self.assertEqual(load(got["yaml"])["i18n"], old["i18n"])
        # Languages the blocks (and the format) do not have are named, never dropped.
        for lang in ("fr", "en"):
            bad = json.loads(json.dumps(base))
            bad["objectives"][0]["i18n"] = {lang: {"name": "X"}}
            lost = page.evaluate(ROUND_TRIP, bad)["lost"]
            self.assertEqual(lost, [f"objectives[0].i18n.{lang}"])

    # --- the view -------------------------------------------------------------------------

    @unittest.skipIf(CORE is None, "the shared core library is not built")
    def test_blocks_edit_check_and_install_in_portuguese_then_english(self):
        """The example as blocks: a block's points changed by a click and typing reach the YAML; a
        wrong reference is shown on its block (Show gives it the focus) and keeps Install off, as
        a rule given twice does; the scenario installed from the blocks is the package of the
        same YAML written by hand. In English the blocks speak English and keep the scenario."""
        page = self.console()
        self.example_as_blocks(page)
        text = self.blocks_text(page)
        for words in ("cenário", "objetivo", "capturar e manter", "dá", "pontos", "depois de cumprido"):
            self.assertIn(words, text)
        self.assertIn("Teclado:", page.locator("#scn-blocks-help").inner_text())
        install = page.get_by_test_id("scenario-install")

        self.edit_field(page, "scn_points", "POINTS", "60")
        expect(page.get_by_test_id("scenario-ok")).to_be_visible()
        self.edit_field(page, "scn_after", "OBJECTIVE", "brige")
        problem = page.locator('[data-testid=scenario-problems] [data-code="unknown_reference"]')
        expect(problem).to_contain_text("objectives[1].depends_on[0]")
        expect(page.locator(".scn-blocks .scn-problem")).to_have_count(1)
        expect(install).to_be_disabled()
        problem.get_by_test_id("scenario-show").click()
        self.assertTrue(page.evaluate("!!document.activeElement.closest('.scn-blocks')"))
        self.edit_field(page, "scn_after", "OBJECTIVE", "bridge")
        expect(page.get_by_test_id("scenario-ok")).to_be_visible()
        expect(page.locator(".scn-blocks .scn-problem")).to_have_count(0)

        # A second points block in the first objective: only the blocks know it is one too many.
        page.evaluate("""() => {
            const ws = Blockly.getMainWorkspace();
            const points = ws.getAllBlocks(true).find((b) => b.type === 'scn_points');
            const extra = ws.newBlock('scn_points');
            extra.initSvg();
            extra.render();
            points.nextConnection.connect(extra.previousConnection);
        }""")
        twice = page.locator('[data-testid=scenario-block-problems] [data-code="twice"]')
        expect(twice).to_contain_text("Dado duas vezes")
        expect(install).to_be_disabled()
        page.evaluate("""() => Blockly.getMainWorkspace().getAllBlocks(true)
            .filter((b) => b.type === 'scn_points')[1].dispose(true)""")
        expect(twice).to_have_count(0)
        expect(install).to_be_enabled()
        install.click()
        expect(page.get_by_test_id("scenario-installed")).to_contain_text("Ponte e cofre 1")
        expect(page.get_by_test_id("scenario-list")).to_contain_text("Tomar a ponte, Abrir o cofre")
        installed = self.field.http.get(f"/api/v1/scenarios/{EXAMPLE_ID}").json()
        by_hand = compile_scenario(load(EXAMPLE.replace("points: 50", "points: 60")))
        self.assertEqual(installed["files"], by_hand.files)

        page.get_by_test_id("lang").first.select_option("en")
        expect(page.locator(".scn-blocks .blocklySvg").first).to_be_visible()
        expect(page.locator(".scn-blocks")).to_contain_text("capture and hold")
        text = self.blocks_text(page)
        for words in ("scenario", "objective", "gives", "points", "is completed"):
            self.assertIn(words, text)
        self.assertEqual(page.evaluate("Blockly.getMainWorkspace().getAllBlocks(true)"
                                       ".find((b) => b.type === 'scn_points').getFieldValue('POINTS')"), 60)
        written = load(self.yaml_text(page))
        self.assertEqual(written["objectives"][0]["effect"], {"points": 60})
        self.assertEqual(compile_scenario(written).files, by_hand.files)

    def test_keyboard_reaches_and_changes_the_blocks(self):
        """Without a mouse: Tab from the view's buttons reaches the categories; the right arrow
        opens one, Enter takes its block and puts it down, Delete removes it; W goes to the blocks,
        the arrows to the scenario block and its name, Enter edits the name, and the YAML follows.
        The blocks have labels a screen reader reads."""
        page = self.console(lang="en")
        self.example_as_blocks(page)
        count = "Blockly.getMainWorkspace().getAllBlocks(false).length"
        focused = "document.activeElement.getAttribute('aria-label') || ''"
        before = page.evaluate(count)
        page.get_by_test_id("scenario-view-blocks").focus()
        page.keyboard.press("Tab")
        self.assertEqual(page.evaluate("document.activeElement.getAttribute('role')"), "treeitem")
        self.assertTrue(page.evaluate("!!document.activeElement.closest('.scn-blocks')"))
        page.keyboard.press("ArrowRight")  # the first category's blocks: a new objective
        self.assertTrue(page.evaluate(focused).startswith("objective, objective, name"), page.evaluate(focused))
        page.keyboard.press("Enter")  # taken
        page.keyboard.press("Enter")  # put down
        self.assertEqual(page.evaluate(count), before + 1)
        page.keyboard.press("Delete")
        self.assertEqual(page.evaluate(count), before)
        page.keyboard.press("w")
        page.keyboard.press("ArrowDown")
        self.assertIn("scenario, Bridge and vault", page.evaluate(focused))
        page.keyboard.press("ArrowRight")
        self.assertEqual(page.evaluate(focused), "Edit text: Bridge and vault")
        page.keyboard.press("Enter")
        page.keyboard.type("Bridge, vault and more")
        page.keyboard.press("Enter")
        expect(page.get_by_test_id("scenario-ok")).to_be_visible()
        self.assertEqual(load(self.yaml_text(page))["name"], "Bridge, vault and more")

    def test_read_token_on_a_phone_in_english(self):
        """A read-only phone: the blocks fit the width (no sideways scroll), the categories are
        above them, the checks work, and there is nothing to install."""
        page = self.console(READ, width=390, height=844, lang="en")
        page.get_by_test_id("scenario-view-blocks").click()
        expect(page.locator(".scn-blocks .blocklySvg").first).to_be_visible()
        expect(page.locator(".scn-blocks")).to_contain_text("scenario")
        expect(page.get_by_test_id("scenario-problems")).to_contain_text("Error")  # a new scenario: no name yet
        expect(page.get_by_test_id("scenario-install")).to_have_count(0)
        self.no_horizontal_scroll(page)
        box = page.locator(".scn-blocks").bounding_box()
        self.assertLessEqual(box["x"] + box["width"], 390)
        self.assertTrue(page.evaluate("Blockly.getMainWorkspace().horizontalLayout"))
        page.get_by_test_id("scenario-example").click()
        expect(page.locator(".scn-blocks")).to_contain_text("enter a code")
        expect(page.get_by_test_id("scenario-ok")).to_be_visible()
        self.no_horizontal_scroll(page)

    def test_what_the_blocks_cannot_show_stays_in_yaml(self):
        """A key the blocks have no place for is named, and the YAML view stays; so does a text the
        controller cannot hand over as it is (a YAML date)."""
        page = self.console(lang="en")
        editor = page.get_by_test_id("scenario-text")
        editor.fill(EXAMPLE + "extra: 1\n")
        expect(page.get_by_test_id("scenario-problems")).to_contain_text("unknown key")
        page.get_by_test_id("scenario-view-blocks").click()
        expect(page.get_by_test_id("scenario-blocks-error")).to_contain_text("these parts as they are: extra.")
        expect(editor).to_be_visible()
        editor.fill(EXAMPLE.replace("version: 1", "version: 2026-10-22"))
        page.get_by_test_id("scenario-view-blocks").click()
        expect(page.get_by_test_id("scenario-blocks-error")).to_contain_text("not a manifest the blocks can show")
        expect(editor).to_be_visible()
        # The comments of a text stay until the blocks change something.
        editor.fill("# kept\n" + EXAMPLE)
        self.blocks_view(page)
        self.assertTrue(self.yaml_text(page).startswith("# kept\n"))

    def test_blockly_styles_are_the_allowed_ones(self):
        """Blockly writes two stylesheets; the console's CSP allows exactly those two texts, by
        their SHA-256, and nothing else inline: in light and in dark (one theme name)."""
        csp = SECURITY_HEADERS["Content-Security-Policy"]
        self.assertNotIn("unsafe-inline", csp)
        self.assertIn("script-src 'self';", csp)
        allowed = set(re.findall(r"sha256-[A-Za-z0-9+/=]+", BLOCKLY_STYLES))
        self.assertEqual(len(allowed), 2)
        served = self.field.http.get("/console/").headers["content-security-policy"]
        self.assertEqual(served, csp)
        for dark in (False, True):
            page = self.console(dark=dark)
            self.example_as_blocks(page)
            hashes = page.evaluate(STYLE_HASHES)
            self.assertEqual(set(hashes), allowed, f"Blockly's stylesheets changed (dark={dark}): put {hashes} "
                             "in BLOCKLY_STYLES (controller/atalaia_controller/api.py)")

    def test_blockly_is_kept_for_offline_use(self):
        """The service worker keeps Blockly and the blocks with the console's shell, and serves
        them from its cache when the controller cannot be reached (the field's Wi-Fi drops)."""
        page = self.console()
        page.evaluate("navigator.serviceWorker.ready.then(() => true)")
        cache = re.search(r"const CACHE = '([^']+)'", (SRC / "sw.js").read_text(encoding="utf-8")).group(1)
        cached = page.evaluate(f"caches.open('{cache}').then((c) => c.keys())"
                               ".then((k) => k.map((r) => new URL(r.url).pathname))")
        files = ("/console/lib/blockly/blockly_compressed.js", "/console/lib/blockly/msg/pt.js",
                 "/console/lib/blockly/msg/en.js", "/console/lib/blockly/media/sprites.svg",
                 "/console/components/scenario-blocks.js", "/console/components/scenario-block-view.js")
        for path in files:
            self.assertIn(path, cached)
        page.reload()  # now controlled by the service worker
        expect(page.get_by_test_id("tab-scenarios")).to_be_visible()
        self.offline = True  # from here on the API's failures are expected
        page.context.set_offline(True)
        got = page.evaluate("(paths) => Promise.all(paths.map((p) => fetch(p).then((r) => r.ok)"
                            ".catch(() => false)))", list(files))
        page.context.set_offline(False)
        self.assertEqual(got, [True] * len(files))


class HashesOfBlocklyStyles(unittest.TestCase):
    """BLOCKLY_STYLES are well-formed CSP hash sources (the browser test checks they are Blockly's)."""

    def test_two_sha256_sources(self):
        for source in re.findall(r"'([^']+)'", BLOCKLY_STYLES):
            algo, _, digest = source.partition("-")
            self.assertEqual(algo, "sha256")
            self.assertEqual(len(base64.b64decode(digest)), hashlib.sha256().digest_size)
