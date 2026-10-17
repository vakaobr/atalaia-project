# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mode packages: the manifest (mode.yaml), scripts and tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ModeError(Exception):
    pass


@dataclass
class Mode:
    path: Path
    id: str
    name: str
    version: str
    roles: dict[str, Any]
    params: dict[str, dict[str, Any]]
    node_script: str

    @property
    def tests(self) -> list[Path]:
        folder = self.path / "tests"
        return sorted(folder.glob("*.yaml")) if folder.is_dir() else []

    def resolve_params(self, overrides: dict[str, Any], teams: list[str]) -> dict[str, Any]:
        """Defaults from the manifest plus overrides, checked against the schema."""
        unknown = set(overrides) - set(self.params)
        if unknown:
            raise ModeError(f"{self.id}: unknown parameter(s) {sorted(unknown)}")
        values: dict[str, Any] = {}
        for name, spec in self.params.items():
            if name in overrides:
                value = overrides[name]
            elif "default" in spec:
                value = spec["default"]
            elif spec.get("optional"):
                continue
            else:
                raise ModeError(f"{self.id}: parameter '{name}' has no value")
            _check_param(self.id, name, spec, value, teams)
            values[name] = value
        return values


def _check_param(mode_id: str, name: str, spec: dict[str, Any], value: Any, teams: list[str]) -> None:
    kind = spec.get("type")
    where = f"{mode_id}: parameter '{name}'"
    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ModeError(f"{where} must be an integer, got {value!r}")
        if "min" in spec and value < spec["min"]:
            raise ModeError(f"{where} must be at least {spec['min']}")
        if "max" in spec and value > spec["max"]:
            raise ModeError(f"{where} must be at most {spec['max']}")
    elif kind == "bool":
        if not isinstance(value, bool):
            raise ModeError(f"{where} must be true or false, got {value!r}")
    elif kind == "team":
        if value not in teams:
            raise ModeError(f"{where} must be one of the game's teams {teams}, got {value!r}")
    elif kind == "string":
        if not isinstance(value, str):
            raise ModeError(f"{where} must be text, got {value!r}")
    else:
        raise ModeError(f"{where} has unknown type {kind!r}")


def load_mode(path: Path) -> Mode:
    manifest_path = path / "mode.yaml"
    if not manifest_path.exists():
        raise ModeError(f"{path}: no mode.yaml")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    for key in ("id", "version", "roles"):
        if key not in manifest:
            raise ModeError(f"{manifest_path}: missing '{key}'")
    node_path = path / "node.lua"
    if not node_path.exists():
        raise ModeError(f"{path}: no node.lua (field.lua arrives with the field controller)")
    return Mode(
        path=path,
        id=manifest["id"],
        name=manifest.get("name", manifest["id"]),
        version=str(manifest["version"]),
        roles=manifest["roles"],
        params=manifest.get("params") or {},
        node_script=node_path.read_text(encoding="utf-8"),
    )


def find_modes(paths: list[Path]) -> list[Path]:
    """Mode folders in the given paths: a mode folder itself or a folder of modes."""
    found = []
    for p in paths:
        if (p / "mode.yaml").exists():
            found.append(p)
        else:
            found.extend(sorted(m.parent for m in p.glob("*/mode.yaml")))
    return found
