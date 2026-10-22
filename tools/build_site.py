#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the project page and its diagrams in every language from one set of templates.

    python3 tools/build_site.py           write the pages, the diagrams and the sitemap
    python3 tools/build_site.py --check   fail if a file is stale or a translation is incomplete

The site has several pages, listed in PAGES below: each has a template,
site/src/<name>.html, and a folder in each language (the glossary is
glossario/ in Portuguese and glossary/ in English). Every language has every
page. With one text file per language, site/i18n/<code>.yaml, and the diagram
templates site/src/diagrams/<name>.svg, the script writes, each marked
"do not edit":

    site/<folder>/index.html      each page in Portuguese (pt-PT), the default
                                  language: site/index.html is the main page
    site/en/<folder>/index.html   each page in English
    site/de/<folder>/index.html   each page in German (decision P5H-3)
    site/img/diagrams/<name>-<layout>-<code>.svg   each diagram, per layout and language
    site/sitemap.xml              every page in every language, with its translations

In a template, {{ key }} inserts the text of a key as HTML, {{ key|text }}
inserts it escaped (for attributes and SVG text), and {{ page.<name> }} inserts
a value this script sets for each page (see page_values): its language, its
addresses, and page.to.<page>, the relative link from this page to another page
in the same language. A text in the YAML files may hold {{ page.<name> }} values
too, so that its links work from every page: href="{{ page.to.glossary }}#glossary-lora".
page.title, page.description and page.og_description are the page's own
meta.<page>.title, .description and .og_description texts, escaped (the last
falls back on the description). Text between {# and #} is a template comment
and is dropped. A line {% include <name> %} inserts the partial
site/src/partials/<name>.html (the head, header and footer every page shares).
Lines between {% if lang en %} and {% endif %}, each tag on a line of its own,
appear only on the pages of the languages listed (for a picture with English
text in it, say). Nested keys in the YAML files are joined with dots
(why.local.title).

A diagram template is an SVG file with the same placeholders, apart from plain
{{ key }}: its text is always escaped. Lines between {% if layout wide %} and
{% endif %} make a layout: a diagram is written once per layout it names (a
wide one for desktops and a narrow one for phones, say), or once if it names
none. Translations differ in length, so a <text> whose only content is a
placeholder gives the space it has: data-width (in SVG units) and, for
{{ key|wrap }}, data-lines, the most lines the text may wrap to (data-leading
sets the line height, 1.3 times the font size by default). The script wraps
the text at spaces (and at line breaks in the YAML), and fails if a line does
not fit, measuring it with the widest of the common fallback fonts
(DejaVu Sans, Liberation Sans, Segoe UI, FreeSans), as a diagram shown as an
image cannot use the page's fonts. The font size and weight come from the
font-size and font-weight attributes of the text or its parents.

Every key a page or a diagram uses must be in that language's file, and every
key in a language file must be used. Every template and partial must be used.
The two languages' versions of a page must link to the same external
addresses. Every link, image and address of a page that stays on the site must
lead to a page or a published file, and an "#id" in it to an id on that page
(the glossary ids differ by language). The HTML must nest correctly, each
diagram must be well-formed XML, and the site must hold no generated page or
diagram that nothing makes any more. Needs only PyYAML.
"""

from __future__ import annotations

import argparse
import html
import posixpath
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
SRC = SITE / "src"
PARTIALS = SRC / "partials"
DIAGRAMS = SRC / "diagrams"
DIAGRAM_OUT = SITE / "img" / "diagrams"
I18N = SITE / "i18n"
SITEMAP = SITE / "sitemap.xml"
# What .github/workflows/pages.yml leaves out of the published site: links must not lead there.
UNPUBLISHED = ("src", "i18n", "README.md")
# Where GitHub Pages publishes site/. Used for the canonical, hreflang, og:url and
# sitemap addresses, which must be absolute; links between the pages stay relative.
SITE_URL = "https://atalaia-project.link/"


@dataclass(frozen=True)
class Language:
    code: str  # the name of the YAML file and of the page.* keys
    html_lang: str  # <html lang> and hreflang
    og_locale: str
    path: str  # the language's folder relative to the site root: "" or "en/"
    # The language whose social preview image (img/og-<code>.jpg, with its title painted in) the
    # pages use: its own, or English's while it has none (P5H-3).
    og_image: str = ""

    @property
    def og_code(self) -> str:
        return self.og_image or self.code


# The first language is the default, served at the site root.
LANGUAGES = (
    Language("pt", "pt-PT", "pt_PT", ""),
    Language("en", "en", "en_GB", "en/"),
    Language("de", "de", "de_DE", "de/", og_image="en"),
)


@dataclass(frozen=True, eq=False)
class Page:
    name: str  # the template site/src/<name>.html, the meta.<name>.* texts and page.to.<name>
    folders: dict[str, str]  # language code -> the page's folder in that language's folder


# Every page, in every language. A folder is "" (the language's main page) or a
# slug in that language ending in "/". Keep the slugs stable: other sites link to them.
PAGES = (
    Page("index", {"pt": "", "en": "", "de": ""}),
    Page("modes", {"pt": "modos/", "en": "modes/", "de": "modi/"}),
    Page("radio", {"pt": "radio/", "en": "radio/", "de": "funk/"}),
    Page("roadmap", {"pt": "roadmap/", "en": "roadmap/", "de": "roadmap/"}),
    Page("glossary", {"pt": "glossario/", "en": "glossary/", "de": "glossar/"}),
)

# page.* values that come from the page's meta.<page>.* texts: value -> (key, fallback key).
META_VALUES = {
    "page.title": ("title", None),
    "page.description": ("description", None),
    "page.og_description": ("og_description", "description"),
}

# The licence header of every generated page.
# REUSE-IgnoreStart
SPDX_LINES = ("SPDX-FileCopyrightText: 2026 The Atalaia contributors",
              "SPDX-License-Identifier: CC-BY-SA-4.0")
# REUSE-IgnoreEnd

# A comment on lines of its own goes with its indentation and line break.
COMMENT_LINES = re.compile(r"^[ \t]*\{#(?:(?!#\}).)*#\}[ \t]*\n", re.S | re.M)
COMMENT = re.compile(r"\{#(?:(?!#\}).)*#\}", re.S)
# {% include name %} on a line of its own; partials do not include others.
INCLUDE = re.compile(r"^[ \t]*\{%\s*include\s+([a-z0-9_-]+)\s*%\}[ \t]*\n", re.M)
# {% if lang pt en %} ... {% endif %}, each tag on a line of its own; blocks do not nest.
IF_LANG = re.compile(r"^[ \t]*\{%\s*if\s+lang\s+([a-z ]+?)\s*%\}[ \t]*\n(.*?)^[ \t]*\{%\s*endif\s*%\}[ \t]*\n",
                     re.S | re.M)
# {% if layout wide %} ... {% endif %}, in diagram templates only; blocks do not nest.
IF_LAYOUT = re.compile(r"^[ \t]*\{%\s*if\s+layout\s+([a-z ]+?)\s*%\}[ \t]*\n(.*?)^[ \t]*\{%\s*endif\s*%\}[ \t]*\n",
                       re.S | re.M)
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*(?:\|\s*(text|wrap)\s*)?\}\}")
# A <text> element whose only content is a placeholder: its text is measured.
TEXT_PLACEHOLDER = re.compile(
    r"(<text\b[^>]*?)\s*>\s*\{\{\s*([A-Za-z0-9_.]+)\s*(?:\|\s*(text|wrap)\s*)?\}\}\s*</text>")
SCHEME = re.compile(r"[a-z][a-z0-9+.-]*:", re.I)
SVG_NS = "http://www.w3.org/2000/svg"
DATA_ATTRIBUTES = ("data-key", "data-filter", "data-width", "data-lines", "data-leading")

# Advance widths in hundredths of an em, the widest of DejaVu Sans, Liberation
# Sans (Arial's metrics), Segoe UI and FreeSans as Chromium measures them, for
# the characters of WIDTH_CHARS; regular (400) and bold (600 and 700) weights.
# A letter with an accent is as wide as the letter; anything else counts as 1 em.
WIDTH_CHARS = "".join(chr(c) for c in range(32, 127)) + "·–—→×€«»“”’…≈±"
WIDTH_REGULAR = (
    "32 40 46 84 64 95 80 27 39 39 50 84 32 40 32 39 64 64 64 64 64 64 64 64 64 64 34 34 84 84 84 56 102 68 69 72"
    " 77 67 61 78 75 29 53 67 56 90 75 79 67 79 72 67 63 73 68 99 69 68 69 39 38 39 84 56 50 61 63 55 63 62 35 63"
    " 63 28 28 58 28 97 63 61 63 63 41 52 39 63 59 82 59 59 52 64 34 64 84 33 56 100 100 84 65 61 61 52 52 32 100"
    " 84 84")
WIDTH_BOLD = (
    "35 46 52 84 70 100 87 31 46 46 52 84 38 42 38 44 70 70 70 70 70 70 70 70 70 70 40 40 84 84 84 61 100 77 76 73"
    " 83 68 68 82 84 37 57 77 64 100 84 85 73 85 77 72 68 81 77 110 77 72 73 46 44 46 84 56 50 67 72 59 72 68 44 72"
    " 71 34 34 67 34 104 71 69 72 72 49 60 48 71 65 92 65 65 58 71 37 71 84 38 56 100 100 84 70 65 65 66 66 38 100"
    " 84 84")
WIDTHS = {weight: dict(zip(WIDTH_CHARS, (int(w) / 100 for w in table.split())))
          for weight, table in (("regular", WIDTH_REGULAR), ("bold", WIDTH_BOLD))}
ET.register_namespace("", SVG_NS)  # write <svg xmlns=...>, not <ns0:svg>
VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                 "source", "track", "wbr"}


class SiteError(Exception):
    pass


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix() if path.is_relative_to(REPO) else path.as_posix()


def folder(page: Page, lang: Language) -> str:
    """The page's folder relative to the site root: "", "en/", "glossario/", "en/glossary/"."""
    return lang.path + page.folders[lang.code]


def output_path(page: Page, lang: Language) -> Path:
    return SITE / folder(page, lang) / "index.html"


def template_path(page: Page) -> Path:
    return SRC / f"{page.name}.html"


def relative(source: str, target: str) -> str:
    """The relative link from one page's folder to another's: "./", "../", "glossario/"..."""
    link = posixpath.relpath(target or ".", source or ".")
    return "./" if link == "." else link + "/"


def check_page_table() -> None:
    """Fails unless every page has one folder per language, and no two pages share a folder."""
    codes = sorted(lang.code for lang in LANGUAGES)
    names: set[str] = set()
    folders: dict[str, str] = {}
    for page in PAGES:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", page.name) or page.name in names:
            raise SiteError(f"tools/build_site.py: page names must be unique lowercase words: {page.name!r}")
        names.add(page.name)
        if sorted(page.folders) != codes:
            raise SiteError(f"tools/build_site.py: the {page.name} page has folders for "
                            f"{', '.join(sorted(page.folders)) or 'no language'}; every page needs one "
                            f"for each language: {', '.join(codes)}")
        for lang in LANGUAGES:
            slug = page.folders[lang.code]
            if slug and not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*/", slug):
                raise SiteError(f"tools/build_site.py: the {page.name} page's {lang.code} folder {slug!r} "
                                f"must be empty or a lowercase ASCII slug ending in /")
            where = folder(page, lang)
            if where in folders:
                raise SiteError(f"tools/build_site.py: the {page.name} and {folders[where]} pages both "
                                f"live in /{where}")
            folders[where] = page.name
        if not template_path(page).is_file():
            raise SiteError(f"{rel(template_path(page))} is missing: every page in PAGES needs a template")
    unknown = sorted(path for path in SRC.glob("*.html") if path.stem not in names)
    if unknown:
        raise SiteError("these templates are not in the page table (PAGES in tools/build_site.py); "
                        "add them, or delete them:" + "".join(f"\n  {rel(path)}" for path in unknown))


def flatten(data: Any, prefix: str, path: Path) -> dict[str, str]:
    if not isinstance(data, dict):
        raise SiteError(f"{rel(path)}: {prefix or 'the file'} must be a mapping")
    flat: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_]+", key):
            raise SiteError(f"{rel(path)}: bad key {key!r} under {prefix or 'the top level'}")
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(flatten(value, name, path))
        elif isinstance(value, str):
            flat[name] = value.strip()
        else:
            raise SiteError(f"{rel(path)}: {name} must be text, not {type(value).__name__}")
    return flat


