#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Builds the project page in every language from one template.

    python3 tools/build_site.py           write the pages
    python3 tools/build_site.py --check   fail if a page is stale or a translation is incomplete

Reads the template site/src/index.html and one text file per language,
site/i18n/<code>.yaml, and writes, each marked "do not edit":

    site/index.html      Portuguese (pt-PT), the default page at the site root
    site/en/index.html   English

In the template, {{ key }} inserts the text of a key as HTML, {{ key|text }}
inserts it escaped (for attributes and SVG text), and {{ page.<name> }} inserts
a value this script sets for each page. Text between {# and #} is a template
comment and is dropped. Lines between {% if lang en %} and {% endif %}, each
tag on a line of its own, appear only on the pages of the languages listed
(for a picture with English text in it, say). Nested keys in the YAML files are
joined with dots (why.local.title).

Every key a page uses must be in that page's language file, and every key in a
language file must be used by its page. Both pages must also link to the same
external addresses, every "#id" link on a page must have its target on that
page (the glossary ids differ by language), and the HTML must nest correctly.
Needs only PyYAML.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
SITE = REPO / "site"
TEMPLATE = SITE / "src" / "index.html"
I18N = SITE / "i18n"
# Where GitHub Pages publishes site/. Used for the canonical, hreflang and
# og:url addresses, which must be absolute; links between the pages stay relative.
SITE_URL = "https://vakaobr.github.io/atalaia-project/"


@dataclass(frozen=True)
class Language:
    code: str  # the name of the YAML file and of the page.* keys
    html_lang: str  # <html lang> and hreflang
    og_locale: str
    path: str  # the page's folder relative to the site root: "" or "en/"


# The first language is the default, served at the site root.
LANGUAGES = (
    Language("pt", "pt-PT", "pt_PT", ""),
    Language("en", "en", "en_GB", "en/"),
)

# The licence header of every generated page.
# REUSE-IgnoreStart
SPDX_LINES = ("SPDX-FileCopyrightText: 2026 The Atalaia contributors",
              "SPDX-License-Identifier: CC-BY-SA-4.0")
# REUSE-IgnoreEnd

# A comment on lines of its own goes with its indentation and line break.
COMMENT_LINES = re.compile(r"^[ \t]*\{#(?:(?!#\}).)*#\}[ \t]*\n", re.S | re.M)
COMMENT = re.compile(r"\{#(?:(?!#\}).)*#\}", re.S)
# {% if lang pt en %} ... {% endif %}, each tag on a line of its own; blocks do not nest.
IF_LANG = re.compile(r"^[ \t]*\{%\s*if\s+lang\s+([a-z ]+?)\s*%\}[ \t]*\n(.*?)^[ \t]*\{%\s*endif\s*%\}[ \t]*\n",
                     re.S | re.M)
PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*(?:\|\s*(text)\s*)?\}\}")
VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                 "source", "track", "wbr"}


class SiteError(Exception):
    pass


def rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def output_path(lang: Language) -> Path:
    return SITE / lang.path / "index.html"


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


def page_values(lang: Language) -> dict[str, str]:
    """The page.* values: language, relative paths and absolute URLs for one page."""
    root = "../" * lang.path.count("/")
    values = {
        "page.lang": lang.html_lang,
        "page.og_locale": lang.og_locale,
        "page.og_locale_alternate": ",".join(o.og_locale for o in LANGUAGES if o != lang),
        "page.root": root,
        "page.url.self": SITE_URL + lang.path,
        "page.og_image": f"{SITE_URL}img/og-{lang.code}.jpg",
    }
    for other in LANGUAGES:
        values[f"page.url.{other.code}"] = SITE_URL + other.path
        values[f"page.href.{other.code}"] = "./" if other == lang else (root + other.path or "./")
        values[f"page.current.{other.code}"] = ' aria-current="page"' if other == lang else ""
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
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.external: set[str] = set()
        self.fragments: set[str] = set()  # targets of href="#..." links
        self.ids: set[str] = set()

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        attributes = dict(attrs)
        if attributes.get("id"):
            self.ids.add(attributes["id"])
        href = attributes.get("href") or ""
        if tag == "a" and re.match(r"[a-z]+:", href):
            self.external.add(href)
        elif tag == "a" and href.startswith("#"):
            self.fragments.add(href[1:])


