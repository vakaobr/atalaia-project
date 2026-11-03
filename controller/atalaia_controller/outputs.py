# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Boxes' modules and outputs on the controller (draft RFC "The expansion port", increment 3).

- **Modules** (EXP-21, EXP-36): the last ``node.modules`` of each box, parsed by the simulator's
  reference (``atalaia_sim.expansion.parse_modules``) into ``[{address, model, fw, caps,
  feedback}]``; ``GET /api/v1/nodes`` gives it as each node's ``modules`` (null until the box says;
  a box from before the RFC never does). A simple output is ``{"address": "g46", "model": "servo",
  "fw": null, "caps": ["siren"], "feedback": false}``. ``node.module_lost`` marks the module it
  names ``"lost": true`` until the box's next ``node.modules``.
- **The capability start check** (EXP-21, Q11): a joined node's role ``requires:`` a capability it
  lacks: missing (Start refuses unless forced); an ``optional:`` one: a warning. Role names that
  are not types (``team_input``, ``team_display``) are met by the types
  ``protocol/schema/capabilities.yaml`` lists under ``role_names``; a name neither a type nor
  there is never checked. Only nodes whose HELLO lists a capability type this controller knows are
  checked (a box from before the RFC, a phone: never). An enabled simple output counts as present,
  and the check names each one as "not checked", so the GM looks.
