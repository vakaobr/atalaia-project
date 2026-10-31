# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The project page's language flags and footer in a real browser (headless Chromium, Playwright).

    docker run --rm -v "$PWD":/src:ro -w /src mcr.microsoft.com/playwright/python:v1.49.0-noble \
        python3 tools/site_browser_test.py

It serves site/ and opens every generated page, at a phone width and a desktop width, in the light
and the dark colour scheme, and checks that: the four flags are links to the same page in each
language (hreflang, lang, aria-label, title, aria-current on the current language only); they sit at
the top right; the page has no horizontal scroll; the flag font is loaded and is used for the flags
only (its unicode-range); a flag shows a visible outline when a keyboard focuses it; and the footer's
text is as wide as its container (not cut at 80ch).
"""

from __future__ import annotations

import functools
import http.server
import threading
import unittest
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

SITE = Path(__file__).resolve().parents[1] / "site"
LANGS = [("pt-PT", "Português"), ("en", "English"), ("de", "Deutsch"), ("zh-Hant-TW", "繁體中文（台灣）")]
FLAGS = ["\U0001F1F5\U0001F1F9", "\U0001F1EC\U0001F1E7", "\U0001F1E9\U0001F1EA", "\U0001F1F9\U0001F1FC"]
PAGES = sorted(p.relative_to(SITE).as_posix() for p in SITE.rglob("index.html")
               if not {"src", "i18n", "img", "fonts"} & set(p.relative_to(SITE).parts))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D102
        pass


class SiteFlags(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sync_playwright is None:
            raise unittest.SkipTest("Playwright is not installed")
        handler = functools.partial(Quiet, directory=str(SITE))
        cls.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}/"
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.httpd.shutdown()

    def test_pages_found(self):
        self.assertEqual(len(PAGES), 7 * 4)

    def test_flags_and_footer_everywhere(self):
        for scheme in ("light", "dark"):
            for width, height in ((375, 700), (1280, 800)):
                ctx = self.browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme)
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                for path in PAGES:
                    with self.subTest(page=path, scheme=scheme, width=width):
                        self.check_page(page, self.base + path.removesuffix("index.html"), width)
                self.assertEqual(errors, [])
                ctx.close()

    def check_page(self, page, url, width):
        page.goto(url, wait_until="load")
        page.evaluate("document.fonts.ready")
        html_lang = page.get_attribute("html", "lang")
        links = page.query_selector_all("nav.lang a")
        self.assertEqual(len(links), 4)
        current = []
        for link, (lang, name), flag in zip(links, LANGS, FLAGS):
            self.assertEqual(link.get_attribute("hreflang"), lang)
            self.assertEqual(link.get_attribute("lang"), lang)
            self.assertEqual(link.get_attribute("aria-label"), name)
            self.assertEqual(link.get_attribute("title"), name)
            self.assertEqual(link.inner_text().strip(), flag)
            if link.get_attribute("aria-current"):
                current.append(lang)
        self.assertEqual(current, [html_lang])
        # Top right, no horizontal scroll, 16 px gutters at least.
        box = links[-1].bounding_box()
        # (the right edge of the content column, which is the page's edge on a phone)
        inner = page.evaluate("(() => { const e = document.querySelector('.top-inner');"
                              "return e.getBoundingClientRect().right - parseFloat(getComputedStyle(e).paddingRight); })()")
        self.assertAlmostEqual(box["x"] + box["width"], inner, delta=1)
        self.assertLessEqual(box["x"] + box["width"], width - 16)
        self.assertLessEqual(box["y"], 20)
        self.assertLessEqual(page.evaluate("document.documentElement.scrollWidth"), width)
        # The flag font is loaded, and only for the regional-indicator letters.
        self.assertTrue(page.evaluate("(f) => document.fonts.check('16px \"Twemoji Country Flags\"', f)", FLAGS[0]))
        self.assertEqual(page.evaluate("[...document.fonts].find(f => f.family.includes('Twemoji')).unicodeRange"),
                         "U+1F1E6-1F1FF")
        loaded = page.evaluate("[...document.fonts].filter(f => f.family.includes('Twemoji') && f.status === 'loaded').length")
        self.assertEqual(loaded, 1)
        # Keyboard focus shows an outline.
        links[1].focus()
        page.keyboard.press("Shift+Tab")
        page.keyboard.press("Tab")
        outline = page.evaluate("(() => { const s = getComputedStyle(document.activeElement); "
                                "return [s.outlineStyle, s.outlineWidth]; })()")
        self.assertNotEqual(outline[0], "none")
        self.assertNotEqual(outline[1], "0px")
        # The footer's text uses its container's width.
        sizes = page.evaluate("(() => { const p = document.querySelector('.foot-inner p');"
                              "return [p.getBoundingClientRect().width, p.parentElement.clientWidth - "
                              "parseFloat(getComputedStyle(p.parentElement).paddingLeft) - "
                              "parseFloat(getComputedStyle(p.parentElement).paddingRight)]; })()")
        self.assertAlmostEqual(sizes[0], sizes[1], delta=1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
