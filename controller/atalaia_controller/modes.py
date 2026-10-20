# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Installed mode packages: the built-in ones from modes/, plus uploads kept in SQLite.

A package is a set of text files: mode.yaml, node.lua and optionally
field.lua (the script the controller itself runs, ADR-P2-14), plus assets
under assets/. An upload is checked before it is stored: the manifest must
parse and name its id, version and roles, and the scripts must load in the
real core (ctypes), so a typo is caught at upload and not on the field.

A package is a main mode, a modifier (``kind: modifier``), a role
package (``kind: role``, the Medic Kit, the objectives package) or a
scenario (``kind: scenario``, decision P4R7: a field.lua and no node.lua,
uploaded only, never built in). A game or a preset names a main mode and
its other parts with one id joined by ``+``
(``org.atalaia.domination+org.atalaia.codes+org.atalaia.medic``), a
scenario first (``org.club.foxhound+org.atalaia.objectives``); ``get``
composes them (atalaia_sim.mode.compose). A box's join names only what that
box runs (Mode.node_mode_id), never a scenario, which the Field Box
composes from its stored presets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import yaml
from atalaia_sim.core import Core, FieldOps, Node
from atalaia_sim.mode import SEPARATOR, Mode, ModeError, check_files, check_manifest, compose

from .store import Store

MAX_PACKAGE_BYTES = 1_000_000  # decision P5-6
_FILE_NAME = re.compile(r"^(mode\.yaml|node\.lua|field\.lua|assets/[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*)$")
_MODE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*(\.[a-z0-9][a-z0-9_-]*)+$")


@dataclass
class ModePackage:
    mode: Mode
    files: dict[str, str]
    builtin: bool

    @property
    def id(self) -> str:
        return self.mode.id

    @property
    def field_script(self) -> Optional[str]:
        return self.mode.field_script

    @property
    def kind(self) -> str:
        return self.mode.kind

    def to_api(self) -> dict[str, Any]:
        manifest = yaml.safe_load(self.files["mode.yaml"]) or {}
        return {
            "id": self.mode.id,
            "kind": self.mode.kind,
            "name": self.mode.name,
            "version": self.mode.version,
            "description": self.mode.description,
            "min_tier": manifest.get("min_tier"),
            "roles": self.mode.roles,
            "params": self.mode.params,
            "commands": self.mode.commands,
            "i18n": self.mode.i18n,
            "parts": list(self.mode.parts),
            "field_script": self.field_script is not None,
            "builtin": self.builtin,
            "files": sorted(self.files),
        }


def parse_package(files: dict[str, str], path: Path = Path("<upload>")) -> ModePackage:
    if not isinstance(files, dict) or not files:
        raise ModeError("a mode package is a map of file names to their text")
    total = 0
    for name, text in files.items():
        if not isinstance(name, str) or not _FILE_NAME.match(name) or ".." in name:
            raise ModeError(f"file {name!r} is not allowed in a mode package")
        if not isinstance(text, str):
            raise ModeError(f"{name}: files are text")
        total += len(name) + len(text.encode("utf-8"))
    if total > MAX_PACKAGE_BYTES:
        raise ModeError(f"the package is {total} bytes; at most {MAX_PACKAGE_BYTES}")
    if "mode.yaml" not in files:
        raise ModeError("the package has no mode.yaml")
    try:
        manifest = yaml.safe_load(files["mode.yaml"]) or {}
    except yaml.YAMLError as exc:
        raise ModeError(f"mode.yaml: {exc}") from None
    if not isinstance(manifest, dict):
        raise ModeError("mode.yaml must be a map")
    kind = manifest.get("kind", "mode")
    if kind != "scenario" and "node.lua" not in files:
        raise ModeError("the package has no node.lua")
    for key in ("id", "version") if kind == "scenario" else ("id", "version", "roles"):
        if key not in manifest:
            raise ModeError(f"mode.yaml: missing '{key}'")
    if not isinstance(manifest["id"], str) or not _MODE_ID.match(manifest["id"]):
        raise ModeError("mode.yaml: id must look like org.club.name")
    if kind != "scenario" and (not isinstance(manifest["roles"], dict) or not manifest["roles"]):
        raise ModeError("mode.yaml: roles must be a non-empty map")
    params = manifest.get("params") or {}
    if not isinstance(params, dict):
        raise ModeError("mode.yaml: params must be a map")
    check_manifest(manifest, "mode.yaml")
    check_files(kind, "node.lua" in files, "field.lua" in files, "the package")
    mode = Mode(path=path, id=manifest["id"], name=str(manifest.get("name", manifest["id"])),
                version=str(manifest["version"]), roles=manifest.get("roles") or {}, params=params,
                node_script=files.get("node.lua", ""), field_script=files.get("field.lua"),
                kind=manifest.get("kind", "mode"), description=str(manifest.get("description", "")),
                i18n=manifest.get("i18n") or {}, commands=manifest.get("commands") or {})
    return ModePackage(mode, dict(files), builtin=False)


