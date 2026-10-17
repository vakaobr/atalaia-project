# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Events on the wire: the CBOR payload of an EVENT message, and schema checks.

An event here is a dict with the envelope fields of protocol/schema/events.yaml:

    {"node": 3, "seq": 17, "t": 734210, "type": "zone.captured",
     "team": 2, "squad": 0, "prio": "normal", "data": {"team": "blue"}}

node, team and squad are short numeric ids, as on the field. team, squad,
prio and data are optional when encoding; decode_event always fills them in.
This mirrors core/src/codec.c, and both are tested against
protocol/vectors/events.yaml.
"""

from __future__ import annotations

import re
from typing import Any

from . import cbor
from .protocol import (CUSTOM_EVENT_PATTERN, DATA_FIELDS, ENVELOPE_KEYS, EVENT_TYPE_MAX, EVENTS,
                       PRIORITIES)

_EVENT_BY_ID = {e.id: name for name, e in EVENTS.items()}
_FIELD_BY_KEY = {f.key: name for name, f in DATA_FIELDS.items()}
_PRIO_BY_VALUE = {v: k for k, v in PRIORITIES.items()}
_KEY_NAMES = {v: k for k, v in ENVELOPE_KEYS.items()}
_CUSTOM = re.compile(CUSTOM_EVENT_PATTERN)
_INT64 = (-(1 << 63), (1 << 63) - 1)

TEAM_MAX = 250
# Keys in the data maps open at once, as ATALAIA_CODEC_MAX_KEYS in the core.
MAX_KEYS = 128


class CodecError(ValueError):
    pass


def default_prio(type_: str) -> str:
    """The schema's priority for a standard event; normal for custom ones."""
    ev = EVENTS.get(type_)
    return ev.prio if ev else "normal"


def _check_type_name(name: Any) -> str:
    if not isinstance(name, str):
        raise CodecError("event type must be text")
    raw = name.encode("utf-8")
    if not 0 < len(raw) < EVENT_TYPE_MAX or not all(0x21 <= b <= 0x7E for b in raw):
        raise CodecError(f"event type must be 1 to {EVENT_TYPE_MAX - 1} printable ASCII characters")
    return name


