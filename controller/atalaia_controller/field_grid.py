# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The field grid: lettered rows and numbered columns over a level's plan (decisions MF-81 to MF-93).

The maintainer's request (2026-10-23): a milsim map grid over the field image, so positions can be called
on the radio ("C4"). Each level's plan has its own grid, off by default: ``{"enabled", "rows", "cols"}``,
1 to ``ROWS_MAX`` rows (letters A, B, ... Z, then AA, AB, ...: ``row_label``) and 1 to ``COLS_MAX`` columns
(numbers 1, 2, ...). The grid divides the plan's rectangle into equal cells (MF-84: image-aligned; with a
map position from a map the image is north-up, so the rows run east-west). It is not drawn into the
image: the console draws it over the plan (components/field-grid.js), and every viewer may hide it.

Kept in the settings key ``field.grid`` (level 0) or ``field.grid.<n>`` (level n), as the plans' own map
positions are (georef.py ``setting``); no table and no schema change. A new or replaced plan keeps its
level's grid (the grid is a number of rows and columns, not places on the image); fewer levels remove
the grids of the levels that go (field_levels.save).
"""

from __future__ import annotations

import json
from typing import Any, Optional

from .engine import ControllerError

SETTING = "field.grid"
ROWS_MAX = 52     # A to Z, then AA to AZ
COLS_MAX = 52
DEFAULT = {"enabled": False, "rows": 8, "cols": 8}
FIELDS = ("enabled", "rows", "cols")


def setting(level: int = 0) -> str:
    """The settings key of a level's grid (level 0: ``field.grid``)."""
    return SETTING if level == 0 else f"{SETTING}.{level}"


def row_label(row: int) -> str:
    """Row 0 is "A", 25 "Z", 26 "AA", 27 "AB", ... (as spreadsheets name columns)."""
    out = ""
    n = row + 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        out = chr(ord("A") + r) + out
    return out


def cell(grid: dict[str, Any], x: float, y: float) -> Optional[str]:
    """The cell of a place on the plan (``x``, ``y``: fractions of its width and height) as the radio says it,
    "C4": the row's letters, then the column's number. The right and bottom edges are in the last cell.
    None when the grid is off or the place is not on the plan."""
    if not grid.get("enabled") or not (0 <= x <= 1 and 0 <= y <= 1):
        return None
    rows, cols = int(grid["rows"]), int(grid["cols"])
    return f"{row_label(min(rows - 1, int(y * rows)))}{min(cols - 1, int(x * cols)) + 1}"


def _count(v: Any, where: str, top: int) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 1 <= v <= top:
        raise ControllerError(f"{where}: a whole number from 1 to {top}")
    return v


def check(body: Any, current: dict[str, Any]) -> dict[str, Any]:
    """The GM's ``{"enabled", "rows"?, "cols"?}``, checked: the new grid (rows and columns not given stay)."""
    if not isinstance(body, dict) or not isinstance(body.get("enabled"), bool):
        raise ControllerError(f'the body is {{"enabled": true|false, "rows": 1-{ROWS_MAX}, "cols": 1-{COLS_MAX}}}')
    unknown = set(body) - set(FIELDS)
    if unknown:
        raise ControllerError(f"unknown fields {sorted(unknown)}")
    return {"enabled": body["enabled"],
            "rows": _count(body.get("rows", current["rows"]), "rows", ROWS_MAX),
            "cols": _count(body.get("cols", current["cols"]), "cols", COLS_MAX)}


def load(store: Any, level: int = 0) -> dict[str, Any]:
    """A level's grid; off, 8 by 8, when never set (or unreadable)."""
    raw = store.get_setting(setting(level))
    if raw:
        try:
            return check(json.loads(raw), DEFAULT)
        except (ValueError, TypeError, ControllerError):
            pass
    return dict(DEFAULT)


def dump(grid: dict[str, Any]) -> str:
    return json.dumps({k: grid[k] for k in FIELDS}, separators=(",", ":"))


def save(store: Any, level: int, grid: dict[str, Any]) -> None:
    store.set_setting(setting(level), dump(grid))


def clear(store: Any, level: int) -> None:
    store.delete_setting(setting(level))
