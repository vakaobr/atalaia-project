#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""The community mode registry's public page, built from its index.json.

    python3 tools/registry_page.py REGISTRY OUT

Writes OUT/index.html (English), OUT/pt/index.html, OUT/de/index.html and OUT/zh-tw/index.html: a
static page (no script, nothing loaded from other sites, one inline stylesheet that uses the project
page's colours, light and dark) listing the registry's modes, saying how to submit one, what the
verified badge means and how a field controller uses the index. The texts are REGISTRY/site/page.yaml
(the registry's own copy, from registry/template/site/); `registry_check.py site` calls this after it
has copied index.json, which keeps its exact address.

Everything that comes from index.json (mode names, descriptions and authors are pull requests'
words, so untrusted) is escaped with html.escape, and an address is linked only when it is a
relative file path or an https:// address with no characters that could leave the attribute.
Needs PyYAML (like the other registry tools); the rest is the standard library.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
TEXTS = Path("site") / "page.yaml"
FALLBACK_TEXTS = REPO / "registry" / "template" / "site" / "page.yaml"

LANGUAGES = ("en", "pt", "de", "zh-tw")
FOLDER = {"en": "", "pt": "pt/", "de": "de/", "zh-tw": "zh-tw/"}
SAFE_PATH = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")
SAFE_HTTPS = re.compile(r"^https://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]+$")
VERSION = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-(.*))?$")
KINDS = ("mode", "modifier", "role", "scenario")

# The project page's palette (site/style.css): slate, sand and signal orange; light and dark.
CSS = """
:root{color-scheme:light dark;--slate:#262d34;--sand:#e3c48d;--sand-deep:#c9a25c;--signal:#f07a1a;
--on-slate:#eef0ee;--on-slate-muted:#b3bbc2;--bg:#f7f8f6;--band:#ebeeea;--surface:#fff;--text:#1f262c;
--muted:#56606a;--line:#d3d8db;--rule:var(--sand-deep);--open:#2f7d4a;--code-bg:var(--slate);
--code-text:#e7eae6;--radius:4px;
--body:"Barlow",system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif;
--display:"Barlow Condensed","Arial Narrow","Roboto Condensed","Noto Sans TC","PingFang TC",system-ui,sans-serif;
--mono:ui-monospace,"SFMono-Regular","Cascadia Mono",Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#1d2328;--band:#232a30;--surface:#29313a;--text:#e9ece8;
--muted:#a7b0b8;--line:#3a444e;--rule:var(--sand);--open:#6fcf8f;--code-bg:#151a1f}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:17px/1.6 var(--body)}
a{color:inherit;text-decoration:underline;text-decoration-color:var(--signal);text-decoration-thickness:2px;text-underline-offset:3px}
a:hover{color:var(--signal)}
a:focus-visible{outline:2px solid var(--signal);outline-offset:3px}
.wrap{max-width:960px;margin:0 auto;padding:0 20px}
.skip{position:absolute;left:-999px;top:8px;background:var(--surface);padding:6px 10px;border-radius:var(--radius);z-index:10}
.skip:focus{left:8px}
h1,h2,h3{margin:0;font-family:var(--display);font-weight:700;line-height:1.1}
h1{font-size:clamp(2.4rem,6vw,3.6rem)}
h2{font-size:clamp(1.7rem,3.5vw,2.2rem);padding-top:8px;border-top:3px solid var(--rule);display:inline-block;margin-bottom:14px}
h3{font-size:1.4rem;font-weight:600}
code{font-family:var(--mono);font-size:.88em}
.top{background:var(--slate);color:var(--on-slate)}
.top-inner{display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:58px;flex-wrap:wrap}
.top a{color:var(--on-slate)}
.brand{display:inline-flex;align-items:center;gap:10px;font:700 1.5rem/1 var(--display);text-decoration:none}
.brand img{width:28px;height:28px}
.top nav{display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-size:.95rem}
.top nav a[aria-current]{color:var(--sand);text-decoration-color:var(--sand)}
.hero{background:var(--slate);color:var(--on-slate);padding:40px 0 48px;border-top:1px solid #39434c}
.hero p{max-width:60ch;margin:16px 0 0;font-size:1.2rem}
section{padding:36px 0}
section.band{background:var(--band)}
p{margin:0 0 12px}
.muted{color:var(--muted)}
.mode{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);padding:18px 20px;margin:0 0 18px}
.mode .meta{color:var(--muted);margin:2px 0 8px}
.mode .id{font-family:var(--mono);font-size:.85rem;color:var(--muted)}
.table{overflow-x:auto;margin-top:10px}
table{border-collapse:collapse;width:100%;font-size:.95rem}
th,td{text-align:left;padding:6px 12px 6px 0;border-top:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted);border-top:0}
.chip{display:inline-block;padding:1px 8px;border-radius:var(--radius);border:1px solid var(--line);font-size:.85rem;color:var(--muted);white-space:nowrap}
.chip.ok{color:var(--open);border-color:currentColor;font-weight:600}
.empty{background:var(--surface);border:1px dashed var(--line);border-radius:var(--radius);padding:22px 20px}
pre{background:var(--code-bg);color:var(--code-text);padding:14px 16px;border-radius:var(--radius);overflow-x:auto;margin:12px 0;font:.9rem/1.5 var(--mono)}
.links{display:flex;gap:16px;flex-wrap:wrap;margin-top:6px}
footer{padding:24px 0 40px;color:var(--muted);font-size:.9rem;border-top:1px solid var(--line)}
@media (max-width:640px){body{font-size:16px}}
"""

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' "
           "height='32' rx='7' fill='%23262d34'/%3E%3Cpath fill='%23f07a1a' d='M16 2.5c1.8 2.2 3.1 3.6 2 5.6-.5.9-1.4"
           ".9-2 .4-.6.5-1.5.5-2-.4-1.1-2 .2-3.4 2-5.6z'/%3E%3Cpath fill='%23eef0ee' d='M10 15.5V10h3v2.6h1.6V10h2.8v2.6H19"
           "V10h3v5.5zM11 15.5h10l1.6 13H9.4z'/%3E%3C/svg%3E")


