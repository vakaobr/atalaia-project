# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field loaded from a map (decision MF-18, built as MF-19 to MF-30).

While the GM sets the game up, the console's *Load the field from a map* page (console/src/field-map.js)
runs in the GM's browser, which has internet: the GM finds the field on an interactive map, draws its
outline, and the browser draws the field image itself, from OpenStreetMap data (the Overpass API) over,
in Portugal, the DGT orthophoto (its WMS), with the attribution burned into a corner. The controller
never goes to the internet for this: it gets one request (``POST /api/v1/field/levels/{n}/from-map``)
with everything, checked here before anything is written:

- ``image``: the drawn image, base64, PNG or JPEG (``content_type``), at most the field image limit;
- ``bounds``: ``{north, south, west, east}``, the image's edges in WGS 84 degrees. The browser draws the
  image north-up with latitude linear down the image and longitude linear across it (an equirectangular
  frame over the area, MF-24), which is exactly what georef.py's two-corner map does, so the map
  position set from the corners is exact by construction (no projection error);
- ``outline``: the field's outline, 3 to ``map_features.POLYGON_MAX`` corners ``{lat, lon}`` inside the
  bounds, which becomes the level's field boundary (``boundary``), in the image's coordinates;
- ``label`` (optional): the boundary's name.

The level's plan, its own map position (``field.georef`` or ``field.georef.<n>``) and its boundary are
then written in one SQLite transaction (store.set_field_from_map): all or nothing (MF-26).
"""

from __future__ import annotations

import base64
import binascii
import math
from typing import Any

from . import georef as georefmod
from . import map_features as mapmod
from .engine import ControllerError
from .store import FIELD_IMAGE_MAX

FIELDS = {"content_type", "image", "bounds", "outline", "label"}
MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}
B64_MAX = 4 * ((FIELD_IMAGE_MAX + 2) // 3)
EDGE_TOLERANCE = 1e-6  # an outline corner on the image's edge, after rounding


def _degrees(v: Any, where: str, limit: float) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not -limit <= v <= limit:
        raise ControllerError(f"{where}: degrees from {-limit:g} to {limit:g}")
    return float(v)


def check(body: Any, meta: dict[str, Any], level: int) -> dict[str, Any]:
    """The request, checked: ``{content_type, data, georef, boundary}`` (``boundary`` as map_features.check
    gives it, its level included). Raises ControllerError with what to change."""
    if not isinstance(body, dict):
        raise ControllerError('the body is {"content_type", "image", "bounds", "outline", "label"?}')
    unknown = set(body) - FIELDS
    if unknown:
        raise ControllerError(f"unknown fields {sorted(unknown)}")
    ctype = body.get("content_type")
    if ctype not in MAGIC:
        raise ControllerError(f"content_type: one of {sorted(MAGIC)}")
    raw = body.get("image")
    if not isinstance(raw, str) or not raw:
        raise ControllerError("image: the image, base64")
    if len(raw) > B64_MAX:
        raise ControllerError(f"image: over {FIELD_IMAGE_MAX} bytes")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise ControllerError("image: not base64") from None
    if len(data) > FIELD_IMAGE_MAX:
        raise ControllerError(f"image: over {FIELD_IMAGE_MAX} bytes")
    if not data.startswith(MAGIC[ctype]):
        raise ControllerError(f"image: not a {ctype} image")
    b = body.get("bounds")
    if not isinstance(b, dict) or set(b) != {"north", "south", "west", "east"}:
        raise ControllerError("bounds: {north, south, west, east} in degrees")
    north = _degrees(b["north"], "bounds.north", georefmod.MAX_LAT)
    south = _degrees(b["south"], "bounds.south", georefmod.MAX_LAT)
    west = _degrees(b["west"], "bounds.west", 180.0)
    east = _degrees(b["east"], "bounds.east", 180.0)
    if not north > south or not east > west:
        raise ControllerError("bounds: north above south and east of west (not across the 180th meridian)")
    points = [{"x": 0, "y": 0, "lat": north, "lon": west}, {"x": 1, "y": 1, "lat": south, "lon": east}]
    try:
        geo = georefmod.Georef(georefmod.check_points(points))
    except georefmod.GeorefError as exc:
        raise ControllerError(f"bounds: {exc}") from None
    outline = body.get("outline")
    if not isinstance(outline, list) or not mapmod.POLYGON_MIN <= len(outline) <= mapmod.POLYGON_MAX:
        raise ControllerError(f"outline: {mapmod.POLYGON_MIN} to {mapmod.POLYGON_MAX} corners {{lat, lon}}")
    plan = []
    for i, p in enumerate(outline):
        if not isinstance(p, dict) or set(p) != {"lat", "lon"}:
            raise ControllerError(f"outline[{i}]: an object with exactly lat and lon")
        lat = _degrees(p["lat"], f"outline[{i}].lat", georefmod.MAX_LAT)
        lon = _degrees(p["lon"], f"outline[{i}].lon", 180.0)
        # The inverse of the two-corner map: longitude across, latitude down, both linear (MF-24).
        x = (lon - west) / (east - west)
        y = (north - lat) / (north - south)
        if not -EDGE_TOLERANCE <= x <= 1 + EDGE_TOLERANCE or not -EDGE_TOLERANCE <= y <= 1 + EDGE_TOLERANCE:
            raise ControllerError(f"outline[{i}]: outside the image's bounds")
        plan.append({"x": round(min(1.0, max(0.0, x)), 7), "y": round(min(1.0, max(0.0, y)), 7)})
    boundary = mapmod.check({"level": level, "type": mapmod.BOUNDARY, "label": body.get("label"),
                             "shape": "polygon", "points": plan, "visibility": "everyone"}, meta)
    return {"content_type": ctype, "data": data, "georef": geo, "boundary": boundary}
