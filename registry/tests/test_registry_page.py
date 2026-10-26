# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The registry's public page (tools/registry_page.py, texts in registry/template/site/page.yaml).

Rendered from the sample index (registry/schema/examples/index.json) and from an index whose mode
names, descriptions, authors, versions and addresses are hostile: nothing from index.json may reach
the page as markup. Also: the empty registry shows its empty state, every language has the same
texts, the project page and the registry's documents are linked, and index.json is left alone.

    python3 -m unittest discover -s registry/tests -v
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
TEMPLATE = REPO / "registry" / "template"
SAMPLE_INDEX = json.loads((REPO / "registry" / "schema" / "examples" / "index.json").read_text(encoding="utf-8"))

_spec = importlib.util.spec_from_file_location("registry_page", REPO / "tools" / "registry_page.py")
rp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rp)

HOSTILE = '<script>alert(1)</script>"><img src=x onerror=alert(2)>&amp;'


class Collector(HTMLParser):
    """Every tag and attribute of a page, as a browser would see them."""

    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attrs: list[tuple[str, str, str]] = []
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.extend((tag, k, v or "") for k, v in attrs)

    def handle_data(self, data):
        self.text.append(data)


def parse(page: str) -> Collector:
    collector = Collector()
    collector.feed(page)
    return collector


def hostile_index() -> dict:
    index = copy.deepcopy(SAMPLE_INDEX)
    mode = index["modes"][0]
    mode["id"] = "org.example." + HOSTILE
    mode["name"] = HOSTILE
    mode["author"] = HOSTILE
    mode["description"] = HOSTILE
    version = mode["versions"][0]
    version["version"] = HOSTILE
    version["license"] = HOSTILE
    version["kind"] = HOSTILE
    version["url"] = 'javascript:alert(3)//"><script>alert(4)</script>'
    second = copy.deepcopy(version)
    second["url"] = 'https://example.org/x.tar"><script>alert(5)</script>'
    third = copy.deepcopy(version)
    third["url"] = "../../etc/passwd"
    fourth = copy.deepcopy(version)
    fourth["url"] = "https://example.org/ok.tar"
    fourth["verified"] = "yes"
    mode["versions"] += [second, third, fourth]
    index["modes"].append({"id": "x.y", "name": 5, "author": None, "versions": "nope"})
    index["modes"].append("not even an object")
    return index