def load_texts(lang: Language) -> dict[str, str]:
    path = I18N / f"{lang.code}.yaml"
    if not path.exists():
        raise SiteError(f"{rel(path)} is missing")
    texts = flatten(yaml.safe_load(path.read_text(encoding="utf-8")) or {}, "", path)
    reserved = sorted(k for k in texts if k.split(".")[0] == "page")
    if reserved:
        raise SiteError(f"{rel(path)}: page.* keys are set by the script: {', '.join(reserved)}")
    return texts


def language_values(lang: Language) -> dict[str, str]:
    """The page.* values that depend only on the language: all that a diagram may use."""
    return {
        "page.lang": lang.html_lang,
        "page.code": lang.code,  # the language's short code, as in file names (lora-wide-en.svg)
        "page.og_locale": lang.og_locale,
        "page.og_locale_alternate": ",".join(o.og_locale for o in LANGUAGES if o != lang),
    }


def meta_keys(page: Page, used: set[str], texts: dict[str, str]) -> set[str]:
    """The meta.<page>.* keys behind the page.title, page.description... values a template uses."""
    keys = set()
    for value in used & META_VALUES.keys():
        key, fallback = META_VALUES[value]
        if fallback and f"meta.{page.name}.{key}" not in texts:
            key = fallback
        keys.add(f"meta.{page.name}.{key}")
    return keys