def resolve_params(mode: Mode, overrides: dict[str, Any], teams: Optional[list[str]]) -> dict[str, Any]:
    """Defaults plus overrides, checked against the schema. Without teams, team parameters
    are only checked to be text (a preset is not tied to team names)."""
    if not isinstance(overrides, dict):
        raise ModeError("params must be a map")
    if teams is None:
        teams = [v for k, v in overrides.items()
                 if mode.params.get(k, {}).get("type") == "team" and isinstance(v, str)]
        teams += [s.get("default") for s in mode.params.values()
                  if s.get("type") == "team" and isinstance(s.get("default"), str)]
    return mode.resolve_params(overrides, teams)


def check_scripts(core: Core, pkg: ModePackage) -> None:
    """Loads node.lua (a scenario has none) and field.lua in the core with the default
    parameters."""
    teams = ["red", "blue"]
    try:
        params = resolve_params(pkg.mode, {}, teams)
    except ModeError:
        params = {}  # parameters without defaults: load with none
    if pkg.kind != "scenario":
        node = Node(core, 1, 1, teams, params, pkg.mode.node_script, f"{pkg.id}/node.lua")
        try:
            if not node.loaded:
                raise ModeError(f"node.lua does not load: {node.last_error}")
        finally:
            node.close()
    if pkg.field_script is not None:
        ops = FieldOps(nodes=lambda role: [], owner=lambda node_id: None,
                       send=lambda node_id, cmd, params: False)
        field = Node(core, 0, 1, teams, params, pkg.field_script, f"{pkg.id}/field.lua", field_ops=ops)
        try:
            if not field.loaded:
                raise ModeError(f"field.lua does not load: {field.last_error}")
        finally:
            field.close()


class ModeRegistry:
    def __init__(self, store: Store, dirs: list[str], core: Optional[Core]) -> None:
        self.store = store
        self.core = core
        self._builtin: dict[str, ModePackage] = {}
        for folder in dirs:
            path = Path(folder)
            candidates = [path] if (path / "mode.yaml").exists() else sorted(
                p.parent for p in path.glob("*/mode.yaml"))
            for mode_dir in candidates:
                files = {name: (mode_dir / name).read_text(encoding="utf-8")
                         for name in ("mode.yaml", "node.lua", "field.lua") if (mode_dir / name).exists()}
                pkg = parse_package(files, mode_dir)
                if pkg.kind == "scenario":
                    # Per game, uploaded: a scenario is never built in (decision P4R7).
                    raise ModeError(f"{mode_dir}: a scenario is uploaded, not built in")
                pkg.builtin = True
                self._builtin[pkg.id] = pkg

    def all(self) -> list[ModePackage]:
        mods = dict(self._builtin)
        for row in self.store.modes():
            if row["id"] not in self._builtin:
                mods[row["id"]] = parse_package(row["files"])
        return [mods[k] for k in sorted(mods)]

    def get(self, mode_id: str) -> Optional[ModePackage]:
        """A package, or a main mode with its modifiers ("main+modifier"), composed.

        None when a part is not installed; ModeError when the parts do not go together.
        """
        if not isinstance(mode_id, str):
            return None
        names = mode_id.split(SEPARATOR)
        found = {m.id: m for m in self.all() if m.id in names}
        if len(names) == 1:
            pkg = found.get(mode_id)
            if pkg is not None and pkg.kind == "scenario":
                compose(pkg.mode, [])  # a scenario alone is no game: ModeError says why
            return pkg
        if any(name not in found for name in names):
            return None
        parts = [found[name] for name in names]
        mode = compose(parts[0].mode, [p.mode for p in parts[1:]])
        # The leading part's manifest stands for the game (min_tier); the scripts are composed.
        files = {"mode.yaml": parts[0].files["mode.yaml"], "node.lua": mode.node_script}
        if mode.field_script is not None:
            files["field.lua"] = mode.field_script
        return ModePackage(mode, files, builtin=all(p.builtin for p in parts))

    def install(self, files: dict[str, str]) -> ModePackage:
        pkg = parse_package(files)
        if pkg.id in self._builtin:
            raise ModeError(f"{pkg.id} is a built-in mode; give your version another id")
        if self.core is None:
            raise ModeError("the core library is not loaded, so scripts cannot be checked")
        check_scripts(self.core, pkg)
        self.store.save_mode(pkg.id, pkg.mode.version, pkg.files)
        return pkg
