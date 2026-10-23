# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""A scenario manifest's problems (ADR-P4-6's rules, as amended), from the core's validator.

The rules are written once, in core/scenario/validator.lua (decision PE24-109), for the Pi and the
phone. ``validate(manifest)`` returns every problem it finds, each with the path of the value
(``objectives[2].params.code``), a short code that programs match (protocol/vectors/scenario.json)
and a sentence for the GM. Errors stop the compiler; warnings do not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from .compiler import call

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

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Problem":
        return cls(d["path"], d["code"], d["message"], d["level"])


class CompilerFailed(RuntimeError):
    """The core could not read the data tree (a bug here, never the manifest's fault)."""


def errors(problems: list[Problem]) -> list[Problem]:
    return [p for p in problems if p.level == ERROR]


def answer(op: str, manifest: Any, core: Optional[Any] = None) -> dict[str, Any]:
    out = call(op, manifest, core)
    if "error" in out:
        raise CompilerFailed(out["error"])
    return out


def validate(manifest: Any, core: Optional[Any] = None) -> list[Problem]:
    """Every problem in the manifest (a parsed map), errors and warnings, in the manifest's order.
    ``core``: the loaded core library (atalaia_sim.core.Core), else the default one;
    CoreUnavailable without one."""
    return [Problem.from_dict(p) for p in answer("check", manifest, core)["problems"]]
