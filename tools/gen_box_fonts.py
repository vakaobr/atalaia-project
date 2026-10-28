#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Makes the Field Box's screen fonts (firmware/esp32/main/fonts/lv_font_atalaia_*.c).

They are LVGL's built-in Montserrat Medium fonts (sizes 14, 20, 28 and 48, 4 bits per pixel,
ASCII, the degree sign, the bullet and LVGL's symbols) with the letters European Portuguese
and German need added (decisions BN-14 and P5H-4: box screens in Portuguese and German), and
the Han letters and full-width punctuation of the box's Traditional Chinese texts from Noto
Sans TC Medium (decision P5K-3). The command is LVGL's own
(lvgl/scripts/built_in_font/built_in_font_gen.py, LVGL 9.2.2) with more ranges and the glyphs
compressed (lv_font_conv's RLE, LV_USE_FONT_COMPRESSED in lv_conf.h; lossless, so every ASCII
glyph, and so every English screen, is drawn exactly as before). clang-format (tools/format.sh)
then rewraps the licence header the way the committed files have it.

Chinese costs flash (about 90, 150, 250 and 480 bytes a letter at 14, 20, 28 and 48 px,
compressed; half as much again without), so the fonts carry exactly the letters
firmware/esp32/main/box_text.c uses, read from its table: every
one at 14, 20 and 28 px (the TFT's texts and the whole OLED), and at 48 px only those of the
texts the TFT draws at 48 (AT_48). The built-in modes' screen templates
(modes/*/assets/screens/*.yaml) add the Chinese letters of their labels, each in the font its
label is drawn with only (decision P5H-12), and the built-in scripts' (node.lua: the Medic
Kit's refusals, shown as data) theirs in 14, 20 and 28 px. The 48 px font falls back on the 28 px one, so a
letter it lacks is drawn smaller, never as an empty box; the host tests fail when any screen
needs that (test_screens.c and test_oled_screens.c check every letter of every label against
its font). The generator also writes firmware/esp32/main/box_fonts_cjk.h, each font's Chinese
letters as a C table: a template's text keeps a letter its label's font has and shows any other
as '?' (screen_template_fold_text); and the same tables as JSON for the GM console
(controller/console/src/box-glyphs.json: the Latin ranges and each font's Chinese letters), which
warns when a team, preset or field name has a letter the box's fonts lack (decision PKE-3).

Needs Node.js with lv_font_conv 1.5.2 (npm install lv_font_conv@1.5.2), LVGL 9.2.2's
scripts/built_in_font/ (Montserrat-Medium.ttf, FontAwesome5-Solid+Brands+Regular.woff) and
Noto Sans TC 2.004 Medium (notofonts/noto-cjk, tag Sans2.004, Sans/SubsetOTF/TC/
NotoSansTC-Medium.otf, SHA-256 in NOTO_SHA256):

    python3 tools/gen_box_fonts.py --lv-font-conv node_modules/.bin/lv_font_conv \\
        --fonts <lvgl>/scripts/built_in_font --cjk-font NotoSansTC-Medium.otf

    python3 tools/gen_box_fonts.py --check

--check (in tools/check.sh, needs only Python) fails when a box text or a built-in template uses
a letter the fonts lack, the fonts carry a Chinese letter no text uses, or box_fonts_cjk.h is not
the fonts' letters or box-glyphs.json is not the same tables: change box_text.c or the template,
then make the fonts again.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import i18n_check  # noqa: E402  (box_text.c's reader)

OUT = REPO / "firmware" / "esp32" / "main" / "fonts"
SIZES = (14, 20, 28, 48)
# LVGL's line height and baseline for each size. The accents and the cedilla would make the lines
# 1-3 pixels taller; kept as LVGL's, every English screen keeps its layout to the pixel, and an
# accent on a capital or a cedilla may reach a pixel or two past its line. Han letters fit the
# line (Noto Sans TC's ideographic box is the font size).
METRICS = {14: (16, 3), 20: (22, 4), 28: (30, 5), 48: (52, 9)}
# ASCII, degree sign and bullet as LVGL's built-in fonts; then a and o ordinals, the middle dot
# and the accented letters of Portuguese; then the umlauts and the sharp s of German (P5H-4).
LATIN = "0x20-0x7F,0xB0,0x2022,0xAA,0xB7,0xBA,0xC0-0xC3,0xC7,0xC9,0xCA,0xCD,0xD3-0xD5,0xDA," \
        "0xE0-0xE3,0xE7,0xE9,0xEA,0xED,0xF3-0xF5,0xFA," \
        "0xC4,0xD6,0xDC,0xDF,0xE4,0xF6,0xFC"
# LVGL's built-in symbols (LV_SYMBOL_*), as built_in_font_gen.py lists them.
SYMBOLS = ("61441,61448,61451,61452,61452,61453,61457,61459,61461,61465,61468,61473,61478,61479,"
           "61480,61502,61507,61512,61515,61516,61517,61521,61522,61523,61524,61543,61544,61550,"
           "61552,61553,61556,61559,61560,61561,61563,61587,61589,61636,61637,61639,61641,61664,"
           "61671,61674,61683,61724,61732,61787,61931,62016,62017,62018,62019,62020,62087,62099,"
           "62212,62189,62810,63426,63650")
# The box texts the TFT draws at 48 px (screen_renderer.c: the results, pause, a free zone, the
# ready and waiting screens, the timer without a limit). Their letters also go into the 48 px
# font; every other Chinese letter is in 14, 20 and 28 px only (P5K-3).
AT_48 = ("TX_DEFUSED_UP", "TX_EXPLODED_UP", "TX_PAUSED_UP", "TX_NEUTRAL_UP", "TX_NEXT_GAME",
         "TX_GAME_N", "TX_NO_LIMIT")
# The 48 px font's fallback: a letter it lacks comes from the 28 px font (LVGL 9's
# lv_font_t.fallback), smaller rather than an empty box.
FALLBACK = {48: 28}
NOTO_SHA256 = "bf206dca0975779bac71cb49a037a364156ca98a0c431b1b7d6b29fb8952ac7e"
# The fonts' Chinese letters as C tables (P5H-12): a template keeps a letter its label's font has.
CJK_TABLE = "firmware/esp32/main/box_fonts_cjk.h"
# The same tables for the GM console (PKE-3): which letters of a name the box's fonts can draw.
GLYPHS_JSON = "controller/console/src/box-glyphs.json"
CJK_HEADER = """\
/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Generated by tools/gen_box_fonts.py with the fonts (main/fonts): the Chinese
 * letters each box font carries, sorted, for screen_template_fold_text (a
 * template's text keeps a letter its label's font has; the 48 px font falls
 * back on the 28 px one). Do not edit.
 */
/* clang-format off */
#ifndef ATALAIA_BOX_FONTS_CJK_H
#define ATALAIA_BOX_FONTS_CJK_H

#include <stdint.h>
"""
HEADER = """\
/*
 * SPDX-FileCopyrightText: 2011 The Montserrat Project Authors (https://github.com/JulietaUla/Montserrat)
 * SPDX-FileCopyrightText: Fonticons, Inc. (https://fontawesome.com)
 * SPDX-FileCopyrightText: 2014-2021 Adobe (http://www.adobe.com/)
 * SPDX-License-Identifier: OFL-1.1
 *
 * Generated by tools/gen_box_fonts.py (lv_font_conv 1.5.2) from LVGL 9.2.2's
 * Montserrat-Medium.ttf and FontAwesome5-Solid+Brands+Regular.woff, and Noto Sans TC
 * 2.004 Medium for the letters of the box's Chinese texts. Do not edit.
 */
/* clang-format off */
"""


def latin_codepoints() -> set[int]:
    out: set[int] = set()
    for part in LATIN.split(","):
        lo, _, hi = part.partition("-")
        out.update(range(int(lo, 16), int(hi or lo, 16) + 1))
    return out


def is_cjk(cp: int) -> bool:
    """Han letters, CJK punctuation and the full-width forms: Noto Sans TC's part."""
    return 0x2E80 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0xFF00 <= cp <= 0xFFEF


def font_px(size: object) -> int:
    """The font a template label's font_size draws with (font_for in screen_template.c: the
    nearest; no size is 20)."""
    px = size if isinstance(size, int) and not isinstance(size, bool) and size > 0 else 20
    return 14 if px <= 16 else 20 if px <= 24 else 28 if px <= 38 else 48


def template_letters(root: Path = REPO) -> tuple[dict[int, set[int]], list[str]]:
    """The Chinese letters of the built-in modes' screen templates (modes/*/assets/screens/*.yaml,
    the ones builtin_screens.cmake puts in the image), per font: each label's at the size it is
    drawn (decision P5H-12; a template's other letters are folded, screen_template.c), and
    those of the built-in scripts (node.lua) at 14, 20 and 28 px."""
    out: dict[int, set[int]] = {size: set() for size in SIZES}
    problems = []

    def walk(widgets: object, where: str) -> None:
        for w in widgets if isinstance(widgets, list) else []:
            if not isinstance(w, dict):
                continue
            style = w.get("style") if isinstance(w.get("style"), dict) else {}
            if w.get("type") == "label" and isinstance(w.get("text"), str):
                for ch in w["text"]:
                    if is_cjk(ord(ch)):
                        out[font_px(style.get("font_size"))].add(ord(ch))
            walk(w.get("children"), where)

    for path in sorted((root / "modes").glob("*/assets/screens/*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            problems.append(f"{path.relative_to(root).as_posix()}: {exc}")
            continue
        walk(data.get("layout") if isinstance(data, dict) else None, path.name)
    # A built-in script's own Chinese texts (the Medic Kit's refusals) reach a template's label
    # and the OLED as data, at any size: in 14, 20 and 28 px, as box_text.c's.
    for path in sorted((root / "modes").glob("*/node.lua")):
        for ch in path.read_text(encoding="utf-8"):
            if is_cjk(ord(ch)):
                for size in (14, 20, 28):
                    out[size].add(ord(ch))
    return out, problems


def needed(root: Path = REPO) -> tuple[dict[int, set[int]], list[str]]:
    """The letters each size must have beyond LATIN, and the problems: a letter of box_text.c
    neither in LATIN nor CJK (add it to LATIN and in_fonts_c3, screen_template.c). box_text.c's
    Chinese letters are in 14, 20 and 28 px, and at 48 those of AT_48 (P5K-3); the built-in
    templates' in the size each label draws them (P5H-12)."""
    box = i18n_check.read_box(root)
    latin = latin_codepoints()
    every: set[int] = set()
    big: set[int] = set()
    problems = []
    for lang, table in box.tables.items():
        for key, text in table.items():
            for ch in text:
                cp = ord(ch)
                if cp in latin:
                    continue
                if not is_cjk(cp):
                    problems.append(f"box_text.c: {key} ({lang}) uses {ch!r} U+{cp:04X}, which is "
                                    "in no font: add it to LATIN in tools/gen_box_fonts.py")
                    continue
                every.add(cp)
                if key in AT_48:
                    big.add(cp)
    templates, more = template_letters(root)
    want = {14: set(every), 20: set(every), 28: set(every), 48: set(big)}
    for size in SIZES:
        want[size] |= templates[size]
    return want, problems + more


def table_header(want: dict[int, set[int]]) -> str:
    """firmware/esp32/main/box_fonts_cjk.h: the Chinese letters of each font, for
    screen_template_fold_text (a template keeps a letter its label's font has, else '?')."""
    out = [CJK_HEADER]
    for size in SIZES:
        cps = sorted(want[size])
        out.append(f"/* {len(cps)} at {size} px */\n"
                   f"static const uint16_t box_fonts_cjk_{size}[] = {{")
        for i in range(0, len(cps), 10):
            out.append("    " + " ".join(f"0x{cp:04X}," for cp in cps[i:i + 10]))
        out.append("};")
    out.append("\n#endif /* ATALAIA_BOX_FONTS_CJK_H */")
    return "\n".join(out) + "\n"


def latin_ranges() -> list[list[int]]:
    """LATIN as [first, last] code point ranges."""
    out = []
    for part in LATIN.split(","):
        lo, _, hi = part.partition("-")
        out.append([int(lo, 16), int(hi or lo, 16)])
    return out


def glyphs_json(want: dict[int, set[int]]) -> str:
    """controller/console/src/box-glyphs.json: what the box's fonts can draw, for the console's warning
    about names with letters they lack (a letter in LATIN is in every font; a Chinese one is in the
    fonts listed under its code point)."""
    desc = ("The letters of the Field Box's fonts (generated by tools/gen_box_fonts.py with the fonts; do not edit): "
            "latin is the code point ranges every font has, cjk each font size's Han letters and "
            "full-width punctuation as code points (the 48 px font falls back on the 28 px one). The console "
            "(components/box-glyphs.js) warns about a name with a letter these tables lack.")
    lines = ["{", f' "description": {json.dumps(desc, ensure_ascii=False)},',
             f' "latin": {json.dumps(latin_ranges())},', ' "cjk": {']
    for i, size in enumerate(SIZES):
        comma = "," if i < len(SIZES) - 1 else ""
        lines.append(f'  "{size}": {json.dumps(sorted(want[size]))}{comma}')
    lines += [" }", "}"]
    return "\n".join(lines) + "\n"


def font_codepoints(path: Path) -> set[int]:
    """The code points of an lv_font_conv font source: its cmaps (ranges and sparse lists)."""
    text = path.read_text(encoding="utf-8")
    lists = {m.group(1): [int(x, 0) for x in re.findall(r"0x[0-9a-fA-F]+", m.group(2))]
             for m in re.finditer(r"static const uint16_t (unicode_list_\d+)\[\] = \{(.*?)\};",
                                  text, re.S)}
    out: set[int] = set()
    for m in re.finditer(r"\.range_start = (\d+), \.range_length = (\d+),.*?"
                         r"\.unicode_list = (\w+),", text, re.S):
        start, length, ulist = int(m.group(1)), int(m.group(2)), m.group(3)
        if ulist == "NULL":
            out.update(range(start, start + length))
        else:
            out.update(start + ofs for ofs in lists[ulist])
    return out


def check(root: Path = REPO, out=sys.stdout) -> int:
    want, problems = needed(root)
    header = root / CJK_TABLE
    if not header.is_file() or header.read_text(encoding="utf-8") != table_header(want):
        problems.append(f"{CJK_TABLE} is not the fonts' Chinese letters: make the fonts again "
                        "(tools/gen_box_fonts.py)")
    glyphs = root / GLYPHS_JSON
    if not glyphs.is_file() or glyphs.read_text(encoding="utf-8") != glyphs_json(want):
        problems.append(f"{GLYPHS_JSON} is not the fonts' letters: make the fonts again "
                        "(tools/gen_box_fonts.py)")
    for size in SIZES:
        path = root / "firmware" / "esp32" / "main" / "fonts" / f"lv_font_atalaia_{size}.c"
        have = {cp for cp in font_codepoints(path) if is_cjk(cp)}
        for cp in sorted(want[size] - have):
            problems.append(f"{path.name}: lacks {chr(cp)} U+{cp:04X}, which a box text or a "
                            f"built-in template uses at {size} px: make the fonts again "
                            "(tools/gen_box_fonts.py)")
        for cp in sorted(have - want[size]):
            problems.append(f"{path.name}: has {chr(cp)} U+{cp:04X}, which no box text or "
                            f"built-in template uses at {size} px: make the fonts again "
                            "(tools/gen_box_fonts.py)")
    for p in problems:
        print(f"gen_box_fonts: {p}", file=sys.stderr)
    if problems:
        return 1
    print("gen_box_fonts: the fonts have every letter of the box texts and the built-in templates, "
          "and no Chinese letter more (" + ", ".join(f"{s} px: {len(want[s])}" for s in SIZES) + ")",
          file=out)
    return 0


def generate(conv: str, fonts: Path, cjk_font: Path) -> int:
    digest = hashlib.sha256(cjk_font.read_bytes()).hexdigest()
    if digest != NOTO_SHA256:
        print(f"gen_box_fonts: {cjk_font} is not Noto Sans TC 2.004 Medium (SHA-256 {digest})",
              file=sys.stderr)
        return 1
    want, problems = needed()
    if problems:
        for p in problems:
            print(f"gen_box_fonts: {p}", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        name = f"lv_font_atalaia_{size}"
        cjk = ",".join(f"0x{cp:X}" for cp in sorted(want[size]))
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / f"{name}.c"
            # Compressed (RLE, no prefilter): the Chinese letters cost 117 KB uncompressed and the
            # image had 13% of its slot free; compressed, every font is smaller (P5K-3).
            cmd = [conv, "--no-prefilter", "--bpp", "4",
                   "--size", str(size), "--font", str(fonts / "Montserrat-Medium.ttf"),
                   "-r", LATIN, "--font",
                   str(fonts / "FontAwesome5-Solid+Brands+Regular.woff"),
                   "-r", SYMBOLS]
            if cjk:
                cmd += ["--font", str(cjk_font), "-r", cjk]
            cmd += ["--format", "lvgl", "-o", str(raw), "--force-fast-kern-format"]
            subprocess.run(cmd, check=True)
            text = raw.read_text(encoding="utf-8")
        # The include as LVGL's own fonts, and no tool comment with the local paths.
        start = text.index("#ifdef LV_LVGL_H_INCLUDE_SIMPLE")
        end = text.index("#endif", start) + len("#endif")
        text = '#include "lvgl.h"' + text[end:]
        # LVGL 9 has no glyph cache in the font descriptor (as its own font sources).
        text = text.replace("static  lv_font_fmt_txt_glyph_cache_t cache;\n", "")
        text = text.replace("#if LV_VERSION_CHECK(8, 0, 0)\n    .cache = &cache\n#endif\n", "")
        text = text.replace("#if LV_VERSION_CHECK(8, 0, 0)", "#if LVGL_VERSION_MAJOR >= 8")
        line, base = METRICS[size]
        text = re.sub(r"\.line_height = \d+,", f".line_height = {line},", text)
        text = re.sub(r"\.base_line = \d+,", f".base_line = {base},", text)
        if size in FALLBACK:
            other = f"lv_font_atalaia_{FALLBACK[size]}"
            anchor = "\n/*-----------------\n *  PUBLIC FONT"
            text = text.replace(anchor, f"\n/*A letter this font lacks: from {other}.*/\n"
                                        f"extern const lv_font_t {other};\n" + anchor, 1)
            text = text.replace("    .dsc = &font_dsc ",
                                f"    .fallback = &{other},\n    .dsc = &font_dsc ", 1)
            if f".fallback = &{other}" not in text:
                print(f"gen_box_fonts: {name}: no place for the fallback", file=sys.stderr)
                return 1
        (OUT / f"{name}.c").write_text(HEADER + text, encoding="utf-8")
        print(f"{name}.c: {len(want[size])} Chinese letters")
    (REPO / CJK_TABLE).write_text(table_header(want), encoding="utf-8")
    (REPO / GLYPHS_JSON).write_text(glyphs_json(want), encoding="utf-8")
    return check()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="only check that the fonts have the box texts' letters (no Node.js)")
    ap.add_argument("--tables", action="store_true",
                    help="only write the letter tables (box_fonts_cjk.h, box-glyphs.json) from the box "
                         "texts and templates, when the fonts already have the letters (no Node.js)")
    ap.add_argument("--lv-font-conv", help="the lv_font_conv program")
    ap.add_argument("--fonts", type=Path, help="LVGL's scripts/built_in_font")
    ap.add_argument("--cjk-font", type=Path, help="NotoSansTC-Medium.otf (Noto Sans TC 2.004)")
    ap.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)  # the tests' copies
    args = ap.parse_args()
    if args.check:
        return check(args.root)
    if args.tables:
        want, problems = needed(args.root)
        for p in problems:
            print(f"gen_box_fonts: {p}", file=sys.stderr)
        if problems:
            return 1
        (args.root / CJK_TABLE).write_text(table_header(want), encoding="utf-8")
        (args.root / GLYPHS_JSON).write_text(glyphs_json(want), encoding="utf-8")
        return check(args.root)
    if not (args.lv_font_conv and args.fonts and args.cjk_font):
        ap.error("--lv-font-conv, --fonts and --cjk-font are needed to make the fonts")
    return generate(args.lv_font_conv, args.fonts, args.cjk_font)


if __name__ == "__main__":
    sys.exit(main())
