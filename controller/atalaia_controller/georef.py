# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field image's georeference: image positions (0-1) to latitude and longitude.

Field Boxes have no GPS (E21): the GM places them on the field image, and
their positions are fractions of it (``x`` across, ``y`` down). To put
them on an ATAK map (ADR-P4-7 as amended, decision P4R18) the GM gives
control points: a point of the image and its latitude and longitude.

- **Two points** are two opposite corners of a north-up image (any two
  points that differ in ``x`` and in ``y``, usually the top-left and the
  bottom-right corner): latitude follows ``y`` and longitude follows
  ``x``, each linearly. The image may be stretched (its pixels need not
  be square on the ground) but not rotated.
- **Three to eight points** give a general affine map (rotation, a
  different scale on each axis, shear), fitted by least squares; with
  four or more the residual says how well the points agree.

The fit is made in a local plane in metres around the points' mean
(east = R cos(lat0) dlon, north = R dlat, on the 6,371 km sphere of
ADR-P4-9), which is good to well under a metre over a field of a few
kilometres, and refused across the 180th meridian or near the poles.
Degenerate points are errors, never a silent wrong map: two points that
share an ``x`` or a ``y`` (or a latitude or a longitude), three or more
on one line in the image or on the ground, points too close together, a
mirror image (latitude and longitude swapped, or the image flipped), or
points that do not fit one flat image (decision M9-3).

Stored in the store's ``settings`` table (``field.georef``) as the GM's
points; the map is fitted again when it is read. A new or removed field
image deletes it (api.py), because its points belong to the old image.

A multi-story field (field_levels.py) has a plan per level: level 0's points
are ``field.georef`` as before, and another level may have its own
(``field.georef.<level>``); a level without them shares level 0's (decision
ML-6: the plans are drawn to the same frame).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any, Optional, Sequence

EARTH_RADIUS_M = 6_371_000.0  # the sphere of geo.c (ADR-P4-9)
SETTING = "field.georef"
POINTS_MIN, POINTS_MAX = 2, 8
MIN_IMAGE_SEP = 0.05          # two points: at least 5 % of the image apart on each axis
MIN_IMAGE_AREA = 0.01         # 3+ points: a triangle of at least 1 % of the image (half of it: 0.5)
MIN_GROUND_SEP_M = 1.0        # two points: at least 1 m apart in latitude and in longitude
MIN_GROUND_AREA_M2 = 1.0      # 3+ points: the whole image covers at least 1 square metre
MAX_SPAN_M = 20_000.0         # every corner of the image within 20 km of the points' mean
MAX_LAT = 85.0
MAX_RESIDUAL = 0.05           # 4+ points: RMS residual at most 5 % of the image's diagonal ...
MIN_RESIDUAL_M = 5.0          # ... or 5 m, whichever is larger


class GeorefError(ValueError):
    """Control points that do not make a map; the message says what to change."""


@dataclass(frozen=True)
class Affine:
    """x' = a x + b y + c, y' = d x + e y + f (the order of a world file's parameters, Wikipedia
    "World file": A, D, B, E, C, F)."""

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return self.a * x + self.b * y + self.c, self.d * x + self.e * y + self.f

    @property
    def det(self) -> float:
        return self.a * self.e - self.b * self.d