def _check_uint(name: str, value: Any, hi: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= hi:
        raise CodecError(f"{name} must be an integer from 0 to {hi}")
    return value


def _check_value(value: Any, depth: int = 1, open_keys: int = 0) -> None:
    """Data values are JSON values, with the core codec's limits.

    depth counts the containers around value (the envelope is the first),
    and open_keys the keys of the maps around it.
    """
    if isinstance(value, (list, dict)) and depth >= cbor.MAX_DEPTH:
        raise CodecError(f"data nested more than {cbor.MAX_DEPTH - 1} deep")
    if isinstance(value, bool) or value is None or isinstance(value, (str, float)):
        return
    if isinstance(value, int):
        if not _INT64[0] <= value <= _INT64[1]:
            raise CodecError("integers in data must fit in 64 bits")
        return
    if isinstance(value, list):
        for v in value:
            _check_value(v, depth + 1, open_keys)
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if not isinstance(k, str):
                raise CodecError("data keys must be text")
            open_keys += 1
            if open_keys > MAX_KEYS:
                raise CodecError("too many keys in nested data")
            _check_value(v, depth + 1, open_keys)
        return
    raise CodecError(f"data cannot hold {type(value).__name__}")


# ---- encoding --------------------------------------------------------------


def encode_event(ev: dict[str, Any]) -> bytes:
    unknown = set(ev) - set(ENVELOPE_KEYS)
    if unknown:
        raise CodecError(f"unknown event fields: {', '.join(sorted(unknown))}")
    type_ = _check_type_name(ev.get("type"))
    prio = ev.get("prio", default_prio(type_))
    if prio not in PRIORITIES:
        raise CodecError(f"unknown priority {prio!r}")
    data = ev.get("data", {})
    if not isinstance(data, dict):
        raise CodecError("data must be a map")
    _check_value(data)

    standard = EVENTS.get(type_)
    m: dict[int, Any] = {
        ENVELOPE_KEYS["node"]: _check_uint("node", ev.get("node"), 0xFFFF),
        ENVELOPE_KEYS["seq"]: _check_uint("seq", ev.get("seq"), 0xFFFF),
        ENVELOPE_KEYS["t"]: _check_uint("t", ev.get("t"), 0xFFFFFFFF),
        ENVELOPE_KEYS["type"]: standard.id if standard else type_,
    }
    team = _check_uint("team", ev.get("team", 0), TEAM_MAX)
    squad = _check_uint("squad", ev.get("squad", 0), 0xFF)
    if team:
        m[ENVELOPE_KEYS["team"]] = team
    if squad:
        m[ENVELOPE_KEYS["squad"]] = squad
    if prio != default_prio(type_):
        m[ENVELOPE_KEYS["prio"]] = PRIORITIES[prio]
    if data:
        m[ENVELOPE_KEYS["data"]] = {
            (DATA_FIELDS[k].key if k in DATA_FIELDS else k): v for k, v in data.items()
        }
    try:
        return cbor.encode(m)
    except cbor.CBORError as exc:
        raise CodecError(str(exc)) from None


# ---- decoding --------------------------------------------------------------


def decode_event(payload: bytes) -> dict[str, Any]:
    try:
        m = cbor.decode(payload)
    except cbor.CBORError as exc:
        raise CodecError(str(exc)) from None
    if not isinstance(m, dict):
        raise CodecError("an event is a map")
    fields: dict[str, Any] = {}
    for k, v in m.items():
        if k not in _KEY_NAMES:
            raise CodecError(f"unknown envelope key {k!r}")
        fields[_KEY_NAMES[k]] = v
    for name in ("node", "seq", "t", "type"):
        if name not in fields:
            raise CodecError(f"the event has no {name}")

    raw_type = fields["type"]
    if isinstance(raw_type, int) and not isinstance(raw_type, bool):
        if raw_type not in _EVENT_BY_ID:
            raise CodecError(f"unknown event id {raw_type}")
        type_ = _EVENT_BY_ID[raw_type]
    else:
        type_ = _check_type_name(raw_type)

    prio_value = fields.get("prio", PRIORITIES[default_prio(type_)])
    if isinstance(prio_value, bool) or prio_value not in _PRIO_BY_VALUE:
        raise CodecError(f"unknown priority {prio_value!r}")

    raw_data = fields.get("data", {})
    if not isinstance(raw_data, dict):
        raise CodecError("data must be a map")
    data: dict[str, Any] = {}
    for k, v in raw_data.items():
        if isinstance(k, int):
            if k not in _FIELD_BY_KEY:
                raise CodecError(f"unknown data key {k}")
            k = _FIELD_BY_KEY[k]
        if k in data:
            raise CodecError(f"duplicate data field {k!r}")
        data[k] = v
    _check_value(data)  # nested maps need text keys, as in JSON

    return {
        "node": _check_uint("node", fields["node"], 0xFFFF),
        "seq": _check_uint("seq", fields["seq"], 0xFFFF),
        "t": _check_uint("t", fields["t"], 0xFFFFFFFF),
        "type": type_,
        "team": _check_uint("team", fields.get("team", 0), TEAM_MAX),
        "squad": _check_uint("squad", fields.get("squad", 0), 0xFF),
        "prio": _PRIO_BY_VALUE[prio_value],
        "data": data,
    }


# ---- schema checks ---------------------------------------------------------

_JSON_TYPES = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
}


def schema_problems(type_: str, data: dict[str, Any]) -> list[str]:
    """What is wrong with an event's type and data, by protocol/schema/events.yaml."""
    ev = EVENTS.get(type_)
    if ev is None:
        if _CUSTOM.match(type_):
            return []
        return [f"'{type_}' is not a standard event; custom events are named x.<club>.<name>"]
    problems = []
    for k, v in data.items():
        field = DATA_FIELDS.get(k)
        if field is None or not (field.common or k in ev.data):
            allowed = [n for n, f in DATA_FIELDS.items() if f.common] + list(ev.data)
            problems.append(f"'{type_}' has no data field '{k}' (allowed: {', '.join(allowed)})")
        elif not _JSON_TYPES[field.type](v):
            problems.append(f"'{type_}' data field '{k}' must be a {field.type}, got {v!r}")
    return problems