class PageTests(unittest.TestCase):
    def setUp(self):
        self.data = yaml.safe_load((TEMPLATE / "site" / "page.yaml").read_text(encoding="utf-8"))

    def render(self, index: dict, lang: str = "en") -> str:
        return rp.render(index, self.data, lang)

    def test_every_language_has_the_same_texts(self):
        languages = self.data["languages"]
        self.assertEqual(set(languages), set(rp.LANGUAGES))
        for lang in rp.LANGUAGES:
            with self.subTest(lang=lang):
                self.assertEqual(set(languages[lang]), set(languages["en"]))
                self.assertTrue(all(isinstance(v, str) and v.strip() for v in languages[lang].values()))
                self.assertIn(lang, self.data["links"]["project"])

    def test_the_sample_index_is_listed(self):
        page = self.render(SAMPLE_INDEX)
        doc = parse(page)
        text = " ".join(doc.text)
        for expected in ("Relay", "Example Club", "org.example.relay", "1.2.0-rc.1", "MIT", "verified"):
            self.assertIn(expected, text)
        hrefs = [v for tag, k, v in doc.attrs if tag == "a" and k == "href"]
        self.assertIn("packages/org.example.relay-1.2.0-rc.1.tar", hrefs)
        self.assertIn("packages/org.example.relay-1.2.0-rc.1.tar.verified.json", hrefs)
        self.assertNotIn("<script", page.lower())
        self.assertNotIn("<script", "".join(doc.tags))
        self.assertNotIn("script", doc.tags)

    def test_the_empty_registry_says_be_the_first(self):
        empty = json.loads((TEMPLATE / "index.json").read_text(encoding="utf-8"))
        self.assertEqual(empty["modes"], [])
        for lang in rp.LANGUAGES:
            with self.subTest(lang=lang):
                page = self.render(empty, lang)
                self.assertIn(self.data["languages"][lang]["modes_empty"], page)
                self.assertNotIn("<table", page)

    def test_the_page_explains_and_links(self):
        page = self.render(SAMPLE_INDEX)
        hrefs = [v for tag, k, v in parse(page).attrs if tag == "a" and k == "href"]
        links = self.data["links"]
        for wanted in (links["contributing"], links["docs"], links["project"]["en"],
                       "https://vakaobr.github.io/atalaia-modes/index.json"):
            self.assertIn(wanted, hrefs)
        self.assertIn("[modes]", page)
        self.assertIn('index = "https://vakaobr.github.io/atalaia-modes/index.json"', page)
        for lang in rp.LANGUAGES:
            self.assertIn(links["project"][lang], self.render(SAMPLE_INDEX, lang))

    def test_hostile_registry_text_is_never_markup(self):
        for lang in rp.LANGUAGES:
            with self.subTest(lang=lang):
                page = self.render(hostile_index(), lang)
                doc = parse(page)
                # No tag or attribute the page's own template does not have.
                self.assertEqual(set(doc.tags) - {"html", "head", "meta", "title", "link", "style", "body", "a", "header",
                                                  "div", "nav", "span", "img", "main", "h1", "p", "section", "h2", "article",
                                                  "h3", "table", "thead", "tr", "th", "tbody", "td", "pre", "code",
                                                  "footer", "strong"}, set())
                self.assertNotIn("script", doc.tags)
                self.assertFalse([a for a in doc.attrs if a[1].startswith("on")], "an event handler attribute")
                self.assertFalse([a for a in doc.attrs if a[1] == "src" and not a[2].startswith("data:image/svg+xml")])
                self.assertNotIn("<script", page)
                self.assertNotIn("<img src=x", page)
                for tag, key, value in doc.attrs:
                    if tag == "a" and key == "href":
                        self.assertRegex(value, r"^(https://|packages/|\.\./packages/|\./|\.\./|#|pt/|de/|zh-tw/|\.\./(pt|de|zh-tw)/)")
                        self.assertNotRegex(value, r"^(javascript|data):")
                # The hostile text is there, as text.
                self.assertIn(HOSTILE, " ".join(doc.text))
                self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
                # Addresses that are not safe are not links: only the plain relative path and the https ones.
                self.assertNotIn("javascript:", page)
                self.assertNotIn("etc/passwd", page)
                self.assertNotIn("alert(5)</script>", page)
                self.assertEqual(len(re.findall(r"<article", page)), 2)

    def test_build_writes_four_pages_and_leaves_index_json_alone(self):
        tmp = Path(tempfile.mkdtemp(prefix="atalaia-registry-page-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        out = tmp / "_site"
        written = rp.build(TEMPLATE, out)
        self.assertEqual({p.relative_to(out).as_posix() for p in written},
                         {"index.html", "pt/index.html", "de/index.html", "zh-tw/index.html"})
        self.assertFalse((out / "index.json").exists())  # this step never touches it
        self.assertIn('lang="en"', (out / "index.html").read_text(encoding="utf-8"))
        self.assertIn('lang="pt-PT"', (out / "pt" / "index.html").read_text(encoding="utf-8"))
        # A page in a folder points to the packages and the other languages one level up.
        pt = rp.render(SAMPLE_INDEX, self.data, "pt")
        self.assertIn('href="../packages/org.example.relay-1.2.0-rc.1.tar"', pt)
        self.assertIn('href="../"', pt)
        self.assertIn('href="../pt/"', pt)


if __name__ == "__main__":
    unittest.main()
