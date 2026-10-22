# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scenarios on the field controller (plan phase 8; ADR-P4-6 as amended, decisions P4-1, P4R7,
P4R8, P4R24).

The GM console's scenario builder sends a manifest (YAML or JSON text) to

    POST /api/v1/scenarios/check   its problems for the editor (GM or read token): the validator's,
                                   then the compiled field.lua's load check in the core
    POST /api/v1/scenarios         GM: compile, check in the core and install it as a mode package
    GET  /api/v1/scenarios         the installed scenarios (GM or read token)
    GET  /api/v1/scenarios/{id}    GM: the manifest and the generated package (field.lua holds the
                                   codes and destinations, so not for the read token)

The scenario compiler (``atalaia_controller.scenarios``) stays plain Python, shared with the site
server; this module is the controller's use of it. The manifest is kept next to its package
(setting ``scenario.manifest:<id>``; decision M8-2), so the GM can read it back, edit it, and install
the same scenario on a standby controller (decision M6-1: a standby needs the package too).

Per game, the names the GM gives the boxes in the Join tab (P4R8, M6-7) are kept in the setting
``scenario.nodes:<game id>`` and are the names the scenario's ``field.nodes()`` returns.

``Meta`` is a scenario package's ``scenario`` block (M7-8): what the routing of objective events
(visibility.py) and the player view need, without reading Lua.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

import yaml
from atalaia_sim.mode import SEPARATOR, ModeError

from . import visibility
from .scenarios import ManifestError, Problem, check_package, compile_scenario, load, validate
from .scenarios.validator import errors

if TYPE_CHECKING:
    from .checkin import Viewer
    from .engine import Controller
    from .modes import ModePackage

MANIFEST_KEY = "scenario.manifest:"
NODES_KEY = "scenario.nodes:"
REVEALED = "scenario.objective.revealed"
# What a player's view of an objective carries: never its target, dependencies or reveals (the
# ids of hidden objectives), and never a code or a destination (those are only in field.lua).
PLAYER_FIELDS = ("id", "type", "name", "description", "i18n", "team", "squad", "visibility", "points", "win",
                 "time_window")


@dataclass(frozen=True)
class Meta:
    """A scenario package's ``mode.yaml``: its names and its ``scenario`` block (M7-8)."""

    id: str
    name: str
    description: str
    i18n: dict[str, Any]
    lang: str
    teams: list[str]
    squads: int
    nodes: dict[str, dict[str, Any]]
    objectives: dict[str, dict[str, Any]] = field(default_factory=dict)  # by id, in the manifest's order

    @staticmethod
    def parse(mode_yaml: str) -> Optional["Meta"]:
        """None for a package that is not a compiled scenario (a hand-written one has no block)."""
        try:
            doc = yaml.safe_load(mode_yaml) or {}
        except yaml.YAMLError:
            return None
        block = doc.get("scenario") if isinstance(doc, dict) and doc.get("kind") == "scenario" else None
        if not isinstance(block, dict):
            return None
        objectives = {o["id"]: dict(o) for o in block.get("objectives") or []
                      if isinstance(o, dict) and isinstance(o.get("id"), str)}
        nodes = {str(k): dict(v) for k, v in (block.get("nodes") or {}).items() if isinstance(v, dict)}
        return Meta(id=str(doc.get("id")), name=str(doc.get("name", doc.get("id"))),
                    description=str(doc.get("description") or ""), i18n=dict(doc.get("i18n") or {}),
                    lang=str(block.get("lang", "pt")), teams=list(block.get("teams") or []),
                    squads=int(block.get("squads") or 0), nodes=nodes, objectives=objectives)

    def box_nodes(self) -> dict[str, str]:
        """The boxes the GM names in the Join tab: name -> role (objective or bomb_site)."""
        return {name: str(spec.get("role")) for name, spec in self.nodes.items() if not spec.get("player")}

    def header(self) -> dict[str, Any]:
        out: dict[str, Any] = {"id": self.id, "name": self.name}
        if self.description:
            out["description"] = self.description
        texts = {lang: {k: v for k, v in t.items() if k in ("name", "description")}
                 for lang, t in self.i18n.items() if isinstance(t, dict)}
        if any(texts.values()):
            out["i18n"] = {lang: t for lang, t in texts.items() if t}
        return out

    def staff_view(self) -> dict[str, Any]:
        """Everything mode.yaml says (the console's Join tab and feed)."""
        return {**self.header(), "lang": self.lang, "teams": self.teams, "squads": self.squads,
                "nodes": self.nodes, "objectives": list(self.objectives.values())}

    def player_view(self, viewer: Optional["Viewer"], game: dict[str, Any], revealed: set[str]) -> dict[str, Any]:
        """The objectives this viewer may know (P4R24): a hidden one only once it is revealed."""
        staff = visibility.is_staff(viewer, game.get("id"))
        objectives = [{k: o[k] for k in PLAYER_FIELDS if k in o} for o in self.objectives.values()
                      if visibility.objective_visible(viewer, o, game)
                      and (staff or o.get("visibility") != "hidden" or o["id"] in revealed)]
        return {**self.header(), "objectives": objectives}


