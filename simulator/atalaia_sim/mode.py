# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mode packages: the manifest (mode.yaml), scripts and tests.

A package is a main mode (``kind: mode``, the default) or a modifier
(``kind: modifier``), which runs alongside a main mode on the same node.
A game names a main mode and its modifiers with one id, joined by ``+``
(``org.atalaia.domination+org.atalaia.codes``); :func:`compose` turns that
into one mode whose scripts are the parts' scripts in order, each in its
own ``do ... end`` block. The Field Box builds the same chunk from its
stored presets (firmware/esp32/main/box_game.c).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

KINDS = ("mode", "modifier")
# A game's mode id travels in the join payload (protocol/join.md): 63 bytes at most.
MODE_ID_MAX = 63
SEPARATOR = "+"


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
    field_script: Optional[str] = None
    kind: str = "mode"
    description: str = ""
    # Translated display strings: {lang: {name, description, params: {param: label}}}.
    i18n: dict[str, Any] = field(default_factory=dict)
    # For a composed mode: the ids of the main mode and its modifiers, in order.
    parts: tuple[str, ...] = ()

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
        if "max" in spec and len(value.encode()) > spec["max"]:
            raise ModeError(f"{where} must be at most {spec['max']} bytes")
    else:
        raise ModeError(f"{where} has unknown type {kind!r}")


def check_manifest(manifest: dict[str, Any], where: str) -> None:
    """The optional parts of a manifest: kind and i18n."""
    kind = manifest.get("kind", "mode")
    if kind not in KINDS:
        raise ModeError(f"{where}: kind must be one of {', '.join(KINDS)}, got {kind!r}")
    i18n = manifest.get("i18n")
    if i18n is None:
        return
    if not isinstance(i18n, dict):
        raise ModeError(f"{where}: i18n must map a language to its strings")
    for lang, strings in i18n.items():
        if not isinstance(lang, str) or not isinstance(strings, dict):
            raise ModeError(f"{where}: i18n.{lang} must be a map of strings")
        for key, value in strings.items():
            if key == "params":
                if not isinstance(value, dict) or not all(
                        isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                    raise ModeError(f"{where}: i18n.{lang}.params maps parameter names to labels")
            elif key in ("name", "description"):
                if not isinstance(value, str):
                    raise ModeError(f"{where}: i18n.{lang}.{key} must be text")
            else:
                raise ModeError(f"{where}: i18n.{lang} has an unknown key {key!r}")


def load_mode(path: Path) -> Mode:
    manifest_path = path / "mode.yaml"
    if not manifest_path.exists():
        raise ModeError(f"{path}: no mode.yaml")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    for key in ("id", "version", "roles"):
        if key not in manifest:
            raise ModeError(f"{manifest_path}: missing '{key}'")
    check_manifest(manifest, str(manifest_path))
    node_path = path / "node.lua"
    if not node_path.exists():
        raise ModeError(f"{path}: no node.lua")
    field_path = path / "field.lua"
    return Mode(
        path=path,
        id=manifest["id"],
        name=manifest.get("name", manifest["id"]),
        version=str(manifest["version"]),
        roles=manifest["roles"],
        params=manifest.get("params") or {},
        node_script=node_path.read_text(encoding="utf-8"),
        field_script=field_path.read_text(encoding="utf-8") if field_path.exists() else None,
        kind=manifest.get("kind", "mode"),
        description=str(manifest.get("description", "")),
        i18n=manifest.get("i18n") or {},
    )


def compose_scripts(scripts: list[str]) -> str:
    """One Lua chunk from a main mode's script and its modifiers' scripts, in that order.

    Each script keeps its own locals in a do ... end block; handlers for the
    same event run in load order. One script is returned unchanged.
    """
    if len(scripts) == 1:
        return scripts[0]
    return "".join(f"do\n{s}\nend\n" for s in scripts)


def split_id(mode_id: str) -> list[str]:
    return mode_id.split(SEPARATOR)


def compose(main: Mode, modifiers: list[Mode]) -> Mode:
    """A main mode with modifiers: one id, one parameter schema, one script per place."""
    if not modifiers:
        return main
    if main.kind != "mode":
        raise ModeError(f"{main.id} is a modifier; a game needs a main mode first")
    seen = {main.id}
    params = dict(main.params)
    for mod in modifiers:
        if mod.kind != "modifier":
            raise ModeError(f"{mod.id} is a main mode, not a modifier")
        if mod.id in seen:
            raise ModeError(f"{mod.id} is named twice")
        seen.add(mod.id)
        clash = set(params) & set(mod.params)
        if clash:
            raise ModeError(f"{mod.id} and {main.id} both have the parameter(s) {sorted(clash)}")
        params.update(mod.params)
    parts = [main, *modifiers]
    mode_id = SEPARATOR.join(m.id for m in parts)
    if len(mode_id.encode()) > MODE_ID_MAX:
        raise ModeError(f"{mode_id}: a mode with its modifiers is named in at most {MODE_ID_MAX} bytes")
    fields = [m.field_script for m in parts if m.field_script is not None]
    i18n: dict[str, Any] = {}
    for lang in sorted({lang for m in parts for lang in m.i18n}):
        names = [m.i18n.get(lang, {}).get("name", m.name) for m in parts]
        labels: dict[str, str] = {}
        for m in parts:
            labels.update(m.i18n.get(lang, {}).get("params", {}))
        entry: dict[str, Any] = {"name": " + ".join(names), "params": labels}
        if "description" in main.i18n.get(lang, {}):
            entry["description"] = main.i18n[lang]["description"]
        i18n[lang] = entry
    return Mode(
        path=main.path,
        id=mode_id,
        name=" + ".join(m.name for m in parts),
        version=main.version,
        roles=main.roles,
        params=params,
        node_script=compose_scripts([m.node_script for m in parts]),
        field_script=compose_scripts(fields) if fields else None,
        kind="mode",
        description=main.description,
        i18n=i18n,
        parts=tuple(m.id for m in parts),
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
