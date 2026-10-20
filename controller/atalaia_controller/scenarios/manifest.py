# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario manifest (ADR-P4-6 as amended): reading it, its names (decision P4R8) and the
objective types.

A manifest is YAML (or JSON, which is YAML too). Reading it never runs code (PyYAML's safe
loader) and refuses a key given twice in one map, which PyYAML would otherwise keep silently
(the last one). What each key means is in controller/README.md, "Scenarios".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

import yaml

# The names (P4R8). An objective id goes into every scenario event (data key 34), so it is short.
OBJECTIVE_ID = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
# A mode id, as modes.py checks it on upload.
SCENARIO_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$")
PARAM_NAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
PLAYER_ROLE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
CODE = re.compile(r"^[0-9]{1,8}$")  # the objectives package takes up to 8 digits, then #

OBJECTIVES_PACKAGE = "org.atalaia.objectives"
MODE_ID_MAX = 63  # a game's id in a join (protocol/join.md)
# The scenario leads the game's id and the objectives package follows (decision M6-1).
SCENARIO_ID_MAX = MODE_ID_MAX - len("+" + OBJECTIVES_PACKAGE)
TEAM_NAME_MAX = 23  # the core's ATALAIA_TEAM_NAME_MAX - 1 (engine.py)
TEAMS_MAX = 8
SQUADS_MAX = 16  # engine.py SQUADS_MAX
NODE_NAME_MAX = 24  # a box's name in its HELLO (protocol/schema/messages.yaml)
NAME_MAX = 64  # bytes: a scenario's or an objective's name
DESCRIPTION_MAX = 2000
VERSION_MAX = 32
OBJECTIVES_MAX = 64
NODES_MAX = 64
POINTS_MAX = 100_000
WINDOW_MAX_MIN = 7 * 24 * 60  # a week, in minutes
MANIFEST_MAX_BYTES = 256 * 1024
LANGS = ("pt", "en")  # the objectives package's screens (modes/objectives/node.lua)
TRANSLATIONS = ("pt",)  # texts are in English, with i18n.pt (P4R8)
NODE_ROLES = ("objective", "bomb_site")  # org.atalaia.objectives' roles
VISIBILITY = ("public", "team", "squad", "hidden")
POLYGON_MAX = 32  # ATALAIA_GEO_POLYGON_MAX (core/include/atalaia/geo.h)
RADIUS_WARN_M = 10  # a phone's GPS is rarely better than this


@dataclass(frozen=True)
class Param:
    """One parameter of an objective type: its type and range, and whether it is required."""

    kind: str  # int, bool, code, destination
    required: bool = False
    lo: int = 0
    hi: int = 0


@dataclass(frozen=True)
class ObjectiveType:
    """An objective type (ADR-P4-6's table): what it targets, its parameters, and what it needs."""

    target: Optional[str]  # "objective" or "bomb_site" (a box's role), "player", or None
    params: dict[str, Param]
    needs_team: bool = False  # an assignee team is required
    needs_end: bool = False  # a time window's end is required (it is judged then)


_HOLD = Param("int", lo=0, hi=600_000)
TYPES: dict[str, ObjectiveType] = {
    # Hold the target: completed when the team has held it for duration_s (0: at the capture).
    "capture_and_hold": ObjectiveType("objective", {"hold_ms": _HOLD, "duration_s": Param("int", lo=0, hi=86_400)}),
    # Type the code on the target's keypad.
    "enter_code": ObjectiveType("objective", {"code": Param("code", required=True)}),
    # Scan tag_count tags at the target: players' own tags, or with any, any cards (intel).
    "scan_tags": ObjectiveType("objective", {"tag_count": Param("int", required=True, lo=1, hi=100),
                                             "any": Param("bool")}),
    # A player with the target's role (the VIP) reaches the destination, by position.fix.
    "escort": ObjectiveType("player", {"destination": Param("destination", required=True),
                                       "max_acc_m": Param("int", lo=1, hi=1000)}),
    # Arm the bomb at the target and let it explode; a defuse fails it.
    "destroy": ObjectiveType("bomb_site", {"hold_ms": _HOLD, "defuse_ms": _HOLD,
                                           "fuse_s": Param("int", lo=10, hi=3600)}),
    # Keep the target for duration_s from when the objective opens; an enemy capture fails it.
    "defend": ObjectiveType("objective", {"duration_s": Param("int", required=True, lo=1, hi=86_400),
                                          "hold_ms": _HOLD}, needs_team=True),
    # Keep at least minimum_lives of Respawn's lives until the time window's end.
    "survive": ObjectiveType(None, {"minimum_lives": Param("int", required=True, lo=0, hi=1000)},
                             needs_team=True, needs_end=True),
}

TOP_KEYS = ("id", "version", "name", "description", "author", "lang", "teams", "squads", "params", "i18n",
            "nodes", "objectives")
OBJECTIVE_KEYS = ("id", "type", "name", "description", "i18n", "target", "assignee", "params", "visibility",
                  "depends_on", "time_window", "effect")


class ManifestError(Exception):
    """The text is not a manifest at all (not YAML, not a map, too large)."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML's safe loader, refusing a key given twice in one map."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in seen
        except TypeError:  # an unhashable key: the safe constructor says so below
            duplicate = False
        if duplicate:
            raise yaml.constructor.ConstructorError(None, None, f"the key {key!r} is given twice",
                                                    key_node.start_mark)
        try:
            seen.add(key)
        except TypeError:
            pass
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_text(text: str) -> dict[str, Any]:
    """The manifest in a YAML or JSON text. ManifestError when it is not one."""
    if not isinstance(text, str):
        raise ManifestError("a scenario manifest is text")
    if len(text.encode("utf-8")) > MANIFEST_MAX_BYTES:
        raise ManifestError(f"the manifest is larger than {MANIFEST_MAX_BYTES} bytes")
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as exc:
        raise ManifestError(f"not valid YAML: {exc}") from None
    if not isinstance(data, dict):
        raise ManifestError("a scenario manifest is a map (id, version, name, nodes, objectives, ...)")
    return data


def text_ok(value: Any, max_bytes: int, required: bool = True) -> bool:
    if value is None:
        return not required
    return isinstance(value, str) and (value.strip() != "" or not required) and len(value.encode()) <= max_bytes


def translated(entry: dict[str, Any], lang: str, key: str = "name") -> Optional[str]:
    """A text in the language: i18n.<lang>.<key>, else the English one."""
    if lang != "en":
        i18n = entry.get("i18n")
        if isinstance(i18n, dict) and isinstance(i18n.get(lang), dict):
            value = i18n[lang].get(key)
            if isinstance(value, str) and value:
                return value
    value = entry.get(key)
    return value if isinstance(value, str) else None


def default_visibility(objective: dict[str, Any]) -> str:
    assignee = objective.get("assignee") or {}
    if isinstance(assignee, dict) and assignee.get("squad") is not None:
        return "squad"
    if isinstance(assignee, dict) and assignee.get("team") is not None:
        return "team"
    return "public"