def render(template: str, texts: dict[str, str], lang: Language, file_name: str) -> str:
    values = page_values(lang)

    def substitute(match: re.Match[str]) -> str:
        key, escape = match.group(1), match.group(2)
        if key.startswith("page."):
            if key not in values:
                raise SiteError(f"{rel(TEMPLATE)}: unknown page value {key}")
            return values[key]
        value = texts[key]  # every key is known to exist: see build()
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
        f"Generated by tools/build_site.py from {rel(TEMPLATE)} and {file_name}. Do not edit.",
        "-->",
    ))
    return header + "\n" + body


def build() -> dict[Path, str]:
    template = TEMPLATE.read_text(encoding="utf-8").replace("\r\n", "\n")
    template = COMMENT.sub("", COMMENT_LINES.sub("", template))
    if "{#" in template or "#}" in template:
        raise SiteError(f"{rel(TEMPLATE)}: a template comment is not closed, or is nested")
    codes = {lang.code for lang in LANGUAGES}
    for match in IF_LANG.finditer(template):
        unknown = sorted(set(match.group(1).split()) - codes)
        if unknown:
            raise SiteError(f"{rel(TEMPLATE)}: {{% if lang %}} names an unknown language: {', '.join(unknown)}")

    problems = []
    all_texts = {}
    templates = {}
    for lang in LANGUAGES:
        file_name = rel(I18N / f"{lang.code}.yaml")
        page_template = IF_LANG.sub(
            lambda m, code=lang.code: m.group(2) if code in m.group(1).split() else "", template)
        if "{%" in page_template or "%}" in page_template:
            raise SiteError(f"{rel(TEMPLATE)}: an {{% if lang %}} block is not closed, nested, "
                            f"or not on lines of its own")
        templates[lang] = page_template
        used = {m.group(1) for m in PLACEHOLDER.finditer(page_template)
                if not m.group(1).startswith("page.")}
        texts = load_texts(lang)
        all_texts[lang] = texts
        for key in sorted(used - texts.keys()):
            problems.append(f"{file_name}: {key} is missing")
        for key in sorted(texts.keys() - used):
            problems.append(f"{file_name}: {key} is not used by {rel(TEMPLATE)}")
    if problems:
        raise SiteError("\n".join(problems))

    pages = {}
    links = {}
    for lang in LANGUAGES:
        file_name = rel(I18N / f"{lang.code}.yaml")
        page = render(templates[lang], all_texts[lang], lang, file_name)
        out = output_path(lang)
        check_nesting(page, f"{rel(out)} (from {file_name})")
        parser = Links()
        parser.feed(page)
        missing = sorted(parser.fragments - parser.ids)
        if missing:
            raise SiteError(f"{rel(out)} (from {file_name}) links to ids it does not have: "
                            + ", ".join(f"#{m}" for m in missing))
        links[lang] = parser.external
        pages[out] = page

    first = LANGUAGES[0]
    for lang in LANGUAGES[1:]:
        if links[lang] != links[first]:
            only = sorted(links[first] - links[lang])
            extra = sorted(links[lang] - links[first])
            raise SiteError(
                f"the {lang.code} and {first.code} pages link to different places"
                + "".join(f"\n  only in {first.code}: {u}" for u in only)
                + "".join(f"\n  only in {lang.code}: {u}" for u in extra))
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="fail if a page is stale or a translation is incomplete")
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
        print("build_site: these pages are out of date; run python3 tools/build_site.py:", file=sys.stderr)
        for p in stale:
            print(f"  {p}", file=sys.stderr)
        return 1
    for p in stale:
        print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
