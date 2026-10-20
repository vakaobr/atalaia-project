# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Checks a scenario manifest before it is compiled (ADR-P4-6's rules, as amended).

``validate(manifest)`` returns every problem it finds, each with the path of the value
(``objectives[2].params.code``), a short code that other implementations match
(protocol/vectors/scenario.json) and a sentence for the GM. Errors stop the compiler; warnings
do not.
"""

from __future__ import annotations

import json
import math
import unicodedata
from dataclasses import dataclass
from typing import Any, Optional

from atalaia_sim import codec
from atalaia_sim.field_controller import CMD_PARAMS_MAX
from atalaia_sim.protocol import RF_PAYLOAD_MAX

from . import manifest as m
from .lua import setup_command

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Problem:
    path: str  # where: "" for the manifest itself, "objectives[1].depends_on[0]"
    code: str  # what, for programs (protocol/vectors/scenario.json)
    message: str  # what, for the GM
    level: str = ERROR

    def __str__(self) -> str:
        where = f"{self.path}: " if self.path else ""
        return f"{where}{self.level}: {self.message} ({self.code})"

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "code": self.code, "message": self.message, "level": self.level}


def errors(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level == ERROR]


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _has_controls(text: str) -> bool:
    """Control characters in a one-line text (a name): newlines, escapes, bidi overrides."""
    return any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in text)


class _Checker:
    def __init__(self, manifest: dict[str, Any]) -> None:
        self.m = manifest
        self.problems: list[Problem] = []

    def err(self, path: str, code: str, message: str) -> None:
        self.problems.append(Problem(path, code, message, ERROR))

    def warn(self, path: str, code: str, message: str) -> None:
        self.problems.append(Problem(path, code, message, WARNING))

    def unknown_keys(self, value: dict[str, Any], allowed: tuple[str, ...], path: str) -> None:
        for key in value:
            if key not in allowed:
                where = f"{path}.{key}" if path else str(key)
                self.err(where, "unknown_key", f"unknown key {key!r} (allowed: {', '.join(allowed)})")

    def text(self, value: Any, path: str, max_bytes: int, required: bool, one_line: bool = True) -> bool:
        if value is None:
            if required:
                self.err(path, "missing", "required")
            return False
        if not isinstance(value, str) or (required and not value.strip()):
            self.err(path, "bad_text", "must be a non-empty text")
            return False
        if len(value.encode()) > max_bytes:
            self.err(path, "too_long", f"at most {max_bytes} bytes")
            return False
        if one_line and _has_controls(value):
            self.err(path, "bad_text", "must be one line, without control characters")
            return False
        return True

    # -- the manifest --

    def run(self) -> list[Problem]:
        mf = self.m
        self.unknown_keys(mf, m.TOP_KEYS, "")
        self.check_id()
        version = mf.get("version")
        if _is_int(version) or isinstance(version, float):
            version = str(version)
        self.text(version, "version", m.VERSION_MAX, True)
        self.text(mf.get("name"), "name", m.NAME_MAX, True)
        self.text(mf.get("description"), "description", m.DESCRIPTION_MAX, False, one_line=False)
        self.text(mf.get("author"), "author", m.NAME_MAX, False)
        lang = mf.get("lang", "pt")
        if lang not in m.LANGS:
            self.err("lang", "bad_lang", f"the boxes' screens are in {' or '.join(m.LANGS)}")
        self.teams = self.check_teams()
        squads = mf.get("squads", 0)
        if not _is_int(squads) or not 0 <= squads <= m.SQUADS_MAX:
            self.err("squads", "bad_squads", f"a number of squads per team, 0 (none) to {m.SQUADS_MAX}")
            squads = 0
        self.squads = squads
        self.params = self.check_params()
        self.check_i18n(mf.get("i18n"), "i18n", ("name", "description", "params"))
        self.nodes = self.check_nodes()
        objectives = mf.get("objectives")
        if not isinstance(objectives, list) or not objectives:
            self.err("objectives", "missing" if objectives is None else "bad_objectives",
                     "a list of at least one objective")
            return self.problems
        if len(objectives) > m.OBJECTIVES_MAX:
            self.err("objectives", "too_many", f"at most {m.OBJECTIVES_MAX} objectives")
        self.ids: dict[str, int] = {}
        for i, o in enumerate(objectives):
            oid = o.get("id") if isinstance(o, dict) else None
            if isinstance(oid, str) and m.OBJECTIVE_ID.match(oid):
                if oid in self.ids:
                    self.err(f"objectives[{i}].id", "duplicate_id",
                             f"{oid!r} is already the id of objectives[{self.ids[oid]}]")
                else:
                    self.ids[oid] = i
        self.revealed_by: set[str] = set()
        for o in objectives:
            effect = o.get("effect") if isinstance(o, dict) else None
            if isinstance(effect, dict) and isinstance(effect.get("reveal"), list):
                self.revealed_by.update(r for r in effect["reveal"] if isinstance(r, str))
        targeted: dict[str, int] = {}
        for i, o in enumerate(objectives):
            self.check_objective(i, o, targeted)
        self.check_cycles(objectives)
        for name in self.nodes:
            if name not in targeted:
                self.warn(f"nodes.{name}", "unused_node", "no objective targets this node")
        return self.problems

    def check_id(self) -> None:
        sid = self.m.get("id")
        if sid is None:
            self.err("id", "missing", "required: the package id, like org.club.foxhound")
        elif not isinstance(sid, str) or not m.SCENARIO_ID.match(sid):
            self.err("id", "bad_id", "a package id like org.club.foxhound: lowercase letters, digits, - and _, "
                     "in at least two parts joined by dots")
        elif len(sid.encode()) > m.SCENARIO_ID_MAX:
            self.err("id", "id_too_long", f"at most {m.SCENARIO_ID_MAX} bytes, so that "
                     f"{sid}+{m.OBJECTIVES_PACKAGE} fits a join's {m.MODE_ID_MAX}")
        elif sid == m.OBJECTIVES_PACKAGE or sid.startswith("org.atalaia."):
            self.err("id", "bad_id", "org.atalaia. is the built-in modes' namespace: use your club's")

    def check_teams(self) -> list[str]:
        teams = self.m.get("teams", ["red", "blue"])
        if (not isinstance(teams, list) or not 1 <= len(teams) <= m.TEAMS_MAX
                or not all(isinstance(t, str) and 0 < len(t.encode()) <= m.TEAM_NAME_MAX and not _has_controls(t)
                           for t in teams)):
            self.err("teams", "bad_teams", f"a list of 1 to {m.TEAMS_MAX} team names of 1 to {m.TEAM_NAME_MAX} "
                     "bytes, as the game names its teams (red, blue, ...)")
            return [t for t in teams if isinstance(t, str)] if isinstance(teams, list) else []
        if len(set(teams)) != len(teams):
            self.err("teams", "bad_teams", "a team is named twice")
        return list(teams)

    def check_params(self) -> dict[str, dict[str, Any]]:
        params = self.m.get("params")
        if params is None:
            return {}
        if not isinstance(params, dict):
            self.err("params", "bad_params", "a map of parameter names to their schema")
            return {}
        good = {}
        for name, spec in params.items():
            path = f"params.{name}"
            if not isinstance(name, str) or not m.PARAM_NAME.match(name):
                self.err(path, "bad_name", "1-32 of a-z, 0-9 and _, starting with a letter")
                continue
            if not isinstance(spec, dict):
                self.err(path, "bad_params", "a map: { type: int, min, max, default, label }")
                continue
            self.unknown_keys(spec, ("type", "min", "max", "default", "label", "gm_only"), path)
            if spec.get("type") != "int":
                self.err(f"{path}.type", "bad_param_type", "a scenario's parameters are int (whole numbers): "
                         "objectives' points")
                continue
            lo, hi, default = spec.get("min", 0), spec.get("max", m.POINTS_MAX), spec.get("default")
            if not _is_int(lo) or not _is_int(hi) or not 0 <= lo <= hi <= m.POINTS_MAX:
                self.err(path, "bad_range", f"min and max are whole numbers from 0 to {m.POINTS_MAX}, min <= max")
                continue
            if not _is_int(default) or not lo <= default <= hi:
                self.err(f"{path}.default", "bad_default", f"a whole number from {lo} to {hi}")
                continue
            self.text(spec.get("label"), f"{path}.label", m.NAME_MAX * 2, False)
            if not isinstance(spec.get("gm_only", False), bool):
                self.err(f"{path}.gm_only", "bad_bool", "true or false")
            good[name] = spec
        return good

    def check_i18n(self, i18n: Any, path: str, keys: tuple[str, ...]) -> None:
        if i18n is None:
            return
        if not isinstance(i18n, dict):
            self.err(path, "bad_i18n", "a map of a language (pt) to its texts")
            return
        for lang, strings in i18n.items():
            where = f"{path}.{lang}"
            if lang not in m.TRANSLATIONS:
                self.err(where, "bad_lang", f"texts are in English with translations in {', '.join(m.TRANSLATIONS)}")
                continue
            if not isinstance(strings, dict):
                self.err(where, "bad_i18n", f"a map of {', '.join(keys)}")
                continue
            self.unknown_keys(strings, keys, where)
            self.text(strings.get("name"), f"{where}.name", m.NAME_MAX, False)
            self.text(strings.get("description"), f"{where}.description", m.DESCRIPTION_MAX, False, one_line=False)
            labels = strings.get("params")
            if labels is not None and "params" in keys:
                if not isinstance(labels, dict):
                    self.err(f"{where}.params", "bad_i18n", "a map of parameter names to labels")
                    continue
                for name, label in labels.items():
                    if not isinstance(self.m.get("params"), dict) or name not in self.m["params"]:
                        self.err(f"{where}.params.{name}", "unknown_param", f"{name!r} is not a parameter")
                    else:
                        self.text(label, f"{where}.params.{name}", m.NAME_MAX * 2, True)

    def check_nodes(self) -> dict[str, dict[str, Any]]:
        nodes = self.m.get("nodes")
        if nodes is None:
            return {}
        if not isinstance(nodes, dict):
            self.err("nodes", "bad_nodes", "a map of node names to { role: objective } or { role: bomb_site }")
            return {}
        if len(nodes) > m.NODES_MAX:
            self.err("nodes", "too_many", f"at most {m.NODES_MAX} nodes")
        good = {}
        for name, spec in nodes.items():
            path = f"nodes.{name}"
            if not isinstance(name, str) or not name.strip() or len(name.encode()) > m.NODE_NAME_MAX \
                    or _has_controls(name):
                self.err(path, "bad_name", f"a node's name: 1 to {m.NODE_NAME_MAX} bytes on one line, as the "
                         "GM names the box in the console")
                continue
            if not isinstance(spec, dict):
                self.err(path, "bad_node", "a map: { role: objective }, { role: bomb_site } or "
                         "{ player: true, role: vip }")
                continue
            self.unknown_keys(spec, ("role", "player"), path)
            player = spec.get("player", False)
            role = spec.get("role")
            if not isinstance(player, bool):
                self.err(f"{path}.player", "bad_bool", "true or false")
                continue
            if player:
                role = spec.get("role", "vip")
                if not isinstance(role, str) or not m.PLAYER_ROLE.match(role):
                    self.err(f"{path}.role", "bad_role", "a player's check-in role: 1-24 of a-z, 0-9 and _")
                    continue
            elif role not in m.NODE_ROLES:
                self.err(f"{path}.role", "bad_role", f"a box runs {m.OBJECTIVES_PACKAGE}: role "
                         f"{' or '.join(m.NODE_ROLES)} (a player: player: true)")
                continue
            good[name] = {"role": role, "player": player}
        return good

    # -- one objective --

    def check_objective(self, i: int, o: Any, targeted: dict[str, int]) -> None:
        path = f"objectives[{i}]"
        if not isinstance(o, dict):
            self.err(path, "bad_objective", "an objective is a map: { id, type, name, ... }")
            return
        before = len(errors(self.problems))
        self.unknown_keys(o, m.OBJECTIVE_KEYS, path)
        oid = o.get("id")
        if oid is None:
            self.err(f"{path}.id", "missing", "required")
        elif not isinstance(oid, str) or not m.OBJECTIVE_ID.match(oid):
            self.err(f"{path}.id", "bad_id", "1-24 of a-z, 0-9 and _, starting with a letter (it goes in every "
                     "scenario event)")
        self.text(o.get("name"), f"{path}.name", m.NAME_MAX, True)
        self.text(o.get("description"), f"{path}.description", m.DESCRIPTION_MAX, False, one_line=False)
        self.check_i18n(o.get("i18n"), f"{path}.i18n", ("name", "description"))
        kind = o.get("type")
        otype = m.TYPES.get(kind) if isinstance(kind, str) else None
        if kind is None:
            self.err(f"{path}.type", "missing", f"required: one of {', '.join(m.TYPES)}")
        elif otype is None:
            self.err(f"{path}.type", "unknown_type", f"{kind!r} is not an objective type ({', '.join(m.TYPES)})")
        team = self.check_assignee(o, path, otype)
        if otype is not None:
            self.check_target(o, path, otype, targeted, i)
            self.check_type_params(o, path, otype)
        self.check_visibility(o, path, team)
        self.check_refs(o.get("depends_on"), f"{path}.depends_on", oid)
        self.check_window(o, path, otype)
        self.check_effect(o, path, oid)
        if otype is not None and otype.target in m.NODE_ROLES and len(errors(self.problems)) == before:
            self.check_sizes(o, path)  # only for an objective with no other error: its setup can be built
        if isinstance(oid, str) and m.OBJECTIVE_ID.match(oid):
            self.check_events(oid, path)

    def check_assignee(self, o: dict[str, Any], path: str, otype: Optional[m.ObjectiveType]) -> Optional[str]:
        assignee = o.get("assignee")
        if assignee is None:
            assignee = {}
        elif not isinstance(assignee, dict):
            self.err(f"{path}.assignee", "bad_assignee", "a map: { team, squad }")
            return None
        self.unknown_keys(assignee, ("team", "squad"), f"{path}.assignee")
        team, squad = assignee.get("team"), assignee.get("squad")
        if team is None:
            if otype is not None and otype.needs_team:
                self.err(f"{path}.assignee.team", "missing_team",
                         f"{o.get('type')} is for one team: name it ({', '.join(self.teams)})")
        elif team not in self.teams:
            self.err(f"{path}.assignee.team", "unknown_team", f"{team!r} is not one of the scenario's teams "
                     f"({', '.join(self.teams)})")
            team = None
        if squad is not None:
            if team is None and assignee.get("team") is None:
                self.err(f"{path}.assignee.squad", "squad_needs_team", "a squad belongs to a team: name the team")
            elif self.squads == 0:
                self.err(f"{path}.assignee.squad", "unknown_squad", "the scenario has no squads (squads: 0)")
            elif not _is_int(squad) or not 1 <= squad <= self.squads:
                self.err(f"{path}.assignee.squad", "unknown_squad", f"squads are numbers, 1 to {self.squads}")
        return team

    def check_target(self, o: dict[str, Any], path: str, otype: m.ObjectiveType, targeted: dict[str, int],
                     i: int) -> None:
        target = o.get("target")
        if otype.target is None:
            if target is not None:
                self.err(f"{path}.target", "unexpected_target", f"{o.get('type')} has no target")
            return
        if target is None:
            self.err(f"{path}.target", "missing_target", "required: a node of the nodes map")
            return
        node = self.nodes.get(target) if isinstance(target, str) else None
        if node is None:
            raw = self.m.get("nodes")
            if not isinstance(target, str) or not isinstance(raw, dict) or target not in raw:
                self.err(f"{path}.target", "unknown_node", f"{target!r} is not in the nodes map")
            return
        if otype.target == "player":
            if not node["player"]:
                self.err(f"{path}.target", "wrong_role", f"{o.get('type')} targets a player "
                         f"(nodes.{target}: {{ player: true, role: vip }})")
        elif node["player"] or node["role"] != otype.target:
            self.err(f"{path}.target", "wrong_role", f"{o.get('type')} needs a node with the role {otype.target}")
        elif target in targeted:
            self.err(f"{path}.target", "node_shared", f"{target!r} is already the target of "
                     f"objectives[{targeted[target]}]: a box serves one objective")
        else:
            targeted[target] = i
        if node["player"]:
            targeted.setdefault(target, i)  # a VIP may be escorted to more than one place

    def check_type_params(self, o: dict[str, Any], path: str, otype: m.ObjectiveType) -> None:
        params = o.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            self.err(f"{path}.params", "bad_params", "a map of the type's parameters")
            return
        for name in params:
            if name not in otype.params:
                self.err(f"{path}.params.{name}", "unknown_param", f"{o.get('type')} takes "
                         f"{', '.join(otype.params) or 'no parameters'}")
        for name, spec in otype.params.items():
            where = f"{path}.params.{name}"
            if name not in params:
                if spec.required:
                    self.err(where, "missing_param", f"{o.get('type')} needs {name}")
                continue
            value = params[name]
            if spec.kind == "int":
                if not _is_int(value) or not spec.lo <= value <= spec.hi:
                    self.err(where, "bad_param", f"a whole number from {spec.lo} to {spec.hi}")
            elif spec.kind == "bool":
                if not isinstance(value, bool):
                    self.err(where, "bad_param", "true or false")
            elif spec.kind == "code":
                if _is_int(value):
                    self.err(where, "bad_param", "write the code in quotes (\"0815\"), so that leading zeros stay")
                elif not isinstance(value, str) or not m.CODE.match(value):
                    self.err(where, "bad_param", "1 to 8 digits")
            elif spec.kind == "destination":
                self.check_destination(value, where)

    def check_destination(self, d: Any, path: str) -> None:
        if not isinstance(d, dict):
            self.err(path, "bad_destination", "{ lat, lon, radius_m } or { points: [[lat, lon], ...] }")
            return
        if "points" in d:
            self.unknown_keys(d, ("points",), path)
            self.check_polygon(d["points"], f"{path}.points")
            return
        self.unknown_keys(d, ("lat", "lon", "radius_m"), path)
        for key, limit in (("lat", 90), ("lon", 180)):
            v = d.get(key)
            if not _is_number(v) or not -limit <= v <= limit:
                self.err(f"{path}.{key}", "bad_destination", f"degrees, -{limit} to {limit}")
        r = d.get("radius_m")
        if not _is_number(r) or not 0 < r <= 10_000:
            self.err(f"{path}.radius_m", "bad_destination", "a radius in metres, more than 0 and at most 10000")
        elif r < m.RADIUS_WARN_M:
            self.warn(f"{path}.radius_m", "small_radius", f"under {m.RADIUS_WARN_M} m: a phone's GPS is rarely "
                      "that precise, so the VIP may never be seen inside")

    def check_polygon(self, points: Any, path: str) -> None:
        if not isinstance(points, list) or not 3 <= len(points) <= m.POLYGON_MAX:
            self.err(path, "bad_polygon", f"a list of 3 to {m.POLYGON_MAX} [lat, lon] points")
            return
        good = []
        for j, p in enumerate(points):
            if (not isinstance(p, list) or len(p) != 2 or not _is_number(p[0]) or not _is_number(p[1])
                    or not -90 <= p[0] <= 90 or not -180 <= p[1] <= 180):
                self.err(f"{path}[{j}]", "bad_polygon", "[lat, lon] in degrees")
                return
            good.append((float(p[0]), float(p[1])))
        if not _simple(good):
            self.err(path, "polygon_not_simple", "the polygon's edges cross or touch, or it has no area: list "
                     "its corners in order around it")

    def check_visibility(self, o: dict[str, Any], path: str, team: Optional[str]) -> None:
        vis = o.get("visibility", m.default_visibility(o))
        assignee = o.get("assignee") if isinstance(o.get("assignee"), dict) else {}
        if vis not in m.VISIBILITY:
            self.err(f"{path}.visibility", "bad_visibility", f"one of {', '.join(m.VISIBILITY)}")
        elif vis == "team" and assignee.get("team") is None:
            self.err(f"{path}.visibility", "visibility_needs_team", "team: name the assignee's team")
        elif vis == "squad" and assignee.get("squad") is None:
            self.err(f"{path}.visibility", "visibility_needs_squad", "squad: name the assignee's squad")
        elif vis == "hidden" and not o.get("depends_on") and not (isinstance(o.get("id"), str)
                                                                  and o["id"] in self.revealed_by):
            self.err(f"{path}.visibility", "never_revealed", "a hidden objective is revealed when what it "
                     "depends_on is completed, or by another's effect.reveal: it has neither")

    def check_refs(self, refs: Any, path: str, oid: Any) -> None:
        if refs is None:
            return
        if not isinstance(refs, list):
            self.err(path, "bad_reference", "a list of objective ids")
            return
        seen = set()
        for j, ref in enumerate(refs):
            if ref == oid:
                self.err(f"{path}[{j}]", "self_reference", "an objective cannot name itself")
            elif not isinstance(ref, str) or ref not in self.ids:
                self.err(f"{path}[{j}]", "unknown_reference", f"{ref!r} is not an objective id")
            elif ref in seen:
                self.err(f"{path}[{j}]", "bad_reference", f"{ref!r} is named twice")
            seen.add(ref if isinstance(ref, str) else None)

    def check_window(self, o: dict[str, Any], path: str, otype: Optional[m.ObjectiveType]) -> None:
        w = o.get("time_window")
        where = f"{path}.time_window"
        if w is None:
            if otype is not None and otype.needs_end:
                self.err(where, "missing_end", f"{o.get('type')} is judged at its time window's end: "
                         "give time_window.end_min")
            return
        if not isinstance(w, dict):
            self.err(where, "bad_time_window", "a map: { start_min, end_min }")
            return
        self.unknown_keys(w, ("start_min", "end_min"), where)
        start, end = w.get("start_min", 0), w.get("end_min")
        if not _is_int(start) or not 0 <= start <= m.WINDOW_MAX_MIN:
            self.err(f"{where}.start_min", "bad_time_window", f"minutes from the game's start, 0 to {m.WINDOW_MAX_MIN}")
            return
        if end is None:
            if otype is not None and otype.needs_end:
                self.err(f"{where}.end_min", "missing_end", f"{o.get('type')} is judged at its time window's end")
            return
        if not _is_int(end) or not 0 < end <= m.WINDOW_MAX_MIN:
            self.err(f"{where}.end_min", "bad_time_window", f"minutes from the game's start, 1 to {m.WINDOW_MAX_MIN}")
        elif start >= end:
            self.err(where, "bad_time_window", "start_min must be before end_min")

    def check_effect(self, o: dict[str, Any], path: str, oid: Any) -> None:
        effect = o.get("effect")
        where = f"{path}.effect"
        if effect is None:
            return
        if not isinstance(effect, dict):
            self.err(where, "bad_effect", "a map: { points, win, reveal }")
            return
        self.unknown_keys(effect, ("points", "win", "reveal"), where)
        points = effect.get("points")
        if isinstance(points, dict):
            self.unknown_keys(points, ("param",), f"{where}.points")
            name = points.get("param")
            if not isinstance(name, str) or name not in self.params:
                self.err(f"{where}.points.param", "unknown_param", f"{name!r} is not one of the scenario's params")
        elif points is not None and (not _is_int(points) or not 0 <= points <= m.POINTS_MAX):
            self.err(f"{where}.points", "bad_points", f"whole points, 0 to {m.POINTS_MAX} (score.add takes "
                     "integers), or { param: name }")
        if not isinstance(effect.get("win", False), bool):
            self.err(f"{where}.win", "bad_bool", "true or false")
        self.check_refs(effect.get("reveal"), f"{where}.reveal", oid)

    def check_cycles(self, objectives: list[Any]) -> None:
        """The depends_on graph is a DAG (Kahn's topological sort); every objective on a cycle is named."""
        deps: dict[str, set[str]] = {}
        for o in objectives:
            if isinstance(o, dict) and isinstance(o.get("id"), str) and o["id"] in self.ids:
                refs = o.get("depends_on") if isinstance(o.get("depends_on"), list) else []
                deps.setdefault(o["id"], set()).update(r for r in refs if isinstance(r, str) and r in self.ids
                                                       and r != o["id"])
        left = {k: set(v) for k, v in deps.items()}
        ready = [k for k, v in left.items() if not v]
        while ready:
            done = ready.pop()
            del left[done]
            for k, v in left.items():
                if done in v:
                    v.discard(done)
                    if not v:
                        ready.append(k)
        # What is left is on a cycle or waits for one; name those on a cycle.
        for oid in sorted(left, key=lambda k: self.ids[k]):
            if _reaches(oid, oid, left):
                self.err(f"objectives[{self.ids[oid]}].depends_on", "cycle",
                         f"{oid!r} depends on itself through {' -> '.join(_cycle(oid, left))}")

    def check_sizes(self, o: dict[str, Any], path: str) -> None:
        """The setup command, as it is sent after a reboot (the longest), fits a box's CMD buffer."""
        longest = max(self.teams, key=lambda t: len(t.encode()), default="red")
        label = m.translated(o, self.m.get("lang", "pt") if self.m.get("lang") in m.LANGS else "pt") or ""
        setup = setup_command(o, self.m.get("lang", "pt"), label)
        # What the runtime adds after a reboot, by kind (runtime.lua, setup()).
        extra = {"capture": {"holder": longest}, "tags": {"have": 100} if "team" in setup else {},
                 "bomb": {"armed": longest, "left": 3600}, "code": {}}[setup["kind"]]
        setup = {"name": "setup", **setup, **extra}
        size = len(json.dumps(setup, separators=(",", ":"), ensure_ascii=False).encode())
        if size > CMD_PARAMS_MAX:
            self.err(f"{path}.name", "setup_too_large", f"the box's setup takes {size} bytes, more than the "
                     f"{CMD_PARAMS_MAX} of a command: shorten the name in the boxes' language")

    def check_events(self, oid: str, path: str) -> None:
        sid = self.m.get("id") if isinstance(self.m.get("id"), str) else ""
        events = [("scenario.objective.completed", {"objective": oid, "squad": "16"}),
                  ("scenario.objective.failed", {"objective": oid, "squad": "16", "reason": "captured"}),
                  ("scenario.objective.revealed", {"objective": oid, "squad": "16"}),
                  ("scenario.started", {"scenario": sid})]
        for type_, data in events:
            try:
                size = len(codec.encode_event({"node": 0, "seq": 0xFFFF, "t": 0xFFFFFFFF, "type": type_,
                                               "team": m.TEAMS_MAX, "prio": "critical", "data": data}))
            except codec.CodecError as exc:
                self.err(path, "event_too_large", f"{type_} cannot be sent: {exc}")
                return
            if size > RF_PAYLOAD_MAX:
                self.err(path, "event_too_large", f"{type_} takes {size} bytes, more than a LoRa payload's "
                         f"{RF_PAYLOAD_MAX}")


def _reaches(start: str, goal: str, graph: dict[str, set[str]]) -> bool:
    seen: set[str] = set()
    stack = list(graph.get(start, ()))
    while stack:
        n = stack.pop()
        if n == goal:
            return True
        if n not in seen and n in graph:
            seen.add(n)
            stack.extend(graph[n])
    return False


def _cycle(start: str, graph: dict[str, set[str]]) -> list[str]:
    """One cycle through start, for the message: start -> ... -> start."""
    path = [start]
    seen = {start}

    def walk(n: str) -> bool:
        for nxt in sorted(graph.get(n, ())):
            if nxt == start:
                path.append(start)
                return True
            if nxt not in seen and nxt in graph:
                seen.add(nxt)
                path.append(nxt)
                if walk(nxt):
                    return True
                path.pop()
        return False

    walk(start)
    return path


def _simple(points: list[tuple[float, float]]) -> bool:
    """A simple polygon: no two edges cross or touch (except neighbours at their shared corner), and an area."""
    n = len(points)
    area = sum(points[i][1] * points[(i + 1) % n][0] - points[(i + 1) % n][1] * points[i][0] for i in range(n))
    if abs(area) < 1e-12:
        return False
    if len(set(points)) != n:
        return False

    def orient(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> int:
        v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
        return 0 if abs(v) < 1e-15 else (1 if v > 0 else -1)

    def on_segment(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> bool:
        return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])

    def intersect(p1, p2, p3, p4) -> bool:  # noqa: ANN001
        d1, d2, d3, d4 = orient(p3, p4, p1), orient(p3, p4, p2), orient(p1, p2, p3), orient(p1, p2, p4)
        if d1 != d2 and d3 != d4:
            return True
        return ((d1 == 0 and on_segment(p3, p4, p1)) or (d2 == 0 and on_segment(p3, p4, p2))
                or (d3 == 0 and on_segment(p1, p2, p3)) or (d4 == 0 and on_segment(p1, p2, p4)))

    edges = [(points[i], points[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            if j == i + 1 or (i == 0 and j == n - 1):
                # Neighbours share a corner s; collinear, they must not fold back over each other.
                a, s, b = (edges[i][0], edges[i][1], edges[j][1]) if j == i + 1 else \
                    (edges[j][0], edges[i][0], edges[i][1])
                if orient(a, s, b) == 0 and (on_segment(a, s, b) or on_segment(s, b, a)):
                    return False
                continue
            if intersect(*edges[i], *edges[j]):
                return False
    return True


def validate(manifest: Any) -> list[Problem]:
    """Every problem in the manifest (a parsed map), errors and warnings, in the manifest's order."""
    if not isinstance(manifest, dict):
        return [Problem("", "bad_manifest", "a scenario manifest is a map (id, version, name, nodes, objectives)")]
    return _Checker(manifest).run()
