#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Checks every translated part of the project against English, in each one's own format.

    python3 tools/i18n_check.py                 check, print a table, warn about missing keys
    python3 tools/i18n_check.py --missing de    also list every key German lacks, per domain
    python3 tools/i18n_check.py --strict de     fail on a key German lacks (before calling it complete)

A language's id is its code in docs/translations/status.yaml ("de", "zh-tw"); file names carry it
as they can: zh-tw.json, zh-tw.yaml, strings_zh_tw.dart (the map zhTwStrings), BOX_LANG_ZH_TW.

Each domain keeps the format it was built with (decision P5R-11):

    site      site/i18n/<lang>.yaml                         (tools/build_site.py builds the pages)
    console   controller/console/src/i18n/<lang>.json       the GM console
    editor    simulator/atalaia_sim/editor/i18n/<lang>.json the mode editor
    app       app/lib/l10n/strings_<lang>.dart              the Flutter app ("-" as "_")
    box       firmware/esp32/main/box_text.c                the Field Box's screens (one column a language)
    server    server/atalaia_server/web/i18n.py, staff_i18n.py   the site server's pages
    modes     modes/*/mode.yaml (i18n.<lang>)               the built-in modes' names, read only for the table

The languages and their state are in docs/translations/status.yaml. For each domain a language
has, the check fails when it has a key English lacks, a placeholder English does not have (or
lacks one English has), or an empty text; a language whose status is "complete" must also have
every key English has. A language still being translated may lack keys: the GM console, the
editor and the app show English for them, the box shows English, and the check lists them as
warnings (decision P5H-2), so that new English and Portuguese texts never break CI. The project
page is the exception: tools/build_site.py requires every language's page to be complete
(decision P5-5). Needs only PyYAML.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

REPO = Path(__file__).resolve().parents[1]
BASE = "en"

# Placeholders per kind of file.
BRACES = re.compile(r"\{\w+\}")  # {team}
EDITOR_ARGS = re.compile(r"%\d|\{\w+\}")  # %1 (Blockly) and {name}
SITE_VALUES = re.compile(r"\{\{\s*[\w.]+\s*\}\}")  # {{ page.to.glossary }}
PRINTF = re.compile(r"%[-+ 0#]*\d*(?:\.\d+)?(?:l|ll|h)?[sdufx]")  # %s, %ld, %lu


@dataclass
class Domain:
    name: str
    placeholders: re.Pattern[str]
    tables: dict[str, dict[str, str]]  # language -> key -> text
    where: dict[str, str] = field(default_factory=dict)  # language -> file, for messages
    read_only: bool = False  # in the table only (the modes' names)
    # Missing keys are another tool's to judge: the project page's single-language parts
    # (tools/build_site.py, which requires each page complete).
    own_completeness: bool = False


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing: dict[tuple[str, str], list[str]] = field(default_factory=dict)  # (domain, lang) -> keys


def flatten(data: object, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            out.update(flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = data if isinstance(data, str) else json.dumps(data)
    return out


# ---- readers -------------------------------------------------------------------------------


def read_json_dir(root: Path, folder: str) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    tables, where = {}, {}
    for path in sorted((root / folder).glob("*.json")):
        tables[path.stem] = flatten(json.loads(path.read_text(encoding="utf-8")))
        where[path.stem] = rel(path, root)
    return tables, where


def read_site(root: Path) -> Domain:
    tables, where = {}, {}
    for path in sorted((root / "site" / "i18n").glob("*.yaml")):
        tables[path.stem] = flatten(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        where[path.stem] = rel(path, root)
    return Domain("site", SITE_VALUES, tables, where, own_completeness=True)


def dart_strings(text: str, name: str) -> dict[str, str]:
    """The const Map<String, String> called name: its keys and texts (adjacent literals joined)."""
    start = re.search(rf"\bconst\s+Map<String,\s*String>\s+{name}\s*=\s*\{{", text)
    if not start:
        raise ValueError(f"no const Map<String, String> {name}")
    i = start.end()
    out: dict[str, str] = {}
    parts: list[str] = []
    key: str | None = None
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
        elif text.startswith("//", i):
            i = text.index("\n", i) if "\n" in text[i:] else len(text)
        elif c in "'\"":
            j, buf = i + 1, []
            while text[j] != c:
                if text[j] == "\\":
                    nxt = text[j + 1]
                    buf.append({"n": "\n", "t": "\t"}.get(nxt, nxt))
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            parts.append("".join(buf))
            i = j + 1
        elif c == ":":
            key, parts = "".join(parts), []
            i += 1
        elif c in ",}":
            if key is not None:
                if key in out:
                    raise ValueError(f"{name}: {key} twice")
                out[key] = "".join(parts)
            key, parts = None, []
            if c == "}":
                return out
            i += 1
        else:
            raise ValueError(f"{name}: unexpected {c!r} at offset {i}")
    raise ValueError(f"{name}: not closed")


def read_app(root: Path) -> Domain:
    tables, where = {}, {}
    for path in sorted((root / "app" / "lib" / "l10n").glob("strings_*.dart")):
        stem = path.stem.removeprefix("strings_")  # zh_tw
        lang = stem.replace("_", "-")  # zh-tw
        first, *rest = stem.split("_")
        name = first + "".join(part.capitalize() for part in rest) + "Strings"  # zhTwStrings
        tables[lang] = dart_strings(path.read_text(encoding="utf-8"), name)
        where[lang] = rel(path, root)
    return Domain("app", BRACES, tables, where)


C_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')


def c_text(literal: str) -> str:
    raw = literal.encode("utf-8")
    return re.sub(rb"\\x([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]),
                  re.sub(rb'\\(["\\])', rb"\1", raw)).decode("utf-8")


def read_box(root: Path) -> Domain:
    """box_text.c's table: one row per id, one column per language in box_lang_t's order."""
    path = root / "firmware" / "esp32" / "main" / "box_text.c"
    header = (root / "firmware" / "esp32" / "main" / "box_text.h").read_text(encoding="utf-8")
    # BOX_LANG_DE = 2 is "de", BOX_LANG_ZH_TW = 3 "zh-tw".
    order = [m.lower().replace("_", "-")
             for m in re.findall(r"\bBOX_LANG_([A-Z]{2}(?:_[A-Z]{2,4})?)\s*=\s*\d+", header)]
    text = path.read_text(encoding="utf-8")
    body = text[text.index("texts[TX_COUNT][BOX_LANG_COUNT]"):]
    body = re.sub(r"/\*.*?\*/", " ", body[:body.index("\n};")], flags=re.S)  # no comments
    tables: dict[str, dict[str, str]] = {lang: {} for lang in order}
    token = re.compile(r'\s*(?:"((?:[^"\\]|\\.)*)"|(NULL)|(,)|(\}))')
    for row in re.finditer(r"\[(TXO?_[A-Z0-9_]+)\]\s*=\s*\{", body):
        # Cells are separated by commas; adjacent literals are one string; NULL is English.
        i, cells, cell, closed = row.end(), [], None, False
        while (m := token.match(body, i)) is not None:
            i = m.end()
            if m.group(4):
                closed = True
                break
            if m.group(3):
                cells.append(cell)
                cell = None
            elif m.group(1) is not None:
                cell = (cell or "") + c_text(m.group(1))
        if not closed:
            raise ValueError(f"{rel(path, root)}: cannot read the row of {row.group(1)}")
        cells.append(cell)
        for lang, value in zip(order, cells):
            if value is not None:
                tables[lang][row.group(1)] = value
    where = {lang: rel(path, root) for lang in order}
    return Domain("box", PRINTF, tables, where)


