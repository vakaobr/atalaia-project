# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lua generation for a scenario's field.lua.

The generated script is a data table, ``SCENARIO``, followed by the scenario runtime
(runtime.lua, the same text for every scenario): one block per objective type, the dependency
wiring, the reveals and the ``setup`` commands of the objectives package. Nothing the GM wrote is
ever pasted into Lua code: every value from the manifest reaches the script only through
:func:`lua_value`, which writes it as a Lua literal (a string in double quotes with every quote,
backslash and control character escaped; numbers that must be finite; keys that are names or
quoted strings). Comments in the generated script hold only names the validator restricted to
``[a-z0-9_.-]``.
"""

from __future__ import annotations

import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

from . import manifest as m

LICENSE = "GPL-3.0-or-later"  # the runtime's (runtime.lua), copied into every package
# The SPDX tag, split so that REUSE does not read this source line as a licence expression.
SPDX_TAG = "SPDX-" "License-Identifier:"

RUNTIME = Path(__file__).with_name("runtime.lua")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\Z")
_KEYWORDS = frozenset("and break do else elseif end false for function goto if in local nil not or repeat "
                      "return then true until while".split())
_SAFE_COMMENT = re.compile(r"^[a-z0-9_.+-]*\Z")
_SHORT = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
LUA_INT_MAX = 2**63 - 1


class LuaError(ValueError):
    pass


def lua_string(text: str) -> str:
    """A Lua string literal for any text: printable characters as they are (so names stay readable),
    quotes and backslashes escaped, and every control, format (bidi) or separator character, or
    anything else not printable, as decimal byte escapes of its UTF-8 (\\ddd)."""
    if not isinstance(text, str):
        raise LuaError(f"not a text: {text!r}")
    out = ['"']
    for ch in text:
        if ch in _SHORT:
            out.append(_SHORT[ch])
        elif " " <= ch <= "~":
            out.append(ch)
        elif ord(ch) > 0x7F and unicodedata.category(ch)[0] in "LMNPS" and unicodedata.category(ch) != "Co":
            out.append(ch)
        else:
            out.extend(f"\\{b:03d}" for b in ch.encode("utf-8", "surrogatepass"))
    out.append('"')
    return "".join(out)


def lua_value(value: Any, indent: int = 0) -> str:
    """A Lua literal for a manifest value: nil, booleans, finite numbers, texts, lists and maps."""
    pad = "  " * (indent + 1)
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        if not -LUA_INT_MAX <= value <= LUA_INT_MAX:
            raise LuaError(f"{value} does not fit a Lua integer")
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise LuaError(f"{value} is not a finite number")
        text = repr(value)
        return text if any(c in text for c in ".en") else text + ".0"
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, (list, tuple)):
        if not value:
            return "{}"
        items = [lua_value(v, indent + 1) for v in value]
        if all("\n" not in i for i in items) and sum(len(i) + 2 for i in items) < 80:
            return "{ " + ", ".join(items) + " }"
        return "{\n" + "".join(f"{pad}{i},\n" for i in items) + "  " * indent + "}"
    if isinstance(value, dict):
        entries = [(k, v) for k, v in value.items() if v is not None]
        if not entries:
            return "{}"
        lines = []
        for k, v in entries:
            if not isinstance(k, str):
                raise LuaError(f"a key must be text: {k!r}")
            key = k if _NAME.match(k) and k not in _KEYWORDS else f"[{lua_string(k)}]"
            lines.append(f"{key} = {lua_value(v, indent + 1)}")
        if all("\n" not in line for line in lines) and sum(len(line) + 2 for line in lines) < 80:
            return "{ " + ", ".join(lines) + " }"
        return "{\n" + "".join(f"{pad}{line},\n" for line in lines) + "  " * indent + "}"
    raise LuaError(f"cannot write {type(value).__name__} as Lua")


def comment(text: str) -> str:
    """A comment line: only for names the validator restricted (never a free text)."""
    if not _SAFE_COMMENT.match(text):
        raise LuaError(f"{text!r} cannot go in a comment")
    return f"-- {text}"


# -- the objectives package's setup (modes/objectives/node.lua) --

_KINDS = {"capture_and_hold": "capture", "defend": "capture", "enter_code": "code", "scan_tags": "tags",
          "destroy": "bomb"}


def setup_command(o: dict[str, Any], lang: str, label: str) -> dict[str, Any]:
    """What the box of an open objective is told (the mode command setup, without its name):
    only what the manifest gives, so the box's defaults apply to the rest."""
    kind = _KINDS[o["type"]]
    params = o.get("params") or {}
    team = (o.get("assignee") or {}).get("team")
    setup: dict[str, Any] = {"kind": kind, "label": label}
    if lang != "pt":
        setup["lang"] = lang
    if team is not None and o["type"] != "defend":  # anyone may take a point from its defenders
        setup["team"] = team
    if kind in ("capture", "bomb") and "hold_ms" in params:
        setup["hold_ms"] = params["hold_ms"]
    if kind == "bomb":
        for key in ("defuse_ms", "fuse_s"):
            if key in params:
                setup[key] = params[key]
    if kind == "code":
        setup["code"] = params["code"]
    if kind == "tags":
        setup["count"] = params["tag_count"]
        if params.get("any"):
            setup["any"] = True
    return setup