class Refused(Exception):
    """The manifest has errors (``problems`` lists them, warnings too): HTTP 400."""

    status = 400

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        super().__init__("; ".join(str(p) for p in errors(problems)) or "the scenario was refused")


def manifest_text(body: Any) -> str:
    """The manifest of a request body {"manifest": "<YAML or JSON text>"}."""
    text = body.get("manifest") if isinstance(body, dict) else None
    if not isinstance(text, str):
        raise Refused([Problem("", "bad_manifest", 'the request body is {"manifest": "<the scenario\'s YAML>"}')])
    return text


def _package(ctrl: "Controller", package_id: Any) -> Optional["ModePackage"]:
    """One installed package by its id (modes.get refuses a scenario on its own: it is no game)."""
    return next((p for p in ctrl.modes.all() if p.id == package_id), None)


def _summary(manifest: dict[str, Any]) -> dict[str, Any]:
    nodes = manifest.get("nodes") if isinstance(manifest.get("nodes"), dict) else {}
    objectives = manifest.get("objectives") if isinstance(manifest.get("objectives"), list) else []
    return {
        "id": manifest.get("id") if isinstance(manifest.get("id"), str) else None,
        "name": manifest.get("name") if isinstance(manifest.get("name"), str) else None,
        "nodes": [{"name": str(name), "role": spec.get("role"), "player": bool(spec.get("player")),
                   **({"level": spec["level"]} if isinstance(spec.get("level"), int) else {})}
                  for name, spec in nodes.items() if isinstance(spec, dict)],
        "objectives": [{"id": o.get("id"), "type": o.get("type"), "name": o.get("name")}
                       for o in objectives if isinstance(o, dict)],
    }


def check(ctrl: "Controller", text: str) -> dict[str, Any]:
    """Every problem of a manifest, for the editor: the validator's, then (without errors) the
    compiled field.lua's load in the core, as an install would do (P4R9). Never raises for a bad
    manifest: ``ok`` is false and ``problems`` say why."""
    try:
        manifest = load(text)
    except ManifestError as exc:
        return {"ok": False, "problems": [Problem("", "bad_manifest", str(exc)).to_dict()], "id": None,
                "name": None, "nodes": [], "objectives": [], "installed": None, "manifest": None}
    problems = validate(manifest)
    if not errors(problems):
        try:
            package = compile_scenario(manifest)
            if ctrl.core is not None:
                check_package(ctrl.core, package)
        except ModeError as exc:
            problems.append(Problem("", "lua_does_not_load", str(exc)))
    out = {"ok": not errors(problems), "problems": [p.to_dict() for p in problems], **_summary(manifest)}
    # The manifest as read, for the console's block view (phase 5 plan phase 7, decision P5F-3):
    # only when JSON carries it unchanged, else None (the block view then says it cannot show it).
    out["manifest"] = manifest if _json_exact(manifest) else None
    installed = _package(ctrl, out["id"])
    out["installed"] = installed.mode.version if installed is not None else None
    out["checked_in_core"] = ctrl.core is not None
    return out


JSON_INT_MAX = 2**53  # a browser's numbers hold whole numbers exactly up to here


def _json_exact(value: Any) -> bool:
    """True when JSON (and a browser's JavaScript) holds the value as it is: maps with text keys,
    lists, texts, booleans, null, whole numbers within 2**53 and finite numbers. A YAML date, a
    set, a number as a key or a NaN would come back as something else."""
    if value is None or isinstance(value, (bool, str)):
        return True
    if isinstance(value, int):
        return -JSON_INT_MAX <= value <= JSON_INT_MAX
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_json_exact(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _json_exact(v) for k, v in value.items())
    return False


