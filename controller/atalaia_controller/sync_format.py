# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The controller sync's request bodies (protocol/sync.md): one checker for both sides.

The field controller's sync client (``sync_client.py``) checks every event
before it sends it, and the site server checks every body it receives, with
the same functions, against the same shared vectors
(``protocol/vectors/sync.json``). Plain Python with no third-party imports,
so it runs on the controller's Raspberry Pi OS packages, in the site
server's image and in tools/check.sh (decisions P4R16, P4R17).

Each ``check_*`` function takes the parsed JSON body and returns it
normalised (unknown keys in a node's ``info`` dropped, defaults filled in);
anything else raises ``SyncFormatError`` with a short code and the path of
the first value that is wrong (``events[3].data``), which the site server
returns in its 400 answer.

What never travels (ADR-P4-3's amendment, P4R25): positions (an event whose
data carries a coordinate is refused), tokens and keys (there is no field
for them), check-in names (likewise). Event types are checked by their
form, not against today's list, so a newer controller's events still reach
an older site server.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from typing import Any

SYNC_VERSION = 1
MAX_EVENTS = 500            # events per batch
MAX_SOURCES = 1024          # score counter sources per snapshot
MAX_NODES = 512             # nodes per snapshot
MAX_EVENT_DATA = 1024       # bytes of an event's data, as compact JSON
MAX_PARAMS = 8192           # bytes of a game's params, as compact JSON
MAX_BODY = 1024 * 1024      # bytes of a request body
TEAM_MAX = 23               # bytes of a team name (the core's ATALAIA_TEAM_NAME_MAX - 1)
TEAMS_MAX = 8
STATES = ("ready", "running", "paused", "ended")
PRIORITIES = ("telemetry", "normal", "critical")
U16 = 0xFFFF
U32 = 0xFFFFFFFF
COUNTER_MAX = 2**31 - 1
TIME_MAX = 2**34            # seconds since 1970: far beyond any real clock

# A standard event name (zone.captured) or a custom one (x.club.name); under 48 bytes (EVENT_TYPE_MAX).
EVENT_TYPE = re.compile(r"[a-z][a-z0-9_]*(\.[a-z0-9][a-z0-9_-]*)+")
EVENT_TYPE_MAX = 47
# A score counter's source: a node's counters (node-3) or one run of a controller's field
# script, qualified by that controller's node id in the game (field-2@0), so two controllers'
# runs never share a key (decision S13-3).
SOURCE = re.compile(r"node-(\d{1,5})|field-(\d{1,6})@(\d{1,5})")
MODE_ID = re.compile(r"[a-z0-9][a-z0-9._+-]{0,127}")
VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,31}")
CREST_ID = re.compile(r"[0-9a-f]{64}")
DATA_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
# Keys that would carry a position (P4R25): refused anywhere in an event's data.
POSITION_KEYS = frozenset({"lat", "lon", "lng", "latitude", "longitude", "alt", "altitude", "position",
                           "positions", "gps", "coords", "coordinates", "x", "y"})
# What a node's info may carry to the site server; anything else is dropped.
NODE_INFO = {
    "owner": "team?", "phase": "int?", "battery_pct": "int?", "rssi": "int?", "snr": "num?", "epoch": "int?",
    "platform": "text?", "fw_version": "text?", "core_version": "text?", "tier": "text?",
    "capabilities": "texts?", "game_time_ms": "int?",
}


class SyncFormatError(ValueError):
    """A body that does not follow protocol/sync.md: ``code`` and the ``path`` of the value."""

    def __init__(self, code: str, path: str = "") -> None:
        super().__init__(f"{code} at {path or 'the body'}")
        self.code = code
        self.path = path


def _fail(code: str, path: str) -> None:
    raise SyncFormatError(code, path)


