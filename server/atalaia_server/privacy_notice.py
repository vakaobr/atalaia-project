# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The privacy notice the operator publishes (decisions CONS-1 to CONS-6): the mechanism, never the text.

The notice is the operator's (legal) text. The server only serves it and asks for consent again when its version
changes. ``ATALAIA_PRIVACY_NOTICE_DIR`` names a folder with one Markdown file per language and version, called
``privacy-notice-<lang>-<version>.md`` (``<lang>`` is ``pt``, ``en``, ``de`` or ``zh-tw``; ``<version>`` is the
``ATALAIA_PRIVACY_NOTICE_VERSION`` the file is for), for example ``privacy-notice-en-campo-tejo-2026-11.md``: the
templates in ``docs/templates/`` filled in by the field. Only the files of the current version are served, so a new
version is a new set of files beside the old ones. Nothing is cached: a file the operator replaces is served at once.

``render`` turns the Markdown into HTML with a small renderer for what the templates use (headings, paragraphs,
lists, block quotes, tables, rules, code, bold, italic, links). Every character of the text is escaped first, raw HTML
in a file shows as text, and a link keeps only an ``https:``, ``http:`` or ``mailto:`` address.
"""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path
from typing import NamedTuple, Optional

LANGUAGES = ("pt", "en", "de", "zh-tw")
MAX_BYTES = 512 * 1024
log = logging.getLogger("atalaia.privacy")


def filename(lang: str, version: str) -> str:
    return f"privacy-notice-{lang}-{version}.md"


class Notice(NamedTuple):
    version: str
    lang: str            # the language of the text served
    markdown: str
    available: tuple[str, ...]  # every language the current version has, in the project's order


def available(directory: Optional[str], version: str) -> tuple[str, ...]:
    """The languages the folder has a file for, for this version."""
    if not directory:
        return ()
    base = Path(directory)
    return tuple(lang for lang in LANGUAGES if (base / filename(lang, version)).is_file())


def load(directory: Optional[str], version: str, wanted: str, fallback: str = "pt") -> Optional[Notice]:
    """The notice in ``wanted``, else in ``fallback``, else in the first language there is one; None when the
    version has no file at all, or the folder is not set. A file too big or not UTF-8 counts as absent."""
    langs = available(directory, version)
    for lang in (wanted, fallback, *langs):
        if lang not in langs:
            continue
        path = Path(directory or "") / filename(lang, version)
        try:
            if path.stat().st_size > MAX_BYTES:
                raise ValueError("file too big")
            text = path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:  # UnicodeDecodeError is a ValueError
            log.warning("privacy notice %s cannot be read: %s", path.name, exc)
            continue
        return Notice(version, lang, text.replace("\r\n", "\n"), langs)
    return None


# ---- Markdown -------------------------------------------------------------------------------------------------

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)[ \t#]*$")
_RULE = re.compile(r"^ {0,3}([-*_])([ \t]*\1){2,}[ \t]*$")
_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])[ \t]+(.*)$")
_FENCE = re.compile(r"^ {0,3}```")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_CODE = re.compile(r"`([^`]+)`")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])")
_SAFE_LINK = re.compile(r"^(https?://|mailto:)[^\s<>\"']+$", re.IGNORECASE)


def _inline(text: str) -> str:
    out = []
    for i, part in enumerate(_CODE.split(text)):
        if i % 2:  # inside backticks
            out.append(f"<code>{html.escape(part)}</code>")
            continue
        part = html.escape(part)

        def link(m: "re.Match[str]") -> str:
            url = html.unescape(m.group(2))
            if not _SAFE_LINK.match(url):
                return m.group(0)
            return f'<a href="{html.escape(url)}" rel="noopener noreferrer">{m.group(1)}</a>'

        part = _LINK.sub(link, part)
        part = _BOLD.sub(r"<strong>\1</strong>", part)
        part = _ITALIC.sub(r"<em>\1</em>", part)
        out.append(part)
    return "".join(out)


def _starts_block(line: str, nxt: Optional[str]) -> bool:
    return bool(_HEADING.match(line) or _RULE.match(line) or _ITEM.match(line) or line.lstrip().startswith(">")
                or _FENCE.match(line) or line.lstrip().startswith("<!--")
                or (line.lstrip().startswith("|") and nxt is not None and _TABLE_SEP.match(nxt)))


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _blocks(lines: list[str]) -> str:
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < n else None
        if not line.strip():
            i += 1
        elif line.lstrip().startswith("<!--"):  # an HTML comment (the templates start with one): dropped
            while i < n and "-->" not in lines[i]:
                i += 1
            i += 1
        elif _FENCE.match(line):
            i += 1
            code = []
            while i < n and not _FENCE.match(lines[i]):
                code.append(lines[i])
                i += 1
            i += 1
            out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>")
        elif (m := _HEADING.match(line)):
            out.append(f"<h{len(m.group(1))}>{_inline(m.group(2))}</h{len(m.group(1))}>")
            i += 1
        elif _RULE.match(line):
            out.append("<hr>")
            i += 1
        elif line.lstrip().startswith(">"):
            quote = []
            while i < n and lines[i].lstrip().startswith(">"):
                quote.append(re.sub(r"^\s*> ?", "", lines[i]))
                i += 1
            out.append("<blockquote>" + _blocks(quote) + "</blockquote>")
        elif line.lstrip().startswith("|") and nxt is not None and _TABLE_SEP.match(nxt):
            head = _cells(line)
            i += 2
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                rows.append(_cells(lines[i]))
                i += 1
            out.append("<table><thead><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in row) + "</tr>" for row in rows)
                       + "</tbody></table>")
        elif _ITEM.match(line):
            i = _list(lines, i, out)
        else:
            para = [line.strip()]
            i += 1
            while i < n and lines[i].strip() and not _starts_block(lines[i], lines[i + 1] if i + 1 < n else None):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>" + _inline("\n".join(para)) + "</p>")
    return "\n".join(out)


def _indent(line: str) -> int:
    return len(line.expandtabs(4)) - len(line.expandtabs(4).lstrip())


def _list(lines: list[str], i: int, out: list[str]) -> int:
    """One list starting at ``lines[i]`` (an item); its items' own lines go through ``_blocks`` again, so a list
    nests by indentation. Returns the index after it."""
    n = len(lines)
    first = _ITEM.match(lines[i])
    assert first is not None
    base = _indent(lines[i])
    ordered = first.group(2)[0].isdigit()
    items: list[list[str]] = []
    while i < n:
        m = _ITEM.match(lines[i])
        if m is not None and _indent(lines[i]) == base and m.group(2)[0].isdigit() == ordered:
            items.append([m.group(3)])
            i += 1
            continue
        if not lines[i].strip():  # a blank line goes on only into more of the list
            j = i
            while j < n and not lines[j].strip():
                j += 1
            if j < n and (_indent(lines[j]) > base or (_ITEM.match(lines[j]) and _indent(lines[j]) == base
                                                         and _ITEM.match(lines[j]).group(2)[0].isdigit() == ordered)):
                items[-1].append("")
                i = j
                continue
            break
        if _indent(lines[i]) > base:
            items[-1].append(lines[i][min(_indent(lines[i]), base + 2):] if _ITEM.match(lines[i]) is None
                             else lines[i])
            i += 1
            continue
        if _starts_block(lines[i], None):
            break
        items[-1].append(lines[i].strip())  # a lazy continuation of the item's text
        i += 1
    tag = "ol" if ordered else "ul"
    body = []
    for item in items:
        inner = _blocks(item)
        if inner.startswith("<p>") and inner.count("<p>") == 1 and inner.endswith("</p>"):
            inner = inner[3:-4]  # a one-paragraph item is not wrapped
        elif inner.startswith("<p>"):
            head, sep, rest = inner.partition("</p>")  # the item's text, then its own nested blocks
            if head.count("<p>") == 1 and "<p>" not in rest:
                inner = head[3:] + rest
        body.append(f"<li>{inner}</li>")
    out.append(f"<{tag}>" + "".join(body) + f"</{tag}>")
    return i


def render(markdown: str) -> str:
    """The Markdown as HTML (see the module's notes: everything escaped, a small subset)."""
    return _blocks(markdown.replace("\r\n", "\n").split("\n"))