def fill(value: str, values: dict[str, str], key: str, file_name: str) -> str:
    """Puts the page.* values into a text from a language file; a text may hold no other placeholder."""

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            what = "unknown page value" if name.startswith("page.") else "placeholder"
            raise SiteError(f"{file_name}: {key} holds the {what} {{{{ {name} }}}}; "
                            f"a text may hold only page.* values")
        return values[name]

    return PLACEHOLDER.sub(substitute, value)


def page_values(page: Page, lang: Language, texts: dict[str, str], file_name: str) -> dict[str, str]:
    """The page.* values of one page in one language: language, relative paths and absolute URLs."""
    here = folder(page, lang)
    values = language_values(lang) | {
        "page.name": page.name,
        "page.root": "../" * here.count("/"),
        "page.url.self": SITE_URL + here,
        "page.og_image": f"{SITE_URL}img/og-{lang.og_code}.jpg",
    }
    for other in LANGUAGES:
        # The same page in each language, for hreflang and the language switcher.
        values[f"page.url.{other.code}"] = SITE_URL + folder(page, other)
        values[f"page.href.{other.code}"] = relative(here, folder(page, other))
        values[f"page.current.{other.code}"] = ' aria-current="page"' if other == lang else ""
    for target in PAGES:
        values[f"page.to.{target.name}"] = relative(here, folder(target, lang))
        values[f"page.nav.{target.name}"] = ' aria-current="page"' if target is page else ""
    for value, (key, fallback) in META_VALUES.items():
        name = f"meta.{page.name}.{key}"
        if name not in texts and fallback:
            name = f"meta.{page.name}.{fallback}"
        if name in texts:
            values[value] = html.escape(fill(texts[name], values, name, file_name), quote=True)
    return values


