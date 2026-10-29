# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The indoor BLE beacon registry (ADR-P3-6, decisions BLE-1 to BLE-9).

Standard iBeacon hardware the GM has put up in a building: each beacon is its ``uuid``, ``major`` and
``minor`` (a beacon's id for a position report is ``major:minor``, so that pair is unique on the field), the
``room`` it is in (and a ``zone`` to group rooms, optional), the ``level`` of the field's plans it is on
(field_levels.py; 0 with levels off) and, optionally, where it is on that level's plan, ``x`` across and ``y``
down as fractions 0 to 1 (as the boxes' and the map features' places).

Phones report the strongest beacon they hear (``source: ble``, ``beacon_id``, positions.py) and the controller
accepts only beacons of this registry: it turns the id into the room, zone, level and plan place the player is
shown at, so the room is what the GM, the ATAK feed and the player see. A beacon never gives a player's place
more exactly than its room (no triangulation, ADR-P3-6).

The registry belongs to the field, like its plans: it stays from game to game. Everyone with a token may read
the ``id`` and ``uuid`` of each beacon (a phone needs them to know which beacons to listen for; they are
broadcast in the air anyway), only staff the rest. Writes are the GM's. A level that goes takes its beacons
to level 0, unplaced (the hardware is still there; the GM places it again). Kept in the store's ``beacons``
table (schema 14), one row per beacon with the rest as JSON.
"""

from __future__ import annotations

import math
import re
import uuid as uuidmod
from typing import Any, Optional

from . import field_levels as levelsmod
from . import visibility
from .engine import ControllerError

BEACON_RE = re.compile(r"[0-9]{1,5}:[0-9]{1,5}")
BEACONS_MAX = 200
# The major of the Field Boxes' own beacons (box_beacons.py, decisions BBC-1 to BBC-12): a GM's tag may not use it,
# so a box's id ``major:minor`` (its node id as the minor) never collides with a tag's.
BOX_MAJOR = 0xB0C5  # 45253
ROOM_MAX = 48            # characters, as a map feature's label
ZONE_MAX = 48
FIELDS = ("uuid", "major", "minor", "room", "zone", "level", "x", "y")
BLE_INTERVAL_DEFAULT_S = 5   # ADR-P3-6: 5 s, 3 to 30
BLE_INTERVAL_MIN_S, BLE_INTERVAL_MAX_S = 3, 30


def parse_id(bid: Any) -> tuple[int, int]:
    """``"major:minor"`` as numbers, or a ControllerError."""
    if not isinstance(bid, str) or not BEACON_RE.fullmatch(bid):
        raise ControllerError("beacon id: major:minor, two numbers from 0 to 65535")
    major, minor = (int(x) for x in bid.split(":"))
    if major > 65535 or minor > 65535:
        raise ControllerError("beacon id: major:minor, two numbers from 0 to 65535")
    return major, minor


def beacon_id(major: int, minor: int) -> str:
    return f"{major}:{minor}"


def _text(v: Any, where: str, limit: int, required: bool = False) -> str:
    if v is None:
        v = ""
    if not isinstance(v, str):
        raise ControllerError(f"{where}: a text")
    text = " ".join(w for w in v.split(" ") if w)
    if len(text) > limit or any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 for c in v):
        raise ControllerError(f"{where}: at most {limit} characters on one line")
    if required and not text:
        raise ControllerError(f"{where}: a name is needed")
    return text


def _fraction(v: Any, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0.0 <= v <= 1.0:
        raise ControllerError(f"{where}: a number from 0 to 1 (fraction of the plan)")
    return float(v)


def _id16(v: Any, where: str) -> int:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 65535:
        raise ControllerError(f"{where}: a whole number from 0 to 65535")
    return v


def check_uuid(v: Any) -> str:
    """An iBeacon UUID in its canonical upper-case form."""
    if not isinstance(v, str) or not re.fullmatch(r"[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", v):
        raise ControllerError("uuid: the beacon's proximity UUID, 8-4-4-4-12 hexadecimal digits")
    return str(uuidmod.UUID(v)).upper()


def check(body: Any, meta: dict[str, Any], path_id: Optional[str] = None) -> dict[str, Any]:
    """The GM's beacon, checked: ``{major, minor, uuid, room, zone, level, x, y}`` as stored (``x`` and ``y``
    both or neither; ``meta``: the field's levels). With ``path_id`` (a PUT) a major and minor given must be it."""
    if not isinstance(body, dict):
        raise ControllerError('the body is {"uuid", "major", "minor", "room", ...}')
    unknown = set(body) - set(FIELDS)
    if unknown:
        raise ControllerError(f"unknown fields {sorted(unknown)}")
    if path_id is not None:
        major, minor = parse_id(path_id)
        for name, want in (("major", major), ("minor", minor)):
            if name in body and body[name] != want:
                raise ControllerError(f"{name}: a beacon's major and minor do not change (delete it and add another)")
    else:
        major, minor = _id16(body.get("major"), "major"), _id16(body.get("minor"), "minor")
    if major == BOX_MAJOR:
        raise ControllerError(f"major: {BOX_MAJOR} is the Field Boxes' own (they register themselves from their "
                              "place); give a tag another major")
    level = body.get("level", 0)
    if isinstance(level, bool) or not isinstance(level, int):
        raise ControllerError("level: a level in use, from 0")
    why = levelsmod.check_level(meta, level, write=True)
    if why:
        raise ControllerError(f"level: {why}")
    out: dict[str, Any] = {"major": major, "minor": minor, "uuid": check_uuid(body.get("uuid")),
                           "room": _text(body.get("room"), "room", ROOM_MAX, required=True),
                           "zone": _text(body.get("zone"), "zone", ZONE_MAX), "level": level,
                           "x": None, "y": None}
    if (body.get("x") is None) != (body.get("y") is None):
        raise ControllerError("x, y: both, or neither (a beacon not yet placed on the plan)")
    if body.get("x") is not None:
        out["x"], out["y"] = _fraction(body["x"], "x"), _fraction(body["y"], "y")
    return out


def view(row: dict[str, Any]) -> dict[str, Any]:
    """A stored beacon as the API gives staff."""
    d = row["data"]
    return {"id": beacon_id(row["major"], row["minor"]), "uuid": d["uuid"], "major": row["major"],
            "minor": row["minor"], "room": d["room"], "zone": d.get("zone", ""), "level": row["level"],
            "x": d.get("x"), "y": d.get("y"), "updated_at": row["updated_at"]}


def short_view(row: dict[str, Any]) -> dict[str, Any]:
    """What anyone with a token is given: what a phone needs to listen for it."""
    return {"id": beacon_id(row["major"], row["minor"]), "uuid": row["data"]["uuid"]}


def every(store: Any) -> list[dict[str, Any]]:
    return [view(r) for r in store.beacons()]


def visible(store: Any, viewer: Any) -> list[dict[str, Any]]:
    """Staff the whole registry, everyone else the ids and UUIDs."""
    if visibility.is_staff(viewer):
        return every(store)
    return [short_view(r) for r in store.beacons()]


def interval(game: Optional[dict[str, Any]]) -> int:
    """How often a phone reports a beacon: the game's ``ble_interval_s``, 3 to 30 s (ADR-P3-6), else 5."""
    v = ((game or {}).get("params") or {}).get("ble_interval_s", BLE_INTERVAL_DEFAULT_S)
    ok = isinstance(v, int) and not isinstance(v, bool) and BLE_INTERVAL_MIN_S <= v <= BLE_INTERVAL_MAX_S
    return v if ok else BLE_INTERVAL_DEFAULT_S


def place_of(store: Any, bid: str) -> Optional[dict[str, Any]]:
    """Where a report's beacon puts the player: ``{beacon_id, room, zone, level[, x, y]}``, or None when the
    beacon is not in the registry."""
    major, minor = parse_id(bid)
    row = store.beacon(major, minor)
    if row is None:
        return None
    d = row["data"]
    out: dict[str, Any] = {"beacon_id": bid, "room": d["room"], "level": row["level"]}
    if d.get("zone"):
        out["zone"] = d["zone"]
    if d.get("x") is not None:
        out["x"], out["y"] = d["x"], d["y"]
    return out
