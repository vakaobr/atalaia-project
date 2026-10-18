# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""A mode's screen templates (assets/screens/*.yaml, ADR-P3-4): the checks CI runs.

Each file is parsed by the core's own parser (core/src/screen_template.c,
through ctypes), the one the Field Box renders with, so a template the
simulator accepts is one every box accepts. On top of that the file's name
must be its `template:` name, which is how ui.screen() finds it.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .core import Core

SOURCE_MAX = 4096  # ATALAIA_TPL_SOURCE_MAX


def screen_files(mode_dir: Path) -> list[Path]:
    folder = mode_dir / "assets" / "screens"
    return sorted(folder.glob("*.yaml")) if folder.is_dir() else []


def check_screen(core: Core, path: Path) -> list[str]:
    """Problems with one template file (empty when it is fine)."""
    source = path.read_bytes()
    if len(source) > SOURCE_MAX:
        return [f"{path.name}: larger than {SOURCE_MAX} bytes"]
    try:
        source.decode("utf-8")
    except UnicodeDecodeError:
        return [f"{path.name}: not UTF-8"]
    why = core.check_screen(source)
    if why is not None:
        return [f"{path.name}: {why}"]
    name = (yaml.safe_load(source) or {}).get("template")
    if name != path.stem:
        return [f"{path.name}: its template: name is {name!r}; it must be {path.stem!r}"]
    return []


def check_screens(core: Core, mode_dir: Path) -> list[str]:
    problems: list[str] = []
    for path in screen_files(mode_dir):
        problems += check_screen(core, path)
    return problems
