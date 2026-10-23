# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario compiler in the C core (decision PE24-109), from Python.

The validator and the compiler are one implementation, in Lua inside the core
(core/scenario/, atalaia/scenario.h), which the phone's controller calls too. Python only reads
the manifest's text (manifest.py) and hands what it read to the core as the manifest's data tree
(core/scenario/README.md): every value typed ({"str": ...}, {"int": "12"}, {"float": "1.5"},
{"timestamp": ...}, {"list": [...]}, {"map": [[k, v], ...]}), and an object that appears twice
(a YAML alias) as {"alias": n}, so the core sees exactly what PyYAML built.
"""

from __future__ import annotations

import datetime
import json
import threading
from typing import Any, Optional

# Deeper than the core reads (core/scenario/tree.lua, MAX_DEPTH = 100): the rest of a branch is not
# written, and the core says the manifest is nested too deep.
_DEPTH_WRITTEN = 102


class CoreUnavailable(RuntimeError):
    """The core library (with its scenario compiler) is not there."""


def encode(value: Any) -> bytes:
    """A manifest (any value PyYAML's safe loader builds, or one built in code) as the data tree's
    JSON, UTF-8 (a lone surrogate as its three bytes, which the core reports as bad_unicode)."""
    shared: dict[int, int] = {}
    keep: list[Any] = []  # every list and map stays alive, so no id() is reused while encoding

    def enc(v: Any, depth: int) -> Any:
        if v is None:
            return {"null": None}
        if v is True or v is False:
            return {"bool": v}
        if isinstance(v, int) and not isinstance(v, bool):
            try:
                return {"int": str(v)}
            except ValueError:  # past Python's int max str digits
                return {"other": {"repr": "<an int of more than 4300 digits>", "truthy": True}}
        if isinstance(v, float):
            return {"float": repr(v)}
        if isinstance(v, str):
            return {"str": v}
        if isinstance(v, (datetime.date, datetime.datetime)):
            return {"timestamp": str(v)}
        if isinstance(v, (list, tuple, dict)):
            n = shared.get(id(v))
            if n is not None:
                return {"alias": n}
            shared[id(v)] = len(shared)
            keep.append(v)
            if depth >= _DEPTH_WRITTEN:
                return {"list": []} if not isinstance(v, dict) else {"map": []}
            if isinstance(v, dict):
                return {"map": [[enc(k, depth + 1), enc(x, depth + 1)] for k, x in v.items()]}
            return {"list": [enc(x, depth + 1) for x in v]}
        # A set, bytes (!!set, !!binary) or anything else: only its repr and its truth matter.
        return {"other": {"repr": repr(v), "truthy": bool(v)}}

    text = json.dumps(enc(value, 0), ensure_ascii=False, separators=(",", ":"))
    return text.encode("utf-8", "surrogatepass")


_lock = threading.Lock()
_default: Optional[Any] = None


def default_core() -> Any:
    """The core library (ATALAIA_CORE_LIB, or a build folder of the repository), loaded once."""
    global _default
    with _lock:
        if _default is None:
            try:
                from atalaia_sim.core import Core, find_library  # noqa: PLC0415 (ctypes: only when needed)

                _default = Core(find_library())
            except (OSError, AttributeError) as exc:
                raise CoreUnavailable(f"the core library is needed to check scenarios: {exc}") from None
        return _default


def call(op: str, manifest: Any, core: Optional[Any] = None) -> dict[str, Any]:
    """The core's answer for a manifest: op is check, compile or literal (atalaia/scenario.h)."""
    core = core if core is not None else default_core()
    try:
        return core.scenario(op, encode(manifest))
    except AttributeError as exc:  # a core built without ATALAIA_SCENARIO, or the FFI stub
        raise CoreUnavailable(f"this core library has no scenario compiler: {exc}") from None
