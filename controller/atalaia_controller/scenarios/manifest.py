# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reading a scenario manifest (ADR-P4-6 as amended): the one part of the scenario compiler that
stays in Python on the Pi (decision PE24-109; the rules, the Lua writer and mode.yaml are the
core's, core/scenario/).

A manifest is YAML (or JSON, which is YAML too), read as the Pi always read it: PyYAML's safe
loader (YAML 1.1: yes is true, 0815 a text, 1:30 a number), which never runs code, refusing a key
given twice in one map (PyYAML would keep the last one silently), and joining a surrogate pair's
two escapes into the character they mean (decision PE24-107). The phone's reader
(app/lib/controller/scenarios/scenario_manifest.dart) reads YAML as this one does, and both are
checked against protocol/vectors/scenario_compile.json's "loads". What each key means is in
controller/README.md, "Scenarios".
"""

from __future__ import annotations

import re
from typing import Any

import yaml

MANIFEST_MAX_BYTES = 256 * 1024


class ManifestError(Exception):
    """The text is not a manifest at all (not YAML, not a map, too large)."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML's safe loader, refusing a key given twice in one map."""


def _construct_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in seen
        except TypeError:  # an unhashable key: the safe constructor says so below
            duplicate = False
        if duplicate:
            raise yaml.constructor.ConstructorError(None, None, f"the key {key!r} is given twice",
                                                    key_node.start_mark)
        try:
            seen.add(key)
        except TypeError:
            pass
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_text(text: str) -> dict[str, Any]:
    """The manifest in a YAML or JSON text. ManifestError when it is not one."""
    if not isinstance(text, str):
        raise ManifestError("a scenario manifest is text")
    # "surrogatepass": a lone surrogate in the text itself is the YAML reader's to refuse, not a crash here.
    if len(text.encode("utf-8", "surrogatepass")) > MANIFEST_MAX_BYTES:
        raise ManifestError(f"the manifest is larger than {MANIFEST_MAX_BYTES} bytes")
    try:
        data = yaml.load(text, Loader=_UniqueKeyLoader)  # noqa: S506 (a SafeLoader subclass)
    except yaml.YAMLError as exc:
        raise ManifestError(f"not valid YAML: {exc}") from None
    except ValueError as exc:
        # A date or timestamp YAML recognises but the calendar has not (2026-13-45): PyYAML raises a
        # plain ValueError, which was a 500 from POST /api/v1/scenarios/check (decision PE24-108).
        raise ManifestError(f"not valid YAML: a date that does not exist ({exc})") from None
    if not isinstance(data, dict):
        raise ManifestError("a scenario manifest is a map (id, version, name, nodes, objectives, ...)")
    _join_surrogates(data, set())
    return data


_PAIR = re.compile("[\ud800-\udbff][\udc00-\udfff]")
_SURROGATE = re.compile("[\ud800-\udfff]")


def _joined(text: str) -> str:
    """A text with each surrogate pair as the one character it encodes; ManifestError for a lone one.

    PyYAML reads an escape per code unit, so "\\ud83d\\ude00" (as JSON writes an emoji with
    ensure_ascii) comes back as two surrogates, which UTF-8 cannot hold (decision PE24-107)."""
    if not _SURROGATE.search(text):
        return text
    text = _PAIR.sub(lambda p: chr(0x10000 + ((ord(p[0][0]) - 0xD800) << 10) + ord(p[0][1]) - 0xDC00), text)
    lone = _SURROGATE.search(text)
    if lone:
        raise ManifestError(f"not valid YAML: \\u{ord(lone[0]):04x} is half of a surrogate pair; a character "
                            "past U+FFFF is written as both halves (\\ud83d\\ude00), as \\U0001F600, or as it is")
    return text


def _join_surrogates(value: Any, seen: set[int]) -> None:
    """Joins the surrogate pairs of every text in the manifest (keys too), in place (an alias is
    one object, and may contain itself)."""
    if not isinstance(value, (dict, list)) or id(value) in seen:
        return
    seen.add(id(value))
    if isinstance(value, list):
        for i, item in enumerate(value):
            if isinstance(item, str):
                value[i] = _joined(item)
            else:
                _join_surrogates(item, seen)
        return
    items = list(value.items())
    if not any(isinstance(k, str) and _SURROGATE.search(k) for k, _ in items):
        for k, v in items:
            if isinstance(v, str):
                value[k] = _joined(v)
            else:
                _join_surrogates(v, seen)
        return
    value.clear()
    for k, v in items:
        key = _joined(k) if isinstance(k, str) else k
        if key in value:
            raise ManifestError(f"not valid YAML: the key {key!r} is given twice")
        if isinstance(v, str):
            v = _joined(v)
        else:
            _join_surrogates(v, seen)
        value[key] = v
