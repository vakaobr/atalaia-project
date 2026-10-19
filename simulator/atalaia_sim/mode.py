# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Mode packages: the manifest (mode.yaml), scripts and tests.

A package is a main mode (``kind: mode``, the default), a modifier
(``kind: modifier``), which runs alongside a main mode on the same node, or
a role package (``kind: role``), which brings roles of its own to any game:
a node given one of its roles runs that package alone (a Medic Kit next to
Domination's zone boxes runs no capture rules). A game names a main mode
and its other parts with one id, joined by ``+``
(``org.atalaia.domination+org.atalaia.codes+org.atalaia.medic``);
:func:`compose` turns that into one mode: the main mode's roles run the
main mode's and the modifiers' scripts in order, each in its own
``do ... end`` block, and each role package's roles run its script alone.
A node's join names only what it runs (:meth:`Mode.node_mode_id`), so the
Field Box builds the same chunk from its stored presets
(firmware/esp32/main/box_game.c) without knowing the kinds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

KINDS = ("mode", "modifier", "role")
# A game's mode id travels in the join payload (protocol/join.md): 63 bytes at most.
MODE_ID_MAX = 63
SEPARATOR = "+"
# A mode command (CMD opcode 8, RFC 0001 Amendment 5): the GM's or a field script's
# word for a node's script, which gets it as cmd.mode with the command's name in its data.
COMMAND_NAME = re.compile(r"^[a-z][a-z0-9_]{0,23}$")


class ModeError(Exception):
    pass


@dataclass(frozen=True)
class RolePart:
    """A role package inside a composed game: the nodes with one of its roles run it alone."""

    id: str
    node_script: str
    chunk_name: str
    param_names: tuple[str, ...]


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
    # Translated display strings: {lang: {name, description, params: {param: label},
    # commands: {command: label}}}.
    i18n: dict[str, Any] = field(default_factory=dict)
    # For a composed mode: the ids of the main mode and its other parts, in order.
    parts: tuple[str, ...] = ()
    # Commands the GM console offers for the nodes of some roles (manifest `commands`):
    # {name: {"roles": [...], "label": ...}}. They reach the node's script as cmd.mode.
    commands: dict[str, dict[str, Any]] = field(default_factory=dict)
    # For a composed mode: role -> the role package its nodes run instead of node_script.
    role_parts: dict[str, RolePart] = field(default_factory=dict)
    # For a composed mode: the id of what the main mode's roles run (main mode and modifiers).
    main_id: str = ""

    @property
    def tests(self) -> list[Path]:
        folder = self.path / "tests"
        return sorted(folder.glob("*.yaml")) if folder.is_dir() else []

    def node_script_for(self, role: str) -> str:
        """The script a node with this role runs."""
        part = self.role_parts.get(role)
        return part.node_script if part else self.node_script

    def chunk_name_for(self, role: str) -> str:
        part = self.role_parts.get(role)
        return part.chunk_name if part else f"@{self.path.name}/node.lua"

    def node_mode_id(self, role: str) -> str:
        """The mode id a node with this role is given in its join: what it runs."""
        part = self.role_parts.get(role)
        return part.id if part else (self.main_id or self.id)

    def params_for(self, role: str, params: dict[str, Any]) -> dict[str, Any]:
        """The game's parameters that a node with this role runs with (its join's)."""
        if not self.role_parts:
            return dict(params)
        part = self.role_parts.get(role)
        if part is not None:
            return {k: v for k, v in params.items() if k in part.param_names}
        others = {n for p in self.role_parts.values() for n in p.param_names}
        return {k: v for k, v in params.items() if k not in others}

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
    """The optional parts of a manifest: kind, commands and i18n."""
    kind = manifest.get("kind", "mode")
    if kind not in KINDS:
        raise ModeError(f"{where}: kind must be one of {', '.join(KINDS)}, got {kind!r}")
    commands = manifest.get("commands")
    if commands is not None:
        if not isinstance(commands, dict):
            raise ModeError(f"{where}: commands must map a command name to its roles and label")
        roles = manifest.get("roles") or {}
        for name, spec in commands.items():
            if not isinstance(name, str) or not COMMAND_NAME.match(name):
                raise ModeError(f"{where}: command {name!r}: 1-24 of a-z, 0-9 and _, "
                                "starting with a letter")
            if (not isinstance(spec, dict) or set(spec) - {"roles", "label"}
                    or not isinstance(spec.get("label"), str)
                    or not isinstance(spec.get("roles"), list) or not spec["roles"]
                    or not all(isinstance(r, str) and r in roles for r in spec["roles"])):
                raise ModeError(f"{where}: command {name!r} needs a label and a list of the "
                                "mode's roles")
    i18n = manifest.get("i18n")
    if i18n is None:
        return
    if not isinstance(i18n, dict):
        raise ModeError(f"{where}: i18n must map a language to its strings")
    for lang, strings in i18n.items():
        if not isinstance(lang, str) or not isinstance(strings, dict):
            raise ModeError(f"{where}: i18n.{lang} must be a map of strings")
        for key, value in strings.items():
            if key in ("params", "commands"):
                if not isinstance(value, dict) or not all(
                        isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                    what = "parameter" if key == "params" else "command"
                    raise ModeError(f"{where}: i18n.{lang}.{key} maps {what} names to labels")
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
        commands=manifest.get("commands") or {},
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
    """A main mode with modifiers and role packages: one id, one parameter schema.

    The main mode's roles run the main mode's and the modifiers' node scripts
    in one chunk; each role package's roles run that package alone. The field
    scripts of every part run together on the controller, in the id's order.
    Parameter, role and command names must differ between the parts.
    """
    if not modifiers:
        return main
    if main.kind != "mode":
        raise ModeError(f"{main.id} is a {main.kind}; a game needs a main mode first")
    seen = {main.id}
    params = dict(main.params)
    roles = dict(main.roles)
    commands = dict(main.commands)
    mods: list[Mode] = []
    role_parts: dict[str, RolePart] = {}
    for mod in modifiers:
        if mod.kind == "mode":
            raise ModeError(f"{mod.id} is a main mode, not a modifier")
        if mod.id in seen:
            raise ModeError(f"{mod.id} is named twice")
        seen.add(mod.id)
        clash = set(params) & set(mod.params)
        if clash:
            raise ModeError(f"{mod.id} and {main.id} both have the parameter(s) {sorted(clash)}")
        params.update(mod.params)
        clash = set(commands) & set(mod.commands)
        if clash:
            raise ModeError(f"{mod.id} and {main.id} both have the command(s) {sorted(clash)}")
        commands.update(mod.commands)
        if mod.kind == "modifier":
            mods.append(mod)
            continue
        clash = set(roles) & set(mod.roles)
        if clash:
            raise ModeError(f"{mod.id} and {main.id} both have the role(s) {sorted(clash)}")
        roles.update(mod.roles)
        part = RolePart(mod.id, mod.node_script, f"@{mod.path.name}/node.lua", tuple(mod.params))
        for role in mod.roles:
            role_parts[role] = part
    parts = [main, *modifiers]
    mode_id = SEPARATOR.join(m.id for m in parts)
    if len(mode_id.encode()) > MODE_ID_MAX:
        raise ModeError(f"{mode_id}: a mode with its modifiers is named in at most {MODE_ID_MAX} bytes")
    fields = [m.field_script for m in parts if m.field_script is not None]
    i18n: dict[str, Any] = {}
    for lang in sorted({lang for m in parts for lang in m.i18n}):
        names = [m.i18n.get(lang, {}).get("name", m.name) for m in parts]
        labels: dict[str, str] = {}
        command_labels: dict[str, str] = {}
        for m in parts:
            labels.update(m.i18n.get(lang, {}).get("params", {}))
            command_labels.update(m.i18n.get(lang, {}).get("commands", {}))
        entry: dict[str, Any] = {"name": " + ".join(names), "params": labels}
        if command_labels:
            entry["commands"] = command_labels
        if "description" in main.i18n.get(lang, {}):
            entry["description"] = main.i18n[lang]["description"]
        i18n[lang] = entry
    return Mode(
        path=main.path,
        id=mode_id,
        name=" + ".join(m.name for m in parts),
        version=main.version,
        roles=roles,
        params=params,
        node_script=compose_scripts([m.node_script for m in [main, *mods]]),
        field_script=compose_scripts(fields) if fields else None,
        kind="mode",
        description=main.description,
        i18n=i18n,
        parts=tuple(m.id for m in parts),
        commands=commands,
        role_parts=role_parts,
        main_id=SEPARATOR.join(m.id for m in [main, *mods]),
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
