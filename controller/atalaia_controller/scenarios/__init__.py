# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario compiler and validator (ADR-P4-6 as amended, decisions P4-1, P4R7, P4R8, P4R9).

A scenario manifest (YAML) compiles to a ``kind: scenario`` package: ``mode.yaml`` and a
``field.lua`` that runs on the field controller over the built-in role package
``org.atalaia.objectives`` (``org.club.foxhound+org.atalaia.objectives``). The library is plain
Python (the standard library and PyYAML), shared by the controller and the site server, which
imports it (P4R16: no FastAPI, no pydantic).

    from atalaia_controller.scenarios import load, validate, compile_scenario, check_package

    manifest = load(text)            # ManifestError if the text is not a manifest at all
    problems = validate(manifest)    # [Problem(path, code, message, level)]
    package = compile_scenario(manifest)  # ScenarioError(problems) on any error
    check_package(core, package)     # the controller's own load check (modes.check_scripts)

The command line: ``python3 -m atalaia_controller.scenarios check|compile|validate``.
"""

from __future__ import annotations

from typing import Any

from .manifest import ManifestError, load_text
from .package import Package, build
from .validator import ERROR, WARNING, Problem, errors, validate

__all__ = ["ERROR", "WARNING", "ManifestError", "Package", "Problem", "ScenarioError", "check_package",
           "compile_scenario", "load", "validate"]


class ScenarioError(Exception):
    """The manifest has errors: ``problems`` lists them (and the warnings)."""

    def __init__(self, problems: list[Problem]) -> None:
        self.problems = problems
        super().__init__("; ".join(str(p) for p in errors(problems)))


def load(text: str) -> dict[str, Any]:
    """The manifest in a YAML (or JSON) text; ManifestError if it is not a map, or a key repeats."""
    return load_text(text)


def compile_scenario(manifest: dict[str, Any]) -> Package:
    """The scenario package of a manifest. ScenarioError when the manifest has an error."""
    problems = validate(manifest)
    if errors(problems):
        raise ScenarioError(problems)
    return build(manifest)


def check_package(core: Any, package: Package) -> None:
    """Loads the package's field.lua in the core, as the controller does on upload (P4R9).

    ModeError (atalaia_sim.mode) when the package or its script does not load.
    """
    from ..modes import check_scripts, parse_package  # noqa: PLC0415 (modes imports the store)

    check_scripts(core, parse_package(package.files))
