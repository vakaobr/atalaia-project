# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A mode's screen templates (assets/screens/*.yaml, ADR-P3-4): the checks CI runs.

Each file is parsed by the core's own parser (core/src/screen_template.c,
through ctypes), the one the Field Box renders with, so a template the
simulator accepts is one every box accepts. On top of that the file's name
must be its `template:` name, which is how ui.screen() finds it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

import yaml

from .core import Core

SOURCE_MAX = 4096  # ATALAIA_TPL_SOURCE_MAX
LITERALS_MAX = 256  # ATALAIA_TPL_LITERALS_MAX: the 'text' literals of one expression (decision TPL-1)
LITERALS_WARN = 230  # a warning from here: about 90 % of the limit


def screen_files(mode_dir: Path) -> list[Path]:
    folder = mode_dir / "assets" / "screens"
    return sorted(folder.glob("*.yaml")) if folder.is_dir() else []


def _split_filter(inner: str) -> str:
    """The expression of "{expr|filter}" ("||" is an operator, a '|' in a 'text' is text)."""
    quoted = False
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == "'":
            quoted = not quoted
        elif c == "|" and not quoted:
            if inner[i + 1:i + 2] == "|":
                i += 2
                continue
            return inner[:i]
        i += 1
    return inner


def _expressions(text: str) -> Iterator[str]:
    """Every {expression} of a template text, as the core finds them."""
    i = 0
    while i < len(text):
        c = text[i]
        if c in "{}" and text[i + 1:i + 2] == c:
            i += 2
            continue
        if c != "{":
            i += 1
            continue
        close = text.find("}", i + 1)
        if close < 0:
            return
        yield _split_filter(text[i + 1:close])
        i = close + 1


def _widgets(node: Any, where: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every widget (a mapping with a `type`), named by where it is: layout[1].children[0]."""
    if isinstance(node, list):
        for n, child in enumerate(node):
            yield from _widgets(child, f"{where}[{n}]")
    elif isinstance(node, dict):
        if "type" in node:
            yield where, node
        for key in ("children", "layout"):
            if key in node:
                yield from _widgets(node[key], f"{where}.{key}" if where else key)


def _strings(node: Any, field: str) -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        yield field, node
    elif isinstance(node, dict):
        for key, value in node.items():
            if key not in ("children", "layout"):
                yield from _strings(value, f"{field}.{key}" if field else str(key))


def literal_budget(core: Core, path: Path) -> list[tuple[str, str, int]]:
    """The 'text' literal bytes of every expression in a template, biggest first: (where, the
    expression, bytes). `where` names the widget and field ("layout[2] label text"). Every language
    is in the one expression (a chain of lang == ... branches), and the core counts them all,
    reached or not, so this is the exact size the evaluator needs, whatever the data."""
    try:
        doc = yaml.safe_load(path.read_bytes()) or {}
    except yaml.YAMLError:
        return []  # the core's parser has already said so
    found: list[tuple[str, str, int]] = []
    for where, widget in _widgets(doc.get("layout", []), "layout"):
        for field, value in _strings(widget, ""):
            for expr in _expressions(value):
                size = core.expression_literal_bytes(expr)
                if size:
                    found.append((f"{where} {widget.get('type')} {field}", expr, size))
    found.sort(key=lambda row: -row[2])
    return found


def _echo(expr: str) -> str:
    expr = " ".join(expr.split())
    return expr if len(expr) <= 60 else expr[:57] + "..."


def check_screen(core: Core, path: Path, mode: str = "") -> list[str]:
    """Problems with one template file (empty when it is fine). `mode` names the mode in the
    message of an expression whose 'text' literals are over the limit."""
    source = path.read_bytes()
    if len(source) > SOURCE_MAX:
        return [f"{path.name}: larger than {SOURCE_MAX} bytes"]
    try:
        source.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{path.name}: not UTF-8"]
    try:
        over = [row for row in literal_budget(core, path) if row[2] > LITERALS_MAX]
    except AttributeError:  # a core from before the limit was checked
        over = []
    if over:
        # The Field Box would show an empty text for these (it refuses them at load), so say which.
        prefix = f"{mode} / " if mode else ""
        return [f"{prefix}{path.stem} / {where}: the expression {{{_echo(expr)}}} has 'text' "
                f"literals of {size} bytes in all (each its length + 1, every language's branch "
                f"counted); the limit is {LITERALS_MAX}. Shorten the texts or split the label "
                f"in two widgets with a visible: each" for where, expr, size in over]
    why = core.check_screen(source)
    if why is not None:
        return [f"{path.name}: {why}"]
    name = (yaml.safe_load(source) or {}).get("template")
    if name != path.stem:
        return [f"{path.name}: its template: name is {name!r}; it must be {path.stem!r}"]
    return []


def check_screens(core: Core, mode_dir: Path) -> list[str]:
    problems: list[str] = []
    for path in screen_files(mode_dir):
        problems += check_screen(core, path, mode_dir.name)
    return problems


def screen_warnings(core: Core, mode_dir: Path) -> list[str]:
    """Expressions that are close to the limit (from LITERALS_WARN bytes): one more translated
    word would tip them over."""
    warnings: list[str] = []
    for path in screen_files(mode_dir):
        try:
            rows = literal_budget(core, path)
        except AttributeError:
            return []
        for where, expr, size in rows:
            if LITERALS_WARN <= size <= LITERALS_MAX:
                warnings.append(f"{mode_dir.name} / {path.stem} / {where}: {{{_echo(expr)}}} uses "
                                f"{size} of {LITERALS_MAX} literal bytes")
    return warnings