def esc(value: Any) -> str:
    """Everything that reaches the page goes through here."""
    return html.escape(str(value), quote=True)


def load_texts(registry: Path) -> dict[str, Any]:
    path = registry / TEXTS
    if not path.is_file():
        path = FALLBACK_TEXTS
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for lang in LANGUAGES:
        if lang not in data["languages"]:
            raise ValueError(f"{path}: no texts for {lang}")
    return data


def safe_address(value: Any, prefix: str) -> str | None:
    """A relative file path (made relative to the page, with prefix) or an https address, else None."""
    if not isinstance(value, str) or len(value) > 500:
        return None
    if SAFE_HTTPS.match(value):
        return value
    if SAFE_PATH.match(value) and ".." not in value.split("/"):
        return prefix + value
    return None


def version_key(version: Any) -> tuple:
    match = VERSION.match(str(version))
    if not match:
        return (0, 0, 0, 0, "")
    major, minor, patch, pre = match.groups()
    # A release sorts after its own pre-releases.
    return (int(major), int(minor), int(patch), 1 if pre is None else 0, pre or "")


def link(address: str | None, label: str) -> str:
    return f'<a href="{esc(address)}">{esc(label)}</a>' if address else esc(label)


def mode_html(mode: dict[str, Any], t: dict[str, str], up: str) -> str:
    name = mode.get("name") if isinstance(mode.get("name"), str) else ""
    author = mode.get("author") if isinstance(mode.get("author"), str) and mode.get("author") else t["unknown_author"]
    parts = [f'<article class="mode"><h3>{esc(name)}</h3>',
             f'<p class="meta">{esc(t["by"])} {esc(author)} · <span class="id">{esc(mode.get("id", ""))}</span></p>']
    if isinstance(mode.get("description"), str) and mode["description"]:
        parts.append(f'<p>{esc(mode["description"])}</p>')
    rows = []
    versions = [v for v in mode.get("versions", []) if isinstance(v, dict)]
    for v in sorted(versions, key=lambda v: version_key(v.get("version")), reverse=True):
        verified = v.get("verified") is True
        address = safe_address(v.get("url"), up)
        sig = safe_address(f'{v.get("url")}.{"verified" if verified else "release"}.json', up) if address else None
        kind = str(v.get("kind", ""))
        kind_text = t.get(f"kind_{kind}", kind) if kind in KINDS else kind
        status = (f'<span class="chip ok">&#10003; {esc(t["verified"])}</span>' if verified
                  else f'<span class="chip">{esc(t["not_reviewed"])}</span>')
        download = link(address, t["download"]) if address else "&ndash;"
        if sig:
            download += f' · {link(sig, t["signature"])}'
        rows.append(f"<tr><td>{esc(v.get('version', ''))}</td><td>{esc(kind_text)}</td><td>{status}</td>"
                    f"<td>{esc(v.get('license', ''))}</td><td>{download}</td></tr>")
    parts.append(f'<div class="table"><table><thead><tr><th>{esc(t["th_version"])}</th><th></th>'
                 f'<th>{esc(t["th_status"])}</th><th>{esc(t["th_licence"])}</th><th>{esc(t["th_download"])}</th>'
                 f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div></article>')
    return "".join(parts)


def render(index: dict[str, Any], data: dict[str, Any], lang: str) -> str:
    """The page of one language. `index` is index.json's content, untrusted."""
    t = data["languages"][lang]
    links = data["links"]
    up = "../" * FOLDER[lang].count("/")
    index_url = links["pages"].rstrip("/") + "/index.json"
    modes = [m for m in index.get("modes", []) if isinstance(m, dict)] if isinstance(index, dict) else []
    switch = []
    for other in LANGUAGES:
        target = (up + FOLDER[other]) or "./"
        current = ' aria-current="page"' if other == lang else ""
        switch.append(f'<a href="{esc(target)}" hreflang="{esc(data["languages"][other]["html_lang"])}" '
                      f'lang="{esc(data["languages"][other]["html_lang"])}"{current}>{esc(data["languages"][other]["name"])}</a>')
    alternates = "".join(
        f'<link rel="alternate" hreflang="{esc(data["languages"][o]["html_lang"])}" '
        f'href="{esc(links["pages"] + FOLDER[o])}">' for o in LANGUAGES)

    if modes:
        listing = "".join(mode_html(m, t, up) for m in modes)
    else:
        listing = (f'<div class="empty"><p><strong>{esc(t["modes_empty"])}</strong></p>'
                   f'<p><a href="#submit">{esc(t["modes_empty_link"])}</a></p></div>')
    toml = f'[modes]\nindex = "{index_url}"\nkeys = ["&lt;key from keys.json&gt;"]'

    return f"""<!doctype html>
<html lang="{esc(t["html_lang"])}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(t["title"])}</title>
<meta name="description" content="{esc(t["description"])}">
<meta name="color-scheme" content="light dark">
<link rel="canonical" href="{esc(links["pages"] + FOLDER[lang])}">
{alternates}
<link rel="icon" href="{FAVICON}">
<style>{CSS}</style>
</head>
<body>
<a class="skip" href="#main">{esc(t["skip"])}</a>
<header class="top"><div class="wrap top-inner">
<a class="brand" href="{esc(links["project"][lang])}"><img src="{FAVICON}" alt="">Atalaia</a>
<nav aria-label="{esc(t["language"])}"><a href="{esc(links["project"][lang])}">{esc(t["project"])}</a> <span aria-hidden="true">·</span> {" ".join(switch)}</nav>
</div></header>
<main id="main">
<div class="hero"><div class="wrap"><h1>{esc(t["title"])}</h1><p>{esc(t["lead"])}</p></div></div>
<section><div class="wrap"><h2>{esc(t["what_title"])}</h2><p>{esc(t["what_text"])}</p></div></section>
<section class="band"><div class="wrap"><h2 id="modes">{esc(t["modes_title"])}</h2>
{listing}
</div></section>
<section id="submit"><div class="wrap"><h2>{esc(t["submit_title"])}</h2><p>{esc(t["submit_text"])}</p>
<div class="links"><a href="{esc(links["contributing"])}">{esc(t["submit_contributing"])}</a>
<a href="{esc(links["docs"])}">{esc(t["submit_docs"])}</a>
<a href="{esc(links["keys_docs"])}">{esc(t["submit_keys"])}</a>
<a href="{esc(links["repository"])}">GitHub</a></div></div></section>
<section class="band"><div class="wrap"><h2>{esc(t["verified_title"])}</h2><p>{esc(t["verified_text"])}</p></div></section>
<section><div class="wrap"><h2>{esc(t["use_title"])}</h2><p>{esc(t["use_text"])}</p>
<pre><code>{toml}</code></pre>
<p class="muted">{esc(t["use_note"])}</p>
<p><a href="{esc(index_url)}">{esc(t["index_label"])}: <code>{esc(index_url)}</code></a></p></div></section>
</main>
<footer><div class="wrap">{esc(t["footer"])}</div></footer>
</body>
</html>
"""


def build(registry: Path, out: Path, index: dict[str, Any] | None = None) -> list[Path]:
    """Writes the four pages under out/ and returns their paths. index defaults to registry/index.json."""
    if index is None:
        index = json.loads((registry / "index.json").read_text(encoding="utf-8"))
    data = load_texts(registry)
    written = []
    for lang in LANGUAGES:
        path = out / FOLDER[lang] / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render(index, data, lang), encoding="utf-8")
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("registry")
    parser.add_argument("out")
    args = parser.parse_args(argv)
    for path in build(Path(args.registry), Path(args.out)):
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