def _solve3(m: list[list[float]], v: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting on a 3x3 system."""
    a = [row[:] + [v[i]] for i, row in enumerate(m)]
    for col in range(3):
        piv = max(range(col, 3), key=lambda r: abs(a[r][col]))
        if a[piv][col] == 0.0:
            raise GeorefError("the control points are on one line")
        a[col], a[piv] = a[piv], a[col]
        for r in range(col + 1, 3):
            k = a[r][col] / a[col][col]
            for c in range(col, 4):
                a[r][c] -= k * a[col][c]
    out = [0.0, 0.0, 0.0]
    for r in (2, 1, 0):
        out[r] = (a[r][3] - sum(a[r][c] * out[c] for c in range(r + 1, 3))) / a[r][r]
    return out


def _max_triangle(pts: Sequence[tuple[float, float]]) -> float:
    best = 0.0
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                (x1, y1), (x2, y2), (x3, y3) = pts[i], pts[j], pts[k]
                best = max(best, abs((x2 - x1) * (y3 - y1) - (x3 - x1) * (y2 - y1)) / 2.0)
    return best


def fit_affine(src: Sequence[tuple[float, float]], dst: Sequence[tuple[float, float]]) -> Affine:
    """The least-squares affine map from src to dst (at least three points, not on one line).

    The points are centred first so the normal equations stay well conditioned with map
    coordinates in the millions (a UTM easting)."""
    if len(src) != len(dst) or len(src) < 3:
        raise GeorefError("an affine map needs at least three points")
    n = len(src)
    sx = sum(p[0] for p in src) / n
    sy = sum(p[1] for p in src) / n
    tx = sum(p[0] for p in dst) / n
    ty = sum(p[1] for p in dst) / n
    u = [(p[0] - sx, p[1] - sy) for p in src]
    w = [(p[0] - tx, p[1] - ty) for p in dst]
    suu = sum(p[0] * p[0] for p in u)
    suv = sum(p[0] * p[1] for p in u)
    svv = sum(p[1] * p[1] for p in u)
    det = suu * svv - suv * suv
    scale = max(suu, svv)
    if scale == 0.0 or abs(det) <= 1e-12 * scale * scale:
        raise GeorefError("the control points are on one line")
    m = [[suu, suv, 0.0], [suv, svv, 0.0], [0.0, 0.0, float(n)]]
    rows = []
    for k in (0, 1):
        su = sum(p[0] * q[k] for p, q in zip(u, w))
        sv = sum(p[1] * q[k] for p, q in zip(u, w))
        a, b, _ = _solve3(m, [su, sv, 0.0])
        rows.append((a, b))
    (a, b), (d, e) = rows
    return Affine(a, b, tx - a * sx - b * sy, d, e, ty - d * sx - e * sy)


def _num(v: Any, name: str, lo: float, hi: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
        raise GeorefError(f"{name}: a number from {lo:g} to {hi:g}")
    return float(v)


@dataclass(frozen=True)
class ControlPoint:
    x: float
    y: float
    lat: float
    lon: float

    def to_json(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "lat": self.lat, "lon": self.lon}


def check_points(raw: Any) -> list[ControlPoint]:
    """The API's ``points``: 2 to 8 objects {x, y, lat, lon}."""
    if not isinstance(raw, list) or not POINTS_MIN <= len(raw) <= POINTS_MAX:
        raise GeorefError(f"points: {POINTS_MIN} to {POINTS_MAX} control points {{x, y, lat, lon}}")
    out = []
    for i, p in enumerate(raw):
        if not isinstance(p, dict) or set(p) != {"x", "y", "lat", "lon"}:
            raise GeorefError(f"points[{i}]: an object with exactly x, y, lat and lon")
        out.append(ControlPoint(_num(p["x"], f"points[{i}].x", 0.0, 1.0), _num(p["y"], f"points[{i}].y", 0.0, 1.0),
                                _num(p["lat"], f"points[{i}].lat", -MAX_LAT, MAX_LAT),
                                _num(p["lon"], f"points[{i}].lon", -180.0, 180.0)))
    return out


class Georef:
    """A fitted map from image positions (0-1) to WGS 84 degrees."""

    def __init__(self, points: Sequence[ControlPoint]) -> None:
        pts = list(points)
        if not POINTS_MIN <= len(pts) <= POINTS_MAX:
            raise GeorefError(f"points: {POINTS_MIN} to {POINTS_MAX} control points")
        lons = [p.lon for p in pts]
        if max(lons) - min(lons) > 180.0:
            raise GeorefError("the points cross the 180th meridian (not supported)")
        self.points = pts
        self.lat0 = sum(p.lat for p in pts) / len(pts)
        self.lon0 = sum(lons) / len(pts)
        self._k_lat = math.radians(1.0) * EARTH_RADIUS_M                         # metres per degree north
        self._k_lon = self._k_lat * math.cos(math.radians(self.lat0))           # metres per degree east
        ground = [self._plane(p.lat, p.lon) for p in pts]
        image = [(p.x, p.y) for p in pts]
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                if math.hypot(image[i][0] - image[j][0], image[i][1] - image[j][1]) < MIN_IMAGE_SEP:
                    raise GeorefError(f"points {i + 1} and {j + 1} are at almost the same place on the image")
        if len(pts) == 2:
            self.kind = "corners"
            (x1, y1), (x2, y2) = image
            (e1, n1), (e2, n2) = ground
            if abs(x2 - x1) < MIN_IMAGE_SEP or abs(y2 - y1) < MIN_IMAGE_SEP:
                raise GeorefError("two points must be opposite corners: they differ in x and in y "
                                  "(or give three points for a rotated image)")
            if abs(e2 - e1) < MIN_GROUND_SEP_M or abs(n2 - n1) < MIN_GROUND_SEP_M:
                raise GeorefError("two points must differ in latitude and in longitude (or give three points "
                                  "for a rotated image)")
            a = (e2 - e1) / (x2 - x1)
            e = (n2 - n1) / (y2 - y1)
            self.affine = Affine(a, 0.0, e1 - a * x1, 0.0, e, n1 - e * y1)
        else:
            self.kind = "affine"
            if _max_triangle(image) < MIN_IMAGE_AREA:
                raise GeorefError("the control points are on one line on the image")
            self.affine = fit_affine(image, ground)
        det = self.affine.det
        if abs(det) < MIN_GROUND_AREA_M2:
            raise GeorefError("the control points are on one line on the ground (or all at one place)")
        if det > 0.0:
            # x grows to the right and y downwards, east to the right and north upwards: a map
            # that is not mirrored turns one into the other with a negative determinant.
            raise GeorefError("the points make a mirror image: check that each point's latitude and longitude "
                              "are not swapped")
        for cx, cy in ((0, 0), (1, 0), (1, 1), (0, 1)):
            east, north = self.affine.apply(cx, cy)
            if math.hypot(east, north) > MAX_SPAN_M:
                raise GeorefError("the image would cover more than 20 km: check the points")
        self.residual_m = 0.0
        if len(pts) >= 3:
            sq = [(self.affine.apply(x, y)[0] - g[0]) ** 2 + (self.affine.apply(x, y)[1] - g[1]) ** 2
                  for (x, y), g in zip(image, ground)]
            self.residual_m = math.sqrt(sum(sq) / len(sq))
            tl, br = self.affine.apply(0, 0), self.affine.apply(1, 1)
            tr, bl = self.affine.apply(1, 0), self.affine.apply(0, 1)
            diag = max(math.dist(tl, br), math.dist(tr, bl))
            if self.residual_m > max(MIN_RESIDUAL_M, MAX_RESIDUAL * diag):
                raise GeorefError(f"the points do not fit one flat image (they are {self.residual_m:.0f} m off "
                                  "on average): check them")

    def _plane(self, lat: float, lon: float) -> tuple[float, float]:
        return (lon - self.lon0) * self._k_lon, (lat - self.lat0) * self._k_lat

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        """An image position (0-1) as (latitude, longitude) in degrees."""
        east, north = self.affine.apply(x, y)
        lat = self.lat0 + north / self._k_lat
        lon = self.lon0 + east / self._k_lon
        if lon > 180.0:
            lon -= 360.0
        elif lon < -180.0:
            lon += 360.0
        return lat, lon

    def to_api(self) -> dict[str, Any]:
        corners = {name: dict(zip(("lat", "lon"), self.to_latlon(x, y)))
                   for name, (x, y) in (("top_left", (0, 0)), ("top_right", (1, 0)),
                                        ("bottom_right", (1, 1)), ("bottom_left", (0, 1)))}
        return {"points": [p.to_json() for p in self.points], "kind": self.kind,
                "residual_m": round(self.residual_m, 2), "corners": corners}


def setting(level: int = 0) -> str:
    """The settings key of a level's own control points (level 0: the field image's, as before)."""
    return SETTING if level == 0 else f"{SETTING}.{level}"


def load(store: Any, level: int = 0) -> Optional[Georef]:
    """A level's own georeference (level 0: the field image's), or None."""
    raw = store.get_setting(setting(level))
    if not raw:
        return None
    try:
        return Georef(check_points(json.loads(raw)))
    except (ValueError, TypeError):
        return None


def for_level(store: Any, level: int) -> Optional[Georef]:
    """What places a level's boxes on the map: its own points, else level 0's (decision ML-6)."""
    return load(store, level) or (load(store, 0) if level else None)


def save(store: Any, georef: Georef, level: int = 0) -> None:
    store.set_setting(setting(level), json.dumps([p.to_json() for p in georef.points], separators=(",", ":")))


def clear(store: Any, level: int = 0) -> bool:
    had = bool(store.get_setting(setting(level)))
    store.delete_setting(setting(level))
    return had
