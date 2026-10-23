#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes controller/console/src/components/ortho-coverage.js: where each open orthophoto of the field-map
page has pictures (decisions MF-66 and MF-73), as each country's (or each region's) land, simplified.

    python3 tools/ortho_coverage.py ne_10m_admin_0_countries.geojson ne_10m_admin_1_states_provinces.geojson

The inputs are Natural Earth's 1:10m admin-0 countries and admin-1 states and provinces (both public domain),
e.g. https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson
and .../ne_10m_admin_1_states_provinces.geojson (not kept in this repository). A coverage is a list of parts:
a country by its ADM0_A3 (optionally only its rings inside a box), or a state or province by its ISO 3166-2
code (a German Land, a Belgian province). Their outer rings are kept, islands under MIN_KM2 dropped, and each
ring simplified with Douglas-Peucker to TOLERANCE degrees (about 1 km), at three decimals. Needs only the
standard library.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

TOLERANCE = 0.01  # degrees
MIN_KM2 = 5.0
OUT = Path(__file__).resolve().parent.parent / "controller/console/src/components/ortho-coverage.js"
# Each coverage: what it is, and its parts: (ADM0_A3, box or None) for a country, only its rings inside the box
# (west, south, east, north) when one is given, or (ISO 3166-2, None) for a state or province (admin-1).
FLANDERS = [(code, None) for code in ("BE-VAN", "BE-VBR", "BE-VLI", "BE-VOV", "BE-VWV")]
WALLONIA = [(code, None) for code in ("BE-WBR", "BE-WHT", "BE-WLG", "BE-WLX", "BE-WNA")]
REGIONS: dict[str, tuple[str, list]] = {
    "PRT": ("mainland Portugal", [("PRT", (-10.0, 36.5, -6.0, 42.5))]),
    "ESP": ("Spain (mainland, the Balearic and Canary Islands, Ceuta and Melilla)",
            [("ESP", (-19.0, 27.0, 5.0, 44.0))]),
    "FRA": ("France: metropolitan, Corsica, the Antilles, Guiana, Réunion, Mayotte, Saint-Pierre-et-Miquelon",
            [("FRA", None), ("MAF", None), ("BLM", None), ("SPM", None)]),
    "NLD": ("the European Netherlands", [("NLD", (3.0, 50.5, 8.0, 54.0))]),
    "BE_BRU": ("the Brussels-Capital Region", [("BE-BRU", None)]),
    "BE_VLG": ("the Flemish Region (its five provinces)", FLANDERS),
    "BE_WAL": ("the Walloon Region (its five provinces)", WALLONIA),
    "LUX": ("Luxembourg", [("LUX", None)]),
    "CHE": ("Switzerland and Liechtenstein", [("CHE", None), ("LIE", None)]),
    "DE_BE": ("Berlin", [("DE-BE", None)]),
    "DE_BB": ("Brandenburg", [("DE-BB", None)]),
    "DE_BY": ("Bayern", [("DE-BY", None)]),
    "DE_HB": ("Bremen (the city and Bremerhaven)", [("DE-HB", None)]),
    "DE_HE": ("Hessen", [("DE-HE", None)]),
    "DE_MV": ("Mecklenburg-Vorpommern", [("DE-MV", None)]),
    "DE_NW": ("Nordrhein-Westfalen", [("DE-NW", None)]),
    "DE_RP": ("Rheinland-Pfalz", [("DE-RP", None)]),
    "DE_SL": ("Saarland", [("DE-SL", None)]),
    "DE_SN": ("Sachsen", [("DE-SN", None)]),
    "DE_TH": ("Thüringen", [("DE-TH", None)]),
    "POL": ("Poland", [("POL", None)]),
    "CZE": ("Czechia", [("CZE", None)]),
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


def outer_rings(feature: dict) -> list:
    g = feature["geometry"]
    return [poly[0] for poly in (g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]])]


def main(admin0: str, admin1: str) -> int:
    parts: dict[str, list] = {}
    for f in json.loads(Path(admin0).read_text(encoding="utf-8"))["features"]:
        parts.setdefault(f["properties"].get("ADM0_A3"), []).extend(outer_rings(f))
    for f in json.loads(Path(admin1).read_text(encoding="utf-8"))["features"]:
        parts.setdefault(f["properties"].get("iso_3166_2"), []).extend(outer_rings(f))
    rings: dict[str, list] = {}
    for key, (_, wanted) in REGIONS.items():
        for code, box in wanted:
            if code not in parts:
                raise SystemExit(f"{code}: not in Natural Earth's files")
            for outer in parts[code]:
                xs, ys = [p[0] for p in outer], [p[1] for p in outer]
                if box and (min(xs) < box[0] or min(ys) < box[1] or max(xs) > box[2] or max(ys) > box[3]):
                    continue
                if area_km2(outer) < MIN_KM2:
                    continue
                r = simplify([(p[0], p[1]) for p in outer], TOLERANCE)
                if r[0] == r[-1]:
                    r = r[:-1]
                if len(r) >= 3:
                    rings.setdefault(key, []).append(r)
    # REUSE-IgnoreStart (the generated file's header, not this file's licence)
    lines = [
        "// SPDX-FileCopyrightText: 2026 The Atalaia contributors",
        "// SPDX-License-Identifier: GPL-3.0-or-later",
        "//",
        "// Where each open orthophoto of ortho-sources.js has pictures (decisions MF-66 and MF-73): each country's",
        "// or region's land as rings of [longitude, latitude, longitude, latitude, ...] in degrees (WGS 84), from",
        "// Natural Earth's 1:10m admin-0 countries and admin-1 states and provinces (public domain,",
        "// naturalearthdata.com), simplified to about 1 km without the islands under 5 km². Written by",
        "// tools/ortho_coverage.py; do not edit by hand.",
        "",
        "export const COVERAGE = {",
    ]
    # REUSE-IgnoreEnd
    for key, (what, _) in REGIONS.items():
        lines += [f"    // {what}", f"    {key}: ["]
        for r in rings.get(key, []):
            parts_ = [num(v) for p in r for v in p]
            cur = "        ["
            for i, p in enumerate(parts_):
                piece = p + ("," if i < len(parts_) - 1 else "")
                if len(cur) + len(piece) > 116:
                    lines.append(cur)
                    cur = "         "
                cur += piece
            lines.append(cur + "],")
        lines.append("    ],")
    lines.append("};")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for key in REGIONS:
        print(f"{key}: {len(rings.get(key, []))} rings, {sum(len(r) for r in rings.get(key, []))} points")
    print(f"{OUT.name}: {OUT.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