def _obj(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("not_an_object", path)
    return value


def _keys(value: dict[str, Any], path: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> None:
    for key in required:
        if key not in value:
            _fail("missing", f"{path}.{key}" if path else key)
    for key in value:
        if key not in required and key not in optional:
            _fail("unknown_field", f"{path}.{key}" if path else str(key))


def _int(value: Any, path: str, lo: int, hi: int, null: bool = False) -> Any:
    if value is None and null:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        _fail("not_an_integer", path)
    if not lo <= value <= hi:
        _fail("out_of_range", path)
    return value


def _num(value: Any, path: str, lo: float, hi: float, null: bool = False) -> Any:
    if value is None and null:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("not_a_number", path)
    if not lo <= value <= hi:
        _fail("out_of_range", path)
    return value


def _text(value: Any, path: str, max_len: int, null: bool = False, pattern: Any = None) -> Any:
    if value is None and null:
        return None
    if not isinstance(value, str) or not value:
        _fail("not_a_text", path)
    if len(value) > max_len or any(ord(c) < 0x20 or 0x7F <= ord(c) <= 0x9F for c in value):
        _fail("bad_text", path)
    if pattern is not None and not pattern.fullmatch(value):
        _fail("bad_text", path)
    return value


def _team(value: Any, path: str, null: bool = False) -> Any:
    if value is None and null:
        return None
    _text(value, path, TEAM_MAX)
    if len(value.encode("utf-8")) > TEAM_MAX:
        _fail("bad_text", path)
    return value


def _json_size(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _envelope(body: Any, extra: tuple[str, ...]) -> dict[str, Any]:
    body = _obj(body, "")
    _keys(body, "", ("sync_version", "controller", "game", *extra))
    if body["sync_version"] != SYNC_VERSION or isinstance(body["sync_version"], bool):
        _fail("unsupported_version", "sync_version")
    ctrl = _obj(body["controller"], "controller")
    _keys(ctrl, "controller", ("id", "version"))
    if not isinstance(ctrl["id"], str):
        _fail("not_a_uuid", "controller.id")
    try:
        parsed = uuid.UUID(ctrl["id"])
    except ValueError:
        parsed = None
    if parsed is None or str(parsed) != ctrl["id"]:
        _fail("not_a_uuid", "controller.id")  # the canonical lower-case form only
    _text(ctrl["version"], "controller.version", 32, pattern=VERSION)
    game = _obj(body["game"], "game")
    _keys(game, "game", ("game_id", "game_seed"))
    _int(game["game_id"], "game.game_id", 0, U16)
    _int(game["game_seed"], "game.game_seed", 0, U32)
    return body


def game_key(body: dict[str, Any]) -> tuple[int, int]:
    """The (game_id, game_seed) a checked body is about (P4R11)."""
    return body["game"]["game_id"], body["game"]["game_seed"]


# --- POST /api/v1/sync/games -----------------------------------------------------------

def check_game(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("meta",))
    meta = _obj(body["meta"], "meta")
    _keys(meta, "meta", ("name", "mode_id", "teams", "state", "created_at"),
          ("team_info", "params", "squads", "duration_ms", "node_id", "joined", "started_at", "ended_at"))
    _text(meta["name"], "meta.name", 64)
    _text(meta["mode_id"], "meta.mode_id", 128, pattern=MODE_ID)
    teams = meta["teams"]
    if not isinstance(teams, list) or not 1 <= len(teams) <= TEAMS_MAX:
        _fail("bad_teams", "meta.teams")
    for i, team in enumerate(teams):
        _team(team, f"meta.teams[{i}]")
    if len(set(teams)) != len(teams):
        _fail("bad_teams", "meta.teams")
    info = _obj(meta.setdefault("team_info", {}), "meta.team_info")
    for team, entry in info.items():
        path = f"meta.team_info.{team}"
        if team not in teams:
            _fail("unknown_team", path)
        entry = _obj(entry, path)
        _keys(entry, path, (), ("display_name", "crest_id"))
        _text(entry.get("display_name"), f"{path}.display_name", 32, null=True)
        _text(entry.get("crest_id"), f"{path}.crest_id", 64, null=True, pattern=CREST_ID)
    params = _obj(meta.setdefault("params", {}), "meta.params")
    if _json_size(params) > MAX_PARAMS:
        _fail("too_large", "meta.params")
    _int(meta.setdefault("squads", 0), "meta.squads", 0, 16)
    _int(meta.setdefault("duration_ms", 0), "meta.duration_ms", 0, U32)
    if meta["state"] not in STATES:
        _fail("bad_state", "meta.state")
    _int(meta.setdefault("node_id", None), "meta.node_id", 0, U16 - 1, null=True)
    if not isinstance(meta.setdefault("joined", False), bool):
        _fail("not_a_boolean", "meta.joined")
    _num(meta["created_at"], "meta.created_at", 0, TIME_MAX)
    _num(meta.setdefault("started_at", None), "meta.started_at", 0, TIME_MAX, null=True)
    _num(meta.setdefault("ended_at", None), "meta.ended_at", 0, TIME_MAX, null=True)
    return body


# --- POST /api/v1/sync/events ------------------------------------------------------------

def _data(value: Any, path: str, depth: int = 0) -> None:
    if isinstance(value, dict):
        if depth >= 2:
            _fail("too_deep", path)
        for key, item in value.items():
            if not isinstance(key, str) or not DATA_KEY.fullmatch(key):
                _fail("bad_key", f"{path}.{key}")
            if key in POSITION_KEYS:
                _fail("position_not_allowed", f"{path}.{key}")
            _data(item, f"{path}.{key}", depth + 1)
    elif isinstance(value, list):
        if depth >= 2 or len(value) > 32:
            _fail("too_deep", path)
        for i, item in enumerate(value):
            _data(item, f"{path}[{i}]", depth + 1)
    elif isinstance(value, float):
        if not math.isfinite(value):
            _fail("not_a_number", path)
    elif value is not None and not isinstance(value, (str, int)):
        _fail("bad_value", path)  # bool is an int


def check_event(ev: Any, path: str = "event") -> dict[str, Any]:
    """One event as the controller's log holds it (store.events), with its ``id`` in that log."""
    ev = _obj(ev, path)
    _keys(ev, path, ("id", "node", "seq", "t", "type", "prio"), ("team", "squad", "data", "epoch", "pkt_seq"))
    _int(ev["id"], f"{path}.id", 1, 2**63 - 1)
    _int(ev["node"], f"{path}.node", 0, U16)
    _int(ev["seq"], f"{path}.seq", 0, U16)
    _int(ev["t"], f"{path}.t", 0, U32)
    _text(ev["type"], f"{path}.type", EVENT_TYPE_MAX, pattern=EVENT_TYPE)
    if ev["prio"] not in PRIORITIES:
        _fail("bad_priority", f"{path}.prio")
    _team(ev.setdefault("team", None), f"{path}.team", null=True)
    _int(ev.setdefault("squad", None), f"{path}.squad", 0, 255, null=True)
    data = _obj(ev.setdefault("data", {}), f"{path}.data")
    _data(data, f"{path}.data")
    if _json_size(data) > MAX_EVENT_DATA:
        _fail("too_large", f"{path}.data")
    _int(ev.setdefault("epoch", None), f"{path}.epoch", 0, U16, null=True)
    _int(ev.setdefault("pkt_seq", None), f"{path}.pkt_seq", 0, U16, null=True)
    if ev["type"] == "score.delta":
        # A GM's adjustment (P4R10): the site server adds these amounts to the counters' sum.
        _int(data.get("amount"), f"{path}.data.amount", -1_000_000, 1_000_000)
        team = data.get("team", ev["team"])
        _team(team, f"{path}.data.team")
        if ev["team"] is not None and ev["team"] != team:
            _fail("team_mismatch", f"{path}.team")
    return ev


def check_events(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("after_id", "events"))
    after = _int(body["after_id"], "after_id", 0, 2**63 - 1)
    events = body["events"]
    if not isinstance(events, list) or not 1 <= len(events) <= MAX_EVENTS:
        _fail("bad_batch_size", "events")
    last = after
    for i, ev in enumerate(events):
        check_event(ev, f"events[{i}]")
        if ev["id"] <= last:
            _fail("ids_not_increasing", f"events[{i}].id")
        last = ev["id"]
    return body


# --- POST /api/v1/sync/scores ------------------------------------------------------------

def check_scores(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("counters",))
    counters = _obj(body["counters"], "counters")
    if len(counters) > MAX_SOURCES:
        _fail("too_large", "counters")
    for source, teams in counters.items():
        path = f"counters.{source}"
        if not isinstance(source, str) or not SOURCE.fullmatch(source):
            _fail("bad_source", path)
        teams = _obj(teams, path)
        if len(teams) > TEAMS_MAX:
            _fail("bad_teams", path)
        for team, value in teams.items():
            _team(team, f"{path}.{team}")
            _int(value, f"{path}.{team}", 0, COUNTER_MAX)
    return body


# --- POST /api/v1/sync/nodes -------------------------------------------------------------

def _info_value(kind: str, value: Any, path: str) -> Any:
    if value is None:
        return None
    if kind == "team?":
        return _team(value, path)
    if kind == "int?":
        return _int(value, path, -(2**31), 2**32)
    if kind == "num?":
        return _num(value, path, -1e9, 1e9)
    if kind == "text?":
        if isinstance(value, int) and not isinstance(value, bool):
            value = str(value)
        return _text(value, path, 32)
    if not isinstance(value, list) or len(value) > 32:  # texts?
        _fail("bad_value", path)
    return [_text(v, f"{path}[{i}]", 32) for i, v in enumerate(value)]


def check_nodes(body: Any) -> dict[str, Any]:
    body = _envelope(body, ("nodes",))
    nodes = body["nodes"]
    if not isinstance(nodes, list) or len(nodes) > MAX_NODES:
        _fail("bad_batch_size", "nodes")
    seen = set()
    for i, node in enumerate(nodes):
        path = f"nodes[{i}]"
        node = _obj(node, path)
        _keys(node, path, ("node_id", "name", "role", "last_seen"), ("info",))
        _int(node["node_id"], f"{path}.node_id", 0, U16)
        if node["node_id"] in seen:
            _fail("duplicate_node", f"{path}.node_id")
        seen.add(node["node_id"])
        _text(node["name"], f"{path}.name", 32)
        _text(node["role"], f"{path}.role", 32)
        _num(node["last_seen"], f"{path}.last_seen", 0, TIME_MAX)
        info = _obj(node.get("info", {}), f"{path}.info")
        node["info"] = {k: _info_value(NODE_INFO[k], v, f"{path}.info.{k}")
                        for k, v in info.items() if k in NODE_INFO}
    return body


CHECKS = {"games": check_game, "events": check_events, "scores": check_scores, "nodes": check_nodes}


def parse(kind: str, raw: bytes) -> dict[str, Any]:
    """Parses and checks a request body of one kind (games, events, scores, nodes)."""
    if len(raw) > MAX_BODY:
        _fail("too_large", "")
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _fail("not_json", "")
    return CHECKS[kind](body)


# --- the merge (P4R10) ------------------------------------------------------------------

def merge_counters(stored: dict[str, dict[str, int]], incoming: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Each (source, team) counter keeps the largest value it was ever reported with."""
    out = {s: dict(t) for s, t in stored.items()}
    for source, teams in incoming.items():
        row = out.setdefault(source, {})
        for team, value in teams.items():
            row[team] = max(row.get(team, 0), value)
    return out


def totals(teams: list[str], counters: dict[str, dict[str, int]], deltas: list[tuple[str, int]]) -> dict[str, int]:
    """A game's totals as the controller's FieldController.total_scores makes them: the sum of the
    counters per team plus every GM adjustment (score.delta), which may be negative."""
    out = {t: 0 for t in teams}
    for row in counters.values():
        for team, value in row.items():
            out[team] = out.get(team, 0) + value
    for team, amount in deltas:
        out[team] = out.get(team, 0) + amount
    return out
