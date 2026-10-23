# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario compiler and validator (ADR-P4-6 as amended, decisions P4-1, P4R7, P4R8, P4R9,
PE24-109).

A scenario manifest (YAML) compiles to a ``kind: scenario`` package: ``mode.yaml`` and a
``field.lua`` that runs on the field controller over the built-in role package
``org.atalaia.objectives`` (``org.club.foxhound+org.atalaia.objectives``). Python reads the
manifest (PyYAML, manifest.py); the rules, the Lua writer and mode.yaml are the C core's, one
implementation in Lua (core/scenario/) that the phone's controller calls too, so this package
needs the core library (``ATALAIA_CORE_LIB`` or a build folder; CoreUnavailable without it).
The site server imports it as well (P4R16: no FastAPI, no pydantic).

    manifest = load(text)            # ManifestError if the text is not a manifest at all
    problems = validate(manifest)    # [Problem(path, code, message, level)]
    package = compile_scenario(manifest)  # ScenarioError(problems) on any error
    check_package(core, package)     # the controller's own load check (modes.check_scripts)

Every function that needs the core takes ``core=`` (an atalaia_sim.core.Core), else loads the
default one once. The command line: ``python3 -m atalaia_controller.scenarios check|compile|validate``.
"""

from __future__ import annotations

from typing import Any, Optional

from .compiler import CoreUnavailable, call
from .manifest import ManifestError, load_text
from .package import Package, compile_package
from .validator import ERROR, WARNING, CompilerFailed, Problem, errors, validate

__all__ = ["ERROR", "WARNING", "CompilerFailed", "CoreUnavailable", "LuaError", "ManifestError", "Package",
           "Problem", "ScenarioError", "check_package", "compile_scenario", "load", "lua_literal", "validate"]


class ScenarioError(Exception):
    """The manifest has errors: ``problems`` lists them (and the warnings)."""

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        super().__init__("; ".join(str(p) for p in errors(problems)))


class LuaError(ValueError):
    """A value Lua cannot hold (lua_literal)."""


def load(text: str) -> dict[str, Any]:
    """The manifest in a YAML (or JSON) text; ManifestError if it is not a map, or a key repeats."""
    return load_text(text)


def compile_scenario(manifest: Any, core: Optional[Any] = None) -> Package:
    """The scenario package of a manifest. ScenarioError when the manifest has an error."""
    problems, package = compile_package(manifest, core)
    if package is None:
        raise ScenarioError(problems)
    return package


def lua_literal(value: Any, core: Optional[Any] = None) -> str:
    """A value as the compiler writes it in field.lua: a Lua literal (LuaError if Lua cannot hold it)."""
    out = call("literal", value, core)
    if "error" in out and "ok" not in out:
        raise CompilerFailed(out["error"])
    if not out["ok"]:
        raise LuaError(out["error"])
    return out["lua"]


def check_package(core: Any, package: Package) -> None:
    """Loads the package's field.lua in the core, as the controller does on upload (P4R9).

    ModeError (atalaia_sim.mode) when the package or its script does not load.
    """
    from ..modes import check_scripts, parse_package  # noqa: PLC0415 (modes imports the store)

    check_scripts(core, parse_package(package.files))