def check_nesting(text: str, where: str) -> None:
    """Fails if the HTML closes an element that is not open, or leaves one open."""

    class Nesting(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.stack: list[tuple[str, int]] = []

        def handle_starttag(self, tag: str, attrs: Any) -> None:
            if tag not in VOID_ELEMENTS:
                self.stack.append((tag, self.getpos()[0]))

        def handle_endtag(self, tag: str) -> None:
            line = self.getpos()[0]
            if not self.stack or self.stack[-1][0] != tag:
                open_tag = f"<{self.stack[-1][0]}> from line {self.stack[-1][1]}" if self.stack else "nothing"
                raise SiteError(f"{where}, line {line}: </{tag}> closes {open_tag}")
            self.stack.pop()

    parser = Nesting()
    parser.feed(text)
    parser.close()
    if parser.stack:
        tag, line = parser.stack[-1]
        raise SiteError(f"{where}, line {line}: <{tag}> is never closed")


class Links(HTMLParser):
    """Collects a page's ids, its external links and every address it uses (links, images, og:*)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.external: set[str] = set()  # <a> links to other sites
        self.ids: set[str] = set()
        self.addresses: list[tuple[int, str]] = []  # (line, address)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        attributes = {name: value or "" for name, value in attrs}
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        line = self.getpos()[0]
        found = []
        if tag in ("a", "link") and "href" in attributes:
            found.append(attributes["href"])
        if tag in ("img", "script", "iframe", "source") and "src" in attributes:
            found.append(attributes["src"])
        if tag in ("img", "source") and attributes.get("srcset"):
            found += [part.split()[0] for part in attributes["srcset"].split(",") if part.strip()]
        if tag == "meta" and attributes.get("property") in ("og:url", "og:image"):
            found.append(attributes.get("content", ""))
        for address in found:
            self.addresses.append((line, address))
            if tag == "a" and SCHEME.match(address) and not address.startswith(SITE_URL):
                self.external.add(address)


def resolve(address: str, here: str) -> tuple[str, str | None]:
    """The site file an address on the page in folder `here` leads to, and its #id (None if it has none).

    Returns ("", None) for an address on another site; raises SiteError(reason) when it cannot work."""
    if address.startswith(SITE_URL):
        here, address = "", address[len(SITE_URL):]
    elif SCHEME.match(address):
        return "", None
    elif address.startswith("/"):
        raise SiteError("starts with /, which leaves the project's folder on GitHub Pages; use a relative link")
    path, hash_sign, fragment = address.partition("#")
    path = path.partition("?")[0]
    if not path:
        target = here + "index.html"
    else:
        joined = posixpath.normpath(posixpath.join(here or ".", path))
        if joined == ".." or joined.startswith("../"):
            raise SiteError("leads outside the site")
        if path.endswith("/") or joined == ".":
            target = ("" if joined == "." else joined + "/") + "index.html"
        else:
            target = joined
    return target, (fragment if hash_sign else None)


def check_addresses(rendered: dict[str, tuple[Links, str, str]], generated: set[str]) -> None:
    """Fails unless every address that stays on the site leads to a page or a published file,
    and every #id to an id on that page. rendered maps each page's site path to its links,
    its folder and how to name it in a message; generated holds the site paths of the other files
    this build writes (the diagrams), which count as published before they are written."""
    problems = []
    for path, (links, here, where) in rendered.items():
        bad = []
        for line, address in links.addresses:
            try:
                target, fragment = resolve(address, here)
            except SiteError as exc:
                bad.append(f"line {line}: {address} {exc}")
                continue
            if not target:
                continue
            if target in rendered:
                if fragment and fragment not in rendered[target][0].ids:
                    bad.append(f"line {line}: {address} leads to site/{target}, which has no id {fragment}")
                continue
            if not target.endswith("index.html") and f"{target}/index.html" in rendered:
                bad.append(f"line {line}: {address} leads to a page's folder; end it with /")
            elif target.split("/")[0] in UNPUBLISHED or not ((SITE / target).is_file() or target in generated):
                bad.append(f"line {line}: {address} leads to site/{target}, which is not a page "
                           f"or a published file")
            elif fragment:
                bad.append(f"line {line}: {address} has #{fragment}, but site/{target} is not a page")
        if bad:
            problems.append(f"{where} has addresses that lead nowhere:" + "".join(f"\n  {b}" for b in bad))
    if problems:
        raise SiteError("\n".join(problems))


def render(template: str, texts: dict[str, str], values: dict[str, str], source: Path, file_name: str) -> str:
    def substitute(match: re.Match[str]) -> str:
        key, escape = match.group(1), match.group(2)
        if key.startswith("page."):
            if key not in values:
                raise SiteError(f"{rel(source)}: unknown page value {key}")
            return values[key]
        if escape == "wrap":
            raise SiteError(f"{rel(source)}: {{{{ {key}|wrap }}}} works only in a diagram")
        value = fill(texts[key], values, key, file_name)  # every key is known to exist: see build()
        return html.escape(value, quote=True) if escape else value

    body = PLACEHOLDER.sub(substitute, template)
    if "{{" in body or "}}" in body:
        leftover = next(line for line in body.splitlines() if "{{" in line or "}}" in line)
        raise SiteError(f"{file_name}: an unreadable placeholder is left: {leftover.strip()}")
    header = "\n".join((
        "<!doctype html>",
        "<!--",
        *SPDX_LINES,
        "",
        f"Generated by tools/build_site.py from {rel(source)} and {file_name}. Do not edit.",
        "-->",
    ))
    return header + "\n" + body


def strip_comments(text: str, path: Path) -> str:
    text = COMMENT.sub("", COMMENT_LINES.sub("", text.replace("\r\n", "\n")))
    if "{#" in text or "#}" in text:
        raise SiteError(f"{rel(path)}: a template comment is not closed, or is nested")
    return text


def include(template: str, partials: dict[str, str], path: Path, included: set[str]) -> str:
    """Puts the partials into a page template, in place of its {% include name %} lines."""

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in partials:
            raise SiteError(f"{rel(path)}: {{% include {name} %}} names no partial: "
                            f"{rel(PARTIALS / (name + '.html'))} is missing")
        included.add(name)
        return partials[name]

    return INCLUDE.sub(substitute, template)


def only_for(template: str, blocks: re.Pattern[str], name: str) -> str:
    """Keeps the {% if ... %} blocks of one kind that list name, and drops the others."""
    return blocks.sub(lambda m: m.group(2) if name in m.group(1).split() else "", template)


def layouts(template: str) -> list[str]:
    """The layouts a diagram template names, in order; [""] when it names none."""
    names = [name for m in IF_LAYOUT.finditer(template) for name in m.group(1).split()]
    return list(dict.fromkeys(names)) or [""]


def diagram_path(source: Path, layout: str, lang: Language) -> Path:
    return DIAGRAM_OUT / ("-".join(part for part in (source.stem, layout, lang.code) if part) + ".svg")


def text_width(text: str, size: float, bold: bool) -> float:
    """The width of one line of text, in SVG units, in the widest fallback font."""
    table = WIDTHS["bold" if bold else "regular"]
    width = 0.0
    for char in text.replace(" ", " "):
        width += table.get(char, table.get(unicodedata.normalize("NFD", char)[0], 1.0))
    return width * size


def wrap(text: str, width: float, size: float, bold: bool) -> list[str]:
    """Breaks text into lines at spaces, and at its own line breaks."""
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            if not word:
                continue
            longer = f"{line} {word}" if line else word
            if line and text_width(longer, size, bold) > width:
                lines.append(line)
                line = word
            else:
                line = longer
        lines.append(line)
    return lines


def fit_text(element: ET.Element, size: float, weight: str, where: str) -> None:
    """Checks that a measured <text> fits its data-width; for |wrap, breaks it into <tspan> lines."""
    key = element.get("data-key")
    if element.get("data-width") is None:
        raise SiteError(f"{where}: the <text> of {key} needs data-width, the room its text has")
    width = float(element.get("data-width", "0"))
    bold = weight in ("bold", "bolder") or (weight.isdigit() and int(weight) >= 600)
    text = element.text or ""
    if element.get("data-filter") == "wrap":
        lines = wrap(text, width, size, bold)
        room = int(element.get("data-lines", "1"))
    elif "\n" in text:
        raise SiteError(f"{where}: {key} has line breaks; its <text> needs {{{{ {key}|wrap }}}}")
    else:
        lines, room = [text], 1
    for number, line in enumerate(lines, 1):
        needed = text_width(line, size, bold)
        if needed > width:
            which = f"line {number}, " if len(lines) > 1 else ""
            raise SiteError(f"{where}: {key} does not fit: {which}\"{line}\" needs about {needed:.0f} units "
                            f"and its <text> has {width:g}")
    if len(lines) > room:
        raise SiteError(f"{where}: {key} needs {len(lines)} lines and its <text> has room for {room}")
    if len(lines) == 1:
        element.text = lines[0]
        return
    leading = element.get("data-leading") or f"{size * 1.3:g}"
    element.text = None
    for number, line in enumerate(lines):
        tspan = ET.SubElement(element, f"{{{SVG_NS}}}tspan", {"x": element.get("x", "0")})
        if number:
            tspan.set("dy", leading)
        tspan.text = line


def render_diagram(template: str, source: Path, texts: dict[str, str], lang: Language, out: Path,
                   file_name: str) -> str:
    where = f"{rel(out)} (from {rel(source)} and {file_name})"
    values = language_values(lang)

    def mark(match: re.Match[str]) -> str:
        attributes, key, how = match.group(1), match.group(2), match.group(3)
        if key.startswith("page.") or not how:
            return match.group(0)  # filled in, or refused, below
        value = html.escape(fill(texts[key], values, key, file_name), quote=True)  # every key exists: see build()
        return f'{attributes} data-key="{key}" data-filter="{how}">{value}</text>'

    def substitute(match: re.Match[str]) -> str:
        key, how = match.group(1), match.group(2)
        if key.startswith("page."):
            if key not in values:
                raise SiteError(f"{rel(source)}: unknown page value {key} (a diagram may use only "
                                f"{', '.join(sorted(values))})")
            return values[key]
        if how == "wrap":
            raise SiteError(f"{rel(source)}: {{{{ {key}|wrap }}}} must be the only content of a <text>")
        if how != "text":
            raise SiteError(f"{rel(source)}: a diagram's text is not HTML: write {{{{ {key}|text }}}}")
        return html.escape(fill(texts[key], values, key, file_name), quote=True)

    body = PLACEHOLDER.sub(substitute, TEXT_PLACEHOLDER.sub(mark, template))
    if "{{" in body or "}}" in body:
        leftover = next(line for line in body.splitlines() if "{{" in line or "}}" in line)
        raise SiteError(f"{where}: an unreadable placeholder is left: {leftover.strip()}")
    try:
        root = ET.fromstring(body, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    except ET.ParseError as exc:
        raise SiteError(f"{where}: not well-formed XML: {exc}") from None
    if root.tag != f"{{{SVG_NS}}}svg":
        raise SiteError(f'{where}: the root element must be <svg xmlns="{SVG_NS}">')

    def walk(element: ET.Element, size: str, weight: str) -> None:
        size = element.get("font-size", size)
        weight = element.get("font-weight", weight)
        if element.tag == f"{{{SVG_NS}}}text" and element.get("data-key"):
            if len(element):
                raise SiteError(f"{where}: the <text> of {element.get('data-key')} must hold only its placeholder")
            try:
                units = float(size.removesuffix("px"))
            except ValueError:
                raise SiteError(f"{where}: font-size {size!r} is not a number") from None
            fit_text(element, units, weight, where)
        for child in element:
            walk(child, size, weight)
        for name in DATA_ATTRIBUTES:
            element.attrib.pop(name, None)

    walk(root, "16", "400")
    header = "\n".join((
        "<!--",
        *SPDX_LINES,
        "",
        f"Generated by tools/build_site.py from {rel(source)} and {file_name}. Do not edit.",
        "-->",
    ))
    return header + "\n" + ET.tostring(root, encoding="unicode") + "\n"


def sitemap() -> str:
    """Every page in every language, each with the addresses of its translations."""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!--",
        *SPDX_LINES,
        "",
        "Generated by tools/build_site.py from its page table (PAGES). Do not edit.",
        "-->",
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    for page in PAGES:
        for lang in LANGUAGES:
            lines += ["  <url>", f"    <loc>{SITE_URL}{folder(page, lang)}</loc>"]
            lines += [f'    <xhtml:link rel="alternate" hreflang="{other.html_lang}" href="{SITE_URL}{folder(page, other)}"/>'
                      for other in LANGUAGES]
            lines += [f'    <xhtml:link rel="alternate" hreflang="x-default" '
                      f'href="{SITE_URL}{folder(page, LANGUAGES[0])}"/>', "  </url>"]
    lines.append("</urlset>")
    text = "\n".join(lines) + "\n"
    ET.fromstring(text.encode("utf-8"))  # well-formed, or a bug here
    return text


def build() -> dict[Path, str]:
    check_page_table()
    partial_files = sorted(PARTIALS.glob("*.html")) if PARTIALS.is_dir() else []
    partials = {path.stem: strip_comments(path.read_text(encoding="utf-8"), path) for path in partial_files}
    for name, text in partials.items():
        if INCLUDE.search(text):
            raise SiteError(f"{rel(PARTIALS / (name + '.html'))}: a partial cannot include another")
    included: set[str] = set()
    templates = {}
    for page in PAGES:
        path = template_path(page)
        templates[page.name] = include(strip_comments(path.read_text(encoding="utf-8"), path), partials, path,
                                       included)
    unused = sorted(set(partials) - included)
    if unused:
        raise SiteError("no page includes these partials; include them, or delete them:"
                        + "".join(f"\n  {rel(PARTIALS / (name + '.html'))}" for name in unused))
    sources = sorted(DIAGRAMS.glob("*.svg")) if DIAGRAMS.is_dir() else []
    diagrams = {source: strip_comments(source.read_text(encoding="utf-8"), source) for source in sources}
    codes = {lang.code for lang in LANGUAGES}
    for path, text in ((template_path(page), templates[page.name]) for page in PAGES):
        for match in IF_LANG.finditer(text):
            unknown = sorted(set(match.group(1).split()) - codes)
            if unknown:
                raise SiteError(f"{rel(path)}: {{% if lang %}} names an unknown language: {', '.join(unknown)}")
    for path, text in diagrams.items():
        for match in IF_LANG.finditer(text):
            unknown = sorted(set(match.group(1).split()) - codes)
            if unknown:
                raise SiteError(f"{rel(path)}: {{% if lang %}} names an unknown language: {', '.join(unknown)}")

    problems = []
    all_texts: dict[Language, dict[str, str]] = {}
    page_templates: dict[tuple[str, Language], str] = {}
    variants: dict[Language, list[tuple[Path, Path, str]]] = {}
    users = "site/src/*.html, site/src/partials/*.html" + (f" or a diagram in {rel(DIAGRAMS)}" if diagrams else "")
    for lang in LANGUAGES:
        file_name = rel(I18N / f"{lang.code}.yaml")
        texts = load_texts(lang)
        all_texts[lang] = texts
        used: set[str] = set()
        missing: dict[str, list[str]] = {}  # key -> the templates that use it
        for page in PAGES:
            path = template_path(page)
            page_template = only_for(templates[page.name], IF_LANG, lang.code)
            if "{%" in page_template or "%}" in page_template:
                raise SiteError(f"{rel(path)}: an {{% if lang %}} block is not closed, nested, or not on "
                                f"lines of its own, or an {{% include %}} is not on a line of its own")
            page_templates[page.name, lang] = page_template
            names = {m.group(1) for m in PLACEHOLDER.finditer(page_template)}
            keys = {name for name in names if not name.startswith("page.")} | meta_keys(page, names, texts)
            for key in keys - texts.keys():
                missing.setdefault(key, []).append(rel(path))
            used |= keys
        variants[lang] = []
        for source, text in diagrams.items():
            for layout in layouts(text):
                variant = only_for(only_for(text, IF_LANG, lang.code), IF_LAYOUT, layout)
                if "{%" in variant or "%}" in variant:
                    raise SiteError(f"{rel(source)}: an {{% if %}} block is not closed, nested, "
                                    f"or not on lines of its own")
                variants[lang].append((diagram_path(source, layout, lang), source, variant))
                keys = {m.group(1) for m in PLACEHOLDER.finditer(variant) if not m.group(1).startswith("page.")}
                for key in keys - texts.keys():
                    missing.setdefault(key, []).append(rel(source))
                used |= keys
        for key, where in sorted(missing.items()):
            where = list(dict.fromkeys(where))
            problems.append(f"{file_name}: {key} is missing (used by "
                            f"{'every page' if len(where) == len(PAGES) else ', '.join(where)})")
        for key in sorted(texts.keys() - used):
            problems.append(f"{file_name}: {key} is not used by {users}")
    if problems:
        raise SiteError("\n".join(problems))

    pages: dict[Path, str] = {}
    rendered: dict[str, tuple[Links, str, str]] = {}
    external: dict[tuple[str, Language], set[str]] = {}
    for page in PAGES:
        for lang in LANGUAGES:
            file_name = rel(I18N / f"{lang.code}.yaml")
            values = page_values(page, lang, all_texts[lang], file_name)
            text = render(page_templates[page.name, lang], all_texts[lang], values, template_path(page), file_name)
            out = output_path(page, lang)
            where = f"{rel(out)} (from {rel(template_path(page))} and {file_name})"
            check_nesting(text, where)
            parser = Links()
            parser.feed(text)
            parser.close()
            rendered[out.relative_to(SITE).as_posix()] = (parser, folder(page, lang), where)
            external[page.name, lang] = parser.external
            pages[out] = text
    check_addresses(rendered, {out.relative_to(SITE).as_posix() for lang in LANGUAGES for out, _, _ in variants[lang]})

    first = LANGUAGES[0]
    for page in PAGES:
        for lang in LANGUAGES[1:]:
            if external[page.name, lang] != external[page.name, first]:
                only = sorted(external[page.name, first] - external[page.name, lang])
                extra = sorted(external[page.name, lang] - external[page.name, first])
                raise SiteError(
                    f"the {lang.code} and {first.code} {page.name} pages link to different places"
                    + "".join(f"\n  only in {first.code}: {u}" for u in only)
                    + "".join(f"\n  only in {lang.code}: {u}" for u in extra))

    for lang in LANGUAGES:
        file_name = rel(I18N / f"{lang.code}.yaml")
        for out, source, variant in variants[lang]:
            pages[out] = render_diagram(variant, source, all_texts[lang], lang, out, file_name)
    pages[SITEMAP] = sitemap()

    strays = sorted(path for path in DIAGRAM_OUT.glob("*.svg") if path not in pages) if DIAGRAM_OUT.is_dir() else []
    if strays:
        raise SiteError("no diagram template makes these files; delete them, or restore their template:"
                        + "".join(f"\n  {rel(path)}" for path in strays))
    strays = sorted(path for path in SITE.rglob("*.html")
                    if path not in pages and path.relative_to(SITE).parts[0] not in UNPUBLISHED)
    if strays:
        raise SiteError("no page in the page table (PAGES in tools/build_site.py) makes these files; "
                        "delete them, or restore their page:" + "".join(f"\n  {rel(path)}" for path in strays))
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="fail if a file is stale or a translation is incomplete")
    args = parser.parse_args(argv)
    try:
        pages = build()
    except (SiteError, yaml.YAMLError, OSError) as exc:
        print(f"build_site: {exc}", file=sys.stderr)
        return 1

    stale = []
    for path, text in pages.items():
        current = path.read_text(encoding="utf-8").replace("\r\n", "\n") if path.exists() else None
        if current == text:
            continue
        stale.append(rel(path))
        if not args.check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")

    if args.check and stale:
        print("build_site: these files are out of date; run python3 tools/build_site.py:", file=sys.stderr)
        for p in stale:
            print(f"  {p}", file=sys.stderr)
        return 1
    for p in stale:
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