def _uses(game: Optional[dict[str, Any]], scenario_id: str) -> bool:
    return game is not None and game.get("state") != "ended" \
        and scenario_id in str(game.get("mode_id", "")).split(SEPARATOR)


def install(ctrl: "Controller", text: str) -> dict[str, Any]:
    """Compiles a manifest and installs its package (modes.install: the core's load check). The
    manifest is kept next to it. Refused: errors in the manifest; Conflict (engine): the id is
    another kind of package, or the live game runs this scenario."""
    from .engine import Conflict  # noqa: PLC0415 (engine imports this module)

    try:
        manifest = load(text)
    except ManifestError as exc:
        raise Refused([Problem("", "bad_manifest", str(exc))]) from None
    problems = validate(manifest)
    if errors(problems):
        raise Refused(problems)
    package = compile_scenario(manifest)
    existing = _package(ctrl, package.id)
    if existing is not None and existing.kind != "scenario":
        raise Conflict(f"{package.id} is installed as a {existing.kind}, not a scenario; give the scenario "
                       "another id")
    if _uses(ctrl.game, package.id):
        raise Conflict(f"game {ctrl.game['id']} runs this scenario; end it before you replace the scenario")
    pkg = ctrl.modes.install(package.files)
    ctrl.store.set_setting(MANIFEST_KEY + pkg.id, text)
    return {**describe(pkg, has_manifest=True), "warnings": [p.to_dict() for p in problems],
            "replaced": existing is not None}


def describe(pkg: "ModePackage", has_manifest: bool) -> dict[str, Any]:
    meta = Meta.parse(pkg.files.get("mode.yaml", ""))
    out: dict[str, Any] = {"id": pkg.id, "version": pkg.mode.version, "name": pkg.mode.name,
                           "description": pkg.mode.description, "i18n": pkg.mode.i18n,
                           "params": pkg.mode.params, "manifest": has_manifest, "compiled": meta is not None}
    if meta is not None:
        out.update({"lang": meta.lang, "teams": meta.teams, "squads": meta.squads,
                    "nodes": [{"name": n, "role": s.get("role"), "player": bool(s.get("player")),
                               **({"level": s["level"]} if isinstance(s.get("level"), int) else {})}
                              for n, s in meta.nodes.items()],
                    "objectives": [{"id": o["id"], "type": o.get("type"), "name": o.get("name"),
                                    "i18n": o.get("i18n") or {}} for o in meta.objectives.values()]})
    return out


def listing(ctrl: "Controller") -> list[dict[str, Any]]:
    return [describe(p, ctrl.store.get_setting(MANIFEST_KEY + p.id) is not None)
            for p in ctrl.modes.all() if p.kind == "scenario"]


def read(ctrl: "Controller", scenario_id: str) -> dict[str, Any]:
    """The manifest (None for a package uploaded as files) and the generated package's files."""
    from .engine import NotFound  # noqa: PLC0415

    pkg = _package(ctrl, scenario_id)
    if pkg is None or pkg.kind != "scenario":
        raise NotFound(f"no scenario {scenario_id}")
    manifest = ctrl.store.get_setting(MANIFEST_KEY + pkg.id)
    return {**describe(pkg, manifest is not None), "manifest_text": manifest, "files": dict(pkg.files)}


# --- per game: the boxes' names and what is revealed --------------------------------------------


def node_names(ctrl: "Controller", game_id: int) -> dict[int, str]:
    raw = ctrl.store.get_setting(f"{NODES_KEY}{game_id}")
    if not raw:
        return {}
    try:
        return {int(k): str(v) for k, v in json.loads(raw).items()}
    except (ValueError, AttributeError):
        return {}


def name_node(ctrl: "Controller", game_id: int, node_id: int, name: str) -> dict[int, str]:
    """Gives a box a scenario node's name; the name leaves any box that had it."""
    names = {k: v for k, v in node_names(ctrl, game_id).items() if v != name}
    names[node_id] = name
    ctrl.store.set_setting(f"{NODES_KEY}{game_id}", json.dumps({str(k): v for k, v in sorted(names.items())}))
    return names


def revealed(ctrl: "Controller", game_id: int) -> set[str]:
    """The objectives whose reveal is in the game's log."""
    return {str((e.get("data") or {}).get("objective")) for e in ctrl.store.events(game_id, event_type=REVEALED)}
