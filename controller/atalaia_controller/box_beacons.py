# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Field Boxes as iBeacons (decisions BBC-1 to BBC-12, protocol/box-beacon.md).

A Field Box joined to a game advertises a non-connectable iBeacon, so a phone that hears it is placed where the
GM put the box. Nothing is registered by hand: the controller derives each box's beacon from the box itself.

  * ``uuid``: the field's, ``HMAC-SHA256(join key, "atalaia box beacon uuid v1")[:16]`` with the version nibble 8
    and the RFC 4122 variant. One per field; a phone filters by it. The box derives the same from the join key it
    holds (firmware/esp32/main/box_beacon.c), so nothing about it travels.
  * ``major``: the constant ``MAJOR`` (45253, 0xB0C5), which a GM's tag may not use (beacons.py refuses it), so a
    box's id ``major:minor`` never collides with a tag's.
  * ``minor``: the box's node id in the game.
  * ``room``: the box's name (the GM's name for it in a scenario, else the node's own), or the room the GM gave it
    here; ``level``, ``x`` and ``y``: the box's place on the field view (ML-4), so a box moved or put on another
    level moves its beacon with it. A box the GM has not placed is not registered (it has no level or place): it
    still advertises, and a phone that hears it reports nothing.

The beacons belong to the live game (a node id is the game's), they are never stored, and a box may be disabled
(its beacon is then left out of the registry, so a phone's report of it is refused) or the whole field's turned off
(``box_beacons`` setting, off: the next join says so, key 19 of the join payload, and the boxes do not advertise).
The registry the controller serves lists the boxes with the tags: staff see each box with ``kind: "box"``, its node
and whether it is enabled; everyone else only the id and UUID of the enabled ones, as for a tag.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid as uuidmod
from typing import TYPE_CHECKING, Any, Optional

from . import beacons as beaconsmod
from . import field_levels as levelsmod
from . import visibility
from .beacons import BOX_MAJOR as MAJOR
from .engine import BOX_BEACONS_SETTING as SETTING_ENABLED
from .engine import ControllerError

if TYPE_CHECKING:
    from .engine import Controller

LABEL = b"atalaia box beacon uuid v1"
SETTING_OFF = "box_beacons_off:"     # + game id: JSON list of the node ids the GM disabled
SETTING_ROOMS = "box_beacon_rooms:"  # + game id: JSON {node id: room} the GM gave
ROOM_MAX = 48


def derive_uuid(join_key: bytes) -> str:
    """The field's box-beacon UUID, upper case 8-4-4-4-12."""
    u = bytearray(hmac.new(join_key, LABEL, hashlib.sha256).digest()[:16])
    u[6] = (u[6] & 0x0F) | 0x80
    u[8] = (u[8] & 0x3F) | 0x80
    return str(uuidmod.UUID(bytes=bytes(u))).upper()


def adv_bytes(join_key: bytes, node_id: int, measured_power: int = -59) -> bytes:
    """The 30 advertisement bytes a box with this node id sends (what a test or a bench phone compares)."""
    u = uuidmod.UUID(derive_uuid(join_key)).bytes
    return (bytes([0x02, 0x01, 0x06, 0x1A, 0xFF, 0x4C, 0x00, 0x02, 0x15]) + u + MAJOR.to_bytes(2, "big")
            + node_id.to_bytes(2, "big") + (measured_power & 0xFF).to_bytes(1, "big"))


def box_id(node_id: int) -> str:
    return f"{MAJOR}:{node_id}"


def enabled(ctrl: "Controller") -> bool:
    """Whether the field's boxes advertise (the GM's setting; on by default)."""
    return ctrl.store.get_setting(SETTING_ENABLED) != "off"


def set_enabled(ctrl: "Controller", value: Any) -> dict[str, Any]:
    if not isinstance(value, bool):
        raise ControllerError("enabled: true or false")
    ctrl.store.set_setting(SETTING_ENABLED, "on" if value else "off")
    return status(ctrl)


def _json_setting(ctrl: "Controller", key: str, default: Any) -> Any:
    raw = ctrl.store.get_setting(key)
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def disabled_nodes(ctrl: "Controller", game_id: int) -> set[int]:
    got = _json_setting(ctrl, f"{SETTING_OFF}{game_id}", [])
    return {n for n in got if isinstance(n, int)} if isinstance(got, list) else set()


def rooms(ctrl: "Controller", game_id: int) -> dict[int, str]:
    got = _json_setting(ctrl, f"{SETTING_ROOMS}{game_id}", {})
    if not isinstance(got, dict):
        return {}
    return {int(k): v for k, v in got.items() if str(k).isdigit() and isinstance(v, str)}


def _room_text(v: Any) -> str:
    if not isinstance(v, str):
        raise ControllerError("room: a text")
    text = " ".join(w for w in v.split(" ") if w)
    if len(text) > ROOM_MAX or any(ord(c) < 0x20 or 0x7F <= ord(c) < 0xA0 for c in v):
        raise ControllerError(f"room: at most {ROOM_MAX} characters on one line")
    return text


def _box_nodes(ctrl: "Controller") -> dict[int, str]:
    """The live game's boxes and their names: node id -> the GM's scenario name, else the node's own."""
    game = ctrl.game
    if game is None:
        return {}
    names: dict[int, str] = {}
    fc = ctrl.fc
    if fc is not None:
        for n in fc.nodes.values():
            names[n.node_id] = ctrl.scenario_names.get(n.node_id, n.name)
    for nid in game.get("assignments", {}):
        if str(nid).isdigit():
            names.setdefault(int(nid), ctrl.scenario_names.get(int(nid), f"node-{int(nid)}"))
    names.pop(ctrl.node_id, None)
    return names


def is_live_box(ctrl: "Controller", game_id: int, node_id: int) -> bool:
    """Whether ``node_id`` is a box of the live game ``game_id``: placing it changes the registry."""
    return ctrl.game is not None and ctrl.game["id"] == game_id and node_id in _box_nodes(ctrl)


def boxes(ctrl: "Controller") -> list[dict[str, Any]]:
    """Every placed box of the live game as a beacon, whether enabled or not, by node id. ``[]`` with no join
    key (a controller that cannot join boxes) or no live game."""
    game = ctrl.game
    if game is None or not ctrl.join_key:
        return []
    uuid = derive_uuid(ctrl.join_key)
    meta = levelsmod.load(ctrl.store)
    placed = ctrl.store.positions(game["id"])
    off = disabled_nodes(ctrl, game["id"])
    given = rooms(ctrl, game["id"])
    out = []
    for nid, name in sorted(_box_nodes(ctrl).items()):
        pos = placed.get(nid)
        if pos is None or not 1 <= nid <= 0xFFFE:
            continue
        out.append({"id": box_id(nid), "kind": "box", "uuid": uuid, "major": MAJOR, "minor": nid,
                    "node_id": nid, "name": name, "room": given.get(nid) or name, "room_given": nid in given,
                    "zone": "", "level": levelsmod.shown(meta, pos["level"]), "x": pos["x"], "y": pos["y"],
                    "enabled": nid not in off, "updated_at": None})
    return out


def registered(ctrl: "Controller") -> list[dict[str, Any]]:
    """The boxes a phone may be placed by: enabled, with the field's setting on."""
    if not enabled(ctrl):
        return []
    return [b for b in boxes(ctrl) if b["enabled"]]


def short_view(b: dict[str, Any]) -> dict[str, Any]:
    return {"id": b["id"], "uuid": b["uuid"]}


def registry(ctrl: "Controller", viewer: Any) -> list[dict[str, Any]]:
    """What GET /api/v1/beacons lists: the GM's tags and the boxes. Staff see all of both (a box with its node,
    name, room and whether it is enabled, ``kind: "box"``); everyone else the id and UUID of each tag and of each
    enabled box, which is what a phone listens for."""
    tags = beaconsmod.visible(ctrl.store, viewer)
    if visibility.is_staff(viewer):
        return tags + boxes(ctrl)
    return tags + [short_view(b) for b in registered(ctrl)]


def place_of(ctrl: "Controller", bid: str) -> Optional[dict[str, Any]]:
    """Where a report of box ``bid`` puts the player, as beacons.place_of does for a tag, or None when it is
    not a registered box."""
    for b in registered(ctrl):
        if b["id"] == bid:
            out: dict[str, Any] = {"beacon_id": bid, "room": b["room"], "level": b["level"], "x": b["x"], "y": b["y"]}
            return out
    return None


def status(ctrl: "Controller") -> dict[str, Any]:
    """The field's box-beacon setting for the console: on or off, and the UUID the boxes advertise."""
    return {"enabled": enabled(ctrl), "major": MAJOR,
            "uuid": derive_uuid(ctrl.join_key) if ctrl.join_key else None}


def update_box(ctrl: "Controller", node_id: int, body: Any) -> dict[str, Any]:
    """The GM's change to one box's beacon (PUT /api/v1/box-beacons/{node_id}): ``enabled`` (a box disabled is
    left out of the registry) and/or ``room`` (a text, or null for the box's name again)."""
    game = ctrl.game
    if game is None:
        raise ControllerError("no live game: the boxes' beacons belong to the game")
    if not isinstance(body, dict) or not body or set(body) - {"enabled", "room"}:
        raise ControllerError('the body is {"enabled": true|false} and/or {"room": "text"|null}')
    if node_id not in _box_nodes(ctrl):
        raise ControllerError(f"node id {node_id} is not a box of this game")
    with ctrl._lock:
        if "enabled" in body:
            if not isinstance(body["enabled"], bool):
                raise ControllerError("enabled: true or false")
            off = disabled_nodes(ctrl, game["id"])
            (off.discard if body["enabled"] else off.add)(node_id)
            ctrl.store.set_setting(f"{SETTING_OFF}{game['id']}", json.dumps(sorted(off)))
        if "room" in body:
            given = rooms(ctrl, game["id"])
            if body["room"] is None or _room_text(body["room"]) == "":
                given.pop(node_id, None)
            else:
                given[node_id] = _room_text(body["room"])
            ctrl.store.set_setting(f"{SETTING_ROOMS}{game['id']}", json.dumps({str(k): v for k, v in given.items()}))
    for b in boxes(ctrl):
        if b["node_id"] == node_id:
            return b
    return {"node_id": node_id, "id": box_id(node_id), "placed": False, "enabled": node_id not in disabled_nodes(
        ctrl, game["id"])}