def read_server(root: Path) -> Domain:
    tables: dict[str, dict[str, str]] = {}
    where = {}
    for name in ("i18n.py", "staff_i18n.py"):
        path = root / "server" / "atalaia_server" / "web" / name
        if not path.is_file():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            target = node.target if isinstance(node, ast.AnnAssign) else (
                node.targets[0] if isinstance(node, ast.Assign) else None)
            if isinstance(target, ast.Name) and target.id == "STRINGS" and node.value is not None:
                for lang, texts in ast.literal_eval(node.value).items():
                    prefix = name.removesuffix(".py") + "."
                    tables.setdefault(lang, {}).update({prefix + k: v for k, v in texts.items()})
                    where[lang] = "server/atalaia_server/web/{i18n,staff_i18n}.py"
    return Domain("server", BRACES, tables, where)


def read_modes(root: Path) -> Domain:
    tables: dict[str, dict[str, str]] = {}
    for path in sorted((root / "modes").glob("*/mode.yaml")):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        mode = path.parent.name
        tables.setdefault(BASE, {})[mode] = str(manifest.get("name", ""))
        for lang, texts in (manifest.get("i18n") or {}).items():
            if isinstance(texts, dict) and texts.get("name"):
                tables.setdefault(lang, {})[mode] = str(texts["name"])
    return Domain("modes", BRACES, tables, {}, read_only=True)


def rel(path: Path, root: Path = REPO) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


