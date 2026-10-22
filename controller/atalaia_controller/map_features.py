# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Map features: what the GM marks on the field's plan besides the boxes (decisions MF-0 to MF-16).

A safe zone, a team's respawn or headquarters (HQ), the car park, a first aid station, an
objective, anything else with a label, or the field's boundary (``boundary``, decisions MF-19 to
MF-30: the field's real outline, an area only, at most one per level, never a team's; the console
dims what is outside it, ATAK shows it as a closed shape without a fill; loaded from a map by
field_map.py or drawn by hand). Each feature is on one level's plan (field_levels.py;
level 0 with levels off) and has one shape, in the plan's own coordinates (``x`` across and ``y``
down, 0 to 1, as the boxes' positions):

- ``point``: a pin at ``x``, ``y``;
- ``circle``: a pin and a radius on the ground, ``radius_m`` metres (the console draws it to the
  plan's scale only when the plan has a map position, georef.py; MF-6);
- ``polygon``: an area, 3 to ``POLYGON_MAX`` ``points`` traced on the plan.

Who may see a feature (``visibility``, MF-3) is checked on the controller, on every path (REST,
the live stream, the ATAK feed), never left to the page:

- ``everyone``: anyone with a token, the read token's console and scoreboards included, and the
  field's Wi-Fi ATAK feed;
- ``team``: the players of that ``team`` (by its name, as games name teams: ``red``, ``blue``...)
  and the organisers;
- ``organisers``: the organisers only (staff: the GM token, the marshal and gm player tokens).

Without a ``visibility`` a feature with a team is for that team and any other for everyone (MF-4).
Features belong to the field, like its plans: they stay from game to game (MF-2). Kept in the
store's ``map_features`` table (schema 11), one row per feature with its level and the rest as
JSON. A level that goes (fewer levels) takes its features with it; with levels off the features
of the other levels are kept but shown nowhere, as their plans (MF-8).
"""

from __future__ import annotations

import math
from typing import Any, Optional

from . import field_levels as levelsmod
from . import visibility
from .engine import ControllerError

TYPES = ("safe_zone", "respawn", "hq", "parking", "first_aid", "objective", "other", "boundary")
BOUNDARY = "boundary"                  # the field's outline: a polygon, one per level, no team (MF-20)
TEAM_TYPES = ("respawn", "hq")         # a team's own: for that team by default (MF-4)
SHAPES = ("point", "circle", "polygon")
VISIBILITIES = ("everyone", "team", "organisers")
FEATURES_MAX = 200                     # on the whole field
LABEL_MAX = 48                         # characters: an ATAK callsign's length (atak.CALLSIGN_MAX)
NOTE_MAX = 200                         # characters, one line
TEAM_NAME_MAX = 23                     # bytes: a team name as games and the boxes know it (engine.py)
RADIUS_MIN_M, RADIUS_MAX_M = 1.0, 2000.0
POLYGON_MIN, POLYGON_MAX = 3, 12       # 12: the polygon's CoT event stays in one datagram (atak.py)
MIN_AREA = 1e-6                        # a polygon's area on the plan (the plan is 1 x 1)
FIELDS = ("level", "type", "label", "shape", "x", "y", "radius_m", "points", "team", "visibility", "note")


def _text(v: Any, where: str, limit: int) -> str:
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ControllerError(f"{where}: a text")
    text = " ".join(w for w in v.split(" ") if w)  # spaces folded; tabs and line breaks refused
    if len(text) > limit or any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 for c in v):
        raise ControllerError(f"{where}: at most {limit} characters on one line")
    return text


def _fraction(v: Any, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0.0 <= v <= 1.0:
        raise ControllerError(f"{where}: a number from 0 to 1 (fraction of the plan)")
    return float(v)


def _team(v: Any) -> Optional[str]:
    if v is None:
        return None
    if not isinstance(v, str) or not 0 < len(v.encode("utf-8")) <= TEAM_NAME_MAX or v != v.strip() \
            or any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 for c in v):
        raise ControllerError(f"team: a team's name as games use it (red, blue...), 1-{TEAM_NAME_MAX} bytes, "
                              "or null")
    return v


def _area(points: list[dict[str, float]]) -> float:
    n = len(points)
    return abs(sum(points[i]["x"] * points[(i + 1) % n]["y"] - points[(i + 1) % n]["x"] * points[i]["y"]
                   for i in range(n))) / 2.0


def default_visibility(team: Optional[str]) -> str:
    """MF-4: a feature with a team is that team's (a respawn, an HQ); any other is everyone's."""
    return "team" if team is not None else "everyone"


def check(body: Any, meta: dict[str, Any]) -> dict[str, Any]:
    """The GM's feature, checked: ``{level, type, label, shape, x, y | radius_m | points, team, visibility,
    note}`` as stored (``meta``: the field's levels, field_levels.load)."""
    if not isinstance(body, dict):
        raise ControllerError('the body is {"type", "shape", "x", "y" | "points", ...}')
    unknown = set(body) - set(FIELDS)
    if unknown:
        raise ControllerError(f"unknown fields {sorted(unknown)}")
    level = body.get("level", 0)
    if isinstance(level, bool) or not isinstance(level, int):
        raise ControllerError("level: a level in use, from 0")
    why = levelsmod.check_level(meta, level, write=True)
    if why:
        raise ControllerError(f"level: {why}")
    kind = body.get("type")
    if kind not in TYPES:
        raise ControllerError(f"type: one of {list(TYPES)}")
    label = _text(body.get("label"), "label", LABEL_MAX)
    if kind == "other" and not label:
        raise ControllerError("label: a feature of type other needs a label")
    shape = body.get("shape")
    if shape not in SHAPES:
        raise ControllerError(f"shape: one of {list(SHAPES)}")
    out: dict[str, Any] = {"level": level, "type": kind, "label": label, "shape": shape}
    if shape in ("point", "circle"):
        if "points" in body:
            raise ControllerError(f"points: only for a polygon (a {shape} has x and y)")
        out["x"] = _fraction(body.get("x"), "x")
        out["y"] = _fraction(body.get("y"), "y")
    if shape == "circle":
        r = body.get("radius_m")
        if isinstance(r, bool) or not isinstance(r, (int, float)) or not math.isfinite(r) \
                or not RADIUS_MIN_M <= r <= RADIUS_MAX_M:
            raise ControllerError(f"radius_m: {RADIUS_MIN_M:g} to {RADIUS_MAX_M:g} metres")
        out["radius_m"] = round(float(r), 1)
    elif "radius_m" in body:
        raise ControllerError("radius_m: only for a circle")
    if shape == "polygon":
        if "x" in body or "y" in body:
            raise ControllerError("x, y: a polygon has points instead")
        raw = body.get("points")
        if not isinstance(raw, list) or not POLYGON_MIN <= len(raw) <= POLYGON_MAX:
            raise ControllerError(f"points: {POLYGON_MIN} to {POLYGON_MAX} points {{x, y}} around the area")
        pts = []
        for i, p in enumerate(raw):
            if not isinstance(p, dict) or set(p) != {"x", "y"}:
                raise ControllerError(f"points[{i}]: an object with exactly x and y")
            pts.append({"x": _fraction(p["x"], f"points[{i}].x"), "y": _fraction(p["y"], f"points[{i}].y")})
        if _area(pts) < MIN_AREA:
            raise ControllerError("points: the area is empty (the points are on one line or at one place)")
        out["points"] = pts
    out["team"] = _team(body.get("team"))
    if kind == BOUNDARY:
        if shape != "polygon":
            raise ControllerError("shape: the field boundary is an area (polygon)")
        if out["team"] is not None:
            raise ControllerError("team: the field boundary belongs to no team")
    vis = body.get("visibility")
    if vis is None:
        vis = default_visibility(out["team"])
    if vis not in VISIBILITIES:
        raise ControllerError(f"visibility: one of {list(VISIBILITIES)}")
    if vis == "team" and out["team"] is None:
        raise ControllerError("visibility team: name the team")
    out["visibility"] = vis
    out["note"] = _text(body.get("note"), "note", NOTE_MAX)
    return out


def boundary_id(store: Any, level: int, except_id: Optional[int] = None) -> Optional[int]:
    """The id of the field boundary on this level (MF-20: at most one), other than ``except_id``."""
    for row in store.map_features():
        if row["level"] == level and row["data"].get("type") == BOUNDARY and row["id"] != except_id:
            return int(row["id"])
    return None


def view(row: dict[str, Any]) -> dict[str, Any]:
    """A stored feature as the API gives it."""
    return {"id": row["id"], **row["data"], "level": row["level"], "updated_at": row["updated_at"]}


def every(store: Any) -> list[dict[str, Any]]:
    """Every stored feature, levels not in use included (the store's order: by id)."""
    return [view(r) for r in store.map_features()]


def in_use(store: Any, meta: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """The features on levels in use (MF-8): what anyone, the GM included, and ATAK are given."""
    count = levelsmod.in_use(meta if meta is not None else levelsmod.load(store))
    return [f for f in every(store) if f["level"] < count]


def centre(feature: dict[str, Any]) -> tuple[float, float]:
    """Where a feature's pin goes: its x, y, or a polygon's vertex average."""
    if feature["shape"] == "polygon":
        pts = feature["points"]
        return sum(p["x"] for p in pts) / len(pts), sum(p["y"] for p in pts) / len(pts)
    return feature["x"], feature["y"]


def viewer_team(store: Any, viewer: Any) -> Optional[str]:
    """A player token's team name in its game (its check-in row's team, checkin.Viewer), else None."""
    if viewer is None or getattr(viewer, "kind", None) != "player" or not viewer.team:
        return None
    game = store.game(viewer.game_id) if viewer.game_id is not None else None
    teams = (game or {}).get("teams") or []
    return teams[viewer.team - 1] if 1 <= viewer.team <= len(teams) else None


def can_see(viewer: Any, feature: dict[str, Any], team: Optional[str]) -> bool:
    """MF-3: staff see every feature; anyone with a token the ones for everyone; a player the ones of
    their team (``team``: the viewer's team name, viewer_team)."""
    if viewer is None:
        return False
    if visibility.is_staff(viewer):
        return True
    vis = feature.get("visibility")
    if vis == "everyone":
        return True
    return vis == "team" and team is not None and feature.get("team") == team


def visible(store: Any, viewer: Any) -> list[dict[str, Any]]:
    """The features on levels in use this viewer may see."""
    team = viewer_team(store, viewer)
    return [f for f in in_use(store) if can_see(viewer, f, team)]
