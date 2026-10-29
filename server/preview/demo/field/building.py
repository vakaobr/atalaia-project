# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The demo's second scenario: an invented three-storey building (decisions DEMO-10 to DEMO-18).

Three floor plans drawn here (PNG, no file, nothing copied from anywhere), a georeference of their own, the rooms,
the stairwell and the BLE beacons that the director registers on the controller. Every level has the same shape,
so one set of control points (level 0's, shared by the other levels as ML-6 says) places all three:

    +--------------+--+--------------+      four rooms a level, a cross-shaped corridor, the stairwell in the
    |  north-west  |  |  north-east  |      middle (the same place on every level). A room's door is its edge
    |  room        |  |  room        |      on the corridor; the corridor is the band y = 0.44 .. 0.56 (and
    +----  door ---+  +--- door -----+      x = 0.44 .. 0.56), so a walk from a room to the stairs is a straight
    |      corridor  STAIRS  corridor |      line to the corridor's middle line and one along it.
    +----  door ---+  +--- door -----+
    |  south-west  |  |  south-east  |
    |  room        |  |  room        |
    +--------------+--+--------------+

The building is 48 x 36 m at 15 px per metre, in the open sea at latitude 0.001, longitude 0.002: no real land,
road or building. Level names are in the controller's language (pt-PT here): the console translates none.
"""

from __future__ import annotations

import struct
import zlib
from typing import Optional

WIDTH, HEIGHT = 720, 540
FIELD_W_M, FIELD_H_M = 48.0, 36.0
M_PER_DEG = 111_320.0
LAT_BOTTOM, LON_LEFT = 0.0010, 0.0020
LAT_TOP = LAT_BOTTOM + FIELD_H_M / M_PER_DEG
LON_RIGHT = LON_LEFT + FIELD_W_M / M_PER_DEG

LEVEL_NAMES = ["R/C", "1.º andar", "2.º andar"]
# What the plans say about themselves (the bitmap font has capitals, digits, "." "/" and "-" only).
LEVEL_TITLES = ["R/C", "1. ANDAR", "2. ANDAR"]
STAIRS = (0.5, 0.5)
BAND = 0.5                         # the corridor's middle line, for both axes

# room key -> (name on each level, centre x, centre y, wing); a room's door is on the corridor at its centre's x.
ROOMS = {
    "nw": (("Entrada", "Sala A", "Sala C"), 0.24, 0.26, "Ala norte"),
    "ne": (("Bar", "Sala B", "Gabinete"), 0.76, 0.26, "Ala norte"),
    "sw": (("Oficina", "Arquivo", "Sotao"), 0.24, 0.74, "Ala sul"),
    "se": (("Arrumos", "Cozinha", "Sala D"), 0.76, 0.74, "Ala sul"),
}
# The boxes, one a level: alpha on R/C in "Oficina", bravo on the 1.º andar in "Sala B", charlie on the 2.º andar
# in "Sala C", as (room, level).
BOX_PLACES = {"alpha": ("sw", 0), "bravo": ("ne", 1), "charlie": ("nw", 2)}
# Where each team starts: red in R/C's "Arrumos", blue on the top floor in "Gabinete".
BASES = {"red": ("se", 0), "blue": ("ne", 2)}
BEACON_UUID = "A7A11A1A-0B1D-4C0D-9E57-00A7A11A0001"   # invented

FLOOR = [(236, 226, 205), (214, 226, 238), (219, 235, 217)]
WALL = (58, 52, 48)
CORRIDOR = (247, 244, 236)
STAIR = (170, 150, 112)
TEXT = (40, 40, 40)

# 5 x 7 capitals, digits and a few marks: seven rows of five characters, "#" a lit pixel.
_FONT_ROWS = {
    "A": ".###. #...# #...# ##### #...# #...# #...#", "B": "####. #...# #...# ####. #...# #...# ####.",
    "C": ".#### #.... #.... #.... #.... #.... .####", "D": "####. #...# #...# #...# #...# #...# ####.",
    "E": "##### #.... #.... ####. #.... #.... #####", "F": "##### #.... #.... ####. #.... #.... #....",
    "G": ".#### #.... #.... #.### #...# #...# .###.", "H": "#...# #...# #...# ##### #...# #...# #...#",
    "I": "##### ..#.. ..#.. ..#.. ..#.. ..#.. #####", "J": "..### ...#. ...#. ...#. ...#. #..#. .##..",
    "K": "#...# #..#. #.#.. ##... #.#.. #..#. #...#", "L": "#.... #.... #.... #.... #.... #.... #####",
    "M": "#...# ##.## #.#.# #.#.# #...# #...# #...#", "N": "#...# ##..# #.#.# #..## #...# #...# #...#",
    "O": ".###. #...# #...# #...# #...# #...# .###.", "P": "####. #...# #...# ####. #.... #.... #....",
    "Q": ".###. #...# #...# #...# #.#.# #..#. .##.#", "R": "####. #...# #...# ####. #.#.. #..#. #...#",
    "S": ".#### #.... #.... .###. ....# ....# ####.", "T": "##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
    "U": "#...# #...# #...# #...# #...# #...# .###.", "V": "#...# #...# #...# #...# #...# .#.#. ..#..",
    "W": "#...# #...# #...# #.#.# #.#.# ##.## #...#", "X": "#...# #...# .#.#. ..#.. .#.#. #...# #...#",
    "Y": "#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..", "Z": "##### ....# ...#. ..#.. .#... #.... #####",
    "0": ".###. #...# #..## #.#.# ##..# #...# .###.", "1": "..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.",
    "2": ".###. #...# ....# ...#. ..#.. .#... #####", "3": "####. ....# ....# .###. ....# ....# ####.",
    "4": "...#. ..##. .#.#. #..#. ##### ...#. ...#.", "5": "##### #.... ####. ....# ....# #...# .###.",
    "6": ".###. #.... #.... ####. #...# #...# .###.", "7": "##### ....# ...#. ..#.. .#... .#... .#...",
    "8": ".###. #...# #...# .###. #...# #...# .###.", "9": ".###. #...# #...# .#### ....# ....# .###.",
    ".": "..... ..... ..... ..... ..... .##.. .##..", "/": "....# ...#. ...#. ..#.. .#... .#... #....",
    "-": "..... ..... ..... ##### ..... ..... .....", " ": "..... ..... ..... ..... ..... ..... .....",
}
FONT = {ch: rows.split() for ch, rows in _FONT_ROWS.items()}
assert all(len(rows) == 7 and all(len(r) == 5 for r in rows) for rows in FONT.values())


class Canvas:
    def __init__(self, w: int, h: int, colour: tuple[int, int, int]) -> None:
        self.w, self.h = w, h
        self.px = bytearray(bytes(colour) * (w * h))

    def rect(self, x0: int, y0: int, x1: int, y1: int, colour: tuple[int, int, int]) -> None:
        """Fills x0 <= x < x1, y0 <= y < y1."""
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.w, x1), min(self.h, y1)
        if x1 <= x0:
            return
        row = bytes(colour) * (x1 - x0)
        for y in range(y0, y1):
            i = (y * self.w + x0) * 3
            self.px[i:i + len(row)] = row

    def frame(self, x0: int, y0: int, x1: int, y1: int, t: int, colour: tuple[int, int, int]) -> None:
        self.rect(x0, y0, x1, y0 + t, colour)
        self.rect(x0, y1 - t, x1, y1, colour)
        self.rect(x0, y0, x0 + t, y1, colour)
        self.rect(x1 - t, y0, x1, y1, colour)

    def text(self, cx: int, cy: int, s: str, scale: int, colour: tuple[int, int, int]) -> None:
        """The text centred on (cx, cy); a character the font lacks is a blank."""
        s = s.upper()
        adv = 6 * scale
        x = cx - (len(s) * adv - scale) // 2
        y = cy - 7 * scale // 2
        for ch in s:
            for r, row in enumerate(FONT.get(ch, FONT[" "])):
                for c, bit in enumerate(row):
                    if bit == "#":
                        self.rect(x + c * scale, y + r * scale, x + (c + 1) * scale, y + (r + 1) * scale, colour)
            x += adv

    def png(self) -> bytes:
        def chunk(kind: bytes, data: bytes) -> bytes:
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

        raw = b"".join(b"\x00" + bytes(self.px[y * self.w * 3:(y + 1) * self.w * 3]) for y in range(self.h))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def plan_png(level: int) -> bytes:
    """Level ``level``'s floor plan: outer wall, four rooms with a door each on the cross-shaped corridor, the
    stairwell with its steps in the middle, every room and the stairs named, the level named in a badge."""
    cv = Canvas(WIDTH, HEIGHT, (200, 196, 188))
    ox, oy, ow, oh = 18, 18, WIDTH - 36, HEIGHT - 36
    cv.rect(ox, oy, ox + ow, oy + oh, FLOOR[level])
    b0, b1 = int(0.44 * HEIGHT), int(0.56 * HEIGHT)
    v0, v1 = int(0.44 * WIDTH), int(0.56 * WIDTH)
    cv.rect(ox, b0, ox + ow, b1, CORRIDOR)
    cv.rect(v0, oy, v1, oy + oh, CORRIDOR)
    quarters = {"nw": (ox, oy, v0, b0), "ne": (v1, oy, ox + ow, b0), "sw": (ox, b1, v0, oy + oh),
                "se": (v1, b1, ox + ow, oy + oh)}
    for key, (x0, y0, x1, y1) in quarters.items():
        cv.frame(x0, y0, x1, y1, 5, WALL)
        cx, cy = int(ROOMS[key][1] * WIDTH), int(ROOMS[key][2] * HEIGHT)
        gap_y = (y1 - 5, y1) if key in ("nw", "ne") else (y0, y0 + 5)
        cv.rect(cx - 26, gap_y[0], cx + 26, gap_y[1], CORRIDOR)
        cv.text(cx, cy - 40 if key in ("nw", "ne") else cy + 40, ROOMS[key][0][level], 3, TEXT)
    cv.frame(ox, oy, ox + ow, oy + oh, 8, WALL)
    sx, sy = int(STAIRS[0] * WIDTH), int(STAIRS[1] * HEIGHT)
    cv.rect(sx - 40, sy - 34, sx + 40, sy + 34, STAIR)
    for i in range(-26, 34, 8):
        cv.rect(sx - 40, sy + i, sx + 40, sy + i + 2, WALL)
    cv.frame(sx - 40, sy - 34, sx + 40, sy + 34, 3, WALL)
    cv.text(sx, sy - 48, "ESCADAS", 2, TEXT)
    title = LEVEL_TITLES[level]
    bw = 24 * len(title) + 12
    cv.rect(ox + 14, oy + 14, ox + 14 + bw, oy + 14 + 32, WALL)
    cv.text(ox + 14 + bw // 2, oy + 14 + 16, title, 4, (255, 255, 255))
    return cv.png()


def georef_points() -> list[dict]:
    """Two opposite corners (north up), the form PUT /api/v1/field/georef takes."""
    return [{"x": 0.0, "y": 0.0, "lat": round(LAT_TOP, 7), "lon": LON_LEFT},
            {"x": 1.0, "y": 1.0, "lat": LAT_BOTTOM, "lon": round(LON_RIGHT, 7)}]


def to_latlon(x: float, y: float) -> tuple[float, float]:
    return round(LAT_TOP - y * (LAT_TOP - LAT_BOTTOM), 7), round(LON_LEFT + x * (LON_RIGHT - LON_LEFT), 7)


def to_plan(lat: float, lon: float) -> tuple[float, float]:
    return (lon - LON_LEFT) / (LON_RIGHT - LON_LEFT), (LAT_TOP - lat) / (LAT_TOP - LAT_BOTTOM)


def room_at(key: str, level: int) -> tuple[str, float, float]:
    """A room's name on a level and its centre on the plan."""
    names, x, y, _ = ROOMS[key]
    return names[level], x, y


def beacons() -> list[dict]:
    """The registry the director gives the controller: one beacon in every room and one at the stairs, on every
    level (major = level + 1, minor = 1 to 5), placed on its level's plan."""
    out = []
    for level in range(len(LEVEL_NAMES)):
        for minor, (names, x, y, wing) in enumerate(ROOMS.values(), start=1):
            out.append({"uuid": BEACON_UUID, "major": level + 1, "minor": minor, "room": names[level], "zone": wing,
                        "level": level, "x": x, "y": y})
        out.append({"uuid": BEACON_UUID, "major": level + 1, "minor": 5, "room": "Escadas", "zone": "Escadas",
                    "level": level, "x": STAIRS[0], "y": STAIRS[1]})
    return out


def nearest_beacon(level: int, x: float, y: float) -> Optional[str]:
    """The id (major:minor) of the beacon nearest to a place on a level: the one a phone hears strongest."""
    best, best_d = None, 9.0
    for b in beacons():
        if b["level"] != level:
            continue
        d = (b["x"] - x) ** 2 + (b["y"] - y) ** 2
        if d < best_d:
            best, best_d = f"{b['major']}:{b['minor']}", d
    return best


def route(level: int, x: float, y: float, to_level: int, to_x: float, to_y: float) -> list[tuple[int, float, float]]:
    """Waypoints (level, x, y) from a place to another, always through doors and the corridor: out to the
    corridor's middle line at the same x, to the stairs, up or down a floor at a time (the stairs are the same place
    on every level, so a change of level is a waypoint on the same x, y), out along the corridor and in at the
    destination's door."""
    pts: list[tuple[int, float, float]] = []
    if abs(y - BAND) > 0.07:
        pts.append((level, x, BAND))
    if to_level != level:
        step = 1 if to_level > level else -1
        pts.append((level, STAIRS[0], STAIRS[1]))
        for lvl in range(level + step, to_level + step, step):
            pts.append((lvl, STAIRS[0], STAIRS[1]))
    pts.append((to_level, to_x, BAND))
    pts.append((to_level, to_x, to_y))
    return pts
