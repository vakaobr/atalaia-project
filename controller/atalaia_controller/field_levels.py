# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Field levels: a multi-story building with a floor plan per level (decisions ML-0 to ML-12).

Off by default: the field has one image (level 0), exactly as before. With levels on, the field
has 2 to 10 of them, numbered 0 to count - 1 in the order the GM lists them (level 0 is the
field image of before), each with a name the GM chose (the console fills in names in its
language: "R/C", "1.º andar", ...; a basement is a level the GM names so, decision ML-2) and
its own plan (store.field_levels, the same types and limit as the field image). A box's
position on the field has a level (store.positions.level, 0 by default); a player's report may
say its level (positions.py).

Kept in the settings key ``field.levels`` as ``{"enabled", "count", "names"}``. Turning levels
off keeps everything (the plans, names and the boxes' levels) and uses only level 0; turning them
on again brings it all back (decision ML-3). Fewer levels delete the plans and own control points
of the levels that go, and move the boxes on them to level 0.

Where a level is shown, a position's level is read with ``shown``: a level that is not in use
(levels off, or past the count) is shown on level 0.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from . import georef as georefmod
from .engine import ControllerError
from .store import FIELD_LEVELS_MAX

SETTING = "field.levels"
LEVELS_MIN = 2              # with levels on
LEVELS_MAX = FIELD_LEVELS_MAX
NAME_MAX = 32               # characters of a level's name


def load(store: Any) -> dict[str, Any]:
    """``{"enabled", "count", "names"}``: off with one unnamed level when never set."""
    out: dict[str, Any] = {"enabled": False, "count": 1, "names": [""]}
    raw = store.get_setting(SETTING)
    if raw:
        try:
            got = json.loads(raw)
            count = int(got["count"])
            names = [str(n) for n in got["names"]][:count]
            if 1 <= count <= LEVELS_MAX:
                out = {"enabled": bool(got["enabled"]), "count": count,
                       "names": names + [""] * (count - len(names))}
        except (ValueError, TypeError, KeyError):
            pass
    return out


def in_use(meta: dict[str, Any]) -> int:
    """How many levels are in use: 1 while levels are off."""
    return int(meta["count"]) if meta["enabled"] else 1


def shown(meta: dict[str, Any], level: Any) -> int:
    """The level a position on ``level`` is shown on: itself while in use, else level 0."""
    return level if isinstance(level, int) and 0 <= level < in_use(meta) else 0


def label(meta: dict[str, Any], level: int) -> str:
    """A level's name for texts the controller writes (the ATAK remarks): the GM's, else ``L<n>``."""
    names = meta["names"]
    name = names[level] if 0 <= level < len(names) else ""
    return name or f"L{level}"


def _name(v: Any, where: str) -> str:
    if not isinstance(v, str):
        raise ControllerError(f"{where}: a text")
    text = " ".join(w for w in v.split(" ") if w)  # spaces folded; tabs and line breaks refused
    if len(text) > NAME_MAX or any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 for c in v):
        raise ControllerError(f"{where}: at most {NAME_MAX} characters on one line")
    return text


def check(body: Any, current: dict[str, Any]) -> dict[str, Any]:
    """The GM's ``{"enabled", "count"?, "names"?}``, checked: the new settings."""
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        raise ControllerError('the body is {"enabled": true|false, "count": 2-10, "names": [...]}')
    unknown = set(body) - {"enabled", "count", "names"}
    if unknown:
        raise ControllerError(f"unknown fields {sorted(unknown)}")
    enabled = body["enabled"]
    count = body.get("count", current["count"] if current["count"] >= LEVELS_MIN or not enabled else LEVELS_MIN)
    lo = LEVELS_MIN if enabled else 1
    if isinstance(count, bool) or not isinstance(count, int) or not lo <= count <= LEVELS_MAX:
        raise ControllerError(f"count: {lo} to {LEVELS_MAX} levels")
    names = list(current["names"])
    if "names" in body:
        given = body["names"]
        if not isinstance(given, list) or len(given) > count:
            raise ControllerError(f"names: a list of at most {count} names, one per level from level 0")
        names[:len(given)] = [_name(n, f"names[{i}]") for i, n in enumerate(given)]
    names = (names + [""] * count)[:count]
    return {"enabled": enabled, "count": count, "names": names}


def save(store: Any, meta: dict[str, Any]) -> list[int]:
    """Stores the settings; the levels that went (their plans, own points and boxes' levels) are
    removed. Returns those levels."""
    removed = []
    for level in range(meta["count"], LEVELS_MAX):
        plan = store.delete_field_image(level)
        points = georefmod.clear(store, level) if level else False
        if plan or points:
            removed.append(level)
    store.move_positions_to_level0(meta["count"])
    store.set_setting(SETTING, json.dumps(meta, separators=(",", ":"), ensure_ascii=False))
    return removed


def view(store: Any) -> dict[str, Any]:
    """The levels for the API and the console: the settings and, per level, its plan and whether it
    has its own control points."""
    meta = load(store)
    images = store.field_images()
    levels = []
    for level in range(meta["count"]):
        img = images.get(level)
        levels.append({"level": level, "name": meta["names"][level],
                       "image": {"content_type": img[0], "bytes": img[1], "updated_at": img[2]} if img else None,
                       "own_georef": georefmod.load(store, level) is not None})
    return {**meta, "in_use": in_use(meta), "levels": levels}


def check_level(meta: dict[str, Any], level: int, write: bool = False) -> Optional[str]:
    """Why ``level`` cannot be read (or written) now, or None. Level 0 always can."""
    if level == 0:
        return None
    if not 0 < level < LEVELS_MAX:
        return f"level: 0 to {LEVELS_MAX - 1}"
    if level >= in_use(meta):
        return "turn levels on and set their number first" if write else "no such level in use"
    return None