- **CMD 12** (EXP-23, EXP-27, EXP-30): the params a GM's request or a field script's
  ``field.send(node, "output", {...})`` become, checked as the box checks them
  (``atalaia_sim.expansion.output_params_problem``), with ``src`` set here (``gm`` or ``field``,
  never the caller's), and the controller's rate limit: at most one CMD 12 to a node every 2 s,
  an ``off`` never held back.

The Android controller does the same (``app/lib/controller/controller_outputs.dart``); the shared
contract cases are in ``protocol/vectors/controller_api.json``.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from atalaia_sim.expansion import output_params_problem, parse_modules
from atalaia_sim.protocol import CAPABILITY_ROLE_NAMES, CAPABILITY_TYPES

OUTPUT_GAP_MS = 2_000         # CMD 12 to one node at most this often (EXP-30); off is never held back
GM_DEFAULT_MS = 5_000         # a GM's on or pulse without ms (EXP-27: "default 5 s")
OUTPUT_TYPE = CAPABILITY_TYPES["output"].id
_IDS = {v.id: k for k, v in CAPABILITY_TYPES.items()}


def modules_of(text: Any) -> Optional[list[dict[str, Any]]]:
    """node.modules' text as the node list's ``modules``; None if it is not well formed."""
    if not isinstance(text, str):
        return None
    try:
        return parse_modules(text)
    except ValueError:
        return None


def mark_lost(modules: Optional[list[dict[str, Any]]], text: Any) -> Optional[list[dict[str, Any]]]:
    """``modules`` with the module(s) a node.module_lost names marked ``lost``; None when nothing changed."""
    gone = modules_of(text)
    if not modules or not gone:
        return None
    addresses = {m["address"] for m in gone}
    if not any(m["address"] in addresses for m in modules):
        return None
    return [{**m, "lost": True} if m["address"] in addresses else m for m in modules]


def types_of(capabilities: Any) -> set[str]:
    """The capability types a HELLO lists, by name; ids this controller does not know are left out."""
    if not isinstance(capabilities, list):
        return set()
    return {_IDS[c] for c in capabilities if isinstance(c, int) and not isinstance(c, bool) and c in _IDS}


def has(types: set[str], name: str) -> Optional[bool]:
    """Whether a node with these types has the role's capability ``name``; None when the name is
    neither a type nor a role name (never checked)."""
    if name in CAPABILITY_TYPES:
        return name in types
    met_by = CAPABILITY_ROLE_NAMES.get(name)
    if met_by is None:
        return None
    return any(t in types for t in met_by)


def simple_outputs(modules: Optional[list[dict[str, Any]]]) -> list[str]:
    """The functions of a node's simple outputs (no feedback: the box cannot tell what is plugged in)."""
    return [c for m in modules or [] if m.get("feedback") is False for c in m.get("caps", [])]


def output_caps(modules: Optional[list[dict[str, Any]]]) -> set[str]:
    """Every capability a node's modules list (its outputs' functions, a target's hit)."""
    return {c for m in modules or [] if not m.get("lost") for c in m.get("caps", [])}


def check_nodes(nodes: Iterable[dict[str, Any]], role_spec: Any) -> dict[str, list[dict[str, Any]]]:
    """The capability part of the start check for the joined nodes, each ``{node, name, role,
    capabilities (HELLO), modules}``; ``role_spec(role)`` gives the role's manifest entry (or None).

    ``missing_caps``: ``{node, name, role, capability}`` for each required one a node lacks;
    ``warnings``: one ``{code: "optional_caps", node, name, role, capabilities}`` per node lacking
    optional ones; ``not_checked``: ``{node, name, role, capability}`` for each simple output."""
    missing: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    unchecked: list[dict[str, Any]] = []
    for n in nodes:
        who = {"node": n["node"], "name": n["name"], "role": n["role"]}
        for fn in simple_outputs(n.get("modules")):
            unchecked.append({**who, "capability": fn,
                              "text": f"{fn} on {n['name']}: not checked (simple output)"})
        types = types_of(n.get("capabilities"))
        spec = role_spec(n["role"])
        if not types or not isinstance(spec, dict):
            continue  # it reports no capability (older firmware, a phone): not checked
        for name in _names(spec.get("requires")):
            if has(types, name) is False:
                missing.append({**who, "capability": name})
        lacking = [name for name in _names(spec.get("optional")) if has(types, name) is False]
        if lacking:
            warnings.append({"code": "optional_caps", **who, "capabilities": lacking,
                             "text": f"{n['name']} ({n['role']}) has no {', '.join(lacking)}"})
    return {"missing_caps": missing, "warnings": warnings, "not_checked": unchecked}


def _names(value: Any) -> list[str]:
    return [v for v in value if isinstance(v, str)] if isinstance(value, list) else []


def output_params(spec: Any, src: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """CMD 12's params from a request or a field script's table: ``(params, None)``, or ``(None,
    why not)``. ``src`` is the controller's (``gm`` or ``field``), whatever the caller gave. A GM's
    on or pulse without ms lasts ``GM_DEFAULT_MS``."""
    if not isinstance(spec, dict):
        return None, "the output request is a map: capability, act, ms, on_ms, off_ms"
    params: dict[str, Any] = {k: spec[k] for k in ("capability", "act", "ms", "on_ms", "off_ms") if k in spec}
    if src == "gm" and params.get("act") in ("on", "pulse", "pattern") and "ms" not in params:
        params["ms"] = GM_DEFAULT_MS
    if params.get("act") == "off":
        params = {k: v for k, v in params.items() if k in ("capability", "act")}
    elif params.get("act") != "pattern":
        params.pop("on_ms", None)
        params.pop("off_ms", None)
    params["src"] = src
    problem = output_params_problem(params)
    return (None, problem) if problem else (params, None)


class RateLimit:
    """At most one CMD 12 that starts an output to a node every ``OUTPUT_GAP_MS`` (EXP-30); off goes always."""

    def __init__(self) -> None:
        self._last: dict[int, int] = {}

    def wait_ms(self, node_id: int, act: str, now_ms: int) -> int:
        """0 when a CMD 12 with this act may go to the node now, else how long until it may."""
        if act == "off" or node_id not in self._last:
            return 0
        return max(0, self._last[node_id] + OUTPUT_GAP_MS - now_ms)

    def sent(self, node_id: int, act: str, now_ms: int) -> None:
        if act != "off":
            self._last[node_id] = now_ms

    def clear(self) -> None:
        self._last.clear()
