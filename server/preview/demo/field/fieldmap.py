# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The demo field's plan (a PNG drawn here, no file, no real place) and the place it is given on the map.

The field is invented: a 360 x 270 m rectangle at the origin of the coordinate grid (latitude 0, longitude 0, in the
open sea), so no real land, road or building is shown on it. The plan is what the GM console and the player's view
draw boxes and players on; the georeference (two opposite corners) turns a player's latitude and longitude into a
place on it.
"""

from __future__ import annotations

import math
import struct
import zlib

WIDTH, HEIGHT = 720, 540          # pixels of the plan: 2 px per metre
FIELD_W_M, FIELD_H_M = 360.0, 270.0
M_PER_DEG = 111_320.0
NORTH = FIELD_H_M / M_PER_DEG     # latitude of the plan's top edge (the bottom edge is 0)
EAST = FIELD_W_M / M_PER_DEG      # longitude of the plan's right edge (the left edge is 0)

# Where things are on the plan, as fractions of its width and height (x to the right, y down).
ZONES = {"alpha": (0.24, 0.30), "bravo": (0.50, 0.70), "charlie": (0.78, 0.34)}
BASES = {"red": (0.09, 0.86), "blue": (0.91, 0.14)}

GRASS = (84, 122, 64)
GRASS2 = (92, 131, 70)
TRACK = (170, 150, 112)
WOOD = (52, 86, 48)
WATER = (86, 132, 168)
ZONE_RING = (250, 236, 120)
BASE = {"red": (176, 60, 52), "blue": (52, 96, 176)}


def georef_points() -> list[dict]:
    """Two opposite corners of the plan (north up), the form PUT /api/v1/field/georef takes."""
    return [{"x": 0.0, "y": 0.0, "lat": round(NORTH, 7), "lon": 0.0},
            {"x": 1.0, "y": 1.0, "lat": 0.0, "lon": round(EAST, 7)}]


def to_latlon(x: float, y: float) -> tuple[float, float]:
    return round((1.0 - y) * NORTH, 7), round(x * EAST, 7)


def to_plan(lat: float, lon: float) -> tuple[float, float]:
    return lon / EAST, 1.0 - lat / NORTH


def _chunk(kind: bytes, data: bytes) -> bytes:
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def plan_png() -> bytes:
    """A top-down plan: grass with a mown stripe pattern, a track, a wood, a pond, a ring at each box and a coloured
    base for each team. Plain 8-bit RGB; the controller's own image check (images.py) accepts it."""
    px = bytearray(WIDTH * HEIGHT * 3)

    def put(x: int, y: int, colour: tuple[int, int, int]) -> None:
        if 0 <= x < WIDTH and 0 <= y < HEIGHT:
            i = (y * WIDTH + x) * 3
            px[i:i + 3] = bytes(colour)

    for y in range(HEIGHT):
        for x in range(WIDTH):
            put(x, y, GRASS if (x // 36 + y // 36) % 2 == 0 else GRASS2)
    # a winding track from the red base to the blue base
    for i in range(0, 2000):
        t = i / 2000
        x = (0.09 + 0.82 * t) * WIDTH
        y = (0.86 - 0.72 * t + 0.12 * math.sin(t * 9)) * HEIGHT
        for dx in range(-5, 6):
            for dy in range(-5, 6):
                if dx * dx + dy * dy <= 25:
                    put(int(x) + dx, int(y) + dy, TRACK)
    # a wood and a pond (ellipses)
    for (cx, cy, rx, ry, colour) in ((0.62, 0.20, 0.10, 0.12, WOOD), (0.18, 0.62, 0.07, 0.06, WATER),
                                     (0.40, 0.18, 0.06, 0.09, WOOD)):
        for y in range(HEIGHT):
            for x in range(WIDTH):
                if ((x / WIDTH - cx) / rx) ** 2 + ((y / HEIGHT - cy) / ry) ** 2 <= 1:
                    put(x, y, colour)
    # a ring at each box (the capture area) and a block at each base
    for fx, fy in ZONES.values():
        for a in range(0, 3600):
            ang = a / 10 * math.pi / 180
            for r in (36, 37, 38):
                put(int(fx * WIDTH + r * math.cos(ang)), int(fy * HEIGHT + r * math.sin(ang)), ZONE_RING)
    for team, (fx, fy) in BASES.items():
        for y in range(int(fy * HEIGHT) - 22, int(fy * HEIGHT) + 22):
            for x in range(int(fx * WIDTH) - 22, int(fx * WIDTH) + 22):
                put(x, y, BASE[team])
    raw = b"".join(b"\x00" + bytes(px[y * WIDTH * 3:(y + 1) * WIDTH * 3]) for y in range(HEIGHT))
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", WIDTH, HEIGHT, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))
