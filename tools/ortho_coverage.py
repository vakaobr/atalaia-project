#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes controller/console/src/components/ortho-coverage.js: where each open orthophoto of the field-map
page has pictures (decision MF-66), as each country's land, simplified.

    python3 tools/ortho_coverage.py ne_10m_admin_0_countries.geojson

The input is Natural Earth's 1:10m admin-0 countries (public domain), e.g.
https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson
(not kept in this repository). Each country's outer rings inside its orthophoto's region are kept, islands under
MIN_KM2 dropped, and each ring simplified with Douglas-Peucker to TOLERANCE degrees (about 1 km), at three
decimals. Needs only the standard library.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

TOLERANCE = 0.01  # degrees
MIN_KM2 = 5.0
OUT = Path(__file__).resolve().parent.parent / "controller/console/src/components/ortho-coverage.js"
# Natural Earth's ADM0_A3, the box a ring must lie in (west, south, east, north), and what is kept.
REGIONS = {
    "PRT": ((-10.0, 36.5, -6.0, 42.5), "mainland Portugal"),
    "ESP": ((-19.0, 27.0, 5.0, 44.0), "Spain (mainland, the Balearic and Canary Islands, Ceuta and Melilla)"),
    "FRA": ((-6.0, 41.0, 10.0, 52.0), "metropolitan France and Corsica"),
    "NLD": ((3.0, 50.5, 8.0, 54.0), "the European Netherlands"),
}


def simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        best, at = 0.0, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            d = math.hypot(px - ax, py - ay) if length == 0 else abs(dy * px - dx * py + bx * ay - by * ax) / length
            if d > best:
                best, at = d, i
        if best > tol and at > 0:
            keep[at] = True
            stack += [(a, at), (at, b)]
    return [p for p, k in zip(pts, keep) if k]


def area_km2(ring: list) -> float:
    lat0 = sum(p[1] for p in ring) / len(ring)
    kx, ky = 111.32 * math.cos(math.radians(lat0)), 110.57
    s = 0.0
    for i, (x1, y1) in enumerate(ring):
        x2, y2 = ring[(i + 1) % len(ring)]
        s += x1 * kx * y2 * ky - x2 * kx * y1 * ky
    return abs(s) / 2


def num(v: float) -> str:
    return ("%.3f" % v).rstrip("0").rstrip(".")


def main(src: str) -> int:
    data = json.loads(Path(src).read_text(encoding="utf-8"))
    rings: dict[str, list] = {}
    for f in data["features"]:
        iso = f["properties"].get("ADM0_A3")
        if iso not in REGIONS:
            continue
        (w, s, e, n), _ = REGIONS[iso]
        g = f["geometry"]
        for poly in g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]:
            outer = poly[0]
            xs, ys = [p[0] for p in outer], [p[1] for p in outer]
            if min(xs) < w or max(xs) > e or min(ys) < s or max(ys) > n or area_km2(outer) < MIN_KM2:
                continue
            r = simplify([(p[0], p[1]) for p in outer], TOLERANCE)
            if r[0] == r[-1]:
                r = r[:-1]
            if len(r) >= 3:
                rings.setdefault(iso, []).append(r)
    # REUSE-IgnoreStart (the generated file's header, not this file's licence)
    lines = [
        "// SPDX-FileCopyrightText: 2026 The Atalaia contributors",
        "// SPDX-License-Identifier: GPL-3.0-or-later",
        "//",
        "// Where each open orthophoto of ortho-sources.js has pictures (decision MF-66): each country's land as",
        "// rings of [longitude, latitude, longitude, latitude, ...] in degrees (WGS 84), from Natural Earth's",
        "// 1:10m admin-0 countries (public domain, naturalearthdata.com), simplified to about 1 km without the",
        "// islands under 5 km². Written by tools/ortho_coverage.py; do not edit by hand.",
        "",
        "export const COVERAGE = {",
    ]
    # REUSE-IgnoreEnd
    for iso, (_, what) in REGIONS.items():
        lines += [f"    // {what}", f"    {iso}: ["]
        for r in rings.get(iso, []):
            parts = [num(v) for p in r for v in p]
            cur = "        ["
            for i, p in enumerate(parts):
                piece = p + ("," if i < len(parts) - 1 else "")
                if len(cur) + len(piece) > 116:
                    lines.append(cur)
                    cur = "         "
                cur += piece
            lines.append(cur + "],")
        lines.append("    ],")
    lines.append("};")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for iso in REGIONS:
        print(f"{iso}: {len(rings.get(iso, []))} rings, {sum(len(r) for r in rings.get(iso, []))} points")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