READERS: dict[str, Callable[[Path], Domain]] = {
    "site": read_site,
    "console": lambda root: Domain("console", BRACES,
                                   *read_json_dir(root, "controller/console/src/i18n")),
    "editor": lambda root: Domain("editor", EDITOR_ARGS,
                                  *read_json_dir(root, "simulator/atalaia_sim/editor/i18n")),
    "app": read_app,
    "box": read_box,
    "server": read_server,
    "modes": read_modes,
}


# ---- the check -----------------------------------------------------------------------------


def load_status(root: Path) -> dict[str, dict]:
    data = yaml.safe_load((root / "docs" / "translations" / "status.yaml").read_text(encoding="utf-8"))
    languages = data.get("languages") or {}
    if BASE not in languages:
        raise ValueError("docs/translations/status.yaml: English (en) is the base language and must be listed")
    for code, info in languages.items():
        if info.get("status") not in ("complete", "draft"):
            raise ValueError(f"docs/translations/status.yaml: {code}: status is complete or draft")
    return languages


def check_domain(d: Domain, languages: dict[str, dict], strict: set[str], report: Report) -> None:
    base = d.tables.get(BASE)
    if base is None:
        report.errors.append(f"{d.name}: no English table")
        return
    for lang, table in d.tables.items():
        where = d.where.get(lang, d.name)
        if lang not in languages:
            report.errors.append(f"{where}: language {lang!r} is not in docs/translations/status.yaml")
            continue
        if lang == BASE or d.read_only:
            continue
        for key in sorted(table.keys() - base.keys()):
            report.errors.append(f"{where}: {key} is not in English (renamed or removed there?)")
        for key in sorted(table.keys() & base.keys()):
            text = table[key]
            if not text.strip() and base[key].strip():
                report.errors.append(f"{where}: {key} is empty")
            mine = sorted(d.placeholders.findall(text))
            theirs = sorted(d.placeholders.findall(base[key]))
            if mine != theirs:
                report.errors.append(f"{where}: {key} has the placeholders {mine}, English {theirs}")
        missing = sorted(base.keys() - table.keys())
        if not missing or d.own_completeness:
            continue
        report.missing[(d.name, lang)] = missing
        complete = languages[lang].get("status") == "complete"
        if complete or lang in strict:
            report.errors.append(f"{where}: {len(missing)} key(s) missing, e.g. {', '.join(missing[:5])}")
        else:
            report.warnings.append(f"{where}: {len(missing)} key(s) not translated yet (English shows)")
    # A draft language listed for a domain must have a table there.
    for lang, info in languages.items():
        if d.name in (info.get("domains") or []) and lang not in d.tables:
            report.errors.append(f"{d.name}: status.yaml lists {lang} here, but there is no {lang} table")


def run(root: Path, strict: set[str], show_missing: set[str], out=None) -> int:
    out = out or sys.stdout
    try:
        languages = load_status(root)
        domains = [reader(root) for reader in READERS.values()]
    except (OSError, ValueError, yaml.YAMLError, SyntaxError, json.JSONDecodeError) as exc:
        print(f"i18n_check: {exc}", file=sys.stderr)
        return 1
    report = Report()
    for d in domains:
        check_domain(d, languages, strict, report)

    codes = list(languages)
    print("i18n_check: texts translated, per domain (English is the base)", file=out)
    print(f"  {'domain':<9}" + "".join(f"{c:>12}" for c in codes), file=out)
    for d in domains:
        base = d.tables.get(BASE) or {}
        cells = []
        for c in codes:
            table = d.tables.get(c)
            cells.append("-" if table is None else f"{len(base.keys() & table.keys())}/{len(base)}")
        print(f"  {d.name:<9}" + "".join(f"{cell:>12}" for cell in cells), file=out)
    for code, info in languages.items():
        if info.get("status") != "complete":
            print(f"  {code}: {info.get('status')}: {' '.join(str(info.get('review', '')).split())}", file=out)
    for (domain, lang), keys in sorted(report.missing.items()):
        if lang in show_missing:
            print(f"  missing in {lang} ({domain}):", file=out)
            for key in keys:
                print(f"    {key}", file=out)
    for w in report.warnings:
        print(f"warning: {w}", file=out)
    for e in report.errors:
        print(f"error: {e}", file=sys.stderr)
    if report.errors:
        print(f"i18n_check: {len(report.errors)} error(s)", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--strict", action="append", default=[], metavar="LANG",
                    help="fail when LANG lacks a key (as for a complete language); may be repeated")
    ap.add_argument("--missing", action="append", default=[], metavar="LANG",
                    help="list the keys LANG lacks in each domain; may be repeated")
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)  # the tests' copies
    args = ap.parse_args(argv)
    return run(args.root, set(args.strict), set(args.missing))


if __name__ == "__main__":
    sys.exit(main())
