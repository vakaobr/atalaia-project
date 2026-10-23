# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The compiled scenario package (kind: scenario, decision P4R7): mode.yaml and field.lua, as the
core's compiler writes them (core/scenario/package.lua and luagen.lua, decision PE24-109).

mode.yaml carries what the controller and the app need to show the scenario without reading
its Lua: the names in English and Portuguese, the scenario's parameters, and under ``scenario``
the boxes' language, the teams, the squads, the nodes the GM assigns (P4R8) and every
objective's id, type, names, assignee, visibility, dependencies and points (for the per-team
routing and the player view of plan phase 8). Codes and destinations are only in field.lua,
which only staff read.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .validator import Problem, answer, errors

LICENSE = "GPL-3.0-or-later"  # the scenario runtime's (core/scenario/runtime.lua), so every package's


@dataclass
class Package:
    id: str
    version: str
    files: dict[str, str]  # mode.yaml and field.lua, as modes.parse_package takes them

    @property
    def mode_yaml(self) -> str:
        return self.files["mode.yaml"]

    @property
    def field_lua(self) -> str:
        return self.files["field.lua"]

    def write(self, folder: Path) -> list[Path]:
        """Writes the package's files into folder (made if needed); returns their paths."""
        folder.mkdir(parents=True, exist_ok=True)
        out = []
        for name, text in sorted(self.files.items()):
            path = folder / name
            path.write_text(text, encoding="utf-8")
            out.append(path)
        return out


def compile_package(manifest: Any, core: Optional[Any] = None) -> tuple[list[Problem], Optional[Package]]:
    """The manifest's problems and, without errors, its package: one call into the core."""
    out = answer("compile", manifest, core)
    problems = [Problem.from_dict(p) for p in out["problems"]]
    if errors(problems):
        return problems, None
    return problems, Package(out["id"], out["version"], dict(out["files"]))


def build(manifest: Any, core: Optional[Any] = None) -> Package:
    """The package of a manifest that validated without errors (ValueError if it has errors)."""
    problems, package = compile_package(manifest, core)
    if package is None:
        raise ValueError("; ".join(str(p) for p in errors(problems)))
    return package
