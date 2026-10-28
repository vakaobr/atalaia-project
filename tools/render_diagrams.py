#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws the architecture diagrams of the project page: Mermaid templates -> plain SVG, per language.

    python3 tools/render_diagrams.py            draw what is out of date (needs Docker)
    python3 tools/render_diagrams.py --force    draw everything again
    python3 tools/render_diagrams.py --png DIR  also write a PNG of each SVG into DIR, light and
                                                dark, to look at (never commit them)

docs/architecture.md holds seven Mermaid diagrams, which GitHub draws in the browser. The
project page shows the same diagrams as SVG files in four languages: the templates
site/src/diagrams/arch-<n>-<name>.mmd (the doc's diagrams with every label a {{ key }} of
site/i18n/*.yaml) are filled in by tools/build_site.py, and this script draws each with the
Mermaid CLI (the minlag/mermaid-cli Docker image, MERMAID_IMAGE below, with Chromium in the image)
into site/img/diagrams/arch-<n>-<name>-<code>.svg.

The SVGs are plain: labels are <text> (htmlLabels off, so no <foreignObject>), there is no script
and no outside address, and no font is loaded. Mermaid's colours are replaced with CSS variables
(PALETTE below, the site's own colours from site/style.css), with a prefers-color-scheme: dark
override, so a diagram follows the reader's light or dark setting when it is shown in an <img>.
Each SVG holds a comment with a fingerprint: the SHA-256 of the filled Mermaid source and of this
file's own text (so of the image tag, the configuration, the palette and the post-processing).
`python3 tools/build_site.py --check` recomputes it and fails when it differs, that is when a
template, a label or this tool changed and the SVGs were not drawn again; CI cannot run Mermaid,
this check is what keeps the SVGs from going stale.

To change a diagram: edit docs/architecture.md and the template together (the English texts
filled into the template must give the doc's block exactly), add or change the labels in all four
site/i18n/*.yaml, then run this script and commit the SVGs.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import build_site as site

MERMAID_IMAGE = "minlag/mermaid-cli:11.12.0"
# The font Mermaid measures its boxes with (in the image: DejaVu Sans, wider than most fonts a
# reader has, so text fits; Noto Sans CJK TC for Traditional Chinese), and the font stack the SVG
# asks for when it is shown, which holds fonts a phone or a desktop has.
MEASURE_FONT = "DejaVu Sans, Noto Sans CJK TC, sans-serif"
SHOW_FONT = ("'Segoe UI', Roboto, 'Helvetica Neue', Arial, 'Liberation Sans', 'DejaVu Sans', "
             "'PingFang TC', 'Noto Sans TC', 'Microsoft JhengHei', sans-serif")

# Colours (light, dark) from site/style.css. Role names are the CSS variables --ad-<role>.
PALETTE = {
    "bg": ("#f7f8f6", "#1d2328"),  # --bg: the page's own background, so the diagram sits on it
    "text": ("#1f262c", "#e9ece8"),  # --text
    "node": ("#fbf3e1", "#2f3740"),  # a box: a light sand, a dark slate
    "nodeline": ("#c9a25c", "#e3c48d"),  # --sand-deep, --sand
    "cluster": ("#f7f8f6", "#1d2328"),  # a group's inside: the same as the page
    "clusterline": ("#8b949b", "#6c7882"),
    "line": ("#4a535c", "#b3bbc2"),  # --granite, --on-slate-muted: links and arrowheads
    "faint": ("#8b949b", "#6c7882"),  # a sequence diagram's lifelines
    "note": ("#e8edf0", "#394450"),
    "noteline": ("#8b949b", "#6c7882"),
}

# Mermaid theme variable -> palette role. Each variable gets its own marker colour, so that the
# colours in the SVG can be told apart and replaced by the variables.
THEME_ROLES = {
    "background": "bg", "edgeLabelBackground": "bg",
    "primaryColor": "node", "mainBkg": "node", "secondaryColor": "node", "tertiaryColor": "node",
    "actorBkg": "node",
    "primaryBorderColor": "nodeline", "secondaryBorderColor": "nodeline", "tertiaryBorderColor": "nodeline",
    "nodeBorder": "nodeline", "actorBorder": "nodeline",
    "primaryTextColor": "text", "secondaryTextColor": "text", "tertiaryTextColor": "text", "textColor": "text",
    "nodeTextColor": "text", "titleColor": "text", "actorTextColor": "text", "signalTextColor": "text",
    "noteTextColor": "text", "labelTextColor": "text", "loopTextColor": "text", "sequenceNumberColor": "bg",
    "lineColor": "line", "arrowheadColor": "line", "signalColor": "line", "actorLineColor": "faint",
    "activationBorderColor": "line",
    "clusterBkg": "cluster", "clusterBorder": "clusterline", "labelBoxBkgColor": "cluster",
    "labelBoxBorderColor": "clusterline", "activationBkgColor": "cluster",
    "noteBkgColor": "note", "noteBorderColor": "noteline",
}
# Colours Mermaid writes into the SVG whatever the theme: sequence diagrams' actors, notes and
# lifelines, and a marker's outline.
FIXED_ROLES = {"#eaeaea": "node", "#666": "nodeline", "#edf2ae": "note", "#999": "faint", "#000000": "line"}
# Colours in rules that no element of these diagrams uses (a pop-up menu, maths): left as they are.
IGNORED_COLOURS = {"#000", "rgba(0,0,0,0.2)", "rgb(0 0 0 / 0.4)"}

COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)|\bwhite\b|\bblack\b")
ATTRIBUTE_COLOUR = re.compile(r'\b(fill|stroke)="(#[0-9a-fA-F]{3,8})"')
FORBIDDEN = ("<foreignObject", "<script", "@import", "http://", "https://", "javascript:", "url(\"http", "<image")
ALLOWED_URLS = ("http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink")

PUPPETEER = {"executablePath": "/usr/bin/chromium", "args": ["--no-sandbox"]}


def marker(index: int) -> str:
    return "#%02x%02x%02x" % (1, index // 256, index % 256 + 1)


MARKERS = {name: marker(i) for i, name in enumerate(THEME_ROLES)}


def mermaid_config() -> dict:
    return {
        "theme": "base",
        "htmlLabels": False,
        "flowchart": {"htmlLabels": False, "useMaxWidth": False, "padding": 12, "subGraphTitleMargin": {"top": 6, "bottom": 24}, "nodeSpacing": 40, "rankSpacing": 50},
        "sequence": {"useMaxWidth": False, "mirrorActors": True, "wrap": False},
        "themeVariables": {"fontFamily": MEASURE_FONT, "fontSize": "15px"} | MARKERS,
    }


def palette_css() -> str:
    def block(index: int) -> str:
        return "".join(f"--ad-{role}:{colours[index]};" for role, colours in PALETTE.items())

    return (f"#my-svg{{{block(0)}}}"
            f"@media (prefers-color-scheme:dark){{#my-svg{{{block(1)}}}}}"
            "#my-svg{background-color:var(--ad-bg);}")


def post_process(svg: str, fingerprint: str, where: str) -> str:
    """Plain, self-contained, themed SVG from Mermaid's output; fails on anything unexpected."""
    svg = svg.replace("\r\n", "\n").strip()
    svg = re.sub(r'(<svg\b[^>]*?) style="[^"]*"', r"\1", svg, count=1)  # Mermaid's white background
    svg = re.sub(r'(<svg\b[^>]*?) width="[\d.]+"', r"\1", svg, count=1)  # the page sets the size
    svg = re.sub(r'(<svg\b[^>]*?) height="[\d.]+"', r"\1", svg, count=1)
    svg = svg.replace(MEASURE_FONT, SHOW_FONT)
    # Rounded numbers keep the file's text stable and small.
    svg = re.sub(r'viewBox="([^"]+)"', lambda m: 'viewBox="' + " ".join(
        f"{float(v):.0f}" for v in m.group(1).split()) + '"', svg, count=1)
    svg = re.sub(r"(\d+\.\d{3})\d+", r"\1", svg)

    by_marker = {MARKERS[name]: THEME_ROLES[name] for name in THEME_ROLES}
    problems = set()

    def role_of(token: str) -> str | None:
        key = token.lower().replace(" ", "")
        if key in by_marker:
            return by_marker[key]
        if key in FIXED_ROLES:
            return FIXED_ROLES[key]
        if re.fullmatch(r"rgba\(1,0,\d+,[\d.]+\)", key):  # a marker colour with an alpha: a label's background
            return "bg"
        return None

    def to_variable(match: re.Match[str]) -> str:
        token = match.group(0)
        if token in IGNORED_COLOURS:
            return token
        role = role_of(token)
        if role is None:
            problems.add(token)
            return token
        return f"var(--ad-{role})"

    # Colours inside <style> and style="" become variables. A colour in an attribute (the
    # sequence diagrams' actors and notes) is replaced by a CSS rule on its value, which wins.
    attribute_rules = []
    for _, value in sorted(set(ATTRIBUTE_COLOUR.findall(svg))):
        role = role_of(value)
        if role is None:
            problems.add(value)
    for attribute, value in sorted(set(ATTRIBUTE_COLOUR.findall(svg))):
        role = role_of(value)
        if role:
            attribute_rules.append(f'#my-svg [{attribute}="{value}"]{{{attribute}:var(--ad-{role});}}')
    parts = re.split(r"(<style>.*?</style>)", svg, flags=re.S)
    parts = [COLOUR.sub(to_variable, part) if part.startswith("<style>") else part for part in parts]
    svg = "".join(parts)
    svg = re.sub(r'(style="[^"]*")', lambda m: COLOUR.sub(to_variable, m.group(1)), svg)
    if problems:
        raise SystemExit(f"{where}: Mermaid used colours that PALETTE and FIXED_ROLES in tools/render_diagrams.py "
                         f"do not map: {', '.join(sorted(problems))}")
    style = f"<style>{palette_css()}{''.join(attribute_rules)}</style>"
    svg = re.sub(r"(<svg\b[^>]*>)", lambda m: m.group(1) + style, svg, count=1)
    for bad in FORBIDDEN:
        found = svg.find(bad)
        while found != -1:
            if not any(svg.startswith(ok, found) for ok in ALLOWED_URLS):
                raise SystemExit(f"{where}: the SVG holds {bad!r}, which a self-contained diagram must not")
            found = svg.find(bad, found + 1)
    header = "\n".join((
        "<!--",
        *site.SPDX_LINES,
        "",
        f"Drawn by tools/render_diagrams.py ({MERMAID_IMAGE}) from the Mermaid template and the labels. Do not edit:",
        "change docs/architecture.md, the template or site/i18n/*.yaml and run the tool again.",
        "-->",
        f"<!-- atalaia-mermaid-fingerprint: sha256={fingerprint} -->",
    ))
    return header + "\n" + svg + "\n"


def run_mermaid(sources: dict[str, str], work: Path) -> dict[str, str]:
    """Draws each filled source (name -> Mermaid text) with the Mermaid CLI in Docker; name -> SVG."""
    (work / "puppeteer.json").write_text(json.dumps(PUPPETEER), encoding="utf-8")
    (work / "mermaid.json").write_text(json.dumps(mermaid_config(), indent=1), encoding="utf-8")
    for name, text in sources.items():
        (work / f"{name}.mmd").write_text(text, encoding="utf-8")
    work.chmod(0o777)  # the image's user writes the SVGs here
    for path in work.iterdir():
        path.chmod(0o666)
    # One container for all diagrams, so that Chromium's start-up is paid once per diagram only.
    script = " && ".join(
        f"/home/mermaidcli/node_modules/.bin/mmdc -p /data/puppeteer.json -c /data/mermaid.json -i /data/{name}.mmd -o /data/{name}.svg --quiet"
        for name in sources)
    result = subprocess.run(["docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{work}:/data", MERMAID_IMAGE,
                             "-c", script], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(f"render_diagrams: the Mermaid CLI failed:\n{result.stdout}{result.stderr}")
    return {name: (work / f"{name}.svg").read_text(encoding="utf-8") for name in sources}


def write_png(svg_path: Path, directory: Path) -> None:
    """A PNG per colour scheme, for looking at the result (headless Chromium in the same image)."""
    directory.mkdir(parents=True, exist_ok=True)
    for scheme in ("light", "dark"):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            text = svg_path.read_text(encoding="utf-8")
            if scheme == "dark":  # a headless Chromium has no switch for the media query: apply it always
                text = text.replace("@media (prefers-color-scheme:dark)", "@media all")
            (work / "in.svg").write_text(text, encoding="utf-8")
            work.chmod(0o777)
            (work / "in.svg").chmod(0o666)
            viewbox = re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"', svg_path.read_text(encoding="utf-8"))
            width, height = (int(float(v)) for v in viewbox.groups())
            script = (f"chromium --no-sandbox --headless --disable-gpu --hide-scrollbars "
                      f"--screenshot=/data/out.png --window-size={width},{height} file:///data/in.svg")
            subprocess.run(["docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{work}:/data", MERMAID_IMAGE,
                            "-c", script], capture_output=True, text=True)
            if (work / "out.png").exists():
                shutil.copy(work / "out.png", directory / f"{svg_path.stem}-{scheme}.png")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="draw every diagram again")
    parser.add_argument("--png", metavar="DIR", help="also write light and dark PNGs of the SVGs into DIR")
    args = parser.parse_args(argv)
    try:
        all_texts = {lang: site.load_texts(lang) for lang in site.LANGUAGES}
        renders = site.arch_renders(all_texts)
        differ = site.check_arch_doc(all_texts[site.LANGUAGES[1]])
        if differ:
            raise site.SiteError("\n".join(differ))
    except site.SiteError as exc:
        print(f"render_diagrams: {exc}", file=sys.stderr)
        return 1
    todo = {}
    for path, template, source in renders:
        found = site.FINGERPRINT.search(path.read_text(encoding="utf-8")) if path.is_file() else None
        if args.force or not found or found.group(1) != site.arch_fingerprint(source):
            todo[path] = (source, site.arch_fingerprint(source))
    if todo:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            drawn = run_mermaid({path.stem: source for path, (source, _) in todo.items()}, work)
        for path, (source, fingerprint) in todo.items():
            text = post_process(drawn[path.stem], fingerprint, site.rel(path))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
            print(f"wrote {site.rel(path)}")
    else:
        print("every architecture diagram is up to date")
    if args.png:
        for path, _, _ in renders:
            write_png(path, Path(args.png))
    return 0


if __name__ == "__main__":
    sys.exit(main())