def _zone(destination: dict[str, Any]) -> dict[str, Any]:
    if "points" in destination:
        return {"type": "polygon", "points": [[float(p[0]), float(p[1])] for p in destination["points"]]}
    return {"type": "circle", "lat": float(destination["lat"]), "lon": float(destination["lon"]),
            "radius_m": float(destination["radius_m"])}


def objective_data(o: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """One objective as the runtime reads it (runtime.lua, "The data")."""
    lang = manifest.get("lang", "pt")
    nodes = manifest.get("nodes") or {}
    params = o.get("params") or {}
    assignee = o.get("assignee") or {}
    effect = o.get("effect") or {}
    window = o.get("time_window") or {}
    points = effect.get("points")
    squad = assignee.get("squad")
    data: dict[str, Any] = {
        "id": o["id"],
        "type": o["type"],
        "team": assignee.get("team"),
        "squad": str(squad) if squad is not None else None,  # the events' squad is text (data key 2)
        "hidden": o.get("visibility", m.default_visibility(o)) == "hidden",
        "depends_on": list(o.get("depends_on") or []),
        "reveals": list(effect.get("reveal") or []),
        "start_s": int(window.get("start_min", 0)) * 60,
        "end_s": int(window["end_min"]) * 60 if window.get("end_min") is not None else None,
        "points": points if isinstance(points, int) else None,
        "points_param": points.get("param") if isinstance(points, dict) else None,
        "win": bool(effect.get("win", False)),
    }
    target = o.get("target")
    if o["type"] in _KINDS:
        data["node"] = target
        data["setup"] = setup_command(o, lang, m.translated(o, lang) or o["id"])
    if o["type"] in ("capture_and_hold", "defend"):
        data["duration_s"] = int(params.get("duration_s", 0))
    if o["type"] == "escort":
        zone = _zone(params["destination"])
        data["role"] = (nodes.get(target) or {}).get("role", "vip")
        data["zone"] = zone
        data["max_acc_m"] = params.get("max_acc_m", zone.get("radius_m", 25.0))
    if o["type"] == "survive":
        data["minimum_lives"] = params["minimum_lives"]
    return data


def field_lua(manifest: dict[str, Any], runtime: Optional[str] = None) -> str:
    """The scenario's field.lua: a header, the data table and the runtime."""
    sid = manifest["id"]
    data = {
        "id": sid,
        "teams": list(manifest.get("teams", ["red", "blue"])),
        "objectives": [objective_data(o, manifest) for o in manifest["objectives"]],
    }
    lines = [
        f"-- {SPDX_TAG} {LICENSE}",
        "--",
        "-- Generated by the Atalaia scenario compiler (controller/atalaia_controller/scenarios)",
        "-- from the scenario manifest of:",
        comment(sid),
        "-- Edit the manifest and compile it again rather than this file. The objectives and",
        "-- their texts are in the table below; the code after it is the same for every scenario.",
        "",
        f"local SCENARIO = {lua_value(data)}",
        "",
    ]
    text = runtime if runtime is not None else RUNTIME.read_text(encoding="utf-8")
    body = text.split("-- @runtime\n", 1)[1]  # the runtime's own header stays in the repository
    return "\n".join(lines) + body
