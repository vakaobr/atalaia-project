#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Draws iOS's app icon and launch image from the Android icon's sources.

    python3 app/tool/gen_ios_icons.py        (needs Pillow)

The watchtower's three polygons and the two colours are those of
android/app/src/main/res/drawable/ic_launcher_foreground.xml and
values/colors.xml (keep them in step). Writes every size listed in
ios/Runner/Assets.xcassets/AppIcon.appiconset/Contents.json (opaque, as
App Store icons must be) and the launch image's three scales (the mark
alone, on a transparent ground; LaunchScreen.storyboard paints the ground).
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw

BG = (0x1B, 0x2A, 0x1E)
MARK = (0xE8, 0xB3, 0x41)
# Android's 108 dp canvas; the mark sits inside the 66 dp safe zone.
POLYS = [
    [(54, 26), (72, 40), (36, 40)],
    [(38, 42), (70, 42), (70, 48), (38, 48)],
    [(44, 50), (64, 50), (68, 82), (40, 82)],
]
SS = 4  # supersampling


def draw(size: int, zoom: float, background) -> Image.Image:
    """The mark centred on a size x size canvas, 108 dp scaled by size/108*zoom."""
    big = size * SS
    fill = background + (255,) if background else (0, 0, 0, 0)
    img = Image.new("RGBA", (big, big), fill)
    d = ImageDraw.Draw(img)
    k = big / 108 * zoom
    c = big / 2
    for poly in POLYS:
        d.polygon([(c + (x - 54) * k, c + (y - 54) * k) for x, y in poly], fill=MARK + (255,))
    out = img.resize((size, size), Image.LANCZOS)
    return out.convert("RGB") if background else out


def main() -> None:
    assets = Path(__file__).resolve().parents[1] / "ios" / "Runner" / "Assets.xcassets"
    icons = assets / "AppIcon.appiconset"
    spec = json.loads((icons / "Contents.json").read_text())
    for entry in spec["images"]:
        base = float(entry["size"].split("x")[0])
        px = round(base * float(entry["scale"].rstrip("x")))
        draw(px, 1.25, BG).save(icons / entry["filename"])
    launch = assets / "LaunchImage.imageset"
    for scale, name in ((1, "LaunchImage.png"), (2, "LaunchImage@2x.png"), (3, "LaunchImage@3x.png")):
        w, h = 168 * scale, 185 * scale
        side = max(w, h)
        sq = draw(side, 1.0, None)
        # The 168 x 185 pt image: the mark centred.
        x0, y0 = (side - w) // 2, (side - h) // 2
        sq.crop((x0, y0, x0 + w, y0 + h)).save(launch / name)


if __name__ == "__main__":
    main()
